#!/usr/bin/env python3
"""RED-F adversarial mock Qwen-Realtime upstream.

Extends `gateway/tests/mock_qwen_server.py` with deliberately hostile event
streams used to attack the realtime / session state machine.  This file is
READ-ONLY-adjacent: it imports nothing from product source and never mutates it.

Usage (standalone):
    python adv_mock_qwen_server.py --port 9277 [--scenario <name>]

The scenario may also be selected per-connection from the URL path
(`/mock/<scenario>`) or query (`?scenario=<scenario>`), so a single server can
serve many scenarios.  Binds 127.0.0.1 only.

Scenarios:
    normal, close_mid, close_after_created, close_immediate, storm,
    bargein, late_final, late_done_after_new, overlap_responses,
    cancel_all_phases, cancel_before_audio, cancel_after_last_delta,
    malformed_stream, done_unknown_rid, duplicate_done,
    audio_done_after_done, out_of_order, wrong_types, null_ids,
    huge_payload, binary_frame, partial_json, started_storm
"""

import argparse
import asyncio
import base64
import json
import logging

from aiohttp import web, WSMsgType

log = logging.getLogger("mock.adv")

SCENARIOS = (
    "normal", "close_mid", "close_after_created", "close_immediate", "storm",
    "bargein", "interrupt_then_close", "late_final", "late_done_after_new",
    "late_final_midstream", "precreated_final",
    "overlap_responses",
    "cancel_all_phases", "cancel_before_audio", "cancel_after_last_delta",
    "malformed_stream", "done_unknown_rid", "duplicate_done",
    "audio_done_after_done", "out_of_order", "wrong_types", "null_ids",
    "huge_payload", "binary_frame", "partial_json", "started_storm",
    "fragmented", "rapid_turns",
)

BENIGN_CANCEL_ERROR = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "code": "response_cancel_not_active",
        "message": "no active response to cancel",
        "param": None,
    },
}


def _pcm(total_bytes):
    return bytes((i * 7 + 11) & 0xFF for i in range(total_bytes))


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _split(total, step=960):
    return [total[i:i + step] for i in range(0, len(total), step)]


async def _send(ws, obj):
    await ws.send_str(json.dumps(obj))


class AdvMockServer:
    def __init__(self, default_scenario="normal"):
        self.default_scenario = default_scenario
        self.conn_count = 0
        self._resp_seq = 0

    def _next_resp(self):
        self._resp_seq += 1
        return "resp_%d" % self._resp_seq

    async def handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.conn_count += 1
        my_conn = self.conn_count
        scenario = (request.match_info.get("scenario")
                    or request.query.get("scenario")
                    or self.default_scenario)
        log.info("adv-mock conn#%d scenario=%s", my_conn, scenario)
        cancel_seen = asyncio.Event()
        tasks = []
        try:
            await _send(ws, {"type": "session.created",
                             "session": {"id": "adv_sess_%d" % my_conn}})
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    obj = json.loads(msg.data)
                except Exception:  # noqa: BLE001
                    continue
                etype = obj.get("type")
                if etype == "session.update":
                    await _send(ws, {"type": "session.updated",
                                     "session": {"id": "adv_sess_%d" % my_conn}})
                    tasks.append(asyncio.create_task(
                        self._run(ws, my_conn, scenario, cancel_seen)))
                elif etype == "response.cancel":
                    await _send(ws, BENIGN_CANCEL_ERROR)
                    cancel_seen.set()
                elif etype == "session.finish":
                    break
        except Exception as e:  # noqa: BLE001
            log.warning("adv-mock handler error: %s", e)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        return ws

    # ---- scenario dispatch ------------------------------------------------

    async def _run(self, ws, my_conn, scenario, cancel_seen):
        try:
            await asyncio.sleep(0.15)
            fn = getattr(self, "_sc_" + scenario, None)
            if fn is None:
                fn = self._sc_normal
            await fn(ws, my_conn, cancel_seen)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("adv-mock scenario %s error: %s", scenario, e)

    # ---- building blocks --------------------------------------------------

    async def _speech(self, ws, item="item_1", stop=True):
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": item})
        if stop:
            await asyncio.sleep(0.02)
            await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                             "audio_end_ms": 200, "item_id": item})

    async def _stream_response(self, ws, rid, n_chunks, gap=0.02, item="item_1",
                               done=True, audio_done=True):
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        for chunk in _split(_pcm(n_chunks * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "item_id": item,
                             "delta": _b64(chunk)})
            if gap:
                await asyncio.sleep(gap)
        if audio_done:
            await _send(ws, {"type": "response.audio.done", "response_id": rid})
        if done:
            await _send(ws, {"type": "response.done",
                             "response": {"id": rid, "status": "completed"}})

    async def _tx_delta(self, ws, rid, delta, item="item_1"):
        await _send(ws, {"type": "response.audio_transcript.delta",
                         "response_id": rid, "item_id": item, "delta": delta})

    async def _tx_done(self, ws, rid, transcript, item="item_1"):
        await _send(ws, {"type": "response.audio_transcript.done",
                         "response_id": rid, "item_id": item,
                         "transcript": transcript})

    # ---- scenarios --------------------------------------------------------

    async def _sc_normal(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await self._stream_response(ws, rid, 40)

    async def _sc_close_immediate(self, ws, my_conn, cancel_seen):
        log.info("adv-mock: close immediately after session.updated")
        await ws.close()

    async def _sc_storm(self, ws, my_conn, cancel_seen):
        # Drop the very next connection instantly (reconnect-budget attack).
        await ws.close()

    async def _sc_close_after_created(self, ws, my_conn, cancel_seen):
        await self._speech(ws)
        rid = self._next_resp()
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        await asyncio.sleep(0.03)
        await ws.close()

    async def _sc_close_mid(self, ws, my_conn, cancel_seen):
        await self._speech(ws)
        rid = self._next_resp()
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        chunks = _split(_pcm(60 * 960))
        for i, chunk in enumerate(chunks):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
            if i == len(chunks) // 2:
                log.info("adv-mock: hard close mid-response")
                await ws.close()
                return
            await asyncio.sleep(0.02)

    async def _sc_bargein(self, ws, my_conn, cancel_seen):
        """resp1 plays -> speech_started triggers product barge-in -> resp2."""
        rid1 = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid1, "status": "in_progress"}})
        for chunk in _split(_pcm(40 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        # Barge-in trigger (user speaks while resp1 plays)
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_2"})
        # Late resp1 audio AFTER the barge-in (must never resume)
        for chunk in _split(_pcm(10 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        try:
            await asyncio.wait_for(cancel_seen.wait(), 3.0)
        except asyncio.TimeoutError:
            log.warning("adv-mock bargein: no cancel seen")
        # resp1's cancelled terminal (prompt, as real Qwen does)
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid1, "status": "cancelled"}})
        rid2 = self._next_resp()
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 200, "item_id": "item_2"})
        await self._stream_response(ws, rid2, 40)

    async def _sc_interrupt_then_close(self, ws, my_conn, cancel_seen):
        """resp1 plays -> barge-in cancel -> upstream hard-closes mid-stream."""
        rid1 = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid1, "status": "in_progress"}})
        for chunk in _split(_pcm(40 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_2"})
        try:
            await asyncio.wait_for(cancel_seen.wait(), 3.0)
        except asyncio.TimeoutError:
            pass
        log.info("adv-mock: hard close right after the barge-in cancel")
        await ws.close()

    async def _sc_late_final_midstream(self, ws, my_conn, cancel_seen):
        """r1 completes; r2 starts and is STREAMING (transcript deltas); then a
        LATE r1 transcript.done arrives (gateway re-stamps it with r2's turn).

        This is the R-F-1 ordering that reaches the client store while the new
        turn is still STREAMING (not yet FINAL)."""
        rid1 = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid1, "status": "in_progress"}})
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        await self._tx_delta(ws, rid1, "R1 partial ")
        await self._tx_done(ws, rid1, "R1 FINAL ANSWER")
        await _send(ws, {"type": "response.audio.done", "response_id": rid1})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid1, "status": "completed"}})
        # ---- r2 begins and streams its transcript (turn 2 STREAMING) ----
        rid2 = self._next_resp()
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid2, "status": "in_progress"}})
        await self._tx_delta(ws, rid2, "Welcome ")
        await asyncio.sleep(0.03)
        # ---- LATE r1 transcript.done, mis-stamped by the gateway with turn 2 ----
        await self._tx_done(ws, rid1, "STALE-R1-TEXT")
        await asyncio.sleep(0.03)
        # ---- r2 continues (real turn-2 text) ----
        await self._tx_delta(ws, rid2, "to class")
        await self._tx_done(ws, rid2, "Welcome to class")
        for chunk in _split(_pcm(10 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid2, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        await _send(ws, {"type": "response.audio.done", "response_id": rid2})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid2, "status": "completed"}})

    async def _sc_precreated_final(self, ws, my_conn, cancel_seen):
        """A transcript.done arrives BEFORE any response.created (turn key 0)."""
        await self._tx_done(ws, "ghost_rid", "PRE-CREATED TEXT")
        await asyncio.sleep(0.03)
        rid = self._next_resp()
        await self._speech(ws)
        await self._stream_response(ws, rid, 20)
        await self._tx_delta(ws, rid, "real ")
        await self._tx_done(ws, rid, "real turn text")

    async def _sc_late_done_after_new(self, ws, my_conn, cancel_seen):
        """resp1 cancelled by barge-in; resp2 starts; resp1's cancelled done is
        delivered LATE (after resp2's created)."""
        rid1 = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid1, "status": "in_progress"}})
        for chunk in _split(_pcm(40 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_2"})
        try:
            await asyncio.wait_for(cancel_seen.wait(), 3.0)
        except asyncio.TimeoutError:
            pass
        rid2 = self._next_resp()
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 200, "item_id": "item_2"})
        await self._stream_response(ws, rid2, 40, done=False, audio_done=False)
        # LATE final for the cancelled resp1 (after resp2 is current)
        await _send(ws, {"type": "response.audio_transcript.done",
                         "response_id": rid1, "transcript": "late-final-text"})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid1, "status": "cancelled"}})
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid2, "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        await _send(ws, {"type": "response.audio.done", "response_id": rid2})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid2, "status": "completed"}})

    async def _sc_late_final(self, ws, my_conn, cancel_seen):
        """resp1 completes (done).  Then a LATE transcript final + audio delta for
        resp1 arrive AFTER the completion, while resp2 is already current."""
        rid1 = self._next_resp()
        await self._speech(ws)
        await self._stream_response(ws, rid1, 30)          # complete resp1
        await asyncio.sleep(0.05)
        rid2 = self._next_resp()
        await self._stream_response(ws, rid2, 30, done=False, audio_done=False)
        # LATE final + audio for the already-completed resp1
        await _send(ws, {"type": "response.audio_transcript.done",
                         "response_id": rid1, "transcript": "STALE-FINAL"})
        for chunk in _split(_pcm(5 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid1, "status": "completed"}})
        await _send(ws, {"type": "response.audio.done", "response_id": rid2})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid2, "status": "completed"}})

    async def _sc_overlap_responses(self, ws, my_conn, cancel_seen):
        """Second response.created while the first still streams."""
        rid1 = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid1, "status": "in_progress"}})
        for chunk in _split(_pcm(50 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        # Overlap: a second response begins while resp1 is still live
        rid2 = self._next_resp()
        await self._stream_response(ws, rid2, 40, done=False, audio_done=False)
        # More resp1 audio after the overlap (must not interleave/resume)
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid1, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid1, "status": "completed"}})
        await _send(ws, {"type": "response.audio.done", "response_id": rid2})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid2, "status": "completed"}})

    async def _sc_cancel_before_audio(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        await asyncio.sleep(0.05)
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "cancelled"}})

    async def _sc_cancel_after_last_delta(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "cancelled"}})

    async def _sc_cancel_all_phases(self, ws, my_conn, cancel_seen):
        await self._sc_cancel_before_audio(ws, my_conn, cancel_seen)

    async def _sc_done_unknown_rid(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        for chunk in _split(_pcm(30 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
            # response.done for a NEVER-created rid mid-stream
            if chunk is not None:
                await _send(ws, {"type": "response.done",
                                 "response": {"id": "ghost_rid",
                                              "status": "completed"}})
            await asyncio.sleep(0.02)
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})

    async def _sc_duplicate_done(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        for _ in range(3):
            await _send(ws, {"type": "response.done",
                             "response": {"id": rid, "status": "completed"}})

    async def _sc_audio_done_after_done(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})
        await asyncio.sleep(0.02)
        await _send(ws, {"type": "response.audio.done", "response_id": rid})

    async def _sc_out_of_order(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        # delta before created, done before audio.done, unknown type
        await _send(ws, {"type": "response.audio.delta", "response_id": rid,
                         "delta": _b64(_pcm(960))})
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "i"})
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})
        await _send(ws, {"type": "response.audio.done", "response_id": rid})

    async def _sc_malformed_stream(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        await _send(ws, {"type": "some.unknown.event", "x": 1})
        await _send(ws, {"type": "response.created"})           # no id at all
        await ws.send_str("this is not json {")                 # truncated JSON
        await _send(ws, {"type": "response.audio.delta", "response_id": rid,
                         "delta": "!!!!not-valid-base64!!!!"})
        await _send(ws, {"type": "response.audio.delta", "response_id": rid,
                         "delta": 12345})                       # wrong type
        await _send(ws, {"type": "response.audio.delta", "response_id": rid,
                         "delta": None})                        # null delta
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})

    async def _sc_wrong_types(self, ws, my_conn, cancel_seen):
        await _send(ws, {"type": "response.created", "response": [1, 2, 3]})
        await _send(ws, {"type": "response.audio.delta",
                         "response_id": {"nested": True},
                         "delta": _b64(_pcm(960))})
        await _send(ws, {"type": "response.done", "response": "not-a-dict"})
        await _send(ws, {"type": "input_audio_buffer.speech_started"})

    async def _sc_null_ids(self, ws, my_conn, cancel_seen):
        await _send(ws, {"type": "response.created", "response_id": None})
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": None, "delta": _b64(chunk)})
        await _send(ws, {"type": "response.done",
                         "response": {"id": None, "status": "completed"}})

    async def _sc_huge_payload(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        # ~6 MB single delta
        big = _pcm(6 * 1024 * 1024)
        await _send(ws, {"type": "response.audio.delta", "response_id": rid,
                         "delta": _b64(big)})
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})

    async def _sc_binary_frame(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        await ws.send_bytes(b"\x00\x01\x02not-json")
        for chunk in _split(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})

    async def _sc_partial_json(self, ws, my_conn, cancel_seen):
        await ws.send_str('{"type": "response.created", "response": {"id"')
        await _send(ws, {"type": "response.created"})

    async def _sc_started_storm(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        for chunk in _split(_pcm(30 * 960)):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(chunk)})
            await asyncio.sleep(0.01)
        # started-started / stopped-twice / stopped-without-started storm
        for _ in range(3):
            await _send(ws, {"type": "input_audio_buffer.speech_started",
                             "audio_start_ms": 0, "item_id": "i"})
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 1, "item_id": "i"})
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 2, "item_id": "i"})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})

    async def _sc_fragmented(self, ws, my_conn, cancel_seen):
        rid = self._next_resp()
        await self._speech(ws)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        total = _pcm(40 * 960)
        i, step = 0, 1
        while i < len(total):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "delta": _b64(total[i:i + step])})
            i += step
            step = (step % 13) + 1
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})

    async def _sc_rapid_turns(self, ws, my_conn, cancel_seen):
        await self._speech(ws)
        for _ in range(2):
            rid = self._next_resp()
            await self._stream_response(ws, rid, 25, gap=0.0)
            await asyncio.sleep(0.05)


def build_app(default_scenario="normal"):
    server = AdvMockServer(default_scenario)
    app = web.Application()
    app.router.add_get("/", server.handler)
    app.router.add_get("/api-ws/v1/realtime", server.handler)
    app.router.add_get("/mock/{scenario}", server.handler)
    return app, server


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9277)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--scenario", default="normal", choices=SCENARIOS)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app, _ = build_app(args.scenario)
    log.info("adv mock qwen ws on ws://%s:%d (default scenario=%s)",
             args.host, args.port, args.scenario)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
