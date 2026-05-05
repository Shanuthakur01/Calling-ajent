"""
Global registry of live CallSession objects.

Uses WeakValueDictionary so sessions are automatically deregistered
when garbage-collected (no manual cleanup required on the happy path).
Graceful-shutdown code iterates this to drain active calls.
"""

from weakref import WeakValueDictionary
from typing import List

_registry: WeakValueDictionary = WeakValueDictionary()


def register(session) -> None:
    _registry[session._call_sid] = session


def unregister(call_sid: str) -> None:
    _registry.pop(call_sid, None)


def all_sessions() -> List:
    return list(_registry.values())
