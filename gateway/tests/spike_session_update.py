"""PHASE 3 — session.update capability spike (direct Qwen Realtime protocol probe).

Determines mechanically whether an already-connected Qwen Realtime session
accepts a SECOND `session.update` at a SAFE BOUNDARY (IDLE / LISTENING: no
active generation, no active TTS, no active pacer output — the probe never
sends audio and never talks during a response).

Bounded: ONE real Qwen session, no audio uplink, all steps timeout-bounded.

Steps
  1. connect (Bearer from the runtime secret file); capture session.created
  2. session.update #1 (production-shaped) -> session.updated / error
  3. session.update #2 at idle (instructions ALPHA->BRAVO, voice Tina->Cherry)
       -> SESSION_UPDATE_MID_SESSION verdict
  4. conversation.item.create (role=user, text) -> error? (shape probes)
  5. response.create -> response events; transcript shows which instruction
     the model followed (ALPHA vs BRAVO) -> INSTRUCTION_HOT_APPLY verdict
  6. second response.create -> does the queued/new instruction show up on the
     NEXT response? (distinguishes IMMEDIATE vs NEXT_RESPONSE application)
  7. conversation.item.create (role=system) -> acceptance evidence
  8. close; write the evidence JSON (never contains the API key)

Usage (inside the lab container, which holds the runtime secret):
  python /tmp/spike_session_update.py --out /tmp/spike_out.json
"""

import argparse
import asyncio
import json
import os
import sys
import time

import aiohttp

DEFAULT_SECRET_FILE = "/app/secrets/qwen-realtime.env"
REAL_HOST_TMPL = "{workspace}.{region}.maas.aliyuncs.com"
REAL_PATH = "/api-ws/v1/realtime"

CONNECT_TIMEOUT = 12.0
STEP_TIMEOUT = 10.0
TOTAL_BUDGET_S = 150.0

# Round-1 finding (2026-10-07): voice "Cherry" is NOT valid for this model —
# session.updated still echoes it, but the next response.create fails with
# `InternalError.Algo.InvalidParameter: Voice 'Cherry' is not supported` and
# the server then drops the connection. Voice hot-apply is therefore tested
# LAST, with a voice from the qwen3.8 voice list.
VALID_ALT_VOICE = "Cindy"

UPDATE1_INSTRUCTION = (
    "You are a protocol probe. When the user asks you to say the word, output "
    "exactly the single word ALPHA and nothing else."
)
UPDATE2_INSTRUCTION = (
    "You are a protocol probe. When the user asks you to say the word, output "
    "exactly the single word BRAVO and nothing else."
)


def _read_secret(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f.read().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    except Exception as e:  # noqa: BLE001
        print("SECRET_READ_FAILED %r" % (e,), file=sys.stderr)
    return values


class Spike:
    def __init__(self, secret_path, out_path):
        self.secret_path = secret_path
        self.out_path = out_path
        sec = _read_secret(secret_path)
        self.api_key = (os.environ.get("QWEN_REALTIME_API_KEY")
                        or sec.get("QWEN_REALTIME_API_KEY", "")).strip()
        self.workspace = (os.environ.get("QWEN_REALTIME_WORKSPACE_ID")
                          or sec.get("QWEN_REALTIME_WORKSPACE_ID", "")).strip()
        self.region = (sec.get("QWEN_REALTIME_REGION") or "cn-beijing").strip()
        self.model = (os.environ.get("QWEN_MODEL")
                      or sec.get("QWEN_REALTIME_MODEL")
                      or "qwen3.8-omni-flash-realtime").strip()
        self.voice = (os.environ.get("QWEN_VOICE")
                      or sec.get("QWEN_REALTIME_VOICE") or "Tina").strip()
        self.url = "wss://%s%s?model=%s" % (
            REAL_HOST_TMPL.format(workspace=self.workspace, region=self.region),
            REAL_PATH, self.model)
        self.session = None
        self.ws = None
        self.closed = False
        self.ev = []                 # bounded raw event log
        self.ev_truncated = 0
        self.audio_delta_bytes = 0
        self.audio_delta_events = 0
        self.session_updated = []    # full payload echoes (bounded)
        self.errors = []             # full error payloads
        self.transcripts = []        # assistant transcript text pieces
        self.response_events = []    # created/done summaries
        self._resp_seq = 0

    # ---- logging ----------------------------------------------------------

    def log(self, kind, **fields):
        rec = {"t": round(time.monotonic(), 3), "kind": kind}
        rec.update(fields)
        self.ev.append(rec)
        if len(self.ev) > 600:
            self.ev.pop(0)
            self.ev_truncated += 1
        line = json.dumps(rec, ensure_ascii=False, default=str)
        print("EVENT %s" % (line[:400],), flush=True)

    def note_error(self, obj):
        err = obj.get("error") or {}
        self.errors.append({
            "t": round(time.monotonic(), 3),
            "code": err.get("code"), "type": err.get("type"),
            "param": err.get("param"),
            "message": (err.get("message") or "")[:300],
        })
        self.log("error_event", code=err.get("code"),
                 param=err.get("param"), message=(err.get("message") or "")[:160])

    # ---- ws plumbing -------------------------------------------------------

    async def send(self, obj):
        if self.closed or self.ws is None or self.ws.closed:
            self.log("send_skipped_closed", type=obj.get("type"))
            return False
        try:
            await self.ws.send_str(json.dumps(obj))
        except Exception as e:  # noqa: BLE001
            self.closed = True
            self.log("send_failed", type=obj.get("type"), error=repr(e))
            return False
        self.log("sent", type=obj.get("type"))
        return True

    async def recv_until(self, predicate, timeout):
        """Read events until predicate(obj, state) is True or timeout."""
        if self.closed:
            return None
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            remaining = timeout - (time.monotonic() - t0)
            try:
                msg = await asyncio.wait_for(self.ws.receive(),
                                             max(0.1, remaining))
            except asyncio.TimeoutError:
                return None
            except Exception as e:  # noqa: BLE001
                self.closed = True
                self.log("recv_failed", error=repr(e))
                return None
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type in (aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.ERROR):
                    if not self.closed:
                        self.closed = True
                        self.log("ws_closed", code=str(msg.type))
                    return None
                continue
            try:
                obj = json.loads(msg.data)
            except Exception:  # noqa: BLE001
                self.log("non_json_upstream", size=len(msg.data))
                continue
            if not isinstance(obj, dict):
                continue
            await self._observe(obj)
            if predicate(obj, self):
                return obj
        return None

    async def _observe(self, obj):
        etype = obj.get("type")
        if etype == "session.updated":
            self.session_updated.append(obj.get("session"))
            self.log("session.updated",
                     echo_keys=sorted((obj.get("session") or {}).keys()),
                     voice=(obj.get("session") or {}).get("voice"),
                     instructions_head=str(
                         (obj.get("session") or {}).get("instructions"))[:70])
        elif etype == "error":
            self.note_error(obj)
        elif etype in ("response.audio.delta", "response.output_audio.delta"):
            self.audio_delta_events += 1
            self.audio_delta_bytes += len(obj.get("delta") or "")
        elif etype in ("response.audio_transcript.delta",
                       "response.output_audio_transcript.delta"):
            self.transcripts.append(("delta", obj.get("delta")))
        elif etype in ("response.audio_transcript.done",
                       "response.output_audio_transcript.done"):
            self.transcripts.append(("done", obj.get("transcript")))
        elif etype in ("response.text.delta", "response.output_text.delta"):
            self.transcripts.append(("text_delta", obj.get("delta")))
        elif etype == "response.created":
            self._resp_seq += 1
            self.response_events.append(
                {"t": round(time.monotonic(), 3), "kind": "created",
                 "id": (obj.get("response") or {}).get("id"),
                 "seq": self._resp_seq})
            self.log("response.created", id=(obj.get("response") or {}).get("id"))
        elif etype == "response.done":
            self.response_events.append(
                {"t": round(time.monotonic(), 3), "kind": "done",
                 "id": (obj.get("response") or {}).get("id"),
                 "status": (obj.get("response") or {}).get("status")})
            self.log("response.done",
                     status=(obj.get("response") or {}).get("status"))
        else:
            if etype not in ("response.audio.done", "conversation.item.created",
                             "input_audio_buffer.committed"):
                self.log("event", type=etype)

    # ---- steps -------------------------------------------------------------

    async def connect(self):
        self.session = aiohttp.ClientSession()
        headers = {"Authorization": "Bearer " + self.api_key}
        self.ws = await self.session.ws_connect(self.url, headers=headers,
                                                heartbeat=20, max_msg_size=0)
        created = await self.recv_until(
            lambda o, s: o.get("type") == "session.created", CONNECT_TIMEOUT)
        if created is None:
            raise RuntimeError("no session.created")
        sess = created.get("session") or {}
        self.log("session.created", model=sess.get("model"),
                 voice=sess.get("voice"),
                 turn_detection=json.dumps(sess.get("turn_detection"),
                                           default=str)[:200])
        return sess

    def production_shaped_update(self, instruction):
        return {
            "type": "session.update",
            "session": {
                "model": self.model,
                "voice": self.voice,
                "instructions": instruction,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {"type": "server_vad", "threshold": 0.5,
                                   "silence_duration_ms": 800},
            },
        }

    async def observe_only(self, seconds):
        """Passively read events for `seconds` (no sends)."""
        t0 = time.monotonic()
        while (time.monotonic() - t0) < seconds and not self.closed:
            await self.recv_until(lambda o, s: False, 0.3)

    async def idle(self):
        """Safe boundary = nothing pending: best-effort quiesce via passive read."""
        await self.observe_only(1.0)
        return not self.closed

    async def trigger_text_turn(self, text, timeout):
        """item.create(user text) + response.create; wait for response.done."""
        await self.send({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        })
        await self.send({"type": "response.create"})
        return await self.recv_until(
            lambda o, s: o.get("type") == "response.done", timeout)


async def amain(args):
    t_start = time.monotonic()
    spike = Spike(args.secret_file, args.out)
    verdicts = {}
    evidence = {
        "probe": "spike_session_update",
        "phase": 3,
        "region": spike.region,
        "model": spike.model,
        "voice": spike.voice,
        "alt_voice": VALID_ALT_VOICE,
        "endpoint_host": spike.url.split("//", 1)[1].split("/", 1)[0],
        "steps": {},
    }
    sessions_used = 0
    try:
        t0 = time.monotonic()
        await spike.connect()
        sessions_used = 1
        evidence["steps"]["connect"] = {"ok": True,
                                        "elapsed_s": round(time.monotonic() - t0, 2)}

        # ---- step 1: session.update #1 (production shaped)
        await spike.send(spike.production_shaped_update(UPDATE1_INSTRUCTION))
        got = await spike.recv_until(
            lambda o, s: o.get("type") == "session.updated", STEP_TIMEOUT)
        evidence["steps"]["update1_accepted"] = got is not None

        # ---- step 2: session.update #2 at the SAFE BOUNDARY (idle),
        #              INSTRUCTIONS ONLY (voice untouched — frozen product voice)
        await spike.idle()
        n_upd_before = len(spike.session_updated)
        n_err_before = len(spike.errors)
        t2 = time.monotonic()
        await spike.send({"type": "session.update",
                          "session": {"instructions": UPDATE2_INSTRUCTION}})
        got2 = await spike.recv_until(
            lambda o, s: (o.get("type") == "session.updated"
                          or o.get("type") == "error"), STEP_TIMEOUT)
        ack_kind = ("timeout" if got2 is None
                    else ("session.updated" if got2.get("type") == "session.updated"
                          else "error"))
        echo = (spike.session_updated[n_upd_before:] or [None])[0]
        verdicts["SESSION_UPDATE_MID_SESSION"] = (
            "SUPPORTED" if ack_kind == "session.updated"
            else ("UNSUPPORTED" if ack_kind == "error" else "TIMEOUT"))
        evidence["steps"]["update2_mid_session"] = {
            "ack": ack_kind,
            "elapsed_ms": round((time.monotonic() - t2) * 1000),
            "echo_voice": (echo or {}).get("voice"),
            "echo_instructions_head": str((echo or {}).get("instructions"))[:80],
            "error": (spike.errors[n_err_before:] or [None])[-1],
        }

        # ---- step 3: response #1 -> which instruction applies?
        if not spike.closed:
            await spike.idle()
            n_err_before = len(spike.errors)
            t5 = time.monotonic()
            done = await spike.trigger_text_turn("Say the word.", STEP_TIMEOUT * 2)
            text = "".join(t for _, t in spike.transcripts if t)
            evidence["steps"]["response_create_1"] = {
                "done": done is not None,
                "elapsed_ms": round((time.monotonic() - t5) * 1000),
                "transcript": text[:200],
                "audio_delta_events": spike.audio_delta_events,
                "error": (spike.errors[n_err_before:] or [None])[-1],
            }
            upper = text.upper()
            if done is not None and text:
                verdicts["ITEM_CREATE_USER_TEXT"] = "SUPPORTED"
            else:
                verdicts["ITEM_CREATE_USER_TEXT"] = "UNDETERMINED"
            if "BRAVO" in upper:
                verdicts["INSTRUCTION_HOT_APPLY"] = "IMMEDIATE_AT_SAFE_BOUNDARY"
                verdicts["LANGUAGE_POLICY_HOT_APPLY"] = "IMMEDIATE_AT_SAFE_BOUNDARY"
            elif "ALPHA" in upper:
                verdicts["INSTRUCTION_HOT_APPLY"] = "PENDING"
            else:
                verdicts["INSTRUCTION_HOT_APPLY"] = "UNDETERMINED"

        # ---- step 4: second trigger (does BRAVO apply on the NEXT response?)
        if (not spike.closed
                and verdicts.get("INSTRUCTION_HOT_APPLY") in ("PENDING", "UNDETERMINED")):
            await spike.idle()
            t6 = time.monotonic()
            done2 = await spike.trigger_text_turn("Say the word again.",
                                                  STEP_TIMEOUT * 2)
            text2 = "".join(t for _, t in spike.transcripts if t)
            evidence["steps"]["response_create_2"] = {
                "done": done2 is not None,
                "elapsed_ms": round((time.monotonic() - t6) * 1000),
                "transcript": text2[:200],
            }
            if "BRAVO" in text2.upper():
                verdicts["INSTRUCTION_HOT_APPLY"] = "NEXT_RESPONSE"
                verdicts["LANGUAGE_POLICY_HOT_APPLY"] = "NEXT_RESPONSE"

        # ---- step 5: conversation.item.create (role=system) at idle
        if not spike.closed:
            await spike.idle()
            n_err_before = len(spike.errors)
            await spike.send({
                "type": "conversation.item.create",
                "item": {"type": "message", "role": "system",
                         "content": [{"type": "input_text",
                                      "text": "System policy note: answer in Chinese."}]},
            })
            await spike.observe_only(1.5)
            sys_errs = spike.errors[n_err_before:]
            verdicts["ITEM_CREATE_SYSTEM_ROLE"] = (
                "SUPPORTED" if not sys_errs else "REJECTED")
            evidence["steps"]["item_create_system"] = {
                "error": sys_errs[-1] if sys_errs else None}

        # ---- step 6 (LAST, deliberately): voice hot-apply with a VALID voice
        #      from the qwen3.8 list. A bad voice kills the session at the next
        #      generation, so this test can never poison earlier evidence.
        if not spike.closed:
            await spike.idle()
            n_upd_before = len(spike.session_updated)
            n_err_before = len(spike.errors)
            t7 = time.monotonic()
            await spike.send({"type": "session.update",
                              "session": {"instructions": UPDATE2_INSTRUCTION,
                                          "voice": VALID_ALT_VOICE}})
            got7 = await spike.recv_until(
                lambda o, s: (o.get("type") == "session.updated"
                              or o.get("type") == "error"), STEP_TIMEOUT)
            echo7 = (spike.session_updated[n_upd_before:] or [None])[0]
            done7 = None
            if got7 is not None and got7.get("type") == "session.updated":
                await spike.idle()
                done7 = await spike.trigger_text_turn("Say the word one more time.",
                                                      STEP_TIMEOUT * 2)
            voice_errs = spike.errors[n_err_before:]
            ok = (got7 is not None and got7.get("type") == "session.updated"
                  and done7 is not None and not voice_errs)
            verdicts["VOICE_HOT_APPLY"] = (
                "SUPPORTED_MECHANICAL" if ok else
                ("REJECTED" if voice_errs else "UNDETERMINED"))
            evidence["steps"]["voice_hot_apply"] = {
                "ack": (got7 or {}).get("type"),
                "echo_voice": (echo7 or {}).get("voice"),
                "response_done": done7 is not None,
                "elapsed_ms": round((time.monotonic() - t7) * 1000),
                "error": voice_errs[-1] if voice_errs else None,
            }

    except Exception as e:  # noqa: BLE001
        evidence["probe_error"] = repr(e)
        spike.log("probe_error", error=repr(e))
    finally:
        try:
            if spike.ws is not None and not spike.ws.closed:
                await spike.ws.close()
        except Exception:  # noqa: BLE001
            pass
        if spike.session is not None:
            await spike.session.close()

    evidence["verdicts"] = verdicts
    evidence["sessions_used"] = sessions_used
    evidence["total_s"] = round(time.monotonic() - t_start, 1)
    evidence["event_log"] = spike.ev
    evidence["event_log_truncated"] = spike.ev_truncated
    evidence["session_updated_payloads"] = spike.session_updated
    evidence["errors"] = spike.errors
    evidence["response_events"] = spike.response_events
    evidence["audio_delta_bytes"] = spike.audio_delta_bytes
    evidence["transcripts_all"] = spike.transcripts[-40:]
    with open(spike.out_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2, default=str)
    print("SPIKE_VERDICTS %s" % json.dumps(verdicts, ensure_ascii=False))
    print("SPIKE_DONE sessions_used=%d out=%s" % (sessions_used, spike.out_path))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret-file", default=DEFAULT_SECRET_FILE)
    ap.add_argument("--out", default="/tmp/spike_out.json")
    ap.add_argument("--url", default="",
                    help="override the upstream URL (mock dry-run only)")
    args = ap.parse_args()
    if args.url:
        _orig = Spike.__init__

        def patched(self, secret_path, out_path):
            _orig(self, secret_path, out_path)
            self.url = args.url
        Spike.__init__ = patched
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())