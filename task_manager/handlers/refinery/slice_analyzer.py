from task_manager.handlers.registry import HandlerRegistry
from ai_services.refinery.slice_analyzer.service import SliceAnalyzerService
from ai_services.schemas.refinery.slice_analyzer import SliceAnalyzerPayload
from .base import RefineryBaseHandler

@HandlerRegistry.register("REFINERY_SLICE_ANALYZER")
class RefinerySliceAnalyzerHandler(RefineryBaseHandler):
    """
    [Handler] [Refinery] 切片语义分析任务
    """
    config_name = "slice_analyzer"
    service_cls = SliceAnalyzerService
    payload_cls = SliceAnalyzerPayload