"""
Tests for Phase 8 — daily cost cap.

1. test_cap_blocks_calls_when_exceeded  — /incoming-call returns hangup XML when cap hit
2. test_cap_resets_at_utc_midnight      — reset_if_new_day() zeroes the counter on date change
3. test_cost_summary_shape              — GET /api/cost-summary returns required keys
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import Request


# ---------------------------------------------------------------------------
# Test 1 — cap blocks incoming call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cap_blocks_calls_when_exceeded():
    """
    When daily cost >= daily_cost_limit_usd, /incoming-call (POST) must return
    a Hangup XML response instead of the Stream XML.
    """
    import agent.cost_tracker as ct
    import main as _main
    from config import settings

    # Force daily cost over the limit; set date to today so reset_if_new_day is a no-op
    original_cost = ct._daily_cost
    original_date = ct._daily_reset_date
    ct._daily_cost = 9999.0
    ct._daily_reset_date = ct._today_utc()

    try:
        req = MagicMock(spec=Request)
        req.form = AsyncMock(return_value={"From": "+15551234567"})

        resp = await _main.incoming_call_post(req)

        assert resp.status_code == 200
        assert b"<Hangup/>" in resp.body, "Must return Hangup XML when cap exceeded"
        assert b"Stream" not in resp.body
    finally:
        ct._daily_cost = original_cost
        ct._daily_reset_date = original_date


# ---------------------------------------------------------------------------
# Test 2 — daily counter resets when UTC date changes
# ---------------------------------------------------------------------------

def test_cap_resets_at_utc_midnight():
    """reset_if_new_day() must zero _daily_cost when the UTC date has changed."""
    import agent.cost_tracker as ct

    original_cost = ct._daily_cost
    original_date = ct._daily_reset_date

    ct._daily_cost = 7.50
    ct._daily_reset_date = "2020-01-01"   # stale date — yesterday

    try:
        ct.reset_if_new_day()
        assert ct._daily_cost == 0.0, "Daily cost must be zeroed after date change"
    finally:
        ct._daily_cost = original_cost
        ct._daily_reset_date = original_date


# ---------------------------------------------------------------------------
# Test 3 — /api/cost-summary returns required shape when debug_mode=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_summary_shape():
    """
    GET /api/cost-summary must return a JSON body with the required keys
    when debug_mode=True, or 403 when debug_mode=False.
    """
    import main as _main
    import agent.cost_tracker as ct
    from config import settings

    original_cost = ct._daily_cost
    original_date = ct._daily_reset_date
    ct._daily_cost = 1.2345
    ct._daily_reset_date = ct._today_utc()   # prevent auto-reset

    _fake = MagicMock()
    _fake.debug_mode = True
    _fake.daily_cost_limit_usd = 10.0
    _fake.rate_limit_calls_per_hour = 5

    try:
        with patch("main.settings", _fake):
            resp = await _main.api_cost_summary()

        assert resp.status_code == 200
        body = json.loads(resp.body)
        for key in ("date", "daily_total_usd", "daily_limit_usd",
                    "headroom_usd", "rate_limit_calls_per_hour"):
            assert key in body, f"Missing key: {key!r}"
        assert body["daily_limit_usd"] == 10.0
        assert body["rate_limit_calls_per_hour"] == 5
        assert body["headroom_usd"] >= 0.0

        # Verify 403 when debug_mode=False
        _fake.debug_mode = False
        with patch("main.settings", _fake):
            resp403 = await _main.api_cost_summary()
        assert resp403.status_code == 403
    finally:
        ct._daily_cost = original_cost
        ct._daily_reset_date = original_date
