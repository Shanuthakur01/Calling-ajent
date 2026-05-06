"""
Tests for MongoWriter.

1. test_disabled_when_no_uri        — mongodb_uri=None → _enabled=False, write_call returns False
2. test_disabled_by_config          — mongodb_enabled=False → _enabled=False
3. test_build_document_converts_iso — ISO strings become datetime objects, fields correct
4. test_build_document_missing_fields — minimal dict, None defaults handled properly
5. test_write_call_swallows_exceptions — insert_one raises, returns False, no exception propagated
6. test_write_call_succeeds         — insert_one mocked, returns True, called with correct shape
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.mongo_writer as _mw
from agent.mongo_writer import MongoWriter


def _fake_settings(**kwargs):
    defaults = dict(
        mongodb_uri=None,
        mongodb_enabled=True,
        mongodb_database="testdb",
        mongodb_collection="test_col",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.fixture(autouse=True)
def reset_singleton():
    MongoWriter._instance = None
    yield
    MongoWriter._instance = None


# ---------------------------------------------------------------------------
# 1. Disabled when no URI
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_when_no_uri():
    with patch("agent.mongo_writer.settings", _fake_settings(mongodb_uri=None)):
        writer = MongoWriter()
        await writer.connect()

    assert writer._enabled is False
    result = await writer.write_call(recording={"call_id": "x"})
    assert result is False


# ---------------------------------------------------------------------------
# 2. Disabled by config flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_by_config():
    with patch("agent.mongo_writer.settings",
               _fake_settings(mongodb_uri="mongodb://localhost", mongodb_enabled=False)):
        writer = MongoWriter()
        await writer.connect()

    assert writer._enabled is False
    result = await writer.write_call(recording={"call_id": "x"})
    assert result is False


# ---------------------------------------------------------------------------
# 3. _build_document converts ISO strings to datetime
# ---------------------------------------------------------------------------

def test_build_document_converts_iso():
    recording = {
        "call_id":    "abc-123",
        "started_at": "2024-01-15T10:30:00+00:00",
        "ended_at":   "2024-01-15T10:35:00+00:00",
        "duration_s": 300.0,
        "end_reason": "user_hangup",
        "transcript": [{"role": "agent", "text": "Hello"}],
        "metrics":    {"turns": 5},
        "errors":     [],
    }

    doc = MongoWriter._build_document(recording, phone="+911234567890", candidate_name="Alice")

    assert doc["call_id"] == "abc-123"
    assert isinstance(doc["started_at"], datetime)
    assert isinstance(doc["ended_at"], datetime)
    assert doc["phone"] == "+911234567890"
    assert doc["candidate_name"] == "Alice"
    assert doc["duration_s"] == 300.0
    assert doc["end_reason"] == "user_hangup"
    assert doc["transcript"] == [{"role": "agent", "text": "Hello"}]
    assert doc["metrics"] == {"turns": 5}
    assert doc["errors"] == []


# ---------------------------------------------------------------------------
# 4. _build_document handles missing / None fields gracefully
# ---------------------------------------------------------------------------

def test_build_document_missing_fields():
    doc = MongoWriter._build_document({}, phone=None, candidate_name=None)

    assert doc["call_id"] is None
    assert doc["started_at"] is None
    assert doc["ended_at"] is None
    assert doc["phone"] is None
    assert doc["candidate_name"] is None
    assert doc["transcript"] == []
    assert doc["metrics"] == {}
    assert doc["errors"] == []


# ---------------------------------------------------------------------------
# 5. write_call swallows exceptions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_call_swallows_exceptions():
    writer = MongoWriter()
    writer._enabled = True
    mock_col = MagicMock()
    mock_col.insert_one = AsyncMock(side_effect=RuntimeError("network failure"))
    writer._collection = mock_col

    result = await writer.write_call(recording={"call_id": "boom"})
    assert result is False


# ---------------------------------------------------------------------------
# 6. write_call succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_call_succeeds():
    writer = MongoWriter()
    writer._enabled = True
    mock_col = MagicMock()
    mock_col.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake_id"))
    writer._collection = mock_col

    recording = {
        "call_id":    "call-xyz",
        "started_at": "2024-03-01T08:00:00+00:00",
        "ended_at":   "2024-03-01T08:05:00+00:00",
        "duration_s": 300.0,
        "end_reason": "completed",
        "transcript": [],
        "metrics":    {},
        "errors":     [],
    }

    result = await writer.write_call(
        recording=recording,
        phone="+910000000000",
        candidate_name="Bob",
    )

    assert result is True
    mock_col.insert_one.assert_called_once()
    inserted_doc = mock_col.insert_one.call_args[0][0]
    assert inserted_doc["call_id"] == "call-xyz"
    assert inserted_doc["phone"] == "+910000000000"
    assert inserted_doc["candidate_name"] == "Bob"
    assert isinstance(inserted_doc["started_at"], datetime)
