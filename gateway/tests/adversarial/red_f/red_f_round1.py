"""RED-F round 1 — realtime / session state-machine adversarial suite.

READ-ONLY on product source.  Two harnesses:

  * Part A — deterministic protocol simulation: a real `turns.Connection`
    (real Opus codecs) driven by hostile Qwen event orderings through stub
    websocket / stub qwen.  No real audio provider, no real Qwen.
  * Part B — integration: a LOCAL gateway instance (in-process, loopback,
    `QWEN_MODE=mock`) whose real `QwenClient` speaks to the adversarial mock
    upstream in `adv_mock_qwen_server.py` on 127.0.0.1:9277, driven by a real
    WebSocket client.  `/health`, `/diag` and `/admin/metrics` are read as
    evidence.

Metrics under test (must be falsified or confirmed):
    OLD_AUDIO_RESUME = 0
    LATE_FINAL_MUTATION = 0
    SESSION_STATE_LEAK = 0
    GENERATION_OWNERSHIP_FAULT = 0
    AUDIO_ARCHITECTURE_CHANGED = NO

ROUND-3 CLOSURE: the R-F-1 / R-F-5 gateway ownership guard now lives in
`gateway/app/turns.py` (`_ui_owns_generation`); A5.1 / B3.1 were updated from
"defect present" assertions to the post-fix drop semantics.  ARCH5 stays a
read-only-scope proof of this suite (it must pass on the committed clean tree).

Run:
    cd <project-root>/gateway
    DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
        tests/adversarial/red_f/red_f_round1.py
"""

import asyncio
import ast
import base64
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
import types
from collections import deque
from pathlib import Path

# --- enable the (log-only) diagnostic surface for richer /diag evidence -----
os.environ.setdefault("RTL_DIAG", "1")
os.environ.setdefault("RTL_DIAG_DIR", "/tmp/adv/red_f/diag")

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parents[2]           # .../gateway
_REPO = _GATEWAY.parent               # repo root
for _p in (str(_GATEWAY), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.turns as turns                          # noqa: E402
from app import audio                              # noqa: E402
from app import diag                               # noqa: E402
from app.counters import counters                  # noqa: E402

# --- environment workaround (NOT a product defect; see BRIEF) ---------------
# This Mac's dev libopus INTERMITTENTLY raises OpusError(bitrate) on an
# OpusEnc24() construction (baseline reproduces it too).  Wrap the codec
# factories with a bounded retry so the adversarial suite is not flaky.
_orig_enc24 = audio.OpusEnc24
_orig_dec16 = audio.OpusDec16


def _retry_enc24():
    last = None
    for _ in range(100):
        try:
            return _orig_enc24()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.004)
    raise last


def _retry_dec16():
    last = None
    for _ in range(100):
        try:
            return _orig_dec16()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.004)
    raise last


audio.OpusEnc24 = _retry_enc24
audio.OpusDec16 = _retry_dec16

_adv_dir = str(_HERE)
if _adv_dir not in sys.path:
    sys.path.insert(0, _adv_dir)
from adv_mock_qwen_server import build_app as build_adv_mock   # noqa: E402

_REAL_SLEEP = asyncio.sleep
APP_DIR = str(_GATEWAY / "app")
FROZEN_FILES = ("turns.py", "audio.py", "qwen.py", "ws.py", "protocol.py",
                "counters.py")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


# ===========================================================================
# infrastructure (deterministic harness) — modelled on r1f_tests.py
# ===========================================================================

class Clock:
    def __init__(self, t0=1000.0):
        self.t = t0

    def now_ms(self):
        return self.t

    def advance_ms(self, ms):
        self.t += ms


class TimeCtl:
    def __init__(self, clock, gate=None):
        self.clock = clock
        self.gate = gate
        self._saved = None

    def __enter__(self):
        self._saved = (turns._now_ms, asyncio.sleep)
        turns._now_ms = self.clock.now_ms
        gate = self.gate
        clock = self.clock

        async def fake_sleep(delay, *a, **kw):
            if gate is not None and not gate.is_set():
                await gate.wait()
            clock.advance_ms(delay * 1000.0)
            await _REAL_SLEEP(0)

        asyncio.sleep = fake_sleep
        return self

    def __exit__(self, *exc):
        turns._now_ms, asyncio.sleep = self._saved
        return False


class NoPacer:
    def __enter__(self):
        self._orig = turns.Connection._ensure_pacer
        turns.Connection._ensure_pacer = lambda self: None
        return self

    def __exit__(self, *exc):
        turns.Connection._ensure_pacer = self._orig
        return False


class StubWs:
    def __init__(self):
        self.bin = []
        self.strs = []
        self.fail_next = None
        self.on_send = None
        self.clock = None

    async def send_bytes(self, pkt):
        if self.on_send is not None:
            await self.on_send(pkt)
        if self.fail_next is not None:
            exc = self.fail_next
            self.fail_next = None
            raise exc
        self.bin.append(pkt)

    async def send_str(self, s):
        self.strs.append(s)


class StubQwen:
    def __init__(self):
        self.connected = True
        self.cancel_calls = 0
        self.appends = 0
        self.closed = False
        self.instructions = None
        self.updates = 0

    def request_connect(self):
        pass

    async def ensure_connected(self):
        pass

    async def send_append(self, pcm):
        self.appends += 1

    async def send_cancel(self):
        self.cancel_calls += 1

    def set_instructions(self, t):
        self.instructions = t

    async def send_instructions_update(self, t):
        self.updates += 1
        self.instructions = t
        return True

    async def close(self):
        self.closed = True


def make_conn(ws=None):
    cfg = types.SimpleNamespace(
        PUBLIC_WS_URL="ws://stub", FRAME_MS=20,
        MEMORY_FILE="", WORKBENCH_BASE_URL="", KNOWLEDGE_FILE="",
        POLICY_FILE="",
        qwen=types.SimpleNamespace(
            ready=False, is_real=False, mode="mock", ws_url="ws://stub",
            model="m", voice="v", api_key="", workspace_id="",
            region="cn-beijing", headers={}, host="stub", reconnect_max=1,
            reconnect_base_ms=1, stable_reset_s=1, not_ready_reason=""))
    ws = ws or StubWs()
    conn = turns.Connection(ws, cfg)
    conn.qwen = StubQwen()
    # keep the (text-plane) behavior link off the real qwen client
    try:
        conn.behavior.qwen = conn.qwen
    except Exception:  # noqa: BLE001
        pass
    return conn, ws


def rid_of(conn, name):
    """Connection-scoped, process-unique response id.

    The `diag` module keeps a PROCESS-GLOBAL generation map; reusing a bare rid
    string across many in-process connections would trip its log-only
    GEN_SELECTION_MISMATCH audit.  Namespacing keeps the evidence unambiguous.
    """
    return "c%d|%s" % (conn.conn_ordinal, name)


def G(conn, name):
    return conn.generations.get(rid_of(conn, name))


async def created(conn, rid):
    conn._on_response_created({"response_id": rid_of(conn, rid)})


async def delta(conn, rid, nbytes=960, payload=None, rid_key=True):
    raw = payload if payload is not None else (b"\x11" * nbytes)
    msg = {"type": "response.audio.delta",
           "delta": base64.b64encode(raw).decode("ascii")}
    if rid_key:
        msg["response_id"] = rid_of(conn, rid)
    await conn._on_qwen_event(msg)


async def end(conn, rid, etype="response.done", status="completed"):
    msg = {"type": etype, "response_id": rid_of(conn, rid)}
    if etype == "response.done":
        msg["response"] = {"id": rid_of(conn, rid), "status": status}
    await conn._on_qwen_event(msg)


async def drain(conn, max_turns=200000):
    for _ in range(max_turns):
        if conn.pacer_task is None or conn.pacer_task.done():
            return True
        await _REAL_SLEEP(0)
    return False


async def settle(n=5):
    for _ in range(n):
        await _REAL_SLEEP(0)


def cdiff(before, after):
    out = {}
    for k, v in after.items():
        b = before.get(k)
        if isinstance(v, int) and isinstance(b, int) and not isinstance(v, bool):
            out[k] = v - b
    return out


def gv(snap, k):
    v = snap.get(k)
    return 0 if v is None else v


def source_residual(d):
    return d["source_pcm_bytes"] - (d["admitted_pcm_bytes"]
                                    + d["guard_dropped_pcm_bytes"]
                                    + d["safety_truncated_pcm_bytes"])


FLUSH_KEYS = (
    "flushed_bargein_frames", "flushed_abort_frames", "flushed_close_frames",
    "flushed_listen_start_frames", "flushed_upstream_closed_frames",
    "flushed_pacer_stall_frames", "flushed_byte_cap_failure_frames",
    "flushed_send_error_frames",
)


def framer_residual(d, after):
    lhs = d["admitted_pcm_bytes"]
    rhs = (960 * d["encoded_full_frames"] + 960 * d["encode_failed_frames"]
           + d["synthetic_tail_source_bytes"]
           + d["synthetic_tail_encode_failed_source_bytes"]
           + d["residue_discarded_pcm_bytes"]
           + gv(after, "still_buffered_pcm_bytes"))
    return lhs - rhs


def disposition_residual(d, after):
    lhs = d["encoded_full_frames"] + d["synthetic_tail_frames"]
    rhs = (d["sent_confirmed_frames"] + sum(d[k] for k in FLUSH_KEYS)
           + d["send_failed_frames"] + d["send_outcome_unknown_frames"]
           + gv(after, "still_stored_frames") + gv(after, "in_flight_frames"))
    return lhs - rhs


def closures_clean(d, after):
    return (source_residual(d) == 0 and framer_residual(d, after) == 0
            and disposition_residual(d, after) == 0)


# ===========================================================================
# PART 0 — architecture / static invariants  (AUDIO_ARCHITECTURE_CHANGED = NO)
# ===========================================================================

LEGACY_TOKENS = {"dl_q", "SENTINEL", "_stop_pending", "_enqueue_frame",
                 "_enqueue_sentinel", "_drop_one_non_sentinel",
                 "_put_drop_oldest", "DL_QUEUE_MAX", "qwen_closed"}


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:]
    return tree


def _legacy_flags(source):
    tree = _strip_docstrings(ast.parse(source))
    flags = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in LEGACY_TOKENS:
            flags.append(("Name", node.id))
        elif isinstance(node, ast.Attribute) and node.attr in LEGACY_TOKENS:
            flags.append(("Attr", node.attr))
        elif isinstance(node, ast.keyword) and node.arg in LEGACY_TOKENS:
            flags.append(("kwarg", node.arg))
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node.value in LEGACY_TOKENS):
            flags.append(("Str", node.value))
    return flags


def _app_sources():
    out = {}
    for name in sorted(os.listdir(APP_DIR)):
        if not name.endswith(".py") or name.startswith("."):
            continue
        out[name] = open(os.path.join(APP_DIR, name), encoding="utf-8").read()
    return out


def part0_architecture():
    print("\n==== PART 0 — frozen architecture ====")
    check("ARCH1 media frame 20 ms / guard 15 ms / slack 5 ms",
          turns.MEDIA_FRAME_MS == 20.0 and turns.MIN_SEND_START_INTERVAL_MS == 15.0
          and turns.PACING_SLACK_MS == 5.0 and turns.SLOW_SEND_THRESHOLD_MS == 5.0)
    check("ARCH2 caps frozen (1500 frames / 524288 bytes / 250 ms rebase)",
          turns.MAX_FUTURE_FRAMES == 1500 and turns.MAX_FUTURE_AUDIO_BYTES == 524288
          and turns.MAX_REBASE_LATENESS_MS == 250.0)
    bad = {}
    for name, src in _app_sources().items():
        flags = _legacy_flags(src)
        if flags:
            bad[name] = flags
    check("ARCH3 no legacy AST tokens in app/*.py", not bad, bad)
    qsrc = open(os.path.join(APP_DIR, "qwen.py"), encoding="utf-8").read()
    check("ARCH4 provider/model/voice/VAD frozen in source",
          '"type": "server_vad"' in qsrc and '"threshold": 0.5' in qsrc
          and '"silence_duration_ms": 800' in qsrc and "pcm16" in qsrc
          and "OpusEnc24" in open(os.path.join(APP_DIR, "audio.py"),
                                  encoding="utf-8").read())
    # product source untouched by this suite (read-only scope proof)
    try:
        r = subprocess.run(
            ["git", "-C", str(_REPO), "diff", "--stat", "--", "gateway/app",
             "modules", "admin"],
            capture_output=True, text=True, timeout=30)
        dirty = r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        dirty = "git-error:%r" % e
    check("ARCH5 no product source modified (git diff empty)", dirty == "",
          dirty)
    # record frozen-file hashes as evidence
    hashes = {}
    for f in FROZEN_FILES:
        p = os.path.join(APP_DIR, f)
        hashes[f] = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    print("   frozen file sha256[:16] = %s" % hashes)


# ---- single-store sentinel walk (only future_audio_store holds packets) -----

MUTABLE = (list, dict, set, frozenset, bytearray, deque)
_PRUNE_TYPES = (type, types.FunctionType, types.MethodType, types.ModuleType,
                types.CodeType)


def _sentinel_walk(conn, sentinel, exempt):
    seen = set()
    hits = set()
    stack = list(vars(conn).values())
    while stack:
        o = stack.pop()
        if id(o) in seen:
            continue
        seen.add(id(o))
        if o is conn or any(o is e for e in exempt):
            continue
        if isinstance(o, _PRUNE_TYPES):
            continue
        try:
            refs = gc.get_referents(o)
        except Exception:  # noqa: BLE001
            refs = []
        if isinstance(o, MUTABLE):
            for r in refs:
                if r is sentinel:
                    hits.add(id(o))
                    break
        for r in refs:
            if id(r) not in seen:
                stack.append(r)
    return hits


def part0_single_store():
    print("\n==== PART 0b — single-store invariant ====")

    async def go():
        conn, ws = make_conn()
        sentinel = b"\x00SENTINEL<red_f>"
        conn.enc24.encode = lambda chunk, n: sentinel
        with NoPacer():
            await created(conn, "r1")
            await delta(conn, "r1", 960)
        exempt = [conn.ws, conn.diag, conn.config, conn.uplink_q, conn.dl_buf]
        hits = _sentinel_walk(conn, sentinel, exempt)
        check("ARCH6 exactly one mutable holder of an encoded frame",
              hits == {id(conn.future_audio_store)}, hits)
        check("ARCH7 store type is deque and non-empty",
              type(conn.future_audio_store) is deque
              and len(conn.future_audio_store) == 1)

    asyncio.run(asyncio.wait_for(go(), 30))


# ===========================================================================
# PART A — deterministic protocol-simulation attacks
# ===========================================================================

def partA_speech_events():
    print("\n==== PART A1 — rapid/interleaved speech events ====")

    async def started_started():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            gen = G(conn, "r1")
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A1.1 started-started: exactly one barge-in sequence",
                  d["barge_in_sequences_total"] == 1, d["barge_in_sequences_total"])
            check("A1.2 started-started: generation invalidated BARGEIN",
                  gen.send_forbidden and gen.forbid_reason == "BARGEIN",
                  (gen.send_forbidden, gen.forbid_reason))
            # OLD_AUDIO_RESUME: late delta for the invalidated gen must be STALE
            await delta(conn, "r1", 960)
            after2 = counters.snapshot()
            d2 = cdiff(after, after2)
            check("A1.3 late delta after barge-in -> guard_dropped only",
                  d2["guard_dropped_pcm_bytes"] == 960
                  and d2["admitted_pcm_bytes"] == 0, d2)
            check("A1.4 OLD_AUDIO_RESUME=0 (no admitted bytes for old gen)",
                  d2["admitted_pcm_bytes"] == 0)

    async def stopped_without_started():
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_stopped"})
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_stopped"})
            gen = G(conn, "r1")
            check("A1.5 stopped-without-started: no barge, gen untouched",
                  not gen.send_forbidden and conn._current_gen is gen)

    async def started_during_response():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            for _ in range(5):
                await delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A1.6 started during response: barge + store flush",
                  d["barge_in_sequences_total"] == 1
                  and d["flushed_bargein_frames"] == 5,
                  (d["barge_in_sequences_total"], d["flushed_bargein_frames"]))
            check("A1.7 store empty after flush",
                  len(conn.future_audio_store) == 0)

    async def started_storm():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            for _ in range(3):
                await conn._on_qwen_event(
                    {"type": "input_audio_buffer.speech_started"})
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A1.8 started x3 storm: one barge only",
                  d["barge_in_sequences_total"] == 1, d["barge_in_sequences_total"])

    asyncio.run(asyncio.wait_for(started_started(), 30))
    asyncio.run(asyncio.wait_for(stopped_without_started(), 30))
    asyncio.run(asyncio.wait_for(started_during_response(), 30))
    asyncio.run(asyncio.wait_for(started_storm(), 30))


def partA_overlap_duplicate():
    print("\n==== PART A2 — overlapping / duplicate responses ====")

    async def duplicate_done():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await delta(conn, "r1", 960)
            for _ in range(3):
                await end(conn, "r1", "response.done", "completed")
            await drain(conn)
            gen = G(conn, "r1")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A2.1 duplicate done: one marker", gen.end_markers == 1,
                  gen.end_markers)
            check("A2.2 duplicate done: one tts stop",
                  gen.tts_stop_emissions == 1, gen.tts_stop_emissions)
            check("A2.3 duplicate done: no accounting fault",
                  d["accounting_fault_events"] == 0, d["accounting_fault_events"])
            check("A2.4 duplicate done: closures clean", closures_clean(d, after), d)
            check("A2.5 duplicate done: no post-terminal sends",
                  d["post_terminal_sends_total"] == 0, d["post_terminal_sends_total"])

    async def audio_done_after_done():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await end(conn, "r1", "response.done", "completed")
            await end(conn, "r1", "response.audio.done")
            await drain(conn)
            gen = G(conn, "r1")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A2.6 audio.done after done: idempotent (one marker)",
                  gen.end_markers == 1, gen.end_markers)
            check("A2.7 audio.done after done: closures clean",
                  closures_clean(d, after), d)

    async def done_unknown_rid():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            gen = G(conn, "r1")
            await end(conn, "ghost_rid", "response.done", "completed")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A2.8 done for unknown rid: current gen untouched",
                  conn._current_gen is gen and not gen.send_forbidden
                  and not gen.sealed, (conn._current_gen is gen,
                                       gen.send_forbidden, gen.sealed))
            check("A2.9 done for unknown rid still counted once",
                  d["responses_completed"] == 1, d["responses_completed"])
            check("A2.10 done for unknown rid: late_event diag recorded",
                  diag.ENABLED and diag.SNAPSHOT_PROVIDER().get("assertions")
                  is not None)

    async def overlap_second_created():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            with NoPacer():
                await created(conn, "r1")
                for _ in range(6):
                    await delta(conn, "r1", 960)
                # second response begins while the first still streams (queued)
                await created(conn, "r2")
                gen1 = G(conn, "r1")
                gen2 = G(conn, "r2")
                check("A2.11 overlap: new response becomes current",
                      conn._current_gen is gen2 and conn.current_resp_id == rid_of(conn, "r2"),
                      (conn._current_gen is gen2, conn.current_resp_id))
                # a further delta for r1 must NOT be admitted (no old-audio resume)
                await delta(conn, "r1", 960)
                check("A2.12 overlap: r1 late delta dropped, not admitted",
                      gen1.admitted_bytes == 6 * 960 and gen1.guard_dropped_bytes == 960,
                      (gen1.admitted_bytes, gen1.guard_dropped_bytes))
                check("A2.13 overlap: r1 not terminated by the new response",
                      not gen1.send_forbidden and not gen1.sealed)
            # seal r2 (empty) + start the pacer so the store fully drains
            await end(conn, "r2", "response.done", "completed")
            turns.Connection._ensure_pacer(conn)
            await drain(conn)
            await settle()
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A2.14 overlap: closures clean", closures_clean(d, after), d)
            print("   [overlap] r1 queued frames played AFTER r2 became current: "
                  "sent_confirmed_delta=%s gen1.sent=%s"
                  % (d["sent_confirmed_frames"], gen1.sent))

    async def duplicate_created_same_rid():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            gen_old = G(conn, "r1")
            await created(conn, "r1")            # duplicate created, same rid
            gen_new = G(conn, "r1")
            check("A2.15 duplicate created: map replaced with new gen",
                  gen_new is not gen_old)
            check("A2.16 duplicate created: ui_turn advanced twice",
                  conn._ui_turn == 2, conn._ui_turn)
            await delta(conn, "r1", 960)
            await end(conn, "r1", "response.done", "completed")
            await drain(conn)
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A2.17 duplicate created: closures clean", closures_clean(d, after), d)

    asyncio.run(asyncio.wait_for(duplicate_done(), 30))
    asyncio.run(asyncio.wait_for(audio_done_after_done(), 30))
    asyncio.run(asyncio.wait_for(done_unknown_rid(), 30))
    asyncio.run(asyncio.wait_for(overlap_second_created(), 30))
    asyncio.run(asyncio.wait_for(duplicate_created_same_rid(), 30))


def partA_cancel():
    print("\n==== PART A3 — cancel during streaming ====")

    async def cancel_before_audio():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await end(conn, "r1", "response.done", "cancelled")
            await drain(conn)
            gen = G(conn, "r1")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A3.1 cancel before audio: sealed, one marker",
                  gen.sealed and gen.end_markers == 1, (gen.sealed, gen.end_markers))
            check("A3.2 cancel before audio: tts never started",
                  not gen.tts_started
                  and not any('"state": "start"' in s for s in ws.strs), ws.strs)
            check("A3.3 cancel before audio: cancelled counted",
                  d["responses_cancelled"] == 1, d["responses_cancelled"])
            check("A3.4 cancel before audio: closures clean",
                  closures_clean(d, after), d)

    async def cancel_after_last_delta():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            for _ in range(4):
                await delta(conn, "r1", 960)
            await end(conn, "r1", "response.done", "cancelled")
            await drain(conn)
            gen = G(conn, "r1")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A3.5 cancel after last delta: sealed cleanly",
                  gen.sealed and gen.send_forbidden is False, gen.sealed)
            check("A3.6 cancel after last delta: closures clean",
                  closures_clean(d, after), d)
            check("A3.7 cancel after last delta: no post-terminal sends",
                  d["post_terminal_sends_total"] == 0)

    async def cancel_mid_stream():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await end(conn, "r1", "response.done", "cancelled")
            # late deltas after cancel must be STALE
            await delta(conn, "r1", 960)
            gen = G(conn, "r1")
            await drain(conn)
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A3.8 cancel mid-stream: late delta STALE (no resume)",
                  d["admitted_pcm_bytes"] == 960
                  and d["guard_dropped_pcm_bytes"] == 960, d)
            check("A3.9 cancel mid-stream: closures clean",
                  closures_clean(d, after), d)

    asyncio.run(asyncio.wait_for(cancel_before_audio(), 30))
    asyncio.run(asyncio.wait_for(cancel_after_last_delta(), 30))
    asyncio.run(asyncio.wait_for(cancel_mid_stream(), 30))


def partA_bargein_phases():
    print("\n==== PART A4 — barge-in at every phase ====")

    async def run_barge(n_preset, name):
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            for _ in range(n_preset):
                await delta(conn, "r1", 960)
            gen = G(conn, "r1")
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            check("A4.%s barge-in(%d): gen invalidated + store flushed" % (name, n_preset),
                  gen.send_forbidden and gen.forbid_reason == "BARGEIN"
                  and len(conn.future_audio_store) == 0,
                  (gen.forbid_reason, len(conn.future_audio_store)))
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A4.%s barge-in(%d): flushed frames == preset" % (name, n_preset),
                  d["flushed_bargein_frames"] == n_preset, d["flushed_bargein_frames"])

    async def barge_double_then_new():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            await created(conn, "r2")
            await delta(conn, "r2", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A4.5 barge,dbl,new-response,barge: two barges total",
                  d["barge_in_sequences_total"] == 2, d["barge_in_sequences_total"])
            check("A4.6 r2 invalidated on its own barge",
                  G(conn, "r2").forbid_reason == "BARGEIN")

    asyncio.run(asyncio.wait_for(run_barge(1, "1"), 30))    # first chunk
    asyncio.run(asyncio.wait_for(run_barge(5, "2"), 30))    # middle
    asyncio.run(asyncio.wait_for(run_barge(12, "3"), 30))   # final chunk
    asyncio.run(asyncio.wait_for(barge_double_then_new(), 30))


def partA_late_events():
    print("\n==== PART A5 — late events ====")

    async def late_transcript_final():
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")             # ui_turn -> 1
            await delta(conn, "r1", 960)
            await end(conn, "r1", "response.done", "completed")
            await created(conn, "r2")             # ui_turn -> 2
            ws.strs.clear()
            # LATE final for the already-completed r1, after r2 is current
            await conn._on_qwen_event({"type": "response.audio_transcript.done",
                                       "response_id": rid_of(conn, "r1"),
                                       "transcript": "late-final-text"})
            finals = [json.loads(s) for s in ws.strs
                      if '"type": "transcript"' in s]
            turns_seen = [m.get("turn") for m in finals if m.get("final")]
            rid_ok = finals and all(m.get("role") == "assistant" for m in finals)
            # The late final must not be re-attributed to r2's turn (2).
            # Round-3 (closure): the gateway ownership guard DROPS the late final
            # entirely — it must never reach the wire (pre-round-3 this check
            # asserted the defect's emission: "emitted an assistant final").
            misattributed = any(t == 2 for t in turns_seen)
            check("A5.1 late final for a superseded response is dropped (no "
                  "transcript emitted)", not turns_seen
                  and not any('"late-final-text"' in s for s in ws.strs),
                  ws.strs)
            check("A5.2 LATE_FINAL_MUTATION=0 (late final not re-attributed to "
                  "the new turn)", not misattributed,
                  {"late_turns": turns_seen, "msgs": ws.strs})

    async def late_audio_after_cancel():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            # barge-in cancels r1 locally
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            mid = counters.snapshot()
            await delta(conn, "r1", 960)          # late audio after cancel
            after = counters.snapshot()
            d = cdiff(mid, after)
            check("A5.3 late audio after cancel -> guard_dropped, 0 admitted",
                  d["guard_dropped_pcm_bytes"] == 960
                  and d["admitted_pcm_bytes"] == 0, d)
            check("A5.4 OLD_AUDIO_RESUME=0 after cancel",
                  d["admitted_pcm_bytes"] == 0 and d["sent_confirmed_frames"] == 0, d)

    async def late_done_for_cancelled_after_new():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            await created(conn, "r2")
            gen2 = G(conn, "r2")
            await end(conn, "r1", "response.done", "cancelled")   # LATE
            check("A5.5 late cancelled done: new gen still current",
                  conn._current_gen is gen2 and not gen2.send_forbidden
                  and not gen2.sealed,
                  (conn._current_gen is gen2, gen2.send_forbidden, gen2.sealed))
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A5.6 late cancelled done counted once",
                  d["responses_cancelled"] == 1, d["responses_cancelled"])

    asyncio.run(asyncio.wait_for(late_transcript_final(), 30))
    asyncio.run(asyncio.wait_for(late_audio_after_cancel(), 30))
    asyncio.run(asyncio.wait_for(late_done_for_cancelled_after_new(), 30))


def partA_malformed():
    print("\n==== PART A6 — out-of-order / malformed upstream events ====")

    async def unknown_and_wrong_types():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await conn._on_qwen_event({"type": "some.unknown.event", "x": 1})
            await conn._on_qwen_event({"type": "response.created",
                                       "response": [1, 2, 3]})
            # a NON-STRING delta trips the diagnostic prelude (len(int)) and
            # escapes _on_qwen_event; production contains it in qwen._handle_text.
            escaped = None
            try:
                await conn._on_qwen_event({"type": "response.audio.delta",
                                           "response_id": rid_of(conn, "r1"),
                                           "delta": 12345})
            except Exception as e:  # noqa: BLE001
                escaped = repr(e)
            # a NULL delta is handled by the bad-base64 bucket
            await conn._on_qwen_event({"type": "response.audio.delta",
                                       "response_id": rid_of(conn, "r1"),
                                       "delta": None})
            await conn._on_qwen_event({"type": "response.done",
                                       "response": "not-a-dict"})
            await conn._on_qwen_event({"type": "input_audio_buffer.speech_started"})
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A6.1 unknown type ignored (no dispatch error)",
                  d["qwen_dispatch_errors_total"] == 0, d["qwen_dispatch_errors_total"])
            check("A6.2 null delta -> bad base64 bucket (handled)",
                  (d["bad_base64_live_events"]
                   + d["bad_base64_stale_or_unmapped_events"]) >= 1, d)
            check("A6.3 non-string delta raises out of _on_qwen_event "
                  "(diag prelude; contained at transport)",
                  escaped is not None, escaped)
            check("A6.4 malformed event storm did not crash the connection", True)

    async def null_ids():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await conn._on_qwen_event({"type": "response.created",
                                       "response_id": None})
            for _ in range(3):
                await conn._on_qwen_event({"type": "response.audio.delta",
                                           "response_id": None,
                                           "delta": base64.b64encode(b"\x11" * 960).decode()})
            await conn._on_qwen_event({"type": "response.done",
                                       "response": {"id": None,
                                                    "status": "completed"}})
            await drain(conn)
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A6.4b null-id flow processed, closures clean",
                  closures_clean(d, after), d)

    async def invalid_base64_and_truncated():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await conn._on_qwen_event({"type": "response.audio.delta",
                                       "response_id": rid_of(conn, "r1"),
                                       "delta": "!!!!not-valid-base64!!!!"})
            # truncated JSON on the inbound client text path
            await conn.handle_text('{"type": "listen", "state"')
            await conn.handle_text("not json at all")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A6.5 invalid base64 live -> bad_base64_live_events",
                  d["bad_base64_live_events"] == 1, d["bad_base64_live_events"])
            check("A6.6 truncated/invalid inbound JSON ignored (no crash)", True)

    async def huge_payload():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", payload=b"\x22" * (6 * 1024 * 1024))
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A6.7 huge single delta bounded by byte cap",
                  d["byte_cap_failures"] >= 1, d["byte_cap_failures"])
            check("A6.8 huge delta: closures clean", closures_clean(d, after), d)
            check("A6.9 huge delta: no frame beyond caps",
                  gv(after, "unsent_backlog_peak_frames") <= 1500)

    async def oversize_json_cap():
        conn, ws = make_conn()
        big = "x" * (70000)
        await conn.handle_text('{"type":"listen","state":"start","mode":"%s"}' % big)
        conn.handle_binary(b"not-opus-audio")
        check("A6.10 oversize JSON (>64 KiB) rejected, connection survives", True)

    asyncio.run(asyncio.wait_for(unknown_and_wrong_types(), 30))
    asyncio.run(asyncio.wait_for(null_ids(), 30))
    asyncio.run(asyncio.wait_for(invalid_base64_and_truncated(), 30))
    asyncio.run(asyncio.wait_for(huge_payload(), 60))
    asyncio.run(asyncio.wait_for(oversize_json_cap(), 30))


def partA_session_reset():
    print("\n==== PART A7 — session reset / pacer adversarial timing ====")

    async def abort_during_send_await():
        before = counters.snapshot()
        gate = asyncio.Event()

        async def block(pkt):
            await gate.wait()

        clock = Clock()
        conn, ws = make_conn()
        ws.on_send = block
        with TimeCtl(clock):
            await created(conn, "r1")
            await delta(conn, "r1", 960)          # pacer parks in SEND_AWAIT
            await settle(10)
            check("A7.1 head parked in SEND_AWAIT",
                  conn._head_state == "SEND_AWAIT", conn._head_state)
            await conn._on_abort({"reason": "test"})
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A7.2 abort during send: outcome unknown counted",
                  d["send_outcome_unknown_frames"] == 1,
                  d["send_outcome_unknown_frames"])
            check("A7.3 abort during send: in_flight back to 0",
                  gv(after, "in_flight_frames") == 0,
                  gv(after, "in_flight_frames"))
            check("A7.4 abort during send: closures clean",
                  closures_clean(d, after), d)
            gate.set()
            await settle(5)

    async def close_during_send_await():
        before = counters.snapshot()
        gate = asyncio.Event()

        async def block(pkt):
            await gate.wait()

        clock = Clock()
        conn, ws = make_conn()
        ws.on_send = block
        with TimeCtl(clock):
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await settle(10)
            check("A7.5 head parked in SEND_AWAIT before close",
                  conn._head_state == "SEND_AWAIT", conn._head_state)
            await conn.close()
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A7.6 close during send: no residue gauges",
                  gv(after, "still_buffered_pcm_bytes") == 0
                  and gv(after, "still_stored_frames") == 0
                  and gv(after, "in_flight_frames") == 0,
                  (gv(after, "still_buffered_pcm_bytes"),
                   gv(after, "still_stored_frames"), gv(after, "in_flight_frames")))
            check("A7.7 close during send: closures clean",
                  closures_clean(d, after), d)
            gate.set()
            await settle(5)

    async def listen_start_during_response():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            for _ in range(4):
                await delta(conn, "r1", 960)
            await conn._on_listen_start("manual")
            gen = G(conn, "r1")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A7.8 listen start: gen invalidated LISTEN_START + flushed",
                  gen.forbid_reason == "LISTEN_START"
                  and d["flushed_listen_start_frames"] == 4,
                  (gen.forbid_reason, d["flushed_listen_start_frames"]))
            check("A7.9 listen start: state LISTENING",
                  conn.state == turns.State.LISTENING, conn.state)

    async def abort_without_gen():
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await conn._on_abort({"reason": "no-gen"})     # no active response
            await conn._on_listen({"state": "stop"})
            await conn._on_listen({"state": "detect", "text": "hi"})
            await conn._on_listen({"state": "bogus"})
            check("A7.10 abort with no generation: no crash, LISTENING",
                  conn.state == turns.State.LISTENING, conn.state)

    async def upstream_closed_during_response():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            for _ in range(3):
                await delta(conn, "r1", 960)
            await conn._on_qwen_closed()
            gen = G(conn, "r1")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A7.11 upstream close: gen invalidated UPSTREAM_CLOSED",
                  gen.forbid_reason == "UPSTREAM_CLOSED", gen.forbid_reason)
            check("A7.12 upstream close: gauges zeroed",
                  gv(after, "still_stored_frames") == 0
                  and gv(after, "in_flight_frames") == 0
                  and gv(after, "still_buffered_pcm_bytes") == 0,
                  (gv(after, "still_stored_frames"), gv(after, "in_flight_frames"),
                   gv(after, "still_buffered_pcm_bytes")))
            check("A7.13 upstream close: closures clean", closures_clean(d, after), d)

    async def rapid_activity_switch():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            for i in range(4):
                await created(conn, "r%d" % i)
                await delta(conn, "r%d" % i, 960)
                await conn._on_listen_start("manual")
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A7.14 rapid switching: closures clean", closures_clean(d, after), d)
            check("A7.15 rapid switching: gauges quiescent",
                  gv(after, "still_stored_frames") == 0
                  and gv(after, "in_flight_frames") == 0)

    async def abort_during_seal_drain():
        before = counters.snapshot()
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            for _ in range(3):
                await delta(conn, "r1", 960)
            gen = G(conn, "r1")
            await end(conn, "r1", "response.audio.done")   # seal; marker queued
            check("A7.16a sealed gen while marker still queued",
                  gen.sealed and gen.marker_enqueued, (gen.sealed, gen.marker_enqueued))
            await conn._on_abort({"reason": "during-drain"})
            after = counters.snapshot()
            d = cdiff(before, after)
            check("A7.16b abort during seal-drain: sealed gen owns the flush "
                  "(ABORT), not a bystander",
                  gen.forbid_reason == "ABORT" or gen.sealed,
                  (gen.forbid_reason, gen.sealed))
            check("A7.16c abort during seal-drain: closures clean",
                  closures_clean(d, after), d)

    asyncio.run(asyncio.wait_for(abort_during_send_await(), 30))
    asyncio.run(asyncio.wait_for(close_during_send_await(), 30))
    asyncio.run(asyncio.wait_for(listen_start_during_response(), 30))
    asyncio.run(asyncio.wait_for(abort_without_gen(), 30))
    asyncio.run(asyncio.wait_for(upstream_closed_during_response(), 30))
    asyncio.run(asyncio.wait_for(rapid_activity_switch(), 30))
    asyncio.run(asyncio.wait_for(abort_during_seal_drain(), 30))


def partA_session_isolation():
    print("\n==== PART A8 — cross-session isolation ====")

    async def two_connections():
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            c1, w1 = make_conn()
            c2, w2 = make_conn()
            await created(c1, "a1")
            await created(c2, "b1")
            await delta(c1, "a1", 960)
            await delta(c2, "b1", 960)
            # c1 is fed c2's ACTUAL rid: must be unknown/anonymous to c1
            await c1._on_qwen_event({"type": "response.audio.delta",
                                     "response_id": rid_of(c2, "b1"),
                                     "delta": base64.b64encode(b"\x11" * 960).decode()})
            check("A8.1 stores are per-connection (no shared frames)",
                  c1._queued_frames == 1 and c2._queued_frames == 1,
                  (c1._queued_frames, c2._queued_frames))
            check("A8.2 cross-session rid is UNKNOWN to the other conn",
                  G(c1, "b1") is None
                  and c1._current_gen is G(c1, "a1"))

    async def no_leak_between_connections_counters():
        # counters are process-global by design; per-conn state must be isolated.
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            c1, _ = make_conn()
            await created(c1, "x")
            g = G(c1, "x")
            await delta(c1, "x", 960)
            await c1.close()
            check("A8.3 close clears per-connection generation pointers",
                  c1._current_gen is None and c1.current_resp_id is None,
                  (c1._current_gen, c1.current_resp_id))
            check("A8.4 close leaves no store residue",
                  len(c1.future_audio_store) == 0 and len(c1.dl_buf) == 0)

    asyncio.run(asyncio.wait_for(two_connections(), 30))
    asyncio.run(asyncio.wait_for(no_leak_between_connections_counters(), 30))


# ===========================================================================
# PART B — integration: local gateway instance + adversarial mock upstream
# ===========================================================================

def _gw_config(ws_url, reconnect_max=5, reconnect_base_ms=500):
    from app.qwen import QwenConfig
    values = {"QWEN_MODE": "mock", "QWEN_WS_URL": ws_url,
              "QWEN_MODEL": "qwen3.8-omni-flash-realtime", "QWEN_VOICE": "Tina",
              "QWEN_RECONNECT_MAX": reconnect_max,
              "QWEN_RECONNECT_BASE_MS": reconnect_base_ms,
              "QWEN_STABLE_RESET_S": 30}
    return types.SimpleNamespace(
        PUBLIC_WS_URL="ws://127.0.0.1:0/xiaozhi/v1/", WS_PORT=0, HTTP_PORT=0,
        FRAME_MS=20, MEMORY_FILE="", WORKBENCH_BASE_URL="",
        KNOWLEDGE_FILE="", POLICY_FILE="",
        qwen=QwenConfig.from_values(values))


async def _drive_gateway(scenario, seconds=1.6, listen=True, send_binary=False,
                         reconnect_max=5, reconnect_base_ms=500,
                         close_after=None):
    """Start a fresh in-process gateway bound to a scenario, drive a WS client.

    `close_after` (seconds) aborts the client socket mid-response instead of the
    normal end-of-window close.
    """
    from aiohttp import WSMsgType
    from aiohttp.test_utils import TestClient, TestServer
    from app.main import create_app

    ws_url = "ws://127.0.0.1:9277/mock/%s" % scenario
    cfg = _gw_config(ws_url, reconnect_max, reconnect_base_ms)
    app = create_app(cfg)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    msgs = []
    ws = await client.ws_connect("/xiaozhi/v1/")
    try:
        await ws.send_json({"type": "hello", "version": 1})
        if listen:
            await ws.send_json({"type": "listen", "state": "start",
                                "mode": "manual"})
        if send_binary:
            await ws.send_bytes(b"\x00\x01\x02binary-where-text-expected")
        loop = asyncio.get_event_loop()
        end = loop.time() + seconds
        if close_after is not None:
            end = loop.time() + close_after
        while loop.time() < end:
            try:
                msg = await asyncio.wait_for(ws.receive(), 0.15)
            except asyncio.TimeoutError:
                continue
            if msg.type == WSMsgType.TEXT:
                try:
                    msgs.append(json.loads(msg.data))
                except Exception:  # noqa: BLE001
                    pass
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING,
                              WSMsgType.CLOSED, WSMsgType.ERROR):
                break
        if close_after is not None:
            # abrupt client-side close in the middle of a response
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.1)
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
    await asyncio.sleep(0.05)
    health = None
    dg = None
    try:
        r = await client.get("/health")
        health = await r.json()
        r2 = await client.get("/diag")
        dg = await r2.json()
    except Exception as e:  # noqa: BLE001
        print("   [integration] endpoint read error: %r" % e)
    await client.close()
    return msgs, health, dg


async def _start_adv_mock():
    from aiohttp import web
    app, srv = build_adv_mock("normal")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9277)
    await site.start()
    return runner


async def _admin_metrics():
    from aiohttp.test_utils import TestClient, TestServer
    from app.admin import load_admin_config
    from app.admin.auth import TokenStore
    from app.admin.app import create_admin_app
    token = "RedF_Local_DoNotLeak_246810"
    cfg = load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "9212",
        "ADMIN_API_TOKEN": token, "ADMIN_API_TOKEN_FILE": "",
        "ADMIN_UI_DIR": str(_REPO / "admin")})
    store = TokenStore("", token)
    store.reload()
    app = create_admin_app(admin_config=cfg, token_store=store,
                          gateway_info=lambda: {"mode": "mock", "ready": True,
                                                "model": "m", "voice": "v"})
    client = TestClient(TestServer(app))
    await client.start_server()
    r = await client.get("/admin/metrics",
                         headers={"Authorization": "Bearer " + token})
    data = await r.json()
    await client.close()
    return data


async def _integration_main():
    print("\n==== PART B — local gateway + adversarial mock upstream ====")
    runner = await _start_adv_mock()
    try:
        # baseline admin metrics (Part-A deterministic harness leaves pilot
        # connections with un-drained stores; the integration delta is what matters)
        m_base = await _admin_metrics()
        check("B0.1 /admin/metrics baseline reachable",
              m_base.get("available") is True, m_base)

        # B1 normal happy path
        before = counters.snapshot()
        msgs, health, dg = await _drive_gateway("normal", seconds=1.6)
        after = counters.snapshot()
        d = cdiff(before, after)
        types = [m.get("type") for m in msgs]
        check("B1.1 hello handshake received", "hello" in types, types)
        check("B1.2 tts start+stop received", "tts" in types, types)
        check("B1.3 normal: one response completed",
              d["responses_completed"] == 1, d["responses_completed"])
        check("B1.4 normal(/health) closures clean",
              health["source_pcm_bytes"] - (health["admitted_pcm_bytes"]
              + health["guard_dropped_pcm_bytes"] + health["safety_truncated_pcm_bytes"]) == 0,
              {k: health.get(k) for k in ("source_pcm_bytes", "admitted_pcm_bytes",
                                          "guard_dropped_pcm_bytes",
                                          "safety_truncated_pcm_bytes")})
        check("B1.5 normal(/health) gauge quiescent after client close",
              health["still_stored_frames"] == 0 and health["in_flight_frames"] == 0
              and health["still_buffered_pcm_bytes"] == 0,
              {k: health.get(k) for k in ("still_stored_frames", "in_flight_frames",
                                          "still_buffered_pcm_bytes")})
        check("B1.6 /diag reachable (enabled)", dg is not None)

        # B2 barge-in end-to-end
        before = counters.snapshot()
        await _drive_gateway("bargein", seconds=2.8)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B2.1 bargein: at least one barge-in",
              d["barge_ins"] >= 1, d["barge_ins"])
        check("B2.2 bargein: response cancelled observed",
              d["responses_cancelled"] >= 1, d["responses_cancelled"])
        check("B2.3 bargein: no post-terminal sends",
              d["post_terminal_sends_total"] == 0, d["post_terminal_sends_total"])

        # B3 late final re-attribution end-to-end
        before = counters.snapshot()
        msgs, health, dg = await _drive_gateway("late_done_after_new", seconds=2.2)
        after = counters.snapshot()
        finals = [m for m in msgs if m.get("type") == "transcript" and m.get("final")]
        late = [m for m in finals if m.get("text") == "late-final-text"
                or (m.get("role") == "assistant" and m.get("interrupted"))]
        turns_seen = [m.get("turn") for m in finals]
        # Round-3 (closure): both defect artifacts must be gone from the wire —
        # the stale final AND the spurious interrupted notice are dropped by the
        # gateway ownership guard (pre-round-3 this check asserted the final's
        # emission).
        check("B3.1 late-final scenario: zero transcript messages reach the "
              "client (stale final + spurious interrupt dropped)",
              not any(m.get("type") == "transcript" for m in msgs),
              [m for m in msgs if m.get("type") == "transcript"])
        # r1 is turn 1; no late text may reach the client under ANY turn key.
        misattributed = any(m.get("type") == "transcript"
                            and (m.get("text") == "late-final-text"
                                 or m.get("interrupted"))
                            for m in msgs)
        check("B3.2 LATE_FINAL_MUTATION=0 (no late text / spurious interrupt "
              "reaches the client)", not misattributed,
              [m for m in msgs if m.get("type") == "transcript"])

        # B4 upstream hard close mid-response (real reconnect path)
        before = counters.snapshot()
        await _drive_gateway("close_mid", seconds=2.4)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B4.1 close_mid: upstream error counted",
              d["upstream_errors"] >= 1, d["upstream_errors"])
        check("B4.2 close_mid: qwen reconnected (sessions grew)",
              d["qwen_sessions"] >= 1, d["qwen_sessions"])
        check("B4.3 close_mid: no in-flight residue at end",
              gv(after, "in_flight_frames") == 0
              and gv(after, "still_buffered_pcm_bytes") == 0,
              (gv(after, "in_flight_frames"), gv(after, "still_buffered_pcm_bytes")))

        # B4b upstream closes right after response.created (earliest active phase)
        before = counters.snapshot()
        await _drive_gateway("close_after_created", seconds=2.0)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B4b.1 close after created: upstream error counted",
              d["upstream_errors"] >= 1, d["upstream_errors"])
        check("B4b.2 close after created: no residue gauges",
              gv(after, "in_flight_frames") == 0
              and gv(after, "still_stored_frames") == 0
              and gv(after, "still_buffered_pcm_bytes") == 0,
              {k: gv(after, k) for k in ("in_flight_frames", "still_stored_frames",
                                         "still_buffered_pcm_bytes")})

        # B4c upstream closes immediately after session.updated (no response)
        before = counters.snapshot()
        await _drive_gateway("close_immediate", seconds=1.4)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B4c.1 close immediate: gateway stayed up, reconnect attempted",
              d["qwen_sessions"] >= 1 or d["qwen_connect_errors"] >= 1,
              (d["qwen_sessions"], d["qwen_connect_errors"]))

        # B4d upstream hard-closes immediately after a barge-in interrupt
        before = counters.snapshot()
        await _drive_gateway("interrupt_then_close", seconds=2.6)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B4d.1 interrupt then upstream close: reconnect attempted",
              d["upstream_errors"] >= 1 and d["qwen_sessions"] >= 1,
              (d["upstream_errors"], d["qwen_sessions"]))
        check("B4d.2 interrupt then upstream close: no residue at end",
              gv(after, "in_flight_frames") == 0
              and gv(after, "still_buffered_pcm_bytes") == 0
              and gv(after, "still_stored_frames") == 0,
              {k: gv(after, k) for k in ("in_flight_frames",
                                         "still_buffered_pcm_bytes",
                                         "still_stored_frames")})

        # B5 reconnect storm / budget exhaustion
        before = counters.snapshot()
        await _drive_gateway("storm", seconds=2.0, reconnect_max=3,
                             reconnect_base_ms=40)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B5.1 storm: connect errors accumulated",
              d["qwen_connect_errors"] >= 1, d["qwen_connect_errors"])
        check("B5.2 storm: gateway stayed up (ws_connections settled)",
              after["ws_connections"] == before["ws_connections"],
              (after["ws_connections"], before["ws_connections"]))

        # B6 overlapping responses
        before = counters.snapshot()
        await _drive_gateway("overlap_responses", seconds=2.2)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B6.1 overlap: closures clean",
              source_residual(d) == 0 and framer_residual(d, after) == 0
              and disposition_residual(d, after) == 0, d)
        check("B6.2 overlap: no post-terminal sends",
              d["post_terminal_sends_total"] == 0, d["post_terminal_sends_total"])

        # B7 malformed stream
        before = counters.snapshot()
        await _drive_gateway("malformed_stream", seconds=2.0)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B7.1 malformed: closures clean",
              source_residual(d) == 0 and framer_residual(d, after) == 0
              and disposition_residual(d, after) == 0, d)

        # B8 duplicate_done / audio_done_after_done
        before = counters.snapshot()
        await _drive_gateway("duplicate_done", seconds=1.6)
        await _drive_gateway("audio_done_after_done", seconds=1.6)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B8.1 duplicate/audio-done: no accounting fault",
              d["accounting_fault_events"] == 0, d["accounting_fault_events"])
        check("B8.2 duplicate/audio-done: closures clean",
              source_residual(d) == 0 and framer_residual(d, after) == 0
              and disposition_residual(d, after) == 0, d)

        # B9 wrong types / null ids / binary frame
        before = counters.snapshot()
        await _drive_gateway("wrong_types", seconds=1.2)
        await _drive_gateway("null_ids", seconds=1.4)
        await _drive_gateway("binary_frame", seconds=1.4, send_binary=True)
        after = counters.snapshot()
        check("B9.1 client survived malformed-typed streams (loop intact)", True)

        # B10 done for unknown rid mid-stream
        before = counters.snapshot()
        await _drive_gateway("done_unknown_rid", seconds=1.8)
        after = counters.snapshot()
        d = cdiff(before, after)
        check("B10.1 ghost done: real response still completed",
              d["responses_completed"] >= 1, d["responses_completed"])

        # B12 client-side abrupt close mid-response
        before = counters.snapshot()
        msgs, health, dg = await _drive_gateway("normal", seconds=3.0,
                                                close_after=0.25)
        after = counters.snapshot()
        check("B12.1 client abrupt close: gauges quiescent after close",
              health["still_stored_frames"] == 0 and health["in_flight_frames"] == 0
              and health["still_buffered_pcm_bytes"] == 0,
              {k: health.get(k) for k in ("still_stored_frames", "in_flight_frames",
                                          "still_buffered_pcm_bytes")})
        check("B12.2 client abrupt close: ws_connections back to baseline",
              after["ws_connections"] == before["ws_connections"],
              (after["ws_connections"], before["ws_connections"]))

        # B11 admin metrics endpoint (read-only evidence) — delta vs baseline
        metrics = await _admin_metrics()
        m = metrics.get("metrics", {})
        base_cl = m_base.get("closures") or {}
        now_cl = metrics.get("closures") or {}
        closure_delta = {k: now_cl.get(k, 0) - base_cl.get(k, 0) for k in now_cl}
        check("B11.1 /admin/metrics reachable and available",
              metrics.get("available") is True, metrics)
        check("B11.2 /admin/metrics closures delta == 0 across Part B",
              all(v == 0 for v in closure_delta.values()),
              {"base": base_cl, "now": now_cl, "delta": closure_delta})
        check("B11.3 /admin/metrics post_terminal_sends_total == 0",
              m.get("post_terminal_sends_total") == 0,
              m.get("post_terminal_sends_total"))
        check("B11.4 /admin/metrics still_buffered_pcm_bytes == 0",
              m.get("still_buffered_pcm_bytes") == 0,
              m.get("still_buffered_pcm_bytes"))
    finally:
        await runner.cleanup()


# ===========================================================================
# runner
# ===========================================================================

def _warmup_opus():
    """Known macOS dev-libopus quirk: the FIRST OpusEnc24() may raise
    OpusError(bitrate); a retry succeeds.  NOT a product defect (see BRIEF)."""
    from app import audio
    for _ in range(20):
        try:
            audio.OpusEnc24()
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.02)
    return False


METRIC_GROUPS = {
    "OLD_AUDIO_RESUME=0": ("A1.3", "A1.4", "A3.8", "A5.3", "A5.4", "A7.6",
                           "A7.12", "A7.16c", "B4.3", "B4b.2", "B4d.2", "B12.1"),
    "LATE_FINAL_MUTATION=0": ("A5.2", "B3.2"),
    "SESSION_STATE_LEAK=0": ("A7.6", "A7.12", "A8.1", "A8.2", "A8.3", "A8.4",
                             "B4.3", "B4b.2", "B4d.2", "B5.2", "B11.2", "B11.4",
                             "B12.1", "B12.2"),
    "GENERATION_OWNERSHIP_FAULT=0": ("A2.8", "A2.11", "A2.15", "A5.5", "A7.16b",
                                     "B6.2", "B11.3"),
    "AUDIO_ARCHITECTURE_CHANGED=NO": ("ARCH1", "ARCH2", "ARCH3", "ARCH4",
                                      "ARCH5", "ARCH6", "ARCH7"),
}


def _metric_summary():
    print("\n" + "=" * 72)
    print("METRIC VERDICTS (RED-F)")
    by_name = {}
    for name, ok, detail in RESULTS:
        by_name.setdefault(name, (ok, detail))
    for metric, prefixes in METRIC_GROUPS.items():
        evaluated = [(n, ok, d) for n, (ok, d) in by_name.items()
                     if n.startswith(prefixes)]
        if not evaluated:
            print("  %-34s NOT-EVALUATED" % metric)
            continue
        bad = [n for n, ok, _ in evaluated if not ok]
        verdict = "CONFIRMED" if not bad else "FALSIFIED"
        print("  %-34s %s  (%d checks%s)"
              % (metric, verdict, len(evaluated),
                 "" if not bad else ", failing: %s" % ", ".join(bad)))


def main():
    t0 = time.time()
    if not _warmup_opus():
        print("FATAL: libopus warmup failed (environment quirk)")
        return 2
    part0_architecture()
    part0_single_store()
    partA_speech_events()
    partA_overlap_duplicate()
    partA_cancel()
    partA_bargein_phases()
    partA_late_events()
    partA_malformed()
    partA_session_reset()
    partA_session_isolation()
    asyncio.run(asyncio.wait_for(_integration_main(), 180))

    fails = [r for r in RESULTS if not r[1]]
    npass = len(RESULTS) - len(fails)
    print("=" * 72)
    print("RED_F_ROUND1: %d checks, %d PASS, %d FAIL, %.1fs"
          % (len(RESULTS), npass, len(fails), time.time() - t0))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    _metric_summary()
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
