# Editing Director Service (Creative)

## 1. 服务简介

**Editing Director** 是 `Creative`（创作）模块的核心决策引擎，扮演“剪辑师”的角色。它接收 `Asset Selector` 提供的候选素材和解说词的时长约束，通过确定性的算法策略，计算出每个片段的具体剪辑指令（使用现有素材、变速、定帧或生成新素材）。

### 核心特性
- **时空编排 (Spatiotemporal Orchestration)**: 精确计算素材时长与配音时长的差异 (Gap Analysis)。
- **策略路由 (Strategy Routing)**:
    - **Overshoot (素材过长)**: 自动计算裁剪范围 (Trim)。
    - **Undershoot (素材过短)**: 自动计算变速倍率 (Speed Ramp) 或触发定帧。
    - **Missing/Extreme (缺失/极短)**: 自动降级为生成指令 (Generate)。
- **纯逻辑服务**: 不依赖 LLM 推理，运行速度极快，结果可预测。

---

## 2. 任务定义

- **Task Type**: `CREATIVE_EDITING_DIRECTOR`
- **Handler**: `CreativeEditingDirectorHandler`
- **Service**: `EditingDirectorService`

---

## 3. 请求载荷 (Payload)

创建任务时，`payload` 字段应符合以下 Schema。

### 3.1 字段说明

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `lang` | string | 否 | `"zh"` | 语言代码。 |
| `mode` | string | 否 | `"PROD"` | 运行模式。 |
| `dubbing_script` | list | 是 | - | 包含目标时长的解说词脚本。 |
| `selections` | list | 是 | - | 来自 Asset Selector 的候选素材列表。 |
| `service_params` | object | 否 | `null` | **仅 DEBUG 模式有效**。覆盖策略阈值。 |

### 3.2 数据结构详情

#### DubbingSegment
```json
{
  "index": 1,
  "text": "这是一个关于身份与抉择的故事。",
  "duration": 5.0
}
```

#### SegmentSelection (来自 Asset Selector)
```json
{
  "segment_index": 1,
  "candidates": [
    { "slice_id": 8, "score": 10, "duration": 9.64, "reason": "..." }
  ]
}
```

#### ServiceParams (策略参数)
```json
{
  "min_speed_rate": 0.5,       // 慢放极限 (0.5x)
  "max_speed_rate": 1.5,       // 快进极限 (1.5x)
  "generation_threshold": 0.3  // 生成阈值 (素材时长 < 目标的 30% 时触发生成)
}
```

---

## 4. 响应结果 (Result)

### 4.1 API 响应结构

```json
{
  "message": "Creative editing director completed.",
  "output_file_path": "shared_tmp/org_uuid/creative_editing_director_514_workspace/result.json",
  "stats": {
    "total_segments": 4,
    "action_use_slice": 2,
    "action_generate": 2,
    "action_empty": 0
  }
}
```

### 4.2 结果文件内容 (JSON)

包含具体的剪辑决策指令列表。

```json
{
  "decisions": [
    {
      "segment_index": 1,
      "action": "USE_SLICE",
      "slice_id": 8,
      "source_range": [0.0, 5.0],
      "speed_rate": 1.0,
      "target_duration": 5.0,
      "reason": "Trimmed from 9.64s to 5.0s."
    },
    {
      "segment_index": 3,
      "action": "GENERATE",
      "generation_prompt": "Cinematic shot: ...",
      "target_duration": 5.0,
      "reason": "Best candidate too short (0.32s vs 5.0s)."
    }
  ]
}
```

---

## 5. 调用示例

### 5.1 生产环境 (PROD)

通常由工作流编排器将 `Asset Selector` 的输出直接透传给 `Editing Director`。

```json
{
  "task_type": "CREATIVE_EDITING_DIRECTOR",
  "payload": {
    "dubbing_script": [...],
    "selections": [...]
  }
}
```