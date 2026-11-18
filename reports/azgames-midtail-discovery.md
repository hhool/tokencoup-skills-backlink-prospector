# 中长尾外链发现（三类来源实时结果）

- 时间：2026-11-17 16:12
- 口径：`authority_score` 为唯一权威标准（用户 16:06 确认）；本批只挖「低权威、能直接投」的三类来源
- 范围：行业小目录/友链页 · 老式 Web 目录 · 细分类目博客 resources/write-for-us
- 实测 34 条候选，**结果比预期更差**：可匿名提交 0 条落单

## 一、分类实测结果

| 判定 | 条数 | 说明 |
|---|---|---|
| 可匿名提交（submittable） | 5 | submit-express、freewebsubmission、sitelike、bizcommunity、gamedev.net |
| 表单不明确（form_unclear） | 3 | jasminedirectory、somuch、brownbook（有表单但无 url 字段，需人工找入口） |
| 反爬拦截（bot_blocked 403/429） | 8 | indiedb、newgrounds、cybo、opendi、construct、itch.io、gamedevblog、dirjournal |
| 死链（404/410） | 9 | viesearch、01webdirectory、2findlocal、indiegamesplus、js13kgames、html5games、freewebarcade、arcadeboss、gamersdecide |
| 无人机验证但无表单 | 6 | gainweb、tupalo、gamejolt、gamesnacks、gamedeveloper、indiegamebundles |
| 人机验证 | 1 | jayde.com |
| 无响应 | 1 | dmegs.com |
| 需登录 | 1 | 80.lv |

## 二、真实投递尝试（不伪造）

| 站点 | 动作 | 真实回执 | 判定 |
|---|---|---|---|
| freewebsubmission.com | POST `/cgi-bin/submit.cgi`（url/Name/email/Agreed/engines） | 「**Automated submissions are not accepted.** You must have Javascript enabled to use our submission service.」 | **rejected**（站点明文拒绝自动化，不是网络问题） |
| submit-express.com | 检查首页表单 | 只有 newsletter 订阅（email + page_url），无站点提交入口 | **非提交页**，退回 |
| sitelike.org | 前轮 POST AddSite.aspx | 返回说明页「去首页搜索后再提交」 | 未成单（两步流程） |

## 三、可用种子（8 条）

`seeds/seed-azgames-midtail.json`：submit-express、freewebsubmission、sitelike、bizcommunity、gamedev.net（submittable）+ jasminedirectory、somuch、brownbook（form_unclear）。

原始实测：`reports/azgames-midtail-raw.json`、`reports/azgames-midtail-submit.json`。

## 四、结论（重要）

1. **老式 Web 目录这一层已经塌了**：34 条里 9 条死链、8 条 Cloudflare 拦截，剩下一半是 newsletter/无表单的壳页。免费匿名目录在 2026 年基本不存在了。
2. **「自动化」被站点主动封堵**：freewebsubmission 直接写「不接受自动提交」。这类站要人工点，脚本提交只会拿到明文拒绝。
3. **真正还能做的三档**（已在 `~/seo/.vault/browser-lane.jsonl` 留痕）：
   - `auto`：无 captcha、表单简单 → 目前样本里 0 个
   - `handoff`：表填好、人点一次（jayde、betalist、startupstash、betalist 的 Agent API）
   - `blocked`：邀请码/明文拒自动化/403（advertcn、freewebsubmission…）
4. **一个真正的发现：BetaList 提供官方 Agent API**（`https://betalist.com/agent`）：`POST /agent/submissions` 无需账号即可起草，返回 `claim_url`；但发布必须由本人在 claim 页选套餐并**付费**，agent 不能发布也不能付款。要不要付费由你定。

## 五、下一步选项

1. 用 `handoff` 档跑一批：脚本填表 → 你点一次人机验证 → 我接管收信/回执/回写（每批 5-10 条可控）。
2. 换发现源：老式目录已死，改挖「niche 博客 resources 页 + 独立站友链」并要求无 captcha（这类需要更大样本量才能凑出可用批次）。
3. 顶级（80-100）那 68 条走专门维护：单独养号、人工精投，不进批量队列。
