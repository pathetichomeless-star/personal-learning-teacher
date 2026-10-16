# CLASSROOM V2 · DELIVERY GATE 02 — Mac .app 构建报告

- 生成时间：2026-10-12 23:50 (UTC+8)
- 性质：构建事实与**总控可复算哈希链**。UI/流程行为验收不在本报告范围（见 INDEPENDENT_QA_REPORT.md）。

## 1. 交付物

| 项 | 值 |
|---|---|
| 路径 | `<project-root>/client/dist/小智 AI 学生课堂.app` |
| 版本 | CFBundleShortVersionString **2.0.0** / CFBundleVersion **2** |
| 大小 | 约 155 MB（PyInstaller onedir 打包，Py3.10.20 + PySide6 6.10.1） |
| 构建源 | 分支 `p2b2-teacher-voice`，HEAD `3754e502701713ee420e19b5badee5c421a77f88` |
| 聚合源指纹 | `source_revision = 745d898bf03f9416b8a3a2ec57b713c93980bf74519872971028c479b2b9c58f`（28 个运行期源文件） |

## 2. 版本一致性哈希链（总控 2026-10-12 23:40–23:46 亲自复算）

```
① 包内 38 个随包源资源（22 QML + course_schema.v1.json×2 + 其余） == 当前源码树   → 38/38 MATCH
② 包内 build_info 28 源文件哈希 == 当前源码树（构建后源码未被改动）               → 28/28 一致
③ 包内 build_info.git_head == 当前 HEAD                                          → 3754e50… 一致
④ Info.plist 版本 == 包内构建信息版本                                            → 2.0.0/2 一致
⑤ boundary_check 13/13 PASS（含冻结六文件、数字人 5 文件、暂存区、D01/D02）
证据：docs/engineering/product-v1/classroom-v2/delivery-02/workspace-manifest/
      ├─ git_status_porcelain.txt   （68 项变更清单）
      ├─ file_hashes.txt / .json    （164 文件逐 sha256 快照；只读，无 git 写操作）
      └─ package_source_consistency.json
```

**诚实边界**：Python 源码在 PYZ 内，未做包内逐模块哈希比对（列为独立 QA 待办）；①②的等价性以"包内 QML==当前源码==构建时刻源码"链路间接覆盖 .py。

## 3. 本轮修复的 P0/P1（构建相关）

- **P0（已修+实测）**：首轮打包启动即 `FileNotFoundError: …/Contents/Frameworks/src/classroom/course_schema.v1.json`。根因：`course_schema.py` 改为 import 期读同目录 JSON，但 spec `datas` 未同步。修复：`classroom_app.spec` datas 补入 + 新增 `_REQUIRED_DATAS` 五项前置守卫（缺资源即 `SystemExit`，不产坏包）。
- **P1（已修+实测）**：弹窗 `ListView` 无界撑宽致按钮不可达（V1 既有）；Basic 样式深色模式黑底黑字（V1 既有）。修复：弹窗显式 `contentItem: ColumnLayout` + `Layout.minimumWidth: 0`；`ApplicationWindow` 显式浅色 `palette`。

## 4. 开发方侧测试记录（数字仅登记，不作独立结论）

- 包体 E2E `test_classroom_app_bundle.py` 16/16（B13–B16 为 V2 新增：V2 页面 QML 在包内/构建信息在包内/版本一致）
- Finder 等效双击 `tools/classroom_finder_open_check.sh` 8/8（截图 `delivery-02/screenshots/v2_finder_open.png`）
- 页面/布局探针 57/57、52/52；客户端 9 套件 277/277；网关 41/41

## 5. 重构建须知（后续轮次）

1. 先跑 `python3 tools/classroom_build_info.py`，再 `PYINSTALLER_CONFIG_DIR=/tmp/xz-classroom-pyinstaller bash tools/build_classroom_app.sh`（缓存目录必须仓库外；构建前移走 `dist/*`、`build/classroom_app`）。
2. 打包后**不得**再往 .app 内补文件（BUNDLE 末段已 ad-hoc 签名）；一切随包资源走 `datas`。
3. 每次重构建后必须重跑 `tools/classroom_delivery_boundary_check.py` 与包体 E2E。
