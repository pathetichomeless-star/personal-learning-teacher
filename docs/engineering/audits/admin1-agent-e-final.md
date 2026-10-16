# ADMIN-1 — Agent E: Fresh Final Review (READ-ONLY)

- Reviewer: Agent E (fresh, no prior context). READ-ONLY; the only file written is this report.
- Repo: `<project-root>` — branch `main`, baseline HEAD `ecb8209e94847fa391104c8db3a77a188e2cd6f5`.
- Reviewed surface (all **uncommitted**): new `gateway/app/admin/{__init__,config,auth,registry,views,app,service,version}.py`,
  new `admin/{index.html,app.js,styles.css}`, new `gateway/tests/{admin1_tests.py,admin1_load.py}`,
  modified `gateway/app/main.py` + `gateway/app/ws.py`, plus the four auditor reports + lead evidence.
- Method: independent re-derivation. `git status`/`git diff`, full manual read of every ADMIN-1 file,
  byte-level manifest comparison, re-runs of all four suites, and **my own adversarial probe**
  (`/tmp/e_probe.py`, my own fixtures + aiohttp `TestClient`) that never reuses the Lead's data.
- Local env (dev-only): `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python` (aiohttp 3.14.4,
  CPython 3.14; local libopus 1.3.1). No NAS, no Workbench, no container access; loopback only.

## Verdict

Every required property independently reproduced. Six falsification attempts produced no blocker and
no major; four minor/cosmetic observations (all pre-existing or non-security) are recorded below.

```text
ADMIN1_TESTS: 80/80 PASS      (my re-run of the current suite)
ADMIN1_LOAD:  29/29 PASS      (requests=444, max_ms=6.3, pacer_rebases=0)
R1F_BRIDGE_TESTS: 180/179/1 (current) == 180/179/1 (pristine baseline), same OpusError item
E_PROBE: 61/61 PASS           (my own adversarial fixtures)
```

---

## 1. Scope / git surface (independently established)

```text
$ git status --porcelain
 M gateway/app/main.py
 M gateway/app/ws.py
?? admin/
?? gateway/app/admin/
?? gateway/tests/admin1_tests.py
?? gateway/tests/admin1_load.py
?? docs/engineering/audits/admin1-agent-{a-api-auth,b-audio-regression,c-security,d-ui-scope}.md
?? docs/engineering/audits/admin1-lead-test-evidence.txt

$ git diff --stat HEAD
 gateway/app/main.py | 11 +++++++++++
 gateway/app/ws.py   |  4 ++++
 2 files changed, 15 insertions(+)
```

The changed/untracked surface is exactly the described one — no other tracked file changed, one new
HTML file (`admin/index.html`). `git diff` is pure additions: `main._run()` gains the admin
start/stop block (default `ADMIN_ENABLED=0` → `[]`), `ws.py` gains two lifecycle-only registry calls.
No NAS / Workbench / container path appears in the working tree.

## 2. Claim 1 — "read only" (no gateway-state writes)

- `views.py` handlers call only `counters.snapshot()`, `diag.SNAPSHOT_PROVIDER()`, `diag.capture_info()`,
  `sessions.snapshot()`/`count()` and `version_mod.build_facts()`; the registry `_row` only
  `getattr`s existing `Connection` attributes (`state`/`tts_active`/`pacer_task`/`qwen`/
  `session_id`/`conn_ordinal`) — all plain attributes, no properties, no locks.
- My probe with the **real** providers: `counters.snapshot()` and `sessions.count()` are byte-identical
  before/after a full six-endpoint sweep (uptime excluded). No write route exists; all `/admin/*`
  routes are GET (aiohttp HEAD companions only). Grep of the admin package for
  `send_update|send_cancel|send_append|ensure_connected|request_connect|on_connect|counters.(inc|set_gauge|set_state|observe)|future_audio_store|_store_|dl_buf` → **zero** real hits (only a comment and metric-name string literals).
- **Counter-evidence (MINOR, pre-existing):** `diag.SNAPSHOT_PROVIDER()` is **not** side-effect-free.
  `Diag.snapshot()` calls `violation("SEND_INTENT_UNRESOLVED", …)` whenever unresolved send intents
  exist, which bumps the diag-local `_assertions` tally and appends a journal entry. I reproduce this:
  with `RTL_DIAG=1` + one fabricated unresolved intent, `assertions_total` goes `1 -> 2` on each call.
  This is inherited unchanged by the pre-existing `/diag` route (`app/http.py`), is documented as
  **log-only** ("never alter control flow or timing decisions"), and touches neither counters, the
  store/FIFO/pacer, the Qwen client, nor the registry. It occurs only when diagnostics are explicitly
  enabled. It does not defeat the intent of "read only" and is not introduced by ADMIN-1; recorded as a
  minor literal caveat to "diag unchanged".

## 3. Claim 2 — "no secret leak" (my own adversarial fixtures)

I built my own fixtures (my token, fake API key, fake MySQL/Redis passwords, workspace id, private
token path, private capture dir, and an env-dump canary) and injected them where the code could copy
from: a hostile `gateway_info` (extra `token/api_key/mysql_password/redis_password/workspace_id/
endpoint/secret_file`), a hostile `diag.SNAPSHOT_PROVIDER` (transcripts, raw ids, `journal_tail`,
`send_intents`, `send_timeline`, `capture.dir`), and a hostile `diag.capture_info` (`dir` + extra keys).

Result: **all 11 fixtures absent from every response body, every response header, and the captured
logs** (11× bodies/headers + 11× logs = 33 assertions, all PASS). `/admin/health` emits only the
allowlisted `mode/ready` + named counter keys; the auth token is never rendered in a header.

## 4. Claim 3 — "no transcript leak" / diag-summary allowlist

- Code reading: `diag_summary_view` constructs its payload key-by-key (`snap.get`, `len(...)`); it never
  references `transcripts`, `journal_tail`, `send_intents`, `send_timeline`, `per_conn` raw ids or
  `connections`; `capture` is `{enabled, bytes:{three fixed filenames}}` only (never `cap_raw["dir"]`).
- My hostile-snapshot probe: diag-summary contains none of `transcripts`/`journal_tail`/`send_intents`/
  `send_timeline`/`dir`, nor my transcript, raw sid/rid, or capture-path fixtures; `capture ==
  {enabled: True, bytes:{…}}`; `resettable: False`. **PASS.**

## 5. Claim 4 — "no audio regression"

- **Byte-freeze:** compared `docs/admin0/baseline-manifest.sha256` (`rtl-lab/app/*`, `config/config.json`)
  against today's `gateway/…` with `shasum -a 256`: **only `main.py` and `ws.py` changed**; every pacing/
  Opus/FIFO/qwen-provider/counters/diag file is byte-identical (`turns.py` byte-identical ⇒
  `MEDIA_FRAME_MS=20.0`, `MIN_SEND_START_INTERVAL_MS=15.0`, `PACING_SLACK_MS=5.0` frozen).
- **Deterministic suite:** current tree `180/179/1` and pristine baseline `/tmp/admin1-baseline/gateway`
  `180/179/1` — **identical counts and the identical single failure** `B test_sentinel_harness
  EXCEPTION OpusError()` (local macOS libopus, environmental, not ADMIN-1).
- **Admin load:** `29/29 PASS`, `requests=444`, `max_ms=6.3`; both scenarios `pacer_rebases=0`,
  `segments_qualifying=1`, `fps≈49.99 ∈ [49.5,50.5]`, closures (source/framer/disposition) = 0,
  zero fatal stalls / guard violations / short intervals / cap transitions / unknown outcomes. The pass
  does **not** depend on pacer rebase recovery.

## 6. Claim 5 — "no external dependency"

- Admin imports: only `aiohttp`, stdlib, and the read-only snapshot sources `..diag`, `..counters`,
  `.version`, `.registry`. No `manager-api`/MySQL/Redis/Workbench/RAG/memory imports.
- Whole-`gateway/app` scan for `manager-api|workbench|sync/state|mysql|redis|rag|memory-service|
  knowledge-base|subprocess|os.system|Popen|socket.socket|urllib|requests.|docker` → only a docstring
  word ("Docker socket") and a comment; **no runtime coupling, no shelling out, no socket clients.**
- Filesystem: admin accesses only (a) the token file (`auth.py`), (b) `FileResponse` over the fixed
  `UI_FILES` allowlist, (c) `os.environ`/`Path(__file__)` for config. Traversal/env probes
  (`/admin/env`, `/admin/config`, `/admin/debug`, `/admin/../etc/passwd`, `/admin/%2e%2e/etc/passwd`,
  `/admin/health/../../secret`, `/admin/passwd`, and shell-level `/etc/passwd`, `/app.js/../etc/passwd`)
  are all rejected (401/404); no file content and no env canary leaked.

## 7. Claim 6 — "ADMIN-1 only"

- Exactly **six** read-only `GET /admin/*` routes + the static shell; no write/reset/routing route;
  **no `/admin/diag/reset`**; no ADMIN-2 endpoint (`instruction|language-policy|provider|model|voice|
  memory-policy|knowledge-assignment|session/reload|routing`) anywhere in `gateway/app/admin/` or `admin/`.
- `main._run()` starts the admin listener **only** when `ADMIN_ENABLED=1` + a token is configured;
  default `ADMIN_ENABLED=0` returns `[]` before building any app ⇒ no third listener, no new port, the
  audio runtime is untouched (audio app still `create_app`'s 7 declared routes).
- UI: exactly Dashboard / Realtime / Diagnostics (three tabs/sections), no fourth page, no legacy page
  duplicated, no Workbench functionality.

## 8. Cross-cutting checks

- **UI network deps = exactly the six endpoints**: one `fetch(` in `app.js` (GET, `cache:"no-store"`),
  driven only by the fixed `API`/`LOADERS`/`POLL_MS` keys `{health,version,sessions,metrics,telemetry,
  diag-summary}`; no `method:`, no POST/PUT/DELETE, no `location.`.
- **Token handling**: `sessionStorage` only (`localStorage` appears once in a comment; real calls are
  get/set/remove), manual entry, cleared after Set, never rendered back, never in a URL; a clear action
  exists and stops polling.
- **Eight UI states** all present (LOADING/EMPTY/HEALTHY/DEGRADED/AUTH_REQUIRED/AUTH_FAILED/
  UPSTREAM_UNAVAILABLE/ERROR) incl. the honest telemetry-unavailable message
  "Telemetry aggregator is not available yet" (server returns `available:false`+reason; no fake zeros).
- **NAS / Workbench**: no evidence of any change — the working tree contains only the ADMIN-1 surface,
  and no runtime code path touches an external system (this host cannot observe a NAS directly; the
  available evidence is the working-tree surface + the absence of any coupling in source).

---

## Findings

- **Blockers: 0.** **Majors: 0.**
- **Minors (4):**
  1. `diag.SNAPSHOT_PROVIDER()` is not perfectly read-only under `RTL_DIAG=1` with unresolved send
     intents (it bumps a log-only assertion tally/journal). Pre-existing, inherited identically by the
     existing `/diag` route, audio-neutral — a literal caveat, not an ADMIN-1 write.
  2. `docs/engineering/audits/admin1-lead-test-evidence.txt` is stale: it records `ADMIN1_TESTS: 79/79`
     while the current suite reports `80/80` (one UI-scope check was added). Documentation drift only;
     the current suite passes independently.
  3. `gateway/tests/admin1_tests.py:test_source_guards` defines a `banned` list that is never used
     (dead variable; the intent is covered by the explicit AST + text checks that follow). Cosmetic.
  4. UI `Clear` resets `.kv`/`.state` panels but leaves the Dashboard `.big` tiles and the sessions
     table showing the last fetched (non-secret) values. Cosmetic, no security impact (also noted by
     Agent D).

## Acceptance

All six claims hold under independent adversarial re-derivation. The read-only intent is preserved
(no admin code path writes counters, audio state, the store/FIFO/pacer, the Qwen client or the registry;
the sole diag caveat is pre-existing, log-only, and diagnostics-gated). Frozen audio files, the R-1f
deterministic parity (both trees `179/1` with the same environmental OpusError), and the admin-load
non-regression (`pacer_rebases=0`, zero stalls/guards/short intervals, in-band steady rates, zero
closures) all reproduce. Scope is exactly ADMIN-1 with the default runtime unchanged.

---

## Post-correction re-check (Agent E, findings-scoped)

The Lead applied three findings-scoped corrections (no product-logic / audio-path / endpoint change).
I re-read the touched artefacts and re-ran the suites mechanically.

- **Minor 2 — stale Lead evidence — RESOLVED.** `docs/engineering/audits/admin1-lead-test-evidence.txt`
  now records `ADMIN1_TESTS: 80/80 PASS`, `ADMIN1_LOAD: 29/29 PASS`, and the R-1f deterministic suite on
  **both** the current tree and the pristine baseline (`180 checks, 179 PASS, 1 FAIL` — the environmental
  `OpusError`). Matches my own re-runs.
- **Minor 3 — dead `banned` variable — RESOLVED.** `gateway/tests/admin1_tests.py::test_source_guards`
  no longer defines `banned` (grep: zero refs); the real checks are intact and still run — the AST offender
  scan, the hostile-key check (`journal_tail|send_intents|send_timeline|transcripts`), the capture-dir
  check and the `ws.py` two-hook check.
- **Minor 4 — UI Clear stale tiles — RESOLVED.** `admin/app.js` Clear handler now blanks `.big` too
  (`.kv, .state, .big`) and empties + hides the sessions `<tbody>` / `#rt-table`; no non-auth panel keeps a
  stale number.

Re-verified invariants after the corrections:

- `git diff --stat HEAD` still **only** `gateway/app/main.py` (+11) + `gateway/app/ws.py` (+4).
- Frozen manifest `docs/admin0/baseline-manifest.sha256`: still **only** `main.py` and `ws.py` changed;
  `audio.py/counters.py/diag.py/http.py/protocol.py/qwen.py/turns.py/config.json` etc. byte-identical —
  the corrections touched no R-1f audio/Opus/FIFO/qwen/counter/diag file.
- `ADMIN1_TESTS: 80/80 PASS` (re-run); `ADMIN1_LOAD: 29/29 PASS` (requests=444, max_ms=8.3,
  `pacer_rebases=0` both scenarios, fps≈49.99 in band, closures 0).
- Admin app router: still exactly six `GET /admin/*` routes + the 5 static-shell routes; no write/reset,
  no new endpoint.

**Remaining minors (unchanged disposition):**

1. Inherited `diag.SNAPSHOT_PROVIDER()` side effect under `RTL_DIAG=1` (bumps a log-only assertion tally
   when unresolved send intents exist). `diag.py` is byte-identical to baseline and untouched by these
   corrections; identical behavior exists on the pre-existing `/diag` route; audio-neutral. **Documented,
   no change required.**
2. The `resettable: false` field name on `/admin/diag-summary` is a hard-coded read-only *honesty marker*
   (no reset control and no reset route exist — router confirms six GETs only). **Correctly dispositioned
   as documented / no-change.**

```text
E_BLOCKERS = 0
E_MAJORS = 0
E_MINORS = 2
E_ADMIN1_FINAL_REVIEW = PASS
```