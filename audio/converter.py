"""
mulaw <-> linear16 conversion using stdlib audioop.

Twilio sends/receives mulaw 8-bit samples at 8 kHz (1 byte/sample).
Deepgram STT expects linear16 (2 bytes/sample, 8 kHz).
Deepgram TTS returns linear16 (2 bytes/sample, 8 kHz).

Frame sizes for 20 ms @ 8 kHz:
  mulaw   : 160 bytes  (160 samples × 1 byte)
  linear16: 320 bytes  (160 samples × 2 bytes)
"""

try:
    import audioop          # Python ≤ 3.12 stdlib
except ModuleNotFoundError:
    import audioop_lts as audioop  # Python 3.13+ — install audioop-lts
import base64

_WIDTH = 2          # 16-bit linear → 2 bytes per sample
MULAW_FRAME = 160   # 20 ms of mulaw
LINEAR16_FRAME = 320  # 20 ms of linear16


def mulaw_to_linear16(data: bytes) -> bytes:
    return audioop.ulaw2lin(data, _WIDTH)


def linear16_to_mulaw(data: bytes) -> bytes:
    # audioop requires an even byte count
    if len(data) % 2:
        data += b"\x00"
    return audioop.lin2ulaw(data, _WIDTH)


def decode_twilio_payload(payload: str) -> bytes:
    """base64 string from Twilio → raw mulaw bytes."""
    return base64.b64decode(payload)


def encode_twilio_payload(mulaw: bytes) -> str:
    """Raw mulaw bytes → base64 string for Twilio."""
    return base64.b64encode(mulaw).decode()
