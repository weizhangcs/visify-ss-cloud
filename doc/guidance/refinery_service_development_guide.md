# Refinery 原子服务开发范式指南

> **版本**: v1.0
> **基准范例**: `subtitle_merger`
> **适用范围**: `ai_services/refinery/` 下的所有原子化 AI 服务

## 1. 核心架构原则

我们在重构 `subtitle_merger` 时确立了以下核心原则，后续所有 Refinery 服务开发均需遵循：

1.  **配置驱动 (Configuration-Driven)**
    *   **原则**: 生产环境下的技术参数（Model, Temperature, Batch Size）必须由服务端统一配置 (`ai_inference_config.yaml`) 管理。
    *   **目的**: 避免客户端硬编码参数，实现服务端热更新和统一调优。

2.  **关注点分离 (Separation of Concerns)**
    *   **Handler**: 负责调度。加载配置、校验 Payload、初始化基础设施 (Logger, CostCalculator)、处理租户隔离。**不包含 AI 业务逻辑**。
    *   **Service**: 负责业务。接收纯净的数据和配置，执行预处理、LLM 交互、后处理。**不关心 HTTP/Celery 上下文**。

3.  **双模式运行 (Dual-Mode Operation)**
    *   **PROD (默认)**: 严格模式。忽略 Payload 中的技术参数，强制使用服务端配置。日志精简。
    *   **DEBUG**: 调试模式。允许 Payload 通过 `service_params` 覆盖技术参数。记录全量 Prompt/Response 日志到独立目录。

4.  **指令生成模式 (Instruction-Based)**
    *   **原则**: 对于数据转换类任务，LLM 仅返回轻量的“操作指令”（如索引列表），由 Python 代码执行具体的数据重构。
    *   **目的**: 节省 Token，规避长文本截断，确保时间戳等关键数据的精确性。

5.  **表现与逻辑分离 (Jinja2 Prompts)**
    *   **原则**: 禁止在 Python 代码中拼接 Prompt 字符串。所有提示词逻辑移入 `.j2` 模板。
    *   **目的**: 提高可维护性，支持多语言模板回退机制。

---

## 2. 标准目录结构

以 `subtitle_merger` 为例，一个标准的原子服务应包含以下文件：

```text
ai_services/
├── schemas/
│   └── refinery/
│       └── subtitle_merger.py      # [公共契约] 对外暴露的 Payload/Response 定义
├── refinery/
│   └── subtitle_merger/            # [服务包]
│       ├── __init__.py
│       ├── service.py              # [核心逻辑] 业务实现
│       ├── schemas.py              # [私有模型] 仅内部使用的 LLM 交互 Schema (Instruction)
│       └── prompts/                # [提示词]
│           ├── subtitle_merge_generic.j2  # 通用/英文模板
│           └── subtitle_merge_zh.j2       # 特定语言特调模板
└── configs/
    └── ai_inference_config.yaml    # [统一配置]

task_manager/
└── handlers/
    └── refinery/
        └── subtitle_merger.py      # [调度器] 任务入口 Handler
```

---

## 3. 开发步骤详解

### 步骤 1: 定义数据契约 (Schemas)

**A. 公共契约 (`ai_services/schemas/refinery/xxx.py`)**
定义输入 (`Payload`) 和输出 (`Response`)。
*   必须包含 `mode` (PROD/DEBUG) 和 `service_params` 字段。
*   使用 `pydantic` 进行严格校验。

**B. 私有模型 (`ai_services/refinery/xxx/schemas.py`)**
定义 LLM 的结构化输出（`response_schema`）。
*   例如：`MergePlanResponse`，仅在 Service 内部与 LLM 交互时使用。

### 步骤 2: 编写提示词模板 (Prompts)

在 `ai_services/refinery/xxx/prompts/` 下创建 Jinja2 模板。

*   **通用模板 (`_generic.j2`)**: 使用英语编写指令，通过 `{{ language_name }}` 变量适配不同数据语言。
*   **特调模板 (`_zh.j2`)**: 针对特定语言优化（可选）。
*   **数据注入**: 使用 `{% for item in items %}` 循环渲染数据，避免 Python 侧字符串拼接。

### 步骤 3: 实现 Service 逻辑

继承 `AIServiceMixin`，实现 `execute` 方法。

**关键模式代码**:

```python
class MyService(AIServiceMixin):
    def execute(self, payload: Dict, config: Dict = None):
        # 1. 加载配置 (优先级: Payload(Debug) > Config > Default)
        if config is None: config = {}
        model_name = config.get("default_model", self.DEFAULT_MODEL)
        
        if payload.mode == "DEBUG" and payload.service_params:
             # 应用覆盖逻辑...
             pass

        # 2. 预处理数据 (转为 List[Dict] 供 Jinja2 使用)
        processed_data = self._preprocess(data)

        # 3. 渲染 Prompt (使用 PromptManager)
        # 自动回退逻辑: zh -> generic
        template_name = f"my_task_{lang}.j2"
        if not (self.prompts_dir / template_name).exists():
            template_name = "my_task_generic.j2"
        prompt = self.prompt_manager.render(template_name, context)

        # 4. 调用 LLM (GeminiProcessor)
        # 务必传入 response_schema
        response, usage = self.gemini_processor.generate_content(
            model_name=model_name,
            prompt=prompt,
            response_schema=MyInternalSchema
        )

        # 5. 后处理 & 成本计算
        # ...
```

### 步骤 4: 实现 Handler 调度

继承 `BaseTaskHandler`，注册 TaskType。

**关键职责**:
1.  **加载配置**: 使用 `AIConfigLoader().get_config("service_name")`。
2.  **初始化基础设施**:
    *   `GeminiProcessor`: 传入 `debug_mode=is_debug`。
    *   `debug_dir`: 仅在 DEBUG 模式下创建。
3.  **租户隔离**:
    *   输出路径应包含 `org_id` (Organization UUID)。
    *   路径示例: `shared_tmp/{org_id}/{task_type}_{task_id}_workspace/`。

### 步骤 5: 注册与配置

关于任务在 `task_manager` 中的完整注册流程（Model, Schema, Handler Registry, Signals, API），请严格遵循现有文档：
👉 **添加新任务开发范式**

在此基础上，Refinery 服务还需要额外配置：
1.  **AI Config**: 在 `ai_services/configs/ai_inference_config.yaml` 中添加该服务的默认推理参数。

---

## 4. 最佳实践 Checklist

- [ ] **Schema 分离**: 确认没有将内部 LLM 的 Schema 暴露在公共 API 中。
- [ ] **Prompt 渲染**: 确认 Python 代码中没有 `f-string` 拼接 Prompt，全部使用 Jinja2。
- [ ] **Debug 模式**: 确认在 DEBUG 模式下，`GeminiProcessor` 能记录全量 Prompt 和 Response。
- [ ] **Prod 模式**: 确认在 PROD 模式下，日志精简，且不允许 Payload 覆盖模型参数。
- [ ] **租户隔离**: 确认落盘文件路径使用了 `org_id`，而不是 `edge_id` 或全局路径。
- [ ] **多语言支持**: 确认至少有一个 `_generic.j2` 模板作为兜底。

---

## 5. 常见代码片段 (Snippets)

### Config Loader (Handler 中使用)
```python
from ai_services.utils.config_loader import AIConfigLoader

# 获取配置
service_config = AIConfigLoader().get_config("my_service_name")
```

### Prompt Manager (Service 中使用)
```python
from ai_services.utils.prompt_manager import PromptManager

self.prompt_manager = PromptManager(self.prompts_dir)
prompt = self.prompt_manager.render("template.j2", {"data": ...})
```

### 租户路径构建 (Handler 中使用)
```python
org_id = str(task.organization.org_id) if task.organization else "unknown_org"
output_dir = settings.SHARED_TMP_ROOT / org_id / f"my_task_{task.id}_workspace"
```