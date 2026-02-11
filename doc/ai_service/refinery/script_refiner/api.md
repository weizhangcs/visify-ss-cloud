# Dubbing Script Refiner API

## 1. 概述 (Overview)

**服务名称**: `DUBBING_SCRIPT_REFINER`
**任务类型**: `REFINERY_DUBBING_SCRIPT_REFINER`

该服务定位为 **“智能字幕校对专家”**。它负责将原始的 ASR (语音识别) 和 OCR (画面文字识别) 数据进行多模态融合与精修。

核心目标是解决 ASR 错字、OCR 噪音、音画不同步等问题，生成一份**忠实于原意、精准校对**的字幕文件，而非进行剧本创作。

## 2. 调用方式 (Invocation)

通过 VSS Cloud 标准异步任务接口调用。

- **接口地址**: `POST /api/v1/tasks/`
- **Content-Type**: `application/json`

### 请求体 (Request Body)

```json
{
  "task_type": "REFINERY_DUBBING_SCRIPT_REFINER",
  "payload": {
    "lang": "zh",
    "mode": "PROD",
    "input_file_path": "tmp/project_123/raw_script_data.json"
  }
}
```

### Payload 字段说明

| 字段名 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `lang` | String | 是 | 目标语言代码，支持 `"zh"`, `"en"`。 |
| `mode` | String | 是 | 运行模式。`"PROD"` (生产) 或 `"DEBUG"` (调试)。 |
| `input_file_path` | String | **PROD必填** | 包含 ASR 和 OCR 数据的 JSON 文件路径（支持相对路径，自动拼接共享存储根目录）。 |
| `asr_segments` | List | DEBUG选填 | ASR 数据列表 (见下文结构)。 |
| `ocr_texts` | List | DEBUG选填 | OCR 数据列表 (见下文结构)。 |
| `service_params` | Object | DEBUG选填 | 调试参数，用于覆盖默认配置。 |

> **注意**: 在 `PROD` 模式下，必须提供 `input_file_path`，且不允许传递 `service_params`。

#### 输入文件/数据结构 (Input Data Structure)

`input_file_path` 指向的 JSON 文件应符合以下结构：

```json
{
  "asr_segments": [
    { "start": 0.52, "end": 2.18, "text": "今天天气不错" }
  ],
  "ocr_texts": [
    { "start_time": 0.45, "end_time": 2.25, "text": "今天天气真好", "avg_score": 0.92 }
  ]
}
```

## 3. 输出结果 (Output)

任务完成后，结果将保存为 JSON 文件。

### 结果文件结构

```json
{
  "refined_script": [
    {
      "start": 0.45,
      "end": 2.25,
      "original_asr": "今天天气不错",
      "original_ocr": "天气真好",
      "refined_text": "今天天气真不错。",
      "source_of_truth": "ASR_OCR_MERGED",
      "reasoning": "结合 ASR 和 OCR 的内容...",
      "confidence_score": 0.9
    }
  ],
  "stats": { ... },
  "usage_report": { ... }
}
```

### 字段说明 (`refined_script`)

| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `start` / `end` | Float | 精修后的台词起止时间 (秒)。 |
| `original_asr` | String | 原始 ASR 文本 (由服务回填，非 LLM 生成)。 |
| `original_ocr` | String | 原始 OCR 文本 (由服务回填，非 LLM 生成)。 |
| `refined_text` | String | **核心产物**：校对后的字幕文本。 |
| `source_of_truth` | String | 决策来源 (见下文)。 |
| `reasoning` | String | LLM 的推理理由。 |
| `confidence_score` | Float | 置信度分数 (0.0 - 1.0)。 |

### 决策来源 (`source_of_truth`) 枚举

| 值 | 含义 | 置信度 |
| :--- | :--- | :--- |
| `ASR_OCR_MERGED` | ASR 与 OCR 融合，取长补短。 | 0.9 |
| `ASR_ONLY` | 仅 ASR 有效，OCR 无匹配。 | 0.75 |
| `OCR_PRIMARY` | ASR 质量差或缺失 (VAD漏识)，以 OCR 为主。 | 0.75 |
| `OCR_IGNORED` | OCR 被识别为非对话噪音 (如水印、路标)。 | 1.0 |
| `CONTEXT_REPAIR` | 利用上下文修复残缺内容。 | 0.6 |

## 4. 核心策略 (Core Strategies)

1.  **时序对齐 (Temporal Alignment)**:
    *   采用 `±1.0s` 容差窗口对齐 ASR 和 OCR。优先使用 ASR 时间戳作为基准。

2.  **异常处理与冲突仲裁 (Exception Handling)**:
    *   **OCR 补盲**: 当 ASR 缺失但 OCR 有高置信度对话文本（含代词/语气词）时，判定为 `OCR_PRIMARY`。
    *   **噪音过滤**: 当 ASR 缺失且 OCR 为孤立名词/地标时，判定为 `OCR_IGNORED`。
    *   **多语种过滤**: 针对双语字幕，仅提取目标语言 (`lang`) 对应的部分。

3.  **Token 优化**:
    *   LLM 仅输出精修结果，不重复输出原始文本，防止长视频任务导致 Token 溢出截断。

## 5. 调试参数 (Debug Params)

在 `mode="DEBUG"` 时，可通过 `service_params` 调整：
- `model`: 指定模型 (e.g. `gemini-2.5-pro`)
- `chunk_duration_seconds`: 切片时长 (默认 180s)
- `max_output_tokens`: 最大输出 Token 数 (默认 8192)