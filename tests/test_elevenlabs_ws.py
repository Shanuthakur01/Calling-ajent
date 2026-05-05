"""
Unit tests for tts/elevenlabs_ws.py — ElevenLabsWSClient (per-call WS).

Covers:
1. stream_sentence opens a fresh WebSocket for each call
2. stream_sentence yields bytes from a healthy connection
3. stream_sentence closes WS on exception before first chunk
4. stream_sentence closes WS when consumer cancels mid-stream
5. tts_ws_open_count increments per successful open
6. tts_with_fallback uses WS tier when ElevenLabs API key is configured
7. tts_with_fallback falls through to HTTP tier when WS raises before first chunk
"""

import asyncio
import base64
import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audio_msg(data: bytes, is_final: bool = False) -> str:
    return json.dumps({"audio": base64.b64encode(data).decode(), "isFinal": is_final})


def _final_msg() -> str:
    return json.dumps({"audio": None, "isFinal": True})


def _fake_settings(**overrides):
    defaults = dict(
        elevenlabs_api_key="test-key",
        elevenlabs_voice_id="voice-id",
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


def _make_ws_mock(recv_side_effect):
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock(side_effect=recv_side_effect)
    ws.close = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Test 1 — fresh WebSocket opened for each stream_sentence call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_sentence_opens_fresh_ws_each_call():
    from tts.elevenlabs_ws import ElevenLabsWSClient

    chunk = b"\x01\x02"
    ws_mock = _make_ws_mock([_audio_msg(chunk, is_final=True)])

    call_count = [0]

    async def _fake_connect(*args, **kwargs):
        call_count[0] += 1
        ws_mock.recv = AsyncMock(side_effect=[_audio_msg(chunk, is_final=True)])
        return ws_mock

    client = ElevenLabsWSClient()
    with patch("tts.elevenlabs_ws.settings", _fake_settings()):
        with patch("websockets.connect", side_effect=_fake_connect):
            async for _ in client.stream_sentence("Hello."):
                pass
            async for _ in client.stream_sentence("World."):
                pass

    assert call_count[0] == 2, f"Expected 2 WS opens, got {call_count[0]}"


# ---------------------------------------------------------------------------
# Test 2 — stream_sentence yields bytes from a healthy connection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_sentence_yields_bytes():
    from tts.elevenlabs_ws import ElevenLabsWSClient

    chunk1 = b"\x00\x01\x02"
    chunk2 = b"\x03\x04\x05"
    ws_mock = _make_ws_mock([
        _audio_msg(chunk1),
        _audio_msg(chunk2, is_final=True),
    ])

    client = ElevenLabsWSClient()
    with patch("tts.elevenlabs_ws.settings", _fake_settings()):
        with patch("websockets.connect", AsyncMock(return_value=ws_mock)):
            received = []
            async for chunk in client.stream_sentence("Hello."):
                received.append(chunk)

    assert received == [chunk1, chunk2]


# ---------------------------------------------------------------------------
# Test 3 — stream_sentence closes WS on exception before first chunk
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_sentence_closes_ws_on_exception():
    from tts.elevenlabs_ws import ElevenLabsWSClient

    ws_mock = _make_ws_mock([ConnectionError("recv failed")])
    ws_mock.recv = AsyncMock(side_effect=ConnectionError("recv failed"))

    client = ElevenLabsWSClient()
    with patch("tts.elevenlabs_ws.settings", _fake_settings()):
        with patch("websockets.connect", AsyncMock(return_value=ws_mock)):
            with pytest.raises(Exception):
                async for _ in client.stream_sentence("Hello."):
                    pass

    ws_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4 — stream_sentence closes WS when consumer cancels mid-stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_sentence_closes_ws_on_consumer_cancel():
    from tts.elevenlabs_ws import ElevenLabsWSClient

    chunk = b"\xAA" * 160

    async def _slow_recv():
        await asyncio.sleep(10)
        return _audio_msg(chunk)

    ws_mock = AsyncMock()
    ws_mock.send = AsyncMock()
    ws_mock.recv = AsyncMock(side_effect=_slow_recv)
    ws_mock.close = AsyncMock()

    client = ElevenLabsWSClient()

    async def _consume():
        with patch("tts.elevenlabs_ws.settings", _fake_settings()):
            with patch("websockets.connect", AsyncMock(return_value=ws_mock)):
                async for _ in client.stream_sentence("Hello."):
                    pass

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    ws_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5 — tts_ws_open_count increments per successful open
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tts_ws_open_count_increments():
    import tts.elevenlabs_ws as ws_mod
    from tts.elevenlabs_ws import ElevenLabsWSClient

    before = ws_mod.tts_ws_open_count
    chunk = b"\xFF"

    def _make_ws():
        ws = AsyncMock()
        ws.send = AsyncMock()
        ws.recv = AsyncMock(return_value=_audio_msg(chunk, is_final=True))
        ws.close = AsyncMock()
        return ws

    ws_pool = [_make_ws(), _make_ws(), _make_ws()]
    pool_idx = [0]

    async def _next_ws(*_args, **_kwargs):
        ws = ws_pool[pool_idx[0]]
        ws.recv = AsyncMock(return_value=_audio_msg(chunk, is_final=True))
        pool_idx[0] += 1
        return ws

    client = ElevenLabsWSClient()
    with patch("tts.elevenlabs_ws.settings", _fake_settings()):
        with patch("websockets.connect", side_effect=_next_ws):
            for _ in range(3):
                async for _ in client.stream_sentence("Hi."):
                    pass

    assert ws_mod.tts_ws_open_count == before + 3


# ---------------------------------------------------------------------------
# Test 6 — tts_with_fallback uses WS tier when API key is configured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_uses_ws_tier_when_available():
    from agent.fallback import tts_with_fallback
    import tts.elevenlabs_ws as ws_mod

    chunk = b"\xFF\xFE"

    async def _fake_stream(_text, _call_metrics=None):
        yield chunk

    original_client = ws_mod._shared_client
    mock_client = MagicMock()
    mock_client.is_available = MagicMock(return_value=True)
    mock_client.stream_sentence = _fake_stream

    http_mock = MagicMock()

    try:
        ws_mod._shared_client = mock_client
        # Patch the reference imported into fallback module
        with patch("agent.fallback._ws_client", mock_client):
            received = []
            async for c in tts_with_fallback("Hello.", http_mock):
                received.append(c)
    finally:
        ws_mod._shared_client = original_client

    assert received == [chunk], "WS tier should have been used"


# ---------------------------------------------------------------------------
# Test 7 — tts_with_fallback falls through to HTTP when WS raises
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_falls_through_to_http_on_ws_error():
    from agent.fallback import tts_with_fallback

    http_chunk = b"\x11\x22"

    async def _failing_stream(_text, _call_metrics=None):
        raise ConnectionError("ws dead")
        yield  # make it an async generator

    mock_client = MagicMock()
    mock_client.is_available = MagicMock(return_value=True)
    mock_client.stream_sentence = _failing_stream

    async def _aiter_bytes(_size):
        yield http_chunk

    resp_mock = MagicMock()
    resp_mock.raise_for_status = MagicMock()
    resp_mock.aiter_bytes = _aiter_bytes

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp_mock)
    cm.__aexit__ = AsyncMock(return_value=False)

    http_mock = MagicMock()
    http_mock.stream = MagicMock(return_value=cm)

    with patch("agent.fallback._ws_client", mock_client):
        with patch("tts.elevenlabs_tts.settings", _fake_settings()):
            received = []
            async for c in tts_with_fallback("Hello.", http_mock):
                received.append(c)

    assert received == [http_chunk], "HTTP fallback tier should have been used"


# ---------------------------------------------------------------------------
# Test 8 — camelCase isFinal exits the recv loop cleanly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recv_handles_camelCase_isFinal():
    from tts.elevenlabs_ws import ElevenLabsWSClient

    chunk = b"\x01\x02\x03"
    ws_mock = _make_ws_mock([
        _audio_msg(chunk),
        json.dumps({"audio": None, "isFinal": True}),
    ])

    client = ElevenLabsWSClient()
    with patch("tts.elevenlabs_ws.settings", _fake_settings()):
        with patch("websockets.connect", AsyncMock(return_value=ws_mock)):
            received = []
            async for c in client.stream_sentence("Hello."):
                received.append(c)

    assert received == [chunk], "camelCase isFinal should exit the loop"
    ws_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test 9 — snake_case is_final also exits the recv loop (backward compat)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recv_handles_snake_case_is_final():
    from tts.elevenlabs_ws import ElevenLabsWSClient

    chunk = b"\x04\x05\x06"
    ws_mock = _make_ws_mock([
        _audio_msg(chunk),
        json.dumps({"audio": None, "is_final": True}),
    ])

    client = ElevenLabsWSClient()
    with patch("tts.elevenlabs_ws.settings", _fake_settings()):
        with patch("websockets.connect", AsyncMock(return_value=ws_mock)):
            received = []
            async for c in client.stream_sentence("Hello."):
                received.append(c)

    assert received == [chunk], "snake_case is_final should exit the loop"
    ws_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test 10 — third WS send is the EOS marker {"text": ""}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eos_sent_after_text():
    from tts.elevenlabs_ws import ElevenLabsWSClient

    chunk = b"\xAB\xCD"
    ws_mock = _make_ws_mock([_audio_msg(chunk, is_final=True)])
    send_calls = []
    original_send = ws_mock.send

    async def _capturing_send(payload):
        send_calls.append(payload)
        return await original_send(payload)

    ws_mock.send = _capturing_send

    client = ElevenLabsWSClient()
    with patch("tts.elevenlabs_ws.settings", _fake_settings()):
        with patch("websockets.connect", AsyncMock(return_value=ws_mock)):
            async for _ in client.stream_sentence("Hi there."):
                pass

    assert len(send_calls) == 3, f"Expected 3 sends (BOS, text, EOS), got {len(send_calls)}"
    eos = json.loads(send_calls[2])
    assert eos == {"text": ""}, f"Third send should be EOS, got {eos}"
