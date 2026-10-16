# RED-A — Adversarial Validation, Round 3 (independent cross-check)

**Agent:** RED-A (Authentication / Authorization)
**Round:** 3 — regression + independent cross-check of fixes in `e3c9b6c` (r1) and `b854778` (r2)
**Role:** independent verifier of OTHER agents' fixes (not the author). Read-only on product source.
**Surface:** admin control-plane auth/authz + the round-1/round-2 fixes that touch it
(`gateway/app/admin/api.py` durable read-back, `modules/_store_lock.py` + the three stores,
`gateway/app/main.py` listener model).
**Mode:** local, mock-only, in-process aiohttp `TestClient` + bounded multi-process lock probe on
ADMIN :9112. No real-Qwen, no NAS sidecar WS, no primary/Workbench/production, no secret printed.
**Artifacts written (only these):**
- `gateway/tests/adversarial/red_a/red_a_round3.py` (42 checks)
- `gateway/tests/adversarial/red_a/red_a_lock_dos.py` (bounded lock-hold probe)
- `docs/engineering/product-v1/adversarial/reports/red_a-round3.md` (this file)
(`red_a_attacks.py` / `probe_semantics.py` from round 1 unchanged.)

---

## 1. Cross-check verdicts per fix

| # | Fix under test | Verdict | Basis |
|---|---|---|---|
| 1 | Durable read-back / persist honesty (`_disk_*`, `_durable`, `PersistError`→500) | **CONFIRMED** | No false `readback_ok:true` reachable; a forced flush failure yields `500 persist_failed` with **no phantom** in-memory change and **no audit entry**; bodies/logs leak no path or token. |
| 2 | Cross-process store lock (`modules/_store_lock.py`, wired in 3 stores) | **WEAKENED** | Cross-process correctness goal is plausible, but the lock takes a **blocking `fcntl.flock(LOCK_EX)` with no timeout** synchronously on the shared realtime event loop → a second holder freezes the whole gateway (RED-A-R3-01). Lock file itself is empty/644, no leak. |
| 3 | Round-1 auth matrix (heavily edited API) | **CONFIRMED** | Round-1 suite re-runs 85/85; new C1 sweep: every GET/POST route `401` anon, all six ADMIN-1 routes `200` authed, identical 401 bodies, path/HEAD tricks still guarded. |
| 4 | New 400/500 validation surface (surrogates, controls, type guards, capped errors) | **WEAKENED** | Ingestion/type hardening is solid (surrogates/newlines/non-str → clean 400, never 500; `top_k` guard works). But the "bounded policy error list" fix is **incomplete**: `/admin/policy/preview` still returns an uncapped list (RED-A-R3-02). |

Existing suites re-run green at this revision: `admin_security_tests 29/29`, `admin2_tests 69/69`,
`product_boundary_tests 23/23`, `adversarial_repair_tests 79/79`, plus my round-1 `85/85`.
My round-3 suite: **`RED_A_ROUND3: 42 checks, 41 PASS, 1 FAIL`** (the 1 FAIL is RED-A-R3-02).

---

## 2. Metrics

- **UNAUTHORIZED_WRITES = 0 — CONFIRMED.** Anonymous POST → 401 on every write route; forced-failure writes return 500 without mutating or auditing; no write route outside `/admin/*`; the audio HTTP app still exposes no `/admin/*`.
- **AUTH_BYPASS = 0 — CONFIRMED.** Full route-table anon sweep + path/encoding/HEAD tricks + no-oracle 401 bodies all hold on the edited revision.
- **Judgement on the new persistence/lock code (auth-adjacent):** it introduced **no** auth/authorization weakness — no new route, no change to the `/admin/` middleware guard, no token/path/secret leak in bodies or (for the exercised paths) logs. It did introduce (a) an **availability** weakness (RED-A-R3-01) and (b) a **response-amplification** gap (RED-A-R3-02). Neither bypasses auth.

---

## 3. NEW findings

### RED-A-R3-01 · RED-A · r3 · MAJOR (availability) · store lock
**Unbounded blocking cross-process flock on the shared realtime event loop.**

- Surface: `modules/_store_lock.py:55` `fcntl.flock(fh.fileno(), fcntl.LOCK_EX)` (blocking, no
  timeout), invoked synchronously from async admin handlers; `gateway/app/main.py:97-121` runs the
  WS, HTTP and admin listeners on **one** asyncio loop.
- Precondition: a second same-uid process holds an exclusive `flock` on `<store>.lock`. (The design
  explicitly contemplates a second container/process writer; flock is released if the holder exits,
  so a *live but stalled* holder is required.)
- Reproduction:
  ```bash
  cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
      tests/adversarial/red_a/red_a_lock_dos.py
  ```
  Output:
  ```
  control (no lock holder): RESULT 200 1
  VERDICT: BLOCKED — admin write did not complete within 6s while <store>.lock was held by another process (event loop frozen)
  ```
  (The probe seeds a memory item, spawns a holder that flocks `<mem>.lock`, issues one authenticated
  `POST /admin/memory/edit`, and is bounded by a 6 s kill so it cannot hang.)
- Expected: an admin write blocks only its own request, or fails fast/timeout — the audio/WS plane
  keeps serving.
- Actual: the handler blocks forever inside the synchronous store call → the **entire event loop**
  (WS + HTTP + admin) is frozen for as long as the lock is held. The probe's own 6 s timeout never
  fires because the timer shares the frozen loop.
- Root cause: blocking `flock(LOCK_EX)` without a timeout, on the same loop that serves realtime.
- Scope/severity note: **not remotely reachable** — no HTTP input controls the lock or its duration;
  it requires local same-uid process access (a stalled legitimate writer, a stuck maint script).
  Rated MAJOR because the blast radius is the whole realtime plane; a timeout/non-blocking lock, or
  running the store call off-loop, would close it.
- Status: open.

### RED-A-R3-02 · RED-A · r3 · MINOR · policy error list
**`/admin/policy/preview` returns an uncapped error list — the round-2 R2-05 bound is incomplete.**

- Surface: `gateway/app/admin/api.py:91` caps the **exception** path (`PolicyInvalid`) at 50, but
  `policy_preview` (`api.py` `@_guard policy_preview`) returns `store.preview()`'s `errors` verbatim;
  `PolicyStore.preview` (`modules/policy/persona.py`) does not bound the list.
- Reproduction: `POST /admin/policy/preview` with a policy containing 5000 unknown `persona` keys.
- Expected: the same ≤50 bound the apply path now enforces.
- Actual: HTTP 200 with **5000** error strings; measured **request 58 915 B → response 149 020 B**
  (~2.5× amplification, bounded only by the 64 KiB request cap). No secret/value leak (messages are
  static "unknown key"/field-path strings + the caller's own key names), just unbounded reflection.
- Root cause: R2-05 mitigation applied only to the raised-exception handler.
- Status: open.

### RED-A-R3-03 · RED-A · r3 · INFO · store lock file
`<store>.lock` is created next to each store with **mode 644** (store files themselves are 600).
It is **empty** (0 bytes, verified), not world-writable, never written to, and appears in no API
response. Content-free, so only the mode deviates from the store's 600 convention. Symlinked
`.lock` is harmless: the holder opens it `a+` and only `flock`s (verified a victim file is untouched).

### RED-A-R3-04 · RED-A · r3 · INFO · type guard
`top_k` accepts `true` because `isinstance(True, int)` is `True`; it is then treated as `top_k=1`.
Harmless coercion quirk (no crash, no bypass); a strict `type(x) is int` would be cleaner.

---

## 4. Coverage evidence (negative results — all held)

- **Durable read-back (C2/C3).** Happy path: policy apply / memory edit / knowledge create each
  return 200 with `readback_ok:true` **and** are independently re-read from the raw JSON file + a
  fresh store instance. Forced flush failure (store dir chmod 0o500): all three writes → `500
  persist_failed` (never 200); no phantom policy version; no phantom memory value; no phantom
  dataset; **no audit entry** for the failed write; response bodies contain no store path/token.
- **Error oracle (C4).** Missing-confirm → 400 `confirm_required`; the only 5xx observed is the
  constant `persist_failed` body — no internal-state enumeration. Captured logs contain no token and
  (for these paths) no store path.
- **New 400/500 surface (C5).** `top_k` ∈ {str, float, list, dict} → 400; int/None → 200. Non-string
  dataset name → 400. Lone surrogate in name / description / title / text / source_uri → 400 (not
  500). Newline in dataset name / document title → 400. `policy/apply` error list ≤ 50.
- **Lock file (C6).** `.lock` empty; no `.lock` or store-dir path in any API response; not
  world-writable; symlink does not touch the victim; authenticated read is prompt (<500 ms) and still
  401 without a token; lock is held only inside synchronous critical sections (no `await` under the
  lock — code inspected in all three stores).
- **Auth matrix (C1).** Anonymous 401 on every GET and POST route; all six ADMIN-1 routes 200 with a
  token; identical no-oracle 401 bodies; path tricks (`/admin/../admin/...`, `/admin/./health`,
  `/%61dmin/health`, `/ADMIN/health`, `/admin//health`) and anonymous HEAD still guarded.

## 5. Hard-lock compliance

No real-Qwen driver run; no NAS sidecar WS client; no primary/Workbench/production contact
(Workbench URL empty); no frozen file/semantics changed; no secret printed; only the three artifact
paths above written. Ports 9110–9112 left free; the lock-hold probe is fully self-bounded and left no
stray processes.
