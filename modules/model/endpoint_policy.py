"""Custom-endpoint safety policy (contract §3.3, SSRF protection).

Validated at Provider create/update time.  The rules are deliberately strict:
a user-configured endpoint must not be able to reach the NAS host, the LAN, or
a cloud metadata service.

Checks (all mandatory):

* scheme must be ``https`` (``http`` only for an explicitly allowed loopback);
* no ``user:pass@`` userinfo;
* hostname must not be a metadata service name;
* **every** IP the hostname resolves to must pass the blocklist (defends against
  DNS-rebinding where the name looks public but resolves inward);
* port must be 443 (loopback exception: any port).

Note: the adapter layer additionally re-checks the *actually connected* IP
(:func:`peer_allowed` via the probe's connection classes) and must not follow
cross-host redirects (documented in the contract).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

METADATA_HOSTS = {
    "metadata", "metadata.google.internal", "metadata.goog",
    "instance-data", "metadata.azure.com",
}

_BLOCKED_NETS = [
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
        "::1/128", "fc00::/7", "fe80::/10",
    )
]


class EndpointRejected(ValueError):
    """The endpoint violates the safety policy (``400 endpoint_not_allowed``)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = str(reason)


_NAT64_NETS = [ipaddress.ip_network(n) for n in (
    "64:ff9b::/96", "64:ff9b:1::/48", "::ffff:0:0:0/96")]   # WKP / local-use / SIIT


def _embedded_v4s(a):
    """Every IPv6 form that embeds an IPv4 address (mapped / 6to4 / Teredo /
    NAT64 / deprecated IPv4-compatible) is judged as its IPv4, so none of them
    can slip a private or metadata address past the IPv4 blocklist."""
    if a.version != 6:
        return [a]
    if a.ipv4_mapped is not None:
        return [a.ipv4_mapped]
    if a.sixtofour is not None:
        return [a.sixtofour]
    if a.teredo is not None:
        srv, cli = a.teredo
        return [srv, cli]
    if any(a in net for net in _NAT64_NETS):
        return [ipaddress.ip_address(int(a) & 0xFFFFFFFF)]
    n = int(a)
    if n not in (0, 1) and (n >> 32) == 0:          # ::a.b.c.d (compatible)
        return [ipaddress.ip_address(n)]
    return [a]


def _norm(a):
    """The single representative IPv4 for well-known mapped forms (used by the
    loopback exceptions); non-embedded addresses pass through unchanged."""
    if a.version == 6 and a.ipv4_mapped is not None:
        return a.ipv4_mapped
    return a


def _is_blocked(ip) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(c in net for c in _embedded_v4s(a) for net in _BLOCKED_NETS)


def peer_allowed(ip, *, allow_local=False) -> bool:
    """Policy check for an **actually connected** peer IP (contract §3.3: the
    adapter layer re-checks the real connection, not just the hostname).
    Loopback passes only under ``allow_local``; unparseable/unknown -> refused."""
    if ip is None:
        return False
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    cands = _embedded_v4s(a)
    if all(c.is_loopback for c in cands):
        return bool(allow_local)
    return not any(c in net for c in cands for net in _BLOCKED_NETS)


def _resolve(host):
    """All addresses the host resolves to (best effort, bounded)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except Exception:  # noqa: BLE001  (unresolvable -> reject, do not guess)
        return []
    out = []
    for info in infos:
        addr = info[4][0]
        if addr not in out:
            out.append(addr)
    return out


def validate_endpoint(url, *, allow_local=False, resolver=None):
    """Return the normalized URL, or raise :class:`EndpointRejected`.

    ``resolver`` is injectable so tests never touch the network.
    """
    raw = str(url or "").strip()
    if not raw:
        raise EndpointRejected("endpoint_required")
    try:
        parts = urlsplit(raw)
    except Exception:  # noqa: BLE001
        raise EndpointRejected("endpoint_unparseable")

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise EndpointRejected("scheme_not_allowed")
    if parts.username or parts.password:
        raise EndpointRejected("userinfo_not_allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise EndpointRejected("host_required")
    if host in METADATA_HOSTS:
        raise EndpointRejected("metadata_host_not_allowed")

    try:
        port = parts.port
    except ValueError:
        raise EndpointRejected("port_invalid")

    # A literal IP is checked directly; a name is resolved first.
    try:
        literal = ipaddress.ip_address(host)
        addrs = [str(literal)]
    except ValueError:
        addrs = (resolver or _resolve)(host)
        if not addrs:
            raise EndpointRejected("host_unresolvable")

    blocked = [a for a in addrs if _is_blocked(a)]
    loopback = all(_norm(ipaddress.ip_address(a)).is_loopback for a in addrs)
    if blocked:
        if not (allow_local and loopback):
            raise EndpointRejected("private_address_blocked")

    if scheme == "http" and not (allow_local and loopback):
        raise EndpointRejected("scheme_must_be_https")
    if port is not None and port != 443 and not (allow_local and loopback):
        raise EndpointRejected("port_not_allowed")

    # ---- base-URL contract (probe.py 的拼接规则配套；禁止重复/端点路径) ------
    # probe 的规则：``base`` 以 /v1 结尾则拼 /models，否则拼 /v1/models。
    # 因此这里拒绝会在拼接后产生重复路径的两种输入，并返回去掉尾部斜杠的
    # 规范形式（存储值即规范值，读回一致）。
    segs = [s for s in (parts.path or "").split("/") if s]
    for a, b in zip(segs, segs[1:]):
        if a.lower() == "v1" and b.lower() == "v1":
            raise EndpointRejected("path_duplicated_v1")
    low = [s.lower() for s in segs]
    if low[-2:] == ["v1", "models"] or low[-1:] == ["models"]:
        raise EndpointRejected("path_includes_endpoint")

    return raw.rstrip("/") or raw
