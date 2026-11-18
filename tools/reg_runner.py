#!/usr/bin/env python3
"""自动注册执行器：真实浏览器（持久化 profile）+ IMAP 验证信闭环。

设计原则
- 最大化自动：通用表单识别（不写死每站选择器）+ 邮箱验证自动点 + 会话持久化复用；
- 卡住就停：人机验证/短信/邀请码这类只记录不硬闯，留给人工一次点击；
- 全程留痕：每站一个 JSONL 步骤流水 + 关键阶段截图，落 ~/seo/.vault/reg-runs/；
- 幂等：已注册成功的域默认跳过（--force 重跑）。

用法
  python3 tools/reg_runner.py --limit 5                 # 有窗口跑 5 站（过验证概率最高）
  python3 tools/reg_runner.py --domains reddit.com,dev.to
  python3 tools/reg_runner.py --headless --limit 20      # 无窗口批量（省事但更易被拦）
  python3 tools/reg_runner.py --list                    # 看清单与进度
"""
import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from identity import identity  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_DIR = os.path.expanduser("~/seo/.vault")
ACCOUNTS = os.path.join(VAULT_DIR, "azgames.poki2.online-accounts.json")
RUNS = os.path.join(VAULT_DIR, "reg-runs")
SHOTS = os.path.join(RUNS, "shots")
PROFILE = os.path.expanduser("~/seo/.browser/profile")
SITE_DIR = os.path.expanduser("~/seo/azgames.poki2.online")
BASE = "http://127.0.0.1:8765"

CST = timezone(timedelta(hours=8))

REQUIRED_EMPTY_JS = r"""
() => {
  const out = [];
  for (const el of document.querySelectorAll('input,textarea,select')) {
    const box = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || box.width < 4) continue;
    const t = (el.getAttribute('type') || '').toLowerCase();
    if (['hidden','submit','button','image','file'].includes(t)) continue;
    if (el.value && el.value.trim()) continue;
    if (el.checked) continue;
    if (!el.required && el.getAttribute('aria-required') !== 'true') continue;
    out.push((el.getAttribute('placeholder') || el.name || el.id || t).slice(0, 40));
  }
  return out;
}
"""

CAPTCHA_SEL = ("iframe[src*='recaptcha']", "iframe[src*='hcaptcha']",
               "iframe[src*='challenges.cloudflare.com']", ".cf-turnstile",
               "#cf-challenge-running", "div[class*='captcha']")

VERIFY_TEXT = ("verify your email", "confirm your email", "check your inbox",
               "check your email", "we sent", "verification email",
               "activate your account", "verify your account", "magic link",
               "verify your address", "确认邮件", "验证邮箱")
DONE_TEXT = ("welcome", "you're in", "your account is ready", "account created",
             "signed up", "you are now registered", "thanks for signing up",
             "setup your profile", "complete your profile")
ALREADY_TEXT = ("already registered", "email has been taken", "already taken",
                "already exists", "already in use", "account with this email exists",
                "this email is already")
ERROR_TEXT = ("invalid", "required", "must be", "too short", "does not match",
              "didn't match", "error", "failed", "not allowed", "try again",
              "incorrect", "captcha", "blocked", "denied")


def now_iso():
    return datetime.now(CST).isoformat(timespec="seconds")


def ensure_dirs():
    for d in (RUNS, SHOTS):
        os.makedirs(d, exist_ok=True)
    try:
        os.chmod(VAULT_DIR, 0o700)
    except OSError:
        pass


# ---------------- 留痕 ----------------
class RunLog:
    def __init__(self, domain):
        ensure_dirs()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = domain.replace("/", "_")
        self.path = os.path.join(RUNS, "%s-%s.jsonl" % (safe, stamp))
        self.domain = domain
        self.rows = []

    def step(self, phase, result, **kw):
        rec = {"ts": now_iso(), "domain": self.domain, "phase": phase,
               "result": result}
        rec.update({k: v for k, v in kw.items() if v not in (None, "", [])})
        self.rows.append(rec)
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec


def shot(page, log, phase):
    try:
        p = os.path.join(SHOTS, "%s-%s-%s.jpg" % (
            log.domain.replace("/", "_"), phase,
            datetime.now().strftime("%H%M%S")))
        page.screenshot(path=p, quality=70, type="jpeg")
        return p
    except Exception:
        return ""


def lane_append(domain, phase, result, url="", note=""):
    """并入既有浏览器通道台账，便于 lane.py writeback 统一回写。"""
    try:
        from lane import append
        append({"ts": now_iso(), "domain": domain, "phase": phase,
                "result": result, "lane": "browser", "url": url, "note": note})
    except Exception:
        pass


# ---------------- 表单识别 ----------------
COLLECT_JS = r"""
() => {
  const out = [];
  const nodes = document.querySelectorAll('input,textarea,select');
  let i = 0;
  for (const el of nodes) {
    el.setAttribute('data-blt', String(i));
    const st = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    const visible = st.display !== 'none' && st.visibility !== 'hidden'
                    && box.width > 4 && box.height > 4;
    let label = '';
    if (el.id) {
      const l = document.querySelector('label[for="' + el.id + '"]');
      if (l) label = l.innerText || '';
    }
    if (!label) {
      const p = el.closest('label');
      if (p) label = p.innerText || '';
    }
    out.push({
      idx: i,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      name: (el.getAttribute('name') || '').toLowerCase(),
      id: (el.id || '').toLowerCase(),
      ph: (el.getAttribute('placeholder') || '').toLowerCase(),
      ac: (el.getAttribute('autocomplete') || '').toLowerCase(),
      label: (label || '').trim().slice(0, 60).toLowerCase(),
      required: el.required || el.getAttribute('aria-required') === 'true',
      visible: visible,
      value: (el.value || '').slice(0, 40),
      checked: !!el.checked
    });
    i++;
  }
  return out;
}
"""

BUTTONS_JS = r"""
() => {
  const out = [];
  const nodes = document.querySelectorAll("button, input[type=submit], input[type=button], a[role=button]");
  let i = 0;
  for (const el of nodes) {
    el.setAttribute('data-blt-btn', String(i));
    const box = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    out.push({
      idx: i,
      text: ((el.innerText || el.value || '') + '').trim().slice(0, 60).toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      visible: st.display !== 'none' && box.width > 4 && box.height > 4,
      disabled: !!el.disabled
    });
    i++;
  }
  return out;
}
"""

PWD_JS = r"""
() => {
  const el = document.querySelector("input[type=password]");
  if (!el) return {ok: true};
  try {
    if (window.__blt_typed) return {ok: true};
    window.__blt_typed = 1;
  } catch (e) {}
  return {ok: true};
}
"""


def pick(fields, kinds):
    for k in kinds:
        for f in fields:
            if not f["visible"]:
                continue
            hay = " ".join([f["name"], f["id"], f["ph"], f["label"], f["ac"]])
            if re.search(k, hay):
                return f
    return None


def classify_fields(fields):
    """把页面字段映射到注册所需角色。通用优先，不依赖具体站点。"""
    email = pick(fields, [r"e-?mail", r"^mail$"])
    if not email:
        for f in fields:
            if f["visible"] and f["type"] == "email":
                email = f
                break
    pwd = [f for f in fields if f["visible"] and f["type"] == "password"]
    user = None
    for f in fields:
        if not f["visible"] or f["type"] == "password" or f is email:
            continue
        hay = " ".join([f["name"], f["id"], f["ph"], f["label"]])
        if re.search(r"user|handle|nick|login|screen.?name|display", hay):
            user = f
            break
    if not user:
        for f in fields:
            if not f["visible"] or f["type"] == "password" or f is email:
                continue
            if f["type"] in ("text", "search", "") and not f["value"]:
                hay = " ".join([f["name"], f["id"], f["ph"], f["label"]])
                if not re.search(r"search|query|phone|company|website|url|code|city", hay):
                    user = f
                    break
    return {"email": email, "password": pwd[0] if pwd else None,
            "password2": pwd[1] if len(pwd) > 1 else None, "username": user}


URL_FIELD = re.compile(r"(?i)(url|website|site|link|homepage|domain|adres)")


def pick_submit_form(page):
    """识别「提交网站」类表单（不是注册）：有 url 字段 + 至少一个文本字段。"""
    try:
        fields = page.evaluate(COLLECT_JS)
    except Exception:
        return None
    vis = [f for f in fields if f["visible"] and f["type"] not in ("hidden", "submit",
                                                                  "button", "password")]
    url_f = None
    for f in vis:
        hay = " ".join([f["name"], f["id"], f["ph"], f["label"]])
        if URL_FIELD.search(hay) and not re.search(r"(?i)(email|mail)", hay):
            url_f = f
            break
    if not url_f:
        return None
    email_f = pick(vis, [r"e-?mail"])
    title_f = pick(vis, [r"title|name|site.?name|nombre|titel"])
    desc_f = pick(vis, [r"desc|about|summary|comment|beschreib|omschrijv"])
    return {"url": url_f, "email": email_f, "title": title_f, "desc": desc_f,
            "all": [f["name"] or f["type"] for f in vis][:12]}


SUBMIT_VALUES = {
    "title": "Azgames", "desc": None,  # 描述按站点类型给
}


def try_submit_path(page, domain, log, args, ident):
    """站点的真实出口是「提交网站」而不是注册时走这里。发送仍过闸门。"""
    form = pick_submit_form(page)
    if not form:
        return None
    desc = ("Azgames is a free browser-game site with instant-play HTML5 games "
            "and no downloads or installs.")
    filled = []
    for role, val in (("url", "https://azgames.poki2.online/"),
                      ("title", "Azgames"), ("desc", desc),
                      ("email", ident.get("email") or "")):
        f = form.get(role)
        if f and val:
            if fill_field(page, f, val):
                filled.append(role)
    log.step("submit", "filled", url=page.url, fields=filled,
             note="识别为「提交网站」表单（非注册）")
    shot(page, log, "sub-filled")
    if not filled:
        return None
    try:
        empty = page.evaluate(REQUIRED_EMPTY_JS)
    except Exception:
        empty = []
    if args.dry_run:
        return "submit_dry_run"
    payload = {"url": "https://azgames.poki2.online/", "title": "Azgames"}
    if form.get("email"):
        payload["email"] = ident.get("email") or ""
    if form.get("desc"):
        payload["description"] = desc
    import gate as _gate
    allowed, info = _gate.check("submit", domain, url=page.url, payload=payload,
                               note="浏览器通道填表提交（必填未填：%s）" % (empty or "无"))
    if not allowed:
        log.step("submit", "queued", url=page.url, queue_id=info.get("id"),
                 note="已进待确认队列（gate 默认人工确认）")
        return "submit_queued"
    before = page.url
    click_submit(page)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    txt = page_text(page)
    shot(page, log, "sub-after")
    ok = [k for k in ("thank", "submitted", "received", "pending review",
                      "added", "will be reviewed", "success") if k in txt]
    bad = [k for k in ("error", "invalid", "required", "not allowed", "captcha")
           if k in txt]
    log.step("submit", "result", url=page.url, ok=ok[:3], bad=bad[:3])
    if ok and not (bad and not ok):
        return "submitted_ok"
    if bad:
        return "submit_failed"
    return "submit_unknown"


def fill_field(page, f, value):
    try:
        el = page.locator('[data-blt="%d"]' % f["idx"])
        el.click(timeout=3000)
        el.fill("", timeout=3000)
        el.type(value, delay=25, timeout=6000)
        return True
    except Exception:
        try:
            page.evaluate("""(a) => {const el=document.querySelector('[data-blt="'+a.i+'"]');
                if(!el) return; const s=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
                s.call(el,a.v); el.dispatchEvent(new Event('input',{bubbles:true}));
                el.dispatchEvent(new Event('change',{bubbles:true}));}""",
                          {"i": f["idx"], "v": value})
            return True
        except Exception:
            return False


def click_submit(page):
    try:
        btns = page.evaluate(BUTTONS_JS)
    except Exception:
        btns = []
    pref = ("sign up", "signup", "register", "create account", "create your account",
            "join", "continue", "get started", "submit", "agree", "next")
    oauth = re.compile(r"(?i)(google|github|apple|facebook|microsoft|twitter|discord|"
                       r"linkedin|gitlab|continue with|sign in with|"
                       r"search|zoeken|find|filter|subscribe|newsletter|cancel|back)")
    cands = [b for b in btns if b["visible"] and not b["disabled"]
             and not oauth.search(b["text"] or "")]
    for want in pref:
        for b in cands:
            if want in b["text"]:
                try:
                    page.locator('[data-blt-btn="%d"]' % b["idx"]).click(timeout=4000)
                    return b["text"]
                except Exception:
                    continue
    for b in cands:
        if b["type"] == "submit":
            try:
                page.locator('[data-blt-btn="%d"]' % b["idx"]).click(timeout=4000)
                return b["text"] or "submit"
            except Exception:
                continue
    try:
        page.keyboard.press("Enter")
        return "enter-key"
    except Exception:
        return ""


ENTRY_WORDS = re.compile(
    r"(?i)(sign[\s_-]?up|register|registreren|registrieren|aanmelden|inschrijven|"
    r"join|create.{0,12}account|submit|add.{0,8}(site|url|link)|toevoegen|"
    r"suggest|get.{0,8}listed|mitmachen|anmelden|inscrire)")


def entry_links(page, dom, limit=4):
    """在页面里找「注册/提交」入口。老站导航写的是 Submit link / Aanmelden 这类词。"""
    try:
        raw = page.eval_on_selector_all(
            "a", "els => els.map(e => [e.href, ((e.innerText||'')+'').trim().slice(0,50)])")
    except Exception:
        return []
    import urllib.parse as up
    scored = []
    for href, txt in raw or []:
        if not href or not href.startswith("http"):
            continue
        host = up.urlsplit(href).netloc.lower().replace("www.", "")
        if dom not in host and host not in dom:
            continue
        low = (href + " " + txt).lower()
        if re.search(r"logout|sign[\s_-]?out|privacy|terms|contact|advertis|language", low):
            continue
        score = 0
        if ENTRY_WORDS.search(txt):
            score += 2
        if ENTRY_WORDS.search(href):
            score += 2
        if re.search(r"(register|signup|sign-up|join|aanmelden|submit)", low):
            score += 1
        if score:
            scored.append((score, href, txt))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _s, href, txt in scored:
        if href in seen:
            continue
        seen.add(href)
        out.append((href, txt))
        if len(out) >= limit:
            break
    return out


def page_text(page):
    try:
        return (page.inner_text("body", timeout=6000) or "").lower()
    except Exception:
        return ""


def has_captcha(page):
    for sel in CAPTCHA_SEL:
        try:
            if page.locator(sel).count() > 0:
                return sel
        except Exception:
            continue
    return ""


def wait_captcha_solved(page, timeout_s, log):
    """有窗模式：脚本已填好表单，停在此处等人工点掉人机验证。返回 True=已解除。"""
    deadline = time.time() + max(timeout_s, 30)
    log.step("captcha", "waiting_human",
             note="%d 秒内请在浏览器窗口人工点掉人机验证（表单已填好）" % max(timeout_s, 30))
    shot(page, log, "captcha-waiting")
    while time.time() < deadline:
        try:
            if not has_captcha(page):
                log.step("captcha", "solved", note="验证码已解除，继续")
                shot(page, log, "captcha-solved")
                return True
        except Exception:
            return False
        time.sleep(4)
    log.step("captcha", "human_timeout", note="人工未在限时内解除")
    return False


def logged_in(page):
    """有登录后特征才算账号真的建成了，避免「提交后跳了个页」就宣布成功。"""
    try:
        txt = page_text(page)
    except Exception:
        return False
    u0 = page.url.lower()
    # 还在注册/登录流程页上，「Sign out」这类字样常来自导航或模板，不能当登录证据
    if re.search(r"(signin|sign-in|signup|sign-up|register|login|accountsignup)", u0):
        return False
    marks = ("log out", "logout", "sign out", "signout", "my account", "your profile",
             "dashboard", "settings", "log uit", "abmelden")
    if any(m in txt for m in marks):
        return True
    u = page.url.lower()
    if any(k in u for k in ("/dashboard", "/account", "/profile", "/settings", "/app")):
        return True
    try:
        if page.locator("a[href*='logout'], a[href*='signout'], a[href*='log-out']").count():
            return True
    except Exception:
        pass
    return False


def classify_outcome(page, before_url):
    url = page.url
    txt = page_text(page)
    if "accounts.google.com" in url or "oauth" in url.lower() or "signin/oauth" in url:
        return "oauth_blocked", {"url": url, "why": "跳到第三方 OAuth 登录页，非本站注册"}
    cap = has_captcha(page)
    moved = url.rstrip("/") != before_url.rstrip("/")
    if any(k in txt for k in ALREADY_TEXT):
        return "already_registered", {"url": url, "why": "页面说已注册/邮箱已占用"}
    if any(k in txt for k in VERIFY_TEXT):
        return "verify_email", {"url": url, "why": "页面要求验证邮箱"}
    if cap and not moved:
        return "captcha", {"url": url, "why": "人机验证组件存在且未跳转", "sel": cap}
    if moved and any(k in txt for k in DONE_TEXT):
        return "registered", {"url": url, "why": "跳转且出现登录后文案"}
    if moved:
        return "registered_unconfirmed", {"url": url, "why": "已跳转但无明确文案"}
    errs = [k for k in ERROR_TEXT if k in txt]
    if errs:
        return "form_error", {"url": url, "errs": errs[:4]}
    return "unknown", {"url": url}


# ---------------- 邮箱闭环 ----------------
class Mailer:
    def __init__(self):
        self.ok = False
        self.err = ""
        try:
            from mail_verify import load_password, connect
            pw, _ = load_password()
            if not pw:
                self.err = "未配置应用专用密码"
                return
            self.conn = connect(pw)
            self.ok = True
        except Exception as e:
            self.err = str(e)

    def links_for(self, domain, minutes=15):
        if not self.ok:
            return []
        try:
            from mail_verify import fetch_recent
            msgs = fetch_recent(self.conn, minutes=minutes, want_domain=domain, limit=8)
        except Exception as e:
            self.err = str(e)
            return []
        out = []
        for m in msgs:
            for u in m.get("links") or []:
                if u.lower().startswith("http"):
                    out.append({"url": u, "subject": m.get("subject", ""),
                                "from": m.get("from", "")})
        return out

    def refresh(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.conn.select("INBOX")
        except Exception:
            pass


VERIFY_WORD = re.compile(r"(?i)(verif|confirm|activat|validat|welcome|token|magic|"
                         r"onboard|set-?up|start|sign-?in|log-?in)")


# ---------------- 网页版邮箱读验证信（IMAP 不通时的第二条路） ----------------
class WebMail:
    """用同一个浏览器 profile 打开 Gmail 网页读验证信。

    前提：这个 profile 已登录过一次 Gmail（`reg_runner.py --gmail-login` 或人工）。
    好处：不依赖应用专用密码，验证信和注册在同一浏览器里闭环。
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.page = None
        self.ok = None
        self.why = ""

    def ensure(self):
        if self.page is not None and not self.page.is_closed() and self.ok is not None:
            return self.ok
        try:
            self.page = self.ctx.new_page()
            self.page.goto("https://mail.google.com/mail/u/0/",
                           wait_until="domcontentloaded", timeout=50000)
            self.page.wait_for_timeout(4500)
            u = self.page.url
            if "accounts.google.com" in u or "/signin" in u:
                self.ok = False
                self.why = "profile 未登录 Gmail"
            else:
                self.ok = True
        except Exception as e:
            self.ok = False
            self.why = str(e)[:120]
        return self.ok

    def links_for(self, domain, timeout_wait=8000):
        if not self.ensure():
            return []
        q = "from:%s" % domain
        try:
            self.page.goto("https://mail.google.com/mail/u/0/#search/" + q,
                           wait_until="domcontentloaded", timeout=45000)
            self.page.wait_for_timeout(4000)
            self.page.reload(wait_until="domcontentloaded")
            self.page.wait_for_timeout(timeout_wait // 2)
        except Exception:
            return []
        try:
            raw = self.page.eval_on_selector_all(
                "a", "els => els.map(e => [e.href, (e.innerText||'').slice(0,80)])")
        except Exception:
            return []
        import urllib.parse as up
        out = []
        for href, txt in raw or []:
            if not href or not href.startswith("http"):
                continue
            real = href
            if "google.com/url" in href:
                m = re.search(r"[?&]q=([^&]+)", href)
                if m:
                    real = up.unquote(m.group(1))
            low = (real + " " + txt).lower()
            if not VERIFY_WORD.search(low):
                continue
            if "mail.google.com" in real or "accounts.google.com" in real:
                continue
            out.append({"url": real, "subject": txt, "from": domain})
        seen, uniq = set(), []
        for o in out:
            if o["url"] not in seen:
                seen.add(o["url"])
                uniq.append(o)
        return uniq[:8]



def verify_via_mail(ctx, page, domain, log, mailer, webmail, wait_s, interval=20,
                    imap_minutes=20):
    deadline = time.time() + wait_s
    seen = set()
    imap_dead = not (mailer and mailer.ok)
    while time.time() < deadline:
        links = []
        if not imap_dead:
            mailer.refresh()
            links = mailer.links_for(domain, minutes=imap_minutes)
            if mailer.err:
                imap_dead = True
                log.step("verify_email", "imap_failed", note=mailer.err[:160])
        if not links and webmail is not None:
            links = webmail.links_for(domain)
            if not links and webmail.ok is False:
                log.step("verify_email", "webmail_unavailable", note=webmail.why)
                webmail = None
        links = [l for l in links if l["url"] not in seen]
        links.sort(key=lambda l: (0 if VERIFY_WORD.search(l["url"]) else 1, len(l["url"])))
        for l in links:
            seen.add(l["url"])
            log.step("verify_email", "link_found", url=l["url"][:180],
                     note="主题：%s" % (l.get("subject") or "")[:80])
            try:
                page.goto(l["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                txt = page_text(page)
                shot(page, log, "verified")
                bad = [k for k in ("expired", "invalid", "not valid", "used already")
                       if k in txt]
                if bad:
                    log.step("verify_email", "link_rejected", url=page.url, errs=bad)
                    continue
                if any(k in txt for k in ("verified", "confirmed", "activated",
                                          "thanks", "welcome", "success")) or \
                        any(k in page.url.lower() for k in ("welcome", "dashboard",
                                                            "onboard", "home")):
                    log.step("verify_email", "ok", url=page.url)
                    return "ok"
                log.step("verify_email", "landed", url=page.url,
                         note="落地页无明确措辞，按已打开处理")
                return "landed"
            except Exception as e:
                log.step("verify_email", "error", note=str(e)[:200])
        time.sleep(interval)
    log.step("verify_email", "timeout", note="%ds 内未收到可用验证信" % wait_s)
    return "timeout"


# ---------------- 单站执行 ----------------
def run_site(ctx, domain, acc, args, mailer, webmail=None):
    log = RunLog(domain)
    url = acc.get("register_url") or ""
    log.step("open", "start", url=url)
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        log.step("open", "ok", url=page.url, note=page.title()[:90])
        shot(page, log, "01-landing")

        # 已经登录？直接算通过
        t = page_text(page)
        if any(k in t for k in ("log out", "logout", "sign out")) and args.resume_session:
            log.step("session", "reused", url=page.url, note="已存在登录态")
            return finalize(domain, log, "session_reused", page.url, args)

        fields = page.evaluate(COLLECT_JS)
        roles = classify_fields(fields)
        need = [k for k in ("email", "password") if not roles.get(k)]
        if need and not args.no_crawl_entry:
            for href, txt in entry_links(page, domain):
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=35000)
                    page.wait_for_timeout(1800)
                except Exception:
                    continue
                fields = page.evaluate(COLLECT_JS)
                cand = classify_fields(fields)
                log.step("form", "entry_probe", url=page.url,
                         note="页内入口「%s」→ 字段 %s" % (
                             txt[:24], ",".join(sorted(k for k, v in cand.items() if v)) or "无"))
                if cand.get("email") and cand.get("password"):
                    roles = cand
                    need = []
                    break
        passwordless = False
        if need:
            cap = has_captcha(page)
            if cap and getattr(args, "human_pause", 0):
                # 有窗人工模式：先等人点掉验证码，再重新识别表单
                if wait_captcha_solved(page, args.human_pause, log):
                    page.wait_for_timeout(1500)
                    fields = page.evaluate(COLLECT_JS)
                    roles = classify_fields(fields)
                    need = [k for k in ("email", "password") if not roles.get(k)]
                    cap = ""
                else:
                    log.step("form", "blocked_by_captcha", url=page.url,
                             note="注册表单前置人机验证（%s），人工未解除" % cap)
                    shot(page, log, "02-captcha")
                    return finalize(domain, log, "captcha", page.url, args)
            if cap:
                log.step("form", "blocked_by_captcha", url=page.url,
                         note="注册表单前置人机验证（%s），脚本无法越过" % cap,
                         fields=[f["name"] or f["type"] for f in fields][:10])
                shot(page, log, "02-captcha")
                return finalize(domain, log, "captcha", page.url, args)
            if roles.get("email") and "password" in need:
                # 免密码注册（magic link / 邮箱验证码）：只填邮箱也能走完
                passwordless = True
                log.step("form", "passwordless", url=page.url,
                         note="无密码字段，按「邮箱魔法链」流程处理")
            else:
                log.step("form", "no_signup_form", url=page.url,
                         note="未识别到注册字段：缺 %s（页面可能先要选套餐/邀请码/OAuth）"
                              % ",".join(need),
                         fields=[f["name"] or f["type"] for f in fields][:10])
                shot(page, log, "02-noform")
                sub = try_submit_path(page, domain, log, args, identity())
                if sub:
                    return finalize(domain, log, sub, page.url, args)
                return finalize(domain, log, "no_form", page.url, args)

        # 填表
        email = acc.get("email") or ""
        pwd = acc.get("password") or ""
        uname = acc.get("username") or "azgameshub"
        filled = []
        plan = [("username", uname), ("email", email), ("password", pwd),
                ("password2", pwd)]
        if passwordless:
            plan = [("username", uname), ("email", email)]
        for role, val in plan:
            f = roles.get(role)
            if f and val:
                if fill_field(page, f, val):
                    filled.append(role)
        log.step("form", "filled", fields=filled, url=page.url)

        # 勾选条款类复选框
        try:
            checks = page.locator("input[type=checkbox]")
            n = checks.count()
            checked = 0
            for i in range(n):
                el = checks.nth(i)
                if el.is_visible() and not el.is_checked():
                    el.check(timeout=1500, force=True)
                    checked += 1
            if checked:
                log.step("form", "checkboxes", note="勾选 %d 个复选框" % checked)
        except Exception:
            pass

        if args.dry_run:
            log.step("submit", "dry_run", url=page.url)
            shot(page, log, "03-filled")
            return finalize(domain, log, "dry_run", page.url, args)

        shot(page, log, "03-filled")
        try:
            empty = page.evaluate(REQUIRED_EMPTY_JS)
        except Exception:
            empty = []
        if empty:
            log.step("form", "needs_extra_field", url=page.url,
                     note="必填但脚本填不了：%s" % ", ".join(empty[:6]))
            return finalize(domain, log, "needs_extra_field", page.url, args)
        before = page.url
        clicked = click_submit(page)
        log.step("submit", "clicked", note=clicked or "(enter)", url=before)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3500)
        outcome, detail = classify_outcome(page, before)
        shot(page, log, "04-after-submit")
        log.step("submit", outcome, **detail)

        verified = None
        if outcome in ("verify_email", "registered_unconfirmed", "registered"):
            if outcome == "verify_email" or args.always_verify:
                verified = verify_via_mail(ctx, page, domain, log, mailer, webmail,
                                           args.verify_wait,
                                           imap_minutes=getattr(args, "verify_minutes", 20) or 20)
            else:
                verified = "not_required"

        if outcome == "registered_unconfirmed" and not logged_in(page):
            log.step("submit", "submit_unconfirmed", url=page.url,
                     note="提交后未见登录态，不判定为注册成功")
            return finalize(domain, log, "submit_unconfirmed", page.url, args)
        if outcome == "already_registered":
            # 试登录一次，确认密码可用
            state = try_login(page, acc, log)
            return finalize(domain, log, "already_" + state, page.url, args)
        if outcome in ("captcha",):
            if getattr(args, "human_pause", 0) and wait_captcha_solved(
                    page, args.human_pause, log):
                outcome, detail = classify_outcome(page, before)
                log.step("submit", outcome, **detail)
                if outcome == "captcha":
                    return finalize(domain, log, "captcha", page.url, args)
            else:
                return finalize(domain, log, "captcha", page.url, args)
        if outcome == "form_error":
            return finalize(domain, log, "form_error", page.url, args)
        if verified in ("ok", "landed"):
            return finalize(domain, log, "registered_verified", page.url, args)
        if outcome == "verify_email" or passwordless:
            return finalize(domain, log, "awaiting_verify", page.url, args)
        if logged_in(page):
            return finalize(domain, log, "registered_session", page.url, args)
        # 提交了、但既没跳成功页也没有登录态：如实记「未证实」，不冒充成功
        return finalize(domain, log, "submit_unconfirmed", page.url, args)
    except Exception as e:
        log.step("run", "error", note=str(e)[:300], tb=traceback.format_exc()[-600:])
        try:
            shot(page, log, "99-error")
        except Exception:
            pass
        return finalize(domain, log, "error", "", args)
    finally:
        try:
            page.close()
        except Exception:
            pass


def try_login(page, acc, log):
    """已注册的站试一次登录，能进就说明密码有效、会话可复用。"""
    try:
        txt = page_text(page)
        if not any(k in txt for k in ("log in", "sign in", "login")):
            return "unknown"
        page.goto(acc.get("login_url") or page.url, wait_until="domcontentloaded",
                  timeout=30000)
        page.wait_for_timeout(1500)
        fields = page.evaluate(COLLECT_JS)
        roles = classify_fields(fields)
        if not roles["email"] or not roles["password"]:
            return "unknown"
        fill_field(page, roles["email"], acc.get("email") or "")
        fill_field(page, roles["password"], acc.get("password") or "")
        click_submit(page)
        page.wait_for_timeout(4000)
        t = page_text(page)
        if any(k in t for k in ("log out", "logout", "sign out", "dashboard", "profile")):
            log.step("login", "ok", url=page.url)
            return "login_ok"
        log.step("login", "failed", url=page.url, note="未见登录后元素")
        return "login_failed"
    except Exception as e:
        log.step("login", "error", note=str(e)[:160])
        return "login_error"


RESULT_STATUS = {
    "registered_verified": ("working", "自动注册成功并已邮箱验证"),
    "registered_unverified": ("working", "自动注册已提交，未见验证要求"),
    "session_reused": ("working", "会话复用，站点已登录"),
    "awaiting_verify": ("working", "注册已提交，等待验证信（本轮未收到）"),
    "captcha": ("working", "注册页人机验证拦住，需人工点一次"),
    "no_form": ("working", "未识别到注册表单（套餐/邀请码/OAuth 前置）"),
    "needs_extra_field": ("working", "必填字段脚本填不了（邀请码/验证码/手机号等），需人工"),
    "oauth_blocked": ("working", "站点只有第三方 OAuth 登录，无法用邮箱密码注册"),
    "registered_session": ("working", "注册后已持登录态（站点未要求验证信）"),
    "submit_unconfirmed": ("working", "已提交但未见登录态，待验证信或人工确认"),
    "submit_queued": ("working", "提交表单已填好，进待确认队列（gate）"),
    "submitted_ok": ("done", "浏览器通道提交并拿到站点成功回执"),
    "submit_failed": ("dropped", "浏览器通道提交被站点拒绝"),
    "submit_unknown": ("working", "浏览器通道提交无明确回执"),
    "sub_dry_run": ("working", "提交表单仅填写未发送（dry-run）"),
    "form_error": ("working", "表单提交报错，需人工核对字段"),
    "already_login_ok": ("working", "站点已注册且密码可登录"),
    "unknown": ("working", "注册结果不明"),
    "error": ("working", "执行异常"),
    "dry_run": ("working", "仅填表未提交（dry-run）"),
}


def finalize(domain, log, result, url, args):
    status, why = RESULT_STATUS.get(result, ("working", "未分类结果"))
    note = "自动注册 %s · %s" % (now_iso()[5:16].replace("T", " "), why)
    log.step("done", result, url=url, note=note)
    lane_append(domain, "signup", result if result in
                ("registered_verified", "captcha", "form_error", "no_form")
                else result, url=url, note=note)
    if not args.no_writeback:
        writeback(domain, status, note)
    return {"domain": domain, "result": result, "url": url, "note": note,
            "log": log.path}


def writeback(domain, status, note):
    try:
        import urllib.request
        tid = None
        with open(os.path.join(SITE_DIR, "targets.jsonl")) as f:
            for line in f:
                t = json.loads(line)
                if t.get("domain") == domain:
                    tid = t["id"]
                    break
        if not tid:
            return False
        req = urllib.request.Request(
            "%s/api/target/%s" % (BASE, tid),
            data=json.dumps({"status": status, "owner_note": note}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=12) as r:
            r.read()
        return True
    except Exception:
        return False


# ---------------- 清单 ----------------
def load_accounts():
    with open(ACCOUNTS) as f:
        return json.load(f)


def ledger_results():
    """从 reg-runs 汇总每域最好结果，用于幂等跳过（按时间戳取最新，避免文件序覆盖）。"""
    out = {}
    ts_of = {}
    if not os.path.isdir(RUNS):
        return out
    for name in os.listdir(RUNS):
        if not name.endswith(".jsonl"):
            continue
        dom = name.rsplit("-", 2)[0]
        try:
            for line in open(os.path.join(RUNS, name)):
                r = json.loads(line)
                if r.get("phase") == "done":
                    t = r.get("ts") or ""
                    if t >= ts_of.get(dom, ""):
                        ts_of[dom] = t
                        out[dom] = r.get("result")
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", default="", help="逗号分隔，只跑这些域")
    ap.add_argument("--limit", type=int, default=0, help="最多跑几站")
    ap.add_argument("--headless", action="store_true", help="无窗口（更快更易被拦）")
    ap.add_argument("--channel", default="chrome", help="chrome = 用真实 Chrome")
    ap.add_argument("--dry-run", action="store_true", help="只填表不提交")
    ap.add_argument("--force", action="store_true", help="已成功的也重跑")
    ap.add_argument("--verify-wait", type=int, default=150, help="等验证信秒数")
    ap.add_argument("--verify-minutes", type=int, default=20,
                    help="IMAP 只看最近 N 分钟的邮件（补验历史注册时调大，如 600）")
    ap.add_argument("--human-pause", type=int, default=0,
                    help="遇人机验证暂停 N 秒等人工点掉（0=关闭；有窗模式建议 240）")
    ap.add_argument("--always-verify", action="store_true")
    ap.add_argument("--no-writeback", action="store_true")
    ap.add_argument("--resume-session", action="store_true", default=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--slow", type=int, default=0, help="每站之间停顿秒数")
    ap.add_argument("--no-crawl-entry", action="store_true",
                    help="不在页内找注册入口（只认给定 URL）")
    ap.add_argument("--verify-only", action="store_true",
                    help="只补验证：对 awaiting_verify/submit_unconfirmed 的站再读一次信")
    ap.add_argument("--gmail-login", action="store_true",
                    help="打开浏览器人工登录 Gmail 一次，之后自动读信可用")
    args = ap.parse_args()

    data = load_accounts()
    accs = data["accounts"]
    done = ledger_results()
    order = sorted(accs)
    if args.domains:
        wanted = [d.strip() for d in args.domains.split(",") if d.strip()]
        order = [d for d in wanted if d in accs]
    if args.list:
        for d in order:
            print("%-26s %-14s %s" % (d, done.get(d, "-"), accs[d].get("register_url")))
        print("\n合计 %d 站，已执行 %d 站" % (len(order), len(done)))
        return
    if not args.force:
        skip = {"registered_verified", "registered_session", "session_reused",
                "already_login_ok"}
        order = [d for d in order if done.get(d) not in skip]
    if args.limit:
        order = order[:args.limit]
    if args.verify_only:
        want = ("awaiting_verify", "submit_unconfirmed", "registered_unverified")
        if args.domains:
            # 显式点名 = 用户强制指定，跳过状态过滤
            wanted = {d.strip() for d in args.domains.split(",") if d.strip()}
            order = [d for d in order if d in wanted]
        else:
            order = [d for d in order if done.get(d) in want]
        args.force = True
        if not order:
            print("没有待补验证的站点")
            return
    if not order:
        print("没有待执行的站点（全部已完成，--force 可重跑）")
        return

    if args.gmail_login:
        from playwright.sync_api import sync_playwright
        os.makedirs(PROFILE, exist_ok=True)
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                PROFILE, headless=False, channel=(args.channel or None),
                viewport={"width": 1280, "height": 900}, locale="en-US",
                args=["--disable-blink-features=AutomationControlled"])
            pg = ctx.new_page()
            pg.goto("https://accounts.google.com/ServiceLogin?service=mail",
                    wait_until="domcontentloaded", timeout=60000)
            print("请在打开的窗口里登录 poki2.online@gmail.com（最多等 5 分钟）…")
            deadline = time.time() + 300
            ok = False
            while time.time() < deadline:
                time.sleep(3)
                try:
                    u = pg.url
                except Exception:
                    break
                if "mail.google.com" in u:
                    ok = True
                    break
            print("登录%s。profile 已保存：%s" % ("成功" if ok else "未完成", PROFILE))
            lane_append("gmail", "login", "ok" if ok else "timeout",
                        url="https://mail.google.com/", note="网页邮箱通道登录")
            ctx.close()
        return

    mailer = Mailer()
    if not mailer.ok:
        print("⚠ IMAP 不可用：%s" % mailer.err)
        print("  → 改用网页版 Gmail 读验证信（需 profile 已登录；--gmail-login 可打开登录）")

    from playwright.sync_api import sync_playwright
    os.makedirs(PROFILE, exist_ok=True)
    results = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            headless=args.headless,
            channel=(args.channel or None),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled",
                  "--no-first-run", "--no-default-browser-check"],
        )
        try:
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        except Exception:
            pass
        webmail = None
        for i, dom in enumerate(order, 1):
            print("\n[%d/%d] %s" % (i, len(order), dom), flush=True)
            if args.verify_only:
                log = RunLog(dom)
                pg = ctx.new_page()
                try:
                    pg.goto(accs[dom].get("register_url") or ("https://%s/" % dom),
                            wait_until="domcontentloaded", timeout=40000)
                    pg.wait_for_timeout(1500)
                except Exception:
                    pass
                if webmail is None:
                    webmail = WebMail(ctx)
                v = verify_via_mail(ctx, pg, dom, log, mailer, webmail,
                                    max(args.verify_wait, 60),
                                    imap_minutes=getattr(args, "verify_minutes", 20) or 20)
                res = {"ok": "registered_verified", "landed": "registered_verified",
                       "timeout": "awaiting_verify"}.get(v, "submit_unconfirmed")
                r = finalize(dom, log, res, pg.url, args)
                try:
                    pg.close()
                except Exception:
                    pass
                print("    → %s  %s" % (r["result"], r["note"][:90]), flush=True)
                results.append(r)
                continue
            if webmail is None and not args.headless:
                webmail = WebMail(ctx)
            r = run_site(ctx, dom, accs[dom], args, mailer, webmail)
            print("    → %s  %s" % (r["result"], r["note"][:90]), flush=True)
            results.append(r)
            if args.slow:
                time.sleep(args.slow)
        ctx.close()

    ensure_dirs()
    outp = os.path.join(RUNS, "summary-%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    with open(outp, "w") as f:
        json.dump({"ts": now_iso(), "mode": "headless" if args.headless else "headful",
                   "results": results}, f, ensure_ascii=False, indent=1)
    from collections import Counter
    print("\n=== 汇总", dict(Counter(r["result"] for r in results)))
    print("明细：%s" % outp)


if __name__ == "__main__":
    main()
