"""
Tests for Groq 429 → OpenAI fallback in LLMClient.

Bug 3: a RateLimitError from Groq must immediately switch to OpenAI
with no retry storm (Groq called exactly once, OpenAI called exactly once).
"""

import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock


def _make_openai_stream(content: str):
    """Return an async iterable that yields one text chunk then None."""
    chunks = [
        MagicMock(choices=[MagicMock(delta=MagicMock(content=content))]),
        MagicMock(choices=[MagicMock(delta=MagicMock(content=None))]),
    ]

    async def _aiter():
        for c in chunks:
            yield c

    return _aiter()


@pytest.mark.asyncio
async def test_rate_limit_triggers_immediate_openai_fallback():
    """
    429 from Groq → exactly one Groq call, exactly one OpenAI call, no retry.
    The sentence yielded by OpenAI must be returned to the caller.
    """
    from llm.llm_client import LLMClient, _CircuitBreaker
    from openai import RateLimitError

    # Build a minimal RateLimitError with a real httpx.Response
    mock_request  = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_response = httpx.Response(429, request=mock_request)
    rate_limit_exc = RateLimitError(
        message="rate limited", response=mock_response, body=None
    )

    groq_create   = AsyncMock(side_effect=rate_limit_exc)
    openai_create = AsyncMock(return_value=_make_openai_stream("Hello there. "))

    primary_mock = MagicMock()
    primary_mock.chat.completions.create  = groq_create
    fallback_mock = MagicMock()
    fallback_mock.chat.completions.create = openai_create

    llm               = object.__new__(LLMClient)
    llm._primary      = primary_mock
    llm._fallback     = fallback_mock
    llm._primary_cb   = _CircuitBreaker()
    llm._fallback_cb  = _CircuitBreaker()
    llm._primary_name  = "groq"
    llm._fallback_name = "openai"

    messages  = [{"role": "user", "content": "hi"}]
    sentences = []
    async for s in llm.stream_sentences(messages):
        sentences.append(s)

    assert groq_create.call_count  == 1, "Groq must be called exactly once (no retry)"
    assert openai_create.call_count == 1, "OpenAI fallback must be called exactly once"
    assert sentences, "At least one sentence must be returned from the fallback"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_three_consecutive_429s():
    """After 3 consecutive 429s the circuit breaker must route directly to OpenAI."""
    from llm.llm_client import LLMClient, _CircuitBreaker
    from openai import RateLimitError

    mock_request  = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_response = httpx.Response(429, request=mock_request)
    rate_limit_exc = RateLimitError(
        message="rate limited", response=mock_response, body=None
    )

    groq_create   = AsyncMock(side_effect=rate_limit_exc)
    openai_create = AsyncMock(return_value=_make_openai_stream("Fallback response. "))

    primary_mock = MagicMock()
    primary_mock.chat.completions.create  = groq_create
    fallback_mock = MagicMock()
    fallback_mock.chat.completions.create = openai_create

    llm               = object.__new__(LLMClient)
    llm._primary      = primary_mock
    llm._fallback     = fallback_mock
    llm._primary_cb   = _CircuitBreaker(threshold=3, cooldown=60.0)
    llm._fallback_cb  = _CircuitBreaker()
    llm._primary_name  = "groq"
    llm._fallback_name = "openai"

    messages = [{"role": "user", "content": "hi"}]

    # Drive 3 failures to open the circuit
    for _ in range(3):
        openai_create.return_value = _make_openai_stream("ok. ")
        async for _ in llm.stream_sentences(messages):
            pass

    assert llm._primary_cb.is_open(), "Circuit breaker must be open after 3 failures"

    # Fourth call must skip Groq entirely
    groq_create.reset_mock()
    openai_create.return_value = _make_openai_stream("Direct fallback. ")
    async for _ in llm.stream_sentences(messages):
        pass

    assert groq_create.call_count == 0, "Groq must not be called when circuit is open"
