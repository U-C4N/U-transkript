"""A throwaway local HTTP server for real-socket transport tests."""

from __future__ import annotations

import gzip
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MEDIA = bytes(range(256)) * 1024  # 256 KiB served at /media, with Range support


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
        elif self.path == "/media":
            self._media()
        elif self.path == "/truncated":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            self.close_connection = True
        elif self.path == "/stall":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            self.wfile.flush()
            time.sleep(1.0)
        else:
            self._send(
                200, json.dumps({"path": self.path}).encode(), {"Content-Type": "application/json"}
            )

    def _media(self) -> None:
        header = self.headers.get("Range")
        if header is None:
            self._send(200, MEDIA, {"Content-Type": "video/mp4"})
            return
        first, _, last = header.removeprefix("bytes=").partition("-")
        start = int(first)
        end = min(int(last) if last else len(MEDIA) - 1, len(MEDIA) - 1)
        headers = {
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes {start}-{end}/{len(MEDIA)}",
        }
        self._send(206, MEDIA[start : end + 1], headers)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = {
            "path": self.path,
            "body": body.decode(),
            "content_type": self.headers.get("Content-Type"),
            "user_agent": self.headers.get("User-Agent"),
        }
        self._send(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})


class _Server6(_Server):
    address_family = socket.AF_INET6


def ipv6_loopback_available() -> bool:
    """True when this machine can listen on ``::1``."""
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
    except OSError:
        return False
    return True


@contextmanager
def local_server(*, ipv6: bool = False) -> Iterator[str]:
    """Serve on 127.0.0.1 (or ``::1``) in a background thread and yield the base URL."""
    server = _Server6(("::1", 0), _Handler) if ipv6 else _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = "[::1]" if ipv6 else "127.0.0.1"
    try:
        yield f"http://{host}:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
