# URL_BUG_AUDIT.md — BASE_URL stale ngrok URL investigation

Generated: 2026-05-01

---

## Check 1 — All Python files that read BASE_URL / base_url

Application code only (venv excluded):

| File | Line | Usage |
|---|---|---|
| `config.py:51` | `base_url: str = ""` | Field definition (default empty) |
| `config.py:103-109` | `self.base_url.endswith("/")` | Trailing-slash strip in model_post_init |
| `main.py:67` | `settings.base_url` | Startup log |
| `main.py:127` | `f"{settings.base_url}/incoming-call"` | answer_url for outbound call |
| `main.py:145` | `request.headers.get("host") or urlparse(settings.base_url).netloc` | **WebSocket URL construction — ROOT CAUSE** |

---

## Check 2 — How Settings loads BASE_URL

```python
# config.py
class Settings(BaseSettings):
    base_url: str = ""
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

Pydantic-Settings priority (highest → lowest):
1. OS environment variables
2. `.env` file
3. Field default (`""`)

No `load_dotenv()` called separately — Pydantic handles it.

---

## Check 3 — The /incoming-call handler in full

```python
# main.py:144-167
def _build_xml(request: Request) -> Response:
    host   = request.headers.get("host") or urlparse(settings.base_url).netloc
    ws_url = f"wss://{host}/media-stream"
    xml    = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Stream bidirectional="true" keepCallAlive="true"'
        f' contentType="audio/x-mulaw;rate=8000">{ws_url}</Stream>'
        "</Response>"
    )
    logger.info("Answer XML [%s]: %s", request.method, xml)
    return Response(content=xml, media_type="text/xml")

@app.post("/incoming-call", response_class=Response)
async def incoming_call_post(request: Request) -> Response:
    logger.info("t_incoming_call=%.6f", time.perf_counter())
    return _build_xml(request)
```

**The `Host` header on line 145 is the bug.** When Plivo receives an answer_url that pointed
to `https://crista-polar-bailee.ngrok-free.dev/incoming-call`, it sends the HTTP request with
`Host: crista-polar-bailee.ngrok-free.dev`. That header is non-empty, so the `or
urlparse(settings.base_url).netloc` fallback NEVER fires. The WebSocket URL is built from
the stale hostname, not from `settings.base_url`.

---

## Check 4 — OS environment for stale BASE_URL

```
OS BASE_URL = None
```

**Result: CLEAN.** No stale OS env var. Not Fix A.

---

## Check 5 — What settings.base_url actually loads at runtime

```
Settings.base_url = 'https://cardiovascular-forth-stakeholders-hollow.trycloudflare.com'
```

**Result: CORRECT.** Pydantic reads `.env` correctly. `settings.base_url` is right.

---

## Check 6 — Module-scope reads of settings.base_url

- `settings` object created at module level (`settings = Settings()` in config.py),
  **but** `settings.base_url` is read inside `_build_xml()` per-request — not cached at
  module scope. The value returned per-request is correct (cloudflare URL).
- **Therefore:** the bug is NOT a stale module-level import. `settings.base_url` is always
  correct when queried.

---

## Check 7 — Multiple .env files

```
(no output — only one .env file exists)
```

**Result:** Single `.env` at project root. No shadowing by a second file.

---

## Check 8 — Pydantic Settings priority

Pydantic-Settings gives OS env vars higher priority than `.env`. Since `OS BASE_URL = None`
(Check 4), `.env` wins cleanly. Priority is not the issue.

---

## Root Cause — Confirmed

**File:** `main.py`, line 145
**Code:** `host = request.headers.get("host") or urlparse(settings.base_url).netloc`

The `Host` HTTP header reflects the hostname the **caller (Plivo)** used to reach the server,
not the server's own configured identity. When Plivo was configured with the old ngrok
`answer_url`, it called `/incoming-call` with `Host: crista-polar-bailee.ngrok-free.dev`.
That string is truthy, so `urlparse(settings.base_url).netloc` (the correct cloudflare host)
is never reached.

`settings.base_url` is always correct. The code just ignores it whenever a `Host` header
is present.

---

## Recommended Fix — Type B

Always derive the WebSocket URL from `settings.base_url`; remove the `Host`-header branch entirely:

```python
def _build_xml(_request: Request) -> Response:
    parsed    = urlparse(settings.base_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url    = f"{ws_scheme}://{parsed.netloc}/media-stream"
    ...
```

`settings.base_url` is already read per-call (inside the function), so there is no
module-scope caching issue. Removing the `Host` header branch makes the WebSocket URL
100 % determined by `.env → settings.base_url`.

---

## Summary Table

| Check | Result | Issue? |
|---|---|---|
| Grep for BASE_URL in *.py | Only app code refs; no hardcoded URL | No |
| settings load method | Pydantic env_file=".env" | No |
| /incoming-call handler | Uses `Host` header before `settings.base_url` | **YES — ROOT CAUSE** |
| OS env BASE_URL | `None` | No |
| settings.base_url at runtime | Correct cloudflare URL | No |
| Module-scope read | `settings.base_url` read per-request inside function | No |
| Multiple .env files | Single .env only | No |
| Pydantic priority | OS env=None so .env wins | No |
