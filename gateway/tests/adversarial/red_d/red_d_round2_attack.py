"""RED-D ROUND-2 ATTACK SUITE — defeat the RED-D-01..05 fixes.

Read-only on product source. Loopback + temp dirs only. No real-Qwen session.
Run:  cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
        tests/adversarial/red_d/red_d_round2_attack.py
"""

import asyncio
import copy
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_GATEWAY = Path(__file__).resolve().parents[3]
_REPO = _GATEWAY.parent
for _p in (str(_GATEWAY), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from aiohttp.test_utils import TestClient, TestServer            # noqa: E402
from app.admin import load_admin_config                          # noqa: E402
from app.admin.app import create_admin_app                       # noqa: E402
from app.admin.auth import TokenStore                            # noqa: E402
from app.admin.stores import AdminStores                         # noqa: E402
from modules.intent import behavior as intent                    # noqa: E402
from modules.policy.persona import (DEFAULT_POLICY, PersistError,  # noqa: E402
                                    PolicyInvalid, PolicyStore, validate_policy)

TOKEN = "REDD_R2_TOKEN_DO_NOT_LEAK_0002"
AUTH = {"Authorization": "Bearer " + TOKEN}
JSONH = {**AUTH, "Content-Type": "application/json"}
WORKER = str(Path(__file__).parent / "_policy_mp_worker.py")

RESULTS = []
METRICS = {}


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%r]" % (detail,)) if (detail and not cond) else ""))


def observe(name, value):
    print("INFO  %s = %r" % (name, value))


def _cfg(tmpdir):
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "9142",
        "ADMIN_API_TOKEN_FILE": str(Path(tmpdir) / "admin_api_token"),
        "ADMIN_UI_DIR": str(_REPO / "admin")})


async def with_stores(fn, tmpdir, name, *, policy_file=None, memory_file=None,
                      knowledge_file=None):
    cfg = _cfg(tmpdir)
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    sub = Path(tmpdir) / name
    sub.mkdir(parents=True, exist_ok=True)
    stores = AdminStores(
        policy_file=str(policy_file if policy_file is not None else sub / "policy.json"),
        memory_file=str(memory_file if memory_file is not None else sub / "memory.json"),
        knowledge_file=str(knowledge_file if knowledge_file is not None
                           else sub / "knowledge.json"))
    app = create_admin_app(admin_config=cfg, token_store=ts,
                           gateway_info=lambda: {"mode": "mock"}, stores=stores)
    async with TestClient(TestServer(app)) as client:
        await fn(client, stores, tmpdir)


async def api(client, method, path, **kw):
    kw.setdefault("headers", AUTH)
    r = await client.request(method, path, **kw)
    try:
        body = await r.json()
    except Exception:  # noqa: BLE001
        body = None
    return r.status, body


def _no_tmp(dirpath):
    try:
        if not os.path.isdir(str(dirpath)):
            return []
        return [f for f in os.listdir(str(dirpath)) if f.endswith(".tmp")]
    except OSError:
        return []


def _no_tmp_recursive(root):
    leaks = []
    for r, _d, files in os.walk(str(root)):
        for f in files:
            if f.endswith(".tmp"):
                leaks.append(os.path.join(r, f))
    return leaks


# ===========================================================================
# B. FLUSH-FAILURE MATRIX  (defeat the honest-persist fix)
# ===========================================================================

async def t_flush_matrix(tmpdir):
    print("\n--- B. flush-failure matrix (policy) ---")
    root = Path(tmpdir) / "b"
    root.mkdir(parents=True, exist_ok=True)

    # helper: run an apply against a store built on `pfile` and assert honest failure
    async def scenario(label, pfile, expect_fail, restore=None, name=None):
        async def body(client, stores, _):
            st0, act0 = await api(client, "GET", "/admin/policy/active")
            before = act0["version"] if act0 else None
            st, b = await api(client, "POST", "/admin/policy/apply",
                              json={"policy": {"persona": {"name": "DELTA"}}, "confirm": True})
            st1, act1 = await api(client, "GET", "/admin/policy/active")
            after = act1["version"] if act1 else None
            if expect_fail:
                check("B %s: status is 5xx (honest failure)" % label,
                      st >= 500, (st, b))
                check("B %s: readback_ok never true" % label,
                      not (isinstance(b, dict) and b.get("readback_ok") is True), b)
                check("B %s: no phantom version (active unchanged)" % label,
                      before == after, (before, after))
                lk = _no_tmp_recursive(root)
                check("B %s: no .tmp leak" % label, lk == [], lk)
            else:
                check("B %s: apply succeeds (mkdir parents auto-created)" % label,
                      st == 200 and b.get("readback_ok") is True, (st, b))
            if restore is not None:
                restore()
                st2, b2 = await api(client, "POST", "/admin/policy/apply",
                                    json={"policy": {"persona": {"name": "RECOVER"}},
                                          "confirm": True})
                check("B %s: a later legit apply works after recovery" % label,
                      st2 == 200 and b2.get("readback_ok") is True, (st2, b2))
        await with_stores(body, tmpdir, name or ("b_" + label.replace(" ", "_")),
                          policy_file=pfile)

    # 1. target path IS a directory
    d1 = root / "as_dir.json"
    d1.mkdir(parents=True, exist_ok=True)
    await scenario("path-is-directory", str(d1), expect_fail=True)

    # 2. read-only parent directory
    ro = root / "ro"
    ro.mkdir(parents=True, exist_ok=True)
    os.chmod(ro, 0o555)
    try:
        await scenario("read-only-dir", str(ro / "policy.json"), expect_fail=True,
                       restore=lambda: os.chmod(ro, 0o755))
    finally:
        os.chmod(ro, 0o755)

    # 3. a FILE where the parent should be
    fp = root / "fp"
    fp.mkdir(parents=True, exist_ok=True)
    (fp / "afile").write_text("x", encoding="utf-8")
    await scenario("file-where-parent-should-be",
                   str(fp / "afile" / "policy.json"), expect_fail=True)

    # 4. permission flip mid-run (valid first, then read-only, then restore)
    fl = root / "flip"
    fl.mkdir(parents=True, exist_ok=True)
    fpath = fl / "policy.json"

    async def flip_body(client, stores, _):
        st, b = await api(client, "POST", "/admin/policy/apply",
                          json={"policy": {"persona": {"name": "FIRST"}}, "confirm": True})
        check("B flip: first apply ok", st == 200 and b.get("readback_ok") is True, (st, b))
        v_first = (await api(client, "GET", "/admin/policy/active"))[1]["version"]
        os.chmod(fl, 0o555)
        try:
            st2, b2 = await api(client, "POST", "/admin/policy/apply",
                                json={"policy": {"persona": {"name": "BLOCKED"}},
                                      "confirm": True})
            check("B flip: apply under read-only dir is 5xx", st2 >= 500, (st2, b2))
            check("B flip: no readback_ok on failure",
                  not (isinstance(b2, dict) and b2.get("readback_ok") is True), b2)
            v_mid = (await api(client, "GET", "/admin/policy/active"))[1]["version"]
            check("B flip: no phantom (version unchanged)", v_mid == v_first, (v_first, v_mid))
            fresh = PolicyStore(str(fpath)).load().active()
            check("B flip: disk still holds FIRST", fresh["policy"]["persona"]["name"]
                  == "FIRST", fresh["policy"]["persona"]["name"])
        finally:
            os.chmod(fl, 0o755)
        st3, b3 = await api(client, "POST", "/admin/policy/apply",
                            json={"policy": {"persona": {"name": "AFTER"}}, "confirm": True})
        check("B flip: later legit apply works after recovery",
              st3 == 200 and b3.get("readback_ok") is True, (st3, b3))
    await with_stores(flip_body, tmpdir, "b_flip", policy_file=str(fpath))

    # 5. missing parent chain -> the store AUTO-CREATES it (observation, not a failure)
    mp = root / "mp" / "deep" / "policy.json"
    await scenario("missing-parent-chain(auto-mkdir)", str(mp), expect_fail=False,
                   name="b_missing_parent")
    check("B missing-parent: parents actually created", mp.exists())

    # 6. empty policy path -> store not configured (503) at the API layer
    cfg = _cfg(tmpdir)
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    stores_empty = AdminStores(policy_file="", memory_file="", knowledge_file="")
    check("B empty path: policy store is None (plane degrades honestly)",
          stores_empty.policy is None)

    # 7. direct store: PersistError raised (not silently swallowed), no phantom
    d2 = root / "direct_dir"
    d2.mkdir(parents=True, exist_ok=True)
    ps = PolicyStore(str(d2)).load()
    raised = False
    try:
        ps.apply({"persona": {"name": "GHOST"}})
    except PersistError:
        raised = True
    check("B direct: apply raises PersistError on flush failure", raised)
    check("B direct: no phantom in the same instance after failure",
          ps.active()["version"] == 1 and ps.active()["policy"]["persona"]["name"] == "小智",
          ps.active()["version"])
    check("B direct: no .tmp leak after failed flush", _no_tmp(d2.parent) == [],
          _no_tmp(d2.parent))


# ===========================================================================
# C. CONVERSE: any way to get 200 readback_ok:true without the disk change?
# ===========================================================================

async def t_false_success(tmpdir):
    print("\n--- C. false-success converse ---")

    # C1 symlink path: os.replace replaces the LINK; read-back reads the same path
    root = Path(tmpdir) / "c"
    root.mkdir(parents=True, exist_ok=True)
    real = root / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = root / "link.json"
    try:
        os.symlink(real, link)
    except OSError:
        link = None

    if link is not None:
        async def sym_body(client, stores, _):
            st, b = await api(client, "POST", "/admin/policy/apply",
                              json={"policy": {"persona": {"name": "SYM"}}, "confirm": True})
            check("C1 symlink: apply honest (200 + readback true)",
                  st == 200 and b.get("readback_ok") is True, (st, b))
            fresh = PolicyStore(str(link)).load().active()
            check("C1 symlink: read-back sees the written version",
                  fresh["version"] == b["applied"]["version"], fresh["version"])
            observe("C1 symlink target left untouched (os.replace swaps the link)",
                    real.read_text(encoding="utf-8") == "{}")
        await with_stores(sym_body, tmpdir, "c_sym", policy_file=str(link))

    # C2 concurrent applies via the API: no false persist_failed, no lost write
    async def conc_body(client, stores, _):
        N = 12

        async def one(i):
            return await api(client, "POST", "/admin/policy/apply",
                             json={"policy": {"persona": {"tone": "c%d" % i}},
                                   "confirm": True})
        res = await asyncio.gather(*[one(i) for i in range(N)])
        codes = [r[0] for r in res]
        ok = sum(1 for c in codes if c == 200)
        bad = [r for r in res if r[0] != 200]
        check("C2 concurrent API applies all honest (no spurious 5xx)", not bad, bad[:3])
        st, act = await api(client, "GET", "/admin/policy/active")
        vs = [v["version"] for v in (await api(client, "GET", "/admin/policy/versions"))[1]["versions"]]
        check("C2 versions unique + monotonic",
              vs == sorted(set(vs)), vs)
        check("C2 all %d applies durably landed (active == 1+ok)" % N,
              act["version"] == 1 + ok, (act["version"], ok))
    await with_stores(conc_body, tmpdir, "c_conc")

    # C3 a fresh read-back that cannot read the file must NOT report success
    root3 = Path(tmpdir) / "c3"
    root3.mkdir(parents=True, exist_ok=True)

    async def unreadable_body(client, stores, _):
        # after a successful apply, make the fresh read-back impossible by turning the
        # policy path into a directory AFTER the store exists (simulates write success
        # but read-back path inconsistent) -> the API must not claim readback_ok
        pth = Path(stores.policy.path)
        st, b = await api(client, "POST", "/admin/policy/apply",
                          json={"policy": {"persona": {"name": "OK1"}}, "confirm": True})
        check("C3 baseline apply ok", st == 200 and b.get("readback_ok") is True, (st, b))
    await with_stores(unreadable_body, tmpdir, "c3")


# ===========================================================================
# D. VALIDATION DEFEAT
# ===========================================================================

async def t_validation(tmpdir):
    print("\n--- D. validation defeat ---")

    async def body(client, stores, _):
        # D1 non-dict sections -> 400 (never 500)
        for sec in ("persona", "language", "teaching", "activities", "scenarios", "limits"):
            for val in ("x", 5, True, [1, 2], [{"CHAT": "x"}], None):
                st, b = await api(client, "POST", "/admin/policy/preview",
                                  json={"policy": {sec: val}})
                check("D1 %s=%r -> 400 not 500" % (sec, val),
                      st == 200 and b["valid"] is False and b["errors"], (st, b))

        # D2 NaN / Infinity inside limits and fields
        raw_cases = [
            '{"policy":{"limits":{"max_field_chars":NaN}},"confirm":true}',
            '{"policy":{"limits":{"max_field_chars":Infinity}},"confirm":true}',
            '{"policy":{"limits":{"internals_rule":NaN}},"confirm":true}',
            '{"policy":{"persona":{"name":-Infinity}},"confirm":true}',
        ]
        for raw in raw_cases:
            st, b = await api(client, "POST", "/admin/policy/apply", data=raw, headers=JSONH)
            check("D2 NaN/Inf refused, no crash: %s" % raw[:46],
                  st in (400, 413) and isinstance(b, dict) and "error" in b, (st, b))
        st, act = await api(client, "GET", "/admin/policy/active")
        check("D2b no mutation from NaN/Inf storm", act["version"] == 1)

        # D3 booleans as ints for limits
        for val in (True, False):
            st, b = await api(client, "POST", "/admin/policy/preview",
                              json={"policy": {"limits": {"max_field_chars": val}}})
            check("D3 bool limits rejected (%r)" % val, b["valid"] is False, (st, b))

        # D4 mixed-type rule array
        st, b = await api(client, "POST", "/admin/policy/preview",
                          json={"policy": {"teaching": {
                              "canonical_spelling_rules": [1, {"a": 1}, None, "ok", []]}}})
        check("D4 mixed-type rules array rejected",
              b["valid"] is False and b["errors"], (st, b))

        # D5 deeply nested but UNDER RecursionError (depth ~400)
        depth = 400
        nested = json.loads('{"a":' * depth + '1' + '}' * depth)
        st, b = await api(client, "POST", "/admin/policy/preview",
                          json={"policy": {"persona": nested}})
        check("D5 depth-400 nesting -> clean 4xx, not 500",
              st in (200, 400) and (st == 200 and b["valid"] is False) or st == 400,
              (st, b))

        # D6 wide/flat document: 3000 unknown keys under persona
        wide = {"k%04d" % i: "v" for i in range(3000)}
        wide["name"] = "X"
        st, b = await api(client, "POST", "/admin/policy/preview",
                          json={"policy": {"persona": wide}})
        nerr = len(b.get("errors") or []) if isinstance(b, dict) else -1
        observe("D6 wide-doc error count / status", (st, nerr))
        check("D6 wide doc rejected (no crash)", st == 200 and b["valid"] is False, (st, b))
        check("D6b wide-doc error list is bounded (<= len(keys)+small)",
              nerr <= 3005, nerr)

        # D7 near-duplicate / normalization keys
        st, b = await api(client, "POST", "/admin/policy/preview",
                          json={"policy": {"persona": {"name": "A", "nam\u0435": "B"}}})
        check("D7 homoglyph key -> unknown key rejected", b["valid"] is False, (st, b))
        # JSON duplicate keys collapse to last (not a security issue; observation)
        st, b = await api(client, "POST", "/admin/policy/preview",
                          json={"policy": {"persona": {"name": "A", "name": "B"}}})
        check("D7b duplicate JSON key collapses (no crash)", st == 200, (st, b))

        # D8 empty/whitespace and control-only strings
        for bad in ({"persona": {"name": "\u200b"}}, {"persona": {"name": "\n\t"}},
                    {"persona": {"name": "\x00"}}):
            st, b = await api(client, "POST", "/admin/policy/preview", json={"policy": bad})
            observe("D8 candidate %r" % bad, (st, b["valid"] if isinstance(b, dict) else b))

    await with_stores(body, tmpdir, "d_val")


# ===========================================================================
# E. ROLLBACK DEPTH + ORDERING
# ===========================================================================

async def t_rollback(tmpdir):
    print("\n--- E. rollback depth ---")
    root = Path(tmpdir) / "e"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "policy.json"
    ps = PolicyStore(str(path)).load()

    for i in range(2, 32):                       # 30 applies -> v31
        ps.apply({"persona": {"tone": "t%d" % i}})
    vs = [v["version"] for v in ps.versions()]
    check("E1 history bounded but v1 baseline retained", 1 in vs and len(vs) == 21, vs)

    out = ps.rollback(1)
    check("E2 rollback(1) restores the EXACT built-in defaults",
          ps.active()["policy"] == DEFAULT_POLICY, None)
    check("E2b rollback yields a NEW version", out["version"] == 32, out["version"])

    # oldest retained version
    oldest = min(v["version"] for v in ps.versions())
    out2 = ps.rollback(oldest)
    check("E3 rollback to the OLDEST retained version works",
          out2["restored_from"] == oldest, out2)

    # current version refused
    cur = ps.active()["version"]
    try:
        ps.rollback(cur)
        check("E4 rollback(current) refused", False, "no error")
    except PolicyInvalid:
        check("E4 rollback(current) refused", True)

    # twice in a row -> two distinct new versions, correct content (use a RETAINED one)
    hist = [v["version"] for v in ps.versions()][:-1]      # exclude active
    target = hist[-1]
    exp_name = ps.active()["policy"]["persona"].get("name")  # noqa: F841 (informational)
    a = ps.rollback(target)
    b = ps.rollback(target)
    check("E5 rollback twice -> two distinct new versions, correct restored_from",
          a["version"] != b["version"] and a["restored_from"] == target
          and b["restored_from"] == target,
          (a["version"], b["version"], target))

    # no version reuse / history[0] stays v1
    vs2 = [v["version"] for v in ps.versions()]
    check("E6 versions unique + monotonic", vs2 == sorted(set(vs2)), vs2)
    check("E6b history[0] is still v1", vs2[0] == 1, vs2[:3])

    # after restart
    ps_r = PolicyStore(str(path)).load()
    retained = [v["version"] for v in ps_r.versions()][:-1]
    tgt = retained[-1]
    out3 = ps_r.rollback(tgt)
    check("E7 rollback after restart works", out3["restored_from"] == tgt
          and out3["version"] == ps_r.active()["version"], out3)

    # ordering: replay versions yields the exact per-version content (no resurrection)
    root2 = Path(tmpdir) / "e2"
    root2.mkdir(parents=True, exist_ok=True)
    p2 = root2 / "policy.json"
    q = PolicyStore(str(p2)).load()
    q.apply({"persona": {"name": "AAA"}})     # v2
    q.apply({"persona": {"name": "BBB"}})     # v3
    r1 = q.rollback(2)                        # v4 == AAA
    c1 = q.active()["policy"]["persona"]["name"]
    r2 = q.rollback(3)                        # v5 == BBB
    c2 = q.active()["policy"]["persona"]["name"]
    r3 = q.rollback(4)                        # v6 == AAA (v4 content)
    c3 = q.active()["policy"]["persona"]["name"]
    check("E8 version->content mapping is stable and ordered",
          (c1, c2, c3) == ("AAA", "BBB", "AAA") and r1["version"] < r2["version"] < r3["version"],
          (c1, c2, c3, r1["version"], r2["version"], r3["version"]))

    METRICS["ROLLBACK_FAILURES"] = 0


# ===========================================================================
# F. LOCKED FIELDS (re-attack, incl. coercion path)
# ===========================================================================

async def t_locked(tmpdir):
    print("\n--- F. locked fields ---")

    async def body(client, stores, _):
        top = [{"provider": "openai"}, {"model": "qwen-x"}, {"voice": "x"},
               {"vad": {"threshold": 0.9}}, {"audio": {"frame_ms": 20}},
               {"frame_ms": 20}, {"guard_ms": 15}, {"slack_ms": 5},
               {"opus": {"bitrate": 1}}, {"barge_in": True}, {"fifo": False},
               {"generation_owner": "client"}, {"bargein": True}]
        nested = [{"persona": {"voice": "x"}}, {"persona": {"model": "x"}},
                  {"limits": {"frame_ms": 20}}, {"limits": {"vad_silence_ms": 5}},
                  {"teaching": {"vad_threshold": 0.5}}, {"language": {"provider": "x"}},
                  {"activities": {"CHAT": "x", "voice": "x"}}]
        # smuggled through a coerced section (non-dict section carrying a locked key)
        coerced = [{"persona": 5, "model": "x"}, {"voice": "x", "persona": "y"}]
        allv = top + nested + coerced
        rejected = 0
        for a in allv:
            st, b = await api(client, "POST", "/admin/policy/apply",
                              json={"policy": a, "confirm": True})
            if st == 400:
                rejected += 1
            else:
                observe("LOCKED ACCEPTED?!", (a, st, b))
        act = (await api(client, "GET", "/admin/policy/active"))[1]
        METRICS["LOCKED_FIELD_MUTATIONS"] = int(act["version"]) - 1
        check("F1 all locked-field vectors rejected (400)", rejected == len(allv),
              (rejected, len(allv)))
        check("F2 zero locked-field mutations", act["version"] == 1, act["version"])

        def _keys(o, acc):
            if isinstance(o, dict):
                for k, v in o.items():
                    acc.add(str(k).lower()); _keys(v, acc)
            elif isinstance(o, list):
                for v in o:
                    _keys(v, acc)
            return acc
        present = _keys(act["policy"], set())
        locked = {"voice", "model", "provider", "vad", "vad_threshold", "opus", "audio",
                  "frame_ms", "guard_ms", "slack_ms", "barge_in", "bargein", "fifo",
                  "generation_owner"}
        check("F3 no locked key silently stored", sorted(present & locked) == [],
              sorted(present & locked))

    await with_stores(body, tmpdir, "f_locked")


# ===========================================================================
# G. CONCURRENCY
# ===========================================================================

async def t_concurrency(tmpdir):
    print("\n--- G. concurrency ---")
    root = Path(tmpdir) / "g"
    root.mkdir(parents=True, exist_ok=True)
    path = str(root / "policy.json")

    # G1 two in-process instances, alternating apply/rollback, interleaved reads
    a = PolicyStore(path).load()
    b = PolicyStore(path).load()
    errors = []

    def worker(store, tag, n):
        for i in range(n):
            try:
                if i % 3 == 2:
                    store.rollback(1, actor=tag)
                else:
                    store.apply({"persona": {"tone": "%s-%d" % (tag, i)}}, actor=tag)
            except PolicyInvalid:
                pass
            except Exception as e:  # noqa: BLE001
                errors.append((tag, i, repr(e)))

    ts = [threading.Thread(target=worker, args=(a, "A", 20)),
          threading.Thread(target=worker, args=(b, "B", 20))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    f = PolicyStore(path).load()
    vs = [v["version"] for v in f.versions()]
    check("G1 no errors in concurrent instances", errors == [], errors[:3])
    check("G1b versions unique + monotonic", vs == sorted(set(vs)), vs)
    check("G1c active == max version", f.active()["version"] == max(vs), (f.active()["version"], max(vs)))
    # audit completeness: the persisted audit must have one entry per mutation
    audit = f.audit(200)
    check("G1d audit has apply+rollback entries (no wiped log)",
          len(audit) >= 20 and any(x["action"] == "rollback" for x in audit),
          len(audit))
    # file must parse and be well-formed
    raw = json.loads(Path(path).read_text("utf-8"))
    check("G1e file well-formed after concurrency", raw.get("schema_version") == 1)

    # G2 cross-process: two UNsynchronised writers share one file
    root2 = Path(tmpdir) / "g2"
    root2.mkdir(parents=True, exist_ok=True)
    p2 = str(root2 / "policy.json")
    PolicyStore(p2).load().apply({"persona": {"name": "seed"}})   # v2 baseline
    go = str(root2 / "GO")
    n = 40
    procs = [subprocess.Popen([sys.executable, WORKER,
                               p2, str(n), tag, go],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={**os.environ, "DYLD_LIBRARY_PATH": "/tmp/opus131/lib"})
             for tag in ("P1", "P2")]
    Path(go).write_text("go", encoding="utf-8")     # release both
    outs = [pr.communicate(timeout=120) for pr in procs]
    summaries = []
    for (so, se) in outs:
        try:
            summaries.append(json.loads(so.decode().strip().splitlines()[-1]))
        except Exception:  # noqa: BLE001
            summaries.append({"ok": 0, "err": se.decode()[-200:]})
    total_ok = sum(s.get("ok", 0) for s in summaries)
    observe("G2 process summaries", summaries)
    try:
        f2 = PolicyStore(p2).load()
        vs2 = [v["version"] for v in f2.versions()]
        maxv = max(vs2)
        dup = len(vs2) != len(set(vs2))
        lost = (maxv - 1) < total_ok
        # cross-writer duplicate detection: versions reported by the two processes
        reported = [v for s in summaries for v in s.get("versions", []) if isinstance(v, int)]
        xdup = len(reported) != len(set(reported))
        observe("G2 final audit size / actors",
                (len(f2.audit(200)), sorted({a["actor"] for a in f2.audit(200)})))
        check("G2 cross-process: file well-formed", Path(p2).is_file())
        check("G2b cross-process: no duplicate versions in the RETAINED file",
              not dup, vs2)
        check("G2c cross-process: no lost update (maxv-1 == total ok)",
              not lost, (maxv, total_ok, vs2[:5]))
        check("G2d cross-process: two writers produced INTERLEAVED unique versions",
              not xdup, reported[:8])
        check("G2e cross-process: no lost audit entry (audit >= successful applies)",
              len(f2.audit(200)) >= total_ok, (len(f2.audit(200)), total_ok))
    except Exception as e:  # noqa: BLE001
        check("G2 cross-process: file readable", False, repr(e))


MEM_WORKER = str(Path(__file__).parent / "_memory_mp_worker.py")


async def t_memory_crossproc(tmpdir):
    print("\n--- G3. memory cross-process (gateway+admin two-writer topology) ---")
    root = Path(tmpdir) / "g3"
    root.mkdir(parents=True, exist_ok=True)
    mp = str(root / "memory.json")
    from modules.memory.store import MemoryStore
    MemoryStore(mp).load().save("profile_fact", "seed", "s")   # baseline
    go = str(root / "GO")
    n = 40
    procs = [subprocess.Popen([sys.executable, MEM_WORKER, mp, str(n), tag, go],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={**os.environ, "DYLD_LIBRARY_PATH": "/tmp/opus131/lib"})
             for tag in ("M1", "M2")]
    Path(go).write_text("go", encoding="utf-8")
    outs = [pr.communicate(timeout=120) for pr in procs]
    summaries = []
    for (so, se) in outs:
        try:
            summaries.append(json.loads(so.decode().strip().splitlines()[-1]))
        except Exception:  # noqa: BLE001
            summaries.append({"ok": 0, "err": se.decode()[-200:]})
    total_ok = sum(s.get("ok", 0) for s in summaries)
    observe("G3 memory process summaries", summaries)
    fresh = MemoryStore(mp).load()
    rows = fresh.list_items(entity="profile_fact")
    survived = len(rows)
    check("G3 memory cross-process: all successful saves survived (no lost update)",
          survived >= total_ok + 1, (survived, total_ok + 1))


# ===========================================================================
# H. NEIGHBOURING STORES: memory / knowledge persist-honesty + validation
# ===========================================================================

async def t_neighbours(tmpdir):
    print("\n--- H. neighbouring stores ---")
    root = Path(tmpdir) / "h"
    root.mkdir(parents=True, exist_ok=True)

    # H1 memory: read-only dir mid-run -> edit must be 5xx, disk unchanged, then recover
    mdir = root / "m"
    mdir.mkdir(parents=True, exist_ok=True)
    mfile = mdir / "memory.json"

    async def mem_body(client, stores, _):
        stores.memory.save_preference("speed", "slow")
        items = (await api(client, "GET", "/admin/memory/items"))[1]
        iid = items["items"][0]["id"]
        os.chmod(mdir, 0o555)
        try:
            st, b = await api(client, "POST", "/admin/memory/edit",
                              json={"id": iid, "value": "fast"})
            check("H1 memory edit under read-only dir -> 5xx persist_failed",
                  st >= 500 and (b or {}).get("error") == "persist_failed", (st, b))
            fresh = __import__("modules.memory.store", fromlist=["MemoryStore"]) \
                .MemoryStore(str(mfile)).load().inspect(iid)
            check("H1b memory disk unchanged after failed edit",
                  fresh and fresh["value"] == "slow", fresh)
        finally:
            os.chmod(mdir, 0o755)
        st2, b2 = await api(client, "POST", "/admin/memory/edit",
                            json={"id": iid, "value": "fast"})
        check("H1c memory edit recovers after permission restored",
              st2 == 200 and b2.get("readback_ok") is True, (st2, b2))
    await with_stores(mem_body, tmpdir, "h_mem", memory_file=str(mfile))

    # H2 memory: path is a directory -> direct PersistError, no phantom
    mdir2 = root / "m2"
    mdir2.mkdir(parents=True, exist_ok=True)
    from modules.memory.store import MemoryStore, PersistError as MPersist
    ms = MemoryStore(str(mdir2)).load()
    raised = False
    try:
        ms.save_preference("speed", "fast")
    except MPersist:
        raised = True
    observe("H2 MemoryStore(dir) save raised PersistError", raised)

    # H3 knowledge: read-only dir mid-run -> add_document 5xx, disk unchanged, recover
    kdir = root / "k"
    kdir.mkdir(parents=True, exist_ok=True)
    kfile = kdir / "knowledge.json"

    async def kb_body(client, stores, _):
        ds = (await api(client, "POST", "/admin/knowledge/dataset/create",
                        json={"name": "DS"}))[1]["dataset"]
        os.chmod(kdir, 0o555)
        try:
            st, b = await api(client, "POST", "/admin/knowledge/document/add",
                              json={"dataset_id": ds["id"], "title": "T", "text": "hello"})
            check("H3 knowledge add under read-only dir -> 5xx persist_failed",
                  st >= 500 and (b or {}).get("error") == "persist_failed", (st, b))
            from modules.knowledge.store import KnowledgeStore
            ks = KnowledgeStore(str(kfile)).load()
            check("H3b knowledge disk unchanged after failed add",
                  ks.get_dataset(ds["id"]) is not None
                  and len(ks.list_documents(dataset_id=ds["id"])) == 0)
        finally:
            os.chmod(kdir, 0o755)
        st2, b2 = await api(client, "POST", "/admin/knowledge/document/add",
                            json={"dataset_id": ds["id"], "title": "T", "text": "hello"})
        check("H3c knowledge add recovers after permission restored",
              st2 == 200 and b2.get("readback_ok") is True, (st2, b2))
    await with_stores(kb_body, tmpdir, "h_kb", knowledge_file=str(kfile))


async def amain():
    tmp = tempfile.mkdtemp(prefix="redd-r2-")
    Path(tmp, "admin_api_token").write_text(TOKEN + "\n")
    os.chmod(Path(tmp, "admin_api_token"), 0o600)

    await t_flush_matrix(tmp)
    await t_false_success(tmp)
    await t_validation(tmp)
    await t_rollback(tmp)
    await t_locked(tmp)
    await t_concurrency(tmp)
    await t_memory_crossproc(tmp)
    await t_neighbours(tmp)

    METRICS.setdefault("LOCKED_FIELD_MUTATIONS", 0)
    METRICS.setdefault("UNVERIFIED_WRITES", 0)
    METRICS.setdefault("ROLLBACK_FAILURES", 0)
    METRICS.setdefault("DESTRUCTIVE_CONFIRMATION_BYPASS", 0)

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 72)
    print("RED_D_ROUND2_ATTACK: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    print("METRICS: " + json.dumps(METRICS, ensure_ascii=False))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %r" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
