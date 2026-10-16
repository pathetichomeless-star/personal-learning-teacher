# CONVERSATIONAL MVP — HUMAN ACCEPTANCE TEST (Mac client → NAS test sidecar)

Status: **ARMED — waiting for the product owner.** The Mac client's OTA now points at
`http://192.0.2.1:28211/xiaozhi/ota/` (sidecar WS `ws://192.0.2.1:28210/xiaozhi/v1/`).
Rollback: see `PHASE-MVP-SIDECAR.md` (single-line restore).

## Before starting

1. Start py-xiaozhi on the Mac **from your own terminal** (macOS accessibility permissions),
   wake word 你好小智 or the manual prefix key.
2. Speak normal Chinese — the default is Chinese chat. No "mode" commands are needed;
   just talk. Internal labels are never spoken.
3. Optional background capture while you test (on the NAS):
   `ssh xiaozhi-nas 'docker logs -f xiaozhi-mvp-sidecar | grep -E "behavior|tts|response" | head -200'`

## The 17 scenarios

| # | do this (speak) | expect |
|---|---|---|
| 1 | “你好小智，我们随便聊聊” then any Chinese chit-chat | natural Chinese chat, short friendly replies |
| 2 | “Can we just talk in English?” (or “说英语”) then chat | English mirror; no menu-like behavior |
| 3 | “我们练一下酒店英语” then play check-in | English hotel role-play; corrections brief, at most one |
| 4 | mid-hotel: “accommodation 是什么意思？” | Chinese meaning → the word → pronunciation → English example; then conversation returns to the hotel scene automatically |
| 5 | “再来一次” | repeats the recent content naturally (no meta talk) |
| 6 | “说慢一点” | slower pace immediately in the same activity |
| 7 | “这个太简单了，难一点” | stays in the same activity, richer language |
| 8 | “我想背几个单词” …then… “别背单词了，聊会儿天” | vocabulary teaching → natural switch back to chat |
| 9 | “以后解释单词先用中文，记住。” | one short confirmation |
| 10 | restart the client (new session) → ask “hotel 是什么意思” | explanation still Chinese-first (preference persisted) |
| 11 | “忘掉这个偏好。” → ask a word again | removal confirmed; default formatting afterwards |
| 12 | “继续上次的课” | announces the real lesson 12 (一般过去时 -ed) and starts it |
| 13 | “我学到哪里了？” | real numbers (lesson 12; lesson 1 needs review; 1 review item due) |
| 14 | start a long answer (ask for a story), interrupt mid-speech | playback stops instantly; the new utterance is understood |
| 15 | watch the client chat bubbles during any turn | user text STREAMING → FINAL; assistant text streams; interrupted turn shows INTERRUPTED with the partial text |
| 16 | after any interrupt / after a barge-in | old audio must NOT resume; no leftover fragment plays |
| 17 | listen carefully during silences | no residual static/buzz/click |

## Advisory checks (machine, afterwards)

```sh
curl -s http://192.0.2.1:28211/health | python -c "import json,sys; d=json.load(sys.stdin); print({k:d[k] for k in ('qwen_connected','qwen_sessions','responses_completed','responses_cancelled','barge_ins','upstream_errors','qwen_dispatch_errors_total')})"
ssh xiaozhi-nas 'docker logs xiaozhi-mvp-sidecar 2>&1 | grep "behavior decision" | tail -20'
ssh xiaozhi-nas 'docker exec xiaozhi-mvp-sidecar sh -c "cat /app/data/memory.json"'
```
Expected after the run: dispatch errors 0; `behavior decision` lines for your utterances
(activity/temp/language changes visible); memory.json holding only preferences/weak words
(no progress keys).

## PASS / FAIL

* **PASS** = scenarios 1–17 behave as described, no old-audio resume, no static, and no
  fabricated progress anywhere.
* **FAIL / notes** = record the scenario number, what was said, and what happened; the
  sidecar logs + `/health` stay available for diagnosis. The automated real-Qwen budget is
  **fully consumed (4/4, LOCKED — remaining 0)**: no automated re-test session exists; the
  next real conversational validation is this product-owner acceptance itself, so please
  capture notes carefully on the first pass.

## GUI TRANSCRIPT RETEST (addendum 2026-10-08)

Human test round 1 passed voice/Chinese/English/CMD+K AUTO but failed only the visible
conversation text. Root cause + fix: `FINDING-GUI-TRANSCRIPT.md` (client-only; no sidecar
rebuild). Retest focus:

1. restart py-xiaozhi (the fix is in the client source; OTA unchanged);
2. during any voice turn the window now shows **你:** / **老师:** bubbles under the avatar —
   user text appears while you speak (STREAMING) then settles (FINAL);
3. assistant text streams while speaking and stays visible when finished;
4. interrupt mid-answer → the bubble keeps only the text that was actually received and
   shows （已打断）;
5. reconnect (restart client) → previous bubbles are cleared, new session starts empty;
6. scroll follows the newest bubble automatically; Chinese and English both render;
7. the avatar/status area remains visible above the bubbles (capped height).

## Stop rules honored

Avatar/digital human, camera vision, Knowledge-1, advanced ADMIN-2 / unified admin UI,
promotion to primary, soak tests and credential rotation were **not** performed.