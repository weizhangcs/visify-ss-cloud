import json
import time
import inspect
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union, List, Callable, Type, Tuple, TypeVar

import httpcore
from google import genai
from google.genai import types
from google.api_core import exceptions
from google.genai.errors import ServerError
from pydantic import BaseModel, ValidationError

from core.exceptions import RateLimitException
from .schemas import UsageStats

# 定义泛型 T
T = TypeVar("T", bound=BaseModel)


class VertexProcessor:
    """
    [Infrastructure] Vertex AI 核心处理器 (Isolated Edition).
    专门用于 Visual Analyzer 等需要 GCS 权限或大规模多模态输入的场景。
    与 GeminiProcessor 代码高度冗余，旨在隔离风险，避免回归测试成本。
    """

    _MAX_RETRIES = 3
    _INITIAL_RETRY_DELAY = 1
    _MAX_RETRY_DELAY = 10
    _RETRYABLE_ERRORS = (
        exceptions.ServiceUnavailable, ServerError, exceptions.TooManyRequests,
        exceptions.InternalServerError, exceptions.GatewayTimeout,
        exceptions.ResourceExhausted,
        httpcore.RemoteProtocolError, httpcore.ConnectError, httpcore.ReadTimeout
    )

    def __init__(self,
                 project: str,
                 location: str,
                 logger: logging.Logger,
                 debug_mode: bool = False,
                 debug_dir: Union[str, Path] = "vertex_debug",
                 client: Optional[genai.Client] = None,
                 caller_class: Optional[str] = None):

        self.logger = logger
        self.debug_mode = debug_mode
        self.caller_class = caller_class or self._get_caller_class_name()

        if client:
            self._client = client
        else:
            try:
                # Vertex AI 模式 (ADC Auth)
                self._client = genai.Client(vertexai=True, project=project, location=location)
                self.logger.info(f"Initialized VertexProcessor (Project: {project}, Location: {location})")
            except Exception as e:
                self.logger.error(f"Vertex Client Init Failed: {e}")
                raise

        if self.debug_mode:
            self.debug_dir = Path(debug_dir)
            try:
                self.debug_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                self.logger.warning(f"Failed to create debug directory '{self.debug_dir}': {e}. Logging disabled.")
                self.debug_dir = None
        else:
            self.debug_dir = None

    def _get_default_safety_settings(self) -> List[types.SafetySetting]:
        return [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
        ]

    def _prepare_config(self,
                        temperature: Optional[float],
                        schema: Optional[Type[BaseModel]],
                        external_config: Optional[types.GenerateContentConfig],
                        extra_kwargs: Dict[str, Any]
                        ) -> types.GenerateContentConfig:
        config = external_config if external_config else types.GenerateContentConfig()

        if not hasattr(config, 'safety_settings') or not config.safety_settings:
            config.safety_settings = self._get_default_safety_settings()

        if temperature is not None:
            config.temperature = temperature

        valid_gen_keys = {
            'top_p', 'top_k', 'max_output_tokens', 'stop_sequences', 'candidate_count',
            'presence_penalty', 'frequency_penalty', 'seed', 'response_logprobs', 'logprobs',
            'thinking_config',
            'system_instruction'
        }

        for k, v in extra_kwargs.items():
            if k in valid_gen_keys:
                setattr(config, k, v)

        if schema:
            config.response_mime_type = "application/json"
            config.response_schema = schema

        return config

    def count_tokens(self, model_name: str, contents: Union[str, List]) -> int:
        """
        计算 Token 数量 (支持重试)。
        Visual Analyzer 需要此方法来预计算多模态输入的 Token 成本。
        """
        def api_call():
            return self._client.models.count_tokens(
                model=model_name,
                contents=contents
            )

        try:
            response, _ = self._retry_api_call(api_call, f"CountTokens({model_name})")
            return response.total_tokens
        except Exception as e:
            self.logger.warning(f"CountTokens failed: {e}")
            return 0

    def generate_content(
            self,
            model_name: str,
            prompt: Union[str, List],
            response_schema: Optional[Type[T]] = None,
            temperature: Optional[float] = None,
            config: Optional[types.GenerateContentConfig] = None,
            **kwargs
    ) -> Tuple[Union[T, str], UsageStats]:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        start_time = datetime.now()

        final_config = self._prepare_config(temperature, response_schema, config, kwargs)

        if self.debug_mode:
            self._log_payload("request", timestamp, {
                "model": model_name,
                "prompt": str(prompt),
                "schema": response_schema.__name__ if response_schema else "None",
                "config": str(final_config)
            })

        def api_call():
            return self._client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=final_config,
            )

        try:
            response, retry_count = self._retry_api_call(api_call, f"Gen({model_name})")

            result, usage = self._process_response(
                response,
                model_name,
                start_time,
                response_schema,
                request_count=1 + retry_count
            )

            if self.debug_mode:
                self._log_payload("response", timestamp, {
                    "usage": usage.model_dump(),
                    "result": str(result)
                })

            return result, usage

        except Exception as e:
            self._log_error(e, "GenerateContent", timestamp)
            raise

    def _process_response(self,
                          response: Any,
                          model_name: str,
                          start_time: datetime,
                          schema: Optional[Type[T]],
                          request_count: int) -> Tuple[Union[T, str], UsageStats]:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        usage_dict = self.normalize_usage(response)
        
        usage = UsageStats(
            model_used=model_name,
            prompt_tokens=usage_dict["prompt_tokens"],
            cached_tokens=usage_dict["cached_tokens"],
            completion_tokens=usage_dict["completion_tokens"],
            total_tokens=usage_dict["total_tokens"],
            duration_seconds=round(duration, 4),
            request_count=request_count,
            timestamp=end_time.isoformat()
        )

        if schema:
            if hasattr(response, 'parsed') and response.parsed:
                return response.parsed, usage
            else:
                raw_text = getattr(response, 'text', '')
                try:
                    return schema.model_validate_json(raw_text), usage
                except ValidationError as e:
                    error_details = json.dumps(e.errors(), ensure_ascii=False)
                    self._log_error(e, f"SchemaValidationFail({model_name})", datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
                    raise ValueError(f"SDK parsed JSON but schema validation failed.\nErrors: {error_details}\nRaw text preview: {raw_text[:1000]}...") from e
                except Exception as e:
                    raise ValueError(f"SDK failed to parse schema. Raw text: {raw_text[:1000]}...") from e
        else:
            return getattr(response, 'text', ''), usage

    def _retry_api_call(self, func: Callable, context: str) -> Tuple[Any, int]:
        retries = 0
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                return func(), retries
            except self._RETRYABLE_ERRORS as e:
                if attempt == self._MAX_RETRIES:
                    if "429" in str(e) or "ResourceExhausted" in str(e):
                        raise RateLimitException(msg=str(e), provider="VertexAI") from e
                    raise

                retries += 1
                delay = min(self._INITIAL_RETRY_DELAY * (2 ** attempt), self._MAX_RETRY_DELAY)
                self.logger.warning(f"⚠️ {context} Retry {attempt + 1}: {e}. Wait {delay}s.")
                time.sleep(delay)
        return None, retries

    def _log_payload(self, phase: str, timestamp: str, data: Any):
        if not self.debug_dir: return
        try:
            def default_ser(obj):
                return str(obj)

            path = self.debug_dir / f"{self.caller_class}_{timestamp}_{phase}.json"
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=default_ser),
                encoding='utf-8'
            )
        except (OSError, TypeError):
            pass

    def _log_error(self, e: Exception, context: str, timestamp: str):
        if not self.debug_dir: return
        self._log_payload("error", timestamp, {
            "context": context,
            "error_type": type(e).__name__,
            "message": str(e)
        })

    def _get_caller_class_name(self) -> str:
        frame = inspect.currentframe()
        while frame:
            frame = frame.f_back
            if not frame: break
            if 'self' in frame.f_locals:
                return frame.f_locals['self'].__class__.__name__
        return "Unknown"

    @staticmethod
    def normalize_usage(response: Any) -> Dict[str, Any]:
        usage_dict = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "request_count": 1
        }
        meta = getattr(response, 'usage_metadata', None)
        if meta:
            usage_dict["prompt_tokens"] = getattr(meta, 'prompt_token_count', 0) or 0
            usage_dict["completion_tokens"] = getattr(meta, 'candidates_token_count', 0) or 0
            usage_dict["total_tokens"] = getattr(meta, 'total_token_count', 0) or 0
            usage_dict["cached_tokens"] = getattr(meta, 'cached_content_token_count', 0) or 0
        return usage_dict