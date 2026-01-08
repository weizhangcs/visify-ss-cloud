import json
from pathlib import Path
from django.conf import settings

from task_manager.models import Task
from task_manager.handlers.base import BaseTaskHandler
from task_manager.handlers.registry import HandlerRegistry

from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from ai_services.refinery.subtitle_merger.service import SubtitleMergerService
from ai_services.schemas.refinery.subtitle_merger import SubtitleMergerPayload

from core.exceptions import BizException
from core.error_codes import ErrorCode

@HandlerRegistry.register(Task.TaskType.SUBTITLE_MERGER)
class SubtitleMergerHandler(BaseTaskHandler):
    """
    [Handler] 字幕语义合并任务
    职责：
    1. 接收原始字幕列表。
    2. 调用 SubtitleMergerService 进行语义合并。
    3. 输出合并后的字幕列表。
    """

    def handle(self, task: Task) -> dict:
        self.logger.info(f"🚀 Starting SUBTITLE_MERGER Task: {task.id} (Type: {task.task_type})")

        # 1. 基础设施
        debug_dir = settings.SHARED_LOG_ROOT / f"subtitle_merger_{task.id}_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

        gemini_processor = GeminiProcessor(
            api_key=settings.GOOGLE_API_KEY,
            logger=self.logger,
            debug_mode=True,
            debug_dir=debug_dir
        )

        cost_calculator = CostCalculator(
            pricing_data=settings.GEMINI_PRICING,
            usd_to_rmb_rate=settings.USD_TO_RMB_EXCHANGE_RATE
        )

        service = SubtitleMergerService(
            logger=self.logger,
            gemini_processor=gemini_processor,
            cost_calculator=cost_calculator
        )

        # 2. Payload 校验
        try:
            SubtitleMergerPayload(**task.payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Invalid Payload: {e}")

        # 3. 执行
        try:
            result_data = service.execute(task.payload)
        except Exception as e:
            self.logger.error(f"SubtitleMergerService execution failed: {e}", exc_info=True)
            raise e

        # 4. 结果落盘
        output_filename = f"subtitle_merger_result_{task.id}.json"
        output_dir = settings.SHARED_TMP_ROOT / f"subtitle_merger_{task.id}_workspace"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / output_filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)

        try:
            rel_output_path = output_path.relative_to(settings.SHARED_ROOT)
        except ValueError:
            rel_output_path = output_path.name

        return {
            "message": "Subtitle merger completed.",
            "output_file_path": str(rel_output_path),
            "stats": result_data.get("stats"),
            "cost_usage": result_data.get("usage_report")
        }