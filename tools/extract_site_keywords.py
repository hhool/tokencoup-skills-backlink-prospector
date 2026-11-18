# -*- coding: utf-8 -*-
"""Extract balancebiketoddler.com's real keyword set from its live sitemap.

Source: https://balancebiketoddler.com/sitemap.xml (266 URLs, fetched 2026-11-17)
Plus homepage H1/section assessment via WebFetch.

Why: the operator profile held only 7 hand-written balance-bike keywords,
while the site actually covers 7 product categories. balance bike backlinks
are already saturated (~1000 sites); the gap is the other 6 categories.

Output: data/keywords-balancebiketoddler.com.json (structured, traceable)
"""
import collections
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = ROOT / "data" / "bbt-sitemap.xml"
OUT = ROOT / "data" / "keywords-balancebiketoddler.com.json"

# Category definition driven by the site's own URL slugs + homepage sections.
# priority: 1 = saturation (balance bike), 2 = gap (needs backlinks).
CATEGORIES = {
    "balance bike": {
        "priority": 1, "saturated": True,
        "slug_tokens": ["balance-bike", "balance"],
        "keywords": ["balance bike", "toddler balance bike", "baby balance bike",
                     "first balance bike", "balance bike safety standards",
                     "balance bike size chart", "balance bike weight"],
    },
    "jogging stroller": {
        "priority": 2, "saturated": False,
        "slug_tokens": ["travel-stroller", "stroller", "jogging"],
        "keywords": ["jogging stroller", "best jogging stroller", "travel stroller",
                     "all-terrain stroller", "double jogging stroller",
                     "stroller wagon", "lightweight folding stroller"],
    },
    "kids bike": {
        "priority": 2, "saturated": False,
        "slug_tokens": ["kids-bike", "kids-bikes"],
        "keywords": ["kids bike", "kids bicycle", "first pedal bike",
                     "12 inch kids bike", "14 inch kids bike", "16 inch kids bike",
                     "kids bike safety standards", "kids bike recalls",
                     "kids bike size chart", "training wheels"],
    },
    "kids scooter": {
        "priority": 2, "saturated": False,
        "slug_tokens": ["kids-scooter", "scooter"],
        "keywords": ["kids scooter", "kick scooter", "electric scooter for kids",
                     "3-wheel scooter", "lean-to-steer scooter",
                     "scooter with LED wheels"],
    },
    "kids ride-on / electric car": {
        "priority": 2, "saturated": False,
        "slug_tokens": ["kids-ride", "ride-on", "kids ride on"],
        "keywords": ["kids electric car", "ride on car", "12v ride on car",
                     "24v ride on car", "ride on car with remote control",
                     "2 seater ride on", "kids ride on safety"],
    },
    "kids tricycle": {
        "priority": 2, "saturated": False,
        "slug_tokens": ["kids-tricycle", "tricycle"],
        "keywords": ["kids tricycle", "toddler tricycle", "tricycle for kids"],
    },
    "safety data & standards": {
        "priority": 2, "saturated": False,
        "slug_tokens": ["safety", "risk", "recalls", "standards"],
        "keywords": ["kids product safety standards", "cpsc recall",
                     "kids bike safety", "stroller safety standards",
                     "children product safety data", "hazard signals"],
    },
}

STOP = {"the", "a", "an", "for", "and", "or", "to", "of", "in", "on", "with",
        "best", "vs", "how", "what", "why", "buy", "guide", "reviews", "review",
        "zh", "en", "html", "com", "www", "https", "http", "sitemap"}


def load_urls():
    xml = SITEMAP.read_text(encoding="utf-8")
    return re.findall(r"<loc>(.*?)</loc>", xml)


def extract():
    urls = load_urls()
    # per-category URL evidence count (how much content exists on site)
    ev = {c: 0 for c in CATEGORIES}
    words = collections.Counter()
    bigrams = collections.Counter()
    for u in urls:
        path = urllib.parse.urlparse(u).path.strip("/")
        toks = [t for t in re.split(r"[-/]", path) if t and not t.isdigit()]
        low = path.lower()
        for c, meta in CATEGORIES.items():
            if any(tok in low for tok in meta["slug_tokens"]):
                ev[c] += 1
        for t in toks:
            if t not in STOP:
                words[t] += 1
        for i in range(len(toks) - 1):
            a, b = toks[i], toks[i + 1]
            if a not in STOP or b not in STOP:
                bigrams[a + "-" + b] += 1

    cats = []
    for c, meta in CATEGORIES.items():
        cats.append({
            "category": c,
            "priority": meta["priority"],
            "saturated": meta["saturated"],
            "site_url_evidence": ev[c],
            "keywords": meta["keywords"],
        })
    cats.sort(key=lambda x: (x["priority"], -x["site_url_evidence"]))
    return {
        "center_domain": "balancebiketoddler.com",
        "source": "live sitemap (266 URLs) + homepage H1/sections",
        "sitemap_url": "https://balancebiketoddler.com/sitemap.xml",
        "total_urls": len(urls),
        "top_words": [{"word": w, "count": n} for w, n in words.most_common(30)],
        "top_bigrams": [{"term": t, "count": n} for t, n in bigrams.most_common(25)],
        "categories": cats,
        "note": "balance bike is saturated (~1000 sites); gap = other 6 categories. "
                "Use priority-2 categories for backlink prospecting.",
    }


def main():
    data = extract()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("total urls:", data["total_urls"])
    print("\n{:<30} {:>8} {:>10} {}".format("category", "priority", "site_urls", "saturated"))
    for c in data["categories"]:
        print("{:<30} {:>8} {:>10} {}".format(
            c["category"], c["priority"], c["site_url_evidence"], c["saturated"]))
    gap_kws = [k for c in data["categories"] if c["priority"] == 2 for k in c["keywords"]]
    print("\nGAP keywords (priority 2):", len(gap_kws))
    return 0


if __name__ == "__main__":
    sys.exit(main())
