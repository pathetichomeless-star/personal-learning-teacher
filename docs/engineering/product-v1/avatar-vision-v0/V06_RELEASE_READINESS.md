# V06_RELEASE_READINESS
分支 avatar-vision-v06-mac-native @ d31d05e（基线 f518778）。
可发布判定：**PARTIAL**——逻辑层+测试 PASS；QML/插件装配待下一切片；Mac 真机验收=PO 人工门禁；
真实 Tina RMS 口型=冻结链路例外待批。
进入真实 Qwen 单图测试前必须：① 装配完成 + PO 真机验收 ② 视觉 token 生产配置 ③ 会话亲和机制
（多会话歧义拒绝）④ PO 明确批准计费影响。
冻结保护：audio/vad/turns 零 diff（复核员实测）；NAS 生产（Admin V2 038d2f6c7a89）零触碰。
