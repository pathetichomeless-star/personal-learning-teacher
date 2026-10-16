# PHASE 4 — BEHAVIOR-1 (natural activity routing, language policy, context model)

Date: 2026-10-07 · Status: **PASS** · Evidence: `evidence/mvp-local-suites.txt`
(`BEHAVIOR1_TESTS: 111/111` final — includes the mirror-language hot-apply fix — and `MVP_INTEGRATION_TESTS: 28/28`)

## Scope delivered (MVP subset of the BEHAVIOR-1 roadmap phase)

* Deterministic rule-based router over the **input transcription** text of each user turn
  (`modules/intent/behavior.py`, pure logic, no gateway/audio imports).
* Context model: `main_activity`, `temporary_intent`, `resume_note`, `recent_word`,
  `recent_sentence`, `recent_passage`, `recent_task`, language override, speed, difficulty
  (session-scoped, in-memory only, never logged, never persisted).
* Instruction renderer: full session instruction block (language policy + activity +
  scenario + speed + difficulty + temp-intent note with the **return-to-main** sentence +
  workbench data + memory preferences + explicit "never mention internal labels" rule).
* Gateway link (`gateway/app/behavior.py`): classifies on
  `conversation.item.input_audio_transcription.completed`, renders, and **hot-applies
  `session.update` (instructions-only) at a safe boundary** — the boundary predicate is
  `Connection.is_safe_boundary()` = no active generation **and** no active TTS **and** no
  active pacer task. Deferred applies retry on the boundary hooks (TTS stop / listen start /
  response.done); identical renders are skipped; every apply is bounded
  (`APPLY_SEND_TIMEOUT=0.8 s`) and read-back-verified against the `session.updated` echo.
* Activities: CHAT / PRACTICE_CONVERSATION (+9 scenarios) / SPEAKING_PRACTICE / VOCAB_LEARN /
  VOCAB_REVIEW / READING / LISTENING / CONTINUE_LESSON.
* Temporary intents: EXPLAIN_WORD (Chinese meaning → English word → pronunciation → example,
  then resume), EXPLAIN_GRAMMAR, TRANSLATE, QUERY_PROGRESS, SAVE_PREFERENCE — cleared on
  `response.done`, with the main activity restored automatically.
* Commands: 再来一次 / 继续 / 慢一点 / 快一点 / 正常语速 / 难一点 / 简单一点 — all stay inside
  the current activity (no new "mode").
* Language policy: Chinese input → Chinese; practice → English; **one English word inside
  Chinese never switches the language**; explicit request (`说中文/说英语/为什么用英文…`)
  always wins (session override).

## Required examples (from the authorization) — deterministic evidence

| utterance | result (test) |
|---|---|
| 我们随便聊聊 | CHAT, zh (A1) |
| 我们练一下酒店英语 | PRACTICE_CONVERSATION hotel, en (B1) |
| accommodation 是什么意思？ | TEMP EXPLAIN_WORD + chinese-first note + return-to-hotel (D1–D4) |
| 再来一次 | repeat, activity untouched (C8) |
| 说慢一点 | speed=slow, activity untouched (C1/C13) |
| 这个太简单了，难一点 | difficulty=hard, stays in activity (C5/C14) |
| 别背单词了，聊会儿天 | VOCAB_LEARN → CHAT naturally (B9) |

## Wiring (R-1f discipline)

* `turns.py` changes are additive and text-plane only: BehaviorLink construction,
  `is_safe_boundary()`, one event hook in `_on_qwen_event`, a prefetch hint on
  `speech_started`, one `schedule_apply()` after `_stop_tts`, on `_on_listen_start`, and
  link teardown in `close()`. **No pacing/Opus/FIFO/generation-ownership change**:
  R-1f suite stays baseline-identical (179/180, same local-libopus-only sentinel).
* `qwen.py`: instructions become dynamic (`set_instructions`) and a new
  `send_instructions_update()` writes a **`{"session": {"instructions": …}}`-only**
  payload. Model/voice/formats/VAD payload fields are unchanged; voice is never hot-applied
  (round-1 spike finding: an invalid voice poisons the next generation).
* Fail-soft: any classifier/link error is contained (`try/except` in the hook); the turn
  engine and audio plane continue; a missing boundary simply defers to the next one.

## Out of scope (deferred by authorization)

Routing-record persistent store, Intent Routing admin page, ADMIN-2 policy centre
integration (the classifier currently owns its own state, no policy duplication).