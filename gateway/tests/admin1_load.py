"""ADMIN-1 Phase 9: administrative load vs R-1f audio non-regression.

Runs the existing mock/synthetic R-1f harness (``r1f_runtime``) while hammering the six
ADMIN endpoints far harder than the UI ever will (health/metrics/sessions every ~150 ms,
diag-summary every ~450 ms), then evaluates the R-1f acceptance gates on the same counters.

The pass must NOT come from pacing rebase/fatal-stall tolerance: the checks below require
zero fatal stalls, zero guard violations, zero short intervals and in-band steady-segment
rates.  Rebase counts are recorded for transparency.  No paid Qwen session is used.

Local run:

    DYLD_LIBRARY_PATH=/tmp/opus/lib gateway/.venv/bin/python gateway/tests/admin1_load.py
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for p in (str(_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

TOKEN = "ADMIN1_LOAD_TEST_BEARER_TOKEN_0123456789"
_admin_port = 18112

# the harness pins the bridge to 18110/18111 (BRIDGE_WS / BRIDGE_HTTP)
os.environ["WS_PORT"] = "18110"
os.environ["HTTP_PORT"] = "18111"
os.environ["ADMIN_ENABLED"] = "1"
os.environ["ADMIN_BIND"] = "127.0.0.1"
os.environ["ADMIN_PORT"] = str(_admin_port)
os.environ["ADMIN_UI_DIR"] = str(_ROOT / "admin")
_tmp = tempfile.mkdtemp(prefix="admin1-load-")
_token_file = Path(_tmp) / "admin_api_token"
_token_file.write_text(TOKEN + "\n")
os.chmod(_token_file, 0o600)
os.environ["ADMIN_API_TOKEN_FILE"] = str(_token_file)

import aiohttp                                                    # noqa: E402

import r1f_runtime as rt                                          # noqa: E402
from app import main as app_main                                  # noqa: E402
from app.admin import load_admin_config                           # noqa: E402
from app.admin.service import start_admin_listener, stop_admin_listener  # noqa: E402
from app.counters import counters                                 # noqa: E402

ADMIN_BASE = "http://127.0.0.1:%d" % _admin_port
FAST = ("/admin/health", "/admin/metrics", "/admin/sessions")
SLOW = ("/admin/diag-summary", "/admin/telemetry", "/admin/version")

_results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    _results.append(ok)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  <- %r" % (detail,)))
    return ok


async def admin_poll(stop_evt, stats):
    hdr = {"Authorization": "Bearer " + TOKEN}
    async with aiohttp.ClientSession() as s:
        i = 0
        while not stop_evt.is_set():
            paths = FAST + (SLOW if i % 3 == 0 else ())
            for path in paths:
                t0 = time.perf_counter()
                try:
                    async with s.get(ADMIN_BASE + path, headers=hdr) as r:
                        await r.read()
                        stats["n"] += 1
                        stats["codes"][r.status] = stats["codes"].get(r.status, 0) + 1
                        if r.status != 200:
                            stats["bad"] += 1
                except Exception as e:                          # noqa: BLE001
                    stats["errors"] += 1
                    stats["last_error"] = str(e)
                dt = (time.perf_counter() - t0) * 1000.0
                stats["max_ms"] = max(stats["max_ms"], dt)
            i += 1
            await asyncio.sleep(0.15)


def gate_deltas(prefix, delta, after):
    checks = [
        ("%s: pacer fatal stalls 0" % prefix, delta.get("pacer_fatal_stalls", 0) == 0,
         delta.get("pacer_fatal_stalls")),
        ("%s: slow-send guard violations 0" % prefix,
         delta.get("slow_send_guard_violations", 0) == 0,
         delta.get("slow_send_guard_violations")),
        ("%s: short intervals 0" % prefix, delta.get("pacer_short_interval_count", 0) == 0,
         delta.get("pacer_short_interval_count")),
        ("%s: no store-cap transitions" % prefix, delta.get("cap_transitions_total", 0) == 0,
         delta.get("cap_transitions_total")),
        ("%s: wire excess <= 1" % prefix, (after.get("wire_rate_excess_frames_max") or 0) <= 1,
         after.get("wire_rate_excess_frames_max")),
        ("%s: single pacer ever" % prefix,
         (after.get("active_pacer_tasks_max") or 0) <= 1,
         after.get("active_pacer_tasks_max")),
        ("%s: no unknown send outcome (pre)" % prefix, True, ""),
        ("%s: no unknown send outcome" % prefix,
         delta.get("send_outcome_unknown_frames", 0) == 0,
         delta.get("send_outcome_unknown_frames")),
        ("%s: no post-terminal sends" % prefix, delta.get("post_terminal_sends_total", 0) == 0,
         delta.get("post_terminal_sends_total")),
    ]
    for name, cond, detail in checks:
        if name.endswith("(pre)"):
            continue
        check(name, cond, detail)
    # steady-segment rate evidence applies to clean (non-aborted) runs only; an aborted
    # barge-in run is judged by its own R-1f gates (barge-in sequence completeness).
    if not delta.get("barge_in_sequences_total", 0):
        check("%s: qualifying steady segments >= 1" % prefix,
              (after.get("steady_pacer_segments_qualifying_total") or 0) >= 1,
              after.get("steady_pacer_segments_qualifying_total"))
        check("%s: fps in band" % prefix,
              (after.get("steady_segment_rate_fps_min") or 0) >= 49.5
              and (after.get("steady_segment_rate_fps_max") or 99) <= 50.5,
              (after.get("steady_segment_rate_fps_min"), after.get("steady_segment_rate_fps_max")))
        check("%s: means in band" % prefix,
              (after.get("steady_segment_mean_inter_send_ms_min") or 0) >= 19.80
              and (after.get("steady_segment_mean_inter_send_ms_max") or 99) <= 20.20,
              (after.get("steady_segment_mean_inter_send_ms_min"),
               after.get("steady_segment_mean_inter_send_ms_max")))
    else:
        check("%s: barge-in completed (no incomplete sequence)" % prefix,
              delta.get("barge_in_sequence_incomplete", 0) == 0,
              delta.get("barge_in_sequence_incomplete"))
        check("%s: steady-segment rate gates N/A (aborted run, judged by barge gates)" % prefix,
              True)


async def amain():
    gateway_info = lambda: {"mode": "real" if app_main.load_config().qwen.is_real else "mock",
                            "ready": bool(app_main.load_config().qwen.ready)}
    runners = await start_admin_listener(admin_config=load_admin_config(),
                                         gateway_info=gateway_info)
    check("admin listener started for the load test", len(runners) == 1, runners)

    stats = {"n": 0, "bad": 0, "errors": 0, "max_ms": 0.0, "codes": {}, "last_error": None}
    stop_evt = asyncio.Event()
    poll_task = asyncio.create_task(admin_poll(stop_evt, stats))

    wanted = set(os.environ.get("ADMIN1_LOAD_SCENARIOS", "clean_long,rapid_barge").split(","))
    picks = [s for s in rt.scenarios() if s[0] in wanted]
    check("requested load scenarios found in the harness", len(picks) == len(wanted),
          ([s[0] for s in picks], sorted(wanted)))
    summary = {}
    try:
        for idx, (name, cfg, fn, expect) in enumerate(picks):
            if idx:
                await asyncio.sleep(1.0)      # let the previous bridge release its ports
            ok, delta, after = await rt.run_scenario(name, cfg, fn, expect)
            check("R-1f harness gates pass under admin load: %s" % name, ok)
            gate_deltas(name, delta, after)
            summary[name] = {
                "pacer_rebases": delta.get("pacer_rebases", 0),
                "sent_confirmed": delta.get("sent_confirmed_frames", 0),
                "segments_qualifying": after.get("steady_pacer_segments_qualifying_total"),
                "fps": (after.get("steady_segment_rate_fps_min"),
                        after.get("steady_segment_rate_fps_max")),
            }
    finally:
        stop_evt.set()
        await poll_task
        await stop_admin_listener(runners)

    check("admin load generated a meaningful number of requests", stats["n"] >= 20, stats["n"])
    check("every admin response was 200", stats["bad"] == 0 and stats["codes"] == {200: stats["n"]},
          stats)
    check("no admin request errored", stats["errors"] == 0, stats.get("last_error"))
    check("admin response latency stayed bounded (< 1s)", stats["max_ms"] < 1000, stats["max_ms"])
    print("\nload summary: requests=%d max_ms=%.1f  %s"
          % (stats["n"], stats["max_ms"], json.dumps(summary)))
    total, passed = len(_results), sum(_results)
    print("\nADMIN1_LOAD: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))