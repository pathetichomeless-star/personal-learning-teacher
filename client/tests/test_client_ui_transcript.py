"""CLIENT-UI-1 deterministic tests (transcript store + message contract).

Pure Python — no Qt, no audio, no network.  Run with any interpreter:

    python3 client/tests/test_client_ui_transcript.py
"""

import ast
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.ui.shared.transcript import (FINAL, INTERRUPTED, STREAMING,  # noqa: E402
                                      TranscriptStore)

_results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    _results.append(ok)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  <- %r" % (detail,)))
    return ok


def msg(role, **kw):
    base = {"type": "transcript", "role": role, "delta": None, "text": None,
            "final": False, "interrupted": False, "turn": 1}
    base.update(kw)
    return base


def test_chinese_user_then_assistant():
    s = TranscriptStore()
    s.apply(msg("user", delta="你好，", turn=1))
    s.apply(msg("user", delta="我们随便聊一会儿。", turn=1))
    out = s.apply(msg("user", delta="", text="你好，我们随便聊一会儿。", final=True, turn=1))
    items = s.snapshot()
    check("Chinese user text accumulates", items[0]["text"] == "你好，我们随便聊一会儿。", items)
    check("user bubble finalised", items[0]["state"] == FINAL, items[0])
    s.apply(msg("assistant", delta="好啊，", turn=1))
    s.apply(msg("assistant", delta="今天想聊点什么？", turn=1, final=True))
    check("assistant Chinese reply streams then finalises",
          s.snapshot()[1]["text"] == "好啊，今天想聊点什么？" and s.snapshot()[1]["state"] == FINAL,
          s.snapshot()[1])


def test_english_and_punctuation():
    s = TranscriptStore()
    s.apply(msg("assistant", delta="Let's practice. ", turn=1))
    s.apply(msg("assistant", delta="Where would you like to travel?", turn=1, final=True))
    item = s.snapshot()[0]
    check("English text + punctuation preserved",
          item["text"] == "Let's practice. Where would you like to travel?" and item["state"] == FINAL,
          item)


def test_partial_completion_replaces_accumulation():
    s = TranscriptStore()
    s.apply(msg("user", delta="我们练", turn=1))
    s.apply(msg("user", delta="酒店", turn=1))
    s.apply(msg("user", text="我们练酒店英语吧。", final=True, turn=1))
    check("completed text replaces the accumulated partial",
          s.snapshot()[0]["text"] == "我们练酒店英语吧。", s.snapshot()[0])


def test_barge_in_interrupted_is_honest():
    s = TranscriptStore()
    s.apply(msg("assistant", delta="This is a long answer about hotels, ", turn=2))
    changed = s.apply(msg("assistant", final=True, interrupted=True, turn=2))
    item = s.snapshot()[-1]
    check("interrupted notice changes the bubble", changed is not None)
    check("interrupted state recorded", item["state"] == INTERRUPTED, item)
    check("no fabricated text added", item["text"] == "This is a long answer about hotels, ", item)


def test_interrupted_without_stream_records_honest_bubble():
    s = TranscriptStore()
    s.apply(msg("assistant", final=True, interrupted=True, turn=3))
    item = s.snapshot()[-1]
    check("interrupted bubble created honestly (empty text, no invention)",
          item["state"] == INTERRUPTED and item["text"] == "", item)


def test_local_abort_fallback():
    s = TranscriptStore()
    s.apply(msg("assistant", delta="partial answer", turn=4))
    s.mark_interrupted("assistant")
    check("local abort marks the streaming bubble interrupted",
          s.snapshot()[-1]["state"] == INTERRUPTED, s.snapshot()[-1])
    check("local abort on a non-streaming bubble is a no-op", s.mark_interrupted("assistant") is None)


def test_duplicate_and_stale_protection():
    s = TranscriptStore()
    s.apply(msg("assistant", text="final answer", final=True, turn=5))
    check("duplicate final ignored", s.apply(msg("assistant", text="final answer", final=True, turn=5)) is None)
    check("duplicate final marker ignored", s.apply(msg("assistant", final=True, turn=5)) is None)
    check("stale turn ignored", s.apply(msg("assistant", delta="late", turn=4)) is None, s.snapshot())
    check("newer turn accepted", s.apply(msg("assistant", delta="next", turn=6)) is not None)


def test_malformed_and_foreign_messages():
    s = TranscriptStore()
    for bad in (None, {}, {"type": "tts", "text": "x"}, {"type": "transcript", "role": "system"},
                "not-a-dict", {"type": "transcript", "role": "user"}):
        check("ignored: %r" % (bad if not isinstance(bad, dict) else bad.get("role", bad.get("type")),),
              s.apply(bad) is None)
    check("store still empty after malformed input", s.snapshot() == [], s.snapshot())


def test_reconnect_reset_and_bounds():
    s = TranscriptStore(max_messages=5)
    for i in range(1, 9):
        s.apply(msg("user", text="m%d" % i, final=True, turn=i))
    snap = s.snapshot()
    check("bounded store keeps only the newest messages", len(snap) == 5, len(snap))
    check("oldest dropped first", snap[0]["text"] == "m4", snap[0])
    check("reset clears the session transcript", s.reset() == [] and s.snapshot() == [])
    check("reset on an empty store is a no-op", s.reset() is None)


def test_late_delta_after_final_is_ignored():
    s = TranscriptStore()
    s.apply(msg("assistant", text="done", final=True, turn=3))
    check("late delta for a completed turn ignored",
          s.apply(msg("assistant", delta="more", turn=3)) is None, s.snapshot())
    check("completed text unchanged", s.snapshot()[-1]["text"] == "done")


def test_interrupted_never_re_marks_a_final_turn():
    s = TranscriptStore()
    s.apply(msg("assistant", text="finished answer", final=True, turn=4))
    check("interrupted notice on a final turn is a no-op",
          s.apply(msg("assistant", final=True, interrupted=True, turn=4)) is None, s.snapshot())
    check("final state preserved", s.snapshot()[-1]["state"] == FINAL, s.snapshot()[-1])


def test_session_reset_makes_a_new_turn_sequence_valid():
    """A reconnect starts a new turn sequence: after reset, turn 1 must be accepted."""
    s = TranscriptStore()
    for i in (1, 2, 3, 4):
        s.apply(msg("assistant", text="old %d" % i, final=True, turn=i))
    check("reset clears the old session", s.reset() == [])
    check("new session turn 1 delta accepted after reset",
          s.apply(msg("assistant", delta="fresh", turn=1)) is not None, s.snapshot())


def test_render_helper():
    s = TranscriptStore()
    s.apply(msg("user", text="你好", final=True, turn=1))
    s.apply(msg("assistant", delta="hello", turn=1))
    s.apply(msg("assistant", final=True, interrupted=True, turn=1))
    lines = s.text_lines()
    check("render helper labels both roles", lines[0].startswith("你: ") and lines[-1].startswith("老师: "), lines)
    check("render helper marks interruption", "已打断" in lines[-1], lines)


def test_counts_and_bubbles_are_stable_for_the_store():
    """Repeated partial updates must not create new bubbles (no bubble explosion)."""
    s = TranscriptStore()
    for i in range(50):
        s.apply(msg("assistant", delta="x", turn=1))
    check("50 partial updates stay in one bubble", len(s.snapshot()) == 1, len(s.snapshot()))


def test_reconnect_reset_is_wired_to_the_real_lifecycle_hook():
    """E-finding regression: the reconnect reset must live on the path that actually runs."""
    root = os.path.join(_ROOT, "src", "plugins")
    ui = open(os.path.join(root, "ui.py")).read()
    mgr = open(os.path.join(root, "manager.py")).read()
    presenter = open(os.path.join(root, "ui_presenter.py")).read()
    check("ui plugin implements the lifecycle hook", "async def on_protocol_connected" in ui)
    check("that hook resets the transcript", "reset_transcript()" in ui)
    check("plugin manager dispatches on_protocol_connected", "on_protocol_connected" in mgr)
    check("presenter hello branch is marked as a fallback",
          "Defensive fallback only" in presenter)
    # behavioural: the store clears and then accepts a fresh (lower) turn sequence
    s = TranscriptStore()
    s.apply(msg("assistant", text="previous session answer", final=True, turn=9))
    s.reset()
    check("after a reconnect-style reset a new turn 1 is accepted",
          s.apply(msg("assistant", delta="new session", turn=1)) is not None
          and s.snapshot()[0]["text"] == "new session", s.snapshot())


def test_no_audio_coupling_and_no_persistence():
    path = os.path.join(_ROOT, "src", "ui", "shared", "transcript.py")
    tree = ast.parse(open(path).read())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    forbidden = [m for m in imports if any(
        k in m for k in ("audio", "codec", "aec", "websocket", "protocol", "sound", "opus"))]
    check("transcript store imports no audio/protocol modules", not forbidden, sorted(imports))
    text = open(path).read()
    for token in ("open(", "json.dump", "sqlite", "write("):
        check("no persistence primitive %r in the store" % token, token not in text)

    presenter = open(os.path.join(_ROOT, "src", "plugins", "ui_presenter.py")).read()
    check("presenter routes the transcript message type", 'elif msg_type == "transcript":' in presenter)
    check("presenter exposes the shared hooks",
          all(k in presenter for k in ("def set_transcript(", "def mark_transcript_interrupted(",
                                       "def reset_transcript(")))

    qml = open(os.path.join(_ROOT, "src", "ui", "gui", "qml", "panels", "ChatPanel.qml")).read()
    check("ChatPanel renders bubbles with states and auto-scroll",
          "mainModel.transcriptItems" in qml and "positionViewAtEnd()" in qml
          and "INTERRUPTED" in qml and "STREAMING" in qml)


def main():
    test_chinese_user_then_assistant()
    test_english_and_punctuation()
    test_partial_completion_replaces_accumulation()
    test_barge_in_interrupted_is_honest()
    test_interrupted_without_stream_records_honest_bubble()
    test_local_abort_fallback()
    test_duplicate_and_stale_protection()
    test_malformed_and_foreign_messages()
    test_reconnect_reset_and_bounds()
    test_late_delta_after_final_is_ignored()
    test_interrupted_never_re_marks_a_final_turn()
    test_session_reset_makes_a_new_turn_sequence_valid()
    test_render_helper()
    test_counts_and_bubbles_are_stable_for_the_store()
    test_reconnect_reset_is_wired_to_the_real_lifecycle_hook()
    test_no_audio_coupling_and_no_persistence()
    total, passed = len(_results), sum(_results)
    print("\nCLIENT_UI1_TESTS: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())