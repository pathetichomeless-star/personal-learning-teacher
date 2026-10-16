# RED-I — Round 1 report (Secrets / Logs / Filesystem / Deployment)

- **Agent:** RED-I (secret handling · log hygiene · filesystem permissions · build/deploy hygiene · public exposure)
- **Round:** 1 · **Date:** 2026-10-08 (Asia/Shanghai)
- **Target:** Product V1 test sidecar (NAS `xiaozhi-product-v1-sidecar`) + local mock instance
- **Mode:** read-only on product source; functional checks LOCAL `QWEN_MODE=mock` only; NAS inspected read-only.
- **Hard locks respected:** no real-Qwen driver run, no WS client opened against the NAS, no secret value printed/copied,
  primary `xiaozhi-rtl-bridge` / Workbench / MVP sidecar / legacy stack untouched, no NAS mutation.
- **Report file:** this file. **Helper script:** `gateway/tests/adversarial/red_i/probe_secrets_logs.py`

Secret values are referenced only by role ("the admin token", "the Qwen key"). No value is printed anywhere.

---

## METRIC VERDICTS (falsification summary)

| Metric | Verdict | Falsification attempt / evidence |
|---|---|---|
| `SECRET_LEAKS = 0` | **HOLDS on every product surface (0)** · one non-product artifact exposure: **RED-I-01** | See "Falsification detail" below. 0 secrets in git-tracked files, git history (all 35 commits), image layers/`docker history`, image `Config.Env`, container logs, admin error responses, admin UI shell. |
| `REAL_LEARNER_DATA_COMMITTED = 0` | **HOLDS (0)** | Only synthetic assets/probes are committed (`gateway/tests/assets/u{1,2,3}.pcm16k.raw`, `docs/.../evidence/*`). No `user_state*`, `knowledge_private/`, `*.db/*.sqlite`, transcript-with-learner files are tracked; `.gitignore` covers them. |
| `PUBLIC_EXPOSURE = 0` | **HOLDS (0, LAN-only)** | Ports 28310/28311/28312 published to the host; host is a LAN NAS with no observed WAN mapping; admin surface token-gated (anonymous → 401 on all routes); admin surface absent on the audio HTTP app (404). Intended exposure documented (RED-I-05). |

### Falsification detail

**SECRET_LEAKS** — I tried, and failed, to make a secret leak on each surface:
1. **Tracked files:** searched every tracked file for `sk-…{16,}`, `AKIA…`, `BEGIN … PRIVATE KEY`, and
   `(bearer|authorization|password|secret|token)[…]={12,}`. Only hits are **test fixtures** (e.g.
   `gateway/tests/admin1_tests.py` `FIX_TOKEN = "TEST_BEARER_TOKEN_DO_NOT_LEAK_…"`) and **placeholders**
   (`deploy/legacy-xiaozhi/.env.example` `change_me_*`). 0 real secrets. (command: `git grep -nIE 'sk-[A-Za-z0-9_-]{16,}'` etc.)
2. **Git history:** `git grep -nIE '<key shapes>' $(git rev-list --all)` across all 35 commits → **0**.
3. **Image / build context:** NAS `docker history --no-trunc` shows only base-python + `libopus` + `pip install` +
   `COPY {app,modules,config,tests,admin-ui}` + probe; `docker image inspect .Config.Env` has **no secret**;
   `.dockerignore` excludes `secrets` and `data`. 0 secrets baked.
4. **Container logs (NAS):** `docker logs xiaozhi-product-v1-sidecar` → 0 match for `hex≥32`, `transcript/role`,
   `traceback/File "`, or `/app/secrets|admin_token|qwen-realtime.env`.
5. **Error responses:** every malformed/oversized/unknown/wrong-type payload → sanitized 4xx/5xx body with no token,
   path, traceback, or store internals (0 forbidden-pattern hits across ~100 requests).
6. **Admin UI shell:** served without auth but contains 0 occurrences of the token and 0 secret-path markers.
7. **The one exposure found (RED-I-01) is an untracked local ops backup archive, not a product surface.**

---

## FINDINGS

### RED-I-01 — MAJOR · Secret file inside a world-readable backup archive
- **ID / agent / round:** RED-I-01 · RED-I · 1 · **MAJOR**
- **Surface:** backups/artifacts (`rtl-lab-backups/`), filesystem permissions.
- **Precondition:** local Mac checkout.
- **Reproduction:**
  ```
  ls -la rtl-lab-backups/*.tar.gz
  tar -tvzf rtl-lab-backups/rtl-lab_r1b_pass_20261006_100334.tar.gz | grep secrets
  ```
- **Expected:** backup bundles containing credentials are mode 600 (and/or contain no secret material).
- **Actual:** `rtl-lab-backups/rtl-lab_r1b_pass_20261006_100334.tar.gz` is mode **`-rw-r--r--` (644, world-readable)**
  and contains **`rtl-lab/secrets/qwen-realtime.env`** — the secret file holds the **Qwen realtime key material**
  (shape: a small `KEY=VALUE` env file, 248 bytes as archived; value **not** printed).
- **Root cause:** the r1b RTL lab snapshot was tarred with the lab `secrets/` directory included; the archive was
  created with the default umask (644). The sibling backups `rtl-lab_pre_r1c_*.tar.gz` and `rtl-lab_r1a_pass_*.tar.gz`
  contain no `secrets/`.
- **Containment:** the path is **git-ignored** (`rtl-lab-backups/`) — not committed, not in any image, not on the NAS.
  Single-user Mac, so real-world reach is limited to local read. Still a secret-at-rest exposure that violates the
  "backups must be mode 600 and secret-free" rule.
- **Status:** open (recorded, not fixed — read-only scope). Recommended: chmod 600 and/or re-create without `secrets/`.

### RED-I-02 — MINOR · Config backup with a token field is world-readable (mode regression)
- **ID / agent / round:** RED-I-02 · RED-I · 1 · **MINOR**
- **Surface:** filesystem permissions (`config-backups/`).
- **Precondition:** local Mac.
- **Reproduction:**
  ```
  ls -la config-backups/
  python3 -c "import json;d=json.load(open('config-backups/config_backup_productv1_arm_20261008_013545.json'));print(list(d))"
  ```
- **Expected:** every backup in `config-backups/` is mode 600 (the 7 sibling backups all are `-rw-------`).
- **Actual:** `config_backup_productv1_arm_20261008_013545.json` is **mode 644** while it carries the key field
  `SYSTEM_OPTIONS.WEBSOCKET_ACCESS_TOKEN` (plus `MUSIC.URL_API_KEY`). The token value is the literal placeholder
  **"test-token"** (length 10, matches the deployment doc's OTA response) and `URL_API_KEY` is empty, so **no real
  secret is exposed** — this is a permission regression only.
- **Root cause:** the Phase-10 arm backup was written by `cp`/redirection without an explicit `chmod 600`.
- **Status:** open.

### RED-I-03 — MINOR · Secret file path can be written to logs on read failure
- **ID / agent / round:** RED-I-03 · RED-I · 1 · **MINOR**
- **Surface:** log hygiene (`gateway/app/qwen.py`).
- **Precondition:** `QWEN_MODE=real` and the secret file is unreadable at read time.
- **Reproduction (in-process, no network, safe):**
  ```
  printf 'QWEN_REALTIME_API_KEY=x\n' > /tmp/adv/red_i/noperm.env; chmod 000 /tmp/adv/red_i/noperm.env
  cd gateway && .venv/bin/python - <<'PY'
  import logging; logging.basicConfig(level=logging.WARNING)
  from app.qwen import _read_secret_file
  _read_secret_file("/tmp/adv/red_i/noperm.env")
  PY
  ```
- **Expected:** a read failure logs that it failed, without disclosing the secret file path.
- **Actual:** emits `WARNING rtl.qwen qwen secret file read failed: [Errno 13] Permission denied: '/tmp/adv/…/noperm.env'`
  — **the secret file path is logged** (`gateway/app/qwen.py:56`, `log.warning("qwen secret file read failed: %s", e)`).
  The **value** is never logged.
- **Root cause:** the raw exception `e` is interpolated; `OSError`/`PermissionError` strings embed the path.
- **Containment:** does **not** trigger in the deployed config (NAS secret files are mode 600 owned by uid 10001, and the
  container runs as 10001, so no read error). Latent only. Secret **paths** are explicitly in this agent's target list.
- **Status:** open.

### RED-I-04 — MINOR · Real-Qwen drivers are shipped inside the deployed sidecar image
- **ID / agent / round:** RED-I-04 · RED-I · 1 · **MINOR**
- **Surface:** build/deploy hygiene (image contents / Qwen budget safety).
- **Precondition:** shell access to the container (`docker exec`).
- **Reproduction (read-only inspection):**
  ```
  ssh xiaozhi-nas 'ls -la /volume1/docker/xiaozhi-product-v1/tests | grep -E "real_probe|spike_|smoke"'
  ssh xiaozhi-nas 'docker history --no-trunc xiaozhi-product-v1-xiaozhi-product-v1-sidecar | grep "COPY tests"'
  ```
- **Expected:** the runtime image should not carry dev-only drivers that can open a paid upstream session
  (`REAL_QWEN_TOTAL_USED` is locked at 4/4).
- **Actual:** `Dockerfile` line 17 `COPY tests /app/tests` ships the full test tree, including
  `r1f_real_probe.py`, `spike_session_update.py`, `spike_vocab_matrix.py`, `mvp_real_smoke.py`, `r1c_probe.py`.
  The sidecar is currently armed `QWEN_MODE=real`, so `docker exec xiaozhi-product-v1-sidecar python /app/tests/r1f_real_probe.py`
  could open a real session.
- **Root cause:** the Dockerfile copies the entire `tests/` directory (only `secrets`/`data` are `dockerignore`d).
- **Status:** open. (Not exploited in this run.)

### RED-I-05 — INFO · Admin surface published on 0.0.0.0 (documented exposure decision)
- **ID / agent / round:** RED-I-05 · RED-I · 1 · **INFO**
- **Surface:** public exposure / LAN-only claim.
- **Reproduction:**
  ```
  ssh xiaozhi-nas 'docker inspect -f "{{json .HostConfig.PortBindings}}" xiaozhi-product-v1-sidecar'
  ssh xiaozhi-nas 'docker ps --format "{{.Names}} {{.Ports}}" | grep product-v1'
  ```
- **Expected (deployment intent text):** admin "published only in this temporary sidecar; loopback-bound in production".
- **Actual:** `HostIp=""` → all three ports (`28310→8110`, `28311→8111`, **`28312→8112` admin**) bind on **0.0.0.0**
  (all host interfaces), and `ADMIN_BIND=0.0.0.0` inside the container. So the admin API is reachable from **any LAN
  host**, not loopback-only. It is nonetheless **bearer-token gated** (anonymous → 401 on all 7 probed routes + a POST)
  and the host is a LAN NAS with no observed WAN port-forward. Exposure decision: acceptable **iff** the NAS is
  firewall-confined to the LAN; recommend host-loopback binding (`127.0.0.1:28312:8112`) when admin is not needed
  off-box.
- **Status:** accepted/INFO (documented, token-protected).

### RED-I-06 — INFO · The reported HTTP-500 `internal_error` paths disclose nothing
- **ID / agent / round:** RED-I-06 · RED-I · 1 · **INFO**
- **Surface:** error responses + logs (this agent's surface for the sibling-reported 500s).
- **Reproduction (LOCAL mock, ports 29310/29311/29312):**
  ```
  POST /admin/policy/preview  {"policy":{"persona":"x"}}              -> 500 {"error":"internal_error","request_id":…}
  POST /admin/policy/apply    <4000-deep persona> + confirm:true      -> 500 {"error":"internal_error","request_id":…}
  POST /admin/knowledge/document/add  {"text":"hello \ud800 world"}  -> 500 {"error":"internal_error","request_id":…}
  ```
- **Expected:** a server error must not disclose secrets, file paths, tracebacks, or store internals.
- **Actual:** all three 500 bodies contain **only** `{"error":"internal_error","request_id":<12-hex>}` — no detail/path/
  traceback (`gateway/app/admin/api.py:93-95`). The server log records `log.warning("admin api error in %s: %r", fn, e)`:
  `AttributeError(...)`, `RecursionError(...)`, and `UnicodeEncodeError('utf-8','hello \ud800 world',6,7,…)`. The last
  one echoes a **bounded snippet of submitted content** (learner/user-supplied, ~7 chars) — no secret, no path, no
  internal module. No traceback is ever emitted.
- **Status:** informational — the 500 paths are non-disclosing on this surface (matches RED-D-03/RED-D-04/RED-C-F1).

### RED-I-07 — INFO · Committed evidence files contain synthetic probes only
- **ID / agent / round:** RED-I-07 · RED-I · 1 · **INFO**
- **Surface:** real-learner-data / committed artifacts.
- **Reproduction:**
  ```
  git show HEAD:docs/engineering/master-run/evidence/mvp_real_smoke.json | grep -c '"transcript"'
  git grep -lIiE 'user_state|knowledge_private|learner transcript' -- docs 2>/dev/null
  ```
- **Expected:** transcripts committed to the repo must be synthetic, never real learner speech.
- **Actual:** `mvp_real_smoke.json` transcripts ("Hold on! Stop! …", "Hello. Can you tell me what you can do?") correspond
  to the **synthetic** assets `u1/u2/u3.pcm16k.raw`; `vocab_matrix_real_session.json` contains real-Qwen answers to
  **synthetic** questions; `phase3_spike_round1.json` carries no transcripts and no credentials, but does commit the
  workspace-scoped endpoint host `ws-<id>.cn-beijing.maas.aliyuncs.com` (a tenant identifier, **not** a credential).
  `REAL_LEARNER_DATA_COMMITTED` therefore stays 0. Note: `docs/engineering/master-run/evidence/` is **not** git-ignored,
  so a future real transcript dropped there would be committable (hardening suggestion).
- **Status:** informational.

---

## COVERAGE / NEGATIVE RESULTS (what I tried that found nothing)

- **Git:** 1026 tracked files; branch `main`; only untracked entries are the two adversarial dirs. **Nothing staged.**
  `.gitignore` verified to cover `secrets/`, `admin0-backups/`, `config-backups/`, `rtl-lab-backups/`, `logs/`,
  `rtl-lab/evidence/**`, `**/user_state*.json`, `**/knowledge_private/**`, `**/*.db|sqlite`.
- **Image:** `USER 10001` (non-root); no prepared secret ENV; `docker history` clean; `.dockerignore` blocks
  `secrets`,`data`; only `.env` (mode selector, 19 B) sits in the build context and is **not** `COPY`ed.
- **Container runtime (NAS):** `Config.User=10001`, `Privileged=false`, `CapDrop=[ALL]`, `no-new-privileges`,
  `secrets → /app/secrets:ro`, `data → /app/data:rw`. `ReadonlyRootfs=false` (hardening gap, INFO only).
- **NAS perms:** `secrets/product_v1_admin_token` and `secrets/qwen-realtime.env` = **600, uid 10001** ✓;
  `data/` = **700, uid 10001** and **not listable** by the ssh user (only the container user can read) ✓.
  (Minor: the `secrets/` dir itself is 755 and the staged build-context files are 777 via NAS ACLs — single-user NAS;
  the running container uses the baked COPY, so host-side modes don't affect runtime integrity.)
- **Logs:** NAS container logs (39 lines) and local `logs/*.log` → 0 hits for bearer token, 32+ hex, transcripts, or
  tracebacks. Gateway error log paths → secret-free except the bounded surrogate echo (RED-I-06).
- **Admin error surface:** ~100 requests (6 ADMIN-1 GETs, 20 ADMIN-2 GETs, malformed JSON, non-dict JSON, empty body,
  wrong types, 70 KiB bodies → 413, chunked oversized, unknown/traversal paths) produced statuses
  `{200:23, 400:60, 401:3, 404:6, 413:14, 500:3}` with **0 forbidden-pattern hits** in any body.
- **Auth/exposure:** anonymous → 401 on all probed admin routes incl. POST; **admin routes absent (404)** on the audio
  HTTP port; UI shell served without auth but contains no token/secret path.
- **Backups/bundles:** `git bundle verify` OK; bundle heads are `main` + tags only, and a git bundle contains only
  objects reachable from tracked refs (no `secrets/`, which was never committed). `admin0-backups/*.tar.gz|*.bundle`
  are 600. `admin0-backups/pre-monorepo-originals/` is 700 with a **key-free** `.config.yaml` (0 `api_key/app_id/api_secret`),
  and its only key-shaped grep hits are third-party `.venv` files (PIL/shiboken `RECORD`) = false positives.
- **Hex runs in tracked files:** 31 files carry 40+ hex (sha256 digests in docs, `yarn.lock`/`uv.lock` integrity hashes,
  baseline manifests) — all digests, no key material.

## PATHS WRITTEN
- `docs/engineering/product-v1/adversarial/reports/red_i-round1.md` (this report)
- `gateway/tests/adversarial/red_i/probe_secrets_logs.py` (error-response disclosure probe)
- Runtime scratch (not product): `/tmp/adv/red_i/` (token, store files, captured responses)
