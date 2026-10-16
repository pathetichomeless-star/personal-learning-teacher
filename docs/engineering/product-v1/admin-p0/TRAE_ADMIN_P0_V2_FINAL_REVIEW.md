# TRAE ADMIN P0 V2 FINAL REVIEW

**最终结论：CONDITIONAL。F1、F2、F3、F5 独立验收通过；F4 原有异常 JSON/异步拒绝问题已修复，但展示字段的嵌套类型校验仍不完整，不能宣称 F1–F5 全部 GO。生产部署仍为 NO-GO：B6 真实生产备份与精确恢复证据未闭合，且没有部署授权。**

日期：2026-10-10，Asia/Shanghai。本轮仅审核及隔离测试，未参与施工。

## 1. 独立性与审核版本

实际审核 HEAD：`d9272e43063bdcb754b53ed25a2a652a3ff64da3`；构建代码/测试来源：`6435e89b349e115f74a137c12afbed0e06b8362e`。

本轮实际启动四个独立 Agent：Security、QA/Reliability、Queries/Regression、B6 Recovery；主审核另外核对真实镜像并运行真实 Chrome。各 Agent 独立读源码、自编测试并出具记录，没有将 Codex 的 PASS 作为本轮 PASS，也不声称由外部 Trae 客户端签署。

读取了 V2 交付说明与前次报告，核对提交链 `249bcb7 → 4dbd68e → fd7448c → 6435e89 → 8a9f4c1 → d9272e4`，保存并审查完整变更清单及 diff。V2 产品代码只修改 `admin/app.js`，其余为测试、工具、报告与证据。后端产品代码未变。

证据：[完整 V2 diff](/private/tmp/trae-admin-p0-v2-review/diff-249bcb7.patch)、[完整历史](/private/tmp/trae-admin-p0-v2-review/history.txt)、[Security报告](/private/tmp/trae-admin-p0-v2-review/security/SECURITY_REVIEW_V2.md)、[QA报告](/private/tmp/trae-admin-p0-v2-review/qa/QA_INDEPENDENT_V2.md)、[Queries报告](/private/tmp/trae-admin-p0-v2-review/queries/QUERY_REGRESSION_REVIEW.md)、[B6报告](/private/tmp/trae-admin-p0-v2-review/recovery/B6_INDEPENDENT_V2_REVIEW.md)。

## 2. 独立执行记录

Python 本地解释器为 `/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python`，设置 `PYTHONDONTWRITEBYTECODE=1`、`DYLD_LIBRARY_PATH=/private/tmp/opus131/lib`、独立 TMPDIR；镜像测试在 Linux 容器内运行。Node 同时执行最终 worktree 与镜像提取源码。所有认证材料都是本轮随机临时凭据。

| 套件 | 最终 worktree 独立复跑 | 候选镜像/提取源码独立复跑 |
| --- | --- | --- |
| ADMIN1 / ADMIN2 | 83 / 69 PASS，零 FAIL | 同左 |
| security / UI合同 / 非ASCII / HTTP认证 | 29 / 23 / 5 / 5 PASS，零 FAIL | 同左 |
| static HTTP | 4 unittest OK | 4 unittest OK |
| independent_security | 39 PASS / 0 FAIL，含JS | backend-only 16 / 0 |
| Node `--test *tests.mjs` | 97 runner项目 / 0 FAIL | 97 / 0；helper的29断言包含在其中1个项目 |
| 原有 Chrome | — | 46 PASS / 0 FAIL |
| V2新增 Chrome | — | 47 PASS / 0 FAIL |
| **本轮自编 Chrome 交叉场景** | — | **35 PASS / 1 FAIL（36项）** |
| **本轮自编 Chrome 字段契约场景** | — | **0 PASS / 4 FAIL** |
| 自编 Security | 43 VM + 35真实aiohttp，全部通过 | 不冒充Chrome |
| 自编 QA交叉矩阵 | 171 PASS / 0 FAIL；另5个非法字段页面探针复现缺口 | 不冒充Chrome |
| 自编 Query矩阵 | 26 PASS / 0 FAIL；同矩阵对249bcb7为6 PASS / 20 FAIL | 验证旧缺陷敏感性 |
| synthetic恢复 | Mac 11项通过，numeric owner未执行 | Linux 11项及numeric owner通过；仅虚构材料 |
| 自编 PolicyStore恢复 | 19 / 19，通过完整raw/audit、篡改与回落测试 | 仅虚构材料 |

Chrome 为 **Google Chrome 155.0.8059.39**，headless、独立临时上下文。browser-use doctor无可用连接，使用本地 Playwright 启动真实 Chrome。两个交付套件从实际候选镜像提取，页面由候选真实 `python -m app.main` 提供，未补供 shared.js/app.js。合计133个浏览器断言：128 PASS / 5 FAIL；5个失败是同一类 F4 契约遗漏，不是五个安全漏洞。全部浏览器套件 pageerror/unhandled 为0。

自编36项覆盖：健康六种终态 × 导航与普通500；刷新时旧200/401/500；清凭据/同值重输/存储污染与旧401；当前普通401结束复验；双复验反序；刷新后的嵌套未知字段投影；当前查询JSON/schema/network/默认8秒超时与旧200、无关200交错；保留旧操作按钮；返回同名页面后旧文档按钮；真实HTTP已收到401/403/500但body未完成；旧401跨刷新。随后4项补测文档来源、会话状态和路由字段。

普通成功登录、导航、静态资源和服务调用均访问真实候选；错误状态、延迟、schema/JSON、断网和body故障明确标为注入。F5额外使用本地HTTP服务器真实发送headers与未完成body，不把VM称为真实网络。没有真实云端或语音测试。

精确argv/exit/stdout：[本地命令](/private/tmp/trae-admin-p0-v2-review/qa/commands.json)、[镜像命令](/private/tmp/trae-admin-p0-v2-review/candidate-tests/commands.json)、[镜像Node结果](/private/tmp/trae-admin-p0-v2-review/node-image-tests.txt)。浏览器结果：[46项](/private/tmp/trae-admin-p0-v2-review/chrome-legacy/chrome-results.json)、[47项](/private/tmp/trae-admin-p0-v2-review/chrome-v2/v2-chrome-results.json)、[自编36项](/private/tmp/trae-admin-p0-v2-review/chrome-cross/results.json)、[自编4项](/private/tmp/trae-admin-p0-v2-review/chrome-schema/results.json)。

自编脚本：[chrome_cross.cjs](/private/tmp/trae-admin-p0-v2-review/chrome_cross.cjs)、[chrome_schema.cjs](/private/tmp/trae-admin-p0-v2-review/chrome_schema.cjs)。前者exit1、后者exit1，未以无崩溃代替通过。QA首版夹具有1个init顺序错误，修正后171项通过；初始记录保留在QA目录，不作为产品缺陷或隐去失败。恒时认证性能未测。

## 3. F1–F5 逐项结论

| 项目 | 结论 | 独立证据与实际实现 |
| --- | --- | --- |
| F1 | **GO** | `AUTH.verification`使当前健康验证独立收尾；200/401/403/500/network/timeout，以及JSON/schema/body异常均结束验证。普通非401失败不能提前结束验证；当前普通401清凭据、旧健康200不能复活。刷新、双复验、凭据变化交叉通过。源码：[app.js:349](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:349)、[397](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:397)、[1248](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1248) |
| F2 | **GO** | 非2xx正文不读取/保留/展示，health/version成功响应按字段表投影；顶层及admin/build/responses嵌套未知字段被剔除，刷新后也不进入DOM。schema非法成功被拒绝。源码：[379](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:379)、[327](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:327)、[517](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:517) |
| F3 | **GO** | `queryScope`绑定局部ticket、页面及凭据代次；memory、KB检索、数据集/文档展开拒绝旧结果和旧操作按钮。写请求已授权发出后无法事后撤销，但旧ack不重绘当前视图，旧控件不能新发请求。真实两数据集操作与独立闭包/反序矩阵通过。源码：[93](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:93)、[883](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:883)、[960](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:960)、[1084](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1084) |
| F4 | **CONDITIONAL** | 非法JSON、已覆盖schema、body读取拒绝、异步事件错误受控且无unhandled；但下述嵌套展示字段仍绕过类型校验，需补齐后才能完整GO |
| F5 | **GO** | 已收到状态单独保留；非2xx body直接丢弃，截断/悬挂/取消异常不能把401/403/500改成0。旧响应保留status但stale且无认证副作用；新凭据/新验证/刷新后的凭据不被旧401清除。源码：[367](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:367)、[375](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:375)、[394](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:394)、[398](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:398) |

F2通过不意味着对恶意服务端所有已知合法字符串作了秘密识别；合法已知字段按业务契约展示。未发现认证绕过或令牌进入请求URL。

## 4. 待整改 P2：F4 嵌套展示字段未完整校验

**高置信；需闭合后重新验收，当前不签署“F1–F5全部通过”。**

| 响应/非法字段 | 契约位置 | 实际消费者与Chrome结果 |
| --- | --- | --- |
| `/admin/knowledge/dataset/<id>/documents`，`source.type={...}` | [app.js:303](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:303)，source只要求object | [1025](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1025) 显示`[object Object]`，无错误提示，行操作按钮仍存在 |
| `/admin/knowledge/search`，`source.uri/type={...}` | [305](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:305)，source只要求object | [1096](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1096) 显示`[object Object]`，无检索失败提示 |
| `/admin/sessions`，`state={...}` | [307](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:307)，未校验state等展示标量 | [649](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:649) 状态列直接显示对象，无格式错误提示 |
| `/admin/behavior/routing`，`behavior.activity={...}` | [307](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:307)，behavior只要求object | [1187](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1187) 活动列直接显示对象 |
| `/admin/behavior/active`，`policy_version={...}` | [315](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:315)，未校验该展示字段 | [1174](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1174) 策略版本直接显示对象 |

这些HTTP200故障注入被`api()`当作成功，真实页面没有响应格式/加载失败提示。QA的5个真实页面VM探针和主审核5个Chrome断言相互印证。未证明正常后端或生产实际返回这些非法值；table/kvList使用textContent，**这是契约/展示可靠性遗漏，不是XSS、已发生泄密或认证绕过。**

整改建议：按后端实际类型为source.type/uri、session状态/布尔值/时长、behavior字段、policy_version/vocab_policy_header建立可选/可空的嵌套契约；非法值返回`ok=false,data=null,error=schema`并保留HTTP状态。同步核对消费者错误分支，不能把失败伪装成“当前无活动会话”。若允许结构化值，必须定义明确的规范化展示与异常反馈，不能默认`String(object)`。补上述5种真实页面回归后再给F4 GO。

证据：[交叉场景失败项](/private/tmp/trae-admin-p0-v2-review/chrome-cross/results.json)、[四页面结果](/private/tmp/trae-admin-p0-v2-review/chrome-schema/results.json)、[会话截图](/private/tmp/trae-admin-p0-v2-review/chrome-schema/session-state.png)、[文档截图](/private/tmp/trae-admin-p0-v2-review/chrome-schema/document-source.png)、[QA独立契约探针](/private/tmp/trae-admin-p0-v2-review/qa/independent-matrix-results.json)。

## 5. 最终源码、镜像及冻结边界

候选完整ID：`sha256:93af2dac4c79939baa7614009cc6bb47305d969e0be66dcbd07ffcd9b75e4fbf`；实际revision label为完整`6435e89…`。

主审核从真实镜像枚举app/config/modules/tests/admin-ui文件，并直接从最终HEAD Git blob构造期望值，含额外probe及restore drill：**122/122 SHA-256一致，missing/extra/mismatch全部为空**。实际HTTP的index.html/app.js/shared.js/styles.css再次逐字节与最终HEAD比较，4/4一致。`6435e89..d9272e4`产品/测试目录diff为0；标签不是唯一依据。此结论覆盖这些打包源码/配置/测试，不扩大为镜像所有二进制与生产完全相同。

实际运行Python3.12.15、aiohttp3.14.3、libopus1.5.2、Linux arm64、UID10001。独立volumes，本机19066/19067环回端口；语音端口未发布；Qwen mock、QwenSecret不存在、Workbench禁用，没有生产挂载。普通Docker bridge未被声称为完全阻断egress。

冻结核验 `git diff --exit-code d5644f1 HEAD -- gateway/app ':!gateway/app/admin' modules client gateway/config` 返回0。本轮NAS只读36个源码hash均与生产基线e51d9a5一致，冻结语音/modules与最终候选也一致。未混入数字人开发分支/client实现；后台原静态“数字人尚未开发”占位仍在。主工作区d177582及本轮开始时所有原有dirty/未跟踪文件内容均未变，整改worktree保持最终HEAD且干净。

证据：[独立镜像枚举](/private/tmp/trae-admin-p0-v2-review/candidate-independent-source.json)、[实际HTTP源码](/private/tmp/trae-admin-p0-v2-review/static-source-independent.json)、[NAS源码](/private/tmp/trae-admin-p0-v2-review/nas-source-independent.json)、[最终边界](/private/tmp/trae-admin-p0-v2-review/final-boundaries.json)。

## 6. B6 剩余条件与生产门禁

**方案逻辑合理，B6仍CONDITIONAL；备份方案正确不等于真实生产备份或精确恢复已经完成。** 回滚文档、release safety、drill及PolicyStore相对249bcb7零差异，V2未改变恢复契约。

本轮NAS上海时间01:52:33及01:59:47白名单只读采样：实际镜像为完整`sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`，容器`295eb64dc48c364de65cc4a5d163a60ec9aa1d936cf2909fafe53e2937b4c4bd`、StartedAt及RestartCount=0未变，running/healthy。两次ws/qwen_connected=0、qwen_sessions=3；这不授予维护权限，也不能替代操作前实时检查。

仍缺以下真实、可核验的完成证据：

1. 当前完整生产镜像save/archive校验、异地保存、独立daemon load后ID/架构/layers核对；旧34ea历史镜像不能替代038d。
2. 实际生效Compose/env/override、私密运行规格与配置安全副本、镜像层配置一致性及恢复规格验收。
3. 完整Secrets安全加密备份、独立解密材料、可恢复性与numeric owner/mode/RO/runtime访问验证；本轮未访问生产Secret内容。
4. 全部写入方静默的一致性完整data快照，全部memory/knowledge附加文件、PolicyStore active/history/audit、目录树/hash、owner/mode、ACL/xattr及已审查链接的恢复证据。
5. 精确生产archive与副本材料的隔离服务恢复：独立daemon/端口/网络/egress、mock/临时凭据、不挂生产卷；逐项认证/health/旧版本静态行为、数据及运行规格验收。候选通过不能替代旧生产镜像恢复。
6. 产品负责人另行授权备份处理与维护窗口；部署前实时零语音连接检查；必要真实语音/Qwen验收须另行授权，代码审核GO不会自动批准生产部署。

本轮`freeze/pre-adminauth-p0`两次不存在，仅证明该路径，不证明NAS其他位置绝无备份；也没有其他完整真实备份/恢复记录供本轮验收。[ROLLBACK_EXACT.md:81](/private/tmp/xiaozhi-admin-p0-rectification/docs/engineering/product-v1/admin-auth-p0/ROLLBACK_EXACT.md:81) 明确材料和恢复未执行，[RELEASE_SAFETY.md:30](/private/tmp/xiaozhi-admin-p0-rectification/docs/engineering/product-v1/admin-auth-p0/RELEASE_SAFETY.md:30) 仍要求独立GO、回滚验收及维护授权。

独立19项PolicyStore测试证明：默认[audit(limit=50)](/private/tmp/xiaozhi-admin-p0-rectification/modules/policy/persona.py:585)会漏掉更早审计，versions仅列摘要也不能证明历史policy正文完整。必须比较完整raw/schema/active/history/audit及私密manifest，并用`audit(limit=200)`验证保留审计；缺失/损坏/错误schema回落v1，HTTP200不构成恢复通过。虚构60/230次写入、完整恢复和篡改检查通过，未使用生产材料。

证据：[NAS前](/private/tmp/trae-admin-p0-v2-review/nas-before.json)、[NAS后](/private/tmp/trae-admin-p0-v2-review/nas-after.json)、[B6独立报告](/private/tmp/trae-admin-p0-v2-review/recovery/B6_INDEPENDENT_V2_REVIEW.md)、[19项完整Policy测试](/private/tmp/trae-admin-p0-v2-review/recovery/independent_policy_restore.json)、[Linux虚构恢复](/private/tmp/trae-admin-p0-v2-review/candidate-tests/isolated_restore_drill.txt)。

## 7. 结束状态

未修改源码、部署/重启NAS、写入生产备份、读取生产密钥正文、合并main或调用真实付费Qwen。NAS仅白名单metadata/stat/源码或配置hash/无认证health读取，未读完整Env或日志。只新增本报告和独立证据。

本地候选容器、测试volumes、临时凭据及QA临时材料已删除，Chrome已关闭，本地VM恢复停止状态，镜像保留；Chrome证据中本轮测试凭据值扫描为0。

**审核完成并停止。等待产品负责人授权下一步；本报告不授予源码整改、生产备份或部署权限。**
