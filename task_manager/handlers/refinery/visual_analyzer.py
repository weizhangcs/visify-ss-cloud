from task_manager.handlers.registry import HandlerRegistry
from ai_services.ai_platform.llm.vertex_processor import VertexProcessor
from ai_services.refinery.visual_analyzer.service import VisualAnalyzerService
from ai_services.schemas.refinery.visual_analyzer import VisualAnalyzerPayload
from .base import RefineryBaseHandler

@HandlerRegistry.register("REFINERY_VISUAL_ANALYZER")
class RefineryVisualAnalyzerHandler(RefineryBaseHandler):
    """
    [Handler] [Refinery] 视觉分析任务
    """
    config_name = "visual_analyzer"
    service_cls = VisualAnalyzerService
    payload_cls = VisualAnalyzerPayload
    processor_cls = VertexProcessor

    def _get_service_init_kwargs(self, processor, cost_calculator):
        return {
            "vertex_processor": processor,
            "cost_calculator": cost_calculator
        }