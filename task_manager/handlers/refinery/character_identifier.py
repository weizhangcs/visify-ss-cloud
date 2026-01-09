import json
from pathlib import Path
from django.conf import settings

from task_manager.models import Task
from task_manager.handlers.base import BaseTaskHandler
from task_manager.handlers.registry import HandlerRegistry

from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator

from ai_services.refinery.character_identifier.service import CharacterIdentifierService
from ai_services.schemas.refinery.character_identifier import CharacterIdentifierPayload
from ai_services.utils.config_loader import AIConfigLoader

from core.exceptions import BizException
from core.error_codes import ErrorCode

@HandlerRegistry.register("REFINERY_CHARACTER_IDENTIFIER")
class RefineryCharacterIdentifierHandler(BaseTaskHandler):
    """
    [Handler] [Refinery] 角色识别任务
    """

    def handle(self, task: Task) -> dict:
        self.logger.info(f"🚀 Starting REFINERY_CHARACTER_IDENTIFIER Task: {task.id}")

        # 0. 加载配置
        service_config = AIConfigLoader().get_config("character_identifier")
        
        mode = task.payload.get("mode", "PROD")
        is_debug = (mode == "DEBUG")

        # 1. 基础设施
        debug_dir = None
        if is_debug:
            debug_dir = settings.SHARED_LOG_ROOT / f"refinery_char_id_{task.id}_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)

        gemini_processor = GeminiProcessor(
            api_key=settings.GOOGLE_API_KEY,
            logger=self.logger,
            debug_mode=is_debug,
            debug_dir=debug_dir
        )

        cost_calculator = CostCalculator(
            pricing_data=settings.GEMINI_PRICING,
            usd_to_rmb_rate=settings.USD_TO_RMB_EXCHANGE_RATE
        )

        service = CharacterIdentifierService(
            logger=self.logger,
            gemini_processor=gemini_processor,
            cost_calculator=cost_calculator
        )

        # 2. Payload 校验
        try:
            CharacterIdentifierPayload(**task.payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Invalid Payload: {e}")

        # 3. 执行
        result_data = service.execute(task.payload, config=service_config)

        # 4. 结果落盘
        org_id = str(task.organization.org_id) if task.organization else "unknown_org"
        output_filename = f"refinery_char_id_result_{task.id}.json"
        output_dir = settings.SHARED_TMP_ROOT / org_id / f"refinery_char_id_{task.id}_workspace"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / output_filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)

        try:
            rel_output_path = output_path.relative_to(settings.SHARED_ROOT)
        except ValueError:
            rel_output_path = output_path.name

        return {
            "message": "Refinery character identifier completed.",
            "output_file_path": str(rel_output_path),
            "stats": result_data.get("stats"),
            "cost_usage": result_data.get("usage_report")
        }