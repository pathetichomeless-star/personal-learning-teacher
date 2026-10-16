"""ADMIN P1 teacher-management API — multiple AI teachers (additive surface).

Mounted only when the teacher store is wired.  Every decision that could present a
teacher as "usable" is taken from **server-stored state**: teacher records come
from the teacher store, and model capability checks reuse the model registry's
:func:`enable_gate` (the same gate the model surface uses) — a request body never
declares a model verified.

Nothing here touches the frozen Tina realtime link: the teacher store refuses to
change its voice/model config, and the frozen link is exposed read-only.
"""

from __future__ import annotations

import functools
import logging

from .api import (_ApiError, _audit, _body, _confirm, _err, _ok)  # noqa: F401

log = logging.getLogger("rtl.admin.api.teacher")

from modules._store_lock import StoreLockTimeout                       # noqa: E402
from modules._jsonstore import (ConfirmRequired, PersistError,         # noqa: E402
                                StoreUnavailable)
from modules.model.gating import enable_gate                           # noqa: E402
from modules.teacher.store import (ACCENT_LABELS, ACCENTS,             # noqa: E402
                                   DEFAULT_TEACHER_ID, LANGUAGES,
                                   LANGUAGE_LABELS, STYLES, STYLE_LABELS,
                                   SUBJECTS, SUBJECT_LABELS, VOICE_MODES,
                                   VOICE_MODE_LABELS, Duplicate,
                                   FrozenTeacher, NotFound, TeacherInvalid)


def _map(exc):
    if isinstance(exc, _ApiError):
        return exc
    if isinstance(exc, StoreLockTimeout):
        return _ApiError(503, "store_busy")
    if isinstance(exc, StoreUnavailable):
        return _ApiError(503, "store_unavailable", getattr(exc, "reason", None))
    if isinstance(exc, PersistError):
        return _ApiError(500, "persist_failed")
    if isinstance(exc, ConfirmRequired):
        return _ApiError(400, "confirm_required", str(exc))
    if isinstance(exc, FrozenTeacher):
        return _ApiError(400, "frozen_teacher", str(exc))
    if isinstance(exc, TeacherInvalid):
        msg = str(exc)
        code = "default_protected" if "default_protected" in msg else (
            "default_on_disabled" if "default_on_disabled" in msg else "teacher_invalid")
        return _ApiError(400, code, "；".join(getattr(exc, "errors", []) or [msg]))
    if isinstance(exc, Duplicate):
        return _ApiError(409, "duplicate_teacher", str(exc))
    if isinstance(exc, NotFound):
        return _ApiError(404, "not_found", str(exc))
    return None


def _tguard(fn):
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except Exception as e:  # noqa: BLE001
            mapped = _map(e)
            if mapped is None:
                log.warning("teacher api error in %s: %r", fn.__name__, e)
                return _err(request, 500, "internal_error")
            return _err(request, mapped.status, mapped.code, mapped.detail)
    return wrapper


def _store(request):
    s = getattr(request.app.get("admin_stores"), "teacher", None)
    if s is None:
        raise _ApiError(503, "teacher_not_configured")
    if hasattr(s, "available") and not s.available:
        raise _ApiError(503, "store_unavailable", s.state().get("reason"))
    return s


def _registry(request):
    return getattr(request.app.get("admin_stores"), "model_registry", None)


def _creds(request):
    return getattr(request.app.get("admin_stores"), "model_credentials", None)


def _disk_teachers(store):
    try:
        from modules.teacher.store import TeacherStore
        return TeacherStore(store.path).load()
    except Exception as e:  # noqa: BLE001
        log.warning("teacher disk read-back failed: %r", e)
        return None


# ---- capability helpers ---------------------------------------------------

def _model_usable(request, model_id, scene):
    """Server-side usability of a model for a teaching scene (never from the body)."""
    reg, creds = _registry(request), _creds(request)
    if reg is None or not model_id:
        return False, "model_missing"
    ok, code, _ = enable_gate(reg, creds, model_id, scene=scene, action="teacher-bind")
    return bool(ok), (code or "ok")


def _availability(request, rec):
    """Honest availability of a teacher's bound capabilities.

    A teacher never inherits the frozen realtime link; realtime teaching is only
    reported usable when the teacher's OWN realtime model passes the server gate.

    The frozen default teacher is the exception by definition: its realtime link
    **is** the existing production link, so it is reported usable **and read-only**
    (the model-bind gate refuses frozen models, which is a write restriction, not
    evidence that the live link is unavailable).
    """
    model = rec.get("model") or {}
    voice = rec.get("voice") or {}
    if rec.get("frozen"):
        return {
            "text": {"usable": False, "reason": "frozen_readonly"},
            "realtime": {"usable": True, "reason": "frozen_production_link",
                         "requested": True, "read_only": True},
            "effective_mode": "realtime",
            "read_only": True,
        }
    text_ok, text_reason = _model_usable(request, model.get("text_model_id"), "text_chat")
    rt_ok = False
    rt_reason = "not_configured"
    if voice.get("mode") == "realtime":
        rt_ok, rt_reason = _model_usable(request, model.get("realtime_model_id"),
                                         "oral_realtime")
    return {
        "text": {"usable": text_ok, "reason": text_reason},
        "realtime": {"usable": rt_ok, "reason": rt_reason,
                     "requested": voice.get("mode") == "realtime"},
        # what the teacher can actually do right now
        "effective_mode": "realtime" if (voice.get("mode") == "realtime" and rt_ok)
        else ("text" if text_ok else "unconfigured"),
    }


def _options():
    return {
        "subjects": [{"id": s, "label": SUBJECT_LABELS[s]} for s in SUBJECTS],
        "languages": [{"id": l, "label": LANGUAGE_LABELS[l]} for l in LANGUAGES],
        "styles": [{"id": s, "label": STYLE_LABELS[s]} for s in STYLES],
        "voice_modes": [{"id": m, "label": VOICE_MODE_LABELS[m]} for m in VOICE_MODES],
        "accents": [{"id": a, "label": ACCENT_LABELS[a]} for a in ACCENTS],
    }


def _view(request, rec):
    out = dict(rec)
    out["availability"] = _availability(request, rec)
    return out


# ---- read -----------------------------------------------------------------

@_tguard
async def options(request):
    return _ok(request, {"available": True, **_options()})


@_tguard
async def capabilities(request):
    """Model choices for the wizard, split by teaching capability (server-checked)."""
    reg = _registry(request)
    if reg is None:
        return _ok(request, {"available": False, "reason": "model_registry_not_configured",
                             "text_models": [], "realtime_models": [],
                             "asr_models": [], "tts_models": []})
    text_models, realtime_models, asr_models, tts_models, frozen = [], [], [], [], []
    for m in reg.list_models():
        row = {"id": m["id"], "name": m.get("display_name") or m.get("model_key"),
               "model_key": m.get("model_key"), "protocol": m.get("protocol"),
               "evidence_level": m.get("evidence_level"), "frozen": bool(m.get("frozen"))}
        if m.get("frozen"):
            frozen.append(dict(row, usable=False, reason="frozen_readonly"))
            continue
        t_ok, t_reason = _model_usable(request, m["id"], "text_chat")
        r_ok, r_reason = _model_usable(request, m["id"], "oral_realtime")
        # P2-B1: the two speech faces of a composed voice pipeline
        a_ok, a_reason = _model_usable(request, m["id"], "voice_asr")
        s_ok, s_reason = _model_usable(request, m["id"], "voice_tts")
        text_models.append(dict(row, usable=t_ok, reason=t_reason))
        realtime_models.append(dict(row, usable=r_ok, reason=r_reason))
        asr_models.append(dict(row, usable=a_ok, reason=a_reason))
        tts_models.append(dict(row, usable=s_ok, reason=s_reason))
    return _ok(request, {"available": True,
                         "text_models": text_models,
                         "realtime_models": realtime_models,
                         "asr_models": asr_models, "tts_models": tts_models,
                         "frozen_models": frozen,
                         "note": "可用性由服务端依据已存验证证据与密钥判定；"
                                 "未通过检测的模型不会标记为可用。"})


@_tguard
async def teachers_list(request):
    store = _store(request)
    rows = [_view(request, r) for r in store.list_teachers()]
    return _ok(request, {"available": True, "count": len(rows), "teachers": rows,
                         "counts": store.counts(),
                         "default_teacher_id": (store.default_teacher() or {}).get(
                             "teacher_id"),
                         "options": _options()})


@_tguard
async def teacher_get(request):
    store = _store(request)
    rec = store.get_teacher(request.match_info["teacher_id"])
    if rec is None or rec.get("deleted"):
        raise _ApiError(404, "not_found")
    out = _view(request, rec)
    # resolve referenced knowledge datasets for a friendly detail view
    kb = getattr(request.app.get("admin_stores"), "knowledge", None)
    if kb is not None and (rec.get("knowledge") or {}).get("dataset_ids"):
        names = {}
        try:
            for ds in kb.list_datasets():
                names[ds["id"]] = ds.get("name")
        except Exception as e:  # noqa: BLE001
            log.warning("teacher knowledge resolve skipped: %r", e)
        out["knowledge"]["datasets"] = [
            {"id": i, "name": names.get(i), "available": i in names}
            for i in (rec["knowledge"].get("dataset_ids") or [])]
    return _ok(request, {"available": True, "teacher": out})


# ---- writes ---------------------------------------------------------------

def _readback_ok(store, tid, expect):
    disk = _disk_teachers(store)
    if disk is None:
        return False
    rec = disk.get_teacher(tid)
    if rec is None:
        return False
    return all(rec.get(k) == v for k, v in expect.items())


@_tguard
async def teacher_create(request):
    store = _store(request)
    body = await _body(request)
    if not isinstance(body.get("name"), str) or not body["name"].strip():
        raise _ApiError(400, "invalid_json", detail="name string required")
    rec = store.create_teacher(
        name=body.get("name"), avatar=body.get("avatar"), intro=body.get("intro"),
        subject=body.get("subject"), language=body.get("language"),
        teaching_style=body.get("teaching_style"),
        custom_instruction=body.get("custom_instruction"),
        default_strategy=body.get("default_strategy"),
        voice=body.get("voice"), model=body.get("model"),
        knowledge=body.get("knowledge"))
    _audit(request, "teacher_create", subject=rec["teacher_id"],
           changed=["name", "subject", "voice.mode"])
    ok = _readback_ok(store, rec["teacher_id"], {"name": rec["name"]})
    if not ok:
        raise _ApiError(500, "persist_failed", detail="the teacher is not durable on disk")
    return _ok(request, {"available": True, "teacher": _view(request, rec),
                         "readback_ok": True})


@_tguard
async def teacher_update(request):
    store = _store(request)
    tid = request.match_info["teacher_id"]
    body = await _body(request)
    changed = [k for k in ("name", "intro", "subject", "language", "teaching_style",
                           "custom_instruction", "default_strategy", "voice", "model",
                           "knowledge") if k in body]
    rec = store.update_teacher(tid, **{k: body[k] for k in changed})
    _audit(request, "teacher_update", subject=tid, changed=changed)
    if not _readback_ok(store, tid, {"version": rec["version"]}):
        raise _ApiError(500, "persist_failed", detail="the teacher is not durable on disk")
    return _ok(request, {"available": True, "teacher": _view(request, rec),
                         "readback_ok": True})


@_tguard
async def teacher_duplicate(request):
    store = _store(request)
    tid = request.match_info["teacher_id"]
    body = await _body(request)
    new_name = body.get("name") if isinstance(body.get("name"), str) else None
    rec = store.duplicate_teacher(tid, new_name=new_name)
    _audit(request, "teacher_duplicate", subject=rec["teacher_id"],
           changed=["duplicate_of=%s" % tid])
    if not _readback_ok(store, rec["teacher_id"], {"name": rec["name"]}):
        raise _ApiError(500, "persist_failed", detail="the copy is not durable on disk")
    return _ok(request, {"available": True, "teacher": _view(request, rec),
                         "readback_ok": True})


@_tguard
async def teacher_set_default(request):
    store = _store(request)
    tid = request.match_info["teacher_id"]
    rec = store.set_default(tid)
    _audit(request, "teacher_set_default", subject=tid)
    disk = _disk_teachers(store)
    if disk is None or (disk.default_teacher() or {}).get("teacher_id") != tid:
        raise _ApiError(500, "persist_failed", detail="the default is not durable on disk")
    return _ok(request, {"available": True, "teacher": _view(request, rec),
                         "default_teacher_id": tid, "readback_ok": True})


@_tguard
async def teacher_enable(request):
    store = _store(request)
    tid = request.match_info["teacher_id"]
    rec = store.set_enabled(tid, True)
    _audit(request, "teacher_enable", subject=tid)
    if not _readback_ok(store, tid, {"enabled": True}):
        raise _ApiError(500, "persist_failed", detail="not durable on disk")
    return _ok(request, {"available": True, "teacher": _view(request, rec),
                         "readback_ok": True})


@_tguard
async def teacher_disable(request):
    store = _store(request)
    tid = request.match_info["teacher_id"]
    rec = store.set_enabled(tid, False)
    _audit(request, "teacher_disable", subject=tid)
    if not _readback_ok(store, tid, {"enabled": False}):
        raise _ApiError(500, "persist_failed", detail="not durable on disk")
    return _ok(request, {"available": True, "teacher": _view(request, rec),
                         "readback_ok": True})


@_tguard
async def teacher_delete(request):
    store = _store(request)
    body = await _body(request)
    tid = request.match_info["teacher_id"]
    if str(body.get("confirm") or "") != tid:
        raise _ApiError(400, "confirm_required", detail="confirm 必须等于老师 ID")
    out = store.delete_teacher(tid, confirm=tid)
    _audit(request, "teacher_delete", subject=tid, changed=["soft_delete"])
    disk = _disk_teachers(store)
    rec = disk.get_teacher(tid) if disk is not None else None
    if rec is None or not rec.get("deleted"):
        raise _ApiError(500, "persist_failed", detail="the delete is not durable on disk")
    return _ok(request, {"available": True, "deleted": out, "readback_ok": True})


# ---- route table ----------------------------------------------------------

def api_route_table_teacher():
    return [
        ("GET", "/admin/teacher/options"),
        ("GET", "/admin/teacher/capabilities"),
        ("GET", "/admin/teacher/teachers"),
        ("POST", "/admin/teacher/teachers"),
        ("GET", "/admin/teacher/teachers/{teacher_id}"),
        ("PUT", "/admin/teacher/teachers/{teacher_id}"),
        ("POST", "/admin/teacher/teachers/{teacher_id}/duplicate"),
        ("POST", "/admin/teacher/teachers/{teacher_id}/set-default"),
        ("POST", "/admin/teacher/teachers/{teacher_id}/enable"),
        ("POST", "/admin/teacher/teachers/{teacher_id}/disable"),
        ("DELETE", "/admin/teacher/teachers/{teacher_id}"),
    ]


def mount_teacher(app):
    routes = [
        ("get", "/admin/teacher/options", options),
        ("get", "/admin/teacher/capabilities", capabilities),
        ("get", "/admin/teacher/teachers", teachers_list),
        ("post", "/admin/teacher/teachers", teacher_create),
        ("get", "/admin/teacher/teachers/{teacher_id}", teacher_get),
        ("put", "/admin/teacher/teachers/{teacher_id}", teacher_update),
        ("post", "/admin/teacher/teachers/{teacher_id}/duplicate", teacher_duplicate),
        ("post", "/admin/teacher/teachers/{teacher_id}/set-default", teacher_set_default),
        ("post", "/admin/teacher/teachers/{teacher_id}/enable", teacher_enable),
        ("post", "/admin/teacher/teachers/{teacher_id}/disable", teacher_disable),
        ("delete", "/admin/teacher/teachers/{teacher_id}", teacher_delete),
    ]
    for method, path, handler in routes:
        app.router.add_route(method.upper(), path, handler)
