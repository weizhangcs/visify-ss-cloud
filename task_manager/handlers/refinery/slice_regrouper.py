from task_manager.handlers.registry import HandlerRegistry
from ai_services.refinery.slice_regrouper.service import SliceRegrouperService
from ai_services.schemas.refinery.slice_regrouper import SliceRegrouperPayload
from .base import RefineryBaseHandler

@HandlerRegistry.register("REFINERY_SLICE_REGROUPER")
class RefinerySliceRegrouperHandler(RefineryBaseHandler):
    """
    [Handler] [Refinery] 场景聚类任务
    """
    config_name = "slice_regrouper"
    service_cls = SliceRegrouperService
    payload_cls = SliceRegrouperPayload