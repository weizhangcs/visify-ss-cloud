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
from .refinery import visual_analyzer
from .refinery import slice_regrouper
from .refinery import character_identifier
from .refinery import subtitle_merger