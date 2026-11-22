#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断用静态服务器：把每个请求（方法、路径、User-Agent、Range）记到日志里。

用来确认客户端到底会向资源根请求什么路径 —— 这是排查"下载失败"最直接的证据。

    python scripts/diag_server.py public diag.log 8000
"""

from __future__ import annotations

import datetime
import http.server
import pathlib
import socket
import socketserver
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "public").resolve()
LOG_PATH = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "diag.log")
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8000

LOG = LOG_PATH.open("a", encoding="utf-8", buffering=1)


def logline(text: str) -> None:
    LOG.write(text + "\n")
    print(text, flush=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):  # noqa: ANN001, ANN002
        # 关掉默认日志，统一走自己的格式
        pass

    def _record(self, method: str) -> None:
        ua = self.headers.get("User-Agent", "-")
        rng = self.headers.get("Range", "-")
        host = self.headers.get("Host", "-")
        logline(
            f"{datetime.datetime.now():%H:%M:%S} {method} {self.path} "
            f"Host={host} UA={ua} Range={rng}"
        )

    def do_GET(self):  # noqa: N802
        self._record("GET")
        super().do_GET()

    def do_HEAD(self):  # noqa: N802
        self._record("HEAD")
        super().do_HEAD()

    def log_error(self, fmt, *args):  # noqa: ANN001, ANN002
        logline(f"  [error] {fmt % args}")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    ip = "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        pass
    finally:
        s.close()

    logline(f"=== 监听 0.0.0.0:{PORT}  根目录 {ROOT} ===")
    logline(f"=== 手机访问 http://{ip}:{PORT}/ ===")
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
