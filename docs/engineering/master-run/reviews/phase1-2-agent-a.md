# Catch-Up Review — Phases 1–2 · AGENT A (ADMIN-1 sidecar / auth / runtime)

Reviewer: AGENT A (read-only) · Date: 2026-10-07 · Repo `<project-root>` @ `5ed3132` (`main`, local-only)
Scope: verify (not redo) Phase-1 NAS sidecar deployment and the ADMIN-1 control plane in the real NAS runtime.
Verdict: **PHASE12_A = PASS** (no real defect found).

## 1. Sidecar runtime (mechanically verified)

| item | observed |
|---|---|
| container | `xiaozhi-product-sidecar` — `State.Status=running`, `Health.Status=healthy` |
| ports | `8110→28110`, `8111→28111`, `8112→28112` (`HostConfig.PortBindings`) |
| env | `ADMIN_ENABLED=1`, `ADMIN_BIND=0.0.0.0`, `ADMIN_PORT=8112`, `ADMIN_API_TOKEN_FILE=/app/secrets/admin_api_token`, `ADMIN_UI_DIR=/app/admin-ui`, `QWEN_MODE=mock` |
| listener log | `admin listener running on 0.0.0.0:8112 (read-only, bearer auth, source=file)` + `admin token material updated (source=file, configured=True)` |
| hardening | `Config.User=10001` (in-container `uid=10001`), `mem_limit=256m`, `no-new-privileges:true` |
| health | in-container `/health` 200; host anonymous `:28112/admin/health` → 401 |

## 2. Token hygiene

- NAS `/volume1/docker/xiaozhi-product-sidecar/secrets/admin_api_token`: `-rw------- 10001 10001` (65 B file).
- SSH user **cannot** read it (`cat` → denied). Confirmed correct hygiene; token never printed anywhere.
- Leak spot-check: token occurrences **in responses = 0** (probe); **in container logs = 0** (`grep -c`, count only — value never printed).

## 3. AUTH-1 verification (in-container probe `probe_admin1.py`)

```
anonymous : [401,401,401,401,401,401]   # health version sessions metrics telemetry diag-summary
invalid   : [401,401,401,401,401,401]
valid     : [200,200,200,200,200,200]
AUTH_MATRIX = PASS
```
- Static console: `GET /` → 200 (text/html, 3359 B), `GET /app.js` → 200 (application/javascript, 9757 B), `/styles.css` → 200.
- `/admin/version` → `image_digest: null`, `image_digest_source: unavailable` (honest).
- `/admin/telemetry` → `{available:false, reason:"server_side_aggregator_unavailable"}` (honest).
- `/admin/diag-summary` → allowlist constructor (`enabled:false` in this run); no transcript / `journal_tail` / raw ids exposed.
- No write/reset surface: `GET /admin/diag/reset` → **404**, `POST/DELETE /admin/health` → **405**, `GET /diag` → **404**.
  Source confirms `app.py` registers **GET only** (six API routes + 5 static); no `add_post/put/delete/patch` anywhere in `gateway/app/admin/`.

## 4. Non-change evidence (primary / others untouched)

| stack | container | StartedAt | Restarts |
|---|---|---|---|
| primary realtime | `xiaozhi-rtl-bridge` | `2026-10-06T18:41:10.230297191Z` | 0 |
| Workbench | `english-learning-workbench-web` | `2026-10-04T01:56:08.229431871Z` | 0 |
| legacy XiaoZhi | `xiaozhi-full-server` | `2026-10-05T14:17:14.15003284Z` | 0 |

All three match the master baseline; no credential rotation. Source default `ADMIN_BIND` remains `127.0.0.1`
(`gateway/app/admin/config.py: DEFAULT_BIND = "127.0.0.1"`); only the temporary sidecar overrides `0.0.0.0`.
`gateway/app/main.py` starts the admin listener only when enabled (default `0` = no third port, audio plane unchanged).

## 5. Deployment source integrity

`deploy/sidecar/{Dockerfile,docker-compose.yml,probe_admin1.py}` contain **no secrets** — token is file-injected at
runtime (`ADMIN_API_TOKEN_FILE` + read-only volume mount). No hex-literal or `ADMIN_API_TOKEN=` value found in
deploy source or `gateway/app/admin`. Files are committed (`c2f657b` phase 0/1, `5ed3132` phase 2).

## Notes (non-blocking, no action for temporary deployment)

- `MASTER-BASELINE.md` records HEAD `71cec08`; current HEAD is `5ed3132` (expected: two phase commits on top). Not a defect.
- `diag-summary` disabled path omits the `resettable` key (returns early); the enabled path sets `resettable: false`. No reset is reachable in either case.
- Documented cosmetic leftover: a probe copy may remain at `/tmp/probe_admin1.py` inside the sidecar (uid 10001 cannot delete a root-copied file); disappears with the container.

**PHASE12_A = PASS**