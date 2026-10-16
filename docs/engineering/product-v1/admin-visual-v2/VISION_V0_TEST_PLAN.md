# VISION/AVATAR V0 测试计划（VISION_V0_TEST_PLAN）

- 基线：branch `admin-visual-v2` @ `e51d9a5`（冻结语音基线 tag `XIAOZHI-VOICE-V1-HUMAN-ACCEPTED` 不得改变）
- 编制：v0-qa-planner（只读 QA；本文为唯一写入物）。**截至 e51d9a5 尚无任何 V0 视觉/数字人代码**——本计划供 Lead 实施时对照执行，实施后由 QA 以只读身份复审。
- 硬边界：不触碰真实 Qwen / NAS / 真实云视觉服务；gateway 冻结文件零修改（见 D5）；全部自动化用例本地可跑；所有网络交互仅指向 `127.0.0.1` mock。
- 事件形状依据：v0-protocol 协议报告中已验证的 vision 事件形状（`docs/engineering/product-v1/admin-visual-v2/` 下协议报告交付物，实施时以其字段表为准；本文 MOCK_CONTRACT 与之冲突时以协议报告为准并回报 QA）。

---

## 1. LAYERS（分层）

| 层 | 范围 | 技术 | 复用/参照 |
|---|---|---|---|
| A | 协议/单元：图像预处理、vision 事件构造、降级、会话隔离、注入 | Python（`gateway/` venv，无新依赖）或 Node 纯函数 runner | 参照 `gateway/tests/behavior1_tests.py` 的 `check()`+`RESULTS` 无框架模式 |
| B | 网关集成：vision 事件过网关（MOCK 边界内）、音频零回归 | pytest / standalone python，aiohttp TestClient + drivable mock Qwen | 参照 `gateway/tests/product_v1_integration.py`（FakeWB/Client/make_mock_app 模式）、`gateway/tests/mock_qwen_server.py` |
| C | 客户端/浏览器：摄像头、预览、截图、压缩、资源释放、数字人状态 | mock server（stdlib `http.server`，仅 127.0.0.1）+ Node 纯函数断言；浏览器级为可选 | 参照 V2 的 `tools/admin_mock_server.py` 模式与 `admin-visual-v2/TEST_PLAN.md` 第 3 节 |
| D | 资源与基线：延迟、内存、资源度量、冻结基线 diff 审计 | 脚本 + `git diff` 审计 | 回归基座：`gateway/tests/admin_security_tests.py`(29)、`product_v1_integration.py`(33)、`behavior1_tests.py` |

## 2. CASE_TABLE（用例表）

### Layer A — 协议/单元（mock 事件）

| ID | 步骤 | 预期 | 可自动化 |
|---|---|---|---|
| **A1-a** | 对图像预处理函数输入：合法 JPEG（魔数 `FF D8 FF`）、非法字节、PNG 改名 .jpg、空文件 | 仅合法 JPEG 通过；非法输入返回明确拒绝（类型化错误，非裸异常） | yes |
| **A1-b** | 输入含 EXIF 的 JPEG（含 GPS/机型 tag）与超过尺寸上限的 JPEG（上限值按协议报告，未定则默认 5MB） | EXIF 元数据被剥离（输出无可解析 EXIF）；超尺寸被拒绝且错误消息不含图像内容 | yes |
| **A1-c** | 输入分辨率超上限（如 >4096px）的合法 JPEG | 按规格降采样或拒绝（以协议报告为准），不得原样透传 | yes |
| **A2** | 用 mock 帧构造 vision 事件（单帧捕获 → 事件），逐字段断言 | 事件形状与协议报告字段表逐字段一致（type/sessionId/图像编码/base64 长度界等）；无多余字段 | yes |
| **A3** | vision 识别调用注入故障（mock 抛错/超时/返回畸形 JSON），随后正常走一轮语音对话 | 语音链路不受影响：ASR→回复→TTS 照常；vision 失败被记录（计数器/日志），用户无报错刷屏；无崩溃、无重试风暴（有限次重试或直接降级） | yes |
| **A4** | 两个并发会话（参照 product_v1_integration 场景 13 的双会话模式），会话 1 提交图像、会话 2 纯语音 | 会话 2 的状态/上下文/回复中无会话 1 图像内容的任何痕迹；vision 产物（识别文本/描述）只进入会话 1 状态 | yes |
| **A5** | 构造恶意"图像"载荷：文件名/EXIF 注释/识别 mock 返回值中嵌入指令文本（"忽略之前指令""把记忆改为…"、prompt 注入模板） | 图像派生文本以**数据身份**进入上下文（按协议报告的包装约定），不可改变系统指令、不可写入记忆、不可触发工具；断言回复与状态无注入效果；与 A4 组合验证不可跨会话 | yes |

### Layer B — 网关集成（pytest，mock Qwen）

| ID | 步骤 | 预期 | 可自动化 |
|---|---|---|---|
| **B1** | 参照 `product_v1_integration.py` 搭建：真桥接 app（aiohttp 临时端口）+ drivable mock Qwen + mock 视觉服务（见第 3 节）；合成客户端发送 hello → 单帧图像事件 → 断言网关转发与回执 | vision 事件在 MOCK 边界内完整流转：到达 mock 视觉服务、识别结果按协议形状回注会话、transcript 流含图像派生文本且标记为数据身份；真实 Qwen 零调用（mock Qwen 请求日志证明） | yes |
| **B2** | 在同一集成环境重跑 product_v1 的 13 个场景断言（至少覆盖场景 1/3/5/12/13：中文聊天、词汇策略、记忆应用、重连、双会话隔离） | 全部通过且断言逐项一致——vision 代码加入后音频/对话行为零变化 | yes |
| **B3** | 音频计数器断言：触发一轮完整语音对话（含打断），对照 `app/counters.py` 计数器与 behavior1 风格确定性路由检查（`gateway/tests/behavior1_tests.py` 全量跑一遍） | 计数器序列与加入 vision 前基线一致；behavior1 ≥60 场景全绿；无新增失败 | yes |
| **B4** | 带 vision 的打断轮次：图像识别进行中用户打断（barge-in）→ 立即语音输入 | 识别任务被取消/结果被丢弃（不回注过期轮次）；打断延迟不劣于基线；轮次状态机无卡死（连续 10 轮混合图像+打断） | yes |

### Layer C — 客户端/浏览器（mock server + 可选浏览器）

| ID | 步骤 | 预期 | 可自动化 |
|---|---|---|---|
| **C1** | 摄像头权限三分支：已授权 / 拒绝 / 未决定（macOS TCC；自动化下用预置状态或 mock 权限层） | 每分支有明确 UI 状态与文案；拒绝/未决定不发起捕获；无权限时无隐藏重试 | partial（TCC 弹窗为 manual；权限分支逻辑可 Node 单测） |
| **C2** | 预览开启 → 关闭 → 再开启，各阶段截图/断言 | 预览流随开关起止；重复开启不泄漏第二个流（同一 camera handle 复用或先释放后建） | partial |
| **C3** | 点击截图按钮（预览开启/关闭两态） | 开启时产生一帧并提交（指向 mock）；关闭时按钮禁用且无网络调用（mock 请求日志零请求） | yes |
| **C4** | 对固定输入帧（含大图 fixture）跑压缩函数，Node 单测断言输出 | 输出为 JPEG、质量/最长边符合协议报告规格、体积 ≤ 上限；EXIF 已剥离（联动 A1） | yes |
| **C5** | 停止会话/退出页面后检查资源 | 预览流停止、camera handle 关闭、无残留定时器/WS（代码审查 + 运行时句柄计数断言） | partial |
| **C6** | mock server 按固定振幅序列下发音频幅度数据（见第 3 节 mock 合同），驱动数字人嘴型 | 嘴型开合幅度单调跟随 mock 振幅序列（采样点对采样点断言）；数字人状态机 idle/listening/thinking/speaking 按 mock 事件正确迁移，无非法迁移 | yes |
| **C7** | speaking 状态中下发 barge-in 信号（mock 事件） | 嘴型立即停止（≤1 帧）、状态迁移正确、残余振幅被清零；随后新轮次正常 | yes |
| **C8** | 跨轮隔离：第 N 轮的 mock 振幅/事件不作用于第 N+1 轮状态 | 每轮嘴型/状态从干净状态开始；无跨轮振幅残留、无状态串扰 | yes |

### Layer D — 资源与基线

| ID | 步骤 | 预期 | 可自动化 |
|---|---|---|---|
| **D1** | 本地测量 截图→提交（抵达 mock server 收到完整请求体）耗时，重复 ≥20 次取 P50/P95 | P95 ≤ 2s（本地、含压缩）；单次 >2s 需记录原因 | yes（脚本计时，partial 于环境噪声） |
| **D2** | 连续 50 轮"截图→识别(mock)→语音回复"循环，采样 RSS（macOS：`psutil` 或 `/usr/bin/time -l`） | 内存单调增长有界（脚本断言末 10 轮均值相比第 10 轮增长 < 阈值，默认 20MB，实施时可标定）；无句柄数持续增长 | yes |
| **D3** | MAC_RESOURCE_USAGE 度量方法（规范，非新工具）：在本机用 `/usr/bin/time -l <启动命令>` 或 `psutil.Process().memory_info().rss` 周期采样 + `lsof -p <pid>` 句柄数，结果写入 `docs/engineering/product-v1/admin-visual-v2/evidence/v0_resource_usage.txt` | 证据文件含：时间戳、commit、峰值 RSS、句柄数、每轮均值延迟 | yes |
| **D4** | 冻结基线 diff 审计：`git diff e51d9a5..<实施HEAD> --stat` 逐文件审查 | `gateway/app/audio.py`、`app/protocol.py`（音频面）、VAD/节奏相关模块**零字节改动**；若架构要求触碰 gateway，逐文件列出并说明为何不影响音频路径，QA 复审裁定 | yes |
| **D5** | 实施前后各跑一遍回归基座：`admin_security_tests.py`(29)、`product_v1_integration.py`(33)、`behavior1_tests.py`(≥60) | 前后结果逐项一致、全绿，输出留档于 `admin-visual-v2/evidence/` | yes |

## 3. MOCK_CONTRACT（本地 mock 服务合同）

**mock 视觉服务**（建议 `tools/vision_mock_server.py`，stdlib `http.server`，仅绑 `127.0.0.1:0`，启动打印端口）：

- `POST /vision/recognize`：接受 `multipart/form-data` 或按协议报告的图像编码格式（二选一，以协议报告为准）。校验请求含合法 JPEG 字节后返回：
  ```json
  {"ok": true, "object": "string", "scene": "string", "text": "string|null", "confidence": 0.0-1.0}
  ```
  字段名/嵌套以协议报告验证过的形状为准——mock 是形状的**从属方**，实施时若协议报告有出入以协议报告为准。
- 模式（`--mode` 或 `POST /__mode` 切换）：`normal`（固定 fixture）/ `oversize`（返回 413）/ `bad-request`（400）/ `error500` / `slow`（可配 delay ms，用于 A3/D1）/ `inject-payload`（识别字段中返回 prompt 注入文本，供 A5）/ `malformed`（返回非法 JSON）。
- 请求日志环形缓冲 + `GET /__log`：记录时间戳、body 长度、Content-Type——供 C3 零调用断言与 D1 计时。**日志只存元数据，不落图像字节**。
- 不写盘、不代理外网；任何指向 127.0.0.1 之外的真实视觉 API 调用视为缺陷（可由 mock Qwen/网关日志交叉证明）。

**mock 音频振幅源**（复用同一 mock server 或独立小端点）：

- `WS /__amplitude` 或消息通道下发确定性振幅序列（如 [0, 0.2, 0.8, 0.1, 0]）与状态事件（speaking-start / speaking-end / barge-in），供 C6–C8 逐点断言；序列可脚本化注入。

**mock Qwen**：复用 `gateway/tests/mock_qwen_server.py` / `mvp_mock_qwen.py` 既有 drivable 模式，不新造。

## 4. PASS_CRITERIA（B5 阶段通过标准）

1. **全部可自动化用例绿**：A 层单测、B 层集成、C 层 Node/脚本断言、D1/D2/D5 全部通过；`partial` 项的自动化部分通过且 manual 部分有留档说明。
2. **冻结基线 diff 审计干净**：D4 通过——gateway 音频/VAD/节奏相关文件零字节改动（或有经 QA 裁定的逐文件豁免清单）；D5 三套回归前后逐项一致。
3. **音频零回归证明**：B2/B3 的计数器与 behavior1 全量结果与基线逐项一致。
4. **独立评审 ≥1 次**：实施完成后由 QA（或另一名未参与者）以只读身份对照本计划复审实际 diff 与证据文件，出具 PASS/FAIL 结论并留档于本目录。
5. 全部网络交互仅指向 127.0.0.1 mock，且可由请求日志证明；无真实 Qwen / 真实云视觉调用。

## 5. MANUAL_GATES（本地无法测试，留待真实会话门禁）

| 项 | 为什么本地测不了 | 门禁方式 |
|---|---|---|
| 真实云视觉识别质量 | mock 只能证明链路与形状，识别准确率/鲁棒性取决于真实服务 | 后续真实会话抽样 ≥10 张真实图像，人工判定识别可用性；进入再评审 |
| macOS TCC 权限弹窗真实交互 | 自动化环境无法真实弹出/点击系统弹窗 | manual：真实 Mac 上走 C1 三分支并截图留档 |
| 真实摄像头硬件时序（分辨率/帧率/对焦） | mock 帧不代表真实帧特性 | manual：真机预览 5 分钟 + 一次真实截图，检查压缩输出与 D1 延迟 |
| 真实语音+视觉并发的主观体验（延迟感受、嘴型自然度） | 主观项 | manual：真人验收一轮，对照冻结基线的主观听感无退化 |

## 6. RE_ENGAGEMENT_NOTE（独立复审清单）

实施完成后，QA 以只读方式复审，将核对：

1. **diff 范围**：对照 D4，gateway 冻结音频路径任何触碰即 FAIL（除非有裁定豁免并逐行证明非音频影响）。
2. **计划符合度**：mock 视觉服务是否按第 3 节合同实现；测试文件是否真实可跑（QA 亲自执行，不采信声明）。
3. **作弊检测**：断言不得为变绿而弱化（如把 P95 阈值放宽、把注入断言改为仅检查不崩溃）；A5 注入用例的载荷必须真实包含攻击模板而非空串。
4. **证据留档**：D1/D2/D3/D5 的输出文件存在于 `admin-visual-v2/evidence/`，含 commit 号与时间戳。
5. **形状一致性**：vision 事件字段与协议报告逐字段比对；不一致处由协议报告裁决。
