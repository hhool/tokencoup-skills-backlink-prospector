# Backlink Prospector · 外链目标发现器

为某一域名查找**真实、有效**的可用外链目标地址，并做**外链缺口分析**。
后台服务 + CSV 输出 + 前端展现。零第三方依赖（纯 Python 标准库）。
License: [MIT](LICENSE) · English docs: [README.md](README.md)

> 本工具在架构与契约上**参考 `seo-page-snapshot`**：仅用免费 / 开放数据源、商业指标（DR/DA）**绝不估算**、双语字段、缺数据即标 `unavailable`。

---

## 1. 三大模块（对应需求）

| 需求 | 实现 |
|---|---|
| **1. 外链地址类型** | 10 类（含 `reciprocal` 已与 `directory` 分离）：`industry_media` 行业媒体/测评站、`guest` 客座博客、`resource` 资源页/链接列表、`directory` 目录（单向收录）、`community` 社区/论坛、`social` 社媒、`partner` 互补品牌、`authority` 安全/权威机构(.gov/.org)、`digital_pr` 数字 PR、`reciprocal` 互链（双向交换，独立类型）。定义见 `analyze.py` 中 `TYPE_LABEL_ZH/EN` 与 `seed.json` 的 `type` 字段。 |
| **2. 优先级筛选标准** | 每条目标打分：`relevance`(0–40) + `authority_score`(0–30) + `obtainability`(0–30) = `priority`(0–100)。权威层级 `authorityTier` 来自种子标注 + 免费 Tranco 排名信号。前端支持按类型、最低优先级、仅缺口、仅有效筛选。 |
| **3. 外链缺口分析** | 候选 = 种子库（真实站点）+ 可选 Bing 实时发现。导入已有外链（GSC/Ahrefs 导出）后，标记 `already_have=true`，未拥有且非竞品者即 `is_gap`（缺口）。竞品域名输入后自动排除。 |

---

## 1.5 功能需求汇总（类型 / 权重 / 互链 / 打分 / 周期查询）

### A. 外链地址类型（10 类，定义于 `analyze.py` + `seed.json`）

| 类型 key | 中文 | 价值权重 | 可获取分(0–30) | 说明 |
|---|---|---|---|---|
| `authority` | 安全/权威机构(.gov/.org) | 信任最高 | 8 | 音乐/音频行业组织、.gov/.org 指南；极难获取但信任权重最高 |
| `industry_media` | 行业媒体/测评站 | 最高 | 12 | Mashable/TechRadar 同类测评站，正文内链权重高、相关性强 |
| `digital_pr` | 数字PR/新闻源 | 极高(若被引) | 10 | 经 HARO/记者求助提供专家观点换媒体/.edu 外链 |
| `guest` | 客座博客(Guest Post) | 高 | 22 | 音频/音乐制作博客正文或作者 bio，可控、可规模化 |
| `resource` | 资源页/链接列表 | 高(性价比好) | 26 | curated "best resources" 页面天然收录外链 |
| `partner` | 互补品牌/合作站 | 中高 | 18 | 非竞品盟友（音乐设备/直播工具/母带平台）互换或协同 |
| `directory` | 目录/导航站（**单向收录**） | 单链接偏低 | **28(最易)** | 多为低质/群发，单链价值低；与互链已分开统计 |
| `community` | 社区/论坛/问答 | 品牌/引流 | 20 | 音频/制作论坛（head-fi/vi-control），多 nofollow，重流量与品牌 |
| `social` | 社媒资料页 | 品牌 | 16 | Pinterest(儿童品类重镇)/Instagram/YouTube 简介 |
| `reciprocal` | **互链（双向交换）· 独立类型** | **最低** | **29(最易)** | 与对方互相挂链；铺量兜底、非主力权重来源；必须控比例（见 B） |

> **`directory` 与 `reciprocal` 已明确分开**：`directory` = 被目录单向收录；`reciprocal` = 与对方双向互链。两者在缺口分析与外链池里分别统计。

### B. 互链（reciprocal）说明 —— 现已是第 10 种独立类型

- 互链（你链我、我链你）与 `directory`（单向收录）**分开统计**：前者是你与对方互相挂链的双向关系，后者是你被目录收录的单向链接。
- 互链可获取性最高（29/30）、单条 SEO 价值最低，仅作「铺量兜底」、非主力权重来源。
- ⚠️ Google 将「以操纵 PageRank 为目的的互链」列为 **link scheme**，会降权甚至判违规。
- **必须控比例**：外链池中互链占比超过 `RECIPROCAL_RATIO_WARN = 0.30`（30%）即触发告警（前端概况页「互链占比监控」实时显示）。
- 实践：**仅与有编辑标准的垂直站点 / 互补品牌**互链，比例自然，不大规模互链。

### C. 优先级打分模型（0–100）

```
priority = relevance(0–40) + authority(0–30) + obtainability(0–30)
```
- `relevance`：命中关键词 +8/个（上限40）；无关键词时按类型基线（如 resource 26、directory 28、social 18）。
- `authority`：`High`=30 / `Medium`=20 / `Low`=10（种子标注 + 免费 Tranco 排名信号）。
- `obtainability`：上表可获取分；URL 命中 `write for us/contribute/guest/submit` 再 +4。
- 商业 DR/DA **从不估算**，缺失即标 `unavailable`。
- `reciprocal` 类型额外施加 `RECIPROCAL_PRIORITY_PENALTY = 12` 的排序惩罚，使其在结果中明确处于「铺量兜底」位（单条价值最低）。

### D. 周期查询 + 已有/空缺查询（外链池）

- 每次分析**自动并入「外链池」**（默认 `persist=1`）：按域名去重，累计 `times_discovered`、首见/末见时间、最佳校验状态与最新优先级。
- 重复运行不断**扩充外链地址列表**。
- 导入真实已有外链（GSC / Ahrefs / 自建 Common Crawl 导出，每行一个域名）→ 标记 `acquired`（已拥有）；池中其余即**空缺(gap)**待拓展。
- 前端「外链池」面板展示：累计发现 / 已拥有 / 空缺 / 空缺且有效 统计卡、按类型分布、可导出池 CSV。

### D2. 后台服务 · 周期查询（前端可配置）

通过前端「后台服务 · 周期查询」面板即可配置，无需改代码：

- **启用开关**：开启后，守护线程按设定间隔自动对「定时档案」逐个执行分析，结果并入外链池（去重、累计）。
- **间隔（小时）**：0.05–8760 小时（即约 3 分钟到 1 年），保存即生效。
- **定时档案 Profiles**：可保存多个待周期查询的目标（每个含 名称/域名/关键词/Bing/Tranco 开关）。点「从当前表单添加为定时档案」即可把顶部表单的域名+关键词一键存入；也可在面板内直接编辑/删除。
- **立即运行**：无视定时器，立刻跑一遍所有档案（用于测试或补跑）。
- **状态与历史**：面板实时显示 启用/运行中/上次运行/下次运行/最近错误，并列出最近 15 条运行记录（时间、域名、成功/失败、候选数、池总数、错误明细）。
- **持久化**：配置存于 `data/schedule.json`，运行历史存于 `data/schedule_runs.json`（最近 50 条）。

> 实现：`scheduler.py`（纯 stdlib 守护线程，30s 轮询、到点执行、原子写盘）；`server.py` 启动时自动加载并运行。配置经 `POST /api/schedule` 校验后落盘（非法档案自动过滤、间隔越界自动钳制）。

### D3. 多域名中心架构（档案 · 种子作用域 · 相关性闸门）

系统所有 Tab 都以「中心域名」为中心；不同域名之间**数据完全隔离**，互不污染：

| 机制 | 存储位置 | 作用 |
|---|---|---|
| **域名档案 profile** | `profiles.json`（默认） + `data/profile-<domain>.json`（编辑后覆盖） | 每个域名一组 `keywords` / `competitors`。切换中心域名时：先把当前表单回写到**旧域名**档案，再载入**新域名**档案 → 关键词、竞品随域名自动切换。 |
| **外链池隔离** | `data/store-<domain>.json` | 每个域名一份外链池，统计与 CSV 互不串台。⚠️ `server.py::run_analysis` 必须从 `params["center_domain"]` 回退解析域名：调度器以 `run_fn(params)` 形式调用（不传位置参数），否则定时任务会把结果写进遗留共享池 `data/store.json`，造成两个垂直领域混池。 |
| **渠道隔离** | `data/channels-<domain>.json` | 每个域名可单独启用/停用发现渠道。 |
| **种子库作用域** | `seed.json` 的 `domains` 字段 + `seeds/seed-<domain>.json` | 种子行**按域名作用域注入**：只注入 `domains` 含当前域名的行（或该域名的独立种子文件）。一个垂直领域的种子绝不会泄漏到另一个领域。 |
| **相关性闸门** | `analyze.py::run_channel` | 实时发现的结果**必须在 URL 中命中关键词**（归一化后比较，`balance bike` 能匹配 `forbalancebikes.com`）才被采纳；旧实现同时接受"关键词出现在查询里"，而查询本就是关键词拼出来的，等于闸门失效，污染池子。 |
| **通道健康度** | `data_sources.discovery_channels.channels[].status` | 渠道状态区分 `ok` / `empty` / **`off-topic`**（返回了结果但全部不相关）/ `error`。面板显示 `✓ 命中数/原始数`。 |
| **黑名单** | `analyze.py::BLOCKED_DOMAINS` | 成人 / 博彩 / 广告跳转类域名永不进入候选（支持子域匹配）。 |

```bash
# 为新域名建立档案（编辑 profiles.json 或在界面里改完关键词后自动保存）
# 维护已验证的域名专属种子库
seeds/seed-<domain>.json
# 清洗历史池：把遗留池里不属于本域名的条目迁移/隔离
python3 tools/migrate_pools.py --domain <domain> --apply --sanitize-legacy
# 端到端自测（真实 Chrome：渠道表渲染 / 域名切换换词 / 结果不串域名 / 全站列表排序）
python3 tools/selftest.py https://backlink-prospector.fly.dev/
```

> `tools/migrate_pools.py` 只**迁移**与**隔离**（写入 `data/store.quarantine-<ts>.json` 存档），不静默删除任何数据。

### D4. 全站列表可排序（统一排序引擎）

前端**所有列表**都支持点击表头排序，由一套共用引擎（`SORT_TABLES` 注册表 + `sortRows()` 通用比较器）驱动：

| 页面 | 列表 | 可排序列 |
|---|---|---|
| 分析 | 分析结果表 | 域名 / 类型 / 权威(Tranco 排名) / 相关 / 权威分 / 可获取 / 优先级 / 校验 / 缺口 / 备注 |
| 类型说明 | 类型权重表 | 类型 / 价值权重 / 可获取分 |
| 外链池 | 外链池主表 | 域名 / 类型 / 权威 / 优先级 / 校验 / 状态 / 发现次数 / 首见·末见 |
| 外链池 | 按类型分布表 | 类型 / 发现 / 已拥有 / 空缺 |
| 后台服务 | 发现渠道表 | 渠道 / 类型 / 状态 / 建议间隔 / 本次结果 |
| 后台服务 | 运行历史表 | 时间 / 域名 / 结果 / 候选数 / 外链池 |

实现要点：

- **排序状态存在注册表里，不存在 DOM 里** → 重新加载数据、切换域名、切换语言、改变筛选条件后排序状态与表头箭头都保持不变。
- 字符串列用 `localeCompare(..., {numeric:true})`（`a10` 排在 `a9` 之后），数值/布尔列直接比较，缺失值排在最后。
- 点击同一列 = 正/反序切换；点击新列 = 该列的默认方向（域名/类型升序，分数/计数降序）。
- 表头带 `aria-sort` 与 `⇅` 悬停提示；「价值权重」这类文本标签会被映射成数值排名后再排序。

### D5. 外链池目录树 · 类型多选 · 状态筛选

外链池页面内置**目录树**，把外链按「类型」组织成树，同时充当筛选器：

```
▾ 全部站点                      44  0  42
  ▾ 内容与评测                  12  0  12
    • 行业媒体                   5  0   5
    • 客座博客                   3  0   3
    • 数字PR                     0  0   0
    • 资源页                     4  0   4
  ▾ 权威与社区                   4  0   4
  ▾ 商业与伙伴                   5  0   5
  ▾ 互链（独立类型）             3  0   3   ← 互链是独立类型，不并入 directory
```

- **目录树**：根节点「全部站点」+ 4 个类型分组 + 10 个类型叶子；每个节点显示 `总数 / 已拥有 / 缺口` 三个计数。
- **类型可多选**：点击类型节点切换选中（可多选），点击分组节点整组选中/取消，点击「全部站点」清空。右侧「类型筛选」胶囊与树状态实时同步。
- **状态筛选**：`已拥有 Acquired` / `缺口 Gap` 两个开关，可单独或组合过滤；两者都关闭时显示全部。
- **分面计数**：节点计数跟随状态筛选变化，但**不**受类型筛选自身影响（标准分面行为），因此计数始终等于「点下去会看到多少行」。
- **完整分类法常驻**：即使某个类型当前 0 条（如互链）也照样显示（置灰），便于确认「该类型尚未收集到条目」。
- 筛选只影响**展示**，不修改池数据；「标记已拥有 / 取消已拥有」仍在表格「编辑」列。

---

## 2. 免费数据源（无 API Key 即可运行）

| 源 | 作用 | 备注 |
|---|---|---|
| **seed_library** | 真实外链目标种子库（手动核验站点，**按中心域名作用域注入**） | 主通道；`seed.json` 的 `domains` 字段 + `seeds/seed-<domain>.json`；分析时逐条 HTTP 存活校验 |
| **bing_rss / bing_cite / ddg_html** | 按关键词×类型实时检索外链目标 | 免费无 Key；**结果必须命中关键词才采纳**；渠道状态区分 `ok`/`off-topic`/`empty`/`error` |
| **tranco** | 免费流行度排名，作为权威信号 | `tranco_global_rank` 字段；商业 DR/DA 标 `unavailable` |
| **local_backlinks** | 导入已有外链做**真缺口差分** | 粘贴 GSC/Ahrefs/自建 Common Crawl 导出，零网络 |

> 免费实时搜索在各网络出口表现差异极大：数据中心 IP 常被 Bing/DuckDuckGo 返回**与查询无关的缓存垃圾**。因此闸门改为"关键词必须出现在结果 URL 中"，垃圾一律拒收并标记为 `off-topic`，**不再进入外链池**；此时以域名作用域种子库为准。种子库是稳定、真实、有效的主通道，实时搜索为加分通道。

---

## 3. 运行

```bash
cd backlink-prospector
python3 server.py --port 8787
# 浏览器打开 http://127.0.0.1:8787
```

- `POST /api/analyze` → JSON（含 `prospects[]`、`totals`、`data_sources`、`limitations`；`persist=1` 时附 `pool_merged`/`pool_stats`）
- `POST /api/analyze/csv` → CSV 附件下载
- `GET  /api/tips` → 类型/权重/互链/打分/周期查询 双语说明
- `GET  /api/store` → 外链池 + 统计（累计发现 / 已拥有 / 空缺 / 空缺且有效）
- `GET  /api/store/csv` → 外链池 CSV 附件
- `POST /api/store/sync-existing` → 导入已有外链（body `{domains}`）标记 `acquired`
- `GET  /api/profiles?domain=<domain>` → 该域名的关键词/竞品档案
- `POST /api/profiles` → 保存档案（body `{center_domain, keywords, competitors}`）
- `GET  /api/schedule` → 周期查询调度状态（config / status / runs）
- `POST /api/schedule` → 保存调度配置（body `{enabled, interval_hours, profiles[]}`）
- `POST /api/schedule/run` → 立即执行所有定时档案（body `{}`）
- `GET  /api/health` · `GET /api/providers`

请求体（`/api/analyze`）：
```json
{
  "domain": "soundbuttons.cc",
  "center_domain": "soundbuttons.cc",
  "keywords": "soundboard, sound buttons, sound effects, meme soundboard, funny sounds",
  "competitors": "twowheelingtots.com\nrascalrides.com",
  "existing": "已拥有的外链域名，每行一个（用于本次真缺口差分）",
  "use_bing": "1", "use_tranco": "1", "persist": "1"
}
```

> `center_domain` 决定数据落在哪个域名的池子里；`keywords` 留空时自动回退到该域名的档案关键词。

---

## 4. CSV 字段

**分析 CSV（`/api/analyze/csv`）**：
`url, domain, type_key, type_label_zh, type_label_en, authority_tier, relevance, authority_score, obtainability, priority, valid, http_status, is_gap, is_competitor, already_have, tranco_global_rank, source, note`

- `valid`：分析时真实 HTTP 存活校验结果（`true`=可达；403/401/429 视为页面存在但拒爬；404/超时视为失效）。
- `source`：`seed`（种子库）或 `bing_discovery`（实时发现）。

**外链池 CSV（`/api/store/csv`）**：
`domain, url, type_key, type_label_zh, authority_tier, tranco_global_rank, priority, valid, http_status, acquired, is_gap, times_discovered, first_seen, last_seen`

- `acquired`：是否已导入为真实已有外链（`true`=已拥有）。
- `is_gap`：是否仍为空缺（`acquired` 为 `false`）。

---

## 5. 诚实声明 / 局限

- 商业指标（DR/DA、外链条数）**从不估算**，缺失即标 `unavailable`。
- 缺口分析基于**导入的已有外链**；若不导入，所有非竞品候选均视为待拓展缺口。
- 实时发现为 best-effort：某些出口 IP 会被搜索引擎返回**与查询无关的缓存结果**，这些结果已被相关性闸门拒收（渠道状态显示 `off-topic`），**不会进入外链池**；此时结果以该域名的作用域种子库为准。
- 扩展候选：新增该域名的种子行（`seed.json` 填 `domains`）或建 `seeds/seed-<domain>.json`；或在 `providers.json` 启用更多免费 provider（如自建 Common Crawl web-graph 服务接入 `local_backlinks`）。
- 周期查询调度器是**单进程内守护线程**：服务器停止则定时任务随之停止（属单主机开发工具，非分布式任务队列）。需常驻可把 `python3 server.py --port 8787` 放进 systemd / pm2 / nohup。
- 并发写入外链池使用原子替换（`os.replace`），但高频并发的两次分析/调度写入理论上存在极小概率的末次写入覆盖，常规使用无影响。

## 6. 许可

[MIT](LICENSE) © 2026 hhool
