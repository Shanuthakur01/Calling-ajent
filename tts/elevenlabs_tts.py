"""
ElevenLabs TTS — μ-law 8kHz streaming for Plivo WebSocket audio.

stream_sentence_mulaw(text, http_client)
  Streams raw μ-law 8kHz bytes directly (output_format=ulaw_8000).
  No WAV/MP3 headers, no audioop conversion needed.
  Yields 160-byte chunks (20 ms per chunk at 8kHz).
"""

import logging
import time
from typing import AsyncIterator, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.elevenlabs.io/v1"
_MULAW_FRAME = 160   # 20 ms × 8000 Hz × 1 byte/sample


async def stream_sentence_mulaw(
    text: str,
    http_client: httpx.AsyncClient,
    call_metrics: Optional[object] = None,
) -> AsyncIterator[bytes]:
    """
    Yield raw μ-law 8kHz bytes for a single sentence/text fragment.
    Guaranteed to close the HTTP stream on cancellation via async generator cleanup.
    call_metrics: if provided, sets t_first_tts_byte on the first chunk (once per call).
    """
    async with http_client.stream(
        "POST",
        f"{_BASE}/text-to-speech/{settings.elevenlabs_voice_id}/stream",
        headers={
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        },
        params={"output_format": "ulaw_8000", "optimize_streaming_latency": settings.tts_optimize_streaming_latency},
        json={
            "text": text,
            "model_id": settings.elevenlabs_model,
            "voice_settings": {
                "stability":        settings.tts_stability,
                "similarity_boost": settings.tts_similarity,
                "style":            settings.tts_style,
                "use_speaker_boost": settings.tts_speaker_boost,
                "speed":            settings.tts_speed,
            },
        },
        timeout=httpx.Timeout(30.0, connect=5.0),
    ) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes(_MULAW_FRAME):
            if chunk:
                if call_metrics is not None and call_metrics.t_first_tts_byte is None:
                    call_metrics.t_first_tts_byte = time.perf_counter()
                yield chunk

    logger.debug("ElevenLabs stream complete: %d chars", len(text))
