# KNOWLEDGE V1 — product-owned reference knowledge

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 1 Knowledge V1 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Phase 1 of the Product V1 final completion run.  Status: **PASS** (KNOWLEDGE1_TESTS 69/69).

## Ownership

`modules/knowledge/store.py` is the ONLY authoritative knowledge source in Product V1.
The legacy `ai_rag_*` schema is unused; nothing is auto-ingested; Knowledge never becomes
Memory, never holds Workbench progress, and never stores conversation transcripts or audio.

## Data model (closed schema, `version: 1`, one atomic JSON file, mode 600)

| Entity | ID | Fields |
|---|---|---|
| Dataset | `ds_…` | name, description, tags, status(enabled\|disabled), created_at, updated_at |
| Document | `doc_…` | dataset_id, title, content_hash (sha256 of normalized text), chars, normalized text (retained for rebuild), chunk_count, status, source{type∈text/markdown/pdf_text, uri, added_by, added_at}, tags, timestamps |
| Chunk | `chk_…` | document_id, dataset_id, index, text, chars, content_hash |

Chunk ids are deterministic (`sha256(doc_id|index|text)[:16]`) — `rebuild_chunks` on unchanged
content reproduces identical ids.  Identical chunk texts inside one document are stored once.

## Operations

* datasets: create / rename / enable / disable / list (with doc+chunk counts) / delete with
  **preview + explicit confirmation token** (the dataset id);
* documents: add (dedupe by content hash per dataset → `DuplicateContent` naming the existing
  doc) / inspect (metadata + chunk preview, raw text never exposed by `_doc_public`) /
  delete / rebuild chunks / list chunks;
* retrieval: `search(query, top_k≤5, dataset_id?, min_score)` — deterministic scoring
  (latin words + CJK bigrams; +2 exact-substring bonus), stable ordering
  `(score desc, chunk_id asc)`, disabled datasets excluded, provenance on every hit;
* diagnostics: dataset/doc/chunk counts, chunk chars, storage bytes, caps;
* ingestion: plain text / Markdown; PDF-**derived** text via the external `pdftotext` tool
  (`extract_pdf_text`, operator-side only; no OCR, no vendored parser, graceful
  `extractor_unavailable`);
* malformed handling: empty/whitespace or over-long content → `MalformedDocument`;
  unknown dataset/bad source_type/empty name → `KnowledgeError`; corrupted file → fail-soft
  empty store (still writable).

## Bounds and privacy

* Caps: 50 datasets, 100 documents, 100 000 chars/doc, 5 000 chunks, 8 tags, top-k ≤ 5.
* Injection bound: `MAX_INJECTION_CHARS = 1200` — the **whole** rendered block is bounded
  (Phase-8 repair): the excerpt budget = `max_chars` − header length, plus a small fixed
  marker/omission overhead (`K9d` asserts the whole block).
* Empty result renders an explicit honesty line (“no matching entry … never invent”).
* Only explicitly added documents are stored; search is read-only (no flush); the file
  contains no transcript/audio/progress keys.
* Concurrency: `threading.RLock` around every public method; atomic tmp→replace writes;
  verified with 6 writers + 4 readers (30 persisted docs, no `.tmp` leftovers).

## Conversation integration

Router (`modules/intent/behavior.py`) emits `Decision.knowledge_query`:

* **explicit** ask (知识库/资料库, or 资料/文档/笔记/文件 + 查/搜/找/有没有…): temporary intent
  `QUERY_KNOWLEDGE`, `knowledge_explicit=True` — the link retrieves with `min_score=1` and
  always renders a block (honest empty line on a miss);
* **implicit probe**: an unclaimed question-shaped utterance sets only `knowledge_query`
  (`K_NONE`) — the link retrieves with `min_score=2` (`KB_PROBE_MIN_SCORE`, noise guard
  against single-bigram coincidences) and injects **nothing** on a miss;
* vocabulary/grammar/workbench intents keep precedence (they return before the probe).

Gateway link (`gateway/app/behavior.py`): bounded local retrieval (`KB_TOP_K=3`) →
ephemeral `knowledge_block` passed into `render_instructions` → hot-applied at the proven
safe boundary; cleared after the turn (`response.done` / successful apply). Stats:
`knowledge_queries / knowledge_hits / knowledge_misses`.  `KNOWLEDGE_FILE=""` (default)
disables the feature entirely — pure R-1f behaviour preserved.

Frozen surfaces untouched: no changes to `ws.py`, `qwen.py`, audio/pacing/VAD code; the
existing `session.update` instructions-only path is reused.

## Tests

`gateway/tests/knowledge1_tests.py` → **KNOWLEDGE1_TESTS: 69 checks, 69 PASS** (ingestion,
chunking, search, top-k, empty honesty, duplicates, malformed, disable/enable, delete
preview+confirm, provenance, rebuild determinism, context bounds, privacy, concurrency,
caps, diagnostics, router decisions, link injection with fake conn/qwen, PDF path).

Regression at Phase 1 (no drift): BEHAVIOR1 111/111, VOCAB_ACCURACY 79/79, MEMORY1 19/19,
WORKBENCH1 25/25 (fixture made date-relative — the hardcoded “future” review date had become
“today”), MVP_INTEGRATION 28/28, ADMIN1 80/80, R-1F 179/180 (known local libopus sentinel).

## Rollback

Feature is off by default (`KNOWLEDGE_FILE=""`).  Phase commit is revertible; rollback tag
`product-v1-pre-run` + bundle `admin0-backups/product-v1-pre-run.bundle` cover the whole run.