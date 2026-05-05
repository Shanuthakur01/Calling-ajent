"""
BackchannelPlayer — pre-cached short ack clips played during listening.

Ack clips are generated via ElevenLabs at startup and cached to
cache/acks/*.ulaw. If generation fails, the player silently returns None
(backchannels are non-fatal and disabled gracefully on any error).

Usage:
    player = await ensure_ack_cache(http_client)
    clip = player.pick()   # returns μ-law bytes or None
"""

import asyncio
import base64
import logging
import random
from pathlib import Path
from typing import Dict, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "cache" / "acks"

_ACK_TEXTS: Dict[str, str] = {
    "mhm":    "Mhm.",
    "yeah":   "Yeah.",
    "right":  "Right.",
    "okay":   "Okay.",
    "got_it": "Got it.",
}


class BackchannelPlayer:
    def __init__(self, clips: Dict[str, bytes]) -> None:
        self._clips = clips
        self._names = list(clips.keys())
        self._last: Optional[str] = None

    def pick(self) -> Optional[bytes]:
        """Return μ-law bytes for a random ack, avoiding two identical picks in a row."""
        if not self._names:
            return None
        candidates = [n for n in self._names if n != self._last]
        if not candidates:
            candidates = self._names
        name = random.choice(candidates)
        self._last = name
        return self._clips[name]


async def ensure_ack_cache(http: httpx.AsyncClient) -> BackchannelPlayer:
    """Load cached ack clips or generate them via ElevenLabs. Non-fatal on failure."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    clips: Dict[str, bytes] = {}

    for name, text in _ACK_TEXTS.items():
        path = _CACHE_DIR / f"{name}.ulaw"
        if path.exists():
            clips[name] = path.read_bytes()
            logger.info("Backchannel loaded from cache: %s (%d bytes)", name, len(clips[name]))
        elif settings.elevenlabs_api_key:
            try:
                data = await _generate_ulaw(text, http)
                path.write_bytes(data)
                clips[name] = data
                logger.info("Backchannel generated: %s (%d bytes)", name, len(data))
            except Exception as exc:
                logger.warning("Backchannel generation failed for %r: %s", name, exc)

    if not clips:
        logger.warning("No backchannel clips available — backchannels disabled")

    return BackchannelPlayer(clips)


class BackchannelManager:
    """
    Manages a single fire-and-forget backchannel clip task.

    Design invariants:
    - At most one clip task is live at a time (_task ref).
    - Never started while state is not LISTENING.
    - cancel() is synchronous: kills the task immediately and schedules
      a clearAudio to flush Plivo's buffer (fire-and-forget async).
    - maybe_play() is safe to call on every interim STT event; it guards
      all timing conditions internally.
    """

    def __init__(
        self,
        player: BackchannelPlayer,
        websocket,
        stream_sid: str,
        call_sid: str,
    ) -> None:
        self._player     = player
        self._ws         = websocket
        self._stream_sid = stream_sid
        self._call_sid   = call_sid
        self._task: Optional[asyncio.Task] = None

    def maybe_play(
        self,
        *,
        is_listening: bool,
        speech_started_at: Optional[float],
        last_played_at: float,
        now: float,
        min_speech_s: float,
        min_interval_s: float,
    ) -> float:
        """
        Schedule a clip if timing conditions are met.
        Returns updated last_played_at (unchanged if clip not scheduled).
        Never fires when is_listening=False.
        """
        if not is_listening:
            return last_played_at
        if speech_started_at is None:
            return last_played_at
        if (now - speech_started_at) < min_speech_s:
            return last_played_at
        if (now - last_played_at) < min_interval_s:
            return last_played_at

        clip = self._player.pick()
        if not clip:
            return last_played_at

        if self._task and not self._task.done():
            self._task.cancel()

        self._task = asyncio.create_task(
            self._play(clip),
            name=f"bchannel-{self._call_sid}",
        )
        return now

    def cancel(self) -> None:
        """Cancel any in-flight clip synchronously and flush Plivo's buffer."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        asyncio.create_task(
            self._clear_audio(),
            name=f"bchannel-clear-{self._call_sid}",
        )

    async def _play(self, clip: bytes) -> None:
        try:
            payload = base64.b64encode(clip).decode()
            await self._ws.send_json({
                "event": "playAudio",
                "media": {
                    "contentType": "audio/x-mulaw",
                    "sampleRate":  8000,
                    "payload":     payload,
                },
            })
        except Exception as exc:
            logger.debug("Backchannel send error call=%s: %s", self._call_sid, exc)

    async def _clear_audio(self) -> None:
        try:
            await self._ws.send_json({
                "event":     "clearAudio",
                "streamSid": self._stream_sid,
            })
        except Exception as exc:
            logger.debug("Backchannel clearAudio error call=%s: %s", self._call_sid, exc)


async def _generate_ulaw(text: str, http: httpx.AsyncClient) -> bytes:
    """Generate μ-law 8kHz audio for text via ElevenLabs streaming TTS."""
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/"
        f"{settings.elevenlabs_voice_id}/stream"
    )
    chunks = []
    async with http.stream(
        "POST",
        url,
        headers={"xi-api-key": settings.elevenlabs_api_key},
        params={"output_format": "ulaw_8000", "optimize_streaming_latency": settings.tts_optimize_streaming_latency},
        json={
            "text": text,
            "model_id": settings.elevenlabs_model,
            "voice_settings": {
                "stability":         settings.tts_stability,
                "similarity_boost":  settings.tts_similarity,
                "style":             settings.tts_style,
                "use_speaker_boost": settings.tts_speaker_boost,
                "speed":             settings.tts_speed,
            },
        },
    ) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes(160):
            if chunk:
                chunks.append(chunk)
    return b"".join(chunks)
