# modules/knowledge

Ownership boundary: **product-owned reference / document knowledge layer (KNOWLEDGE V1)** —
datasets → documents → chunks, deterministic retrieval, bounded context injection.

Implemented in `store.py`:

* `KnowledgeStore` — closed-schema JSON store (atomic 600 writes, `ds_`/`doc_`/`chk_` ids,
  content hashes, provenance, enable/disable, delete-with-preview+confirm, rebuild, diagnostics);
* deterministic chunker (`chunk_text`) and top-k token-overlap search (latin words + CJK
  bigrams, disabled datasets excluded, honest empty result);
* `render_knowledge_block` — bounded (`MAX_INJECTION_CHARS`) ephemeral instruction block;
* `extract_pdf_text` — PDF-*derived* text via the external `pdftotext` tool (no OCR).

This store is the only authoritative knowledge source in Product V1 (legacy `ai_rag_*` tables
are unused and nothing is auto-ingested). Conversation transcripts, raw audio and Workbench
progress are never written here. See `docs/engineering/product-v1/KNOWLEDGE-V1.md`.