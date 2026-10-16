# 个人学习老师 · Personal Learning Teacher

**一个可自行部署的 AI 个人学习老师（英语学习 / 课堂辅助方向）**，基于“小智 AI 学生课堂”项目整理发布。

*English: Personal Learning Teacher — a deployable AI personal-learning / classroom assistant (English-study oriented). This repository contains a PySide6 classroom desktop app, a local gateway service, and a set of teaching modules, built on the “小智 AI 学生课堂” codebase.*

---

## 主要能力（当前实现）

- **学生课堂应用**：选课、课节翻页、双语幻灯片（词汇 / 句子 / 练习）、单词跟读与练习判分、错题与笔记
- **音标 / IPA**：en-GB（RP）词典增强与“诚实缺失”标注
- **学习数据**：本地学习记录（笔记 / 错题 / 复习）、学习位置持久化与跨重启恢复（单用户本地存储，原子写入 + 损坏隔离）
- **书库 / 导入 / 校对 / 发布**：本地课程包扫描；离线解析（txt / md / pdf / docx / pptx / epub，OCR 不支持）；人工校对兜底；发布状态流转
- **数字人形象**：课堂内置自有 QML Canvas 2D 形象（无音频输入时不假造口型）
- **语音**：网关实时语音链路（Qwen realtime 接入，默认关闭，需本地配置）＋确定性 Mock 语音状态机（可离线）；本机老师列表（fail-closed）
- **管理后台**：老师 / 模型 / 知识库 / 教学 / 语音配置（admin-v4，需服务端运行）
- **教学模块库**：课程契约 v1（冻结 schema + 校验器）、教材 → 课程包构建、知识解析、记忆 / 知识库 / 策略 / 人设、多老师语音通道
- **主客户端（fork）**：基于 py-xiaozhi 的桌面客户端（GUI / TUI / CLI）

## 仓库结构

```
client/                  桌面客户端（PySide6）
  main.py                  ├─ 主客户端入口（py-xiaozhi fork 的基础客户端）
  classroom_main.py        ├─ 学生课堂应用入口（本项目主应用）
  src/ui/gui/qml/          ├─ 主客户端 UI（QML）
  src/classroom/           ├─ 课堂应用（数据模型 / QML UI / 内置课程数据 / 测试）
  src/avatar/  src/vision/ ├─ 数字人 / 视觉
  models/                  ├─ 语音识别模型（sherpa-onnx，Apache-2.0）
  documents/               ├─ 上游文档站源码
  classroom_app.spec       └─ 课堂应用打包配置（PyInstaller）
gateway/                 本地网关服务（aiohttp；WebSocket / HTTP；admin API）
modules/                 教学 / 知识 / 记忆 / 策略 / 语音 / 模型接入等模块库
tools/                   构建与流水线工具（classroom_* 系列 / 课程包迁移）
docs/engineering/        工程与验收文档（已脱敏）
```

**双入口 / 双 UI 说明**：`client/main.py` 与 `client/classroom_main.py` 是两个独立可运行的入口——前者为上游 fork 的基础客户端，后者为本项目核心的学生课堂应用；`client/src/ui/gui/qml`（主客户端 UI）与 `client/src/classroom/qml`（课堂 UI）为两套互不依赖的 QML 界面。

## 快速开始

（要求：macOS；Python 3.10）

```sh
# 客户端依赖
cd client
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 运行课堂应用
./.venv/bin/python classroom_main.py

# （可选）打包课堂应用（PyInstaller；产物未公证，仅本机使用）
./.venv/bin/pyinstaller --noconfirm --clean classroom_app.spec
```

```sh
# 网关（本地服务）
cd gateway
# 依赖与运行方式见 gateway/README.md；docker-compose.yml / config/config.json 均为
# 示例配置（含占位值），请按注释替换为你的环境参数后再启动。
```

**配置与密钥**：敏感配置走 `secrets/`（**永不入库**）或环境变量；示例见 `*.env.example` 与配置注释。**数据隔离**：课堂应用支持通过环境变量指向独立数据目录（见 `client/src/classroom/classroom_env.py`），便于测试与多环境使用。

## 状态说明

- 本仓库为**公开发布树（integration 分支产物）**；合入正式发布前接受独立审计。
- 课堂应用当前构建候选（build 6）状态为**复测候选**（尚在验收流程中），不代表“已验收”。
- 真实语音 / 真实模型链路默认关闭，需本地配置与授权；Mock 链路可完全离线运行。
- 视觉 / 摄像头与后台管理等能力依赖本地服务与权限。

## 本发布树未包含（有意排除）

- `client/libs/**` 原生二进制（libopus / webrtc_apm；许可文本未闭合）
- 音频与表情资源（`client/assets/sounds|emojis`；来源审查未完成）
- Live2D 专有资产（不随仓库分发；使用需遵循其自身许可条款）
- 教材 / 课件内容（版权受限）、内部运维脚本、备份与构建产物

## 许可证

- 本项目自有代码：**MIT**（见 `LICENSE`）
- `client/` 为 py-xiaozhi 的 MIT fork（Copyright (c) 2025 Junsen；`client/LICENSE` 保留原文）
- 第三方组件与义务：见 `THIRD_PARTY_LICENSES.md`；本发布树生成基线与脱敏说明：见 `PROVENANCE.md`

## 致谢

感谢 py-xiaozhi、sherpa-onnx、aiohttp、PySide6/Qt 等开源项目与社区模型工具。
