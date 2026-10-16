# -*- coding: utf-8 -*-
"""老师路由拒绝码 → 普通用户中文提示（R3-2C 共享映射）。

被两处使用：
* `src/protocols/websocket_protocol.py` —— 老师 WS 握手被 401/409 拒绝时；
* `src/ui/gui/models/settings_model.py` —— 设置页获取老师列表失败时。

纪律：提示绝不包含部署令牌或任何密钥；`detail` 只在确认非敏感（模型 id 等
服务端标识）时附带。
"""

#: 服务端 `{"error": code}` → 中文提示
TEACHER_ERROR_CN = {
    "invalid_token": "部署令牌无效或缺失",
    "teacher_voice_not_configured": "服务端未开启老师语音服务",
    "teacher_not_found": "老师不存在或已删除",
    "teacher_disabled": "该老师已停用，请先在管理后台启用",
    "frozen_realtime_only": "该老师为内置链路，请选择其他老师",
    "voice_mode_text": "该老师当前为文字教学，未开启语音",
    "realtime_model_not_configured": "该老师未绑定实时语音模型",
    "provider_missing": "该老师的服务商不存在，请联系管理员",
    "model_missing": "老师绑定的模型未登记",
    "model_disabled": "老师绑定的模型已停用",
    "evidence_missing": "模型验证证据不足，需先在后台完成能力验证",
    "capability_mismatch": "模型能力不满足实时语音要求",
    "credential_missing": "网关未配置该老师的服务商凭据",
    "realtime_not_configured": "网关未配置模型注册表或凭据",
    "provider_incompatible": "该服务商协议无法用于实时语音",
    "frozen_provider": "该服务商为冻结链路，请更换",
    "frozen_model": "该模型为冻结链路，请更换",
    "realtime_endpoint_not_configured": "该服务商的实时端点不可用",
    "credential_isolation_violation": "凭据隔离校验失败，连接已拒绝",
    "realtime_probe_not_authorized": "实时验证需产品负责人独立授权",
}


def teacher_error_cn(code, detail="", *, with_detail=False):
    """把服务端拒绝码翻译成中文；未知码返回 None（调用方自行兜底）。

    `detail` 仅在 `with_detail=True` 且非空时附带（目前只用于 model_missing
    这类"缺了哪个模型 id"的非敏感标识）。
    """
    base = TEACHER_ERROR_CN.get(str(code or ""))
    if base is None:
        return None
    if with_detail and detail and str(code) == "model_missing":
        return "%s（%s）" % (base, detail)
    return base
