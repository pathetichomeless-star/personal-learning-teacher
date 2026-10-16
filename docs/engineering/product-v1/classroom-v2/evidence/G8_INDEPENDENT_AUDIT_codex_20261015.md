# G8 独立交叉审计报告（Agent F · codex CLI 只读执行）

> 执行时间：2026-10-15 03:33–04:0x（GMT+8）｜工具：codex-cli 0.162.0-alpha.17.2（ChatGPT.app 内嵌，独立于开发 Agent）
> 模式：正式只读交叉审计。首轮（原仓库路径）因嵌套沙箱（sandbox_apply: Operation not permitted）被诚实阻断、未冒充通过；
> 二轮于同卷 APFS 字节级克隆副本（/tmp/xz-audit-clone-1015/小智）执行，策略=只读纪律 prompt + 无内层沙箱 + 事后正/副本 git 与文件级比对（实证：正本零变化、副本零写入）。
> 会话 id=01a13bec-d6bd-7fe0-b8eb-a89b3c550137｜消耗 tokens=256,222｜原始全文（含过程日志）临时位于 /tmp/xz_g8_audit_v2.txt
> 审计对象：client/dist/build6-candidate/小智 AI 学生课堂.app｜结论：**CONDITIONAL PASS**

# Agent F 只读交叉审计报告

审计对象：`client/dist/build6-candidate/小智 AI 学生课堂.app`  
HEAD：`3754e502701713ee420e19b5badee5c421a77f88`  
分支：`p2b2-teacher-voice`

## 1. Git 状态与差异

- `git status --short`：115 项未提交变更，与包内凭据 `git_dirty_entries=115` 一致。[client/build_info/classroom_build_info.json:7-14](client/build_info/classroom_build_info.json:7)
- 分类：45 个修改、17 个删除、53 个未跟踪。
- `git diff --stat`：3740 行新增、2348 行删除。
- `git diff --check`：通过。
- 文档已披露受控未提交形态、文档整理删除及历史备份安排。[docs/PROJECT_WORKLOG.md:44-49](docs/PROJECT_WORKLOG.md:44)、[docs/PROJECT_WORKLOG.md:615-627](docs/PROJECT_WORKLOG.md:615)

发现：当前工作树混有大量非本交付范围变更，包括数字人运行时、gateway/modules、管理文档、历史文档删除及原型文件。它们与 FIX01 增量文件不完全一致，属于范围可追溯性风险；暂未发现由此破坏课堂包的证据。

## 2. 历史要求与代码事实

文档记录的修复链与代码相符：

- 退出修复：`engine.quit.connect(app.quit)`。[client/classroom_main.py:167-176](client/classroom_main.py:167)
- QML 退出状态机：`quitConfirmed`、`onClosing` 放行、`win.close()`。[client/src/classroom/qml/ClassroomWindow.qml:42-56](client/src/classroom/qml/ClassroomWindow.qml:42)、[client/src/classroom/qml/ClassroomWindow.qml:711-721](client/src/classroom/qml/ClassroomWindow.qml:711)
- 学习位置恢复后直接进入课堂页。[client/src/classroom/classroom_model.py:948-965](client/src/classroom/classroom_model.py:948)
- 学习记录原子落盘、600 权限、损坏隔离。[client/src/classroom/learning_record.py:41-72](client/src/classroom/learning_record.py:41)
- N4 固定文案存在。[client/src/classroom/qml/ProofreadPanel.qml:74-83](client/src/classroom/qml/ProofreadPanel.qml:74)
- N7 白名单文案不再写死条数。[client/src/classroom/qml/ImportPanel.qml:154-164](client/src/classroom/qml/ImportPanel.qml:154)

文档中“Build 6 仅为真人复测候选、正式验收未完成”的表述真实。[HUMAN_GUI_ACCEPTANCE_FIX01_REPORT.md:219-238](HUMAN_GUI_ACCEPTANCE_FIX01_REPORT.md:219)

## 3. 冻结面与重复开发

六个冻结文件均无 Git 差异：

- `gateway/app/turns.py`
- `gateway/app/qwen.py`
- `gateway/app/audio.py`
- `gateway/app/protocol.py`
- `gateway/app/ws.py`
- `gateway/app/behavior.py`

客户端没有导入 `gateway`、`modules`、`websockets`、`aiohttp`、`openai` 等运行时模块。Build 6 的 PYZ 中也未发现这些模块。

`client/src/classroom/classroom_api.py` 是受限环回 API 适配器，明确声明“不重新实现解析流水线”。[client/src/classroom/classroom_api.py:2-18](client/src/classroom/classroom_api.py:2)

真正的教材解析由离线工具调用既有 `modules.knowledge.parsers.parse_file`。[tools/classroom_offline_pipeline.py:5-13](tools/classroom_offline_pipeline.py:5)、[tools/classroom_offline_pipeline.py:149-161](tools/classroom_offline_pipeline.py:149)

结论：未发现客户端重造 gateway/modules 解析流水线。客户端保留课程契约校验镜像，属于已声明的冻结副本。

## 4. 测试证据真实性

抽查结果：

- `test_round02_fixes.py` 使用真实模型状态、持久化文件和字幕计数；退出链断言已修正为空断言的问题。[test_round02_fixes.py:96-114](client/src/classroom/tests/test_round02_fixes.py:96)、[test_round02_fixes.py:133-164](client/src/classroom/tests/test_round02_fixes.py:133)、[test_round02_fixes.py:203-228](client/src/classroom/tests/test_round02_fixes.py:203)
- `test_learning_restore_fix01.py` 检查 JSON 实际写入、重启后恢复及损坏文件隔离。[test_learning_restore_fix01.py:67-90](client/src/classroom/tests/test_learning_restore_fix01.py:67)、[test_learning_restore_fix01.py:101-116](client/src/classroom/tests/test_learning_restore_fix01.py:101)
- `test_voice_mock.py` 检查精确事件序列、未授权 real-online 拒绝及零 socket 连接。[test_voice_mock.py:50-61](client/src/classroom/tests/test_voice_mock.py:50)、[test_voice_mock.py:78-110](client/src/classroom/tests/test_voice_mock.py:78)

未发现抽查测试使用空断言或单纯恒真条件冒充通过。部分 QML 检查属于源码结构断言，不能替代完整运行时验证。测试脚本本身会写入 evidence JSON，例如 `test_voice_mock.py:119-129`；本次未执行测试。

## 5. 包内一致性

- `tools/classroom_build_info.py --print` 重新计算得到的 `source_revision` 与记录一致：

`1aa9292148d2fc508c449b6114cf9463e726a953d47f53a6844865444f913069`

- 源码侧、`.app/Contents/Resources/`、非 bundle 目录中的 `classroom_build_info.json` 三者 SHA-256 一致。
- QML、课程数据、manifest、schema 等 18 个直接资源全部与源码逐字节一致；抽查 `ClassroomWindow.qml` SHA-256 一致。
- `Info.plist` 为 `2.0.0 / build 6`。
- `codesign --verify --deep --strict` 通过；签名类型为 arm64 ad-hoc，无 Team ID。

限制：30 个源文件中部分 Python 文件被编译进 PyInstaller CArchive，无法用普通文件 SHA-256 直接比对。报告自身也把“包内 PYZ 逐模块哈希比对”列为待办。[HUMAN_GUI_ACCEPTANCE_FIX01_REPORT.md:59-65](HUMAN_GUI_ACCEPTANCE_FIX01_REPORT.md:59)

我通过 CArchive 只读检查确认包内字节码包含 `engine.quit` 与 `app.quit` 的连接序列，以及 `classroom_model` 的 `logExitConfirmed`、`resumeLastLearning` 符号。

## 6. 数据安全、费用与许可证

### 通过项

- 未发现项目自有源码、课堂资源或包内资源中的 API key、Bearer 凭据、私钥或真实模型 token。
- PYZ 中无 `openai`、`qwen`、`websockets`、`aiohttp`、`requests`、`gateway`、`modules` 模块。
- `VoiceMockSession` 的 real-online 模式未注入授权适配器时直接拒绝。[client/src/classroom/voice_mock.py:145-157](client/src/classroom/voice_mock.py:145)
- 课堂默认使用本地 Mock，不产生付费模型调用。

包内 QtNetwork 的通用 PEM/证书字符串属于 Qt 框架资源，不是项目凭据。

### 已知许可证缺口

- `gateway/`、`modules/`、`tools/` 等自有代码许可证仍待产品负责人决定。[THIRD_PARTY_LICENSES.md:8-10](THIRD_PARTY_LICENSES.md:8)
- English-learning-workbench 应用主体许可证未核实，内容许可有明确限制。[THIRD_PARTY_LICENSES.md:37-44](THIRD_PARTY_LICENSES.md:37)
- 运行镜像许可证未审计。[THIRD_PARTY_LICENSES.md:46-49](THIRD_PARTY_LICENSES.md:46)
- Build 6 实际捆绑 PySide6/Qt，但 `THIRD_PARTY_LICENSES.md` 未见对应 Qt/PySide6 归属说明，属于补充合规缺口。

## 7. NAS 与离线能力

课堂入口默认使用独立本地数据目录，并拒绝正式 `py-xiaozhi` 数据目录。[client/classroom_main.py:13-20](client/classroom_main.py:13)

老师列表网络能力仅在配置显式开启、地址为环回地址且有 token 时启用；默认配置关闭。[client/src/classroom/classroom_env.py:4-12](client/src/classroom/classroom_env.py:4)、[client/src/classroom/classroom_model.py:999-1013](client/src/classroom/classroom_model.py:999)

`GATEWAY_OPEN=False`，PDF/DOCX/PPTX/EPUB 导入服务默认关闭。[client/src/classroom/classroom_model.py:49-65](client/src/classroom/classroom_model.py:49)

结论：课堂应用启动、课程学习、学习记录恢复不需要 NAS 地址或 NAS 服务。可选环回服务不等于 NAS 依赖。

## 8. 数字人与课件解析的真实程度

- 课堂包中的 `TeacherAvatar.qml` 明确是静态占位形象，文案为“数字人未启用 · 静态占位形象”。[client/src/classroom/qml/TeacherAvatar.qml:4-5](client/src/classroom/qml/TeacherAvatar.qml:4)、[client/src/classroom/qml/TeacherAvatar.qml:36-43](client/src/classroom/qml/TeacherAvatar.qml:36)
- `speechAvailable` 恒为 `False`，语音演练为本地 Mock，不调用真实模型。[client/src/classroom/classroom_model.py:330-351](client/src/classroom/classroom_model.py:330)
- 课件解析链在工具和后端中是真实实现，Build 6 内置的是离线生成后的课程、manifest 和知识库快照；学生端任意用户教材导入仍因 gateway 门禁关闭而不可用。

因此：

- 数字人适配器实现存在，但未接入学生课堂包的真实数字人运行时。
- 课件解析实现存在，但 Build 6 主要展示离线生成结果，不能宣称已完成真实用户教材导入闭环。
- 以上限制均已在文档和 UI 中诚实披露，并非隐瞒。

## 9. 其他交付风险

复验启动器把 `.app` 路径硬编码为原桌面路径，在当前克隆目录中不可直接复用。[启动复验（隔离数据）.command:8-13](client/dist/build6-candidate/启动复验（隔离数据）.command:8)

这不影响 `.app` 本体，但影响交付包迁移后的复测便利性。

## 结论

**结论：CONDITIONAL PASS（有条件通过，允许作为真人复测候选包）。**

通过依据：

- Build 6 版本、source_revision、资源一致性、签名和关键退出修复均可只读复核。
- 六个 gateway 冻结文件未改。
- 未发现客户端重复解析流水线、付费模型调用或项目凭据。
- 学习记录、恢复、退出状态机及 N4/N7 修正有真实代码和测试断言支撑。
- 不依赖 NAS，可离线启动和学习。

条件与发现：

1. 真人 GUI 复测尚未完成，不能宣布正式验收通过。
2. 学生课堂当前仍是静态数字人、本地文字/Mock 语音；真实数字人、真实语音、任意教材导入仍未闭环。
3. 包内 PYZ 尚未完成逐模块哈希级独立核验。
4. 工作树 115 项变更中存在大量与本交付无关的历史/数字人/gateway/docs 变更，后续应保持范围隔离。
5. PySide6/Qt 等捆绑依赖的许可证归属需要补充。

本次严格执行只读操作，未执行测试、未启动应用、未写入或删除文件、未进行任何 Git 写操作。期间有一次只读管道拼接导致 Python `SyntaxError`，未产生文件系统影响。


