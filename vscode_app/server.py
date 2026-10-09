"""Serve the bundled workbench and its workspace API on loopback only."""

from contextlib import suppress
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import threading
from urllib.parse import unquote, urlsplit

from .filesystem import MAX_FILE_BYTES, WorkspaceError, parts
from .preferences import startup_style


BUNDLE = Path(__file__).resolve().parents[1] / "frontend" / "dist"
MAX_REQUEST_BYTES = ((MAX_FILE_BYTES + 2) // 3 * 4) + 65536
CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; worker-src 'self' blob:; connect-src 'self' data:; "
    "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


class LocalServer:
    def __init__(self, app, *, port=0, bundle=BUNDLE):
        self.app = app
        self.bundle = Path(bundle).resolve(strict=True)
        if not (self.bundle / "index.html").is_file():
            raise RuntimeError("Missing frontend/dist. Build the frontend before running this project.")
        self.token = secrets.token_urlsafe(32)
        self.prefix = f"/{self.token}/"
        self.port = port
        self.lock = threading.RLock()
        self.closed = False
        self._listen()
        self.active = True
        self.wake = threading.Event()
        self.finished = threading.Event()
        self.maintenance_thread = threading.Thread(target=self._maintain, name="PythonaVSCodeLifecycle")
        self.maintenance_thread.start()

    def _listen(self):
        self.http = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.http.session = self
        self.http.timeout = 0.05
        self.http.socket.settimeout(0.05)
        self.port = self.http.server_port
        self.origin = f"http://127.0.0.1:{self.port}"
        self.url = self.origin + self.prefix
        self.stopping = threading.Event()
        http, stopping = self.http, self.stopping

        def serve():
            try:
                while not stopping.is_set():
                    http.handle_request()
            except (OSError, ValueError):
                # A suspended iOS process can resume with an invalid listening socket.
                pass

        self.thread = threading.Thread(target=serve, name="PythonaVSCodeHTTP")
        self.thread.start()

    def _stop_listener(self):
        self.stopping.set()
        self.thread.join(timeout=1)
        with suppress(OSError):
            self.http.server_close()
        if self.thread.is_alive():
            raise RuntimeError("The local HTTP listener did not stop.")

    def _healthy(self):
        if self.stopping.is_set() or not self.thread.is_alive():
            return False
        connection = HTTPConnection("127.0.0.1", self.port, timeout=0.5)
        try:
            connection.request("GET", self.prefix + "health")
            response = connection.getresponse()
            return response.status == 200 and response.read(128) == self.token.encode("ascii")
        except (OSError, HTTPException, ValueError):
            return False
        finally:
            connection.close()

    def pause(self):
        """Release the listener before suspension; keep the workspace and origin."""
        with self.lock:
            if not self.closed:
                self._stop_listener()

    def resume(self):
        """Check actual HTTP responses and rebind the same URL when needed."""
        with self.lock:
            if self.closed:
                return
            if not self._healthy():
                self._stop_listener()
                self._listen()

    def set_active(self, active):
        """Queue UIKit lifecycle notifications without blocking the main thread."""
        self.active = active
        self.wake.set()

    def _maintain(self):
        retry = False
        while not self.finished.is_set():
            self.wake.wait(0.5 if retry else None)
            self.wake.clear()
            if self.finished.is_set():
                return
            try:
                if self.active:
                    self.resume()
                else:
                    self.pause()
                retry = False
            except (OSError, RuntimeError):
                # A previous socket may take a moment to release its port.
                retry = self.active

    def close(self):
        self.finished.set()
        self.wake.set()
        with self.lock:
            if not self.closed:
                self.closed = True
                self._stop_listener()
        self.maintenance_thread.join()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "PythonaVSCode"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, _format, *_args):
        # Request paths contain the session capability and workspace filenames.
        pass

    def _send(self, status, body=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _route(self):
        session = self.server.session
        if self.headers.get("Host") != f"127.0.0.1:{session.port}":
            self._send(403)
            return None
        origin = self.headers.get("Origin")
        if origin is not None and origin != session.origin:
            self._send(403)
            return None
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._send(403)
            return None
        route = urlsplit(self.path).path
        if not route.startswith(session.prefix):
            self._send(404)
            return None
        return route[len(session.prefix):]

    def do_GET(self):
        route = self._route()
        if route is None:
            return
        if route == "health":
            self._send(200, self.server.session.token.encode("ascii"))
            return
        try:
            relative = unquote(route, errors="strict") or "index.html"
            parts(relative)
            file = (self.server.session.bundle / relative).resolve(strict=True)
            file.relative_to(self.server.session.bundle)
            body = file.read_bytes()
            if file == self.server.session.bundle / "index.html":
                with self.server.session.app.lock:
                    theme = self.server.session.app.preferences.snapshot()["theme"]
                body = body.replace(b"<!--pythona:appearance-->", startup_style(theme).encode("utf-8"))
        except (OSError, ValueError, WorkspaceError):
            self._send(404)
            return
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if file.suffix in (".js", ".mjs"):
            content_type = "text/javascript; charset=utf-8"
        elif file.suffix == ".wasm":
            content_type = "application/wasm"
        self._send(200, body, content_type)

    do_HEAD = do_GET

    def do_POST(self):
        route = self._route()
        if route is None:
            return
        session = self.server.session
        if route != "api":
            self._send(404)
            return
        if (self.headers.get("X-Pythona-Session") != session.token
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                or self.headers.get("Transfer-Encoding") is not None):
            self._send(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._send(413)
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self._send(400)
                return
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError("Invalid request")
        except (ValueError, OSError):
            self._send(400)
            return
        try:
            result = session.app.dispatch(request.get("action"), request.get("payload"))
            reply = {"result": result}
        except WorkspaceError as error:
            reply = {"error": {"code": error.code, "message": str(error)}}
        except Exception:
            reply = {"error": {"code": "Unavailable", "message": "The file operation failed."}}
        self._send(200, json.dumps(reply, ensure_ascii=True).encode(), "application/json; charset=utf-8")
