# AVATAR_ENGINE_RECOMMENDATION

date=2026-10-09T00:00:00Z (UTC, branch admin-visual-v2 @ e51d9a5)
scope=V0 数字教师形象原型: idle/listening/speaking 三态、眨眼、口型跟随**实际播放音频**、barge-in 立即闭嘴、对音频通路零影响

## SOURCES (官方)

- three-vrm: https://github.com/pixiv/three-vrm (README 标注 LICENSE: MIT; npm package.json "license": "MIT"; pixiv Inc. 维护)
- three-vrm expressions/lipsync API: https://pixiv.github.io/three-vrm/packages/three-vrm-core/documents/guides/use_expressions.html (expressionManager.setValue)
- LiteAvatar: https://github.com/HumanAIGC/lite-avatar (代码 LICENSE = MIT, Copyright (c) 2025 HumanAIGC; 权重经 download_model.sh 从 ModelScope 拉取)
- LiteAvatarGallery: https://github.com/HumanAIGC/LiteAvatarGallery
- OpenAvatarChat: https://github.com/HumanAIGC-Engineering/OpenAvatarChat (Apache-2.0; handler 架构: LiteAvatar(2D)/LAM(3D)/MuseTalk(2D); 官方系统需求 CUDA GPU, 数字人推理可 CPU 30FPS)
- WebAudio AnalyserNode: https://developer.mozilla.org/en-US/docs/Web/API/AnalyserNode (浏览器原生, 被动旁听不改写音频)

## COMPARISON_TABLE

| 维度 | 1. three-vrm | 2. LiteAvatar | 3. OpenAvatarChat handler | 4. 2D canvas + WebAudio AnalyserNode |
|---|---|---|---|---|
| License | 引擎 MIT (pixiv) ✅ | 代码 MIT; **模型权重经 ModelScope 分发, 许可需逐项核对** ⚠️ | 框架 Apache-2.0; 各 handler 子模块/权重 (CosyVoice/SenseVoice/MuseTalk/LAM) 许可不一致, 逐项核对成本高 ⚠️ | 自研代码, 无外部 license ✅ |
| 权重/资源 | 无模型权重; 需一个 .vrm 资产 (官方示例含免费 VRM 样例; **模型资产自身 license 必须单独确认**, 引擎 MIT 不覆盖资产) | ~1.2GB: model_1.onnx 175MB + Paraformer ASR 839MB + lm 226MB | 全链路多模型 (ASR+LLM+TTS+avatar), 数 GB | 零 |
| 计算需求 | 浏览器 GPU 渲染, Mac 本地 HTML 无压力 | Python 服务 + ONNX; 官方称 CPU 可 30FPS, 但需常驻 Python 进程 | 官方面向 CUDA≥12.4 的 Windows/Linux; Mac 仅社区改 MPS 的 hack, 非官方支持 ❌ | 几乎为零 (每帧一次 RMS 计算) |
| 集成复杂度 | 中: npm/CDN 引 three.js + three-vrm, 渲染循环 + expressionManager | 高: Python 后端 + 视频流回传浏览器 (WebRTC/WS), 双进程架构 | 极高: 它是**完整对话系统**, 引入即带 ASR/LLM/TTS 全栈, 与既有 xiaozhi 链路重叠冲突 | 极低: 纯前端 ~百行代码, 单 HTML 即可 |
| Barge-in 延迟 | ≈0: 停播放 → AnalyserNode RMS→0 → 口型同帧闭合 | 需冲刷视频帧队列 + 传输链路, 数十至数百 ms | 同左, 且涉及整条 session 管线 | ≈0 |
| 音频通路影响 | 无 (analyser 被动旁听) | 无直接改写, 但同机额外重计算 | 无直接改写, 但整条管线同机重计算 | 无 |
| V1 升级路径 | ★ 天然路径: 真 3D 口型/表情/实时互动 | 已是成品方案, 但绑定其管线 | 已是成品方案, 但架构重 | 需换渲染层 (canvas → three-vrm), 但音频信号接口可完全复用 |

## RECOMMENDATION

**V0 选方案 4: 简单 2D 音频驱动形象 (canvas/CSS + WebAudio AnalyserNode)。**

理由 (按决策标准逐条):
1. **V0 fitness 最高**: 零依赖、零模型、单 HTML 本地原型即可跑; 先用 mock 音频 (任意 wav/mp3) 验证三态机与口型驱动, 再接真实播放流, 半天内可出 demo。
2. **Barge-in 延迟 ≈0**: 口型直接由播放元素经 MediaElementSource → AnalyserNode 的实时 RMS 驱动; interrupt 时暂停音频源, 振幅同帧归零, 嘴立即闭合——无队列、无冲刷。
3. **音频通路零影响**: AnalyserNode 是被动旁听节点, 不改写音频图输出; V0 的硬性红线 (不碰 xiaozhi 音频链路) 天然满足。
4. **License 安全**: 全部自研代码, 无第三方 license 风险; 本轮无模型下载。
5. **计算成本最低**: 每帧一次振幅采样, Mac 上无感。
6. 唯一短板是升级路径, 由下节方案补齐: 保持「音频振幅 → 口型参数」接口不变, 渲染层从 canvas 换成 three-vrm, 升级成本可控。

实现要点 (V0):
- `AudioContext.createMediaElementSource(audioEl)` → `AnalyserNode` (fftSize 256) → 每帧 `getByteTimeDomainData` 求 RMS → 映射嘴部开合 (canvas 绘制的教师头像, 嘴高 = f(RMS), 加平滑 lerp 防抖)。
- 眨眼: 定时器随机 2–5s 触发, CSS/canvas 闭眼 120ms, 与音频无关。
- 状态机: idle (呼吸微动) / listening (头微偏+耳朵高亮) / speaking (口型驱动), 由现有会话状态直接驱动, 不新增后端。
- barge-in: 复用现有 interrupt 信号 → `audioEl.pause()` 即可, 口型自动闭合, 无需额外代码路径。

## V1_UPGRADE_PATH

方案 4 → three-vrm (V1: 真口型/表情/实时互动):
1. **信号层不变**: 继续用 AnalyserNode 的振幅/频谱作为主驱动信号; V0 的 `amplitude → mouth` 接口原样映射为 `expressionManager.setValue('aa', amplitude)` (three-vrm 标准表情), 立即得到比 canvas 更真实的 VRM 口型。
2. **渐进增强**: 加入 `ih/oh/ee/ou` 按频谱质心粗分元音 → 视觉上已接近真 lip-sync; 再进一步可接入 LiteAvatar 同款思路的 viseme 时间戳 (TTS 若能提供 phoneme 时间戳则升级为逐音素驱动)。
3. **渲染层替换**: canvas face 模块与 three-vrm 模块做成同接口 (in: amplitude, state; out: render), V0/V1 可一键切换, 三态机与 barge-in 逻辑零改动。
4. 若 V1 需要**照片级 2D 形象**, 再评估 LiteAvatar (先解决 ModelScope 权重 license) 或 OpenAvatarChat 的 LiteAvatar handler (先接受 Python 后端架构)——二者作为"成品引擎"引入属于架构级变更, 不应作为 V0 起点资产: 引擎 MIT (pixiv/three-vrm)。风险: VRM 模型资产自身许可五花八门 (VRoid Hub 模型多限非商用), **选模型时必须逐个核对 license**, 优先用 VRoid Studio 自制或明确允许商用的样例。
- b) 选 LiteAvatar: 代码 MIT 清晰, 但 1.2GB 权重经 ModelScope 分发, Paraformer 等模型许可未在本轮核实 → 引入前必须逐项核对; 且需常驻 Python 服务, 违背"轻量本地原型"目标。
- c) 选 OpenAvatarChat: 框架 Apache-2.0, 但各 handler 子模块/权重许可不一 (MuseTalk/CosyVoice/LAM 需逐个核), 官方不支持 Mac (仅社区 MPS hack), 且其 ASR/LLM/TTS 全栈与 xiaozhi 既有链路重叠, 有架构冲突风险。**在许可逐项核实前, 对 V0 一律视为 DO-NOT-USE。**
- d) 通用风险: 任何"音频→模型→视频帧"管线 (LiteAvatar/OAC) 都引入帧队列, barge-in 必须冲刷队列, 延迟与卡顿风险 inherent; 方案 4/three-vrm 无此问题。

## NON_GOALS

- 不替换 Tina: 本方案只做 admin-visual-v2 的 V0 数字教师形象, 不触碰既有 Tina 形象与其链路。
- 不引入第二套 TTS: 口型驱动只旁听**实际播放音频**, 不生成、不转码、不重复合成任何音频。
- 不做 GUI 替代: 仅在现有 admin 页面内嵌 avatar 视图, 不重构现有前端架构。
- 本轮不下载任何模型权重, 不改动任何业务代码 (本文件为唯一产出)。
