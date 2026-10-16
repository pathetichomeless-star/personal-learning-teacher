# CODEX ADMIN P0 CROSS AUDIT

**结论：NO-GO。当前修复禁止部署。** 后端非 ASCII 500 根因及修复得到独立验证，但最终前端仍有可复现功能缺陷；现有回滚方案不能精确恢复当前 ADMIN-V2 生产版本。

审计日期：2026-10-09（Asia/Shanghai）；NAS 主要取证时间 23:16:33，报告整理时间约 23:24。审计期间仅修改本报告及新增证据文件；未修改生产源码、提交、合并、部署、重启 NAS 或共享容器，未发起语音连接或付费 Qwen 测试，未读取生产令牌内容。

## 1. 实际审计范围、工作区与隔离

| 项目 | 独立取证结果 |
|---|---|
| 主工作区 | `<project-root>`；分支 `avatar-vision-v06-mac-native` |
| 主工作区 HEAD | `d177582e1e4ec4737ca0ef8ec68966ce7fb7798d` |
| 修复工作区 | `/private/tmp/p0_fix`（Git 所登记路径）；分支 `fix/admin-auth-p0` |
| 实际审计 HEAD | `31b024b47889264404beae9891586e85e7838628` |
| 修复工作区状态 | 审计前后均干净；未 checkout、reset、clean、stage 或 commit |
| Git worktree | 实际仅上述两个工作区 |
| 分支共同祖先 | `d5644f1956eccae2fa05d66422f8c998b1648663`；`e51d9a5` 不是数字人分支的祖先 |

主工作区已有未提交修改：`client/probe_avatar_qml_offscreen.py`、`client/src/avatar/runtime/avatar_page.js`、`client/src/ui/gui/manager.py`、`client/src/ui/gui/qml/components/AvatarLive2D.qml`、`docs/engineering/product-v1/avatar-vision-v0/V1_MAC_GUI_ACCEPTANCE.md`；已有未跟踪 `client/src/avatar/runtime_server.py`、`docs/engineering/product-v1/admin-auth-p0/`。审计未改动这些源码或既有文档，末次检查既有变更清单一致；新增报告及 `codex-evidence/` 为本轮审计产物。没有审计前的逐文件哈希快照，因此不将状态清单一致描述为对并行开发文件内容的完整哈希证明。

测试仅从修复工作区读取代码，存储、测试令牌、服务和脚本均在 `/private/tmp/codex-xiaozhi-admin-p0-audit/`。没有启动数字人客户端，也没有从主工作区构建生产镜像。两分支已分叉，未来从数字人工作区直接构建本次修复镜像会混入未部署变更，必须禁止。

## 2. 完整提交链与最终 diff

实际线性链，无缺失提交或 merge：

```text
e51d9a5adc06274025008c052bec319466934e09
  → 2f1b2ebec5adf9dd8256aa9c604aa7432c2d8659
  → 8962061e8c7010e16953e82b109c50e97f4ed4d5  （P0_FINAL_QA 文档）
  → 31b024b47889264404beae9891586e85e7838628  （前端 ASCII 输入检查）
```

独立逐项读取 `git diff e51d9a5..31b024b`：6 文件，185 行新增、4 行删除。生产代码仅 `gateway/app/admin/auth.py`、`admin/app.js`；另有两份新增测试、`admin_security_tests.py` 尾部换行调整及 QA 文档。Qwen、Tina、VAD、Opus、打断代码、部署配置、PolicyStore 实现和数字人文件均无本次 diff。

**原 QA 不能覆盖最终提交。** [P0_FINAL_QA.md](/private/tmp/p0_fix/docs/engineering/product-v1/admin-auth-p0/P0_FINAL_QA.md:6) 明确锚定 `2f1b2eb`。后来的 `31b024b` 修改生产前端，但没有增加对应浏览器回归测试。三套 Python 测试不能据此证明新前端通过。本轮已对最终 HEAD 补做真实浏览器测试，结果存在失败。

证据：[提交链](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/commit_chain.txt)、[完整差异](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/final_diff.patch)、[修复区末次状态](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/fix_worktree_final_status.txt)。`git diff --check` 另提示测试文件 EOF 多余空行，属于非阻断格式问题。

## 3. 根因与后端安全复核

根因真实。基线 `TokenStore.matches()` 直接调用 `hmac.compare_digest(str, str)`；非 ASCII 字符触发 `TypeError`，未处理异常由 aiohttp 返回 HTTP 500。本轮使用基线源码中的 TokenStore 接入真实隔离 admin app，复现中文、BOM、Latin-1 输入 HTTP 500；最终源码同样输入返回 401。不是引用 Trae 结果。

修复位于 [auth.py:81](/private/tmp/p0_fix/gateway/app/admin/auth.py:81)：UTF-8 bytes 比较，捕获 `TypeError`、`UnicodeEncodeError`、`UnicodeDecodeError`，普通 HTTP 字符串输入的故障得到修复。空值返回 False；错误 ASCII、Unicode、孤立 surrogate、非字符串测试值及长输入的实际行为见独立日志。HTTP 无令牌、空 Bearer、错误方案、错误令牌均返回 401；有效令牌返回 200。全角尾随空格由 `_bearer().strip()` 去掉后可返回 200；直接 `matches()` 不做这个 trim，二者测试结果不矛盾。

[auth.py:118](/private/tmp/p0_fix/gateway/app/admin/auth.py:118) 的错误响应固定为 `error=unauthorized` 和 `request_id`；无匿名/错误令牌细节、令牌值或路径。日志只记录拒绝原因、请求路径及材料是否配置，本轮临时令牌未进入响应或日志。不能把这表述为对所有异常、所有日志入口或所有时序 oracle 的绝对证明。

比较使用 `hmac.compare_digest(bytes, bytes)`，没有自行逐字符比较或按首个不匹配字符提前返回。没有固定长度检查；空值先拒绝、变长字节比较与编码成本仍可能体现输入长度，**并非所有长度和所有路径耗时相同**。这不构成本轮已证实的认证绕过；已有 S10 只是源码字符串断言，不能证明恒定耗时。独立测试覆盖较短、不同长度、8000 字节 HTTP 值及 100000 字符直接比较，没有产生修复后的认证 500。

[auth.py:128](/private/tmp/p0_fix/gateway/app/admin/auth.py:128) 对有效凭据统一赋 `OPERATOR`，本认证中间件没有角色权限的 403 分支。错误凭据的正确行为是 401；本轮 403 浏览器检查为显式注入的 UI 状态测试，不是证明后端存在独立 RBAC。未发现本次后端修复引入认证绕过或凭据泄露。

## 4. 阻断缺陷及前端实际表现

以下缺陷有源码和执行证据，未在审计中修复。12 个浏览器失败断言包含同一原因的重复场景，不代表 12 个独立漏洞。

| 编号 / 风险 | 源码位置 | 实证与影响 | 必须完成的处理 |
|---|---|---|---|
| B1 / 高：后台静态依赖未暴露（基线既有） | [index.html:43](/private/tmp/p0_fix/admin/index.html:43)、[app.py:41](/private/tmp/p0_fix/gateway/app/admin/app.py:41)、[views.py:19](/private/tmp/p0_fix/gateway/app/admin/views.py:19) | 页面加载 `shared.js`，路由与文件 allowlist 均缺失。基线、最终隔离 app 都 404；NAS 生产静态 GET 同样 404。成功认证后仪表盘显示 `页面渲染失败（ERROR）：XZ is not defined`。 | 补全固定静态路由、allowlist、JS Content-Type 和真实 shell 回归；不能用提供缺失资源的测试 harness 当正式验收。 |
| B2 / 中：成功徽章被覆盖 | [app.js:123](/private/tmp/p0_fix/admin/app.js:123)、[app.js:915](/private/tmp/p0_fix/admin/app.js:915)、[app.js:152](/private/tmp/p0_fix/admin/app.js:152) | `verifyConnection()` 的 200 短暂设置“已连接”，随后 `render(CURRENT)` 的 API 请求逐次调用 `renderAuthBadge()`，稳定状态回到“待验证”。提供缺失 shared.js 后仍复现；刷新、重复连接也失败。 | 建立与当前凭据绑定的验证状态；普通 API 请求不得无条件重置徽章，补刷新、导航、轮询和重复连接测试。 |
| B3 / 中：网络失败没有正确错误状态 | [app.js:116](/private/tmp/p0_fix/admin/app.js:116)、[app.js:915](/private/tmp/p0_fix/admin/app.js:915)、[app.js:963](/private/tmp/p0_fix/admin/app.js:963) | 注入连接失败时 `fetch()` 抛 `Failed to fetch`，`verifyConnection()` 没有 catch，事件处理器也不处理 Promise。徽章停在“待验证”，不可达分支没有执行。 | 捕获网络拒绝与超时，显示统一中文不可达状态；验证浏览器没有 unhandled rejection。 |
| B4 / 中：非法令牌被持久化，刷新/导航绕过输入守卫 | [app.js:85](/private/tmp/p0_fix/admin/app.js:85)、[app.js:109](/private/tmp/p0_fix/admin/app.js:109)、[app.js:953](/private/tmp/p0_fix/admin/app.js:953) | 31b024b 的守卫阻止当次连接请求，但先 `setToken(t)` 把非法输入存入 sessionStorage，并清空输入框。切换页面、刷新再次读出并执行 fetch，出现 `String contains non ISO-8859-1 code point`；刷新后特定中文提示也丢失。 | 非法输入不应覆盖有效存储；持久化恢复和 API 边界同样校验；补已有有效令牌被非法输入覆盖、刷新和导航测试。 |
| B5 / 中：凭据变更与旧请求竞态 | [app.js:119](/private/tmp/p0_fix/admin/app.js:119)、[app.js:918](/private/tmp/p0_fix/admin/app.js:918)、[app.js:965](/private/tmp/p0_fix/admin/app.js:965) | 延迟健康检查成功→点击清除→旧 200 返回，最终 sessionStorage 无令牌但徽章“已连接”；旧错误令牌的延迟 401 能清掉后来已验证的新令牌。 | 使用请求序号/凭据代次或取消机制；旧响应不能改变新凭据及认证状态，覆盖两种竞态。 |
| B6 / 中：生产精确回滚尚未成立 | RELEASE_SAFETY.md:13、23；NAS 镜像、挂载和 freeze 实证 | 当前是 `038d2f6c…`；所述回滚切到 `34ea8277…`，属于退回 ADMIN-V2 之前。P0 完整备份不存在，不能声称精确恢复已验证。 | 改为固定当前完整镜像 ID 的恢复方案，补配置/秘密材料/持久卷完整备份及隔离恢复验收。 |

其他行为：空输入不会清除已有令牌，但点击“连接”直接返回，没有重新请求 `/admin/health`；因此自动清空输入框后的第二次点击不能重试。这需要明确产品行为并补回归。真实 401 能清除存储并显示“令牌无效”；注入的 403、500 能显示对应中文徽章。全角外部空白 trim 有效；内部控制字符和中文首次连接被拦截。独立新标签页没有令牌，切回原标签页令牌仍在；本轮未验证浏览器“复制标签页”及带 opener 新窗口的 sessionStorage 复制语义，不能把它们与普通新标签页等同。

## 5. 独立执行命令、环境与结果

全部主动认证请求使用源码套件的公开测试常量或临时错误值；存储为新建临时目录。HTTP 测试使用真实 aiohttp TestServer；网关信息为 mock，没有运行 Qwen 链路。NAS 只读 HTTP 请求限于健康和静态资源，不携带管理员令牌、不做主动认证探测。

第一轮环境：macOS arm64，Python 3.14.7 / aiohttp 3.14.4。随后独立建立临时环境 Python 3.12.13 / aiohttp 3.14.3 再跑，匹配生产 Python 主次版本及 aiohttp 精确版本。生产实测为 Linux arm64、Python 3.12.15 / aiohttp 3.14.3；本地 Python patch 与系统平台仍不同，**未完成候选生产镜像内验收**。尝试获取 3.12.15 时当前 uv 不支持下载，保留失败证据，没有伪称版本完全一致。

工作目录 `/private/tmp/p0_fix`。第一轮解释器为 `<project-root>/gateway/.venv/bin/python`，仅借用解释器和依赖，不从数字人分支加载生产代码。第二轮实际命令：

```sh
uv venv --python <user-home>/.local/bin/python3.12 /private/tmp/codex-xiaozhi-admin-p0-audit/venv312
uv pip install --python /private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python 'aiohttp==3.14.3'
/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python -B gateway/tests/admin_security_tests.py
/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python -B gateway/tests/p0_nonascii_regression.py
/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python -B gateway/tests/p0_e2e_http.py
/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python -B gateway/tests/admin_ui_tests.py
/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python -B /private/tmp/codex-xiaozhi-admin-p0-audit/independent_http.py
/private/tmp/codex-xiaozhi-admin-p0-audit/venv312/bin/python -B /private/tmp/codex-xiaozhi-admin-p0-audit/browser_server.py
node /private/tmp/codex-xiaozhi-admin-p0-audit/browser_checks.cjs
```

| 测试 | PASS | FAIL | 实证范围 |
|---|---:|---:|---|
| admin_security（两环境各自执行） | 29 | 0 | 后端认证、路由、错误响应、临时数据写入等 |
| p0_nonascii（两环境各自执行） | 5 | 0 | TokenStore 非 ASCII 回归 |
| p0_e2e_http（两环境各自执行） | 5 | 0 | 真实隔离 HTTP app；不是生产 API 验收 |
| admin_ui（两环境各自执行） | 23 | 0 | 现有静态合同套件；漏检 shared.js，不等于浏览器通过 |
| 自编基线/最终 HTTP 与异常矩阵（两环境各自执行） | 70 | 2 | 72 断言；两次失败均是基线/最终 shared.js 404；预期复现旧 500 算复现成功 |
| Chrome 原样最终 shell | 1 | 3 | 实际请求 health 成功；静态资源、仪表盘和稳定徽章失败 |
| Chrome 辅助场景 | 10 | 9 | **显式仅补供 shared.js** 后隔离验证 P0 逻辑；403/500/断网/竞态为注入故障 |
| Chrome 基线前端差异 | 1 | 0 | 复现未请求 health 却宣称 HEALTHY |
| Chrome 合计（两轮分别一致） | 12 | 12 | 24 断言，不作重复执行累计计数 |

自编 HTTP/浏览器脚本收集失败断言后正常退出；表中按断言统计，未以退出码 0 判定全部通过。

浏览器实际是 **Google Chrome 155.0.8059.39，headless，独立临时配置文件**，仅访问 `127.0.0.1:18764`。browser-use doctor 检测到没有可用 daemon/browser connection，使用本地 Playwright 启动独立 Chrome；没有读取用户 Chrome 的生产页面、sessionStorage 或令牌。原样 shell 检查没有拦截补资源；后续辅助用例明确标注，不能当候选原样通过。两个临时测试服务均已关闭。

**生产 Chrome 人工验证：未执行、未通过。** NAS 静态资源 404 的生产实测，不等于在生产 Chrome 登录验收。证据目录 [codex-evidence](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/) 包含实际 stdout/stderr、脚本、JSON、完整 diff、源码哈希和证据文件校验清单。主结果：[浏览器摘要](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/browser_summary.json)、[HTTP 前后对比](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/independent_http.json)。

![隔离 Chrome 成功认证后仍出现页面错误和待验证徽章](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/unmodified_success.png)

## 6. NAS 实际生产状态与共享生命周期

通过 `ssh -o BatchMode=yes xiaozhi-nas python3 -` 执行白名单取证：`docker inspect`、`docker image inspect`、`docker top … -eo pid,comm`；使用 `docker exec … python -B -c …` 仅读取版本、源码哈希和文件 stat。没有输出完整 Docker Env、容器日志、配置内容、数据内容或 secret 文件内容。

实际完整镜像 ID：

```text
sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611
```

容器 ID `295eb64dc48c364de65cc4a5d163a60ec9aa1d936cf2909fafe53e2937b4c4bd`，running / healthy、RestartCount=0；启动时间 `2026-10-09T06:36:55.857693136Z`（上海 14:36:55）。末次 NAS 检查的容器 ID、镜像、启动时间与重启计数一致。镜像带 `admin-visual-v2-release` 及 compose `latest` 标签，RepoDigests 为空。容器内 `/app/app`、`/app/modules`、`/app/admin-ui` 中 36 个 `.py/.js/.html/.css` 文件逐一与 `git show e51d9a5:<path>` 的 SHA-256 比较，**36/36 相同**。这证明所检查源码匹配基线；不把它扩展为镜像中所有二进制、配置和依赖都已验证。

| 主机端口 | 容器端口 | 服务 |
|---|---|---|
| 28310 | 8110 | 实时语音 WebSocket |
| 28311 | 8111 | health / HTTP |
| 28312 | 8112 | 中文后台 |

三个端口属于同一容器，`docker top` 仅一个 Python 进程；CMD=`python -m app.main`。[main.py:97](/private/tmp/p0_fix/gateway/app/main.py:97) 同一 `_run()` 建立语音、HTTP 与 admin listener，并在退出时统一清理。端口当前绑定 IPv4/IPv6 全接口；本轮没有验证 NAS 防火墙或公网路由，不能独立证明 LAN-only。

源码非运行时 bind mount；本次后端修复按现有镜像部署机制需要更换/重建容器，必然中断 28310、28311、28312。没有已验证的后台单独热更新方案。健康探针只检查 8111，healthy 本身不能证明 admin、浏览器或真实口语质量合格。

生产安全环境白名单实测：QWEN_MODE=real、模型 qwen3.5-omni-plus-realtime、Tina、FRAME_MS=20、PUBLIC_WS_URL 指向既有 28310。主取证采样 `/health` 返回 HTTP 200、`ws_connections=1`、`qwen_connected=1`、`qwen_sessions=2`。**采样时已有活动语音连接，禁止据旧报告 ws=0 进入维护。** 未主动连接或调用 Qwen。

## 7. 当前回滚路径与恢复要求

实测另一个镜像：

```text
sha256:34ea8277cb571f327d14deb43659c6dba71c4cd49677a15b1d580cd93445a6a4
```

其标签为 `XIAOZHI-VOICE-V1-HUMAN-ACCEPTED`，创建于 10 月 8 日；当前 ADMIN-V2 镜像创建于 10 月 9 日。NAS `freeze/pre-adminv2/running_image_id.txt` 实际写的正是 `34ea8277…`；该目录仅有镜像 ID、compose、`.env`、`policy_v20.json` 四项。结合 [deploy-log.md:176](<project-root>/docs/engineering/deploy-log.md:176)，原因明确：**它是 ADMIN-V2 上线前的回滚锚点，被错误复用为本次 P0 的回滚方案。** 旧镜像确实存在，但存在不代表能精确恢复当前版本；本轮没有启动旧镜像或验证其语音/后台行为。

当前挂载与恢复依赖：

| 项目 | 实测及要求 |
|---|---|
| 镜像 | 保存/固定当前完整 `038d2f6c…` ID；不能依赖可变 latest 或用 34ea8277 替代。需要受控导出与校验，以及隔离恢复验证。 |
| Compose / env | `/volume1/docker/xiaozhi-product-v1/docker-compose.yml` 与 `.env`；保留端口、Qwen real/Tina、资源/权限配置和镜像固定引用。 |
| 配置 | `/app/config/config.json` 在镜像内，非 bind mount；NAS staging 的 `config/config.json` 仅做 metadata 检查，未证明其内容与镜像内配置相同。恢复必须以实际运行镜像配置为准。 |
| secrets | 主机 `…/secrets` → `/app/secrets:ro`；admin 与 Qwen secret 文件均 uid/gid=10001、0600。由授权操作员安全备份/恢复，不得进入源码、审计日志或普通证据包。 |
| 数据卷 | 主机 `…/data` → `/app/data:rw`；目录 0700、uid=10001；policy/memory/knowledge 文件 0600、uid=10001（实测文件 gid=0）。须保留完整数据目录、策略版本历史/审计及所有权，不能只备份某个 v20 导出。 |
| 本次备份 | `freeze/pre-adminauth-p0` **不存在**；本轮没有创建 NAS 备份，完整性和恢复演练未通过。 |

旧镜像 retag + force-recreate 的文档方案会丢失当前 ADMIN-V2 的镜像层变化，并再次中断实时语音。**B6 属于部署阻断。** 当前镜像/实际运行状态没有与已知 ADMIN-V2 声明不一致；有证据冲突的是“已验证精确回滚”和“当前可以重启”的结论。

证据：[NAS 主取证](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/nas_readonly.json)、[静态资源及末次状态](<project-root>/docs/engineering/product-v1/admin-auth-p0/codex-evidence/nas_followup.json)。

## 8. 实时口语保护结论

本轮没有改动语音源码、生产 28310 配置、容器或存储，没有真实 Qwen 测试。只读采样和源码读取没有引发重启，启动时间及重启计数未变化。不能据此宣称已做真实 Tina 对话回归；产品负责人已有的正常对话能力应继续保留。

候选修复的直接源码范围没有 Qwen、Tina、VAD、Opus 或打断改动；但共用进程意味着更新后台的重建操作必然短暂停掉口语连接。只有后续人工批准维护窗口、临近操作复查连接为零并由产品负责人确认停止练习后，才可考虑执行。

## 9. 浏览器人工验收尚需完成

先关闭 B1–B5 并独立重跑，再用候选原样镜像在隔离 Chrome 验收，不能补供资源或借已有登录态掩盖缺陷。必须覆盖：首次加载 shared.js 200/正确类型、有效令牌稳定“已连接”和可用首页、错误令牌 401 清除、403/500/断网中文提示、非法字符不污染存储、刷新/导航/实时页轮询/重复连接、空输入重试行为、清除与旧响应竞态，以及新标签页/复制标签页/切回行为。控制台不得再出现 XZ、fetch Header 或未处理 Promise 错误。

生产 Chrome 的真实登录与刷新验收仍待产品负责人在后续批准流程中亲自完成；生产令牌由负责人输入，不由审计员读取或记录。完成后才可标记“生产 Chrome 实际验证通过”。真实口语复验由产品负责人决定，本轮不安排或执行付费模型测试。

## 10. 受控生产部署门槛

当前不满足部署条件，**NO-GO**。解除阻断后必须重新独立审核最终 HEAD，以下条件全部成立才能改判：

1. B1–B5 修复并有原样浏览器回归；补测不能只依赖当前全绿的 Python 套件。空输入重试行为须明确。
2. 候选从已批准修复分支构建，不带数字人分支或未提交成果；记录完整提交、镜像 ID、完整 diff 和冻结语音源码哈希。
3. 在隔离的候选生产镜像内运行认证/HTTP/浏览器检查，覆盖实际 Linux/Python 3.12.15/aiohttp 环境；不得使用生产卷、令牌或真实 Qwen。
4. 完成当前 `038d2f6c…` 镜像、实际配置、compose/env、秘密材料和完整持久卷的安全备份；制定按该完整 ID 恢复的精确流程并在隔离环境验证。删除文档中将 `34ea8277…` 当本次精确回滚的错误结论。
5. 产品负责人批准维护窗口并确认停止练习；操作前重新只读检查语音/Qwen 活动连接，非零则中止。审计时的一次采样不能替代临近部署的检查。
6. 由后续获授权执行者部署并按 HTTP、静态资源、后台和负责人 Chrome 实际表现验收；不符合即按精确当前镜像回滚。任何真实口语/付费验收仍需负责人安排。

独立审计结束。本轮不执行上述修复、备份、部署、合并或重启，等待产品负责人决定。
