# VSS Cloud: 添加新任务开发范式 (Standard Guide)

本文档定义了在 VSS Cloud 中添加一个新的原子能力任务 (Atomic Capability Task) 的标准流程。
遵循此范式可确保任务从 API 接入、路由分发到最终执行的链路畅通。

假设我们要添加一个名为 `MY_NEW_TASK` 的任务。

---

## 1. 定义任务类型与配置 (Definitions)

这是任务定义的 **Single Source of Truth**。

**文件**: `task_manager/definitions.py`

```python
class TaskType(models.TextChoices):
    # ... 现有任务 ...
    
    # [新增] 定义枚举值 (建议全大写)
    MY_NEW_TASK = 'MY_NEW_TASK', _('My New Task Description')

# ...

# 任务配置注册表
TASK_CONFIGS = {
    # ... 现有配置 ...
    
    # [新增] 配置队列和输出前缀
    # queue: 指定 Celery 队列 (e.g., 'queue-gemini', 'queue-io', 'queue-audio')
    # output_prefix: 指定输出文件前缀 (e.g., 'my_result')，若不需要自动生成输出路径可设为 None
    TaskType.MY_NEW_TASK: TaskConfig(queue='queue-gemini', output_prefix="my_result"),
}
```

> **注意**: `task_manager/models.py` 会自动引用这里的 `TaskType`，无需手动修改 Model 定义。
> **注意**: `task_manager/signals.py` 和 `task_manager/api.py` 会自动读取 `TASK_CONFIGS` 来配置路由和输出路径。

## 2. 开放 API 校验 (Schemas)

允许 API 接收这个新的 `task_type`。

**文件**: `task_manager/schemas.py`

```python
# 在 validate_task_type 方法中
# 代码会自动读取 Task.TaskType.values，通常无需修改代码，
# 除非你有特殊的白名单逻辑。
```

## 3. 注册 Handler (Handlers)

这是核心执行逻辑。分为两步：编写 Handler 和 注册 Handler。

### 3.1 编写 Handler 文件

**文件**: `task_manager/handlers/my_new_task.py` (示例路径)

```python
from task_manager.handlers.registry import HandlerRegistry
from task_manager.handlers.base import BaseTaskHandler
from task_manager.models import Task
from core.exceptions import BizException # 推荐使用 BizException 抛出业务错误

# [新增] 使用装饰器注册
@HandlerRegistry.register(Task.TaskType.MY_NEW_TASK)
class MyNewTaskHandler(BaseTaskHandler):
    def handle(self, task: Task) -> dict:
        self.logger.info(f"🚀 Starting MY_NEW_TASK: {task.id}")
        
        # ... 业务逻辑 ...
        # 1. 解析 Payload
        # 2. 执行业务
        # 3. 结果落盘
        
        return {"result": "success", "output_file_path": "..."}
```

### 3.2 确保 Handler 被加载

**文件**: `task_manager/handlers/__init__.py`

```python
# ... 现有引用 ...

# [新增] 显式导入模块，触发 @register 装饰器执行
from . import my_new_task 
# 或者如果是在子包中
# from .refinery import my_new_task
```

---

## 总结检查清单 (Checklist)

- [ ] **Definitions**: `TaskType` 枚举添加了吗？`TASK_CONFIGS` 配置了吗？
- [ ] **Handler**: 代码写了吗？`__init__.py` 引入了吗？
- [ ] **Migration**: 如果修改了 `models.py` (通常不需要)，运行迁移了吗？

> **提示**: 现在的架构通过 `definitions.py` 实现了配置驱动，大大简化了 `signals.py` (路由) 和 `api.py` (输出路径) 的修改成本。