"""
Deepgram Nova-2 streaming STT over WebSocket.

Callback signature: on_transcript(text: str, is_final: bool, confidence: float)

Key distinction:
  is_final=True      → Deepgram finalised a speech window
  speech_final=True  → end-of-speech detected (endpointing_ms silence)
  UtteranceEnd       → backup end-of-speech after utterance_end_ms

We accumulate is_final windows in _buf; only fire the callback with
is_final=True on speech_final or UtteranceEnd.

Reconnect: exponential backoff (1 s → 16 s cap) on connection loss.
"""

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import websockets
import websockets.exceptions

from config import settings

logger = logging.getLogger(__name__)


def _build_url() -> str:
    return (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-2"
        "&encoding=linear16"
        "&sample_rate=8000"
        "&channels=1"
        f"&endpointing={settings.dg_endpointing_ms}"
        "&interim_results=true"
        f"&utterance_end_ms={settings.dg_utterance_end_ms}"
        "&vad_events=true"
        "&smart_format=true"
        "&punctuate=true"
        "&keywords=yes:6"
        "&keywords=no:6"
        "&keywords=okay:4"
        "&keywords=sure:4"
        "&keywords=right:3"
        "&keywords=correct:3"
        "&keywords=yep:4"
        "&keywords=nope:3"
        "&keywords=haan:5"
        "&keywords=nahi:5"
    )


class DeepgramSTTClient:
    def __init__(
        self,
        on_transcript: Callable[[str, bool, float], Awaitable[None]],
        on_speech_started: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        self._on_transcript = on_transcript
        self._on_speech_started = on_speech_started
        self._url     = _build_url()
        self._ws      = None
        self._running = False
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)
        self._buf = ""

    async def connect(self) -> None:
        self._running = True
        self._ws = await self._open_ws()
        logger.info("Deepgram STT connected")
        asyncio.create_task(self._sender(),   name="dg-sender")
        asyncio.create_task(self._receiver(), name="dg-receiver")

    async def send_audio(self, linear16: bytes) -> None:
        if self._running:
            try:
                self._send_queue.put_nowait(linear16)
            except asyncio.QueueFull:
                pass

    def clear_buffer(self) -> None:
        self._buf = ""

    # ── Internal ───────────────────────────────────────────────────────────

    async def _open_ws(self):
        return await websockets.connect(
            self._url,
            additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        )

    async def _sender(self) -> None:
        while self._running:
            try:
                chunk = await asyncio.wait_for(self._send_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

            while self._running:
                ws = self._ws
                if ws is None:
                    await asyncio.sleep(0.1)
                    continue
                try:
                    await asyncio.wait_for(ws.send(chunk), timeout=3.0)
                    break
                except Exception:
                    await asyncio.sleep(0.1)

    async def _receiver(self) -> None:
        backoff = 1.0
        while self._running:
            ws = self._ws
            if ws is None:
                await asyncio.sleep(0.1)
                continue
            try:
                raw = await ws.recv()
                backoff = 1.0
                await self._parse(raw)
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ):
                if not self._running:
                    break
                logger.warning("Deepgram WS closed — reconnecting in %.0fs", backoff)
                self._ws = None
                try:
                    await ws.close()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
                try:
                    self._ws = await self._open_ws()
                    logger.info("Deepgram STT reconnected")
                    backoff = 1.0
                except Exception as exc:
                    logger.error("Deepgram reconnect failed: %s", exc)
            except Exception as exc:
                if self._running:
                    logger.warning("Deepgram receiver error: %s", exc)
                break

    async def _parse(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        if msg_type == "Results":
            alts = msg.get("channel", {}).get("alternatives", [])
            if not alts:
                return
            text       = alts[0].get("transcript", "").strip()
            confidence = float(alts[0].get("confidence", 0.0))
            if not text:
                return

            is_final     = msg.get("is_final", False)
            speech_final = msg.get("speech_final", False)

            if speech_final:
                full = (self._buf + " " + text).strip()
                self._buf = ""
                logger.info("STT speech_final: %r (conf=%.2f)", full, confidence)
                await self._on_transcript(full, True, confidence)
            elif is_final:
                self._buf = (self._buf + " " + text).strip()
                await self._on_transcript(self._buf, False, confidence)
            else:
                display = (self._buf + " " + text).strip()
                await self._on_transcript(display, False, confidence)

        elif msg_type == "SpeechStarted":
            if self._on_speech_started is not None:
                await self._on_speech_started()

        elif msg_type == "UtteranceEnd":
            if self._buf.strip():
                text = self._buf.strip()
                self._buf = ""
                logger.info("STT UtteranceEnd flush: %r", text)
                await self._on_transcript(text, True, 1.0)

        elif msg_type == "Error":
            logger.error("Deepgram error event: %s", msg)

    async def close(self) -> None:
        self._running = False
        ws, self._ws = self._ws, None
        if ws:
            try:
                await ws.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass
        logger.info("Deepgram STT closed")
