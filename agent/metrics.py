"""Per-turn and per-call latency metrics."""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TurnMetrics:
    call_id: str
    start: float = field(default_factory=time.perf_counter)

    # ── Absolute perf_counter timestamps for each pipeline stage boundary ──
    # Set by the stage that owns the transition; None = stage not reached yet.
    t_stt_final: Optional[float] = None        # speech_final received from Deepgram
    t_llm_request: Optional[float] = None      # LLM HTTP request sent
    t_first_token: Optional[float] = None      # first non-empty LLM token received
    t_first_sentence: Optional[float] = None   # first complete sentence put into TTS queue
    t_tts_request: Optional[float] = None      # TTS HTTP request sent (first sentence)
    t_first_tts_byte: Optional[float] = None   # first μ-law byte back from TTS
    t_first_ws_frame: Optional[float] = None   # first playAudio frame sent to Plivo

    # ── Legacy fields kept for CallMetrics.log_summary() and existing tests ──
    # Measured from metrics.start (endpoint fired), not from the previous stage.
    llm_ttft_ms: float = 0.0        # start → first sentence in TTS queue
    tts_ttft_ms: float = 0.0        # start → first TTS byte
    e2e_first_audio_ms: float = 0.0  # start → first WS frame sent to Plivo

    def log(self) -> None:
        def _gap(a: Optional[float], b: Optional[float]) -> str:
            return "%.0fms" % ((a - b) * 1000) if (a is not None and b is not None) else "n/a"

        logger.info(
            "TURN  call=%s  "
            "endpoint_wait=%s  queue_to_llm=%s  llm_ttft=%s  "
            "sentence_buffer=%s  tts_ttft=%s  audio_pipe=%s  e2e=%.0fms",
            self.call_id,
            _gap(self.start, self.t_stt_final),                      # user-speech-end → endpoint fired
            _gap(self.t_llm_request, self.start),                    # endpoint fired → LLM request sent
            _gap(self.t_first_token, self.t_llm_request),            # LLM request → first token
            _gap(self.t_first_sentence, self.t_first_token),         # first token → first sentence to TTS
            _gap(self.t_first_tts_byte, self.t_tts_request),         # TTS request → first byte
            _gap(self.t_first_ws_frame, self.t_first_tts_byte),      # first TTS byte → first Plivo frame
            self.e2e_first_audio_ms,
        )


@dataclass
class CallMetrics:
    call_id: str
    turns: List[TurnMetrics] = field(default_factory=list)

    # Call-level stage timestamps (perf_counter, set once per call)
    t_incoming_call: Optional[float] = None       # /incoming-call webhook fired
    t_ws_connected: Optional[float] = None        # /media-stream WS accepted
    t_first_stt_partial: Optional[float] = None   # first interim STT transcript
    t_user_speech_end: Optional[float] = None     # first is_final STT transcript
    t_first_llm_token: Optional[float] = None     # first LLM sentence in any turn
    t_first_tts_byte: Optional[float] = None      # first byte from ElevenLabs
    t_first_audio_to_plivo: Optional[float] = None  # first playAudio WS frame

    # Provider usage counters (incremented by LLMClient.stream_sentences)
    primary_turns: int = 0        # turns where primary provider succeeded
    fallback_turns: int = 0       # turns where fallback provider succeeded
    fallbacks_triggered: int = 0  # turns where primary failed and fallback was used

    # TTS WebSocket health (snapshot at call end)
    tts_ws_reconnect_count: int = 0

    # Phase 3 — Speculative LLM stats
    speculative_hits: int = 0
    speculative_misses: int = 0
    speculative_savings_ms: float = 0.0

    @property
    def speculative_hit_rate(self) -> float:
        total = self.speculative_hits + self.speculative_misses
        return self.speculative_hits / total if total > 0 else 0.0

    def add(self, m: TurnMetrics) -> None:
        self.turns.append(m)

    def log_summary(self) -> None:
        def _delta(a: Optional[float], b: Optional[float]) -> str:
            return "%.0fms" % ((a - b) * 1000) if (a is not None and b is not None) else "n/a"

        n = len(self.turns)

        # Per-turn averages are always non-negative; the call-level timestamps
        # t_first_tts_byte / t_first_audio_to_plivo are set during the greeting
        # (before the user speaks), so cross-turn deltas using t_user_speech_end
        # would produce negative values.  Use per-turn averages instead.
        if n:
            avg_llm = sum(t.llm_ttft_ms for t in self.turns) / n
            avg_tts = sum(t.tts_ttft_ms for t in self.turns) / n
            avg_e2e = sum(t.e2e_first_audio_ms for t in self.turns) / n
            avg_part = (
                f"  avg_llm_ttft={avg_llm:.0f}ms"
                f"  avg_tts_ttft={avg_tts:.0f}ms"
                f"  avg_e2e={avg_e2e:.0f}ms"
                f"  [{n} turn(s)]"
            )
        else:
            avg_llm = avg_tts = avg_e2e = 0.0
            avg_part = "  avg_llm_ttft=n/a  avg_tts_ttft=n/a  avg_e2e=n/a  [0 turns]"

        logger.info(
            "CALL TIMELINE  call=%s"
            "  incoming→ws=%s"
            "  ws→stt_partial=%s"
            "  ws→speech_end=%s"
            "%s",
            self.call_id,
            _delta(self.t_ws_connected, self.t_incoming_call),
            _delta(self.t_first_stt_partial, self.t_ws_connected),
            _delta(self.t_user_speech_end, self.t_ws_connected),
            avg_part,
        )

        if not n:
            return
        logger.info(
            "CALL END  call=%s  turns=%d  avg_e2e=%.0fms  avg_llm=%.0fms  avg_tts=%.0fms"
            "  primary_used=%d  fallback_used=%d  fallbacks_triggered=%d"
            "  tts_ws_reconnects=%d",
            self.call_id, n, avg_e2e, avg_llm, avg_tts,
            self.primary_turns, self.fallback_turns, self.fallbacks_triggered,
            self.tts_ws_reconnect_count,
        )

        if self.speculative_hits + self.speculative_misses > 0:
            logger.info(
                "SPECULATIVE  call=%s  hits=%d  misses=%d  hit_rate=%.0f%%  savings=%.0fms",
                self.call_id,
                self.speculative_hits, self.speculative_misses,
                self.speculative_hit_rate * 100,
                self.speculative_savings_ms,
            )
