"""
LLM Client — unified async interface for OpenAI, Anthropic, Ollama.

Supports:
- Async and streaming (SSE) inference
- JSON mode / structured output
- Token usage tracking
- Retry with exponential backoff
- Automatic fallback: LLM → rule-based
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = ""
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class LLMClient:
    """Unified async LLM client.

    Environment variables
    ---------------------
    LLM_PROVIDER : str
        ``openai`` | ``anthropic`` | ``ollama`` | ``none`` (default stub)
    OPENAI_API_KEY : str
    OPENAI_MODEL : str (default ``gpt-4o-mini``)
    OPENAI_BASE_URL : str (optional, for proxies / Azure)
    ANTHROPIC_API_KEY : str
    ANTHROPIC_MODEL : str (default ``claude-3-5-sonnet-20241022``)
    OLLAMA_HOST : str (default ``http://localhost:11434``)
    OLLAMA_MODEL : str (default ``llama3.1``)
    LLM_MAX_RETRIES : int (default 2)
    LLM_TIMEOUT_SEC : float (default 60.0)
    """

    def __init__(self, provider: Optional[str] = None) -> None:
        self.provider = (provider or _env("LLM_PROVIDER", "none")).lower()
        self._total_usage = TokenUsage()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def total_usage(self) -> TokenUsage:
        return self._total_usage

    async def infer(
        self,
        prompt: str,
        *,
        system: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """Single-shot inference (non-streaming)."""
        t0 = time.perf_counter()
        response = await self._dispatch(
            prompt=prompt,
            system=system,
            messages=messages,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        response.latency_ms = (time.perf_counter() - t0) * 1000
        self._total_usage += response.usage
        return response

    async def infer_stream(
        self,
        prompt: str,
        *,
        system: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Streaming inference — yields text chunks."""
        t0 = time.perf_counter()
        text_parts: List[str] = []
        async for chunk in self._dispatch_stream(
            prompt=prompt,
            system=system,
            messages=messages,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            text_parts.append(chunk)
            yield chunk
        # Approximate token usage for streaming (not all providers return counts)
        full_text = "".join(text_parts)
        approx_tokens = max(1, len(full_text) // 4)
        self._total_usage += TokenUsage(
            prompt_tokens=len(prompt) // 4,
            completion_tokens=approx_tokens,
            total_tokens=len(prompt) // 4 + approx_tokens,
        )
        _ = time.perf_counter() - t0

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        prompt: str,
        system: str,
        messages: Optional[List[Dict[str, str]]],
        json_mode: bool,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> LLMResponse:
        retries = _env_int("LLM_MAX_RETRIES", 2)
        last_err: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                if self.provider == "openai":
                    return await self._openai_infer(prompt, system, messages, json_mode, temperature, max_tokens)
                if self.provider == "anthropic":
                    return await self._anthropic_infer(prompt, system, messages, json_mode, temperature, max_tokens)
                if self.provider == "ollama":
                    return await self._ollama_infer(prompt, system, messages, json_mode, temperature, max_tokens)
                # stub
                return LLMResponse(
                    text="LLM provider is not configured. This is a local prototype stub.",
                    provider="stub",
                )
            except Exception as exc:
                last_err = exc
                if attempt < retries:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
        raise RuntimeError(f"LLM call failed after {retries + 1} attempts: {last_err}")

    async def _dispatch_stream(
        self,
        prompt: str,
        system: str,
        messages: Optional[List[Dict[str, str]]],
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        retries = _env_int("LLM_MAX_RETRIES", 2)
        last_err: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                if self.provider == "openai":
                    async for chunk in self._openai_stream(prompt, system, messages, json_mode, temperature, max_tokens):
                        yield chunk
                    return
                if self.provider == "ollama":
                    async for chunk in self._ollama_stream(prompt, system, messages, json_mode, temperature, max_tokens):
                        yield chunk
                    return
                if self.provider == "anthropic":
                    async for chunk in self._anthropic_stream(prompt, system, messages, json_mode, temperature, max_tokens):
                        yield chunk
                    return
                # stub
                yield "LLM provider is not configured. This is a local prototype stub."
                return
            except Exception as exc:
                last_err = exc
                if attempt < retries:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
        raise RuntimeError(f"LLM streaming failed after {retries + 1} attempts: {last_err}")

    # ------------------------------------------------------------------
    # OpenAI (v1.x SDK)
    # ------------------------------------------------------------------

    async def _openai_infer(
        self, prompt: str, system: str, messages: Optional[List[Dict[str, str]]],
        json_mode: bool, temperature: float, max_tokens: int,
    ) -> LLMResponse:
        import openai

        api_key = _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        base_url = _env("OPENAI_BASE_URL")
        model = _env("OPENAI_MODEL", "gpt-4o-mini")

        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=_env_float("LLM_TIMEOUT_SEC", 60.0),
        )
        msgs = _build_messages(prompt, system, messages)

        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            provider="openai",
            model=model,
            usage=TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
                total_tokens=resp.usage.total_tokens if resp.usage else 0,
            ),
            finish_reason=choice.finish_reason or "",
        )

    async def _openai_stream(
        self, prompt: str, system: str, messages: Optional[List[Dict[str, str]]],
        json_mode: bool, temperature: float, max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        import openai

        api_key = _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        base_url = _env("OPENAI_BASE_URL")
        model = _env("OPENAI_MODEL", "gpt-4o-mini")

        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=_env_float("LLM_TIMEOUT_SEC", 60.0),
        )
        msgs = _build_messages(prompt, system, messages)

        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        stream_resp = await client.chat.completions.create(**kwargs)
        async for chunk in stream_resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ------------------------------------------------------------------
    # Anthropic (Messages API)
    # ------------------------------------------------------------------

    async def _anthropic_infer(
        self, prompt: str, system: str, messages: Optional[List[Dict[str, str]]],
        json_mode: bool, temperature: float, max_tokens: int,
    ) -> LLMResponse:
        import anthropic

        api_key = _env("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        model = _env("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        msgs = _build_anthropic_messages(prompt, messages)
        sys_prompt = system or "You are a helpful assistant."

        kwargs: Dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=sys_prompt,
            messages=msgs,
            temperature=temperature,
        )

        resp = await client.messages.create(**kwargs)
        text = ""
        for block in resp.content:
            if block.type == "text":
                text += block.text
        return LLMResponse(
            text=text,
            provider="anthropic",
            model=model,
            usage=TokenUsage(
                prompt_tokens=resp.usage.input_tokens if resp.usage else 0,
                completion_tokens=resp.usage.output_tokens if resp.usage else 0,
                total_tokens=(resp.usage.input_tokens + resp.usage.output_tokens) if resp.usage else 0,
            ),
            finish_reason=resp.stop_reason or "",
        )

    async def _anthropic_stream(
        self, prompt: str, system: str, messages: Optional[List[Dict[str, str]]],
        json_mode: bool, temperature: float, max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        import anthropic

        api_key = _env("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        model = _env("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        msgs = _build_anthropic_messages(prompt, messages)
        sys_prompt = system or "You are a helpful assistant."

        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=sys_prompt,
            messages=msgs,
            temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    # ------------------------------------------------------------------
    # Ollama (local)
    # ------------------------------------------------------------------

    async def _ollama_infer(
        self, prompt: str, system: str, messages: Optional[List[Dict[str, str]]],
        json_mode: bool, temperature: float, max_tokens: int,
    ) -> LLMResponse:
        import httpx

        host = _env("OLLAMA_HOST", "http://localhost:11434")
        model = _env("OLLAMA_MODEL", "llama3.1")
        msgs = _build_messages(prompt, system, messages)

        payload: Dict[str, Any] = dict(
            model=model,
            messages=msgs,
            stream=False,
            options=dict(temperature=temperature, num_predict=max_tokens),
        )
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=_env_float("LLM_TIMEOUT_SEC", 120.0)) as client:
            resp = await client.post(f"{host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            provider="ollama",
            model=model,
            usage=TokenUsage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            ),
            finish_reason=data.get("done_reason", ""),
        )

    async def _ollama_stream(
        self, prompt: str, system: str, messages: Optional[List[Dict[str, str]]],
        json_mode: bool, temperature: float, max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        import httpx

        host = _env("OLLAMA_HOST", "http://localhost:11434")
        model = _env("OLLAMA_MODEL", "llama3.1")
        msgs = _build_messages(prompt, system, messages)

        payload: Dict[str, Any] = dict(
            model=model,
            messages=msgs,
            stream=True,
            options=dict(temperature=temperature, num_predict=max_tokens),
        )
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=_env_float("LLM_TIMEOUT_SEC", 300.0)) as client:
            async with client.stream("POST", f"{host}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_messages(
    prompt: str,
    system: str,
    messages: Optional[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """Build OpenAI/Ollama-compatible message list."""
    if messages:
        return messages
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return msgs


def _build_anthropic_messages(
    prompt: str,
    messages: Optional[List[Dict[str, str]]],
) -> List[Dict[str, Any]]:
    """Build Anthropic Messages-API-compatible list (no system role in messages)."""
    if messages:
        return [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    return [{"role": "user", "content": prompt}]


# ---------------------------------------------------------------------------
# Singleton convenience
# ---------------------------------------------------------------------------

_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
