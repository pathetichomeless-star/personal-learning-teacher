# RED-I — Round 3 report (cross-check of repairs + new-leak hunt)

- **Agent:** RED-I (secret handling · log hygiene · filesystem permissions · build/deploy hygiene · public exposure)
- **Round:** 3 · **Date:** 2026-10-08 (Asia/Shanghai)
- **Role:** independent cross-checker of the fixes in `e3c9b6c` (round 1) and `b854778` (round 2); + hunt for leaks introduced by the repairs.
- **Mode:** read-only on product source; functional checks LOCAL `QWEN_MODE=mock` only; NAS read-only inspection.
- **Hard locks respected:** no real-Qwen driver run, no WS client opened against the NAS, no secret value printed/copied,
  primary/Workbench/MVP/legacy untouched, no NAS mutation, no product source edited.
- **Helpers (my scope):** `gateway/tests/adversarial/red_i/probe_round3.py`, `…/red_i/verify_dockerignore.py`
- **Report:** this file. No secret VALUE appears anywhere below — locations + shapes only.

---

## 1. CROSS-CHECK VERDICTS PER FIX

| # | Fix (claimed in `e3c9b6c`) | Verdict | Evidence (exact) |
|---|---|---|---|
| 1 | Backup archives containing secrets are mode 600 | **CONFIRMED** | `ls -la rtl-lab-backups/` → the r1b tarball (which still contains `rtl-lab/secrets/qwen-realtime.env`) is now `-rw-------`; sibling tarballs 600. `admin0-backups/*.tar.gz\|*.bundle` 600. `config-backups/*.json` **all** 600 — `config_backup_productv1_arm_…` moved 644→600 (**RED-I-02 closed**). |
| 2 | `.dockerignore` excludes the real-Qwen drivers | **CONFIRMED** | `python …/red_i/verify_dockerignore.py` → **PASS**: `tests/{spike_session_update,spike_vocab_matrix,mvp_real_smoke,r1f_real_probe,r1c_probe}.py` all excluded; `secrets/*`, `data/*` excluded; `tests/mock_qwen_server.py`, `app/main.py`, `modules/**`, `config/config.json`, `probe_product_v1.py` kept. (Docker unavailable here → pattern emulation for the staging layout; patterns are literal relative paths, so membership == match.) |
| 3 | `.gitignore` covers `docs/engineering/master-run/evidence/` | **WEAKENED (forward-only)** | New/untracked paths match (`.gitignore:38` → `git check-ignore -v --no-index <dir>/new.json` matches). **But the 7 already-committed evidence files remain tracked** — `.gitignore` cannot untrack committed files (`git ls-files docs/engineering/master-run/evidence/` still lists all 7). They are synthetic, so no metric impact; the rule protects only future additions. |

Not a "fix" but re-verified: nothing is staged (`git diff --cached` empty).

---

## 2. NEW CODE-PATH AUDIT (`_store_lock`, `PersistError`, normalize/fold, validation msgs, `errors[:50]`)

Live local instance (`QWEN_MODE=mock`, WS 29310 / HTTP 29311 / ADMIN 29312), fresh stores, captured response bodies **and** the full gateway log.

- **`PersistError` 500 path** — made the data dir read-only, then `POST /admin/knowledge/dataset/create`:
  response `500 {"error":"persist_failed","request_id":…}`; log:
  `admin persist failure in knowledge_dataset_create: knowledge persist failed`. `PersistError` messages are
  constant strings (`"… persist failed"`, `modules/{memory,knowledge}/store.py`, `modules/policy/persona.py`) →
  **no path, no value, no learner fact.** No sentinel/`/tmp/adv`/`/app/data`/`Traceback` in any body. **CLEAN.**
- **Old 500s fixed** — policy section type-confusion → `POST /admin/policy/preview` = `200 {"valid":false,"errors":["persona: object required"]}`;
  4000-deep persona → `POST /admin/policy/apply` = `400 {"error":"policy_invalid","errors":["policy: too deeply nested"]}`.
  Validation error strings carry **section/key/length only, never the rejected value**. **CLEAN.**
- **Boundary violation (secret-shaped value)** — seeded a benign memory item, then `POST /admin/memory/edit`
  with a synthetic secret-shaped value → `400 {"error":"boundary_violation","request_id":…}` (**no `detail`**) and
  **no** corresponding log line. The admin path never echoes the value. **CLEAN.**
- **`errors[:50]` cap** — present at `gateway/app/admin/api.py:91` (`list(e.errors)[:50]`); capped list contains no values. **CLEAN.**
- **normalize / fold helpers** — `fold_text`/`_screen`/`looks_secret`/`looks_like_progress` (`modules/memory/store.py`)
  and `_norm`/`_norm_text` are pure functions with **zero logging**; `modules/intent/behavior.py` added a comment only. **CLEAN.**
- **`<store>.lock` files** — after a write, `data/` contains `memory.json.lock`, `knowledge.json.lock`,
  `policy.json.lock`: **size 0 (empty)**; the store JSONs are 600 while the lock files are **mode 0644**. See finding RED-I-R3-02.
- **New warnings** — `store file lock unavailable (%s)`, `memory/knowledge flush failed: %s`, `*_disk read-back failed: %r`
  log the **exception**, which for an `OSError` is the store/tmp path (e.g. `…/knowledge.json.<hex>.tmp`) — a
  **data-store path, not a secrets path, and never a value**. **CLEAN** on my surface.

---

## 3. NEW FINDINGS

### RED-I-R3-01 — MINOR · Conversation path logs the rejected key/value of a boundary violation (PRE-EXISTING, not a regression)
- **Location:** `gateway/app/behavior.py:284` — `log.warning("memory boundary violation refused: %s", e)`.
- **Shape:** `e` is a `BoundaryViolation`; the messages in `modules/memory/store.py` `_validate_key`/`save_preference`
  embed **`%r` of the rejected key** (e.g. `"… secret/progress-shaped key refused: %r" % key`,
  `"closed preference key set %r does not include %r" % (…, key)`). A learner-sourced memory "save" whose **key**
  is secret-shaped would therefore write that key into the log.
- **Expected:** a rejected secret-shaped string is never persisted or logged.
- **Actual:** the raw key is interpolated into the log line. The **value** is generally not included (the secret-value
  branch is a constant string), so the exposure is limited to a secret-shaped *key*.
- **Provenance:** `git blame gateway/app/behavior.py:284` → `b7020586` (pre-fix); the file is **byte-identical**
  across `387ffcc..HEAD` (`git diff --stat 387ffcc..HEAD -- gateway/app/behavior.py` is empty) → **not introduced by
  the repairs.** Reporting it because it is on my surface; flagging provenance so it is not mis-scored as a regression.
- **Status:** open.

### RED-I-R3-02 — INFO · New `<store>.lock` files are mode 0644 (empty)
- **Location:** `modules/_store_lock.py:54` (`open(self.lock_path, "a+")`) → `<store>.lock` next to each store file.
- **Shape:** three files, **0 bytes**, mode **0644** (default umask), created in the data dir.
- **Expected/actual:** no content ever written (the fd is only used for `flock`), so there is **no data leak**; but the
  mode is inconsistent with the 600 store JSONs. Harmless in the deployment because the data dir is `700 uid 10001`.
- **Status:** accepted / INFO.

### RED-I-R3-03 — INFO · Secret-shaped literals in upstream example/reference docs (PRE-EXISTING, missed in round 1)
- **`docs/reference/config.yaml:140`** — `plugins.get_weather.api_key` = a **32-hex** literal. Its own comment and
  `docs/engineering/MONOREPO-MIGRATION-REPORT.md:83` state this is the upstream XiaoZhi **shared/demo QWeather key**
  ("项目共用的key"; rate-limited) — *explicitly disclosed, not a private secret*.
- **`client/documents/docs/guide/配置说明.md:684` (and the `zh/guide` twin)** — a sample `efuse.json` containing a
  **64-hex** `hmac_key`, alongside a placeholder MAC `00:11:22:33:44:55` and a sample serial → documentation sample.
- **Assessment:** neither is a confidential credential of this product; both are copied upstream example docs.
  Reporting location + shape only (values not reproduced). Not introduced by the repairs. No confidential secret is
  committed → `SECRET_LEAKS` unchanged (0). Adjacent pre-existing, non-secret noise: `client/README*.md` carries the
  upstream author contact email (not learner data).

### RED-I-R3-04 — INFO · The DEPLOYED sidecar runs an image older than the fixed tree
- **Evidence:** `docker image inspect … Created = 2026-10-08T01:34:45+08:00`; the repairs landed in `e3c9b6c`
  (~02:16) / `b854778`. The running container has been up ~53 min from that pre-repair image.
- **Effect:** the hygiene fixes are **source/build-level only and are NOT yet active in the deployed artifact** — the
  running image still ships the real-Qwen drivers (RED-I-04 not remediated in the artifact), still contains the old
  `api.py`. No rebuild/redeploy was performed (out of scope, and forbidden). **This does not change any metric verdict**
  below; it means the deployment has not yet picked up the fixes.

---

## 4. METRIC VERDICTS (re-proven)

| Metric | Verdict | Re-proof |
|---|---|---|
| `SECRET_LEAKS = 0` | **HOLDS** | 0 confidential secrets in all git-tracked files (only the two upstream demo/sample literals, RED-I-R3-03, INFO); 0 across all 37 commits of history; 0 in image `docker history`/`Config.Env`; 0 in NAS container logs (121 lines: 0 hex≥32, 0 token, 0 secret path, 0 traceback); 0 in ~30 new-path admin responses; 0 in the gateway log (no sentinel/secret-shape). Corollary: **the repairs introduced NO new secret leak.** One narrow pre-existing log echo path (RED-I-R3-01). |
| `REAL_LEARNER_DATA_COMMITTED = 0` | **HOLDS** | New files scanned (`modules/_store_lock.py`, `gateway/tests/adversarial_repair_tests.py`, `gateway/tests/adversarial/**`, `docs/engineering/product-v1/adversarial/**`) contain only synthetic fixtures (e.g. `DO_NOT_LEAK` tokens, `sk-proj-ABC123456789`, a 32-hex `hex_blob_no_keyword`) and prose; no real transcript/learner data/PII (only the upstream author email in `client/README*`). |
| `PUBLIC_EXPOSURE = 0` | **HOLDS** | NAS ports still `0.0.0.0:28310/28311/28312` on the LAN host; admin still token-gated (anonymous → 401); no NAS mutation; unchanged from round 1. |

**Did the repairs introduce any new leak or new world-readable artifact?**
- **New secret leak: No.**
- **New world-readable artifact: yes, one footprint** — empty `<store>.lock` files at mode 0644 (RED-I-R3-02). No
  secret-bearing file is world-readable anymore: the r1b backup tarball is 600, all `config-backups/*.json` are 600,
  NAS `secrets/*` are 600 and `data/` is 700. Residual 644 non-secret files (unchanged, not in fix scope):
  `rtl-lab-backups/*.bak.md` (design reviews), `admin0-backups/*.sha256` (checksums), `logs/*.log` (grep-clean).

---

## 5. NAS RE-INSPECTION (read-only)

- `/volume1/docker/xiaozhi-product-v1/` 755 (uid NAS-admin); `secrets/` dir 755 with `product_v1_admin_token`
  (64-hex-shaped) and `qwen-realtime.env` both **600, uid 10001**; `data/` **700, uid 10001** (not listable by the ssh
  user → no world-readable file inside observable). Unchanged by the repairs.
- Container: `Config.User=10001`. Logs: 0 hex≥32, 0 transcript/role, 0 traceback, 0 secret path, 0 lock/store path.
- **Image predates the fixes** (RED-I-R3-04).

## 6. COVERAGE / NEGATIVES
- Tracked secret-shape scan (`sk-`, `AKIA`, `ghp_`, `-----BEGIN…PRIVATE KEY-----`, long `Bearer …`) → only test
  fixtures/placeholders; history sweep (all commits) → nothing.
- Key-name=value literal scan → only the two upstream demo/sample docs (RED-I-R3-03) and code references.
- 64-hex scan → docs sha256 digests + the one sample `hmac_key`; 40-hex → lockfile integrity hashes.
- New-path responses (policy preview/apply, memory edit, PersistError, malformed/oversized) → 0 sentinel/path/traceback echo.
- `verify_dockerignore.py` → PASS (build-context claim reproducible without docker).
- `git status` → only my two `red_i/` helper files (plus sibling round-3 files); no product source modified.

## 7. PATHS WRITTEN
- `docs/engineering/product-v1/adversarial/reports/red_i-round3.md` (this report)
- `gateway/tests/adversarial/red_i/probe_round3.py`
- `gateway/tests/adversarial/red_i/verify_dockerignore.py`
- Runtime scratch (non-product): `/tmp/adv/red_i3/`
