# PHASE 7 — WORKBENCH-1 READ-ONLY (real lesson / progress / review)

Date: 2026-10-07 · Status: **PASS** · Evidence: `evidence/mvp-local-suites.txt`
(`WORKBENCH1_TESTS: 25/25`, integration I7/I11)

## Scope delivered

`modules/adapters/workbench.py` — thin **GET-only** adapter over the live
english-learning-workbench (`/sync/state`, `/workbench/content/dayNN.json`),
matching the ADMIN-ARCH-1 Agent-E contract:

* `continue_lesson()` → real `currentLesson` (live: **12**) + unit title from
  `day12.json` (live: 一般过去时（规则动词 -ed）) + objectives;
* `query_progress(scope)` → real counts from `lessons[].decision`
  (PASS/REVIEW/REPEAT, copied verbatim), review due list from `reviews[]`
  (not-done and `nextReviewAt <= today`), next due date, due words (refId tail);
  `scope="review"` strips the rest;
* **FRESH_TTL = 30 s / CACHE_MAX_AGE = 300 s** exactly: fresh served as current;
  30–300 s served **with the stale label** ("约 N 分钟前的记录"); > 300 s never served
  (refetch or `unavailable`); rev-changes observed and logged;
* degradation is honest: malformed/500/timeout/down → `Result(ok=False, reason=…)`, and
  the renderer emits the fixed degrade line ("temporarily unavailable … do not invent");
* **no write path exists** — runtime assertion (fake server saw GET-only traffic) +
  static assertion (no `.put/.post/.patch/.delete`, no `"PUT"`) + the adapter source
  contains no `sync/state` write shape. Workbench stays the authoritative writer.

## Live-schema verification (read-only, 2026-10-07)

`GET /sync/state` on the NAS (`english-learning-workbench-web:18100`): rev 77,
`currentLesson=12`, `lessons["1"].decision=REVIEW`, `reviews[]` entries carry explicit
`nextReviewAt` (AUTH — used verbatim), `foundation`/`ielts` mastery records present.
Shapes were pinned before implementation; no learner data was copied anywhere.

## Wiring / privacy

* Prefetch on `speech_started` keeps the cache warm while the user is speaking; the
  turn-time read then costs ~0 ms (inline fetch only when the cache is empty, bounded
  `WB_FETCH_TIMEOUT=1.2 s`).
* Retrieved data enters only as an **ephemeral session instruction block**, marked
  "authoritative — read-only, do not remember it"; it is never persisted, never mirrored
  into Memory, never written back. Nothing from the workbench reaches MEMORY-1
  (boundary tests M2/M5 re-assert the separation).