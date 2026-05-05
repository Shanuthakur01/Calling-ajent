"""
Streaming LLM client: provider-agnostic with configurable primary/fallback chain.

Provider chain
──────────────
1. Primary provider  (LLM_PRIMARY_PROVIDER, LLM_PRIMARY_MODEL)
   - Per-call read-timeout from settings.llm_primary_timeout_s  (default 8 s)
   - 3-state circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED
     threshold = settings.llm_circuit_fail_threshold  (default 2 consecutive errors)
     cooldown  = settings.llm_circuit_cooldown_s      (default 120 s)

2. Fallback provider  (LLM_FALLBACK_PROVIDER, LLM_FALLBACK_MODEL)
   - Activated when:
     • Circuit breaker is OPEN  (all calls go to fallback)
     • Primary raises a non-auth APIError BEFORE the first sentence is yielded
   - Per-call read-timeout from settings.llm_fallback_timeout_s  (default 4 s)

3. Graceful degradation
   - If both providers fail before yielding any sentence, one hard-coded
     recovery sentence is yielded so the caller never receives silence.

Mid-stream failures (after first sentence already yielded to caller)
   - The partial response is kept; no restart.  The pipeline will send what
     was generated so far.  This prevents duplicate or conflicting audio.
"""

import enum
import logging
import time
from typing import AsyncIterator, Callable, List, Dict, Optional

import httpx
from openai import (
    AsyncOpenAI,
    APIError,
    AuthenticationError,
    PermissionDeniedError,
)

from config import settings

logger = logging.getLogger(__name__)

_MIN_SENTENCE = 12  # ignore punctuation inside very short fragments
_GRACEFUL_FALLBACK_MSG = "I'm having a technical issue, can you repeat that?"

# Provider registry — add a new entry here to support additional LLM providers.
PROVIDER_CONFIG: Dict[str, Dict] = {
    "openai": {
        "base_url":    None,                   # use SDK default (api.openai.com)
        "settings_key": "openai_api_key",
        "default_model": "gpt-4o-mini",
    },
    "groq": {
        "base_url":    "https://api.groq.com/openai/v1",
        "settings_key": "groq_api_key",
        "default_model": "llama-3.3-70b-versatile",
    },
}


def _build_client(
    provider: str,
    timeout_s: float,
    _provider_config: Dict = PROVIDER_CONFIG,
) -> Optional[AsyncOpenAI]:
    """Build an AsyncOpenAI-compatible client for the given provider.
    Returns None if the API key is not configured."""
    cfg = _provider_config[provider]
    api_key = getattr(settings, cfg["settings_key"], None)
    if not api_key:
        return None
    kwargs: Dict = dict(
        api_key=api_key,
        max_retries=0,
        timeout=httpx.Timeout(connect=2.0, read=timeout_s, write=2.0, pool=2.0),
    )
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    return AsyncOpenAI(**kwargs)


# ---------------------------------------------------------------------------
# Auth-error detection
# ---------------------------------------------------------------------------

def _is_auth_error(exc: Exception) -> bool:
    """Return True for errors that should NOT be retried or fallen back."""
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status in (400, 401, 403)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class _CBState(enum.Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class _CircuitBreaker:
    """
    3-state circuit breaker for an LLM provider.

    State transitions
    ─────────────────
    CLOSED    → OPEN      : after `threshold` consecutive failures
    OPEN      → HALF_OPEN : after `cooldown` seconds (first should_skip() call)
    HALF_OPEN → CLOSED    : on record_success()
    HALF_OPEN → OPEN      : on record_failure() (restarts cooldown)
    """

    def __init__(
        self,
        threshold: int = 2,
        cooldown: float = 120.0,
        provider: str = "primary",
    ) -> None:
        self._threshold  = threshold
        self._cooldown   = cooldown
        self._provider   = provider
        self._failures   = 0
        self._open_until = 0.0
        self._state      = _CBState.CLOSED

    def should_skip(self) -> bool:
        """Return True if primary provider should be bypassed entirely for this call."""
        now = time.monotonic()
        if self._state == _CBState.CLOSED:
            return False
        if self._state == _CBState.OPEN:
            if now >= self._open_until:
                self._state = _CBState.HALF_OPEN
                logger.info(
                    "%s circuit breaker → HALF_OPEN — probing with one request",
                    self._provider,
                )
                return False   # allow one probe through
            return True        # still within cooldown window
        # HALF_OPEN: allow the probe through; record_* will settle the state
        return False

    def is_open(self) -> bool:
        """Backwards-compat alias used by existing tests."""
        return self.should_skip()

    def record_failure(self) -> None:
        if self._state == _CBState.HALF_OPEN:
            self._open_until = time.monotonic() + self._cooldown
            self._state = _CBState.OPEN
            logger.warning(
                "%s circuit breaker → OPEN (HALF_OPEN probe failed)", self._provider
            )
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = time.monotonic() + self._cooldown
            self._state = _CBState.OPEN
            logger.warning(
                "%s circuit breaker OPEN — routing all requests to fallback for %.0fs",
                self._provider, self._cooldown,
            )

    def record_success(self) -> None:
        if self._state == _CBState.HALF_OPEN:
            logger.info(
                "%s circuit breaker → CLOSED (HALF_OPEN probe succeeded)", self._provider
            )
        self._failures   = 0
        self._open_until = 0.0
        self._state      = _CBState.CLOSED


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(self, _http_client=None) -> None:
        # _http_client accepted for interface compat; per-provider timeouts are
        # applied via the SDK's own timeout param, not through a shared client.
        self._primary_name: str = settings.llm_primary_provider
        self._fallback_name: str = settings.llm_fallback_provider

        self._primary: AsyncOpenAI = _build_client(
            self._primary_name, settings.llm_primary_timeout_s
        )
        self._fallback: Optional[AsyncOpenAI] = _build_client(
            self._fallback_name, settings.llm_fallback_timeout_s
        )
        self._primary_cb = _CircuitBreaker(
            threshold=settings.llm_circuit_fail_threshold,
            cooldown=settings.llm_circuit_cooldown_s,
            provider=self._primary_name,
        )
        self._fallback_cb = _CircuitBreaker(
            threshold=settings.llm_circuit_fail_threshold,
            cooldown=settings.llm_circuit_cooldown_s,
            provider=self._fallback_name,
        )

        # Backwards-compat aliases (DEPRECATED — use _primary/_fallback/_primary_cb)
        self._groq    = self._primary
        self._openai  = self._fallback
        self._groq_cb = self._primary_cb

        logger.info(
            "LLM chain: primary=%s/%s  fallback=%s/%s",
            self._primary_name, settings.llm_primary_model,
            self._fallback_name, settings.llm_fallback_model,
        )

    async def complete_once(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: int = 1,
    ) -> None:
        """Non-streaming single completion used only for connection warmup.
        Fires against the primary provider. Response is discarded; raises on error."""
        await self._primary.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            max_tokens=max_tokens,
            temperature=0.0,
        )

    async def _stream_provider(
        self,
        client: AsyncOpenAI,
        model: str,
        messages: List[Dict],
        on_first_token: Optional[Callable[[], None]] = None,
    ) -> AsyncIterator[str]:
        """
        Yield complete sentences from one provider.
        Raises APIError (or subclass) on any failure — before or during streaming.
        on_first_token: called once with no args when the first non-empty token arrives.
        """
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=150,
            temperature=0.8,
        )
        ends = frozenset(settings.sentence_delimiters)
        buf  = ""
        _first_token_fired = False
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta and not _first_token_fired:
                _first_token_fired = True
                if on_first_token is not None:
                    on_first_token()
            buf  += delta
            while True:
                sentence, buf = _split_for_tts(buf, ends)
                if sentence:
                    yield sentence
                else:
                    break
        remainder = buf.strip()
        if remainder:
            yield remainder

    async def stream_sentences(
        self,
        messages: List[Dict],
        *,
        call_metrics=None,
        on_first_token: Optional[Callable[[], None]] = None,
    ) -> AsyncIterator[str]:
        """
        Yield complete, TTS-ready sentences from the LLM response stream.

        Fallback logic
        ──────────────
        • Primary is tried first unless the circuit breaker says to skip it.
        • If primary fails BEFORE yielding the first sentence, fallback is tried
          with the original messages (partial primary tokens are discarded).
        • If primary fails AFTER yielding the first sentence, the partial response
          is kept and no restart is attempted (audio already in flight).
        • If both providers fail before yielding, a single graceful message is
          returned so the caller never receives silence.
        • Auth errors (401 / 403 / AuthenticationError) are re-raised
          immediately — switching providers will not fix a bad API key.
        """
        primary  = self._primary_name
        fallback = self._fallback_name
        use_primary = not self._primary_cb.should_skip()

        # ── Primary provider ──────────────────────────────────────────────
        if use_primary:
            yielded = False
            t = time.perf_counter()
            try:
                async for sentence in self._stream_provider(
                    self._primary, settings.llm_primary_model, messages,
                    on_first_token=on_first_token,
                ):
                    if not yielded:
                        yielded = True
                    yield sentence

                elapsed = (time.perf_counter() - t) * 1000
                logger.info(
                    "LLM %s ok  model=%s  elapsed=%.0fms",
                    primary, settings.llm_primary_model, elapsed,
                )
                self._primary_cb.record_success()
                if call_metrics is not None:
                    call_metrics.primary_turns += 1
                return

            except APIError as exc:
                elapsed = (time.perf_counter() - t) * 1000

                if _is_auth_error(exc):
                    logger.error("%s auth error — not falling back: %s", primary, exc)
                    raise

                self._primary_cb.record_failure()

                if yielded:
                    logger.warning(
                        "%s mid-stream failure after yield (%.0fms) — stopping: %s",
                        primary, elapsed, exc,
                    )
                    return

                logger.warning(
                    "%s %s before yield (%.0fms) — falling back to %s: %s",
                    primary, type(exc).__name__, elapsed, fallback, exc,
                )
                if call_metrics is not None:
                    call_metrics.fallbacks_triggered += 1
        else:
            logger.warning(
                "%s circuit breaker %s — using %s fallback directly",
                primary, self._primary_cb._state.value, fallback,
            )

        # ── Fallback provider ─────────────────────────────────────────────
        if self._fallback is None:
            logger.error(
                "%s fallback not configured (API key missing) — "
                "yielding graceful degradation message",
                fallback,
            )
            yield _GRACEFUL_FALLBACK_MSG
            return

        t = time.perf_counter()
        yielded = False
        try:
            async for sentence in self._stream_provider(
                self._fallback, settings.llm_fallback_model, messages,
                on_first_token=on_first_token,
            ):
                if not yielded:
                    yielded = True
                yield sentence

            elapsed = (time.perf_counter() - t) * 1000
            logger.info(
                "LLM %s ok  model=%s  elapsed=%.0fms",
                fallback, settings.llm_fallback_model, elapsed,
            )
            self._fallback_cb.record_success()
            if call_metrics is not None:
                call_metrics.fallback_turns += 1

        except APIError as exc:
            elapsed = (time.perf_counter() - t) * 1000

            if _is_auth_error(exc):
                logger.error("%s auth error: %s", fallback, exc)
                raise

            self._fallback_cb.record_failure()

            if yielded:
                logger.warning(
                    "%s mid-stream failure after yield (%.0fms) — stopping",
                    fallback, elapsed,
                )
                return

            logger.error(
                "Both LLM providers failed before yield (%.0fms): %s — "
                "yielding graceful degradation message",
                elapsed, exc,
            )
            if call_metrics is not None:
                call_metrics.fallbacks_triggered += 1
            yield _GRACEFUL_FALLBACK_MSG


# ---------------------------------------------------------------------------
# Sentence splitters
# ---------------------------------------------------------------------------

_EARLY_FLUSH_WORDS = 8         # hard word-count cap before we force a flush
_MIN_COMMA_FLUSH_CHARS = 20    # don't comma-flush on very short fragments


def _split_for_tts(text: str, ends: frozenset) -> tuple[str, str]:
    """
    TTS-optimised splitter.  Flushes at the FIRST natural break so ElevenLabs
    receives chunks early, reducing sentence_buffer latency by 200–400 ms.

    Priority:
    1. Strong sentence boundary (.!?) after _MIN_SENTENCE chars  (same as _split_sentence)
    2. Comma after _MIN_COMMA_FLUSH_CHARS chars  (clause break)
    3. Word-count hard cap (_EARLY_FLUSH_WORDS words)  (prevents unbounded wait)
    """
    if not text:
        return "", text

    # 1 — sentence boundary
    if len(text) >= _MIN_SENTENCE:
        for i, ch in enumerate(text):
            if ch not in ends or i < _MIN_SENTENCE - 1:
                continue
            next_i = i + 1
            if next_i < len(text) and text[next_i] not in (" ", "\n", "\t"):
                continue
            return text[:next_i].strip(), text[next_i:].lstrip()

    # 2 — comma flush once enough text has accumulated
    if len(text) >= _MIN_COMMA_FLUSH_CHARS:
        for i, ch in enumerate(text):
            if ch == "," and i >= _MIN_COMMA_FLUSH_CHARS - 1:
                next_i = i + 1
                if next_i < len(text) and text[next_i] in (" ", "\n", "\t"):
                    return text[:next_i].strip(), text[next_i:].lstrip()

    # 3 — word-count cap: flush after EARLY_FLUSH_WORDS words
    words = text.split()
    if len(words) >= _EARLY_FLUSH_WORDS:
        pos = 0
        for word in words[:_EARLY_FLUSH_WORDS]:
            # skip leading whitespace
            while pos < len(text) and text[pos].isspace():
                pos += 1
            pos += len(word)
        return text[:pos].strip(), text[pos:].lstrip()

    return "", text


def _split_sentence(text: str, ends: frozenset) -> tuple[str, str]:
    """
    Return (sentence, remainder) if a complete sentence is found in text,
    else ("", text).

    A sentence ends at a delimiter followed by whitespace or end-of-string,
    and only after at least _MIN_SENTENCE characters.
    """
    if len(text) < _MIN_SENTENCE:
        return "", text

    for i, ch in enumerate(text):
        if ch not in ends or i < _MIN_SENTENCE - 1:
            continue
        next_i = i + 1
        if next_i < len(text) and text[next_i] not in (" ", "\n", "\t"):
            continue
        return text[:next_i].strip(), text[next_i:].lstrip()

    return "", text
