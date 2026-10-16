# AGENT E — FRESH FINAL REVIEW (monorepo migration)

Reviewer: Agent E (new, independent, no prior context). Mode: **READ ONLY** — the only file written is this report.
Date: 2026-10-07 · Workspace: `<project-root>` · Root repo `main`, local-only.

Verdict summary: every load-bearing claim in the migration brief was **independently reproduced** with my own
commands/reads. No blocker, no major. A few MINOR accuracy/transparency items and several INFO notes are recorded
below. `E_FINAL_REVIEW = PASS`.

---

## 1. Git history & state (independently sampled)

`git log --graph --oneline -12`:

```
* 6ffabc4 docs: organize approved documentation (admin0, admin1, engineering, reference) + tools
* b379cec modules: scaffold ownership boundaries (adapters, intent, memory, knowledge)
* 1abc74b deploy: import sanitized legacy-stack deployment source
* 561bd80 gateway: accepted R-1f baseline import (source-only, no runtime modification)
*   3e22a4d client: import py-xiaozhi source with locally available history
|\
| * fed4836 feat(client): freeze accepted R-1f rev-9 playout telemetry instrumentation
| * 9bfc807 chore: release v2.1.2
* 303d0d3 admin0: monorepo foundation — share boundary, attribution, approved documentation
```

- `git remote -v` → **empty** (no remote). ✔ local-only.
- `git config --local --list` → only `core.*` defaults; `user.name`/`user.email` local **and** global are **empty**.
  Author/committer of the six new commits = `monorepo-migration <monorepo@local>`; the imported commits keep their
  original identity (`admin0-freeze`, `huangjunsen`). ✔ **per-command identity only, no git config change.**
- SHAs: `303d0d3…` = `303d0d343ac98d20dd7c6dc8eebea476c3ac8a09`, `3e22a4d…` = `3e22a4de0c3f7a3393526a7092c545ed9fb0528f`,
  `561bd80…`/`1abc74b…`/`b379cec…`/`6ffabc4…` all present on `main` — match the brief.
- `git rev-list --parents -n1 3e22a4d…` → `3e22a4d 303d0d3 fed4836` ⇒ **true two-parent merge** (`303d0d3` + `fed4836`),
  no squash/rebase. ✔
- `git rev-parse HEAD:client` = `425589fbae0e5e7f34d4a4b3718d1be3bb56e6d9` = `fed4836^{tree}` ⇒ client subtree byte-identical
  to the accepted source tree. ✔
- `git merge-base --is-ancestor fed48362c65b92a9fb8464aa51ebff4488979d2c HEAD` → **reachable**. ✔ (SHA unchanged, not rewritten.)
- `git tag -l` → `r1f-client-accepted`, `v2.1.2`. `git rev-list -n1 r1f-client-accepted` = `fed4836…`. ✔
- `git ls-files | wc -l` = **896**. ✔ matches report §5.
- Only branch `main`; `git stash list` empty; `git reflog --all` shows **only** `commit`/`commit (merge)` entries
  (no reset/rebase/rewrite). `.git/shallow` = `9bfc807d368cccac71af8d9f7042ab6b5af92030` ⇒ shallow repo declared at the
  imported boundary. ✔ documented/expected.

`git status --porcelain` (every entry seen):

```
 M NOTICE.md
 M THIRD_PARTY_LICENSES.md
 M docs/engineering/deploy-log.md
 M tools/run-client-gui.sh
 M tools/run-client-test.sh
 M tools/run-mic-test.sh
?? docs/engineering/MONOREPO-MIGRATION-REPORT.md
?? docs/engineering/audits/monorepo-agent-a-git-history.md
?? docs/engineering/audits/monorepo-agent-b-source-integrity.md
?? docs/engineering/audits/monorepo-agent-c-security.md
?? docs/engineering/audits/monorepo-agent-d-license.md
```

## 2. Bundle & rollback area

- `git bundle verify admin0-backups/py-xiaozhi-pre-monorepo.bundle` → **"is okay"**, refs `fed4836… refs/heads/main`
  + `b12fd407… refs/tags/r1f-client-accepted`, "records a complete history". Mode `600`, size `61 062 573 B`. ✔ (matches report byte-for-byte.)
- `admin0_pre_monorepo_20261007_123110.tar.gz` mode `600`, size `127 977 509 B`; `.sha256` present (mode 644). Full-workspace
  `admin0_pre_20261007_120737.tar.gz` (600, `127 936 000 B`) also present.
- `stat -f '%Sp %OLp %N'`: `admin0-backups` = **700**, `admin0-backups/pre-monorepo-originals` = **700**;
  the three retired subtrees themselves are `755` but sit behind the 700 parent ⇒ **effectively private** (see INFO 3).
- `git -C admin0-backups/pre-monorepo-originals/py-xiaozhi log -1 --format=%H` = `fed48362c65b92a9fb8464aa51ebff4488979d2c`;
  tags there = `r1f-client-accepted`, `v2.1.2`; worktree clean. ⇒ `.git` intact, rollback real. ✔
- Tree content sizes: `py-xiaozhi` 1.6 G (incl. `.git`/`.venv`), `rtl-lab` 13 M (incl. `evidence/`+`secrets/`), `nas-deploy` 44 K. ✔
- The pre-migration `ref/config.yaml` is present in the snapshot tar (`ref/config.yaml`) — see MINOR 4 provenance.

## 3. Byte-identity re-hashes (I chose the files)

| active path | retired counterpart | sha256 (both sides) | match |
|---|---|---|---|
| `client/src/core/protocol_manager.py` | `pre-monorepo-originals/py-xiaozhi/src/core/protocol_manager.py` | `d46d3e3c8153958d…` | ✔ |
| `gateway/app/turns.py` | `pre-monorepo-originals/rtl-lab/app/turns.py` | `06a41cf98492f49b…` | ✔ |
| `deploy/legacy-xiaozhi/docker-compose_all.yml` | `pre-monorepo-originals/nas-deploy/docker-compose_all.yml` | `0430aa28b1cf9680…` | ✔ |
| `gateway/app/qwen.py` | `pre-monorepo-originals/rtl-lab/app/qwen.py` | `7568521304aa458b…` | ✔ |
| `gateway/tests/assets/u1.pcm16k.raw` | `pre-monorepo-originals/rtl-lab/tests/assets/u1.pcm16k.raw` | `6514eb3d6a0f7125…` | ✔ |
| `gateway/tests/assets/u{2,3}.pcm16k.raw` | same | `d28c04e2…` / `78c1de0a…` | ✔ |
| `gateway/docs/r1f-design-review.md` | `pre-monorepo-originals/rtl-lab/r1f-design-review.md` | `47c82557f5543bb7…` | ✔ |
| `client/LICENSE` | `pre-monorepo-originals/py-xiaozhi/LICENSE` | `49ddd0fdc520a6e9…` | ✔ |

- All 4 deploy files against `nas-deploy`: `compose_all.template.yml`, `docker-compose_all.yml`, `docker-compose.yml`
  all **MATCH**; `.env.example` sha256 `514ff131a4a2555f…` (matches report). ✔
- **client tree list**: `git ls-files client/` vs `git -C …/py-xiaozhi ls-files` → **816 = 816, comm empty both ways** (byte-identical
  file set; 815 regular + 1 symlink). ✔

## 4. Locked constants / model / provider / voice (re-derived by me)

From `gateway/app/turns.py`: `MEDIA_FRAME_MS = 20.0`, `MIN_SEND_START_INTERVAL_MS = 15.0`, `PACING_SLACK_MS = 5.0`
(lines 32–34) — **frame 20 ms / reserve 15 ms / slack 5 ms**. ✔ matches accepted R-1f values.

From `gateway/app/qwen.py`: `DEFAULT_MODEL = "qwen3.8-omni-flash-realtime"`, `DEFAULT_VOICE = "Tina"`,
`is_real` ⇔ `mode == "real"` (lines 36–37, 76–77). `gateway/config/config.json`: `QWEN_MODE=mock`,
`QWEN_MODEL=qwen3.8-omni-flash-realtime`, `QWEN_VOICE=Tina`, `FRAME_MS=20`, no secrets. ✔ unchanged vs accepted R-1f.

## 5. Secret / private-material scan (tracked set = 896 files)

- Zero tracked paths under `secrets|logs|config-backups|admin0-backups|rtl-lab-backups|rtl-lab/evidence|.workbuddy|py-xiaozhi|nas-deploy`. ✔
- Zero tracked `*.env` other than `*.env.example`. ✔ `git grep 'BEGIN … PRIVATE KEY'` → **none**. ✔
- `deploy/legacy-xiaozhi/**`: no literal credential; only `${VAR}` references and exactly **3** `change_me_*` placeholders
  in `.env.example` (mysql_root / druid_db / redis). ✔
- Non-placeholder credential scan (POSIX `[[:space:]]`, since `git grep -E` does **not** honour `\s`) → only these flagged:
  - `docs/reference/config.yaml:140` `api_key: "a861d0d5…"` (qweather) — file comment states it is the **project-shared** key. See MINOR 4.
  - `client/documents/docs/{,zh/}guide/配置说明.md` `hmac_key` 64-hex inside an upstream `efuse.json` **example** (fake MAC `00:11:22:33:44:55`). Upstream doc content. See MINOR 4.
  - `gateway/app/qwen.py:123` `secret = _read_secret_file(...)` — code, not a literal.
- The 407 tracked `*.wav` are all under `client/assets/sounds/` (UI sounds); the only synthetic audio = `gateway/tests/assets/u{1,2,3}.pcm16k.raw`. ✔
- `r1f_ht_*` / learner transcript / `.jsonl` telemetry → **0 tracked**. ✔

## 6. Layout vs the authorised target

Present and correct: `client/ gateway/ modules/{adapters,intent,memory,knowledge} deploy/legacy-xiaozhi/`
`docs/{admin0,admin1,engineering}` + root `.gitignore THIRD_PARTY_LICENSES.md NOTICE.md`.

- `docs/admin0/` (9 files) and `docs/admin1/` (6 files) present. ✔
- `docs/engineering/deploy-log.md` is the **single active copy**; no root `deploy-log.md`. ✔ (working-copy entry 79 = the migration.)
- Additions beyond the authorised layout: `tools/` (11 root helper scripts), `docs/reference/` (upstream `config.yaml` sample,
  58 155 B), `gateway/docs/` (15 `r1f-*.md`). These are **acceptable**: they relocate pre-existing root helpers/upstream
  reference material rather than introduce product code, and the gateway docs are the design/review trail belonging to the
  imported gateway. Nothing required is missing.

## 7. Non-vendoring

- No workbench/IELTS content and no manager-api/server source tracked: the only hits are documentary
  (`docs/admin1/raw-ef-realtime-workbench.md`). Legacy admin/server appear only as **image references**
  (`ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:*`, `mysql:*`, `redis:8.0`) in `deploy/legacy-xiaozhi/*.yml`. ✔
- No nested `.git` under `client gateway modules deploy tools docs` (find → none); no `.gitmodules`. ✔
- No runtime artefacts tracked (`.DS_Store`=0, no `*.log`/`__pycache__`/`.venv`/`node_modules`). Only commented/expected
  hits: `client/src/audio_codecs/rtl_client_telemetry.py` (R-1f source) and `gateway/docs/r1f-human-test-closeout.md` (doc). ✔

## 8. NAS / Workbench non-change (read-only `docker inspect`)

| container | StartedAt | Restarts |
|---|---|---|
| xiaozhi-rtl-bridge | 2026-10-06T18:41:10.230297191Z | 0 |
| english-learning-workbench-web | 2026-10-04T01:56:08.229431871Z | 0 |
| english-learning-workbench-sync | 2026-10-05T02:22:46.41169099Z | 0 |
| xiaozhi-full-server | 2026-10-05T14:17:14.15003284Z | 0 |
| xiaozhi-full-web | 2026-10-05T13:05:07.410415404Z | 0 |
| xiaozhi-full-db | 2026-10-05T02:22:33.87243142Z | 0 |
| xiaozhi-full-redis | 2026-10-05T02:22:33.873377572Z | 0 |
| xiaozhi-esp32-server | 2026-10-05T01:39:35.933633109Z | 0 |
| word-master | 2026-10-06T05:02:58.234653485Z | 0 |
| <legacy-platform> | 2026-10-02T01:46:15.1365145Z | 0 |

All three expected values (lab, workbench-web, workbench-sync) reproduced **exactly**; all `Restarts=0`. ⇒ **no container
was restarted; Workbench not modified.** ✔

## 9. Findings

### BLOCKERS — none.
### MAJORS — none.

### MINORS
1. **Incomplete licence-path correction.** Report finding #6 says `NOTICE.md`/`THIRD_PARTY_LICENSES.md` were corrected to
   `client/`. In fact `NOTICE.md:13` still says the upstream MIT text is "retained verbatim at `py-xiaozhi/LICENSE`", and
   `THIRD_PARTY_LICENSES.md:16,18` still cite `py-xiaozhi/LICENSE`. The tracked file is now `client/LICENSE`
   (`py-xiaozhi/` no longer exists in the active repo). Documentation-only, but the stated correction is partial.
2. **Two extra uncommitted files vs the brief's enumeration.** In addition to the report, the four A–D audits, `deploy-log.md`
   and the three `tools/*.sh`, `NOTICE.md` and `THIRD_PARTY_LICENSES.md` are also modified-but-uncommitted. They correspond to
   the finding-#6 corrections and will be swept up with the rest; noting for completeness ("only delta" framing was slightly narrow).
3. **Stale retired path in a moved helper.** `tools/configure-secrets.sh:5` still references
   `~/Desktop/小智/nas-deploy/data/.config.yaml` (Rollback comment). Only the three `run-*.sh` were patched; this helper
   still points at the retired `nas-deploy/` tree.
4. **Security-label precision.** The tracked set contains two upstream-**public** non-placeholder credentials that a naive
   scan (and the report's "all categories 0" wording) does not surface: `docs/reference/config.yaml:140` qweather
   `api_key` (its own comment calls it "项目共用的key"/project-shared) and an example `hmac_key` in
   `client/documents/docs/…/配置说明.md`. Both are upstream content, **not operator private credentials**, so the "no private
   secret" claim holds — but Agent C / report §5 should have enumerated them explicitly.

### INFO
1. **Tag object, not commit, differs.** Root annotated tag `r1f-client-accepted` object = `8313e16838d8959e5a479fae1f83ed3a6600753a`
   (tagger `monorepo-migration <monorepo@local>`), whereas the source/bundle tag object = `b12fd407…`. Both point to the
   **unchanged** commit `fed4836…`; the report honestly discloses `8313e168…`. Only the annotated-tag byte identity (not the
   commit) differs from upstream.
2. `git fsck` reports a single dangling blob `53b6793…` — harmless residue of the intermediate `.gitignore` edit (finding #2).
3. Retired subtrees are `755` inside a `700` parent ⇒ reachable only by the owner; report's "directory 700" is accurate for the area dirs.
4. Imported files retain historical path strings (`gateway/app/turns.py:3` → `rtl-lab/…`; `gateway/tests/r1f_client_tests.py:6`
   → `py-xiaozhi/…`). These are inside **byte-identical** imported files and must not change; covered by finding #7.
5. `tools/run-mic-test.sh` has no trailing newline; the two compose copies remain byte-identical (report finding #9).

---

## 10. Independent verdict

All nine principal claims of the brief were reproduced by my own commands/reads and hold. The only substantive gaps are
documentation-accuracy items (MINOR 1/3) and transparency items (MINOR 2/4), none of which affect source integrity,
security, history, or the environment.

```
E_BLOCKERS = 0
E_MAJORS   = 0
E_MINORS   = 4
E_FINAL_REVIEW = PASS
```

---

## 11. Post-correction re-check (findings-scoped corrections)

Read-only re-verification of the Lead's findings-scoped corrections. Only this report was written.

**C1 — retired `py-xiaozhi/LICENSE` path removed.** `grep -n 'py-xiaozhi' NOTICE.md` now returns only line 11
("A fork of py-xiaozhi … `client/`") and line 12 (upstream URL `github.com/huangjunsen0406/py-xiaozhi`); line 13 now reads
"retained verbatim at `client/LICENSE`". `THIRD_PARTY_LICENSES.md` lines 14–15 are the heading + upstream URL, and lines
15/17 now cite `client/LICENSE`. ⇒ **zero** remaining refs to the retired `py-xiaozhi/LICENSE`; the surviving `py-xiaozhi`
mentions are intentional project/upstream-identity wording. `client/LICENSE` exists (sha256 `49ddd0fdc520a6e9…`, unchanged). ✔

**C2 — helper rollback path corrected and real.** `tools/configure-secrets.sh:6` now points at
`~/Desktop/小智/admin0-backups/pre-monorepo-originals/nas-deploy/data/.config.yaml` (with a note that runtime data was not
imported per the share boundary). No `nas-deploy/**` active-repo reference remains. The target exists:
`admin0-backups/pre-monorepo-originals/nas-deploy/data/.config.yaml` (660 B). ✔

**C3 — report §5 disclosure.** `MONOREPO-MIGRATION-REPORT.md` §5 now explicitly discloses (lines 83–87) that
`docs/reference/config.yaml` (upstream XiaoZhi sample config) carries one 32-hex value its own comment marks as a
**shared upstream sample key** — i.e. upstream reference material, not our private credential. The reference config's own
comment ("这个密钥是项目共用的key / 想稳定一点就自行申请替换") confirms the disclosure is **accurate**. The 407 client UI
`*.wav` clarification is present. ✔

**C4 — uncommitted delta is exactly the expected set.** `git status --porcelain --untracked-files=all`:

```
 M NOTICE.md
 M THIRD_PARTY_LICENSES.md
 M docs/engineering/deploy-log.md
 M tools/configure-secrets.sh
 M tools/run-client-gui.sh
 M tools/run-client-test.sh
 M tools/run-mic-test.sh
?? docs/engineering/MONOREPO-MIGRATION-REPORT.md
?? docs/engineering/audits/  (a-git-history, b-source-integrity, c-security, d-license, e-final-review)
```

Exactly the 7 modified + report + audits dir. **Nothing else changed** (`git diff --name-only` touches no
`gateway/ deploy/ client/ modules/` file). ✔

**C5 — load-bearing facts untouched.** `git ls-files | wc -l` = **896**; `git rev-list -n1 r1f-client-accepted` =
`fed48362c65b92a9fb8464aa51ebff4488979d2c`; `git remote -v` empty; `gateway/app/turns.py` = `06a41cf98492f49b…`
(== retired `rtl-lab/app/turns.py`); `client/src/core/protocol_manager.py` = `d46d3e3c8153958d…`
(== retired `py-xiaozhi/src/core/protocol_manager.py`). ✔

**C6 — no new secret/private material.** On the 7 modified + 2 new paths: `BEGIN … PRIVATE KEY` → none; non-placeholder
credential scan → none (the sole hit `deploy-log.md:104` is the historical `secret: REPLACE_AFTER_CONSOLE_REGISTRATION`
placeholder); learner hits in `tools/configure-secrets.sh` are the assistant persona prompt strings, not learner data/transcripts. ✔

**Result:** corrections complete, faithful, and impact-free. No source/config/constant/model/docker/environment change.
No new finding. Prior MINORS 1–4 are resolved; MINOR 2 is resolved by the corrected enumeration in C4.

```
E_BLOCKERS = 0
E_MAJORS   = 0
E_MINORS   = 0
E_FINAL_REVIEW = PASS
```