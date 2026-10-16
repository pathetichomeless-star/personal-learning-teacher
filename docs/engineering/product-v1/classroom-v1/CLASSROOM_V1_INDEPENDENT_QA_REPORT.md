# CLASSROOM V1 独立 QA 报告（INDEPENDENT QA REPORT）

- 报告人：独立 QA（WorkBuddy 会话；未参与本功能任何开发）
- 日期：2026-10-12（GMT+8）
- 对象：Mac 学生课堂 V1（预期开发提交 `6ea179e`）
- 结论等级：**CONDITIONAL PASS（本机体验可用；分发入口与窄窗布局存在阻断级/可用级缺陷）**
- 独立检查总量：**105 项**（full 93 / fresh 7 / corrupt 5；另复跑开发方 46 项作参考基线，未计入独立通过）

---

## 0. 结论摘要（先读这一段）

1. **安全结界整体成立**：隔离配置存在时，缺失/损坏目录均为 fail-closed（明确中文提示 + 全程零网络）；课堂模型零 WebSocket、零语音、零真实模型请求；部署令牌仅存在于隔离配置本体，未出现在 UI、控制台输出、日志或截图中；保存老师=仅写 `TEACHER_ID`，无任何自动连接。
2. **本机功能复验 105/105 通过**（真实窗口 + 真实鼠标/键盘事件注入）：老师 A/B 选择与保存、课程切换、五类课件页、双语显示、选择题、文字提交、字幕/词汇/笔记切换、课间隔离、结束与重启、数字人缺席降级。
3. **发现 1 个阻断级（分发性）+ 4 个可用级缺陷**：
   - P1（分发阻断）：`打开学生课堂.command` 不符合"普通用户不接触终端"目标——`.command` 由系统路由至**终端**执行（本轮 macOS 弹窗原文即"在'终端'中打开文稿"），且依赖**开发机专用 venv** 与 **/tmp 默认目录**。
   - P2-1：**narrow(620 宽) 布局破损**——课件区整体离屏，翻页/结束/全屏/退出不可达，老师切换不可达。
   - P2-2：**compact(860 宽)「结束学习」被裁剪**（右侧越出 57px，截图为证）。
   - P2-3："学科"显示缺口——左栏恒显示「学科 — · 音色 X」（网关白名单无 `subject` 字段；对话框把 `language` 当"学科"显示）。
   - P2-4：medium(1000 宽) 输入框被压缩至 65px（implicitWidth=200）。
4. 四个直接回答：
   - **允许产品负责人开始人工体验**：允许（本机）；请先阅读 §6 的三条注意事项。
   - **Mock 范围**：老师列表=本机 Mock 网关；隔离配置=本机 Mock 令牌；课程与讲解=随包本地演示（确定性脚本）；无任何真实模型/语音；数字人=静态占位；1006 拒绝路径复现亦基于 Mock。
   - **是否必须先修启动入口/隔离**：面向"本机体验"→ 可先体验（隔离路径安全）；面向"发给普通用户/学生机"→ **必须先修 P1 启动入口**（窄窗布局建议同批修）。
   - **其他可用性缺陷**：见 §5（P2-1~P2-4 + 观察项）。

---

## 1. 基线核实（BASELINE / COMMIT_SCOPE）

| 项 | 实测 | 判定 |
|---|---|---|
| 实际 HEAD | `6ea179efbcb66eefb05139acff619198f72ed76a` | 与预期 `6ea179e` **一致** |
| 分支 | `p2b2-teacher-voice`（未合并/未打标签，与既有状态链一致） | 一致 |
| 提交内容 | `6ea179e`：20 文件 / +2680 行，**纯新增**（client/classroom_main.py、client/src/classroom/**、`打开学生课堂.command`、docs/…/classroom-v1/**、3 张开发截图） | 纯 additive，未改既有文件 |
| 工作树受保护修改（数字人） | 5 个已修改文件 + 6 个既有未跟踪项；本轮 QA 前后 **哈希前缀逐一相同**（f3cb7ea3 / 1243b98d / bd2de04b / 32c1c16a / 8ac51456） | **未触碰** |
| 冻结六文件 | 6 个 SHA-256 与开发测试内置基线**逐一相同**（e18a0d08… / 13d4800d… / c2218a2c… / 944e2d5a… / dde9d427… / 6d705960…），QA 前后一致 | **未触碰** |
| NAS | 未连接、未部署、未备份（全程零 NAS 操作） | NO |
| 生产客户端配置 | `~/Library/Application Support/py-xiaozhi/config/config.json`：SHA-256 `301f5244…`、mtime Oct 9 23:03 —— QA 前后**完全未变** | 未误改 |
| dev 隔离配置 | `/tmp/xz-acc-f1/client/config/config.json`：SHA-256 `2ee380c6…`、mtime Oct 12 04:12 —— 未变（本轮为只读消费） | 未误改 |
| git 危险操作 | 未执行 reset/clean/stash；QA 新增文件仅为 `CLASSROOM_V1_INDEPENDENT_QA_REPORT.md` 与 `docs/.../qa-independent/`（证据归档） | 合规 |

---

## 2. 启动与安全审计（静态优先，启动前完成）

### 2.1 三个关键文件静态结论

**`client/打开学生课堂.command`**（7 行，755 可执行，无 BOM）
```sh
#!/bin/sh
cd "$(dirname "$0")" || exit 1
: "${XIAOZHI_DATA_DIR:=/tmp/xz-acc-f1/client}"
export XIAOZHI_DATA_DIR
exec ./.venv/bin/python ./classroom_main.py --size wide
```
- **双击必然打开终端窗口**：`.command` 由 LaunchServices 交给 Terminal.app 执行（本轮 macOS 弹窗原文："……无法打开，因为不允许 'Sandbox' 在'终端'中打开文稿"——系统自身即把 .command 归类为"在终端中打开"）。脚本无任何窗口隐藏手段。→ **不符合"普通用户不接触终端"**（P1）。
- **依赖 /tmp 测试目录**：默认 `XIAOZHI_DATA_DIR=/tmp/xz-acc-f1/client`（dev 于 2026-10-12 04:01 创建的隔离目录，现仍存在；重启即失）。目录消失不崩溃（§3.2 fresh 实测），但老师功能不可用。
- **依赖开发机专用 Python venv**：`client/.venv`（Python 3.10.20 + PySide6 等，本机实测存在）。普通用户机器没有该 venv → 脚本以 shell 报错收场。

**`client/classroom_main.py`**（112 行）
- 无 `XIAOZHI_DATA_DIR` 自守卫：直接以 `python classroom_main.py` 运行且未设环境变量时，`initialize_config()` 会落回 `platformdirs` **正式用户目录**（见 2.3）。隔离完全依赖启动器。
- 无 WebSocket/语音/数字人代码路径；启动序列 `refreshTeachers()` 为同步 HTTP（网关不可达时 UI 线程阻塞最多 5s——观察项）。
- 支持 `--geom-file`（供外部截图），本轮用于独立三尺寸取证。

**`client/src/classroom/classroom_model.py`**（532 行）
- 全模块唯一网络调用点：`urllib` GET `<WEBSOCKET_URL→http(s)>/teacher/list`，头 `X-Teacher-Token`；显式 `ProxyHandler({})` 绕过系统代理。
- `speechAvailable` 为常量 `False`；无任何 ws/语音/付费代码（grep 证实无 `websockets/aiohttp`、无密钥字段读取）。
- `saveTeacher()` 仅写 `SYSTEM_OPTIONS.NETWORK.TEACHER_ID`，无连接动作。

### 2.2 隔离矩阵（独立实测）

| 场景 | 实测结果 | 证据 |
|---|---|---|
| `XIAOZHI_DATA_DIR` 指向**不存在**目录 | 目录被创建、生成默认配置（`WEBSOCKET_URL=None`）；老师页显示「未配置服务地址（请在隔离配置中设置网关地址）」；**Mock 网关零请求**；窗口正常、本地课程可用 | fresh 模式 7/7，`logs/driver_fresh.json`、`shots/fresh_after_boot.png` |
| 隔离配置 **JSON 损坏** | 损坏文件被备份为 `config.json.corrupt-<TS>`；回退默认（无 URL）；零网络；应用正常启动 | corrupt 模式 5/5，`logs/driver_corrupt.json` |
| 隔离配置**缺失/空** | 同上（新目录=无配置）→ 明确提示 + 零网络 | 同上 |
| `XIAOZHI_DATA_DIR` **未设**（入口自守卫缺失） | 代码落回正式用户目录 `~/Library/Application Support/py-xiaozhi`（读取正式配置，含真实 `WEBSOCKET_URL`）。本机因正式配置 `TEACHER_VOICE_TOKEN` 不存在，`refreshTeachers` 在发起前终止（"未配置部署令牌"）——**结果安全但不等于 fail-closed 设计**。 | 代码路径 `resource_finder.py:79-91` + 只读核验 |

> 判定：**ISOLATION_FAIL_CLOSED = PARTIAL**。`.command` 双击路径恒定设置隔离变量（不触发回退）；但入口本身无"未隔离则拒绝启动"的断言。建议（仅登记，不施工）：`classroom_main.py` 启动时校验 `XIAOZHI_DATA_DIR` 已设且不等于正式数据目录，否则拒绝启动并给出中文提示。

### 2.3 令牌与"零外呼"审计

- 部署令牌不出现在 UI/日志/截图：105 项检查中多次全量扫描可见文本（含对话框逐字："部署令牌由隔离配置预置……不会在此显示"）；QA 令牌字样仅存在于（a）隔离配置本体、（b）QA 自建的 mock/driver 源码。控制台输出与 QA 日志目录零命中。
- **零外部付费请求**：整个 QA 期间（含产品入口三尺寸运行）Mock 记录到的请求只有两类：`GET /xiaozhi/v1/teacher/list`（仅环回 127.0.0.1）与人为发起的 WS 拒绝探测（§6-G）。`unexpected=0`、无任何非环回目标。
- `.command` 等效直跑（受控 shell）：命中 dev 环回网关 `127.0.0.1:61110` 的 `teacher/list`（dev 网关日志 13:28:25 新增一行 `Python-urllib/3.10 → 200`），**未触碰 NAS/生产**。

---

## 3. 独立 GUI 复验（真实窗口 + 真实事件）

### 3.1 方法与口径（必须区分）

| 类别 | 本轮定义 | 本轮执行 |
|---|---|---|
| 真实 GUI 自动化 | 真实屏幕窗口；QTest 真实鼠标点击（打在渲染后的真实 item 坐标上）、QKeyEvent 真实键入；产品 QML/Model 原样加载，零修改 | ✅ 93+7+5 项 |
| 产品入口实跑 | `classroom_main.py --size wide/fullscreen/compact`（与 `.command` 同入口）真实启动 + 在屏 `screencapture`（Retina 2×） | ✅ 三尺寸 |
| 模型/单元测试 | 直调模型方法的脚本测试 | 开发方 46/46 本机复现（**仅作参考，不计独立通过**） |
| 静态代码审查 | §2 各条 | ✅ |
| 人工未测 | 真人双击 Finder、真人观感 | **PENDING**（见 §7） |

期间发现的驱动侧技术事实（供后续复现者）：Qt delegate（ListView/Repeater 委托项）**不经 `findChildren(QObject)` 可达**，必须走视觉树（`contentItem().childItems()` 递归）——第一轮全量遍历曾因此漏检弹窗行，修正后对话框两行老师真实渲染可见（`shots/probe2_dialog.png`）。

### 3.2 十四步复查结果

| # | 项目 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | 启动 Mac 学生课堂 | PASS | `CLASSROOM_READY size=wide`；三尺寸 `GEOM_READY` |
| 2 | 正常窗口 / 全屏 / 恢复 | PASS | `fullscreen=true`（几何 0,33,1470,923=整屏）→ 退出恢复 1360×808 |
| 3 | 小窗口按钮无遮挡 | **FAIL** | 860：结束学习右溢 57px；620：10 个控件越界（详见 §5） |
| 4 | 选择模拟老师 A | PASS | 弹窗两行真实渲染；点击行 A → `selectedTeacherId=tch_qa_a` |
| 5 | 切换模拟老师 B（名称/学科/音色/保存） | PASS（含一处显示缺口） | 名称/音色正确；磁盘 `TEACHER_ID: tch_qa_a→tch_qa_b`；左栏"学科 —"缺口见 P2-3 |
| 6 | 切换不自动联网 | PASS | 保存前后 Mock 请求增量=0；全程 `WS_REFUSE=0` |
| 7 | 选择课程及课时 | PASS | 酒店英语→数字与时间（状态变化证实点击生效）；课时行点击生效 |
| 8 | 连续翻页（英/中/单词/练习） | PASS | 5 页序列 cover→vocab→sentence→practice→summary；断言精确到文案（如 "It's half past seven."+“现在是七点半。”） |
| 9 | 完成选择题 | PASS | 点击 "A. half past seven" → "答对了！解析：…" + 笔记新增 |
| 10 | 字幕/词汇/笔记标签切换 | PASS | 真实点击三标签，`activeTab` 与内容同步（词汇页=本课单词） |
| 10b | 文字练习 | PASS | 键入 "It is half past seven." + 回车 → 字幕"我：…"＋"（本地模拟回应）…"；笔记新增 |
| 11 | 换课不残留 | PASS | 切换后渲染文本无旧课字样（half past/七点半/Telling time=0 命中）；答案清空、笔记清空；仅含新课封面讲解 |
| 12 | 数字人未启用课件仍显示 | PASS | "数字人未启用 · 静态占位形象"与课件同屏 |
| 13 | 结束课堂并重启 | PASS | 结束后状态归零＋空态提示；重选酒店英语第 2 课→封面渲染 |
| 14 | 无真实模型可用文字课程 | PASS | 全程零真实模型/语音；本地演示课程全流程跑通 |

### 3.3 响应式几何测量（四档，控件级）

| 档位 | 控件数 | 越界 | 控件重叠(>2px) | 挤压 | 备注 |
|---|---|---|---|---|---|
| wide 1360×808 | 15 | 0 | 0 | 0 | — |
| medium 1000×740 | 16 | 0 | 0 | **1**（输入框 65px/implicit 200px） | 四档断点判定全部正确（wide/medium/compact/narrow） |
| compact 860×700 | 15 | **1**（结束学习 x=817..917，超窗 57px） | 0 | 0 | 截图右侧文字被截断 |
| narrow 620×620 | 15 | **10**（全屏/高级设置/退出课堂、课件区上一页/重复讲解/下一页、底部展开字幕/重复讲解/下一页/结束学习） | 0 | **1**（输入框 41px） | 课件区整体位于 x≈620 起（离屏）；老师切换按钮在 narrow 不可用 |

> 说明："文本不重叠"在控件级无重叠、无文字互相覆盖（截图肉眼复核一致）；但"按钮无遮挡"在 860/620 两档不成立。开发方 T10 测试只断言"按钮文本存在"，对可达性/越界是盲的——这正是本项的独立增量发现。

### 3.4 三尺寸界面证据（全部可查 `docs/.../qa-independent/shots/`）

| 尺寸 | 内容渲染（grabWindow） | 在屏截屏（screencapture） |
|---|---|---|
| wide | `wide_360.png` | `wide_on_screen_screen.png`、`product_wide_screen.png` |
| fullscreen | `fullscreen.png` | `product2_fullscreen_fullscreen.png` |
| compact | `layout_compact.png`（可清晰看到"结束学习"被右缘截断） | `product2_compact_screen.png` |
| narrow（补充） | `layout_narrow.png`（课件区离屏的整体破损实况） | —（在屏帧被其他窗口遮挡，未采用） |

失败复现步骤（P2-1/P2-2）：
```
cd client && PYTHONPATH= XIAOZHI_DATA_DIR=<隔离> ./.venv/bin/python classroom_main.py --size compact   # → 右下「结束学习」被窗口右缘截断
cd client && PYTHONPATH= XIAOZHI_DATA_DIR=<隔离> ./.venv/bin/python classroom_main.py --size narrow    # → 主区仅剩老师头像条；课件/翻页/结束/全屏/退出均在窗口右外侧
```

---

## 4. 风险项 A–H 逐条结论

| # | 问题 | 结论 |
|---|---|---|
| A | 第二个演示程序，还是独立学生客户端？ | **介于两者**：它是**独立运行的学生端外壳**（独立入口/独立 UI/独立配置写路径/无数字人耦合），本地链路完整可用；但内容为随包演示课、无真实模型/语音、启动入口未产品化、narrow 布局破损 → 当前定位=**可体验的独立演示客户端**，尚不满足"可交付给普通学生的独立客户端"（差距见 P1/P2）。 |
| B | 双击 .command 符合"不接触终端"？ | **否**。机制上 `.command` 交由终端执行（系统弹窗原文为证）；若终端缺少目录访问权限，用户还会看到英文/系统级报错——正是"普通用户接触终端"的反例。**真实 Finder 双击本轮未能完整模拟**（沙箱 TCC 拦截，见 §8 限制），列为人工待测。 |
| C | 本地临时目录消失后仍安全启动或明确拒绝？ | **安全启动 + 明确提示**（"未配置服务地址…"，零网络、零回退）。功能降级：老师列表不可用，无自动恢复路径。 |
| D | 教师 ID / 隔离令牌 / 学生身份混用？ | 未发现混用：令牌只进 HTTP 头；教师 ID 只做选择→配置写入；课堂无"学生身份"概念；UI/日志/截图零泄露（93 项含逐快照扫描）。 |
| E | 语音按钮始终诚实禁用？ | **是**。按钮 `enabled=False`＋悬停原因："未接入真实实时语音模型…"；代码层无建连路径；实测零 WS 尝试。 |
| F | 课程与字幕来自同一当前课时？ | **是**。字幕/词汇随课时重建；换课后旧课字样 0 命中；笔记与答案同步清空。 |
| G | 1006 的拒绝路径 vs 原始断线原因 | **已验证**：老师路由的拒绝发生在 WS 升级**之前**——网关源码 `teacher_voice.py:487-497`（鉴权失败 401 / 解析失败 409，均为 `web.json_response`）；本轮以自建 Mock 独立复现（无令牌→`InvalidStatus HTTP 401`；错令牌→401（无枚举差异）；正确令牌→409）。**课堂自身零 WS 尝试**（Mock 全程 `WS_REFUSE=0`）。**尚未确定**：早前客户端场景中"原始 1006"的传输层根因本轮未复现、未归因（不在课堂链路内）。 |
| H | macOS 系统 UI 代理是否留有环境异常 | 只读核查：HTTP/HTTPS/SOCKS 代理开启 → `127.0.0.1:10808`，Xray（PID 41972）正常在听；例外表含 localhost/127.0.0.0/8/::1。**未见与课堂研发相关的异常残留**；本轮**未做任何**代理设置更改或重启，也未终止任何系统进程。另：课堂 urllib 显式绕过代理，与代理状态解耦。 |

---

## 5. 缺陷清单（仅报告，未施工）

| 级别 | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| **P1** | 启动入口 `.command`：终端暴露 + 依赖开发机 `client/.venv` + 默认指向 `/tmp/xz-acc-f1/client` | 文件内容；macOS 弹窗；`client/.venv` 实存（Py3.10.20） | 分发到普通用户机器即失败；"免终端"目标不成立 |
| **P2-1** | narrow(620) 布局破损：课件区离屏；翻页/结束/全屏/退出不可达；老师切换不可达 | `GEOM w620 outside=10`；`layout_narrow.png` | 最小窗口尺寸区间内课堂不可上 |
| **P2-2** | compact(860)「结束学习」超出右缘 57px，文字被截 | `GEOM w860 outside=1`；`layout_compact.png` | 关键"退出课堂流程"按钮不完整 |
| **P2-3** | "学科"显示缺口：左栏恒「学科 — · 音色 X」；对话框以 `language` 字段充当"学科" | 实测文本；网关白名单=4 字段（`teacher_id/display_name/voice_id/language`） | 与文档描述（"名称、学科·音色"）不符，观感缺陷 |
| **P2-4** | medium(1000) 输入框被压至 65px（占位提示被吞） | `GEOM w1000 squeezed` | 输入体验差 |
| 观察 | 启动即同步 HTTP（不可达时 UI 阻塞≤5s）；老师列表依赖 /tmp 配置存活；T10 类测试只查存在性不查可达性 | 代码 + 测试脚本 | 小 |

**P0：无。** 安全结界（隔离/禁令/零连接/零泄露）未被击穿。

---

## 6. 给产品负责人的三条注意事项（人工体验前）

1. **入口选择**：本机体验优先使用开发文档中的命令行方式（`XIAOZHI_DATA_DIR=/tmp/xz-acc-f1/client ./.venv/bin/python classroom_main.py --size wide`）——它与 `.command` 是同一入口且已实测可用；**不要**把 `.command` 当作最终交付形态（P1）。若手动双击 `.command`，请知晓它会打开终端窗口。
2. **重启后**：`/tmp/xz-acc-f1` 会被系统清空；届时课堂仍可打开、课程可上，但老师列表会显示"未配置服务地址"。这是**预期内的安全降级**，不是故障。
3. **语音/数字人**：语音按钮为刻意禁用的"诚实标注"；老师形象为静态占位。均属本轮已知边界。

另：本轮等效双击测试触发了一次 macOS 沙箱提示框（"……无法打开，因为不允许 'Sandbox' 在'终端'中打开文稿"），若仍在屏上，请手动点"好"关闭；Terminal.app 因此次测试处于运行状态（无残留脚本进程）。

---

## 7. 验收口径 / 边界声明

- 本报告为**独立 QA**：测试器、Mock、驱动均为本 QA 侧新建（`docs/.../qa-independent/scripts/`），未使用开发方的 46 项测试作为通过依据（仅复跑作对照，其 46/46 属实）。
- **真实**：真实 Qt 窗口、真实鼠标/键盘事件、真实产品入口进程、真实屏幕截取（Retina 2×）。
- **Mock**：老师列表网关（127.0.0.1:61933）、隔离令牌、课程数据本身为本地演示、教学文字为确定性脚本、1006 机制复现用 Mock。
- **未覆盖（人工待测 HUMAN_GUI_TEST=PENDING）**：真人 Finder 双击 `.command` 的端到端观感；真人 5 分钟自由使用评估；真实语音/数字人（本轮明确不在范围）。
- 已知工具性限制：沙箱 TCC 使 `open <.command>` 无法完整模拟 Finder 双击（弹窗为证）；个别在屏截图被同机其他窗口遮挡（已改用窗口内容渲染 + 重拍替代，并在 §3.4 标注）。

---

## 8. 最终状态块

```
BASELINE = HEAD 6ea179e(p2b2-teacher-voice)，与预期一致；工作树受保护数字人修改/未跟踪项与 QA 前逐一相同
COMMIT_SCOPE = 20 文件 +2680 行纯新增（classroom 应用 + 文档 + .command + 3 开发截图）；未改任何既有文件
MAC_APP_STARTUP = PASS（classroom_main.py wide/fullscreen/compact 实跑；macOS 将 850 高度约束为 808）
NO_TERMINAL_USER_ENTRY = FAIL（.command 经终端执行；依赖 client/.venv 与 /tmp 默认目录；真实双击列 HUMAN 待测）
ISOLATION_FAIL_CLOSED = PARTIAL（隔离变量已设→缺失/损坏目录均 fail-closed 且零网络；入口无自守卫，未设变量时读正式配置【本机无 dev 令牌故未外呼】）
TEACHER_PICKER = PASS（Mock 2 位老师真实渲染；对话框行真实点击可选）
TEACHER_SWITCH = PASS（A→B；磁盘 TEACHER_ID 落地；保存零增量请求；零 WS）
COURSEWARE_RENDER = PASS（cover/vocab/sentence/practice/summary 全渲染，截图在案）
BILINGUAL_TEXT = PASS（英文原文 + 中文释义/翻译逐页精确断言）
TEXT_PRACTICE = PASS（选择题判定+解析+笔记；键入提交+本地模拟回应标注）
TRANSCRIPT_AND_NOTES = PASS（三标签真实点击切换；内容与当前课时一致）
COURSE_ISOLATION = PASS（换课无旧课文字/答案/笔记残留）
RESPONSIVE_LAYOUT = FAIL（860 结束学习裁剪 57px；620 十控件越界、课件区离屏；1000 输入框压至 65px）
AVATAR_FALLBACK = PASS（数字人未启用时占位说明与课件同屏）
NO_AUTO_CONNECT = PASS（全程 WS 尝试=0；保存仅写配置）
REAL_MODEL_REQUESTS = ZERO
TINA_FROZEN = 未触碰（六文件 SHA-256 与基线一致，QA 前后同）
DIGITAL_HUMAN_FILES = 未触碰（5 文件哈希前缀 QA 前后一致）
NAS_CHANGED = NO
INDEPENDENT_QA = COMPLETED（105 项独立检查；发现 P1×1、P2×4、P0=0）
P0_P1_P2_REMAINING = P0 无；P1=启动入口产品化（终端/venv//tmp）；P2=narrow 布局破损、compact 按钮裁剪、学科字段显示缺口、medium 输入框压缩
HUMAN_GUI_TEST = PENDING
```

---

## 9. 证据索引（`docs/engineering/product-v1/classroom-v1/qa-independent/`）

- `shots/`：三尺寸内容渲染与在屏截图（wide/fullscreen/compact + narrow 补充）、关键过程帧（老师 B 保存后、练习作答、换课后、重启后、fresh/corrupt 启动）、沙箱拦截弹窗帧、弹窗渲染探针帧。
- `logs/`：`driver_full.json`（93 项逐条结果+几何+文本快照）、`driver_fresh.json`（7 项）、`driver_corrupt.json`（5 项）、`driver_full.out`（完整标准输出）、`qa_mock_requests.log`（全量请求与拒绝记录）、产品入口三尺寸控制台输出、几何 JSON。
- `scripts/`：`driver.py`（独立 GUI 驱动）、`qa_mock.py`（独立 Mock 网关）、`probe*.py`（delegate 可达性探针，含过程说明）。
- 报告本体：仓库根 `CLASSROOM_V1_INDEPENDENT_QA_REPORT.md`。

（完）
