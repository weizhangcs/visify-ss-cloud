import json
import logging
from pathlib import Path
import time
from typing import Dict, Any, List

from django.conf import settings
from pydantic import BaseModel

from ai_services.ai_platform.llm.mixins import AIServiceMixin
from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from ai_services.ai_platform.llm.schemas import UsageStats
from core.exceptions import BizException
from core.error_codes import ErrorCode

from .schemas import (
    SubtitleMergerPayload, SubtitleItem, MergedSubtitleItem, SubtitleMergerResponse,
    MergePlanResponse, MergeInstruction
)

logger = logging.getLogger(__name__)

class SubtitleMergerService(AIServiceMixin):
    SERVICE_NAME = "subtitle_merger"
    
    # Hardcoded Defaults (兜底)
    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_BATCH_SIZE = 200
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Subtitle Merger...")

        # 1. 解析输入
        try:
            task_input = SubtitleMergerPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        target_subtitles = self._load_subtitles(task_input)
        if not target_subtitles:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No subtitles provided.")

        # [架构升级] 参数解析与合并 (Priority: Payload(Debug) > Config File > Defaults)
        if config is None: config = {}
        
        # 1. 从配置或默认值获取
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        batch_size = config.get("batch_size", self.DEFAULT_BATCH_SIZE)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)

        # 2. 如果是 DEBUG 模式，尝试使用 Payload 中的 overrides
        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.batch_size: batch_size = sp.batch_size
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            
            self.logger.info(f"🔧 DEBUG Mode Active. Params: Model={model_name}, Batch={batch_size}, Temp={temperature}, Retries={max_retries}")
        else:
            self.logger.info(f"🏭 PROD Mode Active. Params: Model={model_name}, Batch={batch_size}, Temp={temperature}, Retries={max_retries}")

        # 2. 分批处理
        all_merged_subtitles = []
        usage_accumulator = {}
        
        # 简单的分批策略。
        # 注意：简单的分批可能会导致 Batch 边界处的合并丢失。
        # 对于 V1 版本，这是一个可接受的折衷。更高级的版本可以引入 Overlap 机制。
        chunks = [target_subtitles[i:i + batch_size] for i in range(0, len(target_subtitles), batch_size)]
        
        for i, chunk in enumerate(chunks):
            self.logger.info(f"Processing batch {i+1}/{len(chunks)} ({len(chunk)} items)...")
            
            # 1. 从 LLM 获取合并计划
            merge_plan, batch_usage = self._get_merge_plan_from_llm(
                chunk, task_input.lang, model_name, temperature, max_retries
            )
            
            # 2. 在本地执行合并计划
            processed_indices = set()
            
            # 处理需要合并的组
            for instruction in merge_plan:
                if not instruction.original_indices:
                    continue
                
                # 找到原始条目
                items_to_merge = [sub for sub in chunk if sub.index in instruction.original_indices]
                if not items_to_merge:
                    continue

                # 按原始索引排序，以正确计算时间
                items_to_merge.sort(key=lambda x: x.index)

                merged_item = MergedSubtitleItem(
                    index=0, # 临时索引
                    start_time=items_to_merge[0].start_time,
                    end_time=items_to_merge[-1].end_time,
                    content=instruction.new_content,
                    original_indices=instruction.original_indices
                )
                all_merged_subtitles.append(merged_item)
                processed_indices.update(instruction.original_indices)

            # 处理不需要合并的独立行
            for sub in chunk:
                if sub.index not in processed_indices:
                    all_merged_subtitles.append(MergedSubtitleItem(
                        index=0, # 临时索引
                        start_time=sub.start_time,
                        end_time=sub.end_time,
                        content=sub.content,
                        original_indices=[sub.index]
                    ))

            # 累加用量
            # batch_usage 是 UsageStats 对象，需转为字典
            batch_usage_dict = batch_usage.model_dump()
            for key in ["prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "request_count", "duration_seconds"]:
                usage_accumulator[key] = usage_accumulator.get(key, 0) + batch_usage_dict.get(key, 0)
            
            # 总是用最后一个批次的 timestamp 更新
            if batch_usage_dict.get("timestamp"):
                usage_accumulator["timestamp"] = batch_usage_dict["timestamp"]
                    
        # 3. 对最终结果进行全局排序和重新编号
        all_merged_subtitles.sort(key=lambda x: x.start_time)
        for i, item in enumerate(all_merged_subtitles):
            item.index = i + 1

        # 4. 计算成本
        cost_report = self.cost_calculator.calculate(UsageStats(model_used=model_name, **usage_accumulator))

        # 5. 构造响应
        response = SubtitleMergerResponse(
            merged_subtitles=all_merged_subtitles,
            stats={
                "input_count": len(target_subtitles),
                "output_count": len(all_merged_subtitles)
            },
            usage_report=cost_report.to_dict()
        )
        
        return response.model_dump()

    def _load_subtitles(self, task_input: SubtitleMergerPayload) -> List[SubtitleItem]:
        if task_input.subtitles:
            return task_input.subtitles
        
        if task_input.subtitle_file_path:
            self.logger.info(f"Loading subtitles from file: {task_input.subtitle_file_path}")
            try:
                content = self._read_file(task_input.subtitle_file_path)
                raw_list = json.loads(content)
                return [SubtitleItem(**item) for item in raw_list]
            except Exception as e:
                raise BizException(ErrorCode.FILE_IO_ERROR, f"Failed to load subtitles file: {e}")
        return []

    def _read_file(self, path_str: str) -> str:
        local_path = Path(path_str)
        if not local_path.is_absolute():
            local_path = settings.SHARED_ROOT / local_path
        return local_path.read_text(encoding='utf-8')

    def _convert_to_compact_format(self, subtitles: List[SubtitleItem]) -> str:
        """将字幕列表转换为对 LLM 友好的紧凑文本格式。"""
        lines = []
        for i, current_sub in enumerate(subtitles):
            duration = round(current_sub.end_time - current_sub.start_time, 2)
            gap = 0.0
            if i + 1 < len(subtitles):
                next_sub = subtitles[i + 1]
                gap = round(next_sub.start_time - current_sub.end_time, 2)
            
            lines.append(f"[ID:{current_sub.index}] D:{duration}s G:{gap}s | {current_sub.content}")
        
        return "\n".join(lines)

    def _get_merge_plan_from_llm(self, subtitles: List[SubtitleItem], lang: str, model_name: str, 
                                 temperature: float, max_retries: int) -> tuple[List[MergeInstruction], UsageStats]:
        # 加载 Prompt
        try:
            prompt_path = self.prompts_dir / f"subtitle_merge_{lang}.txt"
            if not prompt_path.exists():
                # Fallback to zh if en not exists (or create en later)
                prompt_path = self.prompts_dir / "subtitle_merge_zh.txt"
            
            template = prompt_path.read_text(encoding='utf-8')
        except Exception as e:
            self.logger.error(f"Failed to load prompt: {e}")
            raise BizException(ErrorCode.FILE_IO_ERROR, "Prompt file missing")

        # 构造紧凑的输入文本
        compact_text = self._convert_to_compact_format(subtitles)
        prompt = template.replace("{subtitles_json}", compact_text)

        # 调用 LLM
        for attempt in range(max_retries):
            try:
                response, usage = self.gemini_processor.generate_content(
                    model_name=model_name,
                    prompt=prompt,
                    response_schema=MergePlanResponse,
                    temperature=temperature
                )
                return response.merge_plan if response else [], usage
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ Batch inference failed after {max_retries} attempts: {e}")
                    raise e
                wait_time = 2 * (attempt + 1)
                self.logger.warning(f"⚠️ Batch inference failed (Attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)