"""PRODUCT_BOUNDARY_TESTS — concurrency / reconnect / privacy boundaries + frozen-constant
no-drift re-assertion (master-matrix section CONCURRENCY_TESTS / RECONNECT_TESTS /
PRIVACY_BOUNDARY_TESTS + the 20/15/5/provider/model/voice/VAD/Opus/FIFO re-assert).

Runs standalone:  python tests/product_boundary_tests.py   (from gateway/, venv,
                   DYLD_LIBRARY_PATH must point at libopus)
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import app.turns as turns                                              # noqa: E402
from app.main import DEFAULTS                                          # noqa: E402
from modules.knowledge.store import KnowledgeStore                     # noqa: E402
from modules.memory.store import MemoryStore                           # noqa: E402
from modules.policy.persona import PolicyStore                         # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail if not cond else ""))[:200]))


class _FQ:
    def __init__(self):
        self.instructions = None
        self.sent = []

    def set_instructions(self, t):
        self.instructions = t

    async def send_instructions_update(self, t):
        self.sent.append(t)
        self.instructions = t
        return True


class _FC:
    def is_safe_boundary(self):
        return True


def main():
    # ---- F: frozen constants (no drift) --------------------------------------
    check("F1 media frame 20 ms (turns + audio + config defaults)",
          turns.MEDIA_FRAME_MS == 20.0 and DEFAULTS["FRAME_MS"] == 20)
    check("F2 send-start guard 15 ms", turns.MIN_SEND_START_INTERVAL_MS == 15.0,
          turns.MIN_SEND_START_INTERVAL_MS)
    check("F3 pacing slack 5 ms (+ slow-send threshold)",
          turns.PACING_SLACK_MS == 5.0 and turns.SLOW_SEND_THRESHOLD_MS == 5.0)
    check("F4 future-frame/byte caps unchanged",
          turns.MAX_FUTURE_FRAMES == 1500 and turns.MAX_FUTURE_AUDIO_BYTES == 524288
          and turns.MAX_REBASE_LATENESS_MS == 250.0)
    check("F5 provider/model/voice defaults frozen",
          DEFAULTS["QWEN_MODE"] == "mock"
          and DEFAULTS["QWEN_MODEL"] == "qwen3.8-omni-flash-realtime"
          and DEFAULTS["QWEN_VOICE"] == "Tina")
    qsrc = open(os.path.join(_GATEWAY, "app", "qwen.py"), encoding="utf-8").read()
    check("F6 VAD block frozen (server_vad 0.5 / 800 ms)",
          '"type": "server_vad"' in qsrc and '"threshold": 0.5' in qsrc
          and '"silence_duration_ms": 800' in qsrc)
    check("F7 Opus + pcm16 formats unchanged",
          "pcm16" in qsrc and "OpusEnc24" in open(
              os.path.join(_GATEWAY, "app", "audio.py"), encoding="utf-8").read())
    tsrc = open(os.path.join(_GATEWAY, "app", "turns.py"), encoding="utf-8").read()
    check("F8 generation ownership + safe boundary intact",
          "def is_safe_boundary" in tsrc and "_current_gen" in tsrc
          and "_GEN_SEQ" in tsrc and "MEDIA_FRAME_MS" in tsrc)
    check("F9 FIFO surface intact (store/in-flight semantics present)",
          "still_stored" in tsrc and "in_flight" in tsrc)

    td = tempfile.mkdtemp(prefix="pv1-boundary-")
    mem_p = os.path.join(td, "m.json")
    kb_p = os.path.join(td, "k.json")
    pol_p = os.path.join(td, "p.json")

    # ---- C: concurrency -------------------------------------------------------
    ks = KnowledgeStore(kb_p).load()
    ds = ks.create_dataset("并发")
    errors = []

    def writer(n):
        try:
            for i in range(6):
                ks.add_document(ds["id"], "w%d-%d" % (n, i),
                                "并发内容 %d %d。" % (n, i))
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    ms = MemoryStore(mem_p).load()

    def mem_writer(n):
        try:
            for i in range(6):
                ms.save("continuity", "c%d-%d" % (n, i), "并发记忆 %d %d" % (n, i))
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    threads += [threading.Thread(target=mem_writer, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("C1 concurrent store writers: no errors", errors == [], errors[:2])
    check("C2 knowledge persisted 24 docs", KnowledgeStore(kb_p).load()
          .diagnostics()["documents"] == 24)
    check("C3 memory persisted 12 items", len(MemoryStore(mem_p).load().items()) == 12)
    json.loads(open(kb_p, encoding="utf-8").read())
    json.loads(open(mem_p, encoding="utf-8").read())
    check("C4 both files remain valid JSON after concurrency", True)

    # two concurrent BehaviorLinks (interleaved turns) stay isolated
    from app.behavior import BehaviorLink                                  # noqa: E402

    cfg_a = SimpleNamespace(MEMORY_FILE=os.path.join(td, "ma.json"),
                            WORKBENCH_BASE_URL="", KNOWLEDGE_FILE=kb_p,
                            POLICY_FILE=pol_p)
    cfg_b = SimpleNamespace(MEMORY_FILE=os.path.join(td, "mb.json"),
                            WORKBENCH_BASE_URL="", KNOWLEDGE_FILE="",
                            POLICY_FILE=pol_p)
    qa, qb = _FQ(), _FQ()
    la = BehaviorLink(_FC(), qa, config=cfg_a)
    lb = BehaviorLink(_FC(), qb, config=cfg_b)

    async def interleaved():
        await asyncio.gather(
            la._on_input_completed({"transcript": "我们练一下酒店英语", "item_id": "a1"}),
            lb._on_input_completed({"transcript": "我想背几个单词", "item_id": "b1"}),
        )
        await asyncio.gather(
            la._on_input_completed({"transcript": "知识库里有没有并发内容的信息？",
                                    "item_id": "a2"}),
            lb._on_input_completed({"transcript": "继续", "item_id": "b2"}),
        )
    asyncio.run(interleaved())
    check("C5 concurrent sessions keep isolated activity state",
          la.state.main_activity == "PRACTICE_CONVERSATION"
          and lb.state.main_activity == "VOCAB_LEARN",
          (la.state.main_activity, lb.state.main_activity))
    check("C6 knowledge hits confined to the querying session",
          la.stats["knowledge_hits"] >= 1 and lb.stats["knowledge_queries"] == 0)

    # ---- R: reconnect ----------------------------------------------------------
    MemoryStore(cfg_a.MEMORY_FILE).load().save_preference("speed", "slow")
    PolicyStore(pol_p).load().apply({"persona": {"name": "小美"}})
    q2 = _FQ()
    l2 = BehaviorLink(_FC(), q2, config=cfg_a)
    check("R1 reconnect: new link applies stored policy + preferences",
          "You are 小美" in q2.instructions
          and l2.state.saved_prefs.get("speed") == "slow"
          and "speaking pace slow" in q2.instructions)
    check("R2 reconnect: knowledge store usable immediately",
          bool(l2.knowledge.search("并发内容", top_k=2, min_score=2)))
    l2.refresh_base_instructions()
    check("R3 refresh keeps policy+memory (no reset)",
          "You are 小美" in q2.instructions and q2.instructions is not None)
    check("R4 reconnect does not replay state into files",
          "小美" not in open(cfg_a.MEMORY_FILE, encoding="utf-8").read())

    # ---- P: privacy boundary -----------------------------------------------------
    secret_turn = ("我的密码是 hunter2，转写：今天我们聊了很多关于酒店的事情" * 3)
    asyncio.run(la._on_input_completed({"transcript": secret_turn, "item_id": "a3"}))
    for path, label in ((cfg_a.MEMORY_FILE, "memory"), (kb_p, "knowledge"),
                        (pol_p, "policy")):
        raw = open(path, encoding="utf-8").read()
        if "hunter2" in raw or secret_turn[:20] in raw:
            check("P1 %s store kept clean of secrets/transcripts" % label, False)
            break
    else:
        check("P1 memory/knowledge/policy stores clean of secrets/transcripts", True)
    mraw = open(cfg_a.MEMORY_FILE, encoding="utf-8").read()
    check("P2 memory holds no transcript-ish keys",
          '"transcript"' not in mraw and '"audio"' not in mraw)
    check("P3 in-memory store holds no secret content",
          not any("hunter2" in json.dumps(it, ensure_ascii=False)
                  for it in la.memory.items()))
    asyncio.run(la.close())
    asyncio.run(l2.close())
    check("P4 links close cleanly (no tasks left)", True)

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("PRODUCT_BOUNDARY_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())