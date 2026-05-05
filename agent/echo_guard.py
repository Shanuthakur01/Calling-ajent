"""
EchoGuard -- suppress agent-echo barge-in.

Tracks recent outgoing agent audio RMS.  During the post-speech mute window,
incoming audio with RMS < RATIO * agent_residual is classified as echo and
suppressed before reaching STT.

Usage:
  guard.record_agent_chunk(linear16_bytes)  -- called for every sent audio chunk
  guard.snapshot()                          -- called when agent stops speaking
  guard.is_echo(linear16_bytes) -> bool     -- called in handle_audio()
  guard.is_agent_active() -> bool           -- True when agent RMS EMA is high
                                              (used to gate SpeechStarted barge-in)
"""

import math
import struct
import logging

logger = logging.getLogger(__name__)

_RATIO   = 1.5   # user RMS must be this multiple of agent residual to pass
_ALPHA   = 0.20  # EMA smoothing coefficient for agent RMS
_SILENCE = 50    # RMS below this is treated as silence (int16 scale, 0-32767)


def _rms16(data: bytes) -> float:
    """RMS of signed 16-bit little-endian PCM."""
    n = len(data) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack_from(f"<{n}h", data, 0)
    return math.sqrt(sum(s * s for s in samples) / n)


class EchoGuard:
    """Single-call echo guard. Not thread-safe; assumes single asyncio event loop."""

    def __init__(self) -> None:
        self._agent_rms_ema: float = 0.0    # running EMA of outgoing audio RMS
        self._snapshot_rms: float = 0.0     # snapshot at end of agent speech

    def record_agent_chunk(self, linear16: bytes) -> None:
        """Update agent RMS EMA with an outgoing audio chunk (linear16 PCM)."""
        rms = _rms16(linear16)
        self._agent_rms_ema = _ALPHA * rms + (1.0 - _ALPHA) * self._agent_rms_ema

    def snapshot(self) -> None:
        """
        Called when agent speech ends.  Freezes the current RMS for the
        post-speech window, then decays the EMA so it doesn't persist into
        the next turn.
        """
        self._snapshot_rms  = self._agent_rms_ema
        self._agent_rms_ema *= 0.5   # gentle decay

    def is_echo(self, linear16: bytes) -> bool:
        """
        Return True if incoming audio is likely an echo of the agent.
        Only meaningful during the post-speech mute window.
        """
        if self._snapshot_rms < _SILENCE:
            return False   # agent was nearly silent -- nothing to echo
        return _rms16(linear16) < _RATIO * self._snapshot_rms

    def is_agent_active(self) -> bool:
        """
        True when the agent's running RMS is high enough that a SpeechStarted
        VAD event is more likely echo than real user speech.
        """
        return self._agent_rms_ema >= _SILENCE * 2
