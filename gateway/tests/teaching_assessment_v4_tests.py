"""TEACHING_ASSESSMENT_V4_TESTS — the P2-B1 §一 correction of the P2-A learning
result: a learning outcome must be traceable to real evidence.

Runs standalone:  python tests/teaching_assessment_v4_tests.py   (from gateway/, venv)

This suite is deliberately store-level (plus one read-side legacy check) so the
rule itself is pinned down independently of any HTTP path:

  A1 no audio input  -> no pronunciation score, no phoneme error, "尚未评估"
  A2 real audio input -> an audio claim may be recorded
  A3 a score exists only when the voice adapter really reported one
  A4 a class with no evidence at all stores no learning claims
  A5 refused items are reported (nothing is silently dropped)
  A6 simulated (local test) results are labelled as such
  A7 legacy records are preserved on disk and never presented as pronunciation
     assessments
"""

import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parent
_REPO = _GATEWAY.parent
for _p in (str(_REPO), str(_GATEWAY)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from modules.teaching.store import (TeachingSessionStore, _audio_meta,  # noqa: E402
                                   _normalize_outcome, derive_evidence,
                                   public_outcome, public_session)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


def _store(tmp, name="teaching.json"):
    return TeachingSessionStore(os.path.join(tmp, name)).load()


def _new(store, **kw):
    base = dict(teacher_id="tch_t", student_id="stu", model_id="mdl_x",
                model_key="mock", modality="text")
    base.update(kw)
    return store.create_session(**base)


def _text_turn(store, sid, role="student", text="你好"):
    return store.append_turn(sid, role=role, text=text, kind="text")


def _speech_turn(store, sid, *, score=None, issues=None, text="（测试音频转写）"):
    audio = {"bytes": 8016, "input_format": "pcm16", "sample_rate": 16000,
             "duration_ms": 250, "source": "isolated_test_source",
             "adapter_id": "voice_test_pipeline"}
    if score is not None:
        audio["score"] = score
    if issues:
        audio["issues"] = issues
    return store.append_turn(sid, role="student", text=text, kind="speech",
                             audio=audio)


def amain():
    tmp = tempfile.mkdtemp(prefix="teaching-assess-")

    # ---- A8 low-level: audio metadata can never be faked ------------------
    check("A8a an empty audio object is not evidence",
          _audio_meta({"bytes": 0}) is None and _audio_meta({}) is None)
    check("A8b a negative/absent byte count is not evidence",
          _audio_meta({"bytes": -5}) is None and _audio_meta(None) is None)
    meta = _audio_meta({"bytes": 100, "input_format": "pcm16", "sample_rate": 16000})
    check("A8c no score is recorded when the adapter reported none",
          meta["score"] is None and meta["assessment_supported"] is False
          and "data" not in meta, json.dumps(meta))
    meta2 = _audio_meta({"bytes": 100, "score": 77.5, "issues": ["θ"]})
    check("A8d a reported score is bounded and marked supported",
          meta2["score"] == 77.5 and meta2["assessment_supported"] is True
          and meta2["issues"] == ["θ"], json.dumps(meta2))

    # ---- A1 text-only class: no audio → no pronunciation verdict ----------
    s1 = _store(tmp)
    sid = _new(s1)["session_id"]
    _text_turn(s1, sid)
    _text_turn(s1, sid, role="teacher", text="你好，我们今天学问候语。")
    ev = derive_evidence(s1.get_session(sid))
    check("A1a a text-only class reports text dialogue evidence only",
          ev["kinds"] == ["text_dialogue"] and ev["audio_turns"] == 0,
          json.dumps(ev))
    out = _normalize_outcome(
        {"knowledge_points": ["问候语 Hello"],
         "weak_points": ["发音不标准", "音素 θ 读错", "第三人称单数 -s"],
         "review_items": ["朗读 Lesson A"],
         "notes": "口音需要加强，但语法不错。",
         "pronunciation": {"score": 88.0, "issues": ["θ 音不准"]}},
        evidence=ev, simulated=False)
    check("A1b no pronunciation score is produced without audio",
          out["pronunciation"]["status"] == "unassessed"
          and out["pronunciation"]["reason"] == "no_audio_evidence"
          and out["pronunciation"]["score"] is None
          and out["pronunciation"]["issues"] == [],
          json.dumps(out["pronunciation"]))
    check("A1c the state is reported as 尚未评估, not as a weakness",
          "pronunciation" in out["unassessed"], json.dumps(out["unassessed"]))
    check("A1d every audio / pronunciation claim is refused, with a reason",
          all(x["reason"] == "no_audio_evidence" for x in out["rejected_items"])
          and {x["item"] for x in out["rejected_items"]}
          == {"发音不标准", "音素 θ 读错", "朗读 Lesson A", "口音需要加强，但语法不错。"},
          json.dumps(out["rejected_items"], ensure_ascii=False))
    check("A1e non-audio items survive (the valid part of the result is kept)",
          out["weak_points"] == ["第三人称单数 -s"]
          and out["knowledge_points"] == ["问候语 Hello"]
          and out["review_items"] == [], json.dumps(out, ensure_ascii=False))
    check("A1f the outcome states which evidence it actually had",
          out["evidence"]["kinds"] == ["text_dialogue"]
          and out["evidence"]["audio_turns"] == 0 and out["evidence"]["source"],
          json.dumps(out["evidence"]))

    # ---- A2/A3 a class with audio evidence -------------------------------
    s2 = _store(tmp, "teaching2.json")
    sid2 = _new(s2, modality="voice",
                knowledge_dataset_ids=None)["session_id"]
    _speech_turn(s2, sid2)
    _text_turn(s2, sid2, role="teacher", text="很好，请再读一遍。")
    ev2 = derive_evidence(s2.get_session(sid2))
    check("A2a a speech turn really produces audio evidence",
          "audio_speech" in ev2["kinds"] and ev2["audio_turns"] == 1, json.dumps(ev2))
    out2 = _normalize_outcome({"weak_points": ["发音不标准"]}, evidence=ev2)
    check("A2b an audio claim is accepted once audio evidence exists",
          out2["weak_points"] == ["发音不标准"] and not out2["rejected_items"],
          json.dumps(out2, ensure_ascii=False))
    check("A2c an unscored adapter still yields no score (never invented)",
          out2["pronunciation"]["status"] == "unassessed"
          and out2["pronunciation"]["reason"] == "adapter_no_assessment"
          and out2["pronunciation"]["score"] is None,
          json.dumps(out2["pronunciation"]))
    check("A2d pronunciation is listed as 尚未评估 even with audio present",
          "pronunciation" in out2["unassessed"], json.dumps(out2["unassessed"]))

    s3 = _store(tmp, "teaching3.json")
    sid3 = _new(s3, modality="voice")["session_id"]
    _speech_turn(s3, sid3, score=82.0, issues=["θ 音不稳"])
    ev3 = derive_evidence(s3.get_session(sid3))
    check("A3a a scoring adapter is reported as scored", ev3["scored_turns"] == 1,
          json.dumps(ev3))
    out3 = _normalize_outcome({"pronunciation": {"score": 82.0, "issues": ["θ 音不稳"]}},
                              evidence=ev3)
    check("A3b the score is recorded ONLY because real scoring evidence exists",
          out3["pronunciation"]["status"] == "assessed"
          and out3["pronunciation"]["score"] == 82.0
          and out3["pronunciation"]["issues"] == ["θ 音不稳"]
          and "pronunciation" not in out3["unassessed"],
          json.dumps(out3["pronunciation"], ensure_ascii=False))

    # ---- A4 no evidence at all -------------------------------------------
    s4 = _store(tmp, "teaching4.json")
    sid4 = _new(s4)["session_id"]
    ev4 = derive_evidence(s4.get_session(sid4))
    check("A4a an empty class has no evidence kinds", ev4["kinds"] == [],
          json.dumps(ev4))
    out4 = _normalize_outcome({"knowledge_points": ["问候语"],
                               "weak_points": ["发音需要加强"],
                               "review_items": ["复习 A"], "notes": "注意发音"},
                              evidence=ev4)
    check("A4b a class with no evidence stores no learning claims",
          out4["knowledge_points"] == [] and out4["weak_points"] == []
          and out4["review_items"] == [] and out4["notes"] == "",
          json.dumps(out4, ensure_ascii=False))
    check("A4c every field is declared 尚未评估 instead of being invented",
          set(["pronunciation", "knowledge_points", "weak_points", "review_items"])
          <= set(out4["unassessed"]), json.dumps(out4["unassessed"]))
    check("A4d all refused items are reported with reason=no_evidence",
          out4["rejected_items"] and
          all(x["reason"] == "no_evidence" for x in out4["rejected_items"]),
          json.dumps(out4["rejected_items"], ensure_ascii=False))

    # ---- A6 simulated labelling ------------------------------------------
    out6 = _normalize_outcome({"knowledge_points": ["x"]}, evidence=ev2,
                              simulated=True)
    check("A6a a simulated class is labelled and explained",
          out6["simulated"] is True and out6["simulation_note"], json.dumps(out6)[:160])
    s6 = _store(tmp, "teaching6.json")
    sid6 = _new(s6, model_is_local=True)["session_id"]
    _text_turn(s6, sid6)
    ended = s6.end_session(sid6, outcome={"knowledge_points": ["local-model class"]})
    check("A6b a locally-served class is auto-labelled simulated on end",
          ended["outcome"]["simulated"] is True,
          json.dumps(ended["outcome"])[:160])

    # ---- A7 legacy records are preserved and never become verdicts --------
    legacy_path = os.path.join(tmp, "legacy.json")
    legacy_doc = {
        "schema_version": 1,
        "sessions": {
            "ses_legacy0001": {
                "session_id": "ses_legacy0001",
                "teacher_id": "tch_old", "teacher_name": "旧老师",
                "student_id": "stu_old",
                "model_id": "mdl_old", "model_key": "old-model",
                "provider_id": "", "model_is_local": False,
                "knowledge_dataset_ids": [], "course_id": "",
                "teaching_policy": {}, "knowledge_scope_note": "",
                "status": "ended", "started_at": 1700000000.0,
                "ended_at": 1700000600.0,
                "turns": [{"role": "student", "text": "hello", "at": 1700000001.0,
                           "sources": []}],
                "turn_count": 1,
                # a pre-gate outcome: no evidence, no pronunciation block
                "outcome": {"knowledge_points": ["greeting"],
                            "weak_points": ["发音不标准"],
                            "review_items": [], "notes": "",
                            "saved_at": 1700000600.0},
            }
        },
    }
    with open(legacy_path, "w", encoding="utf-8") as fh:
        json.dump(legacy_doc, fh, ensure_ascii=False)
    s7 = TeachingSessionStore(legacy_path).load()
    check("A7a a legacy store still loads", s7.available is True)
    rec = s7.get_session("ses_legacy0001")
    check("A7b the legacy raw record is preserved verbatim",
          (rec.get("outcome") or {}).get("weak_points") == ["发音不标准"]
          and "pronunciation" not in (rec.get("outcome") or {})
          and "evidence" not in (rec.get("outcome") or {}),
          json.dumps(rec.get("outcome"), ensure_ascii=False))
    view = public_session(rec)["outcome"]
    check("A7c a legacy outcome is presented as un-assessed, not as a verdict",
          view["pronunciation"]["status"] == "unassessed"
          and view["pronunciation"]["reason"] == "legacy_record"
          and view["pronunciation"]["score"] is None
          and view["legacy_record"] is True, json.dumps(view, ensure_ascii=False))
    check("A7d the legacy evidence block says it is legacy, not fabricated",
          view["evidence"]["legacy"] is True and view["evidence"]["kinds"] == [],
          json.dumps(view["evidence"]))
    with open(legacy_path, encoding="utf-8") as fh:
        after = json.load(fh)
    check("A7e reading a legacy record never rewrites it on disk",
          json.dumps(after, sort_keys=True) == json.dumps(legacy_doc, sort_keys=True))
    check("A7f public_outcome is a pure projection (no mutation of the input)",
          public_outcome({"weak_points": ["x"]}) != {"weak_points": ["x"]}
          and "evidence" in public_outcome({"weak_points": ["x"]}))

    # ---- summary ----------------------------------------------------------
    ok = sum(1 for _, c, _ in RESULTS if c)
    print("\n%d/%d checks passed" % (ok, len(RESULTS)))
    if ok != len(RESULTS):
        print("FAILURES:")
        for n, c, d in RESULTS:
            if not c:
                print("  -", n, ("[%s]" % d) if d else "")
        sys.exit(1)


if __name__ == "__main__":
    amain()
