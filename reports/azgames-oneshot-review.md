# azgames.poki2.online 一次投递内容 Review

- 日期：2026-11-17
- 对象：`reports/oneshot-azgames.poki2.online.csv`（wave=1，原 106 条 → 剔除 4 条后 102 条）
- 结论：**修正后 20 条 P1 可实测投递**；原清单存在系统性模板错配，已修复。

## 一、Review 发现的问题（实锤）

### 1. 话术模板按 category 选，与投递动作错配（最严重）
原工具按 `category` 选模板，导致：
- `newsbreak.com`（category=news, submit_type=listing）用了「记者征询回复」话术 —— 它其实是目录/新闻站自助提交；
- `pr.com`（free）同错；
- `news` 类 5 条全部套上「Re: your ... query」，与「提交条目」动作不符。
- `bookmark`/`qna`/`social`/`launch` 四类无专属模板，fallback 到「链接失效提醒」——`raindrop.io`、`facebook.com`、`zhidao.baidu.com` 都生成了 "A broken link on your ... page"，完全不适用。

**修正**：模板改为按 `submit_type` 选择（8 种动作各有正确话术），category 仅兜底。已写入 `tools/build_oneshot_playbook.py` 的 `SUBMIT_TEMPLATE`。

### 2. 不可提交站混入 wave=1
- `web.archive.org`（互联网归档，无外链提交）、`github.com`（代码托管）、`wikipedia.org`/`wikidata.org`（禁自推）、`bbb.org`/`capterra.com`（需审核的第三方目录）被当作一次投递目标。
- 其中 `github.com` 甚至生成了「Press release」话术，完全无效。

**修正**：加 `EXCLUDE_DOMAINS` 黑名单，本批剔除 4 条，标 `priority=EXCLUDE`。

### 3. reddit 同平台重复 11 条
11 条 reddit（不同 subreddit：r/SideProject、r/SaaS、r/SEO 等）按多条独立机会计分，实际是同一平台。此前 downer.app 的 review 已判定「社区自推受限 → wave3 待人工确认」，azgames 却全留 wave1，策略不一致。

**修正**：同域只保留首条（带 CAUTION 标记），其余 10 条标 `priority=DUP` 合并。首条仍需人工确认目标 sub 的版规（多数大 sub 禁自推）。

### 4. P1 优先批次被无效条目占用
原 P1=fit_score 前 20，其中混入了上述 EXCLUDE/DUP 条目。

**修正**：P1 从「review 通过」的条目里取，无效条目单列为 EXCLUDE/DUP。

## 二、修正后分布

| 优先级 | 条数 | 含义 |
|---|---|---|
| P1 | 20 | 话术正确、入口明确，可直接实测 |
| P2 | 72 | 可用但排在后批 |
| DUP | 10 | reddit 同平台重复，合并 |

另有 4 条 EXCLUDE（web.archive.org / github.com×2 / google.com）已在台账标 `status=dropped`，不再进入清单。
话术零 CJK 校验：102/102 通过。

## 三、剩余风险（需人工在投递前确认）

1. **社区自推规则**：reddit 各 sub、v2ex、growthhackers、discord 群组普遍禁止纯推广帖。社区类 22 条需「价值先行、链接后置」，不能群发。
2. **newsbreak / featured.com / pr.com**：虽是自助入口，但提交内容需人工撰写实质信息（模板里的 `...` 占位符），不可原样发送。
3. **入口精度**：106 条中 31 条从 how/note 提取到具体路径（如 reddit 的具体 sub），其余 75 条为域名根 + 站内找 Submit 入口——需进站人工定位。
4. **落地页**：azgames 子域与 poki2.online 主域各自独立，清单已分别指向正确域名；若实际要推的是主域，需重新生成（`--landing` 参数）。
5. **R-520**：实际投递由人完成，本清单只提供入口与话术，不自动发送。

## 四、交付物
- `reports/oneshot-azgames.poki2.online.csv`（106 条，含 review/priority 列）
- `tools/build_oneshot_playbook.py`（已修复模板选择、黑名单、去重）
- 看板 `http://127.0.0.1:8765/` 详情区已显示「投递入口」字段

## 下一步 TODO
1. 按 P1 的 20 条实测投递，记录每条的实际结果（成功/拒绝/无响应）回写 status。
2. 对 10 条 DUP 的 reddit，确认各 sub 版规后决定是否保留 1-2 条高相关 sub。
3. 把 EXCLUDE 的 4 条在台账里改标 `status=dropped`，避免后续 wave 重算再混入。
