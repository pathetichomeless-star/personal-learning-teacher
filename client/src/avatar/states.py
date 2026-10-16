"""数字人状态机（V0.6）：idle/listening/thinking/speaking/interrupted。

口型同步采用协议包络方案（V06_AUDIO_SYNC_BLOCKER_ANALYSIS 选项 b）：
tts start/stop 事件驱动包络动画；真实逐样本 RMS 探针为冻结链路例外，
须产品负责人批准后方可实施（详见 V06_AUDIO_SYNC_BLOCKER_ANALYSIS）。
"""
STATES = ("idle", "listening", "thinking", "speaking", "interrupted")


class AvatarStateMachine:
    def __init__(self):
        self.state = "idle"
        self.generation = 0
        self.speaking = False

    def to_listening(self): self.state = "listening"
    def to_thinking(self): self.state = "thinking"; self.generation += 1
    def to_speaking(self): self.state = "speaking"; self.speaking = True
    def to_interrupted(self):
        """打断：口型立即归零（调用方同时静音播放）。"""
        self.state = "interrupted"; self.speaking = False
    def to_idle(self): self.state = "idle"; self.speaking = False
    def new_generation(self):
        """新响应代际：递增并复位（防新旧轮次串动画）。"""
        self.generation += 1
        self.speaking = False
        return self.generation
