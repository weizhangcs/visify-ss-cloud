from task_manager.handlers.registry import HandlerRegistry
from ai_services.refinery.dubbing_script_refiner.service import DubbingScriptRefinerService
from ai_services.schemas.refinery.dubbing_script_refiner import DubbingScriptRefinerPayload
from .base import RefineryBaseHandler

@HandlerRegistry.register("REFINERY_DUBBING_SCRIPT_REFINER")
class RefineryDubbingScriptRefinerHandler(RefineryBaseHandler):
    """
    [Handler] [Refinery] 剧本精修任务
    负责将 Task 调度给 DubbingScriptRefinerService 执行。
    """
    config_name = "dubbing_script_refiner"  # 对应 ai_inference_config.yaml 中的 key
    service_cls = DubbingScriptRefinerService
    payload_cls = DubbingScriptRefinerPayload