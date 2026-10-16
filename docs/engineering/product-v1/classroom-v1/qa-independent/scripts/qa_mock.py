#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLASSROOM V1 独立 QA — 本机环回 Mock 网关（仅 127.0.0.1）。
- GET /xiaozhi/v1/teacher/list : 校验 X-Teacher-Token，返回 2 位老师（A/B）
- /xiaozhi/v1/teacher/ (WS 尝试) : 恒在升级前拒绝（无令牌 401 / 令牌正确 409）
- 其余路径一律 404 并记录（用于证明课堂没有其它请求）
"""
import json
import http.server
import socketserver
import time

PORT = 61933
LOG = "/tmp/xz-qa-cv1/mock/requests.log"
TOKEN = "QA-INDEPENDENT-DO-NOT-USE-0001"

TEACHERS = [
    {"teacher_id": "tch_qa_a", "display_name": "模拟老师 A",
     "voice_id": "Cherry", "language": "en"},
    {"teacher_id": "tch_qa_b", "display_name": "模拟老师 B",
     "voice_id": "Serena", "language": "zh"},
]


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _note(self, note):
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s %s %s\n" % (time.strftime("%H:%M:%S"), self.command, self.path, note))

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        tok = self.headers.get("X-Teacher-Token", "")
        if self.path.startswith("/xiaozhi/v1/teacher/") and not self.path.startswith("/xiaozhi/v1/teacher/list"):
            code = 401 if tok != TOKEN else 409
            self._note("WS_REFUSE pre-upgrade -> %d" % code)
            self._json(code, {"error": "unauthorized" if code == 401 else "realtime_model_not_configured"})
            return
        if self.path.startswith("/xiaozhi/v1/teacher/list"):
            ok = tok == TOKEN
            self._note("LIST token=%s" % ("OK" if ok else "BAD/ABSENT"))
            if not ok:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"teachers": TEACHERS})
            return
        self._note("UNEXPECTED_PATH")
        self._json(404, {"error": "not_found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H)
    print("QA_MOCK_READY port=%d" % PORT, flush=True)
    srv.serve_forever()
