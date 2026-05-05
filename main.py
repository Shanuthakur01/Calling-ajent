"""
Voice AI Calling Agent — FastAPI entry point.

Routes:
  GET  /              Dashboard UI
  POST /make-call     Trigger outbound call to a student
  POST /incoming-call Plivo answer_url webhook → returns PlivoXML
  GET  /incoming-call Same (Plivo may use either method)
  POST /hangup        Plivo hangup_url webhook
  WS   /media-stream  Plivo bidirectional audio WebSocket
  GET  /health        Liveness probe

Singleton clients:
  app.state.llm   — LLMClient  (primary + fallback, provider chain config-driven)
  app.state.plivo — PlivoRestClient  (hangup only in Phase 4+)
  app.state.http  — httpx.AsyncClient  (ElevenLabs + Deepgram TTS)

Graceful shutdown:
  Lifespan exit drains all active CallSessions before closing clients.
  SIGTERM handler logs the signal; uvicorn then triggers the lifespan exit.
"""

import asyncio
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from dotenv import find_dotenv

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response

import state
from agent.backchannels import ensure_ack_cache
from agent.session_registry import all_sessions
from config import settings
from dashboard import DASHBOARD_HTML
from llm.llm_client import LLMClient, PROVIDER_CONFIG
from telephony.plivo_handler import PlivoStreamHandler
from telephony.plivo_outbound import make_call
from telephony.plivo_rest import PlivoRestClient
import tts.elevenlabs_ws as _elevenlabs_ws_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_stream_handler = PlivoStreamHandler()


def _validate_llm_config(cfg, provider_config: dict) -> None:
    """Validate the LLM provider chain configuration.
    Raises RuntimeError on misconfiguration so startup fails fast."""
    primary  = cfg.llm_primary_provider
    fallback = cfg.llm_fallback_provider

    if primary not in provider_config:
        raise RuntimeError(
            f"LLM_PRIMARY_PROVIDER={primary!r} is not a known provider. "
            f"Known providers: {sorted(provider_config)}"
        )
    if fallback not in provider_config:
        raise RuntimeError(
            f"LLM_FALLBACK_PROVIDER={fallback!r} is not a known provider. "
            f"Known providers: {sorted(provider_config)}"
        )
    if primary == fallback:
        raise RuntimeError(
            f"LLM_PRIMARY_PROVIDER and LLM_FALLBACK_PROVIDER are both {primary!r}. "
            "They must be different providers."
        )
    primary_key_attr = provider_config[primary]["settings_key"]
    primary_key = getattr(cfg, primary_key_attr, None)
    if not primary_key:
        raise RuntimeError(
            f"Primary LLM provider {primary!r} requires {primary_key_attr.upper()} "
            "to be set in .env"
        )


async def _warmup_llm(llm: LLMClient) -> None:
    """Fire one cheap non-streaming completion against the primary provider to warm
    the connection pool. Called as fire-and-forget; never blocks startup."""
    try:
        await asyncio.wait_for(
            llm.complete_once(
                model=settings.llm_primary_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            ),
            timeout=5.0,
        )
        logger.info("LLM warmup complete")
    except Exception as exc:
        logger.warning("LLM warmup failed (non-fatal): %s", exc)


def _install_sigterm_handler() -> None:
    def _handler(_signum, _frame):
        logger.warning("SIGTERM received — uvicorn will trigger graceful shutdown")
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (OSError, NotImplementedError):
        pass   # Windows may not support all signals


@asynccontextmanager
async def lifespan(app: FastAPI):
    _install_sigterm_handler()

    logger.info("Voice AI Agent starting")

    # Three-value boot log so the active URL is always cross-checkable in logs.
    _dotenv_path = find_dotenv() or "(not found)"
    logger.info(
        "BOOT base_url: env=%r  settings=%r  dotenv_path=%r",
        os.environ.get("BASE_URL"),
        settings.base_url,
        _dotenv_path,
    )

    # Sanity-check: if settings resolved a ngrok URL but .env doesn't contain ngrok,
    # something outside .env (OS env var or stale config) is overriding .env.
    _env_content = Path(_dotenv_path).read_text(encoding="utf-8") if Path(_dotenv_path).exists() else ""
    if "ngrok" in settings.base_url.lower() and "ngrok" not in _env_content.lower():
        raise RuntimeError(
            f"base_url '{settings.base_url}' contains 'ngrok' but .env ({_dotenv_path}) does not. "
            f"A stale OS environment variable (BASE_URL={os.environ.get('BASE_URL')!r}) "
            "is overriding .env. Fix: run `Remove-Item Env:BASE_URL` (PowerShell) "
            "or `unset BASE_URL` (bash) then restart."
        )

    # Validate LLM chain config before constructing clients — fails fast on misconfiguration.
    _validate_llm_config(settings, PROVIDER_CONFIG)

    # Recordings directory — resolved to absolute path so it works regardless of CWD
    if settings.recording_enabled:
        from agent.recorder import ensure_recording_dir
        _rec_path = await ensure_recording_dir()
        logger.info(
            "Recordings dir ensured: %s (writable=%s)",
            _rec_path, os.access(_rec_path, os.W_OK),
        )

    # Singleton provider clients — created once, shared across all calls.
    # http client first: LLMClient receives it for interface compat.
    app.state.http  = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
    app.state.plivo = PlivoRestClient()
    app.state.llm   = LLMClient(_http_client=app.state.http)
    app.state.backchannels = await ensure_ack_cache(app.state.http)

    logger.info("Singleton clients initialised: LLMClient, PlivoRestClient, httpx.AsyncClient")
    asyncio.create_task(_warmup_llm(app.state.llm), name="llm-warmup")

    yield

    # ── Graceful shutdown ──────────────────────────────────────────────────
    sessions = all_sessions()
    if sessions:
        logger.info("Draining %d active call(s)…", len(sessions))
        try:
            await asyncio.wait_for(
                asyncio.gather(*[s.close() for s in sessions], return_exceptions=True),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Drain timed out — forcing shutdown")

    await app.state.plivo.close()
    await app.state.http.aclose()
    logger.info("Voice AI Agent shut down cleanly")


app = FastAPI(title="Voice AI Calling Agent", version="3.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(content=DASHBOARD_HTML)


# ---------------------------------------------------------------------------
# Outbound call trigger
# ---------------------------------------------------------------------------

@app.post("/make-call")
async def trigger_call(request: Request) -> JSONResponse:
    body  = await request.json()
    phone: str = body.get("phone", "").strip()
    name: str  = body.get("name",  "").strip()

    if not phone:
        return JSONResponse({"success": False, "error": "Phone number is required"})

    if phone.isdigit() and len(phone) == 10:
        phone = "+91" + phone

    answer_url = f"{settings.base_url}/incoming-call"
    logger.info("Outbound call → %s (%s)", phone, name or "unnamed")

    try:
        result       = await make_call(to_number=phone, answer_url=answer_url)
        request_uuid = result.get("request_uuid", "")
        state.register(request_uuid, phone, name)
        return JSONResponse({"success": True, "request_uuid": request_uuid})
    except Exception as exc:
        logger.error("make_call failed: %s", exc)
        return JSONResponse({"success": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Plivo answer_url webhook
# ---------------------------------------------------------------------------

def _build_xml(request: Request) -> Response:
    # Always derive the WebSocket URL from settings.base_url — never from the
    # incoming Host header, which reflects whatever tunnel URL the *caller* used
    # and will be stale if Plivo was configured with an old ngrok answer_url.
    parsed    = urlparse(settings.base_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url    = f"{ws_scheme}://{parsed.netloc}/media-stream"
    xml       = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Stream bidirectional="true" keepCallAlive="true"'
        f' contentType="audio/x-mulaw;rate=8000">{ws_url}</Stream>'
        "</Response>"
    )
    logger.info("Answer XML [%s] host_hdr=%r ws_url=%s",
                request.method, request.headers.get("host"), ws_url)
    return Response(content=xml, media_type="text/xml")


@app.post("/incoming-call", response_class=Response)
async def incoming_call_post(request: Request) -> Response:
    logger.info("t_incoming_call=%.6f", time.perf_counter())
    return _build_xml(request)


@app.get("/incoming-call", response_class=Response)
async def incoming_call_get(request: Request) -> Response:
    logger.info("t_incoming_call=%.6f", time.perf_counter())
    return _build_xml(request)


# ---------------------------------------------------------------------------
# Plivo hangup webhook
# ---------------------------------------------------------------------------

@app.post("/hangup")
async def hangup(request: Request) -> JSONResponse:
    ct   = request.headers.get("content-type", "")
    body = await request.json() if ct.startswith("application/json") else {}
    logger.info("Hangup event: %s", body)
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Plivo bidirectional audio WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket) -> None:
    try:
        await _stream_handler.handle(
            websocket,
            llm=websocket.app.state.llm,
            plivo=websocket.app.state.plivo,
            http=websocket.app.state.http,
            backchannels=websocket.app.state.backchannels,
        )
    except Exception as exc:
        # Crash isolation: one bad call must not kill the server process.
        logger.error("Unhandled error in /media-stream: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def api_stats() -> JSONResponse:
    return JSONResponse(state.get_stats())


@app.get("/api/calls")
async def api_calls() -> JSONResponse:
    return JSONResponse({"calls": state.get_all()})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Liveness + readiness probe. Returns 200 only when all three providers are reachable."""
    import websockets as _ws_lib

    results: dict = {}

    # ── OpenAI ──────────────────────────────────────────────────────────
    try:
        await asyncio.wait_for(
            request.app.state.llm.complete_once(
                model=settings.llm_primary_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            ),
            timeout=5.0,
        )
        results["openai"] = "ok"
    except Exception as exc:
        results["openai"] = f"error: {exc!s}"

    # ── ElevenLabs ──────────────────────────────────────────────────────
    try:
        resp = await asyncio.wait_for(
            request.app.state.http.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": settings.elevenlabs_api_key},
            ),
            timeout=5.0,
        )
        resp.raise_for_status()
        results["elevenlabs"] = "ok"
    except Exception as exc:
        results["elevenlabs"] = f"error: {exc!s}"

    # ── Deepgram ────────────────────────────────────────────────────────
    try:
        dg_url = (
            "wss://api.deepgram.com/v1/listen"
            "?encoding=mulaw&sample_rate=8000&model=nova-2-phonecall"
        )
        ws = await asyncio.wait_for(
            _ws_lib.connect(
                dg_url,
                additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
                ping_interval=None,
                close_timeout=3,
            ),
            timeout=5.0,
        )
        await ws.close()
        results["deepgram"] = "ok"
    except Exception as exc:
        results["deepgram"] = f"error: {exc!s}"

    all_ok = all(v == "ok" for v in results.values())
    return JSONResponse(
        {"status": "ok" if all_ok else "degraded", "version": app.version, "providers": results},
        status_code=200 if all_ok else 503,
    )


# ---------------------------------------------------------------------------
# Debug config (non-production only — enable via DEBUG_MODE=true in .env)
# ---------------------------------------------------------------------------

@app.get("/debug/config")
async def debug_config() -> JSONResponse:
    if not settings.debug_mode:
        return JSONResponse(
            {"error": "debug endpoints disabled — set DEBUG_MODE=true in .env to enable"},
            status_code=403,
        )
    dotenv_path = find_dotenv() or "(not found)"
    return JSONResponse({
        "base_url":               settings.base_url,
        "os_BASE_URL":            os.environ.get("BASE_URL"),
        "dotenv_path":            dotenv_path,
        "host":                   settings.host,
        "port":                   settings.port,
        # LLM chain
        "llm_primary_provider":   settings.llm_primary_provider,
        "llm_primary_model":      settings.llm_primary_model,
        "llm_primary_timeout_s":  settings.llm_primary_timeout_s,
        "llm_fallback_provider":  settings.llm_fallback_provider,
        "llm_fallback_model":     settings.llm_fallback_model,
        "llm_fallback_timeout_s": settings.llm_fallback_timeout_s,
        # STT / silence detection
        "dg_endpointing_ms":      settings.dg_endpointing_ms,
        "dg_utterance_end_ms":    settings.dg_utterance_end_ms,
        "endpoint_ms":            settings.endpoint_ms,
        "min_utterance_words":    settings.min_utterance_words,
        # TTS
        "elevenlabs_voice_id":      settings.elevenlabs_voice_id,
        "elevenlabs_model":         settings.elevenlabs_model,
        "tts_stability":            settings.tts_stability,
        "tts_similarity_boost":     settings.tts_similarity,
        "tts_style":                settings.tts_style,
        "tts_speaker_boost":        settings.tts_speaker_boost,
        "tts_speed":                settings.tts_speed,
        "tts_ws_open_count":        _elevenlabs_ws_module.tts_ws_open_count,
    })


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
