#!/usr/bin/env python3
"""用「已知真实提交路径」验证 azgames 核心目录站。

通用路径猜测命中率低（3/34），改用手工整理的行业公认提交路径逐站验证。
只采信 200 且页面命中提交语义的。
"""
import json, re, ssl, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPORTS = Path(__file__).resolve().parent.parent / "reports"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

# 行业公认的真实提交/添加路径（人工整理，非模板拼接）
KNOWN = {
    "alternativeto.net": ["/software/new", "/apps/new"],
    "producthunt.com": ["/posts/new"],
    "saashub.com": ["/submit", "/products/new"],
    "toolify.ai": ["/submit", "/submit-tool"],
    "theresanaiforthat.com": ["/submit", "/submit-a-tool"],
    "futurepedia.io": ["/submit", "/submit-tool"],
    "aitools.fyi": ["/submit"],
    "betalist.com": ["/submit", "/startups/new"],
    "microlaunch.net": ["/submit"],
    "fazier.com": ["/submit"],
    "uneed.best": ["/submit", "/submit-a-tool"],
    "startupstash.com": ["/add", "/submit"],
    "sitelike.org": ["/add-site"],
    "dmoztools.net": ["/add", "/submit"],
    "curlie.org": ["/add", "/cgi-bin/add.cgi"],
    "botw.org": ["/add", "/submit"],
    "jasminedirectory.com": ["/submit", "/add-url"],
    "crunchbase.com": ["/register", "/organizations/new"],
    "g2.com": ["/products/new", "/signup"],
    "trustpilot.com": ["/evaluate", "/signup"],
    "slashdot.org": ["/submit"],
    "folkd.com": ["/submit", "/add"],
    "diigo.com": ["/signup"],
    "getpocket.com": ["/signup"],
    "mix.com": ["/signup"],
    "flipboard.com": ["/signup", "/create"],
    "raindrop.io": ["/signup"],
    "reddit.com": ["/register"],
    "startupbuffer.com": ["/submit"],
    "launchingnext.com": ["/submit"],
    "tinylaunch.com": ["/submit"],
    "pitchwall.co": ["/submit"],
    "sideprojectors.com": ["/submit"],
    "exactly.wtf": ["/submit"],
    "f6s.com": ["/register"],
    "newsbreak.com": ["/creator", "/creator/signup"],
    "pr.com": ["/register", "/press-release"],
    "stackshare.io": ["/signup", "/tools/new"],
    "getapp.com": ["/products/new"],
    "softwareadvice.com": ["/products/new"],
    "goodfirms.co": ["/register", "/vendor/register"],
    "sortlist.com": ["/register"],
    "clutch.co": ["/register", "/get-listed"],
    "designrush.com": ["/register", "/submit"],
    "linkedin.com": ["/signup"],
    "x.com": ["/signup"],
}
SEM = re.compile(r"(?i)(submit|add\s+(a\s+)?(site|url|tool|listing|product)|"
                 r"list\s+your|sign\s*up|register|create\s+(a\s+)?(account|listing))")


def fetch(url, timeout=9):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        return r.status, r.read(120000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def probe(item):
    dom, paths = item
    for p in paths:
        code, body = fetch("https://" + dom + p)
        if code == 200 and body and SEM.search(body):
            return {"domain": dom, "entry": "https://" + dom + p,
                    "status": code, "len": len(body)}
        if code in (301, 302, 307, 308):
            return {"domain": dom, "entry": "https://" + dom + p,
                    "status": code, "len": 0}
    return {"domain": dom, "entry": "", "status": None, "len": 0}


def main():
    with ThreadPoolExecutor(max_workers=10) as ex:
        res = list(ex.map(probe, KNOWN.items()))
    ok = [r for r in res if r["entry"]]
    ok.sort(key=lambda r: r["domain"])
    print("验证到入口：%d / %d\n" % (len(ok), len(res)))
    for r in ok:
        print("  OK  %-26s %s (%s)" % (r["domain"], r["entry"], r["status"]))
    bad = [r for r in res if not r["entry"]]
    print("\n未验证 %d：%s" % (len(bad), ", ".join(r["domain"] for r in bad)))
    (REPORTS / "azgames-known-entries.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
