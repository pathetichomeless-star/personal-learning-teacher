"""ADMIN-2 control-plane API — additive write surface over the ADMIN-1 read-only plane.

Mounted **only** when the store bundle is wired (`create_admin_app(stores=…)`);
without it the app exposes exactly the ADMIN-1 six GET routes (full backward
compatibility).

Every write follows: AUTH (middleware) → VALIDATE → PREVIEW where meaningful →
EXPLICIT APPLY (confirm token) → READ-BACK (re-read from the store) → AUDIT.
There is no silent mutation, no ``/admin/diag/reset``, and no Workbench write
route (the Workbench section is GET-only by construction — no POST handler is
registered for any workbench path).

Errors are coded and sanitized: store values, tokens, file paths, transcripts
and secrets never appear in responses or logs.
"""

import asyncio
import functools
import logging

from aiohttp import web

from .registry import sessions as admin_sessions
from .stores import AdminStores            # noqa: F401  (runs the modules bootstrap)

log = logging.getLogger("rtl.admin.api")

from modules._store_lock import StoreLockTimeout                       # noqa: E402
from modules.intent import behavior as intent                          # noqa: E402
from modules.knowledge.store import (CapExceeded as KCapExceeded,      # noqa: E402
                                     ConfirmRequired as KConfirmRequired,
                                     DuplicateContent as KDuplicateContent,
                                     KnowledgeError as KError,
                                     KnowledgeStore as KStore,
                                     MalformedDocument as KMalformed,
                                     PersistError as KPersist,
                                     StoreUnavailable as KUnavailable)
from modules.memory.store import (BoundaryViolation as MBoundary,      # noqa: E402
                                  ConfirmRequired as MConfirmRequired,
                                  MemoryStore as MStore,
                                  PersistError as MPersist)
from modules.policy.persona import (PersistError as PPersist,          # noqa: E402
                                    PolicyInvalid,
                                    PolicyStore as PStore,
                                    render_policy_overview)

MAX_BODY = 64 * 1024
WB_TIMEOUT = 2.0


def _rid(request):
    return request.get("request_id", "")


def _ok(request, payload):
    payload = dict(payload)
    payload["request_id"] = _rid(request)
    return web.json_response(payload)


def _err(request, status, code, detail=None, extra=None):
    body = {"error": code}
    if detail:
        body["detail"] = str(detail)
    if extra:
        body.update(extra)
    body["request_id"] = _rid(request)
    return web.json_response(body, status=status)


class _ApiError(Exception):
    def __init__(self, status, code, detail=None, extra=None):
        super().__init__(code)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def _guard(fn):
    """Uniform error mapping: coded, sanitized, never leaks store internals."""
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except (_ApiError,) as e:
            return _err(request, e.status, e.code, e.detail, e.extra)
        except (MPersist, KPersist, PPersist) as e:
            # a mutation that could not be made durable is never reported as success
            log.warning("admin persist failure in %s: %s", fn.__name__, e)
            return _err(request, 500, "persist_failed")
        except StoreLockTimeout as e:
            # the cross-process store lock is held elsewhere: refuse honestly and
            # bounded rather than freezing the shared event loop (RED-A-R3-01)
            log.warning("admin store busy in %s: %s", fn.__name__, e)
            return _err(request, 503, "store_busy")
        except KUnavailable as e:
            # V4 §4: a corrupt / unknown-version file is REFUSED, never silently
            # treated as an empty store (that would clobber real data on write).
            log.warning("admin store unavailable in %s: %s", fn.__name__, e)
            return _err(request, 503, "store_unavailable", getattr(e, "reason", None))
        except (KConfirmRequired, MConfirmRequired) as e:
            return _err(request, 400, "confirm_required", e)
        except (MBoundary, PolicyInvalid) as e:
            # bounded error list: a wide document must not amplify the response (R2-05)
            extra = {"errors": list(e.errors)[:50]} if isinstance(e, PolicyInvalid) else None
            return _err(request, 400,
                        "policy_invalid" if isinstance(e, PolicyInvalid)
                        else "boundary_violation", None, extra)
        except KDuplicateContent as e:
            return _err(request, 409, "duplicate_content",
                        extra={"existing_doc_id": e.existing_doc_id})
        except KMalformed as e:
            return _err(request, 400, "malformed_document", e)
        except KCapExceeded as e:
            return _err(request, 409, "cap_exceeded", e)
        except KError as e:
            return _err(request, 400, "knowledge_error", e)
        except asyncio.TimeoutError:
            return _err(request, 504, "upstream_timeout")
        except Exception as e:  # noqa: BLE001  (never leak internals)
            log.warning("admin api error in %s: %r", fn.__name__, e)
            return _err(request, 500, "internal_error")
    return wrapper


async def _body(request):
    if request.content_length and request.content_length > MAX_BODY:
        raise _ApiError(413, "body_too_large")
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise _ApiError(400, "invalid_json")
    if not isinstance(data, dict):
        raise _ApiError(400, "invalid_json")
    return data


def _need(request, name):
    stores = request.app["admin_stores"]
    store = getattr(stores, name, None)
    if store is None:
        raise _ApiError(503, "%s_not_configured" % name)
    return store


def _fresh(store):
    """Pick up external writers before reading (two-writer topology).

    The learner memory is written by the *gateway* conversation path while the
    admin plane reads it; they are separate store instances over one file, so a
    read that skipped the file-signature reload would serve a stale view.  The
    reload is bounded, fail-soft and read-only (no audio-plane effect).
    """
    try:
        store.reload_if_changed()
    except Exception as e:  # noqa: BLE001  (never fail a read because of a refresh)
        log.warning("admin store refresh skipped: %r", e)
    return store


def _need_avail(store):
    """Refuse a READ when the store is unavailable (contract §4.2).

    A corrupt / unknown-version file must never be presented as an empty store:
    ``503 store_unavailable`` is the honest answer, for reads as well as writes.
    """
    if hasattr(store, "available") and not store.available:
        reason = None
        try:
            reason = store.state().get("reason")
        except Exception:  # noqa: BLE001
            pass
        raise _ApiError(503, "store_unavailable", reason)
    return store


# ---- durable read-back ----------------------------------------------------
# The write handlers must verify DURABLE state, not the in-memory object they just
# mutated: re-reading through a NEW instance is the only honest check (adversarial
# findings RED-D-01 / RED-H-01 — a failed flush used to be reported as success).

def _disk_memory_item(store, item_id):
    ok, item = _disk_memory_state(store, item_id)
    return item if ok else None


def _disk_memory_state(store, item_id):
    """(read_ok, item) from a NEW instance — fail-CLOSED: an unreadable disk is not
    evidence that a delete or edit succeeded (adversarial INFO, RED-H round 3)."""
    try:
        it = MStore(store.path, user=getattr(store, "user", "default")).load().inspect(item_id)
        return True, it
    except Exception as e:  # noqa: BLE001
        log.warning("memory disk read-back failed: %r", e)
        return False, None


def _disk_memory_summary(store):
    try:
        return MStore(store.path, user=getattr(store, "user", "default")).load().category_summary()
    except Exception as e:  # noqa: BLE001
        log.warning("memory disk read-back failed: %r", e)
        return None


def _disk_knowledge(store):
    try:
        return KStore(store.path).load()
    except Exception as e:  # noqa: BLE001
        log.warning("knowledge disk read-back failed: %r", e)
        return None


def _disk_policy(store):
    try:
        return PStore(store.path).load().active()
    except Exception as e:  # noqa: BLE001
        log.warning("policy disk read-back failed: %r", e)
        return None


def _audit(request, action, *, subject=None, changed=None):
    """Diagnostic audit append that can never fail a request.

    The write is already durable and read back when this runs, so a failing audit must
    not turn a committed change into an error response (adversarial finding R3-E-2).
    """
    try:
        request.app["admin_stores"].audit.append(action, subject=subject,
                                                 changed=changed)
    except Exception as e:  # noqa: BLE001
        log.warning("admin audit append failed: %r", e)


def _durable(request, ok, detail="the change is not durable on disk"):
    """Refuse to claim success when the durable read-back disagrees."""
    if not ok:
        raise _ApiError(500, "persist_failed", detail=detail)


def _int_arg(request, name, default, cap):
    try:
        v = int(request.query.get(name, default) or default)
    except (TypeError, ValueError):
        raise _ApiError(400, "invalid_query", detail="%s must be an int" % name)
    return max(0, min(v, cap))


def _confirm(body, what="confirm"):
    """Explicit confirmation is mandatory for every destructive write."""
    if body.get(what) is not True:
        raise _ApiError(400, "confirm_required",
                        detail="%s: true is required" % what)


# ---------------------------------------------------------------------------
# PERSONA / POLICY
# ---------------------------------------------------------------------------

@_guard
async def policy_active(request):
    store = _need(request, "policy")
    active = store.active()
    return _ok(request, {"available": True, "version": active["version"],
                         "updated_at": active["updated_at"],
                         "actor": active["actor"],
                         "policy": active["policy"],
                         "rendered_preview": render_policy_overview(active["policy"])})


@_guard
async def policy_versions(request):
    store = _need(request, "policy")
    return _ok(request, {"available": True, "versions": store.versions()})


@_guard
async def policy_audit(request):
    store = _need(request, "policy")
    return _ok(request, {"available": True, "audit": store.audit(50)})


@_guard
async def policy_preview(request):
    store = _need(request, "policy")
    body = await _body(request)
    candidate = body.get("policy")
    if not isinstance(candidate, dict):
        raise _ApiError(400, "invalid_json", detail="policy object required")
    return _ok(request, store.preview(candidate))


@_guard
async def policy_apply(request):
    store = _need(request, "policy")
    body = await _body(request)
    _confirm(body)
    candidate = body.get("policy")
    if not isinstance(candidate, dict):
        raise _ApiError(400, "invalid_json", detail="policy object required")
    applied = store.apply(candidate, actor=str(body.get("actor") or "admin"),
                          reason=str(body.get("reason") or ""))
    readback = _disk_policy(store)                  # READ-BACK from DISK
    _audit(request, 
        "policy_apply", subject="v%d" % applied["version"],
        changed=applied["changed_keys"])
    _durable(request, bool(readback) and readback["version"] == applied["version"])
    return _ok(request, {"available": True, "applied": applied,
                         "active": {"version": readback["version"],
                                    "updated_at": readback["updated_at"]},
                         "readback_ok": True})


@_guard
async def policy_rollback(request):
    store = _need(request, "policy")
    body = await _body(request)
    _confirm(body)
    version = body.get("version")
    if not isinstance(version, int):
        raise _ApiError(400, "invalid_json", detail="version int required")
    out = store.rollback(version, actor=str(body.get("actor") or "admin"))
    readback = _disk_policy(store)                  # READ-BACK from DISK
    _audit(request, 
        "policy_rollback", subject="v%d" % version, changed=out["changed_keys"])
    _durable(request, bool(readback) and readback["version"] == out["version"])
    return _ok(request, {"available": True, "applied": out,
                         "active": {"version": readback["version"],
                                    "updated_at": readback["updated_at"]},
                         "readback_ok": True})


# ---------------------------------------------------------------------------
# MEMORY
# ---------------------------------------------------------------------------

@_guard
async def memory_items(request):
    store = _fresh(_need(request, "memory"))
    entity = request.query.get("entity") or None
    limit = _int_arg(request, "limit", 100, 200)
    # P1: optional teacher attribution filter.  Absent = every teacher;
    # present (even empty) = that exact scope.
    teacher_id = request.query.get("teacher_id")
    rows = store.list_items(entity=entity, include_expired=True,
                            teacher_id=teacher_id)[-limit:]
    return _ok(request, {"available": True, "count": len(rows), "items": rows,
                         "teacher_id": teacher_id,
                         "category_summary": store.category_summary()})


@_guard
async def memory_search(request):
    store = _fresh(_need(request, "memory"))
    q = request.query.get("q") or ""
    if not q.strip():
        raise _ApiError(400, "invalid_query", detail="q required")
    rows = store.search(q, limit=_int_arg(request, "limit", 20, 100))
    return _ok(request, {"available": True, "count": len(rows), "items": rows})


@_guard
async def memory_item(request):
    store = _fresh(_need(request, "memory"))
    row = store.inspect(request.match_info["item_id"])
    if row is None:
        raise _ApiError(404, "not_found")
    return _ok(request, {"available": True, "item": row})


@_guard
async def memory_edit(request):
    store = _need(request, "memory")
    body = await _body(request)
    item_id = body.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise _ApiError(400, "invalid_json", detail="id required")
    changed = [k for k in ("value", "confidence") if k in body]
    row = store.edit(item_id, value=body.get("value"),
                     confidence=body.get("confidence"))
    read_ok, readback = _disk_memory_state(store, item_id)   # READ-BACK from DISK
    _durable(request, read_ok and readback is not None
             and readback.get("updated_at") == row.get("updated_at"))
    _audit(request, 
        "memory_edit", subject=item_id, changed=changed)
    return _ok(request, {"available": True, "item": row, "readback_ok": True})


@_guard
async def memory_delete(request):
    store = _need(request, "memory")
    body = await _body(request)
    _confirm(body)
    item_id = body.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise _ApiError(400, "invalid_json", detail="id required")
    removed = store.delete(item_id)
    if not removed:
        raise _ApiError(404, "not_found")
    read_ok, still_there = _disk_memory_state(store, item_id)
    _durable(request, read_ok and still_there is None)             # gone on DISK
    _audit(request, "memory_delete", subject=item_id)
    return _ok(request, {"available": True, "deleted": True, "readback_ok": True})


@_guard
async def memory_clear_category(request):
    store = _need(request, "memory")
    body = await _body(request)
    entity = body.get("entity")
    if not isinstance(entity, str) or not entity:
        raise _ApiError(400, "invalid_json", detail="entity required")
    if str(body.get("confirm") or "") != entity:
        raise _ApiError(400, "confirm_required",
                        detail="confirm must equal the category name")
    removed = store.forget_category(entity, confirm=entity)
    summary = _disk_memory_summary(store)                              # from DISK
    _durable(request, bool(summary)
             and (summary.get(entity) or {}).get("count") == 0)
    _audit(request, 
        "memory_clear_category", subject=entity, changed=["removed:%d" % removed])
    return _ok(request, {"available": True, "removed": removed,
                         "category_summary": store.category_summary()})


@_guard
async def memory_diagnostics(request):
    store = _fresh(_need(request, "memory"))
    return _ok(request, {"available": True,
                         "boundary": store.boundary_diagnostics(),
                         "category_summary": store.category_summary()})


# ---------------------------------------------------------------------------
# KNOWLEDGE
# ---------------------------------------------------------------------------

@_guard
async def knowledge_datasets(request):
    store = _need_avail(_fresh(_need(request, "knowledge")))
    rows = store.list_datasets()
    return _ok(request, {"available": True, "count": len(rows), "datasets": rows,
                         "diagnostics": store.diagnostics()})


@_guard
async def knowledge_dataset_create(request):
    store = _need(request, "knowledge")
    body = await _body(request)
    if not isinstance(body.get("name"), str):
        raise _ApiError(400, "invalid_json", detail="name string required")
    if body.get("description") is not None \
            and not isinstance(body["description"], str):
        raise _ApiError(400, "invalid_json", detail="description string required")
    tags = body.get("tags")
    if tags is not None and (not isinstance(tags, (list, tuple))
                             or any(not isinstance(t, str) for t in tags)):
        raise _ApiError(400, "invalid_json", detail="tags must be a list of strings")
    ds = store.create_dataset(body.get("name"), description=body.get("description") or "",
                              tags=tags)
    disk = _disk_knowledge(store)                       # READ-BACK from DISK
    _audit(request, "knowledge_dataset_create",
                                             subject=ds["id"])
    _durable(request, disk is not None and disk.get_dataset(ds["id"]) is not None)
    return _ok(request, {"available": True, "dataset": ds, "readback_ok": True})


@_guard
async def knowledge_dataset_rename(request):
    store = _need(request, "knowledge")
    body = await _body(request)
    ds_id, name = body.get("id"), body.get("name")
    if not isinstance(ds_id, str) or not isinstance(name, str):
        raise _ApiError(400, "invalid_json", detail="id and name required")
    ds = store.rename_dataset(ds_id, name)
    disk = _disk_knowledge(store)
    _audit(request, "knowledge_dataset_rename",
                                             subject=ds_id, changed=["name"])
    _durable(request, disk is not None
             and (disk.get_dataset(ds_id) or {}).get("name") == ds["name"])
    return _ok(request, {"available": True, "dataset": ds, "readback_ok": True})


@_guard
async def knowledge_dataset_enable(request):
    store = _need(request, "knowledge")
    body = await _body(request)
    ds_id, enabled = body.get("id"), body.get("enabled")
    if not isinstance(ds_id, str) or not isinstance(enabled, bool):
        raise _ApiError(400, "invalid_json", detail="id and enabled(bool) required")
    ds = store.set_dataset_enabled(ds_id, enabled)
    disk = _disk_knowledge(store)
    _audit(request, "knowledge_dataset_enable",
                                             subject=ds_id,
                                             changed=["status=%s" % ds["status"]])
    _durable(request, disk is not None
             and (disk.get_dataset(ds_id) or {}).get("status") == ds["status"])
    return _ok(request, {"available": True, "dataset": ds, "readback_ok": True})


@_guard
async def knowledge_dataset_preview(request):
    store = _need_avail(_need(request, "knowledge"))
    return _ok(request, {"available": True,
                         "preview": store.delete_dataset_preview(
                             request.match_info["ds_id"])})


@_guard
async def knowledge_dataset_delete(request):
    store = _need(request, "knowledge")
    body = await _body(request)
    ds_id = body.get("id")
    if not isinstance(ds_id, str):
        raise _ApiError(400, "invalid_json", detail="id required")
    if str(body.get("confirm") or "") != ds_id:
        raise _ApiError(400, "confirm_required",
                        detail="confirm must equal the dataset id")
    out = store.delete_dataset(ds_id, confirm=ds_id)
    disk = _disk_knowledge(store)
    _audit(request, "knowledge_dataset_delete",
                                             subject=ds_id)
    _durable(request, disk is not None and disk.get_dataset(ds_id) is None)
    return _ok(request, {"available": True, "deleted": out, "readback_ok": True})


@_guard
async def knowledge_dataset_documents(request):
    store = _need_avail(_fresh(_need(request, "knowledge")))
    rows = store.list_documents(dataset_id=request.match_info["ds_id"])
    return _ok(request, {"available": True, "count": len(rows), "documents": rows})


@_guard
async def knowledge_document_add(request):
    store = _need(request, "knowledge")
    body = await _body(request)
    ds_id, title, text = body.get("dataset_id"), body.get("title"), body.get("text")
    if not isinstance(ds_id, str) or not isinstance(title, str) \
            or not isinstance(text, str):
        raise _ApiError(400, "invalid_json",
                        detail="dataset_id, title and text required")
    if body.get("source_uri") is not None and not isinstance(body["source_uri"], str):
        raise _ApiError(400, "invalid_json", detail="source_uri string required")
    doc = store.add_document(ds_id, title, text,
                             source_type=str(body.get("source_type") or "text"),
                             source_uri=body.get("source_uri"),
                             tags=body.get("tags"), added_by="admin")
    disk = _disk_knowledge(store)                       # READ-BACK from DISK
    _audit(request, "knowledge_document_add",
                                             subject=doc["id"],
                                             changed=["chunks=%d" % doc["chunk_count"]])
    _durable(request, disk is not None and disk.get_document(doc["id"]) is not None)
    return _ok(request, {"available": True, "document": doc, "readback_ok": True})


@_guard
async def knowledge_document(request):
    store = _need_avail(_fresh(_need(request, "knowledge")))
    return _ok(request, {"available": True,
                         "inspection": store.inspect_document(
                             request.match_info["doc_id"])})


@_guard
async def knowledge_document_chunks(request):
    store = _need_avail(_fresh(_need(request, "knowledge")))
    limit = _int_arg(request, "limit", 100, 500)
    offset = _int_arg(request, "offset", 0, 100000)
    rows = store.list_chunks(request.match_info["doc_id"], limit=limit, offset=offset)
    return _ok(request, {"available": True, "count": len(rows), "chunks": rows})


@_guard
async def knowledge_document_delete(request):
    store = _need(request, "knowledge")
    body = await _body(request)
    _confirm(body)
    doc_id = body.get("id")
    if not isinstance(doc_id, str):
        raise _ApiError(400, "invalid_json", detail="id required")
    out = store.delete_document(doc_id)
    disk = _disk_knowledge(store)
    _audit(request, "knowledge_document_delete",
                                             subject=doc_id)
    _durable(request, disk is not None and disk.get_document(doc_id) is None)
    return _ok(request, {"available": True, "deleted": out, "readback_ok": True})


@_guard
async def knowledge_document_rebuild(request):
    store = _need(request, "knowledge")
    body = await _body(request)
    doc_id = body.get("id")
    if not isinstance(doc_id, str):
        raise _ApiError(400, "invalid_json", detail="id required")
    out = store.rebuild_chunks(doc_id)
    disk = _disk_knowledge(store)
    _audit(request, "knowledge_document_rebuild",
                                             subject=doc_id,
                                             changed=["chunks=%d" % out["chunks"]])
    doc = disk.get_document(doc_id) if disk is not None else None
    _durable(request, bool(doc) and doc.get("chunk_count") == out["chunks"])
    return _ok(request, {"available": True, "rebuilt": out, "readback_ok": True})


@_guard
async def knowledge_search(request):
    store = _need_avail(_fresh(_need(request, "knowledge")))
    body = await _body(request)
    q = body.get("query")
    if not isinstance(q, str) or not q.strip():
        raise _ApiError(400, "invalid_json", detail="query required")
    top_k = body.get("top_k")
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int)):
        # `True` is an int subclass but is never a valid top_k
        raise _ApiError(400, "invalid_json", detail="top_k must be an integer")
    results = store.search(q, top_k=top_k,
                           dataset_id=body.get("dataset_id"))
    return _ok(request, {"available": True, "count": len(results),
                         "results": results})


@_guard
async def knowledge_diagnostics(request):
    store = _need_avail(_fresh(_need(request, "knowledge")))
    return _ok(request, {"available": True, "diagnostics": store.diagnostics()})


# ---------------------------------------------------------------------------
# WORKBENCH (READ-ONLY — no write handler exists for any of these paths)
# ---------------------------------------------------------------------------

async def _wb(request, make_coro):
    stores = request.app["admin_stores"]
    if stores.workbench is None:
        return _ok(request, {"available": False,
                             "reason": "workbench_not_configured"})
    res = await asyncio.wait_for(make_coro(), WB_TIMEOUT)
    payload = {"available": bool(res.ok), "reason": res.reason,
               "partial": bool(res.partial),
               "provenance": (res.provenance.to_json()
                              if res.provenance is not None else None),
               "data": res.data if res.ok else {}}
    return _ok(request, payload)


@_guard
async def workbench_status(request):
    stores = request.app["admin_stores"]
    if stores.workbench is None:
        return _ok(request, {"available": False,
                             "reason": "workbench_not_configured"})
    ok = await asyncio.wait_for(stores.workbench.refresh(), WB_TIMEOUT)
    return _ok(request, {"available": bool(ok),
                         "reason": None if ok else stores.workbench.status()["last_error"],
                         "provenance": stores.workbench.status(),
                         "read_only": True})


@_guard
async def workbench_current(request):
    return await _wb(request, lambda: request.app["admin_stores"]
                     .workbench.continue_lesson())


@_guard
async def workbench_progress(request):
    return await _wb(request, lambda: request.app["admin_stores"]
                     .workbench.query_progress())


@_guard
async def workbench_reviews(request):
    return await _wb(request, lambda: request.app["admin_stores"]
                     .workbench.query_progress("review"))


# ---------------------------------------------------------------------------
# BEHAVIOR (bounded routing metadata; no raw transcript, ever)
# ---------------------------------------------------------------------------

def _routing_rows():
    rows = []
    for row in admin_sessions.snapshot():
        behavior = row.get("behavior")
        if behavior is None:
            continue
        rows.append({"session_id_hash": row.get("session_id_hash"),
                     "state": row.get("state"),
                     "behavior": behavior})
    return rows


@_guard
async def behavior_active(request):
    stores = request.app["admin_stores"]
    policy = stores.policy.active()["policy"] if stores.policy is not None else None
    rows = _routing_rows()
    agg = {}
    for row in rows:
        for k, v in (row["behavior"].get("stats") or {}).items():
            if isinstance(v, int):
                agg[k] = agg.get(k, 0) + v
    return _ok(request, {
        "available": True,
        "policy_version": (stores.policy.active()["version"]
                           if stores.policy is not None else None),
        "activities": list(intent.MAIN_ACTIVITIES),
        "temp_intents": list(intent.TEMPORARY_INTENTS),
        "vocab_policy_header": ((policy or {}).get("teaching") or {}).get(
            "vocab_policy_header"),
        "active_sessions": len(rows),
        "routing_stats": agg,
        "note": "routing metadata only — raw transcripts are never stored",
    })


@_guard
async def behavior_routing(request):
    rows = _routing_rows()
    return _ok(request, {"available": True, "count": len(rows), "sessions": rows,
                         "note": "recent routing metadata only; no raw transcript"})


# ---------------------------------------------------------------------------
# ADMIN AUDIT
# ---------------------------------------------------------------------------

@_guard
async def audit_view(request):
    stores = request.app["admin_stores"]
    limit = _int_arg(request, "limit", 50, 200)
    return _ok(request, {"available": True, "audit": stores.audit.recent(limit)})


# ---------------------------------------------------------------------------
# route table
# ---------------------------------------------------------------------------

def api_route_table(stores=None):
    """Route inventory.  V4 routes are listed only when their stores are wired,
    so the inventory always matches what :func:`mount` actually registers."""
    table = [
        ("GET", "/admin/policy/active"), ("GET", "/admin/policy/versions"),
        ("GET", "/admin/policy/audit"), ("POST", "/admin/policy/preview"),
        ("POST", "/admin/policy/apply"), ("POST", "/admin/policy/rollback"),
        ("GET", "/admin/memory/items"), ("GET", "/admin/memory/search"),
        ("GET", "/admin/memory/item/{item_id}"), ("POST", "/admin/memory/edit"),
        ("POST", "/admin/memory/delete"), ("POST", "/admin/memory/clear-category"),
        ("GET", "/admin/memory/diagnostics"),
        ("GET", "/admin/knowledge/datasets"),
        ("POST", "/admin/knowledge/dataset/create"),
        ("POST", "/admin/knowledge/dataset/rename"),
        ("POST", "/admin/knowledge/dataset/enable"),
        ("GET", "/admin/knowledge/dataset/{ds_id}/preview"),
        ("GET", "/admin/knowledge/dataset/{ds_id}/documents"),
        ("POST", "/admin/knowledge/dataset/delete"),
        ("POST", "/admin/knowledge/document/add"),
        ("GET", "/admin/knowledge/document/{doc_id}"),
        ("GET", "/admin/knowledge/document/{doc_id}/chunks"),
        ("POST", "/admin/knowledge/document/delete"),
        ("POST", "/admin/knowledge/document/rebuild"),
        ("POST", "/admin/knowledge/search"),
        ("GET", "/admin/knowledge/diagnostics"),
        ("GET", "/admin/workbench/status"), ("GET", "/admin/workbench/current"),
        ("GET", "/admin/workbench/progress"), ("GET", "/admin/workbench/reviews"),
        ("GET", "/admin/behavior/active"), ("GET", "/admin/behavior/routing"),
        ("GET", "/admin/audit"),
    ]
    if getattr(stores, "model_registry", None) is not None:
        from . import api_model as _mdl
        table = table + [tuple(x) for x in _mdl.api_route_table_model()]
    if getattr(stores, "knowledge_imports", None) is not None:
        from . import api_import as _imp
        table = table + [tuple(x) for x in _imp.api_route_table_import()]
    if getattr(stores, "teacher", None) is not None:
        from . import api_teacher as _tch
        table = table + [tuple(x) for x in _tch.api_route_table_teacher()]
    if getattr(stores, "teaching", None) is not None:
        from . import api_teaching as _tch2
        table = table + [tuple(x) for x in _tch2.api_route_table_teaching()]
    if getattr(stores, "voice", None) is not None:
        from . import api_voice as _vce
        table = table + [tuple(x) for x in _vce.api_route_table_voice()]
    return table


def mount(app):
    """Register the ADMIN-2 routes (called only when stores are wired)."""
    routes = [
        ("get", "/admin/policy/active", policy_active),
        ("get", "/admin/policy/versions", policy_versions),
        ("get", "/admin/policy/audit", policy_audit),
        ("post", "/admin/policy/preview", policy_preview),
        ("post", "/admin/policy/apply", policy_apply),
        ("post", "/admin/policy/rollback", policy_rollback),
        ("get", "/admin/memory/items", memory_items),
        ("get", "/admin/memory/search", memory_search),
        ("get", "/admin/memory/item/{item_id}", memory_item),
        ("post", "/admin/memory/edit", memory_edit),
        ("post", "/admin/memory/delete", memory_delete),
        ("post", "/admin/memory/clear-category", memory_clear_category),
        ("get", "/admin/memory/diagnostics", memory_diagnostics),
        ("get", "/admin/knowledge/datasets", knowledge_datasets),
        ("post", "/admin/knowledge/dataset/create", knowledge_dataset_create),
        ("post", "/admin/knowledge/dataset/rename", knowledge_dataset_rename),
        ("post", "/admin/knowledge/dataset/enable", knowledge_dataset_enable),
        ("get", "/admin/knowledge/dataset/{ds_id}/preview", knowledge_dataset_preview),
        ("get", "/admin/knowledge/dataset/{ds_id}/documents", knowledge_dataset_documents),
        ("post", "/admin/knowledge/dataset/delete", knowledge_dataset_delete),
        ("post", "/admin/knowledge/document/add", knowledge_document_add),
        ("get", "/admin/knowledge/document/{doc_id}", knowledge_document),
        ("get", "/admin/knowledge/document/{doc_id}/chunks", knowledge_document_chunks),
        ("post", "/admin/knowledge/document/delete", knowledge_document_delete),
        ("post", "/admin/knowledge/document/rebuild", knowledge_document_rebuild),
        ("post", "/admin/knowledge/search", knowledge_search),
        ("get", "/admin/knowledge/diagnostics", knowledge_diagnostics),
        ("get", "/admin/workbench/status", workbench_status),
        ("get", "/admin/workbench/current", workbench_current),
        ("get", "/admin/workbench/progress", workbench_progress),
        ("get", "/admin/workbench/reviews", workbench_reviews),
        ("get", "/admin/behavior/active", behavior_active),
        ("get", "/admin/behavior/routing", behavior_routing),
        ("get", "/admin/audit", audit_view),
    ]
    for method, path, handler in routes:
        app.router.add_route(method.upper(), path, handler)

    # V4 additive surfaces (model management + knowledge import).  Mounted only
    # when their stores are wired; each module re-checks its own store presence.
    stores = app["admin_stores"]
    if getattr(stores, "model_registry", None) is not None:
        from . import api_model as _mdl
        _mdl.mount_model(app)
    if getattr(stores, "knowledge_imports", None) is not None:
        from . import api_import as _imp
        _imp.mount_import(app)
    if getattr(stores, "teacher", None) is not None:
        from . import api_teacher as _tch
        _tch.mount_teacher(app)
    if getattr(stores, "teaching", None) is not None:
        from . import api_teaching as _tch2
        _tch2.mount_teaching(app)
    if getattr(stores, "voice", None) is not None:
        from . import api_voice as _vce
        _vce.mount_voice(app)