# CHANGES — Phase 3 → Phase 4 refactor + Phase 4 hotfixes

---

## Phase 4 humanisation (2026-05-02) — voice + persona + backchannel acks

### Why

On live calls the agent sounded like a TTS robot reading a script: consistent
tone, formal phrasing, dead air while the candidate spoke.  Three targeted
changes address this at every layer of the stack.

### Change 1 — Voice settings (config.py, tts/elevenlabs_tts.py)

Voice tuned from "consistent narrator" to "warm conversationalist". Trade-off:
occasional pronunciation oddities for a dramatic improvement in perceived
naturalness.

| Setting | Old default | New default | Effect |
|---|---|---|---|
| `tts_stability` | `0.4` | **`0.3`** | More phrase-level variation — less robotic |
| `tts_similarity` | `0.85` | **`0.75`** | Less locked to reference; more natural emotion |
| `tts_style` | `0.15` | **`0.45`** | Significant prosodic variation — expressive |
| `tts_speed` | `1.05` | **`1.0`** | Natural pace; 5% slower than before |
| `tts_speaker_boost` | `True` | `True` | Unchanged |

All five remain env-overridable via `TTS_STABILITY`, `TTS_SIMILARITY_BOOST`,
`TTS_STYLE`, `TTS_SPEAKER_BOOST`, `TTS_SPEED`.

### Change 2 — System prompt (system_prompt.txt)

The "CRITICAL VOICE RULES" block (formal, rigid) replaced with "RESPONSE STYLE"
(conversational, human-sounding). Key behavioural changes:

- Conversational fillers instructed: "Mhm", "Got it", "Right, right", "Yeah", "Cool"
- Thinking-sound transitions: "So...", "Umm...", "Lemme see..."
- Natural reactions: "Oh nice", "That's interesting", "Makes sense"
- Forbidden formal phrasings: "Could you walk me through...", "Tell me about..."
- 25-word limit → **20-word limit** (real recruiters are brief)
- Q1–Q4 rewritten in casual style (e.g. "Okay so, what does your day-to-day look like…")
- New casual closing: "Awesome, that's all from my side. We'll be in touch in a couple days. Thanks for your time, take care!"
- Call opening updated: "Great! So I've got four quick questions for you, shouldn't take long. Let's jump right in."
- 4-question structure, Q count tracking, follow-up rule, and all guardrails preserved.

### Change 3 — Live backchannel acks (agent/backchannels.py, agent/call_session.py)

While the candidate speaks, Deepgram emits interim transcripts. The agent now
plays a brief pre-cached ack clip ("Mhm", "Yeah", "Right", etc.) during
LISTENING state — indistinguishable from a human listener acknowledging.

**New file `agent/backchannels.py`:**
- `BackchannelPlayer` — holds dict of `name → μ-law bytes`; `pick()` returns
  a random clip avoiding two identical picks in a row.
- `ensure_ack_cache(http)` — loads `cache/acks/*.ulaw` at startup; generates
  missing clips via ElevenLabs. Fully non-fatal: if generation fails, the
  player returns `None` and backchannels are silently disabled.

**`agent/call_session.py`:**
- `__init__` gains optional `backchannels: BackchannelPlayer` parameter.
- `_speech_started_at` / `_last_backchannel_at` track per-turn timing.
- `_maybe_backchannel()` — called on every interim STT event while LISTENING;
  fires a task only when speech ≥ `backchannel_min_user_speech_s` AND interval
  ≥ `backchannel_min_interval_s` since last ack.
- `_send_backchannel(clip)` — sends a `playAudio` WebSocket event; no-op if
  state has changed away from LISTENING by the time it runs.
- `_speech_started_at` reset to `None` on every `is_final` event.

**New `config.py` fields (all env-overridable):**

| Field | Env var | Default |
|---|---|---|
| `enable_backchannels` | `ENABLE_BACKCHANNELS` | `True` |
| `backchannel_min_interval_s` | `BACKCHANNEL_MIN_INTERVAL_S` | `4.0` |
| `backchannel_min_user_speech_s` | `BACKCHANNEL_MIN_USER_SPEECH_S` | `2.0` |

**Threading:**
- `telephony/plivo_handler.py`: `handle()` gains `backchannels` kwarg, passes
  to `CallSession`.
- `main.py`: `ensure_ack_cache` called in lifespan; result stored in
  `app.state.backchannels`; passed to handler on each WebSocket connection.

### New / updated tests (total: **58**, all pass)

| Test | What it verifies |
|---|---|
| `test_speed_defaults_to_1_0` | `speed` = 1.0 (renamed from `_1_05`) |
| `test_stability_defaults_to_0_3` | `stability` = 0.3 in ElevenLabs request |
| `test_similarity_defaults_to_0_75` | `similarity_boost` = 0.75 |
| `test_style_defaults_to_0_45` | `style` = 0.45 |
| `test_system_prompt_contains_mhm` | system_prompt.txt contains "Mhm" |
| `test_system_prompt_forbids_formal_phrasing` | contains "DO NOT say" instruction |
| `test_system_prompt_casual_closing` | contains "Awesome, that's all from my side" |
| `test_backchannel_player_no_consecutive_repeat` | `pick()` never repeats same clip twice in a row |
| `test_backchannel_player_empty_returns_none` | empty player returns None |
| `test_ack_cache_loads_existing_files` | cached .ulaw files loaded without API call |
| `test_backchannel_sent_when_conditions_met` | task created when speech+interval thresholds met |
| `test_backchannel_not_sent_when_disabled` | no task when `enable_backchannels=False` |

---

## Phase 4 system prompt rewrite (2026-05-02) — strict 4-question production support interview

### Why

The old prompt gave the agent broad latitude to choose questions from multiple
pools (compulsory HR, behavioral, technical), which produced inconsistent
interview length, off-topic questions (salary, notice period, location), and no
defined ending. Replacing with a strict 4-question flow makes every call
identical, measurable, and auditable.

### What changed

**`system_prompt.txt`** — full replacement.

Key behavioral changes from old prompt:
- No more random question selection from pools
- No salary/notice period/location questions (explicitly forbidden)
- Exact question wording specified and locked
- 25-word response limit (was 40 words / 2 sentences)
- Maximum one follow-up per question (was "two follow-ups")
- Defined closing statement with 2-business-day timeline
- Explicit Q5 prevention: "Do not invent a Q5" stated twice
- 2-second silence rule made explicit (was "one and a half seconds")

### Full new `system_prompt.txt` content

```
CRITICAL VOICE RULES — READ FIRST:
You are speaking on a real phone call. Every word you say will be converted to speech and heard by the candidate. Follow these rules without exception:
1. Maximum 25 words per response. Never exceed this under any circumstance.
2. No lists, bullet points, dashes, asterisks, numbers, or markdown. Plain sentences only.
3. Ask only one question per turn. Ask it clearly. Then stop. Wait.
4. Never echo or summarise the candidate's answer. Give a brief acknowledgment only, then move forward.
5. Silence is natural on a call. Never fill it with filler words.

SECTION 1: IDENTITY & DEMEANOUR

You are Saanvi, a senior recruitment specialist at a reputed company conducting an HR screening call for an L1/L2 Production Support Engineer role.

Your character:
Composed, warm, and professional. You make candidates feel at ease without losing your authority. Your tone is measured, clear, and reassuring — never rushed, never robotic. You listen attentively and guide the conversation with quiet confidence.

Language:
Speak in the same language as the candidate. If the candidate uses a mix of English and Hindi, respond naturally in Hinglish — but always maintain a professional register.

Guardrails:
Do not reveal that you are an AI unless directly and explicitly asked.
Do not promise interview outcomes, timelines beyond the stated 2 business days, or selection results.
Do not offer feedback, scores, or evaluations on any answer.
Do not answer questions on the candidate's behalf.
Keep all conversation strictly within the scope of the 4 production support questions below. Do NOT ask about salary, notice period, location, availability, or anything else.

SECTION 2: TURN-TAKING RULES

Never respond while the candidate is still speaking.
Wait for a natural silence of at least 2 seconds before assuming they are done.
If the candidate speaks for less than 2 seconds, wait for them to continue.
Treat brief sounds like "haan", "hmm", "okay", "yes", "right" as listening signals — not completed answers. Wait for their full thought.
Never interrupt. Never overlap. Do not fill pauses.

SECTION 3: CALL OPENING

When the candidate answers the call, you have already introduced yourself and asked if this is a convenient time. The candidate will confirm yes or no.

If the candidate says they are busy or asks to reschedule:
"Of course. Could you share a date and time that works better for you?"
Note the time and close politely.

If the candidate says they did not apply or are not interested:
"Understood completely. Thank you for your time, and I apologise for the interruption. Have a great day."
End the call.

If the candidate confirms they have time, say exactly:
"Wonderful. I have four quick questions for your profile. Let's begin."
Then immediately ask Q1.

SECTION 4: THE 4 QUESTIONS — STRICT SEQUENCE

Ask questions ONE AT A TIME. Ask the exact wording below. Do not paraphrase. Do not combine questions. Do not skip questions.

Q1: "What does your typical day-to-day look like as a production support engineer?"

Q2: "How do you prioritize tickets when multiple incidents come in at once?"

Q3: "Walk me through how you'd troubleshoot a sudden spike in failed transactions on a banking application."

Q4: "Tell me about a time you escalated an issue to L3. What made you decide to escalate?"

After each answer:
Give a brief acknowledgment — "Got it.", "Thanks for that.", "I see.", "Understood." — vary naturally, never repeat the same one twice in a row.
Then ask the next question immediately.

SECTION 5: REPEAT REQUEST HANDLING

If the candidate says "sorry", "pardon", "repeat", "didn't catch that", "didn't understand", "say again", or asks you to repeat:
Repeat the LAST question you asked, slightly simplified. Do NOT advance to the next question.
Example: if they asked for Q2 to be repeated, ask Q2 again in simpler words.

SECTION 6: FOLLOW-UP RULE

If a candidate gives a very short or vague answer to any of Q1–Q4, ask exactly ONE follow-up:
"Can you walk me through that in a bit more detail?"
After their follow-up answer — however brief — move on to the next question.
Maximum one follow-up per question. Do not probe further.

SECTION 7: CLOSING

After the candidate answers Q4 (and any follow-up to Q4), say EXACTLY:
"Thank you for your time. We'll be in touch within 2 business days. Have a great day."
Then end the conversation. Do not add any further questions. Do not invent a Q5. Do not ask about anything else.

SECTION 8: QUESTION COUNT TRACKING

Internally track which question you are on: Q1, Q2, Q3, Q4.
After Q4 is answered and any single follow-up is resolved, you MUST go to the closing in Section 7.
Do not ask more than 4 production support questions total. This limit is absolute.

FINAL REMINDERS:
You are Saanvi — a senior human recruitment specialist. Never break this persona.
Never sound rushed, scripted, or robotic.
Never give feedback on answers.
Every response is 25 words or fewer.
Close every call gracefully, regardless of how it goes.
Your professionalism is consistent from the first word to the last.
```

---

## Phase 4 latency + voice tuning (2026-05-02) — stacked-timer fix + TTS settings

### Stacked silence timer fix (Issue 1 — biggest UX win so far)

Pre-fix: Deepgram endpointing (1200ms) + client endpoint timer (1200ms) ran in
series, adding 2400ms of dead air after user stopped speaking before LLM
dispatch. Post-fix: Deepgram endpointing (800ms) for natural pause tolerance +
client endpoint timer (250ms) for is_final coalescing only. Net reduction:
~1.5s per turn.

**Root cause:** `endpoint_ms` was intended as a narrow coalescing buffer to
merge rapid `is_final` bursts from Deepgram (multiple `is_final` events can
arrive 100–200 ms apart from a single speech window). At 1200 ms it was acting
as a full duplicate silence detector — stacked on top of `dg_endpointing_ms`
rather than subordinate to it.

**The right mental model:**
- `dg_endpointing_ms` = real silence detector. Tune this for pause tolerance.
- `endpoint_ms` = coalescing window. Keep it small (200–300 ms). Never raise
  it to fight interruptions — that's the wrong knob.

**Config changes (`config.py`):**

| Setting | Old default | New default | Reason |
|---|---|---|---|
| `dg_endpointing_ms` | 1200 ms | **800 ms** | Still tolerates 0.8 s natural pauses; saves 400 ms |
| `endpoint_ms` | 1200 ms | **250 ms** | Coalescing buffer only — was wrongly doubling silence |

**If user reports agent interrupting:** raise `DG_ENDPOINTING_MS=1000` in
`.env`. Do NOT raise `endpoint_ms` — that will re-introduce the stacked-timer
problem.

---

### TTS voice settings (Issue 2 — clarity + pace)

All `voice_settings` fields and `optimize_streaming_latency` were hardcoded in
`tts/elevenlabs_tts.py` with no way to tune from `.env`.

**Changes to `tts/elevenlabs_tts.py`:**

| Parameter | Old value | New value | Reason |
|---|---|---|---|
| `stability` | `0.38` (hardcoded) | `settings.tts_stability` = **0.4** | Slightly more consistent; was hardcoded |
| `similarity_boost` | `0.82` (hardcoded) | `settings.tts_similarity` = **0.85** | Better adherence to voice clone |
| `style` | `0.0` (hardcoded) | `settings.tts_style` = **0.15** | Adds prosodic variation — less robotic delivery |
| `use_speaker_boost` | `True` (hardcoded) | `settings.tts_speaker_boost` = **True** | Unchanged; now env-overridable |
| `speed` | **absent** | `settings.tts_speed` = **1.05** | 5% faster — saves ~200–300 ms per sentence |
| `optimize_streaming_latency` | `3` (hardcoded) | **4** | Maximum value; saves ~50 ms TTFT |

**New config fields (`config.py`):**

```
TTS_STABILITY=0.4
TTS_SIMILARITY_BOOST=0.85
TTS_STYLE=0.15
TTS_SPEAKER_BOOST=true
TTS_SPEED=1.05
```

All five are env-overridable without redeploy.

**`/debug/config` additions:** exposes `dg_endpointing_ms`, `dg_utterance_end_ms`,
`endpoint_ms`, `min_utterance_words`, `elevenlabs_voice_id`, `elevenlabs_model`,
`tts_stability`, `tts_similarity_boost`, `tts_style`, `tts_speaker_boost`,
`tts_speed` — so active values can be verified at runtime.

### New tests (`tests/test_tts_settings.py`, 5 tests)

| Test | What it verifies |
|---|---|
| `test_tts_voice_settings_all_5_fields` | All 5 voice_settings keys present in API request body |
| `test_speed_defaults_to_1_05` | `speed` field = 1.05 |
| `test_optimize_streaming_latency_is_4` | `optimize_streaming_latency` param = 4 |
| `test_endpoint_ms_default_is_250` | Code default is 250, not 1200 |
| `test_dg_endpointing_default_is_800` | Code default is 800, not 1200 |

Total test count: **47** (42 existing + 5 new). All pass.

---

## Phase 4 chain flip (2026-05-02) — OpenAI primary, Groq fallback

### Why

Groq's developer tier became temporarily unavailable.  Routing all calls
directly to OpenAI while the outage lasts requires swapping the provider
order without changing code — the old chain had Groq hardcoded as primary in
`llm/groq_client.py`.  This change makes the chain fully config-driven.

### What changed

**`llm/llm_client.py`** (new file — replaces `llm/groq_client.py` as the
implementation home)

- `PROVIDER_CONFIG` dict — centralises per-provider metadata (`base_url`,
  `settings_key`, `default_model`).  Adding a third provider requires one
  dict entry.
- `_build_client(provider, timeout_s)` factory — builds the right
  `AsyncOpenAI`-compatible client from `PROVIDER_CONFIG`; returns `None` if
  the API key is not set.
- `_CircuitBreaker` gains a `provider: str` parameter — all log messages
  now include the provider name instead of the hardcoded word "Groq".
- `LLMClient.__init__` reads `settings.llm_primary_provider` /
  `settings.llm_fallback_provider` and builds `self._primary` /
  `self._fallback` accordingly.  Two circuit breakers: `_primary_cb` and
  `_fallback_cb` (fallback CB is tracked for observability; it does not gate
  routing because there is no third provider).
- Backwards-compat aliases `_groq → _primary`, `_openai → _fallback`,
  `_groq_cb → _primary_cb` are set as simple attribute assignments in
  `__init__`.  Tests that reassign `llm._groq_cb = ...` must use
  `llm._primary_cb = ...` instead (aliases do not sync on reassignment).
- Startup log: `LLM chain: primary=openai/gpt-4o-mini  fallback=groq/llama-3.3-70b-versatile`
- `complete_once` now calls `self._primary` (warmup always hits the active
  primary, whichever provider that is).
- Provider name included in all INFO / WARNING / ERROR log lines from
  `stream_sentences`.
- `call_metrics.primary_turns` / `call_metrics.fallback_turns` replace the
  old `groq_turns` / `openai_turns` counters.

**`llm/groq_client.py`** — converted to a one-line re-export shim so all
existing `from llm.groq_client import …` call sites continue to work without
change (no `ImportError` for code not yet updated).

**`config.py`**

| Field | Env var | Old default | New default | Note |
|---|---|---|---|---|
| `llm_primary_provider` | `LLM_PRIMARY_PROVIDER` | *(new)* | `"openai"` | |
| `llm_primary_model` | `LLM_PRIMARY_MODEL` | `llama-3.3-70b-versatile` | `gpt-4o-mini` | follows primary provider |
| `llm_primary_timeout_s` | `LLM_PRIMARY_TIMEOUT_S` | `4.0` | `8.0` | OpenAI p99 TTFT can spike to 3-4 s |
| `llm_fallback_provider` | `LLM_FALLBACK_PROVIDER` | *(new)* | `"groq"` | |
| `llm_fallback_model` | `LLM_FALLBACK_MODEL` | `gpt-4o-mini` | `llama-3.3-70b-versatile` | follows fallback provider |
| `llm_fallback_timeout_s` | `LLM_FALLBACK_TIMEOUT_S` | `8.0` | `4.0` | Groq is fast even on free tier |

**`agent/metrics.py`**

- `groq_turns` → `primary_turns`
- `openai_turns` → `fallback_turns`
- `CALL END` log: `groq_used=N openai_used=M` → `primary_used=N fallback_used=M`

**`main.py`**

- Import from `llm.llm_client` (direct, not via shim).
- `_validate_llm_config(settings, provider_config)` — module-level function
  (importable in tests).  Raises `RuntimeError` on:
  - Unknown provider name
  - Same provider for both roles
  - Missing primary API key
  Called in lifespan before `LLMClient` is constructed.
- `/debug/config` now includes `llm_primary_provider`, `llm_primary_model`,
  `llm_primary_timeout_s`, `llm_fallback_provider`, `llm_fallback_model`,
  `llm_fallback_timeout_s`.

**7 import sites updated** to use `llm.llm_client` directly:
`main.py`, `agent/call_session.py`, `agent/pipeline.py`,
`telephony/plivo_handler.py`, `tests/test_chunker.py`,
`tests/test_llm_fallback_v2.py`, `tests/test_rate_limit_fallback.py`.

### `.env` changes to copy-paste

```
LLM_PRIMARY_PROVIDER=openai
LLM_PRIMARY_MODEL=gpt-4o-mini
LLM_PRIMARY_TIMEOUT_S=8
LLM_FALLBACK_PROVIDER=groq
LLM_FALLBACK_MODEL=llama-3.3-70b-versatile
LLM_FALLBACK_TIMEOUT_S=4
LLM_CIRCUIT_FAIL_THRESHOLD=2
LLM_CIRCUIT_COOLDOWN_S=120
```

### Non-breaking guarantees

- `from llm.groq_client import LLMClient` still works (shim re-exports).
- All existing tests continue to pass — attribute names in `_make_llm` helpers
  updated to `_primary` / `_fallback` / `_primary_cb`; internal logic identical.
- No change to the call flow, barge-in, TTS, or STT layers.

### New tests (`tests/test_provider_config.py`, 4 tests)

| Test | What it verifies |
|---|---|
| `test_provider_order_config_driven` | Default config: `_primary_name="openai"`, `_fallback_name="groq"`, aliases wired correctly |
| `test_provider_order_reversed` | `LLM_PRIMARY_PROVIDER=groq`: `_primary_name="groq"`, `_fallback_name="openai"` |
| `test_startup_fails_if_same_provider_for_primary_and_fallback` | `_validate_llm_config` raises `RuntimeError` when primary == fallback |
| `test_startup_fails_if_primary_api_key_missing` | `_validate_llm_config` raises `RuntimeError` when primary key absent |

Total test count: **42** (38 existing + 4 new). All pass.

---

## Phase 4 production fixes #2 (2026-05-01) — warmup, whitelist, timeline

### Fix 1 — First-turn cold start (Groq 1200 ms → ~400 ms)

**Root cause:** Groq's first call establishes a new TLS connection and HTTP/2
session to `api.groq.com`.  That round-trip adds ~700–800 ms on top of the
inference time, disappearing on subsequent calls once the connection is reused.

**Fix:** `_warmup_llm(llm)` in `main.py` fires a single non-streaming 1-token
completion against Groq immediately after `LLMClient` is constructed in the
lifespan startup, using `asyncio.create_task` (fire-and-forget — does not block
server startup).

New method `LLMClient.complete_once(model, messages, max_tokens)` in
`llm/groq_client.py` — non-streaming, response discarded, used only for warmup.
`asyncio.wait_for(..., timeout=5.0)` prevents a slow warmup from blocking the
event loop.  Failure is logged as WARNING and swallowed (non-fatal).

---

### Fix 2 — Single-word "sorry?" dropped by min_utterance_words filter

**Root cause:** `min_utterance_words=2` filtered ALL single-word utterances,
including "sorry?", "yes", "yeah" — words that carry clear intent and are
needed to trigger the repeat-question rule in the system prompt.

**Fix:** `_is_meaningful_short_utterance(text)` in `agent/call_session.py`.
Strips trailing punctuation, lowercases, checks against
`settings.short_utterance_whitelist_set()` before deciding to drop.  The check
is applied ONLY when `word_count < min_utterance_words` so multi-word utterances
are unaffected.

New `config.py` field `short_utterance_whitelist` (env: `SHORT_UTTERANCE_WHITELIST`,
comma-separated, default: `sorry,pardon,repeat,again,what,huh,yes,no,yeah,okay,ok,
sure,right,correct,wait,hold,stop`).

---

### Fix 3 — CALL TIMELINE showing negative ms values

**Root cause:** `t_first_tts_byte` and `t_first_audio_to_plivo` are set during
the **greeting** (before the user speaks), while `t_user_speech_end` is set when
the user first responds.  The old formula `llm_token→tts_byte = t_first_tts_byte
- t_first_llm_token` subtracted a turn-1 timestamp from a pre-call timestamp,
yielding values like `-38611ms`.

**Fix (option B):** The three broken cross-domain deltas (`speech_end→llm_token`,
`llm_token→tts_byte`, `speech_end→first_audio`) are removed from CALL TIMELINE
and replaced with per-turn averages computed from the `TurnMetrics` list.
Per-turn values are accumulated as `(perf_counter() - turn.start) * 1000` and
are always ≥ 0.  The CALL END line is unchanged.

New CALL TIMELINE format:
```
CALL TIMELINE  call=X  incoming→ws=50ms  ws→stt_partial=750ms  ws→speech_end=1450ms
  avg_llm_ttft=450ms  avg_tts_ttft=630ms  avg_e2e=950ms  [3 turn(s)]
```

### New tests (`tests/test_production_fixes.py`, 3 tests)

| Test | What it verifies |
|---|---|
| `test_warmup_runs_on_startup` | `_warmup_llm` calls `complete_once` exactly once |
| `test_short_utterance_whitelist` | "sorry?" → pipeline called; "yeah" → pipeline called; "um" → filtered |
| `test_call_timeline_no_negatives` | 3-turn call with greeting timestamps before user speech → no `-N ms` values |

Total test count: **38** (35 existing + 3 new). All pass.

---

## Phase 4 LLM fallback v2 (2026-05-01) — robust provider chain

### What changed

**`llm/groq_client.py`** — full rewrite

- **`_is_auth_error(exc)`** — new helper.  Returns `True` for
  `AuthenticationError`, `PermissionDeniedError`, and raw 400/401/403
  responses.  Auth errors raise immediately instead of falling back
  (switching providers cannot fix a bad API key).

- **3-state circuit breaker** (`_CircuitBreaker`)
  - States: `CLOSED → OPEN → HALF_OPEN → CLOSED`
  - `CLOSED → OPEN`: after `llm_circuit_fail_threshold` consecutive failures
    (default **2**, was 3 — lower threshold catches problems sooner).
  - `OPEN → HALF_OPEN`: after `llm_circuit_cooldown_s` seconds
    (default **120 s**, was 60 s — gives Groq enough time to recover).
  - `HALF_OPEN → CLOSED`: on first successful probe request.
  - `HALF_OPEN → OPEN`: on probe failure (restarts cooldown).
  - Eliminates yo-yo behaviour: the old 2-state breaker reset to fully
    CLOSED after cooldown, so if Groq was still rate-limited the breaker
    opened and closed on alternate calls.
  - `is_open()` kept as backwards-compat alias for existing tests.

- **Per-client timeouts** via `httpx.Timeout`:
  - Groq: `read=llm_primary_timeout_s` (default **4 s**)
  - OpenAI: `read=llm_fallback_timeout_s` (default **8 s**)
  - Both: `connect=2 s`, `write=2 s`, `pool=2 s`
  - Prevents a Groq hang from blocking the pipeline for up to 10 minutes
    (the AsyncOpenAI SDK default).

- **Mid-stream failure tracking** — `yielded` flag in `stream_sentences`:
  - Failure BEFORE first sentence → restart with ORIGINAL messages on
    OpenAI (partial Groq tokens live in a local buffer and are discarded).
  - Failure AFTER first sentence → stop cleanly (partial audio already
    in flight; restarting would cause duplicate/conflicting speech).

- **Graceful both-fail message** — if both providers fail before yielding,
  `"I'm having a technical issue, can you repeat that?"` is returned as a
  single sentence so the pipeline never sends silence.

- **Circuit breaker records failure for ALL APIErrors** (not just 429).
  Timeouts and connection errors also count against the threshold.

- **Per-call logging** — provider name, model, and elapsed ms logged at
  INFO on success and WARNING/ERROR on failure.

**`config.py`** — 7 new env-overridable fields:

| Field | Env var | Default | Reason |
|---|---|---|---|
| `llm_primary_model` | `LLM_PRIMARY_MODEL` | `llama-3.3-70b-versatile` | Env-overridable without code change |
| `llm_primary_timeout_s` | `LLM_PRIMARY_TIMEOUT_S` | `4.0` | Hard limit on Groq response time |
| `llm_fallback_model` | `LLM_FALLBACK_MODEL` | `gpt-4o-mini` | Cheapest capable OpenAI model; fast enough for voice |
| `llm_fallback_timeout_s` | `LLM_FALLBACK_TIMEOUT_S` | `8.0` | OpenAI is slightly slower; 8 s still < TTS buffer |
| `llm_circuit_fail_threshold` | `LLM_CIRCUIT_FAIL_THRESHOLD` | `2` | Open after 2 failures (old hardcoded: 3) |
| `llm_circuit_cooldown_s` | `LLM_CIRCUIT_COOLDOWN_S` | `120.0` | 2-min cooldown (old hardcoded: 60 s) |

**`agent/metrics.py`** — three new `CallMetrics` fields:
- `groq_turns: int` — turns where Groq succeeded
- `openai_turns: int` — turns where OpenAI succeeded  
- `fallbacks_triggered: int` — turns where a mid-call fallback was needed
- `CALL END` log line now includes `groq_used=N openai_used=M fallbacks_triggered=K`

**`agent/pipeline.py`** — `_llm_worker` now passes `call_metrics` to
`stream_sentences` so the counters above are populated.

**`main.py`** — `httpx.AsyncClient` created before `LLMClient`; the client
is passed as `LLMClient(http_client=...)` for clean dependency ordering.

### New tests (`tests/test_llm_fallback_v2.py`, 8 tests)

| Test | What it verifies |
|---|---|
| `test_primary_429_immediate_fallback` | 429 → 1 Groq call, 1 OpenAI call, sentence returned |
| `test_primary_timeout_fallback` | `APITimeoutError` triggers fallback |
| `test_circuit_opens_after_two_failures` | Default threshold=2; third call skips Groq |
| `test_circuit_half_open_after_cooldown` | OPEN → HALF_OPEN after cooldown; success → CLOSED |
| `test_mid_stream_failure_before_yield_uses_fallback` | 8 chars of Groq tokens (< 12 min), error, restart with original messages |
| `test_both_providers_fail_graceful_message` | Both fail → exactly one graceful message |
| `test_auth_error_does_not_fallback` | 401 raises, OpenAI never called |
| `test_streaming_contract_preserved` | Sentences yielded in order, not batched |

Total test count: **35** (27 existing + 8 new). All pass.

---

## Phase 4 URL routing fix (2026-05-01) — stale ngrok URL in /incoming-call response

### Root cause

`_build_xml()` (`main.py`) used `request.headers.get("host")` as the primary source for
the WebSocket hostname.  The `Host` header reflects whatever URL **Plivo** used to reach
the server, not the server's own configured identity.  When Plivo's call was set up with
the old ngrok `answer_url`, every `/incoming-call` request arrived with
`Host: crista-polar-bailee.ngrok-free.dev`, which is a non-empty string, so the
`or urlparse(settings.base_url).netloc` fallback was silently bypassed.
`settings.base_url` was correct all along — it just wasn't being used.

Diagnosis method: `python -c "from config import settings; print(settings.base_url)"` → cloudflare URL ✓.
`python -c "import os; print(os.environ.get('BASE_URL'))"` → `None` (no stale OS env var).
Root cause was purely the `Host`-header path in `_build_xml`.

### Fix (`main.py`)

`_build_xml` now derives the WebSocket URL exclusively from `settings.base_url`:

```python
parsed    = urlparse(settings.base_url)
ws_scheme = "wss" if parsed.scheme == "https" else "ws"
ws_url    = f"{ws_scheme}://{parsed.netloc}/media-stream"
```

The incoming `Host` header is logged for diagnostics but never used to construct URLs.
The fix also handles `http://` tunnels correctly (`ws://` instead of `wss://`).

### Startup hardening (`main.py`, `config.py`)

Three additions to catch this class of error at boot rather than at call time:

1. **Three-value boot log** — every startup emits:
   ```
   BOOT base_url: env=<OS env> settings=<resolved value> dotenv_path=<.env file path>
   ```
2. **Startup assertion** — if `settings.base_url` contains `"ngrok"` but the `.env` file
   does not, a `RuntimeError` is raised immediately with instructions to remove the stale
   OS variable (`Remove-Item Env:BASE_URL` / `unset BASE_URL`).
3. **`/debug/config` endpoint** — returns `base_url`, `os_BASE_URL`, `dotenv_path`, and
   key tuning values.  Disabled by default; enable with `DEBUG_MODE=true` in `.env`.

### Config (`config.py`)

- `debug_mode: bool = False` field added (env: `DEBUG_MODE`).

All 27 tests pass.

---

## Phase 4 production bug fixes (2026-05-01)

### Bug 1 — Barge-in cascade: same transcript spawned N pipelines (`agent/call_session.py`)

**Root cause:** `_on_transcript` called `asyncio.create_task(_do_barge_in(text))` on every
qualifying interim transcript.  Six interims in one second = six concurrent LLM calls.

**Fix:**
- State is flipped to `LISTENING` *synchronously* inside `_on_transcript`, before the async
  task is created.  Any subsequent transcript that arrives sees `LISTENING` state and goes
  through the normal endpoint-buffer path — it can never re-enter the SPEAKING branch.
- `_do_barge_in` removed.  Replaced by `_handle_barge_in_cancel` which drains the cancelled
  pipeline, sends `clearAudio`, then appends the barge-in text to `_utterance_buffer` and
  restarts `_endpoint_timer` — identical to the normal LISTENING path.  This guarantees a
  single pipeline per silence window regardless of how many transcripts arrive.
- Dedupe guard in `_handle_user_turn`: if the same text triggers a pipeline within 500 ms,
  the second trigger is silently dropped.

### Bug 2 — Self-echo: agent transcribed its own audio (`agent/call_session.py`, `config.py`)

**Fix:**
- **Acoustic tail mute:** 300 ms after the agent finishes speaking (`_say` / `_run_pipeline`
  finally blocks set `_post_speech_mute_until`), low-confidence STT transcripts are dropped.
  High-confidence (≥ `barge_in_threshold`) transcripts still pass through so genuine
  interruptions are not lost.
- **Phrase filter:** `_is_system_phrase(text)` checks against `settings.stt_drop_phrases`
  (comma-separated substrings, matched case-insensitively).  Matches are dropped at `DEBUG`
  level before any state machine logic runs.
- New config field `stt_drop_phrases` (env: `STT_DROP_PHRASES`).  Defaults cover common
  IVR / hold-music text: "please hold", "please stay on the line", etc.

### Bug 3 — Groq 429, no fallback activation (`llm/groq_client.py`, `agent/fallback.py`)

**Fix:**
- `max_retries=0` on both `AsyncOpenAI` instances — disables the SDK's built-in retry loop.
- `RateLimitError` caught *before* the generic `APIError` handler; immediately falls back to
  OpenAI without retrying Groq.
- **Circuit breaker** (`_CircuitBreaker`): after 3 consecutive 429s the breaker opens and
  routes 100 % of requests directly to OpenAI for 60 s before retrying Groq.
- ElevenLabs 429 (`agent/fallback.py`): already fell back via `httpx.HTTPStatusError`; now
  logs `WARNING "ElevenLabs 429 rate-limited"` specifically.

### Bug 4 — Endpoint timer bypassed in barge-in path

Covered by Bug 1 unification.  All paths to `_handle_user_turn` now go through
`_endpoint_timer`, including barge-in.

### Bug 5 — Hardcoded ngrok URL appeared in `/incoming-call` response (`config.py`, `main.py`)

**Grep result:** only two references to "ngrok" — a comment in `.env` and the `base_url`
default in `config.py`.  Both harmless except the default.

**Fix:**
- `base_url` default changed from `"https://your-tunnel.ngrok.io"` to `""`.
- `model_post_init` emits a `warnings.warn` if `base_url` is empty at startup.
- `main.py` lifespan logs `BASE_URL active: <value>` so the active URL is always visible
  in the startup log.

### New tests (5 added, total: **27**)

| Test file | Tests | What they verify |
|---|---|---|
| `test_barge_in.py` | 7 (+1) | Barge-in dedupe: 6 identical transcripts → 1 pipeline |
| `test_self_echo_filter.py` | 2 (new) | System phrase dropped; normal transcript passes |
| `test_rate_limit_fallback.py` | 2 (new) | 429 → immediate OpenAI fallback; circuit breaker opens after 3 failures |

All 27 tests pass.

---

---

## Phase 4 tuning (2026-05-01) — latency + repetition fixes

### Fix 1A — Deepgram endpointing (`config.py`)

`dg_endpointing_ms` raised from 300 → **1200 ms**: Deepgram waits longer
before declaring `speech_final`, preventing premature interruption while the
candidate is still speaking.

`dg_utterance_end_ms` raised from 1200 → **1500 ms**: `UtteranceEnd` event
fires later, giving further protection on slower speakers.

Both values are runtime-configurable via `DG_ENDPOINTING_MS` and
`DG_UTTERANCE_END_MS` env vars.

### Fix 1B — Client-side endpoint buffer+timer (`agent/call_session.py`)

An `asyncio.Task` endpoint timer is reset on every `is_final` STT event.
Only when the timer expires (after `endpoint_ms = 1200 ms` of silence) does
`_handle_user_turn()` flush the buffered transcripts and start a pipeline.
Utterances under `min_utterance_words = 2` are silently dropped.

This prevents a burst of rapid `is_final` events from firing multiple
pipeline turns, and stops filler words ("um", "uh") from triggering a
response.

New `config.py` fields: `endpoint_ms` (env: `ENDPOINT_MS`),
`min_utterance_words` (env: `MIN_UTTERANCE_WORDS`).

Barge-in and silence watchdog cancel the endpoint timer immediately so stale
buffered text is never replayed in the next turn.

### Fix 2 — Repeat-question handling (`config.py`)

`_CONVERSATION_RULES` appended to the system prompt at startup:

- If the candidate says "sorry", "pardon", "could you repeat", etc., the
  agent immediately repeats its previous question — rephrased more simply —
  without advancing.
- Two consecutive repeat requests → break the question into smaller parts.
- Agent tracks which questions it has already asked.
- Agent waits for the candidate to finish; pauses do not trigger an
  interruption.

### New tests

**`tests/test_endpoint_timer.py`** (2 tests)  
- `test_two_finals_within_window_produce_one_turn` — two `is_final` events
  100 ms apart with a 200 ms timer produce exactly one `_run_pipeline` call
  with the combined text.  
- `test_one_word_utterance_does_not_trigger_turn` — single-word `is_final`
  ("um") does not start a pipeline turn.

Total test count: **22** (20 existing + 2 new). All pass.

---

---

## Phase 4 hotfix (2026-05-01) — live call production fixes

### Bug fixes

**Bug B fixed — `tts/elevenlabs_tts.py`**  
Added `optimize_streaming_latency=3` to ElevenLabs streaming params.
Reduces time-to-first-byte by ~200 ms by disabling server-side text
buffering.

### Dead code removed

**`main.py`** — `/audio/{audio_id}` endpoint and `tts.audio_cache` import
removed.  The endpoint was a Phase 3 artefact (REST Play + URL fetch path).
Phase 4 sends audio directly over the Plivo WebSocket; the cache is never
written.  Confirmed `dashboard.py` does not reference the endpoint.

### Latency instrumentation

Seven stage timestamps are now recorded and logged:

| Timestamp | Where set | What it marks |
|---|---|---|
| `t_incoming_call` | `main.py` `/incoming-call` handler | Plivo answer webhook fires |
| `t_ws_connected` | `CallSession.__init__` | WebSocket accepted, session created |
| `t_first_stt_partial` | `CallSession._on_transcript` | First any STT transcript (interim or final) |
| `t_user_speech_end` | `CallSession._on_transcript` | First `is_final=True` STT result |
| `t_first_llm_token` → `llm_ttft_ms` | `pipeline._llm_worker` | First LLM token delta |
| `t_first_tts_byte` → `tts_ttft_ms` | `pipeline._tts_worker` | First byte from TTS |
| `t_first_audio_to_plivo` → `e2e_first_audio_ms` | `pipeline._ws_sender` | First `playAudio` WS frame sent |

`CallMetrics.log_summary()` now emits a `CALL TIMELINE` log line with
`incoming→ws`, `ws→first_stt_partial`, and `ws→user_speech_end` intervals.

### New test

**`tests/test_first_audio_latency.py`** (2 tests)  
- `test_first_audio_within_1500ms` — asserts first `playAudio` frame arrives
  within 1500 ms of `pipeline.run()` with a 50 ms mock TTS delay.  
- `test_play_audio_json_shape` — asserts exact Plivo spec shape:
  `{"event": "playAudio", "media": {"contentType": "audio/x-mulaw",
  "sampleRate": 8000, "payload": "<base64>"}}`.

Total test count: **20** (18 existing + 2 new). All pass.

### Confirmed not bugs

- `sampleRate: 8000` (integer) — verified against Plivo bidirectional
  streaming spec.  Integer is correct; no change needed.
- `_MULAW_FRAME = 160` bytes (20 ms) — correct for 8kHz μ-law; not changed.

---

# CHANGES — Phase 3 → Phase 4 refactor

## Overview

Phase 3 established singleton clients and ElevenLabs streaming via REST Play.
Phase 4 replaces the REST-Play audio path with direct WebSocket μ-law streaming,
adds per-sentence TTS concurrency, barge-in, provider fallback, latency metrics,
crash isolation, graceful shutdown, and a full test suite.

---

## New files

### `agent/metrics.py`
`TurnMetrics` dataclass records `llm_ttft_ms`, `tts_ttft_ms`,
`e2e_first_audio_ms` per turn using `time.perf_counter()`.
`CallMetrics` aggregates turns and logs a summary at call end.

### `agent/fallback.py`
`with_fallback(primary, fallback)` — generic async call wrapper.
`tts_with_fallback(text, http)` — async generator that streams ElevenLabs
μ-law; switches to Deepgram on timeout/HTTP error *before* the first chunk.

### `agent/pipeline.py`
`StreamingPipeline` — three asyncio tasks connected by `asyncio.Queue`:
- `_llm_worker`: streams sentences from Groq into `sentence_q`
- `_tts_worker`: calls TTS per sentence, pushes μ-law chunks into `audio_q`
- `_ws_sender`: base64-encodes chunks, sends `playAudio` WebSocket events

Cancellation propagates naturally: cancelling the task returned by `run()`
raises `CancelledError` into `asyncio.gather()`, which cancels all workers.
Each worker's `finally` block puts a `None` sentinel so downstream stages
drain cleanly.

### `agent/session_registry.py`
`WeakValueDictionary` keyed by `call_sid`.  Lifespan iterates it to drain
active calls on shutdown.  No manual `unregister()` required on GC.

### `tts/deepgram_tts.py` (recreated)
Deepgram Aura TTS — streams raw μ-law 8kHz (`encoding=ulaw`, `sample_rate=8000`,
`container=none`).  Used exclusively as TTS fallback via `agent/fallback.py`.

### `tests/__init__.py`, `tests/test_chunker.py`, `tests/test_barge_in.py`
18 tests covering sentence splitting (12 unit tests) and barge-in behaviour
(6 integration tests with mocked providers).

---

## Modified files

### `config.py`
Added: `barge_in_threshold` (float, default `0.85`),
`sentence_delimiters` (str, default `".!?"`).

### `tts/elevenlabs_tts.py`
Replaced streaming MP3 with streaming **μ-law 8kHz** (`output_format=ulaw_8000`).
Yields 160-byte frames (20 ms each) — Plivo-ready with no conversion step.
Removed `synthesize()` (WAV fallback) — no longer needed.

### `stt/deepgram_client.py`
Callback signature changed:
`on_transcript(text, is_final)` → `on_transcript(text, is_final, confidence)`.
`confidence` extracted from `alternatives[0].confidence` and forwarded to
`CallSession._on_transcript()` for barge-in threshold checks.

### `llm/groq_client.py`
`_split_sentence` now accepts an explicit `ends: frozenset` parameter
(computed from `settings.sentence_delimiters` once per stream call).
`_SENTENCE_ENDS` module constant removed.

### `agent/call_session.py`
- Audio gate changed: blocks only during `PROCESSING` (LLM running).
  `SPEAKING` forwards audio to STT for barge-in detection.
- `_on_transcript` handles barge-in: calls `_do_barge_in()` when
  `is_final` + ≥2 words, or interim confidence ≥ `barge_in_threshold`.
- `_do_barge_in()`: cancels current task, sends `clearAudio` to WebSocket,
  starts new pipeline task.
- `_run_pipeline()`: delegates to `StreamingPipeline.run()`, waits
  `(audio_duration - elapsed + _PLIVO_BUFFER)` seconds, logs `TurnMetrics`.
  Catches all non-`CancelledError` exceptions (crash isolation).
- `_say()`: streams TTS directly over WebSocket (no REST Play, no cache).
- `start()` registers session in `session_registry`; runs as background task
  (launched via `asyncio.create_task` in handler — not awaited).
- `close()` cancels current task, calls `stt.close()`, logs `CallMetrics`.

### `telephony/plivo_handler.py`
`session.start()` is now `asyncio.create_task(session.start())`.
The WebSocket event loop no longer blocks during greeting synthesis.

### `telephony/plivo_rest.py`
`play()` and `stop_play()` retained for compatibility; not called in normal
call flow.  `hangup()` remains active (used by silence watchdog).

### `main.py`
- `lifespan`: creates singleton `LLMClient`, `PlivoRestClient`,
  `httpx.AsyncClient`; drains `all_sessions()` on shutdown with 10 s timeout.
- SIGTERM handler installed via `signal.signal` (cross-platform).
- `/media-stream` WebSocket handler wrapped in top-level `try/except`
  (crash isolation — one bad call cannot kill the server).
- `/audio/{audio_id}` kept as legacy endpoint (returns 404 for streaming IDs).

### `requirements.txt`
Added `pytest>=8.0.0` and `pytest-asyncio>=0.24.0`.

---

## Removed / simplified

| Item | Reason |
|---|---|
| `tts/audio_cache.py` streaming queue | Audio sent directly over WebSocket; cache only used for legacy `/audio/{id}` |
| `_PLIVO_BUFFER = 1.2 s` (Phase 3) | Reduced to `0.4 s` — WebSocket audio has lower latency than REST Play fetch |
| `_say()` REST Play path | Replaced by direct WebSocket `playAudio` streaming |
| `tts/elevenlabs_tts.py stream_synthesize()` | Replaced by per-sentence `stream_sentence_mulaw()` |
