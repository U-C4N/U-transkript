"""A throwaway local HTTP server for real-socket transport tests."""

from __future__ import annotations

import gzip
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class _Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        """Clients that time out on purpose make writes fail; that is expected here."""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        """Keep test output quiet."""

    def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/json":
            self._send(200, b'{"ok": true}', {"Content-Type": "application/json"})
        elif self.path == "/gzip":
            body = gzip.compress("zipped ♪".encode())
            self._send(
                200, body, {"Content-Type": "text/plain; charset=utf-8", "Content-Encoding": "gzip"}
            )
        elif self.path == "/missing":
            self._send(404, b"nope", {"Content-Type": "text/plain"})
        elif self.path == "/slow":
            time.sleep(1.0)
            self._send(200, b"late", {})
        else:
            self._send(
                200, json.dumps({"path": self.path}).encode(), {"Content-Type": "application/json"}
            )

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = {
            "path": self.path,
            "body": body.decode(),
            "content_type": self.headers.get("Content-Type"),
            "user_agent": self.headers.get("User-Agent"),
        }
        self._send(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})


@contextmanager
def local_server() -> Iterator[str]:
    """Serve on 127.0.0.1 in a background thread and yield the base URL."""
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
