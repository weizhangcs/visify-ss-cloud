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
from ai_services.utils.prompt_manager import PromptManager

from ai_services.schemas.refinery.subtitle_merger import (
    SubtitleMergerPayload, SubtitleItem, MergedSubtitleItem, SubtitleMergerResponse
)
from .schemas import MergePlanResponse, MergeInstruction

logger = logging.getLogger(__name__)

class SubtitleMergerService(AIServiceMixin):
    """
    使用 LLM 将碎片化的字幕合并为语义完整的句子。
    
    架构设计:
    - 配置驱动 (Configuration-Driven): 使用外部配置管理模型参数。
    - 指令生成 (Instruction-Based): LLM 返回合并计划（索引），本地代码负责重构文本。
    - 双模式运行 (Dual-Mode): 支持 PROD（严格配置）和 DEBUG（载荷覆盖）模式。
    """
    SERVICE_NAME = "subtitle_merger"
    
    # 默认配置 (当配置文件缺失或不完整时的兜底值)
    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_BATCH_SIZE = 200
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3

    # 语言代码到自然语言名称的映射，用于通用提示词
    LANG_CODE_TO_NAME = {
        "zh": "Chinese",
        "en": "English",
        "jp": "Japanese",
        "ja": "Japanese",
        "ko": "Korean",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
    }

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompt_manager = PromptManager(self.prompts_dir)

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Subtitle Merger...")

        # --- 1. 输入校验与加载 ---
        try:
            task_input = SubtitleMergerPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        target_subtitles = self._load_subtitles(task_input)
        if not target_subtitles:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No subtitles provided.")

        # --- 2. 配置初始化 ---
        # 优先级: Payload (仅DEBUG) > 配置文件 > 默认值
        if config is None: config = {}
        
        # 从配置或默认值加载
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        batch_size = config.get("batch_size", self.DEFAULT_BATCH_SIZE)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)

        # 如果适用，应用 DEBUG 模式覆盖
        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.batch_size: batch_size = sp.batch_size
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            
            self.logger.info(f"🔧 DEBUG Mode Active. Params: Model={model_name}, Batch={batch_size}, Temp={temperature}, Retries={max_retries}")
        else:
            self.logger.info(f"🏭 PROD Mode Active. Params: Model={model_name}, Batch={batch_size}, Temp={temperature}, Retries={max_retries}")

        # --- 3. 分批处理 ---
        all_merged_subtitles = []
        usage_accumulator = {}
        
        # 将字幕切分为块。
        # 注意：此处使用简单的切分。当前版本不支持跨批次合并。
        chunks = [target_subtitles[i:i + batch_size] for i in range(0, len(target_subtitles), batch_size)]
        
        for i, chunk in enumerate(chunks):
            self.logger.info(f"Processing batch {i+1}/{len(chunks)} ({len(chunk)} items)...")
            
            # A. 从 LLM 获取合并指令
            merge_plan, batch_usage = self._get_merge_plan_from_llm(
                chunk, task_input.lang, model_name, temperature, max_retries
            )
            
            # B. 在本地执行合并指令
            processed_indices = set()
            
            # 应用 LLM 定义的合并
            for instruction in merge_plan:
                if not instruction.original_indices:
                    continue
                
                # 获取原始字幕对象
                items_to_merge = [sub for sub in chunk if sub.index in instruction.original_indices]
                if not items_to_merge:
                    continue

                # 按索引排序以确保正确计算时间范围
                items_to_merge.sort(key=lambda x: x.index)

                merged_item = MergedSubtitleItem(
                    index=0, # 临时索引，稍后将全局重新分配
                    start_time=items_to_merge[0].start_time,
                    end_time=items_to_merge[-1].end_time,
                    content=instruction.new_content,
                    original_indices=instruction.original_indices
                )
                all_merged_subtitles.append(merged_item)
                processed_indices.update(instruction.original_indices)

            # 保留未合并的独立行
            for sub in chunk:
                if sub.index not in processed_indices:
                    all_merged_subtitles.append(MergedSubtitleItem(
                        index=0, # 临时索引
                        start_time=sub.start_time,
                        end_time=sub.end_time,
                        content=sub.content,
                        original_indices=[sub.index]
                    ))

            # 累积用量统计
            batch_usage_dict = batch_usage.model_dump()
            for key in ["prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "request_count", "duration_seconds"]:
                usage_accumulator[key] = usage_accumulator.get(key, 0) + batch_usage_dict.get(key, 0)
            
            # 使用最新批次的时间戳更新
            if batch_usage_dict.get("timestamp"):
                usage_accumulator["timestamp"] = batch_usage_dict["timestamp"]
                    
        # --- 4. 后处理 ---
        # 全局排序和重新索引
        all_merged_subtitles.sort(key=lambda x: x.start_time)
        for i, item in enumerate(all_merged_subtitles):
            item.index = i + 1

        # --- 5. 成本计算与响应 ---
        cost_report = self.cost_calculator.calculate(UsageStats(model_used=model_name, **usage_accumulator))

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
        """从 Payload 列表或外部文件加载字幕。"""
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

    def _preprocess_subtitles(self, subtitles: List[SubtitleItem]) -> List[Dict[str, Any]]:
        """
        将字幕对象预处理为模板所需的结构化格式。
        计算衍生字段，如持续时间和间隔。
        """
        processed = []
        for i, current_sub in enumerate(subtitles):
            duration = round(current_sub.end_time - current_sub.start_time, 2)
            gap = 0.0
            if i + 1 < len(subtitles):
                next_sub = subtitles[i + 1]
                gap = round(next_sub.start_time - current_sub.end_time, 2)
            
            processed.append({
                "index": current_sub.index,
                "duration": duration,
                "gap": gap,
                "content": current_sub.content
            })
        
        return processed

    def _get_merge_plan_from_llm(self, subtitles: List[SubtitleItem], lang: str, model_name: str, 
                                 temperature: float, max_retries: int) -> tuple[List[MergeInstruction], UsageStats]:
        """
        与 LLM 交互以生成合并计划。
        使用结构化输出 (Pydantic schema) 确保有效的 JSON 响应。
        """
        # 为模板准备数据
        processed_subs = self._preprocess_subtitles(subtitles)
        
        # 获取语言全名 (默认为 English，防止 LLM 困惑)
        language_name = self.LANG_CODE_TO_NAME.get(lang.lower(), "English")

        # 渲染提示词
        try:
            template_name = f"subtitle_merge_{lang}.j2"
            
            # [架构优化] 模板加载策略:
            # 1. 尝试加载特定语言模板 (e.g., subtitle_merge_zh.j2)
            # 2. 如果不存在，回退到通用模板 (subtitle_merge_generic.j2)
            if not (self.prompts_dir / template_name).exists():
                 template_name = "subtitle_merge_generic.j2"

            prompt = self.prompt_manager.render(template_name, {"subtitles": processed_subs, "language_name": language_name})
        except Exception as e:
            self.logger.error(f"Failed to render prompt: {e}")
            raise BizException(ErrorCode.FILE_IO_ERROR, f"Prompt rendering failed: {e}")

        # 执行 LLM 推理（带重试）
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