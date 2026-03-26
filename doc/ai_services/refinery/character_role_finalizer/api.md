# Character Role Finalizer API

## 1. 概述 (Overview)

**服务名称**: `character_role_finalizer`
**任务类型**: `REFINERY_CHARACTER_ROLE_FINALIZER`

该服务属于多模态管线的 **“认知层 (Cognitive Layer)”**。它位于物理感知层（ASR/OCR/声纹识别/人脸聚类）之后，利用 LLM 的全局上下文理解能力，对物理算法产生的初步角色标记进行**逻辑校验**和**实体归一化**。

核心目标是将冷冰冰的物理 ID (`PERSON_00`) 转化为有业务价值的角色名（如“安然”），并利用常识和对话逻辑修正物理模型的误判。

## 2. 调用方式 (Invocation)

通过 VSS Cloud 标准异步任务接口调用。

- **接口地址**: `POST /api/v1/tasks/`
- **Content-Type**: `application/json`

### 请求体 (Request Body)

#### 生产模式 (PROD) - 推荐

```json
{
  "task_type": "REFINERY_CHARACTER_ROLE_FINALIZER",
  "payload": {
    "lang": "zh",
    "mode": "PROD",
    "input_file_path": "tmp/project_123/fusion_result.json"
  }
}
```

#### 调试模式 (DEBUG)

```json
{
  "task_type": "REFINERY_CHARACTER_ROLE_FINALIZER",
  "payload": {
    "lang": "zh",
    "mode": "DEBUG",
    "segments": [
      {
        "start": 6.4, "end": 7.0,
        "refined_text": "我是安然。",
        "speaker": "PERSON_00",
        "fusion_score": 0.95
      }
    ],
    "service_params": {
      "model": "gemini-2.5-pro"
    }
  }
}
```

### Payload 字段说明

| 字段名 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `lang` | String | 是 | 目标语言代码，支持 `"zh"`, `"en"`。 |
| `mode` | String | 是 | 运行模式。`"PROD"` (生产) 或 `"DEBUG"` (调试)。 |
| `input_file_path` | String | **PROD必填** | 包含输入片段数据的 JSON 文件路径（支持相对路径）。 |
| `segments` | List | DEBUG选填 | 直接传入的片段列表 (见下文结构)。 |
| `service_params` | Object | DEBUG选填 | 调试参数，用于覆盖默认配置。 |

#### 输入数据结构 (Input Segment)

`input_file_path` 指向的 JSON 文件应包含一个 `segments` 列表，或直接为对象列表。每个对象的结构如下：

| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `start` / `end` | Float | 片段起止时间。 |
| `refined_text` | String | 经过精修的字幕文本。 |
| `speaker` | String | 物理层输出的 Speaker ID (e.g., `PERSON_00`)。 |
| `fusion_score` | Float | 物理层的置信度打分 (0.0-1.0)。分数越低，LLM 介入修正的可能性越大。 |

## 3. 输出结果 (Output)

任务完成后，结果将保存为 JSON 文件。

### 结果文件结构

```json
{
  "finalized_script": [
    {
      "start": 10.6,
      "end": 12.0,
      "text": "我不听！",
      "speaker_id": "PERSON_00",
      "character_name": "安然",
      "reasoning": "Correction. Previous segment PERSON_01 called 'Anran', this is the response..."
    }
  ],
  "character_map": [
    {
      "speaker_id": "PERSON_00",
      "name": "安然",
      "aliases": ["安总", "安然小姐"]
    }
  ],
  "stats": { ... },
  "usage_report": { ... }
}
```

### 字段说明

*   **`finalized_script`**: 最终剧本列表。
    *   `speaker_id`: 修正后的物理 ID。
    *   `character_name`: 归一化后的角色名称。
    *   `reasoning`: 如果发生了修正，这里会包含 LLM 的推理理由。
*   **`character_map`**: 全局角色映射表。
    *   记录了每个 `speaker_id` 对应的真实姓名 (`name`) 和检测到的别名 (`aliases`)。

## 4. 核心策略 (Core Strategies)

1.  **实体归一化 (Entity Linking)**:
    *   LLM 扫描全剧本，通过自我介绍（“我是安然”）或他人称呼（“安总”）来锁定 ID 与名字的关系。
    *   将同一角色的不同称呼（安然、安小姐）归一化为标准名。

2.  **逻辑纠错 (Logical Correction)**:
    *   **呼唤-应答链**: 利用对话结构修正物理误判。例如 A 呼唤 B，随后的回应大概率来自 B，即使物理声纹混淆。
    *   **性别/语气冲突**: 如果文本语气具有明显的性别特征（如“老子”、“奴家”），但物理 ID 性别属性不符，LLM 会进行修正。
    *   **低置信度仲裁**: 当 `fusion_score` 较低时，LLM 会更积极地介入，依据上下文语义重写 `speaker_id`。

## 5. 调试参数 (Debug Params)

在 `mode="DEBUG"` 时，可通过 `service_params` 调整：

```json
"service_params": {
  "model": "gemini-2.5-pro",
  "temperature": 0.1
}
```