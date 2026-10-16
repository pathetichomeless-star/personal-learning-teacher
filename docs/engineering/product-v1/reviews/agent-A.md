# AGENT A — Architecture / Ownership Review (READ-ONLY)

- Reviewed commit: `52facaa24b5b8c97f805e019e66b087faf9ac46b` (HEAD, main; worktree clean)
- Date: 2026-10-08 (Asia/Shanghai)
- Verdict line at the end.

## Method

Files read: `modules/{adapters/workbench,intent/behavior,policy/persona,memory/store,knowledge/store}.py`,
`gateway/app/behavior.py`, `gateway/app/main.py`, `gateway/app/turns.py` (L248-290, L520-600, L1100-1115),
`gateway/app/qwen.py` (L390-429), `gateway/app/admin/{app,service,stores,api,registry}.py`,
`gateway/tests/product_boundary_tests.py`.

Commands (verbatim results):
- `git diff 2fd8d4f..52facaa -- gateway/app/turns.py gateway/app/ws.py gateway/app/audio.py gateway/app/qwen.py`
  → **empty (no output)**. Also `-- gateway/app/protocol.py gateway/app/counters.py gateway/app/diag.py gateway/app/http.py` → **empty**.
- `cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/product_boundary_tests.py` →
  `======================================================================`
  `PRODUCT_BOUNDARY_TESTS: 23 checks, 23 PASS, 0 FAIL`
  (preceded by 6× `memory flush failed: [Errno 2] ... m.tmp -> m.json` log lines — see M2; suite still 23/23).
- Grep `modules/` for `gateway|app|opus|audio` imports → only docstrings; no real cross-imports.

## Findings

### BLOCKER — none

### MAJOR — none

### MINOR

1. **Duplicated prompt text in `Decision` notes (not composed from the policy helpers).**
   `modules/intent/behavior.py:705-708` states "every prompt line is composed from the active
   policy"; the rendered policy block IS injected, but several per-turn notes hard-code teaching
   text that also lives in the policy, so a policy edit will NOT propagate to them:
   - `behavior.py:655-658` ("FIRST its Chinese meaning, then the English word itself, its
     pronunciation …") ≈ `policy/persona.py:70-72` `word_explanation_order`.
   - `behavior.py:617-618` ("Teach 1-3 useful words … word, Chinese meaning, pronunciation, one
     example, then a quick check") ≈ `policy/persona.py:76-77` `vocabulary_format`.
   - `behavior.py:310-313`, `328-333`, `644-648` (canonical-spelling-FIRST / letter-by-letter
     spelling rule) ≈ `policy/persona.py:83-87` `canonical_spelling_rules[0..2]`.
   Bounded: the authoritative block is rendered alongside (`behavior.py:747-750` →
   `render_vocab_policy`), so single-source-of-authority is preserved; impact is drift/maintenance only.
2. **Shared `.tmp` filename in the atomic-flush path races across instances.**
   `policy/persona.py:451`, `knowledge/store.py:290`, `memory/store.py:209` all use
   `p.with_suffix(".tmp")` (one fixed name). Concurrent flushes — and the admin-plane vs
   gateway-plane store instances sharing the same file — can collide, producing the observed
   `memory flush failed: ... m.tmp -> m.json` (`_flush` swallows it, `memory/store.py:204-221`).
   Fail-soft + atomic `os.replace` ⇒ no corruption and no raised error; worst case is a dropped
   flush (previous valid content retained). Severity MINOR.
3. **Duplicate class definition.** `modules/adapters/workbench.py:31` and `:279` both declare
   `class WorkbenchError(Exception): pass` (the second is dead). Cosmetic.

### INFO

4. **Admin plane owns no mirrored state.** `AdminStores` (`admin/stores.py:70-93`) constructs
   live store instances over the *same* files the gateway uses (`main.py:108-114`), and reads the
   live session registry via weakrefs (`admin/registry.py:28-78`, no writes). No duplication.
5. **Realtime separation intact.** Safe-boundary gate `_current_gen is None and not tts_active and
   pacer_task is None` (`turns.py:263-266`); apply deferred otherwise (`behavior.py:372-375`);
   hot-apply is instructions-only `{"session":{"instructions":…}}` (`qwen.py:400-412`) — never
   model/voice/VAD/formats. Link consumes text/session events only (`behavior.py:186-203`; wired
   `turns.py:583`). No audio-plane edits.
6. **Source-of-truth boundaries.** Workbench is GET-only (`workbench.py:91`; no PUT/POST). Memory
   hard-rejects progress-shaped keys/values and secrets (`memory/store.py:51-65`, `226-263`,
   `assert_no_progress_keys:539`). Knowledge owns `ds_/doc_/chk_` ids (`knowledge/store.py:352,463,480`);
   legacy `ai_rag_*` appears only in a comment (`:5`). Admin has no Workbench write route (`api.py:477-523`).
7. **Modules purity.** `modules/*` import only stdlib (+ `aiohttp` in the I/O adapter `workbench.py`);
   no gateway/audio imports.

## Conclusion

No BLOCKER and no MAJOR. Module purity, single-source boundaries, realtime separation and the
admin plane's no-mirroring design all hold; frozen realtime surfaces are byte-unchanged and the
boundary suite is 23/23. Only MINOR duplication/cleanup items remain.

AGENT_A = PASS