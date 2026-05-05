"""
CallSession — per-call orchestrator.

State machine:
  IDLE  → start() →  SPEAKING (greeting)  →  LISTENING
  LISTENING  → STT final  →  PROCESSING  →  SPEAKING (pipeline)  →  LISTENING
  SPEAKING   → barge-in   →  cancel old  →  PROCESSING  →  SPEAKING  →  LISTENING

Audio gate:
  PROCESSING  : audio blocked (LLM is deciding; spurious STT would start a new
                pipeline before the current one even begins to speak)
  LISTENING   : audio forwarded → STT (normal turn)
  SPEAKING    : audio forwarded → STT (barge-in detection)

Barge-in:
  On is_final=True during SPEAKING (min settings.min_barge_in_words words, default 3)
  or interim with confidence >= settings.barge_in_threshold and same word minimum:
  cancel the running pipeline task, send clearAudio to Plivo, start a new pipeline.
  SpeechStarted VAD events also trigger barge-in when EchoGuard says agent is silent.

Crash isolation:
  _run_pipeline() catches all non-CancelledError exceptions so a crash in one
  turn does not end the call.  The WebSocket handler (plivo_handler.py) also
  has a top-level catch to isolate calls from each other.

Latency metrics:
  TurnMetrics is created when speech_final fires; timestamps are recorded at
  each pipeline stage.  CallMetrics prints a summary at call end.
"""

import asyncio
import base64
import logging
import re
import time
from enum import Enum
from typing import Callable, Dict, List, Optional

import httpx

from agent.backchannels import BackchannelManager, BackchannelPlayer
from agent.echo_guard import EchoGuard
from agent.fallback import tts_with_fallback
from agent.metrics import CallMetrics, TurnMetrics
from agent.pipeline import StreamingPipeline
from agent.session_registry import register, unregister
from agent.speculative import SpeculativeWorker
from audio.converter import decode_twilio_payload, mulaw_to_linear16
from pathlib import Path

from config import settings
from agent.recorder import CallRecorder
from llm.llm_client import LLMClient
from stt.deepgram_client import DeepgramSTTClient
from telephony.plivo_rest import PlivoRestClient

logger = logging.getLogger(__name__)


def _is_system_phrase(text: str) -> bool:
    """Return True if text matches a configured drop phrase (IVR/hold-music self-echo)."""
    phrases = settings.stt_drop_phrases_list()
    if not phrases:
        return False
    lower = text.lower()
    return any(p in lower for p in phrases)


def _is_meaningful_short_utterance(text: str) -> bool:
    """Return True if text is a single short word that carries intent (e.g. "sorry?", "yeah").

    Lets whitelisted words bypass the min_utterance_words filter so that
    repeat-request words like "sorry?" and affirmatives like "yeah" reach the LLM
    even though they are only one word.
    """
    cleaned = text.lower().strip().rstrip("?.,!").strip()
    return cleaned in settings.short_utterance_whitelist_set()


_INJECTION_RE = re.compile(
    r"(?i)ignore\s+(previous|all)\s+instructions|system\s*:|<\|",
)
_SAFE_FILLER = "Let me get back to you on that."


def _sanitize_user_input(text: str) -> str:
    """Strip prompt-injection patterns from STT transcript before sending to LLM."""
    sanitized = _INJECTION_RE.sub("[redacted]", text)
    if sanitized != text:
        logger.warning("Prompt injection stripped from user input: %r", text[:120])
    return sanitized


def _make_sentence_filter() -> Callable[[str], str]:
    """Return a per-turn closure that enforces forbidden-phrase and length caps."""
    forbidden = [p.strip().lower() for p in settings.forbidden_phrases.split(",") if p.strip()]
    max_chars  = settings.max_llm_response_chars
    used: list[int] = [0]  # mutable ref — tracks chars already sent this turn

    def _filter(sentence: str) -> str:
        # Forbidden phrase check
        lower = sentence.lower()
        for phrase in forbidden:
            if phrase in lower:
                logger.warning("Forbidden phrase %r — replacing with safe filler", phrase)
                sentence = _SAFE_FILLER
                break
        # Length cap: drop sentence if we've already exceeded max_chars
        remaining = max_chars - used[0]
        if remaining <= 0:
            logger.warning("LLM response over %d chars — dropping sentence: %r", max_chars, sentence[:60])
            return ""
        if len(sentence) > remaining:
            # Truncate at last sentence-boundary char within the remaining budget
            truncated = sentence[:remaining]
            for delim in ".!?":
                idx = truncated.rfind(delim)
                if idx >= 12:
                    sentence = truncated[:idx + 1]
                    break
            else:
                sentence = truncated.rstrip()
            logger.warning("LLM response truncated at %d chars", max_chars)
        used[0] += len(sentence)
        return sentence

    return _filter


# Extra seconds to sleep after the last audio frame so Plivo finishes playing.
# μ-law over WebSocket has low latency; 0.4 s covers jitter + Plivo buffering.
_PLIVO_BUFFER = 0.4

_GOODBYE = (
    "Thank you so much for your time today. "
    "We'll be in touch soon. Goodbye!"
)


class State(str, Enum):
    IDLE       = "idle"
    LISTENING  = "listening"
    PROCESSING = "processing"
    SPEAKING   = "speaking"


class CallSession:
    def __init__(
        self,
        websocket,
        stream_sid: str,
        call_sid: str,
        llm: LLMClient,
        plivo: PlivoRestClient,
        http: httpx.AsyncClient,
        backchannels: Optional[BackchannelPlayer] = None,
    ) -> None:
        self._ws         = websocket
        self._stream_sid = stream_sid
        self._call_sid   = call_sid

        self._llm   = llm
        self._plivo = plivo
        self._http  = http

        # BackchannelManager: None when backchannels are disabled or no clips available.
        if backchannels is not None and settings.enable_backchannels:
            self._bcm: Optional[BackchannelManager] = BackchannelManager(
                player=backchannels,
                websocket=websocket,
                stream_sid=stream_sid,
                call_sid=call_sid,
            )
        else:
            self._bcm = None

        self._state  = State.IDLE
        self._active = True

        self._history: List[Dict] = [
            {"role": "system", "content": settings.system_prompt}
        ]

        self._stt = DeepgramSTTClient(
            on_transcript=self._on_transcript,
            on_speech_started=self._on_speech_started_vad,
        )
        self._echo_guard = EchoGuard()
        self._speculative: Optional[SpeculativeWorker] = (
            SpeculativeWorker(llm) if settings.speculative_llm_enabled else None
        )

        self._pipeline_lock = asyncio.Lock()
        self._current_task: Optional[asyncio.Task] = None

        self._stt_final_at: Optional[float] = None
        self._last_stt_at   = time.monotonic()

        self._utterance_buffer: List[str] = []
        self._endpoint_timer: Optional[asyncio.Task] = None

        self._post_speech_mute_until: float = 0.0
        self._last_pipeline_text: str = ""
        self._last_pipeline_at: float = 0.0

        self._speech_started_at: Optional[float] = None
        self._last_backchannel_at: float = 0.0

        self._call_metrics = CallMetrics(call_id=call_sid)
        self._call_metrics.t_ws_connected = time.perf_counter()

        self._end_reason: str = "user_hangup"
        self._pipelines_fired: int = 0
        if settings.recording_enabled:
            self._recorder: Optional[CallRecorder] = CallRecorder(
                call_sid, Path(settings.recording_dir).resolve()
            )
        else:
            self._recorder = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect STT, start watchdog, play greeting. Called as a background task."""
        logger.info("CallSession starting — call_sid=%s", self._call_sid)
        register(self)
        try:
            await self._stt.connect()
            if self._recorder is not None:
                await self._recorder.start()
            asyncio.create_task(
                self._silence_watchdog(), name=f"watchdog-{self._call_sid}"
            )
            asyncio.create_task(
                self._hard_timeout_watchdog(), name=f"hard-timeout-{self._call_sid}"
            )
            await self._say(settings.greeting_message)
        except Exception as exc:
            logger.error("CallSession start error call=%s: %s", self._call_sid, exc, exc_info=True)
            self._state = State.LISTENING

    async def close(self) -> None:
        if not self._active:
            return
        self._active = False

        timer = self._endpoint_timer
        if timer and not timer.done():
            timer.cancel()
            try:
                await timer
            except (asyncio.CancelledError, Exception):
                pass

        task = self._current_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        if self._speculative is not None:
            self._speculative.cancel()

        await self._stt.close()
        unregister(self._call_sid)

        if self._recorder is not None:
            import tts.elevenlabs_ws as _tws_mod
            cm = self._call_metrics
            n  = len(cm.turns)
            rec_metrics = {
                "turns":                  n,
                "avg_e2e_ms":             round(sum(t.e2e_first_audio_ms for t in cm.turns) / n) if n else 0,
                "avg_llm_ttft_ms":        round(sum(t.llm_ttft_ms        for t in cm.turns) / n) if n else 0,
                "avg_tts_ttft_ms":        round(sum(t.tts_ttft_ms        for t in cm.turns) / n) if n else 0,
                "speculative_hit_rate":   round(cm.speculative_hit_rate, 2),
                "speculative_savings_ms": round(cm.speculative_savings_ms),
                "fallbacks_triggered":    cm.fallbacks_triggered,
                "tts_ws_open_count":      _tws_mod.tts_ws_open_count,
                "pipelines_fired":        self._pipelines_fired,
            }
            await self._recorder.close(self._end_reason, rec_metrics)

        self._call_metrics.log_summary()
        logger.info("CallSession %s closed", self._call_sid)

    # ── Inbound audio → STT ───────────────────────────────────────────────

    async def handle_audio(self, payload: str) -> None:
        # Block only during LLM processing — the response isn't ready yet and
        # any STT result would start a premature second pipeline.
        if self._state == State.PROCESSING:
            return
        mulaw    = decode_twilio_payload(payload)
        linear16 = mulaw_to_linear16(mulaw)
        # Echo-guard: drop audio during post-speech window if it looks like agent echo
        if time.monotonic() < self._post_speech_mute_until:
            if self._echo_guard.is_echo(linear16):
                return
        await self._stt.send_audio(linear16)

    # ── STT callback ──────────────────────────────────────────────────────

    async def _on_transcript(self, text: str, is_final: bool, confidence: float) -> None:
        if text:
            self._last_stt_at = time.monotonic()
            if self._call_metrics.t_first_stt_partial is None:
                self._call_metrics.t_first_stt_partial = time.perf_counter()

        if not self._active or not text.strip():
            return

        # Silently drop known system/IVR phrases (hold music, on-hold messages)
        if _is_system_phrase(text):
            logger.debug("STT dropped (system phrase): %r", text)
            return

        if self._state == State.SPEAKING:
            task = self._current_task
            if task and not task.done():
                should_barge = (
                    (is_final and len(text.split()) >= settings.min_barge_in_words) or
                    (not is_final and confidence >= settings.barge_in_threshold
                     and len(text.split()) >= settings.min_barge_in_words)
                )
                if should_barge:
                    # Flip state BEFORE spawning the task — any transcript arriving
                    # between now and when _handle_barge_in_cancel runs will see
                    # LISTENING state and go through the normal endpoint-buffer path,
                    # preventing a second barge-in task from being spawned.
                    self._state = State.LISTENING
                    task.cancel()
                    asyncio.create_task(
                        self._handle_barge_in_cancel(text), name=f"barge-{self._call_sid}"
                    )
            return

        # Drop STT during the 300 ms acoustic tail after the agent finishes speaking
        if time.monotonic() < self._post_speech_mute_until:
            if confidence < settings.barge_in_threshold:
                logger.debug("STT muted (acoustic tail): %r", text)
                return

        if not is_final:
            if self._state == State.LISTENING:
                self._maybe_backchannel()
                if self._speculative is not None:
                    self._speculative.maybe_start(text, self._history)
            return

        # is_final — reset per-utterance speech timer
        self._speech_started_at = None
        if self._state != State.LISTENING:
            return

        logger.info("STT final: %r (conf=%.2f)", text, confidence)
        self._utterance_buffer.append(text)

        # Restart the endpoint timer on every is_final
        if self._endpoint_timer and not self._endpoint_timer.done():
            self._endpoint_timer.cancel()
        self._endpoint_timer = asyncio.create_task(
            self._endpoint_timeout(), name=f"endpoint-{self._call_sid}"
        )

    # ── Endpoint timer ────────────────────────────────────────────────────

    async def _endpoint_timeout(self) -> None:
        """Sleep endpoint_ms then fire _handle_user_turn."""
        try:
            await asyncio.sleep(settings.endpoint_ms / 1000.0)
            await self._handle_user_turn()
        except asyncio.CancelledError:
            pass

    async def _handle_user_turn(self) -> None:
        """Flush the utterance buffer and start a pipeline turn."""
        text = " ".join(self._utterance_buffer).strip()
        self._utterance_buffer.clear()
        self._endpoint_timer = None

        if not text or not self._active:
            return
        word_count = len(text.split())
        if word_count < settings.min_utterance_words and not _is_meaningful_short_utterance(text):
            logger.info("Utterance too short (%d word(s)), skipping: %r", word_count, text)
            return

        # Dedupe: identical text within 500 ms of the previous pipeline start is dropped.
        # Prevents cascading barge-in bursts from firing multiple pipelines for the same speech.
        now = time.perf_counter()
        if text == self._last_pipeline_text and (now - self._last_pipeline_at) < 0.5:
            logger.debug("Dedupe: dropped duplicate turn %r", text)
            return
        self._last_pipeline_text = text
        self._last_pipeline_at   = now

        self._stt_final_at = now
        if self._call_metrics.t_user_speech_end is None:
            self._call_metrics.t_user_speech_end = self._stt_final_at

        # Cancel any in-flight backchannel and flush Plivo's buffer before
        # the pipeline starts sending its own audio.
        if self._bcm is not None:
            self._bcm.cancel()

        text = _sanitize_user_input(text)
        if self._recorder is not None:
            self._recorder.add_user_turn(text)

        prefilled_text: Optional[str] = None
        if self._speculative is not None:
            result = await self._speculative.try_consume(text)
            if result is not None:
                prefilled_text, savings_ms = result
                self._call_metrics.speculative_hits += 1
                self._call_metrics.speculative_savings_ms += savings_ms
            else:
                self._call_metrics.speculative_misses += 1

        self._state = State.PROCESSING
        self._current_task = asyncio.create_task(
            self._run_pipeline(text, prefilled_text=prefilled_text),
            name=f"pipeline-{self._call_sid}",
        )

    # ── Barge-in ──────────────────────────────────────────────────────────

    async def _handle_barge_in_cancel(self, text: str) -> None:
        """Drain the cancelled pipeline, send clearAudio, then route text through the
        normal endpoint-buffer path.  Called as a fire-and-forget task from _on_transcript
        after the state has already been flipped to LISTENING."""
        if self._speculative is not None:
            self._speculative.cancel()

        # Drain the cancelled pipeline task
        task = self._current_task
        if task and not task.done():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        try:
            await self._ws.send_json({
                "event":     "clearAudio",
                "streamSid": self._stream_sid,
            })
        except Exception:
            pass

        if not self._active:
            return

        logger.info("Barge-in: %r → endpoint buffer (waiting for is_final)", text)
        # Buffer the barge-in text but do NOT start an endpoint timer here.
        # Starting the timer on an interim fires the pipeline before the user
        # finishes speaking, causing a cascade of pipelines per interim burst.
        # The normal is_final path in _on_transcript will start the timer when
        # the user truly finishes.
        self._utterance_buffer.append(text)

    # ── Response pipeline ─────────────────────────────────────────────────

    async def _run_pipeline(self, user_text: str, *, prefilled_text: Optional[str] = None) -> None:
        async with self._pipeline_lock:
            try:
                if not self._active:
                    return

                self._pipelines_fired += 1
                self._state = State.PROCESSING
                self._append_user(user_text)

                metrics = TurnMetrics(call_id=self._call_sid, t_stt_final=self._stt_final_at)

                pipeline = StreamingPipeline(
                    websocket=self._ws,
                    stream_sid=self._stream_sid,
                    llm=self._llm,
                    http=self._http,
                    call_metrics=self._call_metrics,
                    on_audio_sent=self._on_pipeline_audio_sent,
                    sentence_filter=_make_sentence_filter(),
                )

                self._state = State.SPEAKING
                if self._stt_final_at:
                    logger.info(
                        "Pipeline started — %.0f ms after STT final",
                        (time.perf_counter() - self._stt_final_at) * 1000,
                    )

                full_text, dur = await pipeline.run(
                    self._history, metrics, prefilled_text=prefilled_text
                )

                # Wait for Plivo to finish playing (μ-law duration + buffer)
                elapsed   = time.perf_counter() - metrics.start
                remaining = max(0.0, dur - elapsed + _PLIVO_BUFFER)
                if remaining > 0:
                    await asyncio.sleep(remaining)

                if full_text:
                    self._append_assistant(full_text)
                    if self._recorder is not None:
                        self._recorder.add_agent_turn(full_text, duration_ms=dur * 1000)

                metrics.log()
                self._call_metrics.add(metrics)

            except asyncio.CancelledError:
                # Barge-in: do not append to history (response was cut off)
                raise
            except Exception as exc:
                if self._recorder is not None:
                    self._recorder.add_error(f"Pipeline crash: {exc!s}")
                # Crash isolation: log but keep the call alive
                logger.error(
                    "Pipeline crash call=%s: %s", self._call_sid, exc, exc_info=True
                )
            finally:
                self._post_speech_mute_until = time.monotonic() + settings.post_speech_mute_ms / 1000.0
                self._echo_guard.snapshot()
                self._state = State.LISTENING

    # ── Greeting / fixed messages ─────────────────────────────────────────

    async def _say(self, text: str) -> None:
        """Stream TTS directly to WebSocket (no LLM, no history)."""
        if not text.strip() or not self._active:
            return
        self._state = State.SPEAKING
        total_bytes = 0
        send_start  = time.perf_counter()
        try:
            async for chunk in tts_with_fallback(
                text, self._http, self._call_metrics
            ):
                if not self._active:
                    break
                payload = base64.b64encode(chunk).decode()
                if self._call_metrics.t_first_audio_to_plivo is None:
                    self._call_metrics.t_first_audio_to_plivo = time.perf_counter()
                await self._ws.send_json({
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate":  8000,
                        "payload":     payload,
                    },
                })
                total_bytes += len(chunk)
                self._echo_guard.record_agent_chunk(mulaw_to_linear16(chunk))

            # Sleep for the remaining playback time
            dur       = total_bytes / 8000.0
            if self._recorder is not None:
                self._recorder.add_agent_turn(text, duration_ms=dur * 1000)
            elapsed   = time.perf_counter() - send_start
            remaining = max(0.0, dur - elapsed + _PLIVO_BUFFER)
            if remaining > 0:
                await asyncio.sleep(remaining)
        except Exception as exc:
            logger.error("_say error: %s", exc)
        finally:
            self._post_speech_mute_until = time.monotonic() + settings.post_speech_mute_ms / 1000.0
            self._echo_guard.snapshot()
            self._state = State.LISTENING

    # ── Echo guard / VAD barge-in ─────────────────────────────────────────

    def _on_pipeline_audio_sent(self, chunk: bytes) -> None:
        """Called by pipeline._ws_sender for each outgoing μ-law chunk."""
        self._echo_guard.record_agent_chunk(mulaw_to_linear16(chunk))
        if self._recorder is not None:
            self._recorder.add_audio_chunk(chunk)

    async def _on_speech_started_vad(self) -> None:
        """Deepgram SpeechStarted VAD callback — used for early barge-in during SPEAKING."""
        if self._state != State.SPEAKING:
            return
        task = self._current_task
        if task is None or task.done():
            return
        # Suppress if echo guard thinks agent is still actively sending audio
        if self._echo_guard.is_agent_active():
            logger.debug("SpeechStarted VAD suppressed by EchoGuard (agent active)")
            return
        logger.info("SpeechStarted VAD barge-in triggered (call=%s)", self._call_sid)
        self._state = State.LISTENING
        self._utterance_buffer.clear()
        if self._speculative is not None:
            self._speculative.cancel()
        task.cancel()
        asyncio.create_task(
            self._handle_barge_in_cancel_vad(), name=f"barge-vad-{self._call_sid}"
        )

    async def _handle_barge_in_cancel_vad(self) -> None:
        """VAD-triggered barge-in: cancel pipeline, clear Plivo buffer, await transcript."""
        task = self._current_task
        if task and not task.done():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await self._ws.send_json({"event": "clearAudio", "streamSid": self._stream_sid})
        except Exception:
            pass

    # ── Backchannel acks ──────────────────────────────────────────────────

    def _maybe_backchannel(self) -> None:
        """Schedule a backchannel ack clip via BackchannelManager if conditions are met."""
        if self._bcm is None:
            return
        now = time.monotonic()
        if self._speech_started_at is None:
            self._speech_started_at = now
        self._last_backchannel_at = self._bcm.maybe_play(
            is_listening=(self._state == State.LISTENING),
            speech_started_at=self._speech_started_at,
            last_played_at=self._last_backchannel_at,
            now=now,
            min_speech_s=settings.backchannel_min_user_speech_s,
            min_interval_s=settings.backchannel_min_interval_s,
        )

    # ── Hard timeout ──────────────────────────────────────────────────────

    async def _hard_timeout_watchdog(self) -> None:
        await asyncio.sleep(settings.hard_timeout_s)
        if not self._active:
            return
        logger.warning(
            "Hard timeout (%.0fs) reached — ending call=%s",
            settings.hard_timeout_s, self._call_sid,
        )
        self._end_reason = "timeout"
        await self._say("Thank you for your time today. We'll be in touch. Goodbye!")
        await asyncio.sleep(0.3)
        await self._plivo.hangup(self._call_sid)
        await self.close()

    # ── Silence watchdog ──────────────────────────────────────────────────

    async def _silence_watchdog(self) -> None:
        secs = settings.hangup_silence_secs
        while self._active:
            await asyncio.sleep(secs)
            if not self._active:
                return
            elapsed = time.monotonic() - self._last_stt_at
            if elapsed >= secs:
                logger.info(
                    "Silence watchdog: %.0fs idle — hanging up call=%s",
                    elapsed, self._call_sid,
                )
                await self._say(_GOODBYE)
                await asyncio.sleep(0.3)
                await self._plivo.hangup(self._call_sid)
                self._end_reason = "timeout"
                await self.close()
                return

    # ── History ───────────────────────────────────────────────────────────

    def _append_user(self, text: str) -> None:
        self._history.append({"role": "user", "content": text})
        self._trim_history()

    def _append_assistant(self, text: str) -> None:
        self._history.append({"role": "assistant", "content": text})
        self._trim_history()

    def _trim_history(self) -> None:
        max_t = settings.max_conversation_turns
        if len(self._history) > max_t * 2 + 1:
            self._history = [self._history[0]] + self._history[-(max_t * 2):]
