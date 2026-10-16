# VOCABULARY TEACHING ACCURACY AUDIT (broad root-cause analysis)

Date: 2026-10-08 · Status: **COMPLETE — policy + routing fixed, machine-proven; one bounded real
session classified** · Budget: real sessions now **4/4** (this audit used the final one).

## 1. Read-only trace — proven defects BEFORE any change

`docs`-captured trace (`/tmp/vocab_trace_before.txt`, reproduced in the fix commit): of the 17
matrix-style utterances, **7 fell through to plain chat** (class B routing gaps):

| utterance | pre-audit route | verdict |
|---|---|---|
| 房间怎么说 / 英文里的街道怎么说？ / 街道的英文是什么？ / 街道是什么？ | **NONE** (ordinary chat) | routing gap |
| street / hotel / accommodation 怎么拼？ (spelling requests) | **NONE** | routing gap |
| X用英语怎么说 / X 是什么意思 | TRANSLATE / EXPLAIN_WORD | routed, but… |
| **all of the above** | instruction contained **no vocabulary-accuracy policy at all** | policy gap |

Nothing was modified before this trace.

## 2. Fix (smallest general teaching-policy + routing change; no hardcoded word map)

* Routing: natural variants now route to teaching —
  `X怎么说` · `英文里的X怎么说` · `X的英文是什么` · `X是什么`（conservative: short CJK subject;
  deictic “这是什么/他叫什么” stays chat) · `怎么拼` (EN word → EXPLAIN_WORD+spelling; CN term →
  TRANSLATE+spelling). Definition-shaped questions (“街道是什么？”) get an explicit
  vocabulary-first note (see §4, m19).
* Instruction: `VOCABULARY ACCURACY POLICY` (rendered for EXPLAIN_WORD / TRANSLATE /
  VOCAB_LEARN / VOCAB_REVIEW): canonical spelling FIRST · never invent a spelling from
  sound, never a phonetic approximation as the word · pronunciation separate from spelling ·
  怎么拼 = canonical word letter-by-letter · do not guess when unsure · several valid
  translations → context + one-line distinction · keep the learner's spelling verbatim.
* No LLM/ASR/TTS additions; no model/voice/VAD/audio change; no Memory writes; no word map.

## 3. Real-session matrix (ONE session, item.create + response.create, no audio, no human ear)

`evidence/vocab_matrix_real_session.json` — 33 turns: 8 baseline (pre-audit instructions,
rendered from `git HEAD` module) + 25 post-fix matrix turns.

| result | count |
|---|---|
| raw automatic pass (expected token present) | 29 / 33 |
| reclassified after inspection | **31 PASS** · 2 FAIL |
| non-word / pseudo-spelling tokens in any transcript | **0** |
| spelling turns letter-by-letter correct | **4 / 4** (incl. baseline) |

Key observations:

* **Know example 街道 → “strit”: NOT reproduced.** `street` appeared correctly in every
  relevant turn (pre-audit m01, post-fix m01/m20/m21/m22; spelling m16 letter-perfect in
  both phases). With zero pseudo-spellings in 33 transcripts, the human's “strit” is
  classified **AUDIO_ONLY_PERCEPTION** (native Audio↔Audio pronunciation heard differently)
  — or possibly ASR-influenced in the original voice session; it is **not** a model content
  error in text mode.
* Confusable pairs all correct: 船→boat/ship-class, 羊→sheep (not “ship”), 居住→live,
  离开→leave.
* **m11 船 → “boat”** (both phases): a real, correctly-spelled canonical word (boat vs ship
  is context); expectation list was too narrow → reclassified **PASS_POLICY**, no defect.
* **m19 街道是什么？ → Chinese definition, no English word** (both phases): genuine
  instruction-following gap for a definition-shaped question → after this audit the note for
  that branch explicitly forbids a definition-only answer (machine-validated in
  VOCAB_ACCURACY_TESTS A21; no further real session available to re-verify).

### Failure taxonomy (as requested)

| class | count | note |
|---|---|---|
| INPUT_ASR_ERRORS | 0 | text-mode session; ASR not exercised by design |
| ROUTING_ERRORS | 0 in post-fix (7 machine-proven pre-audit, all fixed) | m16/m19 were the 2 baseline-routed NONE cases; m19 failed, m16 still answered correctly |
| MODEL_CONTENT_ERRORS | 2 (m19 pre + post) | *no English word given for a definition-shaped ask*; zero spelling errors |
| AUDIO_ONLY_CASES | 1 | the human's 街道→“strit” listening impression (transcript-side correct) |
| CLIENT_DISPLAY_ERRORS | 0 | GUI transcript path already fixed & live-tested |

## 4. Regression suites added / re-run

* **VOCAB_ACCURACY_TESTS** (`gateway/tests/vocab_accuracy_tests.py`) — **79 checks** covering
  C→E routing (matrix words + variants), E→C preservation, spelling requests, context rules,
  policy-content structure, activity resume, language stability, and the pseudo-spelling
  **fixture validator** (`strit/shep/hotal/acommodation` flagged; canonical words accepted).
  The validator lives only in the test/audit tooling — **never used at runtime**.
* Full battery: BEHAVIOR1 111/111 · MVP_INTEGRATION 28/28 · CLIENT_UI 48/48 ·
  GUI_TRANSCRIPT_LIVE 25/25 · CLIENT_UI_INTEGRATION 19/19 · R-1f 179/180 (unchanged
  env-only sentinel).

## 5. Honest limits

* One session cannot re-verify the refined m19 note; it is machine-validated only.
* The baseline phase ran before the policy switch inside the same session — carryover is
  possible for the 5 repeated questions (noted in the evidence; all still passed).
* Vocabulary answers are never written to Memory (boundary tests re-asserted).