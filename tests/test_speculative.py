"""
Tests for SpeculativeWorker.

1. Hit: final matches speculative -> pre-computed text returned
2. Miss: final differs -> None returned, speculative cancelled
3. Multiple interims: only one task in-flight at a time
4. cancel() terminates in-flight task before it completes
5. try_consume logs full traceback when task fails
"""

import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_llm(response: str = "Hello there."):
    """Return a MagicMock LLM whose stream_sentences yields one sentence."""
    async def _stream(messages, call_metrics=None, **kwargs):
        yield response

    llm = MagicMock()
    llm.stream_sentences = _stream
    return llm


def _make_slow_llm(response: str = "Slow response.", delay: float = 0.5):
    """Return a MagicMock LLM that takes `delay` seconds before yielding."""
    async def _stream(messages, call_metrics=None, **kwargs):
        await asyncio.sleep(delay)
        yield response

    llm = MagicMock()
    llm.stream_sentences = _stream
    return llm


@pytest.mark.asyncio
async def test_speculative_hit_returns_precomputed_text():
    from agent.speculative import SpeculativeWorker

    llm = _make_llm("I am doing well.")
    worker = SpeculativeWorker(llm)
    history = [{"role": "system", "content": "You are helpful."}]

    worker.maybe_start("how are you", history)
    # Let the task complete
    await asyncio.sleep(0.05)

    result = await worker.try_consume("how are you")
    assert result is not None
    text, savings_ms = result
    assert text == "I am doing well."
    assert savings_ms >= 0.0


@pytest.mark.asyncio
async def test_speculative_miss_returns_none():
    from agent.speculative import SpeculativeWorker

    llm = _make_llm("Some answer.")
    worker = SpeculativeWorker(llm)
    history = []

    worker.maybe_start("how are", history)
    await asyncio.sleep(0.05)

    result = await worker.try_consume("what time is it")
    assert result is None
    # Internal task should be cleared
    assert worker._task is None


@pytest.mark.asyncio
async def test_multiple_interims_only_one_task_at_a_time():
    from agent.speculative import SpeculativeWorker

    started_count = 0
    running_at_once = []

    async def _stream(messages, call_metrics=None, **kwargs):
        nonlocal started_count
        started_count += 1
        await asyncio.sleep(0.1)
        yield "answer"

    llm = MagicMock()
    llm.stream_sentences = _stream
    worker = SpeculativeWorker(llm)
    history = []

    # Fire three different interims rapidly
    worker.maybe_start("first interim text", history)
    first_task = worker._task

    worker.maybe_start("second interim text", history)
    second_task = worker._task

    worker.maybe_start("third interim text", history)
    third_task = worker._task

    # Only one task should be running now (the third one)
    assert not first_task.done() or first_task.cancelled() or first_task.cancelling() > 0
    assert worker._task is third_task

    # Allow tasks to settle
    await asyncio.sleep(0.01)

    # first and second tasks should be cancelled
    assert first_task.cancelled() or first_task.cancelling() > 0 or first_task.done()
    assert second_task.cancelled() or second_task.cancelling() > 0 or second_task.done()

    # Clean up
    worker.cancel()
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancel_terminates_inflight_task():
    from agent.speculative import SpeculativeWorker

    llm = _make_slow_llm(delay=5.0)
    worker = SpeculativeWorker(llm)
    history = []

    worker.maybe_start("some interim text here", history)
    task = worker._task
    assert task is not None
    assert not task.done()

    worker.cancel()

    # Give the event loop a chance to process the cancellation
    await asyncio.sleep(0.01)

    assert task.cancelled() or task.cancelling() > 0 or task.done()
    assert worker._task is None
    assert worker._task_text == ""


@pytest.mark.asyncio
async def test_speculative_consume_logs_traceback_on_error(caplog):
    """
    When the speculative task raises an unexpected exception, try_consume()
    must log a WARNING that includes the full traceback (exc_info=True),
    not just the exception message string.
    """
    from agent.speculative import SpeculativeWorker

    async def _failing():
        raise ValueError("boom — intentional test failure")

    llm = MagicMock()
    worker = SpeculativeWorker(llm)
    worker._task = asyncio.create_task(_failing(), name="spec-fail-test")
    worker._task_text = "some text here"

    # Let the task run and raise
    await asyncio.sleep(0.01)

    with caplog.at_level(logging.WARNING, logger="agent.speculative"):
        result = await worker.try_consume("some text here")

    assert result is None
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warning_records, "A WARNING must be logged when speculative task fails"
    assert any(r.exc_info is not None for r in warning_records), (
        "WARNING must include exc_info (traceback), not just the message string"
    )
