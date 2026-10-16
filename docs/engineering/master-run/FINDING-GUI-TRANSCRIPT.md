# FINDING — GUI TRANSCRIPT NOT VISIBLE (human acceptance failure) → FIXED

Date: 2026-10-08 · Reported: human test — real GUI showed no learner/assistant text (only
avatar/status “待命”), while voice/Chinese/English/CMD+K AUTO all worked.

## Root cause (mechanically traced, two breaks)

**Break 1 — the live viewport call died (proven by the real client log):**

```
File ".../src/plugins/ui_presenter.py", line 119, in set_transcript
File ".../src/ui/gui/manager.py", line 107, in set_transcript
    super().set_transcript(items)
AttributeError: 'super' object has no attribute 'set_transcript'
2026-10-07 23:34:57 | ERROR | src.plugins.manager | 插件 ui on_incoming_json 失败:
  'super' object has no attribute 'set_transcript'
```

`GuiViewManager.set_transcript` looked up `self._model` / `self._main_model` — neither
exists (the model is `self._main.main_model`) — and then called
`super().set_transcript(items)`, but `GuiViewManager`'s base is `QObject` (the shared
`ViewPort` is a *Protocol*, not a base class). Every live `transcript` message therefore
raised inside plugin dispatch; the handler in `plugins/manager.py` swallowed it into an
error log, `MainModel` never updated, position 3 of the chain never happened.

**Break 2 — the bubbles panel was never instantiated:** `ChatPanel.qml` was only
referenced by a static source test. The live layout (`main.qml` → `MainWindow.qml`) did
not instantiate it anywhere, so even a working model update had no visible bubble list —
the only text area was the legacy one-line `ttsText` placeholder (“待命”).

## Fix (smallest, findings-scoped; client only)

| file | change |
|---|---|
| `client/src/ui/gui/manager.py` | `set_transcript` now resolves the real model via `getattr(self._main, "main_model", None)` → `MainModel.set_transcript(items)`; the fallback is the shared one-line renderer (guarded, never raises); dead `super()` call removed |
| `client/src/ui/gui/qml/windows/MainWindow.qml` | imports `../panels`; instantiates `ChatPanel` (fill-height, min 150) between the emotion area (now capped at 150) and the buttons; legacy one-line text kept but auto-hides when the server sends no text (Audio↔Audio gateway sends none) |
| `client/src/ui/gui/qml/panels/ChatPanel.qml` | null-guards on `mainModel` bindings (load/teardown safe) |

Nothing else touched: no gateway, no sidecar, no Opus/pacer/FIFO/barge-in/generation
ownership, no Qwen provider/model/voice/VAD, no Behavior/Memory/Workbench changes.

## Regression test that would have caught it

`client/tests/test_gui_transcript_live.py` (offscreen, real classes, real QML engine):

* source contract: MainWindow **instantiates** ChatPanel · binds `mainModel.transcriptItems`
  · delegate role/text/state · auto-scroll · STREAMING/INTERRUPTED markers · no dead
  `super().set_transcript(items)` call;
* live chain: gateway transcript JSON → real `UiPresenter` → real `TranscriptStore` →
  real `GuiViewManager` → real `MainModel` (+`transcriptChanged`) — Chinese + English
  finals, streaming, interrupted-keeps-received-text, reset-on-reconnect;
* **REAL QML engine**: `main.qml` loaded offscreen, `ChatPanel` found in the live object
  tree, `ListView.count` follows the model (0 → 2 → 3 → 0), which is exactly the
  “bubbles visible in QML” mechanical proof.

Result: `GUI_TRANSCRIPT_LIVE_TESTS: 25 checks, 25 PASS, 0 FAIL`.

## Retest results (this fix)

| suite | result |
|---|---|
| CLIENT_UI1_TESTS (client) | 48/48 |
| GUI_TRANSCRIPT_LIVE_TESTS (new) | 25/25 |
| CLIENT_UI1_INTEGRATION (gateway) | 19/19 |
| BEHAVIOR1_TESTS | 111/111 |
| MVP_INTEGRATION_TESTS | 28/28 |
| R1F_BRIDGE_TESTS | 179/180 (identical known local-env libopus sentinel only) |

Deployment: **client-only change — no sidecar rebuild, no redeploy**. The Mac client
source is the repo checkout, so the fix is live on the next client start; OTA stays on
the existing MVP sidecar (`http://192.0.2.1:28211/xiaozhi/ota/`).

Rollback (if ever needed): `git revert` of this commit restores manager.py + the two QML
files; the client config rollback remains the pre-arm backup restore documented in
`PHASE-MVP-SIDECAR.md`.

AUDIO_CHANGED = NO.