"""
Tests for the self-echo / system-phrase filter in CallSession._on_transcript.

Bug 2: while the agent is speaking, STT may pick up its own audio or IVR hold
music.  Configured drop-phrases must be silently discarded.
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
    stt_drop_phrases="please hold,on hold,your call is important",
    enable_backchannels=False,
    speculative_llm_enabled=False,
    post_speech_mute_ms=600,
    recording_enabled=False,
)
_FAKE_SETTINGS.stt_drop_phrases_list = lambda: [
    p.strip().lower()
    for p in _FAKE_SETTINGS.stt_drop_phrases.split(",")
    if p.strip()
]
_FAKE_SETTINGS.short_utterance_whitelist_set = lambda: set()


@pytest.mark.asyncio
async def test_system_phrase_is_dropped():
    """A transcript matching a configured drop-phrase must never reach the pipeline."""
    from agent.call_session import CallSession, State

    with patch("agent.call_session.settings", _FAKE_SETTINGS):
        ws = AsyncMock()
        session = CallSession(
            websocket=ws, stream_sid="sid-ep", call_sid="call-ep",
            llm=MagicMock(), plivo=AsyncMock(), http=AsyncMock(),
        )
        session._state = State.LISTENING

        with patch.object(session, "_run_pipeline", new_callable=AsyncMock) as mock_run:
            await session._on_transcript(
                "The person you are speaking with has put your call on hold",
                is_final=True,
                confidence=0.99,
            )
            await asyncio.sleep(0.35)   # wait past endpoint_ms

        mock_run.assert_not_called()

    if session._endpoint_timer and not session._endpoint_timer.done():
        session._endpoint_timer.cancel()


@pytest.mark.asyncio
async def test_normal_transcript_not_dropped():
    """A normal candidate reply must NOT be filtered out."""
    from agent.call_session import CallSession, State

    with patch("agent.call_session.settings", _FAKE_SETTINGS):
        ws = AsyncMock()
        session = CallSession(
            websocket=ws, stream_sid="sid-nd", call_sid="call-nd",
            llm=MagicMock(), plivo=AsyncMock(), http=AsyncMock(),
        )
        session._state = State.LISTENING

        with patch.object(session, "_run_pipeline", new_callable=AsyncMock) as mock_run:
            await session._on_transcript(
                "I have five years of production support experience",
                is_final=True,
                confidence=0.99,
            )
            await asyncio.sleep(0.35)

        mock_run.assert_called_once()

    if session._current_task and not session._current_task.done():
        session._current_task.cancel()
        await asyncio.gather(session._current_task, return_exceptions=True)
