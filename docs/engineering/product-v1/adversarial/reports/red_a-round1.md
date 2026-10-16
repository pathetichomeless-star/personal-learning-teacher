# RED-A — Adversarial Validation, Round 1

**Agent:** RED-A (Authentication / Authorization)
**Round:** 1
**Surface:** ADMIN control-plane auth + authz — `gateway/app/admin/{auth,app,api,service,config,views,registry}.py`,
`gateway/app/main.py`
**Mode:** local, mock-only, in-process aiohttp `TestClient`/`TestServer` + one loopback raw-socket
probe on the assigned ADMIN port **9112**. No real-Qwen, no primary/Workbench/production, no WS
client to the NAS sidecar, no secret printed.
**Artifacts written (only these):**
- `gateway/tests/adversarial/red_a/red_a_attacks.py` (85 checks)
- `gateway/tests/adversarial/red_a/probe_semantics.py` (recon probe)
- `docs/engineering/product-v1/adversarial/reports/red_a-round1.md` (this file)

No product/implementation file was modified.

---

## 1. Metric verdicts

| Metric | Verdict | How falsified |
|---|---|---|
| **UNAUTHORIZED_WRITES = 0** | **CONFIRMED** | All 14 write routes hit anonymously → `401`; malformed / confirm-less / unknown-id writes → `4xx` with memory+knowledge+policy+audit snapshots byte-identical before/after. No write route is reachable outside `/admin/*`. |
| **AUTH_BYPASS = 0** | **CONFIRMED** | ~40 auth-header forms, path/encoding traversal, method confusion, duplicate/comma/CRLF/long headers, raw-socket smuggling, undocumented-route enumeration — none reached a handler or data without the real bearer token. |

Admin UI shell is **intentionally unauthenticated** and was verified to carry **no operational
data** (serves only static `index.html`/`app.js`/`styles.css`; contains neither the token, learner
values, nor store paths). Metrics are the two required above.

Existing regression suites re-run at this revision, all green:
`admin_security_tests.py 29/29`, `admin1_tests.py 83/83`, `admin2_tests.py 69/69`,
`admin_ui_tests.py 23/23`. My suite: **`RED_A_ATTACKS: 85 checks, 85 PASS, 0 FAIL`**.

Run:
```bash
cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
  tests/adversarial/red_a/red_a_attacks.py
```

---

## 2. Findings

### Findings summary
No BLOCKER. No MAJOR. No MINOR security/integrity defect. Four INFO observations (none is exploitable;
recorded for completeness / defense-in-depth).

---

**RED-A-01 · RED-A · r1 · INFO · admin API route space**
Title: Route shadowing — `GET` on the knowledge document write paths resolves to the read handler.

- Preconditions: valid bearer token (auth is still required).
- Repro:
  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer <token>" \
       http://127.0.0.1:9112/admin/knowledge/document/add
  ```
- Expected: `405 Method Not Allowed` (write-only path, GET not registered).
- Actual: `400 {"error":"knowledge_error"}` for `/admin/knowledge/document/{add,delete,rebuild}` —
  aiohttp matches the literal segment against the registered **GET** route
  `/admin/knowledge/document/{doc_id}` and calls the read handler with `doc_id="add"`.
- Root cause: `api.py:619` registers `GET /admin/knowledge/document/{doc_id}` while
  `add/delete/rebuild` are POST-only siblings under the same prefix; the dynamic GET shadows them.
- Impact: none observed — auth is enforced, no mutation occurs, generated doc ids are `doc_`-prefixed
  so the literal ids can never collide with a real document. Cosmetic/route-space ambiguity only.
- Status: open (INFO).

**RED-A-02 · RED-A · r1 · INFO · auth header handling**
Title: Duplicate `Authorization` headers — first value is authoritative.

- Repro:
  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' \
    -H "Authorization: Bearer wrong" -H "Authorization: Bearer <real>" \
    http://127.0.0.1:9112/admin/policy/active      # -> 401 (first wins)
  ```
- Expected: undefined by RFC 7230 (duplicate `Authorization` is a malformed request).
- Actual: `CIMultiDict.get` returns the first occurrence → invalid-first ⇒ `401`, valid-first ⇒ `200`.
- Impact: none by itself (an attacker still needs the real token). Worth noting because any fronting
  proxy that *normalizes/joins* duplicate headers could change the effective value; the app itself
  fails closed for the invalid-first form.
- Status: open (INFO).

**RED-A-03 · RED-A · r1 · INFO · body-size guard**
Title: Chunked oversize body surfaces as `400 invalid_json`, bypassing the app's own 413 guard.

- Repro (raw socket, valid token, ADMIN :9112):
  `POST /admin/memory/edit` with `Transfer-Encoding: chunked` and a 70 KiB JSON body.
- Expected: `413 body_too_large` (the `api.MAX_BODY = 64 KiB` guard).
- Actual: `400 {"error":"invalid_json"}`. `_body()` only checks `request.content_length`
  (`api.py:102`), which is `None` for chunked; aiohttp's 1 MiB `client_max_size` then aborts the
  read, and `_body`'s broad `except Exception` (`api.py:106`) converts the raised
  `HTTPRequestEntityTooLarge` into a 400.
- Impact: low — the request is still rejected and the body is bounded at 1 MiB by aiohttp, so no
  memory-DoS. Only the status code/diagnostic is misleading for chunked clients.
- Status: open (INFO).

**RED-A-04 · RED-A · r1 · INFO · header normalization**
Title: Scheme case and surrounding whitespace of the credential are normalized (RFC-appropriate).

- Repro: `Authorization: bearer <token>`, `BEARER <token>`, `Bearer\t<token>`,
  `Bearer <token> ` all authenticate (`200`).
- Expected: RFC 7235 auth-scheme is case-insensitive and OWS is allowed around the token ⇒ accepted.
- Actual: matches expectation; the token itself is compared exactly after `.strip()`, in constant
  time (`hmac.compare_digest`, `auth.py:84`). No length/prefix oracle: anonymous, empty, malformed and
  wrong tokens return byte-identical bodies (only `request_id` differs).
- Status: open (INFO, no action required).

---

## 3. Coverage evidence — what was tried (negative results)

Everything below **failed to break the surface**; each was executed by the suite.

**A. Bearer token matrix (`t_token_matrix`, `t_contradictory_headers`)**
- No `Authorization`; empty value; whitespace-only value; `Bearer` with no value; `Bearer` + spaces;
  bare token without scheme; `Basic`/`Token`/`Bearer+` schemes; `realm="…"` value; token+suffix;
  token upper/lower-cased; wrong token; token misplaced in a 3rd field; comma-joined value.
  → all `401`.
- Truncated token for **every** length `1..N-1` → all `401`.
- Token with suffix `x`, prefix `x`, last-char mutation → `401`.
- Very long token (4 KiB) → `401`, no crash.
- No-oracle: anon / empty / `Bearer` / wrong → identical JSON body (modulo `request_id`).
- Duplicate headers (invalid-first, valid-first, both-invalid) → `401/200/401` (first-wins).
- Loopback raw-socket: valid token `200`; no header `401`; duplicate invalid-first `401`;
  CRLF-injected extra header `401`; obs-fold continuation with a bogus token → not `200`;
  smuggled 2nd `Authorization` behind an invalid 1st → `401`; 100 KiB header line rejected;
  bare-LF request → not `200`; `TRACE` → `405`.

**B. Content-type / body hardening (`t_body_hardening`)**
- Write endpoints with `application/x-www-form-urlencoded`, `text/plain` (non-JSON),
  `multipart/form-data`, and no `Content-Type` → `400 invalid_json`.
- JSON shapes: array, string, `null`, number, `true`, truncated object, control chars → `400`.
- Body `> 64 KiB` (with Content-Length) → `413`; body `> 1 MiB` → `413`.
- Legitimate large (~60 KiB) JSON body parsed correctly (no false 413).
- State snapshot unchanged after the whole malformed-write sweep.

**C. Read→write escalation / method confusion (`t_read_write_escalation`)**
- Swept all 23 GET admin routes with a valid token: no `5xx`, and memory/knowledge/policy/audit
  snapshots identical before/after → every GET is side-effect free.
- `GET` on every write-only path → `400/404/405` (never a write), snapshot unchanged.
- Anonymous `HEAD` on an admin GET route → `401`; authenticated `HEAD` → side-effect free.
- `OPTIONS`/`TRACE`/`PUT`/`DELETE`/`PATCH` on a GET route → `405`.

**D. Path traversal / encoding tricks (`t_path_tricks`)**
- `/admin/./health`, `/admin//health`, `/admin/x/../health`, `/admin/../admin/health`,
  `/admin/%2e%2e/admin/health`, `/%61dmin/health`, `/ADMIN/health`, trailing slash, `;params`,
  `%2E%2E` upper-hex, `/./admin/...` — **without** a token none reached a handler
  (`400/401/404/405`); aiohttp normalizes both `request.path` (seen by middleware) and the router
  identically, so the `/admin/` prefix guard cannot be side-stepped. With a token, a traversed path
  lands on the authed handler (`200`) → auth is enforced, not skipped.

**E. Route enumeration / middleware skip (`t_route_enumeration`)**
- Mounted routes == the documented `admin_route_table()` **exactly** (no undocumented route).
- No `/admin/diag/reset`; no non-GET handler for any `/admin/workbench/*` path (Workbench GET-only).
- Probed ~22 plausible backdoors (`/admin/reset`, `/admin/restart`, `/admin/config`, `/admin/token`,
  `/admin/secret`, `/admin/debug`, `/admin/exec`, `/admin/shell`, `/admin/reload`, `/admin/internal`,
  `/admin/version/x`, `/admin/policy`, `/admin/memory`, `/admin/knowledge`, `/admin/workbench`,
  `/admin/behavior`, `/health`, `/diag`, …): none anonymous-accessible; none exist even authenticated
  (all `404`).
- Middleware wiring is a single `web.Application(middlewares=[request_id_middleware, auth_middleware])`;
  no subapp and no second mount point exists (grep across `gateway/app`).

**F. Audit coverage / no-silent-mutation (`t_audit_coverage`)**
- Each of `policy_apply`, `memory_edit`, `knowledge_dataset_enable`, `knowledge_document_rebuild`,
  `memory_clear_category` produced **exactly one** audit entry.
- Failed writes (`policy/apply`, `policy/rollback` unknown version, `memory/delete` no-confirm,
  `memory/clear-category` wrong token, `knowledge/dataset/delete` wrong token,
  `knowledge/document/delete` no-confirm, `knowledge/document/add` unknown dataset): each returned
  `4xx` with the full state snapshot (memory/knowledge/policy/audit counts) **unchanged** → validation
  happens before mutation; nothing mutates-then-fails.

**G. Token reload semantics (`t_token_reload`, `t_listener_fail_closed`)**
- Initial reload configures; **unchanged source keeps** the token (repeated reloads do not clear it).
- Changed file takes effect (new matches, old rejected).
- Emptied file → fail closed (not configured). Removed file → fail closed.
- Whitespace-only file → falls back to env source; env-only works; no source → not configured.
- `start_admin_listener`: `ADMIN_ENABLED=1` with empty token file → no listener; with missing token
  file → no listener; `ADMIN_ENABLED=0` → no listener at all (fail closed, audio plane untouched).

**H. UI shell (`t_ui_shell`)**
- `/`, `/index.html`, `/app.js`, `/styles.css` served without auth (by design); each response body
  contains no token, no stored learner marker, no store path. `/favicon.ico` → `204`.
- No static traversal / directory listing; `app.js` references only `/admin/*` endpoints and always
  attaches the `Authorization` header — it is not a data endpoint.

**I. Admin vs audio app isolation (`t_audio_app_isolation`)**
- The audio HTTP app (`main.create_app`) exposes **no** `/admin/*` route; its route set is exactly
  `{/health, /xiaozhi/ota/, /xiaozhi/v1/, /diag, /diag/reset, /diag/capture}`.
- The admin app exposes no `/health`, `/xiaozhi/*`, or `/diag*` (only `/admin/diag-summary`).

**J. Raw-socket header attacks (`t_raw_headers`, ADMIN :9112 loopback)**
- See section A's raw-socket list; all malformed/smuggling forms failed closed.

---

## 4. Hard-lock compliance

- No `spike_session_update` / `spike_vocab_matrix` / `mvp_real_smoke` / `r1f_real_probe` executed.
- No WS client connected to the NAS sidecar; no listening/uplink audio sent.
- No primary (8110/8111), Workbench (:18100), legacy stack, or accepted-MVP sidecar touched; the
  Workbench URL was empty (client returns `available:false`) — no outbound call made.
- No provider/model/voice/VAD/frame/Opus/FIFO semantics changed; no frozen file edited.
- No secret printed or copied; the test token is a synthetic local fixture, never echoed into output.
- Only the three artifact paths listed at the top were written.
