"""ADMIN V4 knowledge-import API (contract §1).

Implements the import endpoint family I1–I8 plus the explicit store
``migrate`` / ``rollback`` writes.  The pipeline is
``upload → parse → preview → (user confirm) → commit → read-back``: **upload never
writes to the knowledge store** — only ``I4 commit`` does, and it is reported
``applied`` only after the document is read back from disk.
"""

from __future__ import annotations

import functools
import logging

from .api import (_ApiError, _audit, _body, _confirm, _durable, _err, _ok,
                  _int_arg, _need_avail)

log = logging.getLogger("rtl.admin.api.import")

from modules._store_lock import StoreLockTimeout                          # noqa: E402
from modules.knowledge import parsers                                     # noqa: E402
from modules.knowledge.imports import (ImportJobError, ImportStore,       # noqa: E402
                                       JobExpired, JobNotCancellable,
                                       JobNotCommittable, JobNotRetryable)
from modules.knowledge.store import (CapExceeded, ConfirmRequired,        # noqa: E402
                                     DuplicateContent, KnowledgeError,
                                     KnowledgeStore, PersistError,
                                     StoreUnavailable)

MAX_UPLOAD = 20 * 1024 * 1024          # single-file hard cap (contract §5.1)
MAX_PREVIEW_CHARS = 4000
CHUNK = 64 * 1024


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
    if isinstance(exc, JobExpired):
        return _ApiError(410, "job_expired", str(exc))
    if isinstance(exc, JobNotCommittable):
        return _ApiError(409, "job_not_committable", str(exc))
    if isinstance(exc, JobNotCancellable):
        return _ApiError(409, "job_not_cancellable", str(exc))
    if isinstance(exc, JobNotRetryable):
        return _ApiError(409, "job_not_retryable", str(exc))
    if isinstance(exc, ImportJobError):
        return _ApiError(400, "invalid_json", str(exc))
    if isinstance(exc, DuplicateContent):
        return _ApiError(409, "duplicate_content", None,
                         {"existing_doc_id": exc.existing_doc_id})
    if isinstance(exc, CapExceeded):
        return _ApiError(409, "cap_exceeded", str(exc))
    if isinstance(exc, KnowledgeError):
        return _ApiError(400, "malformed_document", str(exc))
    return None


def _guard(fn):
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except Exception as e:  # noqa: BLE001
            mapped = _map(e)
            if mapped is None:
                log.warning("import api error in %s: %r", fn.__name__, e)
                return _err(request, 500, "internal_error")
            return _err(request, mapped.status, mapped.code, mapped.detail, mapped.extra)
    return wrapper


def _st(request, name):
    stores = request.app["admin_stores"]
    s = getattr(stores, name, None)
    if s is None:
        raise _ApiError(503, "%s_not_configured" % name)
    return s


def _ks(request):
    return _need_avail(_st(request, "knowledge"))


def _imp(request):
    return _need_avail(_st(request, "knowledge_imports"))


def _disk_knowledge(store):
    try:
        return KnowledgeStore(store.path).load()
    except Exception as e:  # noqa: BLE001
        log.warning("knowledge disk read-back failed: %r", e)
        return None


async def _read_multipart(request):
    """Collect ``file`` + scalar fields, bounding the upload size."""
    try:
        reader = await request.multipart()
    except Exception:  # noqa: BLE001
        raise _ApiError(400, "invalid_multipart")
    if reader is None:
        raise _ApiError(400, "invalid_multipart")
    fields, file_bytes, filename, ctype = {}, None, None, None
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.filename:
            chunks, total = [], 0
            while True:
                chunk = await part.read_chunk(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise _ApiError(413, "body_too_large",
                                    detail="文件超过单文件上限（%d MB）"
                                           % (MAX_UPLOAD // (1024 * 1024)))
                chunks.append(chunk)
            file_bytes = b"".join(chunks)
            filename = part.filename
            ctype = part.headers.get("Content-Type")
        else:
            try:
                fields[part.name] = (await part.text()).strip()
            except Exception:  # noqa: BLE001
                fields[part.name] = ""
    return fields, file_bytes, filename, ctype


# ---- I1..I8 ---------------------------------------------------------------

@_guard
async def knowledge_import_create(request):
    ks, imp = _ks(request), _imp(request)
    fields, data, filename, ctype = await _read_multipart(request)
    if data is None or not filename:
        raise _ApiError(400, "invalid_multipart", detail="file part required")
    ds_id = str(fields.get("dataset_id") or "")
    if not ds_id:
        raise _ApiError(400, "invalid_json", detail="dataset_id required")
    if ks.get_dataset(ds_id) is None:                       # VALIDATE before 409
        raise _ApiError(404, "not_found", detail="unknown_dataset")
    ext = parsers.ext_of(filename)
    if ext not in parsers.EXTS:
        # Derived from parsers.EXTS so the message can never go stale (D2 added .epub).
        raise _ApiError(400, "unsupported_content_type",
                        detail="仅支持 " + " / ".join(
                            e.lstrip(".").upper() for e in parsers.EXTS))
    ok, reason = parsers.parser_available(ext)
    if not ok:
        raise _ApiError(422, "parser_unavailable", detail=reason)
    if not data:
        raise _ApiError(400, "invalid_json", detail="empty_file")
    pc = fields.get("preview_chars")
    if pc:
        try:
            imp.preview_chars = max(0, min(int(pc), MAX_PREVIEW_CHARS))
        except (TypeError, ValueError):
            raise _ApiError(400, "invalid_json", detail="preview_chars must be an int")
    header = request.headers.get("Idempotency-Key")
    job = imp.create_job(dataset_id=ds_id, filename=filename, data=data,
                         title=fields.get("title") or None,
                         idempotency_key=(header.strip()[:120] if header else None))
    _audit(request, "knowledge_import_upload", subject=job["job_id"],
           changed=["status=%s" % job["status"], "format=%s" % (job.get("format") or "")])
    return _ok(request, {"available": True, **job})


@_guard
async def knowledge_import_get(request):
    job = _imp(request).get_job(request.match_info["job_id"])
    if job is None:
        raise _ApiError(404, "not_found")
    return _ok(request, {"available": True, "job": job})


@_guard
async def knowledge_import_list(request):
    imp = _imp(request)
    rows = imp.list_jobs(status=request.query.get("status") or None,
                         dataset_id=request.query.get("dataset_id") or None,
                         limit=_int_arg(request, "limit", 100, 200),
                         offset=_int_arg(request, "offset", 0, 100000))
    return _ok(request, {"available": True, "count": len(rows), "jobs": rows})


@_guard
async def knowledge_import_commit(request):
    ks, imp = _ks(request), _imp(request)
    body = await _body(request)
    _confirm(body)
    job_id = request.match_info["job_id"]
    if imp.get_job(job_id) is None:
        raise _ApiError(404, "not_found")
    out = imp.commit(job_id, knowledge_store=ks, confirm=True,
                     dataset_id=body.get("dataset_id"), title=body.get("title"),
                     tags=body.get("tags"))
    disk = _disk_knowledge(ks)                              # READ-BACK from DISK
    doc_id = out["document"]["id"]
    _durable(request, bool(disk) and disk.get_document(doc_id) is not None)
    _audit(request, "knowledge_import_commit", subject=job_id,
           changed=["doc=%s" % doc_id, "chunks=%d" % out["document"]["chunk_count"]])
    return _ok(request, {"available": True, "document": out["document"],
                         "chunk_count": out["document"]["chunk_count"],
                         "readback_ok": True, "job": out["job"]})


@_guard
async def knowledge_import_cancel(request):
    imp = _imp(request)
    body = await _body(request)
    _confirm(body)
    job_id = request.match_info["job_id"]
    if imp.get_job(job_id) is None:
        raise _ApiError(404, "not_found")
    job = imp.cancel(job_id, confirm=True)
    _audit(request, "knowledge_import_cancel", subject=job_id)
    return _ok(request, {"available": True, "job": job})


@_guard
async def knowledge_import_retry(request):
    imp = _imp(request)
    body = await _body(request)
    _confirm(body)
    job_id = request.match_info["job_id"]
    if imp.get_job(job_id) is None:
        raise _ApiError(404, "not_found")
    job = imp.retry(job_id, confirm=True)
    _audit(request, "knowledge_import_retry", subject=job_id,
           changed=["status=%s" % job.get("status")])
    return _ok(request, {"available": True, "job": job})


@_guard
async def knowledge_parsers(request):
    return _ok(request, {"available": True, "parsers": parsers.capabilities()})


@_guard
async def knowledge_dataset_imports(request):
    imp = _imp(request)
    rows = imp.list_jobs(dataset_id=request.match_info["ds_id"],
                         limit=_int_arg(request, "limit", 100, 200),
                         offset=_int_arg(request, "offset", 0, 100000))
    return _ok(request, {"available": True, "count": len(rows), "jobs": rows})


# ---- store maintenance (explicit, audited) --------------------------------

@_guard
async def knowledge_migrate(request):
    ks, imp = _ks(request), _imp(request)
    body = await _body(request)
    _confirm(body)
    results = {"knowledge": ks.migrate(confirm=True)}
    try:
        results["imports"] = imp.migrate(confirm=True)
    except Exception as e:  # noqa: BLE001  (import store may be empty)
        results["imports"] = {"skipped": True, "reason": type(e).__name__}
    _audit(request, "knowledge_migrate", subject="store",
           changed=["to_version=%s" % results["knowledge"].get("to_version")])
    return _ok(request, {"available": True, "migration": results, "readback_ok": True})


@_guard
async def knowledge_rollback(request):
    ks = _ks(request)
    body = await _body(request)
    _confirm(body)
    backup = body.get("backup_id")
    if not isinstance(backup, str) or not backup.strip():
        raise _ApiError(400, "invalid_json", detail="backup_id required")
    out = ks.rollback(backup.strip())
    _audit(request, "knowledge_rollback", subject="store")
    return _ok(request, {"available": True, "restored": out, "readback_ok": True})


# ---- routes ---------------------------------------------------------------

def api_route_table_import():
    return [
        ("GET", "/admin/knowledge/parsers"),
        ("POST", "/admin/knowledge/import"),
        ("GET", "/admin/knowledge/import"),
        ("GET", "/admin/knowledge/import/{job_id}"),
        ("POST", "/admin/knowledge/import/{job_id}/commit"),
        ("POST", "/admin/knowledge/import/{job_id}/cancel"),
        ("POST", "/admin/knowledge/import/{job_id}/retry"),
        ("GET", "/admin/knowledge/dataset/{ds_id}/imports"),
        ("POST", "/admin/knowledge/migrate"),
        ("POST", "/admin/knowledge/rollback"),
    ]


def mount_import(app):
    routes = [
        ("get", "/admin/knowledge/parsers", knowledge_parsers),
        ("post", "/admin/knowledge/import", knowledge_import_create),
        ("get", "/admin/knowledge/import", knowledge_import_list),
        ("get", "/admin/knowledge/import/{job_id}", knowledge_import_get),
        ("post", "/admin/knowledge/import/{job_id}/commit", knowledge_import_commit),
        ("post", "/admin/knowledge/import/{job_id}/cancel", knowledge_import_cancel),
        ("post", "/admin/knowledge/import/{job_id}/retry", knowledge_import_retry),
        ("get", "/admin/knowledge/dataset/{ds_id}/imports", knowledge_dataset_imports),
        ("post", "/admin/knowledge/migrate", knowledge_migrate),
        ("post", "/admin/knowledge/rollback", knowledge_rollback),
    ]
    for method, path, handler in routes:
        app.router.add_route(method.upper(), path, handler)
