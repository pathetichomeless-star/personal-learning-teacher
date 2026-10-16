"""AVATAR 数字人引擎解析（纯逻辑，无 Qt 依赖，可独立单测）。

配置项 AVATAR.ENGINE：合法值 live2d | canvas-fallback，默认 live2d。
live2d 仅在 runtime vendor 关键资产齐备时生效；出厂状态仓库不带 vendor，
配置缺失 + 资产缺失自动落 canvas-fallback（由调用方在状态文本明示）。
非法值 / 资产缺失同样回退；显式配置为 canvas-fallback 时恒回退。
"""
from pathlib import Path

ENGINE_LIVE2D = "live2d"
ENGINE_CANVAS = "canvas-fallback"
DEFAULT_ENGINE = ENGINE_LIVE2D
VALID_ENGINES = (ENGINE_LIVE2D, ENGINE_CANVAS)

# 本模块所在目录即 client/src/avatar/
RUNTIME_ROOT = Path(__file__).resolve().parent / "runtime"

# live2d 生效所需的关键资产（相对 runtime/）
VENDOR_KEY_FILES = (
    "avatar_page.html",
    "avatar_page.js",
    "vendor/lib/live2dcubismcore.min.js",
    "vendor/lib/pixi.min.js",
    "vendor/lib/pixi-live2d-display.cubism4.min.js",
    "vendor/models/Hiyori/Hiyori.model3.json",
    "vendor/models/Hiyori/Hiyori.moc3",
)


def resolve_avatar_engine(get_config, runtime_root=None):
    """解析数字人引擎配置。

    Args:
        get_config: callable(path, default) —— ConfigManager 读接口；
                    传 None 表示配置系统缺席（等同配置缺失）。
        runtime_root: 覆盖 runtime 目录（单测用），默认包内 runtime/。

    Returns:
        (engine, reason)：engine 为 ENGINE_LIVE2D / ENGINE_CANVAS；
        reason 为回退原因说明（选择 live2d 时为空串）。
    """
    root = Path(runtime_root) if runtime_root is not None else RUNTIME_ROOT

    raw = None
    try:
        if get_config is not None:
            raw = get_config("AVATAR.ENGINE", DEFAULT_ENGINE)
    except Exception:                                        # noqa: BLE001
        return ENGINE_CANVAS, "配置读取失败，回退 canvas"

    if raw is None:
        raw = DEFAULT_ENGINE                                 # 配置缺失 → 默认 live2d
    engine = str(raw).strip().lower()
    if engine not in VALID_ENGINES:
        return ENGINE_CANVAS, "非法配置 AVATAR.ENGINE=%r，回退 canvas" % (raw,)

    if engine == ENGINE_CANVAS:
        return ENGINE_CANVAS, "配置指定 canvas-fallback"

    for rel in VENDOR_KEY_FILES:
        if not (root / rel).is_file():
            return ENGINE_CANVAS, "运行时资产缺失: %s，回退 canvas" % rel
    return ENGINE_LIVE2D, ""
