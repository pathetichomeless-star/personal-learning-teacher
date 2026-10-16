# -*- coding: utf-8 -*-
"""Avatar adapter + safe static degradation (CLASSROOM V2 · Agent D · Phase 2).

A **thin, new** adapter object that a UI binds to.  It deliberately does *not*
touch the protected, uncommitted avatar files (``client/src/avatar/**``,
``client/src/ui/gui/**``); it only models the small contract the classroom needs.

Hard boundaries
---------------
* **No fake lip-sync.** Mouth opening is derived from a *real* audio level fed in
  by the caller.  When no real level is available the mouth stays closed and
  ``audio_driven`` is ``False`` — the adapter never animates a mouth from nothing.
* **Degrade, don't crash.** When the avatar backend is unavailable the adapter
  flips to ``degraded`` and reports a static card; every other classroom feature
  (course / text / voice mock) keeps working.
"""

from __future__ import annotations

STATES = ("listening", "thinking", "speaking", "waiting", "error")


class AvatarAdapter:
    """State + audio-level model for the digital-human area."""

    def __init__(self, *, available: bool = True, engine: str = "none"):
        self._available = bool(available)
        self.engine = str(engine)
        self._state = "waiting"
        self._audio_level = 0.0
        self._audio_driven = False
        self.degrade_reason = "" if available else "avatar_backend_unavailable"

    # ---- availability ------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._available

    @property
    def degraded(self) -> bool:
        """True when the UI must fall back to a static card."""
        return not self._available

    def set_available(self, available: bool, *, reason: str = "") -> None:
        self._available = bool(available)
        if self._available:
            self.degrade_reason = ""
        else:
            self.degrade_reason = reason or "avatar_backend_unavailable"
            # 降级时清空"音频驱动"字样，避免任何"正在对口型"的假象
            self._audio_level = 0.0
            self._audio_driven = False

    # ---- state -------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> str:
        if state not in STATES:
            raise ValueError("未知头像状态 %r（闭枚举 %s）" % (state, "|".join(STATES)))
        self._state = state
        return self._state

    # ---- audio level (real signal only) -----------------------------------
    def set_audio_level(self, level: float) -> float:
        """Feed a REAL audio level in ``[0, 1]``.  Enables ``audio_driven``.

        Passing ``None`` means "no real signal" → the adapter goes back to
        not-audio-driven (mouth closed), never guessing a shape.
        """
        if level is None:
            self._audio_level = 0.0
            self._audio_driven = False
            return 0.0
        try:
            v = float(level)
        except (TypeError, ValueError):
            raise ValueError("audio level 必须是 0..1 的数值或 None")
        v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
        self._audio_level = v
        self._audio_driven = True
        return v

    @property
    def audio_level(self) -> float:
        return self._audio_level

    @property
    def audio_driven(self) -> bool:
        """True only when a real audio level has been supplied."""
        return self._audio_driven

    def mouth_open(self) -> float:
        """Mouth aperture for the *real* audio level.

        With no real signal (or when degraded) returns ``0.0`` — i.e. a closed,
        static mouth.  **Never** returns a fabricated animated value.
        """
        if self.degraded or not self._audio_driven:
            return 0.0
        # 仅在 speaking 状态下才开口；其它状态闭口（真实信号驱动）
        if self._state != "speaking":
            return 0.0
        return round(self._audio_level, 4)

    # ---- view model for QML -----------------------------------------------
    def snapshot(self) -> dict:
        return {
            "available": self._available,
            "degraded": self.degraded,
            "degrade_reason": self.degrade_reason,
            "engine": self.engine,
            "state": self._state,
            "audio_level": self._audio_level,
            "audio_driven": self._audio_driven,
            "mouth_open": self.mouth_open(),
            # 诚实文案：降级时明确说明"静态展示，不影响学习"
            "caption": ("静态展示（数字人不可用，不影响课程与语音）"
                        if self.degraded else ""),
        }
