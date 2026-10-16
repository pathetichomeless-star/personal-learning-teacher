# XIAOZHI V4 — 前端交互实机审计（Agent E）

- 角色：浏览器交互审计代理（真实浏览器，运行于本机验收环境）
- 日期：2026-10-10（Asia/Shanghai）· 目标：`http://127.0.0.1:8119/v4/`（本地验收服务；管理面 + `/v4/` 双模式 UI；上游仅本地 mock `127.0.0.1:8123`，无付费调用）
- 性质：交互层实测。令牌由页面输入框保存（仅 sessionStorage）；全程未输出令牌/密钥内容。
- 证据：交互快照自动存证于 `<user-home>/.trae-cn/trae-browser-screenshots/6ac9ea83ed28cde36ff02ab8/`（登录后首页、我的模型、提升结果卡、场景配置等）。

## 1. 覆盖范围

令牌登录 → 日常模式 4 页（概览/课件库与检索/我的模型（只读）/使用说明）→ 专业模式全部 14 页逐页浏览 → 能力测试提升全流程 → 场景配置核对 → 真实验证按钮回归 → 全程 console / 网络 / 布局 / 密钥明文监控。

## 2. 逐项结论（首轮）

| # | 项 | 结果 | 关键原文 |
|---|---|---|---|
| 1 | 登录/连接 | PASS | 占位消失；连接点变绿（rgb 63,185,80）；提示「令牌已保存」 |
| 2 | 日常模式 | PASS | 4 页均正常渲染；数据集「验收课件库（隔离数据）」可见；经专业「资料集管理→查看文档」确认恰为 **5 个文档**（unit3.txt、unit4.md、unit5.pdf、lesson5.docx、lesson6.pptx） |
| 3 | 专业模式 | PASS | 服务商含「本地验收 Mock」（openai_compatible/partial，`http://127.0.0.1:8123/v1`）；我的模型含 2 个 mock，且 mock-gpt-realtime 显示 `realtime_safe` 标签；凭据页仅 fingerprint（`0f8000958622b13a`）与 `cred://` 引用，无明文 |
| 4 | 能力测试提升 | PASS | 「提升实时安全」→ 确认模态 →「确认提升」→ 结果卡「当前验证级别：realtime_safe；磁盘读回：一致」 |
| 5 | 场景配置 | PASS | oral_realtime 同时绑定冻结 Tina（只读标记）与 mock-gpt-realtime；默认 `mdl_frozen_tina`（冻结保留） |
| 6 | 交互回归 | PASS | 「真实验证（需授权）」返回结果（mode=verified、verified=true、写入证据：是），无崩溃/白屏 |
| 7 | 监控 | PASS | console 零错误；无横向溢出；未见令牌/密钥明文 |

## 3. 发现的问题与处置

| # | 严重度 | 问题 | 复现 | 处置 |
|---|---|---|---|---|
| E-V4-1 | 中 | 连接指示：圆点绿色但 tooltip 仍为「未连接」（`setDot` 未更新 `title`） | 保存令牌后读取 `#connDot.title` | **已修复**：`admin-v4/app.js:54-58` setDot 同时更新 title（已连接/未连接） |
| E-V4-2 | 低（功能性） | 对已提升为 `realtime_safe` 的模型执行「真实验证」后级别被降回 `verified`（证据写入覆盖高水位） | 提升 → 真实验证 → 「我的模型」级别变 verified | **已修复**：`modules/model/registry.py` `set_evidence` 改为高水位（更低级别只记录 run，不降级）；新增回归：model_v4「高水位」、admin_v4 T6k3/T6k4、E2E「re-test after promote keeps realtime_safe」 |
| E-V4-3 | 低（非本产品） | `GET /@vite/client` 返回 404 | 浏览器网络面板出现该请求 | 非本页面产物（页面为静态 HTML/JS，无 Vite）；属工具链注入请求；allowlist 对未知路径按设计 404，不改动 |
| E-V4-4 | 信息 | 日常「课件库与检索」不直接显示文档数；检索「hello/时态」无命中（语料为酒店/问路词汇，属预期）；专业导航较长需滚动 | — | 设计取舍/非缺陷，记录备查 |

## 4. 修复后定向复验（新浏览器会话）

服务重启加载修复后，定向复验三项，**全部 PASS**：

| # | 复验项 | 结果 | 关键原文 |
|---|---|---|---|
| 1 | 连接指示 tooltip | PASS | `#connDot.title = "已连接"`；圆点绿色（rgb 63,185,80） |
| 2 | 提升后再跑真实验证不降级 | PASS | 结果卡「写入证据：是；当前验证级别：realtime_safe」；「我的模型」页复核仍 `realtime_safe` |
| 3 | 提升幂等 | PASS | 「当前验证级别：realtime_safe；磁盘读回：一致」 |

Console 无页面报错；无横向溢出（scrollWidth=clientWidth=1022）。（会话中唯一 error 为复验代理自身 evaluate 的正则语法产物，非页面缺陷。）

## 5. 边界说明

- 未覆盖：新增/删除/停用等写操作（仅执行提升与真实验证）、上传与导入任务的端到端操作、跨浏览器/缩放/移动端布局（复验仅 1022×627）、全部中文文案逐字校对、API 逐条 HTTP 状态码核对。
- 「磁盘读回一致」为界面文案证据；其底层由确定性测试 T6k2（新实例磁盘读回）独立覆盖。