# ai_services/refinery/character_role_finalizer/service.py
import time
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from django.conf import settings

from ai_services.ai_platform.llm.mixins import AIServiceMixin
from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from ai_services.ai_platform.llm.schemas import UsageStats
from core.exceptions import BizException
from core.error_codes import ErrorCode
from ai_services.utils.prompt_manager import PromptManager

from ai_services.schemas.refinery.character_role_finalizer import (
    CharacterRoleFinalizerPayload, FinalizedSegment, CharacterMapItem,
    CharacterRoleFinalizerResponse, Stats
)
from .schemas import BatchRoleFinalizationResponse

logger = logging.getLogger(__name__)

class CharacterRoleFinalizerService(AIServiceMixin):
    """
    角色身份终结者服务
    职责: 基于全剧本上下文，进行实体归一化(Entity Linking)和逻辑纠错(Speaker Re-ID)。
    """
    SERVICE_NAME = "character_role_finalizer"

    DEFAULT_MODEL = "gemini-2.5-pro"
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompt_manager = PromptManager(self.prompts_dir)

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        start_time_ms = time.time()
        self.logger.info("🚀 Starting Character Role Finalizer...")

        # 1. Input Validation
        try:
            task_input = CharacterRoleFinalizerPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        # 1.1 Load data from file if input_file_path is provided
        if task_input.input_file_path:
            try:
                file_path = Path(task_input.input_file_path)

                # [Fix] 兼容相对路径：如果传入的是相对路径，自动拼接 SHARED_ROOT
                if not file_path.is_absolute():
                    file_path = settings.SHARED_ROOT / file_path

                if not file_path.exists():
                    raise FileNotFoundError(f"Input file not found: {file_path}")
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 补充数据到 task_input 对象中
                    # 我们需要重新验证加载的数据结构
                    loaded_payload = CharacterRoleFinalizerPayload(**{**payload, **data})
                    task_input.segments = loaded_payload.segments
            except Exception as e:
                raise BizException(ErrorCode.FILE_IO_ERROR, f"Failed to load input file: {e}")

        # 2. Config
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)

        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries

        # 3. Prepare Data (Global Context)
        # 假设剧本长度在 Gemini 2.5 Pro 的上下文窗口内 (1M tokens)，我们一次性传入。
        # 如果未来剧本超长，需要实现滑动窗口或分幕处理。
        segments = task_input.segments
        
        # 4. Render Prompt
        try:
            template_name = f"character_role_finalizer_{task_input.lang}.j2"
            if not (self.prompts_dir / template_name).exists():
                # Fallback to zh if generic not found, or create generic. Assuming zh for now based on request.
                template_name = "character_role_finalizer_zh.j2"
            
            prompt = self.prompt_manager.render(template_name, {"segments": segments})
        except Exception as e:
            raise BizException(ErrorCode.FILE_IO_ERROR, f"Prompt rendering failed: {e}")

        # 5. Call LLM
        llm_response = None
        usage = None
        
        for attempt in range(max_retries):
            try:
                llm_response, usage = self.gemini_processor.generate_content(
                    model_name=model_name,
                    prompt=prompt,
                    response_schema=BatchRoleFinalizationResponse,
                    temperature=temperature
                )
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                self.logger.warning(f"Retry {attempt + 1}: {e}")
                time.sleep(2)

        # 6. Post-processing & Merge
        finalized_script = []
        corrected_count = 0
        
        # Create a lookup map for LLM results by index
        llm_seg_map = {s.index: s for s in llm_response.segments}
        
        # Create a name lookup map
        id_to_name = {c.speaker_id: c.name for c in llm_response.character_map}

        for i, original_seg in enumerate(segments):
            llm_seg = llm_seg_map.get(i)
            
            final_speaker = llm_seg.speaker_id if llm_seg else (original_seg.speaker or "UNKNOWN")
            reasoning = llm_seg.reasoning if llm_seg else "Retained original."
            
            if final_speaker != original_seg.speaker:
                corrected_count += 1

            finalized_script.append(FinalizedSegment(
                start=original_seg.start,
                end=original_seg.end,
                text=original_seg.refined_text or "",
                speaker_id=final_speaker,
                character_name=id_to_name.get(final_speaker),
                reasoning=reasoning
            ))

        # 7. Stats & Response
        cost_report = self.cost_calculator.calculate(usage)
        processing_time_ms = int((time.time() - start_time_ms) * 1000)

        stats = Stats(
            processing_time_ms=processing_time_ms,
            total_segments=len(segments),
            corrected_segments_count=corrected_count
        )

        return CharacterRoleFinalizerResponse(
            finalized_script=finalized_script,
            character_map=[CharacterMapItem(**c.model_dump()) for c in llm_response.character_map],
            stats=stats,
            usage_report=cost_report.to_dict()
        ).model_dump()