"""
Integration tests for barge-in behaviour.

Verifies that when a barge-in is triggered mid-pipeline:
  1. The in-flight pipeline task is cancelled.
  2. clearAudio is sent to the WebSocket.
  3. Text is routed through the endpoint buffer → one pipeline starts.

Uses asyncio mocks to avoid real network calls.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ────────────────────────────────────────────────────────────────

def make_slow_sentence_gen(*sentences, delay=0.05):
    async def _gen(_history, **_kwargs):
        for s in sentences:
            await asyncio.sleep(delay)
            yield s
    return _gen


def make_fast_mulaw_gen(frames=5):
    async def _gen(_text, _http, _call_metrics=None, **_kwargs):
        for _ in range(frames):
            yield b"\x7f" * 160
    return _gen


# ── Pipeline cancellation ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_cancelled_by_task_cancel():
    """Cancelling the task returned by pipeline.run() must propagate CancelledError."""
    from agent.pipeline import StreamingPipeline
    from agent.metrics import TurnMetrics

    ws  = AsyncMock()
    llm = MagicMock()
    llm.stream_sentences = make_slow_sentence_gen(
        "First sentence.", "Second sentence.", delay=0.1
    )

    with patch("agent.pipeline.tts_with_fallback", make_fast_mulaw_gen()):
        pipeline = StreamingPipeline(
            websocket=ws, stream_sid="sid-test", llm=llm, http=AsyncMock()
        )
        metrics  = TurnMetrics(call_id="test-call")
        run_task = asyncio.create_task(pipeline.run([], metrics))

        await asyncio.sleep(0.02)
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
async def test_pipeline_sends_audio_before_cancel():
    """Audio frames should be sent to the WebSocket before cancellation."""
    from agent.pipeline import StreamingPipeline
    from agent.metrics import TurnMetrics

    ws  = AsyncMock()
    llm = MagicMock()
    llm.stream_sentences = make_slow_sentence_gen("Hello there.", delay=0.0)

    async def fast_mulaw(_text, _http, _call_metrics=None, **_kwargs):
        for _ in range(3):
            yield b"\x7f" * 160

    with patch("agent.pipeline.tts_with_fallback", fast_mulaw):
        pipeline = StreamingPipeline(
            websocket=ws, stream_sid="sid2", llm=llm, http=AsyncMock()
        )
        metrics  = TurnMetrics(call_id="c2")
        run_task = asyncio.create_task(pipeline.run([], metrics))
        full_text, dur = await asyncio.wait_for(run_task, timeout=3.0)

    assert full_text == "Hello there."
    assert dur > 0
    assert ws.send_json.call_count >= 3


# ── CallSession barge-in via _on_transcript ────────────────────────────────

@pytest.mark.asyncio
async def test_barge_in_cancels_current_task_and_sends_clear():
    """
    _on_transcript() with a qualifying barge-in must:
      - Immediately flip state to LISTENING (prevents re-entry).
      - Cancel the current pipeline task.
      - Send clearAudio (after a yield to the event loop).
      - Start an endpoint timer (not a pipeline task directly).
    """
    from agent.call_session import CallSession, State

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    session = CallSession(
        websocket=ws,
        stream_sid="sid-barge",
        call_sid="call-barge",
        llm=MagicMock(),
        plivo=AsyncMock(),
        http=AsyncMock(),
    )
    session._state = State.SPEAKING

    async def slow_work():
        await asyncio.sleep(10)

    old_task = asyncio.create_task(slow_work())
    session._current_task = old_task

    # Trigger barge-in via _on_transcript (3 words, is_final)
    await session._on_transcript("interrupt this now", is_final=True, confidence=0.99)

    # State flips immediately (synchronous)
    assert session._state == State.LISTENING

    # Yield to the event loop so the cancellation propagates
    await asyncio.sleep(0)
    assert old_task.cancelled() or old_task.done() or old_task.cancelling() > 0

    # Wait for _handle_barge_in_cancel to run (drains task, sends clearAudio, sets timer)
    await asyncio.sleep(0.1)

    ws.send_json.assert_called_once_with({
        "event":     "clearAudio",
        "streamSid": "sid-barge",
    })
    # Barge-in text is buffered for the is_final that will follow
    assert "interrupt this now" in session._utterance_buffer
    # No endpoint timer yet — the cascade fix: timer only starts on is_final
    assert session._endpoint_timer is None or session._endpoint_timer.done()


@pytest.mark.asyncio
async def test_barge_in_not_triggered_without_active_task():
    """
    SPEAKING state with no running pipeline task (e.g. during greeting synthesis)
    must NOT trigger barge-in — clearAudio must NOT be sent.
    """
    from agent.call_session import CallSession, State

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    session = CallSession(
        websocket=ws,
        stream_sid="sid-idle",
        call_sid="call-idle",
        llm=MagicMock(),
        plivo=AsyncMock(),
        http=AsyncMock(),
    )
    session._state        = State.SPEAKING
    session._current_task = None   # No running pipeline (greeting in progress)

    await session._on_transcript("interrupt this now", is_final=True, confidence=0.99)
    await asyncio.sleep(0.05)

    ws.send_json.assert_not_called()
    assert session._endpoint_timer is None


# ── STT confidence threshold ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_interim_below_threshold_does_not_barge_in():
    """Interim transcript below barge_in_threshold must not trigger barge-in."""
    from agent.call_session import CallSession, State

    ws = AsyncMock()
    session = CallSession(
        websocket=ws, stream_sid="s", call_sid="c",
        llm=MagicMock(), plivo=AsyncMock(), http=AsyncMock(),
    )
    session._state = State.SPEAKING

    async def slow_work():
        await asyncio.sleep(10)

    old_task = asyncio.create_task(slow_work())
    session._current_task = old_task

    with patch.object(session, "_handle_barge_in_cancel", new_callable=AsyncMock) as mock_cancel:
        await session._on_transcript("some words here", is_final=False, confidence=0.40)
        await asyncio.sleep(0)
        mock_cancel.assert_not_called()

    old_task.cancel()
    await asyncio.gather(old_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interim_above_threshold_triggers_barge_in():
    """Interim transcript above barge_in_threshold must trigger barge-in."""
    from agent.call_session import CallSession, State
    from config import settings

    ws = AsyncMock()
    session = CallSession(
        websocket=ws, stream_sid="s", call_sid="c",
        llm=MagicMock(), plivo=AsyncMock(), http=AsyncMock(),
    )
    session._state = State.SPEAKING

    async def slow_work():
        await asyncio.sleep(10)

    old_task = asyncio.create_task(slow_work())
    session._current_task = old_task

    with patch.object(session, "_handle_barge_in_cancel", new_callable=AsyncMock) as mock_cancel:
        await session._on_transcript(
            "interrupt right now",
            is_final=False,
            confidence=settings.barge_in_threshold + 0.01,
        )
        await asyncio.sleep(0)
        mock_cancel.assert_called_once_with("interrupt right now")

    old_task.cancel()
    await asyncio.gather(old_task, return_exceptions=True)


# ── Barge-in dedupe ────────────────────────────────────────────────────────

_FAKE_SETTINGS_BARGE = __import__("types").SimpleNamespace(
    endpoint_ms=200,
    min_utterance_words=2,
    barge_in_threshold=0.85,
    min_barge_in_words=3,
    system_prompt="test",
    max_conversation_turns=30,
    hangup_silence_secs=30.0,
    greeting_message="Hello.",
    stt_drop_phrases="",
    enable_backchannels=False,
    speculative_llm_enabled=False,
    post_speech_mute_ms=600,
    recording_enabled=False,
)
_FAKE_SETTINGS_BARGE.stt_drop_phrases_list = lambda: []
_FAKE_SETTINGS_BARGE.short_utterance_whitelist_set = lambda: set()


@pytest.mark.asyncio
async def test_barge_in_dedupe_six_transcripts_one_pipeline():
    """
    6 identical is_final transcripts within 200 ms (endpoint_ms) must produce
    exactly ONE _run_pipeline call — not 6.
    """
    from agent.call_session import CallSession, State

    with patch("agent.call_session.settings", _FAKE_SETTINGS_BARGE):
        ws = AsyncMock()
        session = CallSession(
            websocket=ws, stream_sid="sid-dd", call_sid="call-dd",
            llm=MagicMock(), plivo=AsyncMock(), http=AsyncMock(),
        )
        session._state = State.SPEAKING

        async def slow_work():
            await asyncio.sleep(10)

        old_task = asyncio.create_task(slow_work())
        session._current_task = old_task

        with patch.object(session, "_run_pipeline", new_callable=AsyncMock) as mock_run:
            # First transcript: state flips to LISTENING, barge-in task spawned
            await session._on_transcript(
                "with the monitoring tools", is_final=True, confidence=0.99
            )
            # Remaining 5: LISTENING state → go through normal buffer path
            for _ in range(5):
                await asyncio.sleep(0.01)
                await session._on_transcript(
                    "with the monitoring tools", is_final=True, confidence=0.99
                )

            # Wait for endpoint timer (200 ms) + a little headroom
            await asyncio.sleep(0.35)

        mock_run.assert_called_once()

    # Clean up
    old_task.cancel()
    await asyncio.gather(old_task, return_exceptions=True)
    if session._endpoint_timer and not session._endpoint_timer.done():
        session._endpoint_timer.cancel()
        await asyncio.gather(session._endpoint_timer, return_exceptions=True)
    if session._current_task and not session._current_task.done():
        session._current_task.cancel()
        await asyncio.gather(session._current_task, return_exceptions=True)


# ── Barge-in cascade (interim burst must not fire multiple pipelines) ───────

_FAKE_SETTINGS_CASCADE = __import__("types").SimpleNamespace(
    endpoint_ms=50,
    min_utterance_words=2,
    barge_in_threshold=0.85,
    min_barge_in_words=3,
    system_prompt="test",
    max_conversation_turns=30,
    hangup_silence_secs=9999.0,
    greeting_message="Hello.",
    stt_drop_phrases="",
    enable_backchannels=False,
    speculative_llm_enabled=False,
    post_speech_mute_ms=0,
    recording_enabled=False,
)
_FAKE_SETTINGS_CASCADE.stt_drop_phrases_list = lambda: []
_FAKE_SETTINGS_CASCADE.short_utterance_whitelist_set = lambda: set()


@pytest.mark.asyncio
async def test_barge_in_does_not_cascade_on_interim_transcripts():
    """
    While the agent is SPEAKING, multiple high-confidence interim transcripts
    must NOT each fire a new pipeline. The pipeline fires exactly once, triggered
    only when is_final arrives (not from each barge-in interim).
    """
    from agent.call_session import CallSession, State

    with patch("agent.call_session.settings", _FAKE_SETTINGS_CASCADE):
        ws = AsyncMock()
        session = CallSession(
            websocket=ws, stream_sid="sid-cas", call_sid="call-cas",
            llm=MagicMock(), plivo=AsyncMock(), http=AsyncMock(),
        )

        async def _long_running():
            await asyncio.sleep(10)

        session._current_task = asyncio.create_task(_long_running())
        session._state = State.SPEAKING

        with patch.object(session, "_run_pipeline", new_callable=AsyncMock) as mock_pipeline:
            # 3 high-confidence interims (≥ min_barge_in_words=3) while agent is SPEAKING
            for text in [
                "So yeah technically",
                "So yeah technically I monitor",
                "So yeah technically I monitor our",
            ]:
                await session._on_transcript(text, is_final=False, confidence=0.9)

            # Wait > endpoint_ms (50ms): with the cascade fix, no endpoint timer was
            # started on barge-in, so no pipeline fires yet
            await asyncio.sleep(0.15)
            mock_pipeline.assert_not_called()

            # is_final arrives — this starts the endpoint timer normally
            await session._on_transcript(
                "So yeah technically I monitor our systems.", is_final=True, confidence=0.99
            )
            await asyncio.sleep(0.15)  # wait for endpoint timer (50ms) + headroom

            mock_pipeline.assert_called_once()

    # Cleanup
    if session._current_task and not session._current_task.done():
        session._current_task.cancel()
        await asyncio.gather(session._current_task, return_exceptions=True)
    if session._endpoint_timer and not session._endpoint_timer.done():
        session._endpoint_timer.cancel()
        await asyncio.gather(session._endpoint_timer, return_exceptions=True)
