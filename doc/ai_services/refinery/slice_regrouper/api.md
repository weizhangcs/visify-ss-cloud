# Slice Regrouper Service (Refinery)

## 1. 服务简介

**Slice Regrouper** 是 `Refinery`（精炼）模块下的核心原子服务。它利用大语言模型（LLM）的语义理解能力，将按时间顺序排列的多模态切片（包含视觉描述和对白）聚类为叙事连贯的“场景”（Scenes），并提取场景维度的元数据（如叙事动作、场景类型、运镜逻辑等）。

### 核心特性
- **多模态聚类 (Multimodal Clustering)**: 综合考量视觉画面（Visual）和对白剧情（Dialogue）的变化，识别场景边界。
- **BFF 友好输出**: 关键枚举字段（如 `scene_type`）同时返回机器可读的 `value` 和人类可读的本地化 `label`。
- **配置驱动 (Configuration-Driven)**: 生产环境下的技术参数（模型、Batch Size 等）由服务端统一配置管理。
- **双模式运行 (Dual-Mode)**: 支持 `PROD`（生产）和 `DEBUG`（调试）两种模式。

---

## 2. 任务定义

- **Task Type**: `REFINERY_SLICE_REGROUPER`
- **Handler**: `RefinerySliceRegrouperHandler`
- **Service**: `SliceRegrouperService`

---

## 3. 请求载荷 (Payload)

创建任务时，`payload` 字段应符合以下 Schema。

### 3.1 字段说明

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `lang` | string | 否 | `"zh"` | 输出语言代码。支持 `zh`, `en` 等。影响 `label` 和描述性文本的语言。 |
| `mode` | string | 否 | `"PROD"` | 运行模式。<br>- `PROD`: 严格模式。<br>- `DEBUG`: 调试模式，允许覆盖参数。 |
| `slices_file_path` | string | 否* | `null` | 包含切片列表的 JSON 文件路径（生产环境推荐）。 |
| `slices` | list | 否* | `null` | 直接传入的切片对象列表（调试环境推荐）。 |
| `service_params` | object | 否 | `null` | **仅 DEBUG 模式有效**。覆盖 `model`, `max_slices_per_batch`, `temperature` 等。 |

> **注意**: `slices_file_path` 和 `slices` 必须至少提供其中一个。

### 3.2 数据结构详情

#### MultimodalSlice (切片对象)
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "index": 1,
  "start_time": 0.0,
  "end_time": 4.5,
  "type": "visual_segment", // 或 "dialogue"
  "visual_contents": [
    {
      "frame_id": "frame_001",
      "timestamp": 2.0,
      "path": "gs://bucket/video/frame_001.jpg",
      "visual_analysis": { ... } // 来自 Visual Analyzer 的输出
    }
  ],
  "text_contents": [
    {
      "index": 1,
      "content": "Hello",
      "start_time": 1.0,
      "end_time": 2.0,
      "speaker": "Alice"
    }
  ]
}
```

#### ServiceParams (调试参数)
```json
{
  "model": "gemini-2.5-flash",
  "max_slices_per_batch": 200,
  "temperature": 0.1,
  "max_retries": 3
}
```

---

## 4. 响应结果 (Result)

### 4.1 API 响应结构

```json
{
  "message": "Refinery slice regrouping completed.",
  "output_file_path": "shared_tmp/org_uuid/refinery_slice_regrouper_459_workspace/refinery_slice_regrouper_result_459.json",
  "stats": {
    "input_slice_count": 50,
    "output_scene_count": 12
  },
  "cost_usage": {
    "model_used": "gemini-2.5-flash",
    "total_tokens": 15000,
    "total_cost_usd": 0.002,
    "total_cost_rmb": 0.015
  }
}
```

### 4.2 结果文件内容 (JSON)

```json
{
  "scenes": [
    {
      "scene_id": 1,
      "start_time": 0.0,
      "end_time": 15.5,
      "slice_ids": ["uuid-1", "uuid-2", "uuid-3"],
      "content": {
        "narrative_action": "Alice和Bob在咖啡馆见面并寒暄。",
        "location": "城市咖啡馆",
        "scene_type": {
          "value": "dialogue",
          "label": "对话场景"
        },
        "visual_mood_tags": ["温馨", "现代"],
        "camera_logic": "建立镜头切入中景对话。",
        "character_dynamics": "老友重逢，气氛融洽。",
        "reason": "时间连续，地点一致，且围绕同一个对话事件。"
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
  "task_type": "REFINERY_SLICE_REGROUPER",
  "payload": {
    "lang": "zh",
    "mode": "PROD",
    "slices_file_path": "shared_tmp/pre_process/job_123/slices_list.json"
  }
}
```

### 5.2 开发调试 (DEBUG)

```json
{
  "task_type": "REFINERY_SLICE_REGROUPER",
  "payload": {
    "lang": "zh",
    "mode": "DEBUG",
    "service_params": {
      "model": "gemini-2.5-flash",
      "max_slices_per_batch": 50
    },
    "slices": [
      {
        "id": "uuid-1",
        "index": 1,
        "start_time": 0.0,
        "end_time": 5.0,
        "type": "visual_segment",
        "visual_contents": [...]
      }
    ]
  }
}
```