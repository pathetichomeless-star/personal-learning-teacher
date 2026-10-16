# ADMIN-1 IMPLEMENTATION REPORT (read-only gateway admin plane)

Date: 2026-10-07 · Scope: **Mac source + tests only** — no build, no deployment, no NAS change, no port
exposure, no credential rotation. Baseline HEAD `ecb8209` (branch `main`, local-only, no remote).

## 1. What was delivered

| item | detail |
|---|---|
| isolated control listener | third aiohttp `AppRunner`, independent of the audio/OTA app; **`ADMIN_ENABLED=0` by default**, `ADMIN_BIND=127.0.0.1`, `ADMIN_PORT=8112`; starts only when explicitly enabled |
| bearer auth | every `/admin/*` API requires `Authorization: Bearer <token>`; token from `ADMIN_API_TOKEN_FILE` (env fallback `ADMIN_API_TOKEN`); constant-time compare; fail-closed (no listener) when enabled without token; token never logged/returned/echoed |
| six read-only APIs | `GET /admin/health`, `/admin/version`, `/admin/sessions`, `/admin/metrics`, `/admin/telemetry`, `/admin/diag-summary` — allowlist-built payloads, bounded, deterministic, explicit null/unavailable states |
| minimal console | zero-build `admin/{index.html,app.js,styles.css}` — Dashboard / Realtime / Diagnostics; manual token entry (sessionStorage only), eight visible states, request ids on errors, honest "Telemetry aggregator is not available yet", no write controls anywhere |
| tests | `gateway/tests/admin1_tests.py` (80 checks) + `gateway/tests/admin1_load.py` (29 checks) |
| audits | four independent auditors + a fresh final reviewer (all raw reports persisted) |

## 2. File surface (complete)

```
new:      gateway/app/admin/{__init__,config,auth,registry,views,app,service,version}.py
new:      admin/{index.html,app.js,styles.css}
new:      gateway/tests/admin1_tests.py, gateway/tests/admin1_load.py
modified: gateway/app/main.py   (+11 lines: admin listener start/stop in _run)
modified: gateway/app/ws.py     (+4 lines: two lifecycle-only registry calls)
docs:     docs/engineering/audits/admin1-*.md, docs/engineering/ADMIN-1-IMPLEMENTATION-REPORT.md,
          docs/engineering/deploy-log.md (entry 81)
```

**Frozen-surface proof** (auditor B and E, independently): against `docs/admin0/baseline-manifest.sha256`, exactly
`main.py` and `ws.py` changed; `turns.py` (pacing constants `20/15/5`), `audio.py` (Opus/FIFO), `qwen.py`,
`config/config.json`, `counters.py`, `diag.py`, `http.py`, `protocol.py` are **byte-identical**. No R-1f audio
logic, provider, model, voice or counter contract was touched. The registry is fed only from the WS lifecycle and
holds weak references; no admin code path runs inside the pacer task, the send loop, the audio callback or the
Qwen delta loop.

## 3. Test evidence (Lead-generated file: `docs/engineering/audits/admin1-lead-test-evidence.txt`)

| suite | result |
|---|---|
| ADMIN-1 deterministic (`admin1_tests.py`) | **80/80 PASS** |
| ADMIN-1 load regression (`admin1_load.py`, mock session + admin polling ~150 ms) | **29/29 PASS** — 444–450 requests, all 200, max 5–7 ms, `pacer_rebases = 0`, closures 0, fps ≈ 49.99 in band, zero fatal stalls / guard violations / short intervals / store-cap transitions / post-terminal sends |
| R-1f deterministic suite (current tree) | 180 checks, **179 PASS, 1 FAIL** |
| R-1f deterministic suite (pristine baseline `ecb8209`, same interpreter + libopus) | 180 checks, **179 PASS, 1 FAIL** (identical) |

**Environmental disclosures (not ADMIN-1 defects, independently replicated by auditors B and E):**
1. The single R-1f failure `B test_sentinel_harness EXCEPTION OpusError()` reproduces **identically on the pristine
   baseline** → a property of the *local* macOS libopus build (the authoritative R-1f acceptance ran in the NAS
   image, whose libopus differs, at 187/187).
2. `r1f_runtime.py`'s full-suite run shows a pre-existing `backlog_stress` timing flake in **both** trees
   (passes 13/13 when run in isolation).
3. Local test environment: `gateway/.venv` (uv, aiohttp 3.14.4) + a locally compiled **libopus 1.3.1** at
   `/tmp/opus131/lib` (dev-only, outside the repo; the NAS image ships its own libopus). Test command:
   `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/<suite>.py`.
4. Transient `Errno 48` port collision seen by auditor A when several auditors ran the load test concurrently —
   environmental, resolved, not a defect.

## 4. Independent audit results

| auditor | raw report | verdict |
|---|---|---|
| A — API/auth correctness | `docs/engineering/audits/admin1-agent-a-api-auth.md` | **PASS** (own 76-check probe; 6 endpoints only; 401/401/200 matrix; no oracle; read-only invariants; `ADMIN_ENABLED=0` starts nothing) |
| B — R-1f audio regression | `docs/engineering/audits/admin1-agent-b-audio-regression.md` | **PASS** (frozen hashes; baseline-equal suite counts; load gates; no admin path in the audio loops) |
| C — security/privacy | `docs/engineering/audits/admin1-agent-c-security.md` | **PASS** (own 11 hostile fixtures; zero body/header/log leaks; allowlist proven; traversal/env probes rejected; no external coupling) |
| D — UI/scope | `docs/engineering/audits/admin1-agent-d-ui-scope.md` | **PASS** (3 pages only; GET-only six endpoints; sessionStorage token; 8 states; no write/reset/ADMIN-2 feature) |
| E — fresh final review + re-check | `docs/engineering/audits/admin1-agent-e-final.md` | **PASS** (61-check own probe + falsification of all six claims) · correction re-check **PASS** |

## 5. Findings and dispositions

| # | finding | source | disposition |
|---|---|---|---|
| 1 | token store cleared a valid token on repeated reload (real bug) | Lead test suite | fixed (unchanged source keeps in-memory material); `hmac` comparison unchanged |
| 2 | vacuous UI assertion (`... or True`) | D (minor) | replaced with real checks (forbidden-endpoint list + no write controls + no reset control) → suite now 80 checks |
| 3 | `diag.SNAPSHOT_PROVIDER()` under `RTL_DIAG=1` increments diag-local assertion/journal state when send intents are unresolved | E (minor) | **documented, no change** — inherited `/diag` behaviour, log-only, not introduced by ADMIN-1, and touching `diag.py` would breach the R-1f freeze |
| 4 | Lead evidence file was stale (79/79) | E (minor) | regenerated (80/80, 29/29, both R-1f runs) |
| 5 | dead variable `banned` in `test_source_guards` | E (minor) | removed |
| 6 | UI Clear left stale non-auth tiles | E (minor) | fixed (blanks `.big` tiles, empties/hides the sessions table) |
| 7 | static UI shell is served without auth | C (note) | by design: the shell carries no operational data; all data calls are authenticated |
| 8 | `resettable: false` field name contains "reset" | E (note) | read-only honesty field; the test asserts no reset *control*/*endpoint*, not the word |

## 6. Scope compliance

No `/admin/routing`, no controlled-write endpoints (instruction / language-policy / provider / model / voice /
memory-policy / knowledge-assignment / session-reload), **no `/admin/diag/reset`**, no ADMIN-2 work, no
manager-api / Workbench / Memory / Knowledge / RAG / legacy DB / Redis integration, no provider/model/voice
change, no ASR→LLM→TTS cascade. Nothing deployed: **no image rebuild, no NAS deployment, no compose change, no
container restart, no port 8112 exposure, no firewall change, no credential rotation.**

## 7. Rollback

```
git (local-only repo): revert the ADMIN-1 commit (git revert / git reset), or
pre-ADMIN-1 bundle:  admin0-backups/admin1-pre-source.bundle (mode 600, verified, HEAD ecb8209)
private originals:   admin0-backups/pre-monorepo-originals/*  (pre-monorepo trees)
NAS: no rollback needed — nothing on the NAS changed.
```

## 8. Final acceptance

```
A_ADMIN1_API = PASS · B_ADMIN1_AUDIO = PASS · C_ADMIN1_SECURITY = PASS · D_ADMIN1_UI = PASS
E_ADMIN1_FINAL_REVIEW = PASS (0 blockers · 0 majors · 2 minors documented/no-change · correction re-check PASS)
ADMIN1_IMPLEMENTATION = ACCEPTED (design-locked scope, frozen R-1f surface, zero external dependencies)
SAFE_TO_AUTHORIZE_ADMIN1_DEPLOYMENT = YES (a separate deployment authorization is required; nothing was deployed)
SAFE_TO_START_ADMIN2 = NO (the mid-session `session.update` spike must come first)
```