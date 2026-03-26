from task_manager.handlers.registry import HandlerRegistry
from ai_services.refinery.character_role_finalizer.service import CharacterRoleFinalizerService
from ai_services.schemas.refinery.character_role_finalizer import CharacterRoleFinalizerPayload
from .base import RefineryBaseHandler

@HandlerRegistry.register("REFINERY_CHARACTER_ROLE_FINALIZER")
class RefineryCharacterRoleFinalizerHandler(RefineryBaseHandler):
    """
    [Handler] [Refinery] 角色身份终结者
    负责执行 CharacterRoleFinalizerService。
    """
    config_name = "character_role_finalizer"
    service_cls = CharacterRoleFinalizerService
    payload_cls = CharacterRoleFinalizerPayload