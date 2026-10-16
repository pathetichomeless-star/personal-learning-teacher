# PHASE — CONVERSATIONAL MVP NAS TEST SIDECAR + MAC CLIENT ARM

Deployed: 2026-10-07 23:0x–23:15 CST · **temporary test sidecar only.** The primary realtime
instance (`xiaozhi-rtl-bridge`), the workbench stack and the phase-1 product sidecar were not
modified or restarted.

## Deployment

| item | value |
|---|---|
| NAS path | `/volume1/docker/xiaozhi-mvp-sidecar/` (new; `app/ modules/ config/ tests/ admin-ui/ Dockerfile docker-compose.yml secrets/ data/`) |
| source | canonical Mac source: `gateway/{app,config,tests}` + `modules/` + `admin/`→`admin-ui/` + `deploy/mvp-sidecar/*` |
| container | `xiaozhi-mvp-sidecar` (built from that dir), `Running=true`, `Health=healthy` |
| ports | **28210→8110** (WS) · **28211→8111** (HTTP/OTA) · **28212→8112** (admin); verified free first |
| mode | `QWEN_MODE=real` (runtime secret copied from the lab secret dir via a root scratch container — the host user cannot read the 600/uid-10001 file) |
| behavior | `MEMORY_FILE=/app/data/memory.json` (volume, uid 10001) · `WORKBENCH_BASE_URL=http://192.0.2.1:18100` |
| admin | `ADMIN_ENABLED=1`, fresh 64-hex token generated **on the NAS** (600, uid 10001); never printed/committed |
| build B | includes the mirror-language hot-apply fix (see below); build A (real smoke) → build B differs only in `gateway/app/behavior.py::_render_for_apply` |

## Verification

1. **Structural probe** (`probe_mvp_structural.py`, inside the container):
   `MVP_STRUCTURAL_PROBE: 11/11 PASS` — health/OTA/hello + admin matrix
   (anonymous 401×6 / invalid 401×6 / valid 200×6, token never leaked).
2. **Workbench reachability** from inside the sidecar: `/sync/health` → `ok`,
   `/sync/state` → rev 77, currentLesson 12 (read-only GETs).
3. **Bounded real Qwen smoke** (via `mvp_real_smoke.py`, ONE session — budget 3/4):
   `turn1_done / turn2_audio_started / bargein_stop / turn3_recovery / quiesced` all true,
   closures **0/0/0**, `qwen_dispatch_errors_total=0`, `accounting_fault_events=0`,
   `orphan_pcm_bytes=0`, `barge_ins=2`. The client received STREAMING+FINAL user
   transcripts and assistant deltas; behavior decisions were logged for every turn
   (`kind=NONE`, `lang=en` mirror) and the deferred-apply path was exercised live
   ("apply deferred (not a safe boundary)") with no error.
   Evidence: `evidence/mvp_real_smoke.json`.
   *Build A hosted the smoke run; build B (mirror-language fix) is validated by the local
   suites (BEHAVIOR 111/111, INTEGRATION 28/28) and the structural probe — no extra real
   session spent at that time. The automated real-Qwen budget is now fully consumed
   (4/4, LOCKED — remaining 0); later builds (GUI fix, vocabulary audit) were verified via
   deterministic/mock/structural suites only — see `MVP-HUMAN-TEST.md`.*
4. **Non-change evidence**: `xiaozhi-rtl-bridge` StartedAt 2026-10-06T18:41:10Z / Restarts 0 ·
   `english-learning-workbench-web` StartedAt 2026-10-04 / 0 ·
   `xiaozhi-product-sidecar` StartedAt 2026-10-07T10:30 / 0 · no credentials rotated.

## Mac client arm (OTA only — minimal diff)

| item | value |
|---|---|
| config | `~/Library/Application Support/py-xiaozhi/config/config.json` |
| backup | `config-backups/config_backup_mvp_humantest_20261007_231359.json` |
| SHA256 before | `02b8dffbf9277b39b8da4f329efdd8bad874cc2a82122f2edfc7797c7068a93b` |
| SHA256 after | `2e15dcda60700cc1d0751b8abbf09bc025e967638ea334669d08fdc8ea629d55` |
| diff | exactly **2 lines** (± `OTA_VERSION_URL`): `…:8102/xiaozhi/ota/` → `…:28211/xiaozhi/ota/`; `WEBSOCKET_URL` and everything else byte-identical |
| OTA verified from the Mac | `POST http://192.0.2.1:28211/xiaozhi/ota/` → `ws://192.0.2.1:28210/xiaozhi/v1/` |
| client runtime note | the client consumes OTA and persists the result: `WEBSOCKET_URL` → `ws://192.0.2.1:28210/…` and `WEBSOCKET_ACCESS_TOKEN` → the sidecar's OTA token (both OTA-driven, expected client behaviour; also reset by the rollback) |
| rollback | `cp config-backups/config_backup_mvp_humantest_20261007_231359.json "$HOME/Library/Application Support/py-xiaozhi/config/config.json"` (then verify sha256 == before; restores OTA + WS URL + token to the legacy values) |
| sidecar rollback | `cd /volume1/docker/xiaozhi-mvp-sidecar && docker compose down && rm -rf /volume1/docker/xiaozhi-mvp-sidecar` |

## Boundary notes

* No internet exposure; LAN only; no production credential rotated; Qwen key reused as a
  runtime copy (never committed, never printed).
* MEMORY-1 data lives only in the sidecar's `data/` volume (owner 10001).
* Workbench is read-only from the sidecar (GET-only adapter; no PUT exists in the code).