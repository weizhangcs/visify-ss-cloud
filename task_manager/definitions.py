from dataclasses import dataclass
from django.db import models
from django.utils.translation import gettext_lazy as _

class TaskType(models.TextChoices):
    # === 核心业务 ===
    DEPLOY_RAG_CORPUS = "DEPLOY_RAG_CORPUS", _("Deploy RAG Corpus")
    CHARACTER_IDENTIFIER = "CHARACTER_IDENTIFIER", _("Character Identifier")
    GENERATE_NARRATION = "GENERATE_NARRATION", _("Generate Narration")
    GENERATE_DUBBING = "GENERATE_DUBBING", _("Generate Dubbing")
    GENERATE_EDITING_SCRIPT = "GENERATE_EDITING_SCRIPT", _("Generate Editing Script")
    LOCALIZE_NARRATION = "LOCALIZE_NARRATION", _("Localize Narration")
    
    # === 旧版原子服务 (Biz Services) ===
    SUBTITLE_CONTEXT = 'SUBTITLE_CONTEXT', _('Subtitle Context Analysis')
    CHARACTER_PRE_ANNOTATOR = 'CHARACTER_PRE_ANNOTATOR', _('Character Pre-Annotator')
    SCENE_PRE_ANNOTATOR = 'SCENE_PRE_ANNOTATOR', _('Scene Pre-Annotator')
    VISUAL_ANALYZER = 'VISUAL_ANALYZER', _('Visual Analyzer')
    SUBTITLE_MERGER = 'SUBTITLE_MERGER', _('Subtitle Merger')
    SLICE_REGROUPER = 'SLICE_REGROUPER', _('Slice Regrouper')

    # === Refinery 原子服务 (New Architecture) ===
    REFINERY_SUBTITLE_MERGER = 'REFINERY_SUBTITLE_MERGER', _('[Refinery] Subtitle Merger')
    REFINERY_CHARACTER_IDENTIFIER = 'REFINERY_CHARACTER_IDENTIFIER', _('[Refinery] Character Identifier')
    REFINERY_VISUAL_ANALYZER = 'REFINERY_VISUAL_ANALYZER', _('[Refinery] Visual Analyzer')
    REFINERY_SLICE_REGROUPER = 'REFINERY_SLICE_REGROUPER', _('[Refinery] Slice Regrouper')

@dataclass
class TaskConfig:
    queue: str = 'queue_gemini'  # 默认队列
    output_prefix: str = None    # 输出文件前缀 (None 表示不自动生成)

# 任务配置注册表 (Single Source of Truth)
TASK_CONFIGS = {
    # A类: Gemini 密集型
    TaskType.GENERATE_NARRATION: TaskConfig(output_prefix="narration_script"),
    TaskType.LOCALIZE_NARRATION: TaskConfig(output_prefix="localized_script"),
    TaskType.CHARACTER_IDENTIFIER: TaskConfig(output_prefix="character_facts"),
    TaskType.GENERATE_EDITING_SCRIPT: TaskConfig(output_prefix="editing_script"),
    TaskType.SUBTITLE_CONTEXT: TaskConfig(),
    TaskType.VISUAL_ANALYZER: TaskConfig(output_prefix="visual_analysis"),
    TaskType.SUBTITLE_MERGER: TaskConfig(output_prefix="subtitle_merger"),
    TaskType.SLICE_REGROUPER: TaskConfig(output_prefix="scene_regrouping"),
    
    # Refinery
    # [Optimization] Refinery 任务由 Handler 内部统一管理租户隔离路径 (org_id/workspace)，
    # 无需 API 层预生成扁平的 output_path，保持 Payload 纯净。
    TaskType.REFINERY_SUBTITLE_MERGER: TaskConfig(),
    TaskType.REFINERY_CHARACTER_IDENTIFIER: TaskConfig(),
    TaskType.REFINERY_VISUAL_ANALYZER: TaskConfig(),
    TaskType.REFINERY_SLICE_REGROUPER: TaskConfig(),
    
    # 旧版服务 (部分无 output_prefix)
    TaskType.CHARACTER_PRE_ANNOTATOR: TaskConfig(),
    TaskType.SCENE_PRE_ANNOTATOR: TaskConfig(),

    # B类: 音频密集型
    TaskType.GENERATE_DUBBING: TaskConfig(queue='queue_audio', output_prefix="dubbing_script"),

    # C类: IO 密集型
    TaskType.DEPLOY_RAG_CORPUS: TaskConfig(queue='queue_io', output_prefix="rag_deployment_report"),
}