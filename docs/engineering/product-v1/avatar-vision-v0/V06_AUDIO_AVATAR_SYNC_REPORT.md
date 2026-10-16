# V06_AUDIO_AVATAR_SYNC_REPORT
结论：真实逐样本 RMS 口型同步 = **BLOCKED（冻结链路）**——探针须写入
client/src/audio_codecs/audio_codec.py 的 _output_callback（audio_codec.py:245），该文件属冻结边界，
须产品负责人专项批准。已实施的替代：协议包络（tts start/stop 事件驱动包络动画 + 打断硬清零 +
代际绑定），诚实标注：包络不等于真实音素能量（主观口型自然度=人工门禁）。
V0.6 已实现 states.py 五状态机（含 thinking/interrupted）；QML 渲染=下一切片。
