FRONTEND_AUDIT
date: 2026-10-09
scope: admin/ 前端只读审计（分支 avatar-vision-v06-mac-native，该分支 admin/ 与冻结 tag d5644f1 哈希一致）；生产分支 admin-visual-v2 哈希不同，见 BRANCH_HASHES。

DEFECT_TABLE
| # | 缺陷候选 | 结论 | 证据（file:line） |
|---|---------|------|-------------------|
| 1 | setToken() 清空输入框并更新徽章，但不向后端验证令牌 | 确认 | admin/app.js:87-92（setToken 无任何 fetch）；app.js:96-101（renderAuthBadge 仅凭 token 存在即显示 HEALTHY/绿色）；app.js:774-776（连接按钮只调 setToken）。后果：假令牌也显示"已连接"，所有请求随后 401 |
| 2 | 空输入点"连接"会覆盖/清掉 sessionStorage 里的有效令牌 | 确认 | admin/app.js:775（`setToken(input.value \|\| "")`）；app.js:88-89（空串走 `sessionStorage.removeItem(TOKEN_KEY)`）。且输入框在 app.js:90 被无条件清空，用户无法区分"已连接"与"刚被清空" |
| 3 | 令牌不 trim，粘贴带尾随空白/换行即永久 401 | 确认 | admin/app.js:775（raw `.value`，无 `.trim()`）；api() 在 app.js:109 直接拼 `Bearer + t`。后端 compare_digest 对空白敏感 → 401 循环，且因缺陷 4 徽章仍显示 HEALTHY |
| 4 | 401 处理：徽章不真实、AUTH_FAILED 是死状态 | 确认 | admin/app.js:118（401 时仅调 renderAuthBadge，坏令牌仍在 → 徽章依旧 HEALTHY）；app.js:10 定义 `AUTH_FAILED` 但全文件零引用（grep 证实）；无 401 后自动清令牌/全局处理。各页面仅对首个请求检查 401（如 app.js:154, 211, 246, 313, 426, 512, 672, 719），页面后续请求的 401 只进 showError |
| 5 | 仅 sessionStorage，新标签页令牌丢失 | 确认（按设计） | admin/app.js:85, 88-89；app.js:2 注释明示；app.js:139 UI 文案也提示"仅保存在当前标签页"。属安全取舍，P0 不必改，但连接验证（缺陷 1 修复）会让丢失后果更可感知 |
| 6 | 分支/生产哈希比对 | 见 BRANCH_HASHES | 本地分支与冻结 tag 一致；生产分支 admin-visual-v2 的 app.js/index.html 哈希不同，需与 browser-diag 测得的 served hash 对比后才能断言"线上跑的是哪份代码" |

BRANCH_HASHES
SHA-256（`git show <ref>:admin/<file> | shasum -a 256`）：

| ref | admin/app.js | admin/index.html |
|-----|--------------|------------------|
| avatar-vision-v06-mac-native（当前分支） | f725215be59f71a5040eff17748cd3e14c98cc3408516f2e7bb4623ff6cabd47 | 1e9297f8136497be504798ee43cb6c17ed0f862fcd29a16e9884dbd420560ae2 |
| admin-visual-v2（生产分支） | 42c4a0e4ab2804bac3aeef5205742ceaba56be4da0c27b0feae7557ce7d119ea | 4dd6d985464da3c01624c7e52abc4770848b910c5f5287768cd683d5e0687eee |
| d5644f1（冻结 tag，= d5644f1956eccae2fa05d66422f8c998b1648663） | f725215be59f71a5040eff17748cd3e14c98cc3408516f2e7bb4623ff6cabd47 | 1e9297f8136497be504798ee43cb6c17ed0f862fcd29a16e9884dbd420560ae2 |

结论：avatar-vision-v06-mac-native 的 admin/ 与冻结 tag d5644f1 完全一致（哈希相同），本次审计即为对冻结基线的审计。admin-visual-v2 两份文件均有差异。若 browser-diag 测得 served hash = 42c4a0e4…，则线上即生产分支代码，本审计结论需在 admin-visual-v2 上复核一遍 diff 后才可照搬。

FIX_SPEC（admin/app.js 最小改动，不动 index.html）
1. trim + 空输入守卫（修缺陷 2、3）— init() 中连接按钮 handler（现 app.js:774-776）：
   ```js
   var v = document.getElementById("token").value.trim();
   if (!v) { render(CURRENT); return; }   // 空输入：不碰已存令牌
   setToken(v);
   ```
   setToken() 内保持现有行为（非空才 setItem），并仅在 v 非空时清输入框。
2. 连接即验证（修缺陷 1）— setToken(v) 后立刻调用现有 `GET /admin/health`（页面已用同一 api() 通道，app.js:147）：
   - 200 → 徽章 HEALTHY（此时才是真实的）→ render(CURRENT)；
   - 401 → `sessionStorage.removeItem(TOKEN_KEY)`（坏令牌不留），徽章 AUTH_FAILED + 输入框旁提示"令牌无效（401）"；
   - 网络失败 / 5xx → 徽章 UPSTREAM_UNAVAILABLE（warn 色），令牌保留供重试。
   后端侧无需新端点。
3. 徽章真实性（修缺陷 1/4 的显示面）— renderAuthBadge()（app.js:96-101）去掉"有 token 即 HEALTHY"：
   - 无 token → AUTH_REQUIRED（灰）；
   - 有 token 但未验证 → VERIFYING（默认色）；
   - 仅在 /admin/health 200 后 → HEALTHY（ok）；401 后 → AUTH_FAILED（warn）。
   AUTH_FAILED / UPSTREAM_UNAVAILABLE 这两个已定义的 UI_STATE（app.js:10-11）由此真正投入使用。
4. api() 的 401 真实回显（修缺陷 4）— app.js:118 处由 `renderAuthBadge()` 改为"徽章置 AUTH_FAILED（不动存储，允许重输）"；同时 showError()（app.js:122-134）按状态码区分文案：401 → "令牌无效或已过期（401）"；403 → "权限不足（403）"；≥500 → "服务端错误（UPSTREAM_UNAVAILABLE）"，保留 request_id 透出。
5. sessionStorage（缺陷 5）— 保持现状（安全取舍），仅由 markAuthRequired 的既有文案（app.js:139）向用户说明；P0 不引入 localStorage。
