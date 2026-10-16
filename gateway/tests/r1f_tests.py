"""R-1f rev-9 deterministic static + unit test suite (bridge half).

Groups A-S of the R-1f implementation authorization Phase 2.  Runs with
RTL_DIAG UNSET (mandated by the m10 sentinel-harness declaration).  Deployed
inside the lab image (`/app/tests/r1f_tests.py`).

Client-half tests (groups T-Z) live in `r1f_client_tests.py` and run on the
macOS client interpreter (numpy required).

Usage:  python /app/tests/r1f_tests.py [group ...]
"""

import ast
import asyncio
import base64
import gc
import os
import sys
import time
import types
from collections import deque

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import turns                                  # noqa: E402
from app.counters import counters                      # noqa: E402

_REAL_SLEEP = asyncio.sleep
APP_DIR = os.path.join(_ROOT, "app")

FLUSH_KEYS = (
    "flushed_bargein_frames", "flushed_abort_frames", "flushed_close_frames",
    "flushed_listen_start_frames", "flushed_upstream_closed_frames",
    "flushed_pacer_stall_frames", "flushed_byte_cap_failure_frames",
    "flushed_send_error_frames",
)
REASON_KEYS = {
    "BARGEIN": "flushed_bargein_frames", "ABORT": "flushed_abort_frames",
    "CLOSE": "flushed_close_frames", "LISTEN_START": "flushed_listen_start_frames",
    "UPSTREAM_CLOSED": "flushed_upstream_closed_frames",
    "PACER_STALL": "flushed_pacer_stall_frames",
    "BYTE_CAP_FAILURE": "flushed_byte_cap_failure_frames",
    "SEND_ERROR": "flushed_send_error_frames",
}
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if detail else ""))
    return bool(cond)


# ---- infrastructure --------------------------------------------------------

class Clock:
    def __init__(self, t0=1000.0):
        self.t = t0

    def now_ms(self):
        return self.t

    def advance_ms(self, ms):
        self.t += ms


class TimeCtl:
    """Deterministic virtual time for the pacer (patches turns._now_ms and
    asyncio.sleep).  `gate` (asyncio.Event) optionally blocks the pacer's
    pre-send waits so tests can force RESERVED_WAIT / lateness conditions."""

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
        self.timestamps = []

    async def send_bytes(self, pkt):
        if self.on_send is not None:
            await self.on_send(pkt)
        self.timestamps.append(self.clock.now_ms() if self.clock is not None
                               else None)
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

    def request_connect(self):
        pass

    async def ensure_connected(self):
        pass

    async def send_append(self, pcm):
        self.appends += 1

    async def send_cancel(self):
        self.cancel_calls += 1

    async def close(self):
        self.closed = True


def make_conn(ws=None):
    cfg = types.SimpleNamespace(
        PUBLIC_WS_URL="ws://stub", FRAME_MS=20,
        qwen=types.SimpleNamespace(
            ready=False, is_real=False, mode="mock", ws_url="ws://stub",
            model="m", voice="v", api_key="", workspace_id="",
            region="cn-beijing", headers={}, host="stub", reconnect_max=1,
            reconnect_base_ms=1, stable_reset_s=1, not_ready_reason=""))
    ws = ws or StubWs()
    conn = turns.Connection(ws, cfg)
    conn.qwen = StubQwen()
    return conn, ws


async def created(conn, rid):
    conn._on_response_created({"response_id": rid})


async def delta(conn, rid, nbytes=960, payload=None, rid_key=True):
    raw = payload if payload is not None else (b"\x11" * nbytes)
    msg = {"type": "response.audio.delta",
           "delta": base64.b64encode(raw).decode("ascii")}
    if rid_key:
        msg["response_id"] = rid
    await conn._on_qwen_event(msg)


async def end(conn, rid, etype="response.done", status="completed"):
    msg = {"type": etype, "response_id": rid}
    if etype == "response.done":
        msg["response"] = {"id": rid, "status": status}
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


def g(after, k):
    v = after.get(k)
    return 0 if v is None else v


def source_residual(d):
    return d["source_pcm_bytes"] - (d["admitted_pcm_bytes"]
                                    + d["guard_dropped_pcm_bytes"]
                                    + d["safety_truncated_pcm_bytes"])


def framer_residual(d, after):
    lhs = d["admitted_pcm_bytes"]
    rhs = (960 * d["encoded_full_frames"] + 960 * d["encode_failed_frames"]
           + d["synthetic_tail_source_bytes"]
           + d["synthetic_tail_encode_failed_source_bytes"]
           + d["residue_discarded_pcm_bytes"]
           + g(after, "still_buffered_pcm_bytes"))
    return lhs - rhs


def disposition_residual(d, after):
    lhs = d["encoded_full_frames"] + d["synthetic_tail_frames"]
    rhs = (d["sent_confirmed_frames"] + sum(d[k] for k in FLUSH_KEYS)
           + d["send_failed_frames"] + d["send_outcome_unknown_frames"]
           + g(after, "still_stored_frames") + g(after, "in_flight_frames"))
    return lhs - rhs


# ---- A. legacy AST scan ----------------------------------------------------

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
    """Every Python source file under app/ (dot/AppleDouble files excluded and
    asserted absent separately)."""
    out = {}
    for name in sorted(os.listdir(APP_DIR)):
        if not name.endswith(".py") or name.startswith("."):
            continue
        out[name] = open(os.path.join(APP_DIR, name), encoding="utf-8").read()
    return out


def test_ast_scan_legacy():
    bad = {}
    for name, src in _app_sources().items():
        flags = _legacy_flags(src)
        if flags:
            bad[name] = flags
    check("A1 exact legacy AST scan over app/**/*.py", not bad, bad)
    stray = [n for n in sorted(os.listdir(APP_DIR)) if n.startswith(".")]
    check("A1b no dot/AppleDouble files under app/", not stray, stray)
    # negative/positive fixtures (design A.3 verification status)
    doc_only = '"""dl_q SENTINEL DL_QUEUE_MAX"""\n# dl_q in comment\nx = 1\n'
    check("A2 docstring/comment-only fixture PASS", not _legacy_flags(doc_only))
    getattr_fix = 'y = getattr(c, "DL_QUEUE_MAX", 256)\n'
    check("A3 getattr fixture FAIL (executable string Constant)",
          bool(_legacy_flags(getattr_fix)))
    planned = ("SENTINEL_ENCODED_PACKET = 1\n"
               "future_audio_store = []\n"
               "def on_sentinel(): pass\n"
               "def _on_qwen_closed(): pass\n"
               "UPSTREAM_CLOSED = 'UPSTREAM_CLOSED'\n")
    check("A4 planned-R-1f-names fixture PASS (no false positives)",
          not _legacy_flags(planned))
    cfg = os.path.join(_ROOT, "config", "config.json")
    check("A5 config.json has no DL_QUEUE_MAX",
          "DL_QUEUE_MAX" not in open(cfg, encoding="utf-8").read())
    # A6: every Diag hook call must go through self.diag (a module-level call
    # would raise AttributeError at runtime and abort a core path).
    import app.diag as _diag_mod
    hook_names = {n for n in vars(_diag_mod.Diag) if n[0].isalpha()}
    module_funcs = {"now", "cap_qwen_pcm", "cap_sent_opus", "gen_stats",
                    "b64decode_delta", "capture_info", "violation", "unwrap",
                    "entry", "safe"}
    bad_calls = []
    tree = ast.parse(_app_sources()["turns.py"])
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "diag"
                and node.func.attr in hook_names
                and node.func.attr not in module_funcs):
            bad_calls.append((node.lineno, node.func.attr))
    check("A6 no module-level diag.<hook> calls in turns.py",
          not bad_calls, bad_calls)


# ---- D. audio_out_dropped mutation -----------------------------------------

def test_audio_out_dropped_mutation():
    violations = []
    for name, src in _app_sources().items():
        tree = _strip_docstrings(ast.parse(src))
        for node in ast.walk(tree):
            if isinstance(node, ast.AugAssign):
                t = node.target
                if ((isinstance(t, ast.Attribute) and t.attr == "audio_out_dropped")
                        or (isinstance(t, ast.Name) and t.id == "audio_out_dropped")):
                    violations.append((name, node.lineno, "AugAssign"))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Attribute) and t.attr == "audio_out_dropped":
                        # exemption: the counter-definition assignment in
                        # counters.py (self.audio_out_dropped = 0)
                        is_def = (name == "counters.py"
                                  and isinstance(node.value, ast.Constant)
                                  and node.value.value == 0)
                        if not is_def:
                            violations.append((name, node.lineno, "Assign"))
    check("D1 no runtime audio_out_dropped mutation (definition exempt)",
          not violations, violations)


# ---- B/C. single-store sentinel harness ------------------------------------

MUTABLE = (list, dict, set, frozenset, bytearray, deque)
_PRUNE_TYPES = (type, types.FunctionType, types.MethodType, types.ModuleType,
                types.CodeType)


def _sentinel_walk(conn, sentinel, exempt):
    seeds = list(vars(conn).values())
    seen = set()
    hits = set()
    stack = list(seeds)
    while stack:
        o = stack.pop()
        if id(o) in seen:
            continue
        seen.add(id(o))
        if o is conn:
            continue
        if any(o is e for e in exempt):
            continue
        if isinstance(o, _PRUNE_TYPES):
            continue
        try:
            refs = gc.get_referents(o)
        except Exception:
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


async def _build_sentinel_conn():
    nonce = ("%f" % time.monotonic()).encode()
    sentinel = b"\x00SENTINEL<" + nonce + b">"
    conn, ws = make_conn()
    conn.enc24.encode = lambda chunk, n: sentinel
    with NoPacer():
        await created(conn, "resp_sentinel")
        await delta(conn, "resp_sentinel", 960)
    return conn, sentinel


def test_sentinel_harness():
    async def go():
        conn, sentinel = await _build_sentinel_conn()
        store = conn.future_audio_store
        ok = True
        ok &= check("B1 future_audio_store is collections.deque",
                    type(store) is deque, type(store))
        ok &= check("B2 len(store) == 1", len(store) == 1, len(store))
        ok &= check("B3 store[0] is the exact sentinel object",
                    len(store) == 1 and store[0] is sentinel)
        ok &= check("B4 pacer_task is None (hold point valid)",
                    conn.pacer_task is None)
        absent = {s: (s in vars(conn) or any(s in c.__dict__
                    for c in type(conn).__mro__))
                  for s in ("dl_q", "SENTINEL", "_stop_pending",
                            "_enqueue_frame", "_enqueue_sentinel",
                            "_drop_one_non_sentinel", "_put_drop_oldest")}
        ok &= check("B5 legacy symbols absent on instance/class",
                    not any(absent.values()), absent)
        ok &= check("B6 no module-level SENTINEL",
                    not hasattr(turns, "SENTINEL"))
        exempt = [conn.ws, conn.diag, conn.config, conn.uplink_q, conn.dl_buf]
        hits = _sentinel_walk(conn, sentinel, exempt)
        ok &= check("B7 hits == {id(future_audio_store)} exactly one holder",
                    hits == {id(store)}, hits)
        # B8: exempt-subtree prune self-test
        conn.dl_buf.extend(sentinel)
        hits2 = _sentinel_walk(conn, sentinel, exempt)
        ok &= check("B8 exempt root subtree not counted", hits2 == {id(store)},
                    hits2)
        return ok

    ok = asyncio.run(asyncio.wait_for(go(), 30))
    return ok


def test_rogue_second_store():
    async def go():
        conn, sentinel = await _build_sentinel_conn()
        conn._rogue_store = deque([sentinel])
        exempt = [conn.ws, conn.diag, conn.config, conn.uplink_q, conn.dl_buf]
        hits = _sentinel_walk(conn, sentinel, exempt)
        ok = (len(hits) == 2 and id(conn.future_audio_store) in hits
              and id(conn._rogue_store) in hits)
        check("C1 rogue second deque detected as FAIL by the walk", ok, hits)
        return ok

    return asyncio.run(asyncio.wait_for(go(), 30))


# ---- E. closures -----------------------------------------------------------

async def _run_simple_generation(frames=3, extra_stale=True, idless=False):
    """created -> N frames -> (stale delta) -> seal -> drain."""
    clock = Clock()
    with TimeCtl(clock):
        conn, ws = make_conn()
        await created(conn, "r1")
        for _ in range(frames):
            await delta(conn, "r1", 960)
        if extra_stale:
            await delta(conn, "r1", 480)   # residue -> tail
        if idless:
            await delta(conn, None, 960, rid_key=True)
        await end(conn, "r1")
        if extra_stale:
            await delta(conn, "r1", 960)   # post-seal late delta -> STALE
        await drain(conn)
        await settle()
        return conn, ws


def test_source_closure():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await delta(conn, "r1", 960, rid_key=True)  # live
            await end(conn, "r1")
            await delta(conn, "r1", 240)          # STALE (after seal)
            await delta(conn, None, 960, rid_key=False)   # idless, no live gen
            await drain(conn)
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("E1 source closure residual == 0", source_residual(d) == 0, d)
    check("E2 guard_dropped == 240 (post-seal stale delta)",
          d["guard_dropped_pcm_bytes"] == 240, d["guard_dropped_pcm_bytes"])
    check("E3 post_terminal_delta_events == 1",
          d["post_terminal_delta_events"] == 1)
    check("E4 orphan (idless, no live gen) == 960",
          d["orphan_pcm_bytes"] == 960, d["orphan_pcm_bytes"])
    check("E5 orphan is OUTSIDE the source closure",
          source_residual(d) == 0)
    check("E6 run marked invalid for orphan",
          any("orphan" in r for r in conn._invalid_reasons),
          conn._invalid_reasons)
    return True


def test_idless_live_mapping():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960, rid_key=False)  # id-less LIVE
            await end(conn, "r1")
            await drain(conn)
            return conn

    asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("E7 idless_delta_mapped_bytes == 960",
          d["idless_delta_mapped_bytes"] == 960)
    check("E8 idless participates in source closure", source_residual(d) == 0)
    return True


def test_framer_and_disposition_closure():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await delta(conn, "r1", 960)
            # inject one encode failure on the next complete frame
            calls = {"n": 0}
            real_encode = conn.enc24.encode

            def flaky(chunk, n):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("inject encode failure")
                return real_encode(chunk, n)

            conn.enc24.encode = flaky
            await delta(conn, "r1", 960)
            await delta(conn, "r1", 500)   # residue -> synthetic tail
            await end(conn, "r1")
            await drain(conn)
            return conn

    asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("E9 encode_failed_frames == 1", d["encode_failed_frames"] == 1,
          d["encode_failed_frames"])
    check("E10 synthetic tail frame + source bytes recorded",
          d["synthetic_tail_frames"] == 1 and d["synthetic_tail_source_bytes"] == 500)
    check("E11 source residual == 0", source_residual(d) == 0, source_residual(d))
    check("E12 framer residual == 0", framer_residual(d, after) == 0)
    check("E13 disposition residual == 0",
          disposition_residual(d, after) == 0,
          (disposition_residual(d, after), d))
    check("E14 quiescence gauges zeroed",
          g(after, "still_stored_frames") == 0
          and g(after, "in_flight_frames") == 0
          and g(after, "still_buffered_pcm_bytes") == 0)
    return True


# ---- F. store cap R1 / R2 --------------------------------------------------

async def _fill_store(conn, rid, n_frames):
    for _ in range(n_frames):
        await delta(conn, rid, 960)


def test_store_cap_r1():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await _fill_store(conn, "r1", 1500)
            check("F1 backlog reached exactly 1500", conn._backlog() == 1500,
                  conn._backlog())
            await delta(conn, "r1", 500)          # admitted partial residue
            check("F2 partial residue admitted at full backlog",
                  len(conn.dl_buf) == 500, len(conn.dl_buf))
            await delta(conn, "r1", 500)          # 500+500 >= 960 -> R1
            gen = conn.generations["r1"]
            check("F3 R1 fired exactly once", gen.cap_transitions == 1,
                  gen.cap_transitions)
            check("F4 dl_buf == 0 after R1", len(conn.dl_buf) == 0)
            check("F5 store still 1500 (no 1501st frame)",
                  conn._queued_frames == 1500, conn._queued_frames)
            await delta(conn, "r1", 960)          # later delta -> truncated
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 120))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("F6 cap_transitions_total == 1", d["cap_transitions_total"] == 1)
    check("F7 residue_discarded_store_cap_bytes == 500",
          d["residue_discarded_store_cap_bytes"] == 500)
    check("F8 safety_truncated == 500 + 960 (trigger + later delta)",
          d["safety_truncated_pcm_bytes"] == 1460,
          d["safety_truncated_pcm_bytes"])
    check("F9 cap_transitions_max_per_generation <= 1",
          g(after, "cap_transitions_max_per_generation") <= 1)
    check("F10 unsent_backlog_peak_frames <= 1500",
          g(after, "unsent_backlog_peak_frames") <= 1500)
    check("F11 source residual == 0", source_residual(d) == 0, source_residual(d))
    return True


def test_store_cap_r2():
    ok = True
    for N in (1, 200, 500, 959):
        before = counters.snapshot()

        async def go():
            clock = Clock()
            with TimeCtl(clock):
                with NoPacer():
                    conn, ws = make_conn()
                    await created(conn, "r1")
                    await _fill_store(conn, "r1", 1500)
                    await delta(conn, "r1", N)   # N < 960 -> admitted residue
                ok_res = check("F12.%d residue advertised in dl_buf" % N,
                               len(conn.dl_buf) == N, len(conn.dl_buf))
                await end(conn, "r1")
                await drain(conn)
                await settle()
                return conn, ok_res

        conn, ok_res = asyncio.run(asyncio.wait_for(go(), 120))
        ok &= ok_res
        after = counters.snapshot()
        d = cdiff(before, after)
        gen = conn.generations["r1"]
        ok &= check("F13.%d R2: no synthetic tail" % N,
                    d["synthetic_tail_frames"] == 0
                    and d["synthetic_tail_source_bytes"] == 0)
        ok &= check("F14.%d R2: residue += N exactly once" % N,
                    d["residue_discarded_store_cap_bytes"] == N,
                    d["residue_discarded_store_cap_bytes"])
        ok &= check("F15.%d R2: no safety truncation" % N,
                    d["safety_truncated_pcm_bytes"] == 0)
        ok &= check("F16.%d cap once, one marker, one stop" % N,
                    gen.cap_transitions == 1 and gen.end_markers == 1
                    and gen.tts_stop_emissions == 1,
                    (gen.cap_transitions, gen.end_markers, gen.tts_stop_emissions))
        ok &= check("F17.%d no frame 1501 (peak <= 1500)" % N,
                    g(after, "unsent_backlog_peak_frames") <= 1500)
        ok &= check("F18.%d sent all 1500 frames" % N,
                    d["sent_confirmed_frames"] == 1500,
                    d["sent_confirmed_frames"])
        ok &= check("F19.%d closures residual 0" % N,
                    source_residual(d) == 0 and framer_residual(d, after) == 0
                    and disposition_residual(d, after) == 0,
                    (source_residual(d), framer_residual(d, after),
                     disposition_residual(d, after)))
        ok &= check("F20.%d quiescence zeroed" % N,
                    g(after, "still_stored_frames") == 0
                    and g(after, "in_flight_frames") == 0
                    and g(after, "still_buffered_pcm_bytes") == 0)
    return ok


def test_store_cap_mid_delta():
    """F21: a MULTI-frame delta near the cap must never admit frame 1501."""
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await _fill_store(conn, "r1", 1499)
            check("F21a backlog == 1499 before the burst delta",
                  conn._backlog() == 1499, conn._backlog())
            await delta(conn, "r1", payload=b"\x11" * (960 * 10))
            gen = conn.generations["r1"]
            check("F21b mid-delta cap fired exactly once",
                  gen.cap_transitions == 1 and conn._queued_frames == 1500,
                  (gen.cap_transitions, conn._queued_frames))
            check("F21c dl_buf == 0 (no unformed admitted bytes left)",
                  len(conn.dl_buf) == 0)
            await delta(conn, "r1", 960)      # later delta -> safety truncated
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 180))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("F21d no 1501st frame (peak <= 1500)",
          g(after, "unsent_backlog_peak_frames") <= 1500,
          g(after, "unsent_backlog_peak_frames"))
    check("F21e residue == unformed admitted bytes (10*960 - 960)",
          d["residue_discarded_store_cap_bytes"] == 8640,
          d["residue_discarded_store_cap_bytes"])
    check("F21f later delta safety-truncated",
          d["safety_truncated_pcm_bytes"] == 960,
          d["safety_truncated_pcm_bytes"])
    check("F21g cap at most once per generation",
          g(after, "cap_transitions_max_per_generation") <= 1)
    check("F21h no accounting fault (the guard is a designed branch)",
          d["accounting_fault_events"] == 0, d["accounting_fault_events"])
    check("F21i source + framer closure residual 0",
          source_residual(d) == 0 and framer_residual(d, after) == 0,
          (source_residual(d), framer_residual(d, after)))
    # pacer deliberately stalled (NoPacer): the live store gauge stands in for
    # the quiescence gauge still_stored_frames
    disp = (d["encoded_full_frames"] + d["synthetic_tail_frames"]
            - (d["sent_confirmed_frames"] + sum(d[k] for k in FLUSH_KEYS)
               + d["send_failed_frames"] + d["send_outcome_unknown_frames"]
               + g(after, "audio_store_current_frames")
               + g(after, "in_flight_frames")))
    check("F21j disposition closure residual 0 (store gauge counted)",
          disp == 0, disp)
    return True


def test_failed_send_arms_guard():
    """A.5 §2: a failed send arms send_guard_until = observation + 15 ms."""
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            ws.clock = clock
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await settle(3)
            ws.fail_next = RuntimeError("transport down")
            await delta(conn, "r1", 960)
            await drain(conn)
            fail_time = clock.now_ms()
            guard = conn.send_guard_until
            check("M6a failed send armed send_guard_until",
                  guard is not None and guard >= fail_time - 5.0,
                  (guard, fail_time))
            # a brand-new generation's first send must respect the guard
            await created(conn, "r2")
            await delta(conn, "r2", 960)
            await settle(30)
            starts = [t for t in ws.timestamps if t is not None]
            ok = False
            if guard is not None:
                ok = any(t >= guard - 0.001 for t in starts)
            check("M6b next audio send start respects the failed-send guard",
                  ok, (guard, starts[-3:]))
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 60))
    check("M6c send_failed_frames == 1", cdiff(before, counters.snapshot())[
        "send_failed_frames"] == 1)
    return True


# ---- G. byte cap -----------------------------------------------------------

async def _arm_byte_cap(conn, rid, packet_size=1000):
    conn.enc24.encode = lambda chunk, n: b"x" * packet_size


def test_byte_cap_no_head():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock), NoPacer():
            conn, ws = make_conn()
            await created(conn, "r1")
            await _arm_byte_cap(conn, "r1")
            for _ in range(525):
                await delta(conn, "r1", 960)
            return conn, ws

    conn, ws = asyncio.run(asyncio.wait_for(go(), 120))
    after = counters.snapshot()
    d = cdiff(before, after)
    gen = conn.generations["r1"]
    check("G1 byte_cap_failures == 1", d["byte_cap_failures"] == 1,
          d["byte_cap_failures"])
    check("G2 store emptied, trigger never stored",
          len(conn.future_audio_store) == 0)
    check("G3 flushed == queued(524) + trigger(1)",
          d["flushed_byte_cap_failure_frames"] == 525,
          d["flushed_byte_cap_failure_frames"])
    check("G4 send_outcome_unknown == 0", d["send_outcome_unknown_frames"] == 0)
    check("G5 generation SEND_FORBIDDEN + reason",
          gen.send_forbidden and gen.forbid_reason == "BYTE_CAP_FAILURE")
    check("G6 exactly one TTS stop emitted",
          sum(1 for s in ws.strs if '"state": "stop"' in s
              or '"state":"stop"' in s) == 1, ws.strs)
    check("G7 closures residual 0",
          source_residual(d) == 0 and framer_residual(d, after) == 0
          and disposition_residual(d, after) == 0,
          (source_residual(d), framer_residual(d, after),
           disposition_residual(d, after)))
    return True


def test_byte_cap_reserved_wait():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        gate = asyncio.Event()          # cleared -> pacer waits
        gate.clear()
        with TimeCtl(clock, gate=gate):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)     # frame 1 (sent immediately)
            await settle()
            await delta(conn, "r1", 960)     # frame 2 -> pacer parks in wait
            await settle(10)
            check("G8 head parked in RESERVED_WAIT",
                  conn._head_state == "RESERVED_WAIT", conn._head_state)
            await _arm_byte_cap(conn, "r1")
            for _ in range(525):
                await delta(conn, "r1", 960)
            return conn, ws

    conn, ws = asyncio.run(asyncio.wait_for(go(), 120))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("G9 byte_cap_failures == 1", d["byte_cap_failures"] == 1)
    check("G10 head known-unsent (outcome unknown == 0)",
          d["send_outcome_unknown_frames"] == 0)
    check("G11 flushed == head(1) + queued(524) + trigger(1)",
          d["flushed_byte_cap_failure_frames"] == 526,
          d["flushed_byte_cap_failure_frames"])
    check("G12 closures residual 0",
          source_residual(d) == 0 and framer_residual(d, after) == 0
          and disposition_residual(d, after) == 0)
    return True


def test_byte_cap_send_await():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        send_gate = asyncio.Event()
        conn, ws = make_conn()

        async def on_send(pkt):
            await send_gate.wait()

        ws.on_send = on_send
        with TimeCtl(clock):
            await created(conn, "r1")
            await delta(conn, "r1", 960)      # pacer pops -> blocks in SEND_AWAIT
            await settle(10)
            check("G13 head parked in SEND_AWAIT",
                  conn._head_state == "SEND_AWAIT", conn._head_state)
            await _arm_byte_cap(conn, "r1")
            for _ in range(525):
                await delta(conn, "r1", 960)
            return conn, ws

    conn, ws = asyncio.run(asyncio.wait_for(go(), 120))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("G14 byte_cap_failures == 1", d["byte_cap_failures"] == 1)
    check("G15 SEND_AWAIT head -> outcome unknown == 1 (INVALID)",
          d["send_outcome_unknown_frames"] == 1,
          d["send_outcome_unknown_frames"])
    check("G16 flushed == queued(524) + trigger(1)",
          d["flushed_byte_cap_failure_frames"] == 525,
          d["flushed_byte_cap_failure_frames"])
    check("G17 closures residual 0 (unknown is a disposition term)",
          source_residual(d) == 0 and framer_residual(d, after) == 0
          and disposition_residual(d, after) == 0)
    return True


# ---- H. one-shot cancel ----------------------------------------------------

def test_one_shot_cancel():
    before = counters.snapshot()

    async def go():
        conn, ws = make_conn()
        await created(conn, "r1")
        gen = conn.generations["r1"]
        r1 = await conn._cancel_upstream_once(gen, "BARGEIN")
        r2 = await conn._cancel_upstream_once(gen, "BARGEIN")
        check("H1 first cancel SENT", r1 == "SENT", r1)
        check("H2 second cancel ALREADY_REQUESTED", r2 == "ALREADY_REQUESTED", r2)
        check("H3 exactly one upstream response.cancel",
              conn.qwen.cancel_calls == 1, conn.qwen.cancel_calls)
        gen2 = turns.Generation(99, "r2")
        gen2.upstream_terminal = True
        r3 = await conn._cancel_upstream_once(gen2, "ABORT")
        check("H4 upstream-terminal cancel skipped", r3 == "ALREADY_TERMINAL", r3)

    asyncio.run(asyncio.wait_for(go(), 30))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("H5 cancel_max_per_generation == 1",
          g(after, "cancel_max_per_generation") == 1)
    check("H6 cancel_attempts == 1", d["cancel_attempts"] == 1)
    return True


# ---- I. SEND_FORBIDDEN transitions -----------------------------------------

def test_send_forbidden_ordering_ast():
    path = os.path.join(APP_DIR, "turns.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    targets = {
        "BARGEIN": "_on_speech_started", "ABORT": "_on_abort",
        "CLOSE": "close", "LISTEN_START": "_on_listen_start",
        "UPSTREAM_CLOSED": "_on_qwen_closed",
        "SEND_ERROR": "_send_error_termination",
        "PACER_STALL": "_pacer_fatal_stall",
        "BYTE_CAP_FAILURE": "_byte_cap_failure",
    }
    ok = True
    for reason, fname in targets.items():
        fn = funcs[fname]
        inval_lines = [n.lineno for n in ast.walk(fn)
                       if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "_invalidate_generation"
                       and n.args and isinstance(n.args[-1], ast.Constant)]
        await_lines = [n.lineno for n in ast.walk(fn)
                       if isinstance(n, ast.Await)]
        inval = min(inval_lines) if inval_lines else None
        first_await = min(await_lines) if await_lines else 10 ** 9
        ok &= check("I1.%s %s(): invalidate before first await" % (reason, fname),
                    inval is not None and inval < first_await,
                    (inval, first_await))
    return ok


def test_send_forbidden_transitions():
    ok = True

    async def scenario(reason):
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await delta(conn, "r1", 960)
            await settle(3)
            if reason == "BARGEIN":
                await conn._on_speech_started()
            elif reason == "ABORT":
                await conn._on_abort({})
            elif reason == "CLOSE":
                await conn.close()
            elif reason == "LISTEN_START":
                await conn._on_listen_start("realtime")
            elif reason == "UPSTREAM_CLOSED":
                await conn._on_qwen_closed()
            elif reason == "SEND_ERROR":
                ws.fail_next = RuntimeError("transport down")
                await delta(conn, "r1", 960)
                await drain(conn)
            elif reason == "PACER_STALL":
                async def slow_send(pkt):
                    clock.advance_ms(300.0)
                ws.on_send = slow_send
                await delta(conn, "r1", 960)
                await drain(conn)
            elif reason == "BYTE_CAP_FAILURE":
                with NoPacer():
                    await _arm_byte_cap(conn, "r1")
                    for _ in range(526):
                        await delta(conn, "r1", 960)
            gen = conn.generations.get("r1")
            return gen

    for reason in ("BARGEIN", "ABORT", "CLOSE", "LISTEN_START",
                   "UPSTREAM_CLOSED", "SEND_ERROR", "PACER_STALL",
                   "BYTE_CAP_FAILURE"):
        gen = asyncio.run(asyncio.wait_for(scenario(reason), 120))
        ok &= check("I2.%s send_forbidden + reason" % reason,
                    gen is not None and gen.send_forbidden
                    and gen.forbid_reason == reason,
                    (gen.send_forbidden if gen else None,
                     gen.forbid_reason if gen else None))
    return ok


# ---- J/K. SEALED_DRAINING, drain, duplicate end ----------------------------

def test_sealed_draining_and_late_delta():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await delta(conn, "r1", 960)
            await end(conn, "r1", etype="response.audio.done")
            gen = conn.generations["r1"]
            check("J1 seal enters SEALED_DRAINING (not forbidden)",
                  gen.sealed and not gen.send_forbidden
                  and gen.terminal_tier == "SEALED_DRAINING")
            await delta(conn, "r1", 960)          # late delta -> STALE
            await drain(conn)
            return conn, ws, gen

    conn, ws, gen = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("J2 late delta classified STALE (guard_dropped 960)",
          d["guard_dropped_pcm_bytes"] == 960)
    check("J3 legal drain: sent == 2, post_terminal_sends == 0",
          d["sent_confirmed_frames"] == 2 and d["post_terminal_sends_total"] == 0,
          (d["sent_confirmed_frames"], d["post_terminal_sends_total"]))
    check("J4 one marker, one stop", gen.end_markers == 1
          and gen.tts_stop_emissions == 1,
          (gen.end_markers, gen.tts_stop_emissions))
    check("J5 closures residual 0",
          source_residual(d) == 0 and framer_residual(d, after) == 0
          and disposition_residual(d, after) == 0)
    return True


def test_duplicate_end():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await end(conn, "r1", etype="response.audio.done")
            await end(conn, "r1", etype="response.done", status="completed")
            await drain(conn)
            gen = conn.generations["r1"]
            check("K1 duplicate end idempotent (one marker)",
                  gen.end_markers == 1, gen.end_markers)
            check("K2 tts stop emitted once", gen.tts_stop_emissions == 1)
            return conn

    asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("K3 no accounting fault on clean duplicate end",
          d["accounting_fault_events"] == 0, d["accounting_fault_events"])
    check("K4 end_markers_max_per_generation <= 1",
          g(after, "end_markers_max_per_generation") <= 1)
    return True


def test_duplicate_end_residue_tripwire():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 300)     # residue 300
            await end(conn, "r1", etype="response.audio.done")
            # first seal consumed the residue; force the tripwire state:
            conn.dl_buf.extend(b"\x00" * 123)
            await end(conn, "r1", etype="response.done")
            await drain(conn)
            return conn

    asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("K5 duplicate end with residue -> accounting fault + named bucket",
          d["accounting_fault_events"] == 1, d["accounting_fault_events"])
    check("K6 residue routed (never blind-cleared)",
          (d["residue_discarded_pcm_bytes"] >= 123),
          d["residue_discarded_pcm_bytes"])
    return True


# ---- L. bad base64 / orphan ------------------------------------------------

def test_bad_base64():
    before = counters.snapshot()

    async def go():
        conn, ws = make_conn()
        await created(conn, "r1")
        await conn._on_qwen_event({"type": "response.audio.delta",
                                   "response_id": "r1", "delta": "!!!bad!!!"})
        check("L1 live bad base64 -> bad_base64_live_events",
              conn._invalid_reasons and "bad_base64_live" in conn._invalid_reasons,
              conn._invalid_reasons)
        conn.current_resp_id = None
        conn._current_gen = None
        await conn._on_qwen_event({"type": "response.audio.delta",
                                   "response_id": "r9", "delta": "!!!bad!!!"})

    asyncio.run(asyncio.wait_for(go(), 30))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("L2 bad_base64_live_events == 1", d["bad_base64_live_events"] == 1)
    check("L3 bad_base64_stale_or_unmapped_events == 1",
          d["bad_base64_stale_or_unmapped_events"] == 1)
    return True


# ---- M. slow send (T=10 ms) + N/O stalls -----------------------------------

def test_slow_send_guard():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            n = {"i": 0}

            async def slow_once(pkt):
                n["i"] += 1
                if n["i"] == 1:
                    clock.advance_ms(10.0)   # T = 10 ms slow success

            ws.on_send = slow_once
            await created(conn, "r1")
            for _ in range(6):
                await delta(conn, "r1", 960)
            await end(conn, "r1")
            await drain(conn)
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("M1 slow_send_events == 1", d["slow_send_events"] == 1,
          d["slow_send_events"])
    check("M2 rebase counted (§2 slow-send)", d["pacer_rebases"] >= 1)
    check("M3 no guard violation", d["slow_send_guard_violations"] == 0,
          d["slow_send_guard_violations"])
    check("M4 no interval below 14.999 ms",
          d["pacer_short_interval_count"] == 0
          and (g(after, "pacer_min_inter_send_ms_observed") is None
               or g(after, "pacer_min_inter_send_ms_observed") >= 14.999),
          (d["pacer_short_interval_count"],
           g(after, "pacer_min_inter_send_ms_observed")))
    check("M5 send_guard_until state recorded",
          after.get("send_guard_until") is not None or conn.send_guard_until is not None)
    return True


def test_fatal_stall_post_send():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()

            async def very_slow(pkt):
                clock.advance_ms(300.0)

            ws.on_send = very_slow
            await created(conn, "r1")
            for _ in range(3):
                await delta(conn, "r1", 960)
            await settle(3)
            await drain(conn)
            gen = conn.generations["r1"]
            return conn, ws, gen

    conn, ws, gen = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("N1 pacer_fatal_stalls == 1", d["pacer_fatal_stalls"] == 1,
          d["pacer_fatal_stalls"])
    check("N2 generation invalidated (PACER_STALL)",
          gen.send_forbidden and gen.forbid_reason == "PACER_STALL")
    check("N3 completed slow send is SENT (1), rest flushed to stall bucket",
          d["sent_confirmed_frames"] == 1
          and d["flushed_pacer_stall_frames"] == 2,
          (d["sent_confirmed_frames"], d["flushed_pacer_stall_frames"]))
    check("N4 exactly one TTS stop", gen.tts_stop_emissions == 1)
    check("N5 closures residual 0",
          source_residual(d) == 0 and framer_residual(d, after) == 0
          and disposition_residual(d, after) == 0,
          (source_residual(d), framer_residual(d, after),
           disposition_residual(d, after)))
    return True


def test_fatal_stall_pre_send():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        gate = asyncio.Event()
        gate.clear()
        with TimeCtl(clock, gate=gate):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)          # frame 1 sent immediately
            await settle(3)
            await delta(conn, "r1", 960)          # frame 2 -> waits (gate)
            await settle(10)
            check("N6 head in RESERVED_WAIT before stall",
                  conn._head_state == "RESERVED_WAIT", conn._head_state)
            clock.advance_ms(400.0)               # lateness > 250
            gate.set()
            await drain(conn)
            gen = conn.generations["r1"]
            return conn, gen

    conn, gen = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("N7 pacer_fatal_stalls == 1 (bounded, no silent rebase)",
          d["pacer_fatal_stalls"] == 1)
    check("N8 head known-unsent -> flushed_pacer_stall_frames",
          d["flushed_pacer_stall_frames"] == 1
          and d["send_outcome_unknown_frames"] == 0,
          (d["flushed_pacer_stall_frames"], d["send_outcome_unknown_frames"]))
    check("N9 generation SEND_FORBIDDEN", gen.send_forbidden)
    check("N10 closures residual 0",
          source_residual(d) == 0 and framer_residual(d, after) == 0
          and disposition_residual(d, after) == 0)
    return True


def test_event_loop_stall_10s():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        gate = asyncio.Event()
        gate.clear()
        with TimeCtl(clock, gate=gate):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await settle(3)
            await delta(conn, "r1", 960)
            await settle(10)
            clock.advance_ms(10000.0)     # simulated 10 s event-loop stall
            gate.set()
            await drain(conn)
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("O1 10 s stall -> exactly one PACER_FATAL_STALL",
          d["pacer_fatal_stalls"] == 1, d["pacer_fatal_stalls"])
    check("O2 no undead playback: in_flight == 0 and closures 0",
          g(after, "in_flight_frames") == 0
          and source_residual(d) == 0 and framer_residual(d, after) == 0
          and disposition_residual(d, after) == 0)
    check("O3 post_terminal_sends_total == 0",
          d["post_terminal_sends_total"] == 0)
    check("O4 crash-free 10 s stall (no multi-second rebase)",
          d["pacer_rebases"] == 0, d["pacer_rebases"])
    return True


# ---- P/Q. epochs + wire excess --------------------------------------------

def test_epochs():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        gate = asyncio.Event()
        gate.set()
        with TimeCtl(clock, gate=gate):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await settle(3)
            check("P1 first pacer start is E1",
                  conn.pacer_starts == 1 and conn.epoch_ordinal == 1,
                  (conn.pacer_starts, conn.epoch_ordinal))
            # force an E2 lateness rebase: block the pacer's next pre-send wait
            gate.clear()
            await delta(conn, "r1", 960)
            await settle(8)
            check("P1b pacer parked in RESERVED_WAIT",
                  conn._head_state == "RESERVED_WAIT", conn._head_state)
            clock.advance_ms(100.0)
            gate.set()
            await settle(30)
            check("P2 E2 lateness rebase created a new epoch",
                  conn.epoch_ordinal == 2, conn.epoch_ordinal)
            # E3: slow successful send on the next frame
            async def slow(pkt):
                clock.advance_ms(8.0)

            ws.on_send = slow
            await delta(conn, "r1", 960)
            await settle(30)
            check("P3 E3 slow-send rebase created a new epoch",
                  conn.epoch_ordinal == 3, conn.epoch_ordinal)
            await end(conn, "r1")
            await drain(conn)
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("P4 wire_rate_excess_frames_max <= 1 (E1/E2/E3)",
          g(after, "wire_rate_excess_frames_max") <= 1,
          g(after, "wire_rate_excess_frames_max"))
    check("P5 rebases counted", d["pacer_rebases"] == 2, d["pacer_rebases"])
    return True


def test_response2_new_pacer_e4():
    before = counters.snapshot()

    async def go():
        clock = Clock()
        with TimeCtl(clock):
            conn, ws = make_conn()
            await created(conn, "r1")
            await delta(conn, "r1", 960)
            await end(conn, "r1")
            await drain(conn)
            check("Q1 pacer exited after response-1 drain",
                  conn.pacer_task is None, conn.pacer_task)
            e_before = conn.epoch_ordinal
            await created(conn, "r2")
            await delta(conn, "r2", 960)
            await settle(3)
            check("Q2 response-2 pacer start is E4 (epoch incremented)",
                  conn.epoch_ordinal == e_before + 1
                  and conn.sent_in_epoch >= 1,
                  (e_before, conn.epoch_ordinal, conn.sent_in_epoch))
            await end(conn, "r2")
            await drain(conn)
            return conn

    conn = asyncio.run(asyncio.wait_for(go(), 60))
    after = counters.snapshot()
    d = cdiff(before, after)
    check("Q3 pacer_starts == 2", d["pacer_starts"] == 2, d["pacer_starts"])
    check("Q4 no false wire excess across E4",
          g(after, "wire_rate_excess_frames_max") <= 1,
          g(after, "wire_rate_excess_frames_max"))
    check("Q5 active_pacer_tasks_max <= 1",
          g(after, "active_pacer_tasks_max") <= 1)
    return True


# ---- R/S. segment extrema --------------------------------------------------

def test_segment_extrema():
    CLASS = turns.Connection
    # S (good segments first, so the min/max observations are not polluted)
    conn2, ws2 = make_conn()
    conn2._pacer_pid = 2
    conn2._seg_ordinal_in_epoch = 0
    add2 = CLASS._segment_add.__get__(conn2)
    before2 = counters.snapshot()
    for k in range(3):
        for i in range(260):
            add2(2000.0 + k * 10000.0 + i * 20.0)
        CLASS._segment_terminate.__get__(conn2)("pacer_exit", clean=True)
    after2 = counters.snapshot()
    lo, hi = (g(after2, "steady_segment_rate_fps_min"),
              g(after2, "steady_segment_rate_fps_max"))
    check("S1 all-good segments: fps extrema within [49.5, 50.5]",
          lo is not None and hi is not None and lo >= 49.5 and hi <= 50.5,
          (lo, hi))
    check("S1b three qualifying segments counted",
          g(after2, "steady_pacer_segments_qualifying_total")
          - g(before2, "steady_pacer_segments_qualifying_total") == 3)
    # S2: short segment not qualifying
    conn3, ws3 = make_conn()
    conn3._pacer_pid = 3
    conn3._seg_ordinal_in_epoch = 0
    add3 = CLASS._segment_add.__get__(conn3)
    before3 = counters.snapshot()
    for i in range(100):
        add3(3000.0 + i * 20.0)
    CLASS._segment_terminate.__get__(conn3)("pacer_exit", clean=True)
    after3 = counters.snapshot()
    check("S2 short (<250) segment not qualifying",
          g(after3, "steady_pacer_segments_qualifying_total")
          == g(before3, "steady_pacer_segments_qualifying_total"))
    # S3: dirty segment excluded
    conn4, ws4 = make_conn()
    conn4._pacer_pid = 4
    conn4._seg_ordinal_in_epoch = 0
    add4 = CLASS._segment_add.__get__(conn4)
    for i in range(300):
        add4(4000.0 + i * 20.0)
    conn4._segment_mark_dirty()
    CLASS._segment_terminate.__get__(conn4)("pacer_exit", clean=True)
    after4 = counters.snapshot()
    check("S3 dirty (rebased/stalled) segment excluded",
          g(after4, "steady_pacer_segments_qualifying_total")
          == g(after3, "steady_pacer_segments_qualifying_total"))
    # R: a 49.0 fps segment must FAIL the [49.5, 50.5] gate
    conn, ws = make_conn()
    conn._pacer_pid = 1
    conn._seg_ordinal_in_epoch = 0
    add = CLASS._segment_add.__get__(conn)
    t0 = 1000.0
    n = 300
    for i in range(n):
        add(t0 + i * (1000.0 / 49.0))
    CLASS._segment_terminate.__get__(conn)("pacer_exit", clean=True)
    after = counters.snapshot()
    v = g(after, "steady_segment_rate_fps_min")
    check("R1 49.0 fps segment qualifies and pushes fps_min ~49.0",
          v is not None and abs(v - 49.0) < 0.01, v)
    check("R2 gate verdict: 49.0 < 49.5 -> FAIL", (v is not None and v < 49.5))
    return True


# ---- constants -------------------------------------------------------------

def test_constants_locked():
    check("Z1 MEDIA_FRAME_MS == 20.0", turns.MEDIA_FRAME_MS == 20.0)
    check("Z2 MIN_SEND_START_INTERVAL_MS == 15.0",
          turns.MIN_SEND_START_INTERVAL_MS == 15.0)
    check("Z3 PACING_SLACK_MS == 5.0", turns.PACING_SLACK_MS == 5.0)
    check("Z4 MAX_FUTURE_FRAMES == 1500", turns.MAX_FUTURE_FRAMES == 1500)
    check("Z5 MAX_FUTURE_AUDIO_BYTES == 524288",
          turns.MAX_FUTURE_AUDIO_BYTES == 524288)
    check("Z6 MAX_REBASE_LATENESS_MS == 250",
          turns.MAX_REBASE_LATENESS_MS == 250.0)
    check("Z7 SLOW_SEND_THRESHOLD_MS == 5.0",
          turns.SLOW_SEND_THRESHOLD_MS == 5.0)
    return True


# ---- runner ----------------------------------------------------------------

TESTS = [
    ("A", test_ast_scan_legacy),
    ("B", test_sentinel_harness),
    ("C", test_rogue_second_store),
    ("D", test_audio_out_dropped_mutation),
    ("E", test_source_closure),
    ("E", test_idless_live_mapping),
    ("E", test_framer_and_disposition_closure),
    ("F", test_store_cap_r1),
    ("F", test_store_cap_r2),
    ("F", test_store_cap_mid_delta),
    ("G", test_byte_cap_no_head),
    ("G", test_byte_cap_reserved_wait),
    ("G", test_byte_cap_send_await),
    ("H", test_one_shot_cancel),
    ("I", test_send_forbidden_ordering_ast),
    ("I", test_send_forbidden_transitions),
    ("J", test_sealed_draining_and_late_delta),
    ("K", test_duplicate_end),
    ("K", test_duplicate_end_residue_tripwire),
    ("L", test_bad_base64),
    ("M", test_slow_send_guard),
    ("M", test_failed_send_arms_guard),
    ("N", test_fatal_stall_post_send),
    ("N", test_fatal_stall_pre_send),
    ("O", test_event_loop_stall_10s),
    ("P", test_epochs),
    ("Q", test_response2_new_pacer_e4),
    ("R", test_segment_extrema),
    ("CST", test_constants_locked),
]


def main(argv):
    if os.environ.get("RTL_DIAG", "0") == "1":
        print("FATAL: RTL_DIAG must be UNSET for the deterministic suite (m10)")
        return 2
    wanted = set(argv[1:])
    t0 = time.time()
    for group, fn in TESTS:
        if wanted and group not in wanted:
            continue
        print("---- %s %s ----" % (group, fn.__name__))
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check("%s %s EXCEPTION" % (group, fn.__name__), False, repr(e))
    fails = [r for r in RESULTS if not r[1]]
    npass = len(RESULTS) - len(fails)
    print("=" * 70)
    print("R1F_BRIDGE_TESTS: %d checks, %d PASS, %d FAIL, %.1fs"
          % (len(RESULTS), npass, len(fails), time.time() - t0))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))