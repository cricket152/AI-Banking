import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .agent import BankingAgent
from .domain import BankingDemo


MAX_REQUEST_BYTES = 64 * 1024
WEB_ROOT = Path(__file__).resolve().parent / "web"


class BankingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, BankingRequestHandler)
        self.bank = BankingDemo()
        self.agent = BankingAgent(self.bank)


class BankingRequestHandler(BaseHTTPRequestHandler):
    server_version = "AIBankingDemo/1.0"
    sys_version = ""

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            self.send_response(204)
            self._send_security_headers()
            self.end_headers()
            return
        if path == "/api/health":
            self._send_json({"ok": True, "mode": "local-demo"})
            return
        if path == "/api/state":
            self._send_json(self.server.bank.get_state())
            return
        assets = {
            "/": "index.html",
            "/index.html": "index.html",
            "/app.css": "app.css",
            "/app.js": "app.js",
        }
        filename = assets.get(path)
        if filename is None:
            self._send_json({"error": "未找到该页面或接口。"}, status=404)
            return
        self._send_file(WEB_ROOT / filename)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except ValueError as error:
            self._send_json({"error": str(error)}, status=400)
            return
        if path == "/api/chat":
            message = payload.get("message")
            if not isinstance(message, str) or len(message) > 2000:
                self._send_json({"error": "message 必须是 2000 字以内的文本。"}, status=400)
                return
            self._send_json(self.server.agent.handle(message))
            return
        if path == "/api/reset":
            self.server.agent = BankingAgent(self.server.bank)
            self._send_json(self.server.bank.reset())
            return
        match = re.fullmatch(r"/api/actions/([a-f0-9]{32})/(confirm|reject)", path)
        if match:
            action_id, operation = match.groups()
            result = (
                self.server.agent.confirm(action_id)
                if operation == "confirm"
                else self.server.agent.reject(action_id)
            )
            self._send_json(result, status=200 if result["ok"] else 409)
            return
        self._send_json({"error": "未找到该接口。"}, status=404)

    def _read_json(self):
        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header or "0")
        except ValueError as error:
            raise ValueError("无效的请求长度。") from error
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("请求内容为空或超过 64 KB。")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("请求体必须是 UTF-8 JSON。") from error
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象。")
        return payload

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._send_security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json({"error": "静态资源不可用。"}, status=404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self._send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        self.send_header("Cache-Control", "no-store")

    def log_message(self, format_string, *args):
        if self.path.startswith("/api/"):
            return
        super().log_message(format_string, *args)


def main():
    parser = argparse.ArgumentParser(description="AI Banking 本地演示")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("演示服务仅允许绑定到本机回环地址。")
    candidates = [args.port] if args.port != 8765 else range(args.port, args.port + 10)
    httpd = None
    for port in candidates:
        try:
            httpd = BankingHTTPServer((args.host, port))
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"无法在 {args.port} 附近找到可用端口。")
    display_host = "[::1]" if args.host == "::1" else args.host
    print(
        f"AI Banking 本地演示已启动：http://{display_host}:{httpd.server_port}"
    )
    print("仅使用内存中的模拟数据。按 Ctrl+C 停止服务。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭本地演示服务。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
