# ai_services/refinery/dubbing_script_refiner/service.py
import time
import json
import logging
from pathlib import Path
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional, Tuple

from django.conf import settings

from ai_services.ai_platform.llm.mixins import AIServiceMixin
from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from ai_services.ai_platform.llm.schemas import UsageStats
from core.exceptions import BizException
from core.error_codes import ErrorCode
from ai_services.utils.prompt_manager import PromptManager

from ai_services.schemas.refinery.dubbing_script_refiner import (
    DubbingScriptRefinerPayload, AsrSegment, OcrText, RefinedSegment,
    DubbingScriptRefinerResponse, Stats
)
from .schemas import BatchRefinementResponse, LLMRefinedSegment

logger = logging.getLogger(__name__)

class DubbingScriptRefinerService(AIServiceMixin):
    """
    剧本精修服务 (Refinery)
    职责: 融合 ASR 和 OCR 数据，利用 LLM 生成精修、对齐、翻译后的剧本。
    """
    SERVICE_NAME = "dubbing_script_refiner"

    # Default configs
    DEFAULT_MODEL = "gemini-2.5-pro"
    DEFAULT_TEMP = 0.2
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_CHUNK_DURATION = 180  # 3 minutes
    DEFAULT_CHUNK_OVERLAP = 10    # 10 seconds
    DEFAULT_ALIGNMENT_TOLERANCE = 1.0 # 1 second
    DEFAULT_SIMILARITY_THRESHOLD = 0.2 # 默认相似度阈值

    def __init__(self, logger: logging.Logger, gemini_processor: GeminiProcessor, cost_calculator: CostCalculator):
        self.logger = logger
        self.gemini_processor = gemini_processor
        self.cost_calculator = cost_calculator
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompt_manager = PromptManager(self.prompts_dir)

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        start_time_ms = time.time()
        self.logger.info("🚀 Starting Dubbing Script Refiner...")

        # 1. Input validation
        try:
            task_input = DubbingScriptRefinerPayload(**payload)
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
                    # 补充数据到 task_input 对象中 (注意：这里假设文件中包含 asr_segments 和 ocr_texts 字段)
                    # 我们需要重新验证加载的数据结构
                    loaded_payload = DubbingScriptRefinerPayload(**{**payload, **data})
                    task_input.asr_segments = loaded_payload.asr_segments
                    task_input.ocr_texts = loaded_payload.ocr_texts
            except Exception as e:
                raise BizException(ErrorCode.FILE_IO_ERROR, f"Failed to load input file: {e}")

        # 2. Config initialization
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        temperature = config.get("temperature", self.DEFAULT_TEMP)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        chunk_duration = config.get("chunk_duration_seconds", self.DEFAULT_CHUNK_DURATION)
        chunk_overlap = config.get("chunk_overlap_seconds", self.DEFAULT_CHUNK_OVERLAP)
        alignment_tolerance = config.get("alignment_tolerance_seconds", self.DEFAULT_ALIGNMENT_TOLERANCE)
        similarity_threshold = config.get("similarity_threshold", self.DEFAULT_SIMILARITY_THRESHOLD)

        if task_input.mode == "DEBUG" and task_input.service_params:
            sp = task_input.service_params
            if sp.model: model_name = sp.model
            if sp.temperature is not None: temperature = sp.temperature
            if sp.max_retries: max_retries = sp.max_retries
            if sp.chunk_duration_seconds: chunk_duration = sp.chunk_duration_seconds
            if sp.chunk_overlap_seconds: chunk_overlap = sp.chunk_overlap_seconds
            if sp.alignment_tolerance_seconds: alignment_tolerance = sp.alignment_tolerance_seconds
            self.logger.info(f"🔧 DEBUG Mode. Params: Model={model_name}, Temp={temperature}")
        else:
            self.logger.info(f"🏭 PROD Mode. Params: Model={model_name}")

        # 3. Pre-processing: Align and Chunk data
        dialogue_unit_chunks = self._align_and_chunk_inputs(
            task_input.asr_segments, task_input.ocr_texts,
            chunk_duration, chunk_overlap, alignment_tolerance, similarity_threshold
        )
        self.logger.info(f"Data processed into {len(dialogue_unit_chunks)} chunks.")

        # 4. Batch processing
        # [Optimization] Store tuples of (LLMResult, OriginalUnit) to restore original text later
        all_results: List[Tuple[LLMRefinedSegment, Dict]] = []
        total_usage = {}

        for i, chunk in enumerate(dialogue_unit_chunks):
            self.logger.info(f"Processing Batch {i + 1}/{len(dialogue_unit_chunks)}...")
            if not chunk:
                continue

            # 4.1 Render Prompt
            try:
                template_name = f"script_refinement_{task_input.lang}.j2"
                if not (self.prompts_dir / template_name).exists():
                    template_name = "script_refinement_generic.j2"

                prompt = self.prompt_manager.render(template_name, {"dialogue_units": chunk, "lang": task_input.lang})
            except Exception as e:
                raise BizException(ErrorCode.FILE_IO_ERROR, f"Prompt rendering failed: {e}")

            # 4.2 Call LLM
            for attempt in range(max_retries):
                try:
                    response, usage = self.gemini_processor.generate_content(
                        model_name=model_name,
                        prompt=prompt,
                        response_schema=BatchRefinementResponse,
                        temperature=temperature
                    )
                    self._aggregate_usage(total_usage, usage)
                    if response and response.refined_script:
                        # Map LLM results back to original chunks to preserve ASR/OCR text
                        # Note: This assumes LLM returns segments in the same order or we match by time.
                        # For simplicity and robustness, we'll just collect them and match by timestamp in post-processing
                        # or simply trust the LLM's time if it's accurate enough.
                        # Better strategy: The LLM output contains 'start'/'end'. We use that.
                        # We need to pass the original chunk data to post-processing if we want to restore 'original_*' fields without LLM outputting them.
                        # Let's attach the source chunk to the results for context if needed, 
                        # but actually, if we removed original_* from LLM schema, we need to look them up from 'chunk'.
                        
                        # Simple matching strategy: Find the closest unit in 'chunk' for each result
                        for seg in response.refined_script:
                            # Find matching unit in chunk based on start time (approximate match)
                            matched_unit = next((u for u in chunk if abs(u['start'] - seg.start) < 0.1), None)
                            all_results.append((seg, matched_unit))
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        self.logger.error(f"❌ Batch inference failed: {e}")
                        raise e
                    self.logger.warning(f"⚠️ Retry {attempt + 1}: {e}")
                    time.sleep(2 * (attempt + 1))

        # 5. Post-processing and Response formatting
        final_script = self._post_process_results(all_results)

        # 6. Cost calculation
        final_stats_obj = UsageStats(model_used=model_name, **total_usage)
        cost_report = self.cost_calculator.calculate(final_stats_obj)

        # 7. Build final response
        processing_time_ms = int((time.time() - start_time_ms) * 1000)

        avg_confidence = None
        conf_scores = [s.confidence_score for s in final_script if s.confidence_score is not None]
        if conf_scores:
            avg_confidence = round(sum(conf_scores) / len(conf_scores), 3)

        stats = Stats(
            processing_time_ms=processing_time_ms,
            asr_segments_count=len(task_input.asr_segments),
            ocr_texts_count=len(task_input.ocr_texts),
            refined_segments_count=len(final_script),
            avg_confidence_score=avg_confidence
        )

        return DubbingScriptRefinerResponse(
            refined_script=final_script,
            stats=stats,
            usage_report=cost_report.to_dict()
        ).model_dump()

    def _align_and_chunk_inputs(self, asr_list: List[AsrSegment], ocr_list: List[OcrText],
                                chunk_duration: int, chunk_overlap: int, tolerance: float,
                                similarity_threshold: float) -> List[List[Dict]]:
        """
        [V2] Implements a two-pass, ASR-anchored alignment strategy with similarity gating.
        """
        dialogue_units = []
        processed_ocr_ids = set()

        # Pass 1: ASR-Anchored Traversal
        for asr in asr_list:
            best_match_ocr = None
            max_similarity = -1.0

            # 1. Find temporally overlapping OCR candidates
            candidates = []
            for ocr in ocr_list:
                if max(asr.start, ocr.start_time) < min(asr.end, ocr.end_time) + tolerance:
                    candidates.append(ocr)

            # 2. Find the best candidate based on content similarity
            if candidates:
                for ocr_candidate in candidates:
                    similarity = SequenceMatcher(None, asr.text, ocr_candidate.text).ratio()
                    if similarity > max_similarity:
                        max_similarity = similarity
                        best_match_ocr = ocr_candidate

            # 3. Similarity Gating: Merge only if similarity is above threshold
            if best_match_ocr and max_similarity >= similarity_threshold and id(best_match_ocr) not in processed_ocr_ids:
                dialogue_units.append({
                    'start': asr.start,
                    'end': asr.end,
                    'asr': asr,
                    'ocr': best_match_ocr
                })
                processed_ocr_ids.add(id(best_match_ocr))
            else:
                # No suitable OCR match found, create an ASR-only unit
                dialogue_units.append({'start': asr.start, 'end': asr.end, 'asr': asr, 'ocr': None})

        # Pass 2: Orphan OCR Processing
        for ocr in ocr_list:
            if id(ocr) not in processed_ocr_ids:
                # This OCR was not claimed by any ASR, treat it as a potential ASR omission
                dialogue_units.append({'start': ocr.start_time, 'end': ocr.end_time, 'asr': None, 'ocr': ocr})

        dialogue_units.sort(key=lambda x: x['start'])

        # 2. Sliding Window chunking
        if not dialogue_units:
            return []

        chunks = []
        current_chunk_start = 0.0
        video_duration = max(u['end'] for u in dialogue_units) if dialogue_units else 0

        while current_chunk_start < video_duration:
            chunk_end = current_chunk_start + chunk_duration
            chunk_units = [u for u in dialogue_units if u['start'] >= current_chunk_start and u['start'] < chunk_end]
            chunks.append(chunk_units)
            current_chunk_start += (chunk_duration - chunk_overlap)

        return chunks

    def _post_process_results(self, results: List[Tuple[LLMRefinedSegment, Optional[Dict]]]) -> List[RefinedSegment]:
        """
        Post-processes LLM results, calculates confidence scores, and converts to public schema.
        Restores original_asr/ocr from source units since LLM no longer outputs them.
        """
        final_script = []
        for res, source_unit in results:
            # Construct public response, restoring original text from source_unit if available
            public_res = RefinedSegment(
                start=res.start,
                end=res.end,
                original_asr=source_unit['asr'].text if source_unit and source_unit.get('asr') else None,
                original_ocr=source_unit['ocr'].text if source_unit and source_unit.get('ocr') else None,
                refined_text=res.refined_text,
                source_of_truth=res.source_of_truth,
                reasoning=res.reasoning
            )

            # Calculate confidence score based on CR suggestion
            score = 0.0
            if public_res.source_of_truth == "ASR_OCR_MERGED":
                score = 0.9
            elif public_res.source_of_truth in ["ASR_ONLY", "OCR_PRIMARY"]:
                score = 0.75
            elif public_res.source_of_truth == "CONTEXT_REPAIR":
                score = 0.6
            elif public_res.source_of_truth == "OCR_IGNORED":
                score = 1.0

            public_res.confidence_score = score
            final_script.append(public_res)

        final_script.sort(key=lambda x: x.start)

        # [Deduplication] Remove duplicates caused by sliding window overlap
        if not final_script:
            return []

        deduplicated_script = []
        current_best = final_script[0]

        for i in range(1, len(final_script)):
            candidate = final_script[i]

            # Check for duplicate based on start time (tolerance 0.1s)
            if abs(candidate.start - current_best.start) < 0.1:
                # Duplicate found. Apply selection strategy:
                # 1. Higher confidence score wins
                # 2. If equal, keep the first one (current_best)
                score_curr = current_best.confidence_score or 0.0
                score_cand = candidate.confidence_score or 0.0

                if score_cand > score_curr:
                    current_best = candidate
            else:
                # No overlap, commit current_best and move to next
                deduplicated_script.append(current_best)
                current_best = candidate

        # Append the last pending segment
        deduplicated_script.append(current_best)

        return deduplicated_script