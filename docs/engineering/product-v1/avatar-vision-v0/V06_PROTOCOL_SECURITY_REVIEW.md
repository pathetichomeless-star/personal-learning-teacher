# V06_PROTOCOL_SECURITY_REVIEW
继承链：VISION_PROTOCOL_REPORT（官方事件 doc-verified）→ GATEWAY_PROTOCOL_DESIGN（8111 HTTP 传输）→ V05_FINAL_REVIEW（PASS）→ V06_PROTOCOL_ARCHITECTURE（会话亲和缺口）。
本轮闭合：F1 teardown 注销；F2 token 路径简化；F3 mock fail-closed。
会话亲和（多会话歧义）：V06_PROTOCOL_ARCHITECTURE 给出机制（会话绑定匹配或显式 409 ambiguous_session）；
当前单会话 sidecar 下 ACTIVE_INSTANCES 语义安全，多会话支持前必须实现该机制（下一切片）。
计费：图像计入 text/images/video 桶（低于音频 token 单价）；V0.6 仅 mock，零真实调用。
