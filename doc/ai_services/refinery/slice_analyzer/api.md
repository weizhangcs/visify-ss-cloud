# Slice Analyzer Service (Refinery)

## 1. 服务简介

**Slice Analyzer** 是 `Refinery`（精炼）模块下的核心原子服务。它作为视觉处理管线的“中间层”（Slice Layer），负责对多模态切片（包含视觉帧和对白）进行深度语义分析，提取镜头级的叙事总结、视觉描述和语义标签。

### 核心特性
- **多模态融合 (Multimodal Fusion)**: 综合分析切片内的视觉画面（Visual）和对白文本（Dialogue），生成更准确的语义描述。
- **语义标签化 (Semantic Tagging)**: 输出标准化的镜头标签（如 `Reaction_Shot`, `Close_Up`, `Emotional`），支持下游的自动化剪辑和资产检索。
- **配置驱动**: 生产环境参数由服务端统一管理。
- **双模式运行**: 支持 `PROD`（生产）和 `DEBUG`（调试）两种模式。

---

## 2. 任务定义

- **Task Type**: `REFINERY_SLICE_ANALYZER`
- **Handler**: `RefinerySliceAnalyzerHandler`
- **Service**: `SliceAnalyzerService`

---

## 3. 请求载荷 (Payload)

创建任务时，`payload` 字段应符合以下 Schema。

### 3.1 字段说明

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `lang` | string | 否 | `"zh"` | 输出语言代码。支持 `zh`, `en` 等。影响 Summary 的语言。 |
| `mode` | string | 否 | `"PROD"` | 运行模式。<br>- `PROD`: 严格模式。<br>- `DEBUG`: 调试模式，允许覆盖参数。 |
| `slices_file_path` | string | 否* | `null` | 包含切片列表的 JSON 文件路径（生产环境推荐）。 |
| `slices` | list | 否* | `null` | 直接传入的切片对象列表（调试环境推荐）。 |
| `service_params` | object | 否 | `null` | **仅 DEBUG 模式有效**。覆盖 `model`, `batch_size`, `temperature` 等。 |

> **注意**: `slices_file_path` 和 `slices` 必须至少提供其中一个。

### 3.2 数据结构详情

#### MultimodalSlice (切片对象)
```json
{
  "slice_id": 1,
  "start_time": 0.0,
  "end_time": 3.5,
  "type": "visual_segment",
  "visual_contents": [
    {
      "frame_id": "frame_001",
      "timestamp": 1.5,
      "path": "gs://bucket/video/frame_001.jpg",
      "visual_analysis": { ... } // 来自 Visual Analyzer 的输出
    }
  ],
  "text_contents": []
}
```

#### ServiceParams (调试参数)
```json
{
  "model": "gemini-2.5-flash",
  "batch_size": 50,
  "temperature": 0.1,
  "max_retries": 3
}
```

---

## 4. 响应结果 (Result)

### 4.1 API 响应结构

```json
{
  "message": "Refinery slice analyzer completed.",
  "output_file_path": "shared_tmp/org_uuid/refinery_slice_analyzer_460_workspace/refinery_slice_analyzer_result_460.json",
  "stats": {
    "input_slice_count": 2,
    "analyzed_count": 2
  },
  "cost_usage": {
    "model_used": "gemini-2.5-flash",
    "total_tokens": 1026,
    "total_cost_usd": 0.000609,
    "total_cost_rmb": 0.004415
  }
}
```

### 4.2 结果文件内容 (JSON)

```json
{
  "analyzed_slices": [
    {
      "slice_id": 1,
      "slice_analysis": {
        "narrative_summary": "侦探在昏暗的审讯室里猛拍桌子，营造出紧张的氛围。",
        "visual_summary": "画面呈现昏暗的审讯室，特写侦探猛拍桌子的手，整体视觉风格紧张压抑。",
        "tags": ["Interrogation", "Tension", "Conflict", "Hand_Shot"]
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
  "task_type": "REFINERY_SLICE_ANALYZER",
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
  "task_type": "REFINERY_SLICE_ANALYZER",
  "payload": {
    "lang": "zh",
    "mode": "DEBUG",
    "service_params": {
      "model": "gemini-2.5-flash",
      "batch_size": 10
    },
    "slices": [...]
  }
}
```