import json
from pathlib import Path
import yaml
from django.conf import settings

from task_manager.models import Task
from task_manager.handlers.base import BaseTaskHandler
from task_manager.handlers.registry import HandlerRegistry

from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator

from ai_services.refinery.subtitle_merger.service import SubtitleMergerService
from ai_services.refinery.subtitle_merger.schemas import SubtitleMergerPayload

from core.exceptions import BizException
from core.error_codes import ErrorCode

# [核心修改] 注册一个新的 TaskType，或者复用旧的
# 为了清晰，我们假设会创建一个新的 TaskType: REFINERY_SUBTITLE_MERGER
# 如果你希望复用，可以将这里的 TaskType 改回 SUBTITLE_MERGER
@HandlerRegistry.register("REFINERY_SUBTITLE_MERGER")
class RefinerySubtitleMergerHandler(BaseTaskHandler):
    """
    [Handler] [Refinery] 字幕语义合并任务
    """

    def handle(self, task: Task) -> dict:
        self.logger.info(f"🚀 Starting REFINERY_SUBTITLE_MERGER Task: {task.id}")

        # [架构升级] 加载服务配置
        try:
            config_path = Path(settings.BASE_DIR) / "ai_services" / "configs" / "ai_inference_config.yaml"
            with open(config_path, encoding='utf-8') as f:
                service_configs = yaml.safe_load(f)

            subtitle_merger_config = service_configs.get("subtitle_merger", {})
        except Exception as e:
            raise BizException(ErrorCode.LLM_INFERENCE_ERROR, f"Failed to load service config: {e}")

        # 1. 基础设施
        debug_dir = settings.SHARED_LOG_ROOT / f"refinery_subtitle_merger_{task.id}_debug"
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
            result_data = service.execute(task.payload, config=subtitle_merger_config)
        except Exception as e:
            self.logger.error(f"RefinerySubtitleMergerService execution failed: {e}", exc_info=True)
            raise e

        # 4. 结果落盘
        output_filename = f"refinery_subtitle_merger_result_{task.id}.json"
        output_dir = settings.SHARED_TMP_ROOT / f"refinery_subtitle_merger_{task.id}_workspace"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / output_filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)

        try:
            rel_output_path = output_path.relative_to(settings.SHARED_ROOT)
        except ValueError:
            rel_output_path = output_path.name

        return {
            "message": "Refinery subtitle merger completed.",
            "output_file_path": str(rel_output_path),
            "stats": result_data.get("stats"),
            "cost_usage": result_data.get("usage_report")
        }