"""VOICE ADAPTER REGISTRY (P2-B1) — the pluggable speech-adapter surface.

Ownership: `modules/voice`.  Pure data (descriptors) + resolution helpers.

Three adapter **kinds** are defined so the platform can grow into each of them
without redesigning the session API:

1. ``native_realtime``      — a native realtime speech model (duplex audio).
2. ``local_model``          — a locally hosted speech model.
3. ``pipeline_asr_llm_tts`` — a composed pipeline (ASR → LLM → TTS).

Exactly one implementation is registered in this round: an **isolated test
pipeline** whose declared capability is deliberately conservative (no barge-in,
no full duplex, no pronunciation scoring) and whose ``mode`` is ``"simulation"``.
It exists to exercise the interface and the session state machine — its result is
never presented as real speech quality, and it can never claim to be a realtime
model.  The two real kinds are registered as **unavailable slots** carrying an
explicit requirement, so a teacher can be told honestly what is still missing
instead of being offered a capability that does not exist.

Descriptor semantics:

* ``available``     — an implementation exists *and* may be used in this build;
* ``mode``          — ``"real"`` | ``"simulation"``;
* ``is_test``       — the result is simulation-grade evidence, not real audio;
* ``required_models`` — model roles the session must be able to resolve (server
  side, through the model registry's evidence + credential gates);
* ``capability``    — the validated, honest capability block.
"""

from __future__ import annotations

import copy

from modules.voice.capability import KIND_LABELS, validate as validate_capability

# scene ids in the model registry that back the pipeline's speech stages
SCENE_ASR = "voice_asr"
SCENE_TTS = "voice_tts"

TEST_PIPELINE_ID = "voice_test_pipeline"

_TEST_PIPELINE_CAP = {
    "kind": "pipeline_asr_llm_tts",
    "stages": ["asr", "llm", "tts"],
    # 隔离测试源送来的就是 16k 单声道 PCM，适配器如实声明这一点。
    "input_audio": {"containers": ["pcm16"], "sample_rates": [16000],
                    "channels": 1, "streaming": False},
    "output_audio": {"containers": ["pcm16"], "sample_rates": [24000],
                     "channels": 1, "streaming": False},
    # 如实声明「不支持」：不做打断、不是全双工、不做发音评分、不支持语速调节。
    "barge_in": False,
    "full_duplex": False,
    "transcript": True,
    "speed_control": False,
    "pronunciation_assessment": False,
    "languages": ["zh", "en"],
    "voices": ["test-voice"],
    "notes": "隔离测试管线：音频来自隔离测试源，转录与合成为本地模拟服务；"
             "只用于验证接口与状态机，不代表真实语音模型的音质或打断效果。",
}


def _descriptor(adapter_id, label, kind, *, available, mode, requirement,
                capability=None, required_models=(), is_test=False,
                stages_map=None):
    d = {"id": adapter_id, "label": label, "kind": kind, "kind_label":
         KIND_LABELS.get(kind, kind), "available": bool(available), "mode": mode,
         "is_test": bool(is_test), "requirement": requirement,
         "required_models": list(required_models),
         "stages_map": dict(stages_map or {}),
         "capability": copy.deepcopy(capability)}
    return d


_ADAPTERS = [
    _descriptor(
        "voice_native_realtime_slot",
        "原生实时语音模型（待接入）", "native_realtime",
        available=False, mode="real",
        requirement="需要接入一个真实的原生实时语音模型（双向流式音频 + 服务端 VAD + "
                    "打断 + Opus 线路），并在隔离环境完成验证；本轮未实现，也未验证。"),
    _descriptor(
        "voice_local_model_slot",
        "本地语音模型（待接入）", "local_model",
        available=False, mode="real",
        requirement="需要在本地 / 局域网部署一个语音模型服务（本机 ASR / TTS / 实时语音），"
                    "并配置端点与凭据；本轮未实现，也未验证。"),
    _descriptor(
        TEST_PIPELINE_ID,
        "隔离测试语音管线（模拟 · 仅验证接口与状态机）", "pipeline_asr_llm_tts",
        available=True, mode="simulation", is_test=True,
        required_models=["text_llm", "asr", "tts"],
        stages_map={"asr": SCENE_ASR, "tts": SCENE_TTS},
        capability=validate_capability(_TEST_PIPELINE_CAP),
        requirement="用于验证「音频 → 转录 → 老师作答 → 语音合成」链路与语音会话状态机；"
                    "音频来自隔离测试源，转录 / 合成为本地模拟服务，不是真实语音教学质量。"),
]

_ADAPTER_INDEX = {d["id"]: d for d in _ADAPTERS}


class AdapterNotFound(KeyError):
    """Unknown voice adapter id."""


def list_adapters():
    """Every registered adapter descriptor, in declaration order."""
    return [copy.deepcopy(d) for d in _ADAPTERS]


def get_adapter(adapter_id):
    d = _ADAPTER_INDEX.get(str(adapter_id or ""))
    return copy.deepcopy(d) if d else None


def available_adapters():
    return [copy.deepcopy(d) for d in _ADAPTERS if d["available"]]


def default_adapter_id():
    """The adapter a fresh teacher would sensibly pick (the only usable one)."""
    for d in _ADAPTERS:
        if d["available"]:
            return d["id"]
    return ""


def is_test_adapter(adapter_id):
    d = _ADAPTER_INDEX.get(str(adapter_id or ""))
    return bool(d and d["is_test"])


def adapter_view(adapter_id):
    """Display-safe view of one adapter (capability summary included)."""
    from modules.voice.capability import summary  # local import: avoids a cycle
    d = get_adapter(adapter_id)
    if d is None:
        return None
    d["capability_summary"] = summary(d.get("capability"))
    return d
