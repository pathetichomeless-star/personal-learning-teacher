# R-1f — Agent B:客户端播放路径审计(Client Playout Auditor)

- 客户端:`<project-root>/py-xiaozhi`
- 版本:`9bfc807d368cccac71af8d9f7042ab6b5af92030`(tag v2.1.2)——只读审计,**未修改任何文件**
- 配置:`<user-home>/Library/Application Support/py-xiaozhi/config/config.json`
  - `AUDIO_DEVICES.opus_output_sample_rate = 24000`
  - `AUDIO_DEVICES.output_sample_rate = 48000`,`output_channels = 2`
  - `AUDIO_DEVICES.frame_duration = 20`
  - `AEC_OPTIONS.ENABLED = true`, `FRAME_DELAY = 3`, `MUSIC_PARALLEL = true`, `ENABLE_PREPROCESS = true`
- 运行环境:macOS(darwin arm64),Python 3.10 venv at `.venv`,`soxr` + `sounddevice` 可用

---

## PLAYOUT_PATH_MAP

### PcmFifo — `src/audio_codecs/audio_buffer.py`
| 项 | 位置 | 内容 |
|---|---|---|
| 类定义 | `audio_buffer.py:12-20` | float32 单声道 FIFO;docstring 明确"push 超容量丢最旧(记入 dropped)"、"pull 不足补零;完全无数据返回 None" |
| 容量参数 | `audio_buffer.py:22` | `__init__(max_samples: int)`,存为 `self._max`(`:26`)。**单位=样本数**,非秒 |
| `_size` | `audio_buffer.py:25`, 写于 `:42`/`:48`/`:70`,清零于 `:82` | 当前可读样本总数;`size` property 在 `:30-32`,**读时不取锁** |
| `dropped` 初始化 | `audio_buffer.py:28` | `self.dropped = 0` |
| `push` | `audio_buffer.py:34-52` | 先 reshape/dtype 归一(`:36-39`),持锁追加(`:40-42`) |
| **超容量丢最旧分支** | `audio_buffer.py:43-52` | `while self._size > self._max and self._chunks:`;从**头部**丢弃,`drop = min(remain, self._size - self._max)`,`self._offset += drop`(可能是**部分**丢块),`_offset >= len(head)` 才 popleft |
| **`dropped` 唯一写入点** | `audio_buffer.py:49` | `self.dropped += drop` —— **全仓无任何读取点**(见 UNOBSERVABLE 第 1 项) |
| `pull` | `audio_buffer.py:54-74` | `_size == 0` → 返回 `None`(`:57-58`);否则先 `np.zeros(n)`(`:59`),跨块填充,**不足补零**,返回值恒为长度 `n` |
| `clear` | `audio_buffer.py:76-83` | 清空并返回丢弃样本数 `count`;**UNITS = 样本数(24 kHz 域)**,非 ms |
| 锁 | `audio_buffer.py:27` | `threading.Lock`,`push`/`pull`/`clear` 各自 `with self._lock`;`size` property 无锁 |

### 解码路径
| 项 | 位置 | 内容 |
|---|---|---|
| `parse_opus_toc` | `opus_codec.py:26-73` | RFC 6716 TOC 解析:`config = (toc>>3)&0x1F`(`:41`),`code = toc&0x03`(`:42`);`config<12`→SILK / `<16`→Hybrid / else CELT(`:45-56`);`code==3` 时 `num_frames = opus_data[1] & 0x3F`(`:64`) |
| 帧时长键 | `opus_codec.py:67` | `duration_ms = frame_ms * num_frames` |
| 解码器创建 | `opus_codec.py:116` | `opuslib.Decoder(self.output_sample_rate, self.channels)` → **24 kHz / 1ch**(来自 `AudioConfig.OUTPUT_SAMPLE_RATE` / `CHANNELS`) |
| `decode` | `opus_codec.py:150-172` | `decode_float(opus_data, frame_size, decode_fec=False)`(`:169`),`np.frombuffer(...)`(`:172`)。**无 PLC、无 FEC、无丢包补偿** |
| `write_audio` | `audio_codec.py:373-403` | TOC 解析(`:382`),失败 `return`(**静默丢弃,`:383-384`**);首帧日志一次(`:386-393`);**`frame_size = int(OUTPUT_SAMPLE_RATE * duration_ms / 1000)`(`:395-397`)** → 20 ms = 480;`decode`(`:398`);`self._tts_fifo.push(...)`(`:400`);异常 → `logger.warning("音频写入失败")`(`:402-403`) |
| 解码 PCM 落点 | `audio_codec.py:400` | 直接进 `_tts_fifo`,**无中间缓冲、无背压、无深度检查** |

### 播放路径
| 项 | 位置 | 内容 |
|---|---|---|
| 输出流创建 | `stream_manager.py:64-72` | `sd.OutputStream(samplerate=device.output_sample_rate(48000), channels=2, dtype=float32, blocksize=output_frame_size, callback=output_callback, latency="low")` |
| blocksize 来源 | `audio_device.py:125-127` | `int(output_sample_rate * FRAME_DURATION/1000)` = `int(48000*0.02)` = **960 帧 = 20 ms** |
| **输出回调** | `audio_codec.py:192-239` | 节拍由 PortAudio 按 `blocksize`/`latency="low"` 驱动:**每 20 ms 一次,`frames=960`** |
| status 处理 | `audio_codec.py:207-212` | **限流到 2 s 一条**,`if status: ... logger.warning(f"输出流状态: {status}")`。`status` 是 `sd.CallbackFlags`;`output_underflow` / `output_overflow` 是其成员,但代码只做 `if status` 真值判断,**不区分 under/over,也不计数** |
| 重采样补块循环 | `audio_codec.py:217-221` | `while audio_converted is None: audio_data = self._pull_mixed(self._mix_chunk); if None: break; audio_converted = self.converter.convert_output(audio_data, frames)` |
| 兜底 drain | `audio_codec.py:223-224` | `drain_output_buffer(frames)` |
| 短帧处理 | `audio_codec.py:226-229` | 不足则 `outdata.fill(0.0)` + 部分拷贝 → **尾部补零,无淡入淡出** |
| 满帧写入 | `audio_codec.py:231` | `outdata[:] = audio_converted[:frames]` |
| AEC far 喂入 | `audio_codec.py:233-235` | `self._aec.feed_far(outdata)` —— **在播放路径内,但只读 outdata,不修改** |
| 异常兜底 | `audio_codec.py:237-239` | 异常 → `outdata.fill(0.0)` |
| `_mix_chunk` | `audio_codec.py:74` / 重建于 `:269` | `int(OUTPUT_SAMPLE_RATE * 0.02)` = **480 样本 = 20 ms(24 kHz 域)** |
| `_pull_mixed` | `audio_codec.py:272-297` | 各拉 480;两路皆空 → `None`(`:283-284`);TTS 在场 → 音乐乘 `_MUSIC_DUCK_GAIN=0.35`(`:21`,`:297`);`_DUCK_HOLD_CHUNKS=10`(`:22`) |
| **TTS FIFO 容量** | `audio_codec.py:26`, 构造于 `:68-70` 与 `:263-265` | `_TTS_FIFO_MAX_S = 10.0` → `int(24000*10.0)` = **240000 样本 = 10.0 s** |
| 音乐 FIFO 容量 | `audio_codec.py:27`, `:71-73` | `_MUSIC_FIFO_MAX_S = 2.0` → 48000 样本 = 2.0 s |
| 音乐背压 | `audio_codec.py:405-418` | 唯一有水位背压的写入端:目标 0.30 s(`:24`,`:414`),`await asyncio.sleep(0.02)` 轮询,最多 100 次(`:415-418`)。**TTS 写入端无背压** |

### 转换器 / 重采样器 — `src/audio_codecs/audio_converter.py`
| 项 | 位置 | 内容 |
|---|---|---|
| 输出链配置 | `audio_converter.py:56-81` | `from_rate=OUTPUT_SAMPLE_RATE(24000)` → `to_rate=device_config.output_sample_rate(48000)`,`from_channels=1` → `to_channels=2`(`audio_codec.py:254-259`) |
| soxr 实例 | `audio_converter.py:71-77` | `soxr.ResampleStream(24000, 48000, num_channels=1, dtype="float32", quality="QQ")`,仅在 `from_rate != to_rate` 时创建(`:70`) |
| **内部缓冲** | `audio_converter.py:23`, `:130-140` | `_output_buffer` 是 **`collections.deque`，以「单个 float32 标量」为元素**(`:133` `extend(resampled)` 把 ndarray 逐元素展开;`:139` 逐个 `popleft()` 再 `np.array(..., dtype=float32)` 重建)。**实测稳态残留 956 个元素**(首块 956,其后每块 960,见下方"实测") |
| `convert_output` 返回 None 条件 | `audio_converter.py:136-137` | `len(self._output_buffer) < target_frames` → `None` → 上层继续循环补块 |
| `drain_output_buffer` | `audio_converter.py:150-167` | 排空残留并上混;`available = min(len, target_frames)`(`:155`) |
| `clear_output_buffer` | `audio_converter.py:169-171` | **只 `self._output_buffer.clear()`** —— **不清 soxr 自身内部延迟状态** |
| `clear_buffers` | `audio_converter.py:173-177` | 清 input+output 两个 deque |
| `close` | `audio_converter.py:179-183` | 清 buffer + 置空 resampler(防 nanobind 泄漏) |
| 上混 | `audio_utils.py:187-201` | `np.tile(mono.reshape(-1,1), (1,num_channels))` → 两声道完全相同 |

**实测(本地只读复现,未改客户端)**:
- `soxr.ResampleStream(24000,48000,QQ)`,每块输入 480 样本 → 输出序列 `[956, 960, 960, 960, ...]`,累计 7676/7680。首块少 4 样本是滤波器初始延迟,稳态精确 2.0 倍。**无累积漂移**。
- 稳态下 `convert_output` 全链路(extend 960 元素 + 960 次 popleft + `np.array` 重建)实测 **≈0.049 ms/回调**,占 20 ms 预算 **0.2% CPU**。**重标ample器不是 CPU 瓶颈**,此嫌疑可排除。

### `clear_audio_queue()` 与 keep_listening 不对称 — `src/bootstrap/session.py`
| 项 | 位置 | 内容 |
|---|---|---|
| `clear_audio_queue` | `audio_codec.py:420-426` | 复位 `_server_opus_logged`(`:422`)+ `converter.clear_output_buffer()`(`:423`)+ `self._tts_fifo.clear()`(`:424`);**仅当 `count > 0` 才打日志**(`:425-426`),日志文案「清空 TTS 队列,丢弃 N 样本」 |
| 事件入口 | `session.py:94-99` | `type=="tts"` → `state=="start"` → `_handle_tts_start()`;`"stop"` → `_handle_tts_stop()` |
| `_handle_tts_start` | `session.py:106-113` | keep_listening && REALTIME → `LISTENING`,否则 `SPEAKING`。**不清队列、不重置转换器** |
| `_handle_tts_stop` | `session.py:115-141` | **`if not self.state.keep_listening: await set_device_state(IDLE); return`(`:117-119`)——早退,`clear_audio_queue()` 被完全跳过** |
| keep_listening 分支 | `session.py:122-132` | 非 REALTIME 时补发 `send_start_listening` |
| 清理调用 | `session.py:134-139` | `try: audio_plugin.codec.clear_audio_queue() except: logger.warning("清空音频队列失败")` |
| **不对称结论** | 对比 `session.py:117-119` vs `:134-139` | **keep_listening=False(手动/单次)时,TTS 结束不清 TTS FIFO、不清 `converter._output_buffer`、不复位 `_server_opus_logged`**。残留音频会继续被播放,直到 FIFO 自然排空或下一次 clear |
| 唤醒词打断路径 | `wake_word.py:103-106` | 打断后**会**调 `clear_audio_queue()`(与 tts-stop 路径不同) |
| UI 打断路径 | `ui_session.py:162-176` | `stop_listening()` + `abort_speaking()`,**不直接清队列** |
| `abort_speaking` | `session.py:237-269` | 只发 abort 协议 + 改状态,**不清播放队列** |

### AEC — `src/audio_processing/aec_engine.py`
| 项 | 位置 | 内容 |
|---|---|---|
| far 参考来源 | `audio_codec.py:233-235` | **Self far = 播放回调最终写出的 `outdata`**(TTS+音乐混合、已上混到 2ch、48 kHz) |
| 引擎创建 | `audio_codec.py:299-329` | `near_rate=16000`,`far_rate=device.output_sample_rate(48000)`,**`delay_ms = 40 + FRAME_DELAY*FRAME_DURATION = 40+3*20 = 100 ms`**(`:322`) |
| 输出回调内的处理 | `aec_engine.py:191-212` | `feed_far` **只做下混 + 拷贝入队**(微秒级);`outdata.ndim>1 and shape[1]>1` → `mean(axis=1)`(`:200-201`);否则 `np.array(...).ravel()` 拷贝(`:204`) |
| far 队列上限 | `aec_engine.py:33`, `:206-210` | `_FAR_PENDING_MAX_BLOCKS = 25` ≈ 0.5 s;超限 popleft + `_far_dropped += 1`(`:210`) |
| `_far_dropped` 可观测性 | `aec_engine.py:88`, `:210`, `:266-267` | **仅在 `close()` 时 `logger.debug` 打印一次** —— DEBUG 级,默认被过滤(实测 app.log 中 "AEC far" 出现 **0 次**) |
| 与播放路径的耦合 | `aec_engine.py:167`, `:214-239` | 重采样 + APM 全在**采集线程** `_drain_far_locked` 内完成,持 `self._lock`。**不修改 outdata**;但 far 与 outdata 严格 1:1 时序,**若客户端欠载补零,AEC far 也吃到零** |
| APM 旁路 | `aec_engine.py:30`, `:269-279` | 连续 5 次失败自动 `active=False`(`:271-275`) |

---

## FIFO_CAPACITY_MATH

**输入域(协议/解码侧)**:`OUTPUT_SAMPLE_RATE = 24000` Hz,mono float32
**输出域(设备侧)**:`output_sample_rate = 48000` Hz,2ch,`blocksize = 960 帧 = 20 ms`
**`_mix_chunk` = `int(24000*0.02)` = 480 样本 = 20.00 ms**(`audio_codec.py:74`)
**每回调消耗**:`frames = 960`(48 kHz) ⇒ 960/2 = 480 样本(24 kHz 域)⇒ **恰好 1 个 `_mix_chunk`/回调**
**FIFO 容量**:`int(24000 * 10.0)` = **240000 样本 = 10000.0 ms = 10.000 s**(`audio_codec.py:26`,`:68-70`)

### (a) 稳态 50 fps 喂入
| 量 | 值 |
|---|---|
| 喂入速率 | 50 帧/s × 480 样本 = **24000 样本/s = 1000.0 ms/s** |
| 消费速率 | 50 回调/s × 480 样本 = **24000 样本/s = 1000.0 ms/s** |
| 净变化 | **0 样本/s** → 深度恒定,**不增长、不溢出、不欠载** |
| FIFO 实际持有 | 由 bridge 端节奏决定;健康实时喂入下应稳定在 **1–3 个 chunk = 480–1440 样本 = 20–60 ms** |

**结论(a):在严格 1:1 实时喂入下,10 s 容量永远用不到;它只是"上限",不产生稳态延迟。**

### (b) 喂入停顿
回调是**自由运行**的(PortAudio 按 blocksize 驱动,与网络无关),因此停顿期间 FIFO 单调排空:

| 停顿 | 需在停顿前已有深度才不欠载 | 深度(样本) | 深度(ms) | 是否 ≤ 240000 容量 |
|---|---|---|---|---|
| **1 s** | ≥ 1.0 s | **24000** | **1000.0 ms** | ✅ 是 |
| **2 s** | ≥ 2.0 s | **48000** | **2000.0 ms** | ✅ 是 |
| **5 s** | ≥ 5.0 s | **120000** | **5000.0 ms** | ✅ 是 |

- 停顿期间**每 20 ms 回调都在拉 480 样本**,深度不足时 `pull` 补零(`audio_buffer.py:59`)⇒ 输出**静音补零**(`audio_codec.py:226-229` `outdata.fill(0.0)` + 部分拷贝)⇒ **可听的断裂/咔哒**。
- 深度 < 480 时 `pull` 返回非 None 的补零数组,`_pull_mixed` 视为"有数据"(`audio_codec.py:286`),**掩盖了欠载事实**;只有深度恰为 0 时才返回 `None`(`audio_buffer.py:57-58`)。

### 容量是否合适?
**不合适。**
- 10 s 容量对应 **240000 样本**,而实时客户端只需 **480–1440 样本(20–60 ms)** 就够吸收一个 3 帧的 jitter。
- 容量过大本身**不产生**稳态延迟(见 (a)),但它**允许失败静默**:一旦 bridge 侧真的送来 >10 s 的积压,`push` 会走丢最旧分支(`audio_buffer.py:43-52`)丢掉最早音频,**丢多少只写进无人读取的 `dropped`** ⇒ 表现为"开头被吃掉、中间拼接、语义错乱",而不是报错。
- **客户端的职责是低延迟播放,不是吸收积压。缓冲必须在 bridge 侧。**

**若 bridge 正确实时配速,建议容量**:
- **下限**:2–3 个 `_mix_chunk` = **960–1440 样本 = 40–60 ms** —— 吸收 1–3 帧到达抖动。
- **推荐**:**0.20 s = 4800 样本 = 100 个 chunk** —— 允许 10 帧抖动余量,同时把"最坏情况积压"钉在 200 ms(远小于 AEC 100 ms 延迟假设的 2 倍,可控)。
- **上限(不建议超过)**:**0.5 s = 12000 样本** —— 再大只会让丢最旧行为更难被察觉。
- **改动方式**:`audio_codec.py:26` 的 `_TTS_FIFO_MAX_S = 10.0` 改为 `0.20`(单行常量;`audio_codec.py:68-70` 与 `:263-265` 两处构造点自动跟随)。
- **注意耦合**:`_mix_chunk`(20 ms)与容量解耦,改容量**不会**改变混音节拍,只改上限。但 0.20 s 容量 + 10 s 积压的 bridge 组合 ⇒ 约每 0.2 s 触发一次丢最旧 ⇒ 恰好制造"越说越糊"的症状。**必须与 bridge 配速同批次上线,不能单独改客户端。**

---

## UNOBSERVABLE_METRICS

> 判据:能区分 starvation / FIFO overflow / CoreAudio buffering / 重采样瑕疵 / 解码故障所需的全部量。

### A. FIFO 层
| # | 指标 | 现状 | 来源 / 缺口 |
|---|---|---|---|
| 1 | **`dropped` 样本数(FIFO 溢出量)** | ❌ **NOT observable** | 写于 `audio_buffer.py:49`。**全仓 grep `\.dropped` 仅命中 `:28` 与 `:49` 两处,均为写入;零读取点**。结构上不可观测 |
| 2 | **`dropped` 分 FIFO(TTS vs 音乐)** | ❌ NOT observable | `clear()`/`close()` 都不上报;`audio_codec.py:587` 只合并两者求和 |
| 3 | **当前 FIFO 深度(运行期)** | ❌ NOT observable | `size` property 存在(`audio_buffer.py:30-32`)且被音乐背压读取(`audio_codec.py:416`),但 **TTS FIFO 的深度在运行期从未被读取或打印** |
| 4 | **峰值 FIFO 深度** | ❌ NOT observable | **`PcmFifo` 完全没有 peak 概念**。只有 `dropped` 单调计数器,无 `max(_size)` |
| 5 | **欠载次数(`pull` 返回 None)** | ❌ NOT observable | `audio_buffer.py:57-58` 直接 return,**无计数、无日志**。静默降级为补零 |
| 6 | **部分补零次数(`0 < size < n`)** | ❌ NOT observable | `audio_buffer.py:59` 补零后正常返回;调用方无从区分"满块"与"补零块"。**这是最隐蔽的故障模式** |
| 7 | **`clear_audio_queue` 时深度(单次)** | ⚠️ **observable, 但有条件** | `audio_codec.py:425-426` `if count > 0` 才打 INFO。仅在 **keep_listening=True** 路径被调用(`session.py:134-139`);`session.py:117-119` 早退时**不产生任何记录** |

### B. 解码层
| # | 指标 | 现状 | 来源 / 缺口 |
|---|---|---|---|
| 8 | **TOC 解析失败计数** | ❌ NOT observable | `audio_codec.py:383-384` `if toc_info is None: return` —— **完全静默,无计数无日志** |
| 9 | **解码异常计数** | ⚠️ observable(间接) | `audio_codec.py:402-403` `logger.warning("音频写入失败")`。实测 app.log(6642 行)中出现 **0 次** ⇒ 历史测试窗口内**无解码异常**。但无计数器、无法按窗口聚合 |
| 10 | **实际解码样本数 vs 期望 `frame_size`** | ❌ NOT observable | `opus_codec.py:169-172` 返回长度**从不与 `frame_size` 比对**。若 TOC 谎报帧长,libopus 返回短 buffer,**静默短帧** |
| 11 | **PCM 有效位/直流偏置/削波** | ❌ NOT observable | 全链路无 `np.isfinite` / RMS / 峰值检查。`np.clip` 仅在混音时(`audio_codec.py:297`) |
| 12 | **每包 `duration_ms` 分布** | ⚠️ observable, 但一次性 | `audio_codec.py:386-393` 只在**首个包**后打印一次,之后 `_server_opus_logged=True` 静默。实测:全窗口仅 `Hybrid 24kHz \| 帧时长 20ms (20ms×1)`,**即服务端始终 20 ms 单帧** |

### C. 播放 / 回调层
| # | 指标 | 现状 | 来源 / 缺口 |
|---|---|---|---|
| 13 | **回调实际节拍偏差(jitter)** | ❌ NOT observable | `time_info` 参数在 `audio_codec.py:192` 签名中**接收但从未使用**。无 `time_info` 记录、无 jitter 统计 |
| 14 | **`output_underflow` 事件** | ⚠️ observable, 但被限流且不分类 | `audio_codec.py:207-212`:`if status:` → 2 s 限流一条,**不区分 underflow/overflow,不计数**。实测 app.log 中「输出流状态」出现 **0 次** |
| 15 | **`priming_output` 事件** | ❌ NOT observable | 同上,`CallbackFlags` 成员存在但代码不区分 |
| 16 | **回调 CPU 负载 / `cpu_load`** | ❌ NOT observable | `sd.Stream.cpu_load` 属性**存在**(已实测),但 `stream_manager.py` 未读取 |
| 17 | **回调超时次数(客户端侧饿)** | ❌ NOT observable | `audio_converter` 异常被 `_output_callback:237-239` 吞掉并填零,**只 `logger.error` 不计数** |

### D. 重采样层
| # | 指标 | 现状 | 来源 / 缺口 |
|---|---|---|---|
| 18 | **`_output_buffer` 深度** | ❌ NOT observable | `audio_converter.py:23` 的 deque 长度从不被读(仅 `:136`/`:155` 内部比较)。**实测稳态 956** |
| 19 | **resampler 输入/输出累计样本数** | ❌ NOT observable | `audio_converter.py:131-133` 无累加器 |
| 20 | **soxr 内部延迟状态残留** | ❌ NOT observable | `clear_output_buffer()`(`:169-171`)只清 deque,**不清 soxr 状态**,且无任何记录 ⇒ 打断后残留滤波器尾音**不可见** |
| 21 | **重采样比漂移** | ❌ NOT observable | 无 in/out 累计计数。**实测 24k→48k 精确 2.0,首块 956(少 4 样本)后稳定,无漂移** —— 该嫌疑已可排除 |

### E. AEC 层
| # | 指标 | 现状 | 来源 / 缺口 |
|---|---|---|---|
| 22 | **`_far_dropped`** | ⚠️ observable, 但 DEBUG 且仅在 close 时 | `aec_engine.py:266-267` `logger.debug`。默认日志级别下不可见(实测 0 次) |
| 23 | **AEC 实际对齐延迟 vs 假设 100 ms** | ❌ NOT observable | `delay_ms` 是**静态常量**(`audio_codec.py:322`);实际播放延迟随 FIFO 深度变化,但两者关系无任何测量 |
| 24 | **APM 旁路次数** | ❌ NOT observable | `aec_engine.py:271-275` 旁路时 `logger.error`,但实测 0 次;且旁路后不再上报 |

### F. 端到端/关联层
| # | 指标 | 现状 | 来源 / 缺口 |
|---|---|---|---|
| 25 | **客户端 vs bridge 时钟对齐** | ⚠️ 部分 observable | 客户端日志用 `%(asctime)`(`logging/__init__.py:142`)。**同机同进程时可直接对齐**;跨机需 NTP 保证。实测两端日志时间戳同为 `2026-10-06 17:05:xx` 格式,可关联 |
| 26 | **`peak_queue_depth` 等 bridge 侧量** | ❌ NOT observable(客户端侧) | R-1e 已确认系统以 `RTL_DIAG` 未设置运行。客户端侧亦无对应字段 |

### ⚠️ 从既有日志中抢救出的实证(不需要新代码)
`清空 TTS 队列,丢弃 N 样本` 是**唯一**存在的 FIFO 深度采样点。实测 `app.log`(2026-10-05 09:46:57 → 2026-10-06 18:54:15,6642 行)共 **81 条**:

- 中位数 **480 样本 = 20.0 ms**(即恰好 1 个 `_mix_chunk`,健康的准实时)
- 均值 **74.8 ms**,**最大 13920 样本 = 580.0 ms**(2026-10-06 17:05:49)
- **20 / 80 配对窗口残留 > 50 ms**,最大 **0.58 s**

**这直接证明了积压真实存在且随答案变长而增大**(与人类报告"越长越糟"一致):17:05:45 窗口 4 s 墙钟内残留 580 ms ⇒ **该窗口的有效喂入比实时快约 14%**;17:05:49 前的 17:05:38 窗口快约 10%。

**但这不能证明 FIFO 溢出**:残留深度最大 580 ms,距 240000 样本(10 s)上限差 **41 倍以上**,因此**在已记录的全部窗口内,`dropped` 极可能始终为 0** —— 客户端 FIFO **不是**已观测到的失真源。这把嫌疑明确指向 bridge 侧(drop 掉整段音频 / 喂入非实时)。

---

## GATED_INSTRUMENTATION_DESIGN

### 定位
**临时诊断脚手架(temporary diagnostic scaffolding),不是特性。** 门控关闭时零行为变更、零分配、零日志。**不含任何 UI、不含配置项、不改变任何音频路径。**

### 门控
```
XIAOZHI_PLAYOUT_DIAG=1      # 开启
XIAOZHI_PLAYOUT_DIAG_MS=1000  # 可选，输出周期，默认 1000
```
- 读取点:`audio_codec.py` 模块级一次性 `os.environ.get`;**默认 OFF**。
- 关闭时:所有埋点被 `if _DIAG:` 短路,`PcmFifo` 仍只有现有字段,**不新增属性、不新增计数器**。

### 埋点字段(单行 JSON,便于机器解析)
```json
{"t":1759666800.123,"cb":4821,"peak":8160,"depth":480,"dropped":0,
 "starve":0,"partpad":7,"dec_err":0,"toc_null":0,"dec_short":0,
 "rin":2308800,"rout":4617600,"obuf":956,
 "dev_frames":960,"dev_underflow":0,"dev_overflow":0,"jitter_p99_us":180,
 "clr_depth":13920,"clr_at":"2026-10-06T17:05:49","aec_far_drop":0,
 "latency_s":0.021,"cpu_load":0.03}
```

| 字段 | 语义 | 埋点位置 |
|---|---|---|
| `cb` | 输出回调总次数 | `audio_codec.py:214` try 块首 |
| `depth` / `peak` | FIFO 当前 / 峰值深度(样本,24 kHz) | `_pull_mixed` 前读 `size`;peak 在同一处 max |
| `dropped` | FIFO 累计丢弃样本 | 直接读 `self._tts_fifo.dropped`(修掉 §A-1) |
| `starve` | `pull` 返回 `None` 次数 | `audio_buffer.py:57-58` return 前 |
| `partpad` | **部分补零次数**(`0<size<n`) | `audio_buffer.py:59` 之后,`filled<n` 时 |
| `dec_err` | 解码异常次数 | `audio_codec.py:402` |
| `toc_null` | TOC 解析失败次数 | `audio_codec.py:383-384` |
| `dec_short` | 解码样本数 < `frame_size` 次数 | `audio_codec.py:398` 后比对 `len()` |
| `rin`/`rout` | resampler 输入/输出累计样本 | `audio_converter.py:131`/`:133` |
| `obuf` | `_output_buffer` 深度 | `audio_converter.py:136` |
| `dev_frames` | 本次 `frames`(应为 960) | `audio_codec.py:192` |
| `dev_underflow`/`dev_overflow` | PortAudio 欠载/过载计数(**按 flag 分类**) | `audio_codec.py:207`,`if status.output_underflow` |
| `jitter_p99_us` | `time_info` 抖动(定长环形缓冲,1024 深) | `audio_codec.py:192`,首次见到 `time_info` 后记录 |
| `clr_depth` | `clear_audio_queue` 时深度 | `audio_codec.py:424`,**无条件记录(含 keep_listening=False 早退路径)** |
| `aec_far_drop` | AEC far 丢弃块数 | `aec_engine.py:210` |
| `latency_s` | `output_stream.latency`(已实测属性存在) | `stream_manager.py:96` 后,一次性 |
| `cpu_load` | `output_stream.cpu_load` | 同上,每次输出周期 |

### 输出机制
- 在**输出回调内**只做**整数自增 + 浮点比较**(无分配、无锁、无 I/O);`time.monotonic()` 判定周期。
- 到期时**不在回调里写文件**:置一个 `bool` 标志,由 `write_audio`(`audio_codec.py:373`,已在 asyncio 线程)或一个 1 s 的 `asyncio` 任务单线 `logger.info` 输出。**避免在实时回调内做文件 I/O —— 代码自己在 `:207-208` 已注明"回调内写日志会加剧欠载"。**
- 单行 JSON,前缀 `PLAYOUT_DIAG`,走现有 `app.log`(`logging/__init__.py:142` 的 `%(asctime)` 提供毫秒时间戳,可与 bridge 侧对齐)。

### 开销约束
- 每回调新增:2 次整数加、1 次浮点比较、1 次 `if`。实测该resampler 链路全流程已占 0.2% CPU,增量 **< 0.5%**。
- **有界**:jitter 环形缓冲固定 1024 深;所有计数器标量。**无无界分配**。可整场聆听测试常开。

### 触及的文件与行数估计
| 文件 | 改动 | 估计行数 |
|---|---|---|
| `src/audio_codecs/audio_buffer.py` | `_DIAG` 门控 + `starve`/`partpad` 计数 + `peak` 字段 | **~14** |
| `src/audio_codecs/audio_codec.py` | 门控读取、计数器、`write_audio` 的 `toc_null`/`dec_err`/`dec_short`、`_output_callback` 的 underflow 分类与 jitter、`clear_audio_queue` 无条件记录 | **~55** |
| `src/audio_codecs/audio_converter.py` | `rin`/`rout`/`obuf` 累加 | **~8** |
| `src/audio_codecs/stream_manager.py` | 一次性记 `latency`/`cpu_load` | **~4** |
| `src/audio_processing/aec_engine.py` | 暴露 `_far_dropped` 供读取 | **~2** |
| **合计** | | **~83 行** |

**确认:这是临时诊断脚手架。** 门控默认 OFF;不改协议、不改音频行为、不加 UI、不加持久化。R-1f 结论落地后应整体移除(或转为长期 `peak`/`dropped` 单行日志 —— 那是一个独立且小得多的提议)。

---

## CLIENT_LAYER_VERDICT

### 可以得出的结论
1. **客户端 FIFO 不是已记录窗口内的溢出源。** 唯一存在的深度采样点(`audio_codec.py:425-426`)在 80 个配对窗口中最大残留 **13920 样本 = 580 ms**,距 240000 样本上限差 **41 倍**。⇒ **在已记录的全部窗口内 `dropped` 极可能始终为 0**。这**收窄**了 `CLIENT_OR_OS_PLAYOUT_LAYER` 的范围,但**不能排除**它 —— 因为 §A-4/§A-5/§A-6 全部不可观测。
2. **重采样器无漂移。** 实测 24k→48k 精确 2.0 倍,首块少 4 样本(滤波器初始延迟)后恒定,CPU 占 0.2%。**`resampling artefacts` 假设可排除。**
3. **已记录窗口内无解码异常。** `audio_codec.py:402-403` 的「音频写入失败」在 6642 行日志中出现 **0 次**;PortAudio「输出流状态」出现 **0 次**。⇒ **无证据表明存在 CoreAudio 欠载或解码故障** —— 但两者都被限流/静默处理,证据强度弱。
4. **积压真实存在,且随答案变长增大。** 580 ms 残留出现在 4 s 窗口 ⇒ 该窗口喂入比实时快 ~14%。这与人类"越长越糟"**方向一致**,但积压本身在客户端**只表现为延迟,不必然产生失真**。
5. **`keep_listening` 不对称是真实缺陷。** `session.py:117-119` 早退使 `clear_audio_queue()` 被跳过 ⇒ 手动/单次模式下 TTS 结束后**残留 FIFO 继续播放**,且残留量**无任何日志**。这可独立造成"说完还在响/重复片段"。

### 不能得出的结论
1. **不能证明静态/buzz 的根因在客户端,也不能证明它不在客户端。** 关键盲区是 **§A-6 `partpad`(部分补零)** 与 **§A-5 `starve`**:二者都让 `pull` 返回"看似正常"的补零块,`outdata.fill(0.0)`(实测 0 次状态日志)**不产生任何日志**。这是**唯一能在不触发任何告警的情况下把语音变成静默再恢复的路径**,与"静态/buzz"高度吻合,**却完全不可观测**。
2. **不能量化 FIFO 峰值。** 无 peak 概念。若某窗口曾溢出并回落,残留采样**看不出**。
3. **不能排除 CoreAudio 缓冲问题。** `latency="low"`(`stream_manager.py:71`)+ `cpu_load` 未读 + `输出流状态` 2 s 限流 ⇒ 客户端饿 0 次与饿 10 次在日志上无法区分。
4. **不能排除 AEC 影响。** `delay_ms = 100 ms` 是静态常量(`audio_codec.py:322`),而实际播放延迟随 FIFO 深度变化(实测可达 580 ms)⇒ **AEC far/near 可能失配**,这会污染上行识别、间接影响 bridge 行为,但 `_far_dropped` 默认不可见。
5. **不能用客户端日志区分"bridge 丢了整段"与"客户端没喂上"。** 两者都表现为 `starve`。

**⇒ `STATIC_AUDIO_ROOT_CAUSE` 仍 UNPROVEN;`CLIENT_OR_OS_PLAYOUT_LAYER` 仍 NOT_EXCLUDED。但本审计显著收窄了范围:重采样已排除,解码异常无证据,FIFO 溢出无证据;剩余最可能且完全不可观测的客户端机制是 `partpad`(部分补零)。**

---

## DISCRIMINATING_MEASUREMENT

**单个最便宜的判别实验:**

> 在客户端**只加一个 gated 计数器**(§GATED_INSTRUMENTATION_DESIGN 中的 `starve` + `partpad` + `dropped` + `peak`),门控默认 OFF、只开 `XIAOZHI_PLAYOUT_DIAG=1`。然后**故意让 bridge 侧制造一次已知的多段丢音频**(例如在 4 s 答案中丢弃 3 × 100 ms),同时客户端跑完整场聆听测试。

**判别逻辑(单次测试即可定性)**:

| 观测结果 | 结论 |
|---|---|
| `partpad` 或 `starve` 在**每个**已知丢弃点**同时**跃升,且 `dropped == 0`、`peak` 远低于 240000 | **桥接侧丢音频**。客户端只是忠实播放它收到的东西 ⇒ 修 bridge |
| `dropped > 0` 或 `peak` 接近 240000 | **客户端 FIFO 溢出**。积压超过 10 s ⇒ 修 bridge 配速(**或**先降客户端容量让它显式失败) |
| `dev_underflow > 0` 且以上均为 0 | **CoreAudio / 客户端调度**问题 ⇒ 查 `latency`/`cpu_load`/GIL 竞争 |
| 三者**全部为 0**,但仍有静态/buzz | **解码或内容层**。看 `dec_short`/`toc_null`,再回查 bridge 实际发出的 Opus 字节 |
| `partpad` 跃升但 `starve == 0` | **纯部分补零**(FIFO 半满)。这是客户端最隐蔽的失真源,直接定位到 `audio_buffer.py:59` |

**为什么这是最便宜的一测**:
- 改动量 **~83 行**,全部在已有埋点位置,无音频路径变更。
- 门控 OFF 时**零行为变更**,可安全合入并保留。
- **一次测试同时给全 5 个假设一个是/否**,不需要逐项排查。
- 关键点:它把 §A-5/§A-6 这两个**当前完全不可观测**的量变成可观测量 —— 而这两个正是唯一能产生"无告警静默失真"的机制。**没有这一步,`CLIENT_OR_OS_PLAYOUT_LAYER` 在结构上无法被排除。**

**配套最小改动(强烈建议同批)**:把 `audio_codec.py:26` 的 `_TTS_FIFO_MAX_S` 从 `10.0` 降到 `0.20`,**与 bridge 配速同批次上线**。这让"积压超过 200 ms"从一个静默的、10 s 后才发生的丢最旧,变成一个 200 ms 就触发的、**被 `dropped` 记录**的显式事件。**不要单独改客户端容量** —— 单独改会加重"越长越糊"。

---

## DESIGN_BLOCKERS

**0**

理由:
- 门控用纯环境变量,无配置迁移、无 UI、无协议变更。
- 所有埋点位置均已确认存在且行为已知。
- `sounddevice.Stream.latency` 与 `cpu_load` 属性**已实测存在**,可直接读。
- `soxr` 行为**已实测**,漂移嫌疑已排除。
- 客户端日志 `%(asctime)` 与 bridge 侧时间戳格式一致,可直接关联。
- **无需重启容器、无需付费调用**即可实现;测试运行只需 `XIAOZHI_PLAYOUT_DIAG=1` 环境变量。

唯一需 team-lead 确认的**非阻塞**事项:是否接受把 `_TTS_FIFO_MAX_S` 从 10.0 降到 0.20(**必须与 bridge 配速同批次**,不可单独上线)。

---

## DESIGN = READY_FOR_REVIEW