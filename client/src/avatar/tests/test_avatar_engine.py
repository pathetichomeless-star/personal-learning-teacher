"""AVATAR 数字人引擎解析单测（纯 Python，无 Qt/PySide6 依赖）。

覆盖 resolve_avatar_engine 三大回退分支 + 合法路径：
  1. 配置缺失（get_config 返回 default → live2d）+ vendor 资产缺失 → canvas-fallback
  2. 非法配置值 → canvas-fallback
  3. vendor 缺文件（配置合法 live2d）→ canvas-fallback
  4. 配置 live2d + 资产齐备 → live2d
  5. 配置显式 canvas-fallback → canvas-fallback
  6. 配置系统异常（get_config 抛错）→ canvas-fallback
"""
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # .../client

from src.avatar.engine import (                                # noqa: E402
    DEFAULT_ENGINE, ENGINE_CANVAS, ENGINE_LIVE2D,
    VENDOR_KEY_FILES, resolve_avatar_engine,
)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  <- " + str(detail)) if (detail and not cond) else ""))


def make_runtime(complete=True):
    """构造一个（不）齐备的 runtime 目录，返回根路径。"""
    root = Path(tempfile.mkdtemp())
    if complete:
        for rel in VENDOR_KEY_FILES:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"stub")
    return root


# 1) 配置缺失 → 默认 live2d，但资产缺失 → 回退
engine, why = resolve_avatar_engine(lambda path, default: default,
                                    runtime_root=make_runtime(complete=False))
check("配置缺失+资产缺失 → canvas-fallback", engine == ENGINE_CANVAS, (engine, why))

# 2) 非法配置值
engine, why = resolve_avatar_engine(lambda path, default: "webgl3",
                                    runtime_root=make_runtime(complete=True))
check("非法值 → canvas-fallback", engine == ENGINE_CANVAS, (engine, why))

# 3) vendor 缺文件（配置合法 live2d）
engine, why = resolve_avatar_engine(lambda path, default: "live2d",
                                    runtime_root=make_runtime(complete=False))
check("vendor 缺文件 → canvas-fallback", engine == ENGINE_CANVAS, (engine, why))

# 3b) vendor 单个关键文件缺失（model3.json 存在但 moc3 缺失）
root = make_runtime(complete=True)
(root / "vendor/models/Hiyori/Hiyori.moc3").unlink()
engine, why = resolve_avatar_engine(lambda path, default: "live2d", runtime_root=root)
check("缺 moc3 单文件 → canvas-fallback", engine == ENGINE_CANVAS, (engine, why))

# 4) 配置 live2d + 资产齐备
engine, why = resolve_avatar_engine(lambda path, default: "live2d",
                                    runtime_root=make_runtime(complete=True))
check("配置 live2d+资产齐备 → live2d", engine == ENGINE_LIVE2D and why == "",
      (engine, why))

# 4b) 大小写/空白容差
engine, why = resolve_avatar_engine(lambda path, default: "  Live2D ",
                                    runtime_root=make_runtime(complete=True))
check("大小写/空白容差 → live2d", engine == ENGINE_LIVE2D, (engine, why))

# 5) 显式 canvas-fallback
engine, why = resolve_avatar_engine(lambda path, default: "canvas-fallback",
                                    runtime_root=make_runtime(complete=True))
check("显式 canvas-fallback → canvas-fallback", engine == ENGINE_CANVAS, (engine, why))

# 6) 配置系统缺席（get_config=None）
engine, why = resolve_avatar_engine(None, runtime_root=make_runtime(complete=True))
check("配置系统缺席+资产齐备 → live2d（默认）", engine == ENGINE_LIVE2D, (engine, why))
engine, why = resolve_avatar_engine(None, runtime_root=make_runtime(complete=False))
check("配置系统缺席+资产缺失 → canvas-fallback", engine == ENGINE_CANVAS, (engine, why))

# 7) get_config 抛错
def _boom(path, default):
    raise RuntimeError("config broken")

engine, why = resolve_avatar_engine(_boom, runtime_root=make_runtime(complete=True))
check("配置读取异常 → canvas-fallback", engine == ENGINE_CANVAS, (engine, why))

# 8) 默认引擎常量约定
check("DEFAULT_ENGINE 为 live2d", DEFAULT_ENGINE == "live2d")

print("=" * 60)
fails = [r for r in RESULTS if not r[1]]
print("AVATAR_ENGINE_TESTS: %d checks, %d PASS, %d FAIL"
      % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
if fails:
    traceback.print_exc()
sys.exit(1 if fails else 0)
