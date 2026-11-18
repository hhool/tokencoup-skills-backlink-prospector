#!/usr/bin/env python3
"""P1 实测投递探针：对每条目标做真实 HTTP 观测，判定「能否匿名一次投递」。

不做任何伪造：只有真正 POST 成功并拿到站点成功证据时才判 submitted。
其余一律按实测证据分类为 login_required / captcha / rules_forbid / dead_entry。

用法：
  python3 probe_p1_entries.py --csv reports/oneshot-azgames.poki2.online.csv \
      --priority P1 --out reports/azgames-p1-probe.json
"""
import argparse
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HDRS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
}

# 登录/账号门槛信号：命中即说明「匿名无法一次投递」
LOGIN_SIGNALS = [
    "sign in", "sign up", "log in", "login", "create an account",
    "continue with google", "continue with apple", "register", "登入", "登录",
]
# 反爬 / 人机验证信号
CAPTCHA_SIGNALS = [
    "recaptcha", "hcaptcha", "cf-chl", "just a moment", "checking your browser",
    "enable javascript and cookies", "captcha", "attention required",
    "cloudflare", "access denied", "verify you are human",
]
# 明确禁止自推 / 无法提交
RULES_FORBID = {
    "en.wikipedia.org": "维基百科禁止自推外链（WP:NOTPROMO / WP:COI），无「提交网站」入口",
    "wikipedia.org": "维基百科禁止自推外链",
}
# 已知需要付费或人工审核、没有免费自助入口
PAID_OR_REVIEW = {
    "pr.com": "免费档需注册企业账号，发布前人工审核",
}


def now_iso():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def fetch(url, timeout=15):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read(400000)
            enc = "utf-8"
            ct = r.headers.get("Content-Type", "") or ""
            m = re.search(r"charset=([\w-]+)", ct, re.I)
            if m:
                enc = m.group(1)
            try:
                body = raw.decode(enc, "replace")
            except LookupError:
                body = raw.decode("utf-8", "replace")
            return {
                "ok": 200 <= r.status < 300, "status": r.status,
                "final_url": r.geturl(), "body": body,
                "err": "", "headers": dict(r.headers),
            }
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read(200000)
        except Exception:
            pass
        try:
            body = raw.decode("utf-8", "replace")
        except Exception:
            body = ""
        return {"ok": False, "status": e.code, "final_url": e.url or url,
                "body": body, "err": "HTTP %s" % e.code, "headers": dict(e.headers or {})}
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as e:
        return {"ok": False, "status": 0, "final_url": url, "body": "",
                "err": str(getattr(e, "reason", e))[:160], "headers": {}}


def page_title(body):
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120]


def count_forms(body):
    return len(re.findall(r"<form\b", body, re.I))


def classify(domain, res):
    """返回 (gate, note)。gate ∈ submitted/login_required/captcha/rules_forbid/
    dead_entry/no_response"""
    if res["status"] == 0:
        return "no_response", "入口无响应：%s" % (res["err"] or "连接失败")
    if res["status"] in (404, 410):
        return "dead_entry", "入口 HTTP %s，路径不存在" % res["status"]
    if res["status"] in (403, 412, 429, 503):
        return "captcha", "HTTP %s（反爬/人机验证拦截，非死链）" % res["status"]

    low = res["body"].lower()
    if domain.endswith("wikipedia.org"):
        return "rules_forbid", RULES_FORBID.get("en.wikipedia.org")

    cap = [s for s in CAPTCHA_SIGNALS if s in low]
    # 注意：很多正常站点也引用 cloudflare（CDN 脚本），只有强信号才算拦截
    hard_cap = [s for s in cap if s in ("recaptcha", "hcaptcha", "captcha",
                                        "just a moment", "checking your browser",
                                        "verify you are human", "attention required")]
    if hard_cap:
        return "captcha", "页面含人机验证：%s" % ", ".join(sorted(set(hard_cap))[:3])

    # 入口页是否有「站内自助提交表单」——只有存在表单且无登录门槛才可能匿名投递
    forms = count_forms(res["body"])
    has_login_link = bool(re.search(r'href="[^"]*/(login|signin|sign-in|signup|sign-up|register|join)', low))
    login_text = [s for s in ("sign in", "log in", "login", "sign up", "register", "create an account") if s in low]

    if forms >= 1 and not has_login_link and not login_text:
        return "anonymous_form", "含 %d 个表单，未见登录门槛（可尝试匿名 POST）" % forms
    if has_login_link or login_text:
        why = []
        if has_login_link:
            why.append("入口指向登录/注册页")
        if login_text:
            why.append("页面即要求登录/注册")
        return "login_required", "；".join(why) + "（匿名无法完成投递）"
    return "dead_entry", "页面无提交表单也无登录入口，非可投递页"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--priority", default="P1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    import csv as _csv
    rows = list(_csv.DictReader(open(a.csv)))
    sel = [r for r in rows if r.get("priority") == a.priority]
    if not sel:
        print("没有 priority=%s 的记录" % a.priority, file=sys.stderr)
        return 2

    def work(r):
        url = r.get("entry_url") or r.get("url")
        res = fetch(url)
        gate, note = classify(r["domain"], res)
        return {
            "id": r["id"], "domain": r["domain"], "submit_type": r["submit_type"],
            "fit_score": r.get("fit_score"), "review": r.get("review"),
            "entry_url": url, "http_status": res["status"],
            "final_url": res["final_url"], "title": page_title(res["body"]),
            "forms": count_forms(res["body"]), "gate": gate, "note": note,
            "checked_at": now_iso(),
        }

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(work, sel))

    out = {
        "generated_at": now_iso(), "source": a.csv, "priority": a.priority,
        "count": len(results), "results": results,
    }
    with open(a.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    from collections import Counter
    print("实测 %d 条 → %s" % (len(results), a.out))
    print(Counter(r["gate"] for r in results))
    for r in results:
        print("%-24s %-14s HTTP %-4s %-14s %s" % (
            r["domain"], r["submit_type"], r["http_status"], r["gate"], r["note"][:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
