# Subtitle Merger Service (Refinery)

## 1. 服务简介

**Subtitle Merger** 是 `Refinery`（精炼）模块下的核心原子服务。它利用大语言模型（LLM）的语义理解能力，将碎片化的原始字幕行（通常由 ASR 自动生成）智能合并为语义完整、标点正确、符合阅读习惯的句子。

### 核心特性
- **指令生成模式 (Instruction-Based)**: LLM 仅负责生成合并计划（Merge Plan），具体的文本重构和时间轴计算在本地代码执行。这确保了时间戳的精确性并大幅降低了 Token 消耗。
- **配置驱动 (Configuration-Driven)**: 生产环境下的技术参数（模型版本、Batch Size 等）由服务端统一配置管理，客户端无需关心。
- **双模式运行 (Dual-Mode)**: 支持 `PROD`（生产）和 `DEBUG`（调试）两种模式，兼顾稳定性和开发灵活性。

---

## 2. 任务定义

- **Task Type**: `REFINERY_SUBTITLE_MERGER`
- **Handler**: `RefinerySubtitleMergerHandler`
- **Service**: `SubtitleMergerService`

---

## 3. 请求载荷 (Payload)

创建任务时，`payload` 字段应符合以下 Schema。

### 3.1 字段说明

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `lang` | string | 否 | `"zh"` | 字幕语言代码。支持 `zh`, `en`, `ja`, `ko`, `es`, `fr`, `de` 等。系统会自动加载对应语言或通用的提示词模板。 |
| `mode` | string | 否 | `"PROD"` | 运行模式。<br>- `PROD`: 严格模式，忽略 `service_params`，使用服务端配置。<br>- `DEBUG`: 调试模式，允许通过 `service_params` 覆盖参数，并输出详细调试日志。 |
| `subtitle_file_path` | string | 否* | `null` | 原始字幕文件在共享存储中的相对路径（推荐生产环境使用）。 |
| `subtitles` | list | 否* | `null` | 直接传入的字幕对象列表（推荐调试环境使用）。 |
| `service_params` | object | 否 | `null` | **仅 DEBUG 模式有效**。用于覆盖服务端默认的技术参数。 |

> **注意**: `subtitle_file_path` 和 `subtitles` 必须至少提供其中一个。如果两者都提供，优先使用 `subtitles`。

### 3.2 数据结构详情

#### SubtitleItem (字幕对象)
```json
{
  "index": 1,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "start_time": 10.5,
  "end_time": 12.0,
  "content": "原始字幕文本"
}
```

#### ServiceParams (调试参数)
仅当 `mode="DEBUG"` 时生效。
```json
{
  "model": "gemini-2.5-pro",
  "batch_size": 100,
  "temperature": 0.5,
  "max_retries": 1
}
```

---

## 4. 响应结果 (Result)

任务执行成功后，`task.result` 将包含执行摘要，详细的合并结果将写入共享存储中的 JSON 文件。

### 4.1 API 响应结构

```json
{
  "message": "Refinery subtitle merger completed.",
  "output_file_path": "shared_tmp/org_uuid/refinery_subtitle_merger_123_workspace/refinery_subtitle_merger_result_123.json",
  "stats": {
    "input_count": 100,
    "output_count": 45
  },
  "cost_usage": {
    "model_used": "gemini-2.5-flash",
    "total_tokens": 1500,
    "total_cost_usd": 0.00015,
    "total_cost_rmb": 0.00108
  }
}
```

### 4.2 结果文件内容 (JSON)

结果文件包含合并后的字幕列表及详细统计。

```json
{
  "merged_subtitles": [
    {
      "index": 1,
      "id": "new-uuid-generated-by-cloud",
      "start_time": 10.5,
      "end_time": 15.2,
      "content": "这是合并后的完整句子，标点符号已修正。",
      "original_indices": [1, 2, 3]
    }
    // ...
  ],
  "stats": { ... },
  "usage_report": { ... }
}
```

---

## 5. 调用示例

### 5.1 生产环境 (PROD)
最简调用，依赖服务端 `ai_inference_config.yaml` 配置。

```json
{
  "task_type": "REFINERY_SUBTITLE_MERGER",
  "payload": {
    "lang": "zh",
    "mode": "PROD",
    "subtitle_file_path": "uploads/2023/10/raw_asr_output.json"
  }
}
```

### 5.2 开发调试 (DEBUG)
指定更强的模型进行测试，并直接传入数据。

```json
{
  "task_type": "REFINERY_SUBTITLE_MERGER",
  "payload": {
    "lang": "en",
    "mode": "DEBUG",
    "service_params": {
      "model": "gemini-2.5-pro",
      "temperature": 0.3
    },
    "subtitles": [
      { "index": 1, "id": "uuid-1", "start_time": 0.0, "end_time": 1.5, "content": "Hello world" },
      { "index": 2, "id": "uuid-2", "start_time": 1.6, "end_time": 3.0, "content": "this is a test." }
    ]
  }
}
```