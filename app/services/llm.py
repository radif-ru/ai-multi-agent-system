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
        temperature: float = 0.0,
        keep_alive: str = "5m",
        max_concurrency: int = 1,
    ) -> None:
        self._client = AsyncClient(host=base_url, timeout=timeout)
        self._num_ctx = num_ctx
        self._think = think
        self._temperature = temperature
        self._keep_alive = keep_alive
        # Общий gate на весь процесс: ограничивает одновременные обращения к
        # Ollama (chat + embed), чтобы live-запросы и фоновый recovery не
        # устраивали пайл-ап на GPU. См. `_docs/architecture.md` §3.4.
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        temperature: float | None = None,
        think: bool | None = None,
    ) -> str:
        think_value = self._think if think is None else think
        temperature_value = self._temperature if temperature is None else temperature
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
                    keep_alive=self._keep_alive,
                    options={"temperature": temperature_value, "num_ctx": self._num_ctx},
                )
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                self._log_call("chat", model, len_in, 0, started, "timeout", queue_wait_ms, think_value)
                raise LLMTimeout(f"chat timeout: {exc}") from exc
            except httpx.ConnectError as exc:
                self._log_call("chat", model, len_in, 0, started, "unavailable", queue_wait_ms, think_value)
                raise LLMUnavailable(f"chat connection error: {exc}") from exc
            except ResponseError as exc:
                self._log_call("chat", model, len_in, 0, started, f"http {exc.status_code}", queue_wait_ms, think_value)
                if exc.status_code == 404:
                    raise LLMBadResponse(f"model not found: {exc.error}") from exc
                raise LLMBadResponse(f"chat http error {exc.status_code}: {exc.error}") from exc

            content = (resp.message.content or "") if resp.message else ""
            if not content:
                self._log_call("chat", model, len_in, 0, started, "empty", queue_wait_ms, think_value)
                raise LLMBadResponse("chat empty response")
            # Метрики производительности из ответа Ollama
            eval_count = getattr(resp, "eval_count", None)
            eval_duration_ns = getattr(resp, "eval_duration", None)
            out_tok = int(eval_count) if eval_count is not None else None
            tok_per_s = None
            if eval_count is not None and eval_duration_ns is not None and eval_duration_ns > 0:
                tok_per_s = round(eval_count / (eval_duration_ns / 1_000_000_000), 2)
            self._log_call("chat", model, len_in, len(content), started, "ok", queue_wait_ms, think_value, out_tok, tok_per_s)
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
                self._log_call("embed", model, len_in, 0, started, "timeout", queue_wait_ms, False)
                raise LLMTimeout(f"embed timeout: {exc}") from exc
            except httpx.ConnectError as exc:
                self._log_call("embed", model, len_in, 0, started, "unavailable", queue_wait_ms, False)
                raise LLMUnavailable(f"embed connection error: {exc}") from exc
            except ResponseError as exc:
                self._log_call("embed", model, len_in, 0, started, f"http {exc.status_code}", queue_wait_ms, False)
                if exc.status_code == 404:
                    raise LLMBadResponse(f"embedding model not found: {exc.error}") from exc
                raise LLMBadResponse(f"embed http error {exc.status_code}: {exc.error}") from exc

            embedding = list(resp.embedding or [])
            if not embedding:
                self._log_call("embed", model, len_in, 0, started, "empty", queue_wait_ms, False)
                raise LLMBadResponse("embed empty response")
            self._log_call("embed", model, len_in, len(embedding), started, "ok", queue_wait_ms, False)
            return embedding

    async def list_models(self) -> dict[str, int]:
        """Локальные модели Ollama как `{tag: size_bytes}`.

        Используется командой `/models` (показ размеров) и `/model`
        (VRAM-предупреждение). При недоступности Ollama возвращает пустой
        dict — graceful degradation, чтобы команда работала и без размеров.
        """
        async with self._semaphore:
            try:
                resp = await self._client.list()
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                ResponseError,
                asyncio.TimeoutError,
            ) as exc:
                logger.warning("ollama list failed: %s", exc)
                return {}
        sizes: dict[str, int] = {}
        for model in getattr(resp, "models", None) or []:
            name = getattr(model, "model", None) or getattr(model, "name", None)
            size = getattr(model, "size", None)
            if name and size is not None:
                sizes[str(name)] = int(size)
        return sizes

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
        think: bool = False,
        out_tok: int | None = None,
        tok_per_s: float | None = None,
    ) -> None:
        dur_ms = int((time.monotonic() - started) * 1000)
        event = "external.ok" if status == "ok" else "external.fail"
        log_fn = logger.info if status == "ok" else logger.error
        extra = {
            "service": "ollama",
            "kind": kind,
            "model": model,
            "len_in": len_in,
            "len_out": len_out,
            "duration_ms": dur_ms,
            "queue_wait_ms": queue_wait_ms,
            "status": status,
            "think": think,
        }
        if out_tok is not None:
            extra["out_tok"] = out_tok
        if tok_per_s is not None:
            extra["tok_per_s"] = tok_per_s
        log_fn(
            "%s service=ollama kind=%s model=%s dur_ms=%d queue_wait_ms=%d status=%s think=%s",
            event,
            kind,
            model,
            dur_ms,
            queue_wait_ms,
            status,
            think,
            extra=extra,
        )
