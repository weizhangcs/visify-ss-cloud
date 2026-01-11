from task_manager.handlers.registry import HandlerRegistry
from ai_services.refinery.character_identifier.service import CharacterIdentifierService
from ai_services.schemas.refinery.character_identifier import CharacterIdentifierPayload
from .base import RefineryBaseHandler

@HandlerRegistry.register("REFINERY_CHARACTER_IDENTIFIER")
class RefineryCharacterIdentifierHandler(RefineryBaseHandler):
    """
    [Handler] [Refinery] 角色识别任务
    """
    config_name = "character_identifier"
    service_cls = CharacterIdentifierService
    payload_cls = CharacterIdentifierPayload