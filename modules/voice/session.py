"""VOICE CHANNEL V1 (P2-B1) — the audio-transport lifecycle of one voice class.

Ownership: `modules/voice`.  Pure data + validation + one JSON file (atomic 600
writes, version-gated, locked); NO gateway/audio imports, no sockets, no Opus/VAD
and **no contact with the frozen Tina realtime link**.

Why a separate record from the teaching session?

* the **teaching record** (who taught whom, which model, which material, what was
  learned) is shared with the P2-A text classroom and stays owned by
  :class:`modules.teaching.store.TeachingSessionStore`;
* the **audio transport** has a different lifecycle — connecting / ready /
  streaming / interrupted / ended / error / timeout — and must be closed and
  reaped on its own, without rewriting the learning record.

A channel therefore holds only transport state: ``channel_id``,
``session_id`` (the teaching session it belongs to), ``teacher_id`` /
``student_id``, the adapter that carries the audio, the voice-configuration
snapshot, counters (frames / bytes — never audio bytes themselves) and the
lifecycle timestamps.  One student can hold at most one live channel: opening a
new one closes the previous channel explicitly (teacher switch), which is what
guarantees the previous teacher's voice/model/instructions are released rather
than leaking into the next class.
"""

from __future__ import annotations

import copy
import logging
import time
import uuid

from modules._jsonstore import (BaseJsonStore, ConfirmRequired,  # noqa: F401
                                PersistError, StoreUnavailable)

log = logging.getLogger("voice.session")

SCHEMA_VERSION = 1

# 音频传输状态机（与 modules.voice.capability.SESSION_STATES 一致）
STATUSES = ("connecting", "ready", "streaming", "interrupted", "ended",
            "error", "timeout")
OPEN_STATUSES = ("connecting", "ready", "streaming", "interrupted")

DEFAULT_IDLE_TIMEOUT = 90
MIN_IDLE_TIMEOUT, MAX_IDLE_TIMEOUT = 10, 1800
MAX_CHANNELS = 2000
MAX_ID_CHARS = 64
MAX_NAME_CHARS = 60
MAX_DETAIL_CHARS = 200

# 关闭原因（封闭集合，便于如实汇报「为什么被清理」）
CLOSE_REASONS = ("user_closed", "teacher_switch", "idle_timeout", "error",
                 "adapter_unavailable", "server_shutdown", "superseded")


class VoiceInvalid(ValueError):
    def __init__(self, errors):
        errors = list(errors)
        super().__init__("voice_invalid: %s" % "; ".join(errors[:6]))
        self.errors = errors


class ChannelNotFound(ValueError):
    """Unknown channel id."""


def _clean(value, what, cap, *, required=False):
    s = "" if value is None else str(value).strip()
    if required and not s:
        raise VoiceInvalid(["%s: 不能为空" % what])
    if len(s) > cap:
        raise VoiceInvalid(["%s: 过长（%d > %d）" % (what, len(s), cap)])
    if any(ord(c) < 32 for c in s) or "\x7f" in s:
        raise VoiceInvalid(["%s: 只能是单行文本" % what])
    return s


class VoiceChannelStore(BaseJsonStore):
    """One JSON file holding every voice channel (keyed by channel_id)."""

    SCHEMA_VERSION = SCHEMA_VERSION
    ROOT_KEYS = ("channels",)

    def _all(self):
        return self._data["channels"]

    # ---- helpers ---------------------------------------------------------

    def _require(self, channel_id):
        rec = self._all().get(str(channel_id or ""))
        if rec is None:
            raise ChannelNotFound("unknown voice channel")
        return rec

    # ---- open / read -----------------------------------------------------

    def open_channel(self, *, session_id, teacher_id, student_id, adapter_id,
                     adapter_mode="", adapter_is_test=False, teacher_name="",
                     voice=None, transcript_enabled=True,
                     idle_timeout=DEFAULT_IDLE_TIMEOUT, max_turn_seconds=120):
        with self._lock.exclusive():
            self.reload_if_changed()
            if not self.available:
                raise StoreUnavailable(self._reason or "unavailable")
            if len(self._all()) >= MAX_CHANNELS:
                raise VoiceInvalid(["语音通道数量已达上限（%d）" % MAX_CHANNELS])
            now = time.time()
            cid = "vch_" + uuid.uuid4().hex[:12]
            rec = {
                "channel_id": cid,
                "session_id": _clean(session_id, "session_id", MAX_ID_CHARS,
                                     required=True),
                "teacher_id": _clean(teacher_id, "teacher_id", MAX_ID_CHARS,
                                     required=True),
                "teacher_name": _clean(teacher_name, "teacher_name", MAX_NAME_CHARS),
                "student_id": _clean(student_id or "default", "student_id",
                                     MAX_ID_CHARS, required=True),
                "adapter_id": _clean(adapter_id, "adapter_id", MAX_ID_CHARS,
                                     required=True),
                "adapter_mode": _clean(adapter_mode, "adapter_mode", 24),
                "adapter_is_test": bool(adapter_is_test),
                "voice": _voice_snapshot(voice),
                "transcript_enabled": bool(transcript_enabled),
                "status": "connecting",
                "started_at": now,
                "ready_at": None,
                "last_activity_at": now,
                "ended_at": None,
                "close_reason": "",
                "error_code": "",
                "error_detail": "",
                "frames_in": 0,
                "frames_out": 0,
                "bytes_in": 0,
                "bytes_out": 0,
                "turns": 0,
                "idle_timeout": max(MIN_IDLE_TIMEOUT,
                                    min(int(idle_timeout or DEFAULT_IDLE_TIMEOUT),
                                        MAX_IDLE_TIMEOUT)),
                "max_turn_seconds": max(5, min(int(max_turn_seconds or 120), 600)),
                "interrupts": 0,
            }
            self._all()[cid] = rec
            self._persist()
            return copy.deepcopy(rec)

    def get_channel(self, channel_id):
        with self._lock:
            self.reload_if_changed()
            rec = self._all().get(str(channel_id or ""))
            return copy.deepcopy(rec) if rec else None

    def list_channels(self, *, teacher_id=None, student_id=None,
                      include_closed=False, limit=100):
        with self._lock:
            self.reload_if_changed()
            rows = []
            for rec in self._all().values():
                if teacher_id is not None and rec.get("teacher_id") != str(teacher_id):
                    continue
                if student_id is not None and rec.get("student_id") != str(student_id):
                    continue
                if not include_closed and rec.get("status") not in OPEN_STATUSES:
                    continue
                rows.append(copy.deepcopy(rec))
            rows.sort(key=lambda r: (-(r.get("started_at") or 0), r["channel_id"]))
            return rows[:max(1, int(limit))]

    def counts(self):
        rows = list(self._all().values())
        live = [r for r in rows if r.get("status") in OPEN_STATUSES]
        return {"total": len(rows), "live": len(live),
                "ended": len(rows) - len(live),
                "timed_out": len([r for r in rows
                                  if r.get("status") == "timeout"]),
                "errored": len([r for r in rows if r.get("status") == "error"])}

    # ---- lifecycle -------------------------------------------------------

    def mark_ready(self, channel_id):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._require(channel_id)
            if rec.get("status") in ("ended", "timeout", "error"):
                raise VoiceInvalid(["channel_status: 通道已关闭"])
            rec["status"] = "ready"
            rec["ready_at"] = rec.get("ready_at") or time.time()
            rec["last_activity_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)

    def record_activity(self, channel_id, *, frames_in=0, bytes_in=0,
                        frames_out=0, bytes_out=0, turns=0, error=None):
        """Heartbeat + counters for one exchange.  ``error`` records a failure."""
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._require(channel_id)
            if rec.get("status") in ("ended", "timeout"):
                raise VoiceInvalid(["channel_status: 通道已关闭"])
            if error:
                rec["status"] = "error"
                rec["error_code"] = str((error or {}).get("code") or "")[:MAX_DETAIL_CHARS]
                rec["error_detail"] = str((error or {}).get("detail") or "")[:MAX_DETAIL_CHARS]
                rec["ended_at"] = time.time()
                rec["close_reason"] = "error"
            else:
                if rec.get("status") != "streaming":
                    rec["status"] = "streaming"
                rec["error_code"] = ""
                rec["error_detail"] = ""
            rec["frames_in"] = int(rec.get("frames_in") or 0) + max(0, int(frames_in))
            rec["frames_out"] = int(rec.get("frames_out") or 0) + max(0, int(frames_out))
            rec["bytes_in"] = int(rec.get("bytes_in") or 0) + max(0, int(bytes_in))
            rec["bytes_out"] = int(rec.get("bytes_out") or 0) + max(0, int(bytes_out))
            rec["turns"] = int(rec.get("turns") or 0) + max(0, int(turns))
            rec["last_activity_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)

    def mark_interrupted(self, channel_id):
        """Barge-in attempt on a channel.  Never claims success by itself."""
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._require(channel_id)
            if rec.get("status") not in OPEN_STATUSES:
                raise VoiceInvalid(["channel_status: 通道已关闭"])
            rec["status"] = "interrupted"
            rec["interrupts"] = int(rec.get("interrupts") or 0) + 1
            rec["last_activity_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)

    def close_channel(self, channel_id, *, reason="user_closed", error=None):
        """Idempotent close.  Returns the stored record."""
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._require(channel_id)
            if rec.get("status") in ("ended", "timeout", "error"):
                return copy.deepcopy(rec)
            rec["status"] = "error" if error else "ended"
            rec["close_reason"] = (str(reason) if str(reason) in CLOSE_REASONS
                                   else "user_closed")
            if error:
                rec["close_reason"] = "error"
                rec["error_code"] = str((error or {}).get("code") or "")[:MAX_DETAIL_CHARS]
                rec["error_detail"] = str((error or {}).get("detail") or "")[:MAX_DETAIL_CHARS]
            rec["ended_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)

    def close_active_for_student(self, student_id, *, reason="teacher_switch",
                                 except_channel_id=""):
        """Close every live channel of one student (one live channel at a time).

        This is the resource-release step of a teacher switch: the previous
        teacher's audio session is closed before the new one opens, so its model,
        sound and instructions cannot leak into the next class.
        """
        closed = []
        with self._lock.exclusive():
            self.reload_if_changed()
            for rec in self._all().values():
                if rec.get("status") not in OPEN_STATUSES:
                    continue
                if rec.get("student_id") != str(student_id):
                    continue
                if except_channel_id and rec.get("channel_id") == except_channel_id:
                    continue
                rec["status"] = "ended"
                rec["close_reason"] = (str(reason) if str(reason) in CLOSE_REASONS
                                       else "teacher_switch")
                rec["ended_at"] = time.time()
                closed.append(copy.deepcopy(rec))
            if closed:
                self._persist()
        return closed

    def sweep(self, *, now=None):
        """Reap idle channels.  Deterministic: the caller may inject ``now``."""
        t = float(now if now is not None else time.time())
        reaped = []
        with self._lock.exclusive():
            self.reload_if_changed()
            for rec in self._all().values():
                if rec.get("status") not in OPEN_STATUSES:
                    continue
                idle = t - float(rec.get("last_activity_at") or rec.get("started_at") or t)
                if idle < float(rec.get("idle_timeout") or DEFAULT_IDLE_TIMEOUT):
                    continue
                rec["status"] = "timeout"
                rec["close_reason"] = "idle_timeout"
                rec["error_code"] = "idle_timeout"
                rec["error_detail"] = "超过 %.0f 秒没有任何音频活动，通道已自动关闭。" % idle
                rec["ended_at"] = t
                reaped.append(copy.deepcopy(rec))
            if reaped:
                self._persist()
        return reaped


def _voice_snapshot(voice):
    if voice is None:
        return None
    if not isinstance(voice, dict):
        raise VoiceInvalid(["voice: 需要对象"])
    out = {}
    for k, cap in (("adapter_id", MAX_ID_CHARS), ("voice_id", MAX_NAME_CHARS),
                   ("language", 16), ("accent", 16), ("mode", 16)):
        out[k] = _clean(voice.get(k), "voice.%s" % k, cap)
    speed = voice.get("speed")
    out["speed"] = None if speed is None else max(0.5, min(float(speed), 2.0))
    return out


def public_channel(rec):
    """Display-safe projection: transport state only, never audio bytes."""
    if rec is None:
        return None
    out = {k: copy.deepcopy(rec.get(k)) for k in (
        "channel_id", "session_id", "teacher_id", "teacher_name", "student_id",
        "adapter_id", "adapter_mode", "adapter_is_test", "voice",
        "transcript_enabled", "status", "started_at", "ready_at",
        "last_activity_at", "ended_at", "close_reason", "error_code",
        "error_detail", "frames_in", "frames_out", "bytes_in", "bytes_out",
        "turns", "idle_timeout", "max_turn_seconds", "interrupts")}
    out["is_open"] = rec.get("status") in OPEN_STATUSES
    return out
