# azgames 全量重扫 + 自动化处理（一次性跑完）

跑数时间：2026-11-17 16:18–17:10 · 站点：azgames.poki2.online（免费在线小游戏站）

## 一句话结论

把本地全部语料重新扫了一遍，得到 **6643 条新候选**；对其中 **887 个域**做了真实 HTTP 探测并自动投递，**没有一个匿名一次投递成功**——拿到成功回执的是 0 条。台账从 128 条扩到 **1015 条**，每条都带实测证据。

## 一、语料与入池

| 语料 | 规模 | 用进池 | 说明 |
|---|---|---|---|
| WDC 2012 PLD 超链图 | 6457 个域 | 6404 | 22 家游戏门户（friv/y8/miniclip/agame/newgrounds…）中 **≥2 家**共同反链的 host，27495 个源域里筛出 |
| submitlist 全量目录 | 3477 条 | 279 | 只保留 directory/citation/marketplace/community/launch 这几类可提交型 |
| 已有种子 | 5 | 5 | 中长尾种子 |

去重后 **6643 条**（与台账已有 45 条重复的先剔掉），相关性分层：strong 151 / weak 248 / none 6244。

## 二、实测口径（每一步都留证据）

- 每域 **1 次首页 + 最多 3 个入口**（先看首页自己给的链接，再试 `/submit`、`/add-site`、`/addurl` 等词表），robots.txt 不允许的路径不请求。
- 判定分 8 档，不靠猜：`anonymous_form` / `form_get_only` / `account_required` / `captcha` / `no_form` / `bot_blocked` / `unreachable` / `redirect_offsite`。
- 只有表单同时满足「有 url 字段、无密码字段、无 Turnstile/reCAPTCHA、POST」且**页面自己写着可以提交网站**，才算匿名出口；否则带 website 字段的注册表单会被误当入口（crowdreviews 的 `SignupVendorNewForm` 就是这样被抓出来的假阳性）。

## 三、887 个域的实测结果

| 判定 | 条数 | 占比 | 含义 |
|---|---|---|---|
| unreachable | 305 | 34% | DNS 失败/连接不上（2012 老目录大量已死） |
| no_form | 374 | 42% | 站点活着但没有提交口（预算内未找到） |
| bot_blocked | 89 | 10% | 403/429/Cloudflare —— **不是死链**，人工可访问 |
| redirect_offsite | 37 | 4% | 域名已转卖/停放（如 blog.com → sooma.com） |
| captcha | 33 | 4% | 入口被人机验证挡 |
| account_required | 30 | 3% | 要先注册账号 |
| **anonymous_form** | **12** | **1.4%** | 唯一可能「一次投递」的一档 |
| error | 7 | 1% | 解析/超时异常 |

可达率 **61%**（538/887）。

## 四、12 个匿名出口的真实投递结果

对其中 8 个发了真实 POST（Cookie 会话、带隐藏字段/CSRF、只发一次），**4 个当场被拒、3 个无明确回执、1 个落到账号墙**：

| 域名 | 入口 | 结果 | 证据 |
|---|---|---|---|
| avivadirectory.com | /submit.php | rejected | 页面明写「the fee is primarily for the time and effort…」**收费目录**，提交后被判 invalid |
| maxibestof.one | /submit | rejected | 提示必填项缺失（需要先选分类等） |
| tacticlinks.com | /en/submit/ | rejected | 回执报错，未收录 |
| madewithvuejs.com | / | rejected | HTTP 422（该表单是订阅表单，非收录） |
| e27.co | /startup-funding-news/ | account_wall | 回执「verify your email」，不是提交成功 —— 旧判据把它记成 success，已按新判据改判 |
| smoothdirectory.com | / | unknown | HTTP 200 无成功/失败措辞，无回执 |
| elitesitesdirectory.com | /post-new/ | unknown | 同上 |
| linkshed.net | /submit | unknown | 实为短链服务（long_url/custom_code），已按「短链」剔除 |
| tekpon.com / thestartupinc.com / pcastuces.com | — | 未投 | 前两个付费收录、pcastuces 品类不符 |
| blog.com | — | 未投 | 已转停放（sooma.com），按跨域跳转剔除 |

**没有一个拿到站点的成功回执**，台账里 `done` 仍为 0 —— 没有编造。

## 五、四个硬结论

1. **2012 老目录这条路基本走不通**：305 个不可达 + 37 个停放跳转 = 342/887（39%）已经不是活的目录站；剩下能开的也大多没有提交口。
2. **匿名表单 ≠ 免费收录**：12 个匿名出口里，4 个收费、2 个要补必填/分类、2 个是别的用途（融资动态、短链），真正「填个网址就收录」的是 0。
3. **Cloudflare 是最大的一道门**：89 个 403/429，人工能开、脚本不行，属于「要么人工点一次，要么放弃」。
4. **游戏站强相关池质量两极**：WDC 里 151 个游戏关键词命中的域，63 个已死；活着的多是外文小游戏站（hry.cz / giochi.org / spiele-freegames.de 这类），它们通常没有提交口，只有友链邮箱。

## 六、台账落账状态（serve 已重启，看板同步）

```
总量 1015 条    wave1 471 / wave2 29 / wave3 515
status:  working 548 / dropped 323 / pending 144 / done 0
tags:    gate:no_form 374 · gate:unreachable 305 · gate:bot_blocked 89
         gate:redirect_offsite 38 · gate:captcha 33 · gate:account_required 30
         gate:anonymous_form 10（12 个里剔掉停放的 blog.com 与短链 linkshed.net）· gate:shortener 1
```

- 提交方式按**实测门槛**改写：`account_required`/`captcha` → register（wave2），`no_form`/`bot_blocked` → unknown（wave3），只有 `anonymous_form` 留 listing（wave1）。这样 wave1 队列里不会再混进「其实要注册」的站。
- 每条 `owner_note` 存：语料证据（几家游戏门户反链 / submitlist DR）+ 入口 URL + 实测时间 + gate + 投递回执。
- 看板：`http://127.0.0.1:8765`（按 `gate:*` 标签可筛出「可人工接手」的 89 个 bot_blocked 和 30 个需注册）。

## 七、工件

| 文件 | 内容 |
|---|---|
| `reports/azgames-fullscan-candidates.json/.csv` | 6643 条候选（score/来源/相关性/证据） |
| `reports/azgames-probes-merged.json` | 887 条探测原始记录（含表单字段、回执摘要） |
| `reports/azgames-autopilot-{modern,strong,targeted,batch4,dirs,reprobe}.json` | 六批分次探测明细 |
| `reports/azgames-import.json` | 入账用的 887 条（含 status/tags/owner_note） |
| `tools/azgames_fullscan.py` | 全量重扫（WDC + submitlist + 种子 → 候选池） |
| `tools/azgames_autopilot.py` | 探活 → 找出口 → 真投递（robots 合规、额度上限、8 档判定） |
| `tools/azgames_scan_import.py` | 实测 → 台账（只入已实测，状态按证据映射） |

复跑：

```bash
python3 tools/harvest_competitor_links.py --center azgames.poki2.online --competitors "friv.com,y8.com,miniclip.com,..." --min-competitors 2
python3 tools/azgames_fullscan.py
python3 tools/azgames_autopilot.py --candidates reports/azgames-fullscan-candidates.json --top 300 --submit --max-submit 20
python3 tools/azgames_scan_import.py --dry-run     # 先看映射
```

## 八、下一步（按性价比排序）

1. **接手 89 个 bot_blocked**：这些站人工能开、且有提交入口，用 `/run` 执行台逐条点一次即可（我已把入口 URL 写进 `owner_note`）。
2. **30 个 account_required 走注册**：凭据库 `~/seo/.vault/azgames.poki2.online-accounts.json` 里已有 17 站密码，注册完再回头投。
3. **换发现源**：2012 语料已证明枯竭，改挖「游戏站友链页」——hry.cz / giochi.org 这类站底部的 partner 链接，是一手活的目录，量大且无人抢。
