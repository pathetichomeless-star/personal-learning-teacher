"""Recon probe: understand aiohttp path normalization + header semantics.

Deterministic, loopback only. Not a product test yet — reconnaissance.
"""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp import web                                  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer     # noqa: E402


async def amain():
    seen = []

    async def guard(request):
        seen.append((request.method, request.path, request.headers.get("Authorization"),
                     request.headers.getall("Authorization", [])))
        return web.json_response({"path": request.path})

    app = web.Application()
    app.router.add_get("/admin/health", guard)
    app.router.add_get("/admin/x/health", guard)
    app.router.add_get("/", guard)

    async with TestClient(TestServer(app)) as c:
        probes = [
            "/admin/health",
            "/admin/health/",
            "//admin/health",
            "/admin//health",
            "/admin/./health",
            "/admin/../admin/health",
            "/admin/%2e%2e/admin/health",
            "/ADMIN/health",
            "/admin/HEALTH",
            "/admin%2fhealth",
            "/admin/health%20",
            "/%61dmin/health",
            "/admin/x/../health",
            "/admin/.../health",
            "/admin/health;x=1",
            "/admin/health?x=1",
            "/../admin/health",
        ]
        for p in probes:
            try:
                r = await c.get(p)
                print("GET %-40s -> %s  body=%s" % (p, r.status, (await r.text())[:80]))
            except Exception as e:
                print("GET %-40s -> EXC %r" % (p, e))

        # method probes on a GET route
        for m in ("HEAD", "OPTIONS", "TRACE", "PUT", "DELETE", "PATCH"):
            try:
                r = await c.request(m, "/admin/health")
                print("%-6s /admin/health -> %s  allow=%s" % (m, r.status,
                                                              r.headers.get("Allow")))
            except Exception as e:
                print("%-6s /admin/health -> EXC %r" % (m, e))

        # duplicate Authorization headers
        r = await c.get("/admin/health", headers=[
            ("Authorization", "Bearer a"), ("Authorization", "Bearer b")])
        print("dup auth ->", r.status)

    print("--- seen (method, path, auth first, all auth) ---")
    for s in seen:
        print(s)


if __name__ == "__main__":
    asyncio.run(amain())
