"""
Plivo Media Streams WebSocket handler.

Events received from Plivo:
  connected  — WebSocket handshake confirmed
  start      — stream metadata (streamSid, callId)
  media      — 20 ms mulaw audio chunk (base64) from the caller
  stop       — caller hung up or Plivo ended the stream

Events sent to Plivo (by CallSession/StreamingPipeline):
  playAudio  — outbound μ-law 8kHz frames, base64-encoded
  clearAudio — discard Plivo's audio buffer on barge-in

session.start() is launched as a background task so the event loop
continues processing inbound `media` events while the greeting plays.
"""

import asyncio
import json
import logging
from typing import Optional

import httpx
from fastapi import WebSocket, WebSocketDisconnect

import state
from agent.backchannels import BackchannelPlayer
from agent.call_session import CallSession
from llm.llm_client import LLMClient
from telephony.plivo_rest import PlivoRestClient

logger = logging.getLogger(__name__)


class PlivoStreamHandler:
    async def handle(
        self,
        websocket: WebSocket,
        *,
        llm: LLMClient,
        plivo: PlivoRestClient,
        http: httpx.AsyncClient,
        backchannels: Optional[BackchannelPlayer] = None,
    ) -> None:
        await websocket.accept()
        session: Optional[CallSession] = None

        try:
            async for raw in websocket.iter_text():
                data  = json.loads(raw)
                event = data.get("event")

                if event == "connected":
                    logger.info("Plivo WS connected (protocol=%s)", data.get("protocol"))

                elif event == "start":
                    logger.info("Plivo START: %s", data)
                    meta       = data.get("start", {})
                    stream_sid = (
                        meta.get("streamId")
                        or meta.get("streamSid")
                        or data.get("streamSid", "")
                    )
                    call_id = meta.get("callId", "")
                    logger.info("Stream start — streamSid=%s callId=%s", stream_sid, call_id)
                    state.activate(call_id)

                    session = CallSession(
                        websocket=websocket,
                        stream_sid=stream_sid,
                        call_sid=call_id,
                        llm=llm,
                        plivo=plivo,
                        http=http,
                        backchannels=backchannels,
                    )
                    # Start as background task so media events are not dropped
                    # while the greeting is being synthesised.
                    asyncio.create_task(
                        session.start(), name=f"start-{call_id}"
                    )

                elif event == "media":
                    if session:
                        await session.handle_audio(data["media"]["payload"])

                elif event == "stop":
                    logger.info("Stream stop received")
                    break

                else:
                    logger.debug("Unknown Plivo event: %s", event)

        except WebSocketDisconnect:
            logger.info("Plivo WebSocket disconnected")
        except Exception as exc:
            logger.error("PlivoStreamHandler error: %s", exc, exc_info=True)
        finally:
            if session:
                await session.close()
                state.complete(session._call_sid)
