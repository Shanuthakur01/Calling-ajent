"""
Plivo REST API client — used only for hangup() in Phase 4+.

Audio is now sent directly over the WebSocket (playAudio events), so
play() and stop_play() are retained for compatibility but not used in
the hot path.
"""

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.plivo.com/v1"


class PlivoRestClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            auth=(settings.plivo_auth_id, settings.plivo_auth_token),
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    async def hangup(self, call_uuid: str) -> None:
        """Terminate the live call."""
        if not call_uuid:
            return
        url = f"{_BASE}/Account/{settings.plivo_auth_id}/Call/{call_uuid}/"
        try:
            resp = await self._http.delete(url)
            logger.info("Plivo hangup %s  call=%s", resp.status_code, call_uuid)
        except Exception as exc:
            logger.warning("Plivo hangup error: %s", exc)

    async def play(self, call_uuid: str, audio_url: str) -> None:
        """Legacy REST Play — not used in normal call flow."""
        if not call_uuid or not audio_url:
            return
        url = f"{_BASE}/Account/{settings.plivo_auth_id}/Call/{call_uuid}/Play/"
        try:
            resp = await self._http.post(url, json={"urls": audio_url, "length": 300})
            logger.info("Plivo Play %s  %s", resp.status_code, audio_url[-48:])
        except Exception as exc:
            logger.error("Plivo Play error: %s", exc)

    async def stop_play(self, call_uuid: str) -> None:
        if not call_uuid:
            return
        url = f"{_BASE}/Account/{settings.plivo_auth_id}/Call/{call_uuid}/Play/"
        try:
            await self._http.delete(url)
        except Exception as exc:
            logger.warning("Plivo stop_play error: %s", exc)

    async def close(self) -> None:
        await self._http.aclose()
