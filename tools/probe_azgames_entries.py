#!/usr/bin/env python3
"""实测 azgames A 档提交入口是否存在。

对候选站探测常见提交路径（/submit, /add, /submit-site, /add-your-site ...），
只有返回 200 且页面命中提交语义（submit/add/list your site）才视为「验证入口」。
避免 SPA 通配路由误报：同一站多个完全不同路径都 200 且内容一致 → 判为通配，不采信。
"""
import csv, json, re, ssl, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPORTS = Path(__file__).resolve().parent.parent / "reports"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

PATHS = ["/submit", "/submit-site", "/add", "/add-site", "/add-your-site",
         "/submit-url", "/suggest", "/directory/submit", "/list-your-site",
         "/submit-a-site", "/submit-listing"]
SEM = re.compile(r"(?i)(submit\s+(your\s+)?(site|url|link|tool|listing)|"
                 r"add\s+(your\s+)?(site|url|listing)|list\s+your\s+site|"
                 r"suggest\s+(a\s+)?(site|url)|submit\s+a\s+site|add\s+a\s+listing)")
FORM = re.compile(r"(?is)<form[^>]*>.*?(https?://|url|website|site).{0,300}?</form>")


def fetch(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        return r.status, r.read(120000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def probe(row):
    base = "https://" + row["domain"]
    hits, wildcard = [], False
    ok_pages = {}
    # 先测一个必然不存在的路径，判断是否通配路由
    code_404, _ = fetch(base + "/definitely-not-a-real-page-xyz")
    for p in PATHS:
        code, body = fetch(base + p)
        if code == 200 and body:
            ok_pages[p] = len(body)
            if SEM.search(body) or FORM.search(body):
                hits.append((p, len(body)))
    # 通配检测：不存在的路径也 200 且长度与首页接近
    if code_404 == 200:
        wildcard = True
    best = None
    if hits and not wildcard:
        best = base + hits[0][0]
    return {
        "domain": row["domain"], "category": row["category"],
        "submit_type": row["submit_type"], "fit_score": row["fit_score"],
        "verified_entry": best or "",
        "candidates": [base + h[0] for h in hits],
        "wildcard": wildcard,
        "note": ("SPA通配路由，入口不可信" if wildcard else
                 ("命中 %d 个提交页" % len(hits) if hits else "未探测到提交页，需人工找")),
    }


def main():
    rows = list(csv.DictReader(open(REPORTS / "oneshot-azgames.poki2.online.csv")))
    A_ST = {"listing", "free", "pr", "auto", "register"}
    SKIP = {"reddit.com", "discord.com", "facebook.com", "v2ex.com",
            "growthhackers.com", "warriorforum.com", "hostloc.com", "advertcn.com",
            "substack.com", "ghost.org", "medium.com", "dev.to", "hashnode.com",
            "business.google.com", "linkedin.com", "x.com", "instagram.com",
            "pinterest.com", "mastodon.social", "bsky.app", "biz.yelp.com",
            "businessconnect.apple.com", "trustpilot.com", "g2.com", "getapp.com",
            "softwareadvice.com", "crunchbase.com", "clutch.co", "designrush.com",
            "goodfirms.co", "sortlist.com", "yellowpages.com", "bingplaces.com",
            "foursquare.com", "news.ycombinator.com", "cake.me", "stackshare.io"}
    targets = [r for r in rows
               if r["submit_type"] in A_ST and r["domain"] not in SKIP
               and r["priority"] in ("P1", "P2")]
    print("探测 %d 个自助提交候选..." % len(targets))
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(probe, targets))
    results.sort(key=lambda r: (not r["verified_entry"], -int(r["fit_score"] or 0)))
    out = REPORTS / "azgames-entry-probe.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    verified = [r for r in results if r["verified_entry"]]
    print("\n验证到提交页：%d / %d" % (len(verified), len(results)))
    for r in verified:
        print("  OK  %-26s %s" % (r["domain"], r["verified_entry"]))
    print("\n未验证（需人工找）：%d" % (len(results) - len(verified)))
    for r in results:
        if not r["verified_entry"]:
            print("  --  %-26s %s" % (r["domain"], r["note"]))


if __name__ == "__main__":
    main()
