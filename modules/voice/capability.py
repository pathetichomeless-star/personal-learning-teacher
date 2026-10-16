"""VOICE CAPABILITY (P2-B1) — the honest capability descriptor of a speech adapter.

Ownership: `modules/voice`.  Pure data + validation; no I/O, no gateway imports.

A speech adapter **must declare what it can actually do**, and the declaration is
validated so an impossible claim cannot be registered:

* an audio direction that is not declared is treated as **not supported** — there
  is no implicit "assume supported";
* a ``native_realtime`` adapter must declare streaming input *and* streaming
  output *and* full-duplex *and* barge-in explicitly as booleans; claiming
  ``native_realtime`` while refusing to state them fails validation;
* a ``pipeline_asr_llm_tts`` adapter must declare its concrete stages
  (``asr`` / ``llm`` / ``tts``);
* a plain text-chat model is never acceptable here — the voice adapter kind
  describes a *speech* path, so a text-only description is rejected.

Nothing in this module can turn a text model into a realtime voice model: that is
a property of the adapter's declared kind and capabilities, which are code-owned
(see :mod:`modules.voice.registry`), never request-body-owned.
"""

from __future__ import annotations

import copy

# ---- closed vocabularies --------------------------------------------------

ADAPTER_KINDS = ("native_realtime", "local_model", "pipeline_asr_llm_tts")

KIND_LABELS = {
    "native_realtime": "原生实时语音模型（双向音频会话）",
    "local_model": "本地语音模型（本机 / 局域网部署）",
    "pipeline_asr_llm_tts": "组合式语音管线（ASR + LLM + TTS）",
}

# 音频容器（线路格式）。  这只是**声明**，不代表适配器可以把任意格式转成另一种。
AUDIO_CONTAINERS = ("pcm16", "opus", "wav", "mp3", "aac", "webm_opus")

# 语音交互策略里可被声明的特性（同时用于「要求的特性」与「声明的能力」比对）。
FEATURES = ("barge_in", "full_duplex", "streaming_in", "streaming_out",
            "transcript", "speed_control", "pronunciation_assessment")

FEATURE_LABELS = {
    "barge_in": "说话打断（打断老师）",
    "full_duplex": "全双工（边说边听）",
    "streaming_in": "流式音频输入",
    "streaming_out": "流式音频输出",
    "transcript": "语音转写",
    "speed_control": "语速调节",
    "pronunciation_assessment": "发音评估",
}

# 语音会话状态机：所有适配器共用同一套状态，便于统一的清理与超时处理。
SESSION_STATES = ("connecting", "ready", "streaming", "interrupted", "ended",
                  "error", "timeout")

# 统一错误码（适配器必须只使用这些；未知即实现缺陷，会被判为 error）。
ERROR_CODES = ("adapter_unavailable", "upstream_unreachable", "upstream_timeout",
               "unsupported_audio_format", "unsupported_feature",
               "auth_failed", "protocol_error", "session_closed")

MAX_LIST = 24
MAX_STR = 40


class CapabilityInvalid(ValueError):
    """The declared capability block is not a valid, honest declaration."""

    def __init__(self, errors):
        errors = list(errors)
        super().__init__("capability_invalid: %s" % "; ".join(errors[:8]))
        self.errors = errors


def _str_list(values, what, cap=MAX_LIST):
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise CapabilityInvalid(["%s: 需要列表" % what])
    out = []
    for v in values:
        s = str(v).strip()[:MAX_STR]
        if s and s not in out:
            out.append(s)
    if len(out) > cap:
        raise CapabilityInvalid(["%s: 过多" % what])
    return out


def _direction(d, what):
    """One audio direction.  Absent/unspecified ⇒ NOT supported."""
    if d is None:
        d = {}
    if not isinstance(d, dict):
        raise CapabilityInvalid(["%s: 需要对象" % what])
    containers = _str_list(d.get("containers"), "%s.containers" % what)
    for c in containers:
        if c not in AUDIO_CONTAINERS:
            raise CapabilityInvalid(["%s.containers: 未知格式 %s" % (what, c)])
    rates = []
    for r in (d.get("sample_rates") or []):
        try:
            r = int(r)
        except (TypeError, ValueError):
            raise CapabilityInvalid(["%s.sample_rates: 需要整数" % what])
        if r > 0 and r not in rates:
            rates.append(r)
    try:
        channels = int(d.get("channels") or 0)
    except (TypeError, ValueError):
        raise CapabilityInvalid(["%s.channels: 需要整数" % what])
    if channels < 0:
        raise CapabilityInvalid(["%s.channels: 非法" % what])
    return {"containers": containers, "sample_rates": rates[:8],
            "channels": channels, "streaming": bool(d.get("streaming") is True)}


def blank(kind="pipeline_asr_llm_tts"):
    """A capability block that claims nothing it cannot prove."""
    return {
        "kind": kind if kind in ADAPTER_KINDS else "pipeline_asr_llm_tts",
        "input_audio": {"containers": [], "sample_rates": [], "channels": 0,
                        "streaming": False},
        "output_audio": {"containers": [], "sample_rates": [], "channels": 0,
                         "streaming": False},
        "stages": [],
        "barge_in": False,
        "full_duplex": False,
        "transcript": False,
        "speed_control": False,
        "pronunciation_assessment": False,
        "languages": [],
        "voices": [],
        "session_states": list(SESSION_STATES),
        "errors": list(ERROR_CODES),
        "notes": "",
    }


def validate(cap):
    """Normalize + validate a declared capability block.  Raises on a false claim."""
    if not isinstance(cap, dict):
        raise CapabilityInvalid(["capability: 需要对象"])
    errors = []
    kind = str(cap.get("kind") or "")
    if kind not in ADAPTER_KINDS:
        errors.append("kind: 未知适配器类型（只能是 %s）" % "、".join(ADAPTER_KINDS))

    out = blank(kind if kind in ADAPTER_KINDS else "pipeline_asr_llm_tts")
    try:
        out["input_audio"] = _direction(cap.get("input_audio"), "input_audio")
        out["output_audio"] = _direction(cap.get("output_audio"), "output_audio")
    except CapabilityInvalid as e:
        errors.extend(e.errors)

    for key in ("barge_in", "full_duplex", "transcript", "speed_control",
                "pronunciation_assessment"):
        out[key] = cap.get(key) is True
    try:
        out["stages"] = _str_list(cap.get("stages"), "stages")
        out["languages"] = _str_list(cap.get("languages"), "languages")
        out["voices"] = _str_list(cap.get("voices"), "voices")
    except CapabilityInvalid as e:
        errors.extend(e.errors)
        out["languages"] = out["voices"] = out["stages"] = []
    out["notes"] = str(cap.get("notes") or "")[:400]

    # ---- honesty rules per kind ------------------------------------------
    if kind == "native_realtime":
        # a realtime session is duplex by definition; refusing to state it is a
        # refusal to claim it -> the declaration is not acceptable.
        for k in ("barge_in", "full_duplex"):
            if k not in cap:
                errors.append("native_realtime 必须显式声明 %s" % k)
        if out["full_duplex"] is not True:
            errors.append("native_realtime 必须支持全双工（full_duplex=true）")
        if out["input_audio"]["streaming"] is not True \
                or out["output_audio"]["streaming"] is not True:
            errors.append("native_realtime 必须支持流式输入与流式输出")
    elif kind == "pipeline_asr_llm_tts":
        need = {"asr", "llm", "tts"}
        missing = sorted(need - set(out["stages"]))
        if missing:
            errors.append("组合式管线必须声明全部阶段，缺少：%s" % "、".join(missing))
    elif kind == "local_model":
        if not out["input_audio"]["containers"] and not out["output_audio"]["containers"]:
            errors.append("本地语音模型至少要声明一种音频格式")

    # a kind that cannot move audio in SOME direction is not a speech adapter
    if not out["input_audio"]["containers"] and not out["output_audio"]["containers"] \
            and kind in ADAPTER_KINDS:
        errors.append("适配器必须至少声明一种输入或输出音频格式（纯文字模型不是语音适配器）")

    ss = set(out.get("session_states") or ())
    if ss and not set(SESSION_STATES).issubset(ss):
        errors.append("session_states: 必须覆盖统一状态机 %s" % "、".join(SESSION_STATES))
    errs = set(out.get("errors") or ())
    if errs and not errs.issubset(set(ERROR_CODES)):
        errors.append("errors: 只能使用统一错误码")

    if errors:
        raise CapabilityInvalid(errors)
    return copy.deepcopy(out)


def declared_features(cap):
    """The set of features the adapter truthfully supports."""
    if not cap:
        return []
    feats = []
    if cap.get("barge_in"):
        feats.append("barge_in")
    if cap.get("full_duplex"):
        feats.append("full_duplex")
    if (cap.get("input_audio") or {}).get("streaming"):
        feats.append("streaming_in")
    if (cap.get("output_audio") or {}).get("streaming"):
        feats.append("streaming_out")
    if cap.get("transcript"):
        feats.append("transcript")
    if cap.get("speed_control"):
        feats.append("speed_control")
    if cap.get("pronunciation_assessment"):
        feats.append("pronunciation_assessment")
    return feats


def missing_features(cap, required):
    """Which of the *required* features the adapter does NOT support."""
    have = set(declared_features(cap))
    return [f for f in (required or []) if f not in have]


def summary(cap):
    """A safe, display-oriented projection (no raw internals needed by the UI)."""
    if not cap:
        return None
    return {
        "kind": cap.get("kind"),
        "kind_label": KIND_LABELS.get(str(cap.get("kind") or ""), str(cap.get("kind"))),
        "input_audio": copy.deepcopy(cap.get("input_audio") or {}),
        "output_audio": copy.deepcopy(cap.get("output_audio") or {}),
        "stages": list(cap.get("stages") or []),
        "features": [{"id": f, "label": FEATURE_LABELS.get(f, f), "supported": True}
                     for f in declared_features(cap)],
        "unsupported": [{"id": f, "label": FEATURE_LABELS.get(f, f)}
                        for f in FEATURES if f not in set(declared_features(cap))],
        "languages": list(cap.get("languages") or []),
        "voices": list(cap.get("voices") or []),
        "session_states": list(cap.get("session_states") or []),
        "errors": list(cap.get("errors") or []),
        "notes": cap.get("notes") or "",
    }
