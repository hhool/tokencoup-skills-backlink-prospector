# azgames 外链域名 注册/登录/发布路径登记与归纳

生成：2026-11-17 20:16 · 数据源：reg-runs jsonl + accounts vault + targets.jsonl

## 一、整体统计

| 维度 | 分布 |
|---|---|
| 有注册留痕的域名 | 80 |
| 分类 | 🚧 通道受阻（无表单/报错/反爬） 45 · 🖐 需人工（验证码/额外字段/OAuth） 20 · ⏳ 待验证信 11 · ✅ 可发布（账号已验证/有会话） 4 |
| 登录路径类型 | register_only 55 · magic_link 22 · unknown 3 |
| 发布通道（submit_type） | register 78 · unknown 2 |

## 二、分类归纳

### 可发布（4）

- auraplusplus.com · 发布=register(w1) · 自动注册 11-17 20:04 · 自动注册成功并已邮箱验证
- findstack.com · 发布=register(w1) · 自动注册 11-17 18:53 · 自动注册成功并已邮箱验证
- openhunts.com · 发布=register(w1) · 自动注册 11-17 19:57 · 自动注册成功并已邮箱验证
- saasaitools.com · 发布=register(w1) · 自动注册 11-17 19:24 · 自动注册成功并已邮箱验证

### 待验证信（11）

- alternative.me · 发布=register(w1) · 自动注册 11-17 19:47 · 注册已提交，等待验证信（本轮未收到）
- bizcommunity.com · 发布=register(w1) · 判据修正：旧逻辑把「页面有 Sign out 字样」当登录态，实际仍在注册页；改为 awaiting_verify（停在
- devhunt.org · 发布=register(w1) · 自动注册 11-17 20:13 · 注册已提交，等待验证信（本轮未收到）
- featured.com · 发布=register(w1) · 自动注册 11-17 20:09 · 注册已提交，等待验证信（本轮未收到）
- jayisgames.com · 发布=register(w1) · 自动注册 11-17 19:51 · 注册已提交，等待验证信（本轮未收到）
- launchvault.dev · 发布=register(w1) · 自动注册 11-17 19:55 · 注册已提交，等待验证信（本轮未收到）
- raindrop.io · 发布=register(w1) · 判据修正：旧逻辑把「页面有 Sign out 字样」当登录态，实际仍在注册页；改为 awaiting_verify（停在
- search.com · 发布=register(w1) · 自动注册 11-17 19:05 · 注册已提交，等待验证信（本轮未收到）
- sidebar.io · 发布=register(w1) · 自动注册 11-17 20:15 · 注册已提交，等待验证信（本轮未收到）
- substack.com · 发布=register(w1) · 自动注册 11-17 20:16 · 注册已提交，等待验证信（本轮未收到）
- unita.co · 发布=register(w1) · 自动注册 11-17 20:02 · 注册已提交，等待验证信（本轮未收到）

### 需人工（20）

- advertcn.com · 发布=register(w1) · 自动注册 11-17 17:44 · 必填字段脚本填不了（邀请码/验证码/手机号等），需人工
- bestelinks.nl · 发布=register(w1) · 自动注册 11-17 17:46 · 注册页人机验证拦住，需人工点一次
- dev.to · 发布=register(w1) · 自动注册 11-17 17:50 · 必填字段脚本填不了（邀请码/验证码/手机号等），需人工
- eigenstart.nl · 发布=register(w1) · 自动注册 11-17 17:52 · 注册页人机验证拦住，需人工点一次
- favorietje.nl · 发布=register(w1) · 自动注册 11-17 17:54 · 注册页人机验证拦住，需人工点一次
- favos.nl · 发布=register(w1) · 自动注册 11-17 17:54 · 注册页人机验证拦住，需人工点一次
- growthhackers.com · 发布=register(w1) · 自动注册 11-17 17:58 · 注册页人机验证拦住，需人工点一次
- hashnode.com · 发布=register(w1) · 自动注册 11-17 17:58 · 必填字段脚本填不了（邀请码/验证码/手机号等），需人工
- howbrandsarebuilt.com · 发布=register(w1) · 自动注册 11-17 17:59 · 注册页人机验证拦住，需人工点一次
- jouwpagina.be · 发布=register(w1) · 自动注册 11-17 18:00 · 注册页人机验证拦住，需人工点一次
- jouwpagina.nl · 发布=register(w1) · 自动注册 11-17 18:00 · 注册页人机验证拦住，需人工点一次
- myhq.com · 发布=register(w1) · 自动注册 11-17 18:17 · 注册页人机验证拦住，需人工点一次
- portaportal.com · 发布=register(w1) · 自动注册 11-17 18:04 · 注册页人机验证拦住，需人工点一次
- pr.com · 发布=register(w1) · 自动注册 11-17 18:05 · 必填字段脚本填不了（邀请码/验证码/手机号等），需人工
- saaspirate.com · 发布=register(w1) · 自动注册 11-17 18:06 · 必填字段脚本填不了（邀请码/验证码/手机号等），需人工
- stacksocial.com · 发布=register(w1) · 自动注册 11-17 18:08 · 必填字段脚本填不了（邀请码/验证码/手机号等），需人工
- toolpilot.ai · 发布=register(w1) · 自动注册 11-17 18:10 · 注册页人机验证拦住，需人工点一次
- toolspedia.io · 发布=register(w1) · 自动注册 11-17 18:10 · 必填字段脚本填不了（邀请码/验证码/手机号等），需人工
- uwstart.nl · 发布=register(w1) · 自动注册 11-17 18:12 · 注册页人机验证拦住，需人工点一次
- webdesign-inspiration.com · 发布=register(w1) · 自动注册 11-17 18:13 · 注册页人机验证拦住，需人工点一次

### 通道受阻（45）

- acquire.com · 发布=register(w1) · 自动注册 11-17 17:43 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- aiparabellum.com · 发布=register(w1) · 自动注册 11-17 17:45 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- aixploria.com · 发布=register(w1) · 自动注册 11-17 17:45 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- amust-shop.com · 发布=register(w1) · 自动注册 11-17 17:46 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- appagg.com · 发布=register(w1) · 自动注册 11-17 17:46 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- blog4u.pl · 发布=register(w1) · 自动注册 11-17 17:47 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- community.obsidian.md · 发布=register(w1) · 自动注册 11-17 17:48 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- cssdesignawards.com · 发布=register(w1) · 自动注册 11-17 17:49 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- dealify.com · 发布=register(w1) · 自动注册 11-17 17:49 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- designspiration.com · 发布=register(w1) · 自动注册 11-17 17:50 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- directorycow.com · 发布=register(w1) · 自动注册 11-17 19:42 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- directorydepo.com · 发布=register(w1) · 自动注册 11-17 17:52 · 表单提交报错，需人工核对字段
- easywithai.com · 发布=register(w1) · 自动注册 11-17 17:52 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- escapistmagazine.com · 发布=register(w1) · 自动注册 11-17 17:52 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- extensions.blender.org · 发布=register(w1) · 自动注册 11-17 17:53 · 执行异常
- ezilon.com · 发布=register(w1) · 自动注册 11-17 18:14 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- facebook.com · 发布=unknown(w3) · 自动注册 11-17 17:54 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- flipboard.com · 发布=register(w1) · 自动注册 11-17 17:55 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- folden.de · 发布=register(w1) · 自动注册 11-17 17:55 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- folden.info · 发布=register(w1) · 自动注册 11-17 17:56 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- fupa.com · 发布=register(w1) · 自动注册 11-17 17:57 · 执行异常
- geekwire.com · 发布=register(w1) · 自动注册 11-17 17:57 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- getpocket.com · 发布=register(w1) · 自动注册 11-17 17:57 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- hostloc.com · 发布=register(w1) · 自动注册 11-17 17:59 · 执行异常
- huggingface.co · 发布=register(w1) · 自动注册 11-17 17:59 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- killerstartups.com · 发布=register(w1) · 自动注册 11-17 18:00 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- land-book.com · 发布=register(w1) · 自动注册 11-17 18:00 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- marketingwebdirectory.com · 发布=register(w1) · 自动注册 11-17 18:16 · 表单提交报错，需人工核对字段
- medium.com · 发布=register(w1) · 自动注册 11-17 18:01 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- mercurynews.com · 发布=register(w1) · 自动注册 11-17 18:02 · 执行异常
- neodia.fr · 发布=register(w1) · 自动注册 11-17 18:02 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- newsbreak.com · 发布=unknown(w3) · 自动注册 11-17 18:02 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- opencollective.com · 发布=register(w1) · 自动注册 11-17 18:03 · 表单提交报错，需人工核对字段
- openfuture.ai · 发布=register(w1) · 自动注册 11-17 18:03 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- reddit.com · 发布=register(w1) · 自动注册 11-17 18:05 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- searchmonster.org · 发布=register(w1) · 自动注册 11-17 18:07 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- startbewijs.nl · 发布=register(w1) · 自动注册 11-17 18:08 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- submitdirectory.org · 发布=register(w1) · 自动注册 11-17 18:15 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- thehiveindex.com · 发布=register(w1) · 自动注册 11-17 18:09 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- topai.tools · 发布=register(w1) · 自动注册 11-17 18:10 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- toptools.ai · 发布=register(w1) · 自动注册 11-17 18:11 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- v2ex.com · 发布=register(w1) · 自动注册 11-17 18:12 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- warriorforum.com · 发布=register(w1) · 自动注册 11-17 18:13 · 执行异常
- wellfound.com · 发布=register(w1) · 自动注册 11-17 18:13 · 未识别到注册表单（套餐/邀请码/OAuth 前置）
- yam.com · 发布=register(w1) · 自动注册 11-17 18:14 · 未识别到注册表单（套餐/邀请码/OAuth 前置）

### 死路（0）


## 三、路径明细（每域）

| 域名 | 注册入口 | 登录路径 | 验证方式 | 发布通道 | 结果 |
|---|---|---|---|---|---|
| acquire.com | https://acquire.com/sellers | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| advertcn.com | https://www.advertcn.com/member.php?mod=regist | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） needs_extra_field |
| aiparabellum.com | https://aiparabellum.com/submit-an-article/ | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| aixploria.com | https://www.aixploria.com/en/submit-ai-tool-or | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| alternative.me | https://alternative.me/signup/ | magic_link | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| amust-shop.com | https://amust-shop.com/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| appagg.com | https://appagg.com/add/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| auraplusplus.com | https://auraplusplus.com/sign-up | magic_link | imap+browser_click | register | ✅ 可发布（账号已验证/有会话） registered_verified |
| bestelinks.nl | https://bestelinks.nl/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| bizcommunity.com | https://www.bizcommunity.com/Signup.aspx?ss=ho | unknown | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| blog4u.pl | https://blog4u.pl/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| community.obsidian.md | https://community.obsidian.md | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| cssdesignawards.com | https://www.cssdesignawards.com/submit | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| dealify.com | https://dealify.com/pages/run-a-deal | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| designspiration.com | https://www.designspiration.com/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| dev.to | https://dev.to/enter?state=new-user | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） needs_extra_field |
| devhunt.org | https://devhunt.org/hackathons | register_only | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| directorycow.com | https://directorycow.com/#tab-register | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| directorydepo.com | https://directorydepo.com/register | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） form_error |
| easywithai.com | https://easywithai.com/wplp?registration=disab | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| eigenstart.nl | https://eigenstart.nl/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| escapistmagazine.com | https://escapistmagazine.com/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| extensions.blender.org | https://id.blender.org/login?next=/oauth/autho | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） error |
| ezilon.com | https://ezilon.com/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| facebook.com | https://www.facebook.com/reg | register_only | imap_watch | unknown | 🚧 通道受阻（无表单/报错/反爬） no_form |
| favorietje.nl | https://favorietje.nl/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| favos.nl | https://favos.nl/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| featured.com | https://featured.com/signup | unknown | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| findstack.com | https://findstack.com/signup | magic_link | imap+browser_click | register | ✅ 可发布（账号已验证/有会话） registered_verified |
| flipboard.com | https://flipboard.com/signup | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| folden.de | https://folden.de/ | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| folden.info | https://folden.info/ | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| fupa.com | https://fupa.com/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） error |
| geekwire.com | https://www.geekwire.com/submit-startup/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| getpocket.com | https://getpocket.com/signup | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| growthhackers.com | https://growthhackers.com/signup | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| hashnode.com | https://hashnode.com/onboard | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） needs_extra_field |
| hostloc.com | https://hostloc.com/member.php?mod=register | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） error |
| howbrandsarebuilt.com | https://howbrandsarebuilt.com/submit/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| huggingface.co | https://huggingface.co/new-space | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| jayisgames.com | https://jayisgames.com/cgi-bin/mt4/mt-cp.cgi?_ | magic_link | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| jouwpagina.be | https://jouwpagina.be/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| jouwpagina.nl | https://jouwpagina.nl/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| killerstartups.com | https://killerstartups.com/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| land-book.com | https://land-book.com/register | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| launchvault.dev | https://www.launchvault.dev/sign-up | magic_link | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| marketingwebdirectory.com | https://marketingwebdirectory.com/user/registe | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） form_error |
| medium.com | https://medium.com/m/signin | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| mercurynews.com | https://form.jotform.com/262354732716055 | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） error |
| myhq.com | https://myhq.com/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| neodia.fr | https://neodia.fr/index.php?option=com_content | magic_link | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| newsbreak.com | https://www.newsbreak.com/publisher | register_only | imap_watch | unknown | 🚧 通道受阻（无表单/报错/反爬） no_form |
| opencollective.com | https://opencollective.com/create | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） form_error |
| openfuture.ai | https://openfuture.ai/submit-tool | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| openhunts.com | https://openhunts.com/sign-up | magic_link | imap_watch | register | ✅ 可发布（账号已验证/有会话） registered_verified |
| portaportal.com | https://portaportal.com/users/register | magic_link | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| pr.com | https://www.pr.com/register | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） needs_extra_field |
| raindrop.io | https://app.raindrop.io/ | unknown | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| reddit.com | https://www.reddit.com/register | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| saasaitools.com | https://saasaitools.com/join/ | magic_link https://saasaitools.com/signin/ | imap+browser_click | register | ✅ 可发布（账号已验证/有会话） registered_verified |
| saaspirate.com | https://saaspirate.com/deals/joinsecret/ | magic_link | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） needs_extra_field |
| search.com | https://search.com/auth/sign-up | magic_link https://search.com/auth/sign-in | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| searchmonster.org | https://searchmonster.org/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| sidebar.io | https://sidebar.io/ | register_only | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| stacksocial.com | https://www.stacksocial.com/register | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） needs_extra_field |
| startbewijs.nl | https://startbewijs.nl/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| submitdirectory.org | https://submitdirectory.org/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| substack.com | https://substack.com/signup | register_only | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| thehiveindex.com | https://thehiveindex.com/submit/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| toolpilot.ai | https://www.toolpilot.ai/blogs/news/nsfw-ai-ch | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| toolspedia.io | https://toolspedia.io/submit-tool/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） needs_extra_field |
| topai.tools | https://topai.tools/submit | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| toptools.ai | https://toptools.ai/submit | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| unita.co | https://unita.co/my-account/?register | magic_link | imap_watch | register | ⏳ 待验证信 awaiting_verify |
| uwstart.nl | https://uwstart.nl/ | register_only | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| v2ex.com | https://www.v2ex.com/signup | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| warriorforum.com | https://www.warriorforum.com/register.php | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） error |
| webdesign-inspiration.com | https://www.webdesign-inspiration.com/user/def | magic_link https://www.webdesign-inspiration.c | imap_watch | register | 🖐 需人工（验证码/额外字段/OAuth） captcha |
| wellfound.com | https://wellfound.com/recruit/all-features/pos | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |
| yam.com | https://yam.com/ | register_only | imap_watch | register | 🚧 通道受阻（无表单/报错/反爬） no_form |

留痕索引：`~/.vault/reg-runs/*.jsonl`（过程）+ `~/.vault/reg-runs/shots/*.jpg`（截图） + `~/.vault/azgames.poki2.online-accounts.json`(凭据) + `audit.log`(闸门)