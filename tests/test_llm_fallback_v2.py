"""
Tests for the robust LLM fallback strategy (Phase 4, Step 2).

Coverage
────────
1. Groq 429 → immediate OpenAI fallback
2. Groq APITimeoutError → fallback
3. Circuit breaker opens after 2 failures (default threshold)
4. Circuit transitions OPEN → HALF_OPEN after cooldown; probe success → CLOSED
5. Mid-stream Groq failure before first yield → clean fallback with original messages
6. Both providers fail before yielding → graceful degradation message
7. Auth error (401) does NOT trigger fallback — raises instead
8. Streaming contract: sentences yielded one-by-one in order (not batched)
"""

import time
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from openai import APIError, AuthenticationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stream(*chunks: str):
    """Async iterable yielding one token delta per string."""
    async def _aiter():
        for c in chunks:
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=c))])
    return _aiter()


def _make_error_stream(exc: Exception, *chunks: str):
    """Async iterable yielding tokens, then raising exc."""
    async def _aiter():
        for c in chunks:
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=c))])
        raise exc
    return _aiter()


def _rate_limit_exc():
    req  = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    from openai import RateLimitError
    return RateLimitError(message="rate limited", response=resp, body=None)


def _auth_exc():
    req  = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(401, request=req)
    return AuthenticationError(message="invalid api key", response=resp, body=None)


def _api_exc(message: str = "internal server error"):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return APIError(message=message, request=req, body=None)


def _make_llm(groq_create, openai_create, threshold: int = 2, cooldown: float = 120.0):
    """Build an LLMClient with fully mocked internals.
    First arg acts as the primary (Groq) creator; second as the fallback (OpenAI)."""
    from llm.llm_client import LLMClient, _CircuitBreaker

    primary_mock = MagicMock()
    primary_mock.chat.completions.create = groq_create
    fallback_mock = MagicMock()
    fallback_mock.chat.completions.create = openai_create

    llm = object.__new__(LLMClient)
    llm._primary      = primary_mock
    llm._fallback     = fallback_mock
    llm._primary_cb   = _CircuitBreaker(threshold=threshold, cooldown=cooldown)
    llm._fallback_cb  = _CircuitBreaker(threshold=threshold, cooldown=cooldown)
    llm._primary_name = "groq"
    llm._fallback_name = "openai"
    return llm


MESSAGES = [{"role": "user", "content": "hello"}]


# ---------------------------------------------------------------------------
# Test 1 — Groq 429 → immediate OpenAI fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_429_immediate_fallback():
    """
    A single RateLimitError from Groq must trigger exactly one OpenAI call
    and return at least one sentence to the caller.
    """
    groq_create   = AsyncMock(side_effect=_rate_limit_exc())
    openai_create = AsyncMock(return_value=_make_stream("Hello there. How are you?"))
    llm = _make_llm(groq_create, openai_create)

    sentences = [s async for s in llm.stream_sentences(MESSAGES)]

    assert groq_create.call_count  == 1, "Groq must be called exactly once"
    assert openai_create.call_count == 1, "OpenAI fallback must be called exactly once"
    assert sentences, "At least one sentence must be returned from the fallback"


# ---------------------------------------------------------------------------
# Test 2 — Groq timeout → fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_timeout_fallback():
    """APITimeoutError from Groq must fall back to OpenAI."""
    from openai import APITimeoutError
    req         = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    timeout_exc = APITimeoutError(request=req)

    groq_create   = AsyncMock(side_effect=timeout_exc)
    openai_create = AsyncMock(return_value=_make_stream("I can help with that. "))
    llm = _make_llm(groq_create, openai_create)

    sentences = [s async for s in llm.stream_sentences(MESSAGES)]

    assert groq_create.call_count  == 1
    assert openai_create.call_count == 1
    assert sentences


# ---------------------------------------------------------------------------
# Test 3 — Circuit opens after 2 consecutive failures (default threshold)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_opens_after_two_failures():
    """Two consecutive 429s open the circuit; the third call skips Groq entirely."""
    groq_create   = AsyncMock(side_effect=_rate_limit_exc())
    openai_create = AsyncMock()
    llm = _make_llm(groq_create, openai_create)  # default threshold=2

    for _ in range(2):
        openai_create.return_value = _make_stream("ok fallback sentence. ")
        async for _ in llm.stream_sentences(MESSAGES):
            pass

    assert llm._primary_cb.is_open(), "Circuit must be open after 2 failures"

    # Third call — Groq must not be attempted
    groq_create.reset_mock()
    openai_create.return_value = _make_stream("Direct via fallback. ")
    async for _ in llm.stream_sentences(MESSAGES):
        pass

    assert groq_create.call_count == 0, "Groq must not be called when circuit is open"


# ---------------------------------------------------------------------------
# Test 4 — HALF_OPEN after cooldown; probe success → CLOSED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_half_open_after_cooldown():
    """After cooldown, should_skip() transitions OPEN→HALF_OPEN and allows probe."""
    from llm.llm_client import _CircuitBreaker, _CBState

    cb = _CircuitBreaker(threshold=2, cooldown=120.0)
    cb.record_failure()
    cb.record_failure()
    assert cb._state == _CBState.OPEN

    # Simulate cooldown elapsed by patching time.monotonic inside the module
    with patch("llm.llm_client.time") as mock_time:
        mock_time.monotonic.return_value = time.monotonic() + 200.0
        mock_time.perf_counter = time.perf_counter  # keep real for elapsed logging

        skipped = cb.should_skip()
        assert not skipped, "HALF_OPEN must allow one probe through"
        assert cb._state == _CBState.HALF_OPEN

    # Successful probe → CLOSED
    cb.record_success()
    assert cb._state == _CBState.CLOSED
    assert not cb.is_open()


# ---------------------------------------------------------------------------
# Test 5 — Mid-stream Groq failure before first yield → clean fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mid_stream_failure_before_yield_uses_fallback():
    """
    Groq yields 3 tokens totalling < _MIN_SENTENCE (12) chars — no sentence emitted —
    then raises APIError.  Fallback must restart with the ORIGINAL messages;
    only fallback content must be yielded to the caller.
    """
    stream_err = _api_exc("stream dropped mid-response")

    # Three tokens: "I " + "am " + "G" = 8 chars < _MIN_SENTENCE=12
    groq_create   = AsyncMock(
        return_value=_make_error_stream(stream_err, "I ", "am ", "G")
    )
    openai_create = AsyncMock(
        return_value=_make_stream("Hello, I can certainly help with that. ")
    )
    llm = _make_llm(groq_create, openai_create)

    sentences = [s async for s in llm.stream_sentences(MESSAGES)]

    # Fallback content must be yielded
    assert sentences, "At least one sentence must come from the OpenAI fallback"
    # Graceful degradation message must NOT be present (fallback succeeded)
    assert all("technical" not in s.lower() for s in sentences)

    # OpenAI must have been called with the ORIGINAL messages (no Groq tokens)
    assert openai_create.call_count == 1
    passed_messages = openai_create.call_args.kwargs["messages"]
    assert passed_messages == MESSAGES, (
        "Fallback must receive original messages, not messages contaminated by partial Groq output"
    )


# ---------------------------------------------------------------------------
# Test 6 — Both providers fail → graceful degradation message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_providers_fail_graceful_message():
    """When both Groq and OpenAI fail before yielding, exactly one graceful message is returned."""
    groq_create   = AsyncMock(side_effect=_rate_limit_exc())
    openai_create = AsyncMock(side_effect=_api_exc("openai unavailable"))
    llm = _make_llm(groq_create, openai_create)

    sentences = [s async for s in llm.stream_sentences(MESSAGES)]

    assert len(sentences) == 1, "Exactly one graceful message must be yielded"
    assert "technical" in sentences[0].lower(), (
        f"Expected graceful degradation message, got: {sentences[0]!r}"
    )


# ---------------------------------------------------------------------------
# Test 7 — Auth error does NOT fall back
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_error_does_not_fallback():
    """AuthenticationError (401) from Groq must be raised, not silently fallen back."""
    groq_create   = AsyncMock(side_effect=_auth_exc())
    openai_create = AsyncMock(return_value=_make_stream("should never be called. "))
    llm = _make_llm(groq_create, openai_create)

    with pytest.raises(AuthenticationError):
        async for _ in llm.stream_sentences(MESSAGES):
            pass

    assert openai_create.call_count == 0, "OpenAI must NOT be called on auth errors"


# ---------------------------------------------------------------------------
# Test 8 — Streaming contract: sentences yielded in order, not batched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_contract_preserved():
    """
    Sentences must be yielded one at a time as they arrive from Groq.
    The generator must not buffer the entire response before yielding.
    """
    content = "This is the first sentence. Here comes the second one. "
    groq_create   = AsyncMock(return_value=_make_stream(content))
    openai_create = AsyncMock()
    llm = _make_llm(groq_create, openai_create)

    yielded_sentences = []
    async for sentence in llm.stream_sentences(MESSAGES):
        yielded_sentences.append(sentence)

    assert len(yielded_sentences) >= 1, "At least one sentence must be yielded"
    assert openai_create.call_count == 0, "OpenAI must not be touched when Groq succeeds"
    # Verify order: joined result must contain both sentences
    joined = " ".join(yielded_sentences)
    assert "first" in joined.lower() or "second" in joined.lower()
