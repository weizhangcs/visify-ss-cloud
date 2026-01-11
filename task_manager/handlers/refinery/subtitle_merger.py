from task_manager.handlers.registry import HandlerRegistry
from ai_services.refinery.subtitle_merger.service import SubtitleMergerService
from ai_services.schemas.refinery.subtitle_merger import SubtitleMergerPayload
from .base import RefineryBaseHandler

@HandlerRegistry.register("REFINERY_SUBTITLE_MERGER")
class RefinerySubtitleMergerHandler(RefineryBaseHandler):
    """
    [Handler] [Refinery] 字幕语义合并任务
    """
    config_name = "subtitle_merger"
    service_cls = SubtitleMergerService
    payload_cls = SubtitleMergerPayload