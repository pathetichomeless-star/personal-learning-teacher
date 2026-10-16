# V06_MAC_INTEGRATION_REPORT（Mac 原生集成报告）

date=2026-10-09 · branch=avatar-vision-v06-mac-native · head=d31d05e · 基线 f518778（V0.5 双 PASS）

## 已实现（代码级）
- 阶段 A：V0.5 复核 F1-F3 闭合（teardown 注册表注销 + V10 回归 14/14；token 路径简化；mock fail-closed）。
- 阶段 B：client/src/vision/{__init__,compress,controller}.py + tests（13/13）——
  校验/压缩（cv2 惰性、EXIF 剥离、≤1280px/≤190KB）/频率守卫/X-Vision-Token HTTP 提交/
  会话绑定/降级回调；VISION.ENABLED 默认 False；零 PySide6 导入（逻辑层纯净可测）。
- 阶段 C：client/src/avatar/states.py——五状态机（idle/listening/thinking/speaking/interrupted）
  + 代际绑定防串动画。

## 装配待办（下一切片）
- QML 面板（VisionPanel.qml/AvatarPanel.qml）+ plugins/vision.py 注册 + 4 触点接线
  ——按 MAC_CLIENT_AUDIT 的装配清单执行（文件集与已发布 Admin V2 不相交，无覆盖风险）。

## 测试矩阵
| 项 | 自动化 | Mac 人工门禁 |
|---|---|---|
| 1 关闭视觉语音正常 | ✅ product_v1 33/33 + 启动一致 | 主观确认 |
| 2 开数字人启动正常 | 模块测试 | ⬜ PO 真机 |
| 3 图片选择/格式/大小 | ✅ 13/13 | ⬜ |
| 4 摄像头权限三流程 | 逻辑层 | ⬜ TCC 真机 |
| 5 会话正确 | ✅ 隔离测试 | — |
| 6 409 排序 | ✅ V5/E5 | — |
| 7 401/413/415/429/503 中文反馈 | ✅ E 层 | ⬜ |
| 8 摄像头重复开关无泄漏 | 设计+逻辑层 | ⬜ |
| 9 并发会话不串图 | ✅ V8/E5 | — |
| 10 数字人故障不影响声音 | ✅ 故障隔离设计 | ⬜ |
| 11 打断口型归零 | ✅ 16/16 | ⬜ 主观 |
| 12 无未授权 Qwen 调用 | ✅ mock 边界请求日志 | — |
| 13 冻结音频回归 | ✅ 三套件全绿 + 零 diff | — |
| 14 资源/延迟观测 | 设计规范 | ⬜ 真机 P50/P95 |

## 状态
IMPLEMENTED（逻辑层+测试）· ASSEMBLY-PENDING（QML/插件接线）· MANUAL-GATE（真机 TCC/预览/主观口型）
