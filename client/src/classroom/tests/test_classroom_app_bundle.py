# -*- coding: utf-8 -*-
"""RELEASE-FIX-01 .app 独立启动 E2E（对已构建的「小智 AI 学生课堂.app」直接运行验证）。

验证：
* 包体存在与关键资源（Info.plist / QML / 本地课程）；
* 独立启动（内嵌 Python，不依赖 client/.venv；不依赖 /tmp/xz-acc-f1）；
* 默认隔离目录 = ~/Library/Application Support/xiaozhi-classroom-demo（伪造 HOME 验证）；
* 未配置隔离 → 零网络请求；显式配置（环回 + 令牌）→ 老师列表可用；
* 指向正式目录 → 拒绝启动（退出码 3）；图形化错误路径生效（无自动模式时阻塞于对话框）。

前置：先运行 tools/build_classroom_app.sh 构建 .app。
运行：cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/test_classroom_app_bundle.py

本套件为**开发自验**，不构成独立 QA。
"""
import http.server
import json
import os
import plistlib
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

CLIENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REPO = os.path.dirname(CLIENT)
if CLIENT not in sys.path:
    sys.path.insert(0, CLIENT)

BUNDLE = os.path.join(CLIENT, "dist", "小智 AI 学生课堂.app")
EXE = os.path.join(BUNDLE, "Contents", "MacOS", "xiaozhi-classroom")
MOCK = {"hits": 0, "token": "tok-bundle-e2e"}

RESULTS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append((name, ok, detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else "  <- %r" % (detail,))))


class _Mock(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/xiaozhi/v1/teacher/list"):
            MOCK["hits"] += 1
            if self.headers.get("X-Teacher-Token", "") != MOCK["token"]:
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps({"teachers": [
                {"teacher_id": "t_a", "display_name": "模拟老师甲", "voice_id": "Cherry", "language": "en"},
            ]}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *a):
        pass


def _launch_until(exe, env, marker, timeout=40):
    """启动包体；读到 marker 或超时/退出后返回 (alive, lines)。"""
    proc = subprocess.Popen([exe, "--size", "compact"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []

    def _reader():
        try:
            for ln in proc.stdout:
                lines.append(ln.strip())
                if marker in ln:
                    break
        except Exception:  # noqa: BLE001
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    time.sleep(1.2)
    alive = proc.poll() is None
    return proc, alive, lines


def main():
    check("B01 .app 包体存在于 client/dist", os.path.isdir(BUNDLE), BUNDLE)
    if not os.path.isdir(BUNDLE):
        print("SKIP: 请先运行 tools/build_classroom_app.sh")
        return 1
    check("B02 可执行文件存在（内嵌 Python，不依赖 client/.venv）", os.path.isfile(EXE), EXE)

    plist_path = os.path.join(BUNDLE, "Contents", "Info.plist")
    try:
        with open(plist_path, "rb") as fh:
            pl = plistlib.load(fh)
    except Exception as e:  # noqa: BLE001
        pl = {}
        check("B03 Info.plist 可读", False, e)
    if pl:
        check("B03 Info.plist 名称/标识正确",
              pl.get("CFBundleDisplayName") == "小智 AI 学生课堂"
              and pl.get("CFBundleIdentifier") == "local.xiaozhi.classroom-demo", pl)

    found_qml = found_courses = False
    for root, _dirs, files in os.walk(BUNDLE):
        if "ClassroomWindow.qml" in files:
            found_qml = True
        if "courses.json" in files and "classroom" in root:
            found_courses = True
    check("B04 包内含 QML 界面资源", found_qml)
    check("B05 包内含本地演示课程资源", found_courses)

    # ---------------- B13/B14 包内必须是 V2 界面（不是滞后的旧包） ----------------
    res = os.path.join(BUNDLE, "Contents", "Resources")
    qml_dir = os.path.join(res, "src", "classroom", "qml")
    v2_files = ("NavBar.qml", "LibraryPanel.qml", "ImportPanel.qml",
                "ProofreadPanel.qml", "PublishPanel.qml")
    missing = [f for f in v2_files if not os.path.isfile(os.path.join(qml_dir, f))]
    check("B13 包内含 CLASSROOM V2 全部新页面 QML", not missing, missing)
    try:
        cw = open(os.path.join(qml_dir, "ClassroomWindow.qml"), encoding="utf-8").read()
    except OSError as e:  # noqa: BLE001
        cw = ""
        check("B14 包内 ClassroomWindow.qml 可读", False, e)
    if cw:
        check("B14 包内界面含 V2 特征（语音演练 Mock 入口 / 五栏目导航）",
              "语音演练（Mock）" in cw and "LibraryPanel" in cw and "PublishPanel" in cw)

    # ---------------- B15 版本一致性（Info.plist == 包内 build info） ----------------
    info_bundle = os.path.join(res, "classroom_build_info.json")
    check("B15 包内含构建信息（源码↔安装包一致性凭据）", os.path.isfile(info_bundle),
          info_bundle)
    if os.path.isfile(info_bundle) and pl:
        with open(info_bundle, encoding="utf-8") as fh:
            _bi = json.load(fh)
        check("B16 Info.plist 版本 == 包内构建信息版本",
              pl.get("CFBundleShortVersionString") == _bi.get("app_version")
              and str(pl.get("CFBundleVersion")) == str(_bi.get("app_build")),
              {"plist": (pl.get("CFBundleShortVersionString"), pl.get("CFBundleVersion")),
               "build_info": (_bi.get("app_version"), _bi.get("app_build"))})

    # 模拟网关
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Mock)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # ---------------- E2E-1 默认启动（伪造 HOME；不设任何隔离变量） ----------------
    fake_home = tempfile.mkdtemp(prefix="cls-bundle-home-")
    env1 = dict(os.environ)
    env1["HOME"] = fake_home
    env1["QT_QPA_PLATFORM"] = "offscreen"
    env1["XIAOZHI_CLASSROOM_NO_DIALOG"] = "1"
    for k in ("XIAOZHI_CLASSROOM_DIR", "XIAOZHI_DATA_DIR"):
        env1.pop(k, None)
    hits0 = MOCK["hits"]
    proc, alive, lines = _launch_until(EXE, env1, "CLASSROOM_READY")
    blob = "\n".join(lines)
    expected_dir = os.path.join(fake_home, "Library", "Application Support", "xiaozhi-classroom-demo")
    check("B06 独立启动成功（读到 CLASSROOM_READY）", any("CLASSROOM_READY" in x for x in lines), blob[-260:])
    check("B07 默认隔离目录=独立演示目录（非 /tmp、非正式目录）",
          "CLASSROOM_ISOLATION" in blob and expected_dir in blob
          and "xz-acc" not in blob and "py-xiaozhi/config" not in blob, blob[-260:])
    check("B08 启动后进程存活（GUI 正常进入）", alive)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    check("B09 未配置隔离 → 零网络请求", MOCK["hits"] == hits0, (MOCK["hits"], hits0))

    # ---------------- E2E-2 显式配置（环回 + 令牌）→ 老师列表可用 ----------------
    demo_dir = os.path.join(fake_home, "Library", "Application Support", "xiaozhi-classroom-demo")
    os.makedirs(demo_dir, exist_ok=True)
    with open(os.path.join(demo_dir, "classroom_demo.json"), "w", encoding="utf-8") as fh:
        json.dump({"allow_teacher_list": True,
                   "teacher_list_url": "http://127.0.0.1:%d/xiaozhi/v1/teacher/list" % port,
                   "teacher_token": MOCK["token"],
                   "selected_teacher_id": ""}, fh)
    hits1 = MOCK["hits"]
    proc, alive, lines = _launch_until(EXE, env1, "CLASSROOM_READY")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    check("B10 显式隔离配置 → 老师列表恰好 1 次环回请求", MOCK["hits"] == hits1 + 1,
          (MOCK["hits"], hits1))

    # ---------------- E2E-3 指向正式目录 → 拒绝启动（退出码 3） ----------------
    from src.classroom import classroom_env as cenv

    prod = str(cenv.production_data_dir())
    env3 = dict(os.environ)
    env3["XIAOZHI_DATA_DIR"] = prod
    env3["XIAOZHI_CLASSROOM_NO_DIALOG"] = "1"
    env3["QT_QPA_PLATFORM"] = "offscreen"
    env3.pop("XIAOZHI_CLASSROOM_DIR", None)
    p = subprocess.run([EXE, "--size", "compact"], env=env3, capture_output=True, text=True, timeout=90)
    check("B11 指向正式目录 → 退出码 3 + 拒绝启动文案",
          p.returncode == 3 and "拒绝启动" in p.stdout and "CLASSROOM_STARTUP_ERROR" in p.stdout,
          (p.returncode, p.stdout[-200:]))

    # ---------------- E2E-4 图形化错误路径（不带自动模式 → 阻塞于对话框） ----------------
    env4 = dict(env3)
    env4.pop("XIAOZHI_CLASSROOM_NO_DIALOG", None)
    proc = subprocess.Popen([EXE, "--size", "compact"], env=env4,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(6)
    alive4 = proc.poll() is None
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    check("B12 错误路径弹出图形化说明（无自动模式时阻塞于对话框，而非静默退出）", alive4)

    srv.shutdown()

    print("=" * 70)
    total = len(RESULTS)
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    print("CLASSROOM_APP_BUNDLE_E2E: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s  %r" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
