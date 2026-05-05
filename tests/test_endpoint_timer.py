"""
Tests for client-side endpoint buffer+timer in CallSession.

Fix 1B: multiple is_final transcripts arriving within endpoint_ms are
coalesced into one turn; utterances under min_utterance_words are dropped.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_FAKE_SETTINGS = SimpleNamespace(
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
_FAKE_SETTINGS.stt_drop_phrases_list = lambda: []
_FAKE_SETTINGS.short_utterance_whitelist_set = lambda: set()


def _make_session():
    from agent.call_session import CallSession

    ws = AsyncMock()
    session = CallSession(
        websocket=ws,
        stream_sid="sid-et",
        call_sid="call-et",
        llm=MagicMock(),
        plivo=AsyncMock(),
        http=AsyncMock(),
    )
    return session


@pytest.mark.asyncio
async def test_two_finals_within_window_produce_one_turn():
    """
    Two is_final events 100 ms apart with endpoint_ms=200 must coalesce
    into a single _run_pipeline call with the combined text.
    """
    with patch("agent.call_session.settings", _FAKE_SETTINGS):
        session = _make_session()
        from agent.call_session import State
        session._state = State.LISTENING

        with patch.object(session, "_run_pipeline", new_callable=AsyncMock) as mock_run:
            await session._on_transcript("hello there", is_final=True, confidence=0.99)
            await asyncio.sleep(0.1)
            await session._on_transcript("how are you", is_final=True, confidence=0.99)

            # Wait for timer to fire (200 ms + headroom)
            await asyncio.sleep(0.25)

        mock_run.assert_called_once()
        combined = mock_run.call_args[0][0]
        assert "hello there" in combined
        assert "how are you" in combined

    # Cleanup
    if session._endpoint_timer and not session._endpoint_timer.done():
        session._endpoint_timer.cancel()
    if session._current_task and not session._current_task.done():
        session._current_task.cancel()


@pytest.mark.asyncio
async def test_one_word_utterance_does_not_trigger_turn():
    """
    A single-word is_final ("um") must not start a pipeline turn because it
    is below min_utterance_words=2.
    """
    with patch("agent.call_session.settings", _FAKE_SETTINGS):
        session = _make_session()
        from agent.call_session import State
        session._state = State.LISTENING

        with patch.object(session, "_run_pipeline", new_callable=AsyncMock) as mock_run:
            await session._on_transcript("um", is_final=True, confidence=0.99)
            # Wait longer than endpoint_ms
            await asyncio.sleep(0.35)

        mock_run.assert_not_called()

    # Cleanup
    if session._endpoint_timer and not session._endpoint_timer.done():
        session._endpoint_timer.cancel()
    if session._current_task and not session._current_task.done():
        session._current_task.cancel()
