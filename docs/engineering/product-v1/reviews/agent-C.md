# AGENT C — Memory V1 Review (READ-ONLY)

- Reviewed commit: `52facaa24b5b8c97f805e019e66b087faf9ac46b` (HEAD)
- Date: 2026-10-08 (Asia/Shanghai)
- Scope: `modules/memory/store.py`; wiring `gateway/app/behavior.py`
  (`_memory_block`, `_maybe_reload_stores`, side effects, weak word);
  `gateway/app/admin/api.py` memory routes; `gateway/tests/memory_v1_tests.py`,
  `memory1_tests.py`; `docs/engineering/product-v1/MEMORY-V1.md`.
- Verdict line at the end.

## Method

Read the files above in full. Ran (from `gateway/`, verbatim tails):
- `... python tests/memory_v1_tests.py` → `MEMORY_V1_TESTS: 54 checks, 54 PASS, 0 FAIL`
- `... python tests/memory1_tests.py` → `MEMORY1_TESTS: 19 checks, 19 PASS, 0 FAIL`
- Two independent probe scripts via stdin (no repo writes): (1) weak-word vs
  progress keys; (2) crafted-file load; (3) admin `edit()` validation; (4) caps.

## Findings

### MAJOR — Load/migration seam performs no boundary validation (boundary bypass)

`MemoryStore.load()` (store.py:180-198) deserializes every item via
`MemoryItem.from_json()` (store.py:110-127) and re-keys it, **with no
`_validate_key`/`_validate_value` call**. `from_json` only normalizes
`entity`→`entity_type` and strips a `vocab:` prefix; it never rejects.
Consequently a v1/corrupt-recovered/hand-edited JSON file imports
progress-shaped keys, secret-shaped **values**, and unknown `entity_type`
values that the write interface refuses — and `context()` then injects them
into the conversation prompt.

Probe 2 (crafted file) reproduced all of:
`loaded items: [('profile_fact','lesson_progress','第3课'), ('profile_fact','pw','my password is hunter2'), ('vocab_item','progress',{...}), ('','whatever','v')]`;
`context('lesson progress') → ['lesson_progress','progress']`.
Also `boundary_diagnostics().secret_keys_present == []` for the loaded secret
value — the diagnostic scans keys only (store.py:548), so loaded secret
**values** are invisible, giving false assurance. `assert_no_progress_keys()`
does flag the loaded progress keys, but they are already usable.

Reachability caveat: no in-band writer emits such content — `_flush`
(store.py:204-221) serializes only validated items, and every admin route
(`edit`/`delete`/`clear-category`, api.py:244-292) validates. Exploitation
requires out-of-band write to the 0600 file. Severity reflects that the
headline invariant ("can never hold progress/secrets", doc §Ownership) is
violated through the explicitly-flagged load/migration path, not that it is
remotely reachable.

### MINOR — `note_weak_word()` bypasses key validation; doc overclaims

`note_weak_word` (store.py:345-357) calls `_upsert` directly, skipping
`_validate_key`. Probe 1: `progress/review/pass/score/course/lesson/mastery/repeat`
are all stored as `vocab_item`, so
`assert_no_progress_keys()` returns `['vocab:progress', ...]` on a store that
only wrote legitimate weak words. This contradicts MEMORY-V1.md ("progress-shaped
keys … on **every** entity", line 44-47) and creates a self-check false
positive. Behaviour is defensible (they are genuine English words; test V7
checks only `profile_fact/habit/continuity/preference`), so the defect is the
doc/test claim, not the store.

### MINOR — `render_memory_block` header is outside the char budget

`render_memory_block` (store.py:561-579) counts only item lines against
`max_chars`; the 153-char consent header is uncounted (probe: item cost 2 →
block len 175). Bounded, but the rendered block can exceed `max_chars`
(400+153). `context()` itself respects ≤limit and ≤max_chars.

### INFO — requirements verified independently (all pass)

Entity classes/fields exactly as specified (store.py:41,88-108); per-user
partition (load/write keyed by `self.user`); atomic tmp→replace + `chmod 600`
(store.py:213-216); corrupted file → empty, still writable; caps 200/40/300 +
confidence ∈[0,1]; provenance/confidence mandatory; `context()` excludes
preferences, token-overlap only, deterministic; explicit save requires
`_match_save_preference` commit phrase (behavior.py:685-698), forget requires
explicit phrase; bytes refused (store.py:243); over-long transcript-sized
values refused (store.py:250); closed entity set; admin `edit()` rejects
secret/progress/over-long/dict values (probe 3). Memory never duplicates
Workbench state; `_mem_block` is ephemeral, recomputed per turn and nulled
after a successful apply (behavior.py:256,399); no conversation text is
persisted (only enum preference + weak-word).

## Verdict

MAJOR boundary bypass on the load/migration seam (no validation in
`load()`/`from_json`), with concrete reproduction and false-assurance
diagnostics.

AGENT_C = FAIL

---

## RE-CHECK @ 90b8ab4

Re-verified at `90b8ab46b6c6de5348069390740369b97fabfacb` (worktree clean).

Method: re-read `modules/memory/store.py` (load `_item_passes_boundary`,
`boundary_diagnostics`, `assert_no_progress_keys`, `reload_if_changed`/`_flush`),
the new V14 checks, and re-ran the original probes plus new interleave probes.

Commands (verbatim tails):
- `DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/memory_v1_tests.py` →
  `MEMORY_V1_TESTS: 60 checks, 60 PASS, 0 FAIL`
- `DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/memory1_tests.py` →
  `MEMORY1_TESTS: 19 checks, 19 PASS, 0 FAIL`

Probe A (re-run original poison file) — kept `[('continuity','topic')]` only;
logs `dropped out-of-boundary item` for profile_fact/progress, preference
progress-key, `mystery`, continuity over-long, habit dict; `context("lesson progress
password hunter2") == []`; diagnostics all four lists `[]`; legit item retained.
Probe B (poisoned `vocab_item` values) — see MINOR below.
Probe C (two coexisting writers) — `final keys: ['a','b','c']`, `temp leftovers: []`.

Closure status:
- Original **MAJOR — load/migration boundary bypass: CLOSED** for every
  non-vocab class. `load()` now routes each item through `_item_passes_boundary`
  (store.py:192, 288-306): unknown `entity_type`, progress/secret keys,
  secret/progress/over-long/dict values on `preference`/`profile_fact`/`habit`/
  `continuity` are dropped + logged; `boundary_diagnostics` scans values
  (store.py:589-594); `context()` no longer returns them. Validators are
  symmetric with the write path, so no legitimate item is lost on load.
- MINOR #1 (doc overclaim) — **OPEN**: `MEMORY-V1.md:44-46` still says
  "on **every** entity" and line 3/62 still say `54 checks`; the store now
  exempts `vocab_item` (`assert_no_progress_keys`, store.py:572-580), which is
  the correct behaviour but the doc/test-count were not updated.
- MINOR #2 (render header outside budget) — **OPEN**, unchanged
  (store.py:611-626).

New finding (MINOR, residual of the original seam): a poisoned `vocab_item`
**value** is not validated at load — `_item_passes_boundary` checks only the
word shape (store.py:293-297), mirroring the write path which fixes the value to
`{"status":"weak"}`. Probe B loaded `vocab:foo` with value `"my password is
hunter2"` and `vocab:bar` with a ~1.5 KB transcript; both surfaced via
`items()`/`vocab_items()`/`search("password hunter2")`, and `context("password
hunter2")` matched `foo`. Impact is low: reachable only by out-of-band edit of
the 0600 file (no writer produces a str vocab value), `render_memory_block`
prints only the word (store.py:617-619) so the conversation prompt is not
leaked — hence MINOR, not a re-open of the MAJOR.

New-hole checks: `reload_if_changed()` in mutators is safe (Probe C — no lost
writes, no `.tmp` leftovers); unique tmp names (`p.name + ".<hex>.tmp"`) present
in memory/knowledge/policy stores; no legit-item loss from load validation.

## Verdict (re-check)

Original MAJOR closed for all product-relevant classes; only MINOR residuals
remain.

AGENT_C = PASS