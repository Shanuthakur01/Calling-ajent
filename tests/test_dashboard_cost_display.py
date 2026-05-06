"""
Tests for the per-call INR cost column in the /api/calls response.

1. test_call_history_includes_inr_cost            — recording with cost_breakdown → cost_inr correct
2. test_call_history_handles_missing_cost         — older recording without cost_breakdown → cost_inr = 0.0
3. test_call_history_links_to_recording_by_call_id — regression: activate() must set call_id so
                                                       recording lookup succeeds
"""

import json
import pytest
from unittest.mock import patch
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_settings(tmp_path, usd_to_inr=83.5):
    return SimpleNamespace(recording_dir=str(tmp_path), usd_to_inr=usd_to_inr)


# ---------------------------------------------------------------------------
# Test 1 — recording with cost_breakdown produces correct cost_inr
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_history_includes_inr_cost(tmp_path):
    """
    /api/calls must include cost_inr for a call whose recording JSON contains
    metrics.cost_breakdown.total_usd.  0.20 USD * 83.5 = 16.70 INR.
    """
    import main as _main
    import state

    call_id = "test-cost-inr-001"

    fake_recording = {
        "call_id":    call_id,
        "started_at": "2026-05-05T10:00:00+00:00",
        "ended_at":   "2026-05-05T10:02:00+00:00",
        "duration_s": 120,
        "end_reason": "user_hangup",
        "transcript": [],
        "metrics": {
            "turns": 3,
            "cost_breakdown": {"total_usd": 0.20},
        },
        "errors": [],
    }
    (tmp_path / f"{call_id}.json").write_text(
        json.dumps(fake_recording), encoding="utf-8"
    )

    # Register the call in the in-memory state so get_all() returns it
    old_calls = dict(state._calls)
    state._calls[call_id] = {
        "id":          call_id,
        "call_id":     call_id,
        "phone":       "+911234567890",
        "name":        "Test Candidate",
        "status":      "completed",
        "started_at":  1000.0,
        "answered_at": 1001.0,
        "ended_at":    1120.0,
    }

    fake = _fake_settings(tmp_path, usd_to_inr=83.5)
    try:
        with patch("main.settings", fake):
            resp = await _main.api_calls()
        data = json.loads(resp.body)
        calls = data["calls"]
        call = next((c for c in calls if c["call_id"] == call_id), None)
        assert call is not None, "Call not found in /api/calls response"
        assert "cost_inr" in call, "cost_inr field missing from call entry"
        assert call["cost_inr"] == 16.70, (
            f"Expected 16.70 INR (0.20 USD * 83.5), got {call['cost_inr']}"
        )
    finally:
        state._calls.clear()
        state._calls.update(old_calls)


# ---------------------------------------------------------------------------
# Test 2 — recording without cost_breakdown defaults cost_inr to 0.0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_history_handles_missing_cost(tmp_path):
    """
    /api/calls must not crash when a recording has no cost_breakdown.
    cost_inr must default to 0.0.
    """
    import main as _main
    import state

    call_id = "test-cost-inr-old"

    fake_recording_old = {
        "call_id":    call_id,
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at":   "2026-05-04T10:02:00+00:00",
        "duration_s": 120,
        "end_reason": "user_hangup",
        "transcript": [],
        "metrics":    {"turns": 3},   # no cost_breakdown
        "errors":     [],
    }
    (tmp_path / f"{call_id}.json").write_text(
        json.dumps(fake_recording_old), encoding="utf-8"
    )

    old_calls = dict(state._calls)
    state._calls[call_id] = {
        "id":          call_id,
        "call_id":     call_id,
        "phone":       "+911234567890",
        "name":        "Old Candidate",
        "status":      "completed",
        "started_at":  900.0,
        "answered_at": 901.0,
        "ended_at":    1020.0,
    }

    fake = _fake_settings(tmp_path)
    try:
        with patch("main.settings", fake):
            resp = await _main.api_calls()
        data = json.loads(resp.body)
        calls = data["calls"]
        call = next((c for c in calls if c["call_id"] == call_id), None)
        assert call is not None, "Call not found in /api/calls response"
        assert "cost_inr" in call, "cost_inr field missing from call entry"
        assert call["cost_inr"] == 0.0, (
            f"Expected 0.0 for missing cost_breakdown, got {call['cost_inr']}"
        )
    finally:
        state._calls.clear()
        state._calls.update(old_calls)


# ---------------------------------------------------------------------------
# Test 3 — regression: activate() must populate call_id so cost lookup works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_history_links_to_recording_by_call_id(tmp_path):
    """
    Regression: state.activate() was not setting entry["call_id"], so the
    /api/calls recording-file lookup silently returned cost_inr=0.0 even when
    a valid recording existed.

    Simulates the full outbound call path:
      register(request_uuid) → call_id=None in entry
      activate(call_id)      → must set call_id=call_id in the same entry
    Then verifies /api/calls returns the correct cost_inr from the recording.
    """
    import main as _main
    import state

    # Plivo reuses request_uuid as the call's UUID for outbound calls
    call_id = "plivo-uuid-regression-001"

    # Step 1: register (simulates /make-call)
    old_calls = dict(state._calls)
    state.register(call_id, "+919301545353", "Test Candidate")

    # Confirm call_id is None after register (the pre-fix state)
    assert state._calls[call_id]["call_id"] is None, \
        "Precondition: call_id must be None after register()"

    # Step 2: activate (simulates WebSocket start event from Plivo)
    state.activate(call_id)

    # After the fix, call_id must now be populated
    assert state._calls[call_id]["call_id"] == call_id, \
        "activate() must set entry['call_id'] so recording lookup can succeed"

    # Step 3: write a recording file (simulates what agent/recorder.py does)
    fake_recording = {
        "call_id":    call_id,
        "started_at": "2026-05-05T10:00:00+00:00",
        "ended_at":   "2026-05-05T10:02:00+00:00",
        "duration_s": 120,
        "end_reason": "agent_completed",
        "transcript": [],
        "metrics": {
            "turns": 2,
            "cost_breakdown": {"total_usd": 0.20},
        },
        "errors": [],
    }
    (tmp_path / f"{call_id}.json").write_text(
        json.dumps(fake_recording), encoding="utf-8"
    )
    state.complete(call_id)

    fake = _fake_settings(tmp_path, usd_to_inr=83.5)
    try:
        with patch("main.settings", fake):
            resp = await _main.api_calls()
        data = json.loads(resp.body)
        calls = data["calls"]
        call = next((c for c in calls if c.get("call_id") == call_id), None)
        assert call is not None, "Call not found in /api/calls response"
        assert call["call_id"] is not None, "call_id must not be null after fix"
        assert call["cost_inr"] == 16.70, (
            f"Expected ₹16.70 (0.20 USD × 83.5), got ₹{call['cost_inr']}"
        )
    finally:
        state._calls.clear()
        state._calls.update(old_calls)
