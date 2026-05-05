"""
Tests for three production fixes (2026-05-01):

Fix 1 — LLM warmup:   _warmup_llm fires complete_once at startup.
Fix 2 — Short-utterance whitelist:  "sorry?" and "yeah" reach the pipeline;
                                     filler "um" is still dropped.
Fix 3 — CALL TIMELINE no negatives: per-turn averages replace cross-domain
                                     call-level deltas that produced negative ms.
"""

import asyncio
import logging
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fix 1 ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_warmup_runs_on_startup():
    """_warmup_llm invokes complete_once exactly once on the provided LLM client."""
    from main import _warmup_llm

    mock_llm = MagicMock()
    mock_llm.complete_once = AsyncMock(return_value=None)

    await _warmup_llm(mock_llm)

    mock_llm.complete_once.assert_called_once()


# ── Fix 2 ─────────────────────────────────────────────────────────────────────

_WHITELIST_SETTINGS = SimpleNamespace(
    endpoint_ms=200,
    min_utterance_words=2,
    barge_in_threshold=0.85,
    system_prompt="test",
    max_conversation_turns=30,
    hangup_silence_secs=30.0,
    greeting_message="Hello.",
    stt_drop_phrases="",
)
_WHITELIST_SETTINGS.stt_drop_phrases_list = lambda: []
_WHITELIST_SETTINGS.short_utterance_whitelist_set = lambda: {
    "sorry", "pardon", "repeat", "again", "what", "huh",
    "yes", "no", "yeah", "okay", "ok", "sure", "right", "correct",
    "wait", "hold", "stop",
}


def _make_whitelist_session():
    from agent.call_session import CallSession
    return CallSession(
        websocket=AsyncMock(),
        stream_sid="sid-wl",
        call_sid="call-wl",
        llm=MagicMock(),
        plivo=AsyncMock(),
        http=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_short_utterance_whitelist():
    """
    "sorry?" (1 word, whitelisted) → reaches _run_pipeline.
    "yeah"   (1 word, whitelisted) → reaches _run_pipeline.
    "um"     (1 word, NOT listed)  → filtered out silently.
    """
    from agent.call_session import State

    cases = [
        ("sorry?", True),
        ("yeah",   True),
        ("um",     False),
    ]

    for word, should_call in cases:
        session = _make_whitelist_session()
        session._state = State.LISTENING

        with patch("agent.call_session.settings", _WHITELIST_SETTINGS):
            with patch.object(session, "_run_pipeline", new_callable=AsyncMock) as mock_run:
                await session._on_transcript(word, is_final=True, confidence=0.99)
                await asyncio.sleep(0.25)  # wait for endpoint timer (200 ms)

        assert mock_run.called == should_call, (
            f"'{word}': expected _run_pipeline.called={should_call}, "
            f"got {mock_run.called}"
        )

        # Cleanup outstanding tasks
        for t in (session._endpoint_timer, session._current_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass


# ── Fix 3 ─────────────────────────────────────────────────────────────────────

def test_call_timeline_no_negatives(caplog):
    """
    CALL TIMELINE must not contain negative ms values even when t_first_tts_byte
    and t_first_audio_to_plivo are set during the greeting (before t_user_speech_end).

    Root cause of the bug: greeting sets those timestamps at t≈0.2s; user speaks
    at t≈1.5s.  The old code computed llm_token→tts_byte and speech_end→first_audio
    using those call-level timestamps, yielding deltas like -38 000 ms.
    Fix: replace with per-turn averages (always ≥ 0).
    """
    from agent.metrics import CallMetrics, TurnMetrics

    m = CallMetrics(call_id="test-neg")

    # Greeting fires these early — BEFORE the user speaks
    m.t_incoming_call        = 0.00
    m.t_ws_connected         = 0.05
    m.t_first_tts_byte       = 0.20   # greeting TTS started
    m.t_first_audio_to_plivo = 0.25   # greeting audio sent
    m.t_first_stt_partial    = 0.80

    # User speaks later
    m.t_user_speech_end      = 1.50
    m.t_first_llm_token      = 1.95   # first LLM turn

    # Three turns with realistic positive per-turn values
    for i in range(3):
        t = TurnMetrics(call_id="test-neg")
        t.llm_ttft_ms        = 400.0 + i * 50   # 400, 450, 500
        t.tts_ttft_ms        = 580.0 + i * 50   # 580, 630, 680
        t.e2e_first_audio_ms = 900.0 + i * 50   # 900, 950, 1000
        m.add(t)

    with caplog.at_level(logging.INFO):
        m.log_summary()

    timeline = next(
        (r.message for r in caplog.records if "CALL TIMELINE" in r.message), None
    )
    assert timeline is not None, "CALL TIMELINE log line was not emitted"

    negatives = re.findall(r"-\d+ms", timeline)
    assert negatives == [], (
        f"Negative values found in CALL TIMELINE: {negatives!r}\n"
        f"Full line: {timeline}"
    )
