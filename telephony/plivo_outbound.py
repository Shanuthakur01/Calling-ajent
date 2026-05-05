"""
Plivo outbound call — dials a student's number and connects them to Saanvi.
When the student answers, Plivo hits answer_url which returns the Stream XML.
"""

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.plivo.com/v1"


async def make_call(to_number: str, answer_url: str) -> dict:
    """
    Initiate an outbound call from our Plivo number to `to_number`.
    Returns Plivo's response dict (contains request_uuid).
    Raises httpx.HTTPStatusError on failure.
    """
    url = f"{_BASE}/Account/{settings.plivo_auth_id}/Call/"
    payload = {
        "from": settings.plivo_phone_number,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": answer_url.replace("/incoming-call", "/hangup"),
        "hangup_method": "POST",
    }
    async with httpx.AsyncClient(
        auth=(settings.plivo_auth_id, settings.plivo_auth_token),
        timeout=httpx.Timeout(15.0, connect=5.0),
    ) as client:
        resp = await client.post(url, json=payload)
        logger.info("Plivo make_call → %s: %s", resp.status_code, resp.text[:200])
        resp.raise_for_status()
        return resp.json()
