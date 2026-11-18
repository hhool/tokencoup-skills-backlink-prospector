# azgames：自动注册通道 + 发送闸门（2026-11-17）

两件事落地：**注册尽量全自动**、**发送默认人工确认（可关）**，两者都本地留痕。

---

## 一、发送闸门（默认人工确认，可一键关闭）

所有对外发送（目录提交 / 投稿 / 发信）统一走 `tools/gate.py`，配置在 `~/seo/.gate.json`。

```bash
python3 tools/gate.py status          # 当前模式与队列
python3 tools/gate.py mode auto       # 关闭确认：之后直接发
python3 tools/gate.py mode confirm    # 恢复默认：只排队
python3 tools/gate.py list            # 看待确认项
python3 tools/gate.py approve <id>    # 放行
python3 tools/gate.py reject  <id> --why "品类不符"
python3 tools/gate.py flush --dry-run # 演练：把已批准项真正发出去
python3 tools/gate.py flush           # 真发（带原始回执）
```

- **默认 `confirm`**：`confirm` 模式下 `submit()` 不发请求，只把 payload 写进队列并抛 `GateBlocked`，调用方拿到 queue_id。
- **auto 模式**：同一份代码直接放行，每次放行都记 `gate_allow` 审计。
- 已接线：`tools/attempt_submit.py` 的 `submit()`（唯一的对外提交入口）、`tools/azgames_autopilot.py` 的真实 POST 分支（改为 `queued_for_confirm` 而非发送）。
- **实测验证**：对 `tacticlinks.com` 调 `submit()` → 被拦并排队 `q1117174445e8`，未发出任何请求；把该项 reject 后队列干净。

---

## 二、自动注册通道

`tools/reg_runner.py`：真实浏览器（Playwright + 本机 Chrome，持久化 profile `~/seo/.browser/profile`）逐站执行。

```bash
python3 tools/reg_runner.py --list                    # 清单与进度
python3 tools/reg_runner.py --limit 5                 # 有窗口跑（过验证概率最高）
python3 tools/reg_runner.py --headless --limit 40      # 无窗口批量
python3 tools/reg_runner.py --verify-only              # 只补验证信（可反复跑）
python3 tools/reg_runner.py --gmail-login              # 打开窗口人工登录一次 Gmail
python3 tools/reg_runner.py --dry-run --domains x.com  # 只填表不提交
```

关键设计（都是为了「自动」，但绝不硬闯）：

| 能力 | 做法 |
|---|---|
| 通用表单识别 | 不写死每站选择器：按 type/name/placeholder/label 归类 email、password、password2、username，靠 `data-blt` 索引定位 |
| 入口自发现 | 给定 URL 上没表单时，在页内按「submit/add site/aanmelden/inschrijven/register」找入口，最多试 4 个 |
| 免密码注册 | 只有邮箱字段的站（magic link / 验证码）走 `passwordless` 流程，填邮箱提交后等验证信 |
| 验证信闭环 | IMAP 优先（`mail_verify`）；IMAP 不通时退回**网页版 Gmail**（同一 profile，按 `from:域名` 搜索并点链接） |
| 卡住就停 | 人机验证、邀请码、手机号、OAuth-only 四类**只记录不硬闯**，明确标 `需人工` |
| 反假成功 | 只有出现登录态（logout/dashboard/account 链接）或验证信点了才算成功；否则记 `submit_unconfirmed` |
| 幂等 | 每站一份流水 `~/seo/.vault/reg-runs/<域名>-<时间>.jsonl`；已成功的默认跳过，`--force` 重跑 |
| 回写 | 每站结束 `POST /api/target/<id>` 写 status + owner_note，看板实时可见 |

### 状态取值（与台账对接）

| 结果 | 含义 | 台账 status |
|---|---|---|
| `registered_verified` | 注册成功且验证信已点 | working |
| `awaiting_verify` | 已提交，尚未收到/未点验证信 | working |
| `submit_unconfirmed` | 提交了但没登录态，不冒充成功 | working |
| `captcha` | 图片/人机验证拦住 | working |
| `needs_extra_field` | 必填项脚本填不了（邀请码/短信码等） | working |
| `oauth_blocked` | 只有 Google/GitHub 登录 | working |
| `no_form` | 找不到注册表单 | working |
| `already_login_ok` | 已注册且密码可登录 | working |

---

## 三、留痕位置（全部本地、可追溯）

| 路径 | 内容 |
|---|---|
| `~/seo/.vault/reg-runs/<域名>-<时间>.jsonl` | 每站逐步流水（open/entry_probe/form/submit/verify/done） |
| `~/seo/.vault/reg-runs/shots/*.jpg` | 关键阶段截图（落地页、填完、提交后、验证后） |
| `~/seo/.vault/reg-runs/summary-*.json` | 每批汇总 |
| `~/seo/.vault/azgames.poki2.online-accounts.json` | 80 站账号（0600，唯一密码，幂等不重置） |
| `~/seo/.vault/audit.log` | 凭据生成、闸门判定、放行/拒绝/flush 全审计 |
| `~/seo/.vault/send-queue.jsonl` | 待确认发送队列（含 payload 与回执） |
| `~/seo/.vault/browser-lane.jsonl` | 通道结论（人工/半自动/不可自助） |

---

## 四、当前唯一的硬阻塞：邮箱验证

IMAP 登录被 Gmail 拒绝：

```
b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'
```

`~/.sextant/poki2-gmail.env` 里填的是 12 位字母数字，**不是 Gmail 应用专用密码**（应为 16 位小写字母，需先开两步验证）。两条路，任选其一：

1. 换成真·16 位应用专用密码（自动、可批量）；
2. `python3 tools/reg_runner.py --gmail-login` 打开窗口登录一次 Gmail，之后走网页读信（不需要密码落盘，profile 存 cookie）。

在此之前，注册能跑到「提交完成」，但验证信点不了，结果如实记 `awaiting_verify` / `submit_unconfirmed`，不会写成成功。

---

## 五、80 站批次实测（2026-11-17 17:43–18:18）

80 站全跑完（每站一条流水 + 4 张截图 + 回写台账）。按每站最终结果统计：

| 结果 | 站数 | 占比 | 含义 |
|---|---|---|---|
| `no_form` | 36 | 45% | 找不到注册表单（先要作品/套餐/邀请/OAuth） |
| `captcha` | 13 | 16% | 图片或人机验证拦住 |
| `awaiting_verify` | 9 | 11% | 提交成功，等验证信（含 3 条补正的） |
| `needs_extra_field` | 7 | 9% | 必填项脚本填不了（邀请码/短信码） |
| `submit_unconfirmed` | 7 | 9% | 提交了但没登录态 |
| `error` | 5 | 6% | 超时/异常 |
| `form_error` | 3 | 4% | 站点回执报错 |
| `registered_verified` | **0** | 0% | **真正验证通过的：0** |

**为什么是 0**：邮箱通道坏了（见第四节），所有「提交成功」的站都停在等信，验证信点不了。这不是解析问题，是凭据问题。

### 已修正的假成功（重要）

批次前半段用的旧判据把 3 站记成了「注册成功并已邮箱验证」，实测都不成立，已改判并留痕：

| 站 | 实际情况 |
|---|---|
| bizcommunity.com | 停在 `AccountSignup.aspx`（URL 里带 email 参数），仍是注册页 |
| search.com | 提交后跳回首页，无登录态 |
| raindrop.io | 停在 `/account/signup`，无登录态 |

根因：`logged_in()` 把页面里的 "Sign out" 字样当登录证据，而注册页模板里本来就有。已改为「仍在 signin/signup/register URL 上一律不算登录」。

### 通道结论（可复用到其他站点）

- **荷/德老式链接目录**（jouwpagina.nl、favos.nl、uwstart.nl、eigenstart.nl、bestelinks.nl、folden.de/.info、portaportal.com、myhq.com）：注册页带图片验证码（字段 `captcha_code`），脚本不可越。
- **advertcn.com**：必填邀请码 → `needs_extra_field`。
- **openhunts.com**：只有 Google/GitHub 注册 → 提交被导向 OAuth → `oauth_blocked`（已修掉「点了 Sign up with Google 就算成功」的假阳性）。
- **devhunt.org / directorycow.com**：邮箱魔法链登录（`passwordless`），填邮箱提交即完成注册，只差点信。
- **appagg.com / findstack.com / saasaitools.com / alternative.me**：提交后进等信状态。
- **designspiration / land-book / cssdesignawards / ezilon / submitdirectory.org**：首页或提交页没有可识别表单（ezilon 的 `general_url_submission.htm` 前端无字段，疑似 JS/iframe 渲染）。

### 浏览器端「提交网站」通道（新增，默认不发送）

`reg_runner` 在找不到注册表单时，会尝试识别「提交网站」表单（有 url 字段），填好站点信息后**过闸门**：`confirm` 模式下只截图 + 入队，不发送；`mode auto` 才真发。这一条是为了接住 ezilon 这类「无账号、只有提交页」的目录，本轮尚未命中可识别表单。
