"""把状态/协议消息画到界面上."""

from typing import TYPE_CHECKING, Optional

from src.constants.constants import DeviceState
from src.logging import get_logger

if TYPE_CHECKING:
    from src.ui.shared.viewport import ViewPort

logger = get_logger()


class UiPresenter:
    """写界面：对话、音乐、状态、表情、按钮等."""

    STATE_TEXT_MAP = {
        DeviceState.IDLE: "待命",
        DeviceState.LISTENING: "聆听中...",
        DeviceState.SPEAKING: "说话中...",
    }

    MUSIC_STATE_TEXT = {
        "playing": "正在播放: {song}",
        "paused": "已暂停: {song}",
        "stopped": "已停止: {song}",
        "completed": "播放完成: {song}",
    }

    def __init__(self, viewport: Optional["ViewPort"] = None) -> None:
        self._vp = viewport

    def bind(self, viewport: Optional["ViewPort"]) -> None:
        self._vp = viewport

    @property
    def viewport(self) -> Optional["ViewPort"]:
        return self._vp

    def set_chat_text(self, text: str) -> None:
        if self._vp:
            self._vp.set_chat_text(text)

    def set_music_line(self, text: str) -> None:
        if self._vp:
            self._vp.set_music_line(text)

    def set_emotion(self, emotion: str) -> None:
        if self._vp:
            self._vp.set_emotion(emotion)

    def set_status(self, status: str, connected: bool = True) -> None:
        if self._vp:
            self._vp.set_status(status, connected)

    def set_button_text(self, text: str) -> None:
        if not self._vp:
            return
        setter = getattr(self._vp, "set_button_text", None)
        if callable(setter):
            setter(text)

    def set_auto_mode(self, auto_mode: bool) -> None:
        if self._vp:
            self._vp.set_auto_mode(auto_mode)

    def show_device_state(self, state) -> None:
        if status_text := self.STATE_TEXT_MAP.get(state):
            self.set_emotion("neutral")
            self.set_status(status_text, connected=True)

    def show_network_error(self, message: str = None) -> None:
        # R3-2C: 透传连接失败原因（老师 401/409 的中文提示），不再固定"未连接"
        self.set_status(message or "未连接", connected=False)

    def show_music_state(self, data) -> None:
        try:
            from src.mcp.tools.music.events import MusicStateData

            if not isinstance(data, MusicStateData):
                logger.warning(f"收到非法的音乐状态数据: {type(data)}")
                return

            template = self.MUSIC_STATE_TEXT.get(data.state)
            if not template:
                return
            text = template.format(song=data.song)
            self.set_music_line(text)
            logger.debug(f"UI 更新音乐状态: {data.state}")
        except Exception as e:
            logger.error(f"处理音乐状态变化失败: {e}", exc_info=True)

    def show_music_lyrics(self, data) -> None:
        try:
            from src.mcp.tools.music.events import MusicLyricsData

            if not isinstance(data, MusicLyricsData):
                logger.warning(f"收到非法的歌词数据: {type(data)}")
                return
            self.set_music_line(data.text)
        except Exception as e:
            logger.error(f"处理歌词更新失败: {e}", exc_info=True)

    # ---- CLIENT-UI-1 transcript (shared by every frontend) ----------------

    def _transcript_store(self):
        store = getattr(self, "_transcript_store_obj", None)
        if store is None:
            from src.ui.shared.transcript import TranscriptStore

            store = TranscriptStore()
            self._transcript_store_obj = store
        return store

    def set_transcript(self, items) -> None:
        """Hand the conversation bubbles to the viewport (optional per frontend)."""
        viewport = self._vp
        fn = getattr(viewport, "set_transcript", None) if viewport else None
        if callable(fn):
            fn(items)

    def mark_transcript_interrupted(self, role: str = "assistant") -> None:
        """Local abort fallback (the gateway also sends an interrupted notice)."""
        items = self._transcript_store().mark_interrupted(role)
        if items is not None:
            self.set_transcript(items)

    def reset_transcript(self) -> None:
        items = self._transcript_store().reset()
        if items is not None:
            self.set_transcript(items)

    def show_protocol_message(self, message) -> None:
        if not isinstance(message, dict):
            return
        msg_type = message.get("type")
        if msg_type == "hello":
            # Defensive fallback only: the live protocol layer intercepts `hello` before it
            # reaches plugin dispatch, so the real reconnect reset lives in
            # `src/plugins/ui.py::on_protocol_connected` (called by the plugin manager).
            self.reset_transcript()
        if msg_type in ("tts", "stt"):
            if text := message.get("text"):
                self.set_chat_text(text)
        elif msg_type == "transcript":
            items = self._transcript_store().apply(message)
            if items is not None:
                self.set_transcript(items)
        elif msg_type == "llm":
            if emotion := message.get("emotion"):
                self.set_emotion(emotion)
