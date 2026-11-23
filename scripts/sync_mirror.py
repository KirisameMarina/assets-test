#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把上游补丁包整理成客户端能按固定路径拉取的静态资源目录。

原理
----
游戏的资源清单与资源包是按固定路径拼接的：

    清单      <ResUrls>/AssetBundles/Catalog/<ResourceVersion>/Android/bundleDownloadInfo.json
    资源包    <ResUrls>/AssetBundles/Android/<Name>

清单里每个文件带 ``Crc``（即文件 MD5）与 ``Size``，客户端只下载 CRC 与本地记录
对不上的文件。因此一个最小可用的镜像只需要：

    1. 一份把补丁文件 CRC/Size 改过的清单
    2. 这些补丁文件本体

用法
----
    # 自动取当前官方版本 + 最新上游 Release，产出到 public/
    python scripts/sync_mirror.py --base-url https://<user>.github.io/<repo>

    # 用本地已下载的 zip，避免重复下载
    python scripts/sync_mirror.py --zip downloads/uncensor.zip --base-url ...

产物结构
--------
    public/prodm39/AssetBundles/Catalog/<ver>/Android/bundleDownloadInfo.json
    public/prodm39/AssetBundles/Android/<name>.bundle
    public/.nojekyll
    LocalizeConfig.txt          （模板，含占位好的 ResUrls）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

OFFICIAL_BASE = "https://static.bluearchive-cn.com/prodm39"
CATALOG_URL = OFFICIAL_BASE + "/AssetBundles/Catalog/{version}/Android/bundleDownloadInfo.json"

#: 第三方全量镜像，用来在境外（GitHub Actions）回退取官方 manifest
MIRROR_BASE = "https://mx.infastra.de5.net/prodm39"

#: 客户端启动时按顺序要的文件，缺任何一个都会直接报「网络连接失败」
#: 前五个是官方原样转存，bundleDownloadInfo.hash 由本脚本改写
OFFICIAL_MANIFEST_PATHS = (
    "Manifest/TableBundles/{tv}/TableManifestHash",
    "Manifest/TableBundles/{tv}/TableManifest",
    "Manifest/MediaResources/{mv}/MediaManifestHash",
    "Manifest/MediaResources/{mv}/MediaManifest",
    "AssetBundles/Catalog/{rv}/Android/catalog_Android.hash",
)

STATE_API = "https://gs-api.bluearchive-cn.com/api/state"
SETUP_API = "https://bluearchive-cn.com/api/meta/setup"

UPSTREAM_REPO = "Inf-Astra/Blue-Archive-Uncensor-Reborn"
UPSTREAM_BRANCH = "main_manual"
UPSTREAM_RAW = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{UPSTREAM_BRANCH}"
#: 国内直连 raw.githubusercontent.com 时常被重置，jsDelivr 作为回退源
UPSTREAM_MIRRORS = (
    UPSTREAM_RAW,
    f"https://cdn.jsdelivr.net/gh/{UPSTREAM_REPO}@{UPSTREAM_BRANCH}",
)
RELEASES_API = f"https://api.github.com/repos/{UPSTREAM_REPO}/releases/latest"

UA = "ba-uncensor-mirror/1.0 (+https://github.com/)"

# 客户端资源根里的渠道目录，国服为 prodm39
CHANNEL = "prodm39"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def human(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.2f} {unit}"
        v /= 1024
    return f"{n} B"


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# 网络
# --------------------------------------------------------------------------- #

def http_get_multi(urls, *, retries: int = 2, timeout: int = 120) -> bytes:
    """依次尝试多个镜像源，返回第一个成功的结果。"""
    last: Exception | None = None
    for url in urls:
        try:
            return http_get(url, retries=retries, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last = exc
            log(f"  [回退] {url} 失败，换下一个源")
    raise RuntimeError(f"所有上游源都失败: {urls}") from last


def http_download_multi(urls, dest: Path, *, retries: int = 3) -> Path:
    """多源下载到 dest，命中缓存则直接返回。"""
    if dest.is_file() and dest.stat().st_size > 0:
        log(f"  [缓存] {dest.name} ({human(dest.stat().st_size)})")
        return dest
    last: Exception | None = None
    for url in urls:
        try:
            return http_download(url, dest, retries=retries)
        except Exception as exc:  # noqa: BLE001
            last = exc
            log(f"  [回退] {url} 失败，换下一个源")
    raise RuntimeError(f"所有上游源都失败: {urls}") from last


def upstream_urls(rel_path: str) -> list[str]:
    return [f"{base}/{rel_path}" for base in UPSTREAM_MIRRORS]


def fetch_official_manifest(rel: str, dest: Path) -> bool:
    """官方 CDN 优先，境外拿不到时回退第三方镜像。"""
    for base in (OFFICIAL_BASE, MIRROR_BASE):
        url = f"{base}/{rel}"
        try:
            data = http_get(url, retries=2, timeout=240)
        except Exception as exc:  # noqa: BLE001
            log(f"  [回退] {url} 失败: {exc}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log(f"  OK  {rel}  {human(len(data))}")
        return True
    log(f"  [失败] 拿不到 {rel}（官方与镜像都不通）")
    return False


def http_get(url: str, *, retries: int = 3, timeout: int = 120) -> bytes:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            log(f"  [重试 {attempt}/{retries}] {url} -> {exc}")
    raise RuntimeError(f"下载失败: {url}") from last


def http_download(url: str, dest: Path, *, retries: int = 3) -> Path:
    if dest.is_file() and dest.stat().st_size > 0:
        log(f"  [缓存] {dest.name} ({human(dest.stat().st_size)})")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as resp, tmp.open("wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                last_pct = -10
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        if pct >= last_pct + 10:
                            last_pct = pct
                            log(f"    {pct:3d}%  {human(done)} / {human(total)}")
            os.replace(tmp, dest)
            return dest
        except Exception as exc:  # noqa: BLE001
            last = exc
            tmp.unlink(missing_ok=True)
            log(f"  [重试 {attempt}/{retries}] {dest.name} -> {exc}")
    raise RuntimeError(f"下载失败: {url}") from last


# --------------------------------------------------------------------------- #
# 版本号
# --------------------------------------------------------------------------- #

def fetch_versions() -> dict:
    """取当前国服 GameVersion / ResourceVersion（需要能访问国服域名）。"""
    raw = http_get(SETUP_API, retries=2, timeout=60).decode("utf-8", "replace")
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", raw)
    if not m:
        raise RuntimeError(f"无法从 {SETUP_API} 解析客户端版本号")
    game_version = ".".join(m.groups())

    req = urllib.request.Request(
        STATE_API,
        headers={
            "User-Agent": UA,
            "APP-VER": game_version,
            "PLATFORM-ID": "1",
            "CHANNEL-ID": "2",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    return {
        "GameVersion": game_version,
        "ResourceVersion": str(info.get("ResourceVersion") or "").strip(),
        "TableVersion": str(info.get("TableVersion") or "").strip(),
        "MediaVersion": str(info.get("MediaVersion") or "").strip(),
    }


def fetch_upstream_versions() -> dict:
    """从上游仓库的 current.txt 取版本号（GitHub 可达即可，境外 Actions 也能用）。"""
    raw = http_get_multi(upstream_urls("current.txt"), retries=2, timeout=60).decode(
        "utf-8", "replace"
    )
    out: dict = {}
    for line in raw.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    if not out.get("ResourceVersion"):
        raise RuntimeError(f"上游 current.txt 里没有 ResourceVersion: {raw[:200]!r}")
    return out



# --------------------------------------------------------------------------- #
# 上游补丁包
# --------------------------------------------------------------------------- #

def resolve_release_zip(tag: str = "") -> tuple[str, str]:
    """返回 (tag, 下载地址)，默认取最新 Release 里的 Uncensor 包。"""
    api = RELEASES_API if not tag else f"https://api.github.com/repos/{UPSTREAM_REPO}/releases/tags/{tag}"
    data = json.loads(http_get(api, retries=3, timeout=60).decode("utf-8"))
    picked = None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("BlueArchiveCN-Uncensor-") and name.endswith(".zip"):
            picked = asset
            break
    if not picked:
        raise RuntimeError(f"Release {data.get('tag_name')} 里没有 Uncensor zip")
    return data["tag_name"], picked["browser_download_url"]


def extract_bundles(zip_path: Path, target_dir: Path) -> list[Path]:
    """从上游 zip 里取出 AssetBundles/*.bundle。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            posix = info.filename.replace("\\", "/")
            if not posix.lower().endswith(".bundle"):
                continue
            # 只取 AssetBundles 下的，忽略 TableBundles
            if "/AssetBundles/" not in f"/{posix}":
                continue
            dest = target_dir / Path(posix).name
            with zf.open(info) as src, dest.open("wb") as dst:
                dst.write(src.read())
            out.append(dest)
    return out


# --------------------------------------------------------------------------- #
# 字体替换
# --------------------------------------------------------------------------- #

#: 游戏字体名 -> MiSans 字重（官方包里 MiSans/otf/MiSans-<字重>.otf）
FONT_WEIGHT_MAP = {
    "U-OTF-ShinMGoUpr-DeBold": "Demibold",
    "U-OTF-ShinMGoUpr-Medium": "Medium",
    "MALGUN": "Regular",
    "MALGUNBD": "Bold",
    "MALGUNSL": "Light",
    "CCG_LINESeedKR_Bd": "Semibold",
}


def _load_font_bytes(source: Path) -> dict[str, bytes]:
    """从 MiSans.zip 或单个字体文件里取出每个游戏字体要用的字节。"""
    if source.suffix.lower() in (".ttf", ".otf"):
        log(f"  单一字体文件: {source.name}（所有字重都用它）")
        data = source.read_bytes()
        return {name: data for name in FONT_WEIGHT_MAP}

    import zipfile

    out: dict[str, bytes] = {}
    with zipfile.ZipFile(source) as z:
        names = {i.filename for i in z.infolist()}
        for game_name, weight in FONT_WEIGHT_MAP.items():
            member = f"MiSans/otf/MiSans-{weight}.otf"
            if member not in names:
                # 退而求其次用 ttf
                alt = f"MiSans/ttf/MiSans-{weight}.ttf"
                if alt in names:
                    member = alt
                else:
                    raise SystemExit(f"{source.name} 里找不到 {member}")
            out[game_name] = z.read(member)
    return out


def apply_font(
    source: Path,
    *,
    site_bundles: Path,
    work: Path,
    index: dict,
) -> tuple[str, int, str] | None:
    """下载官方字体包、替换字体数据、写入站点。

    返回 (bundle 名, 新大小, 新 MD5)；失败或未启用返回 None。
    """
    try:
        import UnityPy
    except ImportError:
        log("  [跳过] 没装 UnityPy，无法做字体替换（pip install UnityPy）")
        return None

    font_name = next((n for n in index if "-fonts-" in n), None)
    if not font_name:
        log("  [跳过] 官方清单里找不到字体包（名字含 -fonts-）")
        return None

    log(f"  目标 bundle: {font_name}")
    local = work / font_name
    if not local.is_file() or local.stat().st_size != index[font_name]["Size"]:
        url = f"{OFFICIAL_BASE}/AssetBundles/Android/{quote(font_name)}"
        log(f"  下载官方字体包（{human(index[font_name]['Size'])}）")
        http_download(url, local)

    fonts = _load_font_bytes(source)
    env = UnityPy.load(str(local))
    replaced = 0
    for obj in env.objects:
        if obj.type.name != "Font":
            continue
        d = obj.read()
        name = getattr(d, "m_Name", "") or ""
        if name not in fonts:
            continue
        tree = obj.read_typetree()
        old_len = len(tree.get("m_FontData") or [])
        tree["m_FontData"] = list(fonts[name])
        tree["m_FontNames"] = ["MiSans"]
        obj.save_typetree(tree)
        replaced += 1
        log(f"    {name:28s} {old_len/1024**2:6.2f} MB -> {len(fonts[name])/1024**2:6.2f} MB")

    if replaced == 0:
        log("  [失败] 一个字体都没替换成功")
        return None

    data = env.file.save(packer="original")
    dest = site_bundles / font_name
    dest.write_bytes(data)
    digest = md5_of(dest)
    log(f"  替换 {replaced} 个字体，输出 {human(len(data))}")
    return font_name, len(data), digest


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="生成静态资源镜像目录")
    ap.add_argument("--base-url", required=True,
                    help="访问地址，多个用逗号分隔（写进 ResUrls 做冗余），"
                         "如 https://ghfast.top/raw.githubusercontent.com/<user>/<repo>/assets")
    ap.add_argument("--version", default="", help="资源版本号，默认自动获取")
    ap.add_argument("--tag", default="", help="上游 Release tag，默认取最新")
    ap.add_argument("--zip", type=Path, default=None, help="本地已有的上游 Uncensor zip")
    ap.add_argument("--catalog-source", choices=("official", "upstream"), default="official",
                    help="清单来源：official=国服官方（需能访问国服域名）；"
                         "upstream=上游仓库的 manifest（只依赖 GitHub，境外 Actions 可用）")
    ap.add_argument("--work", type=Path, default=Path("downloads"), help="下载缓存目录")
    ap.add_argument("--out", type=Path, default=Path("public"), help="产物输出目录")
    ap.add_argument("--font", type=Path, default=None,
                    help="替换游戏字体：MiSans.zip（按字重映射）或单个 .ttf/.otf（全部字重用它）")
    args = ap.parse_args()

    # 支持多个源，写进 ResUrls 做冗余；不足 3 个用最后一个补齐
    base_urls: list[str] = []
    for raw in args.base_url.split(","):
        raw = raw.strip().rstrip("/")
        if not raw:
            continue
        p = urlsplit(raw)
        if p.netloc:
            raw = urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))
        base_urls.append(raw)
    if not base_urls:
        raise SystemExit("--base-url 不能为空")
    base_url = base_urls[0]
    while len(base_urls) < 3:
        base_urls.append(base_urls[-1] if len(base_urls) > 1 else base_urls[0])
    base_urls = base_urls[:3]

    work: Path = args.work
    out_root: Path = args.out
    upstream_mode = args.catalog_source == "upstream"

    log("== 1. 确定资源版本 ==")
    versions: dict = {}
    if args.version:
        version = args.version
        log(f"  使用指定版本: {version}")
        if upstream_mode:
            try:
                versions = fetch_upstream_versions()
            except Exception:  # noqa: BLE001
                versions = {}
        else:
            try:
                versions = fetch_versions()
            except Exception:  # noqa: BLE001
                versions = {}
    elif upstream_mode:
        info = fetch_upstream_versions()
        versions = info
        version = info["ResourceVersion"]
        log(f"  上游资源版本 {version}（表 {info.get('TableVersion', '-')}）")
    else:
        info = fetch_versions()
        versions = info
        version = info["ResourceVersion"]
        log(f"  客户端 {info['GameVersion']} / 资源版本 {version}")

    table_version = versions.get("TableVersion", "")
    media_version = versions.get("MediaVersion", "")
    log(f"  TableVersion={table_version or '-'}  MediaVersion={media_version or '-'}")

    log("\n== 2. 取上游补丁包 ==")
    if args.zip:
        zip_path = args.zip
        tag = args.tag or "local"
        if not zip_path.is_file():
            raise SystemExit(f"指定 zip 不存在: {zip_path}")
        log(f"  使用本地 zip: {zip_path}")
    else:
        tag, url = resolve_release_zip(args.tag)
        log(f"  上游 Release: {tag}")
        zip_path = work / f"upstream_{tag}.zip"
        http_download(url, zip_path)

    staging = work / f"bundles_{tag}"
    log("\n== 3. 解包补丁 bundle ==")
    bundles = extract_bundles(zip_path, staging)
    log(f"  共 {len(bundles)} 个 bundle，合计 {human(sum(p.stat().st_size for p in bundles))}")
    if not bundles:
        raise SystemExit("上游包中没有 AssetBundles/*.bundle，检查 zip 结构")

    log("\n== 4. 下载官方清单 ==")
    catalog_cache = work / f"bundleDownloadInfo_{version}.json"
    official_path = work / "bundleDownloadInfo_Official.json"
    if upstream_mode:
        sources = upstream_urls("manifest/bundleDownloadInfo_Official.json")
        log(f"  来源: 上游仓库 manifest（版本 {version}）")
    else:
        sources = [CATALOG_URL.format(version=version)]
        log(f"  来源: 国服官方 CDN（版本 {version}）")
    http_download_multi(sources, catalog_cache)
    official_path.write_bytes(catalog_cache.read_bytes())
    manifest = json.loads(catalog_cache.read_text(encoding="utf-8"))
    index = {e["Name"]: e for e in manifest.get("BundleFiles", [])}
    log(f"  官方清单条目 {len(index)}，{human(catalog_cache.stat().st_size)}")

    log("\n== 5. 计算 MD5 并改写清单 ==")
    original_crc = {name: entry.get("Crc") for name, entry in index.items()}
    patched = 0
    skipped: list[str] = []
    site_bundles = out_root / CHANNEL / "AssetBundles" / "Android"
    site_bundles.mkdir(parents=True, exist_ok=True)
    for path in sorted(bundles):
        entry = index.get(path.name)
        if entry is None:
            skipped.append(path.name)
            continue
        digest = md5_of(path)
        size = path.stat().st_size
        if entry.get("Crc") != digest or entry.get("Size") != size:
            entry["Crc"] = digest
            entry["Size"] = size
            patched += 1
        # 复制到站点目录
        dest = site_bundles / path.name
        if not dest.exists() or dest.stat().st_size != size:
            dest.write_bytes(path.read_bytes())

    log(f"  改写条目 {patched} 个；不在官方清单里被跳过 {len(skipped)} 个")
    for name in skipped[:5]:
        log(f"    - 跳过 {name}")

    if args.font:
        log("\n== 5b. 替换字体 ==")
        if not args.font.is_file():
            log(f"  [跳过] 字体文件不存在: {args.font}")
        else:
            got = apply_font(args.font, site_bundles=site_bundles, work=work, index=index)
            if got:
                fname, fsize, fmd5 = got
                entry = index[fname]
                entry["Size"] = fsize
                entry["Crc"] = fmd5
                patched += 1

    log("\n== 6. 写出站点清单 ==")
    catalog_dir = out_root / CHANNEL / "AssetBundles" / "Catalog" / version / "Android"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog_out = catalog_dir / "bundleDownloadInfo.json"
    catalog_out.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    log(f"  {catalog_out.relative_to(out_root)}  ({human(catalog_out.stat().st_size)})")

    # Jekyll 会忽略下划线开头的路径，必须关掉
    (out_root / ".nojekyll").write_text("", encoding="utf-8")

    # 站点里的 bundle 是二进制，禁止 git 做换行转换（否则 MD5 全废）
    (out_root / ".gitattributes").write_text(
        "* -text -eol -crlf -ident -filter -working-tree-encoding\n",
        encoding="utf-8",
    )

    # 不给搜索引擎留入口：站点本来也没有 HTML 页面，再加一层 robots.txt
    (out_root / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n",
        encoding="utf-8",
    )

    log("\n== 7. 转存官方 manifest（缺一个客户端就报网络连接失败）==")
    missing: list[str] = []
    if not table_version or not media_version:
        log("  [警告] 缺少 TableVersion / MediaVersion，无法转存 manifest")
    else:
        subs = {"tv": table_version, "mv": media_version, "rv": version}
        for tpl in OFFICIAL_MANIFEST_PATHS:
            rel = tpl.format(**subs)
            dest = out_root / CHANNEL / rel
            log(f"  {rel}")
            if not fetch_official_manifest(rel, dest):
                missing.append(rel)

        # bundleDownloadInfo.hash：客户端拿它判断是否要重下清单。
        # 用官方数字，改过清单就 +1，保证只在内容变化时才触发下载。
        hash_rel = f"AssetBundles/Catalog/{version}/Android/bundleDownloadInfo.hash"
        hash_dest = out_root / CHANNEL / hash_rel
        official_num = 0
        for base in (OFFICIAL_BASE, MIRROR_BASE):
            try:
                official_num = int(
                    http_get(f"{base}/{hash_rel}", retries=2, timeout=60).decode().strip()
                )
                break
            except Exception:  # noqa: BLE001
                continue
        if patched:
            official_num += 1
        hash_dest.parent.mkdir(parents=True, exist_ok=True)
        hash_dest.write_text(str(official_num), encoding="ascii")
        log(f"  {hash_rel} = {official_num}" + ("（清单已改写，+1）" if patched else ""))

    if missing:
        log(f"  [警告] {len(missing)} 个 manifest 缺失，客户端启动会直接失败")

    # 一致性检查：凡是被改过 Crc 的条目，站点里必须有对应文件，否则客户端会拿到 404
    orphans = [
        name for name, entry in index.items()
        if entry["Crc"] != original_crc.get(name, entry["Crc"])
        and not (site_bundles / name).is_file()
    ]
    if orphans:
        log(f"  [警告] 有 {len(orphans)} 个被改写的条目缺少文件（客户端会 404）：")
        for name in orphans[:5]:
            log(f"    - {name}")

    res_urls = [f"{u}/{CHANNEL}" for u in base_urls]
    localize = (
        "Env=dev\n"
        "IsLocalize=false\n"
        f"ResUrls={';'.join(res_urls)}\n"
    )
    (out_root.parent / "LocalizeConfig.txt").write_text(localize, encoding="utf-8")

    log("\n== 完成 ==")
    total = sum(p.stat().st_size for p in site_bundles.iterdir() if p.is_file())
    log(f"  站点文件 {len(list(site_bundles.iterdir()))} 个 bundle，合计 {human(total)}")
    log(f"  清单地址 {base_url}/{CHANNEL}/AssetBundles/Catalog/{version}/Android/bundleDownloadInfo.json")
    log("\n  把下面内容写进手机 files/LocalizeConfig.txt：")
    log("  " + "-" * 56)
    for line in localize.strip().splitlines():
        log(f"  {line}")
    log("  " + "-" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
