"""Knowledge import pipeline (contract §1.2–§1.4).

``upload → parse → preview → (user confirm) → commit → read-back``

Upload NEVER writes to the knowledge store: only an explicit ``commit`` after
``preview_ready`` does, and it is reported ``applied`` only when the document is
read back from disk.  Every refusal is coded; nothing is silently truncated.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from pathlib import Path

from modules._jsonstore import BaseJsonStore, ConfirmRequired
from modules.knowledge import parsers
from modules.knowledge.store import (MAX_DOC_CHARS, CapExceeded,  # noqa: F401
                                     DuplicateContent, KnowledgeError,
                                     KnowledgeStore, _norm_text, chunk_text)

log = logging.getLogger("knowledge.imports")

STATES = ("uploaded", "parsing", "preview_ready", "committing", "applied",
          "failed", "cancelled", "expired")
CANCELLABLE = ("uploaded", "parsing", "preview_ready")
RETRYABLE_ERRORS = ("parse_timeout", "extract_failed", "parser_unavailable")
MAX_JOBS = 200
PREVIEW_TTL = 30 * 60          # seconds a preview stays committable


class ImportJobError(KnowledgeError):
    """Base class for import refusals (400/409)."""


class JobNotCommittable(ImportJobError):
    pass


class JobNotCancellable(ImportJobError):
    pass


class JobNotRetryable(ImportJobError):
    pass


class JobExpired(ImportJobError):
    pass


class ImportStore(BaseJsonStore):
    SCHEMA_VERSION = 1
    ROOT_KEYS = ("jobs",)

    def __init__(self, path, *, scratch_dir=None, ttl=PREVIEW_TTL,
                 preview_chars=800):
        super().__init__(path)
        base = Path(self.path).parent if self.path else Path(".")
        self.scratch_dir = str(scratch_dir or (base / "knowledge-imports"))
        self.ttl = int(ttl)
        self.preview_chars = int(preview_chars)

    # ---- scratch ---------------------------------------------------------

    def _scratch(self, job_id, suffix):
        d = Path(self.scratch_dir)
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        return d / ("%s.%s" % (job_id, suffix))

    def _write_scratch(self, job_id, suffix, data: bytes):
        p = self._scratch(job_id, suffix)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        return str(p)

    def _cleanup(self, job_id):
        for suffix in ("bin", "txt"):
            try:
                self._scratch(job_id, suffix).unlink()
            except Exception:  # noqa: BLE001
                pass

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _hash(text):
        return hashlib.sha256(_norm_text(text).encode("utf-8")).hexdigest()

    def _expire_stale(self):
        now = time.time()
        changed = False
        for job in self._data["jobs"].values():
            if job.get("status") == "preview_ready" and \
                    float(job.get("expires_at") or 0) < now:
                job["status"] = "expired"
                job["updated_at"] = now
                changed = True
        if changed:
            try:
                self._persist()
            except Exception:  # noqa: BLE001
                pass

    # ---- create ----------------------------------------------------------

    def create_job(self, *, dataset_id, filename, data, title=None,
                   idempotency_key=None, parse=True):
        """Receive bytes, parse, and return a ``preview_ready`` (or ``failed``) job."""
        ext = parsers.ext_of(filename)
        dataset_id = str(dataset_id or "")
        if not dataset_id:
            raise ImportJobError("dataset_id required")
        with self._lock.exclusive():
            self.reload_if_changed()
            self._expire_stale()
            if idempotency_key:
                for job in self._data["jobs"].values():
                    if job.get("idempotency_key") == idempotency_key:
                        return dict(job)          # idempotent replay
            if len(self._data["jobs"]) >= MAX_JOBS:
                # drop oldest terminal jobs before refusing
                term = sorted((j for j in self._data["jobs"].values()
                               if j.get("status") in ("applied", "cancelled", "expired")),
                              key=lambda j: j.get("updated_at") or 0)
                while len(self._data["jobs"]) >= MAX_JOBS and term:
                    gone = term.pop(0)
                    self._data["jobs"].pop(gone["job_id"], None)
            now = time.time()
            jid = "imp_" + uuid.uuid4().hex[:12]
            job = {"job_id": jid, "status": "uploaded", "dataset_id": dataset_id,
                   "title": (str(title).strip()[:120] if title else
                             str(filename)[:120]),
                   "filename": str(filename)[:160], "ext": ext,
                   "format": (ext[1:] if ext else ""),
                   "source_type": parsers.EXTS.get(ext, {}).get("source_type"),
                   "bytes": len(data or b""), "extracted_chars": 0,
                   "preview": None, "preview_truncated": False,
                   "chunk_estimate": 0, "content_hash": None, "doc_id": None,
                   "error_code": None, "progress": 0.1,
                   "idempotency_key": idempotency_key,
                   "created_at": now, "updated_at": now, "expires_at": None}
            self._data["jobs"][jid] = job
            self._persist()

        if not data:
            return self._fail(jid, "empty_content")
        if ext not in parsers.EXTS:
            return self._fail(jid, "unsupported_content_type")
        ok, reason = parsers.parser_available(ext)
        if not ok:
            return self._fail(jid, (reason or "parser_unavailable").split(" ")[0])

        upload_path = self._write_scratch(jid, "bin", data)
        if parse:
            return self._parse(jid, upload_path)
        return self.get_job(jid)

    def _set(self, job_id, **fields):
        with self._lock.exclusive():
            self.reload_if_changed()
            job = self._data["jobs"].get(job_id)
            if job is None:
                raise ImportJobError("unknown job")
            job.update(fields)
            job["updated_at"] = time.time()
            self._persist()
            return dict(job)

    def _fail(self, job_id, code):
        return self._set(job_id, status="failed", error_code=code, progress=0.0,
                         expires_at=None)

    def _parse(self, job_id, upload_path):
        self._set(job_id, status="parsing", progress=0.4)
        ext = (self._data["jobs"].get(job_id) or {}).get("ext")
        t0 = time.monotonic()
        try:
            text, err = parsers.parse_file(upload_path, ext)
        except Exception as e:  # noqa: BLE001
            log.warning("parse crashed for %s: %r", job_id, e)
            return self._fail(job_id, "extract_failed")
        if time.monotonic() - t0 > 120:            # defensive; parser is sync
            return self._fail(job_id, "parse_timeout")
        if err:
            return self._fail(job_id, err)
        if text is None or not text.strip():
            return self._fail(job_id, "empty_extraction")
        if len(text) > MAX_DOC_CHARS:
            # contract §1.4: refuse, never silently truncate textbook content
            return self._fail(job_id, "cap_exceeded")

        preview = text[:self.preview_chars]
        self._write_scratch(job_id, "txt", text.encode("utf-8"))
        return self._set(job_id, status="preview_ready", extracted_chars=len(text),
                         preview=preview,
                         preview_truncated=len(text) > self.preview_chars,
                         chunk_estimate=len(chunk_text(text)),
                         content_hash=self._hash(text), error_code=None,
                         progress=1.0,
                         expires_at=time.time() + self.ttl)

    # ---- read ------------------------------------------------------------

    def get_job(self, job_id):
        with self._lock:
            self._ensure_loaded()
            job = self._data["jobs"].get(str(job_id or ""))
            return _public(job) if job else None

    def list_jobs(self, *, status=None, dataset_id=None, limit=100, offset=0):
        with self._lock:
            self._ensure_loaded()
            rows = [_public(j) for j in self._data["jobs"].values()
                    if (status is None or j.get("status") == status)
                    and (dataset_id is None or j.get("dataset_id") == str(dataset_id))]
            rows.sort(key=lambda r: (r.get("created_at") or 0, r["job_id"]), reverse=True)
            off, lim = max(0, int(offset)), max(1, min(int(limit), 200))
            return rows[off:off + lim]

    def job_count(self):
        with self._lock:
            self._ensure_loaded()
            return len(self._data["jobs"])

    # ---- commit ----------------------------------------------------------

    def commit(self, job_id, *, knowledge_store, confirm=False, dataset_id=None,
               title=None, tags=None, actor="admin"):
        """User confirmation → write to the knowledge store → disk read-back."""
        if confirm is not True:
            raise ConfirmRequired("confirm: true is required")
        job = self.get_job(job_id)
        if job is None:
            raise ImportJobError("unknown job")
        if job["status"] == "expired" or \
                (job["status"] == "preview_ready" and
                 float(job.get("expires_at") or 0) < time.time()):
            self._set(job_id, status="expired")
            raise JobExpired("preview has expired")
        if job["status"] != "preview_ready":
            raise JobNotCommittable("job is not in preview_ready (%s)" % job["status"])

        text_path = self._scratch(job_id, "txt")
        if not text_path.is_file():
            self._fail(job_id, "extract_failed")
            raise JobNotCommittable("preview payload missing; retry the import")
        text = text_path.read_text("utf-8")

        self._set(job_id, status="committing", progress=0.9)
        try:
            doc = knowledge_store.add_document(
                dataset_id or job["dataset_id"], title or job["title"], text,
                source_type=job["source_type"] or "text",
                source_uri="file://%s" % job["filename"], tags=tags,
                added_by=actor)
        except DuplicateContent as e:
            # not an error state for the job: the user may pick another dataset
            self._set(job_id, status="preview_ready", progress=1.0,
                      error_code="duplicate_content")
            raise
        except CapExceeded:
            self._fail(job_id, "cap_exceeded")
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("commit failed for %s: %r", job_id, e)
            self._fail(job_id, "persist_failed")
            raise

        fresh = KnowledgeStore(knowledge_store.path).load()
        found = fresh.get_document(doc["id"]) if fresh.available else None
        if found is None:
            self._fail(job_id, "persist_failed")
            raise ImportJobError("read-back failed; document not durable")
        self._cleanup(job_id)
        return {"job": self._set(job_id, status="applied", doc_id=doc["id"],
                                 dataset_id=doc["dataset_id"], progress=1.0,
                                 error_code=None),
                "document": doc, "readback_ok": True}

    # ---- cancel / retry --------------------------------------------------

    def cancel(self, job_id, *, confirm=False):
        if confirm is not True:
            raise ConfirmRequired("confirm: true is required")
        job = self.get_job(job_id)
        if job is None:
            raise ImportJobError("unknown job")
        if job["status"] not in CANCELLABLE:
            raise JobNotCancellable("job is not cancellable (%s)" % job["status"])
        self._cleanup(job_id)
        return self._set(job_id, status="cancelled", progress=0.0, expires_at=None)

    def retry(self, job_id, *, confirm=False):
        if confirm is not True:
            raise ConfirmRequired("confirm: true is required")
        job = self.get_job(job_id)
        if job is None:
            raise ImportJobError("unknown job")
        if job["status"] != "failed":
            raise JobNotRetryable("job is not failed (%s)" % job["status"])
        if job.get("error_code") not in RETRYABLE_ERRORS:
            raise JobNotRetryable("error %s is not retryable" % job.get("error_code"))
        upload = self._scratch(job_id, "bin")
        if not upload.is_file():
            raise JobNotRetryable("original upload is gone")
        return self._parse(job_id, str(upload))

    # ---- migration -------------------------------------------------------

    def migrate(self, *, confirm=False):
        return super().migrate(confirm=confirm)


def _public(job):
    out = dict(job)
    out.pop("idempotency_key", None)
    return out
