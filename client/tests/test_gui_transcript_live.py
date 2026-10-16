"""GUI transcript LIVE-binding regression (human acceptance finding 2026-10-08).

The earlier static checks verified ChatPanel.qml *content*, but never that the
panel was instantiated in the live layout, and never exercised the real viewport
path.  The accepted human-test failure ("no conversation text visible") had two
mechanical causes:

  1. `GuiViewManager.set_transcript` looked for a model that does not exist and
     then called `super().set_transcript()` — its base is QObject, so every live
     transcript message raised AttributeError inside plugin dispatch and the GUI
     never updated;
  2. no QML layout instantiated `ChatPanel.qml`, so even a successful model
     update had no visible bubble list.

This suite exercises the real chain as far as mechanically possible:

    gateway transcript JSON -> UiPresenter -> TranscriptStore -> GuiViewManager
    -> MainModel (property + notify) -> REAL QML engine -> ListView.count

Runs offscreen (QT_QPA_PLATFORM=offscreen); no audio, no network, no persistence.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

RESULTS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append((name, ok, detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       "" if ok else "  <- %r" % (detail,)))


def msg(role, **kw):
    base = {"type": "transcript", "role": role, "delta": None, "text": None,
            "final": False, "interrupted": False, "turn": 1}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# A. source contract: the panel must be INSTANTIATED and bound (human-failure guard)
# ---------------------------------------------------------------------------

def test_source_contract():
    mw = open(os.path.join(_ROOT, "src", "ui", "gui", "qml", "windows",
                           "MainWindow.qml"), encoding="utf-8").read()
    cp = open(os.path.join(_ROOT, "src", "ui", "gui", "qml", "panels",
                           "ChatPanel.qml"), encoding="utf-8").read()
    main = open(os.path.join(_ROOT, "src", "ui", "gui", "qml", "main.qml"),
                encoding="utf-8").read()

    check("MainWindow instantiates ChatPanel (bubble list present in the live layout)",
          "ChatPanel {" in mw)
    check("MainWindow imports the panels directory", 'import "../panels"' in mw)
    check("main.qml loads MainWindow", "MainWindow {" in main)
    check("ChatPanel binds mainModel.transcriptItems",
          "model:" in cp and "mainModel.transcriptItems" in cp)
    check("ChatPanel delegate reads role/text/state",
          "modelData.role" in cp and "modelData.text" in cp
          and "modelData.state" in cp)
    check("ChatPanel auto-scrolls on count change",
          "positionViewAtEnd" in cp and "onCountChanged" in cp)
    check("ChatPanel shows STREAMING and INTERRUPTED markers",
          "STREAMING" in cp and "INTERRUPTED" in cp)
    mgr = open(os.path.join(_ROOT, "src", "ui", "gui", "manager.py"),
               encoding="utf-8").read()
    check("no dead super().set_transcript call remains",
          "super().set_transcript(items)" not in mgr
          and 'getattr(self._main, "main_model", None)' in mgr)


# ---------------------------------------------------------------------------
# B/C. live path with real classes + real QML engine
# ---------------------------------------------------------------------------

def main():
    test_source_contract()

    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])

    from src.core.event_bus import EventBus
    from src.core.task_manager import TaskManager
    from src.plugins.ui_presenter import UiPresenter
    from src.ui.gui.manager import GuiViewManager

    bus = EventBus()
    tasks = TaskManager()          # not initialized: nothing is spawned in this test
    manager = GuiViewManager(bus, tasks)
    presenter = UiPresenter()
    presenter.bind(manager)
    model = manager.main_model

    changed = {"n": 0}
    model.transcriptChanged.connect(lambda: changed.__setitem__("n", changed["n"] + 1))

    # ---- B1: full live chain, Chinese + English ---------------------------
    presenter.show_protocol_message(msg("user", delta="你", turn=1))
    presenter.show_protocol_message(msg("user", text="你好，小智。", final=True, turn=1))
    presenter.show_protocol_message(msg("assistant", delta="Sure, ", turn=1))
    presenter.show_protocol_message(
        msg("assistant", text="Sure, let's start.", final=True, turn=1))
    items = list(model.transcriptItems)
    check("live chain produced two bubbles", len(items) == 2, items)
    check("user bubble FINAL with Chinese text",
          items and items[0]["role"] == "user" and items[0]["state"] == "FINAL"
          and items[0]["text"] == "你好，小智。", items[:1])
    check("assistant bubble FINAL with English text",
          len(items) > 1 and items[1]["role"] == "assistant"
          and items[1]["state"] == "FINAL"
          and items[1]["text"] == "Sure, let's start.", items[1:])
    check("transcriptChanged fired for the model", changed["n"] >= 2, changed)

    # ---- B2: streaming visible, then interrupted keeps received text -------
    presenter.show_protocol_message(msg("assistant", delta="Now let me", turn=2))
    items = list(model.transcriptItems)
    check("streaming bubble visible with partial text",
          items[-1]["state"] == "STREAMING" and items[-1]["text"] == "Now let me",
          items[-1])
    presenter.show_protocol_message(
        msg("assistant", final=True, interrupted=True, turn=2))
    items = list(model.transcriptItems)
    check("interrupted keeps only actually received text",
          items[-1]["state"] == "INTERRUPTED" and items[-1]["text"] == "Now let me",
          items[-1])
    check("no fabricated text on interruption",
          items[-1]["text"] == "Now let me")

    # ---- B3: reconnect clears stale transcript ------------------------------
    presenter.reset_transcript()
    check("reset clears the model", list(model.transcriptItems) == [])

    # ---- B4: the manager call itself is safe (regression for super() bug) ----
    manager.set_transcript([{"role": "user", "text": "hi", "state": "FINAL",
                             "turn": 1}])
    check("GuiViewManager.set_transcript never raises and reaches the model",
          len(model.transcriptItems) == 1)
    manager.set_transcript([])                     # cleanup (direct model pokes)
    check("manager reset path clears the model", list(model.transcriptItems) == [])

    # ---- C: REAL QML engine binding -----------------------------------------
    manager._host.create_engine()
    manager._host.inject_context({
        "eventBridge": manager._bridge,
        "mainModel": model,
        "settingsModel": QObject(),          # SettingsWindow Loader stays inactive
        "emotionService": manager._main.emotion_service,
    })
    manager._host.load_main()
    engine = manager._host.engine
    roots = list(engine.rootObjects() or [])
    check("real main.qml loaded offscreen", len(roots) == 1, roots)
    if not roots:
        _summary()
        return 1
    root = roots[0]

    def find_first(pred):
        for child in [root] + root.findChildren(QObject):
            if pred(child):
                return child
        return None

    chat_panel = find_first(lambda c: "ChatPanel" in c.metaObject().className())
    check("ChatPanel exists in the LIVE QML object tree", chat_panel is not None)
    listview = find_first(
        lambda c: c.metaObject().className().startswith("QQuickListView"))
    check("bubble ListView exists in the live tree", listview is not None)

    if listview is not None:
        check("ListView starts empty (placeholder visible)",
              listview.property("count") == 0)

        presenter.show_protocol_message(msg("user", delta="你", turn=1))
        presenter.show_protocol_message(
            msg("user", text="我们练一下酒店英语", final=True, turn=1))
        presenter.show_protocol_message(
            msg("assistant", text="Welcome to our hotel!", final=True, turn=1))
        app.processEvents()
        check("model -> QML binding: 2 bubbles visible in QML",
              listview.property("count") == 2, listview.property("count"))

        presenter.show_protocol_message(
            msg("assistant", delta="And this ", turn=2))
        app.processEvents()
        check("streaming bubble grows the QML list to 3",
              listview.property("count") == 3, listview.property("count"))

        presenter.reset_transcript()
        app.processEvents()
        check("reset clears the QML list", listview.property("count") == 0,
              listview.property("count"))

    engine.deleteLater()
    _summary()
    return 0 if all(ok for _, ok, _ in RESULTS) else 1


def _summary():
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 70)
    print("GUI_TRANSCRIPT_LIVE_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s %s" % (name, detail))


if __name__ == "__main__":
    sys.exit(main())