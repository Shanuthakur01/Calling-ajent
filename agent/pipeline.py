"""
StreamingPipeline — concurrent LLM→TTS→WebSocket audio pipeline.

Three asyncio tasks run concurrently via asyncio.Queue:

  [LLM worker] ──sentence_q──► [TTS worker] ──audio_q──► [WS sender]

LLM worker  : streams sentences from the LLM into sentence_q.
TTS worker  : reads sentences, calls TTS (with fallback), puts μ-law chunks
              into audio_q.  Sentences are processed sequentially so audio
              remains in order.
WS sender   : encodes chunks to base64, sends playAudio events over the
              Plivo WebSocket.

Cancellation (barge-in):
  Cancel the task returned by asyncio.create_task(pipeline.run(...)).
  CancelledError propagates into asyncio.gather(), which cancels all three
  workers.  Each worker's finally block puts a None sentinel so the next
  stage drains cleanly without hanging on queue.get().
"""

import asyncio
import base64
import logging
import time
from typing import Callable, List, Optional

import httpx
from fastapi import WebSocket

from agent.fallback import tts_with_fallback
from agent.metrics import CallMetrics, TurnMetrics
from llm.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SENTINEL = None   # queue end-of-stream marker


class StreamingPipeline:
    def __init__(
        self,
        websocket: WebSocket,
        stream_sid: str,
        llm: LLMClient,
        http: httpx.AsyncClient,
        call_metrics: Optional[CallMetrics] = None,
        on_audio_sent: Optional[Callable[[bytes], None]] = None,
        sentence_filter: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._ws           = websocket
        self._stream_sid   = stream_sid
        self._llm          = llm
        self._http         = http
        self._call_metrics = call_metrics
        self._on_audio_sent = on_audio_sent
        self._sentence_filter = sentence_filter

        self._sentence_q: asyncio.Queue[Optional[str]]   = asyncio.Queue(maxsize=10)
        self._audio_q:    asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=256)

        self._full_text: List[str] = []
        self._total_audio_bytes = 0

    async def run(
        self,
        history: list,
        metrics: TurnMetrics,
        *,
        prefilled_text: Optional[str] = None,
    ) -> tuple[str, float]:
        """
        Run the full pipeline and return (full_assistant_text, audio_duration_seconds).
        Raises CancelledError if the caller task is cancelled (barge-in).
        If prefilled_text is provided, the LLM call is skipped and the pre-computed
        text is fed directly into the TTS queue.
        """
        self._sentence_q       = asyncio.Queue(maxsize=10)
        self._audio_q          = asyncio.Queue(maxsize=256)
        self._full_text        = []
        self._total_audio_bytes = 0

        if prefilled_text is not None:
            llm_task = asyncio.create_task(
                self._prefilled_producer(prefilled_text, metrics), name="llm-prefilled"
            )
        else:
            llm_task = asyncio.create_task(self._llm_worker(history, metrics), name="llm-worker")
        tts_task = asyncio.create_task(self._tts_worker(metrics),           name="tts-worker")
        ws_task  = asyncio.create_task(self._ws_sender(metrics),            name="ws-sender")

        try:
            await asyncio.gather(llm_task, tts_task, ws_task)
        except asyncio.CancelledError:
            # Barge-in: cancel workers that are still running
            for t in (llm_task, tts_task, ws_task):
                if not t.done():
                    t.cancel()
            await asyncio.gather(llm_task, tts_task, ws_task, return_exceptions=True)
            raise

        full_text = " ".join(self._full_text)
        duration  = self._total_audio_bytes / 8000.0   # μ-law: 1 byte = 1 sample = 1/8000 s
        return full_text, duration

    # ── Workers ────────────────────────────────────────────────────────────

    async def _llm_worker(self, history: list, metrics: TurnMetrics) -> None:
        try:
            first = True
            metrics.t_llm_request = time.perf_counter()

            def _on_first_token() -> None:
                if metrics.t_first_token is None:
                    metrics.t_first_token = time.perf_counter()

            async for sentence in self._llm.stream_sentences(
                history,
                call_metrics=self._call_metrics,
                on_first_token=_on_first_token,
            ):
                if first:
                    t = time.perf_counter()
                    metrics.t_first_sentence = t
                    metrics.llm_ttft_ms = (t - metrics.start) * 1000
                    if self._call_metrics is not None and self._call_metrics.t_first_llm_token is None:
                        self._call_metrics.t_first_llm_token = t
                    first = False
                if self._sentence_filter is not None:
                    sentence = self._sentence_filter(sentence)
                if sentence:
                    self._full_text.append(sentence)
                    await self._sentence_q.put(sentence)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("LLM worker error: %s", exc, exc_info=True)
        finally:
            try:
                self._sentence_q.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass

    async def _tts_worker(self, metrics: TurnMetrics) -> None:
        try:
            first = True
            while True:
                sentence = await self._sentence_q.get()
                if sentence is _SENTINEL:
                    break
                try:
                    if first:
                        metrics.t_tts_request = time.perf_counter()
                    async for chunk in tts_with_fallback(
                        sentence, self._http, self._call_metrics,
                    ):
                        if first:
                            t = time.perf_counter()
                            metrics.tts_ttft_ms = (t - metrics.start) * 1000
                            metrics.t_first_tts_byte = t
                            first = False
                        self._total_audio_bytes += len(chunk)
                        await self._audio_q.put(chunk)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "TTS worker error for %r: %s", sentence[:40], exc, exc_info=True
                    )
        except asyncio.CancelledError:
            raise
        finally:
            try:
                self._audio_q.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass

    async def _ws_sender(self, metrics: TurnMetrics) -> None:
        try:
            first = True
            while True:
                chunk = await self._audio_q.get()
                if chunk is _SENTINEL:
                    break
                if first:
                    t = time.perf_counter()
                    metrics.e2e_first_audio_ms = (t - metrics.start) * 1000
                    metrics.t_first_ws_frame = t
                    if self._call_metrics is not None and self._call_metrics.t_first_audio_to_plivo is None:
                        self._call_metrics.t_first_audio_to_plivo = t
                    logger.info("First audio frame sent — e2e=%.0fms", metrics.e2e_first_audio_ms)
                    first = False
                payload = base64.b64encode(chunk).decode()
                await self._ws.send_json({
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate":  8000,
                        "payload":     payload,
                    },
                })
                if self._on_audio_sent is not None:
                    self._on_audio_sent(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("WS sender error: %s", exc, exc_info=True)

    async def _prefilled_producer(self, text: str, metrics: TurnMetrics) -> None:
        """Push pre-computed LLM text directly to sentence_q -- bypasses LLM."""
        try:
            from config import settings
            from llm.llm_client import _split_for_tts
            ends = frozenset(settings.sentence_delimiters)
            t = time.perf_counter()
            metrics.t_llm_request = t
            metrics.t_first_token = t

            first = True
            buf = text.strip()
            while buf:
                sentence, buf = _split_for_tts(buf, ends)
                chunk = sentence if sentence else buf
                if not chunk.strip():
                    break
                if not sentence:   # _split_for_tts couldn't split -- flush remainder
                    buf = ""
                if first:
                    ts = time.perf_counter()
                    metrics.t_first_sentence = ts
                    metrics.llm_ttft_ms = (ts - metrics.start) * 1000
                    if self._call_metrics is not None and self._call_metrics.t_first_llm_token is None:
                        self._call_metrics.t_first_llm_token = ts
                    first = False
                if self._sentence_filter is not None:
                    chunk = self._sentence_filter(chunk)
                if chunk:
                    self._full_text.append(chunk)
                    await self._sentence_q.put(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Prefilled producer error: %s", exc, exc_info=True)
        finally:
            try:
                self._sentence_q.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass
