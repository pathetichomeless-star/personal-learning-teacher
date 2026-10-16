# P2-B2-R1 — Agent C 独立 QA 报告（整理稿）

> 说明：本文件是 **Agent C 交付结论的整理稿**（逐条归并其命题、结果与证据要点），
> 由总控转录，**非逐字原文**。若需逐字原文，请向 Agent C 会话索取。

- 角色：独立 QA / 对抗式验证（只读仓库 + 自建测试）
- 被测版本：`gateway/app/teacher_voice.py`，`git diff --stat HEAD -- gateway` = **+293/−30**
  （与 `06314f8` 的最终修订一致）
- 结论：**PASS**（0 P0 / 0 P1）

---

## 一、执行环境与方法

- 仓库 `<project-root>`；分支 `p2b2-teacher-voice`；HEAD 为 `d53c858` + 未提交改动
  （即 R1 修复工作树）。
- 运行：`<user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python`
  （`env -u PYTHONPATH`）。
- **未修改仓库任何文件**：全部测试脚本写在仓库外 `/tmp/p2b2r1-qa/`。
- **使用与实现方不同的独立测试密钥**（`QAK-*` 前缀），未复用实现方套件中的 `TINA-KEY` /
  `K-A-secret` 等值。
- 未起长驻服务、未访问 NAS、未发起任何真实模型请求。

## 二、验证命题与结果（逐条）

| # | 命题 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | 老师 A/B 不串凭据 | PASS | 两个 `dashscope` 服务商各持独立密钥与独立 workspace 主机，`default_resolver` 分别返回各自的 key/workspace，互不相等 |
| 2 | 不回退 Tina / 全局链路 | PASS | 全局 `api_key=QAK-GLOBAL-TINA`、`workspace_id=global-ws` 时，解析结果 `api_key` = 服务商自有密钥、`workspace_id` = 服务商 `base_url` 解析出的 workspace（反向证明：用与全局同名 host 时，解析出的 workspace 仍来自 provider 记录） |
| 3 | 全局配置不被污染 | PASS | 解析前后全局 `QwenConfig` 的 `api_key/workspace_id/region/ws_url/model/voice` 逐字段与对象身份均不变 |
| 4 | 不泄漏密钥 | PASS | 解析结果 `vars()/repr` 与全部 `TeacherVoiceUnavailable` 的 `str/.code/.detail` 拼接串中不含全局密钥与他方明文密钥；`ws_url` 不含 workspace 或密钥 |
| 5 | fail-closed 全路径 | PASS | 模型不存在 / 模型 frozen / 服务商 frozen 或 `prov_frozen_tina` / 协议 `openai_compatible`、`openai_audio_compatible` / 服务商无凭据 / 凭据不可读 / 地址无法派生 workspace（`https://dashscope.aliyuncs.com`）/ region 非 `cn-beijing` / 缺 `realtime_model_id` —— 各路径均抛出预期 `.code` |
| 6 | 对抗尝试 | PASS | (a) 服务商密钥 = 全局密钥 → 拒绝；(b) 服务商主机与全局同形 → 解析值来自 provider 记录；(c) 全局 `mode=mock` → 老师结果仍为 `mode="real"` 且带自有 `api_key` |
| 7 | 冻结面零改动 | PASS | `git diff HEAD -- turns/qwen/audio/protocol/ws/behavior` 为空；`git status --porcelain` 显示改动仅限 `teacher_voice.py` + `teacher_voice_seam_tests.py` |
| 8 | 复跑官方套件 | PASS | `teacher_voice_seam_tests.py` → **51/51** |

## 三、自研脚本结果

- Agent C 自建断言集：**42/42 PASS**（覆盖上表 1–7 的各细项，含主机形近、端口畸形、
  凭据轮换、跨服务商隔离等）。
- 合计：**42/42（自研）+ 51/51（官方）= 全通过**。

## 四、发现的问题

- **P0：无**
- **P1：无**
- **P2（不阻塞本轮，登记备查）**：
  1. `credential_isolation_violation` 断言仅在全局 `api_key` 非空时生效——属设计意图的
     belt-and-braces；真正兜底是"构造期清空 + 无读取点"，无实际缺口。
  2. `provider_realtime_binding` 不强制 TLS（接受 `http`/`ws`）——属既有策略（服务商创建时
     已由 `endpoint_policy` 限制 https，仅回环可 `allow_local`）；如需老师连接强制 TLS 可另行收紧。

## 五、声明

- 使用**与实现方不同的**测试密钥：是。
- **独立编写**测试脚本：是（仅存于 `/tmp/p2b2r1-qa/`）。
- **未触碰仓库任何文件**：是。
