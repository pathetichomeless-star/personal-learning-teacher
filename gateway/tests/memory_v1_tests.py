"""MEMORY_V1_TESTS — deterministic suite for the upgraded Memory V1 store.

Runs standalone:  python tests/memory_v1_tests.py   (from gateway/, venv)

Covers: all five entity classes, save/list/search/inspect/edit/delete/forget/
forget-by-category/category summary, per-user partition, atomic persistence,
corruption fail-soft, caps, provenance/confidence, expiry, bounded +
relevance-filtered conversational injection, the Workbench-progress hard
boundary and secret/audio/transcript abuse attempts, plus the gateway link's
explicit save/forget/weak-word flow with a fake conn/qwen (no network).
"""

import asyncio
import json
import os
import stat
import sys
import tempfile
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from modules.memory.store import (BoundaryViolation, ConfirmRequired,  # noqa: E402
                                  MemoryStore, render_memory_block)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def _rejects(fn, exc=BoundaryViolation):
    try:
        fn()
        return False
    except exc:
        return True


def main():
    td = tempfile.TemporaryDirectory()
    path = os.path.join(td.name, "memory_v1.json")
    ms = MemoryStore(path).load()

    # ---- V1: entity classes save / reload roundtrip --------------------------
    ms.save_preference("explanation_language", "zh")
    ms.save("profile_fact", "name", "小王")
    ms.save("habit", "answer_length", "prefers short answers")
    ms.save("continuity", "topic", "hotel check-in practice")
    ms.note_weak_word("accommodation")
    ms2 = MemoryStore(path).load()
    check("V1 reload roundtrip: preferences",
          ms2.preferences() == {"explanation_language": "zh"})
    check("V1b reload roundtrip: profile_fact/habit/continuity",
          {i["key"] for i in ms2.list_items(entity="profile_fact")} == {"name"}
          and {i["key"] for i in ms2.list_items(entity="habit")} == {"answer_length"}
          and {i["key"] for i in ms2.list_items(entity="continuity")} == {"topic"})
    check("V1c reload roundtrip: vocab_item",
          ms2.vocab_items() == {"accommodation": {"status": "weak"}})

    # ---- V2: schema of every item ---------------------------------------------
    it = ms2.list_items(entity="profile_fact")[0]
    check("V2 item carries id/user_id/entity_type/key/value/source/confidence/timestamps",
          it["id"].startswith("mem_") and it["user_id"] == "default"
          and it["entity_type"] == "profile_fact" and it["key"] == "name"
          and it["value"] == "小王" and it["source"] == "explicit_user"
          and it["confidence"] == 1.0 and it["created_at"] > 0
          and it["updated_at"] >= it["created_at"] and it["expires_at"] is None)

    # ---- V3: list / category summary ------------------------------------------
    summ = ms2.category_summary()
    check("V3 category summary counts", summ["preference"]["count"] == 1
          and summ["profile_fact"]["count"] == 1 and summ["habit"]["count"] == 1
          and summ["continuity"]["count"] == 1 and summ["vocab_item"]["count"] == 1
          and all(summ[e]["last_updated"] for e in summ))
    check("V3b list_items(entity=) filters",
          [i["key"] for i in ms2.list_items(entity="habit")] == ["answer_length"])

    # ---- V4: search / inspect / edit / delete ----------------------------------
    hits = ms2.search("小王")
    check("V4 search by value token", len(hits) == 1 and hits[0]["key"] == "name")
    check("V4b search mismatch returns []", ms2.search("量子化学") == [])
    check("V4c search empty query returns []", ms2.search("") == [])
    fid = it["id"]
    check("V4d inspect by id", ms2.inspect(fid)["key"] == "name"
          and ms2.inspect("mem_nope") is None)
    edited = ms2.edit(fid, value="小李", confidence=0.9)
    check("V4e edit value + confidence persisted",
          MemoryStore(path).load().inspect(fid)["value"] == "小李"
          and edited["confidence"] == 0.9)
    check("V4f edit invalid value rejected (closed enums)",
          _rejects(lambda: ms2.edit(
              [i["id"] for i in ms2.list_items(entity="preference")][0], value="fr")))
    check("V4g edit unknown id rejected", _rejects(lambda: ms2.edit("mem_nope",
                                                                    value="x")))
    tmp_ex = ms2.save("continuity", "temp", "temporary note", expires_at=1.0)
    check("V4h delete by id",
          ms2.delete(tmp_ex.id) is True and ms2.inspect(tmp_ex.id) is None
          and ms2.delete("mem_nope") is False)

    # ---- V5: expiry ------------------------------------------------------------
    ms.save("continuity", "old", "expired context", expires_at=1.0)
    check("V5 expired item excluded from search/context/list(excl)",
          ms.search("expired context") == []
          and ms.context("expired context") == []
          and all(i["key"] != "old"
                  for i in ms.list_items(include_expired=False)))
    check("V5b expired item still visible in full list (flagged)",
          any(i["key"] == "old" and i["expired"] for i in ms.list_items()))

    # ---- V6: forget / forget-by-category ---------------------------------------
    check("V6 forget one preference by key",
          ms.forget("explanation_language") == ["explanation_language"]
          and "explanation_language" not in ms.preferences())
    ms.save_preference("speed", "slow")
    ms.save_preference("difficulty", "hard")
    check("V6b forget() removes the most recently updated preference",
          ms.forget() == ["difficulty"] and ms.preferences() == {"speed": "slow"})
    check("V6c forget unknown key is a no-op", ms.forget("nope") == [])
    check("V6d category clear requires confirmation",
          _rejects(lambda: ms.forget_category("habit"), ConfirmRequired))
    n = ms.forget_category("habit", confirm="habit")
    check("V6e confirmed category clear removes only that category",
          n == 1 and ms.list_items(entity="habit") == []
          and len(ms.list_items(entity="continuity")) >= 1)
    check("V6f unknown category rejected",
          _rejects(lambda: ms.forget_category("progress", confirm="progress")))

    # ---- V7: hard boundary — Workbench progress can never enter -----------------
    progress_keys = ["lesson_progress", "课程进度", "next_review", "mastery",
                     "pass_state", "review_date", "repeat_count", "course_progress",
                     "复习日期", "掌握度"]
    all_rejected = True
    for key in progress_keys:
        for entity in ("profile_fact", "habit", "continuity", "preference"):
            if not _rejects(lambda k=key, e=entity: ms.save(e, k, "x")):
                all_rejected = False
                print("      NOT REJECTED: entity=%s key=%r" % (entity, key))
    check("V7 progress-shaped keys rejected on every entity", all_rejected)
    check("V7b progress-shaped value rejected",
          _rejects(lambda: ms.save("continuity", "note", "我的课程进度是第3课")))
    check("V7c closed entity set (fact/mistake/audio rejected)",
          _rejects(lambda: ms.save("fact", "k", "v"))
          and _rejects(lambda: ms.save("mistake", "k", "v"))
          and _rejects(lambda: ms.save("audio", "k", "v")))

    # ---- V8: secrets / audio / transcripts --------------------------------------
    check("V8 secret-shaped keys rejected",
          all(_rejects(lambda k=k: ms.save("profile_fact", k, "x"))
              for k in ("password", "api_key", "密码", "token", "credentials")))
    check("V8b secret-shaped values rejected",
          _rejects(lambda: ms.save("profile_fact", "note", "my password is hunter2"))
          and _rejects(lambda: ms.save("profile_fact", "note", "密码是 abc123")))
    check("V8c raw audio (bytes) rejected",
          _rejects(lambda: ms.save("continuity", "clip", b"\x00\x01\x02")))
    check("V8d whole transcript (over-long value) rejected",
          _rejects(lambda: ms.save("continuity", "chat", "用户说的话。" * 60)))
    check("V8e confidence out of range rejected",
          _rejects(lambda: ms.save("habit", "x", "v", confidence=1.5))
          and _rejects(lambda: ms.save("habit", "y", "v", confidence=-0.1)))
    raw = open(path, encoding="utf-8").read()
    check("V8f storage contains no transcript/audio keys",
          '"transcript"' not in raw and '"audio"' not in raw)
    diag = MemoryStore(path).load().boundary_diagnostics()
    check("V8g boundary diagnostics clean after all abuse attempts",
          diag["forbidden_keys_present"] == [] and diag["secret_keys_present"] == []
          and diag["total_items"] == len(MemoryStore(path).load().items()))

    # ---- V9: per-user partition ---------------------------------------------------
    p2 = os.path.join(td.name, "mem_users.json")
    ua = MemoryStore(p2, user="userA").load()
    ua.save("profile_fact", "name", "A")
    check("V9 per-user isolation",
          MemoryStore(p2, user="userB").load().list_items() == []
          and len(MemoryStore(p2, user="userA").load().list_items()) == 1)

    # ---- V10: corruption fail-soft, migration, mode, atomic ------------------------
    bad = os.path.join(td.name, "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{not json")
    ms_bad = MemoryStore(bad).load()
    check("V10 corrupted storage fails soft to empty", ms_bad.items() == [])
    ms_bad.save("continuity", "topic", "after recovery")
    check("V10b writable after recovery",
          MemoryStore(bad).load().list_items(entity="continuity")[0]["key"] == "topic")
    legacy = os.path.join(td.name, "legacy_v1.json")
    with open(legacy, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "users": {"default": {"items": {
            "speed": {"id": "mem_legacy", "entity": "preference", "key": "speed",
                      "value": "slow", "source": "explicit_user", "confidence": 1.0,
                      "created_at": 1.0, "updated_at": 1.0}}}}}, f)
    ms_legacy = MemoryStore(legacy).load()
    check("V10c v1 file migrates (entity → entity_type)",
          ms_legacy.preferences() == {"speed": "slow"}
          and ms_legacy.items()[0]["entity_type"] == "preference")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    check("V10d file mode 600", mode == 0o600, oct(mode))
    leftovers = [f for f in os.listdir(td.name) if f.endswith(".tmp")]
    check("V10e no .tmp leftovers", leftovers == [], repr(leftovers))

    # ---- V11: caps ------------------------------------------------------------------
    cap = MemoryStore(os.path.join(td.name, "cap.json")).load()
    for i in range(200):
        cap.save("continuity", "k%03d" % i, "v%03d" % i)
    check("V11 item cap enforced",
          _rejects(lambda: cap.save("continuity", "overflow", "v"))
          and len(MemoryStore(os.path.join(td.name, "cap.json")).load().items()) == 200)

    # ---- V12: bounded + relevance-filtered conversational injection -------------------
    inj = MemoryStore(os.path.join(td.name, "inj.json")).load()
    inj.save_preference("speed", "slow")
    inj.save("profile_fact", "hometown", "杭州")
    inj.save("habit", "answer_length", "prefers short answers")
    inj.save("continuity", "topic", "hotel check-in practice")
    inj.note_weak_word("reservation")
    ctx = inj.context("杭州 是哪里")
    check("V12 relevance filter keeps only matching items",
          len(ctx) == 1 and ctx[0]["key"] == "hometown")
    check("V12b preferences are never in the context block (separate line)",
          all(c["entity_type"] != "preference" for c in inj.context("杭州 speed")))
    check("V12c context mismatch returns []", inj.context("量子化学") == [])
    check("V12d context without query returns []", inj.context("") == [])
    for i in range(8):
        inj.save("continuity", "topic%02d" % i, "hotel topic %02d" % i)
    ctx8 = inj.context("hotel topic", limit=4)
    check("V12e item limit respected", len(ctx8) <= 4 and len(ctx8) >= 1)
    ctx_tight = inj.context("hotel topic", limit=10, max_chars=40)
    check("V12f char budget shrinks the injection",
          len(ctx_tight) < len(inj.context("hotel topic", limit=10)))
    blk = render_memory_block(ctx8)
    check("V12g rendered block bounded + consent line",
          len(blk) <= 400 + 200 and "explicit consent" in blk)
    check("V12h empty items render empty block", render_memory_block([]) == "")
    vblk = render_memory_block(inj.context("reservation"))
    check("V12i weak-word line phrasing",
          "marked this word as unknown: reservation" in vblk)

    # ---- V14: load-seam boundary enforcement (MAJOR-repair) ----------------------
    poison = os.path.join(td.name, "poison.json")
    with open(poison, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "users": {"default": {"items": {
            "lesson_progress": {"id": "mem_p1", "user_id": "default",
                                "entity_type": "preference", "key": "lesson_progress",
                                "value": "x", "source": "x", "confidence": 1.0,
                                "created_at": 1.0, "updated_at": 1.0,
                                "expires_at": None},
            "profile_fact:note": {"id": "mem_p2", "user_id": "default",
                                  "entity_type": "profile_fact", "key": "note",
                                  "value": "my password is hunter2", "source": "x",
                                  "confidence": 1.0, "created_at": 1.0,
                                  "updated_at": 1.0, "expires_at": None},
            "continuity:topic": {"id": "mem_p3", "user_id": "default",
                                 "entity_type": "continuity", "key": "topic",
                                 "value": "hotel practice", "source": "x",
                                 "confidence": 1.0, "created_at": 1.0,
                                 "updated_at": 1.0, "expires_at": None},
            "mystery:x": {"id": "mem_p4", "user_id": "default",
                          "entity_type": "mystery", "key": "x", "value": "v",
                          "source": "x", "confidence": 1.0, "created_at": 1.0,
                          "updated_at": 1.0, "expires_at": None}}}}}, f)
    msp = MemoryStore(poison).load()
    check("V14 load drops progress-key / secret-value / unknown-entity items",
          [i["key"] for i in msp.items()] == ["topic"], msp.items())
    pd = msp.boundary_diagnostics()
    check("V14b post-load diagnostics clean (keys AND values)",
          pd["forbidden_keys_present"] == [] and pd["secret_keys_present"] == []
          and pd["forbidden_values_present"] == []
          and pd["secret_values_present"] == [])
    check("V14c dropped items cannot be injected",
          msp.context("lesson progress password hunter2") == []
          and msp.context("hotel practice") != [])
    msp.save("continuity", "ok", "still writable")
    check("V14d store writable after a poisoned load",
          len(MemoryStore(poison).load().items()) == 2)
    msp.note_weak_word("progress")
    check("V14e vocab words like 'progress' are words, not progress keys",
          "progress" in msp.vocab_items() and msp.assert_no_progress_keys() == [])
    poison2 = os.path.join(td.name, "poison2.json")
    with open(poison2, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "users": {"default": {"items": {
            "continuity:note": {"id": "mem_q1", "user_id": "default",
                                "entity_type": "continuity", "key": "note",
                                "value": "my password is hunter2", "source": "x",
                                "confidence": 1.0, "created_at": 1.0,
                                "updated_at": 1.0, "expires_at": None}}}}}, f)
    msp2 = MemoryStore(poison2).load()
    check("V14f secret-value item dropped at load (no value scan blind spot)",
          msp2.items() == []
          and msp2.boundary_diagnostics()["secret_values_present"] == [])
    poison3 = os.path.join(td.name, "poison3.json")
    with open(poison3, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "users": {"default": {"items": {
            "vocab:walked": {"id": "mem_r1", "user_id": "default",
                             "entity_type": "vocab_item", "key": "walked",
                             "value": "not-the-fixed-shape", "source": "x",
                             "confidence": 1.0, "created_at": 1.0,
                             "updated_at": 1.0, "expires_at": None}}}}}, f)
    msp3 = MemoryStore(poison3).load()
    check("V14g vocab items with a poisoned value are dropped at load",
          msp3.vocab_items() == {} and msp3.items() == [])

    # ---- V13: gateway link explicit save / apply / forget / weak word (fake qwen) -----
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

    mpath = os.path.join(td.name, "mem_link.json")
    cfg = SimpleNamespace(MEMORY_FILE=mpath, WORKBENCH_BASE_URL="", KNOWLEDGE_FILE="")

    async def turn(link, transcript, item_id):
        await link._on_input_completed({"transcript": transcript, "item_id": item_id})

    async def link_flow():
        link = BehaviorLink(_FakeConn(), _FakeQwen(), config=cfg)
        await turn(link, "以后解释单词先用中文，记住", "i1")
        return link
    link1 = asyncio.run(link_flow())
    check("V13 explicit save: preference persisted (scenario: 记住)",
          MemoryStore(mpath).load().preferences() == {"explanation_language": "zh"}
          and link1.stats["pref_saves"] == 1)

    async def new_session():
        q = _FakeQwen()
        link = BehaviorLink(_FakeConn(), q, config=cfg)
        return link, q
    link2, q2 = asyncio.run(new_session())
    check("V13b new session applies the saved preference",
          link2.state.saved_prefs.get("explanation_language") == "zh"
          and "word explanations first in 中文" in q2.instructions)

    async def weak_flow():
        link = BehaviorLink(_FakeConn(), _FakeQwen(), config=cfg)
        await turn(link, "我不认识 accommodation 这个单词", "i1")
        return link
    link3 = asyncio.run(weak_flow())
    check("V13c weak word stored on the explicit turn",
          "accommodation" in MemoryStore(mpath).load().vocab_items()
          and link3.stats["weak_words"] == 1)

    async def forget_flow():
        msf = MemoryStore(mpath).load()
        msf.save("continuity", "topic", "swimming practice")
        link = BehaviorLink(_FakeConn(), _FakeQwen(), config=cfg)
        await turn(link, "swimming 相关的话题继续", "i0")     # memory injection turn
        injected = link.stats["memory_injections"]
        await turn(link, "忘掉这个偏好", "i1")
        return link, injected
    link4, injected = asyncio.run(forget_flow())
    check("V13d relevant memory item injected into the turn",
          injected == 1
          and any("LEARNER MEMORY" in s for s in link4.qwen.sent),
          "injected=%r sent=%r" % (injected,
                                   ["LEARNER MEMORY" in s for s in link4.qwen.sent]))
    check("V13e explicit forget removes the most recent preference",
          "explanation_language" not in MemoryStore(mpath).load().preferences())

    async def plain_flow():
        mpath2 = os.path.join(td.name, "mem_plain.json")
        cfg2 = SimpleNamespace(MEMORY_FILE=mpath2, WORKBENCH_BASE_URL="",
                               KNOWLEDGE_FILE="")
        link = BehaviorLink(_FakeConn(), _FakeQwen(), config=cfg2)
        await turn(link, "今天天气不错", "i1")
        return mpath2, link
    mpath2, link5 = asyncio.run(plain_flow())
    check("V13f nothing is captured automatically (no explicit save → no file)",
          not os.path.exists(mpath2) and link5.stats["pref_saves"] == 0
          and link5.stats["memory_injections"] == 0)

    td.cleanup()

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("MEMORY_V1_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())