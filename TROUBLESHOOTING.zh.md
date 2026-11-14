# 故障排查 · Backlink Prospector

> English: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

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

覆盖：控制台无报错、渠道表 ≥3 行、域名切换换关键词、分析结果无跨领域泄漏、排序与目录树筛选。

## 6. 部署注意

- `data/` 被 `.dockerignore` 排除且在 Fly 上挂载为 volume → **镜像内的 `data/` 不可见**。
  因此随代码发布的领域种子库放在 `seeds/`（进镜像），`data/` 只放运行期数据。
- `profiles.json`、`channels.json`、`seed.json` 必须出现在 Dockerfile 的 `COPY` 列表里，否则会回落到空默认值。
- **`import server` 会启动调度线程**：`server.py` 在模块级构造 `Scheduler`，构造函数默认 `start()`。测试或一次性脚本导入它时，会按真实的 `data/schedule.json` 跑分析、甚至自动补货，写进真实台账。用环境变量 `BP_NO_SCHEDULER=1`（或 `Scheduler(..., autostart=False)`）关掉。自测里已经这么做了。
- **新增 `.py` 模块必须同时改 Dockerfile**（第 6 行是显式清单，不是 `COPY . .`）。症状：本地和 selftest 全绿，`fly deploy` 报
  `smoke checks failed: the app appears to be crashing`，`fly logs` 里是 `ModuleNotFoundError: No module named 'xxx'`——
  机器能起来，是 `import` 在模块级失败。改完 `COPY` 再部署即可（源码树里有文件不代表镜像里有）。

## 7. 自动补货/定时分析线上不跑

| 现象 | 原因与处理 |
|---|---|
| 冷却到点、间隔到点，但什么都没发生 | Fly 是 scale-to-zero：机器睡着就没有调度线程。要么访问页面把它叫醒，要么部署外部唤醒（见 `USAGE.zh.md` 3.15）：`fly secrets set BDL_TRIGGER_TOKEN=...` + GitHub Actions 定时敲 `POST /api/cron/tick` |
| `POST /api/cron/tick` 返回 `503` | 服务端没设 `BDL_TRIGGER_TOKEN`。这是**故意的 fail closed**：公开地址上不加锁就等于任何人都能花你的配额 |
| 返回 `401` / `403` | 请求没带或带错了 `X-BDL-Trigger` 头；注意 fly 上的值和仓库 Actions secret 里的值必须是同一个 |
| GitHub Actions 里 job 一直重试后失败 | `000/502/503/504` 会重试（冷启动），4xx 直接失败——先看返回体里的错误信息，多半是 secret 没配或配错 |
| 定时工作流忽然不再触发 | GitHub 会在仓库 60 天无提交后停用 scheduled workflow；去 Actions 页面手动 dispatch 一次即可恢复 |

## 8. API 突然全部 401 / 403

设了 `BDL_API_TOKEN` 之后，除页面、`/help`、`/api/health` 和 `/api/cron/tick` 外的所有 `/api` 调用都要带 `X-BDL-Token` 头。

| 现象 | 处理 |
|---|---|
| 页面打开后弹「该 API 已开启令牌保护」输入框 | 粘贴 `BDL_API_TOKEN` 的值（存 localStorage，只需一次）；填错就清 `localStorage.bdlToken` 再刷新 |
| 浏览器一直 401 但不弹框 | 弹框只在每页第一次 401 时出现（防循环），刷新一次页面即可再弹 |
| selftest 全线 401 | 加 `--token=<BDL_API_TOKEN>`；本地服务没配该变量则不用加 |
| 健康检查失败、机器被重启 | 不应发生——`/api/health` 永远开放；若出现说明代码版本不对 |
| 想临时关掉鉴权 | `fly secrets unset BDL_API_TOKEN -a backlink-prospector`（重启后回到开放模式） |
