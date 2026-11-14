# 故障排查 · Backlink Prospector

> 历史文档 "CACHE_CLEAR_GUIDE.md" 的前提（"浏览器缓存旧页面"）已被证实**错误**：
> 真正的根因是 `applyLang()` 用 `innerHTML` 覆盖带 `data-i18n` 的元素，把其内部的
> `#chCount` 徽章节点整个销毁，导致 `renderChannels()` 的 null guard 直接 return，
> 渠道表格永远为空。现已修复并加入防回归保护。

## 1. 渠道表格空白

| 现象 | 排查 |
|---|---|
| "线上外链发现渠道 · 轮询执行" 下方无任何渠道行 | 打开 DevTools Console，看是否出现 `[loadChannels] Error:`；再 Network 看 `/api/channels` 是否 200 |
| `/api/channels` 返回 200 且 `channels` 非空，但表格仍空 | 页面脚本是旧版本。服务端已对所有响应下发 `Cache-Control: no-store, no-cache, must-revalidate`，仍不生效时用无痕窗口打开 |

```bash
curl -s "https://backlink-prospector.fly.dev/api/channels?domain=<domain>" | python3 -m json.tool
```

## 2. 切换域名后关键词/竞品没变

系统按「域名档案」工作：`profiles.json` 提供默认档案，界面里改过则写入 `data/profile-<domain>.json`。

```bash
curl -s "https://backlink-prospector.fly.dev/api/profiles?domain=balancebiketoddler.com" | python3 -m json.tool
```

- 若返回 `source: "none"` → 该域名还没有档案，在界面里填一次关键词即自动保存。
- 若界面填了却没生效 → 检查浏览器控制台 `[loadProfile]` 报错。

## 3. 分析结果与域名无关

**任何域名的分析结果都不会再串到别的领域**：种子库按 `domains` 作用域注入，实时发现结果必须命中关键词。

若结果看起来不相关，按顺序查：

1. `data_sources.seed_library.scope` —— 应当显示 `seeds/seed-<domain>.json` 或 `seed.json (domains=<domain>)`。
2. `data_sources.discovery_channels.channels[]` —— `status` 为 `off-topic` 表示该渠道返回的全是无关缓存垃圾（已拒收，不入池）；此时应补充该域名的种子库。
3. 关键词是否填对：`GET /api/profiles?domain=<domain>`。

## 4. 外链池里有垃圾域名

历史数据（相关性闸门失效期间产生）可通过迁移工具清洗，**只隔离不删除**：

```bash
flyctl ssh console -a backlink-prospector \
  -C "sh -c 'python3 tools/migrate_pools.py --domain <domain> --apply --sanitize-legacy'"
```

被剔除的条目写入 `data/store.quarantine-<ts>.json`，可审计、可回滚。

## 5. 端到端自测

```bash
python3 tools/selftest.py http://127.0.0.1:8787/
python3 tools/selftest.py https://backlink-prospector.fly.dev/
```

覆盖：控制台无报错、渠道表 ≥3 行、域名切换换关键词、分析结果无跨领域泄漏。

## 6. 部署注意

- `data/` 被 `.dockerignore` 排除且在 Fly 上挂载为 volume → **镜像内的 `data/` 不可见**。
  因此随代码发布的领域种子库放在 `seeds/`（进镜像），`data/` 只放运行期数据。
- `profiles.json`、`channels.json`、`seed.json` 必须出现在 Dockerfile 的 `COPY` 列表里，否则会回落到空默认值。
