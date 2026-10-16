"""WORKBENCH-1 deterministic suite — read-only adapter contract.

Runs standalone:  python tests/workbench1_tests.py   (from gateway/, venv)
Spins a local fake workbench (aiohttp) and verifies: DTO normalization
(lesson/progress/review), FRESH_TTL=30s / CACHE_MAX_AGE=300s semantics,
stale labelling, rev-keyed behaviour, malformed/partial/down degradation,
timeout handling, and the NO-WRITE boundary (runtime + static).
"""

import asyncio
import os
import re
import sys
import time
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from aiohttp import web                                          # noqa: E402

from modules.adapters.workbench import (CACHE_MAX_AGE, FRESH_TTL,  # noqa: E402
                                        WorkbenchClient)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


# review dates are relative to the real "today" so the suite is date-independent
_TODAY = date.today()
_D_PAST3 = (_TODAY - timedelta(days=3)).isoformat()     # due
_D_PAST2 = (_TODAY - timedelta(days=2)).isoformat()     # done → irrelevant
_D_FUTURE5 = (_TODAY + timedelta(days=5)).isoformat()   # future
_D_FUTURE12 = (_TODAY + timedelta(days=12)).isoformat()  # future

STATE = {
    "rev": 77,
    "updatedAt": "2026-10-05T02:25:51Z",
    "state": {
        "version": 2, "currentLesson": 12,
        "lessons": {
            "1": {"status": "review_required", "decision": "REVIEW"},
            "2": {"status": "passed", "decision": "PASS"},
            "3": {"status": "repeat_required", "decision": "REPEAT"},
        },
        "reviews": [
            {"id": "foundation:12:walked:+1", "refId": "12:walked",
             "nextReviewAt": _D_PAST3, "done": False},
            {"id": "foundation:12:walked:+3", "refId": "12:walked",
             "nextReviewAt": _D_FUTURE5, "done": False},
            {"id": "foundation:12:talked:+3", "refId": "12:talked",
             "nextReviewAt": _D_PAST2, "done": True},
            {"id": "ielts:w3413:+1", "refId": "w3413",
             "nextReviewAt": _D_FUTURE12, "done": False},
        ],
    },
}

CONTENT12 = {"lesson": 12, "unit": "一般过去时（规则动词 -ed）", "theme": "昨天",
             "objectives": ["用 -ed 说过去做过的事。", "记住时间标记。",
                            "掌握 -ed 拼写规则。", "第五个目标（会被截断）"]}


class FakeWorkbench:
    def __init__(self):
        self.mode = "ok"          # ok | malformed | error500 | slow | no_content
        self.requests = []        # (method, path)
        self.state = STATE

    async def sync_health(self, request):
        self.requests.append(("GET", request.path))
        return web.json_response({"ok": True})

    async def sync_state(self, request):
        self.requests.append((request.method, request.path))
        if self.mode == "error500":
            return web.Response(status=500)
        if self.mode == "slow":
            await asyncio.sleep(5)
        if self.mode == "malformed":
            return web.json_response({"oops": True})
        return web.json_response(self.state)

    async def content(self, request):
        self.requests.append((request.method, request.path))
        if self.mode == "no_content":
            return web.Response(status=404)
        day = int(request.match_info["day"])
        if day == 12:
            return web.json_response(CONTENT12)
        return web.Response(status=404)

    def app(self):
        app = web.Application()
        app.router.add_get("/sync/health", self.sync_health)
        app.router.add_route("*", "/sync/state", self.sync_state)
        app.router.add_get("/workbench/content/day{day}.json", self.content)
        return app


async def amain():
    fake = FakeWorkbench()
    runner = web.AppRunner(fake.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = "http://127.0.0.1:%d" % port

    # ---- W1: continue_lesson normalization --------------------------------
    wc = WorkbenchClient(base)
    res = await wc.continue_lesson()
    check("W1 continue ok", res.ok and res.data["lesson_id"] == 12)
    check("W1b unit title from content", res.data["title"] == "一般过去时（规则动词 -ed）")
    check("W1c objectives capped at 4", len(res.data["objectives"]) == 4)
    check("W1d provenance rev + fresh",
          res.provenance.rev == 77 and res.provenance.fresh is True
          and res.provenance.stale is False)

    # ---- W2: progress counts ---------------------------------------------
    res = await wc.query_progress()
    check("W2 progress counts", res.data["passed"] == 1
          and res.data["review_required"] == 1 and res.data["repeat_required"] == 1)
    check("W2b lessons_started", res.data["lessons_started"] == 3)
    check("W2c due count excludes done and future",
          res.data["due_count"] == 1 and res.data["next_due"] == _D_PAST3,
          repr(res.data))
    check("W2d due words deduped", res.data["due_words"] == ["walked"])

    # ---- W3: review scope strips other fields -----------------------------
    res = await wc.query_progress("review")
    check("W3 review scope", "passed" not in res.data
          and "repeat_required" not in res.data
          and res.data["due_count"] == 1)

    # ---- W4: cache fresh → no refetch -------------------------------------
    n_before = sum(1 for m, p in fake.requests if p == "/sync/state")
    await wc.query_progress()
    n_after = sum(1 for m, p in fake.requests if p == "/sync/state")
    check("W4 fresh cache avoids refetch", n_after == n_before)

    # ---- W5: stale labelling (age 40s, within CACHE_MAX_AGE) --------------
    wc._state_mono = time.monotonic() - 40
    res = await wc.query_progress()
    check("W5 stale but served", res.ok and res.provenance.stale is True
          and res.provenance.fresh is False)
    check("W5b age reported", 39 <= (res.provenance.age_s or 0) <= 42)

    # ---- W6: age > CACHE_MAX_AGE → refetch --------------------------------
    wc._state_mono = time.monotonic() - (CACHE_MAX_AGE + 100)
    n_before = sum(1 for m, p in fake.requests if p == "/sync/state")
    res = await wc.query_progress()
    n_after = sum(1 for m, p in fake.requests if p == "/sync/state")
    check("W6 expired cache refetches", res.ok and n_after == n_before + 1
          and res.provenance.fresh is True)

    # ---- W7: rev change observed ------------------------------------------
    fake.state = dict(STATE, rev=78)
    await wc.refresh()
    res = await wc.query_progress()
    check("W7 rev tracked", res.provenance.rev == 78)
    fake.state = STATE

    # ---- W8: malformed state ----------------------------------------------
    wc2 = WorkbenchClient(base)
    fake.mode = "malformed"
    res = await wc2.continue_lesson()
    check("W8 malformed -> unavailable", not res.ok and res.reason == "malformed_state",
          repr(res))
    fake.mode = "ok"

    # ---- W9: server 500 ----------------------------------------------------
    wc3 = WorkbenchClient(base)
    fake.mode = "error500"
    res = await wc3.continue_lesson()
    check("W9 500 -> unavailable", not res.ok)
    fake.mode = "ok"

    # ---- W10: content missing -> partial -----------------------------------
    wc4 = WorkbenchClient(base)
    fake.mode = "no_content"
    res = await wc4.continue_lesson()
    check("W10 partial when content missing", res.ok and res.partial
          and res.data["title"] is None and res.provenance.partial)
    fake.mode = "ok"

    # ---- W11: timeout -------------------------------------------------------
    wc5 = WorkbenchClient(base, timeout=0.3)
    fake.mode = "slow"
    t0 = time.monotonic()
    res = await wc5.continue_lesson()
    took = time.monotonic() - t0
    check("W11 timeout bounded", not res.ok and took < 1.5, "%.2fs" % took)
    fake.mode = "ok"

    # ---- W12: workbench down (connection refused) ---------------------------
    await runner.cleanup()
    wc6 = WorkbenchClient(base, timeout=0.5)
    res = await wc6.continue_lesson()
    check("W12 down -> unavailable", not res.ok and res.reason == "sync_down")

    # ---- W13: down but cache < 300s → still serves stale --------------------
    wc7 = WorkbenchClient(base)
    wc7._state = STATE
    wc7._state_mono = time.monotonic() - 100
    res = await wc7.query_progress()
    check("W13 stale cache served while down", res.ok and res.provenance.stale)
    wc7._state_mono = time.monotonic() - (CACHE_MAX_AGE + 10)
    res = await wc7.query_progress()
    check("W13b too-old cache never served", not res.ok
          and res.reason == "stale_cache")

    # ---- W14: NO-WRITE boundary (runtime + static) ---------------------------
    methods = {m for m, _ in fake.requests}
    check("W14 runtime: GET only", methods == {"GET"}, repr(methods))
    src = open(os.path.join(_REPO, "modules", "adapters", "workbench.py"),
               encoding="utf-8").read()
    check("W14b static: no PUT/post writing",
          not re.search(r'\.(put|post|patch|delete)\(', src)
          and '"PUT"' not in src)

    # ---- W15: constants ------------------------------------------------------
    check("W15 FRESH_TTL 30s", FRESH_TTL == 30.0)
    check("W15b CACHE_MAX_AGE 300s", CACHE_MAX_AGE == 300.0)

    await wc.close()
    await wc2.close()
    await wc3.close()
    await wc4.close()
    await wc5.close()
    await wc6.close()
    await wc7.close()


def main():
    asyncio.run(amain())
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 70)
    print("WORKBENCH1_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())