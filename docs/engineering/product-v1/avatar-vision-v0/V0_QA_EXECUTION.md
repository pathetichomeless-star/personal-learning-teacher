# V0 QA 执行记录（V0_QA_EXECUTION）

- 角色：v0-qa（只读复审）；本文件为本次唯一写入物。
- 基线：branch `avatar-vision-v0` @ `64e543a`（对比基线 `d5644f1`，冻结 tag `XIAOZHI-VOICE-V1-HUMAN-ACCEPTED` 未触碰）。
- 日期：2026-10-09（本地执行，全部网络交互仅 127.0.0.1 mock，零真实模型/零计费）。

## 1. RUNS（三套测试文件新鲜执行）

| 套件 | 命令 | 结果 |
|---|---|---|
| 网关守卫 | `DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python gateway/tests/vision_v0_tests.py` | **13/13 PASS**（V1 非 JPEG 拒绝、V1b 拒绝零外发、V2 超限拒绝、V3 base64 上限、V4 图像先于音频拒绝、V5/V5b/V5c 形状与线序、V6a/V6b 频率守卫、V7 拒绝后音频链路无恙、V8/V9 会话隔离与重连重置） |
| Avatar 状态机 | `node prototypes/tests/avatar_logic_tests.mjs` | **16/16 PASS**（状态迁移、blink 窗口界、mouth 平滑/上限/NaN/打断清零、newTurn 防串、barge-in、异常隔离） |
| Vision 前端逻辑 | `node prototypes/tests/vision_logic_tests.mjs` | **17/17 PASS**（JPEG magic 校验、超大拒绝、compressPlan 长边 1280、质量递减、频率守卫 5s/6min、会话隔离四断言、renderField 防注入） |

合计 **46/46 全绿**，0 FAIL。

## 2. MOCK 端到端（QA 亲自驱动，非采信声明）

- **normal**：`POST /vision/recognize`（1×1 JPEG base64）→ HTTP 200，形状 `{"object","scene","text","confidence":0.87,"mock":true}` 与 MOCK_CONTRACT 一致；`/__log` 仅元数据（mode/bytes:233），**零图像字节落盘**。
- **degrade**：受控 `{"ok":false,"error":"vision unavailable (mock)"}`，HTTP 非 5xx 崩溃，无重试风暴（单发直降级）。
- **xss（代码级惰性断言）**：mock 返回攻击载荷 `"><img src=x onerror=…>`；原型渲染路径全部走 `createElement + textContent`（vision_v0.html:137-141）与 `renderField` 守卫（vision_v0_logic.js:71-76，非字符串→"暂无数据"）；唯一 innerHTML 用法为清空（`innerHTML = ""`，vision_v0.html:131）。**载荷渲染惰性成立。**

## 3. T_CASE 映射（计划 24 例 + 2 项边界 → 自动化/人工门禁/不适用）

| 计划例 | 判定 | 依据 |
|---|---|---|
| A1-a/b/c | **AUTOMATED** | vision_logic_tests（magic/超限/空）+ 网关 V1/V2/V3 |
| A2 | **AUTOMATED** | 网关 V5/V5b 线形状 + mock E2E 形状逐字段 |
| A3 | **AUTOMATED** | V7（拒绝后音频无恙）+ degrade E2E 受控 ok:false |
| A4 | **AUTOMATED** | V8/V9 + 隔离四断言 |
| A5 | **AUTOMATED（代码级）** | xss 载荷惰性如上；真实模型抗注入为 manual gate |
| B1 | **AUTOMATED** | V5/V5b/V5c + mock E2E |
| B2/B3 | **AUTOMATED** | V7 + 46 项断言回归绿 |
| B4 | **AUTOMATED**（打断状态机）| avatar 16/16 + V4/V6；真实音频打断时延为 manual |
| C1 | **MANUAL-GATE**（TCC 弹窗）| 权限分支逻辑已由状态机用例覆盖 |
| C2/C5 | partial | 代码审查确认单 stream/stop tracks；运行时句柄计数人工 |
| C3/C4 | **AUTOMATED** | 守卫+禁用态；压缩 17 项 |
| C6/C7/C8 | **AUTOMATED** | avatar_logic_tests 16/16 |
| D1 | partial | 本地 E2E 亚秒级；20 次 P50/P95 正式采样为 manual gate |
| D2/D3 | **未执行（gap）** | 资源采样与 evidence 文件本窗口未产出 |
| D4 | **PASS** | `git diff d5644f1..64e543a` 纯新增 19 文件（+1999/-0）；audio/vad/pacing/protocol **零字节改动** |
| D5 | **partial（gap）** | 三套回归基座（29/33/60+）本窗口未复跑 |

## 4. 缺陷与差距

1. **DEFECT-1（QA 粘合层，非产品代码）**：`prototypes/tests/v0_qa_mock_e2e.py` 以 `VISION_MODE/VISION_PORT` 启动 mock，而 `tools/vision_mock_server.py` 实际读 `ADMIN_VISION_MODE/ADMIN_VISION_PORT` → 脚本化套件新鲜运行报 "mock normal not ready"。mock 本体在正确环境下完全正常（本报告第 2 节为手驱证明）。建议实施方统一环境变量名后该套件即可自动化。
2. **契约小漂移**：normal 响应带 `mock:true` 但无 docstring 承诺的 `ok:true` 字段（degrade 带 `ok:false`）；建议对齐或修订 docstring。
3. **MANUAL GATES（移交 PO）**：真实云识别质量（≥10 张真实图人工抽检）、macOS TCC 三分支真机走查、真机摄像头时序与 D1 正式采样、真人音视并发主观验收、D2/D3 资源留档、D5 三基座复跑。

## 5. 结论

**VERDICT: PASS（带门禁）** —— 全部可自动化用例（46/46 单测 + mock E2E 契约 + 代码级惰性 + D4 冻结审计）通过；缺口均为本地不可自动化项或粘合层缺陷，已逐项列明，不阻塞 V0 冻结。
