# -*- coding: utf-8 -*-
"""Mock voice / dialogue state machine tests (CLASSROOM V2 · Agent C · Phase 2).

C01  event contract: user_speech → partial → final → teacher_speaking → done;
C02  **barge_in interrupts** teacher speaking → listening;
C03  error codes map to Chinese reasons (no bare numbers);
C04  three modes are labelled explicitly; ``real-online`` without an injected
     authorized adapter **refuses** (no real request);
C05  Mock round-trip is deterministic and produces the right event sequence;
C06  mic denied → text-only still works and says so;
C07  no network: a round-trip performs zero socket connections.

Run:
    cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/test_voice_mock.py
"""

import json
import os
import socket
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from src.classroom.voice_mock import VoiceMockSession, error_reason, MODES  # noqa: E402

RESULTS = []


def check(cid, name, cond, observed=None):
    line = sys._getframe(1).f_lineno
    RESULTS.append({"case_id": cid, "name": name, "passed": bool(cond),
                    "observed": repr(observed)[:300],
                    "asserted_file": os.path.abspath(__file__), "asserted_line": line})
    print(("PASS " if cond else "FAIL ") + "%s %s%s"
          % (cid, name, "" if cond else "  → %r" % (observed,)))
    return bool(cond)


def main():
    s = VoiceMockSession(mode="local-mock", mic_granted=True)
    s.start_listening()
    s.partial_transcript("I have a")
    s.final_transcript("I have a reservation.")
    s.teacher_speaking("Great!")
    s.finish_speaking()
    types = [e["type"] for e in s.events]
    check("C01", "事件序列 user_speech→partial→final→teacher_speaking→teacher_done",
          types == ["user_speech", "partial_transcript", "final_transcript",
                    "teacher_speaking", "teacher_done"], types)
    check("C01b", "结束后状态回到 idle", s.state == "idle", s.state)

    # C02 barge-in
    s2 = VoiceMockSession()
    s2.start_listening(); s2.final_transcript("hi"); s2.teacher_speaking("long answer…")
    before = s2.state
    s2.barge_in()
    check("C02", "teacher_speaking 时 barge_in → 打断回 listening",
          before == "speaking" and s2.state == "listening", (before, s2.state))

    # C03 error mapping
    check("C03a", "1006 → 中文原因（非裸数字）",
          "中断" in error_reason(1006) and "1006" not in error_reason(1006), error_reason(1006))
    check("C03b", "401/409 各有中文原因",
          "鉴权" in error_reason(401) and "冲突" in error_reason(409))
    check("C03c", "未知码 → 诚实兜底（含码，不臆造）",
          "未分类错误" in error_reason(9999))
    s3 = VoiceMockSession()
    s3.error(1006)
    check("C03d", "error() 记录中文原因并回 idle",
          s3.last_error != "" and s3.state == "idle", s3.last_error)

    # C04 modes
    check("C04a", "三种模式均可构造并显式标注",
          all(VoiceMockSession(mode=m).mode_label() for m in MODES))
    real = VoiceMockSession(mode="real-online")     # 无授权适配器
    check("C04b", "真实在线模式：未注入授权适配器 → real_connected=False",
          real.real_connected() is False)
    r = real.roundtrip("hello")
    check("C04c", "真实在线未授权 → 拒绝（不发起真实请求）",
          r["ok"] is False and "未授权" in real.last_error, r)

    # C05 mock round-trip deterministic
    m = VoiceMockSession(mode="local-mock")
    out1 = m.roundtrip("reservation", canned={"reservation": "很好，继续！"})
    out2 = VoiceMockSession(mode="local-mock").roundtrip("reservation",
                                                         canned={"reservation": "很好，继续！"})
    check("C05", "Mock 往返确定（同输入同输出）且回复来自 canned 表",
          out1 == out2 and out1["reply"] == "很好，继续！", out1)

    # C06 mic denied → text-only
    t = VoiceMockSession(mode="local-mock", mic_granted=False)
    check("C06a", "未授权麦克风 → text_only=True 且明示", t.text_only is True)
    e = t.start_listening()
    check("C06b", "文字模式 start_listening 不报错，发 no_mic 说明",
          e["type"] == "error" and "麦克风" in e["reason"], e)
    rt = t.roundtrip("hi", canned={"hi": "你好"})
    check("C06c", "文字模式仍可完成往返（只用文字）", rt["ok"] and rt["reply"] == "你好", rt)

    # C07 no network
    calls = []
    _orig = socket.socket.connect
    socket.socket.connect = lambda self, *a, **k: (calls.append(a), _orig(self, *a, **k))[1]
    try:
        VoiceMockSession(mode="local-mock").roundtrip("no network please")
    finally:
        socket.socket.connect = _orig
    check("C07", "Mock 往返零 socket 连接（不触网）", calls == [], calls)

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = [r["case_id"] for r in RESULTS if not r["passed"]]
    print("\n" + "=" * 70)
    print("VOICE_MOCK: %d checks, %d PASS, %d FAIL" % (len(RESULTS), passed, len(failed)))
    if failed:
        print("FAILED:", ", ".join(failed))

    ev = os.path.join(_CLIENT, "..", "docs", "engineering", "product-v1",
                      "classroom-v2", "evidence", "voice_mock_tests.json")
    try:
        with open(os.path.abspath(ev), "w", encoding="utf-8") as f:
            json.dump({"artifact": "voice_mock_tests",
                       "scope": "CLASSROOM V2 PHASE2 · Agent C（文字/Mock 语音 + 事件 + 打断）",
                       "results": RESULTS,
                       "summary": {"total": len(RESULTS), "passed": passed,
                                   "failed": len(failed), "failed_ids": failed}},
                      f, ensure_ascii=False, indent=2)
        print("evidence:", os.path.abspath(ev))
    except Exception as e:  # noqa: BLE001
        print("evidence 写入失败（不影响结论）:", e)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
