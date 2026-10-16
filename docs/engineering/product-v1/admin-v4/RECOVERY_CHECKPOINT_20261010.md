# V4 恢复检查点与验收证据（2026-10-10，重启后恢复）

> **【链现行入口 · 2026-10-13】** TASK_ID=ADMIN-V4-AUDIT 链（V4 管理后台开发的多 Agent 审计/整改/复验）：
> AGENT_A–F 八份 + 本检查点按「独立审计证据」例外**全部保留**、正文不合并（不同审计方独立结论）。
> 链关系：A 架构 / B 后端与数据安全 / C QA 交叉 / C2·C2B 复核轮 / D 冻结回归 / E 实机交互 / F B6 部署审查 → 本检查点=现行状态入口。
> 收敛登记见 `docs/PROJECT_WORKLOG.md` 第二阶段批 3 条目；本文件正文未改。

## 1. 现场恢复（只读核实）

- 分支 `v4-admin-dev`，HEAD `d177582e1e4ec4737ca0ef8ec68966ce7fb7798d`（AVATAR Live2D 提交，未变）。
- 工作树：13 个已修改跟踪文件 + 18 组未跟踪新文件（`admin-v4/`、`gateway/app/admin/api_model.py`、`api_import.py`、`modules/model/`、`modules/knowledge/{imports,parsers}.py`、`gateway/tests/{admin_v4_api,import_v4,model_v4}_tests.py`、`deploy/v4-acceptance/` 等）。全部已落盘（按 mtime 复核）。
- 重启前无存活测试进程、无存活 SSH 会话（ps 复核）；验收环境此前从未实际启动过（无 PID、无数据目录）。

## 2. 290 检查点核实

历史 `290 = 72 + 69 + 61 + 49 + 39` 对应五套件；重启后逐套实测：

| 套件 | 重启时实测 | 说明 |
|---|---|---|
| knowledge1_tests | 72 / 72 | = 72 |
| admin2_tests | 69 / 69 | = 69 |
| admin_v4_api_tests | 78 / 78 | 检查点时为 61，随后继续开发增长 |
| model_v4_tests | 49 / 49 | = 49 |
| import_v4_tests | 39 / 39 | = 39 |

结论：290 为真实历史检查点；重启时代码已推进至 307 绿；本轮修复后合计 **311 绿**（admin_v4 80、model_v4 51）。

## 3. 验收环境真实启动发现的真实缺陷（已修复 + 回归）

对**真实运行**的验收服务（127.0.0.1:8119 + 本地 mock 8123）执行端到端验证，首轮 66/70，暴露出 2 个真实缺陷：

1. **同步探测阻塞事件循环**：`probe_verified`（urllib 同步 5s）在 async 处理器内直接调用；验收环境中 mock 与管理面同事件循环 → 互锁至超时（`timeouterror`, 5020ms）。修复：`api_model.model_test` 改用 `asyncio.to_thread` 执行探测（`gateway/app/admin/api_model.py`）。
2. **metadata 路径双拼接**：`base + "/v1/models"`，当 `base_url` 已含 `/v1` 时变成 `/v1/v1/models`（实测 404）。修复：`modules/model/probe.py` 新增 `_models_url()` 容忍拼接（host-only 与 `/v1` 后缀两种约定归一）。

回归测试（新增，均通过）：
- `admin_v4_api_tests` T6e：同事件循环真实 loopback mock（无假 opener）→ 探测成功并写入 verified 证据（fix 前必超时，属真实回归守卫）；T6f：host-only base 归一拼接。
- `model_v4_tests`：`_models_url` 两种入参单测。

修复后复验：**E2E 70/70 全通过**。

## 4. 端到端证据（真实 HTTP / 真实解析 / 仅本地 mock，无任何付费调用）

- UI：`/v4/`、`/v4/app.js`、`/v4/app-pro.js`、`/v4/styles.css` 200；未知文件 404（allowlist）；旧 `/` ADMIN-1 兼容仍 200。
- 鉴权：匿名 401（与错误 token 同体）；带 token health 200，listener running。
- 模型链路：Provider(allow_local) → 凭据（响应无明文，`configured:true`，credential_ref）→ 模型（默认 disabled）→ 无证据 enable=400 `evidence_missing` → **真实本地探测**写入 `verified` → enable 200 → `oral_realtime` 被拒（capability_mismatch）→ `text_chat` 绑定成功。
- 冻结 Tina：自动识别为 `frozen`，enable/bind-scene 均被拒（只读）。
- 五格式**真实解析**导入（txt/md/pdf/docx/pptx，pdfminer.six 20260107、python-docx 1.2.0、python-pptx 1.0.2）：每种均 upload→preview_ready（未入库）→commit→applied+readback→文档数 +1；source_type 分别为 text/markdown/pdf_text/docx_text/pptx_text。
- 检索：search 返回命中且携带 doc/dataset 来源；document 读回与 chunks 可读。
- 秘密卫生：审计与凭据清单均无明文；凭据视图仅 fingerprint + credential_ref。

## 5. 涉及文件（本轮修复）

- `modules/model/probe.py`（+`_models_url`）
- `gateway/app/admin/api_model.py`（`asyncio.to_thread` 执行探测）
- `gateway/tests/admin_v4_api_tests.py`（+T6e/T6f，T7 凭据选择按 provider 过滤）
- `gateway/tests/model_v4_tests.py`（+2 单测）