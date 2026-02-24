# task_manager/models.py
import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from model_utils.models import TimeStampedModel
from django_fsm import FSMField, transition

from organization.models import Organization, EdgeInstance
from .definitions import TaskType


class Task(TimeStampedModel):
    """
    云端任务模型。
    """

    # 保持 Task.TaskType 的访问方式兼容性
    TaskType = TaskType

    class TaskStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        RUNNING = "RUNNING", _("Running")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name=_("Organization")
    )
    assigned_edge = models.ForeignKey(
        EdgeInstance,
        on_delete=models.SET_NULL,
        related_name="tasks",
        null=True,
        blank=True,
        verbose_name=_("Assigned Edge")
    )
    task_type = models.CharField(
        choices=TaskType.choices,
        max_length=100,
        verbose_name=_("Task Type"),
        db_index=True
    )
    status = FSMField(
        default=TaskStatus.PENDING,
        choices=TaskStatus.choices,
        max_length=10,
        verbose_name=_("Status")
    )

    # --- 核心数据 ---
    payload = models.JSONField(_("Payload"), default=dict, blank=True)
    result = models.JSONField(_("Result"), default=dict, blank=True, null=True)
    error = models.JSONField(_("Error"), default=dict, blank=True, null=True)
    logs = models.TextField(_("Logs"), blank=True, null=True)

    # --- 统计字段 ---
    started_at = models.DateTimeField(_("Started At"), null=True, blank=True)
    finished_at = models.DateTimeField(_("Finished At"), null=True, blank=True)
    duration = models.DurationField(_("Duration"), null=True, blank=True, help_text=_("Execution time."))

    class Meta:
        verbose_name = _("Task")
        verbose_name_plural = _("Tasks")
        ordering = ['-created']
        indexes = [
            models.Index(fields=['organization', '-created']),
            models.Index(fields=['status']),
            models.Index(fields=['created']),
        ]

    def __str__(self):
        return f"Task {self.id} ({self.task_type}) - {self.status}"

    def _calculate_duration(self):
        """辅助方法：计算耗时"""
        if self.started_at and self.finished_at:
            self.duration = self.finished_at - self.started_at

    # --- 状态机转换逻辑 ---

    @transition(field=status, source=TaskStatus.PENDING, target=TaskStatus.RUNNING)
    def start(self):
        self.started_at = timezone.now()

    @transition(field=status, source=TaskStatus.RUNNING, target=TaskStatus.COMPLETED)
    def complete(self, result_data):
        self.result = result_data
        self.finished_at = timezone.now()
        self._calculate_duration()

    @transition(field=status, source='*', target=TaskStatus.FAILED)
    def fail(self, error_code: str, error_message: str, error_details: dict = None):
        """
        任务失败处理
        :param error_code: 错误码 (e.g., "INTERNAL_ERROR", "TIMEOUT")
        :param error_message: 人类可读的错误描述
        :param error_details: 额外的上下文信息 (stack trace, etc.)
        """
        self.error = {
            "code": error_code,
            "message": error_message,
            "details": error_details or {}
        }
        self.finished_at = timezone.now()
        self._calculate_duration()