"""VISION V0.6 客户端模块测试（无 PySide6；cv2 缺失时跳过压缩项）。"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import urllib.request

_CLIENT = Path(__file__).resolve().parents[2]   # .../client
if str(_CLIENT) not in sys.path:
    sys.path.insert(0, str(_CLIENT))

import importlib.util
_BASE = Path(__file__).resolve().parents[1]   # client/src/vision

def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _BASE / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m

vcompress = _load("vcompress", "compress.py")
vc_mod = _load("vc_controller", "controller.py")
VisionController = vc_mod.VisionController
import importlib.util as _iu
_spec2 = importlib.util.spec_from_file_location(
    "avatar_states", _BASE.parent / "avatar" / "states.py")
_av = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(_av)
AvatarStateMachine = _av.AvatarStateMachine

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  <- " + str(detail)) if (detail and not cond) else ""))


# validate
check("validate JPEG", vcompress.validate_jpeg(b"\xff\xd8\xff\x00")[0])
check("validate PNG 拒绝", vcompress.validate_jpeg(b"\x89PNG\r\n")[0] is False)
big = b"\xff\xd8\xff" + b"\x00" * (vcompress.MAX_BYTES + 1)
check("validate 超大拒绝", vcompress.validate_jpeg(big)[1] == "too_large")

# compress_plan
tw, th = vcompress.compress_plan(3840, 2160)
check("compress_plan 长边 1280", max(tw, th) == 1280)

# cv2 压缩（可跳过）
try:
    import cv2
    import numpy as np
    img = np.zeros((2160, 3840, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    raw = buf.tobytes()
    out, q = vcompress.compress_jpeg(raw)
    check("compress_jpeg 输出 ≤190KB 且非 None", out is not None
          and len(out) <= vcompress.MAX_BYTES, (out is not None, len(out) if out else 0))
except ImportError:
    check("compress_jpeg 跳过（cv2 缺失）", True)

# controller：disabled / 频率 / 提交
vc = VisionController("http://127.0.0.1:9/vision", "tok", "sess-1", enabled=False)
check("controller 默认关闭", vc.submit(b"\xff\xd8\xff\x00")[1] == "vision_disabled")
vc.set_enabled(True)
now = [1000.0]
class FakeT:
    @staticmethod
    def monotonic(): return now[0]
import time as _t
vc_t = VisionController("http://127.0.0.1:9/vision", "tok", "sess-1", enabled=True)
_real = _t.monotonic
_t.monotonic = (lambda: now[0])
ok1, why1 = vc_t.submit(b"\xff\xd8\xff\x00", now=now[0])
ok2, why2 = vc_t.submit(b"\xff\xd8\xff\x00", now=now[0])
check("controller 频率间隔拒绝（端点不可达不影响守卫）",
      why2 == "rate_interval", (ok1, why1, ok2, why2))
_t.monotonic = _real

# controller E2E：本地 HTTP 服务（401 / 200）
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.headers.get("X-Vision-Token") != "tok-e2e":
            self.send_response(401); self.end_headers(); return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        d = json.loads(body)
        if not d.get("image_b64", "").startswith("/9j/"):
            self.send_response(415); self.end_headers(); return
        resp = json.dumps({"accepted": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers(); self.wfile.write(resp)
    def log_message(self, *a): pass

httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
port = httpd.socket.getsockname()[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
ve = VisionController("http://127.0.0.1:%d/vision" % port, "tok-e2e", "sess-1",
                      enabled=True)
ok, resp = ve.submit(b"\xff\xd8\xff\x01\x02")
check("controller E2E 200 accepted", ok and resp.get("accepted") is True, (ok, resp))
vc_bad = VisionController("http://127.0.0.1:%d/vision" % port, "wrong", "sess-1",
                          enabled=True)
ok, why = vc_bad.submit(b"\xff\xd8\xff\x01\x02")
check("controller E2E 401 → 失败上报", ok is False and "401" in why, (ok, why))
httpd.shutdown()

# 数字人状态机
sm = AvatarStateMachine()
sm.to_thinking()
check("avatar thinking + 代际递增", sm.state == "thinking" and sm.generation == 1)
sm.to_speaking()
check("avatar speaking", sm.state == "speaking" and sm.speaking)
sm.to_interrupted()
check("avatar 打断 → speaking=False（口型归零依据）",
      sm.state == "interrupted" and sm.speaking is False)
g = sm.new_generation()
check("avatar 新代际防串", g == 2 and sm.speaking is False)

print("=" * 60)
fails = [r for r in RESULTS if not r[1]]
print("V06_CLIENT_MODULE_TESTS: %d checks, %d PASS, %d FAIL"
      % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
