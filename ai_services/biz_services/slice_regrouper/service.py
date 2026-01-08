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

from .schemas import (
    SliceRegrouperPayload, MultimodalSlice, RegroupingResponse,
    Scene, SliceRegrouperResult
)

logger = logging.getLogger(__name__)

class SliceRegrouperService(AIServiceMixin):
    SERVICE_NAME = "slice_regrouper"
    
    # [Fix] 降低 Batch Size 以强制 LLM 关注局部细节，避免场景划分过粗
    MAX_SLICES_PER_BATCH = 200 

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.metadata_path = Path(__file__).parent / "metadata" / "context.json"
        self._context_vocab = self._load_context_vocab()

    def _load_context_vocab(self) -> Dict:
        if self.metadata_path.exists():
            try:
                return json.loads(self.metadata_path.read_text(encoding='utf-8'))
            except Exception as e:
                self.logger.warning(f"Failed to load context vocab: {e}")
        return {}

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Slice Regrouper...")

        # 1. 解析 Payload
        try:
            task_input = SliceRegrouperPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        # 2. 加载切片数据
        slices = self._load_slices(task_input)
        if not slices:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, "No slices loaded.")
        
        self.logger.info(f"Loaded {len(slices)} slices. Preparing context...")

        # 3. 分批处理 (Batch Processing)
        # 将切片列表切分为多个 Batch，分别进行聚类，最后合并结果
        all_llm_scenes = []
        total_usage = {}
        
        # 简单的切分策略
        chunks = [slices[i:i + self.MAX_SLICES_PER_BATCH] for i in range(0, len(slices), self.MAX_SLICES_PER_BATCH)]
        self.logger.info(f"Split into {len(chunks)} batches (Batch Size: {self.MAX_SLICES_PER_BATCH}).")

        for i, chunk in enumerate(chunks):
            self.logger.info(f"Processing Batch {i+1}/{len(chunks)} ({len(chunk)} slices)...")
            
            # 3.1 构建上下文
            slice_log = self._convert_to_context(chunk, task_input.lang)
            
            # 3.2 调用 LLM
            batch_scenes, batch_usage = self._perform_regrouping(slice_log, task_input.lang, task_input.model)
            
            # 3.3 收集结果
            all_llm_scenes.extend(batch_scenes)
            
            # 3.4 累加用量
            # batch_usage 是 UsageStats 对象，需转为字典
            for k, v in batch_usage.model_dump().items():
                if isinstance(v, (int, float)):
                    total_usage[k] = total_usage.get(k, 0) + v
        
        # 4. 后处理：计算时间轴并构建最终 Scene 对象
        final_scenes = []
        slice_map = {s.slice_id: s for s in slices}
        global_scene_id = 1

        for ls in all_llm_scenes:
            # 验证 slice_ids 有效性
            valid_ids = [sid for sid in ls.slice_ids if sid in slice_map]
            if not valid_ids:
                continue
            
            # 计算时间范围
            start_time = min(slice_map[sid].start_time for sid in valid_ids)
            end_time = max(slice_map[sid].end_time for sid in valid_ids)

            final_scenes.append(Scene(
                scene_id=global_scene_id, # 重置全局 ID
                start_time=start_time,
                end_time=end_time,
                content=ls.content,
                slice_ids=valid_ids
            ))
            global_scene_id += 1

        # 5. 计算成本
        final_stats_obj = UsageStats(model_used=task_input.model, **total_usage)
        cost_report = self.cost_calculator.calculate(final_stats_obj)

        # 6. 返回结果
        result = SliceRegrouperResult(
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

    def _convert_to_context(self, slices: List[MultimodalSlice], lang: str) -> str:
        """将复杂的多模态切片转换为紧凑的日志格式，供 LLM 阅读"""
        vocab = self._context_vocab.get(lang, self._context_vocab.get('en', {}))
        
        # 词表映射
        type_map = vocab.get("type_mapping", {})
        speaker_unknown = vocab.get("speaker_unknown", "Unknown")
        vis_prefix = vocab.get("vis_prefix", "  Vis: ")
        sub_prefix = vocab.get("sub_prefix", "  Sub: ")

        # [New] 视觉帧去重预处理 (Deduplication)
        # 逻辑：如果 Slice N 的尾帧与 Slice N+1 的首帧 digest 一致，视为冗余，需剔除。
        for i in range(len(slices) - 1):
            curr_s = slices[i]
            next_s = slices[i+1]
            
            if not curr_s.visual_contents or not next_s.visual_contents:
                continue
                
            last_frame = curr_s.visual_contents[-1]
            first_frame_next = next_s.visual_contents[0]
            
            # 仅当 digest 存在且一致时进行去重
            if last_frame.digest and first_frame_next.digest and last_frame.digest == first_frame_next.digest:
                # 场景 1: 当前切片有多帧 -> 删除当前切片的尾帧
                if len(curr_s.visual_contents) > 1:
                    curr_s.visual_contents.pop()
                # 场景 2: 当前切片仅1帧 -> 删除下一切片的首帧 (避免当前切片变空)
                elif len(next_s.visual_contents) > 1:
                    next_s.visual_contents.pop(0)
                # 场景 3: 都是单帧 -> 不处理 (兜底)

        log_blocks = []
        for s in slices:
            current_block = []
            
            # 1. 类型映射
            display_type = type_map.get(s.type, s.type)
            
            # 主信息行，包含类型
            main_line = f"[Slice {s.slice_id}] {s.start_time:.1f}-{s.end_time:.1f}s [Type: {display_type}]"
            current_block.append(main_line)

            # 2. 视觉特征 (移除索引，移除 N/A)
            if s.visual_contents:
                for frame in s.visual_contents:
                    if frame.visual_analysis:
                        v = frame.visual_analysis
                        tags = ",".join(v.visual_mood_tags[:3]) if v.visual_mood_tags else ""
                        # 格式: 前缀 环境 | 主体 动作 | [Tags]
                        vis_line = f"{vis_prefix}{v.environment or 'Unknown'} | {v.subject or ''} {v.action or ''} | [{tags}]"
                        current_block.append(vis_line)

            # 3. 文本特征 (处理 Unknown 角色，移除 N/A)
            if s.text_contents:
                for text_item in s.text_contents:
                    speaker = text_item.speaker
                    if not speaker or speaker == "Unknown":
                        speaker = speaker_unknown
                    
                    # 格式: 前缀 Speaker: "Content"
                    sub_line = f"{sub_prefix}{speaker}: \"{text_item.content}\""
                    current_block.append(sub_line)

            log_blocks.append("\n".join(current_block))

        # 使用 "---" 分隔不同的切片，让 LLM 更清晰地识别边界
        return "\n---\n".join(log_blocks)

    def _perform_regrouping(self, slice_log: str, lang: str, model_name: str):
        try:
            prompt_path = self.prompts_dir / "slice_regrouping_zh.txt" # 暂时只支持中文 Prompt
            template = prompt_path.read_text(encoding='utf-8')
        except Exception as e:
            raise BizException(ErrorCode.FILE_IO_ERROR, f"Prompt missing: {e}")

        # [Debug] 保存 slice_log 到文件以便调试
        try:
            debug_log_path = settings.SHARED_LOG_ROOT / "slice_regrouper_debug" / f"slice_log_{int(time.time())}.txt"
            debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            debug_log_path.write_text(slice_log, encoding='utf-8')
        except Exception as e:
            self.logger.warning(f"Failed to save debug slice log: {e}")

        prompt = template.replace("{slice_log}", slice_log)

        response, usage = self.gemini_processor.generate_content(
            model_name=model_name,
            prompt=prompt,
            response_schema=RegroupingResponse,
            temperature=0.1
        )
        
        return response.scenes if response else [], usage