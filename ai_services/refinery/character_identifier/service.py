import json
import math
import logging
from pathlib import Path
import time
from typing import Dict, Any, List

from django.conf import settings

from ai_services.ai_platform.llm.mixins import AIServiceMixin
from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from ai_services.ai_platform.llm.schemas import UsageStats
from core.exceptions import BizException
from core.error_codes import ErrorCode
from ai_services.utils.prompt_manager import PromptManager

from ai_services.schemas.refinery.character_identifier import (
    CharacterIdentifierPayload, SubtitleItem, IdentifiedSubtitleItem, CharacterIdentifierResponse
)
from .schemas import (
    BatchRoleInferenceResponse, SpeakerNormalizationResponse
)

logger = logging.getLogger(__name__)

class CharacterIdentifierService(AIServiceMixin):
    """
    角色识别服务 (Refinery)
    
    架构设计:
    - 配置驱动: 参数由 ai_inference_config.yaml 管理。
    - 双阶段推理: 
        1. 批量推理 (Batch Inference): 识别每行角色。
        2. 归一化 (Normalization): 统一角色名称变体。
    - 多模态支持: 利用 AudioAnalysis 中的性别特征辅助推理。
    """
    SERVICE_NAME = "character_identifier"
    
    # 默认配置
    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_BATCH_SIZE = 150
    DEFAULT_NORM_BATCH_SIZE = 250
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3

    LANG_CODE_TO_NAME = {
        "zh": "Chinese", "en": "English", "jp": "Japanese", "ja": "Japanese",
        "ko": "Korean", "es": "Spanish", "fr": "French", "de": "German",
    }

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompt_manager = PromptManager(self.prompts_dir)

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Character Identifier...")

        # --- 1. 输入校验与加载 ---
        try:
            task_input = CharacterIdentifierPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        subtitles = self._load_subtitles(task_input)
        if not subtitles:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No subtitles provided.")

        # --- 2. 配置初始化 ---
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        batch_size = config.get("batch_size", self.DEFAULT_BATCH_SIZE)
        norm_batch_size = config.get("normalization_batch_size", self.DEFAULT_NORM_BATCH_SIZE)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)

        # DEBUG 模式覆盖
        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.batch_size: batch_size = sp.batch_size
            if sp.normalization_batch_size: norm_batch_size = sp.normalization_batch_size
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            self.logger.info(f"🔧 DEBUG Mode. Params: Model={model_name}, Batch={batch_size}, NormBatch={norm_batch_size}")
        else:
            self.logger.info(f"🏭 PROD Mode. Params: Model={model_name}, Batch={batch_size}")

        # --- 3. Stage 1: 批量角色推断 ---
        inference_results: List[IdentifiedSubtitleItem] = []
        usage_accumulator = {}

        total_lines = len(subtitles)
        num_batches = math.ceil(total_lines / batch_size)

        # 准备通用上下文
        language_name = self.LANG_CODE_TO_NAME.get(task_input.lang.lower(), "English")
        chars_str = ", ".join(task_input.known_characters) if task_input.known_characters else "None"
        video_title = task_input.video_title or "Unknown"

        for batch_idx in range(num_batches):
            start_idx = batch_idx * batch_size
            end_idx = min((batch_idx + 1) * batch_size, total_lines)
            batch_items = subtitles[start_idx:end_idx]

            self.logger.info(f"Processing Batch {batch_idx + 1}/{num_batches}...")

            # 预处理数据供模板使用
            processed_batch = self._preprocess_subtitles(batch_items)

            # 渲染 Prompt
            # [优化] 动态加载语言模板，回退到通用模板
            template_name = f"role_inference_{task_input.lang}.j2"
            if not (self.prompts_dir / template_name).exists():
                template_name = "role_inference_generic.j2"

            prompt = self.prompt_manager.render(template_name, {
                "subtitles": processed_batch,
                "language_name": language_name,
                "character_list": chars_str,
                "video_title": video_title
            })

            # 调用 LLM
            try:
                response_obj, usage = self.gemini_processor.generate_content(
                    model_name=model_name,
                    prompt=prompt,
                    response_schema=BatchRoleInferenceResponse,
                    temperature=temperature
                )
                self._aggregate_usage(usage_accumulator, usage)

                # 映射结果
                speaker_map = {m.index: m.speaker for m in response_obj.mappings}

                for item in batch_items:
                    inference_results.append(IdentifiedSubtitleItem(
                        id=item.id, # [Change] Pass through UUID
                        index=item.index,
                        speaker=speaker_map.get(item.index, "Unknown"),
                        reasoning="AI Inferred"
                    ))
            except Exception as e:
                self.logger.error(f"Batch {batch_idx + 1} failed: {e}")
                # 错误处理：填充 Unknown
                for item in batch_items:
                    inference_results.append(IdentifiedSubtitleItem(
                        id=item.id,
                        index=item.index,
                        speaker="Unknown (Error)",
                        reasoning=f"Error: {str(e)[:50]}"
                    ))

        # --- 4. Stage 2: 角色名归一化 ---
        raw_speakers = list(set([res.speaker for res in inference_results if res.speaker not in ["Unknown", "Unknown (Error)"]]))

        if len(raw_speakers) >= 2:
            self.logger.info(f"Normalizing {len(raw_speakers)} unique speaker names (Batch Size: {norm_batch_size})...")
            
            # 全量预推理角色列表 (作为全局上下文)
            raw_speakers_str = ", ".join(raw_speakers)

            # [优化] 动态加载归一化模板
            norm_template = f"speaker_normalization_{task_input.lang}.j2"
            if not (self.prompts_dir / norm_template).exists():
                norm_template = "speaker_normalization_generic.j2"

            # 建立索引映射以快速查找 Stage 1 的结果
            inf_map = {item.index: item for item in inference_results}

            # 分批进行归一化
            norm_num_batches = math.ceil(total_lines / norm_batch_size)
            
            for i in range(norm_num_batches):
                start_idx = i * norm_batch_size
                end_idx = min((i + 1) * norm_batch_size, total_lines)
                batch_subtitles = subtitles[start_idx:end_idx]
                
                # 构建当前批次的剧本上下文
                script_lines = []
                for sub in batch_subtitles:
                    inf_item = inf_map.get(sub.index)
                    speaker = inf_item.speaker if inf_item else "Unknown"

                    gender_tag = ""
                    if sub.audio_analysis and sub.audio_analysis.gender != "Unknown":
                        gender_tag = f"[Gender: {sub.audio_analysis.gender}] "

                    script_lines.append(f"[{sub.index}] {gender_tag}[{speaker}] {sub.content}")
                
                batch_script_context = "\n".join(script_lines)

                norm_prompt = self.prompt_manager.render(norm_template, {
                    "script_content": batch_script_context,
                    "language_name": language_name,
                    "character_list": chars_str,  # VIP 列表
                    "raw_speakers": raw_speakers_str # [新增] 全量预推理角色列表，提供全局视野
                })

                try:
                    norm_response, norm_usage = self.gemini_processor.generate_content(
                        model_name=model_name,
                        prompt=norm_prompt,
                        response_schema=SpeakerNormalizationResponse,
                        temperature=temperature
                    )
                    self._aggregate_usage(usage_accumulator, norm_usage)

                    norm_map = {item.original_name: item.normalized_name for item in norm_response.normalization_items}

                    # 应用归一化 (仅针对当前批次的结果)
                    for sub in batch_subtitles:
                        inf_item = inf_map.get(sub.index)
                        if inf_item and inf_item.speaker in norm_map:
                            inf_item.speaker = norm_map[inf_item.speaker]
                            
                except Exception as e:
                    self.logger.error(f"Normalization batch {i+1} failed: {e}")

        # 收集最终的角色列表 (用于 Stats)
        # 过滤掉 Unknown 和 Error，并进行排序
        final_speakers = sorted(list(set(
            [res.speaker for res in inference_results if res.speaker not in ["Unknown", "Unknown (Error)"]]
        )))

        # --- 5. 响应构建 ---
        cost_report = self.cost_calculator.calculate(UsageStats(model_used=model_name, **usage_accumulator))
        
        response = CharacterIdentifierResponse(
            identified_subtitles=inference_results,
            stats={
                "total_lines": total_lines,
                "processed_lines": len(inference_results),
                "batches": num_batches,
                "identified_roles": final_speakers
            },
            usage_report=cost_report.to_dict()
        )
        
        return response.model_dump()

    def _load_subtitles(self, task_input: CharacterIdentifierPayload) -> List[SubtitleItem]:
        if task_input.subtitles:
            return task_input.subtitles
        
        if task_input.subtitle_file_path:
            local_path = Path(task_input.subtitle_file_path)
            if not local_path.is_absolute():
                local_path = settings.SHARED_ROOT / local_path
            content = local_path.read_text(encoding='utf-8')
            raw_list = json.loads(content)
            return [SubtitleItem(**item) for item in raw_list]
        return []

    def _preprocess_subtitles(self, subtitles: List[SubtitleItem]) -> List[Dict[str, Any]]:
        """预处理：提取性别特征供模板使用"""
        processed = []
        for sub in subtitles:
            gender = None
            if sub.audio_analysis and sub.audio_analysis.gender != "Unknown":
                gender = sub.audio_analysis.gender
            
            processed.append({
                "index": sub.index,
                "content": sub.content,
                "gender": gender
            })
        return processed

    def _aggregate_usage(self, accumulator: Dict, usage: UsageStats):
        u_dict = usage.model_dump()
        for key in ["prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "request_count", "duration_seconds"]:
            accumulator[key] = accumulator.get(key, 0) + u_dict.get(key, 0)

        # 使用最新批次的时间戳更新，防止 UsageStats 实例化时缺少 timestamp
        if u_dict.get("timestamp"):
            accumulator["timestamp"] = u_dict["timestamp"]