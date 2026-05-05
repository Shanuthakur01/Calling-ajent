"""
Integration test: first audio frame must reach the WebSocket within 1500 ms
of pipeline start, and its JSON shape must match the Plivo playAudio spec.

Mocks:
  - Plivo WebSocket (AsyncMock with call-time recording)
  - ElevenLabs TTS via tts_with_fallback (50 ms latency, then μ-law frames)
  - LLM stream_sentences (instant, one sentence)

Assertions:
  1. First ws.send_json(playAudio) arrives within 1500 ms of pipeline.run() call.
  2. Payload JSON shape:
       {"event": "playAudio",
        "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000,
                  "payload": "<base64>"}}
"""

import asyncio
import base64
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MULAW_FRAME = b"\x7f" * 160   # 160 bytes = 20 ms of μ-law silence


def make_instant_llm(sentence: str):
    async def _gen(history, **kwargs):
        yield sentence
    return _gen


async def _slow_tts(text: str, http, call_metrics=None, **_kwargs):
    """50 ms cold-start then 5 × 160-byte frames."""
    await asyncio.sleep(0.05)
    for _ in range(5):
        yield _MULAW_FRAME


@pytest.mark.asyncio
async def test_first_audio_within_1500ms():
    """First playAudio frame must arrive within 1500 ms of pipeline.run()."""
    from agent.pipeline import StreamingPipeline
    from agent.metrics import TurnMetrics

    first_send_time: list[float] = []

    ws = AsyncMock()

    async def _capture(data):
        if not first_send_time and data.get("event") == "playAudio":
            first_send_time.append(time.perf_counter())

    ws.send_json.side_effect = _capture

    llm = MagicMock()
    llm.stream_sentences = make_instant_llm("Hello, this is a latency test.")

    with patch("agent.pipeline.tts_with_fallback", _slow_tts):
        pipeline = StreamingPipeline(
            websocket=ws,
            stream_sid="sid-latency",
            llm=llm,
            http=AsyncMock(),
        )
        metrics = TurnMetrics(call_id="lat-test")
        t_start = time.perf_counter()
        await asyncio.wait_for(pipeline.run([], metrics), timeout=5.0)

    assert first_send_time, "No playAudio frame was ever sent"
    elapsed_ms = (first_send_time[0] - t_start) * 1000
    assert elapsed_ms < 1500, (
        f"First audio frame took {elapsed_ms:.0f} ms — exceeds 1500 ms limit"
    )


@pytest.mark.asyncio
async def test_play_audio_json_shape():
    """playAudio JSON must match the Plivo bidirectional streaming spec exactly."""
    from agent.pipeline import StreamingPipeline
    from agent.metrics import TurnMetrics

    ws = AsyncMock()
    llm = MagicMock()
    llm.stream_sentences = make_instant_llm("Shape test.")

    with patch("agent.pipeline.tts_with_fallback", _slow_tts):
        pipeline = StreamingPipeline(
            websocket=ws,
            stream_sid="sid-shape",
            llm=llm,
            http=AsyncMock(),
        )
        metrics = TurnMetrics(call_id="shape-test")
        await asyncio.wait_for(pipeline.run([], metrics), timeout=5.0)

    assert ws.send_json.called, "send_json was never called"
    msg = ws.send_json.call_args_list[0][0][0]

    # Top-level structure
    assert msg["event"] == "playAudio"
    assert "media" in msg

    media = msg["media"]
    assert media["contentType"] == "audio/x-mulaw"
    assert media["sampleRate"] == 8000   # integer, not string
    assert "payload" in media

    # Payload must be valid base64 encoding of exactly one 160-byte μ-law frame
    decoded = base64.b64decode(media["payload"])
    assert len(decoded) == 160
