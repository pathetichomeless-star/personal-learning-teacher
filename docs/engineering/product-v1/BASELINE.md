# PRODUCT V1 FINAL COMPLETION RUN — PHASE 0 BASELINE MANIFEST

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 0 基线取证 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Captured: 2026-10-08 (Asia/Shanghai), before any product change.
Directive: `docs/engineering/product-v1/PRODUCT-V1-RUN-DIRECTIVE.md` (1396 lines, committed as 2fd8d4f).

## Repository

| Fact | Value |
|---|---|
| START_COMMIT | `2fd8d4f8bedffaad8e6973f294b8ac7ed1a365d8` |
| branch | `main` |
| remote | none (local-only repo) |
| worktree | CLEAN (verified before tag creation) |
| tracked files | 991 |
| HEAD subject | `docs: persist the PRODUCT V1 final completion run directive (phases 0-12)` |

Continuity check (directive §"CURRENT EXPECTED BASELINE"): HEAD is a descendant of
`049401a` (vocab-audit), `3f1da03` (budget lock), `bfb23b1` (GUI transcript fix),
`b702058` (behavior/memory/workbench phases), `71cec08` (ADMIN-1). All present in `git log`.

## Rollback

| Artifact | Value |
|---|---|
| git tag | `product-v1-pre-run` → `e8af29d7326d0cf45fbfa854e41db7847c84ab40` |
| git bundle | `admin0-backups/product-v1-pre-run.bundle` (mode 600) |
| bundle sha256 | `fec3096d72592a0c310c4ad76d2f75b60699a6f01d094906ba353e86e91433b1` |
| restore command | `git clone admin0-backups/product-v1-pre-run.bundle restored-repo` (or `git fetch <bundle> main`) |

## NAS containers (read-only inspection)

| Container | StartedAt (UTC) | Restarts | Health | Ports (host) |
|---|---|---|---|---|
| xiaozhi-rtl-bridge (primary realtime) | 2026-10-06T18:41:10Z | 0 | healthy | 8110, 8111 |
| xiaozhi-mvp-sidecar (accepted MVP) | 2026-10-07T16:00:45Z | 0 | healthy | 28210–28212 |
| xiaozhi-product-sidecar (phase-1 mock) | 2026-10-07T10:30:18Z | 0 | healthy | 28110–28112 |
| english-learning-workbench-web | 2026-10-04T01:56:08Z | 0 | healthy | 18100 |
| english-learning-workbench-sync | 2026-10-05T02:22:46Z | 0 | healthy | — |
| xiaozhi-full-server (legacy) | 2026-10-05T14:17:14Z | 0 | none | 8100, 8103 |
| xiaozhi-full-web (legacy) | 2026-10-05T13:05:07Z | 0 | none | 8102 |
| xiaozhi-full-db / xiaozhi-full-redis | 2026-10-05T02:22:33Z | 0 | healthy | internal |
| xiaozhi-esp32-server (origin) | 2026-10-05T01:39:35Z | 0 | none | 8000, 8003 |

Primary realtime and Workbench must remain untouched for the whole run.

## Mac client (armed for MVP human test)

| Fact | Value |
|---|---|
| config path | `~/Library/Application Support/py-xiaozhi/config/config.json` |
| config sha256 (live) | `94b069fa74895c0ec348947a6fbb9794ad87d7b67b29a7ec0aa5c05cf430205e` |
| OTA_VERSION_URL | `http://192.0.2.1:28211/xiaozhi/ota/` (MVP sidecar) |
| WEBSOCKET_URL (persisted) | `ws://192.0.2.1:28210/xiaozhi/v1/` |
| pre-arm backup | `config-backups/config_backup_mvp_humantest_20261007_231359.json` (sha256 before `02b8dffb…`) |
| rollback | `cp` backup over live config path |

Phase 10 will re-point OTA to the Product V1 test sidecar and record before/after hashes.

## Accepted capabilities (inherited evidence)

| Capability | Evidence |
|---|---|
| R-1f realtime invariants | `docs/engineering/master-run/MASTER-BASELINE.md`, r1f suite 179/180 (1 known env-only libopus sentinel) |
| ADMIN-1 read-only plane | `docs/admin1/`, admin1 80/80 + load 29/29, commit 71cec08 |
| CLIENT transcript GUI | `docs/engineering/master-run/FINDING-GUI-TRANSCRIPT.md`, gui_transcript_live 25/25 |
| Behavior-1 | `docs/engineering/master-run/PHASE-4-BEHAVIOR-1.md`, behavior1 111/111 |
| Vocabulary accuracy | `docs/engineering/master-run/VOCAB-ACCURACY-AUDIT.md`, vocab_accuracy 79/79 |
| Memory-1 minimal | `docs/engineering/master-run/PHASE-5-MEMORY-1.md`, memory1 19/19 |
| Workbench-1 read-only | `docs/engineering/master-run/PHASE-7-WORKBENCH-1.md`, workbench1 25/25 |

## Real-Qwen budget (hard lock)

REAL_QWEN_TOTAL_USED = 4/4, REMAINING = 0 (`3f1da03`).
No real-session driver may run during this completion run. Historical tooling
(`spike_session_update.py`, `spike_vocab_matrix.py`, `mvp_real_smoke.py`, `r1f_real_probe.py`)
exists in-tree but MUST NOT be executed.

## Hygiene (Phase 0 CHECK)

- No secrets tracked: only `*.env.example`, tokenizer vocab `tokens.txt`, docs, and the
  secret-writing script `tools/configure-secrets.sh` (reads from gitignored `secrets/`). PASS
- No learner raw transcripts tracked: `logs/`, `*.jsonl`, `r1f_ht_*`, evidence captures all
  gitignored. PASS
- No real learner data committed: `secrets/`, `config-backups/`, `admin0-backups/`,
  `rtl-lab-backups/`, `**/*.sqlite` gitignored. PASS
- Repository clean at baseline. PASS

## Frozen surfaces (all phases)

Native Qwen Audio↔Audio architecture, provider, model `qwen3.8-omni-flash-realtime`,
voice Tina, VAD (server_vad 0.5/800ms), 20ms media frame, 15ms send-start guard,
5ms pacing slack, Opus, FIFO, generation ownership, barge-in, pacing gates,
R-1f accounting semantics. No ASR→LLM→TTS, no second LLM. See directive §LOCKED REALTIME / AUDIO SURFACES.