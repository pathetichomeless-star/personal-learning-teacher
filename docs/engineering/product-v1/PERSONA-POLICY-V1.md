# PERSONA / TEACHING POLICY V1

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 3 Persona/Teaching Policy V1 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Phase 3 of the Product V1 final completion run.  Status: **PASS** (PERSONA_POLICY_TESTS 59/59).

## Ownership

`modules/policy/persona.py` — one authoritative, versioned, validated policy object.
It is **not** another LLM: it is structured data + validation + a versioned store + the
`render_*` helpers that compose every prompt line.  `modules/intent` keeps the routing
orchestration and calls those helpers — there is exactly **one source of prompt text** in
the product (the prompt tables that used to live in `modules/intent/behavior.py` were moved
here verbatim).

## Schema (closed)

| section | fields |
|---|---|
| persona | name / role / tone / personality / teaching_philosophy / default_response_length |
| language | default(zh\|en) / chinese_default_policy / english_practice_policy / explicit_request_priority / word_explanation_order |
| teaching | correction_frequency / correction_style / vocabulary_format / pronunciation_notation / grammar_explanation / encouragement_style / vocab_policy_header / canonical_spelling_rules[1..12] / speed_levels{slow,normal,fast} / difficulty_levels{easy,normal,hard} |
| activities | the 8 activity instructions (VOCAB_LEARN composed from `{vocabulary_format}` — no duplicated prompt) |
| scenarios | the 9 scenario descriptions |
| limits | max_field_chars(100..2000) / max_instruction_chars(500..20000) / closing_followup / internals_rule |

Taxonomy consistency is test-pinned: activity keys == `intent.MAIN_ACTIVITIES`, scenario keys
== router scenarios, speed/difficulty level sets, temp-intent taxonomy covered.

## Validation / precedence

`validate_policy(candidate)` → `(merged, errors)`: unknown sections/keys are errors; strings
must be non-empty and bounded; enums closed; partial candidates deep-merge over the defaults
(missing keys fall back — unknown keys never do).  Precedence is fixed and reflected in the
renderer: hard rule > explicit current user request (language override line) > saved learner
preference > current activity > auto/default.

## Versioned store

One JSON file (atomic tmp→replace, mode 600, `threading.RLock`):

* `active()` → {version, policy, updated_at, actor}; builtin defaults are version 1 and are
  never written until the first apply; missing/corrupted storage fails soft to the defaults;
* `preview(candidate)` → validation + changed dotted key paths + would-be version + a static
  rendered preview (`render_policy_overview`) — **never mutates**;
* `apply(candidate, actor=…)` → validates (raises `PolicyInvalid`), archives the previous
  version (bounded history 20), bumps the version, appends a **sanitized** audit entry
  (ts/action/actor/from/to/changed key paths — never policy payloads, transcripts or secrets);
* `rollback(version)` → restores a historical version as a new version (audited);
* `versions()` / `audit(limit)`; `reload_if_changed()` (stat-signature based).

## Conversation integration (read-back, hot apply)

The gateway `BehaviorLink` loads the store (`POLICY_FILE`), renders every instruction with
the active policy, and calls `_maybe_reload_policy()` before each apply — an admin-applied
policy therefore reaches a live session **at the next safe boundary** (stats `policy_reloads`;
`snapshot()["policy_version"]`).  Hot apply reuses the proven **instructions-only**
`session.update` path (`QwenClient.send_instructions_update` — test-asserted to contain no
model/voice/VAD/modalities keys); the safe-boundary guard is unchanged.  Echo read-back is
verified against `session.updated` (mismatch counter).  `POLICY_FILE=""` (default) keeps the
builtin defaults with no store.

Hard guarantee: this phase changes **text-plane policy rendering only** — no audio/realtime
code, no model/voice/VAD/format changes.

## Tests

`gateway/tests/persona_policy_tests.py` → **PERSONA_POLICY_TESTS: 59 checks, 59 PASS**:
verbatim rendering anchors (persona/language/teaching/vocab-policy/closing), composed-field
single-source checks, closed-schema validation + bounds, preview/apply/rollback/audit/version
semantics, corrupt fail-soft, 600-mode, link integration (policy-driven instructions,
safe-boundary-only apply, hot reload, echo read-back, disabled store, structural
instructions-only check).

Regression at Phase 3 (no drift): BEHAVIOR1 111/111, VOCAB_ACCURACY 79/79, KNOWLEDGE1 69/69,
MEMORY_V1 54/54, MEMORY1 19/19, WORKBENCH1 25/25, MVP_INTEGRATION 28/28, ADMIN1 80/80.

## Rollback

`POLICY_FILE=""` disables the store; phase commit revertible; run rollback tag
`product-v1-pre-run` + bundle.