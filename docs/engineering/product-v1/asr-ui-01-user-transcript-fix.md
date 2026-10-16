# ASR-UI-01 — User transcript preview fix (`gateway/app/turns.py`)

Status: implemented + verified (2026-10-08). Owner-authorized narrow scope:
UI-transcript-only changes in `gateway/app/turns.py`, relevant synthetic tests,
engineering docs.

## 1. Confirmed defects (audit 2026-10-08, first real Qwen3.5-Plus UI run)

**A. Cumulative preview forwarded as append-style delta.**
Qwen input transcription (`conversation.item.input_audio_transcription.delta`)
is a **cumulative, revisable preview**: `text` = confirmed prefix (grows),
`stash` = revisable suffix (behaviourally captured even on the 3.8 era:
`你` → `你。` → …). The gateway forwarded `text + stash` as an incremental
`delta`, and the client `TranscriptStore` appends deltas → progressive
concatenation (“HelloHello.hellohello…”) — reproduced deterministically.

**B. `response.created` re-keyed an unfinished user transcript.**
User events were stamped with the shared assistant `_ui_turn`, which advances
on `response.created`. When the ASR `completed` lost the observed ~43 ms race
(seg-4: `created` 19.544 → `completed` 19.587), it carried a newer turn → the
client opened a second clean bubble and the garbled preview bubble stayed
STREAMING forever.

## 2. Fix design (turns.py only; client untouched)

**Fix A — replace semantics for input previews** (UI forward block):
for `kind == "input"`, forward `text = preview` (never `delta=`); the client’s
existing text branch replaces the bubble text (STREAMING) and the final
`completed` replaces + finalizes. Empty previews are not sent (idempotent for
repeated snapshots). Assistant `response.audio_transcript.delta` stays
append-style — unchanged.

**Fix B — stable per-utterance identity** (new `_ui_user_turn` helper + fields
`_ui_user_seq` / `_ui_user_turns` bounded to newest 64 / `_ui_user_last_key` /
`_ui_user_preview_key`): each upstream input `item_id` binds to a dedicated
monotonic int turn id, independent of the assistant `_ui_turn`; late events of
an older item keep their old id (client drops older-than-newest user turns);
id-less events join the most recent utterance; `…transcription.failed` closes a
previously shown preview bubble honestly (no orphan STREAMING, no empty
bubble when nothing was shown).

## 3. What did NOT change

Assistant transcript path (append deltas + final replace), generation
ownership / R-F-1 / R-F-5 guard, interrupted-notice freezing, audio / pacing /
VAD / barge-in / reconnect / session payload / model / voice / client code /
Workbench / Memory — all untouched. Contract with the existing client
`TranscriptStore` is preserved (`role/delta/text/final/interrupted/turn`).

## 4. Tests

* New `gateway/tests/asr_ui01_tests.py` — **20/20 PASS**: deterministic
  legacy baseline reproduces BOTH defects (garble + orphaned bubble under the
  ~43 ms race), then 16-case matrix on the fixed path (incremental / cumulative
  / shrinking previews, text+stash, repeats, final replacement, one-utterance-
  one-bubble, multi-utterance, race both orders, barge-in, cancelled
  generation isolation, assistant rid isolation, missing/repeated
  speech_started, failed cleanup, duplicated completed, late old-item
  contamination).
* `tests/client_ui1_integration.py` — 19/19 (one assertion updated from the
  old user-delta contract to the ASR-UI-01 replace contract).
* Matrix: RED_F round1/2/3 = 123/20/27 · PRODUCT_V1_INTEGRATION 33/33 ·
  BEHAVIOR1 111/111 · QWEN_DIAG 40/40 · R1F 179/180 (documented macOS
  dev-libopus `OpusError` env sentinel) · ADMIN_SECURITY 29/29.
  (RED_F round1 ARCH5 re-verified green post-commit.)

## 5. Rollback

Code: `git revert <fix-commit>` (turns.py + tests + this doc). Sidecar: image
tag `xiaozhi-product-v1-sidecar:pre-asrui01` retained; `.env` remains `mock`
unless the owner re-arms.
