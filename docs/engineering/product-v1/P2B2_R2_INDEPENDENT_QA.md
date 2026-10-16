# P2-B2-R2 独立 QA 记录

**范围**：`gateway/app/teacher_context.py`（新增）、`gateway/app/teacher_voice.py`、`gateway/app/main.py`、
`gateway/tests/teacher_context_seam_tests.py`（新增）、`gateway/tests/teacher_voice_seam_tests.py`。
**方式**：独立 QA 智能体，仓库只读，自写隔离脚本（仅写入 `/tmp`），全部使用 Mock 上游与隔离夹具。
**未做**：无真实模型调用、无付费请求、无网络、无 NAS 访问、无密钥读取。

---

## 一、QA 受核修订（sha256）

在被复核时（施工方自查加固之后）的修订：

```
16ca10e7a8937adaf9c092c9537185c06e3bb653c09f5a1e75f28b8c6b6f95be  gateway/app/teacher_context.py
1fba38f2b7f5f656dad194cc7ff30bca88024328e307b006f8a85101ba1678cd  gateway/app/teacher_voice.py
cc2f65d373f6a0049ca8f96cd4be82b13db0bf469b5f9f3cdfc0953ef61ecfae  gateway/app/main.py
8ac25d64024e332c0273022b1e70a83b367aae524c2b387847c162e04e6d9c8b  gateway/tests/teacher_context_seam_tests.py
fec1974c317020a14614d44271045f7f996f35de6cf3b79d30f5a0d29aa28a08  gateway/tests/teacher_voice_seam_tests.py
```

QA 结论：**`QA_PASS_WITH_NOTES`** —— 0 个 P0，1 个 P1，3 个 P2。

---

## 二、QA 已独立确认的结论（摘要）

| 项 | QA 结论 |
|---|---|
| 冻结六文件未被修改 | 确认（含 sha256 与 `git diff HEAD`） |
| 教材白名单是结构性的 | 直接读投影文件 JSON 统计归属，确认物理上不含他人 chunk |
| 授权但 `status != enabled` 的 dataset | 确认被排除，且未授权 dataset 绝不出现 |
| 教材确实进入模型会收到的 instruction | 用 `render_instructions` + `render_knowledge_block` 串起验证 |
| 老师政策生效且不串用 | 双老师互证，A 文本不含 B 规则 |
| 老师名为空不借用他人名字 | 确认回落到中性默认 |
| 记忆 fail-closed | 确认任何路径 `MEMORY_FILE` 均为空，客户端无 student 参数可影响 |
| 学习记录不编造 | 确认预览不记录、`pronunciation` 为 `unassessed`、强行声明发音被 `no_audio_evidence` 拒绝 |
| 观察者不触碰音频 | 确认包装后音频事件参数逐一相等、`observe()` 同步不 await 不抛异常 |
| 会话切换/重连隔离 | 确认路径正确切换、字节幂等、全局 config 逐值不变 |
| 默认关闭行为不变 | 确认默认配置下 R1 行为不变 |

---

## 三、QA 提出的问题与施工方处置

| 编号 | 级别 | 问题 | 处置 |
|---|---|---|---|
| Q-P1-1 | **P1** | aiohttp 在客户端消失时会取消 handler 任务，取消点落在 `finally` 的第一个 `await`，导致 drain 与 `end_session` 被跳过 —— 留下 `status=="active"` 的孤儿课堂记录，并静默丢弃真实轮次 | **已修复**：新增 `_teardown()` / `_run_teardown()`，收尾在独立任务中执行并用 `asyncio.shield` 保护；取消时仍让内部任务跑完，同时保留取消语义上抛 |
| Q-P2-1 | P2 | `project_teacher_policy` 的 `active.updated_at` 用 `time.time()`，同老师每次投影字节不同，违反"幂等/不重写" | **已修复**：改为常量 `0`（投影是老师记录的纯函数，与写入时刻无关） |
| Q-P2-2 | P2 | 投影目录权限 `0755`（`os.makedirs` 受 umask 影响），投影含老师私有教学规则，应更紧 | **已修复**：目录统一 `0700`（已存在目录也会被收紧），文件仍 `0600` |
| Q-P2-3 | P2 | 观察者无长度上限，超长转写会在 `append_turn` 抛错而被丢弃，可能连带丢弃后续轮次 | **已修复**：新增 `MAX_TURN_CHARS = 4000`（对齐存储层 `MAX_TURN_CHARS`）与 `stats["truncated"]`，超长截断后仍成功写入 |

### 事实纠正（施工方核对）

QA 报告称"`provider_realtime_binding` / `default_resolver` 在全仓 tests 里零引用"。
施工方核对为**不成立**：`gateway/tests/teacher_voice_seam_tests.py` 中共有 **14 处**引用
（`provider_realtime_binding` 见 T10h–T10k；`default_resolver` 见 T11a–T11i 与 T8）。
该套件在 R1 已覆盖仿冒域、非法端口、冻结 provider、非兼容协议、缺凭据、凭据等于全局等负向路径，
且本轮 54/54 全绿。此纠正不影响 QA 的总体裁定。

---

## 四、施工方对修复的自我证伪

新增回归断言 **T13l**：用一个"`finish()` 内含延时"的假 observer 与假 conn 驱动真实的
`tv._run_teardown`，中途 `task.cancel()`，要求 `close()` 与 `finish()` **都执行完毕**。

双向验证（脚本位于 `/tmp`，仓库未改动）：

```
修复后：ALL PASS  81/81
把 tv._run_teardown 换回未加 shield 的旧行为：
  >>> failing checks: ['T13l a CANCELLED handler still runs the whole teardown (P1 guard)']
```

即该断言对 Q-P1-1 具备鉴别力（旧行为下必然失败），不是"恒真"断言。

注：另有一条 **T13k**（正常断开后记录被关闭）—— 施工方确认它**不能**鉴别 Q-P1-1
（常规断开不触发取消，加不加 shield 都通过），因此它是"正常路径"断言，
Q-P1-1 的回归保护由 T13l 承担。此处如实标注，避免把弱断言当强断言。

---

## 五、修复后的全量回归（施工方复跑）

| 套件 | 结果 |
|---|---|
| `teacher_context_seam_tests.py` | **81/81 PASS** |
| `teacher_voice_seam_tests.py` | **54/54 PASS** |
| `teaching_v4_tests.py` | 36/36 |
| `voice_v4_tests.py` | 74/74 |
| `teaching_assessment_v4_tests.py` | 28/28 |
| `model_v4_tests.py` | 72/72 |
| `knowledge1_tests.py` | 72/72 |
| `memory1_tests.py` | 19/19 |
| `product_v1_integration.py` | 33/33 |
| `admin_v4_api_tests.py` | 107/107 |
| `import_v4_tests.py` | 39/39 |
| `admin1_tests.py` | 81/83（既有基线，纯净 HEAD 已对照复现） |

冻结六文件 sha256 与施工前逐字节一致（见交付记录）。

---

## 六、修复后的独立复验

见交付记录 §六 的提交说明；复验结论见本节回填。

> 复验状态：见 `P2B2_R2_CONTEXT_SEAM_DELIVERY.md` 第六节。
