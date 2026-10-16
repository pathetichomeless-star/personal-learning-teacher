# -*- coding: utf-8 -*-
"""课堂演示环境解析与隔离 —— RELEASE FIX 01（fail-closed）。

设计原则（全部为结构性约束，而非“路径覆盖”）：
* 课堂演示使用**独立数据目录**（默认 ``~/Library/Application Support/xiaozhi-classroom-demo``），
  与正式 py-xiaozhi 用户数据完全分离；解析结果等于正式目录或其子目录时**拒绝启动**。
* 本模块不读取任何正式配置 / 密钥字段；课堂不再经 config_manager 读取 ``config.json``。
* 唯一的网络面是「本机 Mock 老师列表」，且必须同时满足：
    (1) 演示配置中 ``allow_teacher_list`` 显式为真（默认缺省=关闭）；
    (2) 地址为**环回地址**（127.0.0.1 / localhost / ::1），否则拒绝；
    (3) 提供部署令牌，且令牌只进入 HTTP 头，不出现在任何界面文案。
* 任何缺失 / 损坏 / 伪造配置一律降级为“不联网”，并给出明确中文原因。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import platformdirs

# 正式客户端与课堂演示的 app 名称（platformdirs 目录名）
APP_NAME = "py-xiaozhi"
DEMO_APP_NAME = "xiaozhi-classroom-demo"

ENV_CLASSROOM_DIR = "XIAOZHI_CLASSROOM_DIR"   # 首选：课堂演示目录
ENV_DATA_DIR = "XIAOZHI_DATA_DIR"             # 兼容旧启动方式（仍需通过校验）
DEMO_CONFIG_NAME = "classroom_demo.json"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def production_data_dir() -> Path:
    """正式 py-xiaozhi 用户数据目录（仅用于相等性拒绝，绝不读取其内容）。"""
    return Path(platformdirs.user_data_dir(APP_NAME))


def default_demo_dir() -> Path:
    """课堂演示默认数据目录（独立于正式目录）。"""
    return Path(platformdirs.user_data_dir(DEMO_APP_NAME))


def resolve_classroom_dir(env=None):
    """解析课堂数据目录（fail-closed）。

    返回 ``(Path, source)``；校验失败返回 ``(None, "中文原因")``。
    ``source`` ∈ {"env", "default"}，仅成功时有意义。
    """
    env = os.environ if env is None else env
    raw = str(env.get(ENV_CLASSROOM_DIR) or env.get(ENV_DATA_DIR) or "").strip()
    if raw:
        try:
            candidate = Path(raw).expanduser().resolve()
        except Exception:
            return None, "隔离目录无效（无法解析）：%s" % raw
        source = "env"
    else:
        candidate = default_demo_dir().resolve()
        source = "default"

    prod = production_data_dir().resolve()
    if candidate == prod or prod in candidate.parents:
        return None, (
            "拒绝启动：隔离目录指向正式客户端数据目录（%s）。"
            "课堂演示必须使用独立目录（默认：%s）。" % (prod, default_demo_dir())
        )
    return candidate, source


def demo_config_path(data_dir) -> Path:
    return Path(data_dir) / DEMO_CONFIG_NAME


def load_demo_config(path) -> dict:
    """读取课堂演示配置；任何异常都以“关闭联网”的安全缺省返回。

    返回字段：present / corrupt / allow / url / token / selected。
    ``allow`` 仅当值为布尔真（``is True``）才为真——字符串 "true"、数字 1 均视为关闭。
    """
    result = {"present": False, "corrupt": False, "allow": False,
              "url": "", "token": "", "selected": ""}
    try:
        p = Path(path)
        if not p.exists():
            return result
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            result["corrupt"] = True
            return result
        result["present"] = True
        result["allow"] = raw.get("allow_teacher_list") is True
        result["url"] = str(raw.get("teacher_list_url") or "").strip()
        result["token"] = str(raw.get("teacher_token") or "")
        result["selected"] = str(raw.get("selected_teacher_id") or "")
        return result
    except Exception:  # noqa: BLE001 —— 损坏配置绝不抛出，直接降级
        result["corrupt"] = True
        return result


def normalize_teacher_url(raw) -> tuple:
    """校验并规范化老师列表地址。

    成功返回 ``(规范 URL, "")``；失败返回 ``(None, 中文原因)``。
    仅允许环回主机；ws/wss 映射为 http/https；路径须以 ``/teacher/list`` 结尾；
    不允许内嵌凭据、查询串或片段。
    """
    s = str(raw or "").strip()
    if not s:
        return None, "未配置老师列表地址"
    if s.startswith("ws://"):
        s = "http://" + s[5:]
    elif s.startswith("wss://"):
        s = "https://" + s[6:]
    try:
        u = urlparse(s)
    except Exception:  # noqa: BLE001
        return None, "老师列表地址无效"
    if u.scheme not in ("http", "https"):
        return None, "老师列表地址无效（仅支持 http/https）"
    if u.username or u.password:
        return None, "老师列表地址无效（不允许内嵌凭据）"
    if u.query or u.fragment:
        return None, "老师列表地址无效（不允许查询串或片段）"
    host = (u.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        return None, "老师列表地址被拒绝：本演示版仅允许本机地址（127.0.0.1 / localhost / ::1）"
    if not u.path.endswith("/teacher/list"):
        return None, "老师列表地址无效（应以 /teacher/list 结尾）"
    return s, ""


def save_selected_teacher(path, teacher_id) -> bool:
    """原子写回 ``selected_teacher_id``；绝不创建/修改任何正式配置。

    文件权限 600；写入失败返回 False（界面提示保存失败，不抛出）。
    损坏的既有文件不继承其内容（仅重建安全缺省 + 选中项）。
    """
    try:
        p = Path(path)
        cur = {}
        if p.exists():
            try:
                loaded = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    cur = loaded
            except Exception:  # noqa: BLE001
                cur = {}
        cur["selected_teacher_id"] = str(teacher_id or "")
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".classroom_demo.", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cur, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        os.chmod(p, 0o600)
        return True
    except Exception:  # noqa: BLE001
        return False
