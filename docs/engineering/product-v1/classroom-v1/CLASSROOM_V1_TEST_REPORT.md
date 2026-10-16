# CLASSROOM V1 测试与实机验证报告（TEST REPORT）

> **TASK_ID = CLASSROOM-V1 ｜ 本文件为 Classroom V1 单一权威主文档（LIVING DOCUMENT）**
> 依 ONE_TASK=ONE_LIVING_DOCUMENT 制度（见 `docs/PROJECT_WORKLOG.md` 使用规则第 8 条），本任务全部同文档的
> 有效技术正文已收敛至本文件 **§6 任务全生命周期收敛**；SPEC / ARCHITECTURE / FIX01 / FIX02 四份报告正文已收敛至本节（原件于 2026-10-13 经产品负责人批准删除，
> 备份与恢复位置见 §6.7）；两份独立 QA 报告按「独立审计证据」例外保留原件。后续 Agent 默认只读本文件即懂全历史。

**分支** `p2b2-teacher-voice`　**基线 HEAD** `a608b4b`（含已验收 P2-1 修复）
**环境** Mac 本机；隔离配置 `XIAOZHI_DATA_DIR`；本机 Mock 网关（127.0.0.1:61110/61111/8119）；
`QWEN_MODE=mock`；三个授权位 = 0；真实模型请求 = 0；NAS 未触碰。

---

## 1. 新增课堂测试（46/46 PASS）

命令：
```
cd client && QT_QPA_PLATFORM=offscreen ./.venv/bin/python src/classroom/tests/test_classroom_v1.py
→ CLASSROOM_V1_TESTS: 46 checks, 46 PASS, 0 FAIL
```

覆盖（节选，完整清单见脚本）：
- **布局**：T4 窗口加载；T5–T8 四档断点（wide/medium/compact/narrow）；T9 可缩放；
  T10 紧凑宽度下关键按钮存在；T11 数字人不可用仍显示占位说明且课件可用。
- **课程/翻页**：T1–T3 课程加载与来源标注；T12 选课自动进入首课时；T13–T16 翻页与边界不越界。
- **字幕/词汇**：T17 词汇页更新面板；T18 字幕含老师讲解。
- **练习/文字**：T19–T21 练习判定与幂等；T22–T24 文字提交与「本地模拟回应」标注。
- **隔离/恢复**：T25–T27 切课不残留上一门课数据；T28–T30 结束学习后状态归零。
- **老师**：T31–T32 从 Mock 网关读到老师列表（真实端点）；T33 保存写入 `TEACHER_ID`；T34 保存不建连。
- **降级**：T35 课程文件缺失不崩溃；T36 JSON 损坏不崩溃。
- **切换标签**：T41–T43 字幕/词汇/笔记切换与非法值拒绝。
- **保护**：T37 冻结六文件 SHA256 与基线一致；T38 课堂模型不导入 `websockets`/`aiohttp`；
  T39/T40 课堂模块与入口不引用受保护数字人文件。

> 本轮修复的两个真实缺陷（由测试发现）：
> 1. 切换课程未清空**字幕**导致上一门课残留（T26）→ 已修；
> 2. `@Property` 取值被误当函数调用（Python 侧）导致 QML 绑定报错 → 已修。

## 2. 既有回归（全绿）

| 套件 | 结果 |
|---|---|
| `client/tests/test_client_ui_transcript.py` | **48/48** |
| `client/tests/test_gui_transcript_live.py`（Qt offscreen） | **25/25** |
| `gateway/tests/teacher_voice_seam_tests.py` | **60/60** |
| `gateway/tests/teacher_context_seam_tests.py` | **83/83** |

历史已知失败未变化（本轮不新增失败）。

## 3. 实机验证（§13 A–P）

真实启动：`XIAOZHI_DATA_DIR=<隔离> client/.venv/bin/python client/classroom_main.py --size <wide|fullscreen|compact>`

| 项 | 结果 | 证据 |
|---|---|---|
| A 正常窗口打开 | **PASS** | 实机截图 `screenshots/classroom_wide.png`（2752×1708，Retina） |
| B 可最大化/恢复 | **PASS** | 全屏实测几何 `x=0,y=33,w=1470,h=923`（整屏）；截图 `classroom_fullscreen.png`（2940×1846）；界面含「全屏/退出全屏」 |
| C 小窗口无关键元素被遮挡 | **PASS** | `classroom_compact.png`（1752×1492）底部按钮完整、「展开字幕」可见；测试 T10 |
| D 首页直接选择老师 A | **PASS** | 课堂内「更换老师」弹窗；T31/T33（真实端点+真实配置写入） |
| E 切换老师 B | **PASS** | `selectTeacher`+`saveTeacher`；Mock 环境现有 A/B 两位 |
| F 选择本地课程与课时 | **PASS** | T12；「选择课程」弹窗 |
| G 浏览连续多页课件 | **PASS** | T13–T16 |
| H 英中文同时正确显示 | **PASS** | 截图中央区 `reservation … I have a reservation under the name Li. / 我有一个以李为名的预订。` |
| I 完成一次文字练习 | **PASS** | T19–T21；截图为练习前一页 |
| J 看到练习反馈 | **PASS** | T20（「答对了！解析：…」） |
| K 切换字幕/词汇 | **PASS** | T41–T43；右侧三标签 |
| L 结束学习并返回 | **PASS** | T28–T30 |
| M 保存老师不自动联网 | **PASS** | T34；T38（模型不导入任何 WS 库） |
| N 数字人不可用仍能上课 | **PASS** | T11；截图中「数字人未启用·静态占位形象」与课件同屏正常 |
| O 无真实模型时文字课堂可用 | **PASS** | 全流程本地演示课程可跑通 |
| P 无外部模型请求、无令牌泄露 | **PASS** | 课堂模型零网络；学生 UI 无 Token/URL 字段；令牌仅隔离配置 |

**截图**（`docs/engineering/product-v1/classroom-v1/screenshots/`）：
`classroom_wide.png` / `classroom_fullscreen.png` / `classroom_compact.png`
（由**真实窗口**经 `screencapture -R` 抓取，非离屏渲染）

## 4. 「1006」只读定位（§12）

对运行中的 Mock 网关做只读 WS 探测（客户端 `websockets`，令牌来自隔离文件）：

| 场景 | 实测 | 含义 |
|---|---|---|
| 无令牌 | `InvalidStatus HTTP 401` | **正常拒绝** |
| 错令牌 | `InvalidStatus HTTP 401` | 正常拒绝（与缺令牌同码，无枚举 oracle） |
| 正确令牌 + 老师未绑定模型 | `InvalidStatus HTTP 409` | **正常拒绝**（`realtime_model_not_configured` → 中文「该老师未绑定实时语音模型」） |
| 正确令牌 + 未知老师 | `InvalidStatus HTTP 409` | 正常拒绝 |
| 正确令牌 + 缺 teacher_id | `InvalidStatus HTTP 409` | 正常拒绝 |

结论（源码 `gateway/app/teacher_voice.py:487-497`）：**老师解析发生在 WS 升级之前**，
失败时返回 `web.json_response(...)`，因此客户端看到的是 HTTP 状态（`InvalidStatus`），**不是 1006**。

- **正常拒绝**：401/409，客户端映射为中文可读提示（`client/src/utils/teacher_errors.py`）。
- **异常断开（1006）**：只可能发生在**升级成功之后**（上游/中继异常中断 TCP），属传输层异常，
  与「未绑定模型」无关；本轮不在课堂链路内（课堂不建连）。
- **自动连接缺陷**：课堂**不存在**自动建连；`saveTeacher()` 仅写配置（T34）。R3-2C 已修「保存即重连」，
  本轮回归无新增自动连接缺陷。

## 5. 诚实边界

- 课堂为**本地演示**：课程数据随包、教学文字为确定性本地脚本、练习判定为本地规则；
  **不代表**真实教材、真实 AI 生成或真实语音。
- 未执行真实实时语音（`REAL_AUDIO_HUMAN_TEST = PENDING`）。
- 数字人未启用；「静态占位形象」不等于数字人可用，更不等于口型同步通过。
- 本报告为**开发方自验**，不构成独立 QA。

---

## 6. 任务全生命周期收敛（LIVING SECTION · 2026-10-13 PROJECT-DOC-MERGE-01 收敛）

> 本节为 Classroom V1 全部同任务文档的**正文级整合**（非摘要）：继承初始需求、保留架构决策与规格要点、
> 补齐 FIX01/FIX02 修复历史与独立 QA 结论、建立缺陷台账与修订时间线。§1–§5 为 V1 初交付时的原始测试正文（保留不动）。

### 6.1 任务目标与非目标（源：PRODUCT SPEC §1，已收敛）

- **目标**：不懂编程的普通用户在 Mac 上打开小智课堂后，不配置 Token/URL/JSON，即可
  选老师 → 选课 → 浏览课件 → 看双语文字 → 完成本地练习 → 结束返回。
- **非目标（不伪装已做）**：真实实时语音、真实 ASR/TTS、正式教材接入、私有学生记忆、
  数字人真人级口型、管理后台功能下移。
- **前提**：V4 管理后台继续负责老师/模型/凭据/课程/知识库；学生端只负责学习操作。
- **定位演进**（独立 QA §6 结论）：V1 是**独立运行的学生端外壳**（独立入口/UI/配置写路径/无数字人耦合），
  内容为随包演示课 → 经 FIX01/FIX02 后满足「可交付给普通学生的独立客户端」基线
  （READY_FOR_HUMAN_ACCEPTANCE = YES，见 6.4）。

### 6.2 架构决策（源：ARCHITECTURE，已收敛）

- **独立入口 + 新目录、纯新增、零改动**：`client/main.py` 的 GUI 链路与
  `manager.py`/`AvatarLive2D.qml`（携带未提交数字人改动）均为受保护文件；按任务书要求改走纯新增：
  `client/classroom_main.py`（独立入口）+ `client/src/classroom/`（model / data/courses.json / qml 六件
  ClassroomWindow·TeacherPanel·TeacherAvatar·CourseArea·InteractionPanel·theme/ClassroomTheme / tests）。
  **回滚性**：删除这两个新增对象即完全撤销，不影响既有客户端与后台。
- **解耦**：课堂 QML 不 import 既有 `ui/gui/qml/{theme,controls,components}`，自带 `ClassroomTheme` 单例；
  唯一复用=配置层（V1 初交付经 config_manager，FIX01 起改课堂自有 `classroom_demo.json`，见 6.5）
  与网关老师列表端点（真实 HTTP + 真实令牌校验）。
- **数据流**：ClassroomWindow(QML) ↔ ClassroomModel(QObject)——课程/课件读 courses.json；教学脚本确定性；
  练习本地判定；老师列表为基于 `urllib` 的只读 GET（5s 超时、不带代理）；响应式档位由窗口宽度派生。
- **零网络硬约束**：模型内不含 `websockets`/`aiohttp` 导入（T38 断言）；课堂不建立任何 WS/语音连接。
- **后台边界**：学生端只消费老师列表 + 本地演示课程；正式课程契约预留
  `course{id,title,subject,level,description,lessons[]}` / `lesson{id,title,slides[]}` / `slide{type,...}`，
  `source` 由 `local-demo` 切 `admin-knowledge` 时学生端零改动；未新增任何后台接口。

### 6.3 产品规格要点（源：PRODUCT SPEC §2–§8，已收敛）

- **窗口与响应式**：初始 1360×850；可缩放最小 560×480；支持全屏；四档断点——
  wide ≥1180 三栏 / medium 900–1179 左栏收窄+右抽屉 / compact 640–899 头像条+「展开字幕」/
  narrow <640 头像条+底部核心操作。任一档位：核心操作不堆叠遮挡、内容可滚动、按钮状态可见。
- **界面五区**：A 顶栏（课堂名/老师/课程/演示徽标/全屏/高级设置——**不显示令牌或地址**/退出）；
  B 左老师区（静态占位回退/名称/**教学语言·音色**/状态/更换老师）；C 中央课件区（cover/vocab/sentence/
  practice/summary 五页型+翻页+重复讲解）；D 右互动区（字幕/词汇/笔记三标签、双语对照）；E 底部核心操作。
- **老师选择（复用 R3-2C）**：列表来自 `GET /xiaozhi/v1/teacher/list`（恒时令牌校验）；学生不接触
  teacher_id/Token/WS URL；「保存并切换」只写客户端配置、**绝不自动建连**；不可用原因为普通人可读中文。
- **课件与练习（本地演示）**：courses.json（3 课 5 课时）；练习即时判定+解析（本地确定性规则）；
  文字提交标注「（本地模拟回应）」；切课清空上一门课字幕/词汇/笔记/练习状态。
- **数字人边界**：只提供稳定容器，未就绪时静态占位；数字人异常不得导致白屏或课件消失；
  未修改任何既有未提交数字人文件。
- **安全硬约束**：学生入口不显示 WS/MQTT/Token/API Key；三授权位 = 0；`QWEN_MODE=mock`；
  真实模型请求=0；保存设置不触发连接；冻结六文件与数字人未提交文件未触碰（T37–T40）。

### 6.4 修订时间线（版本演进全历史）

| 版本 | 提交 | 内容 | 验证与 QA 状态 |
|---|---|---|---|
| **V1 初交付** | `6ea179e`（20 文件 +2680 纯新增） | 独立学生课堂：`classroom_main.py` + `src/classroom/**` + `.command` 入口；本文件 §1–§5 全部测试即此版本 | 开发方 46/46 + 回归 48/25/60/83 全绿 + 实机 A–P 全 PASS；**独立 QA（根目录报告，例外保留）105/105 通过，发现 P1×1、P2×4、P0=0**：P1=`.command` 终端暴露+dev venv+/tmp 默认路径；P2-1 narrow(620) 布局破损（10 控件越界）；P2-2 compact(860)「结束学习」右溢 57px；P2-3 「学科 —」显示缺口（网关白名单无 subject）；P2-4 medium(1000) 输入框压至 65px |
| **FIX01** | 代码 `d185c28`（14 文件 +1717/−136）+ 文档 `c298a4f` | ① P1 免终端 `.app`（PyInstaller onedir，403→155 MB，剪裁 QtWebEngine 等；`classroom_app.spec`+`tools/build_classroom_app.sh`；ad-hoc 签名）② 入口级 fail-closed 重构：`classroom_env.py` 独立演示目录（指向正式 py-xiaozhi 目录→图形化中文说明+**退出码 3**）；弃用 config_manager，改课堂自有 `classroom_demo.json`（600 原子写；allow_teacher_list 必须布尔真、地址必须环回+`/teacher/list` 结尾、令牌仅进 HTTP 头；缺失/损坏/伪造→零请求）③ 布局修复（根因：窄档老师条取整宽 + Basic 按钮 implicitWidth=100 恒定）：窄档 96px 固定条、次级操作折叠「更多」、按钮宽度自适应；**560–1360 十档离屏横扫零越界** ④ 老师信息诚实（「教学语言 X · 音色 Y」，不再把 language 冒充 subject）+ `started` 门禁（未开始不产生讲解） | 开发方 46/46+40/40+52/52+12/12 全绿；冻结六文件/数字人文件/正式配置 UNCHANGED |
| **FIX02** | `3754e50`（位于 worktree 分支 `workbuddy/p2b2-teacher-voice-f0edf42f`） | 唯一产品改动 `client/src/classroom/qml/CourseArea.qml`（+31 −6）：单词+IPA 由单 Text 改为可换行 `Flow` 中两个 `width=min(implicitWidth, flow.width)`、`wrapMode: WrapAnywhere` 自适应 Text——IPA 无空格必须 WrapAnywhere；无 elide/clip，闭合斜杠不丢 | 真实 cocoa 渲染探针 86/86：正式课件 reservation+IPA 在 560–1360×全屏七档不裁剪（620 IPA 右缘 379.3 / 视口 590）；长词三例断行无丢字；46/46+40/40 回归；冻结/数字人/正式配置 UNCHANGED |
| **FIX02 独立复验** | （根目录报告 `CLASSROOM_V1_RELEASE_FIX02_INDEPENDENT_QA.md`，例外保留） | 复核 FIX01 独立 QA 项在 FIX02 下仍全部通过；4 词×7 档=56 项布局框越界 0.0px；**FIX02 报告 §3.2「−31.8px」判定为报告数字陈旧/口径标注错误，实质不越界（订正待办）** | `INDEPENDENT_QA = COMPLETED`；**`READY_FOR_HUMAN_ACCEPTANCE = YES`**（含 1 项流程提示，不构成阻断） |
| **Build 3 .app（当前交付）** | 未入库（`/dist` 在 .gitignore） | `client/dist/小智 AI 学生课堂.app`：包内 build_info=`2.0.0 build3`、包内 `CourseArea.qml`=`eb016add…`（FIX02 版）；旧包另存 `…app.pre-fix02`（主可执行 `08171ef…`）；FIX02 报告记录的 2026-10-12 重打包为中间件（包内 QML=`bd3eed75…`、主可执行 `146e47a3…`） | Finder 双击 8/8 无终端；`env -i` 独立启动；指向正式目录→退出码 3；真实模型请求=0 |

### 6.5 缺陷台账（全历史单点）

**已关闭（8）**

| 缺陷 | 发现 | 关闭于 |
|---|---|---|
| 切换课程字幕残留上一门课（T26） | V1 开发测试 | V1 初交付已修 |
| `@Property` 取值被误当函数调用（QML 绑定报错） | V1 开发测试 | V1 初交付已修 |
| P1 启动入口：`.command` 终端暴露 + 依赖 dev venv + /tmp 默认路径 | 独立 QA 105 项 | FIX01（`.app` 免终端 + fail-closed 隔离） |
| P2-1 narrow(620) 布局破损、10 控件越界 | 独立 QA | FIX01（96px 固定条 + 菜单折叠，十档零越界） |
| P2-2 compact(860)「结束学习」右溢 57px | 独立 QA | FIX01 |
| P2-3 「学科 —」显示缺口（language 冒充 subject） | 独立 QA | FIX01（「教学语言·音色」口径） |
| P2-4 medium(1000) 输入框压至 65px | 独立 QA | FIX01（fillWidth 实测 388px） |
| P2 `LONG_WORD_IPA_RENDER` 窄窗单词+IPA 截断（560=−89.3px / 620=−29.3px） | FIX01 独立 QA（唯一遗留 P2） | FIX02（Flow+WrapAnywhere）+ 独立复验确认 |

**未关闭（流程/产品级，非缺陷回归）**

1. **V1-HUMAN-GUI-TEST = PENDING（V1 链自身遗留，与 V2 复测分别记录）**：V1 独立 QA 时点定义的真人 Finder 双击/观感评估。
   其对象与口径已被后续 V2 验收链（ROUND01 → Build 3 复测）**覆盖演进**；是否单独补做由产品负责人裁定（见 WORKLOG 待办第 7 项）。
   注意：Build 3 第二轮复测属 **CLASSROOM-V2-ACCEPTANCE** 任务（当前=暂停，产品负责人明确暂停待文档整理通过后再决定恢复），
   其入口为根目录《HUMAN_GUI_ACCEPTANCE_FIX01_RETEST_GUIDE.md》，不属本 V1 链待办。
2. **FIX02 提交未合并**：`3754e50` 位于 worktree 分支，主检出源码仍为 pre-FIX02；交付 `.app` 已含 FIX02。
3. FIX02 报告 §3.2「−31.8px」数字订正（独立复验已判定不越界，属报告口径陈旧）。
4. 产品级未实现（SPEC §9，非缺陷）：真实实时语音、真实 ASR/TTS、正式教材/后台课程接入、
   私有学生记忆、数字人真实呈现与口型——均需 PO 授权或后续版本。

### 6.6 当前交付物与累计测试矩阵

- **交付物**：`client/dist/小智 AI 学生课堂.app`（Build 3）＋ 代码提交链 `6ea179e → d185c28+c298a4f → 3754e50`
  ＋ 一页指南（release-fix01/USER_GUIDE_CLASSROOM_ONE_PAGE.md）＋ 前后对照截图与 test-results ＋ 本文档。
- **累计验证**：开发方课堂测试 46/46、FIX01 新增 40/40、ui_layout_probe 52/52、包体 E2E 12/12、
  FIX02 探针 86/86、独立 QA 105/105、FIX02 独立复验（56 项布局 0.0px 越界）、
  既有回归 48/48+25/25+60/60+83/83、Finder 双击 8/8。
- **安全基线（各轮一致）**：Tina 冻结六文件 SHA-256 全等（e18a0d08…/13d4800d…/c2218a2c…/944e2d5a…/
  dde9d427…/6d705960…）；数字人未提交文件 UNTOUCHED；真实模型请求=0；NAS 零操作；无 git 危险操作。

### 6.7 文档取代关系（本节收敛来源）

| 原文档 | 处置 |
|---|---|
| `CLASSROOM_V1_PRODUCT_SPEC.md` | 正文已收敛至 §6.1/§6.3 → **已删除**（PROJECT-DOC-MERGE-01 批准清理；恢复=项目外 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v1/CLASSROOM_V1_PRODUCT_SPEC.md`，tracked 者另可 `git checkout HEAD --` 取回历史版） |
| `CLASSROOM_V1_ARCHITECTURE.md` | 正文已收敛至 §6.2 → **已删除**（PROJECT-DOC-MERGE-01 批准清理；恢复=项目外 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v1/CLASSROOM_V1_ARCHITECTURE.md`，tracked 者另可 `git checkout HEAD --` 取回历史版） |
| `release-fix01/CLASSROOM_V1_RELEASE_FIX01_REPORT.md` | 正文已收敛至 §6.4–§6.6 → **已删除**（PROJECT-DOC-MERGE-01 批准清理；恢复=项目外 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v1/release-fix01/CLASSROOM_V1_RELEASE_FIX01_REPORT.md`，tracked 者另可 `git checkout HEAD --` 取回历史版） |
| `release-fix02/CLASSROOM_V1_RELEASE_FIX02_REPORT.md` | 正文已收敛至 §6.4–§6.6 → **已删除**（PROJECT-DOC-MERGE-01 批准清理；恢复=项目外 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v1/release-fix02/CLASSROOM_V1_RELEASE_FIX02_REPORT.md`，tracked 者另可 `git checkout HEAD --` 取回历史版） |
| 根目录 `CLASSROOM_V1_INDEPENDENT_QA_REPORT.md` | **例外保留**（独立审计证据）；结论在 §6.4/§6.5 引用 |
| 根目录 `CLASSROOM_V1_RELEASE_FIX02_INDEPENDENT_QA.md` | **例外保留**（独立审计证据）；结论在 §6.4/§6.5 引用 |
| `release-fix01/USER_GUIDE_CLASSROOM_ONE_PAGE.md` | **有效指南**（.app 一页操作），继续独立维护 |
| `CLASSROOM_V1_HUMAN_ACCEPTANCE_GUIDE.md` | **历史版本**（.command 时代验收指南，已被 .app 取代）→ **已删除**（PROJECT-DOC-MERGE-01 批准清理；恢复=项目外 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v1/CLASSROOM_V1_HUMAN_ACCEPTANCE_GUIDE.md`，tracked 者另可 `git checkout HEAD --` 取回历史版）；现行真人验收入口属 V2 验收链（RETEST_GUIDE） |
| 根目录 `HUMAN_GUI_ACCEPTANCE_FIX01_RETEST_GUIDE.md` | 属 **CLASSROOM-V2-ACCEPTANCE** 链现行操作入口（非本 V1 链文档，此处仅作指向） |
| `docs/engineering/product-v1/classroom-v1/qa-independent/`、`release-fix0*/evidence|screenshots|test-results` | **原始证据**，不收敛不移动 |

（§6 收敛完成于 2026-10-13，PROJECT-DOC-MERGE-01 批 1。）
