# -*- coding: utf-8 -*-
"""Text / Mock voice dialogue state machine (CLASSROOM V2 · Agent C · Phase 2).

Implements the classroom voice **events contract** and a deterministic Mock
dialogue engine so the whole UI can be driven and tested **without any real
model call**.

Hard boundaries
---------------
* **No real paid model requests.** Mode ``real-online`` is a *stub* that refuses
  to connect unless a separate, explicitly-authorized adapter is injected.  By
  default every path stays in ``local-demo`` / ``local-mock``.
* **`Mock PASS ≠ real voice`.** The mode is always surfaced verbatim.
* Error codes are mapped to **Chinese reasons** (never a bare ``1006/401/409``).
* Mic denied ⇒ the session falls back to **text-only** and says so.
"""

from __future__ import annotations

MODES = ("local-demo", "local-mock", "real-online")

# 事件 → 状态机允许的当前状态
EVENTS = ("user_speech", "partial_transcript", "final_transcript",
          "teacher_speaking", "barge_in", "error")

# 常见实时语音错误码 → 中文原因（诚实、可操作）
ERROR_REASONS = {
    1006: "连接被意外中断（网络或服务端关闭）",
    1000: "连接正常关闭",
    401: "鉴权失败（凭据无效或已过期）",
    409: "会话冲突（同一会话已有连接）",
    429: "请求过于频繁，请稍后再试",
    1008: "服务端拒绝该请求（策略限制）",
    1011: "服务端内部错误",
}


# 内部（非数字）错误码 → 中文原因
STRING_REASONS = {
    "real_not_authorized": "真实在线模式未授权（未注入已授权的语音适配器）",
    "no_mic": "未授予麦克风权限，可改用文字学习",
}


def error_reason(code) -> str:
    """Map a code to a Chinese reason; unknown codes get an honest fallback."""
    if isinstance(code, str) and code in STRING_REASONS:
        return STRING_REASONS[code]
    try:
        i = int(code)
    except (TypeError, ValueError):
        return "未知错误（%r）" % (code,)
    return ERROR_REASONS.get(i, "未分类错误（错误码 %d）" % i)


class VoiceMockSession:
    """Deterministic dialogue state machine for the classroom.

    States: ``idle`` → ``listening`` → (``thinking``) → ``speaking`` → ``idle``.
    ``barge_in`` from ``speaking`` returns to ``listening`` (interruption).
    """

    def __init__(self, *, mode: str = "local-mock", mic_granted: bool = True,
                 authorized_real_adapter=None):
        if mode not in MODES:
            raise ValueError("未知模式 %r（%s）" % (mode, "|".join(MODES)))
        self.mode = mode
        self.mic_granted = bool(mic_granted)
        self._real = authorized_real_adapter
        self.state = "idle"
        self.transcript = ""            # 已确认文本
        self.partial = ""               # 未确认文本
        self.events: list = []          # 事件日志（结构化）
        self.last_error = ""

    # ---- capability / honesty ---------------------------------------------
    @property
    def text_only(self) -> bool:
        return not self.mic_granted

    def mode_label(self) -> str:
        return {"local-demo": "本地演示", "local-mock": "本地模拟(Mock)",
                "real-online": "真实在线"}[self.mode]

    def real_connected(self) -> bool:
        """True only when a real adapter was injected AND explicitly authorized."""
        return self.mode == "real-online" and self._real is not None

    # ---- emit --------------------------------------------------------------
    def _emit(self, kind: str, **payload) -> dict:
        ev = {"type": kind, **payload}
        self.events.append(ev)
        return ev

    def start_listening(self) -> dict:
        if self.text_only:
            self.state = "idle"
            return self._emit("error", code="no_mic",
                              reason="未授予麦克风权限，可改用文字学习")
        self.state = "listening"
        self.partial = ""
        return self._emit("user_speech", state=self.state)

    def partial_transcript(self, text: str) -> dict:
        self.partial = str(text or "")
        return self._emit("partial_transcript", text=self.partial, state=self.state)

    def final_transcript(self, text: str) -> dict:
        self.transcript = str(text or "")
        self.partial = ""
        self.state = "thinking"
        return self._emit("final_transcript", text=self.transcript, state=self.state)

    def teacher_speaking(self, text: str) -> dict:
        self.state = "speaking"
        return self._emit("teacher_speaking", text=str(text or ""), state=self.state)

    def finish_speaking(self) -> dict:
        self.state = "idle"
        return self._emit("teacher_done", state=self.state)

    def barge_in(self) -> dict:
        """User interrupts the teacher → back to listening (or text-only idle)."""
        if self.text_only:
            self.state = "idle"
        else:
            self.state = "listening"
        return self._emit("barge_in", state=self.state)

    def error(self, code) -> dict:
        self.last_error = error_reason(code)
        self.state = "idle"
        return self._emit("error", code=code, reason=self.last_error)

    # ---- Mock dialogue -----------------------------------------------------
    def mock_reply(self, user_text: str, *, canned: "dict | None" = None) -> str:
        """Deterministic canned reply (NOT a model call).

        ``canned`` maps user text → teacher text; missing → a generic, honest
        template that never pretends to have understood.
        """
        key = str(user_text or "").strip()
        if canned and key in canned:
            return str(canned[key])
        return "（Mock 回显）我听到你说：“%s”。请继续练习。" % key

    def roundtrip(self, user_text: str, *, canned: "dict | None" = None) -> dict:
        """One deterministic user→teacher turn.  Never hits the network."""
        if self.mode == "real-online" and self._real is None:
            self.error("real_not_authorized")
            return {"ok": False, "reason": self.last_error, "mode": self.mode_label()}
        self.final_transcript(user_text)
        reply = self.mock_reply(user_text, canned=canned)
        self.teacher_speaking(reply)
        self.finish_speaking()
        return {"ok": True, "reply": reply, "mode": self.mode_label(),
                "events": [e["type"] for e in self.events[-3:]]}

    def snapshot(self) -> dict:
        return {"mode": self.mode_label(), "raw_mode": self.mode, "state": self.state,
                "text_only": self.text_only, "real_connected": self.real_connected(),
                "transcript": self.transcript, "partial": self.partial,
                "last_error": self.last_error, "event_count": len(self.events)}
