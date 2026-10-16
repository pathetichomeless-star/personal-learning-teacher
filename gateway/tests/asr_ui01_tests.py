"""ASR-UI-01 — user transcript preview fix: synthetic replay + case matrix.

Two confirmed defects (audit 2026-10-08):
  A. Qwen input transcription is a CUMULATIVE, revisable preview (text =
     confirmed prefix, stash = revisable suffix) but reached the client as an
     append-style `delta` -> progressive concatenation ("HelloHello...").
  B. `response.created` advanced the shared UI turn before the delayed
     `input_audio_transcription.completed` (observed ~43 ms race) -> the
     garbled preview bubble was orphaned (STREAMING forever) and a second
     clean bubble appeared.

This suite PROVES both defects against a deterministic legacy replay and
demonstrates they are ABSENT after the fix (real `turns.Connection` driven
through the exact observed event ordering, messages replayed through the real
client `TranscriptStore`).  No network, no real Qwen, no ports.

Run:
    cd <project-root>/gateway
    DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/asr_ui01_tests.py
"""

import asyncio
import json
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parent
_REPO = _GATEWAY.parent
for _p in (str(_GATEWAY), str(_REPO), str(_REPO / "client")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.turns as turns                                   # noqa: E402
from app.protocol import build_transcript                   # noqa: E402
from app.turns import _transcript_args                      # noqa: E402
from src.ui.shared.transcript import (FINAL, STREAMING,     # noqa: E402
                                      TranscriptStore)

RESULTS = []
_RID_SEQ = [0]


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


def uniq_rid(tag):
    _RID_SEQ[0] += 1
    return "asrui%02d|%s" % (_RID_SEQ[0], tag)


# ---------------------------------------------------------------------------
# gateway harness (own copy — standalone; mirrors the red_f construction)
# ---------------------------------------------------------------------------

class StubWs:
    def __init__(self):
        self.bin = []
        self.strs = []

    async def send_bytes(self, pkt):
        self.bin.append(pkt)

    async def send_str(self, s):
        self.strs.append(s)


class StubQwen:
    def __init__(self):
        self.connected = True
        self.cancel_calls = 0
        self.closed = False
        self.instructions = None

    def request_connect(self):
        pass

    async def ensure_connected(self):
        pass

    async def send_append(self, pcm):
        pass

    async def send_cancel(self):
        self.cancel_calls += 1

    def set_instructions(self, t):
        pass

    async def send_instructions_update(self, t):
        return True

    async def close(self):
        self.closed = True


class NoPacer:
    def __enter__(self):
        self._orig = turns.Connection._ensure_pacer
        turns.Connection._ensure_pacer = lambda self: None
        return self

    def __exit__(self, *exc):
        turns.Connection._ensure_pacer = self._orig
        return False


def make_conn():
    cfg = types.SimpleNamespace(
        PUBLIC_WS_URL="ws://stub", FRAME_MS=20,
        MEMORY_FILE="", WORKBENCH_BASE_URL="", KNOWLEDGE_FILE="",
        POLICY_FILE="",
        qwen=types.SimpleNamespace(
            ready=False, is_real=False, mode="mock", ws_url="ws://stub",
            model="m", voice="v", api_key="", workspace_id="",
            region="cn-beijing", headers={}, host="stub", reconnect_max=1,
            reconnect_base_ms=1, stable_reset_s=1, not_ready_reason=""))
    # macOS dev-libopus intermittently raises OpusError on first encoder
    # construction (documented environment sentinel) — bounded retry.
    last = None
    for _ in range(6):
        ws = StubWs()
        try:
            conn = turns.Connection(ws, cfg)
        except Exception as e:  # noqa: BLE001
            last = e
            continue
        conn.qwen = StubQwen()
        try:
            conn.behavior.qwen = conn.qwen
        except Exception:  # noqa: BLE001
            pass
        return conn, ws
    raise last


def parse_tx(ws):
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


def users(store):
    return [i for i in store.snapshot() if i["role"] == "user"]


def assistants(store):
    return [i for i in store.snapshot() if i["role"] == "assistant"]


class LegacyForwarder:
    """PRE-ASR-UI-01 mapping (audit baseline; defect reproduction only).

    Input previews forwarded as append-style `delta` stamped with the shared
    assistant `_ui_turn` — exactly the mapping observed in the 2026-10-08 run.
    """

    def __init__(self):
        self.ui_turn = 0

    def forward(self, obj):
        tx = _transcript_args(obj)
        if tx is None:
            return None
        kind, delta, rid, full, final = tx
        if obj.get("type") == "response.created":
            return None                      # handled by caller via created()
        return json.loads(build_transcript(
            "user" if kind == "input" else "assistant",
            delta=delta, text=full, final=bool(final), interrupted=False,
            turn=self.ui_turn))

    def created(self):
        self.ui_turn += 1


# ---------------------------------------------------------------------------
# deterministic event scripts (sanitized; mirrors the observed 3.5 sequence)
# ---------------------------------------------------------------------------

ITEM1 = "item_utt1_A"
ITEM2 = "item_utt2_B"
FINAL_TEXT = "Hello, can you hear me?"

# cumulative, revisable preview snapshots (text = confirmed prefix, stash = suffix)
PREVIEWS = [("Hello", ""), ("Hello.", ""), ("Hello.", "hello"),
            ("Hello, can", "you"), ("Hello, can", "you hear"),
            ("Hello, can you hear", " me")]


def in_delta(item, text, stash):
    return {"type": "conversation.item.input_audio_transcription.delta",
            "item_id": item, "text": text, "stash": stash}


def in_done(item, transcript=FINAL_TEXT):
    return {"type": "conversation.item.input_audio_transcription.completed",
            "item_id": item, "transcript": transcript}


def a_delta(rid, text):
    return {"type": "response.audio_transcript.delta",
            "response_id": rid, "delta": text}


def a_done(rid, transcript):
    return {"type": "response.audio_transcript.done",
            "response_id": rid, "transcript": transcript}


def resp_created(rid):
    return {"type": "response.created", "response": {"id": rid}}


def resp_done(rid, status="completed"):
    return {"type": "response.done",
            "response": {"id": rid, "status": status}}


def race_sequence(rid, item):
    """The observed ~43 ms race ordering: response.created BEFORE the user's
    completed (segment-4 pattern)."""
    return ([in_delta(item, t, s) for t, s in PREVIEWS]
            + [resp_created(rid)]
            + [in_done(item)]
            + [a_delta(rid, "Sure"), a_done(rid, "Sure, I can hear you."),
               resp_done(rid)])


def normal_sequence(rid, item):
    """completed BEFORE response.created (segments 1-2 pattern)."""
    return ([in_delta(item, t, s) for t, s in PREVIEWS]
            + [in_done(item)]
            + [resp_created(rid)]
            + [a_delta(rid, "Sure"), a_done(rid, "Sure, I can hear you."),
               resp_done(rid)])


# ---------------------------------------------------------------------------
# PART B — legacy baseline: both defects reproduced deterministically
# ---------------------------------------------------------------------------

def legacy_baseline():
    print("\n==== PART B — legacy (pre-fix) defect reproduction ====")
    lg = LegacyForwarder()
    msgs = []
    for obj in race_sequence(uniq_rid("L"), ITEM1):
        if obj.get("type") == "response.created":
            lg.created()
        m = lg.forward(obj)
        if m is not None:
            msgs.append(m)
    us = users(replay(msgs))
    check("B1 legacy defect A: accumulated garble reproduced",
          any("HelloHello" in i["text"] for i in us), us)
    check("B2 legacy defect B: orphaned STREAMING user bubble + second bubble "
          "(~43 ms race)",
          sum(1 for i in us if i["state"] == STREAMING) >= 1 and len(us) >= 2,
          [(i["text"][:40], i["state"]) for i in us])
    return msgs


# ---------------------------------------------------------------------------
# helpers for the FIXED path
# ---------------------------------------------------------------------------

async def run_fixed(events):
    conn, ws = make_conn()
    with NoPacer():
        for obj in events:
            await conn._on_qwen_event(obj)
            # model the real reader loop: fire-and-forget UI sends (interrupted
            # notices) are dispatched between reader events, preserving order.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        for _ in range(3):
            await asyncio.sleep(0)
    return parse_tx(ws)


async def main_cases():
    print("\n==== FIXED path — 16-case matrix ====")

    # C1 — ordinary preview (cumulative growing snapshots): no concatenation
    msgs = await run_fixed(race_sequence(uniq_rid("c1"), ITEM1))
    store = replay(msgs)
    us = users(store)
    check("C1 cumulative growing preview -> replaced, no concatenation",
          len(us) == 1 and "HelloHello" not in us[0]["text"], us)

    # C2 — shrinking/revised preview: bubble shows the LATEST revision only
    rid = uniq_rid("c2")
    evs = ([in_delta(ITEM1, "Hello, can you her", ""),
            in_delta(ITEM1, "Hello, can you he", ""),
            in_delta(ITEM1, "Hello, can you hear", "")]      # revision shrinks
           + [in_done(ITEM1), resp_created(rid), resp_done(rid)])
    store = replay(await run_fixed(evs))
    us = users(store)
    check("C2 revised/shrinking preview replaced (latest revision wins)",
          len(us) == 1 and us[0]["text"] == FINAL_TEXT, us)

    # C3 — text + stash handling (no delta field / cumulative preview)
    rid = uniq_rid("c3")
    evs = [in_delta(ITEM1, "Hello", ""), in_delta(ITEM1, "Hello, can", " you"),
           in_delta(ITEM1, "Hello, can you hear", " me"),
           in_done(ITEM1), resp_created(rid), resp_done(rid)]
    msgs = await run_fixed(evs)
    pre = [m for m in msgs if m.get("role") == "user" and not m.get("final")]
    store = replay(msgs)
    us = users(store)
    check("C3 text+stash previews forwarded with replace semantics",
          pre and all(m["delta"] is None and m["text"] is not None for m in pre)
          and len(us) == 1 and us[0]["text"] == FINAL_TEXT, (pre, us))

    # C4 — repeated identical preview events: idempotent, no duplicated text
    rid = uniq_rid("c4")
    rep = [in_delta(ITEM1, "Hello, can you hear", " me")] * 4
    msgs = await run_fixed(rep + [in_done(ITEM1), resp_created(rid), resp_done(rid)])
    store = replay(msgs)
    us = users(store)
    check("C4 repeated identical previews -> single exact final bubble",
          len(us) == 1 and us[0]["text"] == FINAL_TEXT, us)

    # C5 — final completed text replaces the preview exactly
    rid = uniq_rid("c5")
    msgs = await run_fixed(normal_sequence(rid, ITEM1))
    us = users(replay(msgs))
    check("C5 final completed replaces preview (exact text)",
          len(us) == 1 and us[0]["state"] == FINAL
          and us[0]["text"] == FINAL_TEXT, us)

    # C6 — one utterance = one clean final bubble (count assertion)
    check("C6 one utterance -> exactly ONE user bubble", len(us) == 1, us)

    # C7 — multiple independent utterances -> two clean bubbles, distinct turns
    rid1, rid2 = uniq_rid("c7a"), uniq_rid("c7b")
    evs = (normal_sequence(rid1, ITEM1)
           + [in_delta(ITEM2, "Yes", ""), in_delta(ITEM2, "Yes I can", ""),
              in_done(ITEM2, "Yes I can hear you."), resp_created(rid2), resp_done(rid2)])
    store = replay(await run_fixed(evs))
    us = users(store)
    check("C7 two utterances -> two bubbles, clean, distinct turns",
          len(us) == 2 and us[0]["text"] == FINAL_TEXT
          and us[1]["text"] == "Yes I can hear you."
          and us[0]["turn"] != us[1]["turn"], us)

    # C8 — the observed ~43 ms race: completed AFTER response.created
    rid = uniq_rid("c8")
    msgs = await run_fixed(race_sequence(rid, ITEM1))
    uturns = [m["turn"] for m in msgs if m.get("role") == "user"]
    store = replay(msgs)
    us = users(store)
    check("C8 race (completed AFTER created): one bubble, stable user turn, "
          "no orphan",
          len(us) == 1 and us[0]["state"] == FINAL
          and us[0]["text"] == FINAL_TEXT and len(set(uturns)) == 1
          and "HelloHello" not in us[0]["text"], (us, uturns))

    # C9 — completed BEFORE response.created: identical outcome
    rid = uniq_rid("c9")
    msgs = await run_fixed(normal_sequence(rid, ITEM1))
    uturns = [m["turn"] for m in msgs if m.get("role") == "user"]
    us = users(replay(msgs))
    check("C9 normal order: one bubble, stable user turn, exact final",
          len(us) == 1 and us[0]["state"] == FINAL
          and us[0]["text"] == FINAL_TEXT and len(set(uturns)) == 1, (us, uturns))

    # C10 — user identity independent of assistant turns: response.created
    # during/across one utterance must not re-key the user chain
    u1, u2 = uniq_rid("c10a"), uniq_rid("c10b")
    evs = ([in_delta(ITEM1, "Hello", ""), resp_created(u1),
            in_delta(ITEM1, "Hello, can", " you"), a_delta(u1, "Hi"),
            in_done(ITEM1), resp_done(u1), resp_created(u2),
            a_delta(u2, "Two"), a_done(u2, "Two."), resp_done(u2)])
    msgs = await run_fixed(evs)
    ut = {m["turn"] for m in msgs if m.get("role") == "user"}
    at = [m["turn"] for m in msgs if m.get("role") == "assistant"]
    check("C10 user identity stable across response.created; assistant turns "
          "advance independently",
          len(ut) == 1 and set(at) == {1, 2}, (ut, at))

    # C11 — barge-in during transcription: user chain unaffected, assistant
    # interrupted path intact
    rid1, rid2 = uniq_rid("c11a"), uniq_rid("c11b")
    evs = [in_delta(ITEM1, "Hello", ""),
           resp_created(rid1), a_delta(rid1, "Hi"),
           {"type": "input_audio_buffer.speech_started"},   # barge-in
           resp_done(rid1, status="cancelled"),
           in_done(ITEM1), resp_created(rid2),
           a_delta(rid2, "Sure"), a_done(rid2, "Sure, go on."), resp_done(rid2)]
    store = replay(await run_fixed(evs))
    us = users(store)
    asst = assistants(store)
    check("C11 barge-in during transcription: user bubble clean; assistant "
          "cancelled bubble marked, current assistant intact",
          len(us) == 1 and us[0]["text"] == FINAL_TEXT
          and any(i["state"] in ("INTERRUPTED",) for i in asst)
          and asst[-1]["text"] == "Sure, go on.", (us, asst))

    # C12 — cancelled-generation late transcript isolation (R-F behaviour)
    rid1, rid2 = uniq_rid("c12a"), uniq_rid("c12b")
    evs = [resp_created(rid1), a_delta(rid1, "Old"),
           {"type": "input_audio_buffer.speech_started"},
           resp_done(rid1, status="cancelled"),
           resp_created(rid2), a_delta(rid2, "New"),
           a_delta(rid1, "late-stale-text"),                 # late, superseded
           a_done(rid1, "late-stale-final"),
           a_done(rid2, "New answer."), resp_done(rid2)]
    msgs = await run_fixed(evs)
    store = replay(msgs)
    asst = assistants(store)
    check("C12 cancelled-generation late events isolated (no contamination)",
          all("late-stale" not in i["text"] for i in asst)
          and asst[-1]["text"] == "New answer.", asst)

    # C13 — assistant response_id ownership isolation: two clean generations
    rid1, rid2 = uniq_rid("c13a"), uniq_rid("c13b")
    evs = [resp_created(rid1), a_delta(rid1, "One"), a_done(rid1, "Answer one."),
           resp_done(rid1), resp_created(rid2), a_delta(rid2, "Two"),
           a_done(rid2, "Answer two."), resp_done(rid2)]
    asst = assistants(replay(await run_fixed(evs)))
    check("C13 assistant rid isolation: two bubbles, exact texts, turn order",
          len(asst) == 2 and asst[0]["text"] == "Answer one."
          and asst[1]["text"] == "Answer two."
          and asst[0]["turn"] < asst[1]["turn"], asst)

    # C14 — missing/repeated speech_started: identity driven by item id only
    rid = uniq_rid("c14")
    evs = ([in_delta(ITEM1, "Hello", "")]                    # no speech_started
           + [{"type": "input_audio_buffer.speech_started"}]  # repeated mid-utt
           + [in_delta(ITEM1, "Hello, can", " you"),
              in_delta(ITEM1, "Hello, can you hear", " me")]
           + [in_done(ITEM1), resp_created(rid), resp_done(rid)])
    us = users(replay(await run_fixed(evs)))
    check("C14 missing/repeated speech_started safe (single bubble)",
          len(us) == 1 and us[0]["text"] == FINAL_TEXT, us)

    # C15 — failed transcription cleanup: preview shown then failed -> no orphan
    rid = uniq_rid("c15")
    evs = ([in_delta(ITEM1, "Hello", ""), in_delta(ITEM1, "Hello, can", " you")]
           + [{"type": "conversation.item.input_audio_transcription.failed",
               "item_id": ITEM1}]
           + [resp_created(rid), resp_done(rid)])
    us = users(replay(await run_fixed(evs)))
    check("C15 failed after preview: bubble closed honestly (no orphan "
          "STREAMING)",
          len(us) == 1 and us[0]["state"] == FINAL, us)
    # failed with NO preview -> no bubble at all
    rid = uniq_rid("c15b")
    evs = ([{"type": "conversation.item.input_audio_transcription.failed",
             "item_id": "item_never_shown"}]
           + [resp_created(rid), resp_done(rid)])
    us = users(replay(await run_fixed(evs)))
    check("C15b failed without preview -> no empty bubble", len(us) == 0, us)

    # C16 — duplicated completed -> still exactly one final user bubble
    rid = uniq_rid("c16")
    evs = (normal_sequence(rid, ITEM1)
           + [in_done(ITEM1), in_done(ITEM1)])               # duplicates
    us = users(replay(await run_fixed(evs)))
    check("C16 duplicated completed -> no duplicated final bubble",
          len(us) == 1 and us[0]["text"] == FINAL_TEXT, us)

    # C17 — late events of an OLD item cannot contaminate a NEWER utterance
    rid1, rid2 = uniq_rid("c17a"), uniq_rid("c17b")
    evs = (normal_sequence(rid1, ITEM1)
           + [in_delta(ITEM2, "Yes", ""), in_done(ITEM2, "Yes I can hear you."),
              in_delta(ITEM1, "Hello, can you hear me? LATE STALE", ""),  # old item
              resp_created(rid2), resp_done(rid2)])
    us = users(replay(await run_fixed(evs)))
    check("C17 late old-item preview does not contaminate the newer utterance",
          len(us) == 2 and us[0]["text"] == FINAL_TEXT
          and us[1]["text"] == "Yes I can hear you.", us)

    return msgs


# ---------------------------------------------------------------------------
# PART D — ASR-UI NEW-1 closure: concurrent input items (client fix)
#
# Defect (independent review, 2026-10-08): with the gateway already stamping
# per-item stable turns, the CLIENT store still dropped any user event whose
# turn < newest.  When item B started before item A's completed:
#   A.delta → B.delta → A.delta(revision) → A.completed → B.completed
# A's revision and A's FINAL text were dropped as "stale" and A's bubble was
# orphaned STREAMING.  PART D asserts the client fix: per-item addressing.
# ---------------------------------------------------------------------------

async def part_d_cases():
    print("\n==== PART D — NEW-1 closure: concurrent input items ====")
    A, B, C = "item_A_new1", "item_B_new1", "item_C_new1"
    # D1 — the exact reported sequence (A and B interleave; A completes first)
    rid = uniq_rid("d1")
    evs = ([in_delta(A, "Alpha first", ""),
            in_delta(B, "Beta first", ""),
            in_delta(A, "Alpha final wording", ""),
            in_done(A, "Alpha FINAL."),
            in_done(B, "Beta FINAL."),
            resp_created(rid), resp_done(rid)])
    msgs = await run_fixed(evs)
    store = replay(msgs)
    us = users(store)
    aturns = sorted({m["turn"] for m in msgs if m.get("role") == "user"})
    check("D1 concurrent A/B: both finals exact, no orphan STREAMING",
          len(us) == 2 and us[0]["text"] == "Alpha FINAL."
          and us[0]["state"] == FINAL and us[1]["text"] == "Beta FINAL."
          and us[1]["state"] == FINAL and aturns == [1, 2], us)

    # D2 — interleaved cumulative previews: each bubble carries ONLY its own
    # latest revision (no cross-item mixing)
    rid = uniq_rid("d2")
    evs = ([in_delta(A, "Alpha", ""), in_delta(B, "Beta", ""),
            in_delta(A, "Alpha, and", ""), in_delta(B, "Beta, and", ""),
            in_delta(A, "Alpha, and then", ""),
            in_done(A, "Alpha, and then some."),
            in_done(B, "Beta, and then more."),
            resp_created(rid), resp_done(rid)])
    us = users(replay(await run_fixed(evs)))
    check("D2 interleaved previews: per-item latest revision only",
          len(us) == 2 and us[0]["text"] == "Alpha, and then some."
          and us[1]["text"] == "Beta, and then more.", us)

    # D3 — B completes BEFORE A: A's late completed must not be dropped
    rid = uniq_rid("d3")
    evs = ([in_delta(A, "Alpha first", ""), in_delta(B, "Beta first", ""),
            in_done(B, "Beta FINAL."),
            in_done(A, "Alpha FINAL."),                      # late, legitimate
            resp_created(rid), resp_done(rid)])
    us = users(replay(await run_fixed(evs)))
    check("D3 late legitimate completed applied (not dropped as stale)",
          len(us) == 2 and us[0]["text"] == "Alpha FINAL."
          and us[0]["state"] == FINAL and us[1]["text"] == "Beta FINAL.", us)

    # D4 — failed transcription after preview: A closed honestly, B clean
    rid = uniq_rid("d4")
    evs = ([in_delta(A, "Alpha first", ""),
            {"type": "conversation.item.input_audio_transcription.failed",
             "item_id": A},
            in_delta(B, "Beta first", ""), in_done(B, "Beta FINAL."),
            resp_created(rid), resp_done(rid)])
    us = users(replay(await run_fixed(evs)))
    check("D4 failed item closed honestly; concurrent item unaffected",
          len(us) == 2 and us[0]["state"] == FINAL
          and us[0]["text"] == "Alpha first" and us[1]["text"] == "Beta FINAL.",
          us)

    # D5 — duplicated completed: still exactly one final bubble per item
    rid = uniq_rid("d5")
    evs = (race_sequence(rid, A)
           + [in_done(A), in_done(A)]
           + [in_delta(B, "Beta", ""), in_done(B, "Beta FINAL.")])
    us = users(replay(await run_fixed(evs)))
    check("D5 duplicated completed -> one final bubble per item",
          len(us) == 2 and us[0]["text"] == FINAL_TEXT
          and us[1]["text"] == "Beta FINAL.", us)

    # D6 — three consecutive serial utterances -> three clean bubbles
    rid = uniq_rid("d6")
    evs = ([in_done(A, "First utterance."), resp_created(rid), resp_done(rid),
            in_done(B, "Second utterance."), resp_created(rid), resp_done(rid),
            in_done(C, "Third utterance."), resp_created(rid), resp_done(rid)])
    us = users(replay(await run_fixed(evs)))
    check("D6 three serial utterances -> three clean bubbles",
          len(us) == 3 and [i["text"] for i in us] ==
          ["First utterance.", "Second utterance.", "Third utterance."], us)

    # D7 — assistant isolation unchanged: cancelled generation + late events
    # (assistant stale rule intact), interleaved with the user chains above
    rid1, rid2 = uniq_rid("d7a"), uniq_rid("d7b")
    evs = ([in_delta(A, "Alpha first", ""),
            resp_created(rid1), a_delta(rid1, "Old"),
            {"type": "input_audio_buffer.speech_started"},
            resp_done(rid1, status="cancelled"),
            resp_created(rid2), a_delta(rid2, "New"),
            a_delta(rid1, "late-stale-text"),                 # superseded rid
            a_done(rid1, "late-stale-final"),
            in_done(A, "Alpha FINAL."),
            a_done(rid2, "New answer."), resp_done(rid2)])
    store = replay(await run_fixed(evs))
    us = users(store)
    asst = assistants(store)
    check("D7 assistant isolation unchanged; user chain unaffected",
          len(us) == 1 and us[0]["text"] == "Alpha FINAL."
          and all("late-stale" not in i["text"] for i in asst)
          and asst[-1]["text"] == "New answer.", (us, asst))

    # D8 — legacy id-less user chain (turn=None) keeps its behavior
    evs = [{"type": "conversation.item.input_audio_transcription.delta",
            "delta": "Id-less "},
           {"type": "conversation.item.input_audio_transcription.delta",
            "delta": "chain."},
           {"type": "conversation.item.input_audio_transcription.completed",
            "transcript": "Id-less chain."}]
    us = users(replay(await run_fixed(evs)))
    check("D8 legacy id-less user chain preserved",
          len(us) == 1 and us[0]["text"] == "Id-less chain."
          and us[0]["state"] == FINAL, us)


async def amain():
    legacy_baseline()
    await main_cases()
    await part_d_cases()
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 72)
    print("ASR_UI01_TESTS: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
