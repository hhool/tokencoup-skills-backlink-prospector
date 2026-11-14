# 使用帮助 · Backlink Prospector 外链目标发现器

面向运营 / 推广人员的实操手册。技术细节见 [README.zh.md](README.zh.md)。

---

## 0. 这是什么

一个帮你为某个网站（**中心域名**，如 `soundbuttons.click`）找**真实、可用外链目标地址**并做**缺口分析**的工具。它有三层数据：

| 名称 | 含义 | 谁来写 |
|---|---|---|
| **外链池（候选）** | 历史上发现过的目标站点，是"见过"的清单 | 每次分析自动并入 |
| **已有外链库** | 你真实已经拿到的外链域名（来自 GSC/Ahrefs 等导入） | 你导入 |
| **投放台账** | 你实际去联系 / 提交 / 上线投放位的逐条记录，是"已交付"唯一事实源 | 你认领与推进 |
| **缺口 (gap)** | 在池里、但既没被导入为已有、也没上线投放的待拓展目标 | 系统算出 |

> 关键认知：**"见过"不等于"已拥有"**。只有导入为已有、或台账里验证上线，才从缺口里扣除。

---

## 1. 启动

```bash
cd backlink-prospector
python3 server.py --port 8787
# 浏览器打开 http://127.0.0.1:8787
```

线上已部署：`https://backlink-prospector.fly.dev/`（生产数据在 Fly 持久卷，本地数据在 `data/`，互不干扰，都**不进 git**）。

右上角有 `中 / EN` 切换，全站一键双语。

---

## 2. 标准工作流（五步闭环）

### 第 1 步 · 选定中心域名 + 关键词
- 顶栏的**中心域名**是可输入下拉：点开能看到本机/线上已知的全部域名，并标注 `池 N · 种子 M · 竞品反链 K`——`.cc` 与 `.click` 这类近似域名一眼可分，不会再落错库。也可直接输入新域名。
- 页面会记住你**上次使用的域名**，刷新后不会跳回默认值。
- **关键词**逗号分隔（如 `soundboard, sound effects, meme sounds`），决定相关性打分。
- 点「从当前表单添加为定时档案」可把这组配置保存，下次切换域名自动带上。
- 不同域名数据**完全隔离**，互不串台。

### 第 2 步 · 分析拿候选（🔍 分析）
- 填好表单后点 **分析**。
- 候选来源：① 该域名的**种子库**（`seeds/seed-<域名>.json`，已随镜像内置、稳定可靠）；② 可选 Bing 实时发现（数据中心出口常被返回无关缓存，会被相关性闸门拒掉，属加分通道）。
- 候选来源：③ **竞品外链站**（`seeds/competitor-links-<域名>.json`，由离线 host 图 harvest 生成）——这类行按「证据」准入，不受关键词门限限制，表格里标 `竞品反链: 域名`。
- **竞品域名本身**（含子域）不算候选、不做 HTTP 校验、不进缺口，只在统计卡下方单独计数（如「竞品 2 个已剔除 · 由竞品外链带来的候选 27 条」）。
- 结果按 **优先级 priority（0–100）= 相关性 + 权威 + 可获取** 排序，可按表头任意列排序、按类型/最低优先级/仅缺口/仅有效筛选。
- 默认 `persist=1`，结果**自动并入外链池**并去重累计。

### 第 3 步 · 看池子、算真缺口（🗃 外链池）
- 统计卡：**累计发现 / 已拥有 / 缺口 / 缺口且有效**。
- 左侧**目录树**按 10 种外链类型组织、可多选筛选；右上角可切「已拥有 / 缺口」状态。
- **导出池 CSV** 按钮下载候选清单。
- 此时若没导入已有外链，所有候选都会被算成缺口（正常中间态）。

### 第 4 步 · 导入已有外链，算出真实缺口
把你在 GSC / Ahrefs / 自建记录里的**真实已有外链域名**（每行一个）贴进「导入已有外链」框，点导入。这些域名被标记 `acquired`，缺口立即重算（例：5 个候选导入 2 个 → 缺口从 5 变 3）。
- 误导入可在同一框用「取消已拥有」撤回，候选不丢。

### 第 5 步 · 把候选变成已交付（投放台账，在外链池面板内）
对每个要动手的目标：
1. **认领 / 批量认领**：把候选"占个位"。支持单条认领，也支持粘贴多行批量认领。
2. 推进状态机：`registered → claimed → submitted → live → lost`（`rejected` / `error` 为终态）。
3. 上线必须给**证据**：填 `landing_url` + `verify_method`（如 `manual_check`），状态才能转为 `live`，该位永久锁定。
4. 不要投的：用「排除」永久剔除该域名或该精确投放位。
5. **导出台账 CSV**（含证据列）交给运营 / 留档。

> 排除规则（每次认领都会重判，命中返回原因）：已上线永久锁、进行中幂等不重复、lost 必须人工复核、rejected/error 冷却 90 天、同域名 90 天内已有 live/submitted 触发节奏窗口、显式排除表永久剔除。

---

## 3. 面板速览

| Tab | 用途 |
|---|---|
| 📊 总体概况 | 统计卡、互链占比监控、各类型分布一览 |
| 🔍 分析 | 跑分析、看候选、排序/筛选、导出分析 CSV |
| 📖 类型说明 & 权重 | 10 类外链定义、价值权重、互链风险提示、打分模型 |
| 🗃 外链池 | 候选池、目录树筛选、导入/取消已有外链、**投放台账**、池 CSV / 台账 CSV |
| ⚙ 后台服务·周期查询 | 开启定时自动跑、配置间隔、管理定时档案、立即运行、看运行历史 |

**界面内帮助（无需翻文档）**
- 每个 Tab 顶部都有 **💡 Tips** 按钮，点一下就地展开该视图的说明（再点收起），不打断操作。
- 顶栏右上角 **? 使用帮助** 打开独立帮助页：本地 `http://127.0.0.1:8787/help`、线上 `https://backlink-prospector.fly.dev/help`。加 `?lang=en` 为英文版；帮助页内也可一键切换语言。
- 帮助页内容分七段：这是什么 / 五步闭环 / 面板地图 / 状态机与规则 / API 速查 / 数据与备份 / 常见问题。

---

## 3.5 竞品外链站怎么来（离线 harvest）

「竞品的外链站」是最高价值的候选来源，但它需要一次离线取数：Web Data Commons / Common Crawl 的 host 图有几十 GB，装不进服务镜像。

```bash
# 1) 从 https://webdatamining.org/ 下载同一 crawl 窗口的 domain-ranks + domain-edges
# 2) 反向查：谁链接到我的竞品（三趟流式扫描，内存只随命中增长）
python3 tools/competitor_backlinks.py \
  --center soundbuttons.click \
  --competitors myinstants.com,voicemod.net \
  --ranks /data/wdc/cc-main-2025-may-aug-domain-ranks.txt.gz \
  --edges /data/wdc/cc-main-2025-may-aug-domain-edges.txt.gz \
  --out   seeds/competitor-links-soundbuttons.click.json
```

- 产出随镜像发布（`seeds/` 进 git），线上直接读；也可放 `data/` 作为本机覆盖（不进 git、线上无）。
- 想要更严格的门槛：`--min-links 3`（至少 3 条链接）；先看结果不落盘：`--dry-run`。
- 已有边表（`source,target[,count]`）时用 `--from-csv` 直接喂，不必下载全图。
- 每行自带证据：`via_competitors[]` + `evidence{graph, edges, per_competitor}`；`type` 是按域名猜的（`type_guess=true`），投放前建议人工复核类型。

> 提醒：竞品越多，被扫描的反链面越大，但「有效外链一定变多」不是恒等式——去重、排除表、质量闸门都会削减净增。

## 3.6 本地模拟（不联网、不下载）

拿真实 WDC 图之前，先用合成图把整条链路跑一遍：合成图里的主机全在保留域 `.example` 下，永远不会被误当成真实候选；分析阶段的 HTTP 探测被替换成模拟响应（约 1/9 不存活），所以 `valid < candidates` 依然可见。

```bash
python3 tools/simulate_harvest.py                 # medium：12 万主机 / 60 万边
python3 tools/simulate_harvest.py --preset big    # 40 万主机 / 200 万边，看耗时与内存
python3 tools/simulate_harvest.py --preset tiny --keep --verbose   # 保留中间文件排查
```

它会做三件事，并逐条断言：

1. 生成 `*-domain-ranks` / `*-domain-edges`（gz，列形状与 WDC 一致，id 打乱）；
2. 按竞品个数 1→2→3 各跑一次 harvest，打印行数、耗时、峰值内存、丢弃原因；
3. 把每份证据文件喂给 `analyze()`，打印 `candidates / valid / competitor_rows / from_competitors`，并检查：竞品主机与其子域不进入候选、证据行无需关键词即被接纳、种子行与证据行同域时「合并而非重复」。

**50 个有效/天够不够？** 供给是有限的：一次 release 只能喂出「文件里的行数」这么多地址，用完就得换新 release 或补别的来源。

| 竞品数 | 一次 release 的有效行（模拟） | 50/天 可撑 |
|---|---|---|
| 1 | ~520 | ~10 天 |
| 2 | ~960 | ~19 天 |
| 3 | ~1400 | ~28 天 |

要让线上稳定出 50 个/天，`--max-rows` 建议 1500 上下（文件约 0.9 MB，随镜像发布没压力），并且把 WDC release 的更新当成例行任务；真实小niche 的竞品链接面通常远小于模拟值，harvest 只能算「一次性补库」，日常缺口还得靠种子库 + 线上发现。

## 3.7 日配额与批次队列（默认 100/天）

「每天 100 个」是**工作配额**，不是产量。总览页多了一条「今日队列」：

| 数字 | 含义 |
|---|---|
| 日配额 | 每天最多交付的条数，**在队列条里直接改**（默认 100，上限 2000，按中心域名分别存） |
| 本批可领 | 今天这一批里还没被领走的条数 |
| 今日已领 | `已领/配额`；已领 = 今天（UTC+8）在台账里新领取的条数，含从池里单条「选用」的 |
| 供给缺口 | `配额 − 本批`，即**库存填不满配额的部分**，旁边有「补候选」按钮 |
| 库存 | 当前池里所有「有效 + 未拥有 + 非竞品 + 未排除 + 无在途投放/冷却 + 不在白名单」的域名 |

规则四条，刻意这样设计：

1. **当天冻结**：第一次打开页面时把队列切成一批并写进 `data/queue-<域名>-<YYYYMMDD>.json`（**按天一个文件**），当天再刷新不会重排。按天分开是关键：一条忘了带 `date` 的 curl 或监控探针只会落到它自己那一天，绝不会把你在用的批次推翻重建；文件保留 14 天自动清理。
2. **领走即出队**：点「领取本批」会把本批剩下的全部写进投放台账（`claimed`），并盖上 `batch_id`；被台账/排除/冷却拦住的会单独计数。
3. **不自动补齐**：库存不够就显示缺口，**不会**用重复域名凑数。补缺口只有两条路：跑一次分析（点「补候选」原地跑），或补一份 harvest 文件（见 3.5）。调小配额也不会删掉已经发给你的那批行；调大配额会自动把当天批次补到新配额（`refill`）。
4. **配额是硬闸门**：不只是统计。超过配额的领取会被服务端直接拒绝（`409 daily quota reached`），从池里单条「选用」也照样被拦——否则「100/天」只是句口号。配额日按 **UTC+8** 结算（`QUOTA_TZ_OFFSET`），北京时间 0 点重置，不是 UTC 0 点。

## 3.8 白名单（不计入外链统计）

池里有些域名你不希望被算进任何数字：自家站群、聚合站、镜像站、已知的目录农场。这类域名的处理方式与「排除」不同——**排除**是"永远别再给我这个投放位"，**白名单**是"这条记录留着，但别算数"。

- 每条记录（外链池行、分析结果行、投放台账行）都有「加入白名单 / 移出白名单」按钮，一键切换。
- 白名单里的域名**仍留在池里**（否则按钮就消失了，无法撤销），但会被踢出：累计发现、已拥有、缺口、缺口且有效、类型分布、互链占比、今日队列。
- 池页顶部有白名单区块：输入框可批量粘贴（`example.com, https://www.foo.com/x` 都能识别，自动去协议/`www`/路径），已加的可点 `×` 移除。
- 对白名单域名发起「领取投放位」会被拒绝（`409 whitelisted`），因为它永远进不了统计，做了也白做。
- 白名单按中心域名隔离，存在 `data/store-<域名>.json` 的 `whitelist` 字段。

接口：

- `GET /api/whitelist?domain=`
- `POST /api/whitelist` body `{center_domain, domains|domain, action:"add"|"remove", note}`
- `POST /api/settings` body `{center_domain, daily_quota}`（1–2000，越界 400）
- `GET /api/queue?domain=&date=YYYY-MM-DD`（`&refill=1` 显式补批；`quota` 参数只影响这一批的行数，**硬闸门始终按配置值**）

`date` 由前端传本地日期，所以「今天」是你所在时区的今天，不是机器所在的 UTC 日。

---

## 3.9 导入已有外链（导出 → 台账 → 缺口报告）

「已拥有」有三个来源：台账里已上线的记录、人工标记、以及**导入的已有外链**。第三条最容易被忽略，也最容易把缺口算错——你已经有 300 条外链，池里却全显示成"缺口"。

粘贴格式很宽松：

```
https://www.reddit.com/r/foo/comments/abc/     # 整条 URL
example.org                                     # 裸域名
Linking page,Anchor,Date                        # CSV 表头（自动跳过）
12,https://listicle.example/best,2026-10-08     # 带前置排名列的 CSV 也行
```

导入做的事（不是"打个标记"）：

- 每一行变成**一条 `live` 台账记录**，`verify_method = import:<来源标签>`，`verified_at` 为空——意思是"有导出为证，但没实地探过"。来源标签写清（`ahrefs-2026-11` / `gsc` / `cc-2026-10`），以后复查时能只挑这类没探过的行先跑。
- 池内域名：缺口立刻减对应条数，`已拥有` 同步增加。
- 池外域名：**不塞进池子**（污染"累计发现"），但照记账，并进入 90 天同域节奏保护——所以不会再花配额去要一个你已经有链接的站。
- **不消耗日配额**：导入是记账，不是今天的工作量。一次粘 500 行也不会把当天的闸门顶死。
- 自动跳过：自身域名（含子域）、竞品、白名单、已排除、重复（同一投放位幂等）。

三个按钮：

| 按钮 | 作用 |
|---|---|
| 预览 | `dry_run`，只报"写入后缺口会变成多少"，一个字节都不落盘 |
| 导入为已拥有 | 真写；报告给出 缺口 X→Y、已拥有 P→Q、池内/池外条数、跳过原因 |
| 撤销这批 | 只删**导入产生**的记录（同域），缺口原样回来；人工标记与真实上线记录不动 |

接口：`POST /api/placements/import`，body `{center_domain, text, source, dry_run?, remove?, own_url?}`。返回里有 `before/after/gap_delta/acquired_delta/skipped/in_pool_sample/out_of_pool_sample`，足够直接贴进周报。

---

## 3.10 存活复查（链接还在吗）

台账里的 `live` 只是一个声明。外链只在"页面还带着它"的那一刻才叫有效，所以每一条 live 记录都要定期回访。默认窗口 7 天（`RECHECK_DAYS`，1–90）。

三种判定，只有两种会改状态：

| 判定 | 依据 | 结果 |
|---|---|---|
| 存活 | 页面 2xx，且页面里**还能找到我们的链接**（绝对 href / 相对 href / 域名） | 不动，只记一次检查 |
| 已失活 | 404 / 410，或页面正常打开但链接不见了 | `state=lost`，域名**退回缺口**，可重新排期（需人工确认后再复用） |
| 未能判定 | 超时、DNS/TLS 失败、403、429、5xx | 只记一次尝试，**绝不删行**——机器人墙和超时不能替你判定"链接没了" |

要点：

- **导入的记录优先**：`verified_at` 为空的（导出导入、从没实地看过）排在最前，它们才是最不确定的那批。
- **不消耗日配额**：复查是核对，不是今天的工作量。
- 每次检查写在记录的 `recheck`（最近一次）与 `checks`（最近 5 次），带 HTTP 状态、判定依据、实际请求到的 URL。
- 定时任务每次跑完分析会顺带复查 20 条（`recheck` / `recheck_limit` 可关或改），所以只要机器醒着，链接失活最迟一周内会被发现。

```bash
# 预览：真去探测，但不写任何东西
curl -s -X POST http://127.0.0.1:8787/api/placements/recheck \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","limit":20,"dry_run":true}'

# 正式复查（limit 1-100，days 1-90，timeout 3-30）
curl -s -X POST http://127.0.0.1:8787/api/placements/recheck \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","limit":20,"days":7}'

# 有多少条到期待检
curl -s "http://127.0.0.1:8787/api/placements?domain=soundbuttons.click" | jq .recheck
```

---

## 3.11 入口发现（投稿表单 / 联系邮箱）

投递环节需要两个池子里没有的值：站点**在哪里**接受投稿，以及**该给谁**发信。这两者都能在不发送任何东西的前提下从外部观测到，所以 `tools/discover_entry.py` 观测一次并写出叠加层。

```bash
# 只看会访问哪些站，不联网
python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json --dry-run --limit 10

# 观测 10 个域名，遵守 robots.txt，结果缓存 30 天
python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json \
    --limit 10 --out data/enrichment-soundbuttons.cc.json

# 长任务续跑，不重复抓已完成的站
python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json \
    --out data/enrichment-soundbuttons.cc.json --resume

# 离线自检
python3 tools/discover_entry.py --selftest
```

爬虫被允许做什么，做不到时又会如何诚实说明：

- **零发送。** 全程只读 GET，先看 robots.txt。
- **带打分的 frontier，不是平铺遍历。** 投稿页通常隔两层（`/help` → `/help/advertise`），所以每个已读页面的链接会重新排队，同一页数预算内始终优先读得分最高的 URL。
- **嵌套路径也算数。** `/help/advertise`、`/about/contact`、`/press-room/media-contacts` 都有分；关键词前允许最多两段前缀。
- **论坛的联系表单就是联系表单。** `username` 字段映射为 name 槽位；只有出现密码字段才算登录表单（XenForo / phpBB 场景）。
- **没找到会说原因。** `no <form> element in N page(s)` 表示表单多半是 JS 渲染的，加大 `--max-pages` 也没用；`the site refuses automated reads (HTTP 403)` 表示这个域名改为人工处理，不要重试。

判定规则与理由：

| 问题 | 规则 |
|---|---|
| 读哪些页？ | 先首页，再按路径词表给同站链接打分（`/submit`、`/guest-post`、`/write-for-us`、`/advertise`、`/contact`），什么都没找到时最多再试 3 个未被链接的常见路径 |
| 算不算投稿表单？ | 必须既能写**文字**（textarea，或 message/subject 字段），又能给出**目标**（url 字段或邮箱）。`email + website` 且没有正文框的是订阅框，直接排除 |
| 搜索 / 登录 / 订阅框？ | 排除：`q`/`search` 表单、含 password 字段、只有单个字段的框 |
| 哪一栏是「你的名字」？ | 字段名有意义就用字段名，否则用 `<label>`。WPForms 写的是 `wpforms[fields][0]`，而标签写着 "Your Name" |
| `shape` 是什么？ | `sha256(方法 + 排序后的语义槽位)`，排除隐藏令牌与蜜罐字段。同一插件的两个站会得到**相同 shape**，一次人工核对可同时服务两站 |
| 选哪个邮箱？ | 先 `mailto:` 与 Cloudflare `data-cfemail`，再正文；同域与角色邮箱优先；`noreply@` 与占位域名丢弃 |
| 什么都没找到？ | 记为「已观测」，并写明读了几页。预算内的落空**不是**否定结论——要加覆盖就调 `--max-pages` |

输出（`data/enrichment-<center>.json`）是叠加层，不改写 store：候选池的事实源仍是 store，叠加层在导出时并入（`bin/delivery export-snapshot --enrichment ...`），作为契约 C 1.1.0 的一部分。

安全：所有请求都是 `GET`。不提交表单、不发信、遵守 robots.txt（被拒次数记在 `pages_blocked`），产生判断的那份 HTML 保留在 `data/cache/` 可复查。

## 3.12 变化对比（这次跑完，池子到底多了什么）

只盯着「累计发现 55」这个数字是看不出东西的：它分不清今天多出来的 3 个是新域名，还是昨天那 3 个又被看见了一次。所以每次持久化运行都会留一份**快照**，相邻两次快照的差异就是答案。

快照里存什么：域名列表、无效域名列表、总量/有效/已拥有。保留最近 10 次；超过 2 万个域名时只存总量（此时明确返回「只能对比总量」，不会编一个名字差异出来）。

对比结果四行：

| 字段 | 含义 |
|---|---|
| `added` / `added_count` | 这次新出现的域名（上一份快照里没有） |
| `removed` / `removed_count` | 上一份有、这次池子里没有的域名 |
| `newly_invalid` | 两次都在池里，但这次验证失败（站点挂了 / 反爬 / 404） |
| `recovered` | 上次无效、这次恢复有效 |

```bash
# 最近两次运行的变化
curl -s "http://127.0.0.1:8787/api/runs/diff?domain=soundbuttons.click" | jq .diff

# 跟 3 次之前那次比（back= 范围 1..9）
curl -s "http://127.0.0.1:8787/api/runs/diff?domain=soundbuttons.click&back=3" | jq '.diff.added_count'
```

概览页底部那条虚线框就是它：`上次分析变化 · 新增 N · 转为无效 N · 恢复有效 N · 池总量 N`，后面跟几个新域名示例。`/api/analyze` 的返回里也带 `run_diff`，跑完立刻能看到这次运行贡献了什么。

---

## 3.13 自动补货（库存见底时自己去进货）

队列是「今天干多少」，池子是「柜子里还有多少」。柜子空了，冻结的 100 条也只是个数字。所以除了手动「补候选」，后台还会自己补：

- **触发条件**：可领候选数（`inventory`，即未被领取、未拥有、未排除、验证有效的池内域名）低于 `REFILL_THRESHOLD`（默认 30）。
- **动作**：用该域名保存的档案（关键词/竞品）跑一次完整分析，结果直接并入池子。
- **冷却**：默认 6 小时（`REFILL_COOLDOWN_H`）。冷却记录写在 store 里，重启不会重置。
- **无进展退避**：如果上次补货一个候选都没加，冷却翻倍（6h → 12h → 24h → 48h，上限 8 倍）；一次有产出的补货立刻恢复 6 小时。免费数据源本来就容易饱和，空跑一次就够了，不该每 6 小时去敲别人服务器。

| 开关 | 位置 | 说明 |
|---|---|---|
| `auto_refill` | `data/schedule.json` / `POST /api/schedule` | 默认 `true`；关掉就只保留手动「补候选」 |
| `REFILL_THRESHOLD` | 环境变量 | 库存低水位，默认 30 |
| `REFILL_COOLDOWN_H` | 环境变量 | 基础冷却小时数，默认 6 |

```bash
# 手动立即补一次（用已保存的档案；没有档案会 400 并告诉你先去存关键词）
curl -s -X POST http://127.0.0.1:8787/api/refill \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click"}' | jq '{inventory_before,inventory_after,added}'

# 库存/冷却/退避状态
curl -s "http://127.0.0.1:8787/api/store?domain=soundbuttons.click" | jq .refill
```

概览页队列条上的「补货」小格显示当前状态：`就绪`（可以补）、`12h`（冷却中）、`充足`（库存够）。

---

## 3.14 失活待办（链接死了得有人知道）

存活复查会把失活的记录标成 `lost` 并把域名退回缺口——但如果没人看，这个结果就只躺在台账里。所以概览页顶部有一条红色待办条，**只在近 7 天有失活时出现**：

- 显示条数与域名（前 5 个）；
- 「去台账处理」直接跳到台账，那里能看到 `已失活` 药丸和复查证据（HTTP 状态、判定依据）；
- 窗口由 `LOST_WINDOW_DAYS` 控制（默认 7，1–90）。

失活之后域名回到缺口，同域 90 天节奏解除需要人工确认（`lost → submitted` 状态机已允许），所以这条待办本质上是「该重新谈一次了」的清单。

---

## 3.15 外部唤醒（机器睡着也要每天醒一次）

线上是 scale-to-zero：空闲就把机器停掉，进程结束，调度器线程跟着消失——**没有线程就没人 tick**。所以「冷却到点自动补货」「间隔到点自动跑分析」在线上只会在有人访问页面时碰运气。

`POST /api/cron/tick` 补上这一环：外部定时器把服务叫醒，接口做**恰好一次**它本来该在第一圈循环里做的事——库存低就先补货，到点就跑档案。它不会因为被叫醒就多跑一次：返回里的 `ran` 来自 `last_run` 是否真的变了，两次并发只有一个会报 `true`。`force` 参数存在于调度器层（测试用），HTTP 接口刻意不暴露——想立刻跑一遍请用 `/api/schedule/run`。

它花的是真实配额，部署地址又是公开的，所以**默认是关着的**（fail closed）：

| 情况 | 结果 |
|---|---|
| 服务端没设 `BDL_TRIGGER_TOKEN` | `503`，并告诉你该怎么设 |
| 请求没带令牌 | `401` |
| 令牌不对 | `403` |
| 令牌正确 | `200` + `{ran, refill, last_run, next_run}` |

```bash
# 一次性设置（值用新的随机串）
fly secrets set BDL_TRIGGER_TOKEN=$(openssl rand -hex 24) -a backlink-prospector

# 手动叫醒一次
curl -s -X POST https://backlink-prospector.fly.dev/api/cron/tick \
  -H "X-BDL-Trigger: $BDL_TRIGGER_TOKEN" \
  -H 'Content-Type: application/json' -d '{}' | jq '{ran,refill,next_run}'
```

仓库自带 `.github/workflows/tick.yml`：每天两次（09:17 / 23:17 Asia/Shanghai，UTC `17 1,15 * * *`）敲一次这个接口，也能在 Actions 页面手动 dispatch。敲两次而不是一次是刻意的：手动跑过分析会往后挪 `last_run`，固定时刻可能落在「还没到点」的那一侧；tick 自己判断到没到点，多敲不重复跑。要让它跑起来只差一步——**把同一个值存进仓库的 Actions secret `BDL_TRIGGER_TOKEN`**（Settings → Secrets and variables → Actions）。地址不是默认域名时再加一个仓库变量 `BDL_BASE_URL`。

两个运维注意点：GitHub 的定时工作流在仓库 60 天无提交后会自动停用（手动 dispatch 一次即可恢复）；冷启动要几秒，工作流里对 `000/502/503/504` 会重试 5 次，而 4xx 直接失败——因为令牌错了等多久都没用。

---

## 4. 命令行 / API 速查（批量与自动化用）

下列可直接 curl 调用（本地 `8787` 或线上域名）。

**分析**
```bash
curl -s -X POST http://127.0.0.1:8787/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","keywords":"soundboard, sound effects",
       "competitors":"","use_bing":"0","use_tranco":"1","persist":"1"}'
```

**导入已有外链（标记 acquired，重算缺口）**
```bash
curl -s -X POST http://127.0.0.1:8787/api/store/sync-existing \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","domains":"reddit.com\nnews.ycombinator.com"}'
```

**撤回已有外链（变回 gap）**
```bash
curl -s -X POST http://127.0.0.1:8787/api/store/unmark-existing \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","domains":"reddit.com"}'
```

**批量认领投放位**
```bash
curl -s -X POST http://127.0.0.1:8787/api/placements/claim-batch \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","items":[
        {"target_domain":"a.com","target_url":"https://a.com/post","placement_type":"guest_post"},
        {"target_domain":"b.com","target_url":"https://b.com/page","placement_type":"resource"}
      ]}'
```

**推进某条到上线（需证据）**
```bash
curl -s -X POST http://127.0.0.1:8787/api/placements/transition \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","id":"<记录id>","state":"live",
       "landing_url":"https://a.com/post","verify_method":"manual_check"}'
```

**导出 CSV / 看台账**
```bash
curl -s "http://127.0.0.1:8787/api/store/csv?domain=soundbuttons.click" -o pool.csv
curl -s "http://127.0.0.1:8787/api/placements/csv?domain=soundbuttons.click" -o ledger.csv
curl -s "http://127.0.0.1:8787/api/placements?domain=soundbuttons.click"
```

---

## 5. 数据与备份

- 每个域名一份存储：`data/store-<中心域名>.json`（含候选 `domains`、已有 `acquired_domains`、台账 `placements`、排除 `suppressions`）。
- 调度配置：`data/schedule.json`；运行历史：`data/schedule_runs.json`；渠道开关：`data/channels-<域名>.json`。
- 这些都**不进 git**（`data/` 被忽略）。本地与线上（Fly 卷）各自独立。
- **种子库** `seeds/seed-<域名>.json` **进 git 并随镜像烘焙**，是受控输入，改它需提交。
- 备份：直接复制 `data/` 整个目录即可。

---

## 6. 常见问题

**Q：分析按钮点了没结果？**
A：九成是没种子库或 Bing 被挡。先看 🗃 外链池里统计卡是不是 0；若为 0，说明该域名没有 `seeds/seed-<域名>.json`，需在 `seeds/` 下新建（每行一个候选，含 `url/type/tags/domains/note`）。线上 Bing 出口常被挡，属正常，种子库是主通道。

**Q：为什么所有候选都显示"缺口"？**
A：因为你还没导入已有外链库。导入后（第 4 步）缺口才会缩小。

**Q：导入错了能撤销吗？**
A：能。用「取消已拥有」或 `/api/store/unmark-existing`，候选不丢。

**Q：台账里 "live" 一直加不上？**
A：进入 `live` 必须同时提供 `landing_url` 和 `verify_method` 证据，仅"点了提交"不算。

**Q：不同网站的数据会混吗？**
A：不会。每个中心域名有独立存储与种子作用域，切换域名自动隔离。

**Q：定时任务会不会一直跑？**
A：调度器是服务器进程内的守护线程，服务器停就停。要 7×24 常驻，把启动命令放进 systemd / pm2 / nohup。
