"""
LLM 统一接口 (LLM Provider)

职责：抽象 LLM 调用，支持 API 直连/ 浏览器双通道
设计原则：只负责"把消息发出去"，不关心上下文如何组装

参考: docs/上下文系统建设计划.md
"""

import asyncio
import logging
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, AsyncIterator, Optional, Tuple

import httpx
from openai import OpenAI, AsyncOpenAI
from google import genai
from google.genai import types as genai_types
from app.core.app_constants import DEFAULT_API_BASE_URL, DEFAULT_API_MODEL
from app.core.logging import get_logger

logger = get_logger("app.core.llm_provider", side="worker")


#============================================================
# 配置
# ============================================================

@dataclass
class ProviderConfig:
    """LLM 提供商配置"""
    provider: str = "openai_compatible"
    api_key: str = ""
    base_url: str = DEFAULT_API_BASE_URL
    model: str = DEFAULT_API_MODEL
    temperature: float = 0.7
    max_output_tokens: int = 4096
    timeout: int = 60
    proxy_url: str = ""
    supports_reasoning: bool = False
    reasoning_enabled: bool = False
    reasoning_effort: str = "medium"


# ============================================================
# 抽象基类
# ============================================================

class LLMProvider(ABC):
    """LLM 统一接口"""

    @abstractmethod
    def chat(self, messages: List[dict]) -> str:
        """同步调用，返回完整回复"""

    @abstractmethod
    async def stream_chat(self, messages: List[dict]) -> AsyncIterator[str]:
        """流式调用，逐 chunk 返回"""

    async def stream_chat_events(self, messages: List[dict]) -> AsyncIterator[Dict[str, Any]]:
        """流式调用，返回结构化增量事件。

        默认实现保持向后兼容：只把普通正文包装成 content_delta。
        支持 reasoning 的 provider 可覆写并额外产出 thinking_delta。
        """
        async for chunk in self.stream_chat(messages):
            if chunk:
                yield {"type": "content_delta", "content": chunk}

    def probe_tool_support(self) -> Dict[str, Any]:
        return {
            "status": "unsupported",
            "reason": "provider_probe_not_implemented",
            "protocol": "markdown_fallback",
        }

    def list_models(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "models": [],
            "reason": "provider_model_probe_not_implemented",
        }

    def chat_with_tools(self, messages: List[dict], tools: List[dict]) -> Dict[str, Any]:
        return {
            "content": self.chat(messages),
            "tool_calls": [],
            "raw_message": None,
        }

    async def stream_chat_with_tools(self, messages: List[dict], tools: List[dict]) -> AsyncIterator[Dict[str, Any]]:
        content_parts: List[str] = []
        async for chunk in self.stream_chat(messages):
            content_parts.append(chunk)
            yield {"type": "content_delta", "content": chunk}
        yield {
            "type": "message_end",
            "content": "".join(content_parts),
            "tool_calls": [],
            "raw_message": None,
        }


def _build_httpx_clients(config: ProviderConfig):
    proxy = str(config.proxy_url or '').strip() or None
    http_client = httpx.Client(proxy=proxy, timeout=config.timeout) if proxy else httpx.Client(timeout=config.timeout)
    async_http_client = httpx.AsyncClient(proxy=proxy, timeout=config.timeout) if proxy else httpx.AsyncClient(timeout=config.timeout)
    return http_client, async_http_client


def _build_gemini_client(config: ProviderConfig):
    proxy = str(config.proxy_url or '').strip()
    if proxy:
        try:
            return genai.Client(
                api_key=config.api_key,
                http_options=genai_types.HttpOptions(
                    client_args={
                        'proxy': proxy,
                        'timeout': config.timeout,
                    },
                    async_client_args={
                        'proxy': proxy,
                        'timeout': config.timeout,
                    },
                ),
            )
        except Exception as e:
            logger.warning(f"Gemini 显式代理注入失败(HttpOptions.client_args)，回退默认客户端: {e}")
            return genai.Client(api_key=config.api_key)

    return genai.Client(api_key=config.api_key)


# ============================================================
# API 直连（OpenAI 兼容）
# ============================================================

class APIProvider(LLMProvider):
    """
    直接调 OpenAI 兼容 API
    支持: OpenAI / Claude / Deepseek /本地模型
    """

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig()
        self._http_client, self._async_http_client = _build_httpx_clients(self.config)
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            http_client=self._http_client,
            default_headers=self._default_headers(),
        )
        self._async_client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            http_client=self._async_http_client,
            default_headers=self._default_headers(),
        )
        logger.info(f"APIProvider 初始化: {self.config.base_url} / {self.config.model} / proxy={self.config.proxy_url or '-'}")

    def _is_mimo(self) -> bool:
        provider = str(getattr(self.config, "provider", "") or "").strip().lower()
        base_url = str(getattr(self.config, "base_url", "") or "").strip().lower()
        return provider == "mimo" or "xiaomimimo.com" in base_url

    def _default_headers(self) -> Dict[str, str]:
        if self._is_mimo() and self.config.api_key:
            return {"api-key": self.config.api_key}
        return {}

    def _max_tokens_kwargs(self, value: Optional[int] = None) -> Dict[str, int]:
        tokens = int(value or self.config.max_output_tokens or 4096)
        if self._is_mimo():
            return {"max_completion_tokens": tokens}
        return {"max_tokens": tokens}

    def _extra_body_kwargs(self, *, force_disable_thinking: bool = False) -> Dict[str, Any]:
        if not self._is_mimo():
            return {}
        thinking_type = "enabled" if (self.config.reasoning_enabled and not force_disable_thinking) else "disabled"
        return {"extra_body": {"thinking": {"type": thinking_type}}}

    def _chat_create_kwargs(
        self,
        messages: List[dict],
        *,
        stream: bool = False,
        tools: Optional[List[dict]] = None,
        tool_choice: Any = None,
        max_tokens: Optional[int] = None,
        force_disable_thinking: bool = False,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": stream,
        }
        kwargs.update(self._max_tokens_kwargs(max_tokens))
        kwargs.update(self._extra_body_kwargs(force_disable_thinking=force_disable_thinking))
        if (
            not self._is_mimo()
            and self.config.supports_reasoning
            and self.config.reasoning_enabled
            and not force_disable_thinking
        ):
            effort = str(self.config.reasoning_effort or "medium").strip().lower()
            kwargs["reasoning_effort"] = effort if effort in ("low", "medium", "high") else "medium"
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return kwargs

    def chat(self, messages: List[dict]) -> str:
        """同步调用"""
        try:
            response = self._client.chat.completions.create(**self._chat_create_kwargs(messages))
            content = response.choices[0].message.content or ""
            logger.info(
                f"API 回复: {response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens"
            )
            return content
        except Exception as e:
            logger.error(f"API 调用失败: {e}")
            raise

    def chat_with_tools(self, messages: List[dict], tools: List[dict]) -> Dict[str, Any]:
        """同步调用 OpenAI-compatible native tools，返回归一化消息。"""
        try:
            response = self._client.chat.completions.create(**self._chat_create_kwargs(
                messages,
                tools=tools,
                tool_choice="auto",
                force_disable_thinking=True,
            ))
            message = response.choices[0].message if response.choices else None
            content = getattr(message, "content", "") if message is not None else ""
            tool_calls = self._normalize_tool_calls(getattr(message, "tool_calls", None) if message is not None else None)
            usage = getattr(response, "usage", None)
            if usage is not None:
                logger.info(
                    "API native tools 回复: %s+%s tokens | tool_calls=%d",
                    getattr(usage, "prompt_tokens", "?"),
                    getattr(usage, "completion_tokens", "?"),
                    len(tool_calls),
                )
            else:
                logger.info("API native tools 回复 | tool_calls=%d", len(tool_calls))
            return {
                "content": content or "",
                "tool_calls": tool_calls,
                "raw_message": message,
            }
        except Exception as e:
            logger.error(f"API native tools 调用失败: {e}")
            raise

    @staticmethod
    def _normalize_tool_calls(tool_calls) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for call in tool_calls or []:
            if isinstance(call, dict):
                call_id = call.get("id") or ""
                call_type = call.get("type") or "function"
                fn = call.get("function") or {}
                name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", "")
                arguments = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "")
            else:
                call_id = getattr(call, "id", "") or ""
                call_type = getattr(call, "type", "function") or "function"
                fn = getattr(call, "function", None)
                name = getattr(fn, "name", "") if fn is not None else ""
                arguments = getattr(fn, "arguments", "") if fn is not None else ""

            normalized.append({
                "id": str(call_id),
                "type": str(call_type or "function"),
                "function": {
                    "name": str(name or ""),
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments or {}, ensure_ascii=False),
                },
            })
        return normalized

    @staticmethod
    def _value_to_delta_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            return "".join(APIProvider._value_to_delta_text(item) for item in value)
        if isinstance(value, dict):
            for key in ("text", "content", "value", "reasoning_content", "reasoning", "thinking"):
                if key in value:
                    text = APIProvider._value_to_delta_text(value.get(key))
                    if text:
                        return text
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        return str(value)

    @staticmethod
    def _delta_mapping(delta: Any) -> Dict[str, Any]:
        if isinstance(delta, dict):
            return delta
        for attr in ("model_dump", "dict"):
            method = getattr(delta, attr, None)
            if callable(method):
                try:
                    data = method()
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
        return {}

    @classmethod
    def _delta_field(cls, delta: Any, names: tuple[str, ...]) -> str:
        mapping = cls._delta_mapping(delta)
        extras = []
        for extra_name in ("model_extra", "__pydantic_extra__"):
            extra = getattr(delta, extra_name, None)
            if isinstance(extra, dict):
                extras.append(extra)
        for name in names:
            value = None
            if isinstance(delta, dict):
                value = delta.get(name)
            else:
                value = getattr(delta, name, None)
            if value is None and mapping:
                value = mapping.get(name)
            if value is None:
                for extra in extras:
                    value = extra.get(name)
                    if value is not None:
                        break
            text = cls._value_to_delta_text(value)
            if text:
                return text
        return ""

    @classmethod
    def _extract_stream_delta(cls, delta: Any) -> tuple[str, str]:
        content = cls._delta_field(delta, ("content",))
        thinking = cls._delta_field(delta, (
            "reasoning_content",
            "reasoning",
            "thinking",
            "thought",
            "analysis",
            "reasoning_details",
        ))
        return content, thinking

    async def stream_chat(self, messages: List[dict]) -> AsyncIterator[str]:
        """流式调用，逐 chunk 返回（使用同步客户端避免事件循环问题）"""
        try:
            def _sync_stream():
                """在线程中调用同步客户端的流式接口"""
                return self._client.chat.completions.create(**self._chat_create_kwargs(messages, stream=True))

            stream = await asyncio.to_thread(_sync_stream)
            _SENTINEL = object()

            def _next_chunk():
                """在线程内捕获 StopIteration，避免通过 Future 传播"""
                try:
                    return next(stream)
                except StopIteration:
                    return _SENTINEL

            while True:
                chunk = await asyncio.to_thread(_next_chunk)
                if chunk is _SENTINEL:
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content, _thinking = self._extract_stream_delta(delta)
                if content:
                    yield content
        except Exception as e:
            logger.error(f"API 流式调用失败: {e}")
            raise

    async def stream_chat_events(self, messages: List[dict]) -> AsyncIterator[Dict[str, Any]]:
        """流式调用，逐 chunk 返回正文与 reasoning/thinking 增量。"""
        try:
            def _sync_stream():
                return self._client.chat.completions.create(**self._chat_create_kwargs(messages, stream=True))

            stream = await asyncio.to_thread(_sync_stream)
            _SENTINEL = object()

            def _next_chunk():
                try:
                    return next(stream)
                except StopIteration:
                    return _SENTINEL

            while True:
                chunk = await asyncio.to_thread(_next_chunk)
                if chunk is _SENTINEL:
                    break
                if not getattr(chunk, "choices", None):
                    continue
                delta = getattr(chunk.choices[0], "delta", None)
                if delta is None:
                    continue
                content, thinking = self._extract_stream_delta(delta)
                if thinking:
                    yield {
                        "type": "thinking_delta",
                        "content": thinking,
                        "reasoning_content": thinking,
                    }
                if content:
                    yield {"type": "content_delta", "content": content}
        except Exception as e:
            logger.error(f"API 流式事件调用失败: {e}")
            raise

    async def stream_chat_with_tools(self, messages: List[dict], tools: List[dict]) -> AsyncIterator[Dict[str, Any]]:
        """流式调用 OpenAI-compatible native tools，结束时返回归一化 tool_calls。"""
        try:
            def _sync_stream():
                return self._client.chat.completions.create(**self._chat_create_kwargs(
                    messages,
                    stream=True,
                    tools=tools,
                    tool_choice="auto",
                    force_disable_thinking=True,
                ))

            stream = await asyncio.to_thread(_sync_stream)
            _SENTINEL = object()
            content_parts: List[str] = []
            tool_call_parts: Dict[int, Dict[str, Any]] = {}
            order: List[int] = []

            def _next_chunk():
                try:
                    return next(stream)
                except StopIteration:
                    return _SENTINEL

            while True:
                chunk = await asyncio.to_thread(_next_chunk)
                if chunk is _SENTINEL:
                    break
                if not getattr(chunk, "choices", None):
                    continue
                delta = getattr(chunk.choices[0], "delta", None)
                if delta is None:
                    continue

                content = getattr(delta, "content", None)
                if content:
                    content_parts.append(content)
                    yield {"type": "content_delta", "content": content}

                for call_delta in getattr(delta, "tool_calls", None) or []:
                    if isinstance(call_delta, dict):
                        index = call_delta.get("index")
                        call_id = call_delta.get("id")
                        call_type = call_delta.get("type")
                        fn_delta = call_delta.get("function") or {}
                        fn_name = fn_delta.get("name") if isinstance(fn_delta, dict) else getattr(fn_delta, "name", "")
                        fn_args = fn_delta.get("arguments") if isinstance(fn_delta, dict) else getattr(fn_delta, "arguments", "")
                    else:
                        index = getattr(call_delta, "index", None)
                        call_id = getattr(call_delta, "id", None)
                        call_type = getattr(call_delta, "type", None)
                        fn_delta = getattr(call_delta, "function", None)
                        fn_name = getattr(fn_delta, "name", "") if fn_delta is not None else ""
                        fn_args = getattr(fn_delta, "arguments", "") if fn_delta is not None else ""

                    try:
                        index = int(index)
                    except Exception:
                        index = len(order)
                    if index not in tool_call_parts:
                        tool_call_parts[index] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                        order.append(index)
                    current = tool_call_parts[index]
                    if call_id:
                        current["id"] = str(call_id)
                    if call_type:
                        current["type"] = str(call_type)
                    if fn_name:
                        current["function"]["name"] += str(fn_name)
                    if fn_args:
                        current["function"]["arguments"] += str(fn_args)

            tool_calls = [tool_call_parts[idx] for idx in sorted(order)]
            yield {
                "type": "message_end",
                "content": "".join(content_parts),
                "tool_calls": self._normalize_tool_calls(tool_calls),
                "raw_message": None,
            }
        except Exception as e:
            logger.error(f"API native tools 流式调用失败: {e}")
            raise

    def probe_tool_support(self) -> Dict[str, Any]:
        """Probe whether the OpenAI-compatible endpoint supports native tools."""
        probe_tool = {
            "type": "function",
            "function": {
                "name": "probe_tool",
                "description": "Capability probe. Do not use for real work.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean", "description": "Return true for probe."}
                    },
                    "required": ["ok"],
                },
            },
        }
        messages = [
            {"role": "system", "content": "You are checking tool-calling capability."},
            {"role": "user", "content": "Call probe_tool with ok=true."},
        ]

        def _request(tool_choice_marker):
            kwargs = {
                **self._chat_create_kwargs(
                    messages,
                    tools=[probe_tool],
                    max_tokens=64,
                    force_disable_thinking=True,
                ),
                "temperature": 0,
            }
            if tool_choice_marker == "forced":
                kwargs["tool_choice"] = {"type": "function", "function": {"name": "probe_tool"}}
            elif tool_choice_marker == "auto":
                kwargs["tool_choice"] = "auto"
            return self._client.chat.completions.create(**kwargs)

        errors = []
        for attempt_name in ("forced", "auto", "tools_only"):
            try:
                response = _request(attempt_name)
                message = response.choices[0].message if response.choices else None
                tool_calls = getattr(message, "tool_calls", None) if message is not None else None
                if tool_calls:
                    return {
                        "status": "supported",
                        "reason": "",
                        "protocol": "native_tools",
                        "probe_attempt": attempt_name,
                    }
                return {
                    "status": "partial",
                    "reason": f"tools_request_succeeded_without_tool_calls:{attempt_name}",
                    "protocol": "markdown_fallback",
                    "probe_attempt": attempt_name,
                }
            except Exception as e:
                err = str(e)
                errors.append(f"{attempt_name}: {err[:240]}")
                err_lower = err.lower()
                if attempt_name == "forced" and ("tool_choice" in err_lower or "tool choice" in err_lower):
                    continue
                if attempt_name == "auto" and ("tool_choice" in err_lower or "tool choice" in err_lower):
                    continue
                logger.debug("APIProvider 工具探测尝试失败 | attempt=%s | error=%s", attempt_name, err[:200])

        err_joined = " | ".join(errors)
        err_lower = err_joined.lower()
        unsupported_markers = (
            "tools",
            "function",
            "unsupported",
            "unrecognized",
            "unknown parameter",
            "invalid parameter",
            "extra inputs are not permitted",
        )
        status = "unsupported" if any(marker in err_lower for marker in unsupported_markers) else "partial"
        logger.warning("APIProvider 工具能力探测失败 | status=%s | error=%s", status, err_joined[:300])
        return {
            "status": status,
            "reason": err_joined[:500],
            "protocol": "markdown_fallback",
        }

    def list_models(self) -> Dict[str, Any]:
        """Probe available models from an OpenAI-compatible /models endpoint."""
        try:
            response = self._client.models.list()
            raw_models = getattr(response, "data", None)
            if raw_models is None and isinstance(response, dict):
                raw_models = response.get("data", [])
            models = []
            for item in raw_models or []:
                model_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", "")
                model_id = str(model_id or "").strip()
                if model_id:
                    models.append(model_id)
            return {
                "ok": True,
                "models": sorted(dict.fromkeys(models)),
                "reason": "",
                "source": "models_endpoint",
                "endpoint_ok": True,
            }
        except Exception as e:
            err = str(e)
            logger.warning("APIProvider 模型列表探测失败 | error=%s", err[:300])
            return {
                "ok": False,
                "models": [],
                "reason": err[:500],
                "source": "models_endpoint",
                "endpoint_ok": False,
            }

    def update_config(self, **kwargs) -> None:
        """动态更新配置（切换模型/温度等）"""
        changed = []
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                old = getattr(self.config, key)
                setattr(self.config, key, value)
                changed.append(f"{key}: {old} -> {value}")

        # 如果 api_key 或 base_url 变了，重建客户端
        if any(k in kwargs for k in ("api_key", "base_url", "timeout", "proxy_url")):
            self._http_client, self._async_http_client = _build_httpx_clients(self.config)
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                http_client=self._http_client,
                default_headers=self._default_headers(),
            )
            self._async_client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                http_client=self._async_http_client,
                default_headers=self._default_headers(),
            )

        if changed:
            summary = ", ".join(changed)
            logger.info(f"Provider 配置更新: {summary}")



# ============================================================
# Gemini SDK Provider
# ============================================================

class GeminiProvider(LLMProvider):
    """Google Gen AI SDK provider for Gemini Developer API."""

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig()
        self._client = None
        self._rebuild_client()
        logger.info(f"GeminiProvider 初始化: model={self.config.model} / proxy={self.config.proxy_url or '-'}")

    def _rebuild_client(self):
        self._client = _build_gemini_client(self.config)

    def _split_system_and_contents(self, messages: List[dict]) -> Tuple[str, list]:
        system_parts = []
        contents = []
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get('role', 'user') or 'user').strip().lower()
            content = str(msg.get('content', '') or '')
            if not content:
                continue
            if role in ('system', 'developer'):
                system_parts.append(content)
                continue
            mapped_role = 'model' if role == 'assistant' else 'user'
            contents.append({
                'role': mapped_role,
                'parts': [{'text': content}],
            })
        return '\n\n'.join(system_parts).strip(), contents

    def _build_config(self, system_instruction: str):
        kwargs = {
            'temperature': self.config.temperature,
            'max_output_tokens': self.config.max_output_tokens,
        }
        if system_instruction:
            kwargs['system_instruction'] = system_instruction
        return genai_types.GenerateContentConfig(**kwargs)

    def chat(self, messages: List[dict]) -> str:
        try:
            system_instruction, contents = self._split_system_and_contents(messages)
            response = self._client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config=self._build_config(system_instruction),
            )
            content = getattr(response, 'text', '') or ''
            logger.info(f"Gemini 回复成功: model={self.config.model}")
            return content
        except Exception as e:
            logger.error(f"Gemini 调用失败: {e}")
            raise

    async def stream_chat(self, messages: List[dict]) -> AsyncIterator[str]:
        try:
            system_instruction, contents = self._split_system_and_contents(messages)

            def _stream_chunks():
                for chunk in self._client.models.generate_content_stream(
                    model=self.config.model,
                    contents=contents,
                    config=self._build_config(system_instruction),
                ):
                    try:
                        text = chunk.text or ''
                    except (IndexError, AttributeError, ValueError):
                        text = ''
                    if text:
                        yield text

            iterator = _stream_chunks()
            _SENTINEL = object()

            def _next_chunk():
                """在线程内捕获 StopIteration，避免通过 Future 传播"""
                try:
                    return next(iterator)
                except StopIteration:
                    return _SENTINEL

            while True:
                chunk = await asyncio.to_thread(_next_chunk)
                if chunk is _SENTINEL:
                    break
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error(f"Gemini 流式调用失败: {e}")
            raise

    def list_models(self) -> Dict[str, Any]:
        try:
            models = []
            for item in self._client.models.list():
                name = str(getattr(item, "name", "") or "").strip()
                if name.startswith("models/"):
                    name = name.split("/", 1)[1]
                if name:
                    models.append(name)
            return {
                "ok": True,
                "models": sorted(dict.fromkeys(models)),
                "reason": "",
            }
        except Exception as e:
            err = str(e)
            logger.warning("GeminiProvider 模型列表探测失败 | error=%s", err[:300])
            return {
                "ok": False,
                "models": [],
                "reason": err[:500],
            }

    def update_config(self, **kwargs) -> None:
        changed = []
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                old = getattr(self.config, key)
                setattr(self.config, key, value)
                changed.append(f"{key}: {old} -> {value}")
        if any(k in kwargs for k in ('api_key', 'timeout', 'proxy_url')):
            self._rebuild_client()
        if changed:
            logger.info(f"Gemini Provider 配置更新: {', '.join(changed)}")

# ============================================================
# 工厂函数
# ============================================================

def create_provider(config_dict: dict) -> LLMProvider:
    """
    根据配置创建 Provider

    config_dict 示例:
        {
            "provider": "api",
            "api": {
                "api_key": "sk-xxx",
                "base_url": DEFAULT_API_BASE_URL,
                "model": DEFAULT_API_MODEL
            }
        }
    """
    provider_type = config_dict.get("provider", "api")

    if provider_type in ("api", "openai_compatible", "mimo"):
        api_conf = config_dict.get("api", {})
        api_conf.setdefault("provider", provider_type)
        return APIProvider(ProviderConfig(**api_conf))

    if provider_type == "gemini":
        gemini_conf = config_dict.get("gemini", {})
        return GeminiProvider(ProviderConfig(**gemini_conf))

    # Phase 4: BrowserProvider
    # elif provider_type == "browser":
    #     return BrowserProvider(...)

    raise ValueError(f"未知的 provider类型: {provider_type}")
