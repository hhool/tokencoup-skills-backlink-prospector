#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""azgames 自动化处理：把全量候选逐条过一遍「有没有一次性投递出口」，能投的直接投。

一次跑完三段，全部留下原始证据：

  1. **探活**（GET 首页）：DNS / 4xx / 5xx / Cloudflare 拦截 → 分类，不猜。
  2. **找出口**：robots.txt 允许的路径 + 首页同域链接 → 命中 submit / add-site /
     add-url / suggest 词表；解析表单，判断是不是「提交表单」而不是搜索框、
     登录框、newsletter。
  3. **真投递**（仅当表单同时满足：有 url/site/website 类字段、无密码字段、
     无 reCAPTCHA/hCaptcha/Turnstile、方法可 POST）：带 Cookie 会话 POST 一次，
     用站点自己的措辞判定 accepted / rejected / unknown。

纪律：
  * 每域最多 1 次首页 + 3 个候选入口，请求带 robots 检查，不轰站。
  * 只有站点明确给出成功措辞才算 submitted；「automated submissions are not
    accepted」这类明确拒绝单独归类，绝不记成成功。
  * 不改台账：只产出 reports/azgames-autopilot.json/.csv，入账与状态回写由
    后续步骤统一做（serve 在跑时写 targets.jsonl 会被内存态覆盖）。

用法：
  python3 tools/azgames_autopilot.py --candidates reports/azgames-fullscan-candidates.json \
      --top 200 --submit --out reports/azgames-autopilot
  python3 tools/azgames_autopilot.py --candidates ... --top 50          # 只探测不投
"""
import argparse
import csv
import http.cookiejar
import json
import re
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gate  # noqa: E402  发送闸门
from identity import identity  # noqa: E402

CST = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SITE_NAME = "Azgames"
SITE_URL = "https://azgames.poki2.online/"
SITE_DESC = ("Azgames is a free browser-game portal with instant-play HTML5 games "
             "across arcade, puzzle, action and multiplayer categories. No download, "
             "no install, works on desktop and mobile.")
SITE_TAGS = "games, browser games, html5 games, free games, arcade, puzzle"

ENTRY_PATHS = [
    "/submit", "/submit-site", "/submit-url", "/submit-a-site", "/add-site",
    "/addurl", "/add-url", "/add-link", "/addlink", "/suggest", "/suggest-site",
    "/submit.php", "/cgi-bin/submit.cgi", "/links/submit", "/directory/submit",
]
# 短链/跳转服务：能提交但对外链没意义（nofollow + 302），不算外链位
SHORTENER_RE = re.compile(
    r"(?i)(bit\.ly|tinyurl|is\.gd|ow\.ly|cutt\.ly|t\.co|rebrand\.ly|"
    r"short\.io|shorte\.st|v\.gd|goo\.gl|linktr\.ee|linkshed|shorturl|"
    r"short\.link|clck\.ru|surl\.li)")

OFFTOPIC_PATH = re.compile(
    r"(?i)(funding|milestone|press[-_]release|news[-_]release|/news|/press|"
    r"event|webinar|job|career|hiring|wedding|podcast|advertis|sponsor)")

ENTRY_WORD = re.compile(
    r"(?i)(submit|add[\s_-]?(a\s)?(site|url|link|listing|your|website)|"
    r"suggest[\s_-]?(a\s)?(site|url|link|listing)|get[\s_-]?listed|list[\s_-]?your)")

# 页面必须自己说出来「这里可以提交一个网站」，否则带 website 字段的表单
# 很可能只是注册表单（crowdreviews 的 SignupVendorNewForm）或发里程碑。
SUBMIT_TEXT = re.compile(
    r"(?i)(submit\s+(your\s+)?(site|website|url|link|listing|product|tool|"
    r"startup|project|resource|game)s?|add\s+(your\s+)?(site|website|url|link|"
    r"listing|business|product|resource)s?|suggest\s+(a\s+)?(site|url|link)|"
    r"get\s+(your\s+(site|website)\s+)?listed|list\s+your\s+(site|website|business)|"
    r"submit\s+a\s+(site|link|url))")

# 注册/账号类表单：字段或 action 命中即不当成匿名提交
SIGNUP_HINT = re.compile(r"(?i)(signup|sign_up|register|login|log_in|auth|"
                         r"account|vendor|password|member|profile)")

URL_FIELD = re.compile(
    r"(?i)^(url|website|site|siteurl|site_url|link|domain|homepage|home_page|"
    r"web|weburl|web_url|yoururl|your_url|address|siteaddress)$")
NAME_FIELD = re.compile(r"(?i)^(name|sitename|site_name|title|yourname|your_name|company)$")
EMAIL_FIELD = re.compile(r"(?i)^(email|mail|e_mail|emailaddress|email_address|contact)$")
DESC_FIELD = re.compile(r"(?i)^(desc|description|about|summary|comment|comments|message|details|notes)$")

CAPTCHA_SIGNALS = ("recaptcha", "hcaptcha", "turnstile", "cf-turnstile",
                   "g-recaptcha", "challenge-platform", "just a moment",
                   "checking your browser", "verify you are human")
LOGIN_SIGNALS = ("type=\"password\"", "sign in</a>", "sign up</a>", "login</a>",
                 "continue with google", "log in to continue")

# 宽松词（"thanks"/"success"）在侧边栏、页脚到处都有，只能当辅助信号；
# 判定成功必须有下面这种「站务口吻」的强措辞。
STRONG_SUCCESS = ("thank you for your submission", "thanks for your submission",
                  "thanks for submitting", "submitted successfully",
                  "successfully submitted", "submission received",
                  "we received your submission", "has been submitted",
                  "has been added", "successfully added", "pending review",
                  "will be reviewed", "awaiting review", "under review")
# 命中即视为「没提交成功，被要求先处理账号」
ACCOUNT_WALL = ("verify your email", "email hasn't been verified",
                "please verify your email", "confirm your email",
                "sign in to continue", "please log in", "you must be logged in",
                "login required")
ERROR_HINTS = ("required", "invalid", "already submitted", "already listed",
               "not allowed", "must have javascript", "must be a valid",
               "automated submissions are not accepted", "captcha", "error occurred")
HARD_REJECT = ("automated submissions are not accepted",
               "you must have javascript enabled",
               "must have javascript enabled to use our submission service",
               "submissions are not accepted")

CST_NOW = lambda: datetime.now(CST).isoformat(timespec="seconds")

# 单一出口只发一次：真投递有额度上限，避免一轮把她当成刷子
_SUBMIT_LOCK = threading.Lock()
_SUBMIT_BUDGET = {"left": 40}


def set_budget(n):
    _SUBMIT_BUDGET["left"] = int(n)


def reserve_submit():
    with _SUBMIT_LOCK:
        if _SUBMIT_BUDGET["left"] <= 0:
            return False
        _SUBMIT_BUDGET["left"] -= 1
        return True


def bare(url):
    d = re.sub(r"^https?://", "", str(url or "").lower()).split("/")[0]
    return d[4:] if d.startswith("www.") else d


class Session:
    """带 Cookie 的会话：CSRF/隐藏字段的流程靠它才不会第二次就 403。"""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ctx))

    def get(self, url, timeout=15):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "identity"})
        try:
            with self.op.open(req, timeout=timeout) as r:
                return {"ok": True, "status": r.status, "final_url": r.geturl(),
                        "body": r.read(500000).decode("utf-8", "replace"), "err": ""}
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read(200000)
            except Exception:
                pass
            return {"ok": False, "status": e.code, "final_url": getattr(e, "url", url),
                    "body": raw.decode("utf-8", "replace"), "err": "HTTP %s" % e.code}
        except Exception as e:                      # DNS / 超时 / TLS
            return {"ok": False, "status": 0, "final_url": url, "body": "",
                    "err": type(e).__name__ + ": " + str(e)[:120]}

    def post(self, url, data, referer, timeout=25):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer,
            "Origin": re.match(r"https?://[^/]+", url).group(0),
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"})
        try:
            with self.op.open(req, timeout=timeout) as r:
                return {"status": r.status, "final_url": r.geturl(),
                        "body": r.read(400000).decode("utf-8", "replace"), "err": ""}
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read(200000)
            except Exception:
                pass
            return {"status": e.code, "final_url": getattr(e, "url", url),
                    "body": raw.decode("utf-8", "replace"), "err": "HTTP %s" % e.code}
        except Exception as e:
            return {"status": 0, "final_url": url, "body": "",
                    "err": type(e).__name__ + ": " + str(e)[:120]}


def strip_tags(h):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h)
    t = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", t).strip()


def robots_disallow(sess, base):
    """返回 robots 里 Disallow 的前缀集合（只认 User-agent: * 段）。"""
    r = sess.get(base.rstrip("/") + "/robots.txt", timeout=8)
    if not r["ok"] or "user-agent" not in r["body"].lower():
        return []
    rules, star = [], False
    for line in r["body"].splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            star = v == "*"
        elif k == "disallow" and star and v:
            rules.append(v)
    return rules


def parse_forms(html, page_url):
    """抽出可提交表单：action / method / 可见字段 / 隐藏字段 / 按钮。"""
    forms = []
    for m in re.finditer(r"(?is)<form\b([^>]*)>(.*?)</form>", html):
        attrs, inner = m.group(1), m.group(2)
        action = re.search(r"(?i)action\s*=\s*[\"']([^\"']*)", attrs)
        method = re.search(r"(?i)method\s*=\s*[\"']?(\w+)", attrs)
        fields, hidden, has_pwd = [], {}, False
        for im in re.finditer(r"(?is)<(input|textarea|select)\b([^>]*)>", inner):
            tag, a = im.group(1).lower(), im.group(2)
            nm = re.search(r"(?i)name\s*=\s*[\"']([^\"']+)", a)
            ty = re.search(r"(?i)type\s*=\s*[\"']([^\"']+)", a)
            vl = re.search(r"(?i)value\s*=\s*[\"']([^\"']*)", a)
            if not nm:
                continue
            name = nm.group(1)
            kind = (ty.group(1) if ty else ("textarea" if tag == "textarea" else "text")).lower()
            if kind == "password":
                has_pwd = True
            if kind == "hidden":
                hidden[name] = (vl.group(1) if vl else "")
            elif kind not in ("submit", "button", "reset", "file", "image"):
                fields.append({"name": name, "type": kind})
        btn = None
        for bm in re.finditer(r"(?is)<(input|button)\b([^>]*)>", inner):
            a = bm.group(2)
            ty = re.search(r"(?i)type\s*=\s*[\"'](submit|image)", a)
            nm = re.search(r"(?i)name\s*=\s*[\"']([^\"']+)", a)
            vl = re.search(r"(?i)value\s*=\s*[\"']([^\"']*)", a)
            if ty and nm:
                btn = {"name": nm.group(1), "value": (vl.group(1) if vl else "Submit")}
                break
        if not fields:
            continue
        action_url = urllib.parse.urljoin(page_url, action.group(1)) if action and action.group(1) else page_url
        forms.append({
            "action": action_url,
            "method": (method.group(1).upper() if method else "GET"),
            "fields": fields, "hidden": hidden,
            "button": btn, "has_password": has_pwd,
        })
    return forms


def classify(html, forms, page_url, is_entry=False):
    """判定这页是不是「一次性投递出口」。

    is_entry=False 表示这是首页/普通页：只认「本页就有带 url 字段的表单」，
    不把页面上任何登录链接、任何第三方 captcha 脚本当成门槛 —— 否则每个
    带 "Sign in" 的首页都会被误判成 account_required。
    """
    low = html.lower()
    text = strip_tags(html).lower()[:200000]
    says_submit = bool(SUBMIT_TEXT.search(text))
    candidates = []
    for f in forms:
        if f["has_password"]:
            continue
        if SIGNUP_HINT.search(f["action"] or ""):
            continue
        names = [x["name"] for x in f["fields"]]
        if any(SIGNUP_HINT.search(n.replace("[]", "")) for n in names):
            continue
        url_fields = [n for n in names if URL_FIELD.match(n)]
        if not url_fields:
            # 有些站用 "url[]" / "site-url" / "link_url"
            url_fields = [n for n in names
                          if re.search(r"(?i)(url|website|sitepage|homepage|domain)", n)
                          and not re.search(r"(?i)(email|mail)", n)]
        if not url_fields:
            continue
        if len(names) < 2:
            continue
        candidates.append({"form": f, "url_fields": url_fields,
                           "name_fields": [n for n in names if NAME_FIELD.match(n)],
                           "email_fields": [n for n in names if EMAIL_FIELD.match(n)],
                           "desc_fields": [n for n in names if DESC_FIELD.match(n)]})
    if candidates:
        # 首页/普通页：页面自己没写「提交网站/添加网址」→ 这些表单不是入口
        if not is_entry and not says_submit:
            return "no_form", {}
        best = max(candidates, key=lambda c: len(c["form"]["fields"]))
        best["says_submit"] = says_submit
        best["is_entry"] = is_entry
        if best["form"]["method"] != "POST":
            return "form_get_only", {"fields": [x["name"] for x in best["form"]["fields"]],
                                     "says_submit": says_submit}
        return "anonymous_form", best
    if not is_entry:
        return "no_form", {}
    # 只有在「被识别为提交入口的页面」上，captcha / 登录墙才构成门槛
    cap = [s for s in CAPTCHA_SIGNALS if s in low]
    if cap:
        return "captcha", {"captcha": cap[:2]}
    if "type=\"password\"" in low or any(s in low for s in LOGIN_SIGNALS):
        return "account_required", {}
    return "no_form", {}


def judge_submit(resp, payload):
    """只用站点自己的措辞判定；不做「看起来像成功」的推断。

    e27 的教训：POST 落到「请先验证邮箱」页时，页面里有 "success" 字样，
    旧逻辑就会记成 submitted。现在账号墙优先判，且成功必须有强措辞。
    """
    text = strip_tags(resp["body"]).lower()
    hard = [h for h in HARD_REJECT if h in text]
    if hard:
        return "rejected_automation", hard[:2], text[:300]
    wall = [h for h in ACCOUNT_WALL if h in text]
    if wall:
        return "account_wall", wall[:2], text[:300]
    ok = [h for h in STRONG_SUCCESS if h in text]
    bad = [h for h in ERROR_HINTS if h in text]
    if resp["status"] in (200, 201, 202) and ok and not (bad and not ok):
        return "submitted", ok[:3], text[:300]
    if resp["status"] >= 400:
        return "rejected", ["HTTP %s" % resp["status"]], text[:300]
    if bad:
        return "rejected", bad[:3], text[:300]
    return "unknown", [], text[:300]


def build_payload(form, ident):
    """按表单字段名装配载荷；隐藏字段原样带上（CSRF/VIEWSTATE 必需）。"""
    data = dict(form["hidden"])
    fields = form["fields"]
    names = [f["name"] for f in fields]
    url_f = next((n for n in names if URL_FIELD.match(n)), None) or next(
        (n for n in names if re.search(r"(?i)(url|website|homepage|domain)", n)
         and not re.search(r"(?i)(email|mail)", n)), None)
    name_f = next((n for n in names if NAME_FIELD.match(n)), None)
    mail_f = next((n for n in names if EMAIL_FIELD.match(n)), None)
    desc_f = next((n for n in names if DESC_FIELD.match(n)), None)
    if url_f:
        data[url_f] = SITE_URL
    if name_f:
        data[name_f] = SITE_NAME
    if mail_f:
        data[mail_f] = ident["email"]
    if desc_f:
        data[desc_f] = SITE_DESC
    for f in fields:
        n, t = f["name"], f["type"]
        if n in data:
            continue
        if t == "checkbox":
            data[n] = "on"
        elif re.search(r"(?i)tag|keyword|categor", n):
            data[n] = SITE_TAGS
        elif t in ("text", "search", "url"):
            data[n] = SITE_NAME
    if form["button"]:
        data[form["button"]["name"]] = form["button"]["value"]
    return data


def scan_one(cand, submit=False, max_entry=3):
    dom = cand["domain"]
    sess = Session()
    rec = {"domain": dom, "source": cand.get("source"), "score": cand.get("score"),
           "started": CST_NOW()}
    if SHORTENER_RE.search(dom):
        rec["gate"] = "shortener"
        rec["done"] = CST_NOW()
        return rec
    home = sess.get("https://%s/" % dom)
    if home["status"] == 0:                      # 并发下 15s 可能只是排队
        home = sess.get("https://%s/" % dom, timeout=30)
        rec["home_retry"] = True
    rec["home_status"] = home["status"]
    rec["home_final"] = home["final_url"]
    rec["home_err"] = home["err"]
    if not home["ok"] and home["status"] in (0, 403, 429, 503):
        rec["gate"] = "unreachable" if home["status"] == 0 else "bot_blocked"
        rec["done"] = CST_NOW()
        return rec
    if home["ok"] and bare(home["final_url"] or "") not in ("", dom) \
            and not bare(home["final_url"] or "").endswith("." + dom):
        rec["gate"] = "redirect_offsite"
        rec["redirect_to"] = home["final_url"]
        rec["done"] = CST_NOW()
        return rec
    lp = home["final_url"] or ("https://%s/" % dom)
    base = "%s://%s" % (urllib.parse.urlsplit(lp).scheme or "https", dom)

    # 首页本身就是提交页？（只有本页真的带 url 字段表单才算）
    pages = []
    gate, detail = classify(home["body"], parse_forms(home["body"], lp), lp)
    if gate in ("anonymous_form", "form_get_only"):
        pages.append((lp, gate, detail))

    if not pages:
        disallow = robots_disallow(sess, base)

        def allowed(p):
            return not any(p.startswith(d) for d in disallow)

        tried = 0
        # 先看首页里自己给的链接
        links = []
        for m in re.finditer(r"(?is)<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                             home["body"] or ""):
            href, txt = m.group(1), strip_tags(m.group(2))[:60]
            if ENTRY_WORD.search(href) or ENTRY_WORD.search(txt):
                u = urllib.parse.urljoin(lp, href)
                if bare(u) == dom and u not in [x[0] for x in pages]:
                    links.append(u)
        for path in ENTRY_PATHS:
            u = base + path
            if u not in links and allowed(path):
                links.append(u)
        for u in links:
            if tried >= max_entry:
                break
            if not allowed(urllib.parse.urlsplit(u).path):
                continue
            r = sess.get(u, timeout=12)
            tried += 1
            if not r["ok"] or r["status"] >= 400:
                continue
            # 命中入口词表 / 已知路径而来 → 这是「入口页」，captcha 与登录墙才算门槛
            g, d = classify(r["body"], parse_forms(r["body"], r["final_url"]),
                            r["final_url"], is_entry=True)
            if g != "no_form":
                pages.append((r["final_url"], g, d))
                if g == "anonymous_form":
                    break
        rec["entry_pages"] = tried

    if not pages:
        rec["gate"] = "no_form"
        rec["done"] = CST_NOW()
        return rec

    # 优先级：匿名表单 > 只 GET 的表单 > 账号 > 人机验证
    order = {"anonymous_form": 0, "form_get_only": 1, "account_required": 2, "captcha": 3}
    pages.sort(key=lambda x: order.get(x[1], 9))
    entry_url, gate, detail = pages[0]
    rec["gate"] = gate
    rec["entry_url"] = entry_url
    rec["form_fields"] = ([f["name"] for f in detail["form"]["fields"]]
                          if gate in ("anonymous_form", "form_get_only") else detail.get("fields", []))

    if gate == "anonymous_form" and submit:
        # 只对「品类强相关」的候选真投：弱相关站上的 url 表单常是融资动态、
        # 商家入驻这类专用表单（e27 的 milestone、crowdreviews 的 vendor signup），
        # 往那上面塞一个游戏站是垃圾提交。弱相关的留在报告里等人看。
        generic_dir = (cand.get("source") == "submitlist"
                       or re.search(r"(?i)(directory|dir\.|links|linklist|webdir|"
                                    r"web-?dir|submit)", dom) is not None)
        # 入口页（URL/链接词表命中）上的 url 表单本身就是通用收录口，
        # 不再要求页面文案恰好出现 "submit your website"。
        eligible = cand.get("relevance") == "strong" or (
            generic_dir and (detail.get("says_submit") or detail.get("is_entry")))
        if not eligible:
            rec["submit_verdict"] = "skipped_offtopic"
            rec["submit_hint"] = "表单存在但品类不匹配且非通用目录，未投"
        elif OFFTOPIC_PATH.search(entry_url):
            rec["submit_verdict"] = "skipped_offtopic"
            rec["submit_hint"] = "入口是融资/新闻/活动类专用表单，不是站点收录"
        elif not reserve_submit():
            rec["submit_verdict"] = "skipped_budget"
            rec["submit_hint"] = "本轮投递额度已用完"
        else:
            ident = identity()
            data = build_payload(detail["form"], ident)
            # 发送闸门：默认 confirm 模式只入待确认队列，不真发
            allowed, ginfo = gate.check(
                "submit", dom, url=detail["form"]["action"], payload=data,
                note="表单字段 %s" % ",".join(sorted(data))[:160])
            if not allowed:
                rec["submit_verdict"] = "queued_for_confirm"
                rec["queue_id"] = ginfo.get("id")
                rec["submit_hint"] = ("已进待确认队列 %s（gate 默认人工确认）；"
                                      "gate.py mode auto 可关" % ginfo.get("id"))
                rec["done"] = CST_NOW()
                return rec
            resp = sess.post(detail["form"]["action"], data, referer=entry_url)
            rec["submit_action"] = detail["form"]["action"]
            rec["submit_http"] = resp["status"]
            rec["submit_final"] = resp["final_url"]
            rec["posted_fields"] = sorted(data)
            verdict, hints, excerpt = judge_submit(resp, data)
            rec["submit_verdict"] = verdict
            rec["submit_hints"] = hints
            rec["submit_excerpt"] = excerpt
            rec["submit_at"] = CST_NOW()
    rec["done"] = CST_NOW()
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--top", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--source", help="只处理某个语料来源（wdc/submitlist/seed）")
    ap.add_argument("--submit", action="store_true", help="对匿名表单发起真实 POST")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--max-entry", type=int, default=3)
    ap.add_argument("--max-submit", type=int, default=40, help="本轮最多真投几条")
    ap.add_argument("--out", default="reports/azgames-autopilot")
    args = ap.parse_args()
    set_budget(args.max_submit)

    pool = json.loads(Path(args.candidates).read_text(encoding="utf-8"))["rows"]
    pool = [c for c in pool if c.get("score", 0) >= args.min_score]
    if args.source:
        pool = [c for c in pool if c.get("source") == args.source]
    if args.top:
        pool = pool[:args.top]
    print("处理 %d 条候选（submit=%s, workers=%d）..." % (len(pool), args.submit, args.workers))

    out = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(scan_one, c, args.submit, args.max_entry): c for c in pool}
        for i, f in enumerate(futs, 1):
            try:
                out.append(f.result())
            except Exception as e:                  # 单条失败不影响整批
                c = futs[f]
                out.append({"domain": c["domain"], "gate": "error",
                            "error": type(e).__name__ + ": " + str(e)[:160]})
            if i % 25 == 0:
                print("  ... %d/%d" % (i, len(pool)))

    order = {"anonymous_form": 0, "form_get_only": 1, "account_required": 2,
             "captcha": 3, "bot_blocked": 4, "no_form": 5, "unreachable": 6, "error": 7}
    out.sort(key=lambda r: (order.get(r.get("gate"), 9), -(r.get("score") or 0)))

    from collections import Counter
    gates = Counter(r.get("gate") for r in out)
    verdicts = Counter(r.get("submit_verdict") for r in out if r.get("submit_verdict"))

    pj = ROOT / (args.out + ".json")
    pj.write_text(json.dumps({
        "generated_at": CST_NOW(), "candidates": args.candidates,
        "submit": args.submit, "processed": len(out),
        "gates": dict(gates), "verdicts": dict(verdicts), "rows": out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    pc = ROOT / (args.out + ".csv")
    with pc.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gate", "domain", "score", "source", "entry_url",
                    "submit_verdict", "submit_http", "fields", "note"])
        for r in out:
            w.writerow([r.get("gate"), r["domain"], r.get("score") or "",
                        r.get("source") or "", r.get("entry_url") or "",
                        r.get("submit_verdict") or "", r.get("submit_http") or "",
                        ",".join(r.get("form_fields") or [])[:120],
                        (r.get("submit_hint") or "")[:80]])

    print("\n出口判定：", dict(gates))
    if verdicts:
        print("真实投递结果：", dict(verdicts))
    print("→", pj, "\n→", pc)
    print("\n可投（anonymous_form）前 20：")
    n = 0
    for r in out:
        if r.get("gate") == "anonymous_form":
            n += 1
            print("  %-30s %-14s %s" % (r["domain"], r.get("submit_verdict") or "-",
                                        r.get("entry_url") or ""))
            if n >= 20:
                break
    if not n:
        print("  （0 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
