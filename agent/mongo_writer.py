"""
MongoWriter — best-effort, non-blocking MongoDB sink for call recordings.

Disk is primary; Mongo is append-only and never blocks or aborts a call.
If MONGODB_URI is unset or the ping fails, the writer stays disabled and
all write_call() calls return False immediately.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger(__name__)


class MongoWriter:
    _instance: Optional["MongoWriter"] = None

    def __init__(self) -> None:
        self._client = None
        self._collection = None
        self._enabled = False

    @classmethod
    def instance(cls) -> "MongoWriter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self) -> None:
        """Connect to MongoDB and create indexes. Disables self on any failure."""
        if not settings.mongodb_enabled or not settings.mongodb_uri:
            logger.info("MongoWriter disabled (uri=%s, enabled=%s)",
                        bool(settings.mongodb_uri), settings.mongodb_enabled)
            return

        try:
            import motor.motor_asyncio as motor_asyncio
            from pymongo import ASCENDING, DESCENDING

            self._client = motor_asyncio.AsyncIOMotorClient(settings.mongodb_uri)
            # Ping to verify connectivity before declaring enabled
            await self._client.admin.command("ping")

            db = self._client[settings.mongodb_database]
            self._collection = db[settings.mongodb_collection]

            await self._collection.create_index("call_id", unique=True, background=True)
            await self._collection.create_index("phone", background=True)
            await self._collection.create_index(
                [("started_at", DESCENDING)], background=True
            )

            self._enabled = True
            logger.info(
                "MongoWriter connected: %s / %s",
                settings.mongodb_database,
                settings.mongodb_collection,
            )
        except Exception as exc:
            logger.warning("MongoWriter connect failed — Mongo disabled: %s", exc)
            self._enabled = False

    async def write_call(
        self,
        recording: Dict[str, Any],
        phone: Optional[str] = None,
        candidate_name: Optional[str] = None,
    ) -> bool:
        """Insert a call recording document. Returns True on success, False otherwise."""
        if not self._enabled or self._collection is None:
            return False

        try:
            from pymongo.errors import DuplicateKeyError

            doc = self._build_document(recording, phone, candidate_name)
            await self._collection.insert_one(doc)
            return True
        except Exception as exc:
            logger.error("MongoWriter.write_call failed call=%s: %s",
                         recording.get("call_id"), exc)
            return False

    @staticmethod
    def _build_document(
        recording: Dict[str, Any],
        phone: Optional[str],
        candidate_name: Optional[str],
    ) -> Dict[str, Any]:
        """Convert a recording dict to a Mongo document (ISO strings → datetime)."""

        def _to_dt(value: Any) -> Optional[datetime]:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            try:
                return datetime.fromisoformat(str(value))
            except (ValueError, TypeError):
                return None

        return {
            "call_id":        recording.get("call_id"),
            "phone":          phone,
            "candidate_name": candidate_name,
            "started_at":     _to_dt(recording.get("started_at")),
            "ended_at":       _to_dt(recording.get("ended_at")),
            "duration_s":     recording.get("duration_s"),
            "end_reason":     recording.get("end_reason"),
            "transcript":     recording.get("transcript", []),
            "metrics":        recording.get("metrics", {}),
            "errors":         recording.get("errors", []),
        }

    async def close(self) -> None:
        """Close the motor client."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                logger.warning("MongoWriter close error: %s", exc)
        self._enabled = False
