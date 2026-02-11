import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from django.conf import settings
from google.cloud import storage

from ai_services.ai_platform.llm.mixins import AIServiceMixin
from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from ai_services.ai_platform.llm.schemas import UsageStats
from core.exceptions import BizException
from core.error_codes import ErrorCode
from ai_services.utils.prompt_manager import PromptManager

from ai_services.schemas.creative.asset_selector import (
    AssetSelectorPayload, MultimodalSlice, AssetSelectorResponse, SegmentSelection, SelectedCandidate
)
from .schemas import BatchSelectionResponse

logger = logging.getLogger(__name__)

class AssetSelectorService(AIServiceMixin):
    """
    素材选择服务 (Creative)
    职责: 根据解说词语义，从 Slice 库中检索候选素材。
    """
    SERVICE_NAME = "asset_selector"
    
    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TOP_K = 5

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompt_manager = PromptManager(self.prompts_dir)

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Asset Selector...")

        # 1. 输入校验
        try:
            task_input = AssetSelectorPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        slices = self._load_slices(task_input)
        if not slices:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No slices loaded.")

        # 2. 配置初始化
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        
        top_k = self.DEFAULT_TOP_K

        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            if sp.top_k: top_k = sp.top_k
            self.logger.info(f"🔧 DEBUG Mode. Params: Model={model_name}, TopK={top_k}")
        else:
            self.logger.info(f"🏭 PROD Mode. Params: Model={model_name}")

        # 3. 执行选择 (目前全量一次性处理，如果 Slice 极多可能需要 RAG 或分批)
        # 假设 Slice 数量在 200 以内，Gemini Flash 上下文足够
        
        template_name = f"asset_selection_{task_input.lang}.j2"
        if not (self.prompts_dir / template_name).exists():
            template_name = "asset_selection_generic.j2"

        try:
            prompt = self.prompt_manager.render(template_name, {
                "slices": slices,
                "segments": task_input.dubbing_script,
                "top_k": top_k
            })
        except Exception as e:
            raise BizException(ErrorCode.FILE_IO_ERROR, f"Prompt rendering failed: {e}")

        selections = []
        usage_acc = {}

        for attempt in range(max_retries):
            try:
                response, usage = self.gemini_processor.generate_content(
                    model_name=model_name,
                    prompt=prompt,
                    response_schema=BatchSelectionResponse,
                    temperature=temperature
                )
                
                # 建立索引映射以快速查找 Slice 信息 (用于计算时长)
                slice_map = {s.index: s for s in slices}

                # 转换结果
                if response and response.results:
                    for res in response.results:
                        public_candidates = []
                        for cand in res.candidates:
                            # 计算时长 (cand.slice_id is index here)
                            original_slice = slice_map.get(cand.slice_id)
                            duration = round(original_slice.end_time - original_slice.start_time, 2) if original_slice else 0.0
                            
                            public_candidates.append(SelectedCandidate(
                                slice_id=original_slice.id if original_slice else "unknown", # Map index to UUID
                                score=cand.score,
                                reason=cand.reason,
                                duration=duration
                            ))

                        selections.append(SegmentSelection(
                            segment_index=res.segment_index,
                            candidates=public_candidates
                        ))
                
                # 记录用量
                usage_acc = usage.model_dump()
                # [Fix] 移除 model_used 以避免与 UsageStats 构造函数中的显式参数冲突
                usage_acc.pop("model_used", None)
                break

            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ Inference failed: {e}")
                    raise e
                self.logger.warning(f"⚠️ Retry {attempt + 1}: {e}")

        # 4. 响应
        cost_report = self.cost_calculator.calculate(UsageStats(model_used=model_name, **usage_acc))
        
        return AssetSelectorResponse(
            selections=selections,
            stats={"input_slices": len(slices), "segments": len(task_input.dubbing_script)},
            usage_report=cost_report.to_dict()
        ).model_dump()

    def _load_slices(self, task_input: AssetSelectorPayload) -> List[MultimodalSlice]:
        if task_input.slices:
            return task_input.slices

        if not task_input.slices_file_path:
            return []
        
        path_str = task_input.slices_file_path
        content = ""
        # 复用通用的加载逻辑 (这里简化，实际可提取到 Mixin)
        if path_str.startswith("gs://"):
            # ... GCS logic ...
            pass # 暂略，假设本地调试为主，或者复用之前的逻辑
        else:
            p = Path(path_str)
            if not p.is_absolute(): p = settings.SHARED_ROOT / p
            content = p.read_text(encoding='utf-8')

        return [MultimodalSlice(**item) for item in json.loads(content)]