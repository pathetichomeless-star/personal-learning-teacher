# MASTER-BASELINE (PRODUCT-COMPLETION MASTER RUN)

Captured: 2026-10-07 · Repo: `<project-root>` (canonical source; local-only git)

## Accepted baseline

| fact | value |
|---|---|
| HEAD | `71cec08ed0e659cb941a1237461b06a5af157697` (`admin1: read-only gateway admin plane`) |
| branch / remote / worktree | `main` / **no remote** / **clean** |
| rollback tag | **`product-master-pre-run`** → `71cec08` (annotated) |
| rollback bundle | `admin0-backups/product-master-pre-run.bundle` (600, `git bundle verify` = okay, complete history) |
| earlier bundle | `admin0-backups/admin1-pre-source.bundle` (600) |
| accepted state | ADMIN-1 PASS · R-1f ACCEPTED/FROZEN · ADMIN-ARCH-1 PASS · MONOREPO PASS |

## Frozen-surface verification (R-1f)

10 `rtl-lab/app/*` files re-hashed against `docs/admin0/baseline-manifest.sha256`: **no drift**, except the two
files ADMIN-1 was authorized to wire (`gateway/app/main.py`, `gateway/app/ws.py`). Pacing constants (20/15/5),
Opus/FIFO (`audio.py`), provider/model/voice (`qwen.py`, `config/config.json`), counters (`counters.py`),
diagnostics (`diag.py`, `http.py`), generations (`turns.py`) remain byte-identical to the accepted R-1f build.

## ADMIN-1 evidence at baseline

`docs/engineering/audits/admin1-lead-test-evidence.txt` → `ADMIN1_TESTS: 80/80 PASS`, `ADMIN1_LOAD: 29/29 PASS`;
auditor reports A–E all PASS (`docs/engineering/audits/admin1-agent-*.md`).
Local test env: `gateway/.venv` (uv + aiohttp 3.14.4) + locally built libopus 1.3.1 at `/tmp/opus131/lib`
(dev-only; the NAS image ships its own libopus — hence the one environment-only R-1f sentinel-harness failure).

## Architecture documents in force

`docs/architecture/{ADMIN-ARCH-1,api-boundaries,data-ownership,security-model,admin-navigation,implementation-roadmap}.md`
+ raw design tracks A–G. Rulings R1–R4 (diag/reset not a control-plane endpoint; ADMIN-1 gateway-only;
Knowledge owns its own store — legacy `ai_rag_*` unused in v1; ephemeral workbench task pointer allowed,
state never injected) are binding for this master run.

## Master-run rules in force

- Lead = only writer; independent reviewers read-only except their own reports; raw reports persisted.
- Globally frozen: native Qwen Audio↔Audio, provider, model, production voice, VAD threshold/silence,
  20 ms pacing, 15 ms send-start guard, 5 ms slack, Opus frame behaviour, FIFO semantics, R-1f generation
  ownership, barge-in behaviour, drop accounting, pacing gates.
- Bounded real-Qwen allowance: **MAX_REAL_QWEN_SESSIONS = 4** (short spikes/smoke only; no soak).
- Stop conditions: the 11 listed in the master authorization (true blocker, locked-constant change,
  cascade replacement, unauthorized Workbench writes, irreversible user-data deletion, credential rotation,
  public-internet exposure, licence choice, exceeding the real-Qwen allowance, human listening judgment,
  promotion to the primary realtime instance).

## Phase log (this document is appended as phases complete)

| phase | status | artefact |
|---|---|---|
| 0 master baseline | **DONE** | this file |
| 1 ADMIN-1 NAS sidecar | **DONE** (PO-accepted) | `docs/engineering/master-run/PHASE-1-ADMIN1-DEPLOY.md` |
| 2 CLIENT-UI-1 | **DONE** (PO-accepted) | `PHASE-2-CLIENT-UI.md` |
| 3 session.update spike | **DONE** (MVP run; supersedes as artefact) | `PHASE-3-SESSION-UPDATE-SPIKE.md` |
| 4 BEHAVIOR-1 | **DONE** (MVP scope) | `PHASE-4-BEHAVIOR-1.md` |
| 5 MEMORY-1 | **DONE** (MVP scope) | `PHASE-5-MEMORY-1.md` |
| 6 KNOWLEDGE-1 | deferred by PO (MVP) | `PHASE-6-KNOWLEDGE-1.md` |
| 7 WORKBENCH-1 | **DONE** (MVP scope) | `PHASE-7-WORKBENCH-1.md` |
| 8 ADMIN-2 | pending | `PHASE-8-ADMIN-2.md` |
| 9 unified admin UI | pending | (extend `admin/`) |
| 10 integration regression + security audit | pending | — |
| 11 multi-agent final review (A–F) | pending | — |
| 12 final sidecar integration build | pending | — |
| 13 human final acceptance script | pending | (Chinese H1–H13) |
| 14 cleanup / report / commit | pending | `docs/engineering/PRODUCT-MASTER-RUN-REPORT.md` |

## CONVERSATIONAL MVP RUN (new priority, 2026-10-07 evening)

The product-owner re-scoped the immediate goal to **one daily-usable conversational
version** (avatar / Knowledge-1 / advanced ADMIN-2 / unified admin UI / camera deferred).
Route: Phase 3 spike → Phase 4 BEHAVIOR-1 → Phase 5 MEMORY-1 minimal → Phase 7 WORKBENCH-1
read-only → integration regression → NAS test sidecar → Mac client human-test ready → STOP.

| step | status | artefact |
|---|---|---|
| 3 session.update spike | **DONE (verdicts SUPPORTED)** | `PHASE-3-SESSION-UPDATE-SPIKE.md` + `evidence/phase3_spike_round{1,2}.json` |
| 4 BEHAVIOR-1 | **DONE (109/109)** | `PHASE-4-BEHAVIOR-1.md` |
| 5 MEMORY-1 minimal | **DONE (19/19)** | `PHASE-5-MEMORY-1.md` |
| 7 WORKBENCH-1 read-only | **DONE (25/25)** | `PHASE-7-WORKBENCH-1.md` |
| integration regression (local) | **DONE (28/28 + all suites green)** | `MVP-INTEGRATION-REGRESSION.md` + `evidence/mvp-local-suites.txt` |
| NAS test sidecar (MVP) | **DONE (structural 11/11; real smoke 1 session PASS)** | `PHASE-MVP-SIDECAR.md` + `evidence/mvp_real_smoke.json` |
| Mac client arm + human test | **ARMED — waiting for PO** | `MVP-HUMAN-TEST.md` |

Real-Qwen budget: **4/4 sessions used — LOCKED (REMAINING = 0)** per product-owner
directive (2026-10-08). Breakdown: 2 Phase-3 spike + 1 real smoke + 1 vocabulary matrix.
**No further automated real-Qwen session may be opened under any circumstance.** All
remaining Product V1 work must use deterministic / mock-protocol / structural /
integration / static read-only verification only. The next real conversational
validation is exclusively the product owner's final unified human acceptance.