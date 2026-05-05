"""
Tests for TTS voice settings and silence-detection timing defaults.

Coverage
────────
1. ElevenLabs request body includes all 5 voice_settings fields
2. speed defaults to 1.0
3. optimize_streaming_latency is passed from settings (default 4)
4. endpoint_ms defaults to 250
5. dg_endpointing_ms defaults to 800
6. stability defaults to 0.5 (Phase 2 warmth tuning)
7. similarity_boost defaults to 0.75
8. style defaults to 0.30 (Phase 2 warmth tuning)
9. elevenlabs_model defaults to eleven_turbo_v2_5 (Phase 2 upgrade)
"""

import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_settings(**overrides):
    """Minimal settings namespace for patching."""
    defaults = dict(
        elevenlabs_api_key="test-key",
        elevenlabs_voice_id="EMh4QfWp9dtmYomyxDic",
        elevenlabs_model="eleven_turbo_v2_5",
        tts_stability=0.5,
        tts_similarity=0.75,
        tts_style=0.30,
        tts_speaker_boost=True,
        tts_speed=1.0,
        tts_optimize_streaming_latency=4,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _capture_stream_call():
    """
    Return a mock http_client whose .stream() context manager captures
    the kwargs passed to it and yields no bytes.
    """
    captured = {}

    async def _aiter_bytes(_size):
        return
        yield  # make it an async generator

    resp_mock = MagicMock()
    resp_mock.raise_for_status = MagicMock()
    resp_mock.aiter_bytes = _aiter_bytes

    # Context manager protocol
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp_mock)
    cm.__aexit__ = AsyncMock(return_value=False)

    http_mock = MagicMock()

    def _stream_capture(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return cm

    http_mock.stream = _stream_capture
    return http_mock, captured


# ---------------------------------------------------------------------------
# Test 1 — all 5 voice_settings fields are present in request body
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tts_voice_settings_all_5_fields():
    """
    The ElevenLabs API request body must include all 5 voice_settings fields:
    stability, similarity_boost, style, use_speaker_boost, speed.
    """
    from tts.elevenlabs_tts import stream_sentence_mulaw

    http_mock, captured = _capture_stream_call()
    fake_settings = _make_fake_settings()

    with patch("tts.elevenlabs_tts.settings", fake_settings):
        async for _ in stream_sentence_mulaw("Hello.", http_mock):
            pass

    body = captured["kwargs"]["json"]
    vs = body["voice_settings"]

    assert "stability"        in vs, "stability missing from voice_settings"
    assert "similarity_boost" in vs, "similarity_boost missing from voice_settings"
    assert "style"            in vs, "style missing from voice_settings"
    assert "use_speaker_boost" in vs, "use_speaker_boost missing from voice_settings"
    assert "speed"            in vs, "speed missing from voice_settings"


# ---------------------------------------------------------------------------
# Test 2 — speed defaults to 1.0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speed_defaults_to_1_0():
    """speed in voice_settings must equal 1.0 when using default config."""
    from tts.elevenlabs_tts import stream_sentence_mulaw

    http_mock, captured = _capture_stream_call()
    fake_settings = _make_fake_settings()  # tts_speed=1.0 by default

    with patch("tts.elevenlabs_tts.settings", fake_settings):
        async for _ in stream_sentence_mulaw("Hello.", http_mock):
            pass

    speed = captured["kwargs"]["json"]["voice_settings"]["speed"]
    assert speed == pytest.approx(1.0), f"Expected speed=1.0, got {speed}"


# ---------------------------------------------------------------------------
# Test 3 — optimize_streaming_latency is 4
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_optimize_streaming_latency_from_settings():
    """optimize_streaming_latency query param must equal settings.tts_optimize_streaming_latency."""
    from tts.elevenlabs_tts import stream_sentence_mulaw

    http_mock, captured = _capture_stream_call()
    fake_settings = _make_fake_settings(tts_optimize_streaming_latency=4)

    with patch("tts.elevenlabs_tts.settings", fake_settings):
        async for _ in stream_sentence_mulaw("Hello.", http_mock):
            pass

    osl = captured["kwargs"]["params"]["optimize_streaming_latency"]
    assert osl == 4, f"Expected optimize_streaming_latency=4, got {osl}"


# ---------------------------------------------------------------------------
# Test 4 — endpoint_ms defaults to 250
# ---------------------------------------------------------------------------

def test_endpoint_ms_default_is_250():
    """endpoint_ms code default must be 250 (coalescing buffer, not silence timer)."""
    from config import Settings

    # Instantiate with no .env overrides by pointing at a non-existent file
    with patch.object(Settings, "model_config", {"env_file": "/dev/null", "env_file_encoding": "utf-8"}):
        s = Settings(
            deepgram_api_key="x",
            groq_api_key="x",
        )
    assert s.endpoint_ms == 250, f"Expected endpoint_ms=250, got {s.endpoint_ms}"


# ---------------------------------------------------------------------------
# Test 5 — dg_endpointing_ms defaults to 800
# ---------------------------------------------------------------------------

def test_dg_endpointing_default_is_800():
    """dg_endpointing_ms code default must be 800."""
    from config import Settings

    with patch.object(Settings, "model_config", {"env_file": "/dev/null", "env_file_encoding": "utf-8"}):
        s = Settings(
            deepgram_api_key="x",
            groq_api_key="x",
        )
    assert s.dg_endpointing_ms == 800, f"Expected dg_endpointing_ms=800, got {s.dg_endpointing_ms}"


# ---------------------------------------------------------------------------
# Tests 6–8 — humanised voice defaults (warmth tuning)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stability_defaults_to_0_5():
    """stability in voice_settings must equal 0.5 (Phase 2 warmth tuning)."""
    from tts.elevenlabs_tts import stream_sentence_mulaw

    http_mock, captured = _capture_stream_call()
    fake_settings = _make_fake_settings()

    with patch("tts.elevenlabs_tts.settings", fake_settings):
        async for _ in stream_sentence_mulaw("Hello.", http_mock):
            pass

    val = captured["kwargs"]["json"]["voice_settings"]["stability"]
    assert val == pytest.approx(0.5), f"Expected stability=0.5, got {val}"


@pytest.mark.asyncio
async def test_similarity_defaults_to_0_75():
    """similarity_boost in voice_settings must equal 0.75 (warmth tuning)."""
    from tts.elevenlabs_tts import stream_sentence_mulaw

    http_mock, captured = _capture_stream_call()
    fake_settings = _make_fake_settings()

    with patch("tts.elevenlabs_tts.settings", fake_settings):
        async for _ in stream_sentence_mulaw("Hello.", http_mock):
            pass

    val = captured["kwargs"]["json"]["voice_settings"]["similarity_boost"]
    assert val == pytest.approx(0.75), f"Expected similarity_boost=0.75, got {val}"


@pytest.mark.asyncio
async def test_style_defaults_to_0_30():
    """style in voice_settings must equal 0.30 (Phase 2 warmth tuning)."""
    from tts.elevenlabs_tts import stream_sentence_mulaw

    http_mock, captured = _capture_stream_call()
    fake_settings = _make_fake_settings()

    with patch("tts.elevenlabs_tts.settings", fake_settings):
        async for _ in stream_sentence_mulaw("Hello.", http_mock):
            pass

    val = captured["kwargs"]["json"]["voice_settings"]["style"]
    assert val == pytest.approx(0.30), f"Expected style=0.30, got {val}"


# ---------------------------------------------------------------------------
# Tests 9–11 — system_prompt.txt conversational style
# ---------------------------------------------------------------------------

def _load_system_prompt_text() -> str:
    from pathlib import Path
    p = Path(__file__).parent.parent / "system_prompt.txt"
    return p.read_text(encoding="utf-8")


def test_system_prompt_contains_mhm():
    """system_prompt.txt must contain 'Mhm' (conversational filler example)."""
    assert "Mhm" in _load_system_prompt_text()


def test_system_prompt_forbids_formal_phrasing():
    """system_prompt.txt must instruct against overly formal question phrasing."""
    text = _load_system_prompt_text()
    assert "DO NOT say" in text or "Could you walk me through" in text


def test_system_prompt_casual_closing():
    """system_prompt.txt must contain the new casual closing line."""
    text = _load_system_prompt_text()
    assert "Awesome, that's all from my side" in text


# ---------------------------------------------------------------------------
# Test 9 — elevenlabs_model defaults to eleven_turbo_v2_5 (Phase 2 upgrade)
# ---------------------------------------------------------------------------

def test_elevenlabs_model_default_is_turbo_v2_5():
    """elevenlabs_model Settings default must be eleven_turbo_v2_5."""
    from config import Settings
    from unittest.mock import patch

    with patch.object(Settings, "model_config", {"env_file": "/dev/null", "env_file_encoding": "utf-8"}):
        s = Settings(
            deepgram_api_key="x",
            groq_api_key="x",
        )
    assert s.elevenlabs_model == "eleven_turbo_v2_5", (
        f"Expected eleven_turbo_v2_5, got {s.elevenlabs_model!r}"
    )
