# task_manager/tasks.py
import logging
from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction

from core.exceptions import RateLimitException, BizException
from .models import Task
from .handlers import HandlerRegistry

# 获取 Celery 专用的 logger
logger = get_task_logger(__name__)


@shared_task(bind=True, max_retries=3)
def execute_cloud_native_task(self, task_id):
    """
    通用云端任务执行入口。
    支持队列感知与限流重试机制。
    """
    logger.info(f"Celery worker received task ID: {task_id}")

    try:
        # --- 阶段 1: 锁定任务并标记为运行中 (短事务) ---
        with transaction.atomic():
            # 使用 select_for_update 锁定行，防止竞态条件
            try:
                task = Task.objects.select_for_update().get(pk=task_id)
            except Task.DoesNotExist:
                logger.error(f"Task {task_id} not found.")
                return f"Task {task_id} not found"

            # 幂等性检查
            if task.status in [Task.TaskStatus.COMPLETED, Task.TaskStatus.FAILED]:
                logger.warning(f"Task {task_id} is already in {task.status} state. Skipping.")
                return f"Task {task_id} already processed"

            # FSM Transition: PENDING -> RUNNING
            task.start()
            task.save()

        logger.info(f"Task {task_id} state transitioned to RUNNING. Handing over to strategy...")

        # --- 阶段 2: 执行具体业务逻辑 (长耗时，无数据库锁) ---
        handler = HandlerRegistry.get_handler(task.task_type)
        result_data = handler.handle(task)

        # --- 阶段 3: 标记完成并保存结果 (短事务) ---
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_id)
            task.complete(result_data=result_data)
            task.save()

        logger.info(f"Task {task_id} ({task.task_type}) completed successfully.")
        return f"Task {task_id} success"

    except RateLimitException as e:
        retry_delay = 5 * (2 ** self.request.retries)
        logger.warning(f"⚠️ Rate limit hit: {e.detail}. Retrying in {retry_delay}s...")
        raise self.retry(exc=e, countdown=retry_delay)

    except BizException as e:
        logger.error(f"BizException executing Task {task_id}: {e.detail}")
        try:
            with transaction.atomic():
                task = Task.objects.get(pk=task_id)
                task.fail(
                    error_code=e.code,
                    error_message=str(e.detail),
                    error_details=e.data
                )
                task.save()
        except Exception:
            pass
        return f"Task {task_id} failed: {e.detail}"

    except Exception as e:
        error_str = str(e)
        logger.error(f"Error executing Task {task_id}: {error_str}", exc_info=True)
        try:
            with transaction.atomic():
                task = Task.objects.get(pk=task_id)
                task.fail(
                    error_code="INTERNAL_ERROR",
                    error_message=error_str,
                    error_details={"exception": type(e).__name__}
                )
                task.save()
        except Exception:
            pass
        return f"Task {task_id} failed: {error_str}"