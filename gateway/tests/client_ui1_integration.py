"""CLIENT-UI-1 integration test: gateway → client transcript messages (mock/synthetic).

Runs the existing R-1f mock harness with an upstream that also emits the four real Qwen
transcript events, records the messages the gateway actually sends through the live WS path,
then replays them through the CLIENT's own TranscriptStore to prove the end-to-end contract
(user/assistant text, streaming, final, and the honest interrupted state on barge-in).

Local run:
    DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/client_ui1_integration.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CLIENT = _ROOT.parent / "client"
for p in (str(_ROOT), str(_HERE), str(_CLIENT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ["WS_PORT"] = "18110"
os.environ["HTTP_PORT"] = "18111"

import r1f_runtime as rt                                        # noqa: E402
from app import turns                                           # noqa: E402
from src.ui.shared.transcript import (FINAL, INTERRUPTED,       # noqa: E402
                                      STREAMING, TranscriptStore)

RESULTS = []
RECORDED = []


def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append(ok)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  <- %r" % (detail,)))
    return ok


class TranscriptFakeQwen(rt.FakeQwen):
    """Adds the four real transcript events to the scripted upstream."""

    async def _emit_response(self):
        await self._send({"type": "conversation.item.input_audio_transcription.delta",
                          "item_id": "item-1", "delta": "你好，"})
        await self._send({"type": "conversation.item.input_audio_transcription.delta",
                          "item_id": "item-1", "delta": "我们练一下点餐吧。"})
        await self._send({"type": "conversation.item.input_audio_transcription.completed",
                          "item_id": "item-1", "transcript": "你好，我们练一下点餐吧。"})
        await super()._emit_response()          # assigns self._rid + emits the audio
        rid = self._rid
        await self._send({"type": "response.audio_transcript.delta",
                          "response_id": rid, "delta": "Sure, let's "})
        await self._send({"type": "response.audio_transcript.delta",
                          "response_id": rid, "delta": "practise ordering food."})
        await self._send({"type": "response.audio_transcript.done",
                          "response_id": rid, "transcript": "Sure, let's practise ordering food."})


def patch_sender():
    """Record every transcript message the gateway sends (then call the real sender)."""
    original = turns.Connection._send_transcript

    async def wrapper(self, role, *, delta=None, text=None, final=False,
                      interrupted=False, turn=None):
        # record the EFFECTIVE turn the gateway will put in the message
        effective = turn if turn is not None else self._ui_turn
        RECORDED.append({"role": role, "delta": delta, "text": text,
                         "final": bool(final), "interrupted": bool(interrupted),
                         "turn": effective})
        return await original(self, role, delta=delta, text=text, final=final,
                              interrupted=interrupted, turn=turn)

    turns.Connection._send_transcript = wrapper
    return original


async def run(name, fake_cls):
    scen = {s[0]: s for s in rt.scenarios()}[name]
    _, cfg, fn, expect = scen
    rt.FakeQwen = fake_cls
    RECORDED.clear()
    ok, delta, after = await rt.run_scenario(name, cfg, fn, expect)
    return ok, delta, after


class _StubWS:
    """Minimal ws stub: proves what the gateway would put on the wire."""

    def __init__(self):
        self.sent = []

    async def send_str(self, payload):
        self.sent.append(payload)


async def test_wire_payload_is_json_string():
    """Regression test for the catch-up finding: send_str must receive a JSON string."""
    conn = object.__new__(turns.Connection)      # no __init__ side effects
    conn.ws = _StubWS()
    conn._ui_turn = 7
    await turns.Connection._send_transcript(conn, "user", delta="你", final=False)
    await turns.Connection._send_transcript(conn, "assistant", final=True, interrupted=True)
    payloads = conn.ws.sent
    check("two payloads reached the ws stub", len(payloads) == 2, payloads)
    oks = []
    for payload in payloads:
        try:
            decoded = json.loads(payload)
            oks.append(isinstance(payload, str) and decoded.get("type") == "transcript")
        except Exception:                                       # noqa: BLE001
            oks.append(False)
    check("wire payloads are JSON strings of type=transcript", all(oks), payloads)
    check("interrupted notice carries no fabricated text",
          json.loads(payloads[-1]).get("text") is None
          and json.loads(payloads[-1]).get("interrupted") is True, payloads[-1])


async def amain():
    await test_wire_payload_is_json_string()
    original = patch_sender()
    try:
        # ---- scenario 1: clean turn with transcripts ----
        ok1, d1, a1 = await run("clean_long", TranscriptFakeQwen)
        check("harness gates pass (clean_long with transcripts)", ok1)
        user = [m for m in RECORDED if m["role"] == "user"]
        asst = [m for m in RECORDED if m["role"] == "assistant"]
        # ASR-UI-01: user previews are forwarded with REPLACE semantics
        # (text=…, delta=None) — never append-style delta, because Qwen input
        # transcription is a cumulative, revisable preview.
        check("user transcript previews forwarded (replace semantics)",
              sum(1 for m in user if m["text"] is not None and not m["final"]) >= 2,
              user[:3])
        check("user transcript final forwarded",
              any(m["final"] and m["text"] == "你好，我们练一下点餐吧。" for m in user), user[-2:])
        check("assistant transcript deltas forwarded", sum(1 for m in asst if m["delta"]) >= 2, asst[:3])
        check("assistant transcript final forwarded",
              any(m["final"] and m["text"] == "Sure, let's practise ordering food." for m in asst), asst[-2:])
        check("every forwarded message carries a turn key",
              all(m["turn"] is not None for m in RECORDED), [m["turn"] for m in RECORDED][:5])

        # ---- client-side replay through the REAL store ----
        store = TranscriptStore()
        for m in RECORDED:
            store.apply({"type": "transcript", **m})
        snap = store.snapshot()
        check("replay yields two bubbles (user + assistant)", len(snap) == 2, snap)
        check("user bubble is Chinese final text",
              snap[0]["role"] == "user" and snap[0]["state"] == FINAL
              and snap[0]["text"] == "你好，我们练一下点餐吧。", snap[0])
        check("assistant bubble is final English text",
              snap[1]["role"] == "assistant" and snap[1]["state"] == FINAL
              and snap[1]["text"] == "Sure, let's practise ordering food.", snap[1])

        # ---- scenario 2: barge-in -> honest interrupted assistant bubble ----
        ok2, d2, a2 = await run("rapid_barge", rt.FakeQwen)
        check("harness gates pass (rapid_barge)", ok2)
        interrupted = [m for m in RECORDED if m["interrupted"]]
        check("interrupted notice forwarded on barge-in", len(interrupted) >= 1, RECORDED[-3:])
        check("no fabricated text in the interrupted notice",
              all(not m["text"] for m in interrupted), interrupted[:2])
        check("interrupted notice is final", all(m["final"] for m in interrupted), interrupted[:1])
        check("barge-in actually happened upstream",
              d2.get("barge_in_sequences_total", 0) >= 1, d2.get("barge_in_sequences_total"))
        store2 = TranscriptStore()
        for m in ([{"type": "transcript", "role": "assistant", "delta": "partial answer...",
                    "final": False, "interrupted": False, "turn": 1}] + [
                    {"type": "transcript", **m} for m in RECORDED if m["interrupted"]]):
            store2.apply(m)
        check("client marks the assistant bubble INTERRUPTED and keeps the received text",
              store2.snapshot()[-1]["state"] == INTERRUPTED
              and store2.snapshot()[-1]["text"] == "partial answer...", store2.snapshot()[-1])

        # ---- audio non-regression alongside the new messages ----
        check("R-1f closures stay 0 with transcript forwarding",
              all(v == 0 for v in (
                  d1.get("post_terminal_sends_total", 0), d1.get("send_outcome_unknown_frames", 0),
                  d2.get("post_terminal_sends_total", 0), d2.get("send_outcome_unknown_frames", 0))),
              (d1.get("post_terminal_sends_total"), d2.get("send_outcome_unknown_frames")))
    finally:
        turns.Connection._send_transcript = original

    total, passed = len(RESULTS), sum(RESULTS)
    print("\nCLIENT_UI1_INTEGRATION: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))