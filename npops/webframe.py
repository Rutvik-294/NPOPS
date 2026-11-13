"""NPOPS web framework — zero-dependency WSGI micro-framework.

Provides routing, middleware, request/response objects, JSON handling,
static files, and a dev server. ~400 lines that would otherwise be Flask.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import traceback
import urllib.parse
from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler

_mimetypes = mimetypes.MimeTypes()
_mimetypes.add_type("application/javascript", ".js")
_mimetypes.add_type("text/css", ".css")
_mimetypes.add_type("image/svg+xml", ".svg")


class HTTPError(Exception):
    def __init__(self, status: int, message: str = ""):
        self.status = status
        self.message = message or {
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
            404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
            422: "Unprocessable Entity", 500: "Internal Server Error",
        }.get(status, "Error")
        super().__init__(f"{status} {self.message}")


class Request:
    __slots__ = ("environ", "method", "path", "params", "query", "ctx",
                 "_body", "_json")

    def __init__(self, environ: dict):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "/")
        self.params: dict[str, str] = {}
        self.ctx: dict = {}  # populated by middleware (auth user, session, db)
        self._body: bytes | None = None
        self._json = ...
        qs = environ.get("QUERY_STRING", "")
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}

    @property
    def body(self) -> bytes:
        if self._body is None:
            try:
                length = int(self.environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            stream = self.environ.get("wsgi.input")
            self._body = stream.read(length) if stream and length > 0 else b""
        return self._body

    @property
    def json(self):
        if self._json is ...:
            if not self.body:
                raise HTTPError(400, "Empty request body; expected JSON")
            try:
                self._json = json.loads(self.body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise HTTPError(400, "Invalid JSON")
            if not isinstance(self._json, dict):
                raise HTTPError(400, "JSON body must be an object")
        return self._json

    def cookie(self, name: str) -> str | None:
        raw = self.environ.get("HTTP_COOKIE", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return urllib.parse.unquote(v)
        return None


class Response:
    def __init__(self, body=b"", status: int = 200,
                 content_type: str = "text/html; charset=utf-8",
                 headers: list | None = None):
        self.status = status
        self.headers: list[tuple[str, str]] = list(headers or [])
        if content_type:
            self.headers.append(("Content-Type", content_type))
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = body

    def set_cookie(self, name: str, value: str, max_age: int | None = None,
                   http_only: bool = True, path: str = "/"):
        parts = [f"{name}={urllib.parse.quote(value)}", f"Path={path}",
                 "SameSite=Lax"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        self.headers.append(("Set-Cookie", "; ".join(parts)))


def json_response(data, status: int = 200) -> Response:
    return Response(json.dumps(data, default=str), status=status,
                    content_type="application/json")


class Route:
    __slots__ = ("method", "pattern", "regex", "handler")

    def __init__(self, method: str, pattern: str, handler):
        self.method = method.upper()
        self.pattern = pattern
        self.handler = handler
        rx = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
        self.regex = re.compile(f"^{rx}$")


class App:
    def __init__(self):
        self.routes: list[Route] = []
        self.middleware: list = []   # callables: (req) -> None, may raise
        self.error_handlers: dict[int, callable] = {}
        self.static_dirs: dict[str, str] = {}  # url prefix -> fs path
        self.route_index: dict[str, list[str]] = {}

    # ---- registration -------------------------------------------------
    def route(self, path: str, methods: tuple[str, ...] = ("GET",)):
        def deco(fn):
            for m in methods:
                self.routes.append(Route(m, path, fn))
                self.route_index.setdefault(path, []).append(m)
            return fn
        return deco

    def get(self, path):
        return self.route(path, ("GET",))

    def post(self, path):
        return self.route(path, ("POST",))

    def patch(self, path):
        return self.route(path, ("PATCH",))

    def delete(self, path):
        return self.route(path, ("DELETE",))

    def static(self, url_prefix: str, fs_path: str):
        self.static_dirs[url_prefix.rstrip("/") or "/"] = \
            os.path.normpath(os.path.abspath(fs_path))

    def before_request(self, fn):
        self.middleware.append(fn)
        return fn

    # ---- dispatch ------------------------------------------------------
    def _match(self, method: str, path: str):
        path_matched = False
        for r in self.routes:
            m = r.regex.match(path)
            if m:
                path_matched = True
                if r.method == method or (r.method == "GET" and method == "HEAD"):
                    return r, m.groupdict()
        if path_matched:
            raise HTTPError(405)
        return None, None

    def _serve_static(self, path: str) -> Response | None:
        for prefix, root in self.static_dirs.items():
            rel = path[len(prefix):].lstrip("/") if path != "/" or prefix != "/" \
                else "index.html"
            if path == "/":
                rel = "index.html"
            elif prefix == "/" or path.startswith(prefix + "/"):
                rel = path[len(prefix):].lstrip("/")
            else:
                continue
            rel = os.path.normpath(rel)
            if rel.startswith("..") or os.path.isabs(rel):
                raise HTTPError(403)
            full = os.path.join(root, rel)
            if not os.path.isfile(full):
                continue
            ctype = _mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                return Response(f.read(), content_type=ctype)
        return None

    def handle(self, environ: dict) -> Response:
        req = Request(environ)
        try:
            static = self._serve_static(req.path) if req.method in ("GET", "HEAD") else None
            if static:
                return static
            route, params = self._match(req.method, req.path)
            if not route:
                raise HTTPError(404)
            req.params = {k: urllib.parse.unquote(v) for k, v in params.items()}
            for mw in self.middleware:
                mw(req)
            result = route.handler(req)
            if isinstance(result, Response):
                return result
            if isinstance(result, tuple):
                data, status = result
                return json_response(data, status)
            return json_response(result)
        except HTTPError as e:
            return self._error_response(req, e.status, e.message)
        except Exception:
            traceback.print_exc()
            return self._error_response(req, 500, "Internal Server Error")

    def _error_response(self, req: Request, status: int, message: str) -> Response:
        wants_json = (req.path.startswith("/api/") or
                      "application/json" in req.environ.get("HTTP_ACCEPT", ""))
        if wants_json:
            return json_response({"error": message}, status)
        return Response(f"<h1>{status}</h1><p>{message}</p>", status=status)

    # ---- WSGI -----------------------------------------------------------
    def wsgi(self, environ, start_response):
        resp = self.handle(environ)
        status_line = f"{resp.status} {HTTP_MESSAGES.get(resp.status, 'OK')}"
        body = b"" if environ.get("REQUEST_METHOD") == "HEAD" else resp.body
        headers = [(k, str(v)) for k, v in resp.headers]
        if "Content-Length" not in dict(headers):
            headers.append(("Content-Length", str(len(resp.body))))
        start_response(status_line, headers)
        return [body]

    def run(self, host: str = "0.0.0.0", port: int = 8000):
        server = make_server(host, port, self.wsgi,
                             server_class=QuietServer)
        print(f"  NPOPS serving on http://{host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


HTTP_MESSAGES = {
    200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request",
    401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 409: "Conflict", 422: "Unprocessable Entity",
    500: "Internal Server Error",
}


class QuietServer(WSGIServer):
    pass


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass
