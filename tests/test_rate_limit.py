"""
Tests for Phase 8 — per-phone-number rate limiting.

1. test_blocks_sixth_call              — 5 calls recorded → 6th is blocked
2. test_resets_after_one_hour          — entries older than 1 h are expired
3. test_rate_limits_are_independent    — two phone numbers tracked separately
"""

import time
from collections import deque

import pytest


# ---------------------------------------------------------------------------
# Test 1 — 6th call is rate-limited
# ---------------------------------------------------------------------------

def test_blocks_sixth_call():
    """After 5 recorded calls, is_rate_limited() must return True for that number."""
    import agent.cost_tracker as ct

    phone = "+15550001001"
    ct._call_history.pop(phone, None)   # clean slate

    for _ in range(5):
        ct.record_call(phone)

    assert ct.is_rate_limited(phone, 5) is True, "6th call must be blocked"
    # Sanity: a higher limit must still allow
    assert ct.is_rate_limited(phone, 6) is False

    # Cleanup
    ct._call_history.pop(phone, None)


# ---------------------------------------------------------------------------
# Test 2 — entries expire after 1 hour
# ---------------------------------------------------------------------------

def test_resets_after_one_hour():
    """Calls recorded more than 3600 s ago must be dropped from the sliding window."""
    import agent.cost_tracker as ct

    phone = "+15550001002"
    old_ts = time.time() - 3601.0
    ct._call_history[phone] = deque([old_ts] * 5)

    assert ct.is_rate_limited(phone, 5) is False, "Expired entries must not count"

    # Cleanup
    ct._call_history.pop(phone, None)


# ---------------------------------------------------------------------------
# Test 3 — limits are independent per number
# ---------------------------------------------------------------------------

def test_rate_limits_are_independent():
    """Rate-limiting one number must not affect a different number."""
    import agent.cost_tracker as ct

    phone_a = "+15550001003"
    phone_b = "+15550001004"
    ct._call_history.pop(phone_a, None)
    ct._call_history.pop(phone_b, None)

    for _ in range(5):
        ct.record_call(phone_a)

    assert ct.is_rate_limited(phone_a, 5) is True,  "phone_a must be blocked"
    assert ct.is_rate_limited(phone_b, 5) is False, "phone_b must be unaffected"

    # Cleanup
    ct._call_history.pop(phone_a, None)
    ct._call_history.pop(phone_b, None)
