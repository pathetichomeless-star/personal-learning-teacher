# CLASSROOM V2 — DELIVERY GATE 02 交付报告

**日期**：2026-10-12
**施工基线 HEAD**：`3754e502701713ee420e19b5badee5c421a77f88`（分支 `p2b2-teacher-voice`）
**工作树状态**：**未提交**（按授权，未 `git add` / 未 `git commit` / 未打标签；HEAD 未变动）
**报告性质**：**开发方自验报告**。其中的独立 QA 部分由**单独协商的复核代理**产出，见 §8 与 `delivery-02/INDEPENDENT_QA_REPORT.md`。

> 本报告按指令要求**以运行结果为主**，设计文档仅作索引。

---

## 1. 结论速览（A–F）

| # | 要求 | 状态 | 交付物位置 |
|---|------|------|-----------|
| **A** | 真正能双击打开的最新 V2 Mac `.app` | ✅ | `client/dist/小智 AI 学生课堂.app`（v2.0.0 build 2，158 MB） |
| **B** | 课堂/书库/导入/校对/老师选择的真实运行截图 | ✅ 19 张 | `delivery-02/screenshots/` |
| **C** | 非敏感测试教材的离线解析→课程草稿→课堂展示 | ✅ | `classroom-v2/demo/sample_textbook.md` + `client/src/classroom/data/demo/**` + 复算日志 + 截图 |
| **D** | Mock 双向对话的事件日志及 GUI 状态证明 | ✅ | `delivery-02/test-results/voice_mock_event_log.json` + 2 张截图 |
| **E** | 独立 QA 结果与仍受阻功能 | ✅ | `delivery-02/INDEPENDENT_QA_REPORT.md`（§8 摘要）；仍受阻功能见 §7 |
| **F** | 源码/安装包版本一致性、冻结六文件与数字人保护 | ✅ | `delivery-02/test-results/boundary_check.json`（13/13） |

---

## 2. 交付物 A — 可双击的 V2 Mac `.app`

```
路径        client/dist/小智 AI 学生课堂.app
版本        2.0.0（build 2）
大小        158 MB
源修订      source_revision = 745d898bf03f9416b8a3a2ec57b713c93980bf74519872971028c479b2b9c58f
             git_head = 3754e5027017（p2b2-teacher-voice），源文件 28 个
```

**Finder 双击验收（`tools/classroom_finder_open_check.sh`，8/8 PASS）**：用 `open`（等效双击、不经过终端）启动，随后验收：

- `F02 CFBundlePackageType=APPL`（前台应用）
- `F03` 未设置 `LSBackgroundOnly`
- `F04 Contents/MacOS` 仅 1 个可执行（无附加终端脚本）→ **结构性不可能弹终端**
- `F05` 双击后进程存活；`F06` **真实屏幕截图非空**
- `F07` 启动日志无 `FileNotFoundError` / `CLASSROOM_STARTUP_ERROR`
- `F08` 退出后无残留进程

真实屏幕截图：`delivery-02/screenshots/v2_finder_open.png`（可见 macOS Dock 与桌面，证明是真实窗口而非离屏渲染）。

**包体 E2E（`test_classroom_app_bundle.py`，16/16 PASS）**：包含 V2 全部新页面 QML（`B13`）、包内界面含 V2 特征（`B14`）、包内含构建信息（`B15`）、`Info.plist` 版本 == 构建信息版本（`B16`）、默认隔离目录=独立演示目录（`B07`）、未配置隔离 **零网络请求**（`B09`）、显式配置时**恰好 1 次环回请求**（`B10`）、指向正式目录 **退出码 3 + 拒绝启动**（`B11`）。

### 2.1 本轮修掉的 P0 级缺陷：包体启动即失败

**现象**（新引入，未发布过）：`.app` 启动即 `FileNotFoundError: .../Contents/Frameworks/src/classroom/course_schema.v1.json`。

**根因**：本轮把 `course_schema.py` 改为在 **import 期**读取同目录 `course_schema.v1.json`（单一机器可读事实源），但 `classroom_app.spec` 的 `datas` 未同步加入该 JSON。

**影响面**：若按原样交付，学生双击后只会看到"课堂未能启动"错误对话框。历史归档包（`.pre-fix02` / `.delivery-01-bak`）不含该 JSON 是因为它们构建于该改动之前，**不受影响**。

**修复**：`datas` 增加 `("src/classroom/course_schema.v1.json", "src/classroom")`；并在 spec 中加入**打包前置守卫**：`_REQUIRED_DATAS` 5 项（schema JSON、主窗口、V2 导航、随包课程、构建信息）任一缺失即 `SystemExit`，**不允许产出坏包**（构建日志 `DATAS GUARD OK: 5 项必需资源齐备`）。

---

## 3. 交付物 B — 真实运行截图（19 张）

| 页面/场景 | 宽屏 | 窄屏 620 |
|---|---|---|
| 书库（含**错误态**卡） | `v2_library_wide` | `v2_library_narrow620` |
| 导入（硬门禁横幅 + 能力表） | `v2_import_wide` | `v2_import_narrow620` |
| 导入 · 解析进度（真实阶段） | `v2_import_progress_wide` | — |
| 教材校对 | `v2_proofread_wide` | `v2_proofread_narrow620` |
| 课程发布（Mock）演练前/后 | `v2_publish_before_wide` / `v2_publish_after_wide` | `v2_publish_narrow620` |
| **老师选择**弹窗 | `v2_teacher_dialog_wide` | — |
| 课程选择弹窗 | `v2_course_dialog_wide` | `v2_course_dialog_narrow620` |
| 高级设置弹窗 | `v2_advanced_dialog_wide` | — |
| 语音演练（Mock）启用前/后 | `v2_voice_mock_before_wide` / `v2_voice_mock_after_wide` | — |
| 课堂（离线演示课程） | `v2_classroom_offline_demo_wide` | — |
| Finder 双击实机 | `v2_finder_open.png` | — |

驱动脚本：`client/src/classroom/tests/ui_pages_probe.py`（**57/57 PASS**，写完后自动产出上表截图与 `test-results/ui_pages.json`）。V1 回归探针 `ui_layout_probe.py` **52/52 PASS**（未被 V2 破坏）。

---

## 4. 交付物 C — 离线解析 → 课程草稿 → 课堂展示

**输入**：`docs/engineering/product-v1/classroom-v2/demo/sample_textbook.md`（非敏感自编教材，1325 字节，sha256=`32f3029c4162…`，2 课次：见面问好 / 告别与感谢，含词汇/句型/练习/小结标记）

**流水线**：`tools/classroom_offline_pipeline.py`（真实字节哈希 → 真实解析器 → 隔离 `KnowledgeStore` 提交 → `builder` 生成 → `assert_valid` fail-closed → 回读 store 复核绑定）

**独立复算证据**：`delivery-02/test-results/offline_pipeline_replay.txt`（另起临时输出目录重跑，7 阶段全部成功）

**真实产物**（`client/src/classroom/data/demo/`）：

```
library/crs_offline_demo_basics.course.json    2 课次 / 16 页，source=user-textbook
library/crs_offline_demo_basics.manifest.json  7 阶段全部成功 + needs_review 3 项
library/index.json
kb_snapshot/knowledge.json                     doc_id=doc_8ab3dff32a53
content_hash = 0ed82af7…（**裸 hex**，非 sha256: 前缀）
source_file_sha256 = 32f3029c…（原文件字节哈希，独立可复算）
needs_review = phonetic_unknown: hello / fine / goodbye（未编造音标）
```

> **可复现性说明（诚实口径）**：`source_file_sha256`、`content_hash`、抽取字符数、课次/条目数、`needs_review` 项均可逐位复算一致；`doc_id` 由**隔离 KnowledgeStore 在本次提交时生成**，因此**每用一个全新的库重跑会得到新的 doc_id**（如复算得到 `doc_08b4638077cb`）——这是"真实提交"的证据，而非不稳定缺陷。仓库内演示产物用的是它自己那次的 `doc_id`，其与课程 `source_doc_hash` 的绑定已由 `binding_check` 回读验证。

**课堂展示**：`v2_classroom_offline_demo_wide.png`（课程「离线演示：基础问候」第 1 课，第 1/8 页，右栏字幕为本地脚本生成的讲解）。

---

## 5. 交付物 D — Mock 双向对话（事件日志 + GUI 状态）

**GUI 入口**：底部栏「语音演练（Mock）」按钮（窄档折叠进「更多」菜单）。与始终不可用的「语音对话（不可用）」**并列且文案区分**，避免与真实语音能力混淆。

**硬边界**：默认**未启用**；启用后 `mode=local-mock`，**不联网、不调用任何真实模型、不采集麦克风音频**（`text_only=true`）；回复为**本地预设/回显**，回复文案自带「（Mock 回显）」标记。

**事件日志**（由**真实 GUI 输入 → 回车发送**驱动，非脚本直调）：`delivery-02/test-results/voice_mock_event_log.json`

```json
{ "mode": "本地模拟(Mock)", "state_after": "idle", "text_only": true, "event_count": 3,
  "events": [
    {"type": "final_transcript", "text": "hello",                                        "state": "thinking"},
    {"type": "teacher_speaking", "text": "（Mock 回显）我听到你说：“hello”。请继续练习。", "state": "speaking"},
    {"type": "teacher_done",                                                             "state": "idle"} ] }
```

截图 `v2_voice_mock_after_wide.png` 同时给出：横幅声明、`模式：本地模拟(Mock)`、`会话状态：idle`、`音频：未采集`、老师回复、**事件日志 3 条**。探针检查 `P12a–P12k` 全绿。

---

## 6. 交付物 F — 一致性、冻结六文件、数字人保护

`tools/classroom_delivery_boundary_check.py` → **13/13 PASS**（`test-results/boundary_check.json`）

| 检查 | 内容 | 结果 |
|---|---|---|
| A01/A02 | 冻结六文件（`gateway/app/{turns,qwen,audio,protocol,ws,behavior}.py`）工作树 == HEAD 且 git 状态干净 | PASS |
| B01 | 受保护数字人 5 文件 == R3-0 基线（逐字节） | PASS |
| C01/C02 | 暂存区为空；HEAD 仍为施工基线提交 | PASS |
| D01 | 课堂运行期源码**无非环回 URL 字面量** | PASS |
| D02 | 课堂运行期源码**无子进程能力**（`subprocess`/`os.system`/`Popen` 仅出现在测试套件） | PASS |
| E01–E03 | 包内含构建信息；**9 项运行期必需资源齐备（含导入期 schema JSON）**；包内 18 个随包资源**逐字节**等于构建信息所记 | PASS |
| E04/E05 | 当前源码集合 == 包内记录（打包后源码未被改动）；`git_head`/源文件数一致 | PASS |
| E06 | `Info.plist` 版本 == 构建信息版本（2.0.0 / 2） | PASS |

一致性凭据随包分发：`小智 AI 学生课堂.app/Contents/Resources/classroom_build_info.json`（含 28 个源文件的逐文件 sha256 与聚合 `source_revision`）。

---

## 7. 仍受阻的功能（如实公示，UI 显示真实原因）

| 功能 | 状态 | 运行期证据 / 原因 |
|---|---|---|
| 本机解析服务 / `/cls/knowledge/*` 白名单 | **未开放** | `GATEWAY_OPEN = False`；导入页横幅：「本机解析服务：未开放 —— 等待独立安全复核通过」；客户端 `.txt/.md` 为本地事实，`.pdf/.docx/.pptx/.epub` 标注"需本机解析服务（未开放）" |
| 学生端调用 `/admin/knowledge/*` | **结构上不开放** | 客户端白名单仅 8 条 `/cls/*`；AST 级断言：代码字面量中不存在 `/admin/` 与 `Authorization` |
| 真实课程发布（服务端路由） | **未实现** | 发布页为 Mock 演练；横幅声明「真实发布服务端路由本轮未实现」；状态文案「**未执行**真实发布」 |
| 真实实时语音 | **未接入** | `speechAvailable` 恒 false；「语音对话（不可用）」禁用并给真实原因；仅提供**明确标注**的 Mock 演练 |
| 真实 AI 老师在线状态 / 老师列表 | **需隔离配置** | 默认不联网，如实显示「老师列表未启用（演示模式默认不联网）」；老师列表为空（不硬编码假老师） |
| 扫描件 OCR | **不支持** | 能力表：「OCR 暂不支持（文字型解析已实现，扫描件需 OCR）」 |
| 数字人（Live2D） | **未启用（静态占位）** | `数字人未启用 · 静态占位形象`；适配器无真实音频电平时不伪造口型动画 |
| 安全子进程 / 最终发布 API | **待独立安全复核** | 运行期源码无子进程能力（D02）；解析服务与此类能力在独立安全复核通过前不接入 |

---

## 8. 交付物 E — 独立 QA

- 报告：`docs/engineering/product-v1/classroom-v2/delivery-02/INDEPENDENT_QA_REPORT.md`
- **诚实声明**：本次独立复核由**同一执行管线内、fresh context + 对抗式指令的复核代理**完成，**不是**第三方机构；报告内含其"未能验证"清单。
- 开发方自验汇总（**仅供参考，不可替代独立验收**）：

| 套件 | 结果 |
|---|---|
| `ui_pages_probe.py`（V2 五页面 + 弹窗 + Mock 演练） | 57 / 57 |
| `ui_layout_probe.py`（V1 四档布局回归） | 52 / 52 |
| `test_classroom_v1.py` | 46 / 46 |
| `test_classroom_release_fix01.py` | 40 / 40 |
| `test_course_contract_v1.py` | 20 / 20 |
| `test_classroom_api.py`（环回 SSRF / 恶意重定向） | 20 / 20 |
| `test_voice_mock.py` | 15 / 15 |
| `test_avatar_adapter.py` | 14 / 14 |
| `test_learning_record.py` | 13 / 13 |
| `test_classroom_app_bundle.py`（包体 E2E） | 16 / 16 |
| `gateway/tests/schema_v1_errata_tests.py` | 18 / 18 |
| `gateway/tests/knowledge_hash_format_tests.py` | 23 / 23 |
| `tools/classroom_delivery_boundary_check.py` | 13 / 13 |
| `tools/classroom_finder_open_check.sh` | 8 / 8 |

---

## 9. 本轮发现并修复的缺陷（如实登记）

| # | 严重度 | 缺陷 | 性质 | 修复 |
|---|---|---|---|---|
| 1 | **P0** | 打包 .app 启动即 `FileNotFoundError`（缺 `course_schema.v1.json`） | 本轮新引入 | `datas` 补入 + spec 前置守卫（缺资源即构建失败） |
| 2 | **P1** | 课程弹窗内容溢出窗口：宽档下「进入课堂」按钮落在窗口外（**不可达**） | V1 起既有（历次 QA 只测页面、从未在弹窗打开时测越界） | 弹窗内容显式赋 `contentItem` + `ListView` 加 `Layout.minimumWidth: 0`；探针新增 1360/620 弹窗越界检查 |
| 3 | **P1** | 弹窗/文本框继承系统深色调色板 → **黑底黑字不可读**（同时影响底部输入框） | V1 起既有 | 窗口级显式浅色 `palette`（覆盖全部 Popup） |
| 4 | **P2** | 老师弹窗 `ListView` 同类溢出（老师名/音色越长越明显） | V1 起既有 | 同 #2 |
| 5 | **P2** | 7 处用户可见字符串残留 Markdown `**` 标记 | 本轮 | 改为「」强调 |
| 6 | **P2** | 书库页头文案「全部经冻结契约 v1 校验」易被读成"全部通过" | 本轮 | 改为「全部按契约 v1 校验，未通过的照实显示原因」 |
| 7 | **P2** | 讲解脚本在字段缺失时产生空子句（`要点：。`、`看这个单词 hello ，`、`本课小结：。`） | 既有 | 改为诚实降级（「本页课件未提供要点清单」/「课件未提供音标，不编造」） |
| 8 | — | 探针自身缺陷：缺 `PySide6.QtQuick` 导入导致 `contentItem` 不可用；`QTest.keyClicks` 不接受 `QQuickWindow`；按"最后一个同名按钮"点击会点错卡片 | 探针 | 见 `ui_pages_probe.py` 注释 |

---

## 10. 边界声明（本轮全程）

- 冻结六文件（Tina）：**零改动**（A01/A02 逐字节 + git 状态）。
- 受保护数字人 5 文件：**零改动**（B01 与 R3-0 基线逐字节一致）。
- NAS：**未做任何修改**（本轮未执行任何 NAS/SSH 命令）。
- 真实付费模型请求：**0**（D01 无非环回 URL 字面量；包体 E2E `B09` 未配置隔离时零网络请求）。
- 正式发布服务端路由：**未实现、未调用**。
- git：**未 `add` / 未 `commit` / 未打标签 / 未 reset / 未 stash**（C01/C02）。

---

## 11. 复现方式（一条命令一条证据）

```sh
cd <project-root>

# 源码侧自验（277 项）
cd client
for t in ui_layout_probe ui_pages_probe test_classroom_v1 test_classroom_release_fix01 \
         test_course_contract_v1 test_classroom_api test_voice_mock \
         test_avatar_adapter test_learning_record; do
  PYTHONPATH= ./.venv/bin/python src/classroom/tests/$t.py 2>/dev/null | tail -1
done
cd ..

# 网关侧自验（41 项）
PYTHONPATH= <user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python gateway/tests/schema_v1_errata_tests.py
PYTHONPATH= <user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python gateway/tests/knowledge_hash_format_tests.py

# 打包 + 包体 E2E + Finder 双击 + 一致性/边界（37 项）
PY=<user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python sh tools/build_classroom_app.sh
cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/test_classroom_app_bundle.py; cd ..
sh tools/classroom_finder_open_check.sh
PYTHONPATH= <user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python tools/classroom_delivery_boundary_check.py

# 离线流水线复算（交付物 C）
PYTHONPATH= <user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python \
  tools/classroom_offline_pipeline.py \
  --textbook docs/engineering/product-v1/classroom-v2/demo/sample_textbook.md \
  --out /tmp/iq-offline-demo --course-id crs_offline_demo_basics
```
