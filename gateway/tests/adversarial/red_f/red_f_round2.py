"""RED-F round 2 — re-attack of the R-F-1 mitigation + realtime re-check.

The R-F-1 gateway defect (a late assistant transcript for a superseded/cancelled
response is re-attributed by `gateway/app/turns.py` to the *newest* turn key) was
NOT fixable in the frozen gateway, so the remediation lead closed the
*observable* defect in the consumer: `client/src/ui/shared/transcript.py` now
makes a FINAL bubble immutable.

ROUND-3 CLOSURE (the deferral was lifted by explicit authorization): the
minimal response-id ownership guard now lives in `gateway/app/turns.py`
(`_ui_owns_generation`), so both stale artifacts — the late final AND the late
cancelled done's spurious interrupt — are dropped before they reach the wire.
The D-checks below were updated to the post-fix semantics (they previously
documented the open defect); Part C remains a store-level (defense-in-depth)
matrix, since those message shapes are no longer producible end-to-end.

This suite:
  Part C — direct TranscriptStore (client) attack matrix.
  Part D — end-to-end: a LOCAL mock gateway (real `QwenClient` + adversarial
           upstream) -> capture the actual client-bound message stream -> replay
           it through the real `TranscriptStore` -> assert the learner-visible
           transcript is NOT mutated.

Run:
    cd <project-root>/gateway
    DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
        tests/adversarial/red_f/red_f_round2.py
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

# reuse the round-1 harness (safe: guarded by __main__)
import red_f_round1 as R1                                   # noqa: E402
from src.ui.shared.transcript import (FINAL, INTERRUPTED,   # noqa: E402
                                      STREAMING, TranscriptStore)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


def msg(role, **kw):
    base = {"type": "transcript", "role": role, "delta": None, "text": None,
            "final": False, "interrupted": False, "turn": 1}
    base.update(kw)
    return base


def replay(messages, store=None):
    """Feed the captured gateway message stream into a fresh TranscriptStore."""
    store = store or TranscriptStore()
    for m in messages:
        if isinstance(m, dict) and m.get("type") == "transcript":
            store.apply(m)
    return store


def _assistant(store):
    return [i for i in store.snapshot() if i["role"] == "assistant"]


# ===========================================================================
# PART C — direct client-store attack matrix
# ===========================================================================

def part_c_store_attacks():
    print("\n==== PART C — TranscriptStore attack matrix ====")

    # C1 same-text late final = no-op
    s = TranscriptStore()
    s.apply(msg("assistant", text="A", final=True, turn=1))
    check("C1 same-text late final is a no-op",
          s.apply(msg("assistant", text="A", final=True, turn=1)) is None
          and s.snapshot()[-1]["text"] == "A", s.snapshot())

    # C2 late delta after FINAL = dropped
    s = TranscriptStore()
    s.apply(msg("assistant", text="done", final=True, turn=3))
    check("C2 late delta after FINAL ignored",
          s.apply(msg("assistant", delta="more", turn=3)) is None
          and s.snapshot()[-1]["text"] == "done", s.snapshot())

    # C3 late final for an OLDER turn number = dropped
    s = TranscriptStore()
    s.apply(msg("assistant", text="new", final=True, turn=5))
    check("C3 late final for an older turn ignored",
          s.apply(msg("assistant", text="old", final=True, turn=4)) is None
          and s.snapshot()[-1]["text"] == "new", s.snapshot())

    # C4 interrupted stamp on a FINAL turn = no-op
    s = TranscriptStore()
    s.apply(msg("assistant", text="finished", final=True, turn=2))
    check("C4 interrupted stamp on a FINAL turn is a no-op",
          s.apply(msg("assistant", final=True, interrupted=True, turn=2)) is None
          and s.snapshot()[-1]["state"] == FINAL, s.snapshot())

    # C5 gate: did the mitigation actually close the ORIGINAL R-F-1 creation case?
    # A stale final arriving when the current turn has NO bubble yet CREATES it.
    s = TranscriptStore()
    s.apply(msg("assistant", text="r1 real", final=True, turn=1))
    s.apply(msg("assistant", text="STALE-R1-TEXT", final=True, turn=2))  # stale, turn2 absent
    turns = {i["turn"]: i for i in _assistant(s)}
    check("C5 DEFEAT: stale final CREATES the (absent) current turn's bubble",
          turns.get(2, {}).get("text") == "STALE-R1-TEXT",
          s.snapshot())

    # C6 DEFEAT: stale final overwrites a STREAMING current turn + finalizes early
    s = TranscriptStore()
    s.apply(msg("assistant", text="r1 real", final=True, turn=1))
    s.apply(msg("assistant", delta="Wel", turn=2))                 # r2 STREAMING
    changed = s.apply(msg("assistant", text="STALE-R1-TEXT", final=True, turn=2))
    s.apply(msg("assistant", delta="come", turn=2))                # r2 continues
    s.apply(msg("assistant", final=True, turn=2))                  # r2 own final
    t2 = [i for i in _assistant(s) if i["turn"] == 2][-1]
    check("C6 DEFEAT: stale final overwrites a STREAMING turn and finalizes it",
          changed is not None and t2["text"] == "STALE-R1-TEXT"
          and t2["state"] == FINAL, t2)
    check("C6b DEFEAT: the real turn-2 text is lost", "come" not in t2["text"], t2)

    # C7 turn=None stale final while streaming (latent; gateway always sends int)
    s = TranscriptStore()
    s.apply(msg("assistant", delta="real ", turn=2))
    s.apply(msg("assistant", text="STALE", final=True, turn=None))
    t2 = [i for i in _assistant(s) if i["turn"] == 2][-1]
    check("C7 (latent) turn=None stale final overwrites the streaming turn",
          t2["text"] == "STALE", t2)

    # C8 late student/user-role final overwriting a STREAMING user bubble
    s = TranscriptStore()
    s.apply(msg("user", delta="我", turn=2))
    s.apply(msg("user", text="STALE-USER", final=True, turn=2))
    check("C8 DEFEAT: stale USER final overwrites a streaming user bubble",
          s.snapshot()[-1]["text"] == "STALE-USER", s.snapshot())

    # C9 two stale finals in a row: first wins (still stale text)
    s = TranscriptStore()
    s.apply(msg("assistant", text="STALE-1", final=True, turn=2))
    s.apply(msg("assistant", text="STALE-2", final=True, turn=2))
    check("C9 two stale finals: first text kept, second ignored",
          s.snapshot()[-1]["text"] == "STALE-1", s.snapshot())

    # C10 late final BEFORE any response.created (gateway turn key 0)
    s = TranscriptStore()
    s.apply(msg("assistant", text="PRE-CREATED TEXT", final=True, turn=0))
    check("C10 DEFEAT: pre-created stale final yields a phantom turn-0 bubble",
          any(i["turn"] == 0 and i["text"] == "PRE-CREATED TEXT"
              for i in _assistant(s)), s.snapshot())

    # C11 spurious INTERRUPTED (no bubble) then the real turn's final flips it
    s = TranscriptStore()
    s.apply(msg("assistant", final=True, interrupted=True, turn=2))
    check("C11a spurious interrupted with no bubble creates INTERRUPTED",
          s.snapshot()[-1]["state"] == INTERRUPTED, s.snapshot())
    s.apply(msg("assistant", delta="real text", turn=2))
    s.apply(msg("assistant", final=True, turn=2))
    check("C11b the INTERRUPTED mark is erased by the real turn's final",
          s.snapshot()[-1]["state"] == FINAL, s.snapshot())

    # C12 control: the mitigated case (rewrite of an already-FINAL bubble) is closed
    s = TranscriptStore()
    s.apply(msg("assistant", text="real answer", final=True, turn=2))
    check("C12 control: late final cannot rewrite an already-FINAL bubble",
          s.apply(msg("assistant", text="STALE", final=True, turn=2)) is None
          and s.snapshot()[-1]["text"] == "real answer", s.snapshot())


# ===========================================================================
# PART D — end-to-end: local gateway -> capture -> TranscriptStore replay
# ===========================================================================

async def _capture(scenario, seconds=3.0):
    msgs, health, dg = await R1._drive_gateway(scenario, seconds=seconds)
    return msgs


async def _part_d_integration():
    print("\n==== PART D — local gateway -> client-bound stream -> store ====")
    runner = await R1._start_adv_mock()
    try:
        # D1 — original R-F-1 ordering (late_done_after_new), no turn-2 transcript.
        # Round-3 (closure): the gateway ownership guard now DROPS both stale
        # artifacts (the late r1 final and the late r1 cancelled done).
        msgs = await _capture("late_done_after_new", seconds=3.0)
        tx = [m for m in msgs if isinstance(m, dict) and m.get("type") == "transcript"]
        store = replay(tx)
        asst = _assistant(store)
        stale_presented = any(i["text"] == "late-final-text" for i in asst)
        print("   [D1] gateway transcript msgs: %s" % json.dumps(tx))
        print("   [D1] store assistant bubbles: %s" % json.dumps(asst))
        check("D1.1 late_done_after_new: zero transcript messages reach the "
              "client (stale final + spurious interrupt both dropped)",
              tx == [], tx)
        gateway_misattributed = any(
            (m.get("final") and m.get("text") == "late-final-text")
            or (m.get("role") == "assistant" and m.get("interrupted"))
            for m in tx)
        check("D1.2 gateway attribution fault closed: no late final stamped "
              "with the newest turn, no spurious interrupted (pre-round-3 this "
              "check confirmed the mis-attribution)",
              not gateway_misattributed, tx)
        check("D1.3 stale text is never presented as a turn's reply",
              not stale_presented,
              {"assistant_bubbles": asst, "note": "R-F-1 creation case"})

        # D2 — the STREAMING overwrite (late r1 final lands while turn 2 streams)
        msgs = await _capture("late_final_midstream", seconds=3.0)
        tx = [m for m in msgs if isinstance(m, dict) and m.get("type") == "transcript"]
        store = replay(tx)
        asst = _assistant(store)
        t2 = [i for i in asst if i["turn"] == 2]
        t2_text = t2[-1]["text"] if t2 else None
        print("   [D2] gateway transcript msgs: %s" % json.dumps(tx))
        print("   [D2] store assistant bubbles: %s" % json.dumps(asst))
        check("D2.1 late_final_midstream replayed", bool(tx), tx)
        check("D2.2 learner-visible turn-2 text is the REAL r2 text (stale r1 "
              "text never forwarded)",
              t2_text == "Welcome to class",
              {"turn2_text": t2_text, "expected": "Welcome to class",
               "bubbles": asst})

        # D3 — a transcript.done before any response.created (turn key 0)
        msgs = await _capture("precreated_final", seconds=3.0)
        tx = [m for m in msgs if isinstance(m, dict) and m.get("type") == "transcript"]
        store = replay(tx)
        asst = _assistant(store)
        phantom = any(i.get("turn") == 0 and i["text"] == "PRE-CREATED TEXT"
                      for i in asst)
        print("   [D3] gateway transcript msgs: %s" % json.dumps(tx))
        print("   [D3] store assistant bubbles: %s" % json.dumps(asst))
        check("D3.1 pre-created stale final is never presented (no phantom "
              "turn-0 bubble)",
              not phantom, {"bubbles": asst})
    finally:
        await runner.cleanup()


# ===========================================================================
# runner
# ===========================================================================

METRIC_GROUPS = {
    "R-F-1 CLIENT-BOUNDARY LATE_FINAL_MUTATION=0": (
        "C5", "C6", "C6b", "C8", "C10", "D1.1", "D1.2", "D1.3", "D2.2",
        "D3.1"),
    "R-F-1 MITIGATION (already-FINAL rewrite blocked)": ("C1", "C2", "C3",
                                                         "C4", "C12"),
}


def _metric_summary():
    print("\n" + "=" * 72)
    print("METRIC VERDICTS (RED-F round 2)")
    by_name = {}
    for name, ok, detail in RESULTS:
        by_name.setdefault(name, (ok, detail))
    for metric, prefixes in METRIC_GROUPS.items():
        evaluated = [(n, ok, d) for n, (ok, d) in by_name.items()
                     if n.startswith(prefixes)]
        bad = [n for n, ok, _ in evaluated if not ok]
        print("  %-52s %s (%d checks%s)"
              % (metric, "CONFIRMED" if not bad else "FALSIFIED",
                 len(evaluated), "" if not bad else ", failing: %s"
                 % ", ".join(bad)))


def main():
    part_c_store_attacks()
    asyncio.run(asyncio.wait_for(_part_d_integration(), 120))
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 72)
    print("RED_F_ROUND2: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    _metric_summary()
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
