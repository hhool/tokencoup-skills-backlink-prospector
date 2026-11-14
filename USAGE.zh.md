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
- 顶部表单填 **目标域名**（如 `soundbuttons.click`）；**关键词**逗号分隔（如 `soundboard, sound effects, meme sounds`）。
- 点「从当前表单添加为定时档案」可把这组配置保存，下次切换域名自动带上。
- 不同域名数据**完全隔离**，互不串台。

### 第 2 步 · 分析拿候选（🔍 分析）
- 填好表单后点 **分析**。
- 候选来源：① 该域名的**种子库**（`seeds/seed-<域名>.json`，已随镜像内置、稳定可靠）；② 可选 Bing 实时发现（数据中心出口常被返回无关缓存，会被相关性闸门拒掉，属加分通道）。
- 结果按 **优先级 priority（0–100）= 相关性 + 权威 + 可获取** 排序，可按表头任意列排序、按类型/最低优先级/仅缺口/仅有效筛选。
- 默认 `persist=1`，结果**自动并入外链池**并去重累计。

### 第 3 步 · 看池子、算真缺口（🗃 外链池）
- 统计卡：**累计发现 / 已拥有 / 缺口 / 缺口且有效**。
- 左侧**目录树**按 10 种外链类型组织、可多选筛选；右上角可切「已拥有 / 缺口」状态。
- **导出池 CSV** 按钮下载候选清单。
- 此时若没导入已有外链，所有非竞品候选都会被算成缺口（正常中间态）。

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
