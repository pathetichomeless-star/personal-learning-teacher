# -*- coding: utf-8 -*-
"""Avatar adapter behaviour tests (CLASSROOM V2 · Agent D · Phase 2).

D01  valid states accepted; unknown state rejected;
D02  audio level clamped to [0,1]; non-numeric rejected;
D03  unavailable backend → degraded view model with honest caption;
D04  **no fake lip-sync** — without a real audio level, mouth stays closed;
D05  real audio level in ``speaking`` drives the mouth; leaving ``speaking`` closes it;
D06  degradation forces closed mouth + ``audio_driven=False`` (no phantom animation);
D07  the adapter does not import protected avatar modules.

Run:
    cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/test_avatar_adapter.py
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from src.classroom.avatar_adapter import AvatarAdapter, STATES  # noqa: E402

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
    a = AvatarAdapter(available=True, engine="live2d")
    ok = True
    for s in STATES:
        try:
            a.set_state(s)
        except ValueError:
            ok = False
    check("D01a", "五个合法状态全部接受", ok and a.state in STATES, a.state)
    try:
        a.set_state("dancing")
        bad = False
    except ValueError:
        bad = True
    check("D01b", "未知状态被拒绝", bad)

    check("D02a", "音频电平上界截断到 1.0", a.set_audio_level(5) == 1.0)
    check("D02b", "音频电平下界截断到 0.0", a.set_audio_level(-3) == 0.0)
    try:
        a.set_audio_level("loud")
        bad = False
    except ValueError:
        bad = True
    check("D02c", "非数值电平被拒绝", bad)

    # D04 no fake lip-sync
    b = AvatarAdapter(available=True)
    b.set_state("speaking")
    check("D04", "无真实音频电平 → 嘴闭合（audio_driven=False, mouth=0）",
          b.audio_driven is False and b.mouth_open() == 0.0,
          (b.audio_driven, b.mouth_open()))

    # D05 real audio drives mouth
    b.set_audio_level(0.7)
    check("D05a", "真实电平 0.7 + speaking → 嘴张开 0.7",
          b.audio_driven is True and b.mouth_open() == 0.7, b.mouth_open())
    b.set_state("listening")
    check("D05b", "切到 listening → 嘴闭合（即使有电平）", b.mouth_open() == 0.0)
    b.set_audio_level(None)
    check("D05c", "电平置 None（无真实信号）→ audio_driven=False", b.audio_driven is False)

    # D03 degradation
    c = AvatarAdapter(available=True)
    c.set_state("speaking"); c.set_audio_level(0.9)
    c.set_available(False, reason="backend_timeout")
    snap = c.snapshot()
    check("D03a", "后端不可用 → degraded=True + 原因", snap["degraded"] and snap["degrade_reason"] == "backend_timeout")
    check("D03b", "降级时给出诚实文案（不影响课程与语音）",
          "不影响课程与语音" in snap["caption"], snap["caption"])
    check("D06", "降级强制闭口（吞掉音频驱动，杜绝幽灵口型）",
          snap["audio_driven"] is False and snap["mouth_open"] == 0.0, snap)
    # 恢复可用
    c.set_available(True)
    check("D03c", "恢复可用 → degraded=False 且 caption 清空",
          not c.snapshot()["degraded"] and c.snapshot()["caption"] == "")

    # D07 no protected avatar import
    src = open(os.path.abspath(__file__).replace("tests/test_avatar_adapter.py",
                                                "avatar_adapter.py"), encoding="utf-8").read()
    check("D07", "适配器不 import 受保护数字人模块（仅自身契约）",
          "src.avatar" not in src and "avatar_page" not in src and "AvatarLive2D" not in src)

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = [r["case_id"] for r in RESULTS if not r["passed"]]
    print("\n" + "=" * 70)
    print("AVATAR_ADAPTER: %d checks, %d PASS, %d FAIL" % (len(RESULTS), passed, len(failed)))
    if failed:
        print("FAILED:", ", ".join(failed))

    ev = os.path.join(_CLIENT, "..", "docs", "engineering", "product-v1",
                      "classroom-v2", "evidence", "avatar_adapter_tests.json")
    try:
        with open(os.path.abspath(ev), "w", encoding="utf-8") as f:
            json.dump({"artifact": "avatar_adapter_tests",
                       "scope": "CLASSROOM V2 PHASE2 · Agent D（数字人适配 + 安全降级）",
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
