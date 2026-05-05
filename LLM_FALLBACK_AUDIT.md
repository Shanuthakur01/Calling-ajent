# LLM_FALLBACK_AUDIT.md — Current LLM fallback strategy

Generated: 2026-05-01

---

## 1. Primary model

| Field | Value |
|---|---|
| Provider | Groq |
| Model | `llama-3.3-70b-versatile` |
| Configured in | `config.py:59` (`groq_model: str = "llama-3.3-70b-versatile"`) |
| Client file | `llm/groq_client.py` |
| `max_retries` | `0` ✓ |
| Per-call timeout | **NOT SET** — `AsyncOpenAI` uses its SDK default (~600s) |

No `httpx.Timeout` is passed to the `AsyncOpenAI` constructor.  A Groq hang will
block the pipeline for up to 10 minutes before any exception fires.

---

## 2. Fallback model

| Field | Value |
|---|---|
| Provider | OpenAI |
| Model | `"gpt-4o-mini"` (hardcoded string in `groq_client.py:80`) |
| Configured in | Not in `config.py` — no env-overridable field |
| Client file | `llm/groq_client.py` (instantiated inside `LLMClient.__init__`) |
| `max_retries` | `0` ✓ |
| Per-call timeout | **NOT SET** |
| Separate file | **`llm/openai_client.py` does not exist** — OpenAI client lives inside `LLMClient` |

---

## 3. Circuit breaker

Class `_CircuitBreaker` in `llm/groq_client.py:24-47`.

| Parameter | Current value | Source |
|---|---|---|
| States | **CLOSED / OPEN only** — no HALF_OPEN | `groq_client.py` |
| Open threshold | 3 consecutive `RateLimitError` (429) only | `groq_client.py:27` |
| Cooldown | 60 s | `groq_client.py:27` |
| Config fields in `.env` | **None** — threshold and cooldown are hardcoded | — |

**Missing:** The HALF_OPEN state.  After 60 s the breaker resets to fully CLOSED
(`_failures=0`, `_open_until=0`), meaning the very next call retries Groq normally.
If Groq is still rate-limited at that moment, it opens again immediately —
yo-yo behaviour.

---

## 4. Error types that trigger fallback

| Error | Triggers fallback? | Notes |
|---|---|---|
| `openai.RateLimitError` (429) | ✓ Yes | Records circuit breaker failure |
| `openai.APIError` (all other) | ✓ Yes | **Does NOT record circuit breaker failure** |
| `openai.APITimeoutError` | ✓ Yes (subclass of `APIError`) | Not explicitly caught |
| `openai.APIConnectionError` | ✓ Yes (subclass of `APIError`) | Not explicitly caught |
| HTTP 400 / 401 / 403 | ✓ Yes — **WRONG** | Auth/config errors must NOT fall back |
| `httpx.TimeoutException` | ✗ No | Not in any except clause |
| `asyncio.TimeoutError` | ✗ No | Not in any except clause |
| Mid-stream failure (after 1+ sentences yielded) | ✗ **No — call crashes** | If Groq fails after yielding sentence 1, `_llm_worker` logs the error and puts a sentinel on the queue. The partial response is used. No restart from fallback. |

---

## 5. SDK retries

Both `AsyncOpenAI` instances use `max_retries=0` ✓.  However, the OpenAI SDK's
default connection timeout (~600 s) still applies because no `http_client` or
`timeout` is passed.

---

## 6. Call-site in pipeline.py

```python
# agent/pipeline.py:98
async for sentence in self._llm.stream_sentences(history):
```

`stream_sentences` is consumed as a plain async generator — no wrapping timeout,
no asyncio.wait_for.  If Groq hangs, the pipeline hangs.

---

## 7. Logging gaps

- No per-call log of which provider was attempted.
- No per-call log of total LLM time.
- No call-end summary with `groq_used=N openai_used=M fallbacks_triggered=K`.
- `CALL TIMELINE` log at call end has `[llm_ttft]` but no provider attribution.

---

## 8. Both-providers-fail behaviour

If `use_fallback=True` and OpenAI also fails, the exception propagates up to
`_llm_worker`, which catches it with `except Exception as exc:`, logs it, and
puts `_SENTINEL` on the queue.  The pipeline sends zero audio for that turn.
The candidate hears silence, not a graceful "technical issue" message.

---

## 9. Config fields present vs required

| `.env` variable | In `config.py`? | In `.env`? | Required by spec |
|---|---|---|---|
| `GROQ_API_KEY` | ✓ | ✓ | ✓ |
| `OPENAI_API_KEY` | ✓ (optional) | ✓ | ✓ |
| `LLM_PROVIDER_CHAIN` | ✗ | ✗ | Required |
| `LLM_PRIMARY_MODEL` | partial (`groq_model`) | ✗ | Required |
| `LLM_PRIMARY_TIMEOUT_S` | ✗ | ✗ | Required |
| `LLM_FALLBACK_MODEL` | ✗ hardcoded | ✗ | Required |
| `LLM_FALLBACK_TIMEOUT_S` | ✗ | ✗ | Required |
| `LLM_CIRCUIT_FAIL_THRESHOLD` | ✗ hardcoded as 3 | ✗ | Required |
| `LLM_CIRCUIT_COOLDOWN_S` | ✗ hardcoded as 60 | ✗ | Required |

---

## 10. Summary — gaps vs spec

| Gap | Severity |
|---|---|
| No per-call timeout on either client | **Critical** — hangs block pipeline |
| No HALF_OPEN state in circuit breaker | High — yo-yo opens after cooldown |
| 401/403 incorrectly triggers fallback | High — wrong provider won't fix auth errors |
| No mid-stream failure → fallback restart | High — partial responses on Groq dropout |
| Circuit only opens on 429, not on timeout/connect errors | High |
| No graceful "technical issue" response when both fail | High — caller hears silence |
| Threshold hardcoded at 3 (spec: 2) | Medium |
| Cooldown hardcoded at 60 s (spec: 120 s) | Medium |
| Fallback model not in config.py | Medium |
| No call-end groq_used/openai_used/fallbacks_triggered stats | Low |
