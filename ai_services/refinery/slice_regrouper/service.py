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

from ai_services.schemas.refinery.slice_regrouper import (
    SliceRegrouperPayload, MultimodalSlice, Scene, SliceRegrouperResponse,
    SceneContent, LabelItem, SCENE_TYPE_LABELS
)
from .schemas import RegroupingResponse, LLMScene

logger = logging.getLogger(__name__)

class SliceRegrouperService(AIServiceMixin):
    """
    场景聚类服务 (Refinery)
    
    架构设计:
    - 配置驱动: 参数由 ai_inference_config.yaml 管理。
    - 文本聚类: 将多模态切片转换为文本日志，利用 LLM 进行语义聚类。
    - BFF 友好: 输出 Label/Value 格式的 SceneType。
    """
    SERVICE_NAME = "slice_regrouper"
    
    # 默认配置
    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_MAX_SLICES_PER_BATCH = 200
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3

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
        self.logger.info("🚀 Starting Slice Regrouper...")

        # --- 1. 输入校验与加载 ---
        try:
            task_input = SliceRegrouperPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        slices = self._load_slices(task_input)
        if not slices:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No slices loaded.")
        
        self.logger.info(f"Loaded {len(slices)} slices. Preparing context...")

        # --- 2. 配置初始化 ---
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        max_slices_per_batch = config.get("max_slices_per_batch", self.DEFAULT_MAX_SLICES_PER_BATCH)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)

        # DEBUG 模式覆盖
        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.max_slices_per_batch: max_slices_per_batch = sp.max_slices_per_batch
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            self.logger.info(f"🔧 DEBUG Mode. Params: Model={model_name}, Batch={max_slices_per_batch}")
        else:
            self.logger.info(f"🏭 PROD Mode. Params: Model={model_name}, Batch={max_slices_per_batch}")

        # --- 3. 分批处理 (Batch Processing) ---
        all_llm_scenes = []
        total_usage = {}
        
        chunks = [slices[i:i + max_slices_per_batch] for i in range(0, len(slices), max_slices_per_batch)]
        self.logger.info(f"Split into {len(chunks)} batches (Batch Size: {max_slices_per_batch}).")

        for i, chunk in enumerate(chunks):
            self.logger.info(f"Processing Batch {i+1}/{len(chunks)} ({len(chunk)} slices)...")
            
            # 3.1 预处理切片 (去重)
            processed_slices = self._preprocess_slices(chunk)
            
            # 获取当前语言的词表
            vocab = self._context_vocab.get(task_input.lang, self._context_vocab.get('en', {}))
            
            # 3.2 调用 LLM
            batch_scenes, batch_usage = self._perform_regrouping_with_j2(
                processed_slices, vocab, task_input.lang, model_name, temperature, max_retries
            )
            
            # 3.3 收集结果
            all_llm_scenes.extend(batch_scenes)
            
            # 3.4 累加用量
            self._aggregate_usage(total_usage, batch_usage)
        
        # --- 4. 后处理：计算时间轴并构建最终 Scene 对象 ---
        final_scenes = []
        slice_map = {s.slice_id: s for s in slices}
        global_scene_id = 1
        
        label_map = SCENE_TYPE_LABELS.get(task_input.lang, SCENE_TYPE_LABELS.get('en', {}))

        for ls in all_llm_scenes:
            # 验证 slice_ids 有效性
            valid_ids = [sid for sid in ls.slice_ids if sid in slice_map]
            if not valid_ids:
                continue
            
            # 计算时间范围
            start_time = min(slice_map[sid].start_time for sid in valid_ids)
            end_time = max(slice_map[sid].end_time for sid in valid_ids)

            # [核心变更] 转换 SceneType Enum 为 LabelItem
            llm_content = ls.content
            
            # 构造 LabelItem
            enum_val = llm_content.scene_type
            label = label_map.get(enum_val, enum_val.value)
            scene_type_item = LabelItem(value=enum_val.value, label=label)

            # 构造 Public SceneContent
            public_content = SceneContent(
                narrative_action=llm_content.narrative_action,
                location=llm_content.location,
                scene_type=scene_type_item,
                visual_mood_tags=llm_content.visual_mood_tags,
                camera_logic=llm_content.camera_logic,
                character_dynamics=llm_content.character_dynamics,
                reason=llm_content.reason
            )

            final_scenes.append(Scene(
                scene_id=global_scene_id, # 重置全局 ID
                start_time=start_time,
                end_time=end_time,
                content=public_content,
                slice_ids=valid_ids
            ))
            global_scene_id += 1

        # --- 5. 计算成本 ---
        final_stats_obj = UsageStats(model_used=model_name, **total_usage)
        cost_report = self.cost_calculator.calculate(final_stats_obj)

        # --- 6. 返回结果 ---
        result = SliceRegrouperResponse(
            scenes=final_scenes,
            stats={
                "input_slice_count": len(slices),
                "output_scene_count": len(final_scenes)
            },
            usage_report=cost_report.to_dict()
        )

        return result.model_dump()

    def _load_slices(self, task_input: SliceRegrouperPayload) -> List[MultimodalSlice]:
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

    def _preprocess_slices(self, slices: List[MultimodalSlice]) -> List[MultimodalSlice]:
        """
        预处理切片数据：执行视觉帧去重。
        不再负责字符串拼接，直接返回对象列表供 Jinja2 渲染。
        """
        for i in range(len(slices) - 1):
            curr_s = slices[i]
            next_s = slices[i+1]
            
            if not curr_s.visual_contents or not next_s.visual_contents:
                continue
                
            last_frame = curr_s.visual_contents[-1]
            first_frame_next = next_s.visual_contents[0]
            
            if last_frame.digest and first_frame_next.digest and last_frame.digest == first_frame_next.digest:
                if len(curr_s.visual_contents) > 1:
                    curr_s.visual_contents.pop()
                elif len(next_s.visual_contents) > 1:
                    next_s.visual_contents.pop(0)

        return slices

    def _perform_regrouping_with_j2(self, slices: List[MultimodalSlice], vocab: Dict, lang: str, model_name: str, temperature: float, max_retries: int):
        # 渲染提示词
        try:
            template_name = f"slice_regrouping_{lang}.j2"
            if not (self.prompts_dir / template_name).exists():
                template_name = "slice_regrouping_generic.j2"

            # [核心变更] 直接传递对象列表和词表，由 Jinja2 负责渲染格式
            prompt = self.prompt_manager.render(template_name, {
                "slices": slices,
                "vocab": vocab
            })
        except Exception as e:
            self.logger.error(f"Failed to render prompt: {e}")
            raise BizException(ErrorCode.FILE_IO_ERROR, f"Prompt rendering failed: {e}")

        # 执行 LLM 推理
        for attempt in range(max_retries):
            try:
                response, usage = self.gemini_processor.generate_content(
                    model_name=model_name,
                    prompt=prompt,
                    response_schema=RegroupingResponse,
                    temperature=temperature
                )
                return response.scenes if response else [], usage
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ Batch inference failed after {max_retries} attempts: {e}")
                    raise e
                wait_time = 2 * (attempt + 1)
                self.logger.warning(f"⚠️ Batch inference failed (Attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)

    def _aggregate_usage(self, accumulator: Dict, usage: UsageStats):
        u_dict = usage.model_dump()
        for key in ["prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "request_count", "duration_seconds"]:
            accumulator[key] = accumulator.get(key, 0) + u_dict.get(key, 0)
        if u_dict.get("timestamp"):
            accumulator["timestamp"] = u_dict["timestamp"]