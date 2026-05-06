"""
Regression tests: Cost column removed from dashboard UI.

1. test_dashboard_html_does_not_contain_cost_column — DASHBOARD_HTML has no Cost header/cell/JS
2. test_api_calls_still_includes_cost_inr           — /api/calls JSON still exposes cost_inr
"""

import json
import pytest
from types import SimpleNamespace
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 1. Dashboard HTML must not render any cost UI
# ---------------------------------------------------------------------------

def test_dashboard_html_does_not_contain_cost_column():
    """Regression: dashboard must not render a Cost column in the call history table."""
    from dashboard import DASHBOARD_HTML

    assert "<th>Cost</th>" not in DASHBOARD_HTML
    assert "<th>COST</th>" not in DASHBOARD_HTML
    assert "fmtCost" not in DASHBOARD_HTML
    assert "cost-cell" not in DASHBOARD_HTML


# ---------------------------------------------------------------------------
# 2. Backend API still returns cost_inr (field kept, only rendering removed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_calls_still_includes_cost_inr(tmp_path):
    """Backend cost data must still be available even though the UI hides it."""
    import main as _main
    import state

    call_id = "no-cost-col-regression-001"
    fake_recording = {
        "call_id":    call_id,
        "started_at": "2026-05-06T09:00:00+00:00",
        "ended_at":   "2026-05-06T09:02:00+00:00",
        "duration_s": 120,
        "end_reason": "completed",
        "transcript": [],
        "metrics": {"cost_breakdown": {"total_usd": 0.10}},
        "errors": [],
    }
    (tmp_path / f"{call_id}.json").write_text(
        json.dumps(fake_recording), encoding="utf-8"
    )

    fake_settings = SimpleNamespace(recording_dir=str(tmp_path), usd_to_inr=83.5)

    old_calls = dict(state._calls)
    state._calls[call_id] = {
        "id":          call_id,
        "call_id":     call_id,
        "phone":       "+910000000000",
        "name":        "Test",
        "status":      "completed",
        "started_at":  1000.0,
        "answered_at": 1001.0,
        "ended_at":    1120.0,
    }

    try:
        with patch("main.settings", fake_settings):
            resp = await _main.api_calls()
    finally:
        state._calls.clear()
        state._calls.update(old_calls)

    data = json.loads(resp.body)
    assert "calls" in data
    calls = [c for c in data["calls"] if c["call_id"] == call_id]
    assert calls, "Expected the injected call to appear in /api/calls"
    call = calls[0]
    assert "cost_inr" in call, "cost_inr must still be present in /api/calls response"
    assert call["cost_inr"] == pytest.approx(8.35), (
        f"Expected 8.35 INR (0.10 USD * 83.5), got {call['cost_inr']}"
    )
