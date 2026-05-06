"""
Per-day cost accounting and per-phone-number rate limiting (Phase 8).

Module-level state is intentional: these counters must survive across
individual CallSession instances within a single server process.
"""

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger(__name__)

_daily_cost: float = 0.0
_daily_reset_date: str = ""          # "YYYY-MM-DD" UTC; empty = never reset
_call_history: Dict[str, deque] = {} # phone → deque of call-start timestamps (epoch)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def reset_if_new_day() -> None:
    global _daily_cost, _daily_reset_date
    today = _today_utc()
    if _daily_reset_date != today:
        _daily_cost = 0.0
        _daily_reset_date = today
        logger.info("Daily cost reset for %s", today)


def get_daily_total() -> float:
    reset_if_new_day()
    return _daily_cost


def add_call_cost(cost_usd: float) -> None:
    global _daily_cost
    reset_if_new_day()
    _daily_cost += cost_usd
    logger.info("Daily cost updated: $%.4f (added $%.4f)", _daily_cost, cost_usd)


def is_rate_limited(phone: str, calls_per_hour: int) -> bool:
    """Return True if `phone` has already made `calls_per_hour` calls in the past hour."""
    now = time.time()
    cutoff = now - 3600.0
    q = _call_history.setdefault(phone, deque())
    while q and q[0] < cutoff:
        q.popleft()
    return len(q) >= calls_per_hour


def record_call(phone: str) -> None:
    """Record a new call attempt from `phone` (call record_call before building the XML)."""
    q = _call_history.setdefault(phone, deque())
    q.append(time.time())
