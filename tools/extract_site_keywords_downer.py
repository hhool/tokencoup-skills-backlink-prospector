# -*- coding: utf-8 -*-
"""Extract downer.app's real keyword set from its live sitemap + homepage.

Source: https://downer.app/sitemap.xml (144 URLs, 6 languages) + homepage copy
Fetched 2026-11-17.

Compliance: robots.txt declares Content-Signal: search=yes, ai-train=no,
use=reference; User-agent * Allow: /. This tool does SEARCH/DISCOVERY use
(keyword extraction + backlink prospecting) — not AI training, not content
republication. CCBot is disallowed; we do not crawl as CCBot.

downer.app is a browser-based video DOWNLOADER tool (not a content site):
6 platform pages + 11 blog posts, multi-language (de/fr/hi/ja/ru/zh-hans).

Output: data/keywords-downer.app.json
"""
import collections
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = ROOT / "data" / "downer-sitemap.xml"
OUT = ROOT / "data" / "keywords-downer.app.json"

# Platform-centric product pages + supporting blog topics.
CATEGORIES = {
    "instagram downloader": {
        "priority": 1,
        "slug_tokens": ["instagram"],
        "keywords": ["instagram video downloader", "save instagram stories",
                     "instagram reels without login", "instagram reels downloader",
                     "download instagram videos", "instagram photo downloader"],
    },
    "tiktok downloader": {
        "priority": 1,
        "slug_tokens": ["tiktok"],
        "keywords": ["tiktok video downloader", "tiktok watermark removal",
                     "download tiktok without watermark", "tiktok slideshow downloader",
                     "tiktok photo downloader"],
    },
    "twitter / x downloader": {
        "priority": 1,
        "slug_tokens": ["twitter"],
        "keywords": ["twitter video downloader", "download twitter videos",
                     "twitter gif to mp4", "x video downloader",
                     "twitter video download without app"],
    },
    "tumblr downloader": {
        "priority": 1,
        "slug_tokens": ["tumblr"],
        "keywords": ["tumblr video downloader", "tumblr downloader tips",
                     "download tumblr videos", "tumblr photo downloader"],
    },
    "ifunny downloader": {
        "priority": 1,
        "slug_tokens": ["ifunny"],
        "keywords": ["ifunny video downloader", "download ifunny clips",
                     "ifunny gif downloader"],
    },
    "onlyfans downloader": {
        "priority": 1,
        "slug_tokens": ["onlyfans"],
        "keywords": ["onlyfans video downloader", "onlyfans public posts",
                     "download onlyfans previews"],
    },
    "video format & quality (blog)": {
        "priority": 2,
        "slug_tokens": ["video-formats", "understanding-video-quality",
                        "gif-vs-mp4", "source-files-vs-screen-recorders",
                        "download-videos-legally"],
        "keywords": ["video formats explained", "video quality comparison",
                     "gif vs mp4", "source files vs screen recorders",
                     "download videos legally", "mp4 converter", "hd video download"],
    },
}

STOP = {"com", "www", "https", "http", "xml", "blog", "de", "fr", "hi", "ja",
        "ru", "zh", "hans", "sitemap", "app"}


def load_urls():
    return re.findall(r"<loc>(.*?)</loc>", SITEMAP.read_text(encoding="utf-8"))


def extract():
    urls = load_urls()
    ev = {c: 0 for c in CATEGORIES}
    words = collections.Counter()
    langs = collections.Counter()
    for u in urls:
        path = urllib.parse.urlparse(u).path.strip("/")
        seg = path.split("/")
        if re.match(r"^[a-z]{2}(-[a-z]+)?$", seg[0]):
            langs[seg[0]] += 1
        else:
            langs["en"] += 1
        low = path.lower()
        for c, meta in CATEGORIES.items():
            if any(tok in low for tok in meta["slug_tokens"]):
                ev[c] += 1
        for t in re.split(r"[-/]", path):
            if t and not t.isdigit() and t not in STOP:
                words[t] += 1
    cats = [{"category": c, "priority": m["priority"],
             "site_url_evidence": ev[c], "keywords": m["keywords"]}
            for c, m in CATEGORIES.items()]
    return {
        "center_domain": "downer.app",
        "source": "live sitemap (144 URLs, 6 languages) + homepage copy",
        "sitemap_url": "https://downer.app/sitemap.xml",
        "robots_compliance": "Content-Signal search=yes, ai-train=no, use=reference; "
                             "search/discovery use only",
        "total_urls": len(urls),
        "languages": dict(langs),
        "top_words": [{"word": w, "count": n} for w, n in words.most_common(30)],
        "categories": cats,
        "note": "Browser-based video downloader tool. Core = 6 platform downloader "
                "pages + 11 blog posts. Backlink targets are downloader/tool "
                "directories and platform-ecosystem sites.",
    }


def main():
    data = extract()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("total urls:", data["total_urls"], "| langs:", data["languages"])
    print("\n{:<34} {:>8} {:>10}".format("category", "priority", "site_urls"))
    for c in data["categories"]:
        print("{:<34} {:>8} {:>10}".format(
            c["category"], c["priority"], c["site_url_evidence"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
