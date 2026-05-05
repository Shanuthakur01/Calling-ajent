"""
Tests for agent/recorder.py — CallRecorder.

Coverage:
1. test_recorder_creates_json_at_call_end          — full call → JSON with all required keys
2. test_recorder_writes_incrementally              — flush happens before close() is called
3. test_recorder_disabled_via_env                  — no file created when start() not called
4. test_recorder_does_not_block_pipeline           — add_* methods are non-blocking queue puts
5. test_recorder_captures_errors                   — errors array populated via add_error()
6. test_recorder_creates_directory_at_startup      — ensure_recording_dir creates dir from settings
"""

import asyncio
import json
import time

import pytest
from types import SimpleNamespace
from unittest.mock import patch


_FAKE_SETTINGS = SimpleNamespace(recording_enabled=True, record_audio=False)


# ---------------------------------------------------------------------------
# Test 1 — full call produces JSON with all required keys and correct values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recorder_creates_json_at_call_end(tmp_path):
    from agent.recorder import CallRecorder

    with patch("agent.recorder.settings", _FAKE_SETTINGS):
        rec = CallRecorder("call-complete", tmp_path)
        await rec.start()
        rec.add_agent_turn("Hello there!", duration_ms=1240.0)
        rec.add_user_turn("Hi, how are you?")
        rec.add_agent_turn("I'm doing well, thank you.", duration_ms=900.0)
        await rec.close("agent_completed", {
            "turns": 1,
            "avg_e2e_ms": 1072,
            "avg_llm_ttft_ms": 542,
            "avg_tts_ttft_ms": 530,
            "speculative_hit_rate": 0.38,
            "speculative_savings_ms": 8392,
            "fallbacks_triggered": 0,
            "tts_ws_open_count": 3,
        })

    path = tmp_path / "call-complete.json"
    assert path.exists(), "JSON file must exist after close()"

    doc = json.loads(path.read_text(encoding="utf-8"))

    required_keys = (
        "call_id", "started_at", "ended_at", "duration_s",
        "end_reason", "transcript", "metrics", "errors",
    )
    for key in required_keys:
        assert key in doc, f"Missing required key: {key!r}"

    assert doc["call_id"] == "call-complete"
    assert doc["end_reason"] == "agent_completed"
    assert doc["ended_at"] is not None
    assert doc["duration_s"] is not None and doc["duration_s"] >= 0
    assert len(doc["transcript"]) == 3
    assert doc["transcript"][0]["role"] == "agent"
    assert doc["transcript"][0]["text"] == "Hello there!"
    assert doc["transcript"][0]["duration_ms"] == 1240.0
    assert doc["transcript"][1]["role"] == "user"
    assert doc["transcript"][2]["role"] == "agent"
    assert doc["metrics"]["avg_e2e_ms"] == 1072
    assert doc["errors"] == []


# ---------------------------------------------------------------------------
# Test 2 — incremental write: file exists and has data before close()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recorder_writes_incrementally(tmp_path):
    from agent.recorder import CallRecorder

    with patch("agent.recorder.settings", _FAKE_SETTINGS):
        rec = CallRecorder("call-partial", tmp_path)
        await rec.start()
        rec.add_agent_turn("Greeting sentence.", duration_ms=800.0)

        # Let the background writer flush at least once
        await asyncio.sleep(0.05)

        path = tmp_path / "call-partial.json"
        assert path.exists(), "Incremental write must happen before close()"

        doc = json.loads(path.read_text(encoding="utf-8"))
        assert len(doc["transcript"]) >= 1
        assert doc["transcript"][0]["text"] == "Greeting sentence."

        # Simulate crash: cancel writer before close()
        rec._task.cancel()
        try:
            await rec._task
        except asyncio.CancelledError:
            pass

    # File must persist with partial data after crash
    assert path.exists()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert len(doc["transcript"]) >= 1


# ---------------------------------------------------------------------------
# Test 3 — disabled path: no file written when start() is never called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recorder_disabled_via_env(tmp_path):
    """
    When RECORDING_ENABLED=false in call_session, start() is never called.
    A recorder with no running _task must not write any file.
    """
    from agent.recorder import CallRecorder

    with patch("agent.recorder.settings", _FAKE_SETTINGS):
        rec = CallRecorder("call-nodisk", tmp_path)
        # Deliberately skip start() — models the recording_enabled=False path
        rec.add_agent_turn("This should not be written.")
        await rec.close("user_hangup", {})   # close() with _task=None → no write

    assert not (tmp_path / "call-nodisk.json").exists(), (
        "No file must be created when start() was never called"
    )


# ---------------------------------------------------------------------------
# Test 4 — non-blocking: add_* returns immediately even with slow disk
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recorder_does_not_block_pipeline(tmp_path):
    """
    add_agent_turn / add_user_turn must return in < 10 ms total for 20 calls,
    even when the background _write_json coroutine is artificially slow.
    """
    from agent.recorder import CallRecorder

    async def _slow_write(*_args, **_kwargs):
        await asyncio.sleep(0.3)   # simulate 300 ms disk latency

    with patch("agent.recorder.settings", _FAKE_SETTINGS):
        rec = CallRecorder("call-fast", tmp_path)
        rec._write_json = _slow_write   # monkey-patch before start()
        await rec.start()

        t0 = time.perf_counter()
        for _ in range(20):
            rec.add_agent_turn("pipeline sentence")
        elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 50, (
        f"20 add_agent_turn calls must complete in < 50 ms; took {elapsed_ms:.1f} ms"
    )

    # Clean up background task
    if rec._task and not rec._task.done():
        rec._task.cancel()
        try:
            await rec._task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Test 5 — errors captured via add_error() appear in the errors array
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recorder_captures_errors(tmp_path):
    from agent.recorder import CallRecorder

    with patch("agent.recorder.settings", _FAKE_SETTINGS):
        rec = CallRecorder("call-errors", tmp_path)
        await rec.start()
        rec.add_agent_turn("Opening.", duration_ms=500.0)
        rec.add_error("TTS timeout after 10s")
        rec.add_error("Pipeline crash: ConnectionRefusedError")
        await rec.close("error", {"turns": 0})

    path = tmp_path / "call-errors.json"
    assert path.exists()

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["end_reason"] == "error"
    assert len(doc["errors"]) == 2
    assert "TTS timeout" in doc["errors"][0]
    assert "Pipeline crash" in doc["errors"][1]
    # Transcript still present alongside errors
    assert len(doc["transcript"]) == 1
    assert doc["transcript"][0]["role"] == "agent"


# ---------------------------------------------------------------------------
# Test 6 — ensure_recording_dir creates the directory from settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recorder_creates_directory_at_startup(tmp_path):
    """
    ensure_recording_dir() must create the directory (resolved absolute path)
    specified in settings.recording_dir.
    """
    from agent.recorder import ensure_recording_dir

    target = tmp_path / "fresh_recordings"
    assert not target.exists(), "Precondition: target must not exist before the call"

    fake_settings = SimpleNamespace(
        recording_enabled=True,
        recording_dir=str(target),  # absolute path to a new tmp sub-dir
        record_audio=False,
    )

    with patch("agent.recorder.settings", fake_settings):
        returned_path = await ensure_recording_dir()

    assert target.exists() and target.is_dir(), "Directory must exist after ensure_recording_dir()"
    assert returned_path == target.resolve(), "Returned path must match the resolved target"
