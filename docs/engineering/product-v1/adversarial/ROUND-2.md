# ROUND 2 — targeted re-attack on the Round-1 fixes + neighbouring surfaces

**Method:** each of the ten red-team agents re-attacked its own Round-1 findings and the
surfaces *around* the fix, then a different-class agent cross-checked weekly. Attacks were
deterministic/mock-only (no real-Qwen session, no NAS, no primary/Workbench/production,
product source read-only for the attackers).

**Baseline under attack:** `e3c9b6c` (Round-1 remediation).

**Remediation commit for this round:** `b854778`.

## Reports consumed

`reports/red_b-round2.md` · `red_c-round2.md` · `red_d-round2.md` · `red_f-round2.md` ·
`red_g-round2.md`

## Round-1 finding verdicts (all closed and re-verified)

| Round-1 finding | Verdict | Evidence |
|---|---|---|
| RB-02 / RB-05 secret detector | CLOSED (core) → but obfuscation route reopened (RB2-01/02) | literal case refused at write **and** load |
| RB-06 / RB-07 sibling-partition erase | CLOSED | `D6` keeps both partitions |
| RB-08 renderer flattening | CLOSED | one-line flattening + control-char refusal |
| RB-09 / RG-07 change signature | CLOSED | `SG1–SG4` (equal-size rewrite, in-place append, hardlink edit, symlink swap) all detected |
| F1 lone-surrogate ingestion | PARTIALLY CLOSED → R2-C2 | body guarded; non-body fields still 500 |
| F2 / F3 knowledge framing + header | CLOSED | every field flattened; header denies progress authority |
| RED-D-01 / RED-H-01 unverified write | CLOSED | `_persist()` + honest disk read-back; unwritable disk → non-2xx |
| RG-01 / RG-02 / RG-03 multi-instance | CLOSED (core) | in-process multi-instance/multi-thread scale 0 loss |
| RG-04 / RG-04b memory RMW | CLOSED | 90/90 per configuration |
| RED-I-01 / -02 / -04 / -07 | CLOSED | archive/backup perms 600; drivers excluded from the image |
| RED-J-01 / -02 / -03 / -06 / -07 | CLOSED | see `reports/red_j-round3.md` re-run |
| R-F-1 client FINAL-bubble | CLOSED_MITIGATED → residual **R-F-5** (MAJOR, deferred) | see below |

## NEW findings (Round 2)

### MAJOR (6)

| ID | agent | surface | finding |
|---|---|---|---|
| RB2-01 | RED-B | memory secret guard (write+load) | obfuscated secret values (homoglyph / zero-width / leet) still admitted |
| RB2-02 | RED-B | memory load seam | a crafted file could still plant an obfuscated secret value past the seam |
| RB2-03 | RED-B | memory progress guard (write+load) | progress-shaped values still slipped past the shape regex |
| RB2-04 | RED-B | memory load seam | a crafted file could still plant a progress-shaped value |
| RED-D-R2-01 | RED-D | all three stores (cross-process) | mutations were not serialised **between processes**: ~50 % of committed writes lost, audit entries lost |
| R-F-5 | RED-F | client transcript store | a late/foreign final transcript arriving while an *older* turn is still non-FINAL is re-attributed to the older turn (root cause in the frozen `turns.py`) |

### MINOR (7)

| ID | agent | surface | finding |
|---|---|---|---|
| R2-C1 | RED-C | knowledge whole-block bound | newline separators were not reserved → the block could overshoot `max_chars` by ≤ +2 |
| R2-C2 | RED-C | knowledge ingestion | a lone surrogate in a **non-body** field raised → 500 `persist_failed` instead of 400 |
| R2-N1 | RED-C | policy renderer | policy text fields accepted newline-bearing values (operator-authenticated framing) |
| RED-D-R2-03 | RED-D | policy validation | fields made **only** of zero-width/control characters were accepted (render as nothing) |
| R-F-6 | RED-F | gateway turn keying | a `transcript.done` arriving before any `response.created` |
| R-F-7 | RED-F | client transcript store | a spurious `interrupted:true` for the current turn |
| RG2-02 | RED-G | memory `load`/`reload_if_changed` | the load seam cached a signature NEWER than the bytes read (stale-forever) |

### INFO (6)

RB2-05 (keys not control-char checked) · RB2-06 (evasions reachable via the admin API) ·
R2-N2 (memory whole-block not bounded to `max_chars`) · RED-D-R2-02 (`_flush`
auto-creates parent dirs) · RED-D-R2-04 (symlinked policy path: `os.replace` swaps the
link) · RED-D-R2-05 (wide/flat document error amplification).

## Remediation (commit `b854778`)

1. **normalize-then-match screening** — `modules/memory/store.py` gained `fold_text`
   (NFKC + invisible-character strip + homoglyph fold + traditional→simplified + casefold)
   and a 4-view screen (folded / separator-stripped / leet / leet-loose) applied at **both**
   the write path and the load seam, closing RB2-01…04.
2. **cross-process write serialisation** — new `modules/_store_lock.py`: one per-path
   re-entrant lock shared by every instance, taken around `reload → mutate → flush`,
   closing RED-D-R2-01.
3. **whole-block bound** — the knowledge block now trims-and-marks so the cap is strict
   (R2-C1, R2-N2).
4. **ingestion field guards** — surrogate / control-character guards extended to every
   ingestion field (R2-C2).
5. **policy single-line + visible-text fields** — control characters and
   invisible-only fields refused (R2-N1, RED-D-R2-03).
6. **capped error lists** — validation error lists bounded at 50 (RED-D-R2-05).

Guard suite after this round: **ADVERSARIAL_REPAIR_TESTS 91/91**.

## Cross-process evidence (Round-2 fix)

80/80 memory saves and 80/80 policy applies persisted across two processes (was ~43/~41).

## Deferred by authorization (not fixed)

**R-F-5** (and its parent R-F-1) — root cause is in `gateway/app/turns.py`, which the
product owner locked byte-identical for this run. Status: **DEFERRED_BY_AUTHORIZATION**;
`MAJORS_OPEN = 1`. User-visible impact is transcript presentation only (no audio, no
security). The proposed 3–5-line UI-only patch is recorded in
`FINAL-ADVERSARIAL-REPORT.md`.
