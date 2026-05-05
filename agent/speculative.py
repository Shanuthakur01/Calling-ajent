"""
Speculative LLM pre-computation on interim STT transcripts.

How it works:
  1. On each interim transcript, maybe_start() fires a background LLM task
     with the current interim text as the user message.  Only one task runs
     at a time; if the text changes, the old task is cancelled and a new one
     starts.
  2. When the final transcript arrives, try_consume() is called:
     - HIT : final text matches speculative text (normalized).  The pre-computed
             LLM response is returned immediately, saving the LLM round-trip.
     - MISS: texts differ.  The speculative task is cancelled; the pipeline
             runs a fresh LLM call.
  3. Speculative tasks call LLM only -- NO TTS, NO audio. Text is held in the
     completed asyncio.Task result until consumed or discarded.
"""

import asyncio
import logging
import time
from typing import Optional, Tuple

from llm.llm_client import LLMClient

logger = logging.getLogger(__name__)

_CONSUME_TIMEOUT = 8.0   # max seconds to wait for an in-flight speculative task


def _normalize(text: str) -> str:
    """Lowercase, strip leading/trailing whitespace and sentence-final punctuation."""
    return text.lower().strip().rstrip(".,!?").strip()


class SpeculativeWorker:
    """
    Manages a single background LLM pre-computation task per call.

    Thread-safety: all methods are called from the same asyncio event loop.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._task: Optional[asyncio.Task] = None
        self._task_text: str = ""     # normalized text the current task was started for
        self._task_start: float = 0.0

    # -- Public API -------------------------------------------------------------

    def maybe_start(self, interim_text: str, history: list) -> None:
        """
        Start/restart the speculative LLM task for interim_text.
        No-op if a task is already running for the same normalized text.
        Cancels and restarts if the text changed.
        history: snapshot of conversation history *without* the pending user turn.
        """
        normalized = _normalize(interim_text)
        if not normalized:
            return
        if self._task is not None and not self._task.done() and self._task_text == normalized:
            return   # same text -- task already running
        self._cancel_current()
        self._task_text  = normalized
        self._task_start = time.perf_counter()
        spec_history = list(history) + [{"role": "user", "content": interim_text.strip()}]
        self._task = asyncio.create_task(
            self._run(spec_history), name="spec-llm"
        )
        logger.debug("Speculative LLM started for %r", normalized[:60])

    async def try_consume(
        self, final_text: str
    ) -> Optional[Tuple[str, float]]:
        """
        Called when the final transcript arrives.

        Returns (precomputed_text, savings_ms) on HIT, or None on MISS.
        A MISS cancels the speculative task; the caller must run a fresh LLM.
        """
        if self._task is None:
            return None

        final_norm = _normalize(final_text)
        if final_norm != self._task_text:
            logger.debug(
                "Speculative MISS: final=%r  spec=%r", final_norm[:60], self._task_text[:60]
            )
            self._cancel_current()
            return None

        # HIT -- await the task (may already be done)
        t_consume = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                asyncio.shield(self._task), timeout=_CONSUME_TIMEOUT
            )
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as exc:
            logger.warning("Speculative task failed on consume: %s", exc, exc_info=True)
            self._task = None
            return None

        savings_ms = max(0.0, (t_consume - self._task_start) * 1000)
        logger.info(
            "Speculative HIT  savings=%.0fms  text=%r",
            savings_ms, self._task_text[:60],
        )
        self._task = None
        return result, savings_ms

    def cancel(self) -> None:
        """Cancel any in-flight speculative task (barge-in, close, etc.)."""
        self._cancel_current()

    # -- Internal ---------------------------------------------------------------

    def _cancel_current(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._task_text = ""

    async def _run(self, spec_history: list) -> str:
        """Accumulate all LLM sentences into a single string.  No TTS/audio."""
        sentences = []
        async for sentence in self._llm.stream_sentences(
            spec_history, call_metrics=None
        ):
            sentences.append(sentence)
        return " ".join(sentences)
