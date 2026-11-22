# assets-test

静态资源目录同步。私有用途，不保证任何东西。

## 客户端到底怎么拉的（实测）

把手机接到 adb，改 `ResUrls` 指向自己的服务器，从访问日志里抓到完整请求序列：

| 顺序 | 请求路径 | 说明 |
| --- | --- | --- |
| 1 | `/Manifest/TableBundles/<TableVersion>/TableManifestHash` | 表清单的变更标识 |
| 2 | `/Manifest/TableBundles/<TableVersion>/TableManifest` | 表清单本体（hash 变了才拉） |
| 3 | `/Manifest/MediaResources/<MediaVersion>/MediaManifestHash` | 媒体清单标识 |
| 4 | `/Manifest/MediaResources/<MediaVersion>/MediaManifest` | 媒体清单本体 |
| 5 | `/AssetBundles/Catalog/<ResourceVersion>/Android/bundleDownloadInfo.hash` | 资源清单标识 |
| 6 | `/AssetBundles/Catalog/<ResourceVersion>/Android/bundleDownloadInfo.json` | 资源清单本体 |
| 7 | `/AssetBundles/Catalog/<ResourceVersion>/Android/catalog_Android.hash` | Addressables catalog 标识 |
| 8 | `/AssetBundles/Android/<Name>.bundle` | 按清单逐个取资源包 |

**这 8 个请求，前 7 个缺任何一个，客户端都会直接弹「网络连接失败，请确认网络连接情况」**，
卡在 `Initialize Catalog...`，一个字节都不会下。

`User-Agent` 是 `UnityPlayer/2021.3.56f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)`。

## 为什么走加速站而不是 GitHub Pages

实测（同一台手机、同一网络）：

| 源 | 清单 4.56 MB | 大文件 31.9 MB |
| --- | --- | --- |
| `*.github.io` | 12 KB/s（45 秒只下 557 KB） | 超时 |
| jsDelivr | 391 KB/s | 超过 20 MB 限制，取不到 |
| **ghfast** | **450 KB/s** | **1.8 MB/s，18 秒** |

所以产物不进 Pages，而是强制推送到 `assets` 分支，客户端通过

```
https://ghfast.top/raw.githubusercontent.com/<user>/<repo>/assets/prodm39
```

拉取。`ResUrls` 就填这个地址（三遍，分号分隔）。

## 目录结构

```
public/
├─ .nojekyll
├─ .gitattributes           # 禁止换行转换，否则二进制 MD5 全废
├─ robots.txt
└─ prodm39/
   ├─ Manifest/
   │  ├─ TableBundles/<TableVersion>/{TableManifestHash,TableManifest}
   │  └─ MediaResources/<MediaVersion>/{MediaManifestHash,MediaManifest}
   └─ AssetBundles/
      ├─ Catalog/<ResourceVersion>/Android/
      │  ├─ bundleDownloadInfo.hash     # 官方值，清单改写过就 +1
      │  ├─ bundleDownloadInfo.json     # 改写过的资源清单
      │  └─ catalog_Android.hash        # 官方原值
      └─ Android/<Name>.bundle          # 63 个补丁资源
```

## 用法

```bash
# 国内网络：直接问官方要清单
python scripts/sync_mirror.py --base-url https://ghfast.top/raw.githubusercontent.com/<user>/<repo>/assets

# 境外 / CI：版本与清单都从上游仓库拿
python scripts/sync_mirror.py --catalog-source upstream --base-url ...
```

`--catalog-source upstream` 时，官方 manifest 会先试国服 CDN，失败回退第三方全量镜像；
上游 `current.txt` 与 Release 走 `raw.githubusercontent.com`，失败回退 jsDelivr。

## 更新流程

1. 上游版本一变，Actions 自动重建并强制推送 `assets` 分支（每 12 小时检查一次，版本没变跳过）
2. 手机不用改配置，`bundleDownloadInfo.hash` 变了客户端自己会重拉清单和资源
3. 想强制重建：Actions 里手动跑，勾 `force`

## 故障排查

- **卡在 `Initialize Catalog...` + 「网络连接失败」** → 前 7 个请求里有 404。用
  `scripts/diag_server.py` 把 `ResUrls` 指到电脑，看它到底要哪个文件。
- **下了但画面没变** → 校验清单里的 `Crc` 和文件实际 MD5 是否一致。
- **`assets` 分支里的文件 MD5 和本地不一致** → `.gitattributes` 没生效，被换行转换破坏了。

## 边界

- 只放被改过的 63 个文件（约 72 MB），不做全量镜像（官方 24159 个 / 6.46 GB）。
- 换机、清资源、点「下载全部资源」时，客户端会向站点要没有的文件，得到 404。
  把 `ResUrls` 指向死链也能进游戏，说明客户端对下载失败是容错的。
- `catalog_Android.hash` 用官方原值，依赖客户端本地已有对应 catalog；
  全新安装的机器可能会额外要 catalog 本体（本项目未提供）。

## 来源与免责

补丁内容版权归原作者与游戏厂商所有，仅供个人测试使用。
