"""
Tests for Phase 8 — cost tracking.

1. test_openai_cost_calculation          — compute_cost_usd() with OpenAI provider
2. test_groq_cost_calculation            — compute_cost_usd() with Groq provider
3. test_deepgram_tts_cost_calculation    — compute_cost_usd() with Deepgram TTS chars
4. test_recorder_includes_cost_breakdown — close() stores cost_breakdown in JSON
5. test_recording_json_includes_cost_breakdown_after_real_close
                                         — full CallSession.close() path writes cost_breakdown
"""

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Test 1 — OpenAI cost calculation
# ---------------------------------------------------------------------------

def test_openai_cost_calculation():
    """compute_cost_usd() must return the correct dollar amount for OpenAI tokens."""
    from agent.metrics import CallMetrics
    from config import COST_RATES

    cm = CallMetrics(call_id="c-openai")
    cm.llm_input_tokens  = 1000
    cm.llm_output_tokens = 500
    cm.llm_provider_used = "openai"

    cost = cm.compute_cost_usd()

    expected_in  = 1000 / 1000.0 * COST_RATES["openai_input_per_1k_tokens"]
    expected_out = 500  / 1000.0 * COST_RATES["openai_output_per_1k_tokens"]
    expected_total = expected_in + expected_out

    assert abs(cost["llm_input_usd"]  - expected_in)    < 1e-9
    assert abs(cost["llm_output_usd"] - expected_out)   < 1e-9
    assert abs(cost["total_usd"]      - expected_total) < 1e-9
    assert cost["llm_provider"] == "openai"
    assert cost["llm_input_tokens"]  == 1000
    assert cost["llm_output_tokens"] == 500


# ---------------------------------------------------------------------------
# Test 2 — Groq cost calculation
# ---------------------------------------------------------------------------

def test_groq_cost_calculation():
    """compute_cost_usd() must use Groq rates when llm_provider_used='groq'."""
    from agent.metrics import CallMetrics
    from config import COST_RATES

    cm = CallMetrics(call_id="c-groq")
    cm.llm_input_tokens  = 2000
    cm.llm_output_tokens = 1000
    cm.llm_provider_used = "groq"

    cost = cm.compute_cost_usd()

    expected_in  = 2000 / 1000.0 * COST_RATES["groq_input_per_1k_tokens"]
    expected_out = 1000 / 1000.0 * COST_RATES["groq_output_per_1k_tokens"]

    assert abs(cost["llm_input_usd"]  - expected_in)  < 1e-9
    assert abs(cost["llm_output_usd"] - expected_out) < 1e-9
    assert cost["llm_provider"] == "groq"


# ---------------------------------------------------------------------------
# Test 3 — Deepgram TTS cost calculation
# ---------------------------------------------------------------------------

def test_deepgram_tts_cost_calculation():
    """compute_cost_usd() must use deepgram_tts_per_1k_chars rate."""
    from agent.metrics import CallMetrics
    from config import COST_RATES

    cm = CallMetrics(call_id="c-dgtts")
    cm.tts_chars_deepgram = 1000
    cm.llm_provider_used  = "openai"   # avoids key-missing edge case

    cost = cm.compute_cost_usd()

    expected = 1000 / 1000.0 * COST_RATES["deepgram_tts_per_1k_chars"]
    assert abs(cost["tts_deepgram_usd"] - expected) < 1e-9
    assert cost["tts_chars_deepgram"] == 1000


# ---------------------------------------------------------------------------
# Test 4 — recorder JSON includes cost_breakdown key
# ---------------------------------------------------------------------------

_FAKE_SETTINGS_REC = SimpleNamespace(recording_enabled=True, record_audio=False)


@pytest.mark.asyncio
async def test_recorder_includes_cost_breakdown(tmp_path):
    """
    When call_session.close() includes cost_breakdown in rec_metrics,
    the JSON written by CallRecorder must contain a 'cost_breakdown' key
    with a 'total_usd' field.
    """
    from agent.recorder import CallRecorder

    with patch("agent.recorder.settings", _FAKE_SETTINGS_REC):
        rec = CallRecorder("call-cost", tmp_path)
        await rec.start()
        rec.add_agent_turn("Hello.", duration_ms=800.0)

        cost_breakdown = {
            "total_usd":            0.001234,
            "stt_usd":              0.0,
            "llm_input_usd":        0.0001,
            "llm_output_usd":       0.0002,
            "tts_elevenlabs_usd":   0.0009,
            "tts_deepgram_usd":     0.0,
            "plivo_usd":            0.0001,
            "llm_provider":         "openai",
            "stt_seconds":          0.0,
            "llm_input_tokens":     100,
            "llm_output_tokens":    50,
            "tts_chars_elevenlabs": 30,
            "tts_chars_deepgram":   0,
            "plivo_seconds":        60.0,
        }
        await rec.close("agent_completed", {
            "turns":            1,
            "cost_breakdown":   cost_breakdown,
        })

    path = tmp_path / "call-cost.json"
    assert path.exists()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert "cost_breakdown" in doc["metrics"], "metrics must contain cost_breakdown"
    assert "total_usd" in doc["metrics"]["cost_breakdown"]
    assert abs(doc["metrics"]["cost_breakdown"]["total_usd"] - 0.001234) < 1e-9


# ---------------------------------------------------------------------------
# Test 5 — full CallSession.close() path writes cost_breakdown
# ---------------------------------------------------------------------------

_FAKE_SETTINGS_CLOSE = SimpleNamespace(
    recording_enabled=True,
    recording_dir="",          # overridden per-test with tmp_path
    record_audio=False,
    endpoint_ms=200,
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
    hard_timeout_s=9999.0,
    max_llm_response_chars=400,
    forbidden_phrases="",
)
_FAKE_SETTINGS_CLOSE.stt_drop_phrases_list      = lambda: []
_FAKE_SETTINGS_CLOSE.short_utterance_whitelist_set = lambda: set()


@pytest.mark.asyncio
async def test_recording_json_includes_cost_breakdown_after_real_close(tmp_path):
    """
    Production-path test: CallSession.close() must write a recording JSON that
    contains cost_breakdown with stt_usd, llm_usd, tts_usd, plivo_usd, total_usd.
    This exercises the real close() code path, not just compute_cost_usd() in isolation.
    """
    from agent.call_session import CallSession

    call_sid = "test-cost-call"

    # Point fake settings at tmp_path for recordings
    fake = SimpleNamespace(**vars(_FAKE_SETTINGS_CLOSE))
    fake.recording_dir = str(tmp_path)
    fake.stt_drop_phrases_list         = lambda: []
    fake.short_utterance_whitelist_set = lambda: set()

    with patch("agent.call_session.settings", fake):
        session = CallSession(
            websocket=AsyncMock(),
            stream_sid="sid-cost",
            call_sid=call_sid,
            llm=MagicMock(),
            plivo=AsyncMock(),
            http=AsyncMock(),
        )
        # Replace STT so close() doesn't try to close a real network connection
        session._stt = AsyncMock()

        # Inject non-zero cost counters
        session._call_metrics.stt_seconds          = 30.0
        session._call_metrics.llm_input_tokens     = 50
        session._call_metrics.llm_output_tokens    = 20
        session._call_metrics.llm_provider_used    = "openai"
        session._call_metrics.tts_chars_elevenlabs = 150
        session._call_metrics.call_start_wall      = time.time()

        # Start the recorder directly (session.start() is skipped to avoid
        # real STT/TTS network calls; recorder.start() is what matters here)
        await session._recorder.start()
        session._recorder.add_agent_turn("Hello.", duration_ms=800.0)

        await session.close()

    json_path = tmp_path / f"{call_sid}.json"
    assert json_path.exists(), "Recording JSON must exist after close()"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "cost_breakdown" in data["metrics"], (
        f"cost_breakdown missing from metrics. Got keys: {list(data['metrics'].keys())}"
    )

    cb = data["metrics"]["cost_breakdown"]
    for key in ("stt_usd", "llm_usd", "tts_usd", "plivo_usd", "total_usd"):
        assert key in cb, f"{key} missing from cost_breakdown"
        assert isinstance(cb[key], (int, float)), f"{key} must be numeric"

    assert cb["total_usd"] > 0, "total_usd must be > 0 with non-zero counters"
