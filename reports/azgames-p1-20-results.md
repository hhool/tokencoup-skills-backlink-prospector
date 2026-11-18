# azgames P1 20 条实测投递结果

- 日期：2026-11-17 15:21–15:30
- 对象：`reports/oneshot-azgames.poki2.online.csv` 的 `priority=P1` 20 条
- 方法：真实 HTTP 观测（真实 UA + 跟随重定向）→ 判定「能否匿名一次投递」→ 对判为可匿名提交的站点发起真实 POST
- 结论：**20 条里 0 条可以匿名一次投递**。17 条卡在注册/登录，3 条结构上无投递出口。

## 一、逐条实测结果

| # | 域名 | 方式 | HTTP | 实测判定 | 回写 status |
|---|---|---|---|---|---|
| 1 | newsbreak.com | listing | 200 | 首页无提交表单，需 publisher 账号 | working |
| 2 | reddit.com | posting | 403 | 反爬拦截（真人可访问），需账号 | working |
| 3 | substack.com | publish | 200 | 页面即人机验证，需账号 | working |
| 4 | medium.com | publish | 403 | 反爬拦截，需账号 | working |
| 5 | facebook.com | posting | 400 | 重定向 `/login`，需账号 + 入群 | working |
| 6 | pr.com | free | 200 | 入口指向注册页，需企业账号 | working |
| 7 | featured.com | answer | 200 | 入口指向注册页 | working |
| 8 | ghost.org | publish | 200 | Ghost 是自建博客软件，非社区 | **dropped** |
| 9 | dev.to | publish | 200 | 页面即要求登录 | working |
| 10 | discord.com | posting | 200 | 需具体服务器邀请，无通用入口 | **dropped** |
| 11 | v2ex.com | posting | 403 | 反爬拦截，需账号 | working |
| 12 | hashnode.com | publish | 200 | 入口指向注册页 | working |
| 13 | advertcn.com | register | 200 | 页面即要求登录 | working |
| 14 | growthhackers.com | posting | 200 | 页面含 recaptcha | working |
| 15 | warriorforum.com | posting | 200 | 页面含 recaptcha | working |
| 16 | hostloc.com | posting | 200 | 页面即要求登录 | working |
| 17 | en.wikipedia.org | listing | 200 | 禁自推（WP:NOTPROMO / WP:COI） | **dropped** |
| 18 | raindrop.io | register | 200 | 入口指向注册页 | working |
| 19 | getpocket.com | register | 200 | 页面含 recaptcha | working |
| 20 | flipboard.com | listing | 200 | 入口指向注册页 | working |

回写结果：`working` 17 / `dropped` 3 / `done` 0。每条 `owner_note` 带实测时间、HTTP 码、门槛类型，可在看板详情区直接看到。

## 二、真实 POST 尝试（只对表单结构允许的两条）

| 站点 | 动作 | 观测 | 判定 |
|---|---|---|---|
| uneed.best | `POST /submit {name,url}` | 200，落回 `/submit-a-tool` 预览页，页面仍显示空表单 | **未提交**（是「先预览」的两步流程，不是提交端点） |
| sitelike.org | `POST /AddSite.aspx`（ViewState + url） | 200，返回说明页「去首页搜索后再提交」 | **未提交**（真实流程在首页搜索→底部表单） |
| sitelike.org | `POST /`（首页建议表单 `btnSendEmail`） | 读超时 | **无响应** |

没有伪造任何成功记录：判定为 `submitted` 需要响应里出现站点自己的成功措辞，这两条都没出现。

## 三、更大范围的实测（P2 72 条）

| 门槛类型 | 条数 | 含义 |
|---|---|---|
| captcha | 36 | Cloudflare Turnstile / reCAPTCHA，脚本无法通过 |
| login_required | 28 | 入口即注册/登录页 |
| dead_entry | 5 | 无表单无登录（含 404 / 419） |
| no_response | 3 | 超时 / TLS 中断 |
| **anonymous_form** | **0** | 无一条可匿名自助提交 |

P1 + P2 合计 92 条，`anonymous_form` = 0。即使把此前的 18 个已验证提交页（`aitools.fyi/submit`、`betalist.com/submit`、`startupstash.com/add` 等）算进来，也全部带 Turnstile / reCAPTCHA 或 JS 渲染。

**这条结论比 20 条状态更有价值**：azgames 的 wave=1「一次投递」前提在实测下不成立——它没有匿名一次投递出口，全部是「注册 → 验证 → 发帖」的多轮动作。按定义应整体归 wave=2。

## 四、注册凭据已落盘留痕

- 文件：`~/seo/.vault/azgames.poki2.online-accounts.json`（目录 0700 / 文件 0600）
- 审计：`~/seo/.vault/audit.log`（JSONL，每次写入追加）
- 内容：17 站 × 唯一 20 位字母数字密码、注册入口 URL + 入口可信度（high/medium/low）、实测门槛类型
- 幂等：同域名重跑沿用旧密码，不重置
- 邮箱统一 `poki2.online@gmail.com`，用户名 `azgameshub`，显示名 `Azgames`
- 明文存储是按你的指定（落盘留痕），文件权限已收到 0600

## 五、自动化到不了的地方（硬门槛）

1. **收验证信**：17 站的注册确认信都发到 `poki2.online@gmail.com`，当前机器上没有该邮箱的 IMAP/API 读取凭据（`~/.sextant/soundbuttons-credentials.env` 里只有 Resend 发信 key，发得出去收不回来）。
2. **人机验证**：P1 里 7 条、P2 里 36 条是 Turnstile / reCAPTCHA，纯 HTTP 提交必被拦；只有真实浏览器会话有机会过。
3. **JS 渲染表单**：uneed.best 这类 Vue 页面没有可用的服务端提交端点。

## 六、下一步 TODO

1. 打通邮箱读取（Gmail 应用专用密码）→ 注册闭环才能真正自动化。
2. 或改用已登录的真实浏览器会话（能过 Cloudflare / Turnstile）。
3. 把 azgames 的 106 条 wave=1 整体重判为 wave=2（`wave_source=explicit`），避免后续排期继续按「一次投递」错误排序。
4. 换发现源，专挖「无账号、无 captcha」的小目录（现有种子池结构上就不产出这类）。
