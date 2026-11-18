#!/usr/bin/env python3
"""Resend 流程：对「注册已提交但站点从未发验证信」的域名——
用落盘凭据登录 → 触发重发确认信 → IMAP 即时收信验证；
登录失败（无此账号/无登录表单）→ 回退整站重注册（复用 reg_runner.run_site）。

用法:
  python3 resend_runner.py                                # 全部候选
  python3 resend_runner.py --domains a.com,b.com
  python3 resend_runner.py --verify-minutes 30 --verify-wait 180
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reg_runner as R  # noqa: E402

RESEND_WORDS = re.compile(
    r"(?i)resend|re-?send|send (again|another|me)|didn'?t (get|receive)|"
    r"verify your email|confirm your email")
LOGIN_LINK_WORDS = re.compile(r"(?i)^(log ?in|sign ?in)$")


def find_login_form(page, dom, log):
    """在当前页找登录表单（email/username + password），返回 roles 或 None。"""
    try:
        fields = page.evaluate(R.COLLECT_JS)
    except Exception:
        return None
    roles = R.classify_fields(fields)
    if (roles.get("email") or roles.get("username")) and roles.get("password"):
        return roles
    for href, txt in R.entry_links(page, dom, limit=8):
        if not LOGIN_LINK_WORDS.search(txt or ""):
            continue
        try:
            page.goto(href, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(1800)
        except Exception:
            continue
        try:
            fields = page.evaluate(R.COLLECT_JS)
        except Exception:
            continue
        roles = R.classify_fields(fields)
        if (roles.get("email") or roles.get("username")) and roles.get("password"):
            log.step("login", "entry_found", url=page.url, note="入口「%s」" % txt[:24])
            return roles
    return None


def submit_login(page, roles, acc, log):
    """填登录表单并提交。返回 True；找不到可填字段返回 False。

    策略：username 类字段（user|login 命中）优先填邮箱（WP 等站接受邮箱作用户名）；
    email 角色仅在无 username 字段时使用——避免误填同页的订阅/newsletter 邮箱框。
    """
    email = acc.get("email") or ""
    pwd = acc.get("password") or ""
    uname = acc.get("username") or "azgameshub"
    filled = []
    if roles.get("username") and roles.get("password"):
        # 登录表单：username 字段填邮箱（多数站二者皆收），失败再用 handle
        if not R.fill_field(page, roles["username"], email):
            R.fill_field(page, roles["username"], uname)
        R.fill_field(page, roles["password"], pwd)
        filled = ["username", "password"]
    elif roles.get("email") and roles.get("password"):
        R.fill_field(page, roles["email"], email)
        R.fill_field(page, roles["password"], pwd)
        filled = ["email", "password"]
    elif roles.get("email"):
        R.fill_field(page, roles["email"], email)
        filled = ["email"]
        log.step("login", "passwordless", note="无密码字段，按魔法链登录")
    else:
        return False
    log.step("login", "filled", fields=filled)
    R.shot(page, log, "lg-before-submit")
    R.click_submit(page)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    R.shot(page, log, "lg-after-submit")
    return True


def click_resend(page, log):
    """找并点击「重发验证信」类按钮/链接。"""
    try:
        texts = page.evaluate(
            """() => [...document.querySelectorAll('a,button,input[type=submit],[role=button]')]
                     .map(e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim())
                     .filter(t => t && t.length < 80)""")
    except Exception:
        return False
    seen = set()
    for t in texts or []:
        if t in seen or not RESEND_WORDS.search(t):
            continue
        seen.add(t)
        try:
            page.get_by_text(t, exact=False).first.click(timeout=6000)
            page.wait_for_timeout(2500)
            R.shot(page, log, "rs-after-click")
            log.step("resend", "clicked", note="点击「%s」" % t[:50])
            return True
        except Exception:
            continue
    return False


def login_failure(page, log):
    """登录提交后判断失败原因。返回 'no_account'|'wrong_pw'|'unknown'|None。"""
    t = R.page_text(page).lower()
    if any(k in t for k in ("no account", "not found", "doesn't exist",
                            "does not exist", "we couldn't find", "no user")):
        log.step("login", "no_account", note="站点说无此账号")
        return "no_account"
    if any(k in t for k in ("incorrect password", "wrong password",
                            "invalid credentials", "invalid username or password",
                            "incorrect email or password")):
        log.step("login", "wrong_password", note="密码被拒")
        return "wrong_pw"
    return None


GOOGLE_BTN_WORDS = re.compile(
    r"(?i)(sign[- ]?in|log[- ]?in|continue|join|sign[- ]?up|register)\s*(with)?\s*google"
    r"|with google\b|google ?id|谷歌登录|使用 google")
POKI2_EMAIL = "poki2.online@gmail.com"


def record_account(domain, acc, source, url=""):
    """OAuth 成功后把账号写入 vault（留痕）。"""
    path = os.path.expanduser("~/seo/.vault/azgames.poki2.online-accounts.json")
    try:
        data = json.load(open(path))
        data.setdefault("accounts", {})
        data["accounts"][domain] = {
            "email": acc.get("email") or POKI2_EMAIL,
            "username": acc.get("username") or "azgameshub",
            "password": acc.get("password") or "(google oauth, 无本地密码)",
            "register_url": url,
            "confidence": source,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": source,
        }
        json.dump(data, open(path, "w"), ensure_ascii=False, indent=1)
        return True
    except Exception as e:
        print("⚠ accounts 留痕失败：%s" % e, flush=True)
        return False


def try_google_oauth(ctx, page, domain, acc, log, wait_s=45):
    """回退首选：找 'Sign in with Google' 按钮并完成 OAuth。
    返回 'ok'|'no_button'|'needs_login'|'failed'。全程截图留痕。"""
    log.step("oauth", "probe_google", note="按用户策略：回退首选 Google 登录")
    clicked = False
    try:
        texts = page.evaluate(
            """() => [...document.querySelectorAll('a,button,[role=button],input[type=submit],div[role=link]')]
                     .map(e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim())
                     .filter(t => t && t.length < 90)""")
        for t in texts or []:
            if not GOOGLE_BTN_WORDS.search(t):
                continue
            try:
                page.get_by_text(t, exact=False).first.click(timeout=5000)
                clicked = True
                log.step("oauth", "clicked", note="点击「%s」" % t[:60])
                break
            except Exception:
                continue
        if not clicked:
            # Google Identity Services：跨域 iframe 里的官方按钮
            try:
                fl = page.frame_locator("iframe[src*='accounts.google.com']").first
                fl.locator("[role=button],div[role=link],button").first.click(timeout=6000)
                clicked = True
                log.step("oauth", "clicked_gsi_iframe")
            except Exception:
                pass
    except Exception as e:
        log.step("oauth", "probe_error", note=str(e)[:120])
        return "failed"
    if not clicked:
        log.step("oauth", "no_button", note="页面无 Google 登录按钮")
        return "no_button"
    R.shot(page, log, "go-after-click")

    # 等待：主页面跳 accounts.google.com 或弹出新窗口
    gp = None
    deadline = time.time() + 20
    while time.time() < deadline and gp is None:
        for p2 in ctx.pages:
            if "accounts.google.com" in (p2.url or ""):
                gp = p2
                break
        if gp is None:
            try:
                if "accounts.google.com" in (page.url or ""):
                    gp = page
            except Exception:
                pass
        if gp is None:
            time.sleep(1)
    if gp is None:
        # 没跳 Google 页：可能原地登录成功
        page.wait_for_timeout(4000)
        R.shot(page, log, "go-no-redirect")
        if R.logged_in(page):
            log.step("oauth", "ok_inplace", url=page.url, note="Google 按钮点击后直接登录")
            return "ok"
        log.step("oauth", "no_redirect", url=page.url)
        return "failed"
    try:
        gp.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass
    gp.wait_for_timeout(2500)
    R.shot(gp, log, "go-google-page")
    gmail_url = gp.url
    # 选账号（profile 有 Google 会话时出现账号选择页）
    if "chooser" in gmail_url or "SelectAccount" in gmail_url:
        try:
            gp.locator("[data-identifier*='%s'], div[email*='poki2']" % POKI2_EMAIL
                       ).first.click(timeout=8000)
            gp.wait_for_timeout(3000)
            R.shot(gp, log, "go-account-picked")
            log.step("oauth", "account_picked", note=POKI2_EMAIL)
        except Exception as e:
            log.step("oauth", "chooser_fail", note=str(e)[:120])
            return "needs_login"
    # 授权确认页（Continue/Allow）
    for word in ("Continue", "Allow", "下一步", "继续"):
        try:
            gp.get_by_role("button", name=word).first.click(timeout=4000)
            gp.wait_for_timeout(2500)
            R.shot(gp, log, "go-consent")
            log.step("oauth", "consent", note="点击「%s」" % word)
            break
        except Exception:
            continue
    # 等回到站点
    deadline = time.time() + wait_s
    while time.time() < deadline:
        cur = [p2.url or "" for p2 in ctx.pages]
        site_url = next((u for u in cur if "accounts.google.com" not in u
                         and "google.com" not in u), "")
        if site_url:
            page.wait_for_timeout(4000)
            R.shot(page, log, "go-back-site")
            t = R.page_text(page)
            if R.logged_in(page):
                log.step("oauth", "ok", url=page.url, note="Google OAuth 登录成功")
                return "ok"
            if any(k in t for k in R.VERIFY_TEXT):
                clicked2 = click_resend(page, log)
                log.step("oauth", "verify_wall", note="验证墙，重发%s"
                         % ("已点" if clicked2 else "未点"))
                return "verify_wall"
            log.step("oauth", "back_no_session", url=page.url,
                     note="回到站点但未见登录态")
            return "failed"
        if gp.is_closed() and "accounts.google.com" not in (page.url or ""):
            page.wait_for_timeout(3000)
            if R.logged_in(page):
                log.step("oauth", "ok", url=page.url, note="Google OAuth 登录成功")
                return "ok"
        time.sleep(2)
    log.step("oauth", "timeout", note="OAuth 未在 %ds 内回到站点" % wait_s)
    return "failed"


def resend_site(ctx, domain, acc, args, mailer, webmail):
    log = R.RunLog(domain)
    home = "https://%s/" % domain
    cands = [u for u in (acc.get("login_url"), acc.get("register_url"), home) if u]
    cands += [home.rstrip("/") + p for p in ("/login", "/signin", "/sign-in",
                                             "/users/sign_in")]
    seen_urls = set()
    page = ctx.new_page()
    tried_login = False
    try:
        for url in cands:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(1800)
            except Exception:
                continue
            t = R.page_text(page)
            if any(k in t for k in R.ALREADY_TEXT):
                log.step("probe", "already_registered", url=page.url)
            roles = find_login_form(page, domain, log)
            if not roles:
                continue
            if not submit_login(page, roles, acc, log):
                continue
            tried_login = True
            fail = login_failure(page, log)
            if fail:
                break  # 账号不在/密码错 → 走回退
            t2 = R.page_text(page)
            verify_wall = any(k in t2 for k in R.VERIFY_TEXT)
            if R.logged_in(page) and not verify_wall:
                log.step("login", "ok_no_wall", url=page.url,
                         note="登录成功且无验证墙——账号可用")
                out = R.finalize(domain, log, "registered_session", page.url, args)
                page.close()
                return out
            if verify_wall:
                clicked = click_resend(page, log)
                log.step("resend", "clicked" if clicked else "no_button",
                         note="重发按钮%s" % ("已点" if clicked else "未找到，等待原信"))
            elif not roles.get("password"):
                log.step("resend", "magic_sent", note="魔法链登录已请求，等信")
            v = R.verify_via_mail(ctx, page, domain, log, mailer, webmail,
                                  max(args.verify_wait, 120),
                                  imap_minutes=args.verify_minutes)
            res = {"ok": "registered_verified", "landed": "registered_verified",
                   "timeout": "awaiting_verify"}.get(v, "submit_unconfirmed")
            out = R.finalize(domain, log, res, page.url, args)
            page.close()
            return out
        if tried_login:
            out = R.finalize(domain, log, "no_form", page.url, args)
            page.close()
            return out
    except Exception as e:
        log.step("error", "crash", note=str(e)[:200])
        out = R.finalize(domain, log, "error", page.url if page else "", args)
        try:
            page.close()
        except Exception:
            pass
        return out
    # 登录通道全失败 → 回退：① Google 登录优先 ② 常规重注册（用户 2026-11-17 指定）
    try:
        page.close()
    except Exception:
        pass
    if not args.no_reregister:
        log.step("fallback", "google_first",
                 note="登录被拒/无账号 → 首选 Google 登录，其次常规注册")
        log2 = log  # 继续用同一 RunLog 留痕
        oauth_page = ctx.new_page()
        try:
            oauth_page.goto(acc.get("register_url") or ("https://%s/" % domain),
                            wait_until="domcontentloaded", timeout=40000)
            oauth_page.wait_for_timeout(2000)
            v = try_google_oauth(ctx, oauth_page, domain, acc, log2)
        except Exception as e:
            log2.step("oauth", "crash", note=str(e)[:160])
            v = "failed"
        if v == "ok":
            record_account(domain, acc, "google_oauth", url=oauth_page.url)
            out = R.finalize(domain, log2, "registered_session", oauth_page.url, args)
            oauth_page.close()
            return out
        if v == "verify_wall":
            vv = R.verify_via_mail(ctx, oauth_page, domain, log2, mailer, webmail,
                                   max(args.verify_wait, 120),
                                   imap_minutes=args.verify_minutes)
            res = {"ok": "registered_verified", "landed": "registered_verified",
                   "timeout": "awaiting_verify"}.get(vv, "submit_unconfirmed")
            out = R.finalize(domain, log2, res, oauth_page.url, args)
            oauth_page.close()
            return out
        log2.step("fallback", "google_%s" % v,
                  note="Google 通道未走通（%s）→ 回退常规注册" % v)
        oauth_page.close()
        return R.run_site(ctx, domain, acc, args, mailer, webmail)
    return R.finalize(domain, log, "no_form", "", args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", help="逗号分隔，只跑这些域")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--show", action="store_true", help="有窗口跑（默认无窗口）")
    ap.add_argument("--channel", default="chrome", help="chrome = 用真实 Chrome")
    ap.add_argument("--verify-minutes", type=int, default=30)
    ap.add_argument("--verify-wait", type=int, default=180)
    ap.add_argument("--no-writeback", action="store_true")
    ap.add_argument("--no-reregister", action="store_true",
                    help="登录失败不回退重注册")
    ap.add_argument("--slow", type=int, default=2)
    args = ap.parse_args()
    # run_site 回退所需属性（resend 流程下固定为安全值）
    args.no_crawl_entry = False
    args.resume_session = False
    args.dry_run = False
    args.always_verify = True

    accs_all = json.load(open(os.path.expanduser(
        "~/seo/.vault/azgames.poki2.online-accounts.json")))["accounts"]
    done = R.ledger_results()
    want = ("awaiting_verify", "submit_unconfirmed", "registered_unverified",
            "no_form", "form_error")
    order = [d for d, v in done.items() if v in want and d in accs_all]
    if args.domains:
        names = [x.strip() for x in args.domains.split(",") if x.strip()]
        order = [d for d in names if d in accs_all]
    if args.limit:
        order = order[:args.limit]
    if not order:
        print("没有待 resend 的站点")
        return
    print("候选 %d 站：%s" % (len(order), ", ".join(order)), flush=True)

    mailer = R.Mailer()
    if not mailer.ok:
        print("⚠ IMAP 不可用：%s" % mailer.err)

    from playwright.sync_api import sync_playwright
    os.makedirs(R.PROFILE, exist_ok=True)
    results = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            R.PROFILE, headless=not args.show,
            channel=(args.channel or None),
            viewport={"width": 1280, "height": 900}, locale="en-US",
            args=["--disable-blink-features=AutomationControlled",
                  "--no-first-run", "--no-default-browser-check"])
        try:
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        except Exception:
            pass
        webmail = None
        for i, dom in enumerate(order, 1):
            print("\n[%d/%d] %s" % (i, len(order), dom), flush=True)
            try:
                if webmail is None:
                    webmail = R.WebMail(ctx)
                r = resend_site(ctx, dom, accs_all[dom], args, mailer, webmail)
            except Exception as e:
                log = R.RunLog(dom)
                log.step("error", "crash", note=str(e)[:200])
                r = R.finalize(dom, log, "error", "", args)
            print("    → %s  %s" % (r["result"], r["note"][:90]), flush=True)
            results.append(r)
            time.sleep(args.slow)
        ctx.close()
    cnt = collections.Counter(x["result"] for x in results)
    print("\n=== 汇总", dict(cnt), flush=True)
    ts = datetime.datetime.now().strftime("summary-%Y%m%d-%H%M%S.json")
    out = os.path.join(R.RUNS, ts)
    json.dump({"ts": datetime.datetime.now().isoformat(),
               "mode": "resend", "results": results},
              open(out, "w"), ensure_ascii=False, indent=1)
    print("明细：%s" % out, flush=True)


if __name__ == "__main__":
    main()
