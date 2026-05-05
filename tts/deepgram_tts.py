"""
Deepgram Aura TTS — μ-law 8kHz streaming (TTS fallback provider).

Used by agent/fallback.py when ElevenLabs is unavailable.
Deepgram supports native ulaw encoding at 8kHz — no audioop conversion needed.
"""

import logging
from typing import AsyncIterator

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TTS_URL     = "https://api.deepgram.com/v1/speak"
_VOICE       = "aura-asteria-en"
_MULAW_FRAME = 160   # 20 ms × 8000 Hz × 1 byte/sample


async def stream_sentence_mulaw(
    text: str,
    http_client: httpx.AsyncClient,
) -> AsyncIterator[bytes]:
    """Yield raw μ-law 8kHz bytes via Deepgram Aura TTS."""
    async with http_client.stream(
        "POST",
        _TTS_URL,
        headers={
            "Authorization": f"Token {settings.deepgram_api_key}",
            "Content-Type": "application/json",
        },
        params={
            "model":       _VOICE,
            "encoding":    "ulaw",
            "sample_rate": "8000",
            "container":   "none",
        },
        json={"text": text},
        timeout=httpx.Timeout(30.0, connect=5.0),
    ) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes(_MULAW_FRAME):
            if chunk:
                yield chunk

    logger.debug("Deepgram TTS stream complete: %d chars", len(text))
