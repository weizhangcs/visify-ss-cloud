import json
import logging
import time
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

from ai_services.schemas.refinery.slice_analyzer import (
    SliceAnalyzerPayload, MultimodalSlice, AnalyzedSlice, SliceAnalyzerResponse
)
from .schemas import BatchSliceAnalysisResponse

logger = logging.getLogger(__name__)


class SliceAnalyzerService(AIServiceMixin):
    """
    切片语义分析服务 (Refinery)

    职责:
    - 接收多模态切片列表。
    - 调用 LLM 对每个切片进行语义总结 (Narrative/Visual/Tags)。
    - 输出分析结果列表。
    """
    SERVICE_NAME = "slice_analyzer"

    # 默认配置
    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_BATCH_SIZE = 50
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3

    LANG_CODE_TO_NAME = {
        "zh": "Chinese", "en": "English", "jp": "Japanese",
        "ko": "Korean", "es": "Spanish", "fr": "French", "de": "German",
    }

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompt_manager = PromptManager(self.prompts_dir)
        self.metadata_path = Path(__file__).parent / "metadata" / "context.json"
        self._context_vocab = self._load_context_vocab()

    def _load_context_vocab(self) -> Dict:
        if self.metadata_path.exists():
            try:
                return json.loads(self.metadata_path.read_text(encoding='utf-8'))
            except Exception as e:
                self.logger.warning(f"Failed to load context vocab: {e}")
        return {}

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Slice Analyzer...")

        # 1. 输入校验
        try:
            task_input = SliceAnalyzerPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        slices = self._load_slices(task_input)
        if not slices:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No slices loaded.")

        # 2. 配置初始化
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        batch_size = config.get("batch_size", self.DEFAULT_BATCH_SIZE)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)

        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.batch_size: batch_size = sp.batch_size
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            self.logger.info(f"🔧 DEBUG Mode. Params: Model={model_name}, Batch={batch_size}")
        else:
            self.logger.info(f"🏭 PROD Mode. Params: Model={model_name}, Batch={batch_size}")

        # 3. 分批处理
        all_analyzed_slices = []
        total_usage = {}

        chunks = [slices[i:i + batch_size] for i in range(0, len(slices), batch_size)]
        self.logger.info(f"Split into {len(chunks)} batches (Batch Size: {batch_size}).")

        language_name = self.LANG_CODE_TO_NAME.get(task_input.lang.lower(), "English")

        # 获取当前语言的词表
        vocab = self._context_vocab.get(task_input.lang, self._context_vocab.get('en', {}))

        for i, chunk in enumerate(chunks):
            self.logger.info(f"Processing Batch {i + 1}/{len(chunks)} ({len(chunk)} slices)...")

            # 3.1 渲染 Prompt
            try:
                template_name = f"slice_analysis_{task_input.lang}.j2"
                if not (self.prompts_dir / template_name).exists():
                    template_name = "slice_analysis_generic.j2"

                prompt = self.prompt_manager.render(template_name, {
                    "slices": chunk,
                    "language_name": language_name,
                    "vocab": vocab
                })
            except Exception as e:
                self.logger.error(f"Failed to render prompt: {e}")
                raise BizException(ErrorCode.FILE_IO_ERROR, f"Prompt rendering failed: {e}")

            # 3.2 调用 LLM
            batch_results = []
            for attempt in range(max_retries):
                try:
                    response, usage = self.gemini_processor.generate_content(
                        model_name=model_name,
                        prompt=prompt,
                        response_schema=BatchSliceAnalysisResponse,
                        temperature=temperature
                    )
                    self._aggregate_usage(total_usage, usage)
                    if response and response.results:
                        batch_results = response.results
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        self.logger.error(f"❌ Batch inference failed: {e}")
                        # 失败时填充空结果，保证索引对齐或记录错误
                        # 这里简单跳过，或者可以抛出异常
                        raise e
                    time.sleep(2 * (attempt + 1))

            # 3.3 转换结果
            for res in batch_results:
                all_analyzed_slices.append(AnalyzedSlice(
                    slice_id=res.slice_id,
                    slice_analysis=res.analysis
                ))

        # 4. 成本计算
        final_stats_obj = UsageStats(model_used=model_name, **total_usage)
        cost_report = self.cost_calculator.calculate(final_stats_obj)

        # 5. 返回结果
        result = SliceAnalyzerResponse(
            analyzed_slices=all_analyzed_slices,
            stats={
                "input_slice_count": len(slices),
                "analyzed_count": len(all_analyzed_slices)
            },
            usage_report=cost_report.to_dict()
        )

        return result.model_dump()

    def _load_slices(self, task_input: SliceAnalyzerPayload) -> List[MultimodalSlice]:
        if task_input.slices:
            return task_input.slices

        if not task_input.slices_file_path:
            return []

        path_str = task_input.slices_file_path
        content = ""
        if path_str.startswith("gs://"):
            try:
                parts = path_str[5:].split("/", 1)
                bucket_name, blob_name = parts[0], parts[1]
                client = storage.Client(project=settings.GOOGLE_CLOUD_PROJECT)
                content = client.bucket(bucket_name).blob(blob_name).download_as_text(encoding='utf-8')
            except Exception as e:
                raise BizException(ErrorCode.FILE_IO_ERROR, f"GCS Read Failed: {e}")
        else:
            p = Path(path_str)
            if not p.is_absolute(): p = settings.SHARED_ROOT / p
            if not p.exists(): raise BizException(ErrorCode.FILE_IO_ERROR, f"File not found: {p}")
            content = p.read_text(encoding='utf-8')

        try:
            raw_data = json.loads(content)
            return [MultimodalSlice(**item) for item in raw_data]
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"JSON Parsing failed: {e}")

    def _aggregate_usage(self, accumulator: Dict, usage: UsageStats):
        u_dict = usage.model_dump()
        for key in ["prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "request_count",
                    "duration_seconds"]:
            accumulator[key] = accumulator.get(key, 0) + u_dict.get(key, 0)
        if u_dict.get("timestamp"):
            accumulator["timestamp"] = u_dict["timestamp"]