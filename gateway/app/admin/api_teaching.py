"""ADMIN P2-A teaching-session API — real text teaching over a **verified** model.

Additive over the ADMIN-2 control plane; mounted only when the teaching store is
wired.  Every decision that could present a teacher as "able to teach" is taken
from **server-stored state**:

* the teacher record comes from the teacher store;
* the text model must pass :func:`modules.model.gating.enable_gate` for the
  ``text_chat`` scene (server evidence + a usable credential — a request body
  never declares a model verified);
* the material a session may read is snapshotted from the teacher's authorized
  ``knowledge.dataset_ids`` at session creation and confined to that set on every
  turn (a client cannot widen it);
* the model that answers is the model that was verified: the session stores both
  ``model_id`` and the concrete ``model_key`` actually called.

The classroom record (learning outcomes) lives in the teaching-session store.
Durable learner memory is written to the memory store with the teacher-scoped
namespace, so two teachers of one student never overwrite each other's same-named
field, and two students never see each other's private records.

Scope honesty: the current environment has **no independent student identity
authentication**.  ``student_id`` is a learning-scope label under the single
authenticated operator; it guarantees records are *separated*, not that a hostile
client is *authenticated*.  This is stated in every relevant response
(``scope_note``) and never presented as a multi-user security boundary.
"""

from __future__ import annotations

import asyncio
import functools
import logging

from .api import (_ApiError, _audit, _body, _err, _int_arg, _ok)  # noqa: F401

log = logging.getLogger("rtl.admin.api.teaching")

from modules._store_lock import StoreLockTimeout                        # noqa: E402
from modules._jsonstore import PersistError, StoreUnavailable           # noqa: E402
from modules.knowledge.store import render_knowledge_block              # noqa: E402
from modules.memory.store import (BoundaryViolation as MBoundary,       # noqa: E402
                                  MemoryStore, render_memory_block)
from modules.model.gating import enable_gate                            # noqa: E402
from modules.model.registry import ModelRegistry                        # noqa: E402
from modules.teacher.store import TeacherStore                          # noqa: E402
from modules.teaching.engine import (TextModelError, build_messages,    # noqa: E402
                                     call_text_model, compose_system)
from modules.teaching.store import (SessionNotFound, TeachingInvalid,   # noqa: E402
                                    public_session)

TEXT_SCENE = "text_chat"
DEFAULT_STUDENT = "default"
MODEL_TIMEOUT = 20.0
KNOWLEDGE_TOP_K = 3
MAX_HISTORY_TURNS = 12
MAX_MEMORY_ITEMS_PER_END = 20
MEMORY_INJECT_LIMIT = 4
MAX_STUDENT_CHARS = 64

SCOPE_NOTE = ("当前环境尚未实现独立的学员身份认证：student_id 是同一管理员下的学习范围标签，"
              "用于保证不同学生、不同老师的记录互不混合；它不是身份认证边界。"
              "读取与写入均按 (student_id, teacher_id) 作用域过滤。")

_MEMORY_BOUNDARY_CODES = {
    "credential_missing": 400, "endpoint_missing": 400,
    "endpoint_not_allowed": 400, "redirect_refused": 400,
}

# ---- error mapping --------------------------------------------------------

def _map(exc):
    if isinstance(exc, _ApiError):
        return exc
    if isinstance(exc, StoreLockTimeout):
        return _ApiError(503, "store_busy")
    if isinstance(exc, StoreUnavailable):
        return _ApiError(503, "store_unavailable", getattr(exc, "reason", None))
    if isinstance(exc, PersistError):
        return _ApiError(500, "persist_failed")
    if isinstance(exc, SessionNotFound):
        return _ApiError(404, "not_found", str(exc))
    if isinstance(exc, TeachingInvalid):
        msg = str(exc)
        return _ApiError(400, "teaching_invalid",
                         "；".join(getattr(exc, "errors", []) or [msg]))
    if isinstance(exc, MBoundary):
        return _ApiError(400, "boundary_violation", str(exc)[:160])
    if isinstance(exc, TextModelError):
        status = _MEMORY_BOUNDARY_CODES.get(exc.code, 502)
        return _ApiError(status, exc.code, exc.detail or None)
    return None


def _guard(fn):
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except Exception as e:  # noqa: BLE001
            mapped = _map(e)
            if mapped is None:
                log.warning("teaching api error in %s: %r", fn.__name__, e)
                return _err(request, 500, "internal_error")
            return _err(request, mapped.status, mapped.code, mapped.detail)
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


def _teacher_store(request):
    return _need(request, "teacher")


def _teaching_store(request):
    return _need(request, "teaching")


def _registry(request):
    return getattr(_stores(request), "model_registry", None)


def _creds(request):
    return getattr(_stores(request), "model_credentials", None)


def _knowledge(request):
    return getattr(_stores(request), "knowledge", None)


def _principal(request):
    """The authenticated operator identity (server-side)."""
    mode = request.get("admin_auth_mode") or "unknown"
    user = request.get("admin_user") or "operator"
    return "%s:%s" % (mode, user)


def _student_id(body):
    v = body.get("student_id")
    if v is None or str(v).strip() == "":
        return DEFAULT_STUDENT
    s = str(v).strip()
    if len(s) > MAX_STUDENT_CHARS or any(ord(c) < 32 for c in s) or "\x7f" in s:
        raise _ApiError(400, "invalid_json", detail="student_id 不合法")
    return s


# ---- capability resolution ------------------------------------------------

def _model_usable(request, model_id, scene):
    reg, creds = _registry(request), _creds(request)
    if reg is None or not model_id:
        return False, "model_missing"
    ok, code, _ = enable_gate(reg, creds, model_id, scene=scene, action="teaching")
    return bool(ok), (code or "ok")


def _teacher_text_capability(request, rec):
    """Server-side text-teaching capability of one teacher record."""
    if not rec.get("enabled"):
        return {"can_teach_text": False, "reason": "teacher_disabled"}
    if rec.get("frozen"):
        # the frozen default teacher is the realtime production link; it has no
        # text model bound and this round must not touch it
        return {"can_teach_text": False, "reason": "frozen_realtime_only"}
    model = rec.get("model") or {}
    mid = model.get("text_model_id") or ""
    if not mid:
        return {"can_teach_text": False, "reason": "text_model_not_configured"}
    reg = _registry(request)
    mrec = reg.get_model(mid) if reg is not None else None
    if mrec is None:
        return {"can_teach_text": False, "reason": "model_missing", "model_id": mid}
    if not mrec.get("enabled"):
        # a disabled model is not usable even if it once passed verification
        return {"can_teach_text": False, "reason": "model_disabled", "model_id": mid}
    ok, code = _model_usable(request, mid, TEXT_SCENE)
    if not ok:
        return {"can_teach_text": False, "reason": code, "model_id": mid}
    prov = reg.get_provider(mrec["provider_id"]) if reg is not None else None
    return {"can_teach_text": True, "reason": "ok", "model_id": mid,
            "model_name": mrec.get("display_name") or mrec.get("model_key"),
            "model_key": mrec.get("model_key"),
            "provider_id": mrec.get("provider_id"),
            "model_is_local": _provider_is_local(prov)}


def _provider_is_local(prov):
    """A local (loopback) upstream is a reproducible TEST model, never a cloud one."""
    if not prov:
        return False
    base = str(prov.get("base_url") or "")
    if not (prov.get("allow_local") or False):
        return False
    return bool(base.startswith("http://127.0.0.1") or base.startswith("http://localhost")
                or base.startswith("http://[::1]"))


def _authorized_datasets(request, rec):
    """Datasets this teacher is authorized to teach from (references resolved)."""
    ids = list((rec.get("knowledge") or {}).get("dataset_ids") or [])
    kb = _knowledge(request)
    out, missing = [], []
    known = {}
    if kb is not None:
        try:
            for ds in kb.list_datasets():
                known[ds["id"]] = ds
        except Exception as e:  # noqa: BLE001
            log.warning("teaching knowledge resolve skipped: %r", e)
    for i in ids:
        ds = known.get(i)
        if ds is None:
            missing.append(i)
            continue
        out.append({"id": i, "name": ds.get("name"),
                    "enabled": ds.get("status") == "enabled"})
    return out, missing


def _resolve_binding(request, teacher):
    """Resolve the teacher's text model into a concrete, callable binding.

    Raises a coded :class:`_ApiError` when the teacher cannot really teach text.
    """
    cap = _teacher_text_capability(request, teacher)
    if not cap["can_teach_text"]:
        reason = cap["reason"]
        friendly = {
            "teacher_disabled": "该老师已停用，请先在「AI 老师与教学」中启用。",
            "frozen_realtime_only": "该老师是内置的实时语音老师（冻结链路），"
                                    "本轮文字教学不涉及它；请选择或新建一位文字老师。",
            "text_model_not_configured": "该老师还没有绑定文字模型，"
                                         "请先在老师编辑中为「文字教学」选择并启用一个模型。",
            "model_missing": "该老师绑定的文字模型不存在，请重新选择模型。",
            "model_disabled": "该老师绑定的文字模型已停用，请先在「AI 模型与连接」中启用它。",
            "evidence_missing": "该老师绑定的文字模型尚未通过能力检测，请先完成检测。",
            "credential_missing": "该老师绑定的文字模型还没有配置密钥，请先保存密钥。",
            "capability_mismatch": "该老师绑定的模型不具备文字对话能力，请改选其他模型。",
            "frozen_model": "该老师绑定的是只读的内置模型，请改选一个可用的文字模型。",
            "not_found": "该老师绑定的文字模型不存在，请重新选择模型。",
        }.get(reason, "该老师当前无法开展文字教学（原因：%s）。" % reason)
        raise _ApiError(400, reason if reason != "ok" else "text_model_unusable", friendly)
    reg, creds = _registry(request), _creds(request)
    mid = cap["model_id"]
    mrec = reg.get_model(mid)
    if mrec is None:
        raise _ApiError(400, "not_found", "该老师绑定的文字模型不存在，请重新选择模型。")
    prov = reg.get_provider(mrec["provider_id"])
    if prov is None:
        raise _ApiError(400, "not_found", "该模型所属服务商不存在，请重新配置。")
    ref = creds.current_ref(prov["id"])
    if not ref:
        raise _ApiError(400, "credential_missing",
                        "该服务商还没有可用密钥，请先在「凭据管理」中保存密钥。")
    return {"model_id": mid, "model_key": mrec.get("model_key"),
            "provider_id": prov["id"], "protocol": mrec.get("protocol")
            or prov.get("protocol"), "base_url": prov.get("base_url"),
            "allow_local": bool(prov.get("allow_local")),
            "credential_ref": ref, "model_is_local": _provider_is_local(prov)}


def _read_secret(request, binding):
    creds = _creds(request)
    try:
        return creds.read_secret(binding["credential_ref"])
    except Exception as e:  # noqa: BLE001  (never echo the secret or the ref)
        log.warning("teaching credential read failed: %r", type(e).__name__)
        raise _ApiError(400, "credential_missing",
                        "凭据无法读取，请重新保存该服务商的密钥。")


# 服务商的场景化可用性原因 → 中文提示（文字教室与语音教室共用同一套判定）
SCENE_REASONS = {
    "model_missing": "绑定的模型不存在，请重新选择模型。",
    "model_disabled": "绑定的模型已停用，请先在「AI 模型与连接」中启用它。",
    "evidence_missing": "绑定的模型尚未通过能力检测，请先完成检测。",
    "credential_missing": "绑定的模型还没有配置密钥，请先保存密钥。",
    "capability_mismatch": "绑定的模型不具备该场景需要的能力，请改选其他模型。",
    "frozen_model": "绑定的是只读的内置模型，请改选一个可用的模型。",
    "not_found": "绑定的模型或服务商不存在，请重新配置。",
}


def resolve_model_binding(request, model_id, scene, *, label="模型"):
    """Resolve ONE registry model into a concrete, callable binding for a scene.

    Shared by the text classroom and the voice classroom so both go through the
    **same** server-side evidence + credential gate — a voice class can never
    reach a model the text class would have refused, and neither can be widened by
    a request body.  Raises a coded :class:`_ApiError` on refusal.
    """
    reg, creds = _registry(request), _creds(request)
    if reg is None or creds is None:
        raise _ApiError(503, "model_registry_not_configured")
    mid = str(model_id or "")
    if not mid:
        raise _ApiError(400, "model_not_configured",
                        "%s 还没有配置：请在「AI 老师与教学」中为它选择一个模型。" % label)
    mrec = reg.get_model(mid)
    if mrec is None:
        raise _ApiError(400, "not_found", "%s 不存在，请重新选择。" % label)
    if mrec.get("frozen"):
        raise _ApiError(400, "frozen_model", SCENE_REASONS["frozen_model"])
    if not mrec.get("enabled"):
        raise _ApiError(400, "model_disabled", SCENE_REASONS["model_disabled"])
    ok, code, _ = enable_gate(reg, creds, mid, scene=scene, action="teaching")
    if not ok:
        raise _ApiError(400, code or "model_unusable",
                        SCENE_REASONS.get(code or "", "%s 当前不可用。" % label))
    prov = reg.get_provider(mrec["provider_id"])
    if prov is None:
        raise _ApiError(400, "not_found", "该模型所属服务商不存在，请重新配置。")
    ref = creds.current_ref(prov["id"])
    if not ref:
        raise _ApiError(400, "credential_missing", SCENE_REASONS["credential_missing"])
    return {"model_id": mid, "model_key": mrec.get("model_key"),
            "provider_id": prov["id"], "protocol": mrec.get("protocol")
            or prov.get("protocol"), "base_url": prov.get("base_url"),
            "allow_local": bool(prov.get("allow_local")),
            "credential_ref": ref, "model_is_local": _provider_is_local(prov),
            "model_name": mrec.get("display_name") or mrec.get("model_key")}


# ---- retrieval (confined to the session's authorized datasets) -------------

def _retrieve(request, sess, query):
    ids = list(sess.get("knowledge_dataset_ids") or [])
    if not ids:
        return [], "no_material"
    kb = _knowledge(request)
    if kb is None:
        return [], "knowledge_not_configured"
    merged = {}
    for ds_id in ids:
        try:
            for r in kb.search(query, dataset_id=ds_id, top_k=KNOWLEDGE_TOP_K):
                prev = merged.get(r["chunk_id"])
                if prev is None or r["score"] > prev["score"]:
                    merged[r["chunk_id"]] = r
        except Exception as e:  # noqa: BLE001
            log.warning("teaching retrieval skipped for %s: %r", ds_id, e)
    results = sorted(merged.values(), key=lambda r: (-r["score"], r["chunk_id"]))
    results = results[:KNOWLEDGE_TOP_K]
    return results, ("found" if results else "no_match")


def _source_rows(results):
    return [{"dataset_id": r.get("dataset_id"), "dataset_name": r.get("dataset_name"),
             "document_id": r.get("document_id"),
             "document_title": r.get("document_title")} for r in results]


def _memory_context(request, sess):
    """Bounded, teacher-scoped learner memory for this turn ('' when none)."""
    mem_file = getattr(_stores(request), "memory", None)
    path = getattr(mem_file, "path", "") if mem_file is not None else ""
    if not path:
        return ""
    try:
        store = MemoryStore(path, user=sess["student_id"]).load()
        items = store.list_items(teacher_id=sess["teacher_id"], include_expired=False)
        items = items[-MEMORY_INJECT_LIMIT:]
        block = render_memory_block(items)
        return block if isinstance(block, str) else ""
    except Exception as e:  # noqa: BLE001  (memory is an enhancement, never an error)
        log.warning("teaching memory context skipped: %r", e)
        return ""


def _build_system(request, sess, results, retrieval_state):
    parts = [compose_system(sess.get("teaching_policy") or {},
                            course_id=sess.get("course_id") or "")]
    if retrieval_state == "no_material":
        parts.append("说明：本老师尚未关联教材，请以通用教学方式回答，"
                     "并如实说明没有专门教材可参考。")
    else:
        parts.append(render_knowledge_block("", results, max_chars=1200))
    mem = _memory_context(request, sess)
    if mem:
        parts.append(mem)
    return "\n\n".join(p for p in parts if p)


# ---- read -----------------------------------------------------------------

@_guard
async def overview(request):
    store = _teacher_store(request)
    rows = []
    for rec in store.list_teachers():
        cap = _teacher_text_capability(request, rec)
        datasets, missing = _authorized_datasets(request, rec)
        rows.append({
            "teacher_id": rec["teacher_id"], "name": rec.get("name"),
            "subject": rec.get("subject"), "enabled": bool(rec.get("enabled")),
            "frozen": bool(rec.get("frozen")), "is_default": bool(rec.get("is_default")),
            "teaching_style": rec.get("teaching_style"),
            "can_teach_text": cap["can_teach_text"], "reason": cap["reason"],
            "text_model": ({"id": cap.get("model_id"), "name": cap.get("model_name"),
                            "is_local": cap.get("model_is_local")}
                           if cap.get("can_teach_text") else None),
            "datasets": datasets, "datasets_missing": missing,
        })
    any_text = any(r["can_teach_text"] for r in rows)
    return _ok(request, {"available": True, "teachers": rows,
                         "any_text_teacher": any_text,
                         "scope_note": SCOPE_NOTE,
                         "principal": _principal(request),
                         "note": "「可开展文字教学」由服务端依据已存验证证据与密钥判定；"
                                 "未通过检测或缺少密钥的老师不会被标记为可用。"})


@_guard
async def sessions_list(request):
    store = _teaching_store(request)
    teacher_id = request.query.get("teacher_id")
    student_id = request.query.get("student_id")
    limit = _int_arg(request, "limit", 50, 200)
    rows = store.list_sessions(teacher_id=teacher_id, student_id=student_id,
                               limit=limit)
    return _ok(request, {"available": True, "count": len(rows),
                         "sessions": [public_session(r, include_turns=False) for r in rows],
                         "counts": store.counts(),
                         "teacher_id": teacher_id, "student_id": student_id,
                         "scope_note": SCOPE_NOTE})


@_guard
async def session_get(request):
    store = _teaching_store(request)
    rec = store.get_session(request.match_info["session_id"])
    if rec is None:
        raise _ApiError(404, "not_found")
    return _ok(request, {"available": True, "session": public_session(rec),
                         "scope_note": SCOPE_NOTE})


# ---- start / message / end -------------------------------------------------

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

    binding = _resolve_binding(request, teacher)
    datasets, missing = _authorized_datasets(request, teacher)
    authorized_ids = [d["id"] for d in datasets if d["enabled"]]
    student_id = _student_id(body)
    course_id = body.get("course_id") if isinstance(body.get("course_id"), str) else ""

    policy = {
        "teaching_style": teacher.get("teaching_style"),
        "subject": teacher.get("subject"), "language": teacher.get("language"),
        "system_instruction": teacher.get("system_instruction") or "",
        "default_strategy": teacher.get("default_strategy") or "",
        "course_id": course_id,
    }
    scope_note = ("本会话只能检索该老师授权资料集：%s" %
                  ("、".join(d["name"] or d["id"] for d in datasets) if datasets
                   else "（未关联教材，将开展一般教学）"))
    sess = _teaching_store(request).create_session(
        teacher_id=tid, teacher_name=teacher.get("name") or "",
        student_id=student_id, model_id=binding["model_id"],
        model_key=binding["model_key"], provider_id=binding["provider_id"],
        knowledge_dataset_ids=authorized_ids, course_id=course_id,
        teaching_policy=policy, model_is_local=binding["model_is_local"],
        knowledge_scope_note=scope_note)
    _audit(request, "teaching_session_start", subject=sess["session_id"],
           changed=["teacher=%s" % tid, "model=%s" % binding["model_id"]])
    out = public_session(sess)
    out["material"] = {"datasets": datasets, "datasets_missing": missing,
                       "linked": bool(datasets),
                       "retrieval_scope": authorized_ids}
    out["model_is_local"] = binding["model_is_local"]
    return _ok(request, {"available": True, "session": out,
                         "scope_note": SCOPE_NOTE})


@_guard
async def session_message(request):
    store = _teaching_store(request)
    rec = store.get_session(request.match_info["session_id"])
    if rec is None:
        raise _ApiError(404, "not_found")
    if rec.get("status") != "active":
        raise _ApiError(400, "session_ended", detail="本节课已结束，请重新开始上课。")
    body = await _body(request)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _ApiError(400, "invalid_json", detail="text string required")
    text = text.strip()[:4000]

    # ---- authorization: session's snapshotted datasets only (server-side) ----
    results, retrieval_state = _retrieve(request, rec, text)

    # ---- model binding: re-resolve the SAME model the session was started with --
    teacher = _teacher_store(request).get_teacher(rec["teacher_id"])
    if teacher is None:
        raise _ApiError(409, "teacher_missing",
                        detail="该课程所属老师已被删除，无法继续。")
    binding = _resolve_binding(request, teacher)
    if binding["model_id"] != rec["model_id"]:
        # the teacher's binding changed since the class started: refuse rather than
        # silently answer with a different model than the session recorded
        raise _ApiError(409, "model_binding_changed",
                        detail="该老师绑定的文字模型已变更，请重新开始上课以保持一致。")
    secret = _read_secret(request, binding)

    system = _build_system(request, rec, results, retrieval_state)
    messages = build_messages(rec.get("turns") or [], text,
                              max_history=MAX_HISTORY_TURNS)
    # real call, off the event loop (never fabricates on failure)
    out = await asyncio.to_thread(
        call_text_model, protocol=binding["protocol"], base_url=binding["base_url"],
        model_key=binding["model_key"], secret=secret, system=system,
        messages=messages, timeout=MODEL_TIMEOUT,
        allow_local=binding["allow_local"],
        resolver=request.app.get("model_endpoint_resolver"))

    sources = _source_rows(results)
    store.append_turn(rec["session_id"], role="student", text=text)
    store.append_turn(rec["session_id"], role="teacher", text=out["text"],
                      sources=sources, model_id=binding["model_id"])
    _audit(request, "teaching_session_message", subject=rec["session_id"],
           changed=["sources=%d" % len(sources)])
    return _ok(request, {"available": True, "reply": out["text"],
                         "sources": sources,
                         "material_state": retrieval_state,
                         "model_id": binding["model_id"],
                         "model_is_local": bool(binding["model_is_local"]),
                         "scope_note": SCOPE_NOTE})


@_guard
async def session_end(request):
    store = _teaching_store(request)
    rec = store.get_session(request.match_info["session_id"])
    if rec is None:
        raise _ApiError(404, "not_found")
    body = await _body(request)
    outcome = body.get("outcome")
    if outcome is not None and not isinstance(outcome, dict):
        raise _ApiError(400, "invalid_json", detail="outcome object required")
    saved = store.end_session(rec["session_id"], outcome=outcome)
    mem_saved, mem_rejected = _persist_memory(request, rec, body.get("memory_items"))
    _audit(request, "teaching_session_end", subject=rec["session_id"],
           changed=["memory_saved=%d" % len(mem_saved),
                    "memory_rejected=%d" % len(mem_rejected)])
    return _ok(request, {"available": True, "session": public_session(saved),
                         "memory_saved": mem_saved, "memory_rejected": mem_rejected,
                         "scope_note": SCOPE_NOTE})


def _persist_memory(request, sess, memory_items):
    """Write explicit learner facts into the (student × teacher) memory scope.

    Fail-soft per item: a boundary-violating item is reported, never silently
    dropped and never turned into a failed request.  The teacher namespace keeps
    same-named fields of two teachers apart.
    """
    if not isinstance(memory_items, (list, tuple)) or not memory_items:
        return [], []
    mem = getattr(_stores(request), "memory", None)
    path = getattr(mem, "path", "") if mem is not None else ""
    if not path:
        return [], [{"reason": "memory_not_configured"}]
    store = MemoryStore(path, user=sess["student_id"])
    saved, rejected = [], []
    for it in list(memory_items)[:MAX_MEMORY_ITEMS_PER_END]:
        if not isinstance(it, dict):
            rejected.append({"reason": "invalid_item"})
            continue
        entity, key = it.get("entity"), it.get("key")
        value = it.get("value")
        if not isinstance(entity, str) or not isinstance(key, str):
            rejected.append({"entity": entity, "key": key, "reason": "invalid_item"})
            continue
        try:
            store.save(entity, key, value, source="teaching_session",
                       confidence=float(it.get("confidence") or 1.0),
                       teacher_id=sess["teacher_id"])
            saved.append({"entity": entity, "key": key})
        except MBoundary as e:
            # never echo a secret-shaped key/value (validation is the source)
            rejected.append({"entity": entity, "key": key,
                             "reason": str(e)[:100]})
        except Exception as e:  # noqa: BLE001
            rejected.append({"entity": entity, "key": key,
                             "reason": type(e).__name__})
    return saved, rejected


# ---- route table ----------------------------------------------------------

def api_route_table_teaching():
    return [
        ("GET", "/admin/teaching/overview"),
        ("POST", "/admin/teaching/sessions"),
        ("GET", "/admin/teaching/sessions"),
        ("GET", "/admin/teaching/sessions/{session_id}"),
        ("POST", "/admin/teaching/sessions/{session_id}/messages"),
        ("POST", "/admin/teaching/sessions/{session_id}/end"),
    ]


def mount_teaching(app):
    routes = [
        ("get", "/admin/teaching/overview", overview),
        ("post", "/admin/teaching/sessions", session_start),
        ("get", "/admin/teaching/sessions", sessions_list),
        ("get", "/admin/teaching/sessions/{session_id}", session_get),
        ("post", "/admin/teaching/sessions/{session_id}/messages", session_message),
        ("post", "/admin/teaching/sessions/{session_id}/end", session_end),
    ]
    for method, path, handler in routes:
        app.router.add_route(method.upper(), path, handler)
