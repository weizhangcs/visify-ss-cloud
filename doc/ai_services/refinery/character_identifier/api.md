# Character Identifier Service (Refinery)

## 1. 服务简介

**Character Identifier** 是 `Refinery`（精炼）模块下的核心原子服务。它利用大语言模型（LLM）的语义理解能力，结合声纹分析（可选的多模态输入），为每一行字幕标注说话人角色，并对角色名称进行全局归一化。

### 核心特性
- **双阶段推理 (Dual-Stage Inference)**:
    1. **批量推理 (Batch Inference)**: 对字幕进行分批处理，结合上下文和声纹特征进行初步角色识别。
    2. **递归精修 (Recursive Refinement)**: 将初步识别结果构建为完整剧本上下文，再次输入 LLM 进行全局角色名归一化，消除同人异名现象。
- **多模态支持 (Multimodal Support)**: 支持传入 `audio_analysis` (性别/声纹特征)，作为 LLM 推理的强约束条件。
- **配置驱动 (Configuration-Driven)**: 生产环境下的技术参数（模型、Batch Size 等）由服务端统一配置管理。
- **双模式运行 (Dual-Mode)**: 支持 `PROD`（生产）和 `DEBUG`（调试）两种模式。

---

## 2. 任务定义

- **Task Type**: `REFINERY_CHARACTER_IDENTIFIER`
- **Handler**: `RefineryCharacterIdentifierHandler`
- **Service**: `CharacterIdentifierService`

---

## 3. 请求载荷 (Payload)

创建任务时，`payload` 字段应符合以下 Schema。

### 3.1 字段说明

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `lang` | string | 否 | `"zh"` | 字幕语言代码。支持 `zh`, `en`, `ja`, `ko`, `es`, `fr`, `de` 等。 |
| `mode` | string | 否 | `"PROD"` | 运行模式。<br>- `PROD`: 严格模式，忽略 `service_params`。<br>- `DEBUG`: 调试模式，允许覆盖参数。 |
| `known_characters` | list[str] | 否 | `[]` | **VIP 核心角色列表**。提供此列表可显著提高识别准确度并减少幻觉。 |
| `video_title` | string | 否 | `null` | 视频标题（上下文信息，辅助 LLM 理解剧情背景）。 |
| `subtitle_file_path` | string | 否* | `null` | 原始字幕文件在共享存储中的相对路径（推荐生产环境使用）。 |
| `subtitles` | list | 否* | `null` | 直接传入的字幕对象列表（推荐调试环境使用）。 |
| `service_params` | object | 否 | `null` | **仅 DEBUG 模式有效**。用于覆盖服务端默认的技术参数。 |

> **注意**: `subtitle_file_path` 和 `subtitles` 必须至少提供其中一个。如果两者都提供，优先使用 `subtitles`。

### 3.2 数据结构详情

#### SubtitleItem (字幕对象)
包含可选的多模态分析数据。
```json
{
  "index": 1,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "start_time": 10.5,
  "end_time": 12.0,
  "content": "你好，请问王经理在吗？",
  "audio_analysis": {
    "gender": "Female"  // 可选值: "Male", "Female", "Unknown"
  }
}
```

#### ServiceParams (调试参数)
仅当 `mode="DEBUG"` 时生效。
```json
{
  "model": "gemini-2.5-flash",
  "batch_size": 150,
  "temperature": 0.1,
  "max_retries": 3
}
```

---

## 4. 响应结果 (Result)

任务执行成功后，`task.result` 将包含执行摘要，详细的识别结果将写入共享存储中的 JSON 文件。

### 4.1 API 响应结构

```json
{
  "message": "Refinery character identifier completed.",
  "output_file_path": "shared_tmp/org_uuid/refinery_char_id_453_workspace/refinery_char_id_result_453.json",
  "stats": {
    "total_lines": 1491,
    "processed_lines": 1491,
    "batches": 15,
    "identified_roles": [
      "Dylan Rhodes",
      "J. Daniel Atlas",
      "Thaddeus Bradley"
    ]
  },
  "cost_usage": {
    "model_used": "gemini-2.5-flash",
    "total_tokens": 203807,
    "total_cost_usd": 0.094189,
    "total_cost_rmb": 0.68287
  }
}
```

### 4.2 结果文件内容 (JSON)

结果文件包含识别后的字幕列表。

```json
{
  "identified_subtitles": [
    {
      "index": 1,
      "id": "uuid-1",
      "speaker": "J. Daniel Atlas",
      "reasoning": "AI Inferred"
    },
    {
      "index": 2,
      "id": "uuid-2",
      "speaker": "Dylan Rhodes",
      "reasoning": "AI Inferred"
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
推荐提供 `known_characters` 以获得最佳效果。

```json
{
  "task_type": "REFINERY_CHARACTER_IDENTIFIER",
  "payload": {
    "lang": "zh",
    "mode": "PROD",
    "known_characters": ["王经理", "小李"],
    "video_title": "办公室风云 第一集",
    "subtitle_file_path": "uploads/2023/10/raw_subtitles.json"
  }
}
```

### 5.2 开发调试 (DEBUG)

```json
{
  "task_type": "REFINERY_CHARACTER_IDENTIFIER",
  "payload": {
    "lang": "zh",
    "mode": "DEBUG",
    "service_params": {
      "model": "gemini-2.5-flash",
      "batch_size": 10
    },
    "subtitles": [
      {
        "index": 1,
        "id": "uuid-1",
        "start_time": 0.5,
        "end_time": 2.0,
        "content": "小李啊，你来一下我的办公室。",
        "audio_analysis": { "gender": "Male" }
      }
    ]
  }
}
```