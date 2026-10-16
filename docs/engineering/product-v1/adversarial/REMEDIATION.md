# REMEDIATION LEDGER — the sole product-code writer

Only the remediation lead modified product source during the adversarial run. Every change
below is a repair of a numbered finding (or its guard). No feature, provider, model, voice,
VAD, frame, guard, slack, Opus, FIFO, generation-ownership or barge-in semantics changed,
and the frozen R-1f surfaces stayed byte-identical.

| Commit | Round | Scope |
|---|---|---|
| `e3c9b6c` | 1 | all Round-1 BLOCKER/MAJOR findings + repair guards |
| `b854778` | 2 | obfuscation screening, cross-process serialisation, framing/bounds |
| `6d3c8a9` | 3 | blocking-lock regression + Round-3 residuals |
| `76e22cd` | 4 | Round-3 residual MAJORs (RG2-01, RED-J-R3-01/02/04/06) + MINORs |
| `e9746ad` | RED-F closure | authorized UI-attribution fix in `gateway/app/turns.py` (R-F-1 / R-F-5) |

## Round 1 (`e3c9b6c`)

- **Store durability & concurrency discipline** — shared per-path lock, merge-before-mutate,
  change signature `(mtime,size,ctime,ino)`, tmp cleanup on failure, `PersistError`, honest
  disk read-back through a **new** store instance (`RB-06/07`, `RED-D-01`, `RED-H-01`,
  `RG-01…04b`, `RG-06`, `RG-07`, `RB-09`).
- **Memory partition preservation** — `_read_other_users()` so a flush never erases a
  sibling user's partition (`RB-06/07`).
- **Data framing** — one-line flattening, DATA-not-instructions headers, progress-authority
  denial, control-character refusal (`RB-08`, `F2`, `F3`, `RED-J-06/07`, `RED-I-04`).
- **Secret/progress guards** on write and load (`RB-02`, `RB-05`).
- **Rendered-instruction precedence** — a saved pref is restated only when it agrees with
  the effective state (`RED-J-02/03`).
- **Client FINAL-bubble immutability** (`R-F-1`, mitigated).
- **Deployment hygiene** — drivers excluded from the image, archive perms 600
  (`RED-I-01/02/04/07`).

## Round 2 (`b854778`)

- **normalize-then-match screening** (`modules/memory/store.py`): `fold_text` (NFKC +
  invisible strip + homoglyph fold + traditional→simplified + casefold) and a multi-view
  screen applied at write **and** load (`RB2-01…04`).
- **`modules/_store_lock.py`** (new): one per-path re-entrant lock shared across instances,
  wrapping `reload → mutate → flush` (`RED-D-R2-01`).
- **Whole-block bound** trim-and-mark (`R2-C1`, `R2-N2`).
- **Ingestion-field surrogate/control guards** (`R2-C2`).
- **Policy single-line + visible-text fields** (`R2-N1`, `RED-D-R2-03`).
- **Capped error lists** (`RED-D-R2-05`).

Cross-process evidence: 80/80 memory saves, 80/80 policy applies.

## Round 3 (`6d3c8a9`)

- **Bounded non-blocking lock** — `LOCK_EX|LOCK_NB` with a deadline
  (`XZ_STORE_LOCK_TIMEOUT_MS`, default 500 ms), taken only by **writers**
  (`StoreLock.exclusive()`); reads take only the in-process RLock (an `os.replace` already
  makes a read see a consistent file). On timeout → `StoreLockTimeout` → 503 `store_busy`
  (`RED-A-R3-01`). Measured: no holder 200 in 2 ms; external holder 503 in 509 ms with the
  loop still serving; recovery 200 in 2 ms.
- **Round-3 residuals** — capped preview errors (`RED-A-R3-02`), stale-age floor
  (`R3-E-1`), non-fatal audit append (`R3-E-2`), strict API types + validate-before-dup
  (`RED-H-R3-01…05`), rejected keys no longer echoed (`RED-I-R3-01`), lock file mode 600
  (`RED-A-R3-03`, `RED-I-R3-02`).

## Round 4 (`76e22cd`)

| Finding | Fix | Files |
|---|---|---|
| **RG2-01** history duplication | one `_bound_history()` for `load()` + `_trim_history()` | `modules/policy/persona.py` |
| **RG2-02 / RG2-MP** stale-forever signature | signature captured **before** the read; `MemoryStore.load` under the shared lock | `modules/memory/store.py`, `modules/knowledge/store.py`, `modules/policy/persona.py` |
| **RED-J-R3-01** EN refusal | English inability/refusal forms added to the narrow guard; explicit-Chinese mirrored in English | `modules/intent/behavior.py` |
| **RED-J-R3-02 / R3-06** builtin-vs-explicit language | `explanation_language` suppressed unless it agrees with the effective language | `modules/intent/behavior.py` |
| **RED-J-R3-03** reload reverts explicit pref | `BehaviorState.explicit_prefs` + reload skips user-set keys | `modules/intent/behavior.py`, `gateway/app/behavior.py` |
| **RED-J-R3-04 / R3-05** screen under/over-match | shape-based progress screen + whole-word ASCII secret keywords (separator-tolerant) + CJK lookaheads | `modules/memory/store.py` |

## RED-F closure round (`e9746ad`) — authorized turns.py UI-attribution fix

The product owner lifted the R-F-1 / R-F-5 deferral and authorized **one
narrowly-scoped change to `gateway/app/turns.py`** for UI transcript / interrupt
attribution only:

- `Connection._ui_owns_generation(gen)` — a response owns the live/current UI
  turn iff it is the **most recently created response** (`gen is self._recent_gen`).
- Assistant transcript forwarding: events **with a `response_id`** forward only
  for the owning response; superseded / never-created rids are dropped. Id-less
  events keep the existing tolerance.
- `_count_response_done(status, ui_gen)` — the interrupted notice is emitted
  only when the cancelled response still owns the live generation; the turn key
  is **frozen at decision time** so a fire-and-forget send cannot drift onto a
  newer `response.created`.

Scope audit: the diff touches only the `_ui_*` helper, the transcript-forwarding
block, `_count_response_done` and its call sites; audio/pacing/generation/
cancellation/accounting lines are untouched; `{audio,qwen,ws,protocol,counters}.py`
remain byte-identical to `2fd8d4f`. Guards: `red_f_round3.py` (27/27), updated
round-1 (`A5.1`/`B3.1`) and round-2 (`D1.1`/`D1.2`) semantics. Full closure
record: `reports/red_f-round3.md`.

## Guard coverage

`gateway/tests/adversarial_repair_tests.py` (ADVERSARIAL_REPAIR_TESTS) pins the repaired
behaviour directly — every guard asserts the *fixed* behaviour, never "the product changed".

| Round | Suite size |
|---|---|
| 1 | 62 |
| 2 | 78 |
| 3 | 91 (kept) |
| 4 | **123 / 123 PASS** (adds RG2-01, RG2-02, RED-J-R3-01, -R3-02, -R3-03, -R3-04, -R3-05) |

## Full matrix after Round 4 (all green)

KNOWLEDGE1 70/70 · MEMORY_V1 61/61 · MEMORY1 19/19 · PERSONA_POLICY 62/62 · ADMIN1 83/83 ·
ADMIN2 69/69 · ADMIN_SECURITY 29/29 · ADMIN_UI 23/23 · BEHAVIOR1 111/111 ·
VOCAB_ACCURACY 79/79 · WORKBENCH1 25/25 · MVP_INTEGRATION 28/28 · PRODUCT_V1_INTEGRATION
33/33 · PRODUCT_BOUNDARY 23/23 · CLIENT_UI1_INTEGRATION 19/19 ·
**ADVERSARIAL_REPAIR_TESTS 123/123** · **RED_G_ROUND2 45/45** ·
**R1F_REGRESSION 179/180** (the 1 = documented macOS dev-libopus `OpusError` environment
sentinel, baseline-proven at the pristine commit).

## Closure matrix after `e9746ad` (all green — see `reports/red_f-round3.md` §7)

ADVERSARIAL_REPAIR_TESTS 123/123 · R1F_REGRESSION 179/180 (env sentinel) ·
BEHAVIOR1 111/111 · CLIENT_UI_TESTS 48/48 · GUI_TRANSCRIPT_LIVE 25/25 ·
CLIENT_UI_INTEGRATION 19/19 · PRODUCT_V1_INTEGRATION 33/33 ·
CONCURRENCY (boundary C1–C6 + H13 + I10 + RED_G_ROUND2 45/45) · RECONNECT (R1–R4 + H12 +
I12) · BARGE_IN (R1F barge/abort + I9 + F8) · **RED_F round1 123/123 · round2 20/20 ·
round3 27/27** — `LATE_FINAL_MUTATION=0`, `OLD_AUDIO_RESUME=0`,
`GENERATION_OWNERSHIP_FAULT=0`, `AUDIO_ARCHITECTURE_CHANGED=NO` all CONFIRMED.
Product V1 sidecar rebuilt from the corrected tree: probe 65/65; re-armed
(`QWEN_MODE=real`, `qwen_connected=0`, `qwen_sessions=0`).

## Explicitly NOT changed

- `gateway/app/{audio,qwen,ws,protocol,counters}.py` — byte-identical
  (`git diff 2fd8d4f..HEAD -- <those files>` empty; re-verified post-`e9746ad`).
- `gateway/app/turns.py` — the single authorized exception (`e9746ad`): UI
  transcript / interrupted-notice attribution only (R-F-1 / R-F-5); no other
  line changed.
- Provider / model `qwen3.8-omni-flash-realtime` / voice Tina / VAD (server_vad 0.5/800 ms)
  / 20 ms frame / 15 ms send-start guard / 5 ms pacing slack / Opus / FIFO /
  generation ownership / barge-in / pacing gates / R-1f accounting.
- No real-Qwen session was opened (budget 4/4, remaining 0).
