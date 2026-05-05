# Voice AI Agent — Architecture Audit

Generated: 2026-05-01

## 1. Call Flow

```
POST /make-call ──► plivo_outbound.make_call() ──► state.register()
                                                         │
student answers ─────────────────────────────────────► POST /incoming-call
                                                         │ (PlivoXML with Stream tag)
                                               <Stream bidirectional>
                                                         │
                                              WS /media-stream
                                                         │
                                         PlivoStreamHandler.handle()
                                                         │
                                              CallSession.start()
                                               ┌─────────┴─────────┐
                                    DeepgramSTTClient.connect()    _say(greeting)
                                    (WS → api.deepgram.com)        │
                                                                    ElevenLabs /speak
                                                                    PlivoRestClient.play()
                                                         │
                              ┌────────────── loop ──────┘
                              │
                     Plivo media events (mulaw 20ms chunks)
                              │
                     CallSession.handle_audio()
                     [GATE: only if state == LISTENING]
                              │
                     DeepgramSTTClient.send_audio()
                              │
                     Deepgram sends speech_final
                              │
                     _on_transcript(text, is_final=True)
                              │
                     asyncio.create_task(_run_pipeline(text))
                              │
                     ┌────────┴─────────────────────────────────┐
                     LLMClient.stream_sentences()                 │
                     (Groq llama-3.3-70b, streaming)             │
                     collect ALL sentences                        │
                              │                                   │
                     ElevenLabs /text-to-speech (blocking)        │
                     cache_put(wav)                               │
                     PlivoRestClient.play(url) ─────────────────►│
                     wait(dur + 1.0s) → LISTENING                 │
                              │                                   │
                              └────────────── loop ──────────────┘
```

## 2. Providers

| Layer      | Provider                        | Protocol                         |
|------------|---------------------------------|----------------------------------|
| Telephony  | Plivo                           | WebSocket (mulaw 8kHz) + REST    |
| STT        | Deepgram Nova-2                 | WebSocket (linear16 8kHz)        |
| LLM        | Groq llama-3.3-70b-versatile    | OpenAI-compat HTTP streaming     |
| LLM backup | OpenAI GPT-4o-mini              | OpenAI SDK streaming             |
| TTS        | ElevenLabs eleven_flash_v2_5    | HTTP POST (pcm_16000) → WAV      |
| Audio conv | audioop (stdlib / audioop-lts)  | mulaw ↔ linear16                 |

## 3. Architecture Checklist

### ✅ Audio gate (half-duplex echo prevention)
`CallSession.handle_audio()` returns immediately unless `_state == LISTENING`. Saanvi's
own voice is never forwarded to Deepgram during SPEAKING or PROCESSING. Correctly prevents
echo-triggered double-responses.

### ✅ Single Play call per turn
All LLM sentences are collected before TTS is called, producing one audio file and one
Plivo `/Play/` call. No mid-sentence cancellation artifacts.

### ✅ STT accumulation (speech_final gating)
`DeepgramSTTClient` accumulates `is_final` windows in `_buf` and only fires the pipeline
callback on `speech_final` or `UtteranceEnd`. Prevents premature pipeline triggers while
the speaker is mid-sentence.

### ✅ Groq streaming
`LLMClient.stream_sentences()` uses `stream=True` and parses tokens into grammatically
complete sentences (`.!?` + `_MIN_SENTENCE=12` guard). LLM is ready to stream to TTS.

### ✅ History trimming
`_trim_history()` keeps the last `max_conversation_turns × 2` messages plus the system
prompt. Prevents unbounded memory growth on long calls.

### ⚠️ TTS pipeline — blocking, not streaming
`synthesize()` blocks until the full audio file is downloaded from ElevenLabs before
`play()` is called. This adds 300–600 ms of serialised latency every turn.
**Fix**: use ElevenLabs `/stream` endpoint + `asyncio.Queue` → `StreamingResponse`.
Start `play()` concurrently with synthesis start.

### ⚠️ Provider clients recreated per call
`LLMClient`, `PlivoRestClient`, and ElevenLabs `httpx.AsyncClient` are instantiated
inside `CallSession.__init__`, i.e. once per call. HTTP connection pools are torn down
and rebuilt for every call.
**Fix**: create singletons in lifespan, inject via constructor.

### ❌ Deepgram WebSocket — no reconnect
`_receiver()` calls `self._running = False` on any exception. A network blip silently
kills STT for the rest of the call.
**Fix**: exponential backoff reconnect loop in `_receiver()`.

### ❌ Silence hangup watchdog — missing
No timer to hang up when the student goes silent. Calls run until Plivo's own timeout.
**Fix**: `asyncio.create_task(_silence_watchdog())` that fires `hangup()` after
`settings.hangup_silence_secs` of inactivity.

### ❌ Hardcoded provider constants
ElevenLabs voice ID (`EMh4QfWp9dtmYomyxDic`), ElevenLabs model (`eleven_flash_v2_5`),
Groq model (`llama-3.3-70b-versatile`), Deepgram endpointing (300 ms), and
utterance_end_ms (1200 ms) are module-level constants not exposed in `.env`.
**Fix**: move all to `config.py` `Settings`.

### ❌ `hangup()` missing on PlivoRestClient
The silence watchdog (and any forced termination) cannot end the call. Only `play()` and
`stop_play()` exist.
**Fix**: add `hangup(call_uuid)` calling `DELETE /Account/{id}/Call/{uuid}/`.

### ❌ Dead code
- `telephony/twilio_handler.py` — Twilio was abandoned; imported nowhere.
- `tts/deepgram_tts.py` — superseded by ElevenLabs; imported nowhere.
**Fix**: delete both files.

## 4. Latency Budget

| Step                        | Current     | After Phase 3          |
|-----------------------------|-------------|------------------------|
| LLM generation (Groq)       | 500–800 ms  | 500–800 ms (unchanged) |
| ElevenLabs synthesis        | 300–600 ms  | ~80 ms TTFB (streaming)|
| Plivo Play API call         | ~200 ms     | concurrent with synth  |
| Plivo fetch + buffer start  | ~400 ms     | streaming response     |
| **Total TTFA (p50)**        | **~1.4–1.8 s** | **~0.9–1.1 s**      |

## 5. Phase 3 Refactor Scope

1. `config.py` — 6 new env-configurable fields
2. `tts/audio_cache.py` — streaming queue support
3. `tts/elevenlabs_tts.py` — `stream_synthesize()`, singleton client, config-driven
4. `agent/call_session.py` — streaming pipeline, silence watchdog, singleton injection
5. `main.py` — lifespan singletons, `StreamingResponse` for audio, inject to handler
6. `stt/deepgram_client.py` — exponential backoff reconnect, config-driven URL
7. `telephony/plivo_handler.py` — accept singleton client params
8. `telephony/plivo_rest.py` — `hangup()` method
9. `llm/groq_client.py` — use `settings.groq_model`
10. Delete `telephony/twilio_handler.py`
11. Delete `tts/deepgram_tts.py`
