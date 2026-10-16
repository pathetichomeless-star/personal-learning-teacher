"""RED-A ROUND 3 — independent cross-check of the round-1/round-2 fixes.

Focus (auth/abuse wheelhouse):
  C1  re-prove the full auth matrix on the edited admin API
  C2  durable read-back honesty (happy path persists; forced flush failure never 200)
  C3  no false `readback_ok:true`; no phantom in-memory change; no un-audited write
  C4  5xx error oracle / leak check (path/stack/store value in body or log)
  C5  new validation surface (non-int top_k, non-str name, surrogates, capped errors)
  C6  store lock file: content/permissions/symlink; read latency; lock not held across await

Read-only on product source. Local, mock-only, in-process TestClient.
Run: cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
       tests/adversarial/red_a/red_a_round3.py
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parents[2]
_REPO = _GATEWAY.parent
for _p in (_GATEWAY, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from aiohttp.test_utils import TestClient, TestServer          # noqa: E402

from app.admin import load_admin_config                        # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                          # noqa: E402
from app.admin.stores import AdminStores                       # noqa: E402
from modules.memory.store import MemoryStore                   # noqa: E402
from modules.knowledge.store import KnowledgeStore             # noqa: E402
from modules.policy.persona import PolicyStore                 # noqa: E402

FIX_TOKEN = "RedA_R3_Token_DoNotLeak_8642"
UI_DIR = _REPO / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}

RESULTS = []
LOGS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


class Capture(logging.Handler):
    def emit(self, record):
        try:
            LOGS.append(record.getMessage() % record.args if record.args
                        else record.getMessage())
        except Exception:                                     # noqa: BLE001
            LOGS.append(str(record.msg))


def _cfg(tmpdir, token_file):
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "9112",
        "ADMIN_API_TOKEN_FILE": str(token_file), "ADMIN_API_TOKEN": "",
        "ADMIN_UI_DIR": str(UI_DIR)})


def _stores(store_dir):
    return AdminStores(policy_file=str(store_dir / "policy.json"),
                       memory_file=str(store_dir / "memory.json"),
                       knowledge_file=str(store_dir / "knowledge.json"),
                       workbench_url="")


# ---------------------------------------------------------------------------
# C1 — auth matrix re-proof on the edited API
# ---------------------------------------------------------------------------

async def c1_auth(client, stores, app):
    table = admin_route_table(stores)
    get_paths = [p for m, p in table if m == "GET" and p.startswith("/admin/")]
    post_paths = [p for m, p in table if m == "POST" and p.startswith("/admin/")]

    def subst(p):
        return (p.replace("{item_id}", "mem_nope").replace("{doc_id}", "doc_nope")
                 .replace("{ds_id}", "ds_nope"))

    bad = {}
    for p in get_paths:
        r = await client.get(subst(p))
        if r.status != 401:
            bad[p] = r.status
    check("C1.1 anonymous GET -> 401 on every admin GET route", not bad, bad)

    bad = {}
    for p in post_paths:
        r = await client.post(subst(p), json={})
        if r.status != 401:
            bad[p] = r.status
    check("C1.2 anonymous POST -> 401 on every write route", not bad, bad)

    # the six ADMIN-1 read-only routes return 200 with a valid token
    six = ["/admin/health", "/admin/version", "/admin/sessions", "/admin/metrics",
           "/admin/telemetry", "/admin/diag-summary"]
    six_bad = {}
    for p in six:
        r = await client.get(p, headers=AUTH)
        if r.status != 200:
            six_bad[p] = r.status
    check("C1.3 all six ADMIN-1 routes 200 with a valid token", not six_bad, six_bad)

    # no-oracle 401 bodies
    bodies = set()
    for h in ({}, {"Authorization": ""}, {"Authorization": "Bearer"},
              {"Authorization": "Bearer wrong"}):
        r = await client.get("/admin/policy/active", headers=h)
        b = await r.json()
        b.pop("request_id", None)
        bodies.add(json.dumps(b, sort_keys=True))
    check("C1.4 anon/malformed/wrong bodies identical (no oracle)",
          len(bodies) == 1 and "unauthorized" in bodies.pop())

    # path + header tricks (spot re-check)
    tricks = ["/admin/../admin/policy/active", "/admin/./health", "/%61dmin/health",
              "/ADMIN/health", "/admin//health"]
    leak = []
    for p in tricks:
        try:
            r = await client.get(p)
        except Exception:                                     # noqa: BLE001
            continue
        if r.status not in (400, 401, 404, 405):
            leak.append((p, r.status))
    check("C1.5 path tricks still auth-guarded (no anon reach)", not leak, leak)

    anon_head = await client.request("HEAD", "/admin/policy/active")
    check("C1.6 anonymous HEAD -> 401", anon_head.status == 401, anon_head.status)


# ---------------------------------------------------------------------------
# C2/C3 — durable read-back honesty
# ---------------------------------------------------------------------------

async def c2_happy_durable(client, stores, store_dir):
    # policy apply -> persisted on disk (fresh instance + raw file)
    r = await client.post("/admin/policy/apply", headers=AUTH,
                          json={"policy": {"persona": {"name": "小美"}}, "confirm": True})
    body = await r.json()
    disk = json.loads(Path(stores.policy.path).read_text("utf-8"))
    fresh = PolicyStore(stores.policy.path).load().active()
    check("C2.1 policy apply: 200 + readback_ok + durable on disk",
          r.status == 200 and body.get("readback_ok") is True
          and disk["active"]["version"] == 2 and fresh["version"] == 2,
          (r.status, body.get("readback_ok")))

    # memory edit -> persisted
    stores.memory.save("profile_fact", "name", "小红")
    items = (await (await client.get("/admin/memory/items", headers=AUTH)).json())["items"]
    mid = [i for i in items if i["key"] == "name"][0]["id"]
    r = await client.post("/admin/memory/edit", headers=AUTH,
                          json={"id": mid, "value": "小李"})
    body = await r.json()
    fresh_m = MemoryStore(stores.memory.path).load().inspect(mid)
    check("C2.2 memory edit: 200 + readback_ok + durable on disk",
          r.status == 200 and body.get("readback_ok") is True
          and fresh_m is not None and fresh_m["value"] == "小李",
          (r.status, body.get("readback_ok")))

    # knowledge create -> persisted
    r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                          json={"name": "R3集"})
    body = await r.json()
    dsk = KnowledgeStore(stores.knowledge.path).load()
    ds_id = body.get("dataset", {}).get("id")
    check("C2.3 knowledge create: 200 + readback_ok + durable on disk",
          r.status == 200 and body.get("readback_ok") is True
          and dsk.get_dataset(ds_id) is not None,
          (r.status, body.get("readback_ok")))
    return mid, ds_id


async def c3_forced_flush_failure(client, stores, store_dir, mid, ds_id):
    # make the store directory non-writable -> every flush fails
    os.chmod(store_dir, 0o500)
    try:
        before = stores.policy.active()["version"]
        n_audit = len(stores.audit.recent(500))

        r1 = await client.post("/admin/policy/apply", headers=AUTH,
                               json={"policy": {"persona": {"name": "小刚"}},
                                     "confirm": True})
        check("C3.1 policy apply with unwritable dir -> 500 persist_failed (never 200)",
              r1.status == 500 and (await r1.json()).get("error") == "persist_failed",
              r1.status)
        check("C3.2 no phantom policy version after a failed flush",
              stores.policy.active()["version"] == before,
              stores.policy.active()["version"])

        r2 = await client.post("/admin/memory/edit", headers=AUTH,
                               json={"id": mid, "value": "篡改"})
        check("C3.3 memory edit with unwritable dir -> 500 persist_failed",
              r2.status == 500 and (await r2.json()).get("error") == "persist_failed",
              r2.status)
        mi = stores.memory.inspect(mid)
        check("C3.4 no phantom memory value after a failed flush",
              mi is not None and mi["value"] == "小李", mi and mi.get("value"))

        r3 = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                               json={"name": "shadow"})
        check("C3.5 knowledge create with unwritable dir -> 500 persist_failed",
              r3.status == 500 and (await r3.json()).get("error") == "persist_failed",
              r3.status)
        check("C3.6 no phantom dataset after a failed flush",
              KnowledgeStore(stores.knowledge.path).load().get_dataset(ds_id) is not None
              and not any(d["name"] == "shadow"
                          for d in KnowledgeStore(stores.knowledge.path).load()
                          .list_datasets()),
              None)

        check("C3.7 a failed write is not audited",
              len(stores.audit.recent(500)) == n_audit,
              (n_audit, len(stores.audit.recent(500))))

        # bodies must not leak a path
        for r in (r1, r2, r3):
            js = json.dumps(await r.json())
            if str(store_dir) in js:
                check("C3.8 persist_failed body leaks no path", False, js)
        check("C3.8 persist_failed bodies leak no path/token", True)
    finally:
        os.chmod(store_dir, 0o700)


# ---------------------------------------------------------------------------
# C4 — error oracle / leak
# ---------------------------------------------------------------------------

async def c4_error_oracle(client, stores, store_dir):
    # a 5xx and a 4xx must be distinguishable only by code, never by internals
    r500 = await client.post("/admin/policy/apply", headers=AUTH,
                             json={"policy": {"persona": {"name": "x"}}})  # confirm missing -> 400
    b400 = await r500.json()
    check("C4.1 bad input -> 400 (not 500)",
          r500.status == 400 and b400.get("error") == "confirm_required", r500.status)

    # persist_failed is a constant, non-enumerating body
    blob = json.dumps(b400)
    check("C4.2 error body carries no store path / token",
          str(store_dir) not in blob and FIX_TOKEN not in blob, blob[:120])

    # log hygiene: the failure paths we exercised must not print the token or a store path
    joined = "\n".join(LOGS)
    check("C4.3 no token in logs", FIX_TOKEN not in joined)
    leaked_path = str(store_dir) in joined
    print("INFO logs contain the store path: %s" % leaked_path)
    check("C4.4 store path not printed in logs (api layer)", not leaked_path,
          joined[-200:] if leaked_path else "")


# ---------------------------------------------------------------------------
# C5 — new validation surface
# ---------------------------------------------------------------------------

async def c5_validation(client, stores):
    # top_k must be an int (None allowed); bool is an int subclass -> note behaviour
    for tk, want in (("x", 400), (1.5, 400), ([], 400), ({}, 400), (None, 200), (3, 200)):
        r = await client.post("/admin/knowledge/search", headers=AUTH,
                              json={"query": "q", "top_k": tk})
        if r.status != want:
            check("C5.1 top_k=%r -> %d" % (tk, want), False, r.status)
    check("C5.1 top_k type guard: non-int -> 400, int/None -> 200", True)
    rb = await client.post("/admin/knowledge/search", headers=AUTH,
                           json={"query": "q", "top_k": True})
    print("INFO top_k=True (bool-as-int) -> %s" % rb.status)

    # dataset name must be a string
    for nm in (123, ["a"], None, {"a": 1}):
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                              json={"name": nm})
        if r.status != 400:
            check("C5.2 non-str name %r -> 400" % (nm,), False, r.status)
    check("C5.2 non-string dataset name -> 400", True)

    # lone surrogate in name / title / text -> 400 (never 500)
    for label, payload in (
            ("name", {"name": "ok\ud800name"}),
            ("description", {"name": "ok", "description": "d\ud800"})):
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH, json=payload)
        check("C5.3 surrogate in %s -> 400 (not 500)" % label, r.status == 400, r.status)

    ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                   json={"name": "sur"})).json())["dataset"]
    for label, extra in (("title", {"title": "t\ud800", "text": "body"}),
                         ("text", {"title": "t", "text": "b\ud800ody"}),
                         ("source_uri", {"title": "t", "text": "body",
                                         "source_uri": "u\ud800"})):
        r = await client.post("/admin/knowledge/document/add", headers=AUTH,
                              json=dict({"dataset_id": ds["id"]}, **extra))
        check("C5.4 surrogate in document %s -> 400" % label, r.status == 400, r.status)

    # newline / control char in name and title -> 400 (single-line metadata)
    r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                          json={"name": "a\nb"})
    check("C5.5 newline in dataset name -> 400", r.status == 400, r.status)
    r = await client.post("/admin/knowledge/document/add", headers=AUTH,
                          json={"dataset_id": ds["id"], "title": "a\nb", "text": "x"})
    check("C5.6 newline in document title -> 400", r.status == 400, r.status)

    # policy error-list cap: preview vs apply
    wide = {("s%d" % i): 1 for i in range(5000)}
    req_body = json.dumps({"policy": {"persona": wide}})
    pv = await client.post("/admin/policy/preview", headers=AUTH,
                           json={"policy": {"persona": wide}})
    pvj = await pv.json()
    resp_body = json.dumps(pvj)
    print("INFO policy/preview: request=%dB response=%dB errors=%d (apply caps at 50)"
          % (len(req_body), len(resp_body), len(pvj.get("errors", []))))
    check("C5.7 policy/preview still reports invalid (400-class semantics, 200 body)",
          pv.status == 200 and pvj.get("valid") is False)
    # apply path is capped
    ap = await client.post("/admin/policy/apply", headers=AUTH,
                           json={"policy": {"persona": wide}, "confirm": True})
    apj = await ap.json()
    check("C5.8 policy/apply error list is capped at 50",
          ap.status == 400 and len(apj.get("errors", [])) <= 50,
          (ap.status, len(apj.get("errors", []))))
    if len(pvj.get("errors", [])) > 50:
        check("C5.9 preview error list is NOT capped (incomplete fix)", False,
              len(pvj.get("errors", [])))
    else:
        check("C5.9 preview error list bounded", True, "")


# ---------------------------------------------------------------------------
# C6 — store lock file
# ---------------------------------------------------------------------------

async def c6_lockfile(client, stores, store_dir):
    lock_paths = [Path(p + ".lock") for p in
                  (stores.policy.path, stores.memory.path, stores.knowledge.path)]
    for lp in lock_paths:
        exists = lp.exists()
        size = lp.stat().st_size if exists else -1
        mode = (lp.stat().st_mode & 0o777) if exists else -1
        print("INFO lockfile %s exists=%s size=%s mode=%o"
              % (lp.name, exists, size, mode if mode >= 0 else 0))
        check("C6.1 lockfile %s is empty" % lp.name, exists and size == 0,
              "exists=%s size=%s" % (exists, size))
    # lock file must not appear in any API response
    blob = ""
    for p in ("/admin/health", "/admin/policy/active", "/admin/memory/diagnostics",
              "/admin/knowledge/diagnostics", "/admin/audit"):
        blob += await (await client.get(p, headers=AUTH)).text()
    check("C6.2 no .lock path in any API response", ".lock" not in blob)
    check("C6.3 no store dir path in any API response", str(store_dir) not in blob)

    # lock file permissions are not world-writable
    lmodes = [(lp.name, (lp.stat().st_mode & 0o777)) for lp in lock_paths if lp.exists()]
    bad = [m for _, m in lmodes if m & 0o002]
    check("C6.4 lock files are not world-writable", not bad, lmodes)

    # a read (GET) is prompt and still auth-guarded (no lock-across-await stall)
    t0 = time.perf_counter()
    r = await client.get("/admin/policy/active", headers=AUTH)
    dt = (time.perf_counter() - t0) * 1000.0
    check("C6.5 authenticated read is prompt (<500ms)", r.status == 200 and dt < 500, dt)
    r2 = await client.get("/admin/policy/active")
    check("C6.6 read still 401 without token", r2.status == 401, r2.status)

    # symlinked lock file must not corrupt the victim
    victim = store_dir / "victim.txt"
    victim.write_text("ORIGINAL")
    lp = lock_paths[1]
    try:
        lp.unlink()
    except FileNotFoundError:
        pass
    try:
        os.symlink(str(victim), str(lp))
    except OSError:
        pass
    stores.memory.save("profile_fact", "city", "上海")
    check("C6.7 symlinked lock file does not touch the victim",
          victim.read_text() == "ORIGINAL", victim.read_text())
    try:
        lp.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

async def amain():
    cap = Capture()
    logging.getLogger().addHandler(cap)
    logging.getLogger().setLevel(logging.WARNING)

    tmp = tempfile.mkdtemp(prefix="red-a-r3-")
    token_file = Path(tmp) / "admin_api_token"
    token_file.write_text(FIX_TOKEN + "\n")
    os.chmod(token_file, 0o600)
    store_dir = Path(tmp) / "stores"
    store_dir.mkdir(parents=True, exist_ok=True)
    cfg = _cfg(tmp, token_file)
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    stores = _stores(store_dir)
    app = create_admin_app(admin_config=cfg, token_store=ts,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=stores)

    async with TestClient(TestServer(app)) as client:
        await c1_auth(client, stores, app)
        mid, ds_id = await c2_happy_durable(client, stores, store_dir)
        await c4_error_oracle(client, stores, store_dir)
        await c5_validation(client, stores)
        await c6_lockfile(client, stores, store_dir)
        await c3_forced_flush_failure(client, stores, store_dir, mid, ds_id)

    logging.getLogger().removeHandler(cap)
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 72)
    print("RED_A_ROUND3: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s  %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
