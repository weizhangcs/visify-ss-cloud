from task_manager.handlers.registry import HandlerRegistry
from ai_services.creative.editing_director.service import EditingDirectorService
from ai_services.schemas.creative.editing_director import EditingDirectorPayload
from .base import CreativeBaseHandler

@HandlerRegistry.register("CREATIVE_EDITING_DIRECTOR")
class CreativeEditingDirectorHandler(CreativeBaseHandler):
    """
    [Handler] [Creative] 剪辑决策任务
    """
    config_name = "editing_director"
    service_cls = EditingDirectorService
    payload_cls = EditingDirectorPayload

    # 覆盖初始化方法，因为 EditingDirectorService 不需要 Processor 和 CostCalculator
    # 但为了简单，我们在 Service __init__ 里接收但不使用，或者在这里适配
    def _get_service_init_kwargs(self, processor, cost_calculator):
        # EditingDirectorService 目前只需要 logger
        # 我们在 Service __init__ 中只定义了 logger 和 **kwargs
        return {}