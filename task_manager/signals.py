# task_manager/signals.py
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Task
from .tasks import execute_cloud_native_task
from .definitions import TASK_CONFIGS

# --- [Refactor] 1. 自动生成路由映射表 ---
QUEUE_ROUTING = {
    task_type: config.queue for task_type, config in TASK_CONFIGS.items()
}

@receiver(post_save, sender=Task)
def trigger_task_execution(sender, instance, created, **kwargs):
    """
    当一个新的 Task 实例的保存事务 *成功提交后*，触发异步任务。
    """
    if created:
        # 我们只处理定义的云原生任务类型
        # 如果是 Edge 端执行的任务 (如 RUN_DUBBING)，这里通常不处理，或者分发给 Edge 队列(未来实现)

        # 获取目标队列，如果未定义则回退到默认的 'celery' 队列
        target_queue = QUEUE_ROUTING.get(instance.task_type, 'celery')

        # [日志] 方便调试路由逻辑 (生产环境可调整日志级别)
        # print(f"New cloud-native task saved (ID: {instance.id}). Scheduling to queue: {target_queue}")

        # 2. 将 .apply_async() 调用包裹在 transaction.on_commit 中
        # 这确保了只有在 Task 记录确实已经存在于数据库中之后，
        # Celery 任务才会被发送到队列里。
        transaction.on_commit(
            lambda: execute_cloud_native_task.apply_async(
                args=[instance.id],
                queue=target_queue  # <--- [核心修改] 指定物理队列
            )
        )