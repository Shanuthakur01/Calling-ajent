"""
Tests for EchoGuard.

1. Quiet agent -> is_echo() always False
2. Loud agent + low user RMS -> is_echo() True (echo detected)
3. Loud agent + high user RMS -> is_echo() False (real user speech)
4. snapshot() required: before snapshot is called, is_echo() returns False
   even after record_agent_chunk
"""

import struct
import math


def _make_pcm16(rms_target: float, n_samples: int = 160) -> bytes:
    """Generate a sine-wave buffer with approximately the given RMS (int16 scale)."""
    amplitude = rms_target * math.sqrt(2)
    amplitude = min(amplitude, 32767.0)
    samples = [int(amplitude * math.sin(2 * math.pi * i / n_samples)) for i in range(n_samples)]
    return struct.pack(f"<{n_samples}h", *samples)


def _make_silence(n_samples: int = 160) -> bytes:
    return b"\x00" * (n_samples * 2)


def test_quiet_agent_is_echo_always_false():
    from agent.echo_guard import EchoGuard, _SILENCE

    guard = EchoGuard()
    # Feed near-silence agent chunks
    silent_chunk = _make_pcm16(rms_target=10.0)
    for _ in range(20):
        guard.record_agent_chunk(silent_chunk)
    guard.snapshot()

    user_chunk = _make_pcm16(rms_target=10.0)
    # Even though user RMS matches agent, snapshot_rms < _SILENCE so not classified as echo
    assert guard.is_echo(user_chunk) is False


def test_loud_agent_low_user_rms_is_echo_true():
    from agent.echo_guard import EchoGuard, _SILENCE, _RATIO, _ALPHA

    guard = EchoGuard()
    # Drive agent EMA high by feeding loud audio repeatedly
    loud_chunk = _make_pcm16(rms_target=2000.0)
    for _ in range(50):
        guard.record_agent_chunk(loud_chunk)
    guard.snapshot()

    # snapshot_rms should now be well above _SILENCE
    assert guard._snapshot_rms >= _SILENCE

    # User audio with RMS much lower than RATIO * snapshot_rms
    quiet_user = _make_pcm16(rms_target=50.0)
    assert guard.is_echo(quiet_user) is True


def test_loud_agent_high_user_rms_is_echo_false():
    from agent.echo_guard import EchoGuard, _SILENCE, _RATIO

    guard = EchoGuard()
    loud_chunk = _make_pcm16(rms_target=2000.0)
    for _ in range(50):
        guard.record_agent_chunk(loud_chunk)
    guard.snapshot()

    assert guard._snapshot_rms >= _SILENCE

    # User audio with RMS clearly above RATIO * snapshot_rms
    loud_user = _make_pcm16(rms_target=guard._snapshot_rms * _RATIO * 2)
    assert guard.is_echo(loud_user) is False


def test_is_echo_false_before_snapshot():
    from agent.echo_guard import EchoGuard

    guard = EchoGuard()
    loud_chunk = _make_pcm16(rms_target=2000.0)
    # Record many loud chunks but do NOT call snapshot()
    for _ in range(50):
        guard.record_agent_chunk(loud_chunk)

    # snapshot_rms is still 0.0 (never snapshotted), so is_echo must be False
    quiet_user = _make_pcm16(rms_target=10.0)
    assert guard.is_echo(quiet_user) is False
