"""RED-A R3 — bounded probe: can an external holder of <store>.lock wedge the gateway?

The admin store calls are SYNCHRONOUS and run on the single asyncio event loop shared by
the WS/HTTP/admin listeners (main.py). The round-2 fix added a BLOCKING `fcntl.flock(LOCK_EX)`
with no timeout (modules/_store_lock.py). This probe checks whether a second process holding
that flock makes an admin write hang (which would freeze the whole event loop / audio plane).

Three modes, orchestrated by the parent so nothing hangs:
  hold   <memstore>          : flock <memstore>.lock EX, print READY, sleep.
  request <store_dir> <token> <item_id> : issue one authenticated admin write, print latency.
  (default)                  : orchestrator — spawns hold + request, bounded by a timeout.

Local/mock only. No product source touched. Ports: ephemeral TestServer.
"""
import fcntl
import json
import os
import subprocess
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

TOKEN = "RedA_R3_LOCK_Token_DoNotLeak_97531"
FIXED_AUTH = {"Authorization": "Bearer " + TOKEN}


def _hold(memstore):
    lp = str(Path(memstore).resolve()) + ".lock"
    Path(lp).parent.mkdir(parents=True, exist_ok=True)
    fh = open(lp, "a+")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    print("READY", flush=True)
    time.sleep(60)
    os._exit(0)


def _request(store_dir, token_file, item_id):
    import asyncio
    from aiohttp.test_utils import TestClient, TestServer
    from app.admin import load_admin_config
    from app.admin.app import create_admin_app
    from app.admin.auth import TokenStore
    from app.admin.stores import AdminStores

    async def go():
        sd = Path(store_dir)
        cfg = load_admin_config(env={
            "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "9112",
            "ADMIN_API_TOKEN_FILE": str(token_file), "ADMIN_API_TOKEN": "",
            "ADMIN_UI_DIR": str(_REPO / "admin")})
        ts = TokenStore(cfg.token_file, cfg.token_env)
        ts.reload()
        stores = AdminStores(policy_file=str(sd / "policy.json"),
                             memory_file=str(sd / "memory.json"),
                             knowledge_file=str(sd / "knowledge.json"),
                             workbench_url="")
        app = create_admin_app(admin_config=cfg, token_store=ts,
                               gateway_info=lambda: {"mode": "mock", "ready": True},
                               stores=stores)
        async with TestClient(TestServer(app)) as client:
            t0 = time.perf_counter()
            r = await client.post("/admin/memory/edit", headers=FIXED_AUTH,
                                  json={"id": item_id, "value": "x"})
            dt = round((time.perf_counter() - t0) * 1000)
            print("RESULT", r.status, dt, flush=True)

    asyncio.run(go())


def _orchestrate():
    tmp = tempfile.mkdtemp(prefix="red-a-lock-")
    sd = Path(tmp) / "stores"
    sd.mkdir(parents=True, exist_ok=True)
    token_file = Path(tmp) / "admin_api_token"
    token_file.write_text(TOKEN + "\n")
    os.chmod(token_file, 0o600)

    # seed one memory item BEFORE holding the lock
    from modules.memory.store import MemoryStore
    m = MemoryStore(str(sd / "memory.json")).load()
    it = m.save("profile_fact", "name", "小红")
    item_id = it.id

    py = sys.executable
    this = str(Path(__file__).resolve())

    # control: no holder
    p0 = subprocess.run([py, this, "request", str(sd), str(token_file), item_id],
                        capture_output=True, text=True, timeout=30)
    control = p0.stdout.strip().splitlines()[-1] if p0.stdout.strip() else "?"
    print("control (no lock holder):", control)

    # with a holder
    holder = subprocess.Popen([py, this, "hold", str(sd / "memory.json")],
                              stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()          # READY

    req = subprocess.Popen([py, this, "request", str(sd), str(token_file), item_id],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    started = time.time()
    blocked = None
    try:
        req.wait(timeout=6)
        blocked = False
    except subprocess.TimeoutExpired:
        blocked = True
    elapsed = round(time.time() - started, 1)
    if blocked:
        req.kill()
        req.wait()
        print("VERDICT: BLOCKED — admin write did not complete within 6s "
              "while <store>.lock was held by another process (event loop frozen)")
    else:
        print("VERDICT: completed in %.1fs -> %s" % (elapsed, req.stdout.read().strip()))
    holder.kill()
    holder.wait()
    return blocked


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "hold":
        _hold(sys.argv[2])
    elif len(sys.argv) >= 5 and sys.argv[1] == "request":
        _request(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        _orchestrate()
