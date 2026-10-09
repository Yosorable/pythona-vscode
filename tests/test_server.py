from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import time
import unittest

from vscode_app.server import LocalServer, MAX_REQUEST_BYTES
from vscode_app.workspace import WorkspaceApp


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pythona_vscode_http_")
        root = Path(self.temporary.name)
        self.documents = root / "Documents"
        (self.documents / "Project").mkdir(parents=True)
        (self.documents / "Project/main.py").write_text("print(42)\n")
        bundle = root / "bundle"
        bundle.mkdir()
        (bundle / "index.html").write_text("<!doctype html><!--pythona:appearance--><title>Workbench</title>")
        (bundle / "test.wasm").write_bytes(b"\0asm")
        self.app = WorkspaceApp(self.documents, root / "state.json")
        self.server = LocalServer(self.app, bundle=bundle)

    def tearDown(self):
        self.server.close()
        self.app.close()
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def api(self, action, payload=None, headers=None):
        return self.request("POST", self.server.prefix + "api", json.dumps({"action": action, "payload": payload}), {
            "Content-Type": "application/json", "X-Pythona-Session": self.server.token,
            "Origin": self.server.origin, **(headers or {}),
        })

    def test_bundle_supports_offline_workers_and_wasm(self):
        status, headers, body = self.request("GET", self.server.prefix)
        self.assertEqual(status, 200)
        self.assertIn(b"Workbench", body)
        self.assertIn("worker-src 'self' blob:", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.request("GET", self.server.prefix + "test.wasm")[1]["Content-Type"], "application/wasm")

    def test_plain_paths_and_path_traversal_do_not_expose_files(self):
        for path in ["/", "/api", self.server.prefix + "../state.json",
                     self.server.prefix + "%2e%2e/Documents/Project/main.py",
                     self.server.prefix + "%2fetc/passwd"]:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_html_uses_saved_light_colors_before_javascript(self):
        self.app.dispatch("preferences.update", {"settings": "{}", "theme": {
            "name": "Light Modern", "type": "light", "colors": {
                "sideBar.background": "#f8f8f8", "editor.background": "#ffffff", "foreground": "#616161"}}})
        for route in (self.server.prefix, self.server.prefix + "index.html"):
            status, _, body = self.request("GET", route)
            self.assertEqual(status, 200)
            self.assertIn(b"--startup-background: #f8f8f8", body)
            self.assertIn(b"color-scheme: light", body)
            self.assertNotIn(b"<!--pythona:appearance-->", body)

    def test_api_requires_session_and_matching_origin_and_host(self):
        self.assertEqual(self.api("bootstrap")[0], 200)
        for headers in [{"X-Pythona-Session": "wrong"}, {"Origin": "https://example.com"},
                        {"Host": "attacker.example"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Content-Type": "text/plain"}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.api("bootstrap", headers=headers)[0], 403)

    def test_real_workspace_round_trip(self):
        reply = json.loads(self.api("workspace.open", {"path": "Project"})[2])
        workspace = reply["result"]["id"]
        reply = json.loads(self.api("fs.write", {"workspace": workspace, "path": "main.py",
                                                "data": "aGVsbG8=", "create": True, "overwrite": True})[2])
        self.assertIn("revision", reply["result"])
        self.assertEqual((self.documents / "Project/main.py").read_text(), "hello")

    def test_oversized_requests_are_rejected_before_reading_the_body(self):
        status, _, _ = self.request("POST", self.server.prefix + "api", b"", {
            "Content-Type": "application/json", "X-Pythona-Session": self.server.token,
            "Content-Length": str(MAX_REQUEST_BYTES + 1),
        })
        self.assertEqual(status, 413)

    def test_shutdown_joins_the_http_thread(self):
        self.assertTrue(self.server.thread.is_alive())
        self.server.close()
        self.assertFalse(self.server.thread.is_alive())
        self.assertFalse(self.server.maintenance_thread.is_alive())

    def test_pause_and_resume_keep_the_origin_session_and_workspace(self):
        workspace = self.app.dispatch("workspace.open", {"path": "Project"})
        url, token = self.server.url, self.server.token
        self.server.pause()
        self.assertFalse(self.server.thread.is_alive())
        self.assertFalse(self.app.closed.is_set())
        self.server.resume()
        self.assertEqual(self.server.url, url)
        self.assertEqual(self.server.token, token)
        self.assertEqual(self.app.workspace, workspace)
        self.assertEqual(self.request("GET", self.server.prefix + "health")[2], token.encode())
        self.assertEqual(json.loads(self.api("bootstrap")[2])["result"]["workspace"], workspace)

    def test_resume_replaces_a_live_listener_that_does_not_serve_health(self):
        original_thread = self.server.thread
        handler = self.server.http.RequestHandlerClass

        class UnhealthyHandler(handler):
            def do_GET(self):
                self._send(503)

        self.server.http.RequestHandlerClass = UnhealthyHandler
        self.assertTrue(original_thread.is_alive())
        self.server.resume()
        self.assertFalse(original_thread.is_alive())
        self.assertEqual(self.request("GET", self.server.prefix + "health")[0], 200)

    def test_resume_replaces_an_invalidated_socket(self):
        url = self.server.url
        self.server.http.socket.close()
        self.server.resume()
        self.assertEqual(self.server.url, url)
        self.assertEqual(self.request("GET", self.server.prefix)[0], 200)

    def test_lifecycle_requests_are_async_and_close_prevents_restart(self):
        self.server.set_active(False)
        deadline = time.monotonic() + 3
        while self.server.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.server.thread.is_alive())
        self.server.set_active(True)
        while not self.server._healthy() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server._healthy())
        self.server.close()
        self.server.set_active(True)
        self.server.resume()
        self.assertFalse(self.server.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
