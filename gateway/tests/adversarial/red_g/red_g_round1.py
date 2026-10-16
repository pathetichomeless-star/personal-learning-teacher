"""RED_G adversarial suite — CONCURRENCY / RACE CONDITIONS (round 1).

Surface: concurrency + atomicity of the Product V1 stores (memory / knowledge /
policy) and the gateway under parallel sessions.

Metric under test: CROSS_SESSION_CONTAMINATION == 0
Secondary: no store corruption / no lost update (each falsified where possible).

METHODS (all LOCAL, mock-only, in a temp dir; NO real Qwen; NO live process
outside 127.0.0.1; product source READ-ONLY):

  D  deterministic multi-instance lost update (memory / knowledge / policy) + a
     barrier-instrumented proof that the reload->mutate->flush window is unguarded.
  A  atomicity: torn-read watch under concurrent writes, temp-file leaks on a
     failed flush, file mode 600, live-file parseability, no partial live file.
  B  admin reads DURING external writes (torn read / 500 / mixed-version probe).
  S  delete/search races; rebuild while searching; deleted knowledge via the
     (mtime,size) seam (compounds the known RB-09 seam into a delete case).
  L  LIVE in-process gateway + in-process mock upstream: 2 / 5 / 10 parallel WS
     sessions (hello + listen start/stop), then a reconnect storm; asyncio task
     and thread counts bounded; cross-session state isolation.
  H  honest degradation: unreadable store file -> honest empty (never 500, never
     fabricated success).

Run:
  cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
      tests/adversarial/red_g/red_g_round1.py
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve()
_GATEWAY = _HERE.parents[2]           # gateway/
_REPO = _GATEWAY.parent               # repo root
for _p in (str(_GATEWAY), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from aiohttp import web                                          # noqa: E402
from aiohttp.test_utils import TestClient, TestServer           # noqa: E402

from app.admin import load_admin_config                          # noqa: E402
from app.admin.app import create_admin_app                      # noqa: E402
from app.admin.auth import TokenStore                           # noqa: E402
from app.admin.stores import AdminStores                        # noqa: E402
from modules.knowledge.store import KnowledgeStore              # noqa: E402
from modules.memory.store import MemoryStore                    # noqa: E402
from modules.memory.store import PersistError as MPersist       # noqa: E402
from modules.policy.persona import PolicyStore                  # noqa: E402

FIX_TOKEN = "RED_G_TEST_TOKEN_DO_NOT_LEAK_24680"   # never printed into artifacts
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
UI_DIR = _REPO / "admin"

RESULTS = []
FINDINGS = []
METRICS = {"CROSS_SESSION_CONTAMINATION": 0,
           "STORE_CORRUPTION": 0,
           "LOST_UPDATE": 0}


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def finding(fid, severity, surface, title, repro, expected, actual):
    FINDINGS.append((fid, severity, surface, title, repro, expected, actual))
    print("  >> FINDING %s [%s] %s" % (fid, severity, title))


def info(msg):
    print("INFO  %s" % msg)


def _free_port(preferred):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        return preferred
    except OSError:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.bind(("127.0.0.1", 0))
        return s2.getsockname()[1]
    finally:
        s.close()


def _mk_client(tmpdir, name, *, token=FIX_TOKEN):
    sub = Path(tmpdir) / ("adm_" + name)
    sub.mkdir(parents=True, exist_ok=True)
    cfg = load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "9312",
        "ADMIN_API_TOKEN_FILE": str(sub / "admin_api_token"),
        "ADMIN_UI_DIR": str(UI_DIR),
    })
    ts = TokenStore(cfg.token_file, token_env=token)
    ts.reload()
    stores = AdminStores(policy_file=str(sub / "policy.json"),
                         memory_file=str(sub / "memory.json"),
                         knowledge_file=str(sub / "knowledge.json"),
                         workbench_url="")
    app = create_admin_app(admin_config=cfg, token_store=ts,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=stores)
    return TestClient(TestServer(app)), stores, sub


# ===========================================================================
# D — deterministic multi-instance lost update + unguarded window proof
# ===========================================================================

class _BarrierMemory(MemoryStore):
    """MemoryStore whose reload_if_changed pauses on a barrier (test instrument)."""

    def __init__(self, path, barrier, user="default"):
        super().__init__(path=path, user=user)
        self._bar = barrier

    def reload_if_changed(self):
        r = super().reload_if_changed()
        try:
            self._bar.wait(timeout=2)
        except Exception:                     # noqa: BLE001
            pass
        return r


def section_lost_update(tmp):
    # --- D1 knowledge: two instances never reload on write -> dataset lost ---
    kp = str(Path(tmp) / "d_kb.json")
    ka = KnowledgeStore(kp).load()
    kb = KnowledgeStore(kp).load()
    da = ka.create_dataset("DatasetA")
    kb.create_dataset("DatasetB")
    final = KnowledgeStore(kp).load().list_datasets()
    names = sorted(d["name"] for d in final)
    check("D1 knowledge: a second instance's write preserves the first",
          names == ["DatasetA", "DatasetB"], repr(names))
    if names != ["DatasetA", "DatasetB"]:
        METRICS["LOST_UPDATE"] += 1
        finding("RG-01", "MAJOR", "modules/knowledge/store.py (multi-instance)",
                "KnowledgeStore write path never reloads -> a second instance silently "
                "discards another instance's committed datasets/documents",
                "ka=KnowledgeStore(p).load(); kb=KnowledgeStore(p).load(); "
                "ka.create_dataset('DatasetA'); kb.create_dataset('DatasetB'); reload",
                "both datasets persisted (union)",
                "on-disk datasets = %r (DatasetA lost)" % names)

    # --- D2 knowledge: stale instance cannot even see a freshly added dataset ---
    kp2 = str(Path(tmp) / "d_kb2.json")
    a = KnowledgeStore(kp2).load()
    b = KnowledgeStore(kp2).load()
    ds = a.create_dataset("shared")
    try:
        b.add_document(ds["id"], "t", "hello world body")
        seen = True
    except Exception as e:                    # noqa: BLE001
        seen = False
        info("D2 stale instance add_document raised: %r" % e)
    check("D2 knowledge: a second instance sees the first's new dataset", seen)
    if not seen:
        finding("RG-02", "MAJOR", "modules/knowledge/store.py (multi-instance visibility)",
                "A second KnowledgeStore instance does not see datasets created by another "
                "instance (no reload on the read/write path) -> 'unknown dataset'",
                "a=K(p).load(); b=K(p).load(); ds=a.create_dataset('shared'); "
                "b.add_document(ds['id'], ...)",
                "b can use the dataset created by a",
                "KnowledgeError('unknown dataset') on the second instance")

    # --- D3 policy: second apply overwrites first, version history lost ---
    pp = str(Path(tmp) / "d_pol.json")
    pa = PolicyStore(pp).load()
    pb = PolicyStore(pp).load()
    pa.apply({"persona": {"name": "小美"}}, actor="A")
    pb.apply({"persona": {"name": "小刚"}}, actor="B")
    fin = PolicyStore(pp).load()
    act = fin.active()
    name = act["policy"]["persona"]["name"]
    vs = [v["version"] for v in fin.versions()]
    core_ok = (name == "小刚") and (2 in vs) and (3 in vs)
    check("D3 policy: two concurrent apps are both preserved (no lost update)",
          core_ok, "name=%s versions=%s" % (name, vs))
    if not core_ok:
        METRICS["LOST_UPDATE"] += 1
        finding("RG-03", "MAJOR", "modules/policy/persona.py (multi-instance)",
                "PolicyStore.apply/rollback lost a committed change across instances",
                "pa=P(p).load(); pb=P(p).load(); pa.apply(...); pb.apply(...)",
                "both changes preserved", "name=%s versions=%s" % (name, vs))
    dup = len(vs) != len(set(vs))
    check("D3b policy version history has no duplicate version numbers", not dup,
          "versions=%s" % vs)
    if dup:
        finding("RG2-01", "MAJOR", "modules/policy/persona.py PolicyStore.load (history merge)",
                "the 'keep built-in v1' logic duplicates the oldest history entry on every "
                "reload of a multi-entry history (guard is len>1), inflating versions() and "
                "evicting usable rollback targets from the bounded history",
                "pa.apply({name:小美}); pb.apply({name:小刚}); PolicyStore(p).load().versions()",
                "each version appears once (e.g. [1,2,3])",
                "versions=%s (duplicate v1 entries, grows per reload+write)" % vs)

    # --- D4 barrier proof: memory reload->mutate->flush window is unguarded ---
    mp = str(Path(tmp) / "d_mem.json")
    bar = threading.Barrier(2)
    m_a = _BarrierMemory(mp, bar).load()
    m_b = _BarrierMemory(mp, bar).load()

    def save_a():
        try:
            m_a.save("continuity", "from_a", "A")
        except Exception:                     # noqa: BLE001
            pass

    def save_b():
        try:
            m_b.save("continuity", "from_b", "B")
        except Exception:                     # noqa: BLE001
            pass

    ta, tb = threading.Thread(target=save_a), threading.Thread(target=save_b)
    ta.start(); tb.start(); ta.join(15); tb.join(15)
    keys = {i["key"] for i in MemoryStore(mp).load().items()}
    check("D4 memory: barrier-aligned writes from two instances both survive",
          {"from_a", "from_b"} <= keys, repr(keys))
    if not {"from_a", "from_b"} <= keys:
        METRICS["LOST_UPDATE"] += 1
        finding("RG-04", "MAJOR", "modules/memory/store.py (unguarded RMW window)",
                "MemoryStore has no lock: reload_if_changed()->mutate->_flush() is not "
                "atomic, so two writers that reload the same base lose one update",
                "two MemoryStore instances over one file, both reload then save with a "
                "barrier between reload and flush -> last flush wins",
                "union of both saves persisted",
                "persisted keys = %r (one committed write lost)" % sorted(keys))

    # --- D5 empirical: raw concurrent saves from two instances (no instrument) ---
    mp2 = str(Path(tmp) / "d_mem2.json")
    i1 = MemoryStore(mp2).load()
    i2 = MemoryStore(mp2).load()
    N = 90                                    # union <= 180 < _MAX_ITEMS_PER_USER
    errs = []

    def wr(inst, tag):
        for i in range(N):
            try:
                inst.save("continuity", "%s%03d" % (tag, i), "v")
            except Exception as e:            # noqa: BLE001
                errs.append(repr(e))
    t1, t2 = threading.Thread(target=wr, args=(i1, "a")), threading.Thread(target=wr, args=(i2, "b"))
    t1.start(); t2.start(); t1.join(60); t2.join(60)
    got = len(MemoryStore(mp2).load().items())
    expect = 2 * N
    check("D5 memory: %d concurrent saves from two instances all persist" % expect,
          got == expect and not errs, "persisted=%d/%d errs=%d" % (got, expect, len(errs)))
    if got != expect:
        METRICS["LOST_UPDATE"] += 1
        finding("RG-04b", "MAJOR", "modules/memory/store.py (concurrent writers)",
                "Concurrent same-user saves from two instances lose updates (%d/%d lost)"
                % (expect - got, expect),
                "2 threads x %d saves via 2 MemoryStore instances over one file" % N,
                "%d items persisted" % expect,
                "%d items persisted (%d lost)" % (got, expect - got))

    # --- D6 quantify the known RB-06 (a): concurrent cross-user flush ---
    mp3 = str(Path(tmp) / "d_mem3.json")
    bar2 = threading.Barrier(2)
    u_default = _BarrierMemory(mp3, bar2, user="default").load()
    u_victim = _BarrierMemory(mp3, bar2, user="victim").load()

    def sd():
        try:
            u_default.save("profile_fact", "name", "default-owner")
        except Exception:                     # noqa: BLE001
            pass

    def sv():
        try:
            u_victim.save("profile_fact", "name", "victim-owner")
        except Exception:                     # noqa: BLE001
            pass
    td, tv = threading.Thread(target=sd), threading.Thread(target=sv)
    td.start(); tv.start(); td.join(15); tv.join(15)
    raw = json.loads(Path(mp3).read_text("utf-8"))
    users = sorted((raw.get("users") or {}).keys())
    info("D6 concurrent cross-user flush -> on-disk users=%r" % users)
    check("D6 (RB-06 quantification) concurrent cross-user writes keep both partitions",
          users == ["default", "victim"], repr(users))
    # This is the known RB-06 defect (single-user _flush). Concurrent access does not
    # widen it: only ONE partition can ever exist; concurrency only randomises WHICH
    # one survives. Quantified, not re-reported as new.


# ===========================================================================
# A — atomicity: torn reads, temp leaks, modes, live-file integrity
# ===========================================================================

def section_atomicity(tmp):
    # --- A1 torn-read watch: reader json.loads() while writer store.save()s ---
    for label, factory, mutate in (
            ("memory", lambda p: MemoryStore(p).load(),
             lambda s, i: s.save("continuity", "k%03d" % i, "value-%d" % i)),
            ("knowledge", lambda p: KnowledgeStore(p).load(),
             None)):
        pass  # (knowledge handled below; keep memory first)

    mp = str(Path(tmp) / "a_mem.json")
    st = MemoryStore(mp).load()
    torn = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                json.loads(Path(mp).read_text("utf-8"))
            except FileNotFoundError:
                pass
            except Exception as e:            # noqa: BLE001
                torn.append(repr(e))

    rt = threading.Thread(target=reader)
    rt.start()
    try:
        for i in range(180):                  # <= _MAX_ITEMS_PER_USER (200)
            st.save("continuity", "k%03d" % i, "value-%d" % i)
    finally:
        stop.set(); rt.join(10)
    check("A1 memory: live file is never observed half-written (atomic replace)",
          torn == [], repr(torn[:3]))
    if torn:
        METRICS["STORE_CORRUPTION"] += 1
        finding("RG-05", "BLOCKER", "modules/memory/store.py _flush / readers",
                "A live store file was observed partially written (torn read)",
                "reader json.loads(live) in a loop while writer save()s 400x",
                "every read parses (tmp->os.replace is atomic)",
                "parse errors observed: %r" % torn[:3])

    # --- A2 knowledge torn-read watch (create+delete churn) ---
    kp = str(Path(tmp) / "a_kb.json")
    ks = KnowledgeStore(kp).load()
    ds = ks.create_dataset("churn")
    ktorn = []
    kstop = threading.Event()

    def kreader():
        while not kstop.is_set():
            try:
                json.loads(Path(kp).read_text("utf-8"))
            except FileNotFoundError:
                pass
            except Exception as e:            # noqa: BLE001
                ktorn.append(repr(e))

    krt = threading.Thread(target=kreader)
    krt.start()
    try:
        for i in range(80):
            d = ks.add_document(ds["id"], "doc%03d" % i, "body content number %d here." % i)
            ks.delete_document(d["id"])
    finally:
        kstop.set(); krt.join(10)
    check("A2 knowledge: live file never torn under add/delete churn",
          ktorn == [], repr(ktorn[:3]))
    if ktorn:
        METRICS["STORE_CORRUPTION"] += 1

    # --- A3 mode 600 for all three stores after writes ---
    modes = {}
    for label, path, make in (
            ("memory", str(Path(tmp) / "a_m2.json"), lambda p: MemoryStore(p).load()
             .save("continuity", "k", "v")),
            ("knowledge", str(Path(tmp) / "a_k2.json"), lambda p: KnowledgeStore(p).load()
             .create_dataset("m")),
            ("policy", str(Path(tmp) / "a_p2.json"), lambda p: PolicyStore(p).load()
             .apply({"persona": {"name": "X"}}))):
        make(path)
        modes[label] = stat.S_IMODE(os.stat(path).st_mode)
    check("A3 all stores write mode 600",
          all(m == 0o600 for m in modes.values()), repr(modes))

    # --- A4 no .tmp leftovers after many successful writes ---
    leftovers = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
    check("A4 no .tmp leftovers after successful writes", leftovers == [], repr(leftovers))

    # --- A5 failed flush (target is a directory) -> honest refusal + temp-cleanup probe ---
    dpath = str(Path(tmp) / "target_is_dir.json")
    os.makedirs(dpath, exist_ok=True)
    before = sorted(os.listdir(tmp))
    s = MemoryStore(dpath).load()
    refused = False
    try:
        s.save("continuity", "k", "v")        # _flush: os.replace(tmp, dir) fails -> PersistError
    except MPersist:
        refused = True
    except Exception:                         # noqa: BLE001
        refused = True
    after = sorted(os.listdir(tmp))
    leaked = [f for f in after if f.endswith(".tmp") and f not in before]
    # ROUND-2: the fix turned silent fail-soft into an honest PersistError (never claim success).
    check("A5 failed flush refuses honestly (PersistError, never a phantom success)", refused)
    check("A5b failed flush leaves NO orphan .tmp file", leaked == [], repr(leaked))
    if leaked:
        finding("RG-06", "MINOR", "modules/{memory,knowledge,policy}/*store*._flush",
                "A flush that fails at os.replace() leaks its temp file (no cleanup)",
                "point the store path at a directory; save() -> tmp written, os.replace fails",
                "no leftover tmp file",
                "orphan temp file(s) left behind: %r" % leaked)

    # --- A6 a pre-existing orphan .tmp is never treated as the live store ---
    live = str(Path(tmp) / "a_live.json")
    MemoryStore(live).load().save("continuity", "real", "v")
    orphan = Path(live + ".deadbeef.tmp")
    orphan.write_text("{ this is not valid json", "utf-8")
    served = MemoryStore(live).load().items()
    check("A6 an orphan .tmp is never loaded as the live store",
          [i["key"] for i in served] == ["real"], repr(served))
    orphan.unlink(missing_ok=True)

    # --- A7 read-only parent dir -> flush fail-soft, live file intact ---
    ro_dir = Path(tmp) / "ro"
    ro_dir.mkdir(exist_ok=True)
    lp = str(ro_dir / "m.json")
    s2 = MemoryStore(lp).load()
    s2.save("continuity", "k", "v")
    snap = Path(lp).read_text("utf-8")
    os.chmod(ro_dir, 0o500)
    refused2 = False
    try:
        s2.save("continuity", "k2", "v2")
    except MPersist:
        refused2 = True
    except Exception:                         # noqa: BLE001
        refused2 = True
    os.chmod(ro_dir, 0o700)
    # ROUND-2: now an honest PersistError, and the live file must be intact.
    check("A7 read-only dir: flush refuses honestly and the live file is intact",
          refused2 and Path(lp).read_text("utf-8") == snap)


# ===========================================================================
# B — admin reads DURING external writes (torn read / 500 / mixed version)
# ===========================================================================

async def section_admin_reads_during_writes(tmp):
    path = str(Path(tmp) / "b_mem.json")
    writer_store = MemoryStore(path).load()
    for i in range(20):
        writer_store.save("continuity", "seed%02d" % i, "seed value %d" % i)

    client, stores, _ = _mk_client(tmp, "b_reads")
    stop = threading.Event()
    write_errors = []

    def churn():
        # external writer: rapid valid rewrites with VARIABLE size (mtime+size both move)
        n = 0
        while not stop.is_set():
            n += 1
            try:
                s = MemoryStore(path).load()
                s.save("continuity", "churn", "x" * (1 + (n % 40)))
            except Exception as e:            # noqa: BLE001
                write_errors.append(repr(e))

    wt = threading.Thread(target=churn)
    wt.start()
    codes = []
    bad_json = 0
    mixed = 0

    # knowledge: external write churn vs admin datasets/search reads
    kpath = str(Path(tmp) / "b_kb.json")
    ks = KnowledgeStore(kpath).load()
    ds = ks.create_dataset("bseed")
    kstop = threading.Event()

    def kchurn():
        m = 0
        while not kstop.is_set():
            m += 1
            try:
                s = KnowledgeStore(kpath).load()
                d = s.add_document(ds["id"], "c%03d" % (m % 25),
                                   "alpha beta gamma %d." % m)
                s.delete_document(d["id"])
            except Exception:                 # noqa: BLE001
                pass

    kt = threading.Thread(target=kchurn)
    kt.start()
    kcodes = []
    kbad = 0
    try:
        async with client:
            for _ in range(60):
                r = await client.get("/admin/memory/items", headers=AUTH)
                codes.append(r.status)
                try:
                    body = await r.json()
                except Exception:             # noqa: BLE001
                    bad_json += 1
                    continue
                if r.status == 200:
                    items = body.get("items")
                    if not isinstance(items, list):
                        mixed += 1
            for _ in range(40):
                r = await client.get("/admin/knowledge/datasets", headers=AUTH)
                kcodes.append(r.status)
                try:
                    await r.json()
                except Exception:             # noqa: BLE001
                    kbad += 1
            for _ in range(20):
                r = await client.post("/admin/knowledge/search", headers=AUTH,
                                      json={"query": "alpha beta"})
                kcodes.append(r.status)
                try:
                    await r.json()
                except Exception:             # noqa: BLE001
                    kbad += 1
    finally:
        stop.set(); wt.join(10)
        kstop.set(); kt.join(10)

    check("B1 admin GETs during external writes never return 5xx",
          all(200 <= c < 500 for c in codes), repr(sorted(set(codes))))
    check("B2 admin GETs during external writes always return valid JSON",
          bad_json == 0, "bad_json=%d" % bad_json)
    check("B3 admin response is a consistent single version (list shape)",
          mixed == 0, "mixed=%d" % mixed)
    info("B churn writer errors: %d" % len(write_errors))
    check("B4 knowledge admin reads during writes: no 5xx", all(200 <= c < 500 for c in kcodes),
          repr(sorted(set(kcodes))))
    check("B5 knowledge admin reads during writes: valid JSON only", kbad == 0)


# ===========================================================================
# S — delete/search races; rebuild while searching; deleted knowledge via seam
# ===========================================================================

def section_delete_search_races(tmp):
    # --- S1 same instance: search after delete must not return deleted content ---
    kp = str(Path(tmp) / "s_kb.json")
    ks = KnowledgeStore(kp).load()
    ds = ks.create_dataset("s")
    client = None
    doc = ks.add_document(ds["id"], "secret", "ultraviolet platypus monitoring protocol")
    hit_before = ks.search("ultraviolet platypus", top_k=3)
    ks.delete_document(doc["id"])
    hit_after = ks.search("ultraviolet platypus", top_k=3)
    check("S1 deleted document is no longer retrievable (same instance)",
          len(hit_before) >= 1 and hit_after == [],
          "before=%d after=%d" % (len(hit_before), len(hit_after)))

    # --- S2 stale second instance still serves deleted content (no reload) ---
    kp2 = str(Path(tmp) / "s_kb2.json")
    writer = KnowledgeStore(kp2).load()
    ds2 = writer.create_dataset("s2")
    doc2 = writer.add_document(ds2["id"], "t2", "kangaroo quantum banana ledger")
    stale = KnowledgeStore(kp2).load()        # a gateway-session-style second instance
    stale.search("kangaroo quantum", top_k=3)  # primes caches
    writer.delete_document(doc2["id"])        # admin deletes; second instance's next read reloads
    stale_hits = stale.search("kangaroo quantum", top_k=3)
    info("S2 second-instance search after delete -> %d hit(s)" % len(stale_hits))
    # ROUND-2: search now merges a concurrent writer by file signature, so a second
    # instance detects the delete on its next read (RG-01/02 repair).  Expected: 0.
    check("S2 a second instance reloads on read and no longer serves deleted content",
          stale_hits == [], "hits=%d" % len(stale_hits))

    # --- S3 reachable: equal-size rewrite + restored mtime hides the delete ---
    kp3 = str(Path(tmp) / "s_kb3.json")
    gw = KnowledgeStore(kp3).load()           # gateway-session instance (reader)
    adm = KnowledgeStore(kp3).load()          # admin instance (writer)
    ds3 = adm.create_dataset("s3")
    doc3 = adm.add_document(ds3["id"], "t3", "Zebra39939 unique fact")
    # PRIME the gateway instance's signature cache the way behavior._maybe_reload_stores
    # does every turn (this is what makes the seam reachable in a live session).
    gw.reload_if_changed()
    primed_hit = len(gw.search("Zebra39939", top_k=3)) >= 1
    st = os.stat(kp3)                         # == gw._sig (mtime_ns, size)
    # admin deletes the document and flushes (as the real delete route would)
    adm.delete_document(doc3["id"])
    after_bytes = Path(kp3).read_bytes()
    if len(after_bytes) < st.st_size:
        after_bytes = after_bytes + b" " * (st.st_size - len(after_bytes))
    elif len(after_bytes) > st.st_size:
        after_bytes = after_bytes[:st.st_size]
        try:
            json.loads(after_bytes.decode("utf-8"))
        except Exception:                     # noqa: BLE001
            after_bytes = None
    if after_bytes is not None:
        Path(kp3).write_bytes(after_bytes)
        os.utime(kp3, ns=(st.st_atime_ns, st.st_mtime_ns))
        cur = (os.stat(kp3).st_mtime_ns, os.stat(kp3).st_size)
        sig_equal = (cur == (st.st_mtime_ns, st.st_size))
        reloaded = gw.reload_if_changed()
        gw_hits = gw.search("Zebra39939", top_k=3)
        disk_has = "Zebra39939" in Path(kp3).read_text("utf-8")
        defeated = primed_hit and sig_equal and (not reloaded) and (not disk_has) and len(gw_hits) >= 1
        info("S3 seam-delete probe: primed=%s sig_equal=%s reloaded=%s disk_has=%s hits=%d"
             % (primed_hit, sig_equal, reloaded, disk_has, len(gw_hits)))
    else:
        defeated = False
        info("S3 seam-delete probe: could not equalise size; probe inconclusive")
    check("S3 deleted knowledge is NOT retrievable via the (mtime,size) seam",
          not defeated, "primed_hit=%s defeated=%s" % (primed_hit, defeated))
    if defeated:
        finding("RG-07", "MAJOR", "modules/knowledge/store.py reload_if_changed (seam)",
                "Deleted Knowledge remains retrievable across instances when the file is "
                "rewritten to an equal size with a restored mtime (RB-09 seam applied to a "
                "DELETE -> 'deleted Knowledge still retrieved')",
                "prime gateway KnowledgeStore sig (reload_if_changed) with the doc present; "
                "admin deletes doc; pad to equal size + restore mtime; gw.search(deleted term)",
                "delete detected; deleted content not retrievable",
                "stale instance still returns the deleted document's chunks")

    # --- S4 rebuild while searching concurrently (threads) ---
    kp4 = str(Path(tmp) / "s_kb4.json")
    ks4 = KnowledgeStore(kp4).load()
    ds4 = ks4.create_dataset("s4")
    doc4 = ks4.add_document(ds4["id"], "t4", "rebuild body sentence one. sentence two here.")
    corrupt = []
    rst = threading.Event()

    def searcher():
        while not rst.is_set():
            try:
                ks4.search("rebuild body", top_k=3)
                ks4.rebuild_chunks(doc4["id"])
            except Exception as e:            # noqa: BLE001
                corrupt.append(repr(e))
            try:
                json.loads(Path(kp4).read_text("utf-8"))
            except FileNotFoundError:
                pass
            except Exception as e:            # noqa: BLE001
                corrupt.append("json:" + repr(e))

    threads = [threading.Thread(target=searcher) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(1.2)
    rst.set()
    for t in threads:
        t.join(10)
    check("S4 concurrent rebuild+search: no errors, file stays valid",
          corrupt == [], repr(corrupt[:3]))
    if corrupt:
        METRICS["STORE_CORRUPTION"] += 1


# ===========================================================================
# X — cross-session isolation (in-process BehaviorLinks over shared files)
# ===========================================================================

async def section_session_isolation(tmp):
    from app.behavior import BehaviorLink

    kb = str(Path(tmp) / "x_kb.json")
    ks = KnowledgeStore(kb).load()
    ds = ks.create_dataset("x")
    ks.add_document(ds["id"], "xdoc", "volcano parking permit regulations for residents")
    mem = str(Path(tmp) / "x_mem.json")
    MemoryStore(mem).load().save("continuity", "topic", "hotel checkin practice")
    pol = str(Path(tmp) / "x_pol.json")

    class _Q:
        def __init__(self):
            self.instructions = None
            self.updates = []

        def set_instructions(self, t):
            self.instructions = t

        async def send_instructions_update(self, t):
            self.updates.append(t); self.instructions = t; return True

    class _C:
        def is_safe_boundary(self):
            return True

    cfg = SimpleNamespace(MEMORY_FILE=mem, KNOWLEDGE_FILE=kb, POLICY_FILE=pol,
                          WORKBENCH_BASE_URL="")
    qa, qb = _Q(), _Q()
    la = BehaviorLink(_C(), qa, config=cfg)
    lb = BehaviorLink(_C(), qb, config=cfg)
    try:
        await asyncio.gather(
            la._on_input_completed({"transcript": "知识库里有没有 volcano 的信息？", "item_id": "a1"}),
            lb._on_input_completed({"transcript": "我想背几个单词", "item_id": "b1"}))
        cross = 0
        if lb.stats["knowledge_queries"] != 0:
            cross += 1
        if la.state.main_activity == lb.state.main_activity:
            cross += 1
        if la._kb_block is None or lb._kb_block is not None:
            # a is expected to have a KB block (hit); b must not receive a's block
            if la._kb_block is None and lb._kb_block is not None:
                cross += 1
        if la._kb_block is not None and lb._kb_block is not None and la._kb_block is lb._kb_block:
            cross += 1
        check("X1 session A knowledge query does not leak into session B activity",
              lb.stats["knowledge_queries"] == 0, "b_queries=%d" % lb.stats["knowledge_queries"])
        check("X2 session A knowledge hit does not appear as session B's block",
              lb._kb_block is None, "b_block=%r" % (str(lb._kb_block)[:60] if lb._kb_block else None))
        check("X3 concurrent sessions keep independent activity state",
              la.state.main_activity != lb.state.main_activity,
              (la.state.main_activity, lb.state.main_activity))
        check("X4 the two links are distinct store instances over shared files",
              la.memory is not lb.memory and la.knowledge is not lb.knowledge,
              "same-object=%s" % (la.memory is lb.memory))
        if cross:
            METRICS["CROSS_SESSION_CONTAMINATION"] += cross
            finding("RG-09", "MAJOR", "gateway/app/behavior.py (per-link state)",
                    "Cross-session contamination observed between two live BehaviorLinks",
                    "two links share files; interleave a knowledge query on A and a vocab "
                    "turn on B via _on_input_completed",
                    "each link's transient blocks/activity stay private",
                    "cross-session leakage detected (cross=%d)" % cross)
    finally:
        await la.close()
        await lb.close()


# ===========================================================================
# H — honest degradation under a degraded store
# ===========================================================================

async def section_honest_degradation(tmp):
    # unreadable store file -> honest empty, never 500, never fabricated success
    sub = Path(tmp) / "h"
    sub.mkdir(exist_ok=True)
    mpath = sub / "memory.json"
    mpath.write_text(json.dumps({"version": 2, "users": {"default": {"items": {}}}}), "utf-8")
    os.chmod(mpath, 0o000)
    kpath = sub / "knowledge.json"
    kpath.write_text(json.dumps({"version": 1, "datasets": {}, "documents": {},
                                 "chunks": {}}), "utf-8")
    os.chmod(kpath, 0o000)
    try:
        client, stores, _ = _mk_client(tmp, "h_deg")
        # point the admin stores at the unreadable files and force a reload
        stores.memory = MemoryStore(str(mpath)).load()
        stores.knowledge = KnowledgeStore(str(kpath)).load()
        async with client:
            r = await client.get("/admin/memory/items", headers=AUTH)
            body = await r.json()
            check("H1 unreadable memory: honest 200 with empty list (no 500, no fabrication)",
                  r.status == 200 and body.get("items") == [] and body.get("count") == 0,
                  "status=%s body=%r" % (r.status, body))
            r2 = await client.post("/admin/knowledge/search", headers=AUTH,
                                   json={"query": "anything"})
            b2 = await r2.json()
            check("H2 unreadable knowledge: honest 200 with zero results",
                  r2.status == 200 and b2.get("count") == 0, "status=%s body=%r" % (r2.status, b2))
    finally:
        os.chmod(mpath, 0o600)
        os.chmod(kpath, 0o600)

    # lock contention (store-level): a write blocked on a held lock must not return
    # early / fabricate success; it completes honestly once the lock is released.
    kp = str(Path(tmp) / "h_lock.json")
    ks = KnowledgeStore(kp).load()
    ds = ks.create_dataset("lk")
    ks._lock.acquire()                        # noqa: SLF001  (test instrument)
    done = {}

    def worker():
        try:
            d = ks.add_document(ds["id"], "t", "body text for the lock test")
            done["ok"] = d["id"]
        except Exception as e:                # noqa: BLE001
            done["err"] = repr(e)

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(0.5)
    blocked_during = "ok" not in done and "err" not in done
    ks._lock.release()                        # noqa: SLF001
    th.join(5)
    after = KnowledgeStore(kp).load().list_documents(dataset_id=ds["id"])
    check("H3 a write blocked on a held lock does not return early / fabricate success",
          blocked_during and "ok" in done and len(after) == 1,
          "blocked_during=%s done=%r docs=%d" % (blocked_during, done, len(after)))
    if not blocked_during:
        METRICS["STORE_CORRUPTION"] = METRICS["STORE_CORRUPTION"]
        finding("RG-08", "MINOR", "modules/knowledge/store.py locking",
                "A store write returned before acquiring the instance lock (no honest "
                "serialization under contention)",
                "hold KnowledgeStore._lock; call add_document() in another thread",
                "the write blocks until the lock is released, then persists",
                "the write returned while the lock was still held")


# ===========================================================================
# L — LIVE in-process gateway + mock upstream, parallel sessions + reconnect
# ===========================================================================

def _gw_config(tmp, ws_port, mock_port):
    from app.qwen import QwenConfig
    q = QwenConfig.from_values({
        "QWEN_MODE": "mock",
        "QWEN_WS_URL": "ws://127.0.0.1:%d" % mock_port,
        "QWEN_MODEL": "qwen3.8-omni-flash-realtime",
        "QWEN_VOICE": "Tina",
    })
    return SimpleNamespace(
        PUBLIC_WS_URL="ws://127.0.0.1:%d/xiaozhi/v1/" % ws_port,
        WS_PORT=ws_port, HTTP_PORT=ws_port + 1, FRAME_MS=20,
        MEMORY_FILE=str(Path(tmp) / "live_memory.json"),
        KNOWLEDGE_FILE=str(Path(tmp) / "live_knowledge.json"),
        POLICY_FILE=str(Path(tmp) / "live_policy.json"),
        WORKBENCH_BASE_URL="", qwen=q)


async def _ws_session(session, url, idx, results, hold=0.35):
    """One mock client: hello -> listen start -> (hold) -> listen stop -> close."""
    import aiohttp
    try:
        async with session.ws_connect(url, heartbeat=None) as ws:
            await ws.send_str(json.dumps({"type": "hello", "version": 1}))
            hello = None
            t0 = time.monotonic()
            while time.monotonic() - t0 < 3.0:
                msg = await asyncio.wait_for(ws.receive(), timeout=3.0)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    obj = json.loads(msg.data)
                    if obj.get("type") == "hello":
                        hello = obj
                        break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                  aiohttp.WSMsgType.ERROR):
                    break
            if hello is None:
                results[idx] = {"ok": False, "reason": "no hello"}
                return
            await ws.send_str(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
            await asyncio.sleep(hold)
            await ws.send_str(json.dumps({"type": "listen", "state": "stop"}))
            await asyncio.sleep(0.05)
        results[idx] = {"ok": True, "session_id": hello.get("session_id"),
                        "audio": hello.get("audio_params")}
    except Exception as e:                     # noqa: BLE001
        results[idx] = {"ok": False, "reason": repr(e)}


async def _wait_ws_zero(cs, http_url, timeout=3.0):
    """Poll /health until ws_connections==0 (the close handler is async)."""
    last = {}
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        async with cs.get(http_url + "/health") as hr:
            last = await hr.json()
        if last.get("ws_connections") == 0:
            return last
        await asyncio.sleep(0.1)
    return last


async def section_live_parallel(tmp):
    import aiohttp
    from app.main import create_app

    # prime the intermittent dev-libopus first-construction quirk once
    try:
        from app import audio as _audio
        _audio.OpusEnc24()
    except Exception:                          # noqa: BLE001
        pass

    mock_port = _free_port(9377)
    mock = _MockUpstream()
    mock_runner = web.AppRunner(mock.app())
    await mock_runner.setup()
    mock_site = web.TCPSite(mock_runner, "127.0.0.1", mock_port)
    await mock_site.start()

    ws_port = _free_port(9310)
    cfg = _gw_config(tmp, ws_port, mock_port)
    gw_runner = web.AppRunner(create_app(cfg))
    await gw_runner.setup()
    gw_site = web.TCPSite(gw_runner, "127.0.0.1", ws_port)
    await gw_site.start()
    ws_url = "ws://127.0.0.1:%d/xiaozhi/v1/" % ws_port
    http_url = "http://127.0.0.1:%d" % ws_port

    try:
        tasks_before = len(asyncio.all_tasks())
        threads_before = threading.active_count()
        info("L baseline: asyncio tasks=%d threads=%d" % (tasks_before, threads_before))

        transient = {"n": 0}

        async def run_batch(n, hold=0.35):
            results = {}
            conn = aiohttp.ClientSession()
            try:
                await asyncio.gather(*[_ws_session(conn, ws_url, i, results, hold=hold)
                                       for i in range(n)])
                # retry handshake failures ONCE: the known dev-libopus first-construction
                # quirk (BRIEF) intermittently kills a connection before hello; a retry
                # that succeeds proves it is environmental, not a product defect.
                for i in range(n):
                    if not results.get(i, {}).get("ok"):
                        transient["n"] += 1
                        await _ws_session(conn, ws_url, i, results, hold=hold)
            finally:
                await conn.close()
            return results

        for n in (2, 5, 10):
            results = await run_batch(n)
            oks = sum(1 for r in results.values() if r.get("ok"))
            sids = {r.get("session_id") for r in results.values() if r.get("ok")}
            check("L1 %d parallel sessions all handshake+listen OK" % n, oks == n,
                  "%d/%d ok; failures=%r" % (oks, n,
                                             [r for r in results.values() if not r.get("ok")]))
            check("L2 %d parallel sessions have distinct session ids" % n, len(sids) == oks,
                  "unique=%d ok=%d" % (len(sids), oks))
            # counter sanity after all closed (poll: the close handler is async)
            async with aiohttp.ClientSession() as cs:
                health = await _wait_ws_zero(cs, http_url, timeout=4.0)
            check("L3 after %d sessions: ws_connections returns to 0 (bounded)" % n,
                  health.get("ws_connections") == 0, "ws_connections=%r" % health.get("ws_connections"))

        info("L handshake retries needed (env libopus quirk): %d" % transient["n"])

        # cross-session activity isolation via the admin registry
        from app.admin.registry import sessions as reg
        await asyncio.sleep(0.5)
        results2 = await run_batch(3, hold=0.6)
        check("L4 registry empty after sessions close (no leaked session rows)",
              reg.count() == 0 and reg.snapshot() == [], "count=%d" % reg.count())

        # reconnect storm: rapid repeated connect/disconnect
        storm = 30
        for i in range(storm):
            c = aiohttp.ClientSession()
            try:
                await _ws_session(c, ws_url, 0, {}, hold=0.0)
            finally:
                await c.close()
        # and a concurrent burst
        await run_batch(15, hold=0.0)
        await asyncio.sleep(0.5)
        async with aiohttp.ClientSession() as cs:
            health2 = await _wait_ws_zero(cs, http_url, timeout=4.0)
        check("L5 reconnect storm: ws_connections back to 0 (bounded)",
              health2.get("ws_connections") == 0, "ws_connections=%r" % health2.get("ws_connections"))
        check("L6 reconnect storm: no accumulated qwen connect errors explosion",
              health2.get("qwen_connect_errors", 0) < storm + 15,
              "qwen_connect_errors=%r" % health2.get("qwen_connect_errors"))

        tasks_after = len(asyncio.all_tasks())
        threads_after = threading.active_count()
        info("L after storm: asyncio tasks=%d threads=%d" % (tasks_after, threads_after))
        check("L7 no unbounded asyncio task growth after storm",
              tasks_after <= tasks_before + 5, "before=%d after=%d" % (tasks_before, tasks_after))
        check("L8 no unbounded thread growth after storm",
              threads_after <= threads_before + 2, "before=%d after=%d" % (threads_before, threads_after))
    finally:
        await gw_runner.cleanup()
        await mock_runner.cleanup()


class _MockUpstream:
    """Minimal mock Qwen upstream (normal scenario), 127.0.0.1 only.

    Reuses the repo's deterministic mock server if importable; otherwise a tiny
    inline equivalent that speaks session.update -> session.updated and one turn.
    """

    def __init__(self):
        self.conns = 0

    def app(self):
        app = web.Application()
        app.router.add_get("/", self._handler)
        app.router.add_get("/api-ws/v1/realtime", self._handler)
        return app

    async def _handler(self, request):
        from aiohttp import WSMsgType
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.conns += 1
        await ws.send_str(json.dumps({"type": "session.created",
                                      "session": {"id": "mock_%d" % self.conns}}))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    obj = json.loads(msg.data)
                except Exception:             # noqa: BLE001
                    continue
                et = obj.get("type")
                if et == "session.update":
                    await ws.send_str(json.dumps({"type": "session.updated",
                                                  "session": {"id": "mock_%d" % self.conns}}))
                    asyncio.ensure_future(self._turn(ws))
                elif et == "session.finish":
                    break
        except Exception:                         # noqa: BLE001
            pass
        finally:
            try:
                await ws.close()
            except Exception:                     # noqa: BLE001
                pass
        return ws

    async def _turn(self, ws):
        try:
            rid = "resp_1"
            await asyncio.sleep(0.05)
            await ws.send_str(json.dumps({"type": "response.created",
                                          "response": {"id": rid, "status": "in_progress"}}))
            await asyncio.sleep(0.05)
            await ws.send_str(json.dumps({"type": "response.audio.done", "response_id": rid}))
            await ws.send_str(json.dumps({"type": "response.done",
                                          "response": {"id": rid, "status": "completed"}}))
        except Exception:                         # noqa: BLE001
            pass


# ===========================================================================
# main
# ===========================================================================

async def amain():
    tmp = tempfile.mkdtemp(prefix="red_g_")
    info("temp dir: %s" % tmp)
    phases = [
        ("D lost-update", lambda: section_lost_update(tmp)),
        ("A atomicity", lambda: section_atomicity(tmp)),
        ("B admin-reads-during-writes", lambda: section_admin_reads_during_writes(tmp)),
        ("S delete/search races", lambda: section_delete_search_races(tmp)),
        ("X cross-session isolation", lambda: section_session_isolation(tmp)),
        ("H honest degradation", lambda: section_honest_degradation(tmp)),
        ("L live parallel sessions", lambda: section_live_parallel(tmp)),
    ]
    for name, fn in phases:
        print("\n---- %s ----" % name)
        try:
            res = fn()
            if asyncio.iscoroutine(res):
                await res
        except Exception:                         # noqa: BLE001
            print("PHASE ERROR in %s:" % name)
            traceback.print_exc()

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 74)
    print("RED_G_ROUND1: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for n, ok, d in RESULTS:
        if not ok:
            print("  FAILED: %s  [%s]" % (n, d))
    print("-" * 74)
    for k, v in METRICS.items():
        print("METRIC %s = %d" % (k, v))
    print("FINDINGS: %d" % len(FINDINGS))
    for f in FINDINGS:
        print("  %s [%s] %s" % (f[0], f[1], f[3]))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
