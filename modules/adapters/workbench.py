"""WORKBENCH-1 — read-only adapter for the external English-learning-workbench.

Ownership: `modules/adapters`.  GET-only.  **No write path exists in this file
by construction** (`PUT /sync/state` must never be called by anything but the
workbench's own browser client — the workbench stays authoritative).

Contract (data-ownership + raw-agent-e-workbench-adapter):

* FRESH_TTL = 30 s — a spoken progress statement may be presented as current
  only when the payload age ≤ FRESH_TTL;
* 30 s < age ≤ CACHE_MAX_AGE (300 s) — serve but label as stale;
* age > 300 s — never serve from cache: re-fetch or return `unavailable`;
* every result carries provenance (rev / updatedAt / age) — presentation only,
  nothing is persisted and nothing is mirrored into Memory or the gateway.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import aiohttp

log = logging.getLogger("adapters.workbench")

FRESH_TTL = 30.0
CACHE_MAX_AGE = 300.0


class WorkbenchError(Exception):
    pass


@dataclass
class Provenance:
    source: str = "sync"          # sync | content | cache
    rev: int | None = None
    updated_at: str | None = None
    age_s: float | None = None
    fresh: bool = False
    stale: bool = False
    partial: bool = False

    def to_json(self):
        return {"source": self.source, "rev": self.rev,
                "updated_at": self.updated_at,
                "age_s": (None if self.age_s is None else round(self.age_s, 3)),
                "fresh": self.fresh, "stale": self.stale,
                "partial": self.partial}


@dataclass
class Result:
    ok: bool
    data: dict = field(default_factory=dict)
    provenance: Provenance | None = None
    reason: str | None = None      # workbench_down|sync_down|malformed_state|timeout|...
    partial: bool = False


class WorkbenchClient:
    """Thin read-only client with a rev-aware TTL cache (one per gateway)."""

    def __init__(self, base_url, *, fresh_ttl=FRESH_TTL, cache_max_age=CACHE_MAX_AGE,
                 timeout=2.0, session=None):
        self.base_url = (base_url or "").rstrip("/")
        self.fresh_ttl = float(fresh_ttl)
        self.cache_max_age = float(cache_max_age)
        self.timeout = float(timeout)
        self._session = session
        self._state: dict | None = None         # raw /sync/state payload
        self._state_mono: float | None = None
        self._content: dict = {}                # lesson -> (data, mono)
        self._last_error = "sync_down"

    # ---- plumbing ---------------------------------------------------------

    async def _ensure_session(self):
        if self._session is None or getattr(self._session, "closed", False):
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _get_json(self, path):
        session = await self._ensure_session()
        async with session.get(self.base_url + path,
                               timeout=aiohttp.ClientTimeout(total=self.timeout)) as r:
            if r.status != 200:
                raise WorkbenchError("upstream_status_%d" % r.status)
            return await r.json(content_type=None)

    def cache_age(self):
        if self._state_mono is None:
            return None
        return max(0.0, time.monotonic() - self._state_mono)

    def status(self):
        """Read-only status snapshot (no fetch; never invents values)."""
        return {"has_state": self._state is not None,
                "rev": (self._state or {}).get("rev"),
                "age_s": self.cache_age(),
                "last_error": self._last_error,
                "fresh_ttl": self.fresh_ttl,
                "cache_max_age": self.cache_max_age}

    # ---- state / rev ------------------------------------------------------

    async def refresh(self):
        """Fetch /sync/state (read-only). True on success."""
        try:
            raw = await self._get_json("/sync/state")
        except WorkbenchError as e:
            self._last_error = "sync_down"
            log.info("workbench refresh failed: %s", e)
            return False
        except (aiohttp.ClientError, TimeoutError, OSError) as e:
            self._last_error = ("timeout" if isinstance(e, TimeoutError)
                                else "sync_down")
            log.info("workbench refresh failed: %r", e)
            return False
        except Exception as e:  # noqa: BLE001
            self._last_error = "upstream_error"
            log.warning("workbench refresh error: %r", e)
            return False
        if not self._validate(raw):
            self._last_error = "malformed_state"
            log.warning("workbench state malformed (ignored)")
            return False
        old_rev = (self._state or {}).get("rev")
        self._state = raw
        self._state_mono = time.monotonic()
        if old_rev is not None and raw.get("rev") != old_rev:
            log.info("workbench rev %s -> %s (cache invalidated)", old_rev,
                     raw.get("rev"))
        return True

    @staticmethod
    def _validate(raw):
        try:
            return (isinstance(raw, dict) and isinstance(raw.get("rev"), int)
                    and isinstance(raw.get("state"), dict))
        except Exception:  # noqa: BLE001
            return False

    def _prov(self, *, source="sync"):
        age = self.cache_age()
        prov = Provenance(source=source,
                          rev=(self._state or {}).get("rev"),
                          updated_at=(self._state or {}).get("updatedAt"),
                          age_s=age)
        if age is not None:
            prov.fresh = age <= self.fresh_ttl
            prov.stale = age > self.fresh_ttl
        return prov

    async def _state_for_read(self, *, inline_fetch=True):
        """Return (raw, Result|None).  Never serves data older than CACHE_MAX_AGE."""
        age = self.cache_age()
        if self._state is not None and age is not None and age <= self.cache_max_age:
            return self._state, None
        if not inline_fetch:
            return None, Result(ok=False, reason="stale_cache",
                                provenance=self._prov(source="cache"))
        if await self.refresh():
            return self._state, None
        if self._state is not None:
            reason = "stale_cache" if (age or 0) > self.cache_max_age else "sync_down"
        else:
            reason = self._last_error
        return None, Result(ok=False, reason=reason, provenance=self._prov(source="cache"))

    # ---- content ----------------------------------------------------------

    async def _content_for(self, lesson):
        hit = self._content.get(lesson)
        if hit is not None and (time.monotonic() - hit[1]) <= self.cache_max_age:
            return hit[0]
        try:
            data = await self._get_json("/workbench/content/day%02d.json" % lesson)
        except Exception as e:  # noqa: BLE001
            log.info("workbench content day%02d unavailable: %r", lesson, e)
            return None
        self._content[lesson] = (data, time.monotonic())
        return data

    def _content_cached(self, lesson):
        hit = self._content.get(lesson)
        if hit is not None and (time.monotonic() - hit[1]) <= self.cache_max_age:
            return hit[0]
        return None

    # ---- read operations (the MVP subset of the 8-op contract) ------------

    async def continue_lesson(self, *, inline_fetch=True):
        raw, err = await self._state_for_read(inline_fetch=inline_fetch)
        if err is not None:
            return err
        st = raw.get("state") or {}
        lesson = st.get("currentLesson")
        if not isinstance(lesson, int) or lesson <= 0:
            return Result(ok=False, reason="malformed_state",
                          provenance=self._prov())
        data = {"lesson_id": lesson, "title": None, "objectives": []}
        content = await self._content_for(lesson)
        partial = False
        if content is not None:
            data["title"] = (content.get("unit") or content.get("theme") or None)
            objs = content.get("objectives")
            if isinstance(objs, list):
                data["objectives"] = [str(o) for o in objs[:4]]
            data["theme"] = content.get("theme")
        else:
            partial = True
        prov = self._prov()
        prov.partial = partial
        return Result(ok=True, data=data, provenance=prov, partial=partial)

    async def query_progress(self, scope=None, *, inline_fetch=True):
        raw, err = await self._state_for_read(inline_fetch=inline_fetch)
        if err is not None:
            return err
        st = raw.get("state") or {}
        lessons = st.get("lessons") or {}
        decisions = []
        if isinstance(lessons, dict):
            decisions = [v.get("decision") for v in lessons.values()
                         if isinstance(v, dict)]
        passed = sum(1 for x in decisions if x == "PASS")
        review = sum(1 for x in decisions if x == "REVIEW")
        repeat = sum(1 for x in decisions if x == "REPEAT")

        today = time.strftime("%Y-%m-%d")
        due_count, next_due, due_words = 0, None, []
        reviews = st.get("reviews") or []
        if isinstance(reviews, list):
            for rv in reviews:
                if not isinstance(rv, dict) or rv.get("done"):
                    continue
                nd = rv.get("nextReviewAt")
                if not isinstance(nd, str):
                    continue
                if next_due is None or nd < next_due:
                    next_due = nd
                if nd <= today:
                    due_count += 1
                    ref = str(rv.get("refId") or "")
                    word = ref.split(":")[-1] if ref else ""
                    if word and word not in due_words:
                        due_words.append(word)

        data = {
            "lesson_id": st.get("currentLesson"),
            "title": None,
            "passed": passed,
            "review_required": review,
            "repeat_required": repeat,
            "due_count": due_count,
            "next_due": next_due,
            "due_words": due_words[:4],
            "lessons_started": len(decisions),
        }
        lesson = st.get("currentLesson")
        if isinstance(lesson, int) and lesson > 0:
            content = self._content_cached(lesson)   # cached-only: no extra latency
            if content is not None:
                data["title"] = (content.get("unit") or content.get("theme") or None)
        if scope == "review":
            data.pop("passed", None)
            data.pop("repeat_required", None)
        prov = self._prov()
        return Result(ok=True, data=data, provenance=prov)


class WorkbenchError(Exception):
    pass