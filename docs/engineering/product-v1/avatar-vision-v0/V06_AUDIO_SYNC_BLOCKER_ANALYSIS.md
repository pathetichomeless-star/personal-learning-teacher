# V06_AUDIO_SYNC_BLOCKER_ANALYSIS — 数字人嘴部与真实播放同步：阻塞项分析

- 基线：branch `avatar-vision-v06-mac-native` @ `f518778`（已实测 `git rev-parse` 确认）
- 编制：v06-audio-sync（只读审计；本文为唯一写入物）
- 上游依据：`AVATAR_AUDIO_SYNC_DESIGN.md`（V0.5 设计，播放链定桩与两候选观测点均出自该文）
- 原则：诚实汇报阻塞，不做伪装——若真实播放观测无法在不改冻结链的前提下获得，必须明说。

---

## FROZEN_BOUNDARY（冻结边界核实）

- `client/src/audio_codecs/` 全部 7 文件（含 `audio_codec.py`）在冻结边界内：
  - `MAC_CLIENT_AUDIT.md:31` 明确列为冻结清单："全部 7 文件：audio_buffer.py、audio_codec.py、opus_codec.py、audio_converter.py、music_decoder.py、rtl_client_telemetry.py、stream_manager.py"。
  - `VISION_CLIENT_DESIGN.md:81` 同样把 `client/src/audio_codecs/` 全部列为冻结。
- 冻结基线 tag `XIAOZHI-VOICE-V1-HUMAN-ACCEPTED` 不得改变（`V05_SECURITY_QA_TEST_DESIGN.md:3`）。
- 回归闸门先例：V05-R10/E9 要求冻结文件零字节 diff，任何触碰需 QA/PO 裁定豁免清单（`V05_SECURITY_QA_TEST_DESIGN.md:71-72,96`）。

## OPTION_A_RMS（播线程 RMS 探针）——需要修改冻结链 ⇒ 阻塞

- 位置：`client/src/audio_codecs/audio_codec.py:245-320` `_output_callback`（PortAudio 实时播放回调），探针拟落在 `:311-313` AEC `feed_far(outdata)` 同点旁，对最终送设备 PCM 每 20ms 求 RMS。
- 代码核实：`_output_callback` 内当前无任何嘴部/RMS 发布逻辑；`outdata` 写出后仅有 AEC far 消费（audio_codec.py:312-313）。加探针 = 在 `audio_codec.py` 中新增代码行。
- **结论：audio_codec.py 属冻结边界（MAC_CLIENT_AUDIT.md:31），任何新增（哪怕是"6 行加法式内层改动"）都构成冻结链修改 ⇒ V0.6 未经 PO 批准的冻结链豁免即 BLOCKED。**
- 技术面备注（供 PO 决策参考，非豁免理由）：该改动技术上是安全的——数微秒级内存运算、无 I/O、无锁属性发布、独立内层 try/except 隔离（详见 AVATAR_AUDIO_SYNC_DESIGN.md SAFE_TAP_RECOMMENDATION/FAULT_ISOLATION）；但"技术安全"不能替代流程豁免。
- 附带说明：既有 `add_audio_listener` 机制（audio_codec.py:451-460）只覆盖**输入**回调（`_input_callback:234-240` 通知监听器），**输出回调无监听器通道**——不存在"用现有扩展点绕过冻结"的后门。

## OPTION_B_ENVELOPE（协议包络）——零音频文件改动 ⇒ 可行

完全不动 `client/src/audio_codecs/` 与 `plugins/audio.py`；头像组件自身（新文件）+ 事件订阅即可落地。

**事件源（全部既有，file:line 已核实）**

| 事件 | 来源 | 头像动作 |
|---|---|---|
| `{"type":"tts","state":"start"}` | gateway `app/protocol.py:46-47` `build_tts`；发射点 `app/turns.py:1161` | `mouthGen++` + `hardClose()` 复位 → 启动模拟包络（8-14Hz 伪随机瓣动 + 起音斜坡）；进入 SPEAKING |
| `{"type":"tts","state":"stop"}` | 同上（`turns.py:1161` `_stop_tts` 路径） | `hardClose()` 硬归零 + 停包络 |
| 本地打断（唤醒词） | `client/src/plugins/wake_word.py:103-106` → 本地清队 + 状态迁移 | 订阅状态迁移即 `hardClose()`（≤50ms） |
| 本地打断（手动 abort） | `client/src/bootstrap/session.py:258-290` → 状态迁移 | 同上 |
| `DEVICE_STATE_CHANGED` | `client/src/core/event_bus.py:23`；StateManager 发布（state_manager.py:92） | SPEAKING→包络开；LISTENING/IDLE→`hardClose()` + idle 姿态；断线覆盖（session.py:70-71,73-80 → IDLE） |
| `transcript`（user final / assistant interrupted） | gateway `app/protocol.py:52-69`；客户端消费 `ui_presenter.py:144-147` | 新 `turn` id → `mouthGen++` 代际复位；`interrupted:true` 仅作旁证 |

**接线点**：头像仅订阅 `Events.INCOMING_JSON`（session.py:50 已把全部 JSON 广播上总线）与 `Events.DEVICE_STATE_CHANGED`（event_bus.py:23）。客户端 `tts` 消费路径核实：session.py:94-99 分发 → `_handle_tts_start:106-119`（置 SPEAKING）/ `_handle_tts_stop:128-162`（清队+回 LISTENING/IDLE）——头像作为**并行订阅方**，不触碰这些既有消费者。

**代际绑定**：`mouthGen` 在 ①`tts start` ②`DEVICE_STATE_CHANGED→SPEAKING` ③ user `transcript` 新 `turn` 三点递增并 `hardClose()`；线上无 resp_id（`build_tts` 只有 type/state/session_id，protocol.py:47）不阻塞，事件序已足够。

**打断归零**：三重保证中第 2 重（清队后 zero-fill→RMS=0 自然闭嘴）依赖探针，包络模式下不可用；剩余两重有效——本地状态迁移 `hardClose()`（≤50ms，wake_word.py:103-106 / session.py:258-290）+ 远端 `tts stop`（turns.py 毫秒级发射 + RTT）。

## HONEST_LOSS（包络方案诚实损失清单，不粉饰）

1. **无音量对应**：嘴部开合幅度是确定性伪随机包络，与真实音素能量/响度零相关。大声喊与轻声细语嘴动一样。
2. **无停顿对应**：句中停顿、字间间隙不会闭嘴（除非引入复杂启发式，而启发式仍是猜测）；真实语音节奏丢失。
3. **起播延迟错位**：`tts start` 是**协议事件**（gateway 开始 pacing 时发出），音频经 FIFO 缓冲后才是扬声器实际出声；FIFO 可积压（上限 10s，audio_codec.py:28 `_TTS_FIFO_MAX_S`），正常时积压小（数百 ms 级），但包络起点≠发声起点，头部可能有轻微"先动嘴后出声"。
4. **打断感知靠状态而非音频事实**：本地打断靠状态迁移（快但依赖各路径都正确迁移状态）；无法像 RMS 那样"听到扬声器没声了就闭嘴"的物理兜底（≤20ms zero-fill 那一重保证消失）。
5. **音乐同屏失真**：TTS 停止而音乐继续播放时，包络归零（嘴闭）但扬声器仍在出声——包络只跟 TTS 事件走，不感知音乐混音（`_pull_mixed`，audio_codec.py:372-397）。

## THINKING_STATE（thinking 状态标记，客户端协议现状）

- **协议无专用 thinking 事件**。`DeviceState` 仅 IDLE/LISTENING/SPEAKING（constants.py:25-32），无 THINKING。
- gateway 实际下发的 JSON 全集：`hello`（protocol.py:31）、`tts start/stop`（:46）、`transcript`（:52）。`ui_presenter.py:148` 的 `msg_type == "llm"`（emotion）与 `:141` 的 `"stt"` 处理在当前 gateway **无发射点**（gateway 全库 grep 无 `"llm"`/`emotion` 发送），属上游 xiaozhi 协议遗留死路径，**不能作为 thinking 事件源**。
- 可派生的 thinking 窗口：**user `transcript` `final:true`（带新 `turn` id，protocol.py:52-69）→ `tts start`** 之间视为"思考中"（头像显示思考微表情/耳朵动效）。MANUAL 模式下客户端自知 `stop_listening`（session.py:218-221）亦可作起点。窗口内嘴保持闭合。

## V06_RECOMMENDATION

1. **V0.6 现在实施 Option B（协议包络）+ 5 状态机**：IDLE / LISTENING / THINKING（派生：user final → tts start）/ SPEAKING（包络动嘴）/ INTERRUPTED（hardClose 瞬态）。全部为新增文件+事件订阅，冻结链零触碰，与 V0.5 prototype 契约（`avatar_v0_logic.js` createMouth/hardClose/newTurn）直接对接。
2. **Option A（RMS 探针）立案为 PO 门控的冻结链豁免请求**：写明改动点（audio_codec.py:311-313 旁 6 行内层加法）、技术安全论证（见 AVATAR_AUDIO_SYNC_DESIGN.md）、回归影响面（需重跑 R-1f 遥测与音频回归基座）；PO 批准后方可进 V1。
3. **手工验收项（不可自动化，诚实声明）**：主观"嘴-音同步感"真人验收一轮——对照冻结基线听感无退化、包络嘴型自然度可接受、打断归零 ≤50ms 感知。包络的 HONEST_LOSS 各项须在验收标准中明示为"预期内近似"，不算缺陷。
4. 保留**自动降级路径**：若未来探针获批，包络实现可平滑切换到 RMS 源（订阅接口不变，仅换电平来源）。

## VERDICT

**feasible-with-(b)**。V0.6 可在零冻结链改动下交付"嘴随播放"的包络近似版（开头/结尾/打断/代际全部准确，中段细粒度为模拟）；真实逐样本 RMS 同步被冻结边界阻塞，作为 PO 门控豁免项挂账 V1。

---

### 3 行总结

1. Option A（audio_codec.py `_output_callback` RMS 探针）落在冻结边界内（MAC_CLIENT_AUDIT.md:31 列明 `client/src/audio_codecs/` 全 7 文件），V0.6 未经 PO 豁免即 BLOCKED，且输出回调无既有监听器扩展点可借道。
2. Option B 零音频改动可行：订阅 `tts start/stop`（protocol.py:46 / turns.py:1161）+ `DEVICE_STATE_CHANGED`（event_bus.py:23）+ `transcript.turn`（protocol.py:52-69），驱动 8-14Hz 伪随机包络 + mouthGen 代际复位 + hardClose 归零；thinking 由 user-final→tts-start 窗口派生（协议无专用事件，`llm`/`stt` 为无发射点的遗留死路径）。
3. 诚实损失：包络无音量/停顿对应、起播有 FIFO 级错位、打断失去 zero-fill 物理兜底、音乐不感知；V0.6 建议实施 B + 5 状态机，A 立案 PO 门控豁免，主观嘴型同步列为手工验收项。
