# XIAOZHI V4 — 独立复核（新增改动）· AGENT_C2_REVERIFY_MC

- 角色：独立验证代理（只读，不采信主控描述）
- 日期：2026-10-10（Asia/Shanghai）· 分支 `v4-admin-dev`，HEAD `d177582e1e4ec4737ca0ef8ec68966ce7fb7798d`（复核时工作树含本轮未提交改动）
- 性质：只读。未修改任何仓库文件；未停止/重启 8119/8123；未 SSH NAS；未调用付费模型；未 commit。
- 复核对象：本轮 M-C（promote-realtime 端点 + 独立授权位 + UI 入口）与 m3（health stores）改动及受影响面。

## 1. 七套确定性测试（亲手运行原始计数）

| 套件 | total | pass | fail |
|---|---|---|---|
| admin_v4_api_tests | 100 | 100 | 0 |
| model_v4_tests | 71 | 71 | 0 |
| import_v4_tests | 39 | 39 | 0 |
| knowledge1_tests | 72 | 72 | 0 |
| admin2_tests | 69 | 69 | 0 |
| admin_security_tests | 29 | 29 | 0 |
| admin_ui_tests | 23 | 23 | 0 |

## 2. E2E 幂等复跑

`V4 ACCEPTANCE E2E SUMMARY total=70 pass=70 fail=0`（仅本地 mock；未触碰验收进程操作）。

## 3. 代码级核验（file:line）

- promote 处理器 `gateway/app/admin/api_model.py:400-429`，顺序确为 404(`:412`)→frozen(`:414`)→confirm(`:417`)→授权(`:418`)→adapter(`:421`)→提升(`:423`)→审计/读回(`:425-426`)。
- `_KNOWN_CODES` 含 `evidence_missing: 400`（`api_model.py:45`）；底层来源 `raise ModelRegistryError("evidence_missing")`（`modules/model/registry.py:473`，evidence<verified 时）。
- health stores：`gateway/app/admin/views.py:130-131`；`AdminStores.describe()` 纯布尔（`stores.py:129-137`）；未挂载时为 null（`:96`）。
- 路由表 `api_route_table_model()` 含 `promote-realtime`（`api_model.py:600`），`mount_model` 亦含（`:630`）。
- 授权环境位接线：`MODEL_PROMOTE_AUTHORIZED` 默认 `"0"`（`gateway/app/main.py:50`）→ `stores.promote_authorized`（`main.py:150`）→ `app["model_promote_authorized"]`（`gateway/app/admin/app.py:37`）。

## 4. 反向证伪（独立尝试推翻）

- `git diff HEAD --` 9 个冻结语音链路文件（turns/audio/qwen/diag/counters/protocol/http/behavior/ws）+ `admin/{auth,registry,service}.py`：**输出为空**（零改动）。
- 全仓 grep：写入 `realtime_safe` 仅 `promote_realtime_safe`（`registry.py:474`）与 `ensure_frozen_link`（`:544`）；admin 侧唯一 `set_evidence` 为 `"verified"`（真实测试，`api_model.py:391`）。**无请求体直通路径**（服务端只认存储证据）。
- 测试与前端齐备：admin_v4 T6g–T6o 11 项、model_v4 提升 4 项、`verify_v4_e2e.py` 5b 段 + health stores 检查均在位。
- `node --check admin-v4/app-pro.js` 通过（node v22.23.1）；按钮 `data-prom` + 模态 `POST …/promote-realtime {confirm:true}`（`app-pro.js:332-333`）。

## 5. 判定与边界

- **判定：PASS —— 未发现 Blocker / Major / Minor。**
- 本代理未覆盖的边界：并发/竞态下重复提升未测（依赖既有 store 锁语义）；未真实渲染浏览器 UI（另由浏览器交互代理覆盖）；未以真实进程级环境变量单独验证授权开关（依赖代码接线 + 确定性单测）；E2E 仅复跑一次；未直接请求 8123 活服务。