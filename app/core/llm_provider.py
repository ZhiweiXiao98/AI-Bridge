"""
LLM 统一接口 (LLM Provider)

职责：抽象 LLM 调用，支持 API 直连/ 浏览器双通道
设计原则：只负责"把消息发出去"，不关心上下文如何组装

参考: docs/context_system_plan.md
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, AsyncIterator, Optional, Tuple

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
    api_key: str = ""
    base_url: str = DEFAULT_API_BASE_URL
    model: str = DEFAULT_API_MODEL
    temperature: float = 0.7
    max_output_tokens: int = 4096
    timeout: int = 60
    proxy_url: str = ""


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
        )
        self._async_client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            http_client=self._async_http_client,
        )
        logger.info(f"APIProvider 初始化: {self.config.base_url} / {self.config.model} / proxy={self.config.proxy_url or '-'}")

    def chat(self, messages: List[dict]) -> str:
        """同步调用"""
        try:
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_output_tokens,
            )
            content = response.choices[0].message.content or ""
            logger.info(
                f"API 回复: {response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens"
            )
            return content
        except Exception as e:
            logger.error(f"API 调用失败: {e}")
            raise
    async def stream_chat(self, messages: List[dict]) -> AsyncIterator[str]:
        """流式调用，逐 chunk 返回（使用同步客户端避免事件循环问题）"""
        try:
            def _sync_stream():
                """在线程中调用同步客户端的流式接口"""
                return self._client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_output_tokens,
                    stream=True,
                )
            
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
                if delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"API 流式调用失败: {e}")
            raise

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
            )
            self._async_client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                http_client=self._async_http_client,
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
            if role == 'system':
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

    if provider_type in ("api", "openai_compatible"):
        api_conf = config_dict.get("api", {})
        return APIProvider(ProviderConfig(**api_conf))

    if provider_type == "gemini":
        gemini_conf = config_dict.get("gemini", {})
        return GeminiProvider(ProviderConfig(**gemini_conf))

    # Phase 4: BrowserProvider
    # elif provider_type == "browser":
    #     return BrowserProvider(...)

    raise ValueError(f"未知的 provider类型: {provider_type}")