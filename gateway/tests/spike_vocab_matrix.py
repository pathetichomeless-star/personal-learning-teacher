"""VOCAB matrix — single real-Qwen session driver (bounded: ONE session).

Replays the generated turn table (pre-audit instructions for the baseline
subset, then the full matrix with the post-fix instructions) using
conversation.item.create + response.create at safe boundaries, and captures
response.audio_transcript.done for every turn.

Runs inside the lab container (holds the runtime secret). No audio uplink; no
credentials are ever printed.

Usage:
  python /tmp/spike_vocab_matrix.py --turns /tmp/vocab_turns.json \
      --out /tmp/vocab_matrix_out.json
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
UPDATE_TIMEOUT = 8.0
TURN_TIMEOUT = 35.0
TOTAL_BUDGET_S = 900.0


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


class Driver:
    def __init__(self, secret_path):
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
        self.cur_instructions = None
        self._transcript = []          # per-turn collector
        self._errors = []

    # ---- plumbing ----------------------------------------------------------

    async def send(self, obj):
        if self.closed or self.ws is None or self.ws.closed:
            return False
        try:
            await self.ws.send_str(json.dumps(obj))
            return True
        except Exception:  # noqa: BLE001
            self.closed = True
            return False

    async def recv_until(self, predicate, timeout):
        if self.closed:
            return None
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            try:
                msg = await asyncio.wait_for(
                    self.ws.receive(), max(0.1, timeout - (time.monotonic() - t0)))
            except asyncio.TimeoutError:
                return None
            except Exception:  # noqa: BLE001
                self.closed = True
                return None
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type in (aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.ERROR):
                    self.closed = True
                    return None
                continue
            try:
                obj = json.loads(msg.data)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(obj, dict):
                continue
            etype = obj.get("type")
            if etype == "error":
                self._errors.append((obj.get("error") or {}).get("message", "")[:200])
            elif etype in ("response.audio_transcript.delta",
                           "response.output_audio_transcript.delta"):
                self._transcript.append((False, obj.get("delta") or ""))
            elif etype in ("response.audio_transcript.done",
                           "response.output_audio_transcript.done"):
                self._transcript.append((True, obj.get("transcript") or ""))
            if predicate(obj):
                return obj
        return None

    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(
            self.url, headers={"Authorization": "Bearer " + self.api_key},
            heartbeat=20, max_msg_size=0)
        created = await self.recv_until(
            lambda o: o.get("type") == "session.created", CONNECT_TIMEOUT)
        return created is not None

    async def set_instructions(self, text):
        if text == self.cur_instructions:
            return True
        await self.send({"type": "session.update",
                         "session": {"instructions": text}})
        ack = await self.recv_until(
            lambda o: o.get("type") in ("session.updated", "error"),
            UPDATE_TIMEOUT)
        if ack is not None and ack.get("type") == "session.updated":
            self.cur_instructions = text
            return True
        return False

    async def run_turn(self, question):
        self._transcript = []
        self._errors = []
        t0 = time.monotonic()
        await self.send({"type": "conversation.item.create",
                         "item": {"type": "message", "role": "user",
                                  "content": [{"type": "input_text",
                                               "text": question}]}})
        await self.send({"type": "response.create"})
        done = await self.recv_until(
            lambda o: o.get("type") == "response.done", TURN_TIMEOUT)
        final = "".join(t for is_done, t in self._transcript if is_done)
        if not final:
            final = "".join(t for _, t in self._transcript)
        return {"transcript": final,
                "done": done is not None,
                "status": ((done or {}).get("response") or {}).get("status"),
                "errors": list(self._errors),
                "elapsed_ms": round((time.monotonic() - t0) * 1000)}

    async def close(self):
        try:
            if self.ws is not None and not self.ws.closed:
                await self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        if self.session is not None:
            await self.session.close()


def contains_any(text, tokens):
    low = text.lower()
    return [t for t in tokens if t.lower() in low]


async def amain(args):
    with open(args.turns, encoding="utf-8") as f:
        turns = json.load(f)["turns"]
    drv = Driver(args.secret_file)
    evidence = {"probe": "spike_vocab_matrix", "model": drv.model,
                "voice": drv.voice, "turns": [], "sessions_used": 0}
    t_start = time.monotonic()
    ok_connect = False
    try:
        ok_connect = await drv.connect()
        evidence["sessions_used"] = 1 if ok_connect else 0
        if not ok_connect:
            raise RuntimeError("connect failed")
        for t in turns:
            if time.monotonic() - t_start > TOTAL_BUDGET_S:
                evidence["budget_exhausted_at"] = t["id"]
                break
            ins_ok = await drv.set_instructions(t["instruction"])
            res = await drv.run_turn(t["question"])
            hits = contains_any(res["transcript"], t["accepted"])
            rec = dict(t)
            rec.pop("instruction", None)
            rec.update({"instruction_applied": ins_ok,
                        "transcript": res["transcript"],
                        "done": res["done"], "status": res["status"],
                        "errors": res["errors"],
                        "elapsed_ms": res["elapsed_ms"],
                        "contains_expected": hits,
                        "pass": bool(hits) and res["done"]})
            evidence["turns"].append(rec)
            print("TURN %-4s %-10s %-3s %-28s -> %s" % (
                rec["id"], rec["phase"], "PASS" if rec["pass"] else "FAIL",
                rec["question"][:26], rec["transcript"][:90].replace("\n", " ")),
                flush=True)
            if drv.closed:
                evidence["connection_closed_at"] = t["id"]
                break
    except Exception as e:  # noqa: BLE001
        evidence["probe_error"] = repr(e)
    finally:
        await drv.close()
    evidence["total_s"] = round(time.monotonic() - t_start, 1)
    n = len(evidence["turns"])
    npass = sum(1 for t in evidence["turns"] if t["pass"])
    evidence["summary"] = {"turns": n, "pass": npass, "fail": n - npass}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=1)
    print("MATRIX_SUMMARY %s" % json.dumps(evidence["summary"]))
    print("MATRIX_DONE out=%s sessions_used=%d"
          % (args.out, evidence["sessions_used"]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", default="/tmp/vocab_turns.json")
    ap.add_argument("--out", default="/tmp/vocab_matrix_out.json")
    ap.add_argument("--secret-file", default=DEFAULT_SECRET_FILE)
    args = ap.parse_args()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())