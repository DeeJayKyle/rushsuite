"""Local bridge for the 'Listen with ReadRush' Chrome/Edge extension: the extension posts the
page (or selected) text to http://127.0.0.1:47653/read and ReadRush starts reading it.
Only accepts connections from this computer."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .voice_input import post

PORT = 47653
_server = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        body = json.dumps({"app": "ReadRush", "ok": True}).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.end_headers()
            return
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 20_000_000)
            data = json.loads(self.rfile.read(n).decode("utf-8", errors="replace"))
            text = str(data.get("text", "")).strip()
            if self.path.startswith("/read") and text:
                post("bridge_read", str(data.get("title", "Web page"))[:200], text, str(data.get("url", "")))
                code, msg = 200, {"ok": True}
            else:
                code, msg = 400, {"ok": False, "error": "no text"}
        except Exception as e:  # noqa: BLE001
            code, msg = 400, {"ok": False, "error": str(e)}
        body = json.dumps(msg).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(port: int = PORT) -> bool:
    global _server
    if _server:
        return True
    try:
        _server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError:
        return False
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return True


def stop():
    global _server
    if _server:
        _server.shutdown()
        _server = None
