#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在局域网里把镜像目录当成资源服务器，供手机上的游戏客户端拉取。

用法::

    python scripts/serve.py                 # 默认 8000 端口，自动探测本机局域网 IP
    python scripts/serve.py --port 9000
    python scripts/serve.py --adb           # 顺便把 LocalizeConfig.txt 推到手机
    python scripts/serve.py --adb --package com.RoamingStar.BlueArchive.bilibili

前提：手机和电脑连同一个 WiFi；客户端允许 http 明文（社区教程里用 http 死链的配置
同样能进游戏）。
"""

from __future__ import annotations

import argparse
import http.server
import socket
import subprocess
import sys
import threading
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CHANNEL = "prodm39"


def lan_ip() -> str:
    """拿到本机在局域网里的地址（不会真的发包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def build_localize(urls: str) -> str:
    return f"Env=dev\nIsLocalize=false\nResUrls={urls};{urls};{urls}\n"


def push_to_device(config: str, package: str, serial: str) -> None:
    """把配置写到手机的 files/ 里。需要 adb 可用。"""
    target = f"/storage/emulated/0/Android/data/{package}/files/LocalizeConfig.txt"
    tmp = ROOT / "LocalizeConfig.txt"
    tmp.write_text(config, encoding="utf-8")
    print(f"\n[adb] 推送 -> {target}")
    for cmd in (
        ["adb", *(["-s", serial] if serial else []), "shell", "mkdir", "-p",
         f"/storage/emulated/0/Android/data/{package}/files"],
        ["adb", *(["-s", serial] if serial else []), "push", str(tmp), target],
    ):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        print(f"  {' '.join(cmd[:3])} ... -> {proc.returncode}")
        if proc.stdout.strip():
            print(f"    {proc.stdout.strip()}")
        if proc.returncode != 0 and proc.stderr.strip():
            print(f"    {proc.stderr.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser(description="局域网资源服务器")
    ap.add_argument("--dir", type=Path, default=ROOT / "public", help="要发布的目录")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--adb", action="store_true", help="同时用 adb 把配置推到手机")
    ap.add_argument("--package", default="com.RoamingStar.BlueArchive.bilibili",
                    help="游戏包名（B 服带 .bilibili，官服不带）")
    ap.add_argument("--serial", default="", help="adb 设备序列号（多设备时指定）")
    args = ap.parse_args()

    root: Path = args.dir
    if not root.is_dir():
        print(f"目录不存在: {root}\n先运行 scripts/sync_mirror.py 生成产物")
        return 1

    catalogs = sorted(root.glob(f"{CHANNEL}/AssetBundles/Catalog/*/Android/bundleDownloadInfo.json"))
    if not catalogs:
        print(f"{root} 里没有清单，先运行 scripts/sync_mirror.py")
        return 1
    version = catalogs[-1].parts[-4]
    bundle_count = len(list((root / CHANNEL / "AssetBundles" / "Android").glob("*.bundle")))

    ip = lan_ip()
    base = f"http://{ip}:{args.port}/{CHANNEL}"
    config = build_localize(base)

    print("=" * 68)
    print(f"  目录    {root}")
    print(f"  版本    {version}")
    print(f"  bundle  {bundle_count} 个")
    print(f"  地址    http://{ip}:{args.port}/")
    print("=" * 68)
    print("手机 files/LocalizeConfig.txt 的内容：")
    print("-" * 68)
    for line in config.strip().splitlines():
        print("  " + line)
    print("-" * 68)
    print(f"自检: http://{ip}:{args.port}/{CHANNEL}/AssetBundles/Catalog/{version}/Android/bundleDownloadInfo.json")
    print()

    if args.adb:
        push_to_device(config, args.package, args.serial)
        print()

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(root), **kw
    )
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"[{threading.current_thread().name}] 正在监听 0.0.0.0:{args.port}，Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
