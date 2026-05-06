"""
Provider fallback helpers.

with_fallback()       — wraps a single async call: primary → secondary on error.
tts_with_fallback()   — async generator with three-tier TTS chain:
                          1. ElevenLabs per-call WebSocket  (lowest latency)
                          2. ElevenLabs HTTP streaming        (fallback if WS absent/fails)
                          3. Deepgram Aura TTS                (final fallback)

Errors that trigger fallback: asyncio.TimeoutError, httpx.TimeoutException,
httpx.HTTPStatusError (4xx/5xx from provider), ConnectionError.
"""

import asyncio
import logging
from typing import AsyncIterator, Awaitable, Callable, TypeVar

import httpx

from config import settings
from llm.llm_client import _CircuitBreaker
from tts.elevenlabs_ws import _shared_client as _ws_client

logger = logging.getLogger(__name__)

T = TypeVar("T")

_FALLBACK_ERRORS = (asyncio.TimeoutError, httpx.TimeoutException, httpx.HTTPStatusError)
_WS_ERRORS       = (ConnectionError, asyncio.TimeoutError, OSError)

# Circuit breaker shared across all calls — trips after 2 consecutive ElevenLabs
# failures and routes directly to Deepgram for 120 s.
_elevenlabs_cb = _CircuitBreaker(
    threshold=settings.tts_circuit_fail_threshold,
    cooldown=settings.tts_circuit_cooldown_s,
    provider="elevenlabs",
)


async def with_fallback(
    primary: Callable[[], Awaitable[T]],
    fallback: Callable[[], Awaitable[T]],
    *,
    name: str = "provider",
) -> T:
    """Call primary(); on timeout/HTTP error call fallback()."""
    try:
        return await primary()
    except _FALLBACK_ERRORS as exc:
        logger.warning("%s primary failed (%s) — switching to fallback", name, exc)
        return await fallback()


async def tts_with_fallback(
    text: str,
    http_client: httpx.AsyncClient,
    call_metrics=None,
) -> AsyncIterator[bytes]:
    """
    Stream μ-law 8kHz audio for `text`.

    Tier 1 — ElevenLabs per-call WebSocket (fresh connection per sentence)
    Tier 2 — ElevenLabs HTTP streaming
    Tier 3 — Deepgram Aura TTS

    Falls back to the next tier only when the current tier fails BEFORE yielding
    the first chunk.  Mid-stream failures raise rather than silently switching.
    call_metrics: forwarded to record t_first_tts_byte (once per call).
    """
    from tts.elevenlabs_tts import stream_sentence_mulaw as el_http
    from tts.deepgram_tts  import stream_sentence_mulaw as dg_stream

    # Circuit breaker: skip ElevenLabs tiers entirely if recently tripped
    if _elevenlabs_cb.should_skip():
        logger.warning("ElevenLabs circuit breaker OPEN — routing directly to Deepgram")
        async for chunk in dg_stream(text, http_client):
            yield chunk
        return

    # ── Tier 1: per-call WebSocket ────────────────────────────────────────
    if _ws_client.is_available():
        started = False
        try:
            async for chunk in _ws_client.stream_sentence(text, call_metrics):
                started = True
                yield chunk
            _elevenlabs_cb.record_success()
            if call_metrics is not None:
                call_metrics.tts_chars_elevenlabs += len(text)
            return
        except Exception as exc:
            if started:
                logger.error("ElevenLabs WS failed mid-stream: %s", exc)
                raise
            logger.warning(
                "ElevenLabs WS failed before first chunk (%s) — HTTP fallback", exc
            )
            _elevenlabs_cb.record_failure()
            # fall through to tier 2

    # ── Tier 2: ElevenLabs HTTP ───────────────────────────────────────────
    started = False
    try:
        async for chunk in el_http(text, http_client, call_metrics):
            started = True
            yield chunk
        _elevenlabs_cb.record_success()
        if call_metrics is not None:
            call_metrics.tts_chars_elevenlabs += len(text)
        return
    except _FALLBACK_ERRORS as exc:
        if started:
            logger.error("ElevenLabs HTTP failed mid-stream: %s", exc)
            raise
        _elevenlabs_cb.record_failure()
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 429:
            logger.warning("ElevenLabs 429 rate-limited — Deepgram TTS fallback")
        else:
            logger.warning(
                "ElevenLabs HTTP failed before first chunk (%s) — Deepgram TTS fallback", exc
            )

    # ── Tier 3: Deepgram TTS ──────────────────────────────────────────────
    async for chunk in dg_stream(text, http_client):
        yield chunk
    if call_metrics is not None:
        call_metrics.tts_chars_deepgram += len(text)
