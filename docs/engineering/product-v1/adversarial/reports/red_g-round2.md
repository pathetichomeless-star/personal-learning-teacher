# RED_G — Round 2 — Concurrency / Race Conditions (re-attack of the Round-1 fixes)

- **Agent:** RED_G (Concurrency / Race Conditions)
- **Round:** 2
- **Fix under test:** commit `e3c9b6c` ("repair all BLOCKER/MAJOR findings + add repair guards").
- **Surface:** `modules/memory/store.py`, `modules/knowledge/store.py`, `modules/policy/persona.py`,
  `modules/_store_lock.py`, the admin read-back seam (`gateway/app/admin/api.py`), and the live gateway.
- **Method:** in-process multi-instance/multi-thread probes + **multi-process** subprocess workers +
  a **live local gateway** (ports 9310/9311/9312, local mock upstream 9377, `QWEN_MODE=mock`) with real
  WS clients. All store files in temp dirs. **No real-Qwen session, no NAS, no primary/Workbench/production.
  Product source READ-ONLY.**
- **Test files:**
  - `gateway/tests/adversarial/red_g/red_g_round1.py` (regression gate; expectations updated to the new contract)
  - `gateway/tests/adversarial/red_g/red_g_round2.py` (new attacks)
  - run: `cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/adversarial/red_g/red_g_round2.py`
- **Results:** round-1 gate **45 checks, 44 PASS / 1 FAIL**; round-2 **45 checks, 43 PASS / 2 FAIL**.
  Every FAIL is an intended finding.

## What the fix actually is (verified by reading the current source)

- `modules/_store_lock.py` provides `store_lock(path)`: a per-path **in-process `RLock`** (`with store_lock(p):`,
  used for reads) **plus**, for writers only, `store_lock(p).exclusive()` which additionally takes a
  **bounded, non-blocking advisory `fcntl.flock`** on `<store>.lock` (deadline `XZ_STORE_LOCK_TIMEOUT_MS`,
  default 500 ms; on timeout raises `StoreLockTimeout`). Reads never take the file lock (`os.replace` gives
  old-or-new).
- All three stores use `_path_lock(...) = store_lock(...)`; **every mutator** wraps `reload → mutate → flush`
  in `.exclusive()`; knowledge/policy reads additionally `reload_if_changed()` under the RLock.
- Change signature is `(mtime_ns, size, ctime_ns, ino)`; `_flush` unlinks its tmp on a caught failure and
  raises `PersistError`; the admin API re-reads durable state through a **new** store instance.

## Per-finding verdicts (Round-1 findings)

| Round-1 finding | Verdict | Evidence (Round-2) |
|---|---|---|
| **RG-01** knowledge multi-instance lost update | **CLOSED** | `D knowledge 2/5/10xI` — no lost update; `S2` a second instance now reloads on read and no longer serves deleted content. |
| **RG-02** knowledge multi-instance invisibility | **CLOSED** | `D2` (round-1 gate) passes — a second instance can use the first's new dataset. |
| **RG-03** policy multi-instance lost update | **CLOSED (core)** | `D policy 2/5/10xI`: version == applies+1, both changes preserved. **But see NEW RG2-01.** |
| **RG-04 / RG-04b** memory unguarded RMW / concurrent lost update | **CLOSED** | `D memory 2/5/10 instances x 2/5/10 threads` → 0 loss (90/90 per config). |
| **RG-06** tmp leak on failed flush | **CLOSED** | `A5b`, `AT2b` — no orphan `.tmp`; failure now raises `PersistError` honestly (`A5`, `A7`). |
| **RG-07** deleted Knowledge via `(mtime,size)` seam | **CLOSED** | `SG1` equal-size+restored-mtime → **detected** (ctime moves); `S3` no longer retrieves the delete. |
| **RB-06/RB-07** single-user flush erases sibling partitions | **CLOSED** | `D6` — concurrent cross-user writes now keep **both** partitions. |
| **RB-09** `(mtime,size)` seam defeated | **CLOSED** | New signature adds `ctime_ns`+`ino`; `SG1–SG4` all detected. |

## NEW findings

### RG2-01 · MAJOR · `modules/policy/persona.py PolicyStore.load` (history merge)
- **Reproduction:** two `PolicyStore` instances over one file, each applies once (history length becomes 2):
  ```python
  p1 = PolicyStore(p).load(); p2 = PolicyStore(p).load()
  p1.apply({"persona": {"name": "aa"}}); p2.apply({"persona": {"name": "bb"}})
  [v["version"] for v in PolicyStore(p).load().versions()]   # -> [1, 1, 2, 3]
  ```
  (round-1 gate `D3b`, round-2 `D policy small-history reload`).
- **Expected:** each version once, e.g. `[1, 2, 3]`.
- **Actual:** the built-in v1 entry is duplicated; `versions()` inflates and, once persisted, the bounded
  20-entry history can evict usable `rollback` targets.
- **Root cause (exact):** `persona.py` lines 459–462:
  ```python
  if len(self._history) > 1:
      self._history = self._history[:1] + self._history[-(HISTORY_MAX - 1):]
  ```
  For a 2..19-entry history `self._history[-(HISTORY_MAX-1):]` is the whole list, so
  `[:1] + whole_list` duplicates the first entry. It is a no-op only when `len == HISTORY_MAX`.
  This is a **regression introduced by the RG-03 repair**.
- **Reachability:** persists only with **≥2 policy writers** (multi-process) or an external writer that
  forces a reload of a 2..19-entry history. In the deployed topology the admin instance is the only policy
  writer and its own `_sig` matches after each `_flush`, so it does not reload its own writes → **not
  reachable** there. The gateway's `BehaviorLink` PolicyStore does reload on admin writes but only ever reads
  (`active()`); the duplicate stays in that instance's memory and is never surfaced or flushed.
- **Status:** OPEN (latent).

### RG2-MP-M10 (and M5) · MINOR · `modules/_store_lock.py exclusive()` (cross-process)
- **Reproduction:** `Popen` 10 processes (5 for the M5 case), each opens its own `MemoryStore` over one file
  and `save()`s 15 (30) distinct keys; repeated 6 trials.
  ```
  MP memory 10-proc x15 (6 trials) losses=[0,0,0,0,0,2] worker_errors=0
  MP memory  5-proc x30 (6 trials) losses=[0,1,0,0,0,0] worker_errors=0
  ```
- **Expected:** every committed save persisted (writers hold `.exclusive()` = flock).
- **Actual:** occasional **silent** lost updates (0–2 items/trial). `worker_errors=0` proves it is **not** an
  honest `StoreLockTimeout` refusal — the flock does not fully exclude across processes. The live file always
  stays valid JSON (no corruption).
- **Reachability:** requires **≥2 processes**; the deployed topology is a **single process** (see below) →
  **not reachable** there. Latent for a second process / maintenance script.

### RG2-02 · MINOR · `modules/memory/store.py load/reload_if_changed` (unlocked)
- **Reproduction (deterministic harness):** a subclass forces a concurrent writer between the `read_text`
  and the `_stat_sig` inside `MemoryStore.load()`:
  ```
  ML TOCTOU: disk={'k': 'NEW'} served={'k': 'OLD'} reload_again=False
  ```
- **Expected:** the change is detected and the new value served.
- **Actual:** `load()` caches the **post-write** signature against the **pre-write** content, so
  `reload_if_changed()` returns `False` thereafter and the stale value is served indefinitely.
- **Root cause:** `MemoryStore.reload_if_changed`/`load` take **no lock** (knowledge/policy `load` run under
  `with self._lock:`; memory does not). Requires a concurrent thread/process → **not reachable** in the
  single-threaded deployed loop; latent.

### INFO · RG2-AT-KILL · crash-time orphan `.tmp`
- A **SIGKILLed** writer cannot run the cleanup path; an orphan `<store>.tmp` can remain (observed once
  across runs; the live file stayed the previous atomic version and parseable every time). Inherent to
  `tmp→os.replace`; not a fix defect. `AT1c` best-effort check, no numbered warning.

## Reachability in the DEPLOYED topology

**Deployed = ONE process, ONE asyncio loop** (verified: `app/main.py` starts the admin listener in the same
`_run()` loop via `app/admin/service.py`; `modules/**` and `gateway/app/**` contain **no `threading.Thread`
/ `ThreadPoolExecutor` / `run_in_executor`**). Store calls are synchronous with no `await` inside, so they
cannot interleave within the loop.

- **Reachable in the deployed single-process topology: none of the residual findings.**
  All in-process fixes hold: `D memory/knowledge/policy 2/5/10 instances × 2/5/10 threads → 0 loss`.
- **Only in artificial multi-process / multi-thread setups:** RG2-MP-M10/M5 (2nd process),
  RG2-02 (concurrent thread/process), RG2-01 (≥2 policy writers). These are latent robustness gaps —
  relevant if a maintenance script, a second container, or a multi-worker deployment ever shares the file.

## Metric verdicts

| Metric | Verdict |
|---|---|
| `CROSS_SESSION_CONTAMINATION` | **0 — HOLDS** (`X1–X4` in-process links; `LV` 2/5/10 parallel live sessions: distinct sids, registry empty after close; no cross-session state). |
| `STORE_CORRUPTION` | **0 — HOLDS** (no torn read across 4377 concurrent reads during 250+ writes; live file always valid JSON; SIGKILL/read-only/dir failures leave the file intact; mode 600). |
| `LOST_UPDATE` (deployed single-process) | **0** (in-process multi-instance/multi-thread scale all clean). |
| `LOST_UPDATE` (multi-process, latent) | **1 intermittent** — silent cross-process memory loss (RG2-MP). |

## Negative results / coverage evidence (what I tried that found nothing)

- **Signature defeats** — `SG1` equal-size rewrite + restored mtime, `SG2` in-place append (same inode),
  `SG3` hard-linked in-place edit, `SG4` symlink swap to a different inode: **all detected**.
- **Lock behaviour** — `LK1` two different store paths interleaved: no deadlock; `LK2` a mutation that raises
  while holding the lock releases it (usable again); `LK3` a slow (400 ms) flush blocks a concurrent writer
  but both complete within the 500 ms deadline (no hang, honest ordering).
- **Atomicity** — `AT1` SIGKILL mid-flush: live file parseable; `AT2/AT3` target-is-dir and read-only dir:
  mutation refused (`PersistError`), live file intact, **no in-memory phantom** (store reloaded); `AT4` no torn
  read across 200 writes.
- **Reads during writes** — `RD1/RD2`: 4377 cross-store reads during memory/knowledge/policy writer churn →
  0 torn, 0 writer errors.
- **Live sessions / reconnect storm** — `LV`: 2/5/10 parallel sessions handshake+listen, distinct ids,
  `ws_connections→0`, admin `/behavior/active` reachable (200) during a 25-sequential + 15-concurrent storm,
  **bounded asyncio tasks and threads**.
- **Honest failure** — the fix turns silent fail-soft into an honest `PersistError` (round-1 `A5/A7` updated).

## Hard-lock compliance

No real-Qwen session; no forbidden driver; `QWEN_MODE=mock` with a `127.0.0.1` mock upstream only; the NAS and
primary/Workbench/production were never contacted; all store files under temp dirs; the admin token is
referenced only as "the admin token"; **no product/implementation file was modified** — only files under
`gateway/tests/adversarial/red_g/` and this report.

## Files written

- `gateway/tests/adversarial/red_g/red_g_round1.py` (regression gate; expectations updated)
- `gateway/tests/adversarial/red_g/red_g_round2.py`
- `docs/engineering/product-v1/adversarial/reports/red_g-round2.md`
