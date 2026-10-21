import json
import sys
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_banking.server import BankingHTTPServer


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = BankingHTTPServer(("127.0.0.1", 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=2)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, response.read(), response.getheaders()
        connection.close()
        return result

    def test_static_page_has_security_headers(self):
        status, body, headers = self.request("GET", "/")
        header_map = dict(headers)
        self.assertEqual(status, 200)
        self.assertIn("澄明银行", body.decode("utf-8"))
        self.assertEqual(header_map["X-Frame-Options"], "DENY")
        self.assertIn("Content-Security-Policy", header_map)

    def test_health_and_state_endpoints(self):
        status, body, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "local-demo")

        status, body, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["accounts"]), 2)

    def test_missing_favicon_is_handled_without_a_404(self):
        status, _, _ = self.request("GET", "/favicon.ico")
        self.assertEqual(status, 204)

    def test_chat_action_confirmation_round_trip(self):
        status, body, _ = self.request(
            "POST", "/api/chat", {"message": "转 88 元给周明"}
        )
        self.assertEqual(status, 200)
        pending = json.loads(body)["pending_action"]

        status, body, _ = self.request(
            "POST", f"/api/actions/{pending['id']}/confirm", {}
        )
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertIn("周明", result["message"])

    def test_invalid_or_oversized_messages_are_rejected(self):
        status, _, _ = self.request("POST", "/api/chat", {"message": "x" * 2001})
        self.assertEqual(status, 400)

        status, body, _ = self.request("POST", "/api/chat", {"message": ""})
        self.assertEqual(status, 200)
        self.assertIn("想办理", json.loads(body)["reply"])

    def test_unknown_static_path_is_not_served(self):
        status, _, _ = self.request("GET", "/../../README.md")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
