# TRAE REVIEW OF CODEX ADMIN P0

**结论：NO-GO。最终 HEAD 的并发健康复验仍有可复现阻断缺陷；真实生产备份与精确恢复门禁也未闭合。禁止据现有 PASS 部署生产。**

审核日期：2026-10-10，Asia/Shanghai。本轮为独立只读复审，没有整改代码。

## 1. 独立审核组织与范围

本会话实际启动四个独立子 Agent：Security、QA/Reliability、B6 Recovery、Intent/Regression。各自读取真实源码、形成独立报告；主审核另外执行候选镜像文件核对、真实 Chrome 和 NAS 白名单只读取证。没有把整改会话的 PASS 当作本轮结论，也不声称由外部 Trae 客户端签署。

- [Security 报告](/private/tmp/trae-admin-p0-review/security/SECURITY_REVIEW.md)
- [QA 报告](/private/tmp/trae-admin-p0-review/qa/QA_INDEPENDENT_FINDINGS.md)
- [B6 报告](/private/tmp/trae-admin-p0-review/rollback/B6_INDEPENDENT_REVIEW.md)
- [回归报告](/private/tmp/trae-admin-p0-review/regression/REGRESSION_REVIEW.md)

审核对象为 `/private/tmp/xiaozhi-admin-p0-rectification` 的完整 HEAD `249bcb7aae2f6a20977a566487825eb7a4946fd0`。保存并复核提交历史、完整变更清单与 diff：整改范围 `31b024b..249bcb7`，此前管理后台变化 `d5644f1..249bcb7`，构建版本与最终版本差异 `c38065c..249bcb7`。证据：[提交历史](/private/tmp/trae-admin-p0-review/history.txt)、[整改完整 diff](/private/tmp/trae-admin-p0-review/diff-31b024b.patch)、[基线完整 diff](/private/tmp/trae-admin-p0-review/diff-d5644f1.patch)。

提交链为 `31b024b → 0373bda → c38065c → 7011471 → 249bcb7`；后两次提交未改变已验收产品源码，最终 HEAD 与构建提交的产品/测试目录比较为零差异。

## 2. 阻断项及具体缺口

### F1 / P1：并发导航成功使健康复验失败永远停在验证中（B2/B3/B5，新增）

位置：[app.js:218](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:218)、[app.js:256](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:256)、[app.js:1078](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:1078)。

实际 Chrome 步骤：正常登录完成 → 空输入点击连接开始健康复验 → 延迟该 health 请求 → 点击诊断，真实诊断 API 先成功 → health 返回 500、连接中断或默认 8 秒超时。三种情况都显示“正在验证…”，而没有应有的服务异常、网络不可达或超时终态。超时用例实测 8506ms 后仍 `verifying`；健康请求 barrier/statusSequence=8，普通成功使 acceptedSequence=15。

原因：`api()` 将较早的失败作为 stale 丢弃，`verifyConnection()` 直接返回，未结束当前验证生命周期。自编 QA VM 矩阵进一步覆盖 401/403/500/network/timeout 五个交错，全部复现。

**整改建议：分开管理当前验证的终态、凭据代次、普通响应顺序。保留旧 401 不清新凭据的保护，但当前验证必须在所有成功/失败/超时路径结束，补并发导航 × 全部健康终态的真实 Chrome 回归。不能简单删除旧响应守卫。**

证据：[独立 Chrome JSON](/private/tmp/trae-admin-p0-review/chrome-independent/results.json)、[超时截图](/private/tmp/trae-admin-p0-review/chrome-independent/health-timeout-navigation.png)、[QA 自编矩阵](/private/tmp/trae-admin-p0-review/qa/trae_independent_behavior.txt)。高置信，足以否定本次最终 GO。

### F2 / P2：错误正文仍可绕过脱敏进入仪表盘（B4，既存遗漏）

位置：[app.js:364](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:364)。仪表盘无条件将 `health.data/version.data` 交给 `raw()`，没有检查响应是否成功，绕过 [showError:266](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:266) 的安全展示。

独立 Chrome 对 `/admin/version` 注入 HTTP500、正文含本轮随机一次性测试凭据，原样仪表盘 DOM 包含该值。证据仅保留 `credentialInDOM=true`，截图遮蔽原始正文，没有保存凭据值。此路径基线已存在；**未证明当前后端正常路径会反射凭据，不代表生产已泄密，也不是 XSS。**

建议：仅对成功且 schema 合格的响应按字段白名单展示；非 2xx 统一安全错误展示，补原页面反射回归。证据：[Security 自编验证](/private/tmp/trae-admin-p0-review/security/independent_token_reflection.json)、[Chrome JSON](/private/tmp/trae-admin-p0-review/chrome-independent/results.json)。

### F3 / P2：局部查询的旧成功结果仍进入新查询界面（B5，既存遗漏）

位置：[app.js:726](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:726)、[app.js:737](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:737)。整页 `RENDER_SEQUENCE` 不保护已挂载的 `reload()` 回调；普通旧 200 未被丢弃。

真实 Chrome 连续查询 old/new，new200 先到、old200 后到，输入框为 new，但新旧结果同时出现，`tables=2`，旧结果还带编辑/删除按钮。这是原有局部查询代码，不是本次新增实现；B5 不能据全局认证竞态测试宣称所有请求竞态已解决。

建议：查询/局部更新各自设置操作序号，并绑定页面及凭据代次；最新结果原子替换，丢弃过期回调。知识库同类回调也应检查。证据：[原页面 Chrome 查询结果](/private/tmp/trae-admin-p0-review/chrome-independent-memory/results.json)、[截图](/private/tmp/trae-admin-p0-review/chrome-independent-memory/old-new-query.png)。

### F4 / P2：200 畸形 JSON 仍引发未处理 Promise（B3，既存遗漏）

位置：[app.js:245](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:245)、[app.js:733](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:733)。JSON SyntaxError 被吞掉后仍返回 `ok=true,data=null`，后续查询监听器读取 `data.items` 抛错；整页 render 的 catch 不覆盖按钮回调。

原页面 Chrome 对记忆查询注入 200 malformed JSON：`unhandled=1`、`pageerrors=1`，没有中文加载失败反馈。正常后端未被证明会产生该正文；这是异常响应处理缺口。

建议：无效 JSON/schema 转为 `ok=false` 的统一错误，给交互异步回调设置错误边界，补故障回归。证据：[独立 Chrome JSON](/private/tmp/trae-admin-p0-review/chrome-independent-memory/results.json)。

### F5 / P2：已知 HTTP401 被 body 读取错误覆盖（B3/登录状态，新增）

位置：[app.js:243](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:243)、[app.js:251](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:251)、[app.js:187](/private/tmp/xiaozhi-admin-p0-rectification/admin/app.js:187)。收到 401 后 JSON reader 抛 TypeError，外层 catch 将状态替换为 0/network，未进入当前 401 清凭据路径。独立 VM 已复现凭据仍保留；403/500 也丢失已知状态。此行为相较 `31b024b` 新引入，**本轮未补 Chrome，不将 VM 算作浏览器实证；服务器认证仍拒绝请求，不构成授权绕过。**

建议：保留已收到的 HTTP 状态，将 body 错误单独表示；经过现有代次/顺序守卫后处理当前 401，不能绕过旧 401 保护提前清新凭据。补非 2xx + 中断/超时 body 的验收。证据：[独立 probe](/private/tmp/trae-admin-p0-review/regression/probe-results.jsonl)。

## 3. 独立复跑与 B1–B5 判定

全部主动认证使用新建隔离数据及随机临时测试凭据；候选 Chrome 使用镜像原始静态文件、真实 `python -m app.main`、真实 AdminStores。未补供 shared.js/app.js。故障场景仅显式拦截对应 API/reader；正常登录、静态文件、导航和诊断访问真实候选服务。

| 验证 | 本地独立复跑 | 候选镜像独立复跑 |
| --- | --- | --- |
| ADMIN1 / ADMIN2 | 83 / 69 PASS，均零 FAIL | 同左 |
| security / UI合同 / 非ASCII / HTTP认证 | 29 / 23 / 5 / 5 PASS，均零 FAIL | 同左 |
| 真实静态 HTTP | 4 cases OK | 4 cases OK |
| 独立安全矩阵 | 39 PASS / 0 FAIL | backend-only 16 / 0 |
| auth_state / frontend | 38 / 29 PASS，均零 FAIL | 主机 Node 执行 |
| 原有 Chrome 套件 | — | 46 PASS / 0 FAIL |
| 本轮自编 Chrome 健康/反射套件 | — | 1 PASS / 4 FAIL；3种 F1 + F2 |
| 本轮自编 Chrome 记忆套件 | — | 0 PASS / 2 FAIL；F3 + F4 |
| 自编 QA 行为矩阵 | 1 PASS / 8 FAIL（重复变体与辅助断言） | 不冒充镜像/Chrome |
| 虚构完整恢复 | 11项通过；Mac owner未执行 | 11项通过，Linux numeric owner通过 |

Chrome 为 Google Chrome **155.0.8059.39**，headless、独立临时 profile。browser-use doctor 无可用连接，采用本地 Playwright 启动真实 Chrome。原有套件与第一组自编用例没有 pageerror；第二组畸形 JSON 用例出现上述 1 次未处理拒绝，不能继续声称所有独立验收都零异常。测试失败数不是不同漏洞数量。字符串检查 `compare_digest` 不是恒时性能证明。

| 项目 | 本轮结论 | 依据 |
| --- | --- | --- |
| B1 | GO | shared.js 原样200、MIME/UTF-8正确；allowlist、未知/遍历/越界symlink、缺失资源失败闭合；仪表盘真实渲染 |
| B2 | NO-GO | 正常登录/刷新/导航通过，但 F1 验证无终态 |
| B3 | NO-GO | 普通网络和8秒超时通过，但 F1/F4/F5 异常路径遗漏 |
| B4 | CONDITIONAL | 非ASCII/内部空白/storage污染守卫通过；F2错误展示安全契约未完全闭合 |
| B5 | NO-GO | 凭据变更与旧200/401原有回归通过；F1并发验证与F3局部查询遗漏 |

完整命令和重新生成的 stdout：[本地 QA 命令/结果](/private/tmp/trae-admin-p0-review/qa/QA_INDEPENDENT_FINDINGS.md)、[镜像命令及退出码](/private/tmp/trae-admin-p0-review/candidate-tests/commands.json)、[原有 Chrome 本轮结果](/private/tmp/trae-admin-p0-review/chrome-candidate/chrome-results.json)。新增 Chrome 脚本为 [independent_chrome.cjs](/private/tmp/trae-admin-p0-review/independent_chrome.cjs) 和 [independent_memory_chrome.cjs](/private/tmp/trae-admin-p0-review/independent_memory_chrome.cjs)；实际 exit 均为1。

## 4. 最终提交、候选与冻结边界

候选完整 ID：`sha256:7152e3ebdb4d8d87313f15c54d3dda7889a69d1311e0304834d9602c13e5de4b`；实际 revision label：`c38065c60d24b0d8a528c452477e25251c32d189`。

本轮从镜像枚举 app/config/modules/tests/admin-ui 全部文件，直接对最终 HEAD 的 Git blob 逐项 SHA-256 比较，并核对额外打包的 probe/restore drill：**120/120 一致，零 missing/extra/mismatch**。这是独立运行结果，不是读取原 manifest 后采信 PASS；不把源码匹配扩大为全部镜像二进制与生产完全相同。实际运行版本 Python3.12.15、aiohttp3.14.3、libopus1.5.2，Linux arm64，UID10001。

候选仅使用本轮新建 volumes，管理/健康端口绑定本机18866/18867；语音端口未发布。Qwen显式mock、QwenSecret不存在、Workbench禁用；没有生产挂载。使用任务 VM 的普通 bridge，**未宣称完整阻断外部 egress**。

冻结核对：`git diff --exit-code d5644f1 HEAD -- gateway/app ':!gateway/app/admin' modules client gateway/config` 返回0。NAS只读哈希的36个源码文件与生产基线 `e51d9a5` 全部一致，其中冻结语音/modules源码与最终候选也一致。整改历史未混入数字人开发分支/client实现；后台此前已有纯静态“数字人尚未开发”占位，不应字面声称不存在任何数字人相关文本。

主工作区仍为 `d177582`，既有数字人 dirty 文件及未跟踪文件哈希未变；整改 worktree 最终 HEAD未变且仍干净。证据：[独立镜像核对](/private/tmp/trae-admin-p0-review/candidate-independent-source.json)、[NAS源码核对](/private/tmp/trae-admin-p0-review/nas-source-independent.json)、[最终边界核对](/private/tmp/trae-admin-p0-review/final-boundary-checks.json)。

## 5. B6：方案正确与生产备份完成是两项结论

**B6 方案结论：CONDITIONAL；真实生产回滚准备仍未闭合，阻断部署。**

本轮 NAS 上海时间00:55:42及01:02:08只读采样：实际镜像均为 `sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`，容器均为 `295eb64dc48c364de65cc4a5d163a60ec9aa1d936cf2909fafe53e2937b4c4bd`，StartedAt未变、RestartCount=0、running/healthy。两次 ws/qwen_connected=0、qwen_sessions=3；这不是维护授权，也不能替代操作前实时检查。

| 材料/一致性 | 独立设计审核 | 真实生产完成状态 |
| --- | --- | --- |
| 镜像 | 固定完整038d ID，要求save、archive校验、独立daemon load后核对；34ea历史镜像不能替代 | 未执行真实export/load或精确旧镜像服务恢复 |
| Compose/env/运行配置 | 要求识别实际生效文件/override、私密Env/runtime、镜像内配置、端口/mount/用户/安全规格 | 只读白名单与config hash一致；未取得完整安全副本或image-layer恢复验收 |
| Secrets | 完整目录、加密副本、独立解密材料、numeric owner/mode、私密manifest，禁止普通报告泄密 | 未执行真实安全备份、解密恢复和runtime访问验收 |
| data | 完整树、全部写入方静默的一致快照、owner/mode、ACL/xattr与额外文件；不能只导policy_v20或统一chown | 未执行真实一致快照及元数据恢复；虚构演练不验证生产ACL/xattr |
| PolicyStore | raw schema/active/history/audit与store级一致性；缺失/损坏会回落v1，HTTP200不足 | 自编60次虚构写入恢复与回落验证通过；真实策略未恢复验收 |
| 隔离服务 | 精确生产archive+副本挂载、隔离daemon/端口/egress、mock/临时令牌；旧版本shared.js404应如实复现 | 未执行；整改候选成功不能替代精确旧生产镜像恢复 |

方案已明确跨文件一致性、秘密材料处理、保留或丢弃快照后数据、恢复后逐项核对及维护窗口约束，设计逻辑合理。建议真实 PolicyStore验收显式比较完整 raw audit，并使用 `audit(limit=200)`；[persona.py:585](/private/tmp/xiaozhi-admin-p0-rectification/modules/policy/persona.py:585) 默认只返回最近50条。

**阻断证据与整改要求：**[ROLLBACK_EXACT.md:81](/private/tmp/xiaozhi-admin-p0-rectification/docs/engineering/product-v1/admin-auth-p0/ROLLBACK_EXACT.md:81) 明确真实材料/恢复未执行，[RELEASE_SAFETY.md:30](/private/tmp/xiaozhi-admin-p0-rectification/docs/engineering/product-v1/admin-auth-p0/RELEASE_SAFETY.md:30) 要求独立GO、完整回滚验收及维护授权。NAS本轮两次检查 `freeze/pre-adminauth-p0` 均不存在；该检查只覆盖此路径，不证明NAS其他位置没有任何备份，也不能以目录存在证明备份完整。

后续须由另行授权的操作员完成真实镜像、实际配置、Secrets、一致性data安全备份和精确隔离恢复，再验证全部条件；本轮不得代为执行。证据：[NAS前采样](/private/tmp/trae-admin-p0-review/nas-before.json)、[后采样](/private/tmp/trae-admin-p0-review/nas-after.json)、[Linux虚构恢复](/private/tmp/trae-admin-p0-review/candidate-tests/isolated_restore_drill.txt)、[独立完整Policy验证](/private/tmp/trae-admin-p0-review/rollback/policy_restore_independent.json)。

## 6. 停止状态

本轮没有修改生产代码、部署、重启、备份写入、读取生产令牌/密钥内容、合并main或调用真实Qwen。NAS操作仅白名单metadata、文件stat、配置/源码hash、无认证health GET；未读取完整Env/日志/Secrets正文。候选使用本轮自行生成的临时测试凭据。

本地测试容器、fixture volumes、临时凭据及QA临时材料已删除；证据扫描未发现本轮Chrome凭据值；本地VM已恢复停止状态，镜像保留。只新增本报告及独立审查证据，没有应用修复。需先整改F1并重新独立验收，收敛F2–F5，再按授权闭合B6；现有NO-GO不授予后续操作权限。

**复审完成，停止，等待产品负责人授权。**
