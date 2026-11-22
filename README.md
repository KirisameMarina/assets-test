# assets-test

自用测试项目：把一个游戏的补丁包重新整理成客户端能按固定路径拉取的静态资源目录，
顺便提供一个局域网分发脚本。纯自用，不保证任何东西，随时可能弃坑。

## 它做的事

游戏客户端在 `Android/data/<包名>/files/` 下有一个 `LocalizeConfig.txt`：

```
Env=dev
IsLocalize=false
ResUrls=<资源根>;<资源根>;<资源根>
```

客户端按固定路径向 `ResUrls` 请求文件：

| 用途 | 路径 |
| --- | --- |
| 资源清单 | `<ResUrls>/AssetBundles/Catalog/<ResourceVersion>/Android/bundleDownloadInfo.json` |
| 资源包 | `<ResUrls>/AssetBundles/Android/<Name>` |

清单里每个文件带 `Crc`（文件 MD5）与 `Size`，客户端拿它跟本机 `manifest.db`
（SQLite，`文件名 → MD5`）比对，**只下载 CRC 不一致的文件**。

所以只需要两样东西：一份把补丁文件 `Crc` / `Size` 替换掉的清单，和这些补丁文件本身。

`sync_mirror.py` 会把它们整理成：

```
public/
├─ .nojekyll
├─ robots.txt
└─ prodm39/
   └─ AssetBundles/
      ├─ Catalog/<ResourceVersion>/Android/bundleDownloadInfo.json
      └─ Android/<Name>.bundle
```

## 两条取数据的路

| 模式 | 版本号来源 | 官方清单来源 | 适用场景 |
| --- | --- | --- | --- |
| `--catalog-source official`（默认） | 官方接口 | 官方 CDN | 本机在国内运行时 |
| `--catalog-source upstream` | 上游仓库 `current.txt` | 上游仓库 `manifest/` | GitHub Actions（境外访问不了国内 CDN） |

`upstream` 模式带 jsDelivr 回退，国内直连 `raw.githubusercontent.com` 被重置时也能用。

## 用法

```bash
# 本机直接构建
python scripts/sync_mirror.py --base-url https://<user>.github.io/<repo>

# 只依赖 GitHub，境外/CI 也能跑
python scripts/sync_mirror.py --catalog-source upstream --base-url https://<user>.github.io/<repo>

# 用本地已下载的 zip，省一次下载
python scripts/sync_mirror.py --zip downloads/patch.zip --catalog-source upstream --base-url ...
```

### 局域网分发

```bash
python scripts/serve.py            # 起 HTTP 服务，自动探测本机 IP 并打印配置
python scripts/serve.py --adb      # 顺手用 adb 把 LocalizeConfig.txt 推到手机
```

手机与电脑连同一个 WiFi，把打印出来的 `LocalizeConfig.txt` 放进
`/storage/emulated/0/Android/data/<包名>/files/`，重启游戏。

部分机型隐藏了 `Android/data`，需要 Shizuku + MT 管理器，或直接用 `--adb`。

## 边界

- **不做全量镜像**：官方资源好几 GB，这里只保留被改过的几十个文件。
- **客户端会请求本地没有的文件**：换机、清资源、点「下载全部资源」时会拿到 404。
  把 `ResUrls` 指向死链也能进游戏，说明客户端对下载失败是容错的，但没在所有版本上验证。
- **每次游戏更新都要重跑**：官方 `ResourceVersion` 一变，旧清单路径就 404。

## 来源与免责

补丁内容版权归原作者与游戏厂商所有。本项目仅作个人测试使用，不提供担保。
