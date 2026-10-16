# ROUND 3 — regression attack, fault injection, and independent cross-check of every fix

**Method:** each red-team agent cross-checked the fixes it did **not** write (regression
attack), plus a fault-injection pass against degraded dependencies. Deterministic/mock-only
(no real-Qwen session, no NAS, no primary/Workbench/production, product source read-only for
the attackers).

**Baseline under attack:** `b854778` (Round-2 remediation).

**Remediation commits:** `6d3c8a9` (blocking-lock regression + Round-3 residuals) and
`76e22cd` (the residual MAJORs from the two late-arriving Round-3 reports — see §3).

## Reports consumed

`reports/red_a-round3.md` · `red_e-round3.md` · `red_h-round3.md` · `red_i-round3.md` ·
`red_j-round3.md` · `red_g-round2.md` (concurrency re-attack) · `red_f-round2.md`
(fault-injection / client boundary)

## 1. Cross-check verdicts per fix

Every Round-1/2 MAJOR was independently re-verified as closed by a different agent, with two
exceptions that produced new findings:

| Fix under test (Round 2) | Verdict | Note |
|---|---|---|
| normalize-then-match screen (write + load) | CONFIRMED for the literal/obfuscated case | but the shape set was incomplete (RED-J-R3-04) and over-broad (RED-J-R3-05) |
| cross-process write serialisation | CLOSED core; **regression found** | the locking `flock` had no deadline and ran on the shared event loop (RED-A-R3-01) |
| whole-block bound | CONFIRMED | strict after `6d3c8a9` |
| ingestion field guards | CONFIRMED | |
| policy single-line / visible-text | CONFIRMED | |
| capped error lists | CONFIRMED (also fixed the read path, RED-H-R3-01) | |
| Framing / data-vs-instructions (F2/F3, RED-J-07) | CONFIRMED | both blocks deny progress authority |
| Frozen surfaces | CONFIRMED byte-identical | `git diff 2fd8d4f..HEAD -- app/{turns,audio,qwen,ws,protocol,counters}.py` empty |

## 2. NEW findings (Round 3, first pass) — remediated in `6d3c8a9`

### MAJOR (1)

| ID | agent | surface | finding |
|---|---|---|---|
| RED-A-R3-01 | RED-A | `modules/_store_lock.py` | the cross-process `flock` was **blocking with no deadline** and was taken synchronously on the shared WebSocket/HTTP/admin event loop → any local lock holder could freeze the whole realtime plane. Blast radius = availability of the primary audio path. |

### MINOR (9)

| ID | agent | surface | finding | fix |
|---|---|---|---|---|
| RED-A-R3-02 | RED-A | policy preview | `errors` list unbounded (response amplification) | capped at 50 in the store |
| R3-E-1 | RED-E | `render_memory_block` | a sub-minute stale age rendered "about 0 minute(s) old" | rounds to nearest minute, floor 1 |
| R3-E-2 | RED-E | admin audit ordering | an audit-append failure turned an already-durable write into an error response | audit append made non-fatal |
| RED-H-R3-01 | RED-H | policy read path | robustness/consistency | capped + typed |
| RED-H-R3-02 | RED-H | knowledge search | `top_k: true` accepted as 1 | bool rejected → 400 |
| RED-H-R3-03 | RED-H | knowledge dataset create | non-string `description` silently coerced | 400 |
| RED-H-R3-04 | RED-H | knowledge dataset create | non-string `tags[]` silently coerced | 400 |
| RED-H-R3-05 | RED-H | knowledge document add | validated **after** the duplicate lookup (409 before 400) | validate first → 400 |
| RED-I-R3-01 | RED-I | conversation path log | a rejected secret-shaped key was echoed into the log message | not echoed |

### INFO (5)

RED-A-R3-03 (lock file mode 0644 → now 600) · RED-A-R3-04 (type guard) ·
RED-I-R3-02 (lock files 0644 → 600) · RED-I-R3-03 (secret-shaped literals in upstream
example docs — pre-existing, documented) · RED-I-R3-04 (the **deployed** sidecar ran an
image older than the fixed tree — closed by the Final Clean Check rebuild).

## 3. Round-3 residuals (late reports) — remediated in `76e22cd`

`red_g-round2.md` and `red_j-round3.md` arrived after `6d3c8a9` and raised the items below.
They were fixed after the round-3 commit and re-verified by **re-running the reporters' own
suites**.

### MAJOR (5)

| ID | agent | surface | finding | fix |
|---|---|---|---|---|
| RG2-01 | RED-G | `PolicyStore.load` | the history bound was re-applied to any history longer than ONE entry, duplicating the oldest entry (`versions()` → `[1,1,2,3]` with two writers) — a regression of the RG-03 repair | one `_bound_history()` used by `load()` and `_trim_history()`, applied only when the history exceeds `HISTORY_MAX` |
| RED-J-R3-01 | RED-J | `route()` language override | the inability/refusal guard was CJK-only → "I can't speak English" flipped the session to English | English inability/refusal forms added (speech/ability verb required); the explicit-Chinese request mirrored in English |
| RED-J-R3-02 | RED-J | `render_instructions()` | a saved `explanation_language` was restated even when it contradicted the explicit current language request | suppressed exactly like speed/difficulty (only restated when it agrees) |
| RED-J-R3-04 | RED-J | memory progress screen | shape set incomplete: `第十二课`, `12课`, `lesson #12`, `progress=12`, `unit 12 done`, `我已学完第十二課` still admitted | screen rebuilt: shape-based for lesson/unit/number claims (Chinese numerals, `#`, bare `progress`, noun+done order, multi-char verb gap) |
| RED-J-R3-06 | RED-J | holistic render | same root as RED-J-R3-02 in a full turn composition | same fix |

### MINOR (5)

| ID | agent | surface | finding | fix |
|---|---|---|---|---|
| RG2-02 | RED-G | memory `load`/`reload_if_changed` | the signature was captured **after** the read → a concurrent writer left a signature newer than the content, so every later reload reported "unchanged" (stale forever) | signature captured **before** the read in the memory/knowledge/policy stores; `MemoryStore.load` now runs under the shared per-path lock |
| RG2-MP-M10 / M5 | RED-G | cross-process memory writes | intermittent **silent** lost updates in the multi-process harness | same fix as RG2-02 (RED-G's "the flock does not exclude" attribution was disproved: a direct flock counter test gave **400/400**) |
| RED-J-R3-03 | RED-J | `_maybe_reload_stores()` | a control-plane memory reload re-forced the saved speed/difficulty over a value the learner set explicitly this session | `BehaviorState.explicit_prefs` records user-set prefs; the reload skips them |
| RED-J-R3-05 | RED-J | memory screen (false positives) | ordinary facts refused by substring matching: `密码学`/`密码学家`, `进度条`, `我完成了作业`, `我学到了很多`, `tokenize`, `secretary`, `passwordless` | ASCII keywords matched as whole words (separator-tolerant but not sub-word); CJK lookaheads (`密码(?![学家])`, `进度(?![条栏表])`); bare verbs dropped in favour of shapes |

### INFO (1)

RG2-AT-KILL — a SIGKILLed writer can leave one orphan `.tmp` (inherent to `tmp→os.replace`;
the live file stayed the previous atomic version and parseable every time).

## 4. Fault-injection round (degraded dependencies)

Run by RED-E (PART 2) and RED-F. Store paths made read-only / a directory target / a
symlink / a stale external holder; the admin plane with a failing audit sink; the live
gateway under a reconnect storm. Result: every degradation is **honest** (non-2xx or an
explicit degraded line), no phantom state, no torn read, bounded tasks/threads; `R3-E-2`
was the only defect (fixed).

## 5. Re-attack verdicts after remediation

| Suite | Result |
|---|---|
| `RED_G_ROUND2` (concurrency re-attack) | **45 checks, 45 PASS, 0 FAIL**; `CROSS_SESSION_CONTAMINATION=0`, `STORE_CORRUPTION=0`, `LOST_UPDATE=0`; `FINDINGS: 0` |
| `RED_J_ROUND3` (semantic cross-check) | all R1/R2/R4/R5/R6 checks PASS (incl. every English-refusal defeat and every false-positive control); the only 6 FAILs are the **defect pins** that encoded the old buggy outcome — `CAUGHT: [all 10 smugglers]`, `MISSED: []` |
| `RED_J_TESTS` (round-1 pin) | 6 of 9 `[EXPECTED-DEFECT]` pins flipped green; the remaining 3 are the same defect pins (now closed) |
| cross-process memory | 10×15 and 5×30 saves, 8+6 trials → **0 lost** (was 1–2 per trial) |
