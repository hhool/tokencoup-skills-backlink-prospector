# Backlink Prospector · 外链目标发现器

为某一域名查找**真实、有效**的可用外链目标地址，并做**外链缺口分析**。
后台服务 + CSV 输出 + 前端展现。零第三方依赖（纯 Python 标准库）。
License: [MIT](LICENSE) · English docs: [README.md](README.md)

> **文档说明（该读哪份）**
> - **[USAGE.zh.md](USAGE.zh.md)**（英文 [USAGE.md](USAGE.md)）：**用户使用手册**——面向运营 / 推广人员，讲怎么用界面和接口完成"发现候选 → 算缺口 → 投放交付"的闭环。日常操作看这份。
> - **README.zh.md**（本文）：**技术与架构文档**——模块设计、打分模型、多域名隔离、端点契约、CSV 字段、局限说明。二次开发或排障看这份。

> 本工具在架构与契约上**参考 `seo-page-snapshot`**：仅用免费 / 开放数据源、商业指标（DR/DA）**绝不估算**、双语字段、缺数据即标 `unavailable`。

---

## 1. 三大模块（对应需求）

| 需求 | 实现 |
|---|---|
| **1. 外链地址类型** | 10 类（含 `reciprocal` 已与 `directory` 分离）：`industry_media` 行业媒体/测评站、`guest` 客座博客、`resource` 资源页/链接列表、`directory` 目录（单向收录）、`community` 社区/论坛、`social` 社媒、`partner` 互补品牌、`authority` 安全/权威机构(.gov/.org)、`digital_pr` 数字 PR、`reciprocal` 互链（双向交换，独立类型）。定义见 `analyze.py` 中 `TYPE_LABEL_ZH/EN` 与 `seed.json` 的 `type` 字段。 |
| **2. 优先级筛选标准** | 每条目标打分：`relevance`(0–40) + `authority_score`(0–30) + `obtainability`(0–30) = `priority`(0–100)。权威层级 `authorityTier` 来自种子标注 + 免费 Tranco 排名信号。前端支持按类型、最低优先级、仅缺口、仅有效筛选。 |
| **3. 外链缺口分析** | 候选 = 种子库（真实站点）+ 可选 Bing 实时发现 + 竞品外链站（离线 host 图 harvest）。导入已有外链（GSC/Ahrefs 导出）后，标记 `already_have=true`，未拥有者即 `is_gap`（缺口）。**竞品域名整行剔除**（含子域，不计入候选/有效/缺口，也不做 HTTP 校验），竞品的**外链站**反而是高价值候选。 |

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
- 导入真实已有外链（GSC / Ahrefs / 自建 Common Crawl 导出，每行一个域名）→ 标记 `acquired`（已拥有）。
- **「见过」不等于「已拥有」**：缺口只与台账中已验证上线的投放、人工标记及显式导入比对；仅出现在池里不会排除候选。详见 D7。
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
# 动态输出中英文审计（157 项断言，含「数据加载完成后原地切语言」场景）
python3 tools/i18n_audit.py https://backlink-prospector.fly.dev/
# 投放台账：幂等 / 证据门 / 排除规则 / 缺口口径 / 双语界面
python3 tools/placement_selftest.py https://backlink-prospector.fly.dev/
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

### D6. 页面中英双语 · 动态输出

界面默认中文，点 `EN` 一键切换。静态文案走 `data-i18n` + `applyLang()`；**所有由 render 函数运行时拼出的字符串**由统一重绘流程覆盖：

- `renderAllDynamic()` 是语言切换的唯一入口，依次重绘：分析结果、外链池统计/目录树/类型芯片/表格行、类型说明、渠道表、后台状态/定时档案/运行历史、概况 SVG 标签、排序表头提示、中心域名标签以及已缓存的临时消息。新增任何依赖 `LANG` 的渲染函数都**必须**登记到这里，否则旧语言会一直残留到下次数据重载。
- 重绘只读缓存状态（`LAST`、`POOL`、`SCHED`、`LAST_CHANNELS`、`LAST_PROFILE`、`TIPS`），不重新请求接口。定时档案通过 `collectProfileCards()` 从 DOM 反向收集再重绘，因此运营者未保存的编辑不会被切换语言冲掉。
- 临时文案（错误条、导入提示、按钮「进行中」状态）以 `{zh, en}` 对存储并跟随语言重新渲染，而不是冻结在事件发生的那一刻。
- 自由文本数据在源头就双语：种子行 `note` + `note_en`，类型说明 `value_weight` / `value_weight_en` 与 `reciprocal_note` / `reciprocal_note_en`，档案 `note` / `note_en`，分析结果 `limitations`（英文）/ `limitations_zh`。`analyze.py::note_en()` 对历史数据降级为中性英文描述，确保纯中文备注不会漏进英文界面。
- 属性文案同属该契约：`data-i18n-ph` / `data-i18n-title` / `data-i18n-aria` 分别驱动 `placeholder` / `title` / `aria-label`，`applyLang()` 同时设置 `document.title`。只查 innerText 的审计看不到这些字符串——中文表单提示曾因此躲过一次语言切换。
- 数据里的双语字段（类型标签 `type_label_zh/en`、渠道 `name_zh/name_en`、类型说明 `zh/en`）按语言切换而非同时展示：英文界面只显示英文，中文界面为中文主 + 英文副。服务端原始错误文本改存 `data-raw`，不再以中文 tooltip 直接暴露。
- **英文界面全 DOM 零 CJK**（文本节点 + placeholder / title / aria-label / alt）。唯一白名单是 `#langToggle`，它显示的是目标语言「中」，不是界面文案。

`tools/i18n_audit.py` 用真实 Chrome 加载全部 Tab，按 ZH → EN → ZH 逐项审计，并覆盖错误/运行中消息、未保存输入、属性文案与全 DOM 零 CJK 断言，共 157 项断言，是该契约的回归防线。

### D7. 投放台账 —— 按域名建库，成功投放后不再复用

外链池是**候选清单**（「见过」），不是「已使用」记录。台账是「已投递」的唯一事实源：

| 层 | 存储位置 | 含义 | 谁可写 |
|---|---|---|---|
| 候选池 | `data/store-<center_domain>.json` 的 `domains{}` | 发现过某个目标 | 分析运行（按域名幂等合并） |
| 投放台账 | 同文件的 `placements{}` | 每个投放位一条记录 | 仅运营动作 |
| 排除表 | `suppressions{}` | 域名或精确投放位永久排除 | 仅运营动作 |

`center_domain` 由存储文件名隐含，隔离方式不变，新增记录不带跨品类字段。投放位主键为 `sha256(target_domain | target_url | placement_type)[:16]`，**不是域名**——同一站点的不同页面仍是可利用资源。

状态机：`registered → claimed → submitted → live → lost`，`rejected` / `error` 为终态。进入 `live` 必须提供 `landing_url` + `verify_method` 作为证据；「点了提交」不算成功。

每次领取都会重新判定排除规则，命中即返回 `409` 并附原因：

1. 该投放位已有验证上线的外链 → 永久锁定。
2. 该位处于 `claimed` / `submitted` → 幂等，不重复插行。
3. `lost` → 必须人工复核，绝不自动回到可投队列。
4. `rejected` / `error` → 冷却至 `cooldown_until`（默认 90 天）。
5. 同一 `target_domain` 在 90 天内已有 `live` / `submitted` → 节奏窗口（按域名分组，绝不按 URL 分组）。
6. `suppressions` 中显式排除的域名或投放位 → 永久排除。

`gap` 现按 `owned_domains = 已上线投放 ∪ acquired_domains ∪ 显式导入` 计算。旧的「整池当已有外链库」行为仍可用 `use_pool_as_existing=1` 复现以便对比，但默认关闭；定时任务显式传 `0`。

新增端点：`GET /api/placements`、`GET /api/placements/csv`、`POST /api/placements/claim`、`/claim-batch`、`/transition`、`/suppress`。台账 CSV 与池 CSV 分开且带证据列，交接给运营时两层不会混淆。

`tools/placement_selftest.py` 是该契约的回归防线（状态机、HTTP 409、缺口口径、真实 Chrome 双语渲染）：
`python3 tools/placement_selftest.py https://backlink-prospector.fly.dev/`
审计线上时加 `--no-write`，跳过会写数据的端点小节，避免在 Fly 卷上留下测试台账文件。

---

### D8. 竞品模型 —— 竞品本身不是外链站，竞品的外链站才是

同一份「竞品域名」清单，在流水线里被拆成两个完全不同的实体：

| 实体 | 处理 | 计数 |
|---|---|---|
| 竞品域名**本身**（含子域，如 `blog.compa.test`） | 校验前直接剔除；不请求 HTTP、不入池、不进缺口 | 只在 `totals.competitor_rows` 单独报告 |
| 竞品的**外链站**（链接到竞品的站点） | 正常候选，按证据准入，不受关键词门限限制 | 计入 `totals.candidates` / `valid` / `gap`，并标 `source=competitor_backlink` |

「竞品越多 → 有效外链越多」不是恒等式：能保证的只有「被扫描的反链面变大」，净增要按去重与质量闸门后的结果算。

**证据来源（离线 harvest）**：`tools/competitor_backlinks.py` 流式扫描 Web Data Commons / Common Crawl 的 host（或 domain）级边表，做一次反向查询：哪些 host 指向竞品。图有几十 GB，镜像只有几十 MB，所以**离线跑、产出受控文件**、随镜像发布：

```bash
# 1) 从 https://webdatamining.org/ 取同一 crawl 窗口的 domain-ranks + domain-edges
# 2) 反向查：谁链接到我的竞品
python3 tools/competitor_backlinks.py \
  --center soundbuttons.click \
  --competitors myinstants.com,voicemod.net \
  --ranks /data/wdc/cc-main-2025-may-aug-domain-ranks.txt.gz \
  --edges /data/wdc/cc-main-2025-may-aug-domain-edges.txt.gz \
  --out   seeds/competitor-links-soundbuttons.click.json
```

- 三趟流式扫描：ranks 找竞品 id → edges 收「指向竞品的边」并按 source 聚合 → 再扫 ranks 把 source id 还原成域名。内存只随命中数增长。
- 质量闸门：竞品自身与子域、中心域名、`BLOCKED_DOMAINS`、`NOISE_DOMAINS` 全部丢弃；`--min-links` 可要求至少 N 条链接。
- 产出即证据：每行带 `via_competitors[]` 与 `evidence{graph, edges, per_competitor}`；`type` 由域名启发式推测并标 `type_guess=true`，等人工确认。
- 已有边表（`source,target[,count]`）也可用 `--from-csv` 直接喂；`--dry-run` 只报告不落盘。

读取顺序：`data/competitor-links-<域名>.json`（运营覆盖）→ `seeds/competitor-links-<域名>.json`（随镜像）。文件存在才生效，缺失时 `data_sources.competitor_backlinks.status` 为 `empty`，流水线行为与之前一致。

### D9. 日配额是闸门，不是仪表盘

`100/天`（按中心域名可配，1–2000，`POST /api/settings`）拦在**写台账的那一刻**，不是画批次的时候：`claim_placement` 超过上限直接拒绝（`409 daily quota reached`），`claim-batch` 把被砍掉的行数记进 `quota_blocked`。池里的单条「选用」走同一道闸，绕不过去。配额日按 **UTC+8**（`QUOTA_TZ_OFFSET`）结算，台账时间戳存的是 UTC，比较前先换算——直接截字符串会把本地 08:00 前的领取全算到昨天。

### D10. 白名单 —— 记录留着，数字不算

白名单不是排除。排除的意思是不再提供这个投放位；白名单只是这个域名**不参与任何外链统计**（自家站群、聚合站、镜像站、目录农场）。

| 层 | 影响 |
|---|---|
| `store_stats` | 从累计发现 / 已拥有 / 缺口 / 缺口且有效 / 类型分布 / 互链占比中剔除，单独报 `whitelisted` |
| `domain_list` | 行仍返回（`whitelisted: true`，界面置灰），否则按钮消失就没法撤销；`is_gap` 强制为 `false` |
| `daily_queue` | 拦截原因 `whitelisted`，永进不了批次 |
| `claim_placement` | 拒绝：这里的外链永远进不了统计，做了也是白做 |
| `analyze` | 候选行标 `whitelisted`，不计入缺口 |

域名在入口归一（`https://www.Foo.com/x` → `foo.com`），非法输入直接拒绝而不是存进去；按中心域名隔离，存在 `data/store-<域名>.json` 的 `whitelist` 字段。界面上每条记录（池行、分析行、台账行）都有切换按钮，池页还有批量粘贴框。

---

### D11. 导入已有外链 = 有证据的上线记录，不是布尔标记

缺口算错的根源通常是第三层数据缺失：你已经有几百条外链，工具里却一条都不知道。导入因此不能只翻一个 `acquired` 开关，而要落成**台账事实**：

- 一行导出 → 一条 `state=live` 记录，`verify_method = import:<来源>`、`verified_at` 为空（有导出为证、没实地探过）。这样「存活复查」以后能精准挑出这些未探测的行。
- 池内域名：缺口减、已拥有加；池外域名：**不进池**（否则"累计发现"虚高），但记账 + 受 90 天同域节奏保护，不会再去要一个已有链接的站。
- **不吃日配额**：`claimed_on()` 显式跳过 `import:` 记录。否则一次粘 500 行就把当天的硬闸门顶死——这是实测踩到的坑。
- 解析层接受整条 URL / 裸域名 / CSV（含前置排名列），自身域名（含子域）、竞品、白名单、已排除、重复一律跳过并计数。
- `dry_run` 在深拷贝上跑，预览数字与真实写入完全一致却零落盘；`remove` 只删导入产生的行，缺口原样回来。
- 连带修掉一处埋着的矛盾：`merge_result()` 曾用 `acquired_domains` 覆盖 `acquired`，导致每次分析后"已上线"的域名在 JSON 里又变回 false（统计靠并集没露出来）。现在按「人工标记 ∪ 台账 live」计算，`unmark-existing` 也会返回 `still_live`，不再假装撤销成功。

---

### D12. 存活复查 —— 只有硬证据才能把 live 判成 lost

`live` 是台账的声明，不是事实。判断标准分三档，**只有一档会改状态**：

| 判定 | 依据 | 动作 |
|---|---|---|
| 存活 | 2xx + 页面里还能找到我们的链接 | 只记录 |
| 已失活 | 404/410，或 2xx 但链接不在页面上 | `live → lost`，域名退回缺口 |
| 未能判定 | 超时 / DNS / TLS / 403 / 429 / 5xx | **只记录，绝不删行** |

三个设计取舍：

1. **403 与超时不算失活**。反爬墙、CDN 抖动、你自己的 VPS 抽风，都会让一次探测失败；把这种当失活会误删真实外链（而且 `lost` 之后同域要人工确认才能复用）。宁可留着等下一次。
2. **匹配从强到弱**：绝对 href（`mine.example/guide`）→ 相对 href（`href="/guide"`，真实页面最常见）→ 裸路径（≥6 字符，防止命中的是导航）→ 仅域名（最弱，只在没有 own_url 时的兜底）。命中哪一档都写进 `recheck.found`，报告不装。
3. **导入行优先探**。`verified_at` 为空的记录（Grsc/Ahrefs 导入）是整张台账里最不确定的部分，先探它们。

`lost` 只改记录状态，不会自动重发；同域 90 天节奏里，`lost` 的行需要人工确认后再 `submitted`（状态机已允许 `lost → submitted`）。复查不消耗日配额。默认窗口 7 天（`RECHECK_DAYS`），调度器每次跑完分析顺带复查 20 条（`recheck` / `recheck_limit` 可关可调）。

代码落在 `recheck.py`（探测 + 判定），`store.py` 不引入任何网络调用；`scheduler.py` 通过注入的 `recheck_fn` 调用它，保持"调度器不认识网络策略"的原有分层。

---

### D13. 运行快照 + 差异 = 「这次到底多了什么」

`times_discovered` 只说"又被看见一次"，回答不了"哪些是新的"。所以每次持久化运行后写一份**快照**（域名列表 + 无效域名列表 + 总量/有效/已拥有），保留最近 10 份，`run_diff()` 对比最近两份（`back=n` 可选更早的那份）给出 `added / removed / newly_invalid / recovered`。

三个刻意保守的地方：

1. **超上限就只报总量**。快照最多存 2 万个域名，超了 `total_only=true`，diff 返回 `comparable:false` + `reason:"snapshot truncated"`，而不是编一个名字差异。宁可说"我只能给你总量"，也不给假明细。
2. **`recovered` 必须仍在池中**。算法是「上次无效 ∩ 这次在池 − 这次无效」；如果只做「上次无效 − 这次无效」，一个被删掉的域名会冒充"恢复"。
3. **优先级变化不进 diff**。优先级每次重算都会微调，把它塞进差异里会把真正重要的"新增/失活"淹掉。

### D14. 自动补货：冷却 + 无进展退避

配额是硬闸门，但闸门后面得有货。`inventory_count()` 数的是「现在可以发出去的候选」（未领取、未拥有、未排除、验证有效、不受同域节奏限制），低于 `REFILL_THRESHOLD`（默认 30）就触发一次分析；同一域名 `REFILL_COOLDOWN_H`（默认 6h）内不再触发，冷却记录写在 store 里，重启不重置。

真正需要设计的是**空跑**：免费源本来就饱和，池子只有 17 个候选时，每 6 小时跑一次分析是纯噪音（对别人服务器也是）。所以连续"零产出"的补货会让冷却翻倍（6→12→24→48，上限 8×），一次有产出立刻归零。`added` 字段就是为此写在 `refills` 记录里的——没有它就没法判断"上次到底有没有用"。

分工：`store.py` 只算状态（`refill_state`），`scheduler.py` 决定什么时候调（每个 tick 最多补一个 profile，且 `status.running` 时不动手），`server.run_refill()` 负责真跑 + 记账。`Scheduler(autostart=False)` / `BP_NO_SCHEDULER=1` 让「import server」不再偷偷启动调度线程——自测里踩到过：导入 server 会拿真实 `schedule.json` 去补生产域名的货。

### D15. 失活待办：复查结果必须有人看见

`lost` 只是把记录改了状态、把域名退回缺口；没人看的话，这个信息等于零。概览页红条（近 7 天、`LOST_WINDOW_DAYS`）把"哪条链接死了、什么时候死的、证据是什么"顶到第一屏，点一下直达台账。

### D16. 外部唤醒：没有线程的时候，没人 tick

线上是 scale-to-zero，机器一停进程就没了，调度器线程跟着消失——**冷却到点、间隔到点这些事在睡着的时候永远不会发生**。`POST /api/cron/tick` 让外部定时器把机器叫醒并做恰好一次它本来该做的事（先补货，再跑到点的档案）；`ran` 取自 `last_run` 是否真的变了，两次并发只有一个会报真。

这个接口花的是真实配额，地址又是公开的，所以**没配 `BDL_TRIGGER_TOKEN` 就返回 503 而不是默默开放**（fail closed）。令牌错 403、没带 401。仓库自带 `.github/workflows/tick.yml` 每天敲两次（tick 自己判断到没到点，多敲不重复跑）。

### D17. 全站 API 鉴权：锁唤醒接口，也要锁旁门

`/api/cron/tick` 加了锁，但 `/api/refill`、`/api/schedule/run` 这些旁门同样花配额。设了 `BDL_API_TOKEN` 之后，**所有 `/api` 调用**都必须带 `X-BDL-Token` 头；页面、`/help`、`/api/health` 保持开放（健康检查不能带密钥，UI 也要能加载到弹窗那一步）。前端用一个 fetch monkey-patch 统一注入头，401 时弹一次输入框存进 localStorage——30 处 fetch 一处都没改。不设该变量则一切照旧（本地开发零负担）。

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
- `GET  /api/placements?domain=<domain>` → 投放台账记录 + 统计（见 D7）
- `GET  /api/placements/csv?domain=<domain>` → 台账 CSV（含证据列）
- `POST /api/placements/claim` → 领取投放位（被排除时返回 `409` + 原因）
- `POST /api/placements/claim-batch` → 批量领取（`center_domain` + `items[]`）；按投放位幂等，被排除的行单独回报、不中断整体
- `POST /api/placements/transition` → 推进状态；`live` 需证据
- `POST /api/placements/suppress` → 永久排除域名或投放位
- `GET  /api/profiles?domain=<domain>` → 该域名的关键词/竞品档案
- `POST /api/profiles` → 保存档案（body `{center_domain, keywords, competitors}`）
- `GET  /api/schedule` → 周期查询调度状态（config / status / runs）
- `POST /api/schedule` → 保存调度配置（body `{enabled, interval_hours, profiles[]}`）
- `POST /api/schedule/run` → 立即执行所有定时档案（body `{}`）
- `GET  /api/domains` → 工作区已知的全部中心域名（合并 profile / seeds / 池 / 竞品反链文件），供顶部下拉使用
- `GET  /api/health` · `GET /api/providers`
- `GET  /help` → 独立使用帮助页（`assets/help.html`，`?lang=en|zh` 双语）。顶栏「? 使用帮助」进入；每个 Tab 顶部另有 `💡 Tips` 按钮，就地展开对应说明。

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
`url, domain, type_key, type_label_zh, type_label_en, authority_tier, relevance, authority_score, obtainability, priority, valid, http_status, is_gap, is_competitor, already_have, tranco_global_rank, source, note, note_en`

- `valid`：分析时真实 HTTP 存活校验结果（`true`=可达；403/401/429 视为页面存在但拒爬；404/超时视为失效）。
- `source`：`seed`（种子库）或 `bing_discovery`（实时发现）。
- `note` / `note_en`：中文与英文运营备注，成对导出，使 CSV 与界面语言无关。

**外链池 CSV（`/api/store/csv`）**：
`domain, url, type_key, type_label_zh, authority_tier, tranco_global_rank, priority, valid, http_status, acquired, is_gap, times_discovered, first_seen, last_seen`

- `acquired`：是否已导入为真实已有外链（`true`=已拥有）。
- `is_gap`：是否仍为空缺（`acquired` 为 `false`）。

**台账 CSV（`/api/placements/csv`）** —— 每个投放位一行，与上面的候选清单分开：
`id, target_domain, target_url, placement_type, own_url, state, batch_id, created_at, claimed_at, submitted_at, live_at, lost_at, rejected_at, error_at, cooldown_until, failure_reason, verify_method, landing_url, observed_href, rel, anchor_text, verified_at, note`

- `state`：`live` 表示链接已验证上线，该投放位永久锁定。
- `verify_method` / `landing_url` / `verified_at`：使 `live` 可审计的证据。

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
