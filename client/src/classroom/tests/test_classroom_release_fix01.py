# -*- coding: utf-8 -*-
"""RELEASE-FIX-01 回归套件：入口隔离 / fail-closed 演示配置 / 诚实状态 / 入口子进程。

覆盖（对应验收 §3/§6）：
* 环境解析：默认独立演示目录、XIAOZHI_CLASSROOM_DIR / XIAOZHI_DATA_DIR 兼容、
  指向正式 py-xiaozhi 目录（或其子目录）时**拒绝启动**；
* 配置门禁：缺失 / 损坏 / 伪造（非环回 / 内嵌凭据 / 错误路径 / 无令牌）→ 零请求；
  显式开启 + 环回 + 令牌 → 恰好 1 次请求；令牌不出现在任何界面状态文案；
* 保存老师：只写课堂演示配置（原子、600），不建连、不写正式配置、不产生请求；
* 诚实状态：未开始恒「待开始」且无讲解；开始后才产生讲解与状态迁移；
* 本地课程：完整跑通、课程切换无残留、坏数据降级；
* 入口子进程：正式目录 → 退出码 3 + 图形化错误（NO_DIALOG 模式经标准输出）；
  默认目录（伪造 HOME）→ 正常隔离启动 + 零网络。

运行：
    cd client && PYTHONPATH= QT_QPA_PLATFORM=offscreen ./.venv/bin/python \
        src/classroom/tests/test_classroom_release_fix01.py

注意：本套件为**开发自验**，不构成独立 QA。
"""
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CLIENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if CLIENT not in sys.path:
    sys.path.insert(0, CLIENT)

RESULTS = []
MOCK = {"hits": 0, "token": "tok-fix01"}


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
                {"teacher_id": "t_1", "display_name": "模拟老师甲", "voice_id": "Cherry", "language": "en"},
                {"teacher_id": "t_2", "display_name": "模拟老师乙", "voice_id": "Serena", "language": "zh"},
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


def _write_demo_cfg(path, **kw):
    cfg = {"allow_teacher_list": False, "teacher_list_url": "", "teacher_token": "",
           "selected_teacher_id": ""}
    cfg.update(kw)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return path


def main():
    from PySide6.QtGui import QGuiApplication
    from src.classroom import classroom_env as cenv

    app = QGuiApplication.instance() or QGuiApplication([])

    # ================================ A. 环境解析（fail-closed）
    prod = cenv.production_data_dir()
    default_dir = cenv.default_demo_dir()

    d, src = cenv.resolve_classroom_dir({})
    check("F01 默认目录=独立演示目录（非正式目录）",
          d == default_dir.resolve() and "xiaozhi-classroom-demo" in str(d)
          and str(d) != str(prod.resolve()), (str(d), src))
    check("F02 默认目录不位于正式目录之下",
          prod.resolve() not in d.parents, str(d))

    tmp_ok = tempfile.mkdtemp(prefix="cls-fix01-ok-")
    tmp_resolved = os.path.realpath(tmp_ok)
    d2, src2 = cenv.resolve_classroom_dir({"XIAOZHI_CLASSROOM_DIR": tmp_ok})
    check("F03 XIAOZHI_CLASSROOM_DIR 被采纳", str(d2) == tmp_resolved and src2 == "env", (d2, src2))
    d3, src3 = cenv.resolve_classroom_dir({"XIAOZHI_DATA_DIR": tmp_ok})
    check("F04 XIAOZHI_DATA_DIR 兼容且通过校验", str(d3) == tmp_resolved and src3 == "env", (d3, src3))
    d4, _s4 = cenv.resolve_classroom_dir({"XIAOZHI_CLASSROOM_DIR": tmp_ok,
                                          "XIAOZHI_DATA_DIR": "/nonexistent-x"})
    check("F05 XIAOZHI_CLASSROOM_DIR 优先于 XIAOZHI_DATA_DIR", str(d4) == tmp_resolved, d4)

    d5, err5 = cenv.resolve_classroom_dir({"XIAOZHI_DATA_DIR": str(prod)})
    check("F06 指向正式目录 → 拒绝启动", d5 is None and "拒绝启动" in str(err5), err5)
    d6, err6 = cenv.resolve_classroom_dir({"XIAOZHI_DATA_DIR": str(prod / "config")})
    check("F07 指向正式目录子路径 → 拒绝启动", d6 is None and "拒绝启动" in str(err6), err6)

    # ================================ B. 演示配置门禁（零请求 / 恰好一次）
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Mock)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    loop_url = "http://127.0.0.1:%d/xiaozhi/v1/teacher/list" % port

    from src.classroom.classroom_model import ClassroomModel

    workdir = tempfile.mkdtemp(prefix="cls-fix01-cfg-")
    states_seen = []

    def fresh_model(cfg_path=None):
        # F32 隔离修复（CLASSROOM-V2-BUILD4）：传入独立 data_dir，测试不再读写
        # 真实演示目录（~/Library/Application Support/xiaozhi-classroom-demo），
        # 避免拾取产品负责人真实学习位置/记录残留，也不再向其写入测试数据。
        data_dir = os.path.join(workdir, "data")
        os.makedirs(data_dir, exist_ok=True)
        return ClassroomModel(demo_config_path=cfg_path,
                              courses_path=os.path.join(CLIENT, "src", "classroom", "data", "courses.json"),
                              data_dir=data_dir)

    def refresh_and_state(m):
        before = MOCK["hits"]
        m.refreshTeachers()
        states_seen.append(m.teachersState)
        return MOCK["hits"] - before, m.teachersState

    m = fresh_model(os.path.join(workdir, "missing.json"))
    delta, st = refresh_and_state(m)
    check("F08 配置缺失 → 不联网 + 中文提示", delta == 0 and "未启用" in st, (delta, st))

    corrupt = os.path.join(workdir, "corrupt.json")
    open(corrupt, "w").write("{ not json")
    m = fresh_model(corrupt)
    delta, st = refresh_and_state(m)
    check("F10 配置损坏 → 不联网 + 损坏提示", delta == 0 and "损坏" in st, (delta, st))

    m = fresh_model(_write_demo_cfg(os.path.join(workdir, "off.json"), allow_teacher_list=False))
    delta, st = refresh_and_state(m)
    check("F11 allow=False → 不联网", delta == 0 and "未启用" in st, (delta, st))

    m = fresh_model(_write_demo_cfg(
        os.path.join(workdir, "forged.json"), allow_teacher_list=True,
        teacher_list_url="http://192.0.2.1:28310/xiaozhi/v1/teacher/list",
        teacher_token=MOCK["token"]))
    delta, st = refresh_and_state(m)
    check("F12 伪造非环回地址（生产形）→ 拒绝 + 零请求", delta == 0 and "仅允许本机" in st, (delta, st))

    m = fresh_model(_write_demo_cfg(
        os.path.join(workdir, "cred.json"), allow_teacher_list=True,
        teacher_list_url="http://user:pw@127.0.0.1:%d/xiaozhi/v1/teacher/list" % port,
        teacher_token=MOCK["token"]))
    delta, st = refresh_and_state(m)
    check("F13 内嵌凭据地址 → 拒绝 + 零请求", delta == 0 and "内嵌凭据" in st, (delta, st))

    m = fresh_model(_write_demo_cfg(
        os.path.join(workdir, "path.json"), allow_teacher_list=True,
        teacher_list_url="http://127.0.0.1:%d/wrong" % port, teacher_token=MOCK["token"]))
    delta, st = refresh_and_state(m)
    check("F14 非 /teacher/list 路径 → 拒绝 + 零请求", delta == 0 and "teacher/list" in st, (delta, st))

    m = fresh_model(_write_demo_cfg(
        os.path.join(workdir, "notoken.json"), allow_teacher_list=True,
        teacher_list_url=loop_url, teacher_token=""))
    delta, st = refresh_and_state(m)
    check("F15 环回地址但无令牌 → 不联网 + 令牌提示", delta == 0 and "部署令牌" in st, (delta, st))

    good = _write_demo_cfg(os.path.join(workdir, "good.json"), allow_teacher_list=True,
                           teacher_list_url=loop_url, teacher_token=MOCK["token"])
    m = fresh_model(good)
    delta, st = refresh_and_state(m)
    check("F16 显式开启+环回+令牌 → 恰好 1 次请求且读出 2 位老师",
          delta == 1 and len(m.teachers) == 2 and "共 2 位" in st, (delta, st, m.teachers))
    check("F17 令牌不出现在任何界面状态文案",
          all(MOCK["token"] not in s for s in states_seen), states_seen)

    # ================================ C. 保存老师（不建连 / 不写正式配置）
    before = MOCK["hits"]
    m.selectTeacher("t_2")
    m.saveTeacher()
    delta = MOCK["hits"] - before
    saved = json.load(open(good, encoding="utf-8"))
    check("F18 保存写入课堂演示配置 selected_teacher_id",
          saved.get("selected_teacher_id") == "t_2", saved)
    check("F19 保存不产生任何网络请求", delta == 0, delta)
    check("F20 保存保留原 allow/url/token 键（不做隐式扩权/降权）",
          saved.get("allow_teacher_list") is True and saved.get("teacher_list_url") == loop_url, saved)
    check("F21 保存后状态与 started 不变（无隐式开始/连接）",
          m.started is False and m.status == "待开始", (m.started, m.status))
    check("F22 保存目录中不产生 config.json（不触碰正式配置形状）",
          not os.path.exists(os.path.join(workdir, "config.json")))
    m2 = fresh_model(good)
    m2.loadSelectedTeacher()
    check("F23 重新加载读回已保存老师", m2.selectedTeacherId == "t_2", m2.selectedTeacherId)

    # ================================ D. 诚实状态（未开始不讲解）
    demo_dir = tempfile.mkdtemp(prefix="cls-fix01-state-")
    m3 = fresh_model(os.path.join(demo_dir, "classroom_demo.json"))
    m3.selectCourse(0)
    m3.selectLesson(0)
    check("F24 未开始时状态=待开始（预置课件后依然）",
          m3.started is False and m3.status == "待开始", (m3.started, m3.status))
    m3.nextSlide()
    m3.nextSlide()
    tr = [t for t in m3.transcript if t.get("role") == "teacher"]
    check("F25 未开始时翻页不产生讲解", len(tr) == 0 and m3.status == "待开始", tr)
    n0 = len(m3.transcript)
    m3.repeatSlide()
    check("F26 未开始时「重复讲解」无操作", len(m3.transcript) == n0, len(m3.transcript))
    m3.submitText("hello pre-start")
    check("F27 未开始时文字提交不改变状态（仍待开始）",
          m3.status == "待开始" and any(n.get("text") == "hello pre-start" for n in m3.notes),
          (m3.status, m3.notes[-1:]))
    m3.startLearning()
    tr = [t for t in m3.transcript if t.get("role") == "teacher"]
    check("F28 开始学习后产生讲解且状态=讲解",
          m3.started is True and len(tr) >= 1 and m3.status == "讲解", (m3.status, len(tr)))
    n1 = len(m3.transcript)
    m3.repeatSlide()
    check("F29 开始后「重复讲解」追加讲解", len(m3.transcript) > n1, (n1, len(m3.transcript)))
    m3.endLearning()
    check("F30 结束学习复位（started=False，状态=待开始）",
          m3.started is False and m3.status == "待开始" and m3.currentCourseIndex == -1,
          (m3.started, m3.status))

    # ================================ E. 本地课程完整 E2E + 切课无残留
    m4 = fresh_model(good)
    check("F31 本地演示课程装载（3 门）", m4.courseCount == 3, m4.courseCount)
    m4.selectCourse(0)
    m4.startLearning()
    seen = []
    practice_ok = False
    for _ in range(8):
        seen.append(m4.currentSlide.get("type"))
        if m4.currentSlide.get("type") == "practice":
            m4.answerPractice(int(m4.practice.get("answer", -1)))
            practice_ok = bool(m4.practice.get("answered") and m4.practice.get("correct"))
        if m4.slideIndex + 1 >= m4.slideCount:
            break
        m4.nextSlide()
    check("F32 五类课件页完整渲染（cover/vocab/sentence/practice/summary）",
          {"cover", "vocab", "sentence", "practice", "summary"} <= set(seen), seen)
    check("F33 练习判定 + 反馈", practice_ok, m4.practice)
    old_tr = "\n".join(t.get("text", "") for t in m4.transcript)
    m4.selectCourse(1)
    new_tr = "\n".join(t.get("text", "") for t in m4.transcript)
    check("F34 切课后无残留（旧课字幕/笔记/词汇清空）",
          "办理入住" not in new_tr and m4.notes == [] and m4.slideVocab == [] and
          m4.currentCourseTitle == "日常口语 · Daily English", (new_tr[:60], m4.notes))

    bad = ClassroomModel(courses_path=os.path.join(demo_dir, "nope.json"),
                         data_dir=os.path.join(workdir, "data"))          # F32 隔离修复
    broken = os.path.join(demo_dir, "broken.json")
    open(broken, "w").write("{ nope")
    bad2 = ClassroomModel(courses_path=broken,
                          data_dir=os.path.join(workdir, "data"))         # F32 隔离修复
    check("F35 空/坏课程数据降级不崩溃",
          bad.courseCount == 0 and "不可用" in bad.coursesError and bad2.courseCount == 0)

    # ================================ F. 源码结构性约束
    src_model = open(os.path.join(CLIENT, "src", "classroom", "classroom_model.py"), encoding="utf-8").read()
    src_main = open(os.path.join(CLIENT, "classroom_main.py"), encoding="utf-8").read()
    src_env = open(os.path.join(CLIENT, "src", "classroom", "classroom_env.py"), encoding="utf-8").read()
    check("F36 课堂不复用 config_manager（结构性不读正式配置）",
          "config_manager" not in src_model and "config_manager" not in src_main)
    check("F37 课堂无 WS/付费连接库引用",
          all(x not in src_model + src_main for x in ("websockets", "aiohttp")) and
          "WEBSOCKET_ACCESS_TOKEN" not in src_model + src_main)
    check("F38 classroom_env 自身不含网络调用（解析模块纯本地；urlparse 纯解析除外）",
          all(x not in src_env for x in ("urllib.request", "urllib.error", "requests",
                                         "socket", "http.client")))

    # ================================ G. 入口子进程（隔离拒绝 / 默认目录启动）
    main_py = os.path.join(CLIENT, "classroom_main.py")
    py = sys.executable

    env_bad = dict(os.environ)
    env_bad["XIAOZHI_DATA_DIR"] = str(prod)
    env_bad["XIAOZHI_CLASSROOM_NO_DIALOG"] = "1"
    env_bad["QT_QPA_PLATFORM"] = "offscreen"
    env_bad.pop("XIAOZHI_CLASSROOM_DIR", None)
    p = subprocess.run([py, main_py, "--size", "compact"], env=env_bad,
                       capture_output=True, text=True, timeout=60)
    check("F39 入口指向正式目录 → 退出码 3 + 图形化错误（自动模式文案）",
          p.returncode == 3 and "CLASSROOM_STARTUP_ERROR" in p.stdout and "拒绝启动" in p.stdout,
          (p.returncode, p.stdout[-200:]))

    fake_home = tempfile.mkdtemp(prefix="cls-fix01-home-")
    env_ok = dict(os.environ)
    env_ok["HOME"] = fake_home
    env_ok["XIAOZHI_CLASSROOM_NO_DIALOG"] = "1"
    env_ok["QT_QPA_PLATFORM"] = "offscreen"
    for k in ("XIAOZHI_CLASSROOM_DIR", "XIAOZHI_DATA_DIR"):
        env_ok.pop(k, None)
    hits_before = MOCK["hits"]
    proc = subprocess.Popen([py, main_py, "--size", "compact"], env=env_ok,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []

    def _reader():
        try:
            for ln in proc.stdout:
                lines.append(ln.strip())
                if "CLASSROOM_READY" in ln or "CLASSROOM_STARTUP_ERROR" in ln:
                    break
        except Exception:  # noqa: BLE001
            pass

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    reader.join(timeout=30)
    time.sleep(1.5)
    alive = proc.poll() is None
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    blob = "\n".join(lines)
    expected_dir = os.path.join(fake_home, "Library", "Application Support", "xiaozhi-classroom-demo")
    check("F40 默认入口正常启动且隔离目录=独立演示目录（伪造 HOME）",
          alive and "CLASSROOM_ISOLATION" in blob and expected_dir in blob, blob[-300:])
    check("F41 未配置隔离时入口零网络请求",
          MOCK["hits"] == hits_before, (MOCK["hits"], hits_before))

    srv.shutdown()

    print("=" * 70)
    total = len(RESULTS)
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    print("CLASSROOM_RELEASE_FIX01: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s  %r" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
