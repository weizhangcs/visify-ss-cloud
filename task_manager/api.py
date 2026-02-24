# task_manager/api.py
import uuid
from typing import Dict, Any

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.urls import reverse
from ninja import Router
from ninja.errors import HttpError

from .models import Task
from core.auth import EdgeAuth
from .schemas import TaskCreateRequest, TaskResponse
from .definitions import TASK_CONFIGS

router = Router(auth=EdgeAuth())


@router.post("/", response={202: Dict[str, Any], 400: Dict[str, Any]})
def create_task(request, data: TaskCreateRequest):
    """
    创建云原生任务
    """
    edge_instance = request.auth
    task_payload = data.payload

    # --- 1. 路径自动补全与校验 ---
    absolute_paths_to_add = {}

    for key, value in task_payload.items():
        if key.endswith("_path"):
            if not isinstance(value, str):
                raise HttpError(400, f"Path param '{key}' must be a string.")

            # 跳过云存储/网络路径的本地校验
            if value.startswith(("gs://", "http://", "https://", "s3://")):
                continue

            relative_path = value
            absolute_input_path = settings.SHARED_ROOT / relative_path

            if not absolute_input_path.is_file():
                raise HttpError(400, f"Input file not found at: {relative_path}")

            absolute_paths_to_add[f'absolute_{key}'] = str(absolute_input_path)

    task_payload.update(absolute_paths_to_add)

    # --- 2. 输出路径生成 ---
    task_config = TASK_CONFIGS.get(data.task_type)
    output_prefix = task_config.output_prefix if task_config else None

    if output_prefix:
        output_filename = f"{output_prefix}_{uuid.uuid4()}.json"
        absolute_output_path = settings.SHARED_TMP_ROOT / output_filename
        task_payload['absolute_output_path'] = str(absolute_output_path)

    # --- 3. 任务创建 ---
    try:
        task = Task.objects.create(
            organization=edge_instance.organization,
            assigned_edge=edge_instance,
            task_type=data.task_type,
            payload=task_payload,
            status=Task.TaskStatus.PENDING
        )
    except Exception as e:
        raise HttpError(500, f"Task creation failed: {str(e)}")

    return 202, {
        "id": task.id,
        "status": task.status,
        "message": "Task accepted for processing."
    }


@router.get("/{task_id}", response=TaskResponse)
def get_task_detail(request, task_id: int):
    """
    查询任务详情
    """
    edge_instance = request.auth

    # 确保只能查自己组织的任务
    task = get_object_or_404(
        Task,
        pk=task_id,
        organization=edge_instance.organization
    )

    # 计算 download_url
    download_url = None
    if task.status == Task.TaskStatus.COMPLETED and task.result and task.result.get("output_file_path"):
        path = reverse('vss_api:task_download', kwargs={'task_id': task.id})
        download_url = request.build_absolute_uri(path)

    return TaskResponse(
        id=task.id,
        status=task.status,
        task_type=task.task_type,
        result=task.result,
        error=task.error,
        created=task.created,
        modified=task.modified,
        download_url=download_url
    )