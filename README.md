# assets-test

静态资源目录同步。

## 目录结构

```
public/
├─ .nojekyll
├─ robots.txt
└─ prodm39/
   └─ AssetBundles/
      ├─ Catalog/<ResourceVersion>/Android/bundleDownloadInfo.json
      └─ Android/<Name>.bundle
```

清单里每个条目带 `Crc`（文件 MD5）与 `Size`，客户端的下载路径是固定的：

| 用途 | 路径 |
| --- | --- |
| 清单 | `<ResUrls>/AssetBundles/Catalog/<ResourceVersion>/Android/bundleDownloadInfo.json` |
| 资源包 | `<ResUrls>/AssetBundles/Android/<Name>` |

## 客户端配置

`LocalizeConfig.txt` 放到 `Android/data/<包名>/files/`：

```
Env=dev
IsLocalize=false
ResUrls=https://kirisamemarina.github.io/assets-test/prodm39;https://kirisamemarina.github.io/assets-test/prodm39;https://kirisamemarina.github.io/assets-test/prodm39
```

## 更新

Actions 里手动跑 `Build & Deploy`，或等定时任务（每 12 小时，版本没变会自动跳过）。

本机构建：

```bash
python scripts/sync_mirror.py --base-url https://kirisamemarina.github.io/assets-test
```

## 说明

资源来自第三方公开工程，版权归原作者与厂商所有，仅供个人测试使用，不提供担保。
