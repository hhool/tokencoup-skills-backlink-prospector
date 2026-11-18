#!/usr/bin/env python3
"""中长尾外链发现：只挖三类「权威度低但能直接投」的来源。

  1. 行业小目录 / 独立站友链页
  2. 老式 Web 目录（仍接受免费提交、表单简单）
  3. 细分类目博客的 resources / write-for-us 页

判定靠实测：HTTP 可达 + 页面有 url/link/site 类输入框 + 无 captcha + 无登录墙。
输出 seeds/seed-azgames-midtail.json（只留有戏的）+ reports/azgames-midtail-discovery.md
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_p1_entries import fetch, count_forms, page_title  # noqa: E402

CANDIDATES = [
    # ── 老式 Web 目录（免费提交口） ─────────────────────────────
    ("directory", "jasminedirectory.com", "https://jasminedirectory.com/submit"),
    ("directory", "somuch.com", "https://www.somuch.com/submit-links/"),
    ("directory", "viesearch.com", "https://www.viesearch.com/submit-url"),
    ("directory", "gainweb.org", "https://www.gainweb.org/submit"),
    ("directory", "01webdirectory.com", "https://www.01webdirectory.com/submit/"),
    ("directory", "dmegs.com", "https://www.dmegs.com/submit"),
    ("directory", "jayde.com", "https://www.jayde.com/submit.html"),
    ("directory", "dirjournal.com", "https://www.dirjournal.com/info/request-listing/"),
    ("directory", "submit-express.com", "https://www.submit-express.com/"),
    ("directory", "freewebsubmission.com", "https://www.freewebsubmission.com/"),
    ("directory", "sitelike.org", "https://www.sitelike.org/add-site"),
    ("directory", "brownbook.net", "https://www.brownbook.net/"),
    ("directory", "cybo.com", "https://www.cybo.com/add-business"),
    ("directory", "tupalo.co", "https://www.tupalo.co/add-business"),
    ("directory", "2findlocal.com", "https://www.2findlocal.com/add-business"),
    ("directory", "opendi.us", "https://www.opendi.us/add-listing"),
    ("directory", "bizcommunity.com", "https://www.bizcommunity.com/"),
    # ── 游戏行业小目录 / 独立站友链 ─────────────────────────────
    ("resource", "indiedb.com", "https://www.indiedb.com/games/add"),
    ("resource", "gamejolt.com", "https://gamejolt.com/games/new"),
    ("resource", "newgrounds.com", "https://www.newgrounds.com/projects/games/submit"),
    ("resource", "indiegamesplus.com", "https://indiegamesplus.com/submit-your-game"),
    ("resource", "js13kgames.com", "https://js13kgames.com/submit"),
    ("resource", "gamesnacks.com", "https://gamesnacks.com/"),
    ("resource", "html5games.com", "https://html5games.com/submit"),
    ("resource", "freewebarcade.com", "https://www.freewebarcade.com/submit"),
    ("resource", "arcadeboss.com", "https://www.arcadeboss.com/submit"),
    ("resource", "construct.net", "https://www.construct.net/en/game-assets"),
    ("resource", "itch.io", "https://itch.io/game/new"),
    # ── 细分类目博客 resources / write-for-us ───────────────────
    ("resource", "gamedeveloper.com", "https://www.gamedeveloper.com/"),
    ("resource", "gamersdecide.com", "https://www.gamersdecide.com/write-for-us"),
    ("resource", "indiegamebundles.com", "https://www.indiegamebundles.com/submit"),
    ("resource", "gamedev.net", "https://www.gamedev.net/"),
    ("resource", "80.lv", "https://80.lv/"),
    ("resource", "gamedeveloperblog.com", "https://gamedeveloperblog.com/"),
]

CAPTCHA = ("recaptcha", "hcaptcha", "turnstile", "just a moment", "verify you are human", "cf-chl")
LOGIN = ("sign in to continue", "log in to continue", "please log in", "login required")
URL_FIELD = re.compile(r'name="[^"]*(url|link|site|website|domain)[^"]*"', re.I)


def probe(cat, domain, url):
    r = fetch(url, timeout=20)
    low = r["body"].lower()
    cap = [c for c in CAPTCHA if c in low]
    login = [l for l in LOGIN if l in low]
    has_url_field = bool(URL_FIELD.search(r["body"]))
    forms = count_forms(r["body"])
    if r["status"] == 0:
        verdict = "no_response"
    elif r["status"] in (404, 410):
        verdict = "dead"
    elif r["status"] in (403, 412, 429, 503):
        verdict = "bot_blocked"
    elif cap:
        verdict = "captcha"
    elif login:
        verdict = "needs_login"
    elif has_url_field and forms >= 1:
        verdict = "submittable"
    elif forms >= 1:
        verdict = "form_unclear"
    else:
        verdict = "no_form"
    return {
        "category": cat, "domain": domain, "entry_url": url,
        "http": r["status"], "final_url": r["final_url"], "title": page_title(r["body"]),
        "forms": forms, "url_field": has_url_field, "captcha": cap, "login_wall": login,
        "verdict": verdict,
    }


def main():
    out = [probe(*c) for c in CANDIDATES]
    from collections import Counter
    print("实测 %d 条 →" % len(out), dict(Counter(x["verdict"] for x in out)))
    for x in out:
        print("%-24s %-6s %-13s http=%-4s forms=%d urlfield=%d %s" % (
            x["domain"], x["category"][:6], x["verdict"], x["http"], x["forms"],
            x["url_field"], x["title"][:40]))

    seeds = [{"domain": x["domain"], "url": x["entry_url"], "category": x["category"],
              "submit_url": x["entry_url"] if x["verdict"] == "submittable" else "",
              "how": "站内提交表单（实测有 url 输入框）" if x["verdict"] == "submittable"
                     else "实测：%s" % x["verdict"],
              "note": (x["title"] or "")[:80], "cost": "free", "effort": "low",
              "submit_type": "listing", "geo": "global", "language": "en"}
             for x in out if x["verdict"] in ("submittable", "form_unclear")]

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "seeds", "seed-azgames-midtail.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(seeds, f, ensure_ascii=False, indent=1)
    with open(os.path.join(root, "reports", "azgames-midtail-raw.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n可用种子 %d 条 → %s" % (len(seeds), path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
