"""VOICE (P2-B1) — multi-teacher voice-teaching infrastructure.

Ownership: `modules/voice`.  Three strictly separated pieces:

* :mod:`modules.voice.capability` — the **honest capability descriptor** of a
  speech adapter (audio formats in/out, streaming, barge-in, full duplex,
  languages, voices, session states, error codes).  Anything not declared is
  treated as *not supported*; a ``native_realtime`` claim must state duplex
  streaming and barge-in explicitly, and a text-chat model can never pass as a
  realtime voice adapter.
* :mod:`modules.voice.registry`   — the pluggable adapter surface: three kinds
  (``native_realtime`` / ``local_model`` / ``pipeline_asr_llm_tts``), with one
  runnable **isolated test pipeline** and two honest *unavailable slots* that
  state what is still required.
* :mod:`modules.voice.session`    — the audio-transport lifecycle of one voice
  class (channel state machine + idle sweep + teacher-switch release), kept
  separate from the shared teaching record.
* :mod:`modules.voice.engine`     — real ASR / TTS HTTP calls (never fabricated).

Nothing here opens the frozen Tina realtime link, its protocol, VAD or Opus path:
the voice classroom is an independent adapter layer over plain HTTP.
"""

from modules.voice.capability import (  # noqa: F401
    ADAPTER_KINDS, AUDIO_CONTAINERS, ERROR_CODES, FEATURES, FEATURE_LABELS,
    KIND_LABELS, SESSION_STATES, CapabilityInvalid, declared_features,
    missing_features, summary as capability_summary, validate as validate_capability,
)
from modules.voice.registry import (  # noqa: F401
    AdapterNotFound, TEST_PIPELINE_ID, adapter_view, available_adapters,
    default_adapter_id, get_adapter, is_test_adapter, list_adapters,
)
from modules.voice.session import (  # noqa: F401
    CLOSE_REASONS, DEFAULT_IDLE_TIMEOUT, ChannelNotFound, STATUSES, VoiceChannelStore,
    VoiceInvalid, public_channel,
)
from modules.voice.engine import (  # noqa: F401
    VoiceUpstreamError, call_asr, call_tts,
)

__all__ = [
    "ADAPTER_KINDS", "AUDIO_CONTAINERS", "ERROR_CODES", "FEATURES",
    "FEATURE_LABELS", "KIND_LABELS", "SESSION_STATES", "CapabilityInvalid",
    "declared_features", "missing_features", "capability_summary",
    "validate_capability", "AdapterNotFound", "TEST_PIPELINE_ID", "adapter_view",
    "available_adapters", "default_adapter_id", "get_adapter", "is_test_adapter",
    "list_adapters", "CLOSE_REASONS", "DEFAULT_IDLE_TIMEOUT", "ChannelNotFound",
    "STATUSES", "VoiceChannelStore", "VoiceInvalid", "public_channel",
    "VoiceUpstreamError", "call_asr", "call_tts",
]
