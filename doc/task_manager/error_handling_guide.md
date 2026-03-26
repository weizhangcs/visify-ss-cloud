# Task Manager 异常处理指南 (Client Integration Guide)

本文档面向客户端开发团队 (Android/iOS/Web)，详细说明了 VSS Cloud 任务管理模块 (`task_manager`) 的统一异常处理机制。

## 1. 核心设计理念

为了简化客户端的错误处理逻辑，我们将任务执行结果分为两个互斥的字段：
*   **`result`**: 仅在任务 **成功 (COMPLETED)** 时有值，包含业务数据。
*   **`error`**: 仅在任务 **失败 (FAILED)** 时有值，包含标准化的错误详情。

客户端无需解析 `result` 来判断是否出错，只需检查 `status` 和 `error` 字段。

## 2. API 响应结构

所有任务详情接口 (`GET /api/v1/tasks/{id}`) 均遵循以下响应结构：

```json
{
  "id": 12345,
  "status": "FAILED",  // 状态枚举: PENDING, RUNNING, COMPLETED, FAILED
  "task_type": "GENERATE_NARRATION",
  
  // 成功时有值，失败时为 null
  "result": null,
  
  // 失败时有值，成功时为 null
  "error": {
    "code": "PAYLOAD_VALIDATION_ERROR",  // 错误码 (字符串或数字)
    "message": "Invalid Task Payload: Missing required field 'asset_id'", // 人类可读描述
    "details": {  // 可选的详细上下文
      "field": "asset_id",
      "received": null
    }
  },
  
  "created": "2023-10-27T10:00:00Z",
  "modified": "2023-10-27T10:00:05Z"
}
```

## 3. 错误码定义 (Error Codes)

以下是系统通用的错误码定义。客户端可根据 `code` 进行差异化处理（如弹窗提示、自动重试等）。

### 3.1 基础系统级 (0-999)
| Code | Description | 建议处理方式 |
| :--- | :--- | :--- |
| `SUCCESS` (0) | 成功 | - |
| `UNKNOWN_ERROR` (1000) | 未知系统错误 | 提示“服务器繁忙，请稍后重试” |
| `INVALID_PARAM` (1001) | 参数无效 | 检查请求参数，通常是开发阶段问题 |
| `UNAUTHORIZED` (1002) | 认证失败 | 跳转登录页 |
| `PERMISSION_DENIED` (1003) | 权限不足 | 提示无权访问 |
| `NOT_FOUND` (1004) | 资源未找到 | 提示资源不存在 |

### 3.2 任务调度级 (2000-2999)
| Code | Description | 建议处理方式 |
| :--- | :--- | :--- |
| `TASK_CREATION_FAILED` (2001) | 任务创建失败 | 提示重试 |
| `TASK_NOT_FOUND` (2002) | 任务不存在 | 检查 Task ID 是否正确 |
| `TASK_ALREADY_FINISHED` (2003) | 任务已结束 | 无需处理，视为幂等成功 |
| `TASK_EXECUTION_FAILED` (2004) | 任务执行失败 | 查看 `message` 获取详情 |

### 3.3 AI 服务级 (3000-3999)
| Code | Description | 建议处理方式 |
| :--- | :--- | :--- |
| `RAG_DEPLOYMENT_ERROR` (3001) | RAG 部署失败 | 检查输入文件格式 |
| `LLM_INFERENCE_ERROR` (3002) | 大模型推理失败 | 提示“AI 服务暂时不可用” |
| `TTS_GENERATION_ERROR` (3003) | 语音生成失败 | 提示重试 |
| `PAYLOAD_VALIDATION_ERROR` (3004) | 任务参数校验失败 | **重点关注**: 通常意味着客户端传参格式错误 |

### 3.4 外部依赖级 (4000-4999)
| Code | Description | 建议处理方式 |
| :--- | :--- | :--- |
| `THIRD_PARTY_API_ERROR` (4001) | 第三方 API 调用失败 | 提示重试 |
| `RATE_LIMIT_EXCEEDED` (4002) | 配额耗尽/限流 | **自动重试**: 建议客户端等待一段时间后重试 |
| `FILE_IO_ERROR` (4003) | 文件读写错误 | 检查文件路径或权限 |

## 4. 客户端最佳实践

### 4.1 轮询策略
建议客户端使用指数退避 (Exponential Backoff) 策略轮询任务状态：
1.  初始间隔: 1s
2.  后续间隔: 2s, 4s, 8s...
3.  最大间隔: 30s
4.  超时时间: 根据任务类型设定 (e.g., 视频生成任务可能需要 5-10 分钟)

### 4.2 错误展示
*   **开发环境**: 直接展示 `error.message` 和 `error.details`，便于调试。
*   **生产环境**:
    *   对于 `PAYLOAD_VALIDATION_ERROR`，提示“输入数据格式有误”。
    *   对于 `RATE_LIMIT_EXCEEDED`，提示“服务繁忙，正在排队中...”。
    *   对于其他错误，展示友好的通用错误提示，并提供“复制错误ID”功能以便反馈。

### 4.3 异常恢复
*   如果遇到 `RATE_LIMIT_EXCEEDED`，服务端通常会自动重试（Celery 机制）。客户端只需继续轮询即可，无需重新提交任务。
*   如果状态变为 `FAILED`，则表示服务端重试已耗尽或遇到不可恢复错误，此时客户端应停止轮询。