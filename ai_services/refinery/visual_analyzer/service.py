import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from google.genai import types

from ai_services.ai_platform.llm.mixins import AIServiceMixin
from ai_services.ai_platform.llm.vertex_processor import VertexProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from ai_services.ai_platform.llm.schemas import UsageStats
from configuration.tag_manager import TagManager
from core.exceptions import BizException
from core.error_codes import ErrorCode
from ai_services.utils.prompt_manager import PromptManager

from ai_services.schemas.refinery.visual_analyzer import (
    VisualAnalyzerPayload, VisualFrameInput, AnnotatedFrame, VisualAnalysisData,
    VisualAnalyzerResponse, SHOT_TYPE_LABELS, LabelItem
)
from .schemas import BatchVisualOutput, FrameAnalysisResult, LLMVisualAnalysisData

logger = logging.getLogger(__name__)

class VisualAnalyzerService(AIServiceMixin):
    """
    视觉分析服务 (Refinery)
    
    架构设计:
    - 配置驱动: 参数由 ai_inference_config.yaml 管理。
    - 多模态处理: 使用 VertexProcessor 处理图片+文本输入。
    - 并发执行: 使用 ThreadPoolExecutor 并发处理图片批次。
    - 断点续传: 支持结果缓存，防止长任务中断。
    """
    SERVICE_NAME = "visual_analyzer"
    
    # 默认配置
    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_BATCH_SIZE = 20
    DEFAULT_MAX_WORKERS = 5
    DEFAULT_TEMP = 0.1
    DEFAULT_MAX_RETRIES = 3
    
    RESULT_CACHE_FILE = "visual_analyzer_result.json"

    def __init__(self, logger: logging.Logger, vertex_processor: VertexProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.vertex_processor = vertex_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompt_manager = PromptManager(self.prompts_dir)

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Visual Analyzer...")

        # --- 1. 输入校验与加载 ---
        try:
            task_input = VisualAnalyzerPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        target_frames = self._load_frames(task_input)
        if not target_frames:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No frames provided.")

        # --- 2. 配置初始化 ---
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        batch_size = config.get("batch_size", self.DEFAULT_BATCH_SIZE)
        max_workers = config.get("max_workers", self.DEFAULT_MAX_WORKERS)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)

        # DEBUG 模式覆盖
        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.batch_size: batch_size = sp.batch_size
            if sp.max_workers: max_workers = sp.max_workers
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            self.logger.info(f"🔧 DEBUG Mode. Params: Model={model_name}, Batch={batch_size}, Workers={max_workers}")
        else:
            self.logger.info(f"🏭 PROD Mode. Params: Model={model_name}, Batch={batch_size}, Workers={max_workers}")

        # --- 3. 准备缓存路径 ---
        # 使用 第一个 frame_id 作为缓存键源
        cache_key_source = target_frames[0].frame_id if target_frames else "default"
        cache_key = str(abs(hash(cache_key_source)))
        cache_dir = settings.SHARED_TMP_ROOT / "visual_analyzer_cache" / f"{cache_key}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        result_cache_path = cache_dir / self.RESULT_CACHE_FILE

        # --- 4. 执行分析 ---
        annotated_frames, usage_accumulator = self._process_visuals(
            target_frames, task_input, result_cache_path, 
            model_name, batch_size, max_workers, temperature
        )

        # --- 5. 后处理 (ShotType 本地化) ---
        final_frames_output = []
        label_map = SHOT_TYPE_LABELS.get(task_input.lang, SHOT_TYPE_LABELS.get('en', {}))

        for frame_res in annotated_frames:
            # frame_res.visual_analysis 是 LLMVisualAnalysisData (Private)
            llm_data = frame_res.visual_analysis

            # 转换为 Public Data (VisualAnalysisData)
            public_data_dict = llm_data.model_dump()

            # 构造 LabelItem
            if llm_data.shot_type:
                enum_val = llm_data.shot_type
                label = label_map.get(enum_val, enum_val.value)
                public_data_dict['shot_type'] = LabelItem(value=enum_val.value, label=label)

            final_frames_output.append(AnnotatedFrame(
                frame_id=frame_res.frame_id,
                visual_analysis=VisualAnalysisData(**public_data_dict)
            ))

        # --- 6. 响应构建 ---
        cost_report = self.cost_calculator.calculate(UsageStats(model_used=model_name, **usage_accumulator))

        response = VisualAnalyzerResponse(
            annotated_frames=final_frames_output,
            stats={"total_frames": len(target_frames), "processed": len(annotated_frames)},
            usage_report=cost_report.to_dict()
        )

        return response.model_dump()

    def _process_visuals(self, frames: List[VisualFrameInput], task_input: VisualAnalyzerPayload, 
                         result_path: Path, model_name: str, batch_size: int, max_workers: int, temperature: float):
        # 加载断点
        results_map = {}
        if result_path.exists():
            try:
                raw = json.loads(result_path.read_text(encoding='utf-8'))
                for k, v in raw.items():
                    results_map[k] = LLMVisualAnalysisData(**v)
            except Exception:
                pass

        usage_acc = {}
        to_process = [f for f in frames if f.frame_id not in results_map]

        if to_process:
            # 渲染 Prompt 指令
            template_name = f"visual_analyze_{task_input.lang}.j2"
            if not (self.prompts_dir / template_name).exists():
                template_name = "visual_analyze_generic.j2"
            
            instruction = self.prompt_manager.render(template_name, {})

            chunks = [to_process[i:i + batch_size] for i in range(0, len(to_process), batch_size)]

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_chunk = {
                    executor.submit(self._batch_inference, chunk, model_name, instruction, temperature): chunk
                    for chunk in chunks
                }

                for future in as_completed(future_to_chunk):
                    try:
                        batch_res, batch_usage = future.result()
                        results_map.update(batch_res)

                        # 累加 Usage
                        self._aggregate_usage(usage_acc, batch_usage)

                        # 保存断点
                        save_data = {str(k): v.model_dump() for k, v in results_map.items()}
                        result_path.write_text(json.dumps(save_data, ensure_ascii=False), encoding='utf-8')

                    except Exception as e:
                        self.logger.error(f"Batch failed: {e}")

        # 组装最终结果
        final_list = []
        for f in frames:
            vis = results_map.get(f.frame_id)
            if vis:
                if vis.visual_mood_tags:
                    vis.visual_mood_tags = TagManager.normalize_tags(vis.visual_mood_tags, 'visual_mood', True)
            else:
                vis = LLMVisualAnalysisData()

            final_list.append(FrameAnalysisResult(frame_id=f.frame_id, visual_analysis=vis))

        return final_list, usage_acc

    def _batch_inference(self, frames: List[VisualFrameInput], model_name: str, instruction: str, temperature: float) -> tuple[Dict[str, LLMVisualAnalysisData], UsageStats]:
        contents: List[Union[str, types.Part]] = [instruction]

        for f in frames:
            contents.append(f"\n--- Frame ID: {f.frame_id} ---")
            part = self._load_image_part(f.path)
            if part:
                contents.append(part)
            else:
                contents.append("[Missing Frame Data]")

        # 预计算 Token (可选，VertexProcessor 内部暂未自动修正，这里先依赖 API 返回)
        # 如果需要精确计费，可以在这里调用 self.vertex_processor.count_tokens

        response_obj, usage = self.vertex_processor.generate_content(
            model_name=model_name,
            prompt=contents,
            response_schema=BatchVisualOutput,
            temperature=temperature
        )

        result_map = {}
        if response_obj and response_obj.results:
            for res_item in response_obj.results:
                result_map[res_item.frame_id] = res_item.visual_analysis
        
        return result_map, usage

    def _load_image_part(self, path_str: str) -> Optional[types.Part]:
        if path_str.startswith("gs://"):
            return types.Part.from_uri(file_uri=path_str, mime_type="image/jpeg")
        else:
            local_path = Path(path_str)
            if not local_path.is_absolute():
                local_path = settings.SHARED_ROOT / local_path
            if local_path.exists():
                return types.Part.from_bytes(data=local_path.read_bytes(), mime_type="image/jpeg")
            else:
                return None

    def _load_frames(self, task_input: VisualAnalyzerPayload) -> List[VisualFrameInput]:
        if task_input.frames:
            return task_input.frames
        
        if task_input.frames_file_path:
            local_path = Path(task_input.frames_file_path)
            if not local_path.is_absolute():
                local_path = settings.SHARED_ROOT / local_path
            content = local_path.read_text(encoding='utf-8')
            raw_list = json.loads(content)
            return [VisualFrameInput(**item) for item in raw_list]
        return []

    def _aggregate_usage(self, accumulator: Dict, usage: UsageStats):
        u_dict = usage.model_dump()
        for key in ["prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "request_count", "duration_seconds"]:
            accumulator[key] = accumulator.get(key, 0) + u_dict.get(key, 0)
        if u_dict.get("timestamp"):
            accumulator["timestamp"] = u_dict["timestamp"]