# task_manager/signals.py
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Task
from .tasks import execute_cloud_native_task
from .definitions import TASK_CONFIGS

# 自动生成路由映射表
QUEUE_ROUTING = {
    task_type: config.queue for task_type, config in TASK_CONFIGS.items()
}

@receiver(post_save, sender=Task)
def trigger_task_execution(sender, instance, created, **kwargs):
    """
    当一个新的 Task 实例的保存事务 *成功提交后*，触发异步任务。
    """
    if created:
        # 获取目标队列，如果未定义则回退到默认的 'celery' 队列
        target_queue = QUEUE_ROUTING.get(instance.task_type, 'celery')

        # 确保只有在 Task 记录确实已经存在于数据库中之后，Celery 任务才会被发送到队列里。
        transaction.on_commit(
            lambda: execute_cloud_native_task.apply_async(
                args=[instance.id],
                queue=target_queue
            )
        )