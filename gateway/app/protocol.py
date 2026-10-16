"""XiaoZhi protocol message builders / parsers and the JSON size cap."""

import json
import uuid

MAX_JSON_BYTES = 65536


def new_session_id():
    return str(uuid.uuid4())


def parse_json(raw):
    """Parse an inbound JSON text message, enforcing a hard size cap.

    Raises ValueError / json.JSONDecodeError on any malformed input so the
    caller can ignore the frame without crashing the connection.
    """
    if isinstance(raw, str):
        data = raw.encode("utf-8")
    else:
        data = raw
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("json message too large: %d bytes" % len(data))
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("json message is not an object")
    return obj


def build_hello(session_id):
    return json.dumps({
        "type": "hello",
        "version": 1,
        "transport": "websocket",
        "session_id": session_id,
        "audio_params": {
            "format": "opus",
            "sample_rate": 24000,
            "channels": 1,
            "frame_duration": 20,
        },
    })


def build_tts(state, session_id, text=None):
    msg = {"type": "tts", "state": state, "session_id": session_id}
    if text is not None:
        msg["text"] = text
    return json.dumps(msg)

def build_transcript(role, *, delta=None, text=None, final=False,
                     interrupted=False, turn=None):
    """CLIENT-UI-1: forward a transcript event to the client (additive message type).

    ``role`` is ``"user"`` (Qwen input transcription) or ``"assistant"`` (response audio
    transcript).  ``delta`` carries partial text, ``text`` the completed text; ``final``
    marks the end of that role's turn, ``interrupted`` marks an assistant turn whose audio
    was cancelled before it finished playing.
    """
    return json.dumps({
        "type": "transcript",
        "role": role,
        "delta": delta,
        "text": text,
        "final": bool(final),
        "interrupted": bool(interrupted),
        "turn": turn,
    }, ensure_ascii=False)
