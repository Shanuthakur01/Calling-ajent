"""
Tests for the backchannel ack system.

Coverage
────────
1.  BackchannelPlayer.pick() never returns the same clip twice in a row
2.  BackchannelPlayer with no clips returns None
3.  ensure_ack_cache loads existing .ulaw files from cache dir
4.  Backchannel is sent when LISTENING + conditions met  (via BackchannelManager)
5.  Backchannel is NOT sent when _bcm is None (enable_backchannels=False)
6.  BackchannelManager.cancel() cancels the in-flight task within 50 ms
7.  BackchannelManager.cancel() issues clearAudio to Plivo
8.  BackchannelManager.maybe_play() is a no-op when is_listening=False
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.backchannels import BackchannelPlayer, BackchannelManager


# ---------------------------------------------------------------------------
# Test 1 — pick() avoids consecutive repeat
# ---------------------------------------------------------------------------

def test_backchannel_player_no_consecutive_repeat():
    """pick() must not return the same clip name twice in a row."""
    clips = {"a": b"clip_a", "b": b"clip_b", "c": b"clip_c"}
    player = BackchannelPlayer(clips)

    last = None
    for _ in range(30):
        data = player.pick()
        assert data is not None
        name = next(k for k, v in clips.items() if v == data)
        assert name != last, f"Consecutive repeat of {name!r}"
        last = name


# ---------------------------------------------------------------------------
# Test 2 — empty player returns None
# ---------------------------------------------------------------------------

def test_backchannel_player_empty_returns_none():
    """pick() on an empty BackchannelPlayer must return None."""
    player = BackchannelPlayer({})
    assert player.pick() is None


# ---------------------------------------------------------------------------
# Test 3 — ensure_ack_cache loads existing files
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ack_cache_loads_existing_files(tmp_path):
    """ensure_ack_cache must load .ulaw files that already exist in the cache dir."""
    from agent.backchannels import ensure_ack_cache, _ACK_TEXTS

    acks_dir = tmp_path / "acks"
    acks_dir.mkdir()
    for name in _ACK_TEXTS:
        (acks_dir / f"{name}.ulaw").write_bytes(b"\xff\xfe" * 80)

    http_mock = MagicMock()

    with patch("agent.backchannels._CACHE_DIR", acks_dir):
        player = await ensure_ack_cache(http_mock)

    http_mock.stream.assert_not_called() if hasattr(http_mock, "stream") else None
    assert player.pick() is not None


# ---------------------------------------------------------------------------
# Test 4 — backchannel sent when conditions are met (via BackchannelManager)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backchannel_sent_when_conditions_met():
    """
    CallSession._maybe_backchannel() must schedule a clip through BackchannelManager
    when state == LISTENING and timing conditions are met.
    """
    from agent.call_session import CallSession, State

    fake_settings = SimpleNamespace(
        system_prompt="test",
        enable_backchannels=True,
        backchannel_min_user_speech_s=2.0,
        backchannel_min_interval_s=4.0,
        greeting_message="hi",
        hangup_silence_secs=30.0,
        barge_in_threshold=0.85,
        endpoint_ms=250,
        min_utterance_words=2,
        stt_drop_phrases_list=lambda: [],
        short_utterance_whitelist_set=lambda: set(),
        max_conversation_turns=30,
    )

    clip_data = b"\xfe" * 160
    player    = BackchannelPlayer({"mhm": clip_data})
    ws_mock   = AsyncMock()

    session = object.__new__(CallSession)
    session._state               = State.LISTENING
    session._active              = True
    session._speech_started_at   = time.monotonic() - 3.0   # 3 s → meets 2 s threshold
    session._last_backchannel_at = time.monotonic() - 5.0   # 5 s → meets 4 s interval
    session._call_sid            = "test-call"
    session._ws                  = ws_mock
    session._stream_sid          = "sid-test"

    # Wire a real BackchannelManager so maybe_play() can create tasks
    manager      = BackchannelManager(player=player, websocket=ws_mock,
                                      stream_sid="sid-test", call_sid="test-call")
    session._bcm = manager

    tasks_created = []
    original_create_task = asyncio.create_task

    def _mock_create_task(coro, **kwargs):
        tasks_created.append(kwargs.get("name", ""))
        return original_create_task(coro, **kwargs)

    with patch("agent.call_session.settings", fake_settings), \
         patch("asyncio.create_task", side_effect=_mock_create_task):
        session._maybe_backchannel()

    assert any("bchannel" in name for name in tasks_created), (
        "Expected a backchannel task to be created"
    )


# ---------------------------------------------------------------------------
# Test 5 — backchannel NOT sent when _bcm is None (backchannels disabled)
# ---------------------------------------------------------------------------

def test_backchannel_not_sent_when_disabled():
    """_maybe_backchannel() must be a no-op when _bcm is None."""
    from agent.call_session import CallSession, State

    fake_settings = SimpleNamespace(
        enable_backchannels=False,
        backchannel_min_user_speech_s=2.0,
        backchannel_min_interval_s=4.0,
    )

    session = object.__new__(CallSession)
    session._state               = State.LISTENING
    session._active              = True
    session._bcm                 = None   # disabled
    session._speech_started_at   = time.monotonic() - 10.0
    session._last_backchannel_at = 0.0
    session._call_sid            = "test-call"

    tasks_created = []

    with patch("agent.call_session.settings", fake_settings), \
         patch("asyncio.create_task", side_effect=lambda c, **kw: tasks_created.append(kw)):
        session._maybe_backchannel()

    assert not tasks_created, "No task should be created when _bcm is None"


# ---------------------------------------------------------------------------
# Test 6 — cancel() completes within 50 ms
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backchannel_cancel_within_50ms():
    """cancel() must return in < 50 ms (task is killed synchronously)."""
    ws_mock = AsyncMock()
    player  = BackchannelPlayer({"mhm": b"\xfe" * 160})
    manager = BackchannelManager(player=player, websocket=ws_mock,
                                 stream_sid="sid", call_sid="call-cancel")

    # Plant a long-running task
    manager._task = asyncio.create_task(asyncio.sleep(10), name="dummy")

    t0 = time.perf_counter()
    manager.cancel()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 50, f"cancel() took {elapsed_ms:.1f} ms — exceeds 50 ms limit"
    assert manager._task is None, "_task must be cleared after cancel()"

    # Drain the clearAudio task so it does not leak into other tests
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Test 7 — cancel() sends clearAudio to Plivo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backchannel_cancel_sends_clear_audio():
    """cancel() must send a clearAudio event to the WebSocket."""
    ws_mock = AsyncMock()
    player  = BackchannelPlayer({"mhm": b"\xfe" * 160})
    manager = BackchannelManager(player=player, websocket=ws_mock,
                                 stream_sid="sid-clear", call_sid="call-clear")

    manager.cancel()
    # Let the fire-and-forget _clear_audio coroutine run
    await asyncio.sleep(0)

    ws_mock.send_json.assert_called_once_with({
        "event":     "clearAudio",
        "streamSid": "sid-clear",
    })


# ---------------------------------------------------------------------------
# Test 8 — maybe_play() is a no-op when is_listening=False
# ---------------------------------------------------------------------------

def test_backchannel_maybe_play_no_op_when_not_listening():
    """maybe_play() must not schedule a task when is_listening=False."""
    ws_mock = MagicMock()
    player  = BackchannelPlayer({"mhm": b"\xfe" * 160})
    manager = BackchannelManager(player=player, websocket=ws_mock,
                                 stream_sid="sid", call_sid="call-noop")

    tasks_created = []
    now = time.monotonic()

    with patch("asyncio.create_task", side_effect=lambda c, **kw: tasks_created.append(kw)):
        manager.maybe_play(
            is_listening=False,
            speech_started_at=now - 10.0,
            last_played_at=0.0,
            now=now,
            min_speech_s=2.0,
            min_interval_s=4.0,
        )

    assert not tasks_created, "No task must be created when is_listening=False"
