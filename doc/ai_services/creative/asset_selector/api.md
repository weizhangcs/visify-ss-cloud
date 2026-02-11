# Asset Selector Service (Creative)

## 1. 服务简介

**Asset Selector** 是 `Creative`（创作）模块下的首个原子服务，扮演“智能素材管理员”的角色。它接收解说词脚本（Dubbing Script）和经过 Refinery 处理的资产库（Slice Inventory），利用 LLM 的语义理解能力，为每一段解说词挑选最匹配的视觉切片。

### 核心特性
- **语义检索 (Semantic Retrieval)**: 不仅仅匹配关键词，更能理解解说词的意境（如“焦虑”、“决心”）与镜头语言（如“特写”、“运镜”）之间的联系。
- **多模态消费**: 直接消费上游 `SliceAnalyzer` 产出的 `narrative_summary` 和 `tags`，实现从“文案”到“视觉语义”的映射。
- **配置驱动**: 支持通过配置调整候选数量 (`top_k`) 和模型参数。

---

## 2. 任务定义

- **Task Type**: `CREATIVE_ASSET_SELECTOR`
- **Handler**: `CreativeAssetSelectorHandler`
- **Service**: `AssetSelectorService`

---

## 3. 请求载荷 (Payload)

创建任务时，`payload` 字段应符合以下 Schema。

### 3.1 字段说明

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `lang` | string | 否 | `"zh"` | 语言代码。影响 LLM 输出的“选择理由”语言。 |
| `mode` | string | 否 | `"PROD"` | 运行模式。<br>- `PROD`: 严格模式。<br>- `DEBUG`: 调试模式，允许覆盖参数。 |
| `dubbing_script` | list | 是 | - | 解说词片段列表。 |
| `slices_file_path` | string | 否* | `null` | 包含切片列表的 JSON 文件路径（生产环境推荐）。 |
| `slices` | list | 否* | `null` | 直接传入的切片对象列表（调试环境推荐）。 |
| `service_params` | object | 否 | `null` | **仅 DEBUG 模式有效**。覆盖 `model`, `top_k` 等。 |

> **注意**: `slices_file_path` 和 `slices` 必须至少提供其中一个。

### 3.2 数据结构详情

#### DubbingSegment (解说词片段)
```json
{
  "index": 1,
  "text": "她闭上双眼，深吸一口气...",
  "duration": 8.2,
  "semantic_requirements": ["Close_Up", "Determination"] // 可选的显式需求
}
```

#### ServiceParams (调试参数)
```json
{
  "model": "gemini-2.5-flash",
  "top_k": 5,
  "temperature": 0.1
}
```

---

## 4. 响应结果 (Result)

### 4.1 API 响应结构

```json
{
  "message": "Creative asset selector completed.",
  "output_file_path": "shared_tmp/org_uuid/creative_asset_selector_513_workspace/creative_asset_selector_result_513.json",
  "stats": {
    "input_slices": 50,
    "segments": 10
  },
  "cost_usage": {
    "model_used": "gemini-2.5-flash",
    "total_tokens": 2732,
    "total_cost_usd": 0.000847
  }
}
```

### 4.2 结果文件内容 (JSON)

```json
{
  "selections": [
    {
      "segment_index": 1,
      "candidates": [
        {
          "slice_id": 8,
          "score": 10,
          "reason": "完美匹配解说词中闭眼、睁眼、决心以及身份转变的核心情节。"
        },
        {
          "slice_id": 1,
          "score": 2,
          "reason": "场景和动作与解说词描述不符，但作为备选。"
        }
      ]
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
  "task_type": "CREATIVE_ASSET_SELECTOR",
  "payload": {
    "lang": "zh",
    "mode": "PROD",
    "dubbing_script": [...],
    "slices_file_path": "shared_tmp/refinery/job_123/slices_analyzed.json"
  }
}
```

### 5.2 开发调试 (DEBUG)

```json
{
  "task_type": "CREATIVE_ASSET_SELECTOR",
  "payload": {
    "lang": "zh",
    "mode": "DEBUG",
    "service_params": {
      "top_k": 3
    },
    "dubbing_script": [
      {
        "index": 1,
        "text": "测试文本...",
        "duration": 5.0
      }
    ],
    "slices": [...]
  }
}
```