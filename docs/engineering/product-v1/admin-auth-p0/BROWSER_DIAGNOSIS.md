# BROWSER_DIAGNOSIS — NAS 中文管理控制台 AUTH_REQUIRED 排查

```
BROWSER_DIAGNOSIS
date=2026-10-09
branch=avatar-vision-v06-mac-native (local <project-root>/admin/)
PAGE_VERSION=MISMATCH — served app.js sha256=42c4a0e4ab2804bac3aeef5205742ceaba56be4da0c27b0feae7557ce7d119ea
             local  app.js sha256=f725215be59f71a5040eff17748cd3e14c98cc3408516f2e7bb4623ff6cabd47
             服务端版本比本地分支【新】：served 含 SECURITY R5（401 清令牌）与 ADMIN-VISUAL-V2 趋势图代码，本地分支均无
FLOW_ASCII_WRONG=输入 "diag-invalid-token-123"(22B) → 连接：徽章变绿色 HEALTHY（仅表示"存储了令牌"，未发任何请求，main 仍显示 AUTH_REQUIRED）→ 点仪表盘：/admin/health 返回 401
                 {"error":"unauthorized","request_id":"5bd27d9c7c02"} → 令牌被【静默清除】(sessionStorage 变 null)、徽章回 AUTH_REQUIRED、页面【无任何错误提示】(errorText=null)
FLOW_NONASCII=输入 "diag－token－中文" → 连接：徽章 HEALTHY、令牌存入 sessionStorage → 点仪表盘：fetch 客户端直接抛异常
              "Failed to execute 'fetch' on 'Window': ... String contains non ISO-8859-1 code point" → main 显示"页面渲染失败（ERROR）"+英文异常文本
              令牌【持续残留】、徽章【保持 HEALTHY】（绿色"已连接"假象）；curl 直接打后端：非 ASCII Bearer → HTTP **500**（"500 Internal Server Error / Server got itself in trouble"，非 401）——后端缺陷确认
FLOW_EMPTY=空输入点连接 → setToken("") → 无操作、无报错，徽章保持 AUTH_REQUIRED
SESSION_STORAGE=key=xz_admin_token（sessionStorage，按标签页隔离）。无效令牌会残留且徽章声称 HEALTHY，直到某次渲染触发 401 才被静默清除；非 ASCII 令牌永远残留（客户端抛异常收不到 401）。新开标签页令牌即丢失。
RELOAD=带坏令牌刷新 → init→render(dashboard)→/admin/health 401→令牌被静默清除→AUTH_REQUIRED（自动重试存在，但失败完全无提示）
```

## 根因证据链（ROOT_CAUSE_EVIDENCE）

PO 症状（正确令牌仍见 AUTH_REQUIRED）由以下缺陷叠加造成，均已在真实 Chromium + 真实生产页取证：

1. **连接按钮不刷新主视图**（served app.js:919-921 `init()` 内 `#connect` handler 只调 `setToken()`，不触发 `render()`）：
   粘贴【正确】令牌点"连接"后，右上徽章变绿 HEALTHY，但 main 面板依旧显示"需要管理员令牌（AUTH_REQUIRED）"——必须再手动点导航（仪表盘）才会发请求。PO 以 main 面板为准 → 看起来"连接了还是 AUTH_REQUIRED"。
2. **401 静默清令牌且零错误提示**（served app.js:118-121 `api()` 401 → `clearToken()`；pageDashboard 401 分支直接 `markAuthRequired`，不调 `showError`；`UI_STATE.AUTH_FAILED` 已定义但全文件【从未使用】，徽章永远只有 AUTH_REQUIRED/HEALTHY 两态）：
   任何一次 401（令牌输错、粘贴带杂质）都会把令牌悄悄抹掉并回到 AUTH_REQUIRED，无"令牌无效"提示 → 死循环式重试。
3. **非 ASCII 令牌双缺陷**：
   - 前端：fetch 抛 ISO-8859-1 异常 → 令牌残留 + 徽章假 HEALTHY + 英文报错，只能手动"清除令牌"逃生；
   - 后端：该类 Authorization 头到达后端时返回 **500**（未处理异常）而非 401 —— 已用 curl 复现。
4. **徽章语义误导**：`renderAuthBadge()`（app.js:96-101）对任意非空令牌显示绿色 HEALTHY，从不反映真实鉴权结果。
5. **sessionStorage 按标签页隔离**：PO 若换标签页/重开窗口，令牌即丢，回到 AUTH_REQUIRED。

最可能解释 PO 实际经历的链条：粘贴正确令牌 → 点连接 → 徽章绿但 main 仍 AUTH_REQUIRED（缺陷1）→ 刷新页面（触发 401 重试链）或期间任何一次 401（如粘贴瞬间带杂质）→ 令牌被静默清除（缺陷2）→ 无论重粘多少次都看到 AUTH_REQUIRED。若令牌本身含非 ASCII 字符（从文档复制时被转换），则命中缺陷3的 500/异常路径，表现同样为"永远连不上"。

## 测试边界

- 全程使用代表性无效令牌（ASCII / 非 ASCII / 空），未接触真实管理员令牌；报告中只有状态码、徽章文本与长度。
- `/admin/health` 无令牌=401、dummy Bearer=401（curl 复核，与服务端行为一致）。
- 本地分支 `avatar-vision-v06-mac-native` 的 admin/app.js 落后于 NAS 上实际部署版本，修复需先对齐部署基线。
