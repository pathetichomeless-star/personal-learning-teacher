# PRODUCT V1 — PHASE 9/10 DEPLOYMENT RECORD

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 9 NAS 部署 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Isolated Product V1 **test** sidecar on the NAS + Mac client arm.
Prepared 2026-10-08 (Asia/Shanghai). **Temporary, LAN-only, never the primary gateway.**

## Phase 9 — Product V1 test sidecar

| item | value |
|---|---|
| NAS path | `/volume1/docker/xiaozhi-product-v1/` (new) |
| source | canonical Mac source: `gateway/{app,config,tests}` + `modules/` + `admin/`→`admin-ui/` + `deploy/product-sidecar/{Dockerfile,docker-compose.yml,probe_product_v1.py,.dockerignore}` |
| transfer | `tar czf` → pipe (`cat f \| ssh xiaozhi-nas 'cat > /tmp/f'`), sha256 verified on both ends: `9ab66e13b90dd6a18d5bf6121efda069044f7bcd0d72a15fd32c80c110552e38` |
| container | `xiaozhi-product-v1-sidecar` (own compose project + network `xiaozhi-product-v1_default`), `restart: unless-stopped`, `mem_limit 384m`, `cap_drop ALL`, `no-new-privileges` |
| ports | **28310→8110** (WS) · **28311→8111** (HTTP/OTA) · **28312→8112** (admin); verified free before deploy |
| stores (persisted) | `MEMORY_FILE`/`KNOWLEDGE_FILE`/`POLICY_FILE` = `/app/data/*.json` (volume, uid 10001, dir 700) |
| Workbench | `WORKBENCH_BASE_URL=http://192.0.2.1:18100` — GET-only by construction |
| admin | `ADMIN_ENABLED=1`, `ADMIN_UI_DIR=/app/admin-ui`; token **generated on the NAS** (`secrets/product_v1_admin_token`, 64 hex, mode 600, uid 10001) — never printed, never committed |
| Qwen secret | runtime copy from the lab secret (`secrets/qwen-realtime.env`, mode 600, uid 10001); no rotation |
| mode | `QV1_QWEN_MODE` in the NAS-local `.env`: **mock** for machine verification → **real** for the armed state |

### Machine verification (no paid Qwen traffic)

`docker exec xiaozhi-product-v1-sidecar python /app/tests/probe_product_v1.py`

**PRODUCT_V1_STRUCTURAL_PROBE: 65 checks, 65 PASS, 0 FAIL** — health; OTA (28310);
WS hello; full admin auth matrix (anonymous 401 / invalid 401 / valid on all 21 GET +
14 POST routes, six ADMIN-1 routes 200); admin surface absent on the audio app;
no `/admin/diag/reset`; Workbench write verb refused (405); GET on write-only path
refused (405); token absent from every served body; **routing integration with a local
mock Qwen upstream** (client hello + listen-start → the gateway dials the mock → a routed
input-transcription turn → the learner-memory write becomes visible through the ADMIN-2
memory API, i.e. the two-writer reload seam); Memory CRUD (items/inspect/search/edit/
read-back/boundary refusals/delete/diagnostics); Knowledge CRUD + search + provenance +
rebuild + confirmed deletes + diagnostics collapse; Workbench GET-only
(status/current/progress/reviews); persona preview/apply/read-back/rollback + audit.

The same probe was pre-flighted locally (65/65) against a Mac instance of the sidecar
before shipping.

### Isolation evidence (before → after, unchanged)

| container | StartedAt (UTC) | Restarts |
|---|---|---|
| xiaozhi-rtl-bridge (primary realtime) | 2026-10-06T18:41:10Z | 0 |
| english-learning-workbench-web | 2026-10-04T01:56:08Z | 0 |
| english-learning-workbench-sync | 2026-10-05T02:22:46Z | 0 |
| xiaozhi-mvp-sidecar (accepted MVP) | 2026-10-07T16:00:45Z | 0 |
| xiaozhi-product-sidecar (phase-1 mock) | 2026-10-07T10:30:18Z | 0 |
| legacy `xiaozhi-full-*` | 2 days up | 0 |

### Armed state (after switching to real mode)

`status=ok`, `degraded_reasons=[]`, `qwen_connected=0`, `qwen_sessions=0`,
`qwen_dispatch_errors_total=0` — the real provider is configured and ready but **no
upstream session has been opened** (the gateway dials only on a client listen-start or
uplink audio; the real-Qwen budget stays 4/4, remaining 0).

## Phase 10 — Mac client arm

| item | value |
|---|---|
| config | `~/Library/Application Support/py-xiaozhi/config/config.json` |
| backup | `config-backups/config_backup_productv1_arm_20261008_013545.json` |
| SHA256 before | `94b069fa74895c0ec348947a6fbb9794ad87d7b67b29a7ec0aa5c05cf430205e` |
| SHA256 after | `fa61ca44893c270fa393c3e8261e9c81559587c8302afb1f4b0357485f58ea77` |
| changed fields | **exactly one**: `SYSTEM_OPTIONS.NETWORK.OTA_VERSION_URL` `…:28211/xiaozhi/ota/` → `…:28311/xiaozhi/ota/` (1 line removed + 1 added; every other byte identical, including `WEBSOCKET_URL`/`WEBSOCKET_ACCESS_TOKEN`) |
| OTA result | `POST http://192.0.2.1:28311/xiaozhi/ota/` (from the Mac) → `{"websocket": {"url": "ws://192.0.2.1:28310/xiaozhi/v1/", "token": "test-token"}}` |
| WS result | hello-only WS connect from the Mac to `ws://192.0.2.1:28310/xiaozhi/v1/` → `{"type":"hello",…}`; sidecar `qwen_sessions` still **0** afterwards → the check opened **no** upstream session |
| GUI transcript fix | untouched (accepted fix kept) |
| rollback | `cp config-backups/config_backup_productv1_arm_20261008_013545.json "$HOME/Library/Application Support/py-xiaozhi/config/config.json"` then verify sha256 == before |

The client is armed (OTA points at the Product V1 sidecar). The accepted mechanism keeps a
minimal diff: only the OTA URL changes; the client re-consumes OTA and refreshes its own
WS URL/token when the product owner launches it for the single human acceptance.
`py-xiaozhi` was **not** launched by this run.

## Rollback (whole phase)

```bash
ssh xiaozhi-nas 'cd /volume1/docker/xiaozhi-product-v1 && docker compose down && rm -rf /volume1/docker/xiaozhi-product-v1'
cp config-backups/config_backup_productv1_arm_20261008_013545.json "$HOME/Library/Application Support/py-xiaozhi/config/config.json"
```

## Boundaries respected

No internet exposure (LAN only) · no production credential rotated · no Qwen session
opened · primary realtime / Workbench / legacy stack untouched · Workbench write count 0 ·
frozen realtime surfaces untouched (`turns/audio/qwen/ws/protocol/counters` byte-identical
to the pre-run baseline).
