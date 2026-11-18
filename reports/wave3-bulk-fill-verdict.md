# soundbuttons 两站 wave=3 批量补全结论（负结果）

日期：2026-11-17 14:15
问题：soundbuttons.cc 5283 条 + click 5175 条 wave3 资源页 `submit_type=unknown`，
能否批量补全以扩大一次投递池？

## 结论：不批量补全，保持 wave3

**理由：可验证性不足 + 误报率高 + 成本不可接受。**

1. 这 5276 条来自 WDC 2012 竞品反链图，note 只有「类型: 资源页/链接列表 +
   发现打分 + 竞品反链证据」。「历史上链接过竞品」≠「现在接受新提交」，
   没有一条包含提交入口证据。
2. 形态统计：5249/5283 是根域名无路径，24 条 blog 形态、12 条目录形态。
   域名关键词筛选出的 206 条高置信候选中，实探 30 条仅 2 条表面命中（6.7%）。
3. 复核发现 2 条「命中」皆为误报：
   - `linkshed.net`：不存在的路径也返回 200 且页面相同（SPA 通配路由），
     "submit-form" 实为 URL 缩短工具输入框 → 不是目录提交入口。
   - `cool-tools.org`：首页有 submit 提示但 /submit 超时、无法确证 → 人工待确认。
   **实际可自动升级：0/30。**
4. 成本：30 域名 × 11 路径探测耗时 4m23s；全量 1 万条需 >12 小时，
   且反爬误报需逐条人工复核，得不偿失。

## 已执行的动作

- `tools/probe_wave3_submit.py`：加严探测规则（必须出现「submit/add/list your site」
  明确引导 + 表单含 URL 字段且有 submit 按钮），支持传高置信域名子集。
- 抽样报告：`reports/wave3-probe.json`（30 条逐域名证据）。
- **台账未改动**：soundbuttons.cc/click 的 wave3 保持原样，不注入猜测数据。

## 更优的替代路径（建议）

真正能扩大一次投递池的不是给旧 WDC 数据猜类型，而是**新增可验证的自助目录源**：
- 复用 downer 的 47 条策展方法（明确目录 + 显式 submit_type + HTTP 验证），
  为 soundbuttons 建一批新的「软件目录 / 音效资源目录 / 开发者工具目录」种子。
- 对 wave3 只做**按需人工复核**：当人工准备投递某条时，打开页面确认提交路径，
  再用 `blw mark --submit-type listing` 单条升级（wave 自动派生为 1）。
- 把**多个竞品共同反链**的条目优先排队复核，而不是 1 万条平铺。

## 复核优先队列（已生成）

`reports/wave3-review-queue.csv`：两站共 **515 条**，筛选口径为
`via_competitors ≥ 3`（≥3 个竞品的历史反链证据，远高于单条的 4518/4435 条）。

- soundbuttons.cc 257 条、soundbuttons.click 258 条。
- 注意：wave3 全部 fit_score ≤63（WDC 资源页无 authority 数据，workbench 重算分低），
  所以**不能用 fit_score 筛**；via 数是唯一有区分度的信号。
- 队列首条：`es.tl`（8 竞品）、`mister-wong.de`（8）、`hispasonic.com`（7）、
  `metafilter.com`（7）、`only2clicks.com`（7）—— 这些是看起来像真实链接目录的高优先项。

## 下一步

1. 人工复核 515 条队列：打开页面确认提交路径 → `blw mark --submit-type listing` 单条升级。
2. 为 soundbuttons 补新目录种子（非 WDC 旧数据），走 downer 同款策展+验证流程。
