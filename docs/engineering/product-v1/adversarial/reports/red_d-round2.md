# RED-D Round 2 — re-attack of the policy/persona mutation-plane fixes

- **Agent:** RED-D (Persona / Policy / Admin Mutation) · **Round:** 2
- **Fix under test:** commit `e3c9b6c` ("product-v1 adversarial round 1: repair all
  BLOCKER/MAJOR findings")
- **Hard locks obeyed:** no real-Qwen session (no WS client, no uplink audio);
  mock/offline only; no primary/Workbench/production writes; no secret value printed;
  all store files in temp dirs. **No product source modified** (the working tree's
  `modules/{memory,knowledge}/store.py` and `red_{b,c,f,g}` edits are other agents'
  concurrent work — RED-D edited none of them).
- **Artifacts:**
  - `gateway/tests/adversarial/red_d/red_d_round2_attack.py` (110 checks)
  - `gateway/tests/adversarial/red_d/_policy_mp_worker.py`, `_memory_mp_worker.py`
  - Round-1 suite re-run: `gateway/tests/adversarial/red_d/red_d_policy_attack.py`
- **Run:** `cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/adversarial/red_d/red_d_round2_attack.py`
- **Result:** **110 checks, 106 PASS, 4 FAIL** (all 4 FAILs = one NEW cross-process finding).

## Metric verdicts (round 2)

| Metric | Verdict |
|---|---|
| `LOCKED_FIELD_MUTATIONS` | **0 — CONFIRMED** (all locked-field vectors rejected, incl. smuggled-through-coerced-section and unknown sub-keys; no locked key stored) |
| `UNVERIFIED_WRITES` | **0 — CONFIRMED** (6 independent flush-failure modes all yield 5xx / never `readback_ok:true`; disk read-back via a NEW instance) |
| `ROLLBACK_FAILURES` | **0 — CONFIRMED** |
| `DESTRUCTIVE_CONFIRMATION_BYPASS` | **0 — CONFIRMED** |
| *(new)* `CROSS_PROCESS_LOST_UPDATES` | **>0 — FALSIFIES "no lost change / no lost audit entry"** (RED-D-R2-01) |

---

## Round-1 finding verdicts

### RED-D-01 (MAJOR, unverified write) — **CLOSED**
`apply`/`rollback` now `_persist()` → raise `PersistError` on flush failure, `load()` to
drop the phantom, and `policy_apply`/`rollback` read back through a **new**
`PolicyStore`. Verified against **6** failure modes — every one returns HTTP **5xx**,
never `readback_ok:true`, with the served active version unchanged and no phantom:
- `path is a directory` → `500 persist_failed`
- read-only parent dir (`chmod 0555`) → `500`, disk unchanged, **recovers** after `chmod 0755`
- a regular file where a parent dir should be → `500`
- permission flip mid-run → `500`, disk still holds the pre-flip value, later apply works
- direct `PolicyStore.apply` on an unwritable path → raises `PersistError`, no phantom
- empty `POLICY_FILE` → store is `None` → API `503` (degrades honestly)
Converse (false success) could **not** be produced: in-process symlink path, concurrent
API applies (12×, all 200, unique versions, `active == 1+ok`), all honest.

### RED-D-02 (MINOR, tmp leak) — **CLOSED**
`_flush` unlinks its tmp on failure. Recursive `.tmp` scan across all failure scenarios = 0.

### RED-D-03 (MINOR, section type confusion → 500) — **CLOSED**
`validate_policy` rejects non-object sections. 36 combinations (`persona|language|
teaching|activities|scenarios|limits` × `"x"|5|True|[1,2]|[{"CHAT":"x"}]|None`) all → `400`.

### RED-D-04 (MINOR, deep nesting → 500) — **CLOSED**
`_deep_merge` `RecursionError` → validation error. Depth-400 nesting → `200 valid:false`;
~4000-deep raw body → `400`. No 500.

### RED-D-05 (MINOR, v1 evicted) — **CLOSED**
After 30 applies, `rollback(1)` restores policy **byte-equal to `DEFAULT_POLICY`**; history
stays bounded (21 entries) with the v1 baseline retained as `history[0]`.

### RED-D-06 / 07 / 08 (INFO) — **UNCHANGED (by design)**
"Hard" vocab/label rules remain editable prompt text; policy text is still stored verbatim
(now incl. NUL / ZWSP inside string fields — see R2-03); locked *runtime* fields remain
properly rejected (no accepted-but-ignored field). No regression.

---

## NEW findings (round 2)

### RED-D-R2-01 — MAJOR · Cross-process mutations are not serialised: lost updates and lost audit entries
- **Surface:** `PolicyStore`, `MemoryStore`, `KnowledgeStore` — the per-path lock
  (`_PATH_LOCKS`) is **process-local**; cross-process serialisation relies on the optimistic
  `reload_if_changed()` (file-signature), which has a TOCTOU window between reload and flush.
  No OS-level lock exists (`grep flock|fcntl|LOCK_EX` over `modules/` → none).
- **Precondition:** two processes mutate the same store file concurrently. For **memory** this
  is the *documented* two-writer topology (gateway conversation path + admin plane). For policy
  it needs two admin writers.
- **Reproduction:**
  - Policy: `_policy_mp_worker.py` ×2 (barrier-released), each `apply()` 40× on one file →
    **80 successful applies, only ~41 surviving versions**; both processes report the
    **identical** version sequence `[3..42]` (never interleaved); persisted audit = **~41
    entries < 80** (≈39 audit entries lost). Observed across 3 runs: `(42,80)`,`(44,80)`,`(42,80)`.
  - Memory (gateway+admin): `_memory_mp_worker.py` ×2, each `save()` 40× → **80 successful
    saves, only ~43 items survived** (`(42,81)`,`(45,81)`,`(43,81)`).
- **Expected:** "no lost change, no lost audit entry, no corrupted file" (round-2 brief; and the
  commit's claim that reload→mutate→flush "cannot interleave between the gateway and the admin
  control plane").
- **Actual:** concurrent writers overwrite each other; ~50% of successful mutations and their
  audit entries are silently lost. (In-process concurrency **is** safe — two `PolicyStore`
  instances/threads over one file pass, thanks to the shared in-process lock.)
- **Root cause:** `_path_lock` is a per-process `dict`; no `flock`/`fcntl`; `reload_if_changed`
  is check-then-act without holding a cross-process lock across `reload → mutate → flush`.
- **Status:** open. **The driver log lines also show the failure mode** (`PolicyStore.load()`
  resets `_audit`/`_history` from the file, so a reloading writer discards its own unflushed
  audit entries that the other process already overwrote).

### RED-D-R2-02 — INFO · `_flush` auto-creates missing parent directories
- **Reproduction:** `POLICY_FILE=<tmp>/missing/deep/policy.json` → apply returns `200
  readback_ok:true`; the parent chain is created.
- **Note:** the round-2 brief lists "target parent missing" as an expected flush-failure; it is
  actually a **success** because `_flush` does `p.parent.mkdir(parents=True, exist_ok=True)`.
  Not a bug per se, but an operator-supplied path can cause arbitrary directory creation.
  Only `file-where-a-parent-should-be` fails (→ 500). INFO.

### RED-D-R2-03 — MINOR · Validation accepts visually-empty / control-only persona fields
- **Reproduction:** `{"policy":{"persona":{"name":"\u200b"}}}` (zero-width space) and
  `{"policy":{"persona":{"name":"\x00"}}}` are accepted (`valid:true`); `"\n\t"` is correctly
  rejected because `.strip()` removes it.
- **Expected:** a "non-empty string" should not accept a zero-width or NUL-only value (it
  renders a persona line with no visible name and can blank the persona).
- **Actual:** `_str` uses only `value.strip()`; ZWSP/NUL are not whitespace → accepted. MINOR.

### RED-D-R2-04 — INFO · Symlinked policy path: `os.replace` swaps the link, not the target
- **Reproduction:** `POLICY_FILE=<tmp>/link.json` (symlink → `real.json`); apply returns honest
  `200 readback_ok:true` reading back through the link (consistent — **not** a false success),
  but `os.replace` replaced the symlink with a regular file, leaving `real.json` untouched.
  An operator who configured a symlink would silently stop updating the intended target. INFO.

### RED-D-R2-05 — INFO · Wide/flat document error amplification
- **Reproduction:** `{"policy":{"persona":{...3000 unknown keys...}}}` → `200 valid:false` with
  ~3000 `errors` entries returned in one response (`errors` is not capped in the payload).
  No crash; minor response amplification. INFO.

### Coverage (attacks that found nothing)
- Section type confusion (36 combos) → 400; NaN/Infinity in limits/fields → 400; booleans as
  limits → 400; mixed-type rule arrays → 400; homoglyph/duplicate JSON keys → rejected/collapsed
  safely; depth-400 nesting → 4xx.
- Locked fields: 22 vectors (top-level, nested, smuggled via coerced section) → all 400, zero
  mutations, no key stored.
- Rollback: v1 baseline retained & byte-exact after 30 applies; oldest-retained rollback;
  current-version refused; twice-in-a-row distinct new versions; after-restart; version→content
  mapping stable/ordered (AAA→BBB→AAA replay).
- Neighbouring stores: memory/knowledge read-only-dir edits → `500 persist_failed`, disk
  unchanged, recover after permission restore; `MemoryStore(dir)` raises `PersistError`.
- False-success converse: no way found to get `200 readback_ok:true` without the durable change
  (in-process single-writer).
