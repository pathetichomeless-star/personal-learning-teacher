# ADMIN-1 — Agent A: API / Auth Correctness Audit (READ-ONLY)

- Reviewer: Agent A (API/auth correctness)
- Repo: `<project-root>` — branch `main`, baseline HEAD `ecb8209e94847fa391104c8db3a77a188e2cd6f5`
- Scope reviewed (uncommitted working tree): new `gateway/app/admin/*`, new static console
  `admin/{index.html,app.js,styles.css}`, new tests `gateway/tests/admin1_tests.py` +
  `gateway/tests/admin1_load.py`, modified `gateway/app/main.py` and `gateway/app/ws.py`.
- Method: full manual read of every ADMIN-1 source file + an **independent** probe
  (`/tmp/agentA_probe.py`, my own aiohttp loopback `AppRunner` + `TestClient`) + independent re-run
  of both ADMIN-1 suites. No file other than this report was modified; no NAS / Workbench / container
  access; only loopback ports bound.
- Test env: `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python` (aiohttp 3.14.4, CPython 3.14.7,
  local libopus 1.3.1; the NAS image ships its own).

## Verdict

All required properties reproduced. No defect found.

```
AGENTA_PROBE: 76/76 PASS   (my independent probe)
ADMIN1_TESTS: 79/79 PASS   (repo suite, re-run)
ADMIN1_LOAD:  29/29 PASS   (repo suite, re-run)
```

---

## 1. Separate listener (third AppRunner, default OFF)

`gateway/app/admin/service.py::start_admin_listener` returns `[]` immediately when
`admin_config.enabled` is false, before constructing a `TokenStore` or an app. It only builds a
`web.AppRunner` + `TCPSite(runner, bind, port)` when `ADMIN_ENABLED=1` **and** a token is configured;
otherwise it logs an error and returns `[]` (fail closed).

`gateway/app/admin/config.py`: `enabled=_as_bool(...)` default `"0"`, `DEFAULT_BIND="127.0.0.1"`,
`DEFAULT_PORT=8112`, `DEFAULT_TOKEN_FILE="/app/secrets/admin_api_token"`, `ui_dir` resolves to
`<repo>/admin`. `describe_public()` exposes only `{enabled, bind, port}`.

Independent probe evidence (`/tmp/agentA_probe.py`):

```
== 1. config defaults (empty env) ==
PASS enabled default False
PASS bind default 127.0.0.1
PASS port default 8112
PASS token file default /app/secrets/admin_api_token
PASS ui_dir resolves to repo/admin
PASS describe_public hides token/paths
== 3. disabled listener / port not bound ==
PASS port 19113 not open before start
PASS ADMIN_ENABLED=0 -> no runner
PASS ADMIN_ENABLED=0 -> port still closed
== 3b. enabled + no token -> fail closed ==
PASS enabled+no token -> no runner (fail closed)
PASS enabled+no token -> port not bound
```

`port_open()` is a real `socket.connect(("127.0.0.1",PORT))` probe, so "starts nothing / binds nothing"
is verified at the TCP layer, not just by return value. With `ADMIN_ENABLED=0` the audio plane is not
touched (the module returns before any app construction).

## 2. Exactly six endpoints; no extra/write routes; audio app unchanged

`gateway/app/admin/app.py::create_admin_app` registers only the six `GET /admin/*` handlers plus five
static-UI routes (`/`, `/index.html`, `/app.js`, `/styles.css`, `/favicon.ico`). `admin_route_table()`
matches. Enumerated live in the probe:

```
== 2. route enumeration ==
PASS admin app canonical paths == route table
PASS exactly six /admin API paths   -> ['/admin/diag-summary','/admin/health','/admin/metrics','/admin/sessions','/admin/telemetry','/admin/version']
PASS every /admin route is GET (harness auto-adds HEAD)
PASS no /admin/diag/reset route
PASS no /admin/routing route
PASS no write method anywhere in admin app
PASS admin app mounts no audio/OTA/diag/health route
PASS audio app declares 7 routes (auto-HEAD objects aside)
PASS audio app canonical set unchanged
PASS audio app still owns POST /diag/reset
audio route objects (incl auto HEAD): 12; declared: [('GET','/health'),('POST','/xiaozhi/ota/'),('GET','/xiaozhi/ota/'),('GET','/xiaozhi/v1/'),('GET','/diag'),('POST','/diag/reset'),('GET','/diag/capture')]
PASS app/http.py unchanged (empty git diff)
```

- No write route exists on the admin app (only `GET`; `HEAD` is aiohttp's automatic companion).
- No `/admin/diag/reset`, no `/admin/routing`.
- The admin app mounts none of `/xiaozhi/*`, `/diag*`, `/health`, OTA or the WS route.
- Audio app: 7 declared routes (`create_app`), canonical set unchanged; it still owns its own
  `POST /diag/reset` (unrelated to admin). `admin_route_table()` deliberately excludes it.
- `app/http.py` git diff is empty (unmodified).

Note: aiohttp auto-adds `HEAD` for every `GET` (12 route objects for the audio app, 11 for the admin app),
so the "7 routes" figure counts declared `add_*` calls; canonical resources are 6 (audio) / 11 (admin:
6 API + 5 UI).

## 3. Auth behaviour (own token file, real loopback listener)

Own probe on a live `AppRunner` bound to `127.0.0.1:19113`, token file created in `/tmp`:

```
== 4. auth matrix on real listener ==
PASS enabled+token -> exactly one runner
PASS port binds only on loopback
PASS anonymous -> 401 on all six
PASS invalid token -> 401 on all six
PASS malformed (no scheme) -> 401
PASS malformed (scheme only) -> 401
PASS malformed (empty) -> 401
PASS malformed (basic) -> 401
PASS scheme 'bearer' accepted -> 200
PASS scheme 'BEARER' accepted -> 200
PASS scheme 'BeArEr' accepted -> 200
PASS valid token -> 200 all six
PASS token value never in any body
PASS token value never in any response header
PASS 401 bodies identical apart from request_id
PASS 401 body has no token material
PASS X-Request-Id present and opaque
```

- Anonymous → 401 on all six; invalid (`Bearer nope`) → 401 on all six.
- Malformed headers (missing scheme, scheme-only, empty, `Basic <token>`) → 401.
- Scheme is case-insensitive (`_bearer` lowercases the scheme token).
- Valid token → 200 on all six; the token value appears in no body and no response header.
- 401 body is always `{"error":"unauthorized","request_id":<12 hex>}` — identical for anonymous vs
  invalid (no oracle); `request_id` is `os.urandom(6).hex()` (opaque, non-secret).
- Missing token material + `ADMIN_ENABLED=1` → listener refuses to start (see §1); additionally
  `auth_middleware` fails closed (`auth_not_configured`) if a store were ever empty at request time.
- Token material is compared with `hmac.compare_digest`; the module never logs/returns the value
  (only `source`/`configured` booleans).

## 4. Response schemas — bounded, deterministic, honest, allowlist-built

```
== 5. schema + determinism + honesty ==
PASS /admin/health key set deterministic
PASS /admin/health bounded (<16KB)
PASS /admin/version key set deterministic
PASS /admin/version bounded (<16KB)
PASS /admin/sessions key set deterministic
PASS /admin/sessions bounded (<16KB)
PASS /admin/metrics key set deterministic
PASS /admin/metrics bounded (<16KB)
PASS /admin/telemetry key set deterministic
PASS /admin/telemetry bounded (<16KB)
PASS /admin/diag-summary key set deterministic
PASS /admin/diag-summary bounded (<16KB)
PASS telemetry available=false + reason
PASS version image_digest null + source unavailable
PASS diag-summary (disabled) honest branch + no hostile keys
PASS no leaked gateway-info keys anywhere
```

- Determinism: each of the six payloads was fetched twice; key sets compare equal; all payloads < 16 KB.
- `/admin/telemetry` → `available=false`, `reason="server_side_aggregator_unavailable"` (no fake zeros).
- `/admin/version` → `image_digest: null`, `image_digest_source: "unavailable"`; read of `version.py`
  confirms no `subprocess`/`os.system`/`Popen`/docker-socket code (AST scan of executable code, docstring
  prose stripped — the word "socket" only appears in the explanatory docstring).

`/admin/diag-summary` is allowlist built in `views.py::diag_summary_view`: it copies only named
aggregate keys and rejects hostile keys by construction. Verified against a **hostile enabled snapshot**
(my own fixtures, monkeypatched `diag.SNAPSHOT_PROVIDER`):

```
== 8. diag-summary allowlist under a HOSTILE enabled snapshot ==
PASS diag enabled -> aggregates kept
PASS diag capture payload is byte-counts only (no dir)
PASS diag-summary omits hostile key 'transcripts'
PASS diag-summary omits hostile key 'journal_tail'
PASS diag-summary omits hostile key 'send_intents'
PASS diag-summary omits hostile key 'send_timeline'
PASS no hostile token surfaces anywhere
PASS no hostile workspace surfaces anywhere
PASS no hostile raw sid surfaces anywhere
PASS no hostile raw rid surfaces anywhere
PASS no hostile transcript surfaces anywhere
PASS no hostile capture dir surfaces anywhere
```

- Raw `sid`/`resp_id`, transcripts, `journal_tail`, `send_intents`, `send_timeline` never leave the view.
- `capture` is `{enabled, bytes:{...}}` only — the capture directory (`cap_raw["dir"]`) is never copied.
- `resettable: false` (no reset surface). `health` copies only whitelisted gateway-info keys, so a hostile
  `gateway_info` carrying `token`/`workspace_id`/`endpoint` leaks nothing.

## 5. Read-only invariants

```
== 6. read-only invariants ==
PASS counters unchanged (uptime excluded)
PASS diag snapshot unchanged
PASS session registry unchanged
== 7. AST source scan (read-only by construction) ==
PASS admin package: no counter writes / internals / shell / sockets
PASS views.py never references hostile keys
PASS views.py never copies capture dir
PASS version.py code never shells/docker/sockets
PASS ws.py has exactly 2 admin_sessions. hooks
```

- Before/after a full sweep of the six GETs: `counters.snapshot()` identical ignoring `uptime_s`;
  `diag.SNAPSHOT_PROVIDER()` identical; `sessions.count()` identical.
- AST scan over `gateway/app/admin/*.py`: no `counters.{inc,set_gauge,set_state,observe_max,observe_min,
  inc_dispatch_error}`, no store/FIFO/pacer internals (`future_audio_store`, `dl_buf`, `_store_*`,
  `pacer_task`, `send_update/send_cancel/send_append`), no `subprocess`/`Popen`/`os.system`, no
  `socket`/`urllib`/`requests`/`docker`. The registry holds weak refs and only reads existing
  connection attributes when producing a session row.

## 6. Isolation / minimal diff

`git diff` (unmodified elsewhere):

```
 modified:   gateway/app/main.py     (+11 / -0)
 modified:   gateway/app/ws.py       (+4  / -0)
```

- `main.py` additions: one import of `load_admin_config/start_admin_listener/stop_admin_listener`, the
  `admin_cfg = load_admin_config()` + `start_admin_listener(...)` block after the two existing listeners,
  and `await stop_admin_listener(admin_runners)` before the existing runner cleanup. Nothing else.
- `ws.py` additions: one import of the admin registry and exactly two lifecycle calls —
  `admin_sessions.register(conn)` after `Connection(...)` and `admin_sessions.discard(conn)` in the
  `finally` block. No hot-path work, no locks.
- No other tracked file changed. `git status` shows only the two modified files plus the untracked
  admin package / console / tests / evidence files.

## 7. Repo-suite results (re-run by me)

```
ADMIN1_TESTS: 79/79 PASS
ADMIN1_LOAD:  29/29 PASS   (requests=450, max_ms=5.5, both scenarios pass; pacer_rebases=0)
```

Both match the Lead evidence file (`admin1-lead-test-evidence.txt`: 79/79 and 29/29). One transient
note: the first `admin1_load.py` attempt failed to bind `127.0.0.1:19977` (`Errno 48`, held by a
concurrent peer process); the port was released and the retry passed cleanly. This was an environment
port collision, not an ADMIN-1 defect.

## Checks I could not reproduce / caveats

- The load suite's `r1f_runtime` harness is pre-existing and unrelated to ADMIN-1; only its
  non-regression under admin polling was re-verified. Its hardcoded `FAKE_PORT=19977` was momentarily
  contended by a peer process (see above) — resolved on retry.
- The `v.fail-closed` path is proven via the listener refusing to start; the in-request
  `auth_not_configured` branch is not reachable in a normally-started listener by construction.

## Conclusion

All ADMIN-1 API/auth correctness, isolation, honesty, allowlist and read-only invariants hold with
independently reproduced evidence. No exploitable or functional defect found.

`A_ADMIN1_API = PASS`