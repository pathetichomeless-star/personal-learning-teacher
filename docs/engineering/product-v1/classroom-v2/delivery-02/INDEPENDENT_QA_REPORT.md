# CLASSROOM V2 · DELIVERY GATE 02 — 独立 QA 报告

- **状态：NOT_COMPLETED（独立 QA 未完成，本报告不构成任何签收）**
- 生成时间：2026-10-12 23:50 (UTC+8)
- 被验收对象：`client/dist/小智 AI 学生课堂.app`（v2.0.0 build 2）
- 基线 HEAD：`3754e502701713ee420e19b5badee5c421a77f88`（分支 `p2b2-teacher-voice`，68 项 uncommitted，未做任何 git 写操作）
- 结论性质：本报告仅登记事实与剩余工作。**开发方任何自验数字（含 314/314、57/57 等）均不作为独立判定依据。**

## 1. NOT_COMPLETED 原因

独立 QA 代理（fresh-context 对抗式复核）在执行中被额度限制中断：

```
429 您的使用量已超出频率限制，将在 2026-10-13 14:35:22 UTC+8 重置
```

代理存活 6m19s 后终止，未产出任何独立 QA 证据文件。**总控不代替其签收。**

## 2. 十项验收项状态登记（全部 PENDING，待独立 QA 执行）

| # | 验收项 | 状态 | 说明 |
|---|---|---|---|
| 1 | Finder 启动/退出/重启/无终端 | **PENDING** | 开发方有 `tools/classroom_finder_open_check.sh` 8/8 证据（delivery-02/screenshots/v2_finder_open.png），须独立重跑 |
| 2 | 560–1360px + 全屏真实点击、弹窗越界、可读性、空态 | **PENDING** | 开发方 `ui_pages_probe` 57/57、`ui_layout_probe` 52/52 均不替代；且历史教训：越界检查须覆盖"弹窗打开时" |
| 3 | 书库→导入→解析→校对→草稿→课堂完整离线流程（真实 GUI 操作） | **PENDING** | 须区分测试夹具与真实 GUI 操作，逐屏留痕 |
| 4 | EPUB 安全、PDF 多栏、Schema、哈希交叉兼容、课程来源绑定 | **PENDING** | 服务端侧已有开发方套件，须独立复跑（`PYTHONPATH= .venv(网关侧 xiaozhi-p2b2)`） |
| 5 | 学习记录退出/重启后恢复与课程隔离 | **PENDING** | 须用真实 .app 做完全退出重启验证，非单元测试夹具 |
| 6 | 语音 Mock 字幕/打断/错误恢复；数字人静态降级、禁止假口型 | **PENDING** | 开发方 voice_mock 事件日志仅为开发证据 |
| 7 | 包内关键资源/Schema/源码快照一致性 | **PENDING（总控已预复核，见 §3）** | 独立 QA 应自行重算，不引用本报告数字 |
| 8 | 学生 .app 无管理端凭据/生产密钥/未经批准管理服务 | **PENDING（总控已预复核，见 SECURITY_REVIEW_REPORT.md §2）** | 同上 |
| 9 | Tina 冻结六文件、数字人保护文件、NAS 与正式配置未变 | **PENDING（总控已预复核，见 §3.1）** | 独立 QA 须自算哈希 |
| 10 | 独立安全复核：最小权限子应用、IPC、会话密钥、路由白名单、资源隔离 | **PENDING** | 详见 SECURITY_REVIEW_REPORT.md；**该复核未通过前安全门禁维持关闭** |

## 3. 总控预复核（供独立 QA 参照，非独立 QA 结论）

证据全部落在 `docs/engineering/product-v1/classroom-v2/delivery-02/workspace-manifest/`：

1. **冻结与保护面**（总控于 23:40 亲自 shasum）：冻结六文件 git diff 为空且哈希==基线；数字人 5 文件哈希==基线；HEAD 未移动；暂存区空（boundary_check 13/13 复跑 PASS）。
2. **包内一致性**：包内 38 个随包源资源（22 QML + 2 份 schema JSON + 其余）与源码树逐字节比对 **38/38 MATCH**（`package_source_consistency.json`）；包内 build_info 的 28 个源文件哈希与当前源码树回验 **28/28 一致**（构建后源码未被改动）；Info.plist 2.0.0/build 2 == 包内构建信息。
3. **已知诚实边界**：Python 源码经 PyInstaller PYZ 打包，未做包内 PYZ 逐模块哈希比对（列为独立 QA 待办 P3）；包内二进制仅做了粗粒度 strings URL 筛查。

## 4. 恢复计划

- 额度重置后（2026-10-13 14:35 UTC+8 之后）重新拉起独立 QA 代理，按 §2 逐项执行并落盘证据。
- 独立 QA 未完成前：**MAC_APP_BUILD_REPORT.md 中的"构建事实"可采信（属可复算哈希链），但整体 DELIVERY GATE 02 不关闭**；产品负责人可依据 HUMAN_GUI_ACCEPTANCE_GUIDE.md 先行真人操作（真人验收与独立 QA 并行不互替）。
