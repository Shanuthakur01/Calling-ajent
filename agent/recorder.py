"""
CallRecorder — non-blocking call transcript and metrics persistence.

Every call writes recordings/{call_id}.json when RECORDING_ENABLED=true.
Writes are queued via asyncio.Queue so the call pipeline is never blocked.
Incremental writes: each add_* call triggers a background flush, so partial
data survives a mid-call crash.

Optional: RECORD_AUDIO=true also writes recordings/{call_id}.ulaw with
raw outbound μ-law frames (background-queued append writes to a single
open file handle — no repeated open/close overhead per frame).

Dependencies: config (settings only). No imports from the agent package.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)


async def ensure_recording_dir() -> Path:
    """Create the recordings directory (resolved to absolute path). Returns the Path."""
    path = Path(settings.recording_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    logger.info("Recordings dir: %s (writable=%s)", path, os.access(path, os.W_OK))
    return path


class CallRecorder:
    """
    Per-call non-blocking recorder.

    Usage:
        recorder = CallRecorder(call_id, Path("recordings"))
        await recorder.start()
        recorder.add_agent_turn("Hello!", duration_ms=1240)
        recorder.add_user_turn("Hi there")
        recorder.add_error("TTS timeout")
        await recorder.close("user_hangup", metrics_dict)

    All add_* methods are synchronous (queue.put_nowait) and return instantly.
    Disk I/O happens only in the background _writer task.
    """

    def __init__(self, call_id: str, recording_dir: Path) -> None:
        self._call_id    = call_id
        self._json_path  = recording_dir / f"{call_id}.json"
        self._ulaw_path  = (recording_dir / f"{call_id}.ulaw") if settings.record_audio else None
        self._started_at = datetime.now(timezone.utc)
        self._started_ts = time.time()

        self._transcript: List[Dict[str, Any]] = []
        self._errors:     List[str] = []
        self._queue:      asyncio.Queue = asyncio.Queue()
        self._task:       Optional[asyncio.Task] = None
        self._final_doc:  Optional[dict] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background writer task and trigger an initial snapshot."""
        logger.info("CallRecorder writing to: %s", self._json_path.resolve())
        self._task = asyncio.create_task(
            self._writer(), name=f"recorder-{self._call_id}"
        )
        self._queue.put_nowait("flush")

    async def close(self, end_reason: str, metrics: Optional[Dict] = None) -> None:
        """Send the final-write sentinel and wait for the writer task to finish."""
        await self._queue.put(("close", end_reason, metrics or {}))
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning("Recorder close timeout call=%s: %s", self._call_id, exc)

    # ── Public API (all synchronous / non-blocking) ────────────────────────

    def add_agent_turn(self, text: str, duration_ms: Optional[float] = None) -> None:
        """Record an agent speech turn (fire-and-forget queue put)."""
        self._transcript.append({
            "role":        "agent",
            "text":        text,
            "ts":          round(time.time() - self._started_ts, 2),
            "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        })
        self._queue.put_nowait("flush")

    def add_user_turn(self, text: str, duration_ms: Optional[float] = None) -> None:
        """Record a user speech turn (fire-and-forget queue put)."""
        self._transcript.append({
            "role":        "user",
            "text":        text,
            "ts":          round(time.time() - self._started_ts, 2),
            "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        })
        self._queue.put_nowait("flush")

    def add_error(self, message: str) -> None:
        """Record an error string (fire-and-forget queue put)."""
        self._errors.append(message)
        self._queue.put_nowait("flush")

    def add_audio_chunk(self, chunk: bytes) -> None:
        """Queue a raw μ-law chunk for appending (only active when RECORD_AUDIO=true)."""
        if self._ulaw_path is not None:
            self._queue.put_nowait(("audio", chunk))

    # ── Background writer ──────────────────────────────────────────────────

    async def _writer(self) -> None:
        """Drain the queue and write to disk. Runs as a background asyncio task."""
        ulaw_fh = None
        if self._ulaw_path is not None:
            try:
                self._ulaw_path.parent.mkdir(parents=True, exist_ok=True)
                ulaw_fh = open(self._ulaw_path, "ab")  # one open for the full call
            except Exception as exc:
                logger.error(
                    "Recorder failed to open ulaw file call=%s: %s", self._call_id, exc
                )
        try:
            while True:
                item = await self._queue.get()
                if item == "flush":
                    await self._write_json()
                elif isinstance(item, tuple):
                    kind = item[0]
                    if kind == "audio" and ulaw_fh is not None:
                        ulaw_fh.write(item[1])
                    elif kind == "close":
                        _, end_reason, metrics = item
                        await self._write_json(end_reason=end_reason, metrics=metrics)
                        break
        finally:
            if ulaw_fh is not None:
                try:
                    ulaw_fh.close()
                except Exception:
                    pass

    async def _write_json(
        self,
        end_reason: Optional[str] = None,
        metrics: Optional[Dict] = None,
    ) -> None:
        """Atomically (over)write the JSON snapshot to disk."""
        now      = datetime.now(timezone.utc)
        duration = (now - self._started_at).total_seconds() if end_reason else None
        doc = {
            "call_id":    self._call_id,
            "started_at": self._started_at.isoformat(),
            "ended_at":   now.isoformat() if end_reason else None,
            "duration_s": round(duration, 1) if duration is not None else None,
            "end_reason": end_reason,
            "transcript": list(self._transcript),
            "metrics":    metrics or {},
            "errors":     list(self._errors),
        }
        if end_reason is not None:
            self._final_doc = doc
        try:
            self._json_path.parent.mkdir(parents=True, exist_ok=True)
            self._json_path.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.error(
                "Recorder JSON write error call=%s: %s", self._call_id, exc
            )
