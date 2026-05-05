# CHAIN_FLIP_AUDIT.md — Provider order flip: OpenAI primary, Groq fallback

Generated: 2026-05-02

---

## 1. Where is the provider order encoded?

**Short answer: hardcoded in `llm/groq_client.py`, not config-driven.**

`LLMClient.__init__` (`llm/groq_client.py:136-167`) constructs two fixed client objects:

```python
self._groq   = AsyncOpenAI(api_key=settings.groq_api_key,
                           base_url="https://api.groq.com/openai/v1", ...)   # ← always primary
self._openai = AsyncOpenAI(api_key=settings.openai_api_key, ...)              # ← always fallback
```

The dispatch function (`stream_sentences`, line 238) picks Groq by checking a
Groq-named circuit breaker:

```python
use_groq = not self._groq_cb.should_skip()   # line 238
```

`complete_once` (warmup, line 177) also hardcodes `self._groq`.

Config has `llm_primary_model` / `llm_fallback_model` (models only) but **no
`LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` fields** to select which API
endpoint is primary. Flipping currently requires code changes, not env changes.

---

## 2. Renaming: groq_client.py → llm_client.py

The class inside the file is already `LLMClient` (provider-agnostic ✓).
The filename `groq_client.py` implies Groq-specific and must change.

**Plan:**
- Rename `llm/groq_client.py` → `llm/llm_client.py`
- Update all 7 import sites (listed in §3 below)
- The old filename disappears entirely (no shim needed — tests will be updated
  to use the new import path as required by the spec)

**Import sites to update:**

| File | Current import |
|---|---|
| `main.py:42` | `from llm.groq_client import LLMClient` |
| `agent/call_session.py:45` | `from llm.groq_client import LLMClient` |
| `agent/pipeline.py:33` | `from llm.groq_client import LLMClient` |
| `telephony/plivo_handler.py:28` | `from llm.groq_client import LLMClient` |
| `tests/test_chunker.py:3` | `from llm.groq_client import _split_sentence` |
| `tests/test_llm_fallback_v2.py:65,65,167` | `from llm.groq_client import LLMClient, _CircuitBreaker` / `patch("llm.groq_client.time")` |
| `tests/test_rate_limit_fallback.py:34,70` | `from llm.groq_client import LLMClient, _CircuitBreaker` |

---

## 3. Every "groq as primary" reference that must change

### `llm/groq_client.py` (to become `llm/llm_client.py`)

| Line | Current | Change to |
|---|---|---|
| 2 | `# Streaming LLM client: Groq (primary) with OpenAI fallback.` | `# … primary/fallback determined by LLM_PRIMARY_PROVIDER` |
| 6 | `1. Groq  (llm_primary_model …)` | `1. Primary provider  (LLM_PRIMARY_PROVIDER, LLM_PRIMARY_MODEL)` |
| 71 | `_CircuitBreaker` docstring: "for the Groq LLM client" | "for the primary LLM provider" |
| 92 | `should_skip`: "Return True if Groq should be bypassed" | "Return True if primary provider should be bypassed" |
| 98 | log `"Groq circuit breaker → HALF_OPEN"` | `"{primary} circuit breaker → HALF_OPEN"` |
| 112 | log `"Groq circuit breaker → OPEN (HALF_OPEN probe failed)"` | `"{primary} circuit breaker → OPEN …"` |
| 119 | log `"Groq circuit breaker OPEN — routing all requests to fallback"` | `"{primary} circuit breaker OPEN …"` |
| 125 | log `"Groq circuit breaker → CLOSED"` | `"{primary} circuit breaker → CLOSED"` |
| 136-148 | `self._groq = AsyncOpenAI(api_key=settings.groq_api_key, base_url=GROQ_URL, …)` hardcoded | `self._primary = _build_client(settings.llm_primary_provider, settings.llm_primary_timeout_s)` |
| 164 | `self._groq_cb = _CircuitBreaker(…)` | `self._primary_cb = _CircuitBreaker(…)` |
| 177 | `complete_once` calls `self._groq.chat.completions.create(…)` | `self._primary.chat.completions.create(…)` |
| 238 | `use_groq = not self._groq_cb.should_skip()` | `use_primary = not self._primary_cb.should_skip()` |
| 240 | comment `# ── Groq (primary)` | `# ── Primary provider` |
| 246 | `self._groq, settings.llm_primary_model` | `self._primary, settings.llm_primary_model` |
| 254 | log `"LLM groq ok  model=%s"` | `"LLM {primary} ok  model=%s"` |
| 257 | `self._groq_cb.record_success()` | `self._primary_cb.record_success()` |
| 259 | `call_metrics.groq_turns += 1` | `call_metrics.primary_turns += 1` |
| 266 | log `"Groq auth error — not falling back"` | `"{primary} auth error — not falling back"` |
| 269 | `self._groq_cb.record_failure()` | `self._primary_cb.record_failure()` |
| 273 | log `"Groq mid-stream failure after yield"` | `"{primary} mid-stream failure after yield"` |
| 279 | log `"Groq %s before yield (%.0fms) — falling back to OpenAI"` | `"{primary} %s before yield (%.0fms) — falling back to {fallback}"` |
| 286 | log `"Groq circuit breaker %s — using OpenAI fallback directly"` | `"{primary} circuit breaker %s — using {fallback} fallback directly"` |

### `main.py`

| Line | Current | Change to |
|---|---|---|
| 14 | `app.state.llm  — LLMClient  (Groq + OpenAI, shared connection pools)` | `(primary + fallback, provider chain config-driven)` |
| 58 | `_warmup_llm` docstring: "Fire one cheap non-streaming Groq completion" | "… primary provider completion" |

### `agent/metrics.py`

| Line | Current | Change to |
|---|---|---|
| 44 | `groq_turns: int = 0  # turns where Groq succeeded` | `primary_turns: int = 0  # turns where primary provider succeeded` |
| 45 | `openai_turns: int = 0  # turns where OpenAI succeeded` | `fallback_turns: int = 0  # turns where fallback provider succeeded` |
| 92 | log `groq_used=%d  openai_used=%d` | `primary_used=%d  fallback_used=%d` |
| 94 | `self.groq_turns, self.openai_turns` | `self.primary_turns, self.fallback_turns` |

### `config.py`

| Line | Current | Change to |
|---|---|---|
| 43 | `# Groq (primary LLM)` | `# Groq (LLM — role determined by LLM_PRIMARY_PROVIDER)` |
| 58 | `# Groq tuning (legacy alias …)` | keep but note it's now fallback default |

---

## 4. Every "openai as fallback" reference that must change

### `llm/groq_client.py`

| Line | Current | Change to |
|---|---|---|
| 12 | `2. OpenAI  (llm_fallback_model …)` | `2. Fallback provider  (LLM_FALLBACK_PROVIDER, LLM_FALLBACK_MODEL)` |
| 150-163 | `self._openai = AsyncOpenAI(api_key=settings.openai_api_key, …)` | `self._fallback = _build_client(settings.llm_fallback_provider, settings.llm_fallback_timeout_s)` |
| 279 | log `"falling back to OpenAI"` | `"falling back to {fallback}"` |
| 286 | log `"using OpenAI fallback directly"` | `"using {fallback} fallback directly"` |
| 290 | comment `# ── OpenAI (fallback)` | `# ── Fallback provider` |
| 291-296 | `self._openai is None` | `self._fallback is None` |
| 303 | `self._openai, settings.llm_fallback_model` | `self._fallback, settings.llm_fallback_model` |
| 311 | log `"LLM openai ok  model=%s"` | `"LLM {fallback} ok  model=%s"` |
| 315 | `call_metrics.openai_turns += 1` | `call_metrics.fallback_turns += 1` |
| 323 | log `"OpenAI mid-stream failure after yield"` | `"{fallback} mid-stream failure after yield"` |
| 330 | log `"OpenAI auth error"` | `"{fallback} auth error"` |

### `config.py`

| Line | Current | Change to |
|---|---|---|
| 44 | `# OpenAI (fallback LLM)` | `# OpenAI (LLM — role determined by LLM_PRIMARY_PROVIDER)` |
| 46 | comment on `openai_api_key` | add note: now serves as primary key when `LLM_PRIMARY_PROVIDER=openai` |

---

## 5. Timeout appropriateness after flip

| Setting | Old value | Old role | New value | New role | Appropriate? |
|---|---|---|---|---|---|
| `LLM_PRIMARY_TIMEOUT_S` | 4.0 s | Groq primary (fast, dedicated tier) | **8.0 s** | OpenAI primary (gpt-4o-mini p50 TTFT ~300-500 ms, p99 can spike to 3-4 s) | ✓ 8 s is safe margin |
| `LLM_FALLBACK_TIMEOUT_S` | 8.0 s | OpenAI fallback | **4.0 s** | Groq fallback (free tier, may be slow but 4 s still sufficient; fast at off-peak) | ✓ acceptable for fallback |

**Config default changes required:**
- `llm_primary_timeout_s: float = 4.0` → **`8.0`**
- `llm_fallback_timeout_s: float = 8.0` → **`4.0`**

These are code-default changes; the `.env` overrides in the spec (`LLM_PRIMARY_TIMEOUT_S=8`, `LLM_FALLBACK_TIMEOUT_S=4`) will match and document the intent.

---

## 6. New config fields required

Two new fields needed in `config.py` to make provider order config-driven:

```python
llm_primary_provider: str = "openai"   # env: LLM_PRIMARY_PROVIDER  ("openai" | "groq")
llm_fallback_provider: str = "groq"    # env: LLM_FALLBACK_PROVIDER  ("groq" | "openai")
```

The `.env` block to add (as provided by user):
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

---

## 7. Circuit breaker changes

Currently: one `_CircuitBreaker` on `self._groq_cb` — only the primary has a CB.
Spec requires: two `_CircuitBreaker` instances keyed by provider name.

New structure:
```python
self._primary_cb  = _CircuitBreaker(threshold=…, cooldown=…)
self._fallback_cb = _CircuitBreaker(threshold=…, cooldown=…)
```

Dispatch logic uses only `self._primary_cb.should_skip()` to decide whether to
attempt primary.  `self._fallback_cb` is tracked for observability (record_failure
on fallback errors) but does not gate routing (there is no third provider to fall
back to).  The CB docstring "for the Groq LLM client" → "for an LLM provider".

---

## 8. Backwards-compat constraints

- `tests/test_rate_limit_fallback.py` sets `llm._groq_cb = _CircuitBreaker(…)` and
  checks `llm._groq_cb.is_open()`.  After rename to `_primary_cb`, these tests must
  be updated (allowed by spec: "Update existing tests … don't hardcode groq/openai").
- `tests/test_llm_fallback_v2.py` uses `patch("llm.groq_client.time")` — must
  change to `patch("llm.llm_client.time")` after file rename.
- `_split_sentence` stays in `llm_client.py`; test import path updates accordingly.

---

## 9. Summary of changes required

| File | Change type |
|---|---|
| `llm/groq_client.py` → **`llm/llm_client.py`** | Full rewrite: provider-agnostic dispatch, rename attrs, update logs |
| `config.py` | Add `llm_primary_provider`, `llm_fallback_provider`; flip `llm_primary_timeout_s`/`llm_fallback_timeout_s` defaults |
| `agent/metrics.py` | Rename `groq_turns` → `primary_turns`, `openai_turns` → `fallback_turns`; update CALL END log |
| `main.py` | Update import, update `_warmup_llm` docstring and to call `self._primary` |
| `agent/call_session.py` | Update import path only |
| `agent/pipeline.py` | Update import path only |
| `telephony/plivo_handler.py` | Update import path only |
| `tests/test_chunker.py` | Update import path |
| `tests/test_llm_fallback_v2.py` | Update import path + patch path + remove groq/openai hardcoding |
| `tests/test_rate_limit_fallback.py` | Update import path + `_groq_cb` → `_primary_cb` |
| `tests/test_production_fixes.py` | No changes needed (uses `main._warmup_llm` indirectly) |
| `.env.example` | Add new LLM chain vars |
| `CHANGES.md` | Document rationale |
| `README.md` | Update LLM section to show chain is config-driven |
