import json
from pathlib import Path
from django.conf import settings
from task_manager.handlers.base import BaseTaskHandler
from ai_services.utils.config_loader import AIConfigLoader
from ai_services.ai_platform.llm.gemini_processor import GeminiProcessor
from ai_services.ai_platform.llm.cost_calculator import CostCalculator
from core.exceptions import BizException
from core.error_codes import ErrorCode

class RefineryBaseHandler(BaseTaskHandler):
    """
    Refinery 原子服务的通用处理器基类。
    封装了配置加载、基础设施初始化、Payload校验、执行和结果落盘的标准流程。
    """
    # 子类必须定义的属性
    config_name: str = None          # e.g., "subtitle_merger" (对应 ai_inference_config.yaml 中的 key)
    service_cls: type = None         # e.g., SubtitleMergerService
    payload_cls: type = None         # e.g., SubtitleMergerPayload
    
    # 可选覆盖
    processor_cls: type = GeminiProcessor # 默认为 Gemini，VisualAnalyzer 可覆盖为 VertexProcessor

    def handle(self, task):
        self.logger.info(f"🚀 Starting {self.config_name.upper()} Task: {task.id}")

        # 1. 加载配置
        service_config = AIConfigLoader().get_config(self.config_name)
        
        # 2. 解析模式
        mode = task.payload.get("mode", "PROD")
        is_debug = (mode == "DEBUG")
        
        # 3. 基础设施
        debug_dir = None
        if is_debug:
            debug_dir = settings.SHARED_LOG_ROOT / f"refinery_{self.config_name}_{task.id}_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)

        # 准备 Processor 参数
        processor_kwargs = {
            "logger": self.logger,
            "debug_mode": is_debug,
            "debug_dir": debug_dir
        }
        
        # 适配 VertexProcessor (需要 project/location) 与 GeminiProcessor (需要 api_key)
        if self.processor_cls.__name__ == "VertexProcessor":
             processor_kwargs.update({
                 "project": settings.GOOGLE_CLOUD_PROJECT,
                 "location": settings.GOOGLE_CLOUD_LOCATION
             })
        else:
             processor_kwargs["api_key"] = settings.GOOGLE_API_KEY

        processor = self.processor_cls(**processor_kwargs)

        cost_calculator = CostCalculator(
            pricing_data=settings.GEMINI_PRICING,
            usd_to_rmb_rate=settings.USD_TO_RMB_EXCHANGE_RATE
        )

        # 4. 初始化 Service
        service = self.service_cls(
            logger=self.logger,
            **self._get_service_init_kwargs(processor, cost_calculator)
        )

        # 5. Payload 校验
        try:
            self.payload_cls(**task.payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Invalid Payload: {e}")

        # 6. 执行
        result_data = service.execute(task.payload, config=service_config)

        # 7. 落盘
        org_id = str(task.organization.org_id) if task.organization else "unknown_org"
        # 统一命名规范: refinery_{config_name}_result_{task_id}.json
        output_filename = f"refinery_{self.config_name}_result_{task.id}.json"
        output_dir = settings.SHARED_TMP_ROOT / org_id / f"refinery_{self.config_name}_{task.id}_workspace"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / output_filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)

        try:
            rel_output_path = output_path.relative_to(settings.SHARED_ROOT)
        except ValueError:
            rel_output_path = output_path.name

        return {
            "message": f"Refinery {self.config_name} completed.",
            "output_file_path": str(rel_output_path),
            "stats": result_data.get("stats"),
            "cost_usage": result_data.get("usage_report")
        }

    def _get_service_init_kwargs(self, processor, cost_calculator):
        """子类可重写此方法以适配不同的 Service 构造函数参数名"""
        return {
            "gemini_processor": processor,
            "cost_calculator": cost_calculator
        }