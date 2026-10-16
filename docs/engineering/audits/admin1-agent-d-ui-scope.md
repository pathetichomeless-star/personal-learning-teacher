# ADMIN-1 — Agent D: UI / Scope Audit

- Repo: `<project-root>` (local-only git, branch `main`, baseline HEAD `ecb8209`)
- Scope audited (uncommitted ADMIN-1): `admin/index.html`, `admin/app.js`, `admin/styles.css`,
  `gateway/app/admin/*.py`, `gateway/app/ws.py`, `gateway/app/main.py`
- Method: read-only. Independent source inspection + my own aiohttp probe
  (`create_admin_app` + `TestClient`) + the shipped suite
  `gateway/tests/admin1_tests.py` (**79/79 PASS**, libopus only needed because the audio app is
  imported for the isolation check). No NAS, no Workbench. No secrets printed.
- Verdict: **D_ADMIN1_UI = PASS**

---

## 1. Pages — exactly Dashboard / Realtime / Diagnostics

The shell (`admin/index.html`) exposes exactly three tabs (`data-page`:
`dashboard|realtime|diagnostics`) and three `<section class="page">` blocks. No fourth page exists
in the repo (`Glob **/*.html` → only `admin/index.html` plus incidental venv test fixtures under
`admin0-backups/`). This matches the locked scope doc
`docs/architecture/admin-navigation.md` L34 ("ADMIN-1 = gateway-only pages: Dashboard, Diagnostics,
Realtime read views").

| Page | Purpose | Data rendered | Endpoints used |
|---|---|---|---|
| **Dashboard** | Gateway status at a glance | status pill (HEALTHY/DEGRADED), uptime, active sessions, Qwen mode/connected, counters (responses completed/cancelled/turns, ws_connections, qwen_sessions), warnings list, build/version facts | `/admin/health`, `/admin/version` |
| **Realtime** | Live session view + pacing/closure health | sanitized session table (session_id_hash, state, qwen, generation, tts, pacer, age), pacer/latency aggregates, 3 closure residuals | `/admin/sessions`, `/admin/metrics` |
| **Diagnostics** | Aggregate diagnostics + telemetry honesty | diag-summary aggregates (journal entries, assertions, connections, live pacers, send-interval pcts, steady segments, closures, capture byte counts, `resettable=false`), explicit telemetry-unavailable state | `/admin/diag-summary`, `/admin/telemetry` |

## 2. No forbidden features

- **No write/save/apply controls.** The only `<button>`s are `Set token`, `Clear` (auth) and the
  three tab buttons. Grep over `admin/**` for `apply|save|write|method:|POST|PUT|DELETE`:
  hits are only in JS *comments*; there are no write controls and no non-GET request.
- **No provider/model/voice/instruction/language-policy/memory/knowledge/session-reload controls.**
  None of those words appear as identifiers/controls. `/admin/instruction`, `/admin/voice`,
  `/admin/session/reload` (which `admin-navigation.md` L10 lists for a *later* phase) are **not**
  mounted and **not** called.
- **No reset control.** `reset` appears nowhere as a UI element; `resettable` appears only as a
  read-only JSON field on `/admin/diag-summary` (hard-coded `False`, `views.py` L221) — the
  `ADMIN-ARCH-1.md` L100 rule "ADMIN-1 and ADMIN-2 expose no reset at all" is respected.
- **No ADMIN-2 started early.** See §8.
- **No legacy XiaoZhi page duplicated.** `admin/index.html` is a new 3-page console shell, not a
  copy of any legacy page.
- **No Workbench / legacy integration.** Grep for `manager-api`, `sync/state`, `workbench`,
  `ielts` → zero code hits. The admin app mounts only its own routes (`admin/app.py`
  `create_admin_app`); it does not proxy `/xiaozhi/*`, `/diag*`, `/health` or the WS route.

## 3. Only six API dependencies, GET-only, bearer header

Every `fetch()` in `app.js` is the single call at L58: `fetch(path, {headers:{Authorization: Bearer ${t}}, cache:"no-store"})`.
`path` comes only from the fixed `API` array (L12–13) / `LOADERS` map (L194–199) / `POLL_MS`
keys (L17–22), each exactly:

`/admin/health`, `/admin/version`, `/admin/sessions`, `/admin/metrics`, `/admin/telemetry`,
`/admin/diag-summary`

Extraction (`grep -o '"/admin/[a-z-]*"'`) equals exactly that sorted set — **set equality proven**.
No `method:` override anywhere → all requests are **GET** (fetch default); no POST/PUT/DELETE.
Authorization header carries the manually entered token. Server side mirrors this: `admin/app.py`
registers exactly those six `add_get` API routes plus the four shell routes + favicon.
Live probe: anonymous → 401 on all six; `Bearer <token>` → 200 on all six.

## 4. Token handling

- **Manual entry**: `<input id="token" type="password">` + `Set token` button (no auto-fetch).
- **sessionStorage only** (`TOKEN_KEY`, L14/L26–30); `localStorage` appears only inside a comment —
  not in code.
- **Never in URL/query**: no `location.` and no `?token` in `app.js`.
- **Never logged**: the token is never passed to `console`/error strings; errors carry only the
  request id.
- **Never rendered back**: after `Set token` the input is cleared (`el("token").value = ""`, L228).
- **Clear-token action exists and stops polling**: `Clear` → `token.clear(); stopPolling();`
  `setAuthState("AUTH_REQUIRED")` (L232–238).

Server-side auth (`auth.py`) is fail-closed, constant-time (`hmac.compare_digest`), returns an
identical 401 body for anonymous vs invalid token, and never logs/returns the value.

## 5. UI states

All eight rendered by `app.js`:

| State | Where |
|---|---|
| LOADING | `begin()` pre-fills panels before each fetch (L83–89) |
| EMPTY | `loadSessions` (`!d.count`), `loadDiagSummary` (`!d.enabled`) |
| HEALTHY | `loadHealth`, `loadSessions`, `loadDiagSummary`, `loadTelemetry` |
| DEGRADED | `loadHealth` when `d.status === "degraded"` |
| AUTH_REQUIRED | `api()` with no token; boot/clear |
| AUTH_FAILED | `api()` on HTTP 401 |
| UPSTREAM_UNAVAILABLE | `api()` fetch throw (network) **and** telemetry-unavailable |
| ERROR | `api()` on non-OK HTTP, carrying `HTTP <code>` + `request_id` from body or `X-Request-Id` |

Errors surface the request id via `showError(message, requestId)` into `#lastError`. The telemetry
card renders the explicit **"Telemetry aggregator is not available yet"** state (L184) when
`/admin/telemetry` returns `available:false` — **no fake zeros** (server returns
`{available:false, reason:"server_side_aggregator_unavailable"}`; confirmed by probe and by the
suite's "no fake zero metrics" check).

Note (cosmetic, not a defect): on `Clear`, L237 resets `.kv`/`.state` nodes but not the `.big`
Dashboard tiles (`dash-uptime/-sessions/-qwen`) or the sessions table; those keep the last fetched
values (still non-secret, no token). No security impact.

## 6. No embedded operational data; shell served from a fixed allowlist

- `index.html` contains static labels/placeholders only — no counters, session data, build facts or
  token. Grep for `uptime_s":`, `ws_connections":`, token fixtures → none in HTML.
- `styles.css` is pure presentation (no data).
- `app.js` hard-codes only endpoint paths and polling intervals; every value comes from an
  authenticated call.
- Shell serving (`views.ui_shell`, L228–245): the filename is looked up in the **fixed**
  `UI_FILES` dict keyed by `request.path`; unknown path → 404 JSON; missing file → 503. The path
  joined is `admin_ui_dir / <allowlisted filename>`, so there is **no directory listing and no
  user-controlled path**. Probe: `GET /nope` → 404; `/gateway/app/admin/config.py` → 404;
  traversal attempts → 401/404. Shell responses set `Cache-Control: no-store` and `X-Request-Id`.

## 7. Polling hygiene

`POLL_MS` (L17–22): health 5000, sessions 5000, metrics 5000, diag-summary 10000, telemetry 15000,
version 0 (fetched once, no interval). `startPolling()` uses `setInterval(fn, POLL_MS[path])` and
skips paths already timer-registered. **No page polls faster than declared**; tab switching only
toggles visibility and never changes intervals. Telemetry 15 s is within the declared 10–30 s band.

## 8. Scope-creep / "ADMIN-2 started early" notes

Nothing found. Specifically not present: any write/apply path, `/admin/instruction`,
`/admin/voice`, `/admin/session/reload`, `/admin/routing`, config/provider/model/voice/language/
memory/knowledge controls, adapter/memory/knowledge/workbench pages, and any reset (in-process
`/admin/diag/reset` is explicitly ADMIN-3+). The auth middleware stamps only `admin_role=VIEWER`
(no `OPERATOR`). Read-only fields that mention future phases — `resettable:false` on diag-summary,
`image_digest_source:"unavailable"`, `config_version_source:"unavailable"` — are honest
read-only markers, not partial ADMIN-2 features.

---

### Evidence summary
- `gateway/tests/admin1_tests.py`: **79/79 PASS** (isolation, auth, leak/allowlist, read-only,
  source guards, UI acceptance).
- Agent-D independent probe: shell `/,/index.html,/app.js,/styles.css` → 200 (`no-store`),
  favicon 204, unknown 404; six endpoints 200 with bearer / 401 without; telemetry honest.
- Caveat: the suite's `check("UI has no write/reset/model/voice controls", ... or True)` is
  vacuous (`or True`); Agent D re-verified this claim by direct grep — no forbidden control exists,
  so the finding stands on independent evidence rather than that assertion.