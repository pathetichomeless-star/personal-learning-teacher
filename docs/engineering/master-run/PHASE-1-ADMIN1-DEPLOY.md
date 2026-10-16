# PHASE 1 — ADMIN-1 NAS SIDECAR DEPLOYMENT

Deployed: 2026-10-07 18:29–18:32 CST · **temporary sidecar only** — the primary realtime instance was not
modified or restarted, and no production credential was rotated.

## Deployment

| item | value |
|---|---|
| NAS path | `/volume1/docker/xiaozhi-product-sidecar/` (new; contains `app/ config/ tests/ admin-ui/ Dockerfile docker-compose.yml secrets/`) |
| source | canonical Mac source: `gateway/{app,config,tests}` + `admin/` → `admin-ui/`, plus `deploy/sidecar/{Dockerfile,docker-compose.yml,probe_admin1.py}` |
| container | `xiaozhi-product-sidecar` (build from that dir), image `sha256:321b1068cf39…b21848`, `Running=true`, `Health=healthy` |
| ports | **28110→8110** (WS) · **28111→8111** (HTTP/OTA) · **28112→8112** (admin); 28110–28112 were verified free |
| mode | `QWEN_MODE=mock` in this phase (credential-free; **no paid Qwen traffic**) |
| admin | `ADMIN_ENABLED=1`, `ADMIN_BIND=0.0.0.0` **inside this temporary container only** (the source default stays `127.0.0.1`), `ADMIN_PORT=8112`, `ADMIN_UI_DIR=/app/admin-ui` |
| token | fresh 64-hex runtime secret generated **on the NAS**, file-injected read-only, `-rw------- 1 10001 10001` (mirrors the lab precedent); never committed, never printed, never reused from Qwen/DB credentials |
| permissions note | first start failed closed (`ADMIN_ENABLED=1 but no token configured`) because the host-owned file was unreadable by uid 10001 → fixed by `chown 10001:10001` via a root scratch container (no sudo needed); this is the documented fail-closed behaviour working as designed |

## Verification (probe executed **inside** the container, so the token never left it)

`deploy/sidecar/probe_admin1.py` → `AUTH_MATRIX = PASS`

```
anonymous : [401, 401, 401, 401, 401, 401]      (health version sessions metrics telemetry diag-summary)
invalid   : [401, 401, 401, 401, 401, 401]
valid     : [200, 200, 200, 200, 200, 200]
health    : status ok · gateway_version r1f-rev9+admin1 · qwen_mode mock · qwen_ready True · ws_connections 0
            admin {enabled True, bind 0.0.0.0, port 8112, auth_configured True, listener running}
version   : version r1f-rev9+admin1 · schema_version a14 · image_digest null · image_digest_source unavailable
telemetry : {available false, reason server_side_aggregator_unavailable}
sessions  : {available true, count 0}
diag-summary: {available true, enabled false (RTL_DIAG unset), capture {enabled false}}
metrics   : whitelist keys + closures {source 0, framer 0, disposition 0}
token occurrences in responses: 0
token occurrences in container logs: 0   (count computed in a scratch container; token never printed)
static console: GET / → 200 (3359 B, contains the shell), GET /app.js → 200
audio app (mock): GET :28111/health → 200
```

## Non-change evidence

| stack | evidence |
|---|---|
| primary realtime (`xiaozhi-rtl-bridge`) | `StartedAt=2026-10-06T18:41:10.230297191Z`, `Restarts=0` (byte-identical to the master baseline) |
| Workbench (`english-learning-workbench-web`) | `StartedAt=2026-10-04T01:56:08.229431871Z`, `Restarts=0` |
| legacy XiaoZhi (`xiaozhi-full-server`) | `StartedAt=2026-10-05T14:17:14.15003284Z`, `Restarts=0` |
| credentials | none rotated; the sidecar token is a new temporary secret; Qwen/DB credentials untouched |

## Notes / dispositions

- One probe copy remains at `/tmp/probe_admin1.py` **inside the sidecar container** (uid 10001 cannot delete a
  root-copied file; the file contains no secrets). It disappears with the sidecar; future probes should be copied
  to `/app/tests/` instead. MINOR, no action needed for this temporary deployment.
- This deployment is **not promoted**; Phase 12 builds the combined product sidecar (real Qwen + behavior/memory/
  knowledge/workbench) and Phase 13 stops for human acceptance.

**PHASE 1 = PASS → continue to Phase 2 (CLIENT-UI-1).**