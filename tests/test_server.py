from http.client import HTTPConnection
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import quote

from vscode_app.filesystem import MAX_FILE_BYTES
from vscode_app.server import LocalServer, MAX_FILE_REQUEST_HEADER_BYTES, MAX_REQUEST_BYTES
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

    def request(self, method, path, body=None, headers=None, *, incomplete=False):
        connection = HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            if incomplete:
                connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def api(self, action, payload=None, headers=None):
        return self.request("POST", self.server.prefix + "api", json.dumps({"action": action, "payload": payload}), {
            "Content-Type": "application/json", "X-Pythona-Session": self.server.token,
            "Origin": self.server.origin, **(headers or {}),
        })

    def file(self, action, payload, data=b"", headers=None, **options):
        metadata = quote(json.dumps({"action": action, "payload": payload}, ensure_ascii=False), safe="")
        return self.request("POST", self.server.prefix + "file", data, {
            "Content-Type": "application/octet-stream", "X-Pythona-Session": self.server.token,
            "Origin": self.server.origin, "X-Pythona-Request": metadata, **(headers or {}),
        }, **options)

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
        path = '你好 %?#& 🐍.bin'
        for data in (b"", bytes(range(256)) * 513, b"\xff\xfe" + "你好 🐍\0".encode("utf-16-le")):
            with self.subTest(length=len(data)):
                reply = json.loads(self.file("fs.write", {"workspace": workspace, "path": path,
                                                        "create": True, "overwrite": True}, data)[2])
                revision = hashlib.sha256(data).hexdigest()
                self.assertEqual(reply["result"]["revision"], revision)
                self.assertEqual((self.documents / "Project" / path).read_bytes(), data)
                status, headers, actual = self.file("fs.read", {"workspace": workspace, "path": path})
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/octet-stream")
                self.assertEqual(headers["Content-Length"], str(len(data)))
                self.assertEqual(headers["X-Pythona-Revision"], revision)
                self.assertEqual(actual, data)

    def test_file_endpoint_requires_session_and_matching_origin_and_host(self):
        workspace = self.app.open_workspace("Project")
        payload = {"workspace": workspace["id"], "path": "main.py"}
        for action in ("fs.read", "fs.write"):
            for headers in [{"X-Pythona-Session": "wrong"}, {"Origin": "https://example.com"},
                            {"Host": "attacker.example"}, {"Sec-Fetch-Site": "cross-site"},
                            {"Content-Type": "text/plain"}, {"Transfer-Encoding": "chunked"}]:
                with self.subTest(action=action, headers=headers):
                    self.assertEqual(self.file(action, payload, headers=headers)[0], 403)
        self.assertEqual((self.documents / "Project/main.py").read_text(), "print(42)\n")

    def test_invalid_file_metadata_cannot_execute_other_actions_or_write_files(self):
        workspace = self.app.open_workspace("Project")
        payload = {"workspace": workspace["id"], "path": "main.py"}
        invalid = ["", "%FF", "not-json", "[]", '{"action":"host.close","payload":{}}',
                   '{"action":"fs.write","payload":{"data":"hidden"}}',
                   "x" * (MAX_FILE_REQUEST_HEADER_BYTES + 1)]
        for metadata in invalid:
            with self.subTest(metadata=metadata[:80]):
                self.assertEqual(self.file("fs.write", payload, headers={"X-Pythona-Request": metadata})[0], 400)
        self.assertEqual(self.file("fs.read", payload, b"unexpected body")[0], 400)
        self.assertFalse(self.app.closed.is_set())
        self.assertEqual((self.documents / "Project/main.py").read_text(), "print(42)\n")

    def test_file_requests_reject_stale_workspaces_traversal_and_symlinks(self):
        old = self.app.open_workspace("Project")
        outside = self.documents / "private.bin"
        outside.write_bytes(b"private")
        (self.documents / "Project/link.bin").symlink_to(outside)
        for path in ("../private.bin", "/private.bin", "link.bin"):
            for action in ("fs.read", "fs.write"):
                payload = {"workspace": old["id"], "path": path, "create": True, "overwrite": True}
                with self.subTest(path=path, action=action):
                    self.assertIn("error", json.loads(self.file(action, payload)[2]))
        (self.documents / "Other").mkdir()
        self.app.open_workspace("Other")
        for action in ("fs.read", "fs.write"):
            reply = json.loads(self.file(action, {"workspace": old["id"], "path": "main.py"})[2])
            self.assertEqual(reply["error"]["code"], "Unavailable")
        self.assertEqual(outside.read_bytes(), b"private")
        self.assertFalse((self.documents / "Other/main.py").exists())

    def test_failed_binary_saves_preserve_existing_bytes(self):
        workspace = self.app.open_workspace("Project")
        payload = {"workspace": workspace["id"], "path": "main.py", "create": True, "overwrite": True}
        revision = self.file("fs.read", payload)[1]["X-Pythona-Revision"]
        file = self.documents / "Project/main.py"
        file.write_bytes(b"external edit\0\xff")
        reply = json.loads(self.file("fs.write", {**payload, "expected": revision}, b"stale")[2])
        self.assertEqual(reply["error"]["code"], "FileWriteLocked")
        with patch("vscode_app.filesystem.os.replace", side_effect=OSError("Failed atomic replacement")):
            reply = json.loads(self.file("fs.write", payload, b"replacement")[2])
        self.assertIn("error", reply)
        self.assertEqual(self.file("fs.write", payload, b"partial", headers={"Content-Length": "100"},
                                   incomplete=True)[0], 400)
        self.assertEqual(file.read_bytes(), b"external edit\0\xff")
        self.assertFalse(list(file.parent.glob(".pythona-vscode-*.tmp")))

    def test_binary_file_limit_accepts_exact_boundary_and_rejects_larger_bodies(self):
        workspace = self.app.open_workspace("Project")
        payload = {"workspace": workspace["id"], "path": "large.bin", "create": True, "overwrite": True}
        data = b"\0" * MAX_FILE_BYTES
        reply = json.loads(self.file("fs.write", payload, data)[2])
        self.assertIn("result", reply)
        self.assertEqual(self.file("fs.read", payload)[2], data)
        self.assertEqual(self.file("fs.write", payload, headers={"Content-Length": str(MAX_FILE_BYTES + 1)})[0], 413)
        self.assertEqual((self.documents / "Project/large.bin").read_bytes(), data)

    def test_json_api_does_not_accept_file_contents(self):
        workspace = self.app.open_workspace("Project")
        for action in ("fs.read", "fs.write"):
            reply = json.loads(self.api(action, {"workspace": workspace["id"], "path": "main.py", "data": "text"})[2])
            self.assertEqual(reply["error"]["code"], "InvalidRequest")

    def test_execution_keeps_session_checks_and_survives_listener_recovery(self):
        workspace = self.app.open_workspace("Project")
        (self.documents / "Project/main.py").write_text('print(input("Name: "))\n')
        payload = {"workspace": workspace["id"], "id": str(uuid.uuid4()), "path": "main.py"}
        for headers in ({"Origin": "https://example.com"}, {"X-Pythona-Session": "wrong"},
                        {"Host": "attacker.example"}):
            self.assertEqual(self.api("run.start", payload, headers)[0], 403)
        self.assertIsNone(self.app.runner.current)
        self.assertIn("result", json.loads(self.api("run.start", payload)[2]))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = json.loads(self.api("run.status", payload)[2])["result"]
            if status["state"] == "input":
                break
            time.sleep(.01)
        self.assertEqual(status["state"], "input")
        self.server.pause()
        self.server.resume()
        restored = json.loads(self.api("run.status", payload)[2])["result"]
        self.assertEqual((restored["id"], restored["input"]), (payload["id"], status["input"]))
        reply = self.api("run.input", {**payload, "request": status["input"], "text": "你好"})
        self.assertIn("result", json.loads(reply[2]))
        self.assertTrue(self.app.runner.current.done.wait(3))
        completed = json.loads(self.api("run.status", payload)[2])["result"]
        self.assertEqual(completed["exitCode"], 0)
        self.assertEqual(completed["output"], "Name: 你好\n你好\n")

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
