"""KNOWLEDGE1_TESTS — deterministic suite for the product-owned Knowledge V1 store.

Runs standalone:  python tests/knowledge1_tests.py   (from gateway/, venv)

Covers: ingestion, chunking, search, top-k, empty-result honesty, duplicates,
malformed documents, disable/enable, delete preview+confirm, provenance,
context bounds, privacy, concurrency, caps, the router knowledge decisions and
the gateway link's bounded retrieval/injection (fake conn/qwen — no network).
"""

import asyncio
import hashlib
import json
import os
import stat
import sys
import tempfile
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from modules.intent import behavior as intent                    # noqa: E402
from modules.knowledge.store import (CapExceeded, ConfirmRequired,  # noqa: E402
                                     DuplicateContent, KnowledgeError,
                                     KnowledgeStore, MalformedDocument,
                                     StoreUnavailable,
                                     chunk_text, extract_pdf_text,
                                     render_knowledge_block)
from types import SimpleNamespace                                  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


HOTEL_DOC = (
    "酒店入住时间是下午三点以后。退房时间是中午十二点前。\n\n"
    "入住时需要出示护照或身份证，前台会核对预订信息。\n\n"
    "酒店提供免费早餐，餐厅在二楼，早餐时间是早上七点到十点。\n\n"
    "The hotel has a gym and a laundry room. Luggage can be stored at the "
    "front desk after checkout."
)
TRAVEL_DOC = (
    "Travel planning: book the flight early, check the visa, and weigh your "
    "luggage at home. Accommodation near the airport is usually cheaper.\n\n"
    "At the airport, arrive two hours before departure. Boarding starts forty "
    "minutes before takeoff."
)


def _mk_store(td, name="kb.json", **kw):
    return KnowledgeStore(os.path.join(td, name), **kw).load()


def main():
    td = tempfile.TemporaryDirectory()
    path = os.path.join(td.name, "kb.json")
    ks = _mk_store(td.name)

    # ---- K1 ingestion + chunking -------------------------------------------
    ds = ks.create_dataset("酒店与出行", description="course reference", tags=["travel"])
    check("K1 dataset created with ds_ id", ds["id"].startswith("ds_")
          and ds["status"] == "enabled")
    doc = ks.add_document(ds["id"], "酒店入住信息", HOTEL_DOC,
                          source_type="text", source_uri="internal://hotel",
                          tags=["hotel"])
    check("K1b document created with doc_ id", doc["id"].startswith("doc_")
          and doc["chunk_count"] >= 1)
    check("K1c content hash = sha256(normalized text)",
          doc["content_hash"] == hashlib.sha256(
              HOTEL_DOC.strip().encode("utf-8")).hexdigest())
    chunks = ks.list_chunks(doc["id"])
    check("K1d chunks readable, ids chk_*, bounded size",
          len(chunks) == doc["chunk_count"]
          and all(c["id"].startswith("chk_") and len(c["text"]) <= 600
                  for c in chunks))
    md = ks.add_document(ds["id"], "出行笔记", TRAVEL_DOC, source_type="markdown")
    check("K1e markdown ingestion accepted", md["chunk_count"] >= 1)
    check("K1f chunker deterministic",
          chunk_text(HOTEL_DOC) == chunk_text(HOTEL_DOC))
    reloaded = _mk_store(td.name)
    check("K1g store reload roundtrip", len(reloaded.list_datasets()) == 1
          and reloaded.get_document(doc["id"])["content_hash"] == doc["content_hash"])

    # ---- K2 duplicates ------------------------------------------------------
    try:
        ks.add_document(ds["id"], "dup", HOTEL_DOC)
        check("K2 duplicate content rejected", False, "no error")
    except DuplicateContent as e:
        check("K2 duplicate content rejected (names existing doc)",
              e.existing_doc_id == doc["id"])
    ds2 = ks.create_dataset("第二组")
    allowed = ks.add_document(ds2["id"], "dup elsewhere", HOTEL_DOC)
    check("K2b same content in another dataset allowed",
          allowed["id"] != doc["id"])
    big = "句子甲。" * 100           # one whole chunk (400 chars, single paragraph)
    dup_doc = ks.add_document(ds2["id"], "重复段落", big + "\n\n" + big)
    check("K2c identical chunks deduplicated inside one document",
          dup_doc["chunk_count"] == 1, repr(dup_doc["chunk_count"]))

    # ---- K3 search ----------------------------------------------------------
    hits = ks.search("酒店退房是几点")
    check("K3 CJK query retrieves the hotel doc", len(hits) >= 1
          and any(h["document_id"] == doc["id"] for h in hits))
    hits_en = ks.search("luggage")
    check("K3b latin query retrieves the hotel doc", len(hits_en) >= 1)
    again = ks.search("酒店退房是几点")
    check("K3c retrieval deterministic (identical order)",
          [h["chunk_id"] for h in hits] == [h["chunk_id"] for h in again])
    check("K3d scores non-increasing",
          all(hits[i]["score"] >= hits[i + 1]["score"] for i in range(len(hits) - 1)))
    check("K3e top_k=1 returns one; top_k=99 capped at 5",
          len(ks.search("酒店", top_k=1)) == 1
          and len(ks.search("酒店 the hotel luggage", top_k=99)) <= 5)
    check("K3f empty query returns []", ks.search("") == []
          and ks.search("   ") == [])
    check("K3g no-match query returns []",
          ks.search("量子计算机的退相干机制") == [])

    # ---- K4 empty-result honesty + block render ------------------------------
    empty_block = render_knowledge_block("量子计算", [])
    check("K4 empty block states honesty explicitly",
          "no matching entry" in empty_block and "never invent" in empty_block)
    hit_block = render_knowledge_block("酒店", hits)
    check("K4b hit block carries provenance + authority line",
          "KNOWLEDGE BASE DATA" in hit_block
          and "酒店入住信息" in hit_block and "authoritative" in hit_block)

    # ---- K5 disable / enable --------------------------------------------------
    ks.set_dataset_enabled(ds["id"], False)
    check("K5 disabled dataset excluded from search", ks.search("酒店退房") == []
          or all(h["dataset_id"] != ds["id"] for h in ks.search("酒店退房")))
    ks.set_dataset_enabled(ds["id"], True)
    check("K5b re-enabled dataset searchable again", len(ks.search("酒店退房")) >= 1)
    check("K5c list shows enabled/disabled counts",
          any(d["id"] == ds["id"] and d["status"] == "enabled"
              for d in ks.list_datasets()))

    # ---- K6 delete preview + confirm ------------------------------------------
    prev = ks.delete_dataset_preview(ds2["id"])
    check("K6 preview counts docs+chunks and exposes confirm token",
          prev["documents"] == 2 and prev["chunks"] >= 2
          and prev["confirm_token"] == ds2["id"])
    try:
        ks.delete_dataset(ds2["id"])
        check("K6b delete without confirmation refused", False, "no error")
    except ConfirmRequired:
        check("K6b delete without confirmation refused", True)
    out = ks.delete_dataset(ds2["id"], confirm=ds2["id"])
    check("K6c confirmed delete removes dataset+documents+chunks",
          out["documents"] == 2 and ks.get_dataset(ds2["id"]) is None
          and ks.search("重复段落 句子甲") == [])

    # ---- K7 malformed / boundary ----------------------------------------------
    def _rejects(fn, exc):
        try:
            fn()
            return False
        except exc:
            return True

    check("K7 empty/whitespace content rejected",
          _rejects(lambda: ks.add_document(ds["id"], "bad", ""), MalformedDocument)
          and _rejects(lambda: ks.add_document(ds["id"], "bad", "   \n  "),
                       MalformedDocument))
    check("K7b bad source_type rejected",
          _rejects(lambda: ks.add_document(ds["id"], "bad", "x" * 20,
                                           source_type="pdf_binary"),
                   MalformedDocument))
    small = _mk_store(td.name, "kb_small.json", max_doc_chars=50)
    sd = small.create_dataset("tiny")
    check("K7c over-long document rejected",
          _rejects(lambda: small.add_document(sd["id"], "long", "长" * 60),
                   MalformedDocument))
    check("K7d unknown dataset rejected",
          _rejects(lambda: ks.add_document("ds_nope", "x", "hello"),
                   KnowledgeError))
    check("K7e empty dataset name rejected",
          _rejects(lambda: ks.create_dataset("   "), KnowledgeError))
    # V4 contract §4: a corrupt/unknown file must be REFUSED, never silently
    # loaded as an empty store and then overwritten.
    corrupt = os.path.join(td.name, "corrupt.json")
    with open(corrupt, "w", encoding="utf-8") as f:
        f.write("{not json")
    cs = KnowledgeStore(corrupt).load()
    check("K7f corrupted file is refused (not silently empty)",
          cs.state()["state"] == "unavailable" and not cs.available)
    check("K7g write refused while unavailable",
          _rejects(lambda: cs.create_dataset("recovered"), StoreUnavailable))
    with open(corrupt, encoding="utf-8") as f:
        check("K7h corrupt bytes are never clobbered", f.read() == "{not json")

    # forward/backward: an unknown NEWER version is refused too
    ahead = os.path.join(td.name, "ahead.json")
    with open(ahead, "w", encoding="utf-8") as f:
        json.dump({"version": 99, "datasets": {}, "documents": {}, "chunks": {}}, f)
    av = KnowledgeStore(ahead).load()
    check("K7i newer schema version is refused",
          av.state()["reason"] == "version_ahead" and not av.available)

    # ---- K8 provenance + rebuild ----------------------------------------------
    r0 = ks.search("酒店退房 luggage")[0]
    check("K8 result provenance complete",
          r0["dataset_name"] == "酒店与出行"
          and r0["document_title"] in ("酒店入住信息", "出行笔记")
          and r0["source"].get("type") in ("text", "markdown")
          and r0["source"].get("added_by") == "operator"
          and isinstance(r0["tags"], list))
    uri_hit = [h for h in ks.search("护照 前台 预订") if h["document_id"] == doc["id"]]
    check("K8b source uri retained on the ingested doc",
          bool(uri_hit) and uri_hit[0]["source"].get("uri") == "internal://hotel")
    insp = ks.inspect_document(doc["id"])
    check("K8c inspect lists preview + chunk count",
          insp["chunk_count"] == doc["chunk_count"]
          and len(insp["chunks_preview"]) >= 1
          and "text" not in insp["document"])
    before_ids = [c["id"] for c in ks.list_chunks(doc["id"])]
    ks.rebuild_chunks(doc["id"])
    after_ids = [c["id"] for c in ks.list_chunks(doc["id"])]
    check("K8d rebuild chunks deterministic (identical ids)", before_ids == after_ids)

    # ---- K9 context bounds -----------------------------------------------------
    many = ks.create_dataset("many")
    for i in range(12):
        ks.add_document(many["id"], "chunk %02d" % i,
                        ("住宿预订说明 %02d。" % i) * 20)
    hits_many = ks.search("住宿预订说明", top_k=5)
    block = render_knowledge_block("住宿预订说明", hits_many)
    head = block.split("\n- ", 1)[0]
    excerpt_portion = block[len(head):]
    check("K9 top-k bound: never more than 5 excerpts", len(hits_many) <= 5)
    check("K9b default excerpt portion bounded (~1200 chars)",
          len(excerpt_portion) <= 1400, repr(len(excerpt_portion)))
    tiny_block = render_knowledge_block("住宿预订说明", hits_many, max_chars=200)
    tiny_excerpts = [ln for ln in tiny_block.split("\n") if ln.startswith("- [")]
    check("K9c custom bound limits excerpts + marks omission",
          len(tiny_excerpts) <= 1 and "omitted" in tiny_block)
    check("K9d whole rendered block bounded (excerpts + header/marker overhead)",
          len(block) <= 1200 + 400 and len(tiny_block) <= 200 + 400,
          (len(block), len(tiny_block)))

    # ---- K10 privacy ------------------------------------------------------------
    raw = open(path, encoding="utf-8").read()
    check("K10 no transcript/audio/progress keys in storage",
          '"transcript"' not in raw and '"audio"' not in raw
          and '"progress"' not in raw and '"lesson"' not in raw)
    st_before = os.stat(path)
    ks.search("酒店")
    st_after = os.stat(path)
    check("K10b search is read-only (file unchanged)",
          (st_before.st_mtime_ns, st_before.st_size)
          == (st_after.st_mtime_ns, st_after.st_size))
    fresh = _mk_store(td.name, "kb_fresh.json")
    check("K10c fresh store holds no auto-ingested content",
          fresh.diagnostics()["documents"] == 0 and fresh.search("a") == [])

    # ---- K11 concurrency ---------------------------------------------------------
    cpath = os.path.join(td.name, "kb_conc.json")
    conc = KnowledgeStore(cpath).load()
    cds = conc.create_dataset("concurrent")
    errors = []

    def writer(n):
        try:
            for i in range(5):
                conc.add_document(cds["id"], "w%d-%d" % (n, i),
                                  "并发写入测试 %d %d 内容。" % (n, i))
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    def reader():
        try:
            for _ in range(10):
                conc.search("并发写入测试")
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    threads += [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = KnowledgeStore(cpath).load()
    check("K11 concurrent writers/readers: no errors", errors == [], repr(errors[:2]))
    check("K11b all concurrent writes persisted (30 docs)",
          final.diagnostics()["documents"] == 30,
          repr(final.diagnostics()["documents"]))
    leftovers = [f for f in os.listdir(td.name) if f.endswith(".tmp")]
    check("K11c no .tmp leftovers", leftovers == [], repr(leftovers))

    # ---- K12 file mode ------------------------------------------------------------
    mode = stat.S_IMODE(os.stat(path).st_mode)
    check("K12 store file mode 600", mode == 0o600, oct(mode))

    # ---- K13 caps ------------------------------------------------------------------
    cap_docs = _mk_store(td.name, "kb_capd.json", max_docs=2)
    cds2 = cap_docs.create_dataset("cap")
    cap_docs.add_document(cds2["id"], "a", "first document")
    cap_docs.add_document(cds2["id"], "b", "second document")
    try:
        cap_docs.add_document(cds2["id"], "c", "third document")
        check("K13 document cap enforced", False, "no error")
    except CapExceeded:
        check("K13 document cap enforced", True)
    cap_ds = _mk_store(td.name, "kb_capds.json", max_datasets=1)
    cap_ds.create_dataset("only")
    try:
        cap_ds.create_dataset("second")
        check("K13b dataset cap enforced", False, "no error")
    except CapExceeded:
        check("K13b dataset cap enforced", True)
    cap_ch = _mk_store(td.name, "kb_capch.json", max_chunks=2)
    cds3 = cap_ch.create_dataset("capch")
    try:
        cap_ch.add_document(cds3["id"], "too many",
                            "第一段内容。" * 60 + "\n\n" + "第二段内容。" * 60
                            + "\n\n" + "第三段内容。" * 60 + "\n\n" + "第四段内容。" * 60)
        check("K13c chunk cap enforced", False, "no error")
    except CapExceeded:
        check("K13c chunk cap enforced", True)

    # ---- K14 diagnostics -------------------------------------------------------
    diag = ks.diagnostics()
    check("K14 diagnostics counts consistent",
          diag["datasets"]["total"] == len(ks.list_datasets())
          and diag["documents"] >= 3 and diag["chunks"] >= 3
          and diag["schema_version"] == 1)
    check("K14b diagnostics exposes caps + storage size",
          diag["caps"]["top_k_max"] == 5 and diag["storage_bytes"] > 0)

    # ---- K15 router decisions ---------------------------------------------------
    st = intent.BehaviorState()
    d = intent.route("知识库里有没有关于酒店入住的内容？", st)
    check("K15 explicit knowledge ask routes to QUERY_KNOWLEDGE",
          d.kind == intent.K_TEMP and d.temporary == intent.QUERY_KNOWLEDGE
          and d.knowledge_explicit and d.knowledge_query)
    check("K15b explicit note references the knowledge base",
          "KNOWLEDGE BASE" in d.note)
    d2 = intent.route("帮我查一下资料里关于住宿的记录", intent.BehaviorState())
    check("K15c 资料+查 routes to knowledge", d2.temporary == intent.QUERY_KNOWLEDGE
          and d2.knowledge_explicit)
    d3 = intent.route("酒店退房是几点", intent.BehaviorState())
    check("K15d implicit question sets a bounded probe only",
          d3.kind == intent.K_NONE and not d3.knowledge_explicit
          and d3.knowledge_query == "酒店退房是几点")
    d4 = intent.route("今天天气不错", intent.BehaviorState())
    check("K15e statements are not probed", d4.knowledge_query is None)
    d5 = intent.route("街道是什么？", intent.BehaviorState())
    check("K15f vocabulary questions keep vocab precedence (no probe)",
          d5.temporary == intent.TRANSLATE and d5.knowledge_query is None)
    d6 = intent.route("我学到哪里了？", intent.BehaviorState())
    check("K15g progress questions answer from the workbench, not knowledge",
          d6.temporary == intent.QUERY_PROGRESS and d6.knowledge_query is None)
    st_r = intent.BehaviorState()
    block_r = intent.render_instructions(st_r, d, knowledge_block="KNOWLEDGE BASE DATA: X")
    check("K15h renderer carries the knowledge block verbatim once",
          block_r.count("KNOWLEDGE BASE DATA: X") == 1)

    # ---- K16 gateway link (fake conn/qwen, no network) --------------------------
    class _FakeQwen:
        def __init__(self):
            self.instructions = None
            self.sent = []

        def set_instructions(self, t):
            self.instructions = t

        async def send_instructions_update(self, t):
            self.sent.append(t)
            self.instructions = t
            return True

    class _FakeConn:
        def is_safe_boundary(self):
            return True

    from app.behavior import BehaviorLink                # noqa: E402

    kb_path = os.path.join(td.name, "kb_link.json")
    lks = KnowledgeStore(kb_path).load()
    lds = lks.create_dataset("客服资料")
    lks.add_document(lds["id"], "入住说明", HOTEL_DOC, source_type="text",
                     source_uri="internal://front-desk")

    async def link_case(transcript):
        q = _FakeQwen()
        conn = _FakeConn()
        cfg = SimpleNamespace(MEMORY_FILE="", WORKBENCH_BASE_URL="",
                              KNOWLEDGE_FILE=kb_path)
        link = BehaviorLink(conn, q, config=cfg)
        await link._on_input_completed({"transcript": transcript, "item_id": "i1"})
        return link, q

    link, q = asyncio.run(link_case("知识库里有没有关于酒店入住的信息？"))
    check("K16 explicit hit injects the bounded block",
          link.stats["knowledge_hits"] == 1
          and link._kb_block is None          # cleared after the successful apply
          and bool(q.sent) and "KNOWLEDGE BASE DATA" in q.sent[-1])
    check("K16b block hot-applied to the session (safe boundary)",
          bool(q.sent) and "KNOWLEDGE BASE DATA" in q.sent[-1])

    link2, q2 = asyncio.run(link_case("酒店退房是几点"))
    check("K16c implicit question with a store match injects",
          link2.stats["knowledge_hits"] == 1
          and bool(q2.sent) and "KNOWLEDGE BASE DATA" in q2.sent[-1])

    link3, q3 = asyncio.run(link_case("月球上一天有多长时间"))
    check("K16d implicit miss injects nothing (no fabrication)",
          link3._kb_block is None and link3.stats["knowledge_misses"] == 1
          and (not q3.sent or "KNOWLEDGE" not in q3.sent[-1]))

    link4, q4 = asyncio.run(link_case("知识库里有关于量子计算的内容吗"))
    check("K16e explicit miss renders the honest empty line",
          link4.stats["knowledge_misses"] == 1 and bool(q4.sent)
          and "no matching entry" in q4.sent[-1])

    link5, _ = asyncio.run(link_case("街道是什么？"))
    check("K16f vocabulary ask never pulls knowledge (precedence)",
          link5._kb_block is None and link5.stats["knowledge_queries"] == 0)

    async def link_ephemeral():
        q = _FakeQwen()
        cfg = SimpleNamespace(MEMORY_FILE="", WORKBENCH_BASE_URL="",
                              KNOWLEDGE_FILE=kb_path)
        link = BehaviorLink(_FakeConn(), q, config=cfg)
        await link._on_input_completed({"transcript": "知识库里有没有酒店入住的信息？",
                                        "item_id": "i1"})
        await link.on_qwen_event({"type": "response.done"})
        await asyncio.sleep(0.05)          # let schedule_apply run
        return link

    link6 = asyncio.run(link_ephemeral())
    check("K16g knowledge block is ephemeral (cleared after the turn)",
          link6._kb_block is None and link6.state.temporary_intent is None)

    async def link_disabled():
        q = _FakeQwen()
        cfg = SimpleNamespace(MEMORY_FILE="", WORKBENCH_BASE_URL="", KNOWLEDGE_FILE="")
        link = BehaviorLink(_FakeConn(), q, config=cfg)
        await link._on_input_completed({"transcript": "知识库里有没有酒店入住的信息？",
                                        "item_id": "i1"})
        return link

    link7 = asyncio.run(link_disabled())
    check("K16h KNOWLEDGE_FILE unset disables retrieval entirely",
          link7.knowledge is None and link7._kb_block is None)

    # ---- K17 PDF-derived text path (external tool; no OCR) -----------------------
    text, reason = extract_pdf_text(os.path.join(td.name, "missing.pdf"))
    check("K17 missing PDF rejected with a clear reason",
          text is None and isinstance(reason, str) and reason)
    text2, reason2 = extract_pdf_text(None)
    check("K17b empty path rejected", text2 is None and isinstance(reason2, str))

    td.cleanup()

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("KNOWLEDGE1_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())