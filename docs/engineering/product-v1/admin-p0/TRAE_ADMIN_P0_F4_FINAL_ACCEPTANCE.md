# TRAE ADMIN P0 F4 FINAL ACCEPTANCE

**最终结论：CODE_GO。F4 闭环及 F1/F2/F3/F5 关键代码回归通过，可以结束本轮后台代码整改。未发现本范围内可复现的产品阻断缺陷。**

**仅代码验收通过，不代表生产部署授权。B6 真实备份和精确恢复仍须另行完成。**

日期：2026-10-10，Asia/Shanghai。审核范围仅 F4 最小整改及上述关键回归，没有扩大整改范围。

## 1. 审核对象与独立性

- 最终 HEAD：`f57b8cde741821928b0d90c03e5f8628a77ee146`。
- 修复提交：`948c8e23d7c5e1dce596c5dca3f6252ef7859f00`；前次基线：`d9272e43063bdcb754b53ed25a2a652a3ff64da3`。
- 实际候选镜像：`sha256:4d26ae4ab3f746e6d2a931a6be708949a45028067d6ee89a2b5f47ed21e10669`，标签 `xiaozhi-admin-p0:f4-closure`。

读取整改说明与前次独立报告，仅用于定位待验收项目。主审核另组织三个只读 Agent，分别独立检查后端契约、QA 回归和安全边界；主审核核对镜像、执行真实 Chrome 和交叉场景。结论来自本轮执行及源码取证，没有引用 Codex 的 PASS 作为最终 PASS。“Trae”沿用交付报告命名，不声称外部 Trae 客户端另行签署。

实际提交历史、完整 diff、文件清单均已核对保存。相对 d9272e4，唯一产品修改为 `admin/app.js`：23 行新增、7 行删除；另有四个测试文件、报告与证据。948c8e2 到最终 HEAD 的打包产品/测试源码零差异。

证据：[提交历史](/private/tmp/trae-admin-p0-f4-review/history.txt)、[完整 diff](/private/tmp/trae-admin-p0-f4-review/diff-d9272e4.patch)、[契约子报告](/private/tmp/trae-admin-p0-f4-review/contracts/CONTRACT_REVIEW.md)、[QA 子报告](/private/tmp/trae-admin-p0-f4-review/regression/INDEPENDENT_QA.md)、[安全子报告](/private/tmp/trae-admin-p0-f4-review/security/notes.md)。

## 2. F4 逐项验收

| 项目 | 最终契约及合法边界 | 后端依据与前端位置 | 结论 |
| --- | --- | --- | --- |
| dataset documents | source 可缺失/null/{}；type 可缺失，存在则为 text/markdown/pdf_text；uri 可缺失/string/null | [store.py:504](/private/tmp/xiaozhi-admin-p0-rectification/modules/knowledge/store.py:504)、[app.js:298](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:298)、[315](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:315) | 通过；补测了交付字段矩阵未单列的 documents.source.uri |
| knowledge search | 同一来源契约，兼容旧 source 缺失/null 的空对象回退；type=null 属非法值 | [store.py:675](/private/tmp/xiaozhi-admin-p0-rectification/modules/knowledge/store.py:675)、[app.js:317](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:317) | 通过 |
| sessions | session_id_hash/state 为 string；generation_active/tts_active 为 boolean；uptime_s 为有限非负 number/null；展示字段必须存在 | [registry.py:109](/private/tmp/xiaozhi-admin-p0-rectification/gateway/app/admin/registry.py:109)、[app.js:303](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:303)、[659](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:659) | 通过；合法 0、小数、null 均接受，字符串布尔值/负时长拒绝 |
| behavior routing | activity/speed/difficulty 为 string；scenario/temporary_intent 为 string/null；policy_version 为正安全整数/null；字段必须存在 | [behavior.py:456](/private/tmp/xiaozhi-admin-p0-rectification/gateway/app/behavior.py:456)、[api.py:654](/private/tmp/xiaozhi-admin-p0-rectification/gateway/app/admin/api.py:654)、[app.js:305](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:305)、[1204](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1204) | 通过；无 behavior 会话由真实后端过滤 |
| behavior active | policy_version 为正安全整数/null；vocab_policy_header 为 string/null；字段必须存在 | [api.py:678](/private/tmp/xiaozhi-admin-p0-rectification/gateway/app/admin/api.py:678)、[app.js:328](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:328)、[1186](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1186) | 通过；实际未配置 PolicyStore 时两个 null 不误拒 |

独立构造对象、数组、错误标量、必填缺失、非法版本/时长，以及合法 optional/null、空字符串、三类知识来源、混合合法/非法行和错误后恢复样本。另由真实 create_admin_app、KnowledgeStore、SessionRegistry、BehaviorLink、PolicyStore 产生响应，核对实际 wire，而非只按前端测试夹具推测后端。

非法 HTTP200 均受控返回 `ok=false, data=null, error=schema, status=200`，页面出现“响应格式异常，请重试”和对应中文加载失败提示；没有 `[object Object]`，没有非法文档行重建/删除控件，没有未处理 Promise。会话/路由错误没有被伪装为“当前无活动会话”。合法数据集自身的停用、重命名、删除等控件仍可显示，不属于非法文档行控件。

已查看本轮真实 Chrome [会话错误截图](/private/tmp/trae-admin-p0-f4-review/chrome-f4-clean/f4-sessions.png)及[文档错误截图](/private/tmp/trae-admin-p0-f4-review/chrome-f4-clean/f4-documents.png)。独立旧版敏感性检查也确认：16 个嵌套非法对象在 d9272e4 全部被错误接受，在最终实现全部被拒绝，未修改或 checkout 源码。[敏感性证据](/private/tmp/trae-admin-p0-f4-review/contracts/regression-sensitivity.json)

## 3. 独立测试记录

Python 使用 `/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python -B`；Node 使用 `<user-home>/.local/bin/node`。本地设置 PYTHONDONTWRITEBYTECODE、独立临时材料及所需 libopus 路径。镜像内测试使用原样候选、network=none、只读根、临时 /tmp。合成 numeric owner 恢复仅在一次性 root 测试容器执行。

| 测试 | 本轮独立结果 |
| --- | --- |
| Python 工作树 ADMIN1 / ADMIN2 / security / UI / 非 ASCII / HTTP | 83 / 69 / 29 / 23 / 5 / 5，全部通过 |
| Python static HTTP / independent_security | 工作树 4 unittest OK、39 PASS；镜像 4 unittest OK、16 backend-only PASS |
| 上述六套 Python 候选镜像内执行 | 同样全部通过 |
| 新 F4 真实后端 wire | 工作树 10/10、镜像 10/10；另自编 producer 18/18 |
| Node 完整测试，读取本轮新 wire | 工作树及镜像提取源码均 226 runner 项目 PASS / 0 FAIL |
| Agent 自编契约 / QA 矩阵 | 194/194、128/128；独立构造，未使用交付 F4 fixture |
| 原有 Chrome / V2 Chrome / F4 Chrome | 46/46、47/47、22/22：原有 115 项全部通过 |
| 主审核新增五类字段 Chrome | 108/108 |
| 主审核独立交叉回归 Chrome | 36/36 |
| 合成 Linux 恢复测试 | 11 项及 numeric owner 通过；不代表生产恢复 |

Node 226 已包含 frontend helper 所在 runner 项目，helper 的29个内部断言不重复累加。各矩阵有覆盖重叠，不合并宣称独立覆盖数量。

Chrome 为真实 **Google Chrome 155.0.8059.39**，本机启动 headless 独立上下文，访问本地镜像原始 `python -m app.main` 服务；Chrome 本身运行在宿主机，页面和普通 API 均由未改动候选提供。静态资源没有补供或替换。异常响应、网络故障、延迟均明确标为故障注入；F5 使用独立 loopback HTTP 服务真实发送状态头及未完成正文。未调用真实 Qwen 或建立语音会话。

最终验收浏览器断言为 **259/259**，pageerror/unhandled Promise 为0。必须保留的一次测试隔离误报：初次按 legacy→V2→F4 顺序共用数据卷，F4 为20/22；两个 search 断言把 legacy 留下的合法文档表/按钮也算入整个 view 的 table 数。两项实际均已返回 schema、中文提示且无对象展示。换全新数据卷、原镜像和原测试脚本后22/22通过；没有修改脚本或源码。原始 exit1 与失败记录保留，不隐去、不计入最终通过的259项。建议今后每套浏览器测试使用新数据卷，或只断言所属结果区域。

精确命令、退出码、输出：[本地 Python/Node](/private/tmp/trae-admin-p0-f4-review/regression/commands.json)、[镜像 Python](/private/tmp/trae-admin-p0-f4-review/candidate-tests/commands.json)、[镜像 Node](/private/tmp/trae-admin-p0-f4-review/node-image-tests.txt)、[Chrome 执行器](/private/tmp/trae-admin-p0-f4-review/run_chrome.py)。浏览器逐项证据：[46项](/private/tmp/trae-admin-p0-f4-review/chrome-legacy/chrome-results.json)、[47项](/private/tmp/trae-admin-p0-f4-review/chrome-v2/v2-chrome-results.json)、[干净数据卷22项](/private/tmp/trae-admin-p0-f4-review/chrome-f4-clean/f4-chrome-results.json)、[新增108项](/private/tmp/trae-admin-p0-f4-review/chrome-independent/results.json)、[交叉36项](/private/tmp/trae-admin-p0-f4-review/chrome-cross/results.json)、[初次隔离误报](/private/tmp/trae-admin-p0-f4-review/chrome-f4/f4-chrome-results.json)。

## 4. F1/F2/F3/F5 关键回归

| 项目 | 本轮复验结论 |
| --- | --- |
| F1 | 通过。健康200/401/403/500/断网/默认超时与导航、普通500交错均结束验证；刷新、双验证反序及凭据改变没有卡住或旧结果复活 |
| F2 | 通过。错误正文不进入仪表盘；刷新后顶层及嵌套未知字段仍被投影剔除；故障响应中临时凭据不进入DOM |
| F3 | 通过。当前查询 JSON/schema/network/timeout 与旧200交错不会覆盖错误；旧记忆删除按钮、离开后返回同名页面的旧文档按钮不能发请求 |
| F5 | 通过。已收到401/403/500在正文悬挂/异常时仍保留原状态；旧401跨凭据变化、重复验证或刷新不能清除新凭据 |

交互/queryScope、认证、传输、受控错误分支与 d9272e4 逐字一致；本次仅补契约和对应错误展示，未删除竞态保护。[独立区域哈希](/private/tmp/trae-admin-p0-f4-review/security/security-audit.json)

## 5. 源码、镜像和安全边界

主审核从实际镜像枚举 app/config/modules/tests/admin-ui，直接用最终 HEAD Git blob 构造期望值，含打包 probe/restore 工具映射：**126/126 SHA-256 一致，missing/extra/mismatch 均为空**。实际 HTTP 的 index.html/app.js/shared.js/styles.css 再与最终 HEAD 比较，**4/4逐字节一致**。revision label 为948c8e2，未仅凭标签判断。[镜像源码证据](/private/tmp/trae-admin-p0-f4-review/candidate-independent-source.json)、[HTTP源码证据](/private/tmp/trae-admin-p0-f4-review/static-http-source.json)

范围是打包源码、配置与测试，不扩大为镜像全部依赖二进制可重现或生产运行环境相同。实际测试运行 Python3.12.15、aiohttp3.14.3、libopus1.5.2、UID10001；只发布本机环回管理/健康端口，无生产挂载、无语音端口，Qwen mock且对应Secret不存在，Workbench禁用。普通 Docker bridge 未作为完全阻断 egress 的证明。

冻结命令 `git diff --exit-code d5644f1 HEAD -- gateway/app ':!gateway/app/admin' modules client gateway/config` 返回0；未混入 client 数字人实现，原后台数字人占位页仍是占位。B6文档、deploy和恢复工具对 d9272e4 diff为0。未发现新增Token泄漏路径；本轮两个随机临时凭据在独立文本证据中原值匹配数为0。

主工作区 HEAD d177582e1e4ec4737ca0ef8ec68966ce7fb7798d及开始时42个原有dirty/未跟踪文件内容均未变，整改worktree保持最终HEAD且干净；本报告另行新增。[最终边界](/private/tmp/trae-admin-p0-f4-review/final-boundaries.json)

## 6. B6 剩余条件与停止点

**备份方案覆盖要求，不等于真实生产备份或精确恢复已完成。** 本轮没有连接NAS，不把前轮038d2f6c…取证称为当前生产镜像身份；没有新增真实生产备份/恢复完成证据。仍须产品负责人另行决定并授权：

1. 核定当时实际生产完整镜像ID，完成归档、完整性与异地副本验证，在独立daemon精确load并核对ID/架构/layers。
2. 安全保存实际生效Compose/env/override、运行规格和完整Secrets；验证独立解密材料、权限、numeric UID/GID及只读挂载可恢复性，敏感正文不得进入普通报告。
3. 在全部写入方静默或可证明一致性快照条件下，备份完整data及附加文件；包括PolicyStore active/history/audit，目录树/hash、owner/mode、ACL/xattr与链接审查。
4. 用精确生产材料做隔离服务恢复，核对完整PolicyStore原始内容和全部保留审计，防止缺失/损坏回落默认v1却HTTP200；验收旧生产镜像的认证、health、静态行为、完整数据及运行规格。合成恢复或候选测试不能代替。
5. 保留维护窗口、快照后数据取舍、部署前实时零语音连接和另行生产授权门禁。真实语音或付费Qwen验收也须另行授权。

依据：[ROLLBACK_EXACT.md:20](/private/tmp/xiaozhi-admin-p0-rectification/docs/engineering/product-v1/admin-auth-p0/ROLLBACK_EXACT.md:20)、[未完成证据:81](/private/tmp/xiaozhi-admin-p0-rectification/docs/engineering/product-v1/admin-auth-p0/ROLLBACK_EXACT.md:81)、[RELEASE_SAFETY.md:30](/private/tmp/xiaozhi-admin-p0-rectification/docs/engineering/product-v1/admin-auth-p0/RELEASE_SAFETY.md:30)。B6安全门禁未修改。

本轮未修改源码、部署/重启NAS、写入生产备份、读取生产Secrets、合并main或调用真实付费Qwen。两个本地测试容器、四个测试卷及两组临时凭据已删除，Chrome关闭，本地VM恢复停止状态，保留候选镜像和无秘密证据。[清理记录](/private/tmp/trae-admin-p0-f4-review/cleanup.json)

**审核完成并停止，等待产品负责人决定B6阶段。CODE_GO仅结束本轮代码整改，不授权生产备份、恢复或部署。**
