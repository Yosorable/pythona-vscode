"""Serve the bundled workbench and its workspace API on loopback only."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import threading
from urllib.parse import unquote, urlsplit

from .filesystem import MAX_FILE_BYTES, WorkspaceError, parts


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
        self.http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.http.session = self
        self.port = self.http.server_port
        self.prefix = f"/{self.token}/"
        self.origin = f"http://127.0.0.1:{self.port}"
        self.url = self.origin + self.prefix
        self.thread = threading.Thread(target=self.http.serve_forever,
                                       kwargs={"poll_interval": 0.05}, name="PythonaVSCodeHTTP")
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)


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
        try:
            relative = unquote(route, errors="strict") or "index.html"
            parts(relative)
            file = (self.server.session.bundle / relative).resolve(strict=True)
            file.relative_to(self.server.session.bundle)
            body = file.read_bytes()
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
