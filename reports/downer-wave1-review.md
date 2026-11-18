# downer.app 一次投递（wave=1）人工抽查审阅

日期：2026-11-17 13:58
范围：`~/seo/downer.app/targets.jsonl` 中 wave=1 的条目（抽查前 25 条）
方法：按「是否真的一次动作即拿到链接、无外部回复依赖」逐条判定；对高不确定项实地抓取页面取证。

## 抽查取证结果

| 站点 | 原判 | 取证 | 结论 |
|---|---|---|---|
| alternativeto.net | listing / wave1 | 页面确认众包目录，有 add app 自助提交，条目由社区维护 | ✅ 一次投递成立 |
| buffer.com | publish / wave1 | 抓 `/resources/`：全为具名作者的编辑部博客，无 "write for us / submit / contribute" 入口 | ❌ 外部无法自助发布 → 改 pitch / wave2 |
| mailchimp.com | publish / wave1 | 同属品牌官博，无自助投稿入口 | ❌ 改 pitch / wave2 |
| hootsuite.com | publish / wave1 | 同属品牌官博，无自助投稿入口 | ❌ 改 pitch / wave2 |
| reddit.com | posting / wave1 | 页面反爬未取到；主流 sub 普遍限自推、需养号与逐 sub 确认 | ⚠️ 降级 unknown / wave3 待人工复核 |
| redd.it | posting / wave1 | reddit 官方短链，与 reddit.com 同一平台 | ❌ 重复且同受限 → 标记 dropped |
| softonic.com | listing / wave1（备选含 guest_post） | 候选显式给 listing，但旧 build_target 让推断的 guest_post 排首位 | 🔧 修正主类型顺序，wave1 成立 |

## 执行的修正（已落盘）

- buffer.com / mailchimp.com / hootsuite.com：`publish` → `pitch`，wave 1 → 2，重算 fit_score。
- reddit.com / redd.it：`posting` → `unknown`，wave 1 → 3（待人工确认具体 subreddit）。
- redd.it：`status=dropped`（与 reddit.com 重复，避免双投）。
- softonic.com：`submit_types` 主类型归位为 listing，wave=1。
- 修复根因：`blw.py build_target()` 现强制把候选显式指定的 submit_type 置顶，避免推断路径篡位。

## 修正后 wave 分布

| 波次 | 条数 | 说明 |
|---|---|---|
| wave=1 一次投递 | 21 | 目录提交 / 社区发帖 / 问答 / 注册 / 开源 PR |
| wave=2 多次交互 | 26 | 投稿撰文 / 媒体征询 / 申请审核（需邮件往返） |
| wave=3 待判定 | 3 | reddit 域名 ×2、blog.hootsuite.com，待人工确认 sub / 投稿路径 |

## 仍需人工确认的 4 类（抽查发现的系统性风险）

1. **社区发帖类（betanet/hackernews.cc/videohelp/doom9/videolan）**：允许发布 ≠ 允许带推广链接。逐个确认版规，纯推广会被删帖/封号。
2. **问答类（quora / stackexchange）**：回答需真实有价值，硬塞链接违反规则。StackExchange 对自我推广尤其严格。
3. **开源 PR（ffmpeg.org）**：需符合仓库收录标准，不能硬塞，实际周期可能按周计——名义一次投递，实质有审核往返。
4. **反爬拦截的 12 条目录站**：403/412/429 仅证明服务器存活，是否真的能匿名自助提交需人工打开确认（Cloudflare 可能要求 JS/注册）。

## 审阅结论

一次投递池从 25 条收紧为 **21 条高置信条目**。误判主要来自「把品牌官博误解为可自助发布」与「推断路径覆盖显式类型」，两者均已修。剩余风险集中在社区/问答的规则合规，建议在实际投递前按上表逐条确认版规。
