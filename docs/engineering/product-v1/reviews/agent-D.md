# Agent D — Persona / Teaching Policy V1 + Unified Admin UI review (RAW)

Reviewed commit: `52facaa` (2026-10-08, `52facaa` @ 2026-10-08 01:03:50 +0800). Read-only reviewer; the only file created is this report. No real-Qwen drivers run.

## Method

Files read: `modules/policy/persona.py`; `modules/intent/behavior.py`; `gateway/app/behavior.py`; `gateway/app/qwen.py` (update path); `gateway/app/admin/api.py`; `admin/{index.html,app.js,styles.css}`; `gateway/tests/{persona_policy_tests.py,admin_ui_tests.py,admin2_tests.py}`; `docs/engineering/product-v1/{PERSONA-POLICY-V1.md,UNIFIED-ADMIN-UI.md}`.

Commands (verbatim summary lines):
```
PERSONA_POLICY_TESTS: 59 checks, 59 PASS, 0 FAIL
ADMIN_UI_TESTS: 23 checks, 23 PASS, 0 FAIL
```

Probes (stdin heredoc, nothing written in repo): duplication probe (F1); validation probes — `unknown section`, nested-unknown (`speed_levels`), `language.default` enum, over-long (700>600), empty string all rejected; `DEFAULT_POLICY` not mutated by validate/render.

## Findings

**MAJOR — F1: the "exactly ONE source of prompt text" guarantee is violated; router notes hardcode policy-configurable directive text.**
`render_instructions` appends the activity instruction (`behavior.py:740`, composed from the policy) *and* `dec.note` (`behavior.py:752-754`) in the same block. Several `d.note` literals in `modules/intent/behavior.py` restate content that is already an admin-editable policy field:
- `behavior.py:616-618` (VOCAB_LEARN note) near-verbatim duplicates `persona.py:78` `teaching.vocabulary_format`. Probe: rendered block contains both `"Teach vocabulary conversationally: <format>"` and the hardcoded `"Teach 1-3 useful words naturally (word, Chinese meaning, pronunciation, one example), then a quick check."` After `validate_policy({"teaching":{"vocabulary_format":"NEWFORMAT_XYZ"}})` the block shows `NEWFORMAT_XYZ` **and** the stale old format note — the edit is only half-applied. This is operator-reachable: `admin/app.js:298` ships `vocabulary_format` in the form, so editing it via the UI emails contradictory guidance to the model.
- `behavior.py:328-333` (TRANSLATE) and `behavior.py:312-314` (spelling) duplicate the canonical-spelling rule from `persona.py:83-98`. Probe: `"canonical English spelling FIRST"` occurs **twice** in the rendered TRANSLATE block.

This directly contradicts `PERSONA-POLICY-V1.md:11` ("there is exactly **one source of prompt text** in the product"). Impact is bounded (the policy line still renders; no security/data issue), but the single-source requirement is a stated V1 acceptance item and is not met — the policy does not fully control the rendered prompt.

**MINOR — F2: temp-intent directive wording is not in the policy schema.** The policy's closed sections are persona/language/teaching/activities/scenarios/limits (`persona.py:40`); there is no temp-intent section. The QUERY_KNOWLEDGE (`behavior.py:414-418`), EXPLAIN_GRAMMAR, QUERY_PROGRESS and TRANSLATE notes are hardcoded router strings. Requirement item "temp intent policy incl. QUERY_KNOWLEDGE" is satisfied functionally (a directive is rendered) but not as structured, admin-configurable policy.

**MINOR — F3: a second, legacy prompt string remains in the gateway.** `qwen.py:24-31` `TUTOR_INSTRUCTION` is an independent persona prompt, used only as a fallback when instructions are empty (`qwen.py:397,408`). `BehaviorLink` always calls `set_instructions(render_instructions(...))` (`behavior.py:121-124,165-167`), so it is unreachable in the product path — but it is a surviving duplicate prompt source.

**INFO — F4: `render_policy_overview` (`persona.py:361-368`) previews only persona/language/teaching.** Edits to activities/scenarios/limits are validated but their rendered effect is not shown in the UI preview.

## Verified correct (no finding)

1. **Structured policy + validation** — closed sections; all directive fields present (persona name/role/tone/personality/philosophy/length; language default/code-switch/English-practice/explanation/explicit-priority; teaching frequency/style/vocabulary format/canonical spelling/IPA/grammar/speed/difficulty/encouragement; 8 activity policies; 9 scenarios; limits). Unknown sections/keys, bad enums, over-long/empty fields, non-dict all rejected (`persona.py:188-275`); partial candidates deep-merge without mutating defaults (probe; P1p/P1r). Taxonomy pinned to `intent.MAIN_ACTIVITIES` (P1m/P1n/P1o).
2. **Precedence** reflected: language header "highest priority" + override line (`persona.py:293-302`), saved-preference line (`behavior.py:769-783`), activity default, then persona/closing default; `effective_language` encodes explicit > EXPLAIN_WORD pref > activity default > input mirror (`behavior.py:222-235`). P1t confirms override wins.
3. **Bounded render** — `max_instruction_chars` truncation marker (`behavior.py:792-795`; P1s).
4. **Store** — preview/apply/read-back/rollback/audit/versions, atomic 600 write, HISTORY_MAX=20/AUDIT_MAX=200, corrupt fail-soft, sanitized audit (`persona.py:376-561`; P3a-P3q, admin2 B1-B13).
5. **Hot apply** — only at a safe boundary; instructions-only `session.update` (`qwen.py:399-411` contains no model/voice/turn_detection/modalities; P4e); `_maybe_apply` guards `is_safe_boundary` (`behavior.py:369-407`); policy hot-reload at next turn (`behavior.py:126-158`; P4b/P4c/P4d). UI exposes **no** model/voice/VAD controls — `index.html:39` and `app.js:353-354` state the frozen surface; only read-only display (`app.js:162`).
6. **Admin UX** — nav 仪表盘/实时状态/诊断/角色与教学/记忆/知识库/课程进度/意图·路由诊断 (`index.html:24-31`); ≥6 `window.confirm` guards; sessionStorage-only token, no URL token, no external URLs (U8/U9); memory page note "课程进度由 Workbench 管理，不存储在记忆中。" (`app.js:430`); workbench 只读 badge (`app.js:675`); no raw JSON required for common actions. Both UI suites 100% pass.

AGENT_D = FAIL

## RE-CHECK @ 90b8ab4 (2026-10-08)

Verified commit `90b8ab4` (2026-10-08 01:13:09 +0800; worktree clean). Read-only.

### Re-ran
```
PERSONA_POLICY_TESTS: 61 checks, 61 PASS, 0 FAIL
ADMIN_UI_TESTS: 23 checks, 23 PASS, 0 FAIL
```
Independent probes (stdin heredoc, /tmp only):
- P1 edit `teaching.vocabulary_format=NEWFORMAT_XYZ`, route "学几个新单词", render → `NEWFORMAT present: True | stale old-format note present: False`
- P2 TRANSLATE block `'canonical English spelling FIRST' count: 1` (was 2); `in d2.note: False`
- P3 edit `language.word_explanation_order` → note composes it: `True`
- P4 default EXPLAIN_WORD note carries pinned phrase `FIRST its Chinese meaning`: `True`
- P5 `BehaviorLink` + `PolicyStore` (admin `apply` `LINKFMT_ABC`) → next turn's hot-apply block carries the new format; `stale old-format note present: False` (link passes `self._policy` into `intent.route`, `gateway/app/behavior.py:231`)
- broad scan of policy phrases (≥4 words) appearing verbatim in `behavior.py` → only `.teaching.grammar_explanation => one point, plain words, one example`
- grammar probe: edit `teaching.grammar_explanation=NEWGRAMMAR_QQQ`, route "这句话语法为什么" → block contains `NEWGRAMMAR_QQQ` **and** the stale `one point, plain words, one example` (note at `behavior.py:563`)

### Status per original finding
- **MAJOR (single source / duplicated directive text): PARTIALLY CLOSED — STILL OPEN.** `vocabulary_format`, `canonical_spelling_rules` and `word_explanation_order` now reference/compose the policy (verified: P1-P5). BUT `teaching.grammar_explanation` is still duplicated verbatim in the EXPLAIN_GRAMMAR note (`modules/intent/behavior.py:563`); that field is admin-editable (`admin/app.js:300`), so editing it leaves the stale directive in the live prompt. Same class as the original MAJOR → remains **MAJOR**.
- **MINOR (temp-intent wording not in policy schema): OPEN.** Unchanged (QUERY_KNOWLEDGE / EXPLAIN_GRAMMAR / QUERY_PROGRESS notes remain router-side).
- **MINOR (`qwen.py` TUTOR_INSTRUCTION fallback): OPEN.** Unchanged (`gateway/app/qwen.py:24`).
- **INFO F4 (preview covers 3/6 sections): OPEN.** Unchanged.

### New finding
- **INFO — residual tail duplication.** The VOCAB_LEARN switch note keeps the tail fragment "then a quick check" (`modules/intent/behavior.py:622`), echoing the default `vocabulary_format` tail. Generic, low impact; not the full format clause.

### Verdict
The repair closes the vocabulary/spelling/explanation-order duplication, but the MAJOR "exactly ONE source of prompt text" defect recurs for `teaching.grammar_explanation` (verbatim duplicate in the EXPLAIN_GRAMMAR note, operator-reachable, edit does not propagate). MAJOR still open → FAIL.

AGENT_D = FAIL

## RE-CHECK 2 @ 2cf4211 (2026-10-08)

Verified commit `2cf4211` (2026-10-08 01:16:40 +0800). Read-only.

### Re-ran
```
PERSONA_POLICY_TESTS: 62 checks, 62 PASS, 0 FAIL
BEHAVIOR1_TESTS: 111 checks, 111 PASS, 0 FAIL
VOCAB_ACCURACY_TESTS: 79 checks, 79 PASS, 0 FAIL
```
Independent probes (stdin heredoc, /tmp only):
- grammar: edit `teaching.grammar_explanation=NEWGRAMMAR_QQQ`, route "这句话为什么用过去式？" →
  note `'TEMPORARY (this turn only): explain the grammar briefly in Chinese — NEWGRAMMAR_QQQ. Then return naturally to free chat.'`;
  `NEWGRAMMAR in block: True | stale 'plain words' present: False`
- final sweep — every policy string (persona/language/teaching/activities/scenarios/limits), all phrases ≥4 words, tested for verbatim presence in `modules/intent/behavior.py`: `(none)`.

### Status per finding
- **MAJOR (duplicated directive text / single source): CLOSED.** `grammar_explanation` now composes into the EXPLAIN_GRAMMAR note (`behavior.py:562-565`); no policy phrase ≥4 words survives verbatim in `behavior.py`. Combined with RE-CHECK 1, `vocabulary_format`, `canonical_spelling_rules`, `word_explanation_order` and now `grammar_explanation` are all policy-driven.
- **MINOR (temp-intent wording not in the policy schema): NON-BLOCKING / accepted.** Notes remain router-side but now compose/reference the policy text; no directive text is duplicated. Requirement is met in substance.
- **MINOR (`qwen.py` TUTOR_INSTRUCTION fallback): OPEN, non-blocking.** Unchanged (`gateway/app/qwen.py:24`); unreachable (BehaviorLink always sets rendered instructions). Not the duplication class — a distinct fallback constant.
- **INFO F4 (preview covers 3/6 sections): OPEN, non-blocking.** Unchanged.

### New finding
- **INFO — residual tail fragment.** VOCAB_LEARN note keeps the 4-word tail "then a quick check" (`modules/intent/behavior.py:622`), a fragment of the default `vocabulary_format` tail. Generic phrasing; the substantive format clause is no longer duplicated. Non-blocking.

### Verdict
The D-MAJOR is closed and no remaining MAJOR/BLOCKER exists; all three suites pass. Only non-blocking INFO/MINOR residuals remain.

AGENT_D = PASS