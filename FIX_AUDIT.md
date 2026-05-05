# FIX_AUDIT.md — Live Call Diagnosis

## 1. Where does TTS audio go after generation?

**In Phase 4 code (files on disk right now):** audio chunks are piped directly over the
Plivo WebSocket, never written to a file or memory cache.

The path is:

```
ElevenLabs /stream  →  tts_with_fallback() async generator
                         ↓  160-byte μ-law chunks
              pipeline._tts_worker  →  audio_q
                         ↓
              pipeline._ws_sender   →  ws.send_json({"event":"playAudio", ...})
```

The legacy `audio_cache.py` is still imported in `main.py` only to serve the
`/audio/{audio_id}` endpoint — but nothing in `call_session.py` or
`pipeline.py` calls `cache_put()`.

---

## 2. Is `/audio/{audio_id}` used during live calls?

**It should not be — but the ngrok log proves it is.**

`GET /audio/{id}` can only be fetched by Plivo when our server calls:

```python
await self._plivo.play(call_uuid, f"{settings.base_url}/audio/{audio_id}")
```

Plivo receives this REST call, then GETs the audio URL to play it.

**Searching every file on disk for `plivo.play` or `cache_put` in the live path:**

| File | `plivo.play()` called? | `cache_put()` called? |
|------|------------------------|----------------------|
| `agent/call_session.py` | **NO** | **NO** |
| `agent/pipeline.py`     | **NO** | **NO** |
| `telephony/plivo_rest.py` | defined but not called | — |

**Conclusion:** The server is running **stale code** — almost certainly the Phase 3
version of `agent/call_session.py`, which contained:

```python
# Phase 3 call_session.py (OLD — should no longer be on disk)
aid, q = create_stream()
url = f"{settings.base_url}/audio/{aid}"
synth_task = asyncio.create_task(stream_synthesize(full_text, q, self._http))
await self._plivo.play(self._call_sid, url)          # ← this triggers GET /audio/{id}
```

**Most probable cause:** The Python process was started before Phase 4 edits were
saved and has not been restarted. Python's `__pycache__` `.pyc` files may also
be stale if the server is running with `python -m` directly.

**Fix:** `CTRL-C` the server, delete `__pycache__` directories, restart.

---

## 3. Is TTS streaming chunks or generating full audio then sending?

**On disk:** streaming, correctly. `stream_sentence_mulaw()` uses
`http_client.stream(...)` → `resp.aiter_bytes(160)`, which yields chunks as they
arrive from ElevenLabs. No full-file buffering.

**If Phase 3 is running instead:** `stream_synthesize()` used to stream MP3 into
an `asyncio.Queue`, but Plivo was fetching a separate HTTP URL — so the "streaming"
benefit was lost because Plivo had to wait for the full file before it started
playing (or at least until enough bytes arrived for it to buffer).

The 10–12 s delay matches Phase 3 behaviour: ElevenLabs generates ~8–10 s of
speech audio (long greeting), the full MP3 arrives, Plivo fetches it, plays it.

---

## 4. Where is the Plivo WebSocket send? Exact lines.

**`agent/call_session.py` — greeting (`_say()`):**
```python
# call_session.py:280
await self._ws.send_json({
    "event": "playAudio",
    "media": {
        "contentType": "audio/x-mulaw",
        "sampleRate":  8000,        # ← BUG A — may need to be string "8000"
        "payload":     payload,
    },
})
```

**`agent/pipeline.py` — normal turns (`_ws_sender()`):**
```python
# pipeline.py:152
await self._ws.send_json({
    "event": "playAudio",
    "media": {
        "contentType": "audio/x-mulaw",
        "sampleRate":  8000,        # ← BUG A — same issue
        "payload":     payload,
    },
})
```

The method is `WebSocket.send_json()` which calls FastAPI's JSON serialiser.
`sampleRate: 8000` will be emitted as integer `8000`, not string `"8000"`.

---

## 5. Is the event name correct?

**Used:** `"event": "playAudio"`

Plivo's bidirectional streaming documentation specifies `"playAudio"` for outbound
audio — so the event name itself is correct.

However, Plivo's documentation also shows `sampleRate` as a **string** in their
examples:
```json
{ "event": "playAudio", "media": { "contentType": "audio/x-mulaw",
  "sampleRate": "8000", "payload": "..." } }
```

Plivo may silently ignore frames where `sampleRate` is the wrong type,
which would cause silence on the call even if the WebSocket send succeeds.

---

## 6. Bugs found in Phase 4 code (independent of the stale-code issue)

| ID | File | Line | Bug | Severity |
|----|------|------|-----|----------|
| A | `call_session.py`, `pipeline.py` | 280, 152 | `sampleRate: 8000` (int) — Plivo expects `"8000"` (string) | High |
| B | `tts/elevenlabs_tts.py` | 38 | `optimize_streaming_latency` not set — adds ~200 ms TTFB | Medium |
| C | `tts/elevenlabs_tts.py` | 20 | `_MULAW_FRAME = 160` (20 ms) — very small frames → high WS overhead. 320 bytes (40 ms) is safer | Low |
| D | `agent/call_session.py` | 53 | `_PLIVO_BUFFER = 0.4` may be too short for ngrok round-trip; should be `0.6` | Low |
| E | `agent/pipeline.py` | 79 | `asyncio.gather` does not propagate `CancelledError` from external cancel properly in Python 3.11+: the gather itself isn't cancelled, only `run_task` is — see note below | Medium |

**Note on Bug E:**  When the outer task (`_run_pipeline`) is cancelled,
`asyncio.CancelledError` is raised at the `await asyncio.gather(...)` line.
Python 3.11 changed `CancelledError` propagation semantics.  The current
`try/except CancelledError` handler in `pipeline.run()` re-cancels the sub-tasks
and re-raises, which is correct — but needs verification.

---

## 7. No sync blocking calls

```
grep -rn "time\.sleep\|import requests\|requests\." agent/ tts/ stt/ main.py
(no output)
```

Clean. All I/O is async. ✓

---

## 8. Root-cause summary

| Symptom | Root cause |
|---------|-----------|
| GET /audio/{id} fetched | **Stale Phase 3 process running** — calls REST Play API |
| 10–12 s delay | Phase 3 collects full audio before playing; greeting is ~8 s |
| Only first sentence plays | Phase 3 pipeline: REST Play cancels any in-progress Play call when a new one is made — only the LAST play wins; but Phase 3 already fixed that by collecting all sentences. More likely: ElevenLabs MP3 streaming fails after one successful play. |
| Call dropped | Plivo's stream times out when no audio arrives for N seconds |

---

## 9. What needs to happen before Step 2

1. **Restart the server** (kill process + clear `__pycache__`) to ensure Phase 4 code runs.
2. Fix Bug A (`sampleRate` string).
3. Add `optimize_streaming_latency=3` to ElevenLabs params (Bug B).
4. Optionally: increase `_MULAW_FRAME` to 320 bytes and `_PLIVO_BUFFER` to 0.6 s.
5. Add proper latency timestamps at every call-path stage (as requested in Step 2.7).
6. Add the integration test that asserts first media frame within 1500 ms (Step 3.1).

**Awaiting your approval to proceed with Step 2.**
