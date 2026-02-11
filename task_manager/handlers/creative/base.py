# 复用 RefineryBaseHandler，因为逻辑完全一致
from task_manager.handlers.refinery.base import RefineryBaseHandler

class CreativeBaseHandler(RefineryBaseHandler):
    """
    Creative 模块的通用处理器基类。
    目前逻辑与 Refinery 一致，未来可扩展 Creative 特有的逻辑（如 Veo3 集成）。
    """
    pass