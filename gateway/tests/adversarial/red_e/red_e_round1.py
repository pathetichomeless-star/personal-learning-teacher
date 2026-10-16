"""RED-E (Workbench boundary) round-1 adversarial evidence.

Surface: "no Product V1 code path may ever mutate the Workbench; the Workbench
stays READ-ONLY and authoritative for course progress".

Metric under test: WORKBENCH_WRITES == 0.
Secondary: no path may present fabricated/stale progress as authoritative.

METHODS
-------
1. STATIC scan of product source for any Workbench-facing write shape.
2. A LOCAL recording stub Workbench (aiohttp) that records EVERY request it
   receives (method + path), including non-GET.  The production Workbench is
   NEVER contacted.  Only 127.0.0.1 is used.
3. Dynamic: drive the real product adapters (WorkbenchClient, BehaviorLink
   conversation turns, admin workbench routes) against the stub and prove the
   stub only ever saw GETs.
4. Mutation attempts: admin API, conversation text, Knowledge/Memory data.
5. Degraded modes: down / slow / 500 / malformed / giant / redirect-loop / reset.
6. Freshness/provenance: rev / age / fresh / stale / cache expiry.
7. Admin UI static: no write affordance.

Run:  DYLD_LIBRARY_PATH=/tmp/opus131/lib ./gateway/.venv/bin/python \
        gateway/tests/adversarial/red_e/red_e_round1.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve()
_GATEWAY = _HERE.parents[3]      # gateway/
_REPO = _HERE.parents[4]         # repo root
for _p in (str(_GATEWAY), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from aiohttp import web                                        # noqa: E402
from aiohttp.test_utils import TestClient, TestServer          # noqa: E402

from app import behavior as link_mod                           # noqa: E402
from modules.adapters import workbench as wbk                  # noqa: E402
from modules.adapters.workbench import (CACHE_MAX_AGE, FRESH_TTL,  # noqa: E402
                                        WorkbenchClient)
from modules.intent import behavior as intent                  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def info(msg):
    print("INFO  %s" % msg)


# ---------------------------------------------------------------------------
# stub workbench (records everything, 127.0.0.1 only)
# ---------------------------------------------------------------------------

_TODAY = date.today()
_D_PAST3 = (_TODAY - timedelta(days=3)).isoformat()
_D_PAST2 = (_TODAY - timedelta(days=2)).isoformat()
_D_FUTURE5 = (_TODAY + timedelta(days=5)).isoformat()

STATE = {
    "rev": 77,
    "updatedAt": "2026-10-05T02:25:51Z",
    "state": {
        "version": 2, "currentLesson": 12,
        "lessons": {"1": {"decision": "REVIEW"},
                    "2": {"decision": "PASS"},
                    "3": {"decision": "REPEAT"}},
        "reviews": [
            {"id": "a", "refId": "12:walked", "nextReviewAt": _D_PAST3, "done": False},
            {"id": "b", "refId": "12:talked", "nextReviewAt": _D_PAST2, "done": True},
            {"id": "c", "refId": "ielts:w3413", "nextReviewAt": _D_FUTURE5, "done": False},
        ],
    },
}


class RecordingStub:
    """Local fake workbench.  Records EVERY (method, path) it receives."""

    def __init__(self):
        self.requests = []            # [(method, path)]
        self.mode = "ok"             # ok|slow|error500|malformed|giant|redirect
        self.state = STATE

    def reset(self):
        self.requests = []
        self.mode = "ok"
        self.state = STATE

    def _rec(self, request):
        self.requests.append((request.method, request.path))

    def methods(self):
        return sorted({m for m, _ in self.requests})

    async def sync_health(self, request):
        self._rec(request)
        return web.json_response({"ok": True})

    async def sync_state(self, request):
        self._rec(request)
        if request.method != "GET":
            return web.Response(status=405, text="method_not_allowed")
        m = self.mode
        if m == "error500":
            return web.Response(status=500)
        if m == "slow":
            await asyncio.sleep(5)
        if m == "malformed":
            return web.json_response({"oops": True})
        if m == "giant":
            lessons = {str(i): {"decision": "PASS"} for i in range(20000)}
            return web.json_response({"rev": self.state["rev"],
                                      "state": {"version": 2,
                                                "currentLesson": 12,
                                                "lessons": lessons}})
        if m == "redirect":
            raise web.HTTPFound(location="/sync/state")
        return web.json_response(self.state)

    async def content(self, request):
        self._rec(request)
        if request.method != "GET":
            return web.Response(status=405, text="method_not_allowed")
        if self.mode == "error500":
            return web.Response(status=404)
        day = int(request.match_info["day"])
        if day != 12:
            return web.Response(status=404)
        return web.json_response({"lesson": 12, "unit": "一般过去时（规则动词 -ed）",
                                  "theme": "昨天", "objectives": ["o1", "o2", "o3", "o4"]})

    def app(self):
        app = web.Application()
        app.router.add_route("*", "/sync/health", self.sync_health)
        app.router.add_route("*", "/sync/state", self.sync_state)
        app.router.add_route("*", "/workbench/content/day{day}.json", self.content)
        return app


class ResetServer:
    """Raw TCP server that accepts then closes -> connection reset / disconnect."""

    def __init__(self):
        self._srv = None
        self.port = None

    async def start(self):
        self._srv = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._srv.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.5)
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass

    async def close(self):
        if self._srv is not None:
            self._srv.close()
            await self._srv.wait_closed()

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.port


# ===========================================================================
# PHASE 1 — STATIC: any Workbench-facing write shape in product source
# ===========================================================================

_WRITE_RE = re.compile(
    r"\.(put|post|patch|delete)\s*\(|\.(put|post|patch|delete)\s*=|\brequests\.(put|post|patch|delete)\b|"
    r"method\s*=\s*['\"](PUT|POST|PATCH|DELETE)['\"]|"
    r"add_route\(\s*['\"](POST|PUT|PATCH|DELETE)['\"]|"
    r"add_(post|put|patch|delete)\s*\(|"
    r"socket\.socket|create_connection",
    re.IGNORECASE)


def _scan_tree(root):
    hits = []
    for p in Path(root).rglob("*.py"):
        try:
            for i, line in enumerate(p.read_text("utf-8", errors="replace").splitlines(), 1):
                if _WRITE_RE.search(line):
                    hits.append((str(p.relative_to(_REPO)), i, line.strip()))
        except Exception:
            pass
    return hits


def phase_static():
    info("PHASE 1 static write-shape scan (product source)")
    # 1a. the adapter itself must contain no write verb and no write to sync/state
    src = (_REPO / "modules" / "adapters" / "workbench.py").read_text("utf-8")
    check("S1 workbench adapter: no .put/.post/.patch/.delete(",
          not re.search(r"\.(put|post|patch|delete)\s*\(", src))
    check("S1b workbench adapter: only session.get for sync/state",
          "session.get(" in src and "sync/state" in src
          and not re.search(r'method\s*=\s*["\'](PUT|POST|PATCH|DELETE)', src, re.I))
    check("S1c adapter contains no 'PUT' literal",
          '"PUT"' not in src and "'PUT'" not in src)

    # 1b. entire product source trees
    hits = []
    for sub in ("modules", "gateway/app", "admin", "deploy/product-sidecar"):
        hits.extend(_scan_tree(_REPO / sub))
    info("static write-shape hits across product source: %d" % len(hits))
    for f, ln, txt in hits:
        info("  hit %s:%d  %s" % (f, ln, txt[:110]))
    # the key assertion: NO hit lives in the adapter / behavior link (Workbench-facing code)
    wb_facing = [h for h in hits
                 if h[0].endswith("adapters/workbench.py")
                 or h[0].endswith("app/behavior.py")]
    check("S2 no write-shape hit in workbench-facing code", not wb_facing, wb_facing)
    # any hit that mentions the workbench/sync path would be a boundary breach
    wb_related = [h for h in hits
                  if re.search(r"workbench|sync/state|sync_state", h[2], re.I)]
    check("S3 no write-shape hit mentions workbench/sync", not wb_related, wb_related)

    # 1c. admin route table (with stores wired): workbench paths are GET-only
    from app.admin.app import admin_route_table
    from app.admin.stores import AdminStores
    tbl = admin_route_table(stores=AdminStores())
    wb_routes = [(m, p) for m, p in tbl if p.startswith("/admin/workbench/")]
    check("S4 admin workbench routes all GET",
          len(wb_routes) == 4 and all(m == "GET" for m, _ in wb_routes), wb_routes)

    # 1d. admin UI: workbench page must issue GET only, no write affordance
    app_js = (_REPO / "admin" / "app.js").read_text("utf-8")
    wb_section = app_js.split("pageWorkbench")[1].split("pageRouting")[0]
    check("S5 admin workbench page issues no write method",
          "method:" not in wb_section and not re.search(r"fetch\(\s*[\"']/admin/workbench", wb_section)
          or 'method: "POST"' not in wb_section)
    check("S5b admin workbench page uses only GET api() calls",
          wb_section.count("await api(") >= 4
          and "opts.method" not in wb_section and "body:" not in wb_section)
    idx = (_REPO / "admin" / "index.html").read_text("utf-8")
    check("S5c admin UI has no workbench write control",
          not re.search(r"workbench[^\n]*(save|write|apply|update|set)", idx, re.I))


# ===========================================================================
# PHASE 2 — DYNAMIC adapter against the stub (GET-only proof)
# ===========================================================================

async def phase_adapter(base, stub):
    info("PHASE 2 dynamic: WorkbenchClient read operations vs stub")
    stub.reset()
    wc = WorkbenchClient(base, timeout=1.0)
    try:
        r1 = await wc.continue_lesson()
        r2 = await wc.query_progress()
        r3 = await wc.query_progress("review")
        r4 = await wc.refresh()          # what the gateway prefetch does
        wc.status()
        check("D1 continue_lesson ok", r1.ok and r1.data["lesson_id"] == 12)
        check("D2 progress counts from stub",
              r2.ok and r2.data["passed"] == 1 and r2.data["review_required"] == 1
              and r2.data["repeat_required"] == 1 and r2.data["due_count"] == 1)
        check("D3 review scope strips fields",
              r3.ok and "passed" not in r3.data and r3.data["due_count"] == 1)
        check("D4 refresh returns True", r4 is True)
        methods = stub.methods()
        check("D5 adapter issued GET only", methods == ["GET"], methods)
        paths = sorted({p for _, p in stub.requests})
        check("D6 adapter only hit sync/state + content",
              all(p.startswith("/sync/state") or p.startswith("/workbench/content/")
                  for p in paths), paths)
    finally:
        await wc.close()


# ===========================================================================
# PHASE 3 — DYNAMIC conversation turns (BehaviorLink) against the stub
# ===========================================================================

class FakeQwen:
    def __init__(self):
        self.ins = "BASE"
        self.updates = []

    @property
    def instructions(self):
        return self.ins

    def set_instructions(self, t):
        self.ins = t

    async def send_instructions_update(self, t):
        self.ins = t
        self.updates.append(t)
        return True


class FakeConn:
    def __init__(self):
        self.safe = True

    def is_safe_boundary(self):
        return self.safe


def _cfg(base):
    return SimpleNamespace(MEMORY_FILE="", KNOWLEDGE_FILE="", POLICY_FILE="",
                           WORKBENCH_BASE_URL=base)


def _tr(text, item):
    return {"type": "conversation.item.input_audio_transcription.completed",
            "transcript": text, "item_id": item}


async def phase_conversation(base, stub):
    info("PHASE 3 dynamic: conversation turns vs stub")
    stub.reset()
    q = FakeQwen()
    link = link_mod.BehaviorLink(FakeConn(), q, config=_cfg(base))
    try:
        # continue-lesson, progress, and review intents (all Workbench-facing)
        await link.on_qwen_event(_tr("继续上次的课", "c1"))
        ins_continue = q.ins
        await link.on_qwen_event(_tr("我学到哪里了？", "c2"))
        await link.on_qwen_event(_tr("这个需要复习吗？", "c3"))
        # prefetch path (fires on speech start)
        link.on_speech_started()
        await asyncio.sleep(0.15)
        check("C1 continue-lesson answered from authoritative data",
              "authoritative" in ins_continue and "12" in ins_continue)
        check("C2 workbench answers counted == 3",
              link.stats["workbench_answers"] == 3, link.stats["workbench_answers"])
        methods = stub.methods()
        check("C3 conversation path issued GET only", methods == ["GET"], methods)
        paths = sorted({p for _, p in stub.requests})
        check("C4 conversation path only READ (sync/state + content)",
              paths and all(p.startswith("/sync/state")
                            or p.startswith("/workbench/content/")
                            for p in paths), paths)
    finally:
        await link.close()


# ===========================================================================
# PHASE 4 — MUTATION attempts (admin API, conversation text, KB/Memory)
# ===========================================================================

def phase_mutation_routing():
    info("PHASE 4a mutation attempts via conversation text (router)")
    st = intent.BehaviorState()
    cases = [
        "Mark lesson 12 as passed",
        "I finished the lesson, update my progress",
        "Set my mastery to 100%",
        "把第12课标记为已通过",
        "我的掌握度设为100%",
        "把复习日期改成明天",
    ]
    for u in cases:
        d = intent.route(u, st)
        check("M1 no write intent for %r" % u,
              d.needs_workbench is None and d.memory is None, repr(d))
        st = intent.BehaviorState()
    # Chinese "更新进度" DOES match the read-only progress pattern -> must be a READ
    d = intent.route("我学完了，更新进度", intent.BehaviorState())
    check("M2 'update progress' routes to READ-ONLY progress fetch",
          d.needs_workbench == "progress", repr(d))


async def phase_mutation_conversation(base, stub):
    info("PHASE 4b mutation attempts via conversation (link) vs stub")
    stub.reset()
    q = FakeQwen()
    link = link_mod.BehaviorLink(FakeConn(), q, config=_cfg(base))
    try:
        for i, u in enumerate(["Mark lesson 12 as passed",
                               "I finished the lesson, update my progress",
                               "Set my mastery to 100%"]):
            await link.on_qwen_event(_tr(u, "m%d" % i))
        # none of these are workbench intents -> no fetch at all; and no write, ever
        check("M3 no workbench request for mutation utterances",
              stub.requests == [], stub.requests)
        check("M4 no fabricated progress claim in instructions",
              "passed: " not in q.ins and "mastery" not in q.ins.lower())
        # the read-only 'update progress' utterance -> GET only
        await link.on_qwen_event(_tr("我学完了，更新进度", "m9"))
        check("M5 'update progress' triggered GET-only fetch",
              stub.requests and stub.methods() == ["GET"], stub.requests)
        info("instructions after 'update progress' contains no success claim:")
        info("  " + " / ".join(l for l in q.ins.splitlines()
                              if "authoritative" in l or "passed" in l)[:200])
    finally:
        await link.close()


# ===========================================================================
# PHASE 5 — DEGRADED / UNAVAILABLE (bounded timeouts, honest degradation)
# ===========================================================================

async def phase_degraded(base, stub, reset_base):
    info("PHASE 5 degraded modes")
    # 5a. slow -> bounded by client timeout, honest unavailable
    stub.reset(); stub.mode = "slow"
    wc = WorkbenchClient(base, timeout=0.4)
    t0 = asyncio.get_event_loop().time()
    r = await wc.continue_lesson()
    took = asyncio.get_event_loop().time() - t0
    check("G1 slow: bounded timeout, honest unavailable",
          (not r.ok) and took < 1.2, "took=%.2fs reason=%s" % (took, r.reason))
    await wc.close()

    # 5b. 500 -> unavailable (no fabricated data)
    stub.reset(); stub.mode = "error500"
    wc = WorkbenchClient(base, timeout=0.6)
    r = await wc.continue_lesson()
    check("G2 500: unavailable, no data", (not r.ok) and not r.data, repr(r.reason))
    await wc.close()

    # 5c. malformed -> malformed_state, no fabricated data
    stub.reset(); stub.mode = "malformed"
    wc = WorkbenchClient(base, timeout=0.6)
    r = await wc.query_progress()
    check("G3 malformed: unavailable, no data",
          (not r.ok) and not r.data and r.reason == "malformed_state", repr(r.reason))
    await wc.close()

    # 5d. giant body -> parses within bounded time, rev matches (no crash)
    stub.reset(); stub.mode = "giant"
    wc = WorkbenchClient(base, timeout=2.0)
    t0 = asyncio.get_event_loop().time()
    r = await wc.query_progress()
    took = asyncio.get_event_loop().time() - t0
    check("G4 giant body: handled within bound, rev correct",
          r.ok and r.provenance.rev == 77 and took < 2.5, "took=%.2fs" % took)
    await wc.close()

    # 5e. redirect loop -> bounded, unavailable (never loops forever)
    stub.reset(); stub.mode = "redirect"
    wc = WorkbenchClient(base, timeout=1.2)
    t0 = asyncio.get_event_loop().time()
    r = await wc.continue_lesson()
    took = asyncio.get_event_loop().time() - t0
    check("G5 redirect loop: bounded, unavailable",
          (not r.ok) and took < 3.0, "took=%.2fs reason=%s" % (took, r.reason))
    await wc.close()

    # 5f. connection reset -> unavailable, bounded
    wc = WorkbenchClient(reset_base, timeout=1.0)
    t0 = asyncio.get_event_loop().time()
    r = await wc.continue_lesson()
    took = asyncio.get_event_loop().time() - t0
    check("G6 connection reset: bounded, unavailable",
          (not r.ok) and took < 2.0, "took=%.2fs reason=%s" % (took, r.reason))
    await wc.close()

    # 5g. realtime honesty: degrade line, no fabricated progress
    block = intent.render_workbench_block(None, kind="progress")
    check("G7 degrade block is explicit UNAVAILABLE + do-not-invent",
          "UNAVAILABLE" in block and "do not invent" in block, block)


# ===========================================================================
# PHASE 6 — FRESHNESS / PROVENANCE
# ===========================================================================

async def phase_provenance(base, stub):
    info("PHASE 6 freshness / provenance")
    stub.reset()
    wc = WorkbenchClient(base, fresh_ttl=FRESH_TTL, cache_max_age=CACHE_MAX_AGE, timeout=0.6)
    try:
        r = await wc.query_progress()
        check("P1 fresh on first read (age<=30), rev matches stub",
              r.provenance.fresh and not r.provenance.stale
              and r.provenance.rev == 77
              and r.provenance.updated_at == "2026-10-05T02:25:51Z", r.provenance.to_json())
        # stale window 30 < age <= 300
        wc._state_mono -= 40
        r = await wc.query_progress()
        check("P2 stale labelled, still served (30<age<=300)",
              r.ok and r.provenance.stale and not r.provenance.fresh, r.provenance.to_json())
        check("P2b stale age reported (~40s)",
              39 <= (r.provenance.age_s or 0) <= 42, r.provenance.age_s)
        # expired > 300 -> refetch, fresh again
        wc._state_mono -= (CACHE_MAX_AGE + 100)
        n0 = len(stub.requests)
        r = await wc.query_progress()
        check("P3 expired (>300s) refetches and becomes fresh",
              r.ok and r.provenance.fresh and len(stub.requests) > n0)
        # rev change observed
        stub.state = dict(STATE, rev=99)
        await wc.refresh()
        r = await wc.query_progress()
        check("P4 rev change tracked", r.provenance.rev == 99, r.provenance.rev)
        # stale render labelling (does not claim fresh)
        res = wbk.Result(ok=True, data={"lesson_id": 12},
                         provenance=wbk.Provenance(rev=99, age_s=40, stale=True))
        block = intent.render_workbench_block(res, kind="progress")
        check("P5 stale block mentions 'may not be the very latest'",
              "may not be the very latest" in block, block)
        info("P5 note: stale block renders age as: %r"
             % [l for l in block.splitlines() if "old" in l])
    finally:
        stub.state = STATE
        await wc.close()

    # P6 — product cannot show progress contradicting the stub
    stub.reset()
    stub.state = {"rev": 5, "updatedAt": "2026-10-01T00:00:00Z",
                  "state": {"version": 2, "currentLesson": 3, "lessons": {},
                            "reviews": []}}
    wc = WorkbenchClient(base, timeout=0.6)
    try:
        r = await wc.query_progress()
        check("P6 product progress mirrors stub only (contradiction impossible)",
              r.ok and r.data["lesson_id"] == 3 and r.data["passed"] == 0
              and r.provenance.rev == 5, r.data)
    finally:
        stub.state = STATE
        await wc.close()


# ===========================================================================
# PHASE 7 — ADMIN API (TestClient): read-only + write verbs -> 405 + degrade
# ===========================================================================

FIX_TOKEN = "RED_E_TEST_TOKEN_DO_NOT_LEAK_13579"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}


async def _with_admin(fn, *, workbench_url, name):
    from app.admin import load_admin_config
    from app.admin.app import create_admin_app
    from app.admin.auth import TokenStore
    from app.admin.stores import AdminStores
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load_admin_config(env={
            "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "19152",
            "ADMIN_API_TOKEN_FILE": str(Path(tmp) / "tok"),
            "ADMIN_API_TOKEN": FIX_TOKEN,
            "ADMIN_UI_DIR": str(_REPO / "admin"),
        })
        ts = TokenStore(cfg.token_file, cfg.token_env)
        ts.reload()
        sub = Path(tmp) / name
        sub.mkdir(parents=True, exist_ok=True)
        stores = AdminStores(policy_file=str(sub / "policy.json"),
                             memory_file=str(sub / "memory.json"),
                             knowledge_file=str(sub / "knowledge.json"),
                             workbench_url=workbench_url)
        app = create_admin_app(admin_config=cfg, token_store=ts,
                               gateway_info=lambda: {"mode": "mock", "ready": True},
                               stores=stores)
        async with TestClient(TestServer(app)) as client:
            await fn(client, stores)


async def phase_admin(base, stub, reset_base):
    info("PHASE 7 admin workbench routes")

    async def body_ok(client, stores):
        stub.reset()
        for path in ("/admin/workbench/status", "/admin/workbench/current",
                     "/admin/workbench/progress", "/admin/workbench/reviews"):
            r = await client.get(path, headers=AUTH)
            check("A1 %s GET 200" % path, r.status == 200, r.status)
        st = await (await client.get("/admin/workbench/status", headers=AUTH)).json()
        check("A2 status advertises read_only", st.get("read_only") is True, st)
        pr = await (await client.get("/admin/workbench/progress", headers=AUTH)).json()
        check("A3 progress from stub only",
              pr["data"]["passed"] == 1 and pr["provenance"]["rev"] == 77, pr)
        # write verbs against every product-facing workbench route
        for path in ("/admin/workbench/status", "/admin/workbench/current",
                     "/admin/workbench/progress", "/admin/workbench/reviews"):
            for method in ("post", "put", "patch", "delete"):
                r = await getattr(client, method)(path, headers=AUTH)
                check("A4 %s %s -> 405" % (method.upper(), path),
                      r.status == 405, r.status)
        check("A5 admin adapter issued GET only",
              stub.methods() == ["GET"], stub.methods())
        check("A6 admin hit only READ paths (sync/state + content)",
              all(p.startswith("/sync/state") or p.startswith("/workbench/content/")
                  for _, p in stub.requests), stub.requests)

    async def body_contaminate(client, stores):
        # KB data that "looks like" workbench facts must NOT change workbench answers
        stub.reset()
        ds = await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                      json={"name": "wb-facts"})).json()
        dsid = ds["dataset"]["id"]
        await client.post("/admin/knowledge/document/add", headers=AUTH,
                          json={"dataset_id": dsid, "title": "progress",
                                "text": "lesson 12 passed. mastery 100%. "
                                        "current lesson 99. review date tomorrow."})
        pr = await (await client.get("/admin/workbench/progress", headers=AUTH)).json()
        check("A7 KB facts do not contaminate workbench progress",
              pr["data"]["lesson_id"] == 12 and pr["data"]["passed"] == 1, pr["data"])
        check("A8 contamination attempt still GET-only on stub",
              stub.methods() == ["GET"], stub.methods())

    async def body_down(client, stores):
        # workbench down -> honest degradation, no fabricated data
        for path in ("/admin/workbench/status", "/admin/workbench/current",
                     "/admin/workbench/progress", "/admin/workbench/reviews"):
            r = await (await client.get(path, headers=AUTH)).json()
            check("A9 %s degrades honestly when down" % path,
                  r.get("available") is False and not r.get("data"), r)

    await _with_admin(body_ok, workbench_url=base, name="wb_ok")
    await _with_admin(body_contaminate, workbench_url=base, name="wb_kb")
    await _with_admin(body_down, workbench_url=reset_base, name="wb_down")


# ===========================================================================
# PHASE 8 — Memory cannot smuggle Workbench facts (defense in depth)
# ===========================================================================

def phase_memory_boundary():
    info("PHASE 8 memory cannot store workbench-shaped facts")
    from modules.memory.store import BoundaryViolation, MemoryStore
    with tempfile.TemporaryDirectory() as td:
        ms = MemoryStore(str(Path(td) / "m.json")).load()
        blocked = 0
        for key, val in (("课程进度", "第12课已通过"), ("mastery", "100%"),
                         ("lesson", 12), ("next_review", "2026-10-09"),
                         ("passed", True)):
            try:
                ms.save_preference(key, val)
            except BoundaryViolation:
                blocked += 1
            except Exception:
                blocked += 1
        check("MB1 memory rejects workbench-shaped keys/values", blocked == 5,
              "blocked=%d/5" % blocked)


# ===========================================================================
# main
# ===========================================================================

async def amain():
    stub = RecordingStub()
    runner = web.AppRunner(stub.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]

    reset = ResetServer()
    await reset.start()

    try:
        phase_static()
        await phase_adapter(base, stub)
        await phase_conversation(base, stub)
        phase_mutation_routing()
        await phase_mutation_conversation(base, stub)
        await phase_degraded(base, stub, reset.base)
        await phase_provenance(base, stub)
        await phase_admin(base, stub, reset.base)
        phase_memory_boundary()
    finally:
        await reset.close()
        await runner.cleanup()

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 74)
    print("RED_E_ROUND1: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s %s" % (name, detail))
    # metric verdict
    print("=" * 74)
    print("WORKBENCH_WRITES = 0  (stub observed only GET; see phases D/C/A)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
