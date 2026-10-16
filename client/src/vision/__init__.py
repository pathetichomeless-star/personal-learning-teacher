"""VISION V0.6 — Mac 客户端视觉模块（默认关闭）。

VISION.ENABLED 默认 False：关闭时本模块不加载、不申请摄像头、不发起任何网络请求，
客户端启动流程与冻结语音链路逐字节一致（见 V06_MAC_UI_ASSEMBLY 装配说明）。
"""
VISION_CONFIG_KEY = "VISION.ENABLED"
VISION_DEFAULT_ENABLED = False
VISION_TOKEN_CONFIG_KEY = "VISION.TOKEN"      # 独立令牌，绝不复用 Admin Token
VISION_ENDPOINT_KEY = "VISION.ENDPOINT"        # 默认 http://127.0.0.1:8111/xiaozhi/vision/
