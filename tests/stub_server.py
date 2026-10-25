"""A scripted in-process HTTP server for provider tests.

No test may reach the real network, and no test may require a real credential. This server speaks
just enough HTTP to exercise every transport branch, and it records what it received so a test can
assert on the request as well as the response.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: dict[str, Any] | None


@dataclass
class StubResponse:
    status: int = 200
    body: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


class StubServer:
    """Routes registered as ``(method, path) -> StubResponse``; unknown paths answer 404."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], StubResponse] = {}
        self.recorded: list[Recorded] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def route(self, method: str, path: str, *, status: int = 200, body: Any = None,
              headers: dict[str, str] | None = None) -> None:
        self.routes[(method.upper(), path)] = StubResponse(
            status=status, body=body if body is not None else {}, headers=headers or {}
        )

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("server not started")
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def __enter__(self) -> StubServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:  # silence
                return

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    parsed = json.loads(raw) if raw else None
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                outer.recorded.append(
                    Recorded(
                        method=self.command,
                        path=self.path,
                        headers={k.lower(): v for k, v in self.headers.items()},
                        body=parsed,
                    )
                )
                spec = outer.routes.get((self.command, self.path))
                if spec is None:
                    payload = json.dumps({"error": "not found"}).encode()
                    self.send_response(404)
                else:
                    payload = json.dumps(spec.body).encode()
                    self.send_response(spec.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for key, value in (spec.headers if spec else {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _handle
            do_POST = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
