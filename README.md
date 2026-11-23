# assets-test

静态资源目录同步，自用。

## 站点结构

```
public/prodm39/
├─ Manifest/
│  ├─ TableBundles/<TableVersion>/{TableManifestHash,TableManifest}
│  └─ MediaResources/<MediaVersion>/{MediaManifestHash,MediaManifest}
└─ AssetBundles/
   ├─ Catalog/<ResourceVersion>/Android/
   │  ├─ bundleDownloadInfo.hash
   │  ├─ bundleDownloadInfo.json
   │  └─ catalog_Android.hash
   └─ Android/<Name>.bundle
```

## 客户端配置

`Android/data/<包名>/files/LocalizeConfig.txt`：

```
Env=dev
IsLocalize=false
ResUrls=<源1>;<源2>;<源3>
```

三个源分号分隔，前两个是不同加速服务，第三个是第一个的重复。

## 更新

Actions 手动跑 `Build & Publish`，或等定时任务（每 12 小时，版本没变自动跳过）。
构建成功后强制推送 `assets` 分支，客户端下次启动自己拉新。

本机构建：

```bash
python scripts/sync_mirror.py \
  --base-url "https://ghfast.top/raw.githubusercontent.com/<user>/<repo>/assets,https://gh-proxy.com/https://raw.githubusercontent.com/<user>/<repo>/assets" \
  --catalog-source upstream
```

### 替换字体

加 `--font` 即可，支持两种输入：

```bash
# MiSans 官方完整包（按字重自动映射）
python scripts/sync_mirror.py --font MiSans.zip --base-url ... --catalog-source upstream

# 单个字体文件（所有字重都用它，会丢失粗细层次）
python scripts/sync_mirror.py --font my-font.ttf --base-url ... --catalog-source upstream
```

游戏字体包里 6 个动态字体的映射关系：

| 游戏字体 | MiSans 字重 |
| --- | --- |
| U-OTF-ShinMGoUpr-DeBold | Demibold |
| U-OTF-ShinMGoUpr-Medium | Medium |
| MALGUN | Regular |
| MALGUNBD | Bold |
| MALGUNSL | Light |
| CCG_LINESeedKR_Bd | Semibold |

> 需要 `pip install UnityPy`。字体文件不随仓库分发（MiSans 协议禁止单独再分发字体文件）。

## 排查

系统连不上资源根时，用 `scripts/diag_server.py` 把 `ResUrls` 指到本机，看它到底请求哪个路径。

## 说明

资源来自第三方公开工程，版权归原作者与厂商所有，仅供个人测试。
