# azgames 分带规则变更与第一批重选（DR 20-80）

- 时间：2026-11-17 16:05
- 触发：用户指令「第一批验证 DR 80-100 顶级外链地址不需要执行，需要专门维护。第一批先找一些 20 到 80」
- 结论：**原第一批 20 条里有 12 条属 DR 80-100 顶级，全部移出批量执行**；第一批改为 DR 20-80 区间，当前池只捞得出 11 条。

## 一、规则（已生效）

| 分带 | 处置 | 台账标签 |
|---|---|---|
| DR 80-100 | 不批量投递。改专门维护（单独养号、走关系/人工精投） | `tier-top` |
| DR 20-80 | 第一批批量执行对象 | `dr20-80` |
| DR < 20 | 低价值，排在 20-80 之后 | `dr-lt20` |
| 无数据 | 先测 DR 再定档 | `dr-unknown` |

标签已写入 `targets.jsonl`，看板可按标签筛选。

## 二、数据口径（必须先说清）

台账里**没有真正的 Ahrefs DR 字段**，只有 `authority_score`（known 榜单分）。本轮用它作 **DR 代理值**，报告与标签一律标「DR代理」，不冒充实测 DR。

需要真 DR 的话只有三条路：Ahrefs API（付费）、第三方 DR API（付费）、浏览器逐条查（128 条成本高）。当前没有可用 key，OpenPageRank 旧 key 已全部失效。

## 三、分带结果（128 条）

| 分带 | 条数 | 备注 |
|---|---|---|
| 80-100（顶级，不执行） | 68 | reddit / medium / substack / facebook / x / linkedin / youtube / quark 系 / wikipedia / dev.to / producthunt 等 |
| 20-80（第一批） | 14 | 下表 |
| 未知 | 46 | 榜单无数据，需实测 DR |

## 四、第一批候选（DR 20-80，共 14 条，wave=1 的 11 条）

| 域名 | DR代理 | fit | wave | 提交方式 | 现状 | 入口实测 |
|---|---|---|---|---|---|---|
| hashnode.com | 76 | 71 | 1 | publish | working | 需账号，页面即注册 |
| hostloc.com | 68 | 67 | 1 | posting | working | 需账号（Discuz） |
| lobste.rs | 74 | 61 | 1 | posting | pending | 需账号 |
| startupstash.com | 76 | 43 | 1 | listing | pending | reCAPTCHA |
| saashub.com | 74 | 42 | 1 | listing | pending | HTTP 403 |
| sortlist.com | 78 | 40 | 1 | listing | pending | 需账号 |
| futurepedia.io | 74 | 38 | 1 | listing | pending | 入口 404 |
| toolify.ai | 72 | 37 | 1 | listing | pending | HTTP 403 |
| theresanaiforthat.com | 79 | 36 | 1 | listing | pending | HTTP 403 |
| designrush.com | 79 | 36 | 1 | listing | pending | HTTP 403 |
| betalist.com | 78 | 17 | 1 | listing | pending | Cloudflare Turnstile |
| prlog.org | 76 | 75 | 2 | pitch | pending | 需邮件沟通 |
| openpr.com | 74 | 75 | 2 | pitch | pending | 需邮件沟通 |
| newswire.com | 76 | 61 | 2 | pitch | pending | 需邮件沟通 |

**现实**：11 条里 5 条是 Cloudflare 403/Turnstile，2 条入口 404 或需账号，真正「进去填个表就能交」的接近 0。DR 20-80 区间在现有池子里就是这个密度。

## 五、结论：需要换发现源

现有 128 条的来源（WDC + 竞品反链）天然偏向高权重平台，所以 68/128 落在顶级带。要凑出像样的 DR 20-80 第一批，必须专门找**中长尾**：
- 行业小目录 / 独立站友链页（DR 20-50 为主，多数无 captcha）
- 老式 Web 目录（仍接受免费提交、表单简单）
- 细分类目博客的 resources 页

这三类在现有池子里几乎没有，得新跑一轮发现（并按 DR 20-80 过滤，而不是按 fit_score 排序）。

## 六、留痕

- 标签：`tier-top` 68 / `dr20-80` 14 / `dr-unknown` 46，已写入台账
- 清单：`reports/azgames-toptier-80-100.csv`、`reports/azgames-batch1-dr20-80.csv`、`reports/azgames-dr-unknown.csv`
- 工具：`tools/band_select.py`（分带 + 打标）
- 通道日志：`~/seo/.vault/browser-lane.jsonl`（dev.to 已按新规标 skipped：DR代理 87 属顶级）
