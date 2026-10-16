BACKEND_AUDIT — XIAOZHI P0 ADMIN AUTH RECOVERY（只读后端审计）
date: 2026-10-09
auditor: p0-backend-audit
scope: gateway/app/admin/auth.py（工作分支 avatar-vision-v06-mac-native @ d177582 与生产分支 admin-visual-v2 @ e51d9a5 双向比对，两者 auth.py 在缺陷路径上逐字节一致）

DEFECT_ROOT_CAUSE=gateway/app/admin/auth.py:84 — `TokenStore.matches()` 直接调用 `hmac.compare_digest(presented, self._token)`，两个参数均为 **str**（presented 来自 `_bearer()` 解析的 Authorization 头，auth.py:87-94；self._token 来自 token 文件/env 读入的 utf-8 文本，auth.py:46）。`hmac.compare_digest` 要求 ASCII-only str 或 bytes，当 Bearer 值含非 ASCII 字符时抛 `TypeError: comparing strings with non-ASCII characters is not supported`。异常流：`matches()`（auth.py:84）无捕获 → `auth_middleware`（auth.py:121-140）无 try/except → `request_id_middleware` 仅捕获 `web.HTTPException`（auth.py:104），TypeError 直接穿透 → aiohttp web_protocol 兜底处理未捕获异常 → **500 Internal Server Error**（而非 401）。生产分支 e51d9a5 的 auth.py 已核实为同一代码，缺陷成立。

FIX_SPEC=最小补丁（auth.py 的 `matches`，diff 级）：
```diff
     def matches(self, presented):
         if not self._token or not presented:
             return False
-        return hmac.compare_digest(presented, self._token)
+        try:
+            return hmac.compare_digest(
+                presented.encode("utf-8"), self._token.encode("utf-8"))
+        except (TypeError, UnicodeEncodeError):
+            return False
```
两侧统一 encode 为 bytes 后比较（保持常数时间语义，S10 源码检查 `"hmac.compare_digest" in src` 仍通过）；非 ASCII 输入与非法 ASCII 输入返回同一 False → 走 auth_middleware 既有 `unauthorized(request, "invalid_token")` 路径（auth.py:138），401 响应体完全一致（`{"error": "unauthorized", "request_id": rid}`），两种拒绝面无 oracle 差异。不需要新增中间件或全局异常处理（授权面不变，改动仅一处函数体）。

TEST_GAP=gateway/tests/admin_security_tests.py **无任何非 ASCII Bearer 行为测试**。S10（tests/admin_security_tests.py:269-270）仅是源码字符串 grep（`"hmac.compare_digest" in src`），非行为断言；全文件仅 2 处 "Bearer"（合法 token 的 AUTH 头），16 处 "non" 均与该用例无关（无 latin-1/非 ASCII/TypeError 相关用例）。补测建议（回归用例）：配置 token 后分别请求 `/admin/health`，Authorization 值含非 ASCII（如 `Bearer token✦` / `Bearer 管理员`）→ 断言 401 + 响应体与无效 ASCII token 的 401 响应体逐字节一致；合法 Bearer → 200（该正向路径 S8b 等已覆盖，tests 行 261-262：`/admin/health` with AUTH → 200）。

LOG_HYGIENE=已核实全部路径 token 不落日志：
- auth.py 全部 log 语句仅输出 source 标签/布尔（auth.py:59、65）与 path+reason（auth.py:113 `unauthorized()`：`log.warning("admin auth rejected path=%s reason=%s", request.path, reason)`，reason 为固定枚举字符串）；
- 500 路径：aiohttp 默认错误日志打印请求行（method+path，不含 headers）与 traceback（traceback 只含代码行 `return hmac.compare_digest(...)`，不含实参值）→ token 不进入日志；
- grep 全 admin 包（app/admin/*.py）无任何输出 Authorization 头/token 值的语句；request_id（auth.py:100）为 os.urandom 随机 hex，非机密。

PRODUCTION_STATUS=**是 — 缺陷在生产运行**。docs/engineering/deploy-log.md:176 记录 2026-10-09 生产发布：分支 admin-visual-v2 @ e51d9a5 → 镜像 **038d2f6c7a89**（tag admin-visual-v2-release），且 V06_RELEASE_READINESS.md:7 复述"NAS 生产（Admin V2 038d2f6c7a89）"。`git show e51d9a5:gateway/app/admin/auth.py` 与缺陷代码一致（auth.py:84 同为裸 str compare_digest）→ 运行镜像 038d2f6c7a89 携带该缺陷：任何非 ASCII Bearer 值触发 500，可被用于指纹/探测生产管理面。
