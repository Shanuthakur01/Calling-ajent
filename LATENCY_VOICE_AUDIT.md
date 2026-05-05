# LATENCY_VOICE_AUDIT.md — Endpoint timing + TTS voice settings

Generated: 2026-05-02

---

## 1. Endpoint silence timer (`endpoint_ms`)

### Where it lives

**`config.py` line 76**
```python
endpoint_ms: int = 1200             # env: ENDPOINT_MS
```

**`agent/call_session.py` lines 243-249**
```python
async def _endpoint_timeout(self) -> None:
    """Sleep endpoint_ms then fire _handle_user_turn."""
    try:
        await asyncio.sleep(settings.endpoint_ms / 1000.0)   # ← reads here
        await self._handle_user_turn()
    except asyncio.CancelledError:
        pass
```

The timer is **reset on every `is_final` STT event** (line 236-239). It fires
`_handle_user_turn()` only after `endpoint_ms` ms of no new `is_final` events.

### Active value

| Setting | Default | In `.env` | Active |
|---|---|---|---|
| `endpoint_ms` | 1200 | not set | **1200 ms** |

---

## 2. Deepgram endpointing (`dg_endpointing_ms`)

### Where it lives

**`config.py` lines 72-73**
```python
dg_endpointing_ms: int = 1200       # env: DG_ENDPOINTING_MS  (was 300)
dg_utterance_end_ms: int = 1500     # env: DG_UTTERANCE_END_MS (was 1200)
```

**`stt/deepgram_client.py` lines 36-39**
```python
f"&endpointing={settings.dg_endpointing_ms}"
...
f"&utterance_end_ms={settings.dg_utterance_end_ms}"
```

Deepgram fires `speech_final=True` after `dg_endpointing_ms` ms of silence in
a speech window. The STT client only fires `on_transcript(is_final=True)` on
`speech_final` (not on individual `is_final` windows). Once the speech_final
fires, the client-side `endpoint_ms` timer starts.

### Active values

| Setting | Default | In `.env` | Active |
|---|---|---|---|
| `dg_endpointing_ms` | 1200 | not set | **1200 ms** |
| `dg_utterance_end_ms` | 1500 | not set | **1500 ms** |

**Total worst-case silence before pipeline starts:**
`dg_endpointing_ms (1200)` + `endpoint_ms (1200)` = **2400 ms** after user stops speaking.

---

## 3. ElevenLabs TTS — exact API call

### File: `tts/elevenlabs_tts.py` lines 34-59

```python
async with http_client.stream(
    "POST",
    f"{_BASE}/text-to-speech/{settings.elevenlabs_voice_id}/stream",
    headers={
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    },
    params={
        "output_format": "ulaw_8000",
        "optimize_streaming_latency": 3,   # ← hardcoded
    },
    json={
        "text": text,
        "model_id": settings.elevenlabs_model,
        "voice_settings": {
            "stability":       0.38,       # ← hardcoded
            "similarity_boost": 0.82,      # ← hardcoded
            "style":           0.0,        # ← hardcoded
            "use_speaker_boost": True,     # ← hardcoded
            # "speed" field is ABSENT
        },
    },
    timeout=httpx.Timeout(30.0, connect=5.0),
)
```

### Voice / model settings

| Parameter | Where set | Current value | Env-overridable? |
|---|---|---|---|
| `voice_id` | `config.py:55` (`elevenlabs_voice_id`) | `EMh4QfWp9dtmYomyxDic` | ✅ (field exists) |
| `model_id` | `config.py:56` (`elevenlabs_model`) | `eleven_flash_v2_5` | ✅ (field exists) |
| `optimize_streaming_latency` | hardcoded in `elevenlabs_tts.py:41` | `3` | ❌ |
| `stability` | hardcoded in `elevenlabs_tts.py:46` | `0.38` | ❌ |
| `similarity_boost` | hardcoded in `elevenlabs_tts.py:47` | `0.82` | ❌ |
| `style` | hardcoded in `elevenlabs_tts.py:48` | `0.0` | ❌ |
| `use_speaker_boost` | hardcoded in `elevenlabs_tts.py:49` | `True` | ❌ |
| `speed` | **not sent at all** | — | ❌ |

---

## 4. Active values at runtime (from `.env` + config defaults)

The `.env` file does NOT override any TTS or timing settings. All values below
come from code defaults.

| Setting | Value |
|---|---|
| `endpoint_ms` | **1200 ms** |
| `dg_endpointing_ms` | **1200 ms** |
| `dg_utterance_end_ms` | **1500 ms** |
| `elevenlabs_voice_id` | `EMh4QfWp9dtmYomyxDic` |
| `elevenlabs_model` | `eleven_flash_v2_5` |
| `stability` | `0.38` (hardcoded) |
| `similarity_boost` | `0.82` (hardcoded) |
| `style` | `0.0` (hardcoded) |
| `use_speaker_boost` | `True` (hardcoded) |
| `speed` | **not sent** (field absent from request) |
| `optimize_streaming_latency` | `3` (hardcoded) |

---

## 5. Issues identified

### Issue 1 — Late reply (silence too long)

Both `dg_endpointing_ms` and `endpoint_ms` are set to 1200 ms each.
The pipeline cannot start until **both** timers have fired:
- User stops speaking
- → Deepgram waits 1200 ms → fires `speech_final`
- → Client endpoint timer waits another 1200 ms → calls `_handle_user_turn`
- **Total minimum latency added: 2400 ms before LLM even starts**

`endpoint_ms` was intended as a coalescing window to merge rapid `is_final`
bursts, not as a second long silence timeout. At 1200 ms it doubles the
Deepgram-side silence window.

Proposed: both 1200 → **800 ms** (saves ~800 ms worst-case; still prevents
premature cuts on natural pauses).

### Issue 2 — TTS voice clarity/pace

- `style: 0.0` disables prosodic variation (flat delivery).
- `speed` field is absent (uses ElevenLabs server default of 1.0×).
- `optimize_streaming_latency: 3` is one step below maximum (4).
- All four fields are hardcoded — no ability to tune from `.env`.

Proposed:
- `stability: 0.4` (raise slightly from 0.38 for more consistent output)
- `similarity_boost: 0.85` (raise slightly for better voice resemblance)
- `style: 0.15` (add mild prosodic variation — less robotic)
- `use_speaker_boost: True` (keep)
- `speed: 1.05` (5% faster — noticeably quicker without sounding rushed)
- `optimize_streaming_latency: 4` (max — saves ~50 ms TTFT)

All should be config-driven so they can be tuned from `.env` without redeploy.
