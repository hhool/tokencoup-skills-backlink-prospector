# azgames 注册路径登记（CUA 全量实测版）

生成：2026-11-17 21:45 · 邮箱 poki2.online@gmail.com · 全部实测留痕

## 本轮成果

| 站点 | 结果 | 方式 |
|---|---|---|
| favorietje.nl | ✅ registered_verified | CUA 图形验证码（第2次） |
| favos.nl | ✅ registered_verified | CUA（第2次） |
| jouwpagina.be | ✅ registered_verified | CUA（第2次） |
| bestelinks.nl | ✅ registered_verified | CUA（补验） |
| eigenstart.nl | ✅ registered_verified | 人工填码（补验） |
| portaportal.com | ⚠️ 表单填齐，reCAPTCHA 未渲染 | CUA |
| webdesign-inspiration.com | ⚠️ reCAPTCHA v2 挑战，需人工 | CUA |
| toolpilot.ai | ℹ️ 无账号体系，listing 投稿表单 | CUA 探测 |
| growthhackers.com | ❌ /signup 404 站点改版 | CUA 探测 |
| howbrandsarebuilt.com | ℹ️ /submit/ 仅邮件订阅 | CUA 探测 |

**ready（已验证可发布）共 9 站**：findstack.com / saasaitools.com / openhunts.com / auraplusplus.com / bestelinks.nl / eigenstart.nl / favorietje.nl / favos.nl / jouwpagina.be

## 可复用路径模板（新账号注册直接照做）

### 荷兰系引擎 register.php（已验证 4 站）

适用：bestelinks.nl, favorietje.nl, favos.nl, jouwpagina.be（及同引擎 uwstart.nl/jouwpagina.nl 等）

1. 打开 https://<domain>/register.php
2. 截图读图形验证码（6位大小写敏感，出错页会自带服务端新码图，直接用新码重试，勿整页刷新）
3. 点 email 输入框输入 poki2.online@gmail.com
4. 点 captcha_code 输入框输入验证码
5. 点 Register Now 提交
6. 成功标志：'A confimation mail was sent to your mailbox'

**关键经验**：提交失败后错误页会直接显示服务端新验证码图——读新码重试即可，切勿整页刷新（触发 Confirm Form Resubmission + 旧码缓存）。验证码大小写敏感，提交前用 DOM 校验输入值。

### 独立站路径

**portaportal.com** — status: `form_filled_captcha_blocked`
- 入口: https://portaportal.com/users/register
- 字段: user[email], user[nick], user[password], user[password_confirmation]
- 验证码: reCAPTCHA（控件未渲染，提交报 must be completed）

**webdesign-inspiration.com** — status: `captcha_blocked_manual`
- 入口: https://www.webdesign-inspiration.com/user/default/register
- 字段: username, email, password, occupation(select), newsletter(checkbox)
- 验证码: reCAPTCHA v2 挑战（new/audio/visual challenge）

**toolpilot.ai** — status: `wave1 listing 投递`
- 入口: https://www.toolpilot.ai/pages/submit-your-ai-tool
- listing 投稿表单（无账号体系，Shopify）
- 字段: q5_yourName[first/last], q19_company, q6_email, q112_backlinkUrl, q30_aiToolName, q34_url, q32_tagline, q33_description, q43_longText_WhatIsIt, q47_lowestPrice, 社交链接可选

**growthhackers.com** — status: `dead_path`
- /signup 404 站点改版

**howbrandsarebuilt.com** — status: `newsletter_only`
- /submit/ 仅邮件订阅，无账号注册
