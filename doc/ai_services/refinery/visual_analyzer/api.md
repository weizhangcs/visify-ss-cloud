# Visual Analyzer Service (Refinery)

## 1. 服务简介

**Visual Analyzer** 是 `Refinery`（精炼）模块下的核心原子服务。它利用多模态大模型（Gemini Vision via Vertex AI）对视频关键帧进行深度视觉分析，提取景别、环境、主体、动作及视觉情绪等元数据。

### 核心特性
- **多模态处理 (Multimodal)**: 基于 Google Vertex AI 架构，支持直接读取 GCS (`gs://`) 上的图片资源，无需下载到本地。
- **BFF 友好输出**: 关键枚举字段（如 `shot_type`）同时返回机器可读的 `value` 和人类可读的本地化 `label`。
- **高并发与断点续传**: 内置线程池并发处理，并支持结果缓存，防止长任务中断导致的数据丢失。
- **配置驱动**: 生产环境参数由服务端统一管理。

---

## 2. 任务定义

- **Task Type**: `REFINERY_VISUAL_ANALYZER`
- **Handler**: `RefineryVisualAnalyzerHandler`
- **Service**: `VisualAnalyzerService`

---

## 3. 请求载荷 (Payload)

创建任务时，`payload` 字段应符合以下 Schema。

### 3.1 字段说明

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `lang` | string | 否 | `"en"` | 输出语言代码。支持 `zh`, `en` 等。影响 `label` 和描述性文本的语言。 |
| `mode` | string | 否 | `"PROD"` | 运行模式。<br>- `PROD`: 严格模式。<br>- `DEBUG`: 调试模式，允许覆盖参数。 |
| `frames_file_path` | string | 否* | `null` | 包含帧列表的 JSON 文件路径（生产环境推荐）。 |
| `frames` | list | 否* | `null` | 直接传入的帧对象列表（调试环境推荐）。 |
| `service_params` | object | 否 | `null` | **仅 DEBUG 模式有效**。覆盖 `model`, `batch_size`, `max_workers` 等。 |

> **注意**: `frames_file_path` 和 `frames` 必须至少提供其中一个。

### 3.2 数据结构详情

#### VisualFrameInput (帧对象)
```json
{
  "frame_id": "slice_001_mid",
  "path": "gs://bucket/path/to/image.jpg" // 支持 gs:// 或本地绝对路径
}
```

#### ServiceParams (调试参数)
```json
{
  "model": "gemini-2.5-flash",
  "batch_size": 20,
  "max_workers": 5,
  "temperature": 0.1
}
```

---

## 4. 响应结果 (Result)

### 4.1 API 响应结构

```json
{
  "message": "Refinery visual analysis completed.",
  "output_file_path": "shared_tmp/org_uuid/refinery_visual_458_workspace/refinery_visual_result_458.json",
  "stats": {
    "total_frames": 100,
    "processed": 100
  },
  "cost_usage": {
    "model_used": "gemini-2.5-flash",
    "total_tokens": 35000,
    "total_cost_usd": 0.005,
    "total_cost_rmb": 0.036
  }
}
```

### 4.2 结果文件内容 (JSON)

```json
{
  "annotated_frames": [
    {
      "frame_id": "slice_001_mid",
      "visual_analysis": {
        "shot_type": {
          "value": "close_up",
          "label": "特写"
        },
        "environment": "室内-办公室",
        "subject": "一名穿着西装的男子",
        "action": "正在打电话",
        "lighting_time": "白天自然光",
        "visual_mood_tags": ["忙碌", "专业"]
      }
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

```json
{
  "task_type": "REFINERY_VISUAL_ANALYZER",
  "payload": {
    "lang": "zh",
    "mode": "PROD",
    "frames_file_path": "shared_tmp/extract_frames/job_123/frames_list.json"
  }
}
```

### 5.2 开发调试 (DEBUG)

```json
{
  "task_type": "REFINERY_VISUAL_ANALYZER",
  "payload": {
    "lang": "zh",
    "mode": "DEBUG",
    "service_params": {
      "model": "gemini-2.5-flash",
      "max_workers": 2
    },
    "frames": [
      {
        "frame_id": "test_01",
        "path": "gs://my-bucket/test_image.jpg"
      }
    ]
  }
}
```