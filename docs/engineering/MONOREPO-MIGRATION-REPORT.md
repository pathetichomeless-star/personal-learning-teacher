# MONOREPO MIGRATION REPORT

Date: 2026-10-07 · Scope: **source organisation only** (Mac-only, local git, no remote, no push).
No runtime behaviour change, no R-1f audio-logic change, no model/provider/settings change, no credential
rotation, no NAS container action, no Workbench data change, no ADMIN UI code.

## 1. Lead actions (executed in order)

| step | action | result |
|---|---|---|
| P0 | re-verified py-xiaozhi `HEAD=fed4836…`, tag `r1f-client-accepted`, worktree clean; rtl-lab 92/92 baseline matches; sanitized nas-deploy (0 literal credential sites); root `.git` absent | all green |
| P0 | migration-specific private backup `admin0-backups/admin0_pre_monorepo_20261007_123110.tar.gz` (128 MB, mode 600) + `.sha256`; git bundle `admin0-backups/py-xiaozhi-pre-monorepo.bundle` (61 062 573 B, mode 600) | `git bundle verify` = **okay**, refs `main` + `r1f-client-accepted`, "records a complete history" |
| P1 | `git init -b main` at the root; **no remote**; **no git config change** (per-command `-c user.name/email` only); temporary `.git/info/exclude` = `py-xiaozhi/ rtl-lab/ nas-deploy/` | branch `main`, `git remote -v` empty |
| P2 | foundation commit (approved shareable files only) | `303d0d3` |
| P3 | client import with locally available history | `3e22a4d` |
| P4 | gateway baseline import (source-only) | `561bd80` |
| P5 | deploy import (sanitized) | `1abc74b` |
| P6 | module scaffold (4 boundary READMEs) | `b379cec` |
| P7 | documentation organisation + tools | `6ffabc4` |
| P8 | old trees retired into the private rollback area | `admin0-backups/pre-monorepo-originals/{py-xiaozhi,rtl-lab,nas-deploy}` (dir mode 700) |
| P9 | temporary excludes removed (`.git/info/exclude` emptied) | private material still covered by the public `.gitignore` alone |
| P10 | final security scan (tracked scope) | all secret categories 0 |
| P11 | this report + change-log entry | `docs/engineering/MONOREPO-MIGRATION-REPORT.md`; `docs/engineering/deploy-log.md` entry 79 |

## 2. Commit SHAs (local only; no remote configured, nothing pushed)

```
303d0d343ac98d20dd7c6dc8eebea476c3ac8a09  admin0: monorepo foundation — share boundary, attribution, approved documentation
3e22a4de0c3f7a3393526a7092c545ed9fb0528f  client: import py-xiaozhi source with locally available history
561bd80                                   gateway: accepted R-1f baseline import (source-only, no runtime modification)
1abc74b                                   deploy: import sanitized legacy-stack deployment source
b379cec                                   modules: scaffold ownership boundaries (adapters, intent, memory, knowledge)
6ffabc4                                   docs: organize approved documentation (admin0, admin1, engineering, reference) + tools
fed48362c65b92a9fb8464aa51ebff4488979d2c  feat(client): freeze accepted R-1f rev-9 playout telemetry instrumentation   (imported, unchanged SHA)
9bfc807d368cccac71af8d9f7042ab6b5af92030  chore: release v2.1.2                                                       (imported, unchanged SHA)
```
Tags: `r1f-client-accepted` → `fed48362c65b92a9fb8464aa51ebff4488979d2c` (annotated object `8313e168…`);
`v2.1.2` came along with the import (same commit as upstream `9bfc807…`).

## 3. Imported-history verification (Agent A, independent)

- Import commit `3e22a4d` is a true two-parent merge (`303d0d3` + `fed4836`) — **no squash, no rebase, no reset**;
  source reflog shows only `clone` + `commit`.
- `HEAD:client` tree SHA equals `fed4836^{tree}` (`425589fb…`) and `git diff` is empty → the client subtree is
  byte-identical to the accepted source (815 regular files compared, 0 mismatches; the 7 R-1f files match
  `b489a282… / e4014df6… / 314d6a72… / 60e726c8… / 8e216718… / d46d3e3c… / b0229681…`).
- **Shallow-source disclosure**: `py-xiaozhi` was a shallow clone (boundary
  `9bfc807d368cccac71af8d9f7042ab6b5af92030`, no parent). `git subtree add --prefix=client …` **failed**
  ("shallow roots are not allowed to be updated"); the import was completed with the standard subtree procedure
  (`git fetch … main:refs/heads/import-client` → `git merge -s ours --allow-unrelated-histories --no-commit`
  → `git read-tree --prefix=client/ -u` → commit) and by declaring **the same shallow boundary** in the root
  repository, so exactly the locally available history is preserved (no history reconstructed or rewritten).
  `git rev-parse --is-shallow-repository` = `true` for the root repo — documented, expected.
- No nested repository: `find client gateway modules deploy tools docs -name .git` → none; no `.gitmodules`;
  the only retired `.git` is `py-xiaozhi/.git` inside the private rollback area.

## 4. Imported-tree hash verification (Agent B, independent)

| tree | comparison | result |
|---|---|---|
| `client/` | 815 tracked regular files vs `py-xiaozhi/` | 0 mismatches / 0 missing |
| `gateway/` | 42 files vs the ADMIN-0 baseline (`rtl-lab/`), 15 `r1f-*.md` relocated to `gateway/docs/` | 0 mismatches; 50 files excluded by the share boundary (evidence + secrets) |
| `deploy/legacy-xiaozhi/` | 4 files vs the sanitized `nas-deploy/` | 0 mismatches; composes byte-identical (`0430aa28b1cf9680…` ×2), `.env.example` `514ff131a4a2555f…` |
| constants | `gateway/app/turns.py` | `MEDIA_FRAME_MS=20.0`, `MIN_SEND_START_INTERVAL_MS=15.0`, `PACING_SLACK_MS=5.0` — unchanged (hash `06a41cf9…` matches baseline) |
| model/provider | `gateway/app/qwen.py`, `gateway/config/config.json` | `DEFAULT_MODEL="qwen3.8-omni-flash-realtime"`, `DEFAULT_VOICE="Tina"`, `is_real==(mode=="real")` — unchanged |
| dependencies | imported trees | no new requirements/lock/version files |

No baseline source file is missing (`BASELINE_MISSING_TOTAL = 0`); the 24 files without a baseline counterpart are
the scaffold/docs/root files added by this migration.

## 5. Security verification (Agent C + Lead, independent)

Tracked scope **896** files (+ the 4 pending audit reports, also clean). All counts **0**:
`QWEN_API_KEY`, `MYSQL_PASSWORD`, `REDIS_PASSWORD`, `ADMIN/manager credentials`, `SSH_PRIVATE_KEY`,
`PRIVATE_CONFIG`, `PRIVATE_BACKUP`, `REAL_LEARNER_AUDIO` (outside the approved asset path),
`REAL_LEARNER_TRANSCRIPT`.
- No tracked path under `secrets/ logs/ config-backups/ admin0-backups/ rtl-lab-backups/ rtl-lab/evidence/ py-xiaozhi/ nas-deploy/ .workbuddy/`; no tracked `*.env` (except `*.env.example`).
- Synthetic test audio exists only in `gateway/tests/assets/u{1,2,3}.pcm16k.raw` (approved). The other 407 tracked
  `*.wav` files are the client's own UI sound assets (`client/assets/sounds/<locale>/*.wav`).
- Human-test artefacts `r1f_ht_*`: **0 tracked**; they live only in the private area.
- `deploy/legacy-xiaozhi/**`: 0 literal credentials; only `${VAR}` references + the 3 allowed `change_me_*` placeholders.
- Known false positives cleared: `third-party-content` (licence wording in `NOTICE.md`) and `change_me_*`.
- **Explicitly disclosed, not a private secret**: `docs/reference/config.yaml` (the upstream XiaoZhi sample config)
  contains one 32-hex value that its own comment marks as a **shared upstream sample key**; it is upstream reference
  material, not our credential, and it is not used by any of our services. It is listed here so the "0" counts above
  are unambiguous about what they mean (no *private* credential is tracked).
- The 407 non-synthetic `*.wav` files are the client's own UI sounds (`client/assets/sounds/<locale>/*.wav`), inherited
  from the MIT fork — not learner audio.
- Retirement safety: the 44 paths that became trackable after removing the temporary excludes were scanned
  clean, and the genuinely sensitive material (`rtl-lab/evidence/**`, `rtl-lab/secrets/`, `nas-deploy/data|monitor/`)
  is covered by the public `.gitignore` **independently** of the temporary exclude.

## 6. Independent audit reports (raw artefacts)

| auditor | raw report | verdict |
|---|---|---|
| A — git/history | `docs/engineering/audits/monorepo-agent-a-git-history.md` | **PASS** |
| B — source integrity | `docs/engineering/audits/monorepo-agent-b-source-integrity.md` | **PASS** |
| C — security/privacy | `docs/engineering/audits/monorepo-agent-c-security.md` | **PASS** |
| D — licence/attribution | `docs/engineering/audits/monorepo-agent-d-license.md` | **PASS** |
| E — fresh final review | `docs/engineering/audits/monorepo-agent-e-final-review.md` | **PASS** (0 blockers / 0 majors / 4 minors, all corrected; 6/6 correction re-checks PASS, then 0/0/0) |

## 7. Findings and dispositions

| # | finding | source | disposition |
|---|---|---|---|
| 1 | `git subtree add` fails against a shallow source | Lead (P3) | recovered via the standard subtree merge + declaring the same shallow boundary; disclosed in §3 |
| 2 | `.gitignore` inline `#` comment made the synthetic-asset un-ignore inert (my own edit) | Lead | fixed: comment moved to its own line; `git check-ignore` now reports the assets SHAREABLE |
| 3 | un-ignore path had to relocate with the asset move (`rtl-lab/tests/assets` → `gateway/tests/assets`) | Lead | rule unchanged (synthetic assets stay shareable); only the path it names changed |
| 4 | `tools/*.sh` still pointed at `py-xiaozhi/` | Lead | patched to `client/`; operational note: the client `.venv` was never tracked, so a future run needs `cd client && uv sync` |
| 5 | naive scanners flag the 3 `change_me_*` lines in `.env.example` | Lead/C | false positives (dummy placeholders are required); documented |
| 6 | `NOTICE.md` / `THIRD_PARTY_LICENSES.md` referred to the fork as `py-xiaozhi/` | D (MINOR) | corrected to `client/` (the tracked fork) with the upstream fork noted |
| 7 | historical docs still mention old paths (e.g. `rtl-lab/tests/assets/…`) | B/C (INFO) | archival documents left verbatim; path mapping recorded here |
| 8 | symlink entry `client/documents/docs/zh/guide/images` (upstream quirk) | B (INFO) | upstream artefact imported as-is; not a defect |
| 9 | two compose copies remain byte-identical | Lead/B (INFO) | future cleanup candidate (deleting one needs separate approval) |
| 10 | `.gitignore` lines for retired paths (`nas-deploy/data|monitor`, `rtl-lab/evidence/**`) are now inert | Lead/C (INFO) | public boundary rules left unchanged on purpose; harmless |
| 11 | root repository is shallow (import boundary) | A (disclosure) | documented; history is exactly what was available locally |
| 12 | `NOTICE.md` / `THIRD_PARTY_LICENSES.md` still named `py-xiaozhi/LICENSE` | E (MINOR) | corrected to `client/LICENSE` (historical wording kept only where intentional) |
| 13 | the uncommitted set was larger than the Lead brief (two attribution files) | E (MINOR) | acknowledged; the corrected brief was re-verified by E |
| 14 | `tools/configure-secrets.sh` referenced the retired `nas-deploy` path | E (MINOR) | corrected; the rollback hint now points at the private rollback area (existence verified) |
| 15 | §5 "all 0" did not name the upstream shared sample key | E (MINOR) | explicit disclosure added (upstream reference material, not our credential) |
| 16 | annotated tag object SHA differs from the source repo (`8313e168…` vs `b12fd407…`) | E (INFO) | expected: the tag was recreated in the monorepo; the pointed commit is unchanged |
| 17 | one dangling blob; retired subtrees are 755 inside a 700 parent | E (INFO) | harmless; the private area's directory protection is what matters |
| 18 | independent E re-check of the correction delta | E | 6/6 verified, no source/security/history/environment impact |

## 8. Environment non-change evidence

- **NAS**: `xiaozhi-rtl-bridge` `StartedAt=2026-10-06T18:41:10.230297191Z`, `Restarts=0`; all nine protected
  containers unchanged (`english-learning-workbench-web` 2026-10-04T01:56:08Z, `-sync` 2026-10-05T02:22:46Z,
  `<legacy-platform>` 2026-10-02T01:46:15Z, `word-master` 2026-10-06T05:02:58Z, `xiaozhi-esp32-server` 2026-10-05T01:39:35Z,
  `xiaozhi-full-db/-redis` 2026-10-05T02:22:33Z, `xiaozhi-full-server` 2026-10-05T14:17:14Z,
  `xiaozhi-full-web` 2026-10-05T13:05:07Z) — all `Restarts=0`, byte-identical to the pre-migration values.
  No container was started, stopped, restarted, rebuilt or reconfigured.
- **Workbench**: untouched (no exec, no data access, rev not advanced); its content stays external and unvendored.
- **Legacy XiaoZhi admin/server**: external and pinned (images referenced only); not forked or vendored.
- **Credentials**: no rotation performed (the ADMIN-0 `ROTATION_NEEDED` items remain deferred); no secret value was
  copied into any shareable file.
- **ADMIN UI**: no code written.

## 9. Rollback (exact location)

```
private backup set (mode 600, directory 700):
  admin0-backups/pre-monorepo-originals/py-xiaozhi/     ← original client repo incl. .git (fed4836, tag r1f-client-accepted)
  admin0-backups/pre-monorepo-originals/rtl-lab/        ← gateway source incl. evidence/ (11 MB) + secrets/
  admin0-backups/pre-monorepo-originals/nas-deploy/     ← sanitized deployment copy
  admin0-backups/admin0_pre_monorepo_20261007_123110.tar.gz (+ .sha256)
  admin0-backups/py-xiaozhi-pre-monorepo.bundle         ← verified git bundle (main + tag)
Pre-migration full workspace snapshot: admin0-backups/admin0_pre_20261007_120737.tar.gz
Rollback = restore from these paths; the monorepo itself can be reverted with `git revert`/`git reset` per the PO's
decision (the root repository is local-only, so no remote coordination is involved). No NAS rollback is needed.
```

## 10. Final acceptance

```
A_GIT_HISTORY = PASS · B_SOURCE_INTEGRITY = PASS · C_SECURITY = PASS · D_LICENSE = PASS
E_FINAL_REVIEW = PASS (0 blockers · 0 majors · 4 minors corrected · correction re-check PASS)
MONOREPO_MIGRATION_ACCEPTED = A + B + C + D + E all PASS
```