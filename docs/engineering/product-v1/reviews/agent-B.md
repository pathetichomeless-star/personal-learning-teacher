# Agent B — Knowledge V1 review (RAW)

Reviewed commit: `52facaa24b5b8c97f805e019e66b087faf9ac46b` (2026-10-08). Read-only; no product file modified.

## Method
Files read: `modules/knowledge/store.py`, `gateway/app/behavior.py`, `gateway/app/admin/api.py`, `gateway/app/admin/stores.py`, `modules/intent/behavior.py`, `gateway/app/main.py`, `gateway/tests/knowledge1_tests.py`, `docs/engineering/product-v1/KNOWLEDGE-V1.md`.

Command run:
```
cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/knowledge1_tests.py
```
Verbatim summary line:
```
KNOWLEDGE1_TESTS: 69 checks, 69 PASS, 0 FAIL
```

Ad-hoc probes (stdin heredoc; nothing written inside the repo):
- `PROBE1 total=1508 header=230 excerpt=1278 MAX=1200`
- `PROBE2 datasets=1 names=['B']`
- `PROBE3 rejected: MalformedDocument too_long (199 > 50 chars)`
- `PROBE4 stable: True scores: [7, 7, 7, 7, 7]`
- `PROBE5 empty: True nomatch: True`

## Findings
- **MINOR — injection "bound" is soft, not a hard cap.** `render_knowledge_block` (`store.py:654-681`) budgets only excerpt lines; the header (`store.py:665-668`) and the omission-marker line (`store.py:677`) are outside the budget. PROBE1: total block 1508 chars, header 230, excerpt portion 1278 — every value exceeds `MAX_INJECTION_CHARS=1200` (`store.py:59`). The doc (`KNOWLEDGE-V1.md:43-44`) and test K9b (`knowledge1_tests.py:228-229`, asserts ≤1400) treat it as a soft target. Output stays deterministic and small, so not blocking, but the name overstates the guarantee.
- **MINOR — cross-instance writes are not serialized (lost update).** The RLock is per-instance (`store.py:237`) and each instance caches `_data` without re-reading before flush (`store.py:285-303`). PROBE2: two instances loaded from the same empty file; `A.create_dataset` then `B.create_dataset` → only `'B'` survives. Not reachable today: the gateway never writes knowledge — `search`/`get`/`list` call no `_flush` — the only writer is the admin plane's single instance (`admin/stores.py:79`). Latent risk only if a second writer is added; the "concurrency safety" claim holds for one instance/many threads (K11), not across instances.
- **INFO — tmp-path collision.** `_flush` writes `p.with_suffix(".tmp")` (`store.py:290`); distinct store paths sharing a stem (e.g. `kb.json` and `kb.txt`) map to the same tmp file. Not hit in the shipped layout/tests.
- **INFO — confirmation styles differ but both explicit.** `knowledge_dataset_delete` requires `confirm == ds_id` (`api.py:371`, `store.py:417-425`); `knowledge_document_delete` requires `confirm: true` (`api.py:429`, `api.py:127-131`). Both are explicit-confirmation; consistent with the spec.

## Verified correct (no finding)
1. **Data model** — `ds_`/`doc_`/`chk_` prefixes (`store.py:352,463,480`); tags/timestamps/status/`content_hash`/`source{type,uri,added_by,added_at}` present; schema closed to `{datasets,documents,chunks}` (`store.py:238`); `ai_rag_*` appears only in comments/docs, never in code (grep).
2. **Operations** — dataset create/rename/enable/disable/list/delete-with-preview+confirm (`store.py:345-438`; `api.py:305-379`); document add/inspect/delete/rebuild + list chunks (`store.py:442-566`); search; diagnostics; all routes registered (`api.py:597-610,634-647`).
3. **Retrieval** — k clamped to `TOP_K_MAX=5` (`store.py:585`); stable `(score desc, chunk_id asc)` sort (`store.py:603`); disabled datasets skipped (`store.py:592-594`); provenance on every hit (`store.py:608-617`); honest empty line (`store.py:660-664`); bounded render (`store.py:654-681`). PROBE4/5 confirm stability and empty behaviour.
4. **Malformed/duplicate** — empty/whitespace/over-long → `MalformedDocument` (`store.py:334-341`, PROBE3); duplicate-per-dataset → `DuplicateContent` naming the existing id (`store.py:454-456,81-83`); corrupted file fails soft to an empty, still-writable store (`store.py:273-275`; K7f/g).
5. **Privacy** — only mutation methods call `_flush` (`store.py:358,390,401,436,475,547,565`); search/get/list do not write; storage holds no transcript/audio/progress keys (K10).
6. **Conversation integration** — explicit vs implicit probe with `KB_PROBE_MIN_SCORE=2` noise guard (`behavior.py:325`); the probe sits in §10, after every vocabulary/workbench/command/activity/reflex handler has returned (`behavior.py:406-422,580-588`); stat/hot-apply/ephemeral behaviour confirmed (K16).
7. **Test suite** — 69/69 PASS.

AGENT_B = PASS