# MONOREPO MIGRATION — AGENT B: SOURCE HASH / ZERO-DRIFT AUDIT (READ ONLY)

- Date: 2026-10-07
- Auditor: Agent B (independent, read-only)
- Repository root: `<project-root>` (root repo, branch `main`)
- Trees under audit: `client/` (← `py-xiaozhi/`), `gateway/` (← `rtl-lab/`), `deploy/legacy-xiaozhi/` (← sanitized `nas-deploy/`)
- Baseline: `docs/admin0/baseline-manifest.sha256` (950 lines; generated `20261007_120737`)
- Constraint honoured: no file, git state, container or config was modified. The only file written is this report. No secret values are printed.

---

## 0. Scope & method

Every claim below is mechanical: `sha256` of the source file vs the destination file (or vs the recorded baseline hash), with literal-filename handling (`git -c core.quotepath=false`) so non-ASCII paths hash correctly. All counters are computed over the exact file sets stated in each section.

Tooling note: `sha256sum` (`/sbin/sha256sum`) is used with stdin redirection (`sha256sum < FILE`) to avoid quoting issues on CJK filenames.

---

## 1. `client/` vs `py-xiaozhi/` (subtree import) — PASS

### 1.1 Pre-conditions

```
git -C py-xiaozhi rev-parse HEAD        # fed48362c65b92a9fb8464aa51ebff4488979d2c
git -C py-xiaozhi status --porcelain | wc -l   # 0
git -C py-xiaozhi log --oneline -2
```

```
fed4836 feat(client): freeze accepted R-1f rev-9 playout telemetry instrumentation
9bfc807 chore: release v2.1.2
```

`git -C py-xiaozhi ls-files -s` mode histogram: `811 × 100644`, `4 × 100755`, `1 × 120000` (symlink) = **816 tracked entries**.
The baseline manifest recorded 814 tracked entries at HEAD `9bfc807` (pre-freeze); the freeze commit `fed4836` promoted 2 previously-untracked files to tracked and modified 5 (`git diff --name-status 9bfc807 fed4836` → 6 × `M`, 1 × `A`, all under `src/`).

### 1.2 Hash comparison

Command (all 816 `ls-files` entries):

```
for path in $(git -C py-xiaozhi -c core.quotepath=false ls-files); do
  # skip symlink / non-regular; else compare sha256 < py-xiaozhi/<p> vs client/<p>
done
```

Trimmed output:

```
NONFILE(symlink both): documents/docs/zh/guide/images
COMPARED=815 MISMATCH=0 MISSING=0 NONFILE=1
```

**Result: 815 regular files compared, 0 mismatches, 0 missing.** The single non-file entry is the symlink `documents/docs/zh/guide/images -> ../../guide/images`, present and identical as a symlink on both sides.

### 1.3 Upstream quirk

`documents/docs/zh/guide/images` is a **symlink** (`120000`), not a regular file. It is **absent from the baseline manifest** (`grep -c 'documents/docs/zh/guide/images' docs/admin0/baseline-manifest.sha256` = `0`) — i.e. the manifest's "tracked files" section enumerated regular files only. This is the documented upstream quirk; it is not drift. (It is listed under §5 with no baseline counterpart.)

### 1.4 The 7 accepted R-1f client files

Command: `sha256sum < client/src/...` for each of the 7 accepted paths.

```
b489a282eea5f0f32e756f6e67340d78779d4a84534d5b4b68782666f93949cc  client/src/audio_codecs/audio_buffer.py
e4014df6b2f5731b43e8bb7ef4b4f1c1569aea90d03ac587d9a43f5c9efafb85  client/src/audio_codecs/audio_codec.py
314d6a72680e462eb827782492a8c4296b7e91c8d03cd6bf290333386748623d  client/src/audio_codecs/audio_converter.py
b02296817cc6b0398da3aa6b5f30631b4eefe4565982d68da1b80d1d26c6a944  client/src/audio_codecs/rtl_client_telemetry.py
60e726c8ad715c513a55809ce05e69944839a843eda58654d04b4768780414fd  client/src/audio_processing/aec_engine.py
8e2167186e77901bc23af3d43935568d860a44273701b888e7ed2cb9b606de4e  client/src/bootstrap/session.py
d46d3e3c8153958d0fb3c0ffdb500374896a74eebd4bd63b9c7576fda20a6da0  client/src/core/protocol_manager.py
```

All seven **exactly match** the accepted R-1f prefix set (`b489a282…`, `e4014df6…`, `314d6a72…`, `b0229681…`, `60e726c8…`, `8e216718…`, `d46d3e3c…`) and equal their `py-xiaozhi/` counterparts byte-for-byte.

### 1.5 Freeze integrity

`client/` content is byte-identical to `py-xiaozhi/` at HEAD `fed4836` (the freeze commit), and the `py-xiaozhi` worktree is clean (`status --porcelain | wc -l` = `0`). **No edit after the freeze commit.** Note also that the frozen client corresponds to the source tag `r1f-client-accepted` (cross-reference: Agent A report §1).

---

## 2. `gateway/` vs ADMIN-0 baseline (`rtl-lab/`) — PASS

Relocation map applied (see §5): `rtl-lab/<rel>` → `gateway/<rel>`; `rtl-lab/r1f-*.md` → `gateway/docs/<basename>`; **`rtl-lab/evidence/` excluded by the share boundary**.

Command:

```
# for every baseline path under rtl-lab/, remap and compare sha256 to gateway/...
for each baseline rtl-lab path: skip evidence/* ; target = gateway/[docs/]rel ; compare
```

Trimmed output:

```
GATEWAY IMPORTED=42 EXCLUDED=50 MISMATCH=0 MISSING=0
```

Baseline `rtl-lab/` section = 92 entries = **42 imported/verified** (`app/` ×10, `config/config.json`, `docker-compose.yml`, `Dockerfile`, `r1f-*.md` ×15, `README.md`, `tests/assets/*.raw` ×3, `tests/*.py` ×10) + **50 excluded-by-design** (all under `evidence/`). **0 mismatch, 0 missing.** The 50 `evidence/` entries are intentionally excluded by the share boundary and are not part of the imported gateway tree.

---

## 3. `deploy/legacy-xiaozhi/` vs sanitized `nas-deploy/` — PASS

Command:

```
for f in .env.example compose_all.template.yml docker-compose_all.yml docker-compose.yml; do
  compare sha256(deploy/legacy-xiaozhi/$f) vs sha256(nas-deploy/$f)
done
```

Trimmed output:

```
OK   .env.example             514ff131a4a2555fbdffb7f76458513c7dcae4bd17c33f2275852f3c78b0e0a9
OK   compose_all.template.yml 0430aa28b1cf96801ff7f6893ad48e54f9e5944ed0dcdaed98ee98a43ddd8f56
OK   docker-compose_all.yml   0430aa28b1cf96801ff7f6893ad48e54f9e5944ed0dcdaed98ee98a43ddd8f56
OK   docker-compose.yml       6d166c06772467e3f6a47bbd863c06c23f3eafb6b71af74aea54b76308958472
DEPLOY COMPARED=4 MISMATCH=0
```

**4 files compared, 0 mismatches.** The two sanitized compose artifacts are byte-identical to each other (`cmp` → `IDENTICAL`), and both hashes and the `.env.example` hash match the values recorded before this migration (`0430aa28b1cf9680…` ×2, `514ff131a4a2555f…`). No mode normalisation was observed (all four are regular `-rw-r--r--`).

Note (out of scope but recorded for completeness): the baseline manifest's raw `nas-deploy` entries for `docker-compose_all.yml` (`bf20e716…`) and `compose_all.template.yml` (`99e87810…`) are pre-sanitization snapshots — the manifest was generated at `12:07:37`, before the `nas-deploy` sanitization (dir mtime `12:18`). The authoritative post-sanitization hashes above match. `deploy/legacy-xiaozhi/` intentionally carries only the 4 shared files (not `data/.config.yaml` or `monitor/`).

---

## 4. No runtime / config / model / constant drift — PASS

### 4.1 `gateway/app/turns.py` — locked pacing constants

```
MEDIA_FRAME_MS           = 20.0    # 20 ms frame
MIN_SEND_START_INTERVAL_MS = 15.0  # 15 ms reserve (anti-burst floor)
PACING_SLACK_MS          = 5.0     # 5 ms jitter/slack
```

Exactly 20 ms frame / 15 ms reserve / 5 ms jitter, per A.5. Hash:

```
MATCH   gateway/app/turns.py  06a41cf98492f49b31be103c9576b12087c1676a0c3126e81bd63acf222fad7a
```

### 4.2 `gateway/app/qwen.py` + `gateway/config/config.json`

Command/values:

```
DEFAULT_MODEL = "qwen3.8-omni-flash-realtime"   # qwen.py:36
DEFAULT_VOICE = "Tina"                          # qwen.py:37
config.json: "QWEN_MODEL": "qwen3.8-omni-flash-realtime", "QWEN_VOICE": "Tina", "QWEN_MODE": "mock", "FRAME_MS": 20
```

Real-mode semantics are intact: `QwenConfig.is_real == (mode == "real")`; `ready` requires `api_key` + `workspace_id` + `region == "cn-beijing"`; real mode is engaged purely via env/secret (`QWEN_MODE=real`, `QWEN_REALTIME_API_KEY`, `QWEN_REALTIME_WORKSPACE_ID`) — "switching from mock to real is a pure env/secret change with no code change" (module docstring). The committed `config.json` ships `QWEN_MODE="mock"` as the default (same as baseline); there is **no code/config change**.

Hashes:

```
MATCH   gateway/app/qwen.py        7568521304aa458b1b71f5719226baace93149fde31ea3abe72e09d4c15ad39f
MATCH   gateway/config/config.json 670c1c9dc88b77f1c2e3dcb88bc4d8731a71388be32c431c75b79ff5105883c3
```

All three values (model / voice / mode semantics) **equal the accepted R-1f values**.

### 4.3 No dependency / runtime version drift

- `client/`: `requirements.txt`, `uv.lock`, `pyproject.toml`, `.python-version` all hash-match the baseline py-xiaozhi entries (`66f483a6…`, `17a7ed22…`, `a8db112b…`, `7a41a413…`).
- `gateway/`, `deploy/legacy-xiaozhi/`: **no** requirements / lock / Pipfile / poetry / conda file exists (`find` for such names → empty). The gateway baseline (`rtl-lab/`) never carried one.
- `gateway/` contains exactly the 42 files mapped in §2 — no extra file beyond the baseline set plus the relocated `r1f-*.md` docs.

No new requirements/lock/version files were introduced in the imported trees.

---

## 5. Relocation map & files without a baseline counterpart

### 5.1 Relocation map (baseline path → repo path)

| Baseline (ADMIN-0) | Repo path | Verified |
|---|---|---|
| `py-xiaozhi/<p>` (tracked, 814 reg. + 1 symlink omitted) | `client/<p>` | sha256 equal (815/815) |
| `rtl-lab/<rel>` | `gateway/<rel>` | sha256 equal (42/42) |
| `rtl-lab/r1f-*.md` (15) | `gateway/docs/r1f-*.md` | sha256 equal |
| `rtl-lab/evidence/*` (50) | — (excluded by share boundary) | n/a |
| `nas-deploy/<f>` (4 shared files) | `deploy/legacy-xiaozhi/<f>` | sha256 equal (4/4) |
| `ref/config.yaml` | `docs/reference/config.yaml` | sha256 equal (`c5dcb389…`) |
| `deploy-log.md` | `docs/engineering/deploy-log.md` | content **updated** (see below) |
| root scripts (`run-*.sh`, `docker-group-grant*.sh`, `install-nas-key.sh`, `fix-nas-ssh-perms.sh`, `configure-secrets.sh`, `asr-probe.py`, `mic-local-test.py`) | `tools/<same>` | sha256 equal (10/10) |

Relocation-integrity command:

```
DIFF   docs/engineering/deploy-log.md  vs deploy-log.md (base=dfde5400… now=70d3c6cb…)
MATCH  docs/reference/config.yaml  ==  ref/config.yaml
MATCH  tools/run-client-gui.sh     ==  run-client-gui.sh
MATCH  tools/run-client-test.sh    ==  run-client-test.sh
MATCH  tools/run-mic-test.sh       ==  run-mic-test.sh
MATCH  tools/install-nas-key.sh    ==  install-nas-key.sh
MATCH  tools/docker-group-grant.sh ==  docker-group-grant.sh
MATCH  tools/docker-group-grant-v3.sh == docker-group-grant-v3.sh
MATCH  tools/fix-nas-ssh-perms.sh  ==  fix-nas-ssh-perms.sh
MATCH  tools/configure-secrets.sh  ==  configure-secrets.sh
MATCH  tools/asr-probe.py          ==  asr-probe.py
MATCH  tools/mic-local-test.py     ==  mic-local-test.py
```

- `docs/reference/config.yaml` and the 10 `tools/*` files **do have baseline counterparts** (they are byte-identical relocations of `ref/config.yaml` and the root-level scripts respectively) — contrary to the task's "expected no-counterpart" list. This is a **stronger** result, not drift.
- `docs/engineering/deploy-log.md` is a relocation whose content was **edited** after relocation (hash differs from baseline root `deploy-log.md`). It is a documentation/log artifact, not source/config/constant — see §6.

### 5.2 Files present in the new tree with NO baseline counterpart

Command (literal filenames, all root-repo tracked files, `git -c core.quotepath=false ls-files`):

```
NO-BASELINE: .gitignore
NO-BASELINE: NOTICE.md
NO-BASELINE: THIRD_PARTY_LICENSES.md
NO-BASELINE: client/documents/docs/zh/guide/images            # symlink (§1.3)
NO-BASELINE: deploy/legacy-xiaozhi/.env.example               # sanitization artifact
NO-BASELINE: docs/admin0/ADMIN-0-implementation-report.md
NO-BASELINE: docs/admin0/ADMIN-0-plan.md
NO-BASELINE: docs/admin0/admin-adapter-contract.md
NO-BASELINE: docs/admin0/baseline-manifest.sha256
NO-BASELINE: docs/admin0/license-attribution-plan.md
NO-BASELINE: docs/admin0/realtime-admin-security-contract.md
NO-BASELINE: docs/admin0/secret-hygiene-plan.md
NO-BASELINE: docs/admin0/share-boundary.md
NO-BASELINE: docs/admin0/source-migration-map.md
NO-BASELINE: docs/admin1/ADMIN-1-audit-report.md
NO-BASELINE: docs/admin1/raw-a-mac-source-trees.md
NO-BASELINE: docs/admin1/raw-b-nas-deployments.md
NO-BASELINE: docs/admin1/raw-cd-admin-capabilities-db.md
NO-BASELINE: docs/admin1/raw-ef-realtime-workbench.md
NO-BASELINE: docs/admin1/raw-gi-gaps-sourcetruth-licenses.md
NO-BASELINE: modules/adapters/README.md
NO-BASELINE: modules/intent/README.md
NO-BASELINE: modules/knowledge/README.md
NO-BASELINE: modules/memory/README.md
TRUE_UNMAPPED_TOTAL=24
```

These are exactly the expected scaffold/administrative set: root scaffold (`.gitignore`, `NOTICE.md`, `THIRD_PARTY_LICENSES.md`), the admin doc trees (`docs/admin0/*`, `docs/admin1/*`), the module scaffold READMEs (`modules/*/README.md`), plus two benign extras:
- `client/documents/docs/zh/guide/images` — the upstream symlink quirk (§1.3).
- `deploy/legacy-xiaozhi/.env.example` — a sanitization artifact (a new, sanitized env sample; not part of the raw baseline `nas-deploy` listing).

(`tools/`, `docs/reference/config.yaml`, `docs/engineering/deploy-log.md` are correctly counted as relocations in §5.1, not as new files.)

### 5.3 Full coverage sweep — no source file missing

Command: map **every** non-evidence baseline path to its destination and assert existence.

```
BASELINE_MISSING_TOTAL=0
```

Every baseline path resolves to an existing file in the new tree. No source file is missing.

---

## 6. Verdict rationale

- `client/` == `py-xiaozhi/` (frozen `fed4836`): **815/815 regular files equal, 0 mismatch**; the 7 accepted R-1f files match exactly; worktree clean → no post-freeze edit.
- `gateway/` == baseline `rtl-lab/` (non-evidence): **42/42 equal, 0 mismatch**; 50 `evidence/` entries excluded by design.
- `deploy/legacy-xiaozhi/` == sanitized `nas-deploy/`: **4/4 equal, 0 mismatch**; hashes match the recorded sanitized values.
- Locked pacing constants (20 / 15 / 5 ms), model (`qwen3.8-omni-flash-realtime`), voice (`Tina`) and real-mode semantics are byte-identical to the frozen baseline (hashes `06a41cf9…`, `75685213…`, `670c1c9d…`). No dependency/lock/version file changed or was added.
- Only documentation/scaffold files are new; the one non-identical relocation is a doc log (`docs/engineering/deploy-log.md`), which is outside source/config/constant scope.

No real content drift, no missing source file, no changed constant/model/provider were found.

---

## 7. Read-only compliance

```
git status --porcelain   # ?? docs/engineering/audits/   (this report only)
```

No tracked file, git state, container or config was modified. No secret values were read out or printed.

B_SOURCE_INTEGRITY = PASS