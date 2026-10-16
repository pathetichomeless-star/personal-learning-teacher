# RED_G — Round 1 — Concurrency / Race Conditions

- **Agent:** RED_G (Concurrency / Race Conditions)
- **Round:** 1
- **Surface:** Product V1 stores (`modules/memory/store.py`, `modules/knowledge/store.py`,
  `modules/policy/persona.py`), the admin control plane (`gateway/app/admin/{stores,api}.py`),
  the gateway behavior link (`gateway/app/behavior.py` `_maybe_reload_stores`), and the live
  gateway under parallel sessions.
- **Method:** in-process aiohttp `TestClient` (admin) + direct multi-instance/thread store probes
  + a **live local gateway** (`app.main.create_app`, bound `127.0.0.1`) fed by a **local mock
  upstream** (`127.0.0.1`) with real WS clients. All store files in temp dirs.
  **No real-Qwen session, no forbidden driver, no NAS sidecar, primary/Workbench/production
  untouched. Product source READ-ONLY.**
- **Test file:** `gateway/tests/adversarial/red_g/red_g_round1.py`
  (run: `cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/adversarial/red_g/red_g_round1.py`)
- **Result:** 44 checks, 36 PASS / 8 FAIL, 7 findings. Every FAIL is an intended finding.

## Metric verdict

| Metric | Verdict | Evidence / falsification attempt |
|---|---|---|
| `CROSS_SESSION_CONTAMINATION` | **0 — HOLDS** | `X1–X4`: two live `BehaviorLink`s over **shared** files — session A's knowledge query did not enter session B's stats (`b_queries=0`), A's KB block never appeared as B's, and the two activities stayed distinct. `L1–L4`: 2/5/10 concurrent WS sessions on one live gateway all handshake+listen, got **distinct** session ids, and the registry had **no leaked session rows** after close. `L7/L8`: no asyncio-task or thread growth. |
| `STORE_CORRUPTION` (torn/partial live file) | **0 — HOLDS (atomicity OK)** | `A1/A2`: a reader `json.loads()`-ing the live file during 180 memory saves and during 80 knowledge add/delete cycles **never** observed a partial file (`os.replace` atomic). `B1–B5`: reads *during* external writes are always valid JSON, a consistent single version, no 5xx. `L3/L5`: `ws_connections` returns to 0. |
| `LOST_UPDATE` | **4 — FALSIFIED (defect confirmed)** | Deterministic multi-instance lost updates on all three stores — see RG-01…RG-04b. |

> Note: `LOST_UPDATE` counts check-level failures, not distinct defects; RG-01/02 and RG-04/04b
> share root causes.

## Findings

### RG-01 · MAJOR · `modules/knowledge/store.py` (multi-instance)
- **Surface:** `KnowledgeStore.create_dataset`/`add_document`/`delete_*`/`rebuild_chunks` (write paths).
- **Precondition:** two `KnowledgeStore` instances over one file (e.g. two admin workers/processes,
  or an admin + a gateway session during a write) — the "two-writer topology" the product documents.
- **Reproduction:**
  ```python
  ka = KnowledgeStore(p).load(); kb = KnowledgeStore(p).load()
  ka.create_dataset("DatasetA")
  kb.create_dataset("DatasetB")          # kb never reloaded
  KnowledgeStore(p).load().list_datasets()   # -> only ["DatasetB"]
  ```
  (test `D1`; observed disk datasets `['DatasetB']`)
- **Expected:** union of both instances' committed datasets (the admin API even returns `readback_ok`).
- **Actual:** the second writer replaces the whole file with only its own view → `DatasetA` (and any
  documents/chunks it held) are permanently lost. **Silent last-writer-wins discarding a committed change.**
- **Root cause:** unlike `MemoryStore`, the knowledge write API calls only `_ensure_loaded()` (loads
  once) and **never `reload_if_changed()`**; `_flush` serialises the entire in-memory `_data`.
- **Status:** OPEN.

### RG-02 · MAJOR · `modules/knowledge/store.py` (multi-instance visibility)
- **Surface:** same paths.
- **Reproduction:** `a=K(p).load(); b=K(p).load(); ds=a.create_dataset("shared");
  b.add_document(ds["id"], ...)` → `KnowledgeError('unknown dataset')` (test `D2`).
- **Expected:** the second instance can use the dataset created by the first.
- **Actual:** the second instance cannot even *see* it, so an add is rejected (and if it forced the
  add it would also clobber on flush). Same root cause as RG-01.
- **Status:** OPEN.

### RG-03 · MAJOR · `modules/policy/persona.py` (multi-instance)
- **Surface:** `PolicyStore.apply` / `rollback`.
- **Reproduction:** `pa=P(p).load(); pb=P(p).load(); pa.apply({...name:"小美"}); pb.apply({...name:"小刚"})`
  → `active().policy.persona.name == "小刚"`, `versions() == [1, 2]` (test `D3`).
- **Expected:** version 3 with **both** changes in history/audit (each apply is a new version).
- **Actual:** the second instance's apply overwrote the first — the change **and its version/audit
  entry** are silently lost. `rollback` from a stale instance has the same stale-base hazard.
- **Root cause:** `apply`/`rollback` call only `_ensure_loaded()`, never `reload_if_changed()`.
- **Status:** OPEN.

### RG-04 · MAJOR · `modules/memory/store.py` (unguarded read-modify-write window)
- **Surface:** `MemoryStore._upsert` / `edit` / `delete` / `forget` (`reload_if_changed()` → mutate → `_flush()`).
- **Reproduction (deterministic):** two instances over one file; a test subclass pauses on a
  `threading.Barrier` *inside* `reload_if_changed` so both reload the same base, then both flush:
  ```python
  # both threads: reload_if_changed(); <barrier>; add key; _flush()
  # result: sorted(keys) == ['from_a']   (or ['from_b'] — whichever flushed last)
  ```
  (test `D4`; observed `{'from_a'}` / `{'from_b'}` on different runs)
- **Expected:** both committed writes survive.
- **Actual:** one committed write is lost. `MemoryStore` has **no lock**; the reload→mutate→flush
  sequence is not atomic, so the "merge first" reload only narrows — it does not close — the window.
- **Status:** OPEN.

### RG-04b · MAJOR · `modules/memory/store.py` (empirical concurrent writers)
- **Reproduction:** 2 threads × 90 distinct `save()`s via **2 instances** over one file (no instrument)
  → **90/180 items persisted** (one instance's whole batch lost); 0 errors (test `D5`).
- **Expected:** 180. **Actual:** 90. Same root cause as RG-04. Confirms the loss occurs without any
  test instrumentation.
- **Status:** OPEN.

### RG-06 · MINOR · `modules/{memory,knowledge,policy}/*store*._flush`
- **Surface:** all three `_flush()` implementations.
- **Reproduction:** point the store path at a **directory** and `save()`:
  `_flush` writes `tmp`, then `os.replace(tmp, p)` raises → the exception is swallowed (fail-soft)
  but the temp file is **not removed** (test `A5b`; leftover `target_is_dir.json.<hex>.tmp`).
- **Expected:** fail-soft **and** no leftover temp file.
- **Actual:** orphan `.tmp` remains; repeated failures accumulate temp files. (The live store is
  correctly left untouched; the orphan is never loaded — verified `A6`.)
- **Status:** OPEN.

### RG-07 · MAJOR · `modules/knowledge/store.py reload_if_changed` (seam → DELETE)
- **Surface:** cross-instance freshness seam (the same `(mtime_ns, size)` signature used by
  `behavior._maybe_reload_stores` and admin `_fresh`).
- **Precondition:** a gateway session instance primed its signature (as it does every turn) while a
  document existed; the file is then rewritten by another writer to an **equal size with a restored
  mtime**.
- **Reproduction (deterministic):** prime `gw` (`gw.reload_if_changed()` with the doc present);
  `adm.delete_document(doc)`; pad the post-delete file to the primed size with trailing spaces and
  `os.utime(..., ns=original)`; `gw.reload_if_changed()` → `False`; `gw.search(deleted term)` → **hit**
  (test `S3`; probe `primed=True sig_equal=True reloaded=False disk_has=False hits=1`).
- **Expected:** the delete is detected; deleted content is no longer retrievable
  (severity guide: *"deleted Knowledge still retrieved"* = MAJOR).
- **Actual:** the stale gateway instance keeps serving the **deleted** document's chunks.
- **Root cause / relationship:** this is the known RB-09 seam (equal-size rewrite + restored mtime)
  **applied to a DELETE**. RB-09 was reported as a stale *value* read (MINOR); under the documented
  two-writer topology it is reachable as a durable *deleted-Knowledge-still-retrieved* defect.
- **Status:** OPEN (compounds RB-09).

## Analysis of the three sibling findings (as requested — not re-reported)

- **(a) `MemoryStore._flush` serialises only `self.user` (RB-06).** Quantified by `D6`: a barrier-aligned
  concurrent `default` write and `victim` write on one file leaves exactly **one** partition on disk
  (observed `['default']` and `['victim']` on different runs). **Concurrency does not widen this
  defect**: because `_flush` only ever emits the single writer's partition, the file can hold at most
  one partition regardless of timing — concurrency merely randomises *which* one survives (vs the
  deterministic sequence in RB-06). No new class of loss; MVP stays single-user `default`.
- **(b) secret-shape detector bypass (RB-02/RB-05).** Orthogonal to concurrency: it is a regex-shape
  gap in `_validate_value`/`_item_passes_boundary`, unaffected by interleaving. **No widening.**
- **(c) `(mtime_ns, size)` reload seam (RB-09).** **Concurrency WIDENS it** (RG-07): the seam is the
  *only* cross-instance freshness mechanism in the two-writer topology (`behavior._maybe_reload_stores`
  every turn; admin `_fresh` on reads), so a defeated seam is not just a stale display — a gateway
  session can keep retrieving a **deleted** document. Severity escalates from MINOR (stale value) to
  MAJOR (deleted Knowledge still retrieved) when cross-instance access exists.

## Negative results / coverage evidence (what I tried that found nothing)

- **Torn / partial live files** — memory `A1` (reader vs 180 writes) and knowledge `A2` (reader vs 80
  add/delete cycles): **0** parse errors in either loop; `os.replace` is atomic. `B2`/`B5`: every admin
  read during external-write churn is valid JSON, never a mixed version (`B3`).
- **Admin reads under write load** — 60 memory + 60 knowledge admin reads interleaved with a hot
  external writer: **no 5xx**, **no** bad JSON (`B1–B5`).
- **Modes / temp hygiene** — all three stores write mode `600` (`A3`); **no** `.tmp` leftovers after
  successful writes (`A4`); an orphan `.tmp` is never loaded as the live store (`A6`).
- **Atomicity of a failing writer** — read-only parent dir (`A7`) and target-is-a-directory (`A5`):
  flush is **fail-soft**, the live file is untouched and still parseable; the only leak is the orphan
  temp file (RG-06).
- **delete/search + rebuild races** — same-instance delete removes retrievability (`S1`); concurrent
  rebuild+search from 4 threads: no errors, file stays valid (`S4`). A *stale* second instance would
  serve deleted content (`S2`) but the gateway reloads each turn, so this alone is latent (the
  reachable path is the seam, RG-07).
- **Cross-session isolation (the metric)** — in-process (`X1–X4`) and live (`L1–L4`): no cross-session
  activity/state/block leakage; distinct session ids; empty registry after close.
- **Reconnect storms** — 30 sequential + 15 concurrent + 2/5/10 parallel batches: `ws_connections`
  returns to 0 (polled), no qwen-connect-error explosion, **asyncio tasks 1→2**, **threads 1→1**
  (bounded; `L5–L8`).
- **Honest degradation** — unreadable memory/knowledge files → admin 200 with honest **empty** results,
  never 500, never fabricated (`H1/H2`); a write blocked on a held store lock does **not** return early
  or fabricate success (`H3`).
- **Env quirk (not a defect):** the documented dev-libopus first-construction failure killed 1 of 10
  connections once; a single retry succeeded (proving it environmental, per the BRIEF).

## Hard-lock compliance

No real-Qwen session; no forbidden driver; `QWEN_MODE=mock` with a local `127.0.0.1` mock upstream
only; the NAS and primary/Workbench/production were never contacted; all store files under temp dirs;
the admin token is referenced only as "the admin token"; **no product/implementation file was
modified** (only files under `gateway/tests/adversarial/red_g/` and this report).

## Files written

- `gateway/tests/adversarial/red_g/red_g_round1.py`
- `docs/engineering/product-v1/adversarial/reports/red_g-round1.md`
