# AVATAR_AUDIO_SYNC_DESIGN — 数字人嘴部与 Mac 客户端真实播放音频的同步设计

- 基线：branch `avatar-vision-v0` @ HEAD（仓库 <project-root>）
- 编制：v05-avatar-sync（只读审计 + 设计；本文为唯一写入物）
- 原则：**零音频路径改动、零耦合、故障即旁路**——头像任何异常都不得影响 TTS 播放
- 关联：`prototypes/avatar_v0_logic.js`（createMouth/hardClose/newTurn 契约）、`VISION_CLIENT_DESIGN.md`

---

## PLAYBACK_PATH_AUDIT（client/ 播放路径审计，file:line）

**下行音频链（网络 → 扬声器）**

1. 二进制 opus 帧接收：`client/src/core/protocol_manager.py:82`（`on_incoming_audio` 接线）→ `:236` `_on_incoming_audio` → 内部队列（`:25` `_INCOMING_AUDIO_QUEUE_SIZE=64`）→ `:160` 经 `Events.INCOMING_AUDIO` 直连分发（不走 EventBus）。
2. 播放入口：`client/src/plugins/audio.py:168-176` `on_incoming_audio(data)` → `:174` `await self.codec.write_audio(data)`。
3. 解码：`client/src/audio_codecs/audio_codec.py:473-513` `write_audio()` —— TOC 解析 `:482` → opus 解码为 float32 PCM `:500`（`opus_codec.py:150-176`，libopus `decode_float`）→ push 进 `_tts_fifo` `:510`。FIFO 容量上限 10s（`audio_codec.py:28` `_TTS_FIFO_MAX_S=10.0`）。
4. **真实播放线程（PortAudio 实时回调）**：`audio_codec.py:245-320` `_output_callback` —— 每 20ms 从 TTS/音乐 FIFO 混音拉块 `:292`/`:372-397`（`_pull_mixed`，TTS 在场时音乐闪避 0.35 `:397`）→ 重采样/上混 `:295` → 写 `outdata` 送扬声器 `:305-309` → AEC far 参考 `:311-313`（`self._aec.feed_far(outdata)`，**对最终播放 PCM 的既有只读消费先例**）。
5. 回调内既有安全规约：异常捕获后 zero-fill、不做 I/O（`audio_codec.py:315-320`），日志经 `_defer_callback_log` 延迟到事件循环线程 `:322-337`。

**客户端已收到的播放状态事件（JSON，与音频路径无关）**

- 下行 `tts` 事件：gateway `app/protocol.py:46-50` `build_tts(state, session_id)` → `{"type":"tts","state":"start|stop","session_id":…}`。发射点：`app/turns.py:1181`（`_tts_start`，含 `tts_active` 去重 `:1166-1170`）与 `:1205`（`_stop_tts`）。
- 客户端两处独立消费（均为订阅方，零音频耦合）：
  - `client/src/bootstrap/session.py:94-99` → `_handle_tts_start` `:106-119`（置 `DeviceState.SPEAKING`）、`_handle_tts_stop` `:128-162`（`clear_audio_queue()` `:158` + 状态回 LISTENING/IDLE）。
  - `client/src/plugins/audio.py:141-150`（音乐暂停/恢复）。
- 状态广播：`Events.DEVICE_STATE_CHANGED`（`client/src/core/event_bus.py:23`）由 StateManager 发布，头像可直接订阅。

**generation 生命周期（客户端视角）**

- 网线上**没有** resp_id/gen_id：`build_tts`（protocol.py:46-50）只有 type/state/session_id；gateway 内部的 gen/resp_id（turns.py:1171、diag.py:506-524）不透传。
- 客户端可感知的代际边界 = ①`tts start`（新响应开始）；②`tts stop`（响应播完/被打断后终局）；③`transcript` 事件的 `turn` id 与 `interrupted` 标志（`gateway/app/protocol.py:52-69`，NEW-1 转写轮次：用户 final 开启新轮、assistant `interrupted:true` 标记该轮音频被取消）；④`DeviceState` 迁移（SPEAKING/LISTENING/IDLE）。

**barge-in 路径（两条，客户端行为不同）**

- 本地打断（零往返）：唤醒词检测 → `client/src/plugins/wake_word.py:103-106`：`is_speaking()` → `abort_speaking()` **并立即** `codec.clear_audio_queue()`（`audio_codec.py:530-540` 清空 TTS FIFO）；手动按钮路径 `session.py:258-290` `abort_speaking()` 发送 abort 并切状态（**不本地清队**，依赖回程）。
- 远端 VAD 打断：gateway `_on_abort`（turns.py:591-611）：作废 generation `:596` → 取消 pacer `:597` → 丢弃队列 `:598` → `_stop_tts("abort")` `:600`（毫秒级，`:610` 日志佐证）→ 客户端收到 `tts stop` → `session.py:158` 清队。另 `listen start` 亦触发 `_stop_tts`（turns.py:580）。
- 清队后下一帧输出回调必然走 zero-fill 分支（audio_codec.py:300-307）→ 扬声器实际输出静音。

---

## SAFE_TAP_RECOMMENDATION（安全观测点）

**主选：输出回调内 `outdata` RMS 探针（播线程事实播放电平）**

- 位置：`audio_codec.py:311-313` `feed_far(outdata)` 同点旁，对最终 `outdata`（TTS+音乐混音、重采样后、真正送设备的 PCM）每回调一次算 RMS（约 20ms 一块）。
- 发布方式：写两个内存属性 —— `_mouth_rms`（float）与 `_mouth_gen`（int 代际号）。Python GIL 下属性赋值近似原子，**无锁、无队列、无回调进入头像**；头像 UI 线程按自身帧率（30fps QTimer）轮询读取。
- 理由：
  1. **精确同步**：测的就是扬声器此刻播出的信号；欠载 zero-fill（`:305`）自然使嘴闭合，永不"空转嘴"。
  2. **零延迟影响**：20ms float32 RMS ≈ 数微秒，远低于回调预算；完全复制 `feed_far` 的既有模式（先例 :311-313 证明可行且已验收）。
  3. **零耦合**：头像拿不到音频引用、音频代码不知道头像存在；探针异常被独立 try/except 吞掉（见 FAULT_ISOLATION）。
  4. 遵守 A.12 规约：回调内无 I/O、无日志；RMS 写属性即返回。

**备选：协议包络（不动音频文件一行）**

- 仅订阅 `Events.INCOMING_JSON`（tts start/stop）与 `Events.DEVICE_STATE_CHANGED`，用确定性开合包络（如 8-14Hz 伪随机瓣动 + 起止斜坡）驱动嘴部。粒度粗、无音量对应，但**对 `client/src/audio_codecs/` 与 `plugins/audio.py` 零改动**，可在主选被冻结评审否决时独立落地；也可作为主选探针失效时的自动降级（探针故障闩 → 切包络）。

**否决项**：`write_audio` 解码点探针（audio_codec.py:500-510）——解码时刻 ≠ 播放时刻（FIFO 可积压至 10s，:28），会"抢拍"；且位于 asyncio 线程，语义不如播线程点干净。

---

## GENERATION_BINDING（代际绑定）

- 头像侧维护单调递增 `mouthGen`（int）。**递增点**（即 envelope 复位点）：
  1. `tts start` JSON 到达（session.py:96-97 路径）；
  2. `DeviceState → SPEAKING`（event_bus.py:23 广播）；
  3. `transcript` 收到用户轮 `final:true` 且带新 `turn` id（protocol.py:52-69，NEW-1）。
- 每次递增同步执行 `mouth.hardClose()`（prototype 契约 `avatar_v0_logic.js:52`）+ 平滑状态清零 —— 对应 prototype `newTurn(turnId)` 的 `mouthReset`（`avatar_v0_logic.js:57-61`），**杜绝跨轮残影**（上一轮尾音电平不得污染新轮首帧）。
- 播放线程探针侧同步携带 `_mouth_gen`：`tts stop`/状态迁移时由事件循环线程原子递增；头像只消费 `gen == mouthGen` 的样本，旧代样本直接丢弃。
- 线上无 resp_id 不阻塞 V0.5：以事件序（tts start/stop + turn id）绑定已足够；未来增强为 gateway 在 `build_tts`（protocol.py:46）加 `resp_id` 附加字段（加法式、向后兼容），客户端可选消费。

## BARGE_IN（打断归零，感知延迟 ≤50ms）

嘴部归零的三重保证，按触发时序：

1. **本地即时**（覆盖往返窗口）：`DEVICE_STATE_CHANGED → LISTENING/IDLE` 头像订阅即 `hardClose()`——唤醒词路径（wake_word.py:103-106，清队+切状态同轮完成）与手动 abort（session.py:258-290）均在本地毫秒级触发，不等网线。此为 ≤50ms 感知延迟的主保证。
2. **音频事实兜底**：任一路径 `clear_audio_queue()`（audio_codec.py:530-540）后，输出回调下一块即 zero-fill（:300-307）→ RMS=0 → 嘴部自然闭合，延迟 ≤ 一个回调块（20ms）。
3. **协议终局**：远端 `tts stop`（turns.py:600 毫秒级发射 + RTT）→ `session.py:158` 清队 + 头像 `hardClose()`。

三者幂等：`hardClose()` 与 prototype `createMouth` 的"打断/空闲立即闭合，无残留"（avatar_v0_logic.js:35-55）一致；`transcript` assistant `interrupted:true`（protocol.py:58,67）作为该轮被取消的旁证，仅用于日志/动效，不参与归零时序。

## RECONNECT_IDLE（断线/空闲）

- 头像订阅 `DEVICE_STATE_CHANGED`：IDLE → 回 idle 姿态（嘴闭合、眨眼保持）。断线自动覆盖：`AUDIO_CHANNEL_CLOSED` → IDLE（session.py:70-71）；`NETWORK_ERROR` → IDLE（session.py:73-80）。
- 看门狗：头像轮询侧若 >500ms 未收到新 RMS（探针停摆/流未启动），电平按 200ms 时间常数衰减到 0 —— 防止"冻结在张嘴帧"。
- 重连后新会话首个 `tts start` 走 GENERATION_BINDING 递增，无残留状态。

## FAULT_ISOLATION（故障隔离）

- **音频侧探针**：RMS 计算与属性写入包在**独立内层 try/except**（不得复用 `:315-320` 的外层，以免探针异常改变 zero-fill 语义）：异常 → 置 `_mouth_probe_ok=False` 并永久发布 0 电平，随后探针自身短路。音频主路径在该 except 之后**无任何新代码**，行为与今天逐比特一致。
- **头像侧**：全部渲染在 QML Canvas 组件 + Python 轮询器内；每帧 `try/except`，连续 3 次异常 → 头像进入禁用态（定格/隐藏 + 状态条提示），轮询器停止。头像代码永不 import 音频模块、永不持有 codec 引用（仅读发布属性，经一个 10 行的只读 accessor）。
- 线程边界：音频侧只有"写两个属性"一个动作（播线程）；其余一切（轮询、平滑、渲染、看门狗）都在 UI 线程。音频线程到头像线程**无回调、无锁、无队列**——异常不可能跨线程传播。

## PREVIEW_EQUIVALENT（V0.5 预览 vs 真实客户端）

**V0.5 浏览器预览实现**（`prototypes/avatar_v0.html` + `avatar_v0_logic.js`，已具备骨架）：

- 用 WebAudio `AudioContext.createMediaElementSource(<audio>)` → `AnalyserNode.getFloatTimeDomainData` 求 RMS —— 与主选探针**同构**：都是"对真实播放信号取 RMS → createMouth 平滑（smooth 0.35 / gain 2.2，avatar_v0_logic.js:40-41）→ hardClose 打断清零 → newTurn 代际复位"。预览因此验证的是同一套嘴部契约，只是 tap 点不同。
- 预览同时实现：tts start/stop 事件模拟、barge-in 按钮 → hardClose、断线模拟 → idle、异常注入 → 冻结禁用（验证 FAULT_ISOLATION 行为）。

**等待真实客户端（V1）**：`_output_callback` RMS 探针落点（audio_codec.py:311-313 旁）、`_mouth_rms/_mouth_gen` 发布属性、QML Canvas 组件与轮询器、`transcript.turn` 代际消费。以上均为加法式改动，落地顺序：先备选包络（可只加订阅）→ 后主选探针（单文件 6 行内层改动）。

## VERDICT

可行且低成本。真实播放电平的最优观测点是输出回调 `outdata` 的 RMS 探针（audio_codec.py:311-313 `feed_far` 同点，先例成熟），以无锁属性发布、UI 线程轮询消费；协议包络（tts start/stop + DEVICE_STATE_CHANGED）作为零音频耦合的备选与降级。代际绑定靠 tts start/stop + transcript.turn 序（线上暂无 resp_id 不阻塞）；打断归零由本地状态迁移（≤50ms）+ 清队后 zero-fill（≤20ms）+ tts stop 三重幂等保证；断线经既有 IDLE 迁移归 idle；故障面被"单写属性 + 双侧 try/except 闩"完全隔离。零音频路径改动成立。

---

### 5 行总结

1. 播放链已定桩：opus→`write_audio`(audio_codec.py:473)→TTS FIFO→播线程 `_output_callback`(:245) 写 `outdata`，AEC `feed_far`(:313) 是最终 PCM 只读消费的既有先例。
2. 主选 tap = 输出回调 `outdata` RMS 探针（播线程事实电平，数微秒/20ms，无锁属性发布，UI 30fps 轮询）；备选 = tts start/stop + 状态事件驱动的包络（零音频文件改动，兼作降级）。
3. 代际绑定：`mouthGen` 在 tts start / SPEAKING / transcript 新 turn（protocol.py:52-69 `turn`+`interrupted`）递增并 hardClose，旧代样本丢弃；resp_id 缺失不阻塞，未来加法式补齐。
4. 打断三重保证：本地状态迁移 hardClose（≤50ms）→ 清队后 zero-fill 自然闭嘴（≤20ms）→ 远端 tts stop 终局；断线走既有 IDLE 迁移 + 500ms 看门狗。
5. 故障隔离：探针独立内层 try/except 闩（音频路径逐比特不变），头像侧冻结禁用；V0.5 预览用 WebAudio AnalyserNode 同构验证嘴部契约，探针落点留给真实客户端 V1。
