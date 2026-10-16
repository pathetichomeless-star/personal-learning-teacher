"""V4 model-management + version-gate tests (deterministic, no network, no paid calls).

Run:  gateway/.venv-v4/bin/python gateway/tests/model_v4_tests.py
"""

import http.client
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.model._jsonstore import (BaseJsonStore, ConfirmRequired,  # noqa: E402
                                      PersistError, StoreUnavailable)
from modules.model.credentials import (CredentialInUse, CredentialStore,  # noqa: E402
                                       fingerprint_of)
from modules.model.endpoint_policy import (EndpointRejected, peer_allowed,  # noqa: E402
                                           validate_endpoint)
from modules.model.gating import enable_gate  # noqa: E402
from modules.model.probe import _models_url, _peer_checked_class  # noqa: E402
from modules.model.registry import (Duplicate, FrozenModel, ModelRegistry,  # noqa: E402
                                    ModelRegistryError, NotFound)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  → " + str(extra)) if extra and not cond else ""))


class Demo(BaseJsonStore):
    SCHEMA_VERSION = 2
    ROOT_KEYS = ("items",)


def main():
    tmp = tempfile.mkdtemp(prefix="v4model_")

    # ---------- 1. version gate ----------
    p = os.path.join(tmp, "demo.json")
    Path(p).write_text("{not json", "utf-8")
    s = Demo(p).load()
    check("损坏文件 → unavailable", s.state()["state"] == "unavailable" and not s.available)
    try:
        s._persist()
        check("unavailable 时写被拒绝", False, "persist 未抛错")
    except StoreUnavailable:
        check("unavailable 时写被拒绝", True)
    original = Path(p).read_text("utf-8")
    check("unavailable 未覆盖原文件", Path(p).read_text("utf-8") == original)

    Path(p).write_text(json.dumps({"schema_version": 99, "items": {"a": {}}}), "utf-8")
    s2 = Demo(p).load()
    check("高版本 → unavailable(version_ahead)", s2.state()["reason"] == "version_ahead")
    check("高版本拒写", not s2.available)

    Path(p).write_text(json.dumps({"schema_version": 1, "items": {"a": {"x": 1}}}), "utf-8")
    s3 = Demo(p).load()
    check("低版本可向前兼容读取", s3.available and s3.state()["migrated_from"] == 1
          and "a" in s3._data["items"])

    mig = s3.migrate(confirm=True)
    check("迁移创建备份且读回通过", mig["readback_ok"] and Path(mig["backup"]).is_file())
    check("迁移后版本为当前版本",
          json.loads(Path(p).read_text("utf-8"))["schema_version"] == 2)
    check("备份列表可见", len(s3.list_backups()) >= 1)
    s3.restore(mig["backup"])
    check("回滚恢复到旧版本",
          json.loads(Path(p).read_text("utf-8"))["schema_version"] == 1)
    try:
        Demo(p).migrate(confirm=False)
        check("迁移需 confirm", False, "未抛错")
    except ConfirmRequired:
        check("迁移需 confirm", True)

    # ---------- 2. endpoint policy ----------
    def rejects(url, **kw):
        try:
            validate_endpoint(url, resolver=lambda h: ["93.184.216.34"], **kw)
            return False
        except EndpointRejected:
            return True

    check("拒绝 http", rejects("http://api.example.com/v1"))
    check("拒绝 userinfo", rejects("https://user:pass@api.example.com/v1"))
    try:
        validate_endpoint("https://evil.example.com/v1", resolver=lambda h: ["10.0.0.5"])
        check("拒绝解析到私网（DNS 重绑定）", False, "未拒绝")
    except EndpointRejected:
        check("拒绝解析到私网（DNS 重绑定）", True)
    try:
        validate_endpoint("https://meta.example.com/v1",
                          resolver=lambda h: ["169.254.169.254"])
        check("拒绝云元数据地址", False, "未拒绝")
    except EndpointRejected:
        check("拒绝云元数据地址", True)
    try:
        validate_endpoint("https://metadata.google.internal/v1")
        check("拒绝元数据主机名", False, "未拒绝")
    except EndpointRejected:
        check("拒绝元数据主机名", True)
    ok = validate_endpoint("https://api.example.com/v1",
                           resolver=lambda h: ["93.184.216.34"])
    check("接受合法 https 公网地址", ok == "https://api.example.com/v1")
    try:
        validate_endpoint("http://127.0.0.1:11434", resolver=lambda h: ["127.0.0.1"])
        check("默认拒绝回环 http", False, "未拒绝")
    except EndpointRejected:
        check("默认拒绝回环 http", True)
    ok2 = validate_endpoint("http://127.0.0.1:11434", allow_local=True,
                            resolver=lambda h: ["127.0.0.1"])
    check("allow_local 放行回环", ok2.startswith("http://127.0.0.1"))
    check("metadata 路径拼接（host-only）",
          _models_url("https://api.example.com") == "https://api.example.com/v1/models")
    check("metadata 路径拼接（已含 /v1 不双拼）",
          _models_url("https://api.example.com/v1") == "https://api.example.com/v1/models")

    # IPv4-mapped IPv6 不得绕过黑名单（独立审计 B-SSRF-1 回归）
    for bad in ("https://[::ffff:169.254.169.254]/latest",
                "https://[::ffff:10.0.0.1]/v1",
                "https://[::ffff:192.168.1.1]/v1",
                "https://[::ffff:127.0.0.1]/v1"):
        try:
            validate_endpoint(bad)
            check("拒绝 IPv4-mapped %s" % bad, False, "未拒绝")
        except EndpointRejected:
            check("拒绝 IPv4-mapped %s" % bad, True)
    check("IPv4-mapped 公网地址不误伤",
          validate_endpoint("https://[::ffff:93.184.216.34]/v1").startswith("https://["))

    # 其他嵌入 IPv4 的 IPv6 形式同样不得绕过（审计 B-SSRF-2 回归）
    for bad in ("https://[2002:7f00:1::]/v1",                    # 6to4 → 127.0.0.1
                "https://[64:ff9b::a00:1]/v1",                   # NAT64 → 10.0.0.1
                "https://[::127.0.0.1]/v1",                      # compatible
                "https://[::ffff:0:a9fe:a9fe]/v1",               # SIIT → 169.254.169.254
                "https://[2001:0:4136:e378:8000:63bf:f5ff:fffe]/v1"):  # Teredo → 10.0.0.1
        try:
            validate_endpoint(bad)
            check("拒绝嵌入 IPv4 形式 %s" % bad, False, "未拒绝")
        except EndpointRejected:
            check("拒绝嵌入 IPv4 形式 %s" % bad, True)
    check("NAT64 公网地址不误伤（按嵌入 IPv4 判定）",
          validate_endpoint("https://[64:ff9b::5db8:d822]/v1").startswith("https://["))

    # 实际连接 IP 校验（契约 §3.3；独立审计 A-Major 回归）
    check("peer_allowed: 回环需 allow_local",
          peer_allowed("127.0.0.1") is False
          and peer_allowed("127.0.0.1", allow_local=True) is True)
    check("peer_allowed: mapped 元数据地址拒绝",
          peer_allowed("::ffff:169.254.169.254") is False)
    check("peer_allowed: 公网放行", peer_allowed("93.184.216.34") is True)
    check("peer_allowed: 未知 peer 拒绝",
          peer_allowed(None) is False and peer_allowed("not-an-ip") is False)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)                     # room for both probe connects below
    pport = srv.getsockname()[1]
    try:
        conn = _peer_checked_class(http.client.HTTPConnection, False)("127.0.0.1", pport)
        try:
            conn.connect()
            check("连接后 peer 校验拒绝回环（无 allow_local）", False, "未拒绝")
        except EndpointRejected as e:
            check("连接后 peer 校验拒绝回环（无 allow_local）",
                  e.reason == "connected_ip_blocked", e.reason)
        finally:
            conn.close()
        conn2 = _peer_checked_class(http.client.HTTPConnection, True)("127.0.0.1", pport)
        try:
            conn2.connect()
            check("连接后 peer 校验放行回环（allow_local）", True)
        except Exception as e:  # noqa: BLE001
            check("连接后 peer 校验放行回环（allow_local）", False, repr(e))
        finally:
            conn2.close()
    finally:
        srv.close()

    # ---------- 3. credentials ----------
    cpath = os.path.join(tmp, "creds.json")
    kpath = os.path.join(tmp, "creds.key")
    cs = CredentialStore(cpath, key_path=kpath).load()
    pub = cs.put("prov_x", "sk-super-secret-123", label="main")
    check("凭据视图含 fingerprint", pub["fingerprint"] == fingerprint_of("sk-super-secret-123"))
    check("凭据视图含 credential_ref", pub["credential_ref"].startswith("cred://"))
    check("凭据视图不含明文", "sk-super-secret-123" not in json.dumps(pub))
    raw_file = Path(cpath).read_text("utf-8")
    check("落盘文件不含明文", "sk-super-secret-123" not in raw_file)
    check("文件权限 600", oct(os.stat(cpath).st_mode & 0o777) == "0o600")
    check("密钥文件权限 600", oct(os.stat(kpath).st_mode & 0o777) == "0o600")
    check("受控读取可取回明文", cs.read_secret(pub["credential_ref"]) == "sk-super-secret-123")
    check("is_configured 为真", cs.is_configured("prov_x") is True)
    rot = cs.rotate(pub["id"], "sk-rotated-456", confirm=True)
    check("轮换产生新版本", rot["current_v"] == 2 and rot["fingerprint"] == fingerprint_of("sk-rotated-456"))
    check("新 ref 读到新密钥", cs.read_secret(rot["credential_ref"]) == "sk-rotated-456")
    try:
        cs.read_secret(pub["credential_ref"])
        check("旧 ref 失效（stale）", False, "未拒绝")
    except Exception:
        check("旧 ref 失效（stale）", True)
    try:
        cs.delete(pub["id"], confirm=True, in_use=True)
        check("被引用时拒绝删除", False, "未拒绝")
    except CredentialInUse:
        check("被引用时拒绝删除", True)
    try:
        cs.delete(pub["id"], confirm=False)
        check("删除需 confirm", False, "未拒绝")
    except ConfirmRequired:
        check("删除需 confirm", True)

    # ---------- 4. registry + gating ----------
    rpath = os.path.join(tmp, "registry.json")
    reg = ModelRegistry(rpath).load().ensure_seeded()
    prov = reg.create_provider(name="星河 AI", protocol="openai_compatible",
                               base_url="https://api.galaxy.internal/v1",
                               capabilities=["text_llm", "streaming"],
                               resolver=lambda h: ["93.184.216.34"])
    try:
        reg.create_provider(name="星河 AI", protocol="openai_compatible",
                            base_url="https://api.galaxy.internal/v1",
                            resolver=lambda h: ["93.184.216.34"])
        check("重复 Provider 被拒绝", False, "未拒绝")
    except Duplicate:
        check("重复 Provider 被拒绝", True)
    mdl = reg.create_model(provider_id=prov["id"], model_key="galaxy-model-x1",
                           capabilities=["text_llm", "streaming"])
    check("新建模型默认未启用", mdl["enabled"] is False)
    check("新建模型适配器为 partial", mdl["adapter"] == "partial")

    cs2 = CredentialStore(os.path.join(tmp, "c2.json"),
                          key_path=os.path.join(tmp, "c2.key")).load()
    ok, code, _ = enable_gate(reg, cs2, mdl["id"], scene="text_chat")
    check("无凭据 → credential_missing（门禁先于启用）",
          (ok, code) == (False, "evidence_missing"), code)

    reg.set_evidence(mdl["id"], "adapter_present", source="sim")
    ok, code, _ = enable_gate(reg, cs2, mdl["id"], scene="text_chat")
    check("模拟仅到 adapter_present → evidence_missing",
          (ok, code) == (False, "evidence_missing"), code)

    reg.set_evidence(mdl["id"], "verified", source="real_test")
    ok, code, _ = enable_gate(reg, cs2, mdl["id"], scene="text_chat")
    check("已验证但无凭据 → credential_missing", (ok, code) == (False, "credential_missing"), code)

    cs2.put(prov["id"], "sk-abc")
    ok, code, det = enable_gate(reg, cs2, mdl["id"], scene="text_chat")
    check("已验证 + 有凭据 + 能力满足 → 放行", (ok, code) == (True, None), (code, det))

    ok, code, det = enable_gate(reg, cs2, mdl["id"], scene="oral_realtime")
    check("实时语音：能力不足先被拒（契约步骤6先于7）",
          (ok, code) == (False, "capability_mismatch") and str(det).startswith("missing:"),
          (code, det))

    # 声明实时语音能力后，仍必须 realtime_safe 才可绑定（步骤7）
    reg.update_model(mdl["id"], capabilities=["text_llm", "streaming",
                                              "realtime_audio", "barge_in"])
    ok, code, det = enable_gate(reg, cs2, mdl["id"], scene="oral_realtime")
    check("声明实时能力但未 realtime_safe → 拒绝",
          (ok, code) == (False, "capability_mismatch"), (code, det))

    # 显式提升（契约 §2.3 步骤3）：promote_realtime_safe 是写入 realtime_safe 的唯一通道
    try:
        reg.promote_realtime_safe(mdl["id"], confirm=False)
        check("提升需 confirm（ConfirmRequired）", False, "未拒绝")
    except ConfirmRequired:
        check("提升需 confirm（ConfirmRequired）", True)

    mlow = reg.create_model(provider_id=prov["id"], model_key="promote-low",
                            capabilities=["text_llm"])
    try:
        reg.promote_realtime_safe(mlow["id"], confirm=True)
        check("低于 verified 的提升被拒（evidence_missing）", False, "未拒绝")
    except ModelRegistryError as e:
        check("低于 verified 的提升被拒（evidence_missing）",
              str(e) == "evidence_missing", str(e))

    out = reg.promote_realtime_safe(mdl["id"], operator="tester", confirm=True)
    check("已 verified 的显式提升写入 realtime_safe",
          out.get("level") == "realtime_safe"
          and str(out.get("source") or "").startswith("authorized_promotion:"), out)
    out2 = reg.set_evidence(mdl["id"], "verified", source="real_test_rerun")
    check("重复真实验证不回退已提升的 realtime_safe（高水位）",
          out2.get("level") == "realtime_safe"
          and any(r.get("level") == "verified" and r.get("source") == "real_test_rerun"
                  for r in (out2.get("runs") or [])), out2)
    ok, code, det = enable_gate(reg, cs2, mdl["id"], scene="oral_realtime")
    check("提升 realtime_safe 后放行（非永久禁止）", (ok, code) == (True, None), (code, det))

    # unknown protocol -> never usable
    prov2 = reg.create_provider(name="未知协议", protocol="custom_unknown",
                                base_url="https://u.internal/v1",
                                resolver=lambda h: ["93.184.216.34"])
    m2 = reg.create_model(provider_id=prov2["id"], model_key="unknown-1")
    cs2.put(prov2["id"], "sk-xyz")
    check("未知协议 evidence 恒为 id_only", reg.evidence_level(m2["id"]) == "id_only")
    ok, code, _ = enable_gate(reg, cs2, m2["id"], scene="text_chat")
    check("未知协议无法启用", ok is False)

    # frozen protection
    reg.mark_frozen(mdl["id"], True)
    check("冻结后 evidence 仍可查", reg.is_frozen(mdl["id"]) is True)
    try:
        reg.set_enabled(mdl["id"], True)
        check("冻结模型禁止 enable", False, "未拒绝")
    except FrozenModel:
        check("冻结模型禁止 enable", True)
    ok, code, _ = enable_gate(reg, cs2, mdl["id"], scene="text_chat")
    check("冻结模型门禁拒绝", (ok, code) == (False, "frozen_model"), code)
    try:
        reg.delete_model(mdl["id"], confirm=mdl["id"])
        check("冻结模型禁止删除", False, "未拒绝")
    except FrozenModel:
        check("冻结模型禁止删除", True)

    # delete requires confirm == id
    try:
        reg.delete_model(m2["id"], confirm="wrong")
        check("删除模型需 confirm==id", False, "未拒绝")
    except ConfirmRequired:
        check("删除模型需 confirm==id", True)

    print("\n==== SUMMARY ====")
    print("total=%d pass=%d fail=%d" % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
