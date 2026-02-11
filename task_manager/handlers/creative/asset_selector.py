from task_manager.handlers.registry import HandlerRegistry
from ai_services.creative.asset_selector.service import AssetSelectorService
from ai_services.schemas.creative.asset_selector import AssetSelectorPayload
from .base import CreativeBaseHandler

@HandlerRegistry.register("CREATIVE_ASSET_SELECTOR")
class CreativeAssetSelectorHandler(CreativeBaseHandler):
    """
    [Handler] [Creative] 素材选择任务
    """
    config_name = "asset_selector"
    service_cls = AssetSelectorService
    payload_cls = AssetSelectorPayload