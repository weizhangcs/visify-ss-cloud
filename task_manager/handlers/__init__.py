# task_manager/handlers/__init__.py
from .base import BaseTaskHandler
from .registry import HandlerRegistry
from . import refinery  # [旁路重构] 导入新的 refinery 包

# 导入所有 Handler 模块以触发装饰器注册
from . import rag
from . import narration
from . import character
from . import editing
from . import dubbing
from . import localization
from . import subtitle_context
from . import character_pre_annotator
from . import scene_pre_annotator
from . import visual_analyzer
from . import subtitle_merger
from . import slice_regrouper