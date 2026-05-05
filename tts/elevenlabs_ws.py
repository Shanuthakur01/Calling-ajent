"""
Per-call ElevenLabs WebSocket TTS client.

Each stream_sentence() call opens a fresh WebSocket, sends BOS + text,
streams audio chunks, then closes the connection in a finally block.

No long-lived connection.  No reconnect loop.  No background tasks.

tts_ws_open_count: module-level int incremented per successful WebSocket open.
"""

import asyncio
import base64
import json
import logging
import time
from typing import AsyncIterator, Optional

import websockets
import websockets.exceptions

from config import settings

logger = logging.getLogger(__name__)

# Module-level counter — read by /debug/config
tts_ws_open_count: int = 0


def _ws_url() -> str:
    return (
        f"wss://api.elevenlabs.io/v1/text-to-speech"
        f"/{settings.elevenlabs_voice_id}/stream-input"
        f"?model_id={settings.elevenlabs_model}"
        f"&output_format=ulaw_8000"
        f"&optimize_streaming_latency={settings.tts_optimize_streaming_latency}"
    )


def _voice_settings() -> dict:
    return {
        "stability":         settings.tts_stability,
        "similarity_boost":  settings.tts_similarity,
        "style":             settings.tts_style,
        "use_speaker_boost": settings.tts_speaker_boost,
        "speed":             settings.tts_speed,
    }


class ElevenLabsWSClient:
    """
    Per-call WebSocket TTS client.

    stream_sentence() opens a fresh WS per sentence, yields μ-law chunks,
    and closes the WS in a finally block — even on consumer cancel or exception.
    """

    def is_available(self) -> bool:
        return bool(settings.elevenlabs_api_key)

    async def stream_sentence(
        self,
        text: str,
        call_metrics=None,
    ) -> AsyncIterator[bytes]:
        """
        Open a fresh WebSocket, yield μ-law 8 kHz audio for `text`, close.
        Raises on error — tts_with_fallback handles the fallback tiers.
        """
        global tts_ws_open_count
        ws = None
        t0 = time.perf_counter()
        url = _ws_url()
        logger.info("TTS_WS connecting  url=%s  text=%r", url, text[:60])
        try:
            ws = await websockets.connect(
                url,
                additional_headers={"xi-api-key": settings.elevenlabs_api_key},
                ping_interval=None,   # short-lived connection; no keepalive needed
                close_timeout=3,
            )
            tts_ws_open_count += 1
            handshake_ms = (time.perf_counter() - t0) * 1000
            logger.info("TTS_WS connected  handshake_ms=%.1f  open_count=%d",
                        handshake_ms, tts_ws_open_count)

            # BOS: voice settings initialisation
            bos_payload = json.dumps({
                "text": " ",
                "voice_settings": _voice_settings(),
                "try_trigger_generation": True,
            })
            logger.info("TTS_WS sending BOS  payload=%s", bos_payload)
            await ws.send(bos_payload)
            logger.info("TTS_WS BOS sent")

            # Text payload
            text_payload = json.dumps({
                "text": text + " ",
                "flush": True,
                "try_trigger_generation": True,
            })
            logger.info("TTS_WS sending text payload  payload=%s", text_payload)
            await ws.send(text_payload)
            logger.info("TTS_WS text sent")

            # EOS: signal no more input so ElevenLabs finalises and sends isFinal
            await ws.send(json.dumps({"text": ""}))
            logger.info("TTS_WS EOS sent — waiting for first recv")

            first_byte = True
            chunk_n = 0
            while True:
                t_recv_start = time.perf_counter()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                except asyncio.TimeoutError:
                    logger.error(
                        "TTS_WS recv TIMEOUT after %.1fs  chunk_n=%d  text=%r",
                        time.perf_counter() - t_recv_start, chunk_n, text[:60],
                    )
                    raise ConnectionError(
                        f"ElevenLabs WS recv timeout for: {text[:40]!r}"
                    )
                recv_ms = (time.perf_counter() - t_recv_start) * 1000
                msg = json.loads(raw)
                audio_b64 = msg.get("audio")
                # Accept both camelCase (API v1) and snake_case (backward compat)
                is_final = msg.get("isFinal") or msg.get("is_final") or False
                normalised = msg.get("normalizedAlignment")
                logger.info(
                    "TTS_WS recv #%d  recv_ms=%.1f  has_audio=%s  is_final=%s  "
                    "has_alignment=%s  extra_keys=%s",
                    chunk_n, recv_ms, bool(audio_b64), is_final,
                    normalised is not None,
                    [k for k in msg if k not in (
                        "audio", "isFinal", "is_final", "normalizedAlignment",
                    )],
                )
                if audio_b64:
                    data = base64.b64decode(audio_b64)
                    if first_byte:
                        first_byte = False
                        logger.info(
                            "TTS_WS first audio byte  ttfb_ms=%.1f  bytes=%d",
                            (time.perf_counter() - t0) * 1000, len(data),
                        )
                        if call_metrics is not None and call_metrics.t_first_tts_byte is None:
                            call_metrics.t_first_tts_byte = time.perf_counter()
                    chunk_n += 1
                    yield data
                if is_final:
                    logger.info("TTS_WS isFinal received  total_chunks=%d", chunk_n)
                    break
        finally:
            if ws is not None:
                try:
                    await ws.close()
                    logger.info("TTS_WS closed cleanly  total_ms=%.1f",
                                (time.perf_counter() - t0) * 1000)
                except Exception as exc:
                    logger.warning("TTS_WS close error: %s", exc)


# Module-level shared instance — zero-cost to create (no connection state).
_shared_client = ElevenLabsWSClient()
