# VSS Cloud: 添加新任务开发范式 (Standard Guide)

本文档定义了在 VSS Cloud 中添加一个新的原子能力任务 (Atomic Capability Task) 的标准流程。
遵循此范式可确保任务从 API 接入、路由分发到最终执行的链路畅通。

假设我们要添加一个名为 `MY_NEW_TASK` 的任务。

---

## 1. 定义任务类型 (Models)

首先在数据库层面定义新的任务枚举。

**文件**: `task_manager/models.py`

```python
class Task(models.Model):
    class TaskType(models.TextChoices):
        # ... 现有任务 ...
        
        # [新增] 定义枚举值 (建议全大写)
        MY_NEW_TASK = 'MY_NEW_TASK', _('My New Task Description')
```

## 2. 开放 API 校验 (Schemas)

允许 API 接收这个新的 `task_type`。

**文件**: `task_manager/schemas.py`

```python
# 在 validate_task_type 方法或 allowed 列表中
allowed = [
    # ... 现有任务 ...
    
    # [新增] 允许该字符串通过 Pydantic 校验
    Task.TaskType.MY_NEW_TASK, 
    "MY_NEW_TASK" # 兼容字符串形式
]
```

## 3. 注册 Handler (Handlers)

这是核心执行逻辑。分为两步：编写 Handler 和 注册 Handler。

### 3.1 编写 Handler 文件

**文件**: `task_manager/handlers/my_new_task.py` (示例路径)

```python
from task_manager.handlers.registry import HandlerRegistry
from task_manager.handlers.base import BaseTaskHandler
from task_manager.models import Task

# [新增] 使用装饰器注册
@HandlerRegistry.register(Task.TaskType.MY_NEW_TASK)
class MyNewTaskHandler(BaseTaskHandler):
    def handle(self, task: Task) -> dict:
        self.logger.info(f"🚀 Starting MY_NEW_TASK: {task.id}")
        
        # ... 业务逻辑 ...
        
        return {"result": "success"}
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

## 4. 配置队列路由 (Signals)

决定这个任务由哪个 Celery Worker 队列处理（例如 `queue_gemini` 用于 AI 任务，`celery` 用于普通任务）。

**文件**: `task_manager/signals.py`

```python
QUEUE_ROUTING = {
    # ... 现有映射 ...
    
    # [新增] 指定队列
    Task.TaskType.MY_NEW_TASK: 'queue_gemini', 
}
```

## 5. 配置输出路径 (API)

决定任务创建时，`absolute_output_path` 的文件名前缀。

**文件**: `task_manager/api.py`

```python
# 在 create_task 函数中
    output_prefixes = {
        # ... 现有前缀 ...
        
        # [新增] 定义输出文件前缀 (e.g. my_result_uuid.json)
        Task.TaskType.MY_NEW_TASK.value: "my_result",
    }
```

---

## 总结检查清单 (Checklist)

- [ ] **Model**: Enum 添加了吗？
- [ ] **Schema**: API 允许这个 Enum 传参了吗？
- [ ] **Handler**: 代码写了吗？`__init__.py` 引入了吗？
- [ ] **Signal**: 队列路由配了吗？
- [ ] **API**: 输出文件前缀配了吗？