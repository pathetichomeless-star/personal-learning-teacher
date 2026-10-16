"""RED-F round 3 — closure re-attack of the EXACT fixed R-F-1 / R-F-5 cases.

Context: round 1 found the gateway re-attributed a late/superseded assistant
transcript (and the late cancelled done's interrupt notice) to the newest UI
turn; round 2 proved the client-side FINAL-immutability mitigation correct but
insufficient (creation + STREAMING cases remained reachable).  The product
owner then authorized ONE narrowly-scoped change inside `gateway/app/turns.py`:
the `_ui_owns_generation` response-id ownership guard.

This suite re-runs the EXACT fixtures in the FIXED direction:

  Part A — deterministic gateway ownership attacks (real `Connection`, hostile
           orderings) with both the attacks (must now fail) and the legitimate
           behaviours (must be preserved).
  Part B — end-to-end against the adversarial mock upstream: capture the actual
           client-bound message stream for each fixed scenario.
  Part C — replay those streams through the real client `TranscriptStore` and
           assert the LEARNER-VISIBLE transcript.

Assertions of record:
    LATE_FINAL_MUTATION = 0 · OLD_AUDIO_RESUME = 0 (audio surface untouched)
    R-F-1 = CLOSED · R-F-5 = CLOSED · R-F-6 / R-F-7 = DEFENDED
    LEGIT transcript forwarding + legit interrupt + id-less tolerance preserved

Run:
    cd <project-root>/gateway
    DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
        tests/adversarial/red_f/red_f_round3.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parents[2]
_REPO = _GATEWAY.parent
for _p in (str(_GATEWAY), str(_REPO), str(_REPO / "client")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# reuse the round-1 harness (guarded by __main__)
import red_f_round1 as R1                                   # noqa: E402
from app.counters import counters                           # noqa: E402
from src.ui.shared.transcript import (FINAL, INTERRUPTED,   # noqa: E402
                                      STREAMING, TranscriptStore)

RESULTS = []
CAPTURED = {}          # scenario -> captured transcript messages (Part B)


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


def tx_of(msgs):
    return [m for m in msgs if isinstance(m, dict) and m.get("type") == "transcript"]


def parse_strs(ws):
    out = []
    for s in ws.strs:
        try:
            m = json.loads(s)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(m, dict) and m.get("type") == "transcript":
            out.append(m)
    return out


def replay(msgs):
    store = TranscriptStore()
    for m in msgs:
        store.apply(m)
    return store


def _assistant(store):
    return [i for i in store.snapshot() if i["role"] == "assistant"]


# ===========================================================================
# PART A — deterministic gateway ownership attacks + preserved behaviours
# ===========================================================================

def part_a():
    print("\n==== PART A — deterministic gateway ownership re-attack ====")

    # ---------------------------------------------------------------- A1
    # The exact R-F-1 fixture: late final for a SUPERSEDED response.
    async def a1():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            await R1.delta(conn, "r1", 960)
            await R1.end(conn, "r1", "response.done", "completed")
            await R1.created(conn, "r2")           # r2 now owns the live turn
            ws.strs.clear()
            await conn._on_qwen_event({"type": "response.audio_transcript.done",
                                       "response_id": R1.rid_of(conn, "r1"),
                                       "transcript": "late-final-text"})
            await R1.settle(6)
            msgs = parse_strs(ws)
            check("R3-A1.1 stale final is dropped (zero transcript msgs)", msgs == [],
                  ws.strs)
            check("R3-A1.2 no late text anywhere on the wire",
                  not any("late-final-text" in s for s in ws.strs), ws.strs)

    # ---------------------------------------------------------------- A2
    # R-F-6 fixture: transcript.done for a NEVER-CREATED response id.
    async def a2():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            ws.strs.clear()
            await conn._on_qwen_event({"type": "response.audio_transcript.done",
                                       "response_id": "ghost_rid",
                                       "transcript": "PRE-CREATED TEXT"})
            await R1.settle(6)
            check("R3-A2.1 ghost-rid final is dropped (no phantom turn)",
                  parse_strs(ws) == [], ws.strs)

    # ---------------------------------------------------------------- A3
    # The exact R-F-7 gateway fixture: late cancelled done for a SUPERSEDED
    # response must NOT emit the interrupt notice.
    async def a3():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            await R1.delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            await R1.created(conn, "r2")
            ws.strs.clear()
            await R1.end(conn, "r1", "response.done", "cancelled")   # LATE
            await R1.settle(10)
            msgs = parse_strs(ws)
            check("R3-A3.1 superseded cancelled done emits NO interrupted notice",
                  msgs == [], ws.strs)

    # ---------------------------------------------------------------- A4
    # Control: the OWNING response's own transcript still forwards.
    async def a4():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            ws.strs.clear()
            await conn._on_qwen_event({"type": "response.audio_transcript.delta",
                                       "response_id": R1.rid_of(conn, "r1"),
                                       "delta": "hel"})
            await conn._on_qwen_event({"type": "response.audio_transcript.done",
                                       "response_id": R1.rid_of(conn, "r1"),
                                       "transcript": "hello"})
            await R1.settle(6)
            msgs = parse_strs(ws)
            check("R3-A4.1 owning-response delta+final forwarded (turn 1)",
                  len(msgs) == 2 and msgs[0].get("delta") == "hel"
                  and msgs[1].get("text") == "hello"
                  and all(m.get("turn") == 1 for m in msgs), msgs)

    # ---------------------------------------------------------------- A5
    # Control: a POST-SEAL transcript for the newest response still forwards
    # (protects the clean_long ordering used by CLIENT_UI_INTEGRATION).
    async def a5():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            await R1.end(conn, "r1", "response.done", "completed")
            ws.strs.clear()
            await conn._on_qwen_event({"type": "response.audio_transcript.done",
                                       "response_id": R1.rid_of(conn, "r1"),
                                       "transcript": "post-seal text"})
            await R1.settle(6)
            msgs = parse_strs(ws)
            check("R3-A5.1 post-seal newest-response final still forwards (turn 1)",
                  len(msgs) == 1 and msgs[0].get("text") == "post-seal text"
                  and msgs[0].get("turn") == 1, msgs)

    # ---------------------------------------------------------------- A6
    # Control: the legit interrupt — the NEWEST response cancelled after a
    # barge-in (tombstone) still notifies, stamped with its own turn.
    async def a6():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            await R1.delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            ws.strs.clear()
            await R1.end(conn, "r1", "response.done", "cancelled")
            await R1.settle(10)
            msgs = parse_strs(ws)
            check("R3-A6.1 legit interrupt preserved (exactly one notice, turn 1, "
                  "no fabricated text)",
                  len(msgs) == 1 and msgs[0].get("interrupted") is True
                  and msgs[0].get("turn") == 1 and not msgs[0].get("text"), msgs)

    # ---------------------------------------------------------------- A7
    # Mixed storm: r1 stale cancelled (suppressed) THEN r2 cancelled (notified).
    async def a7():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            await R1.delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            await R1.created(conn, "r2")
            ws.strs.clear()
            await R1.end(conn, "r1", "response.done", "cancelled")  # stale -> silent
            await R1.settle(8)
            after_stale = parse_strs(ws)
            check("R3-A7.1 stale cancelled done suppressed in the mixed storm",
                  after_stale == [], ws.strs)
            await R1.end(conn, "r2", "response.done", "cancelled")  # owning -> notify
            await R1.settle(10)
            msgs = parse_strs(ws)
            check("R3-A7.2 the owning response's cancel still notifies (turn 2)",
                  len(msgs) == 1 and msgs[0].get("interrupted") is True
                  and msgs[0].get("turn") == 2, msgs)

    # ---------------------------------------------------------------- A8
    # Id-less tolerance: an output transcript without a response_id forwards
    # (the guard applies only "if response_id is present").
    async def a8():
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            ws.strs.clear()
            await conn._on_qwen_event({"type": "response.audio_transcript.done",
                                       "transcript": "id-less text"})
            await R1.settle(6)
            msgs = parse_strs(ws)
            check("R3-A8.1 id-less output transcript tolerance preserved",
                  len(msgs) == 1 and msgs[0].get("text") == "id-less text", msgs)

    # ---------------------------------------------------------------- A9
    # Audio control: the guard must not alter the audio plane — a late delta
    # for a superseded generation is still guard-dropped, never admitted.
    async def a9():
        before = counters.snapshot()
        clock = R1.Clock()
        with R1.TimeCtl(clock), R1.NoPacer():
            conn, ws = R1.make_conn()
            await R1.created(conn, "r1")
            await R1.delta(conn, "r1", 960)
            await R1.created(conn, "r2")
            mid = counters.snapshot()
            await R1.delta(conn, "r1", 960)        # late audio for superseded r1
            after = counters.snapshot()
            d = R1.cdiff(mid, after)
            check("R3-A9.1 OLD_AUDIO_RESUME=0 (late superseded delta guard-dropped "
                  "only)", d["guard_dropped_pcm_bytes"] == 960
                  and d["admitted_pcm_bytes"] == 0, d)

    asyncio.run(asyncio.wait_for(a1(), 30))
    asyncio.run(asyncio.wait_for(a2(), 30))
    asyncio.run(asyncio.wait_for(a3(), 30))
    asyncio.run(asyncio.wait_for(a4(), 30))
    asyncio.run(asyncio.wait_for(a5(), 30))
    asyncio.run(asyncio.wait_for(a6(), 30))
    asyncio.run(asyncio.wait_for(a7(), 30))
    asyncio.run(asyncio.wait_for(a8(), 30))
    asyncio.run(asyncio.wait_for(a9(), 30))


# ===========================================================================
# PART B — end-to-end: local gateway -> client-bound stream (exact fixtures)
# ===========================================================================

async def _capture(scenario, seconds=3.0):
    msgs, health, dg = await R1._drive_gateway(scenario, seconds=seconds)
    return msgs


async def part_b():
    print("\n==== PART B — end-to-end client-bound streams (fixed fixtures) ====")
    runner = await R1._start_adv_mock()
    try:
        # B1 — R-F-1 ordering: late r1 final + late r1 cancelled done after r2.
        msgs = await _capture("late_done_after_new", seconds=3.0)
        CAPTURED["B1"] = tx_of(msgs)
        tx = CAPTURED["B1"]
        print("   [B1] client-bound transcript msgs: %s" % json.dumps(tx))
        check("R3-B1.1 zero transcript messages reach the client",
              tx == [], tx)
        check("R3-B1.2 no late text / no spurious interrupt on the wire",
              not any("late-final-text" in json.dumps(m) or m.get("interrupted")
                      for m in tx), tx)

        # B2 — R-F-5 ordering: late r1 final while r2 is STREAMING.
        msgs = await _capture("late_final_midstream", seconds=3.0)
        CAPTURED["B2"] = tx_of(msgs)
        tx = CAPTURED["B2"]
        print("   [B2] client-bound transcript msgs: %s" % json.dumps(tx))
        check("R3-B2.1 stale r1 text never forwarded",
              not any(m.get("text") == "STALE-R1-TEXT" for m in tx), tx)
        check("R3-B2.2 r2's real final forwarded with turn 2",
              any(m.get("text") == "Welcome to class" and m.get("final")
                  and m.get("turn") == 2 for m in tx), tx)

        # B3 — R-F-6 ordering: ghost final before any created; the real turn's
        # post-seal text still forwards.
        msgs = await _capture("precreated_final", seconds=3.0)
        CAPTURED["B3"] = tx_of(msgs)
        tx = CAPTURED["B3"]
        print("   [B3] client-bound transcript msgs: %s" % json.dumps(tx))
        check("R3-B3.1 ghost final never forwarded (no phantom turn)",
              not any(m.get("text") == "PRE-CREATED TEXT" for m in tx), tx)
        check("R3-B3.2 the real turn's text still forwards (turn 1, post-seal)",
              any(m.get("text") == "real turn text" and m.get("turn") == 1
                  for m in tx), tx)
        check("R3-B3.3 no turn-0 message on the wire",
              not any(m.get("turn") == 0 for m in tx), tx)

        # B4 — control: barge-in on the newest response -> legit interrupt only.
        msgs = await _capture("bargein", seconds=3.0)
        CAPTURED["B4"] = tx_of(msgs)
        tx = CAPTURED["B4"]
        print("   [B4] client-bound transcript msgs: %s" % json.dumps(tx))
        interrupted = [m for m in tx if m.get("interrupted")]
        check("R3-B4.1 exactly one interrupted notice, stamped turn 1, no text",
              len(interrupted) == 1 and interrupted[0].get("turn") == 1
              and not interrupted[0].get("text"), tx)
        check("R3-B4.2 the interrupt is the only transcript message",
              len(tx) == 1, tx)

        # B5 — late final for an already-completed r1 after r2 started.
        msgs = await _capture("late_final", seconds=3.0)
        CAPTURED["B5"] = tx_of(msgs)
        tx = CAPTURED["B5"]
        print("   [B5] client-bound transcript msgs: %s" % json.dumps(tx))
        check("R3-B5.1 completed-response's late final dropped (no STALE-FINAL)",
              not any("STALE-FINAL" in json.dumps(m) for m in tx), tx)
        check("R3-B5.2 no interrupted notice for a completed response",
              not any(m.get("interrupted") for m in tx), tx)
    finally:
        await runner.cleanup()


# ===========================================================================
# PART C — learner-visible replay through the real TranscriptStore
# ===========================================================================

def part_c():
    print("\n==== PART C — learner-visible transcript (real store replay) ====")

    # C1 — the R-F-1 stream must not present stale text or a phantom interrupt.
    store = replay(CAPTURED.get("B1", []))
    asst = _assistant(store)
    check("R3-C1.1 no assistant bubble carries the stale text",
          not any("late-final-text" in (i["text"] or "") for i in asst), asst)
    check("R3-C1.2 no INTERRUPTED bubble is fabricated",
          not any(i["state"] == INTERRUPTED for i in asst), asst)

    # C2 — the R-F-5 stream must show r2's REAL reply on turn 2.
    store = replay(CAPTURED.get("B2", []))
    asst = _assistant(store)
    t2 = [i for i in asst if i["turn"] == 2]
    t2_text = t2[-1]["text"] if t2 else None
    check("R3-C2.1 learner-visible turn-2 reply is the REAL text (FINAL)",
          t2_text == "Welcome to class" and t2[-1]["state"] == FINAL, asst)
    check("R3-C2.2 stale text appears in NO bubble",
          not any("STALE-R1-TEXT" in (i["text"] or "") for i in asst), asst)

    # C3 — the R-F-6 stream must not create a phantom turn-0 bubble.
    store = replay(CAPTURED.get("B3", []))
    asst = _assistant(store)
    check("R3-C3.1 no phantom turn-0 bubble; the real turn-1 reply is displayed",
          not any(i["turn"] == 0 for i in asst)
          and any(i["turn"] == 1 and i["text"] == "real turn text"
                  and i["state"] == FINAL for i in asst), asst)


# ===========================================================================
# runner
# ===========================================================================

METRIC_GROUPS = {
    "R-F-1 (stale final / spurious interrupt dropped)": (
        "R3-A1", "R3-A3", "R3-A7", "R3-B1", "R3-B5", "R3-C1"),
    "R-F-5 (no cross-turn mutation at the composed boundary)": (
        "R3-B2", "R3-C2"),
    "R-F-6 (pre-created final dropped)": ("R3-A2", "R3-B3", "R3-C3"),
    "R-F-7 (superseded interrupt suppressed)": ("R3-A3", "R3-A7", "R3-B4"),
    "LATE_FINAL_MUTATION=0": (
        "R3-A1", "R3-A7", "R3-B1", "R3-B2", "R3-B5", "R3-C1", "R3-C2"),
    "LEGIT_TRANSCRIPT_FORWARDING_PRESERVED": ("R3-A4", "R3-A5", "R3-A8",
                                              "R3-B3"),
    "LEGIT_INTERRUPT_PRESERVED": ("R3-A6", "R3-A7", "R3-B4"),
    "ID_LESS_TOLERANCE_PRESERVED": ("R3-A8",),
    "OLD_AUDIO_RESUME=0 (audio surface untouched)": ("R3-A9",),
}
CLOSURE_VERDICTS = {
    "R-F-1 = CLOSED": ("R3-A1", "R3-A3", "R3-A7", "R3-B1", "R3-B5", "R3-C1"),
    "R-F-5 = CLOSED": ("R3-B2", "R3-C2"),
}


def _summary():
    print("\n" + "=" * 72)
    print("RED_F_ROUND3 VERDICTS")
    by_name = {}
    for name, ok, detail in RESULTS:
        by_name.setdefault(name, (ok, detail))
    verdicts = {}
    for metric, prefixes in METRIC_GROUPS.items():
        evaluated = [(n, ok, d) for n, (ok, d) in by_name.items()
                     if n.startswith(prefixes)]
        bad = [n for n, ok, _ in evaluated if not ok]
        verdicts[metric] = not bad
        print("  %-46s %s (%d checks%s)"
              % (metric, "CONFIRMED" if not bad else "FALSIFIED",
                 len(evaluated), "" if not bad else ", failing: %s"
                 % ", ".join(bad)))
    print("-" * 72)
    for label, prefixes in CLOSURE_VERDICTS.items():
        evaluated = [(n, ok, d) for n, (ok, d) in by_name.items()
                     if n.startswith(prefixes)]
        bad = [n for n, ok, _ in evaluated if not ok]
        print("  %-46s %s" % (label, "CLOSED" if not bad else "STILL_OPEN"))


def main():
    part_a()
    asyncio.run(asyncio.wait_for(part_b(), 180))
    part_c()
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 72)
    print("RED_F_ROUND3: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    _summary()
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
