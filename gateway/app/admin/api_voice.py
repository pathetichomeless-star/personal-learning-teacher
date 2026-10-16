"""ADMIN P2-B1 voice-classroom API — multi-teacher voice teaching infrastructure.

Additive over the ADMIN-2 control plane; mounted only when the voice channel store
is wired.  Nothing here touches the frozen Tina realtime link (28310 / its
protocol / VAD / Opus / barge-in): this surface carries audio over plain HTTP
through a **registered voice adapter**, and the frozen production audio session is
neither opened nor reconfigured.

Server-authoritative by construction:

* the teacher record comes from the teacher store — model, voice configuration,
  material and teaching rules are read from it, never from the request body;
* a voice class needs a **registered, available adapter** whose declared
  capability covers everything the class requires (an unsupported requirement is
  refused, never silently ignored) and whose model roles pass the same
  :func:`modules.model.gating.enable_gate` the text classroom uses;
* the model / adapter binding is re-resolved on every exchange, so a mid-class
  change is refused (``409 voice_binding_changed``) instead of quietly answering
  with a different configuration;
* one student holds at most one live channel: opening a new class closes the
  previous channel explicitly, which is how the previous teacher's sound, model,
  instructions and private memory are released rather than leaked.

Honest scope: ``student_id`` is still a learning-scope label, not authenticated
identity (`scope_note` on every relevant response).  The only adapter registered
in this round is an **isolated test pipeline** (``mode="simulation"``); its
transcript and synthesised audio come from local mock services, so the result
proves the interface and the state machine — never real speech quality.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import logging

from .api import (_ApiError, _audit, _body, _err, _int_arg, _ok)  # noqa: F401

log = logging.getLogger("rtl.admin.api.voice")

from modules._jsonstore import PersistError, StoreUnavailable                 # noqa: E402
from modules._store_lock import StoreLockTimeout                              # noqa: E402
from modules.model.gating import enable_gate                                  # noqa: E402
from modules.teacher.store import TeacherStore                                # noqa: E402
from modules.teaching.store import (SessionNotFound, TeachingInvalid,         # noqa: E402
                                    public_session)
from modules.teaching.engine import build_messages, call_text_model           # noqa: E402
from modules.voice import (ChannelNotFound, VoiceInvalid, VoiceUpstreamError,  # noqa: E402
                          adapter_view, get_adapter, is_test_adapter,
                          list_adapters, public_channel)
from modules.voice.capability import FEATURE_LABELS, missing_features         # noqa: E402
from modules.voice.engine import call_asr, call_tts                           # noqa: E402
from modules.voice.session import (DEFAULT_IDLE_TIMEOUT, MAX_IDLE_TIMEOUT,     # noqa: E402
                                  MIN_IDLE_TIMEOUT)

from .api_teaching import (DEFAULT_STUDENT, KNOWLEDGE_TOP_K, MAX_HISTORY_TURNS,  # noqa: E402
                           SCENE_REASONS, SCOPE_NOTE, TEXT_SCENE,
                           _authorized_datasets, _build_system, _memory_context,
                           _read_secret, _resolve_binding, _retrieve, _source_rows,
                           _student_id, resolve_model_binding)

VOICE_MODE = "realtime"          # teacher.voice.mode for a voice teacher
VOICE_MODALITY = "voice"         # teaching-session modality for a voice class
VOICE_TIMEOUT = 20.0
MAX_AUDIO_BYTES = 2 * 1024 * 1024
DEFAULT_SAMPLE_RATE = 16000
TTS_SAMPLE_RATE = 24000
TTS_VOICE_FALLBACK_CAP = 60

# 语音相关的能力拒绝原因 → 中文提示（前端直接展示，不暴露内部标识）
VOICE_REASONS = {
    "teacher_disabled": "该老师已停用，请先在「AI 老师与教学」中启用。",
    "frozen_realtime_only": "该老师是内置的实时语音老师（冻结的原有生产链路），"
                            "本轮语音教室不接管这条链路；如需新增语音老师，请新建一位老师"
                            "并选择可用的语音适配器。",
    "voice_mode_text": "该老师的交流方式还是「文字教学」，请先在老师编辑中改为「语音教学」。",
    "voice_adapter_not_configured": "该老师还没有选择语音适配器，请先在老师编辑的"
                                    "「声音与交流方式」中选择一个可用的语音适配器。",
    "voice_adapter_unknown": "该老师选择的语音适配器不存在，请重新选择。",
    "voice_adapter_unavailable": "该老师选择的语音适配器尚未接入（没有实现），"
                                 "请改选可用的适配器。",
    "voice_model_missing": "该语音管线需要的模型尚未配置，请先在「AI 模型与连接」中"
                           "配置并绑定对应场景的模型。",
    "voice_binding_changed": "该老师的语音配置在课堂进行中发生了变化，"
                             "为保持一致请重新开始上课。",
    "adapter_capability_unsupported": "该语音适配器不支持本节课要求的语音能力，"
                                      "请取消该要求或改选支持的适配器。",
}


# ---- error mapping --------------------------------------------------------

def _map(exc):
    """Voice-specific mapping first, then the shared teaching mapping."""
    from .api_teaching import _map as _teaching_map
    if isinstance(exc, ChannelNotFound):
        return _ApiError(404, "channel_not_found", "语音通道不存在或已清理。")
    if isinstance(exc, VoiceUpstreamError):
        status = 400 if exc.code in ("credential_missing", "endpoint_missing",
                                     "endpoint_not_allowed", "empty_audio",
                                     "empty_text", "unsupported_audio_format") else 502
        return _ApiError(status, exc.code, exc.detail or None)
    if isinstance(exc, VoiceInvalid):
        msg = str(exc)
        return _ApiError(400, "voice_invalid",
                         "；".join(getattr(exc, "errors", []) or [msg]))
    return _teaching_map(exc)


def _guard(fn):
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except Exception as e:  # noqa: BLE001
            mapped = _map(e)
            if mapped is None:
                log.warning("voice api error in %s: %r", fn.__name__, e)
                return _err(request, 500, "internal_error")
            return _err(request, mapped.status, mapped.code, mapped.detail,
                        mapped.extra)
    return wrapper


# ---- store access ---------------------------------------------------------

def _stores(request):
    return request.app.get("admin_stores")


def _need(request, name):
    s = getattr(_stores(request), name, None)
    if s is None:
        raise _ApiError(503, "%s_not_configured" % name)
    if hasattr(s, "available") and not s.available:
        reason = None
        try:
            reason = s.state().get("reason")
        except Exception:  # noqa: BLE001
            pass
        raise _ApiError(503, "store_unavailable", reason)
    return s


def _voice_store(request):
    return _need(request, "voice")


def _teaching_store(request):
    return _need(request, "teaching")


def _teacher_store(request):
    return _need(request, "teacher")


def _registry(request):
    return getattr(_stores(request), "model_registry", None)


def _creds(request):
    return getattr(_stores(request), "model_credentials", None)


# ---- capability resolution (server-side) ----------------------------------

def _adapter_status(adapter_id):
    """(descriptor, error_code, friendly_reason) for a teacher's adapter choice."""
    aid = str(adapter_id or "").strip()
    if not aid:
        return None, "voice_adapter_not_configured", VOICE_REASONS[
            "voice_adapter_not_configured"]
    d = get_adapter(aid)
    if d is None:
        return None, "voice_adapter_unknown", VOICE_REASONS["voice_adapter_unknown"]
    if not d.get("available"):
        return d, "voice_adapter_unavailable", "%s %s" % (
            VOICE_REASONS["voice_adapter_unavailable"], d.get("requirement") or "")
    return d, None, ""


def _resolve_role(request, model_id, scene, label):
    """Resolve one model *role* of a voice adapter through the shared gate."""
    return resolve_model_binding(request, model_id, scene, label=label)


def _voice_binding(request, teacher, *, required_features=None):
    """The full, server-resolved voice capability of one teacher record.

    Never raises for an unavailable teacher — it returns an honest verdict so the
    overview can list *why* a teacher cannot teach by voice.
    """
    voice = teacher.get("voice") or {}
    base = {"can_teach_voice": False, "reason": "ok", "adapter": None,
            "unsupported_requested": [], "required_features": [],
            "is_test": False, "bindings": {}}

    if not teacher.get("enabled"):
        base["reason"] = "teacher_disabled"
        return base
    if teacher.get("frozen"):
        # the frozen default teacher IS the existing production realtime link; this
        # round does not take it over (and must not reconfigure it)
        base["reason"] = "frozen_realtime_only"
        return base
    if str(voice.get("mode") or "text") != VOICE_MODE:
        base["reason"] = "voice_mode_text"
        return base

    d, code, _reason = _adapter_status(voice.get("adapter_id"))
    if code:
        base["reason"] = code
        base["adapter"] = adapter_view(d["id"]) if d else None
        return base
    base["adapter"] = adapter_view(d["id"])
    base["is_test"] = bool(d.get("is_test"))

    # ---- the class may REQUIRE features; the adapter must really support them --
    req = [f for f in (required_features or []) if isinstance(f, str)]
    base["required_features"] = req
    missing = missing_features(d.get("capability"), req)
    if missing:
        base["reason"] = "adapter_capability_unsupported"
        base["missing_features"] = missing
        return base

    # ---- the teacher's stored interaction preferences that the adapter cannot do -
    inter = voice.get("interaction") or {}
    prefs = []
    if inter.get("barge_in"):
        prefs.append("barge_in")
    base["unsupported_requested"] = missing_features(d.get("capability"), prefs)

    # ---- model roles of this adapter (all server-gated) ----------------------
    # Every role is resolved from THIS teacher's own bindings — there is no global
    # fallback, so two teachers can never end up sharing (or bleeding) each
    # other's speech models.
    tmodel = teacher.get("model") or {}
    roles = {}
    try:
        needs = list(d.get("required_models") or [])
        if "text_llm" in needs:
            roles["text_llm"] = (tmodel.get("text_model_id") or "", TEXT_SCENE,
                                 "文字对话模型")
        if "asr" in needs:
            roles["asr"] = (tmodel.get("asr_model_id") or "", "voice_asr",
                            "语音识别模型")
        if "tts" in needs:
            roles["tts"] = (tmodel.get("tts_model_id") or "", "voice_tts",
                            "语音合成模型")
    except Exception as e:  # noqa: BLE001
        log.warning("voice role lookup failed: %r", e)
        base["reason"] = "voice_model_missing"
        return base

    resolved = {}
    for role, (mid, scene, label) in roles.items():
        try:
            resolved[role] = _resolve_role(request, mid, scene, label)
        except _ApiError as e:
            base["reason"] = ("voice_model_missing" if e.code == "model_not_configured"
                              else e.code)
            base["missing_role"] = role
            base["detail"] = e.detail or SCENE_REASONS.get(e.code, label)
            return base
        except Exception as e:  # noqa: BLE001
            log.warning("voice role %s resolve failed: %r", role, e)
            base["reason"] = "voice_model_missing"
            base["missing_role"] = role
            base["detail"] = "%s 无法解析，请重新配置。" % label
            return base

    base["can_teach_voice"] = True
    base["bindings"] = resolved
    return base


def _provider_is_local_binding(binding):
    return bool(binding.get("model_is_local"))


# ---- read -----------------------------------------------------------------

@_guard
async def overview(request):
    """Per-teacher voice capability — decided from server state, never the body."""
    store = _teacher_store(request)
    rows = []
    for rec in store.list_teachers():
        cap = _voice_binding(request, rec)
        datasets, missing = _authorized_datasets(request, rec)
        voice = rec.get("voice") or {}
        rows.append({
            "teacher_id": rec["teacher_id"], "name": rec.get("name"),
            "enabled": bool(rec.get("enabled")), "frozen": bool(rec.get("frozen")),
            "is_default": bool(rec.get("is_default")),
            "voice_mode": voice.get("mode") or "text",
            "voice_config": {
                "adapter_id": voice.get("adapter_id") or "",
                "voice_id": voice.get("voice_id") or "",
                "language": voice.get("language") or "",
                "accent": voice.get("accent") or "",
                "speed": voice.get("speed"),
                "interaction": voice.get("interaction") or {},
            },
            "can_teach_voice": cap["can_teach_voice"], "reason": cap["reason"],
            "reason_text": ("" if cap["can_teach_voice"]
                            else VOICE_REASONS.get(cap["reason"], cap.get("detail")
                                                   or cap["reason"])),
            "adapter": cap.get("adapter"),
            "is_test_adapter": bool(cap.get("is_test")),
            # 拒绝时指出**具体缺什么**（哪个模型角色 / 哪项能力），界面才能给出准确原因，
            # 而不是一句笼统的「不可用」。
            "missing_role": cap.get("missing_role") or "",
            "missing_features": cap.get("missing_features") or [],
            "detail": cap.get("detail") or "",
            "unsupported_requested": cap.get("unsupported_requested") or [],
            "datasets": datasets, "datasets_missing": missing,
        })
    return _ok(request, {
        "available": True, "teachers": rows,
        "any_voice_teacher": any(r["can_teach_voice"] for r in rows),
        "live_channels": _voice_store(request).counts(),
        "scope_note": SCOPE_NOTE,
        "principal": _principal(request),
        "note": "「可开展语音教学」由服务端依据已注册的语音适配器能力、模型检测证据与"
                "密钥判定；未接入的适配器不会被标记为可用。",
    })


@_guard
async def adapters(request):
    """The registered voice-adapter surface, with honest capability declarations."""
    rows = []
    for d in list_adapters():
        v = adapter_view(d["id"]) or d
        rows.append({
            "id": v["id"], "label": v["label"], "kind": v["kind"],
            "kind_label": v.get("kind_label"), "available": bool(v["available"]),
            "mode": v.get("mode"), "is_test": bool(v.get("is_test")),
            "requirement": v.get("requirement"),
            "required_models": list(v.get("required_models") or []),
            "capability": v.get("capability_summary"),
        })
    return _ok(request, {
        "available": True, "count": len(rows), "adapters": rows,
        "features": [{"id": k, "label": v} for k, v in FEATURE_LABELS.items()],
        "note": "适配器只声明它确实支持的能力；未声明的一律视为不支持。"
                "原生实时语音 / 本地语音模型本轮未接入，仅保留接口位置。",
    })


@_guard
async def channels_list(request):
    store = _voice_store(request)
    rows = store.list_channels(
        teacher_id=request.query.get("teacher_id"),
        student_id=request.query.get("student_id"),
        include_closed=(request.query.get("include_closed") == "1"),
        limit=_int_arg(request, "limit", 50, 200))
    return _ok(request, {"available": True, "count": len(rows),
                         "channels": [public_channel(r) for r in rows],
                         "counts": store.counts(), "scope_note": SCOPE_NOTE})


@_guard
async def channel_get(request):
    rec = _voice_store(request).get_channel(request.match_info["channel_id"])
    if rec is None:
        raise _ApiError(404, "channel_not_found")
    tstore = _teacher_store(request)
    teacher = tstore.get_teacher(rec["teacher_id"])
    cap = _voice_binding(request, teacher) if teacher else {"adapter": None,
                                                            "is_test": False}
    sess = _teaching_store(request).get_session(rec["session_id"])
    return _ok(request, {"available": True, "channel": public_channel(rec),
                         "adapter": cap.get("adapter"),
                         "session": public_session(sess, include_turns=False)
                         if sess else None,
                         "scope_note": SCOPE_NOTE})


@_guard
async def sessions_list(request):
    """Voice-class history — the shared teaching records with modality=voice."""
    store = _teaching_store(request)
    rows = store.list_sessions(teacher_id=request.query.get("teacher_id"),
                               student_id=request.query.get("student_id"),
                               limit=_int_arg(request, "limit", 50, 200))
    rows = [r for r in rows if str(r.get("modality") or "text") == VOICE_MODALITY]
    return _ok(request, {"available": True, "count": len(rows),
                         "sessions": [public_session(r, include_turns=False)
                                      for r in rows],
                         "scope_note": SCOPE_NOTE,
                         "note": "语音课堂与文字课堂共享同一套教学记录归属；"
                                 "此列表只显示交流方式为语音的课堂。"})


def _principal(request):
    mode = request.get("admin_auth_mode") or "unknown"
    user = request.get("admin_user") or "operator"
    return "%s:%s" % (mode, user)


# ---- start / audio / interrupt / close ------------------------------------

def _cap_extra(cap):
    """Machine-readable extra fields for a refusal (never contains secrets)."""
    out = {}
    for k in ("missing_role", "missing_features"):
        if cap.get(k):
            out[k] = cap[k]
    if cap.get("adapter"):
        out["adapter_id"] = cap["adapter"].get("id")
        if cap["adapter"].get("requirement"):
            out["requirement"] = cap["adapter"]["requirement"]
    return out or None


def _required_features(body):
    feats = body.get("features")
    if feats is None:
        return []
    if not isinstance(feats, (list, tuple)):
        raise _ApiError(400, "invalid_json", detail="features 需要字符串列表")
    out = []
    for f in feats:
        if not isinstance(f, str) or f not in FEATURE_LABELS:
            raise _ApiError(400, "invalid_json",
                            detail="features 含未知能力：%s" % str(f)[:32])
        if f not in out:
            out.append(f)
    return out


@_guard
async def session_start(request):
    tstore = _teacher_store(request)
    body = await _body(request)
    tid = body.get("teacher_id")
    if not isinstance(tid, str) or not tid.strip():
        raise _ApiError(400, "invalid_json", detail="teacher_id string required")
    tid = tid.strip()
    teacher = tstore.get_teacher(tid)
    if teacher is None or teacher.get("deleted"):
        raise _ApiError(404, "not_found", detail="unknown teacher")

    required = _required_features(body)
    cap = _voice_binding(request, teacher, required_features=required)
    if not cap["can_teach_voice"]:
        raise _ApiError(400, cap["reason"],
                        VOICE_REASONS.get(cap["reason"], cap.get("detail")
                                          or cap["reason"]),
                        extra=_cap_extra(cap))

    d = cap["adapter"]
    text_binding = cap["bindings"]["text_llm"]
    datasets, missing = _authorized_datasets(request, teacher)
    authorized_ids = [x["id"] for x in datasets if x["enabled"]]
    student_id = _student_id(body)
    course_id = body.get("course_id") if isinstance(body.get("course_id"), str) else ""

    inter = (teacher.get("voice") or {}).get("interaction") or {}
    try:
        idle = int(body.get("idle_timeout") or DEFAULT_IDLE_TIMEOUT)
    except (TypeError, ValueError):
        raise _ApiError(400, "invalid_json", detail="idle_timeout 需要整数")
    idle = max(MIN_IDLE_TIMEOUT, min(idle, MAX_IDLE_TIMEOUT))

    policy = {
        "teaching_style": teacher.get("teaching_style"),
        "subject": teacher.get("subject"), "language": teacher.get("language"),
        "system_instruction": teacher.get("system_instruction") or "",
        "default_strategy": teacher.get("default_strategy") or "",
        "course_id": course_id,
    }
    voice_cfg = dict(teacher.get("voice") or {})
    scope_note = ("本会话只能检索该老师授权资料集：%s" %
                  ("、".join(x["name"] or x["id"] for x in datasets) if datasets
                   else "（未关联教材，将开展一般教学）"))
    tch_store = _teaching_store(request)
    vstore = _voice_store(request)

    # 先建立新课堂，再释放这位学生上一位老师的旧通道——这样新课堂创建失败时，
    # 既有的语音课堂不会被误关。
    sess = tch_store.create_session(
        teacher_id=tid, teacher_name=teacher.get("name") or "",
        student_id=student_id, model_id=text_binding["model_id"],
        model_key=text_binding["model_key"], provider_id=text_binding["provider_id"],
        knowledge_dataset_ids=authorized_ids, course_id=course_id,
        teaching_policy=policy, model_is_local=text_binding["model_is_local"],
        knowledge_scope_note=scope_note, modality=VOICE_MODALITY, voice=voice_cfg)

    channel = vstore.open_channel(
        session_id=sess["session_id"], teacher_id=tid,
        teacher_name=teacher.get("name") or "", student_id=student_id,
        adapter_id=d["id"], adapter_mode=d.get("mode") or "",
        adapter_is_test=bool(d.get("is_test")), voice=voice_cfg,
        transcript_enabled=bool((d.get("capability") or {}).get("transcript")),
        idle_timeout=idle,
        max_turn_seconds=int(inter.get("max_turn_seconds") or 120) or 120)
    channel = vstore.mark_ready(channel["channel_id"])

    # ---- one live channel per student: release the previous teacher's session ---
    replaced = vstore.close_active_for_student(
        student_id, reason="teacher_switch",
        except_channel_id=channel["channel_id"])
    for old in replaced:
        try:
            prev = tch_store.get_session(old["session_id"])
            if prev is not None and prev.get("status") == "active":
                tch_store.end_session(old["session_id"], outcome=None)
        except Exception as e:  # noqa: BLE001  (release must never block a start)
            log.warning("voice switch: closing previous session failed: %r", e)

    _audit(request, "voice_session_start", subject=channel["channel_id"],
           changed=["teacher=%s" % tid, "adapter=%s" % d["id"],
                    "replaced=%d" % len(replaced)])

    out = public_session(sess)
    out["material"] = {"datasets": datasets, "datasets_missing": missing,
                       "linked": bool(datasets), "retrieval_scope": authorized_ids}
    return _ok(request, {
        "available": True, "channel": public_channel(channel), "session": out,
        "adapter": d,
        "speech": {
            "transcript_supported": bool((d.get("capability") or {}).get("transcript")),
            "barge_in_supported": bool((d.get("capability") or {}).get("barge_in")),
            "full_duplex": bool((d.get("capability") or {}).get("full_duplex")),
            "speed_control": bool((d.get("capability") or {}).get("speed_control")),
            "pronunciation_assessment": bool(
                (d.get("capability") or {}).get("pronunciation_assessment")),
            "unsupported_requested": cap.get("unsupported_requested") or [],
            "mode": d.get("mode"),
            "is_test": bool(d.get("is_test")),
            "input_audio": (d.get("capability") or {}).get("input_audio"),
            "output_audio": (d.get("capability") or {}).get("output_audio"),
        },
        "replaced_channels": [public_channel(c) for c in replaced],
        "scope_note": SCOPE_NOTE,
    })


def _decode_audio(body):
    b64 = body.get("audio_b64")
    if not isinstance(b64, str) or not b64.strip():
        return b""
    raw = b64.strip()
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception:  # noqa: BLE001
        raise _ApiError(400, "invalid_json", detail="audio_b64 不是合法的 base64")
    if len(data) > MAX_AUDIO_BYTES:
        raise _ApiError(413, "audio_too_large",
                        detail="单个音频帧上限 %d 字节" % MAX_AUDIO_BYTES)
    return data


@_guard
async def channel_audio(request):
    """One exchange: audio (or text) → transcript → teacher reply → synthesised audio."""
    vstore = _voice_store(request)
    tch = _teaching_store(request)
    cid = request.match_info["channel_id"]
    ch = vstore.get_channel(cid)
    if ch is None:
        raise _ApiError(404, "channel_not_found")
    if ch.get("status") not in ("connecting", "ready", "streaming", "interrupted"):
        raise _ApiError(400, "channel_closed", detail="语音通道已关闭，请重新开始上课。")

    body = await _body(request)
    audio = _decode_audio(body)
    text_in = body.get("text")
    text_in = text_in.strip()[:4000] if isinstance(text_in, str) else ""
    if not audio and not text_in:
        raise _ApiError(400, "invalid_json", detail="需要 audio_b64 或 text")

    sess = tch.get_session(ch["session_id"])
    if sess is None:
        raise _ApiError(404, "not_found", detail="课堂记录不存在。")
    if sess.get("status") != "active":
        raise _ApiError(400, "session_ended", detail="本节课已结束，请重新开始上课。")

    # ---- re-resolve the binding: the class must keep the SAME teacher config ----
    teacher = _teacher_store(request).get_teacher(ch["teacher_id"])
    if teacher is None:
        raise _ApiError(409, "teacher_missing",
                        detail="该课程所属老师已被删除，无法继续。")
    cap = _voice_binding(request, teacher)
    if not cap["can_teach_voice"]:
        raise _ApiError(400, cap["reason"],
                        VOICE_REASONS.get(cap["reason"], cap["reason"]),
                        extra=_cap_extra(cap))
    if cap["adapter"]["id"] != ch["adapter_id"]:
        raise _ApiError(409, "voice_binding_changed",
                        detail=VOICE_REASONS["voice_binding_changed"])
    text_binding = cap["bindings"]["text_llm"]
    if text_binding["model_id"] != sess["model_id"]:
        raise _ApiError(409, "voice_binding_changed",
                        detail=VOICE_REASONS["voice_binding_changed"])

    results, retrieval_state = _retrieve(request, sess, text_in or "语音提问")
    text_secret = _read_secret(request, text_binding)
    system = _build_system(request, sess, results, retrieval_state)
    sources_rows = _source_rows(results)

    audio_meta = None
    transcript = text_in
    asr_info = None
    if audio:
        asr_binding = cap["bindings"].get("asr")
        if asr_binding is None:
            raise _ApiError(400, "voice_model_missing",
                            detail=VOICE_REASONS["voice_model_missing"])
        fmt = str(body.get("format") or "pcm16")[:24]
        rate = int(body.get("sample_rate") or DEFAULT_SAMPLE_RATE)
        try:
            asr_out = await asyncio.to_thread(
                call_asr, protocol=asr_binding["protocol"],
                base_url=asr_binding["base_url"], model_key=asr_binding["model_key"],
                secret=_read_secret(request, asr_binding), audio_bytes=audio,
                audio_format=fmt, sample_rate=rate,
                language=str((teacher.get("voice") or {}).get("language") or ""),
                timeout=VOICE_TIMEOUT, allow_local=asr_binding["allow_local"],
                resolver=request.app.get("model_endpoint_resolver"))
        except VoiceUpstreamError as e:
            # a failed speech call is recorded as an error state and cleaned up —
            # never turned into an invented transcript
            vstore.record_activity(cid, error={"code": e.code, "detail": e.detail})
            raise
        transcript = asr_out["text"]
        asr_info = {"model_id": asr_binding["model_id"],
                    "is_local": bool(asr_binding["model_is_local"])}
        audio_meta = {"bytes": len(audio), "input_format": fmt, "sample_rate": rate,
                      "duration_ms": int(round(len(audio) / max(1, rate * 2) * 1000)),
                      "source": "isolated_test_source" if ch.get("adapter_is_test")
                                else "client_audio",
                      "adapter_id": ch["adapter_id"]}

    if not transcript:
        raise _ApiError(502, "upstream_empty_transcript",
                        detail="语音识别没有返回可用文本，未生成任何学习内容。")

    # ---- the teacher answers through its OWN text model (real call) ------------
    history = (tch.get_session(ch["session_id"]) or {}).get("turns") or []
    out = await asyncio.to_thread(
        call_text_model, protocol=text_binding["protocol"],
        base_url=text_binding["base_url"], model_key=text_binding["model_key"],
        secret=text_secret, system=system,
        messages=build_messages(history, transcript, max_history=MAX_HISTORY_TURNS),
        timeout=VOICE_TIMEOUT, allow_local=text_binding["allow_local"],
        resolver=request.app.get("model_endpoint_resolver"))

    tch.append_turn(ch["session_id"], role="student", text=transcript,
                    kind=("speech" if audio_meta else "text"), audio=audio_meta)
    tch.append_turn(ch["session_id"], role="teacher", text=out["text"],
                    sources=sources_rows, model_id=text_binding["model_id"])

    # ---- synthesise the reply (honest failure reporting, never fake success) ---
    tts_report = {"attempted": False, "ok": False, "audio_bytes": 0}
    tts_binding = cap["bindings"].get("tts")
    if tts_binding is not None:
        tts_report["attempted"] = True
        vcfg = teacher.get("voice") or {}
        try:
            tts_out = await asyncio.to_thread(
                call_tts, protocol=tts_binding["protocol"],
                base_url=tts_binding["base_url"], model_key=tts_binding["model_key"],
                secret=_read_secret(request, tts_binding), text=out["text"],
                voice_id=str(vcfg.get("voice_id") or "")[:TTS_VOICE_FALLBACK_CAP],
                audio_format="pcm16", sample_rate=TTS_SAMPLE_RATE,
                speed=vcfg.get("speed"), timeout=VOICE_TIMEOUT,
                allow_local=tts_binding["allow_local"],
                resolver=request.app.get("model_endpoint_resolver"))
            tts_report.update({"ok": True, "audio_bytes": tts_out["audio_bytes"],
                               "format": tts_out["format"],
                               "is_local": bool(tts_binding["model_is_local"])})
        except VoiceUpstreamError as e:
            # the text answer stands; the missing audio is reported, not faked
            tts_report.update({"ok": False, "code": e.code, "detail": e.detail})

    vstore.record_activity(cid, frames_in=(1 if audio else 0),
                           bytes_in=len(audio), frames_out=(1 if tts_report["ok"] else 0),
                           bytes_out=int(tts_report.get("audio_bytes") or 0), turns=2)
    _audit(request, "voice_channel_audio", subject=cid,
           changed=["speech=%s" % bool(audio_meta), "sources=%d" % len(sources_rows)])

    return _ok(request, {
        "available": True, "reply": out["text"], "transcript": transcript,
        "transcript_available": bool(audio_meta) and ch.get("transcript_enabled"),
        "sources": sources_rows, "material_state": retrieval_state,
        "audio_in": ({"bytes": len(audio)} if audio else None),
        "audio_out": tts_report,
        "model_id": text_binding["model_id"],
        "model_is_local": bool(text_binding["model_is_local"]),
        "asr": asr_info,
        "channel": public_channel(vstore.get_channel(cid)),
        "scope_note": SCOPE_NOTE,
    })


@_guard
async def channel_interrupt(request):
    """Barge-in.  Honest: an adapter without barge-in reports ``supported: false``."""
    vstore = _voice_store(request)
    cid = request.match_info["channel_id"]
    ch = vstore.get_channel(cid)
    if ch is None:
        raise _ApiError(404, "channel_not_found")
    if ch.get("status") not in ("ready", "streaming", "interrupted"):
        raise _ApiError(400, "channel_closed", detail="语音通道已关闭。")
    d = get_adapter(ch["adapter_id"]) or {}
    cap = d.get("capability") or {}
    if not cap.get("barge_in"):
        return _ok(request, {"available": True, "supported": False,
                             "reason": "adapter_no_barge_in",
                             "detail": "当前语音适配器不支持说话打断，"
                                       "老师会先说完这一轮再听你说。",
                             "channel": public_channel(ch),
                             "scope_note": SCOPE_NOTE})
    rec = vstore.mark_interrupted(cid)
    _audit(request, "voice_channel_interrupt", subject=cid)
    return _ok(request, {"available": True, "supported": True,
                         "channel": public_channel(rec), "scope_note": SCOPE_NOTE})


@_guard
async def channel_close(request):
    """Close the audio channel and save the learning result through the evidence gate."""
    vstore = _voice_store(request)
    tch = _teaching_store(request)
    cid = request.match_info["channel_id"]
    ch = vstore.get_channel(cid)
    if ch is None:
        raise _ApiError(404, "channel_not_found")
    body = await _body(request)
    outcome = body.get("outcome")
    if outcome is not None and not isinstance(outcome, dict):
        raise _ApiError(400, "invalid_json", detail="outcome object required")
    rec = vstore.close_channel(cid, reason=str(body.get("reason") or "user_closed"))
    saved = tch.end_session(ch["session_id"], outcome=outcome)
    from .api_teaching import _persist_memory
    mem_saved, mem_rejected = _persist_memory(request, saved,
                                              body.get("memory_items"))
    _audit(request, "voice_channel_close", subject=cid,
           changed=["reason=%s" % rec.get("close_reason"),
                    "memory_saved=%d" % len(mem_saved),
                    "memory_rejected=%d" % len(mem_rejected)])
    return _ok(request, {"available": True, "channel": public_channel(rec),
                         "session": public_session(saved),
                         "memory_saved": mem_saved, "memory_rejected": mem_rejected,
                         "scope_note": SCOPE_NOTE})


@_guard
async def sweep(request):
    """Reap idle channels and close their teaching sessions (timeout cleanup)."""
    vstore = _voice_store(request)
    tch = _teaching_store(request)
    body = {}
    try:
        body = await _body(request)
    except Exception:  # noqa: BLE001  (an empty body is valid here)
        body = {}
    now = body.get("now") if isinstance(body.get("now"), (int, float)) else None
    if now is not None and not (0 < float(now) < 4102444800):
        now = None
    reaped = vstore.sweep(now=now)
    ended = []
    for rec in reaped:
        try:
            sess = tch.get_session(rec["session_id"])
            if sess is not None and sess.get("status") == "active":
                tch.end_session(rec["session_id"], outcome=None)
                ended.append(rec["session_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("voice sweep: closing session %s failed: %r",
                        rec.get("session_id"), e)
    if reaped:
        _audit(request, "voice_sweep", subject=None,
               changed=["reaped=%d" % len(reaped), "sessions=%d" % len(ended)])
    return _ok(request, {"available": True, "reaped": len(reaped),
                         "channels": [public_channel(r) for r in reaped],
                         "sessions_closed": ended,
                         "counts": vstore.counts(), "scope_note": SCOPE_NOTE})


# ---- route table ----------------------------------------------------------

def api_route_table_voice():
    return [
        ("GET", "/admin/voice/overview"),
        ("GET", "/admin/voice/adapters"),
        ("GET", "/admin/voice/channels"),
        ("POST", "/admin/voice/sessions"),
        ("GET", "/admin/voice/sessions"),
        ("GET", "/admin/voice/channels/{channel_id}"),
        ("POST", "/admin/voice/channels/{channel_id}/audio"),
        ("POST", "/admin/voice/channels/{channel_id}/interrupt"),
        ("POST", "/admin/voice/channels/{channel_id}/close"),
        ("POST", "/admin/voice/sweep"),
    ]


def mount_voice(app):
    routes = [
        ("get", "/admin/voice/overview", overview),
        ("get", "/admin/voice/adapters", adapters),
        ("get", "/admin/voice/channels", channels_list),
        ("post", "/admin/voice/sessions", session_start),
        ("get", "/admin/voice/sessions", sessions_list),
        ("get", "/admin/voice/channels/{channel_id}", channel_get),
        ("post", "/admin/voice/channels/{channel_id}/audio", channel_audio),
        ("post", "/admin/voice/channels/{channel_id}/interrupt", channel_interrupt),
        ("post", "/admin/voice/channels/{channel_id}/close", channel_close),
        ("post", "/admin/voice/sweep", sweep),
    ]
    for method, path, handler in routes:
        app.router.add_route(method.upper(), path, handler)
