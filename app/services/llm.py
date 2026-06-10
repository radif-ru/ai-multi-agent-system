"""LLM-клиент над Ollama.

См. `_docs/architecture.md` §3.4 и `_docs/testing.md` §3.2.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Sequence

import httpx
from ollama import AsyncClient, ResponseError

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Базовое исключение LLM-слоя."""


class LLMTimeout(LLMError):
    """Таймаут при обращении к LLM."""


class LLMUnavailable(LLMError):
    """LLM недоступна (connection refused и т.п.)."""


class LLMBadResponse(LLMError):
    """LLM вернула некорректный ответ (битый JSON, 4xx/5xx, пустой ответ)."""


class OllamaClient:
    """Async-клиент над `ollama.AsyncClient` с явной обработкой ошибок."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        num_ctx: int = 8192,
        think: bool = False,
        max_concurrency: int = 1,
    ) -> None:
        self._client = AsyncClient(host=base_url, timeout=timeout)
        self._num_ctx = num_ctx
        self._think = think
        # Общий gate на весь процесс: ограничивает одновременные обращения к
        # Ollama (chat + embed), чтобы live-запросы и фоновый recovery не
        # устраивали пайл-ап на GPU. См. `_docs/architecture.md` §3.4.
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        think: bool | None = None,
    ) -> str:
        think_value = self._think if think is None else think
        len_in = sum(len(m.get("content", "")) for m in messages)
        queue_started = time.monotonic()
        async with self._semaphore:
            queue_wait_ms = int((time.monotonic() - queue_started) * 1000)
            started = time.monotonic()
            try:
                resp = await self._client.chat(
                    model=model,
                    messages=list(messages),
                    think=think_value,
                    options={"temperature": temperature, "num_ctx": self._num_ctx},
                )
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                self._log_call("chat", model, len_in, 0, started, "timeout", queue_wait_ms)
                raise LLMTimeout(f"chat timeout: {exc}") from exc
            except httpx.ConnectError as exc:
                self._log_call("chat", model, len_in, 0, started, "unavailable", queue_wait_ms)
                raise LLMUnavailable(f"chat connection error: {exc}") from exc
            except ResponseError as exc:
                self._log_call("chat", model, len_in, 0, started, f"http {exc.status_code}", queue_wait_ms)
                if exc.status_code == 404:
                    raise LLMBadResponse(f"model not found: {exc.error}") from exc
                raise LLMBadResponse(f"chat http error {exc.status_code}: {exc.error}") from exc

            content = (resp.message.content or "") if resp.message else ""
            if not content:
                self._log_call("chat", model, len_in, 0, started, "empty", queue_wait_ms)
                raise LLMBadResponse("chat empty response")
            self._log_call("chat", model, len_in, len(content), started, "ok", queue_wait_ms)
            return content

    async def embed(self, text: str, *, model: str) -> list[float]:
        len_in = len(text)
        queue_started = time.monotonic()
        async with self._semaphore:
            queue_wait_ms = int((time.monotonic() - queue_started) * 1000)
            started = time.monotonic()
            try:
                resp = await self._client.embeddings(model=model, prompt=text)
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                self._log_call("embed", model, len_in, 0, started, "timeout", queue_wait_ms)
                raise LLMTimeout(f"embed timeout: {exc}") from exc
            except httpx.ConnectError as exc:
                self._log_call("embed", model, len_in, 0, started, "unavailable", queue_wait_ms)
                raise LLMUnavailable(f"embed connection error: {exc}") from exc
            except ResponseError as exc:
                self._log_call("embed", model, len_in, 0, started, f"http {exc.status_code}", queue_wait_ms)
                if exc.status_code == 404:
                    raise LLMBadResponse(f"embedding model not found: {exc.error}") from exc
                raise LLMBadResponse(f"embed http error {exc.status_code}: {exc.error}") from exc

            embedding = list(resp.embedding or [])
            if not embedding:
                self._log_call("embed", model, len_in, 0, started, "empty", queue_wait_ms)
                raise LLMBadResponse("embed empty response")
            self._log_call("embed", model, len_in, len(embedding), started, "ok", queue_wait_ms)
            return embedding

    async def close(self) -> None:
        # ollama.AsyncClient наследует httpx.AsyncClient; aclose закрывает соединения.
        aclose = getattr(self._client, "aclose", None)
        if aclose is not None:
            await aclose()

    @staticmethod
    def estimate_tokens(value: str | Sequence[dict[str, Any]]) -> int:
        if isinstance(value, str):
            return max(1, len(value) // 4)
        total = sum(len(m.get("content", "")) for m in value)
        return max(1, total // 4)

    @staticmethod
    def _log_call(
        kind: str,
        model: str,
        len_in: int,
        len_out: int,
        started: float,
        status: str,
        queue_wait_ms: int = 0,
    ) -> None:
        dur_ms = int((time.monotonic() - started) * 1000)
        event = "external.ok" if status == "ok" else "external.fail"
        log_fn = logger.info if status == "ok" else logger.error
        log_fn(
            "%s service=ollama kind=%s model=%s dur_ms=%d queue_wait_ms=%d status=%s",
            event,
            kind,
            model,
            dur_ms,
            queue_wait_ms,
            status,
            extra={
                "service": "ollama",
                "kind": kind,
                "model": model,
                "len_in": len_in,
                "len_out": len_out,
                "duration_ms": dur_ms,
                "queue_wait_ms": queue_wait_ms,
                "status": status,
            },
        )
