"""
Shared in-memory call store — imported by main.py and plivo_handler.py.
"""

import time
from typing import Any, Dict, List, Optional

_calls: Dict[str, Dict[str, Any]] = {}   # keyed by call_id (Plivo CallUUID)
_ref_map: Dict[str, str] = {}            # request_uuid → call_id


def register(request_uuid: str, phone: str, name: str) -> None:
    _calls[request_uuid] = {
        "id":           request_uuid,
        "call_id":      None,
        "phone":        phone,
        "name":         name or "Student",
        "status":       "calling",
        "started_at":   time.time(),
        "answered_at":  None,
        "ended_at":     None,
    }


def answer(request_uuid: str, call_uuid: str) -> None:
    """Called when Plivo POSTs to /incoming-call — links request → call UUID."""
    if request_uuid in _calls:
        entry = _calls.pop(request_uuid)
        entry["call_id"] = call_uuid
        entry["status"]  = "ringing"
        _calls[call_uuid] = entry
    _ref_map[request_uuid] = call_uuid


def activate(call_id: str) -> None:
    """Called when WebSocket START event fires."""
    if call_id in _calls:
        _calls[call_id]["status"]      = "active"
        _calls[call_id]["answered_at"] = time.time()
    else:
        # Inbound call (no prior register) — create a minimal record
        _calls[call_id] = {
            "id":          call_id,
            "call_id":     call_id,
            "phone":       "Inbound",
            "name":        "Student",
            "status":      "active",
            "started_at":  time.time(),
            "answered_at": time.time(),
            "ended_at":    None,
        }


def complete(call_id: str) -> None:
    if call_id in _calls:
        _calls[call_id]["status"]   = "completed"
        _calls[call_id]["ended_at"] = time.time()


def get_all(limit: int = 100) -> List[Dict]:
    return sorted(_calls.values(), key=lambda c: c["started_at"], reverse=True)[:limit]


def get_stats() -> Dict[str, int]:
    vals = list(_calls.values())
    return {
        "total":     len(vals),
        "calling":   sum(1 for c in vals if c["status"] == "calling"),
        "ringing":   sum(1 for c in vals if c["status"] == "ringing"),
        "active":    sum(1 for c in vals if c["status"] == "active"),
        "completed": sum(1 for c in vals if c["status"] == "completed"),
        "failed":    sum(1 for c in vals if c["status"] == "failed"),
    }
