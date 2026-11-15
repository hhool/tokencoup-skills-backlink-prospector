#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Meme radar (G3): daily scan of 5 trend sources -> on-site hit check -> action board.

PRD §0.5 G3 / §9 Q5 decision (2026-11-15): runs as an INDEPENDENT cron (never
inside the prospector tick — a scraping failure must not stall the quota
engine). Output lands in data/meme-radar/ as JSON + a human-readable
three-column board (meme word -> on-site hit -> action). The tick and the
human each consume it on their own schedule.

Sources (each independent; a failing source never fails the run):
  1. Google Trends daily RSS (US)          https://trends.google.com/trending/rss?geo=US
  2. Reddit rising (r/dankmemes, r/memes)  https://www.reddit.com/r/<sub>/rising/.rss
  3. Know Your Meme trending page          https://knowyourmeme.com/trendingpage
  4. TikTok Creative Center hashtags       (best effort; datacenter/JS-gated, may stay unavailable)
  5. 9gag hot posts JSON                   https://9gag.com/v1/group-posts/type/hot

On-site hit check is a polite read-only GET against the production search API
(/api/sounds?q=<term>&limit=3) — at most --max-probe calls per run.

Usage:
  python3 tools/meme_radar.py                      # one run, writes data/meme-radar/
  python3 tools/meme_radar.py --limit 15           # probe only top 15 candidates
  python3 tools/meme_radar.py --selftest           # offline fixture test

Output JSON: {"meta": {...source statuses...}, "rows": [{"term", "sources",
"hits", "hit_titles", "action"}]}
"""

import argparse
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "meme-radar"

USER_AGENT = "meme-radar/1.0 (soundbuttons.cc outreach tooling; contact links-cc@soundbuttons.cc)"
TIMEOUT = 15

# Words too generic to be a meme lead, or too short to be a phrase.
STOPWORDS = {
    "the", "and", "for", "you", "your", "with", "this", "that", "have", "not",
    "are", "was", "how", "why", "what", "when", "who", "new", "best", "top",
    "official", "video", "full", "part", "update", "news", "live", "today",
    "game", "games", "vs", "ep", "episode", "season", "trailer", "watch",
}
MIN_TERM_LEN = 4

REDDIT_SUBS = ["dankmemes", "memes"]


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        return resp.read().decode("utf-8", "replace")


def _clean_term(text):
    """Normalize a raw title into a candidate meme phrase, or None."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"[\"'“”‘’\[\](){}]+", "", t)
    t = re.sub(r"\s*[|·—–-]\s*.*$", "", t).strip()  # drop site-suffixes after separators
    words = [w for w in re.split(r"[^A-Za-z0-9']+", t) if w]
    if not words or len(words) > 4:
        return None
    if any(w.lower() in STOPWORDS for w in words):
        return None
    if any(len(w) < MIN_TERM_LEN for w in words if not w.isdigit()):
        return None
    if sum(ch.isdigit() for ch in t) > len(t) / 2:
        return None
    return " ".join(words)


# ---------------------------------------------------------------- sources ---

def src_google_trends():
    """Google Trends daily RSS (US): <item><title>term</title>."""
    xml_text = _fetch("https://trends.google.com/trending/rss?geo=US")
    root = ET.fromstring(xml_text)
    return [(item.findtext("title") or "").strip() for item in root.iter("item")]


def src_reddit_rising():
    """Reddit rising RSS for the meme subs: <entry><title>...</title>."""
    titles = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for sub in REDDIT_SUBS:
        try:
            xml_text = _fetch(f"https://www.reddit.com/r/{sub}/rising/.rss")
            root = ET.fromstring(xml_text)
            for entry in root.findall("a:entry", ns):
                titles.append((entry.findtext("a:title", "", ns) or "").strip())
        except Exception:
            continue  # one sub failing must not sink the source
    if not titles:
        raise RuntimeError("all reddit subs failed")
    return titles


_KYM_LINK_RE = re.compile(r'href="(/memes/[a-z0-9-]+)"[^>]*>([^<]{2,60})<', re.I)


def src_know_your_meme():
    """KYM trending page: trending meme entry links."""
    html = _fetch("https://knowyourmeme.com/trendingpage")
    out = []
    for slug, label in _KYM_LINK_RE.findall(html):
        term = _clean_term(label)
        if term:
            out.append(term)
    if not out:  # fallback: slugs alone carry the phrase
        for slug, _ in _KYM_LINK_RE.findall(html):
            term = _clean_term(slug.replace("/memes/", "").replace("-", " "))
            if term:
                out.append(term)
    if not out:
        raise RuntimeError("no trending entries parsed")
    return out


def src_tiktok_hashtags():
    """Best effort: TikTok Creative Center popular hashtags.

    The page is JS-gated and the internal API moves; this source is allowed to
    stay unavailable without affecting the run (PRD §9 Q5).
    """
    url = (
        "https://ads.tiktok.com/creative_center/api/v2/hashtag/list?"
        + urllib.parse.urlencode(
            {"page": 1, "limit": 20, "period": 7, "country_code": "US"}
        )
    )
    data = json.loads(_fetch(url))
    items = (data.get("data") or {}).get("list") or []
    out = []
    for it in items:
        name = it.get("hashtag_name") or it.get("name") or ""
        term = _clean_term(name.lstrip("#"))
        if term:
            out.append(term)
    if not out:
        raise RuntimeError("tiktok api returned no usable hashtags")
    return out


_9GAG_POST_RE = re.compile(r'"title"\s*:\s*"([^"]{6,120})"')


def src_9gag_hot():
    """9gag hot posts JSON API: post titles."""
    data = _fetch("https://9gag.com/v1/group-posts/type/hot")
    return _9GAG_POST_RE.findall(data)


SOURCES = [
    ("google_trends", src_google_trends),
    ("reddit_rising", src_reddit_rising),
    ("know_your_meme", src_know_your_meme),
    ("tiktok_hashtags", src_tiktok_hashtags),
    ("9gag_hot", src_9gag_hot),
]


# ------------------------------------------------------------ hit + action --

def site_hits(term, api_base="https://soundbuttons.cc", limit=3):
    """Read-only production search. Returns (count, [titles])."""
    url = f"{api_base}/api/sounds?q={urllib.parse.quote(term)}&limit={limit}"
    try:
        data = json.loads(_fetch(url))
        rows = data.get("data") or []
        return len(rows), [r.get("title", "") for r in rows]
    except Exception:
        return -1, []  # -1 = probe failed; do not invent a verdict


def action_for(hits, hit_titles):
    if hits < 0:
        return "probe-failed：下次运行重查，不记结论"
    if hits == 0:
        return "缺口：CC0 补源进候选池（贴合调性才收，不硬凑）"
    if hits >= 3:
        return "已有库：出合集页/看板 + 内链 audio-editor 页"
    return f"已有 {hits} 条：补内容块/解释段后内链"


# -------------------------------------------------------------------- run ---

def collect():
    """Run every source; returns (candidates, source_statuses)."""
    candidates = {}  # term -> set(source names)
    statuses = {}
    for name, fn in SOURCES:
        try:
            raw = fn()
            kept = 0
            for title in raw:
                term = _clean_term(title)
                if term:
                    candidates.setdefault(term, set()).add(name)
                    kept += 1
            statuses[name] = {"status": "ok", "raw": len(raw), "kept": kept}
        except Exception as exc:
            statuses[name] = {"status": "unavailable", "error": str(exc)[:120]}
    return candidates, statuses


def run(limit, api_base, out_dir=OUT_DIR, now=None):
    now = now or datetime.now(timezone.utc)
    candidates, statuses = collect()

    # Rank: multi-source consensus first, then source order weight.
    ranked = sorted(candidates.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    rows = []
    for term, srcs in ranked[:limit]:
        hits, titles = site_hits(term, api_base)
        rows.append(
            {
                "term": term,
                "sources": sorted(srcs),
                "hits": hits,
                "hit_titles": titles,
                "action": action_for(hits, titles),
            }
        )

    doc = {
        "meta": {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date": now.strftime("%Y-%m-%d"),
            "api_base": api_base,
            "candidates_seen": len(candidates),
            "probed": len(rows),
            "sources": statuses,
        },
        "rows": rows,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"meme-radar-{doc['meta']['date']}.json"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")
    (out_dir / "latest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), "utf-8"
    )
    (out_dir / f"meme-radar-{doc['meta']['date']}.md").write_text(
        render_markdown(doc), "utf-8"
    )
    return doc, json_path


def render_markdown(doc):
    lines = [
        f"# Meme radar · {doc['meta']['date']}",
        "",
        f"生成于 {doc['meta']['generated_at']} · 候选 {doc['meta']['candidates_seen']} · 探查 {doc['meta']['probed']}",
        "",
        "| 梗词 | 站内命中 | 动作 | 来源 |",
        "|---|---|---|---|",
    ]
    for r in doc["rows"]:
        hit = f"{r['hits']} 条（{'; '.join(r['hit_titles'][:2])}）" if r["hits"] > 0 else str(r["hits"])
        lines.append(
            f"| {r['term']} | {hit} | {r['action']} | {', '.join(r['sources'])} |"
        )
    lines.append("")
    statuses = doc["meta"]["sources"]
    lines.append(
        "源状态："
        + ", ".join(f"{k}={v['status']}" for k, v in statuses.items())
    )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- selftest ---

def selftest():
    fixture_rss = """<rss><channel><item><title>Vine Boom</title></item>
<item><title>Skibidi Toilet Saga Explained</title></item>
<item><title>New Update</title></item></channel></rss>"""
    root = ET.fromstring(fixture_rss)
    titles = [(i.findtext("title") or "").strip() for i in root.iter("item")]
    terms = [t for t in (_clean_term(x) for x in titles) if t]
    assert terms == ["Vine Boom", "Skibidi Toilet Saga Explained"], terms

    fixture_kym = '<a href="/memes/oh-no-blackout">Oh No Blackout</a> <a href="/memes/tubular">Tubular</a>'
    out = []
    for slug, label in _KYM_LINK_RE.findall(fixture_kym):
        t = _clean_term(label)
        if t:
            out.append(t)
    assert out == ["Tubular"], out  # "Oh No Blackout" rejected whole ("Oh"/"No" < 4 chars)

    fixture_9gag = '{"data":{"posts":[{"title":"When the impostor is sus"},{"title":"Cat"}]}}'
    gag = _9GAG_POST_RE.findall(fixture_9gag)
    assert gag == ["When the impostor is sus"], gag

    assert action_for(0, []) == "缺口：CC0 补源进候选池（贴合调性才收，不硬凑）"
    assert action_for(5, []) == "已有库：出合集页/看板 + 内链 audio-editor 页"
    assert "probe-failed" in action_for(-1, [])

    doc_md = render_markdown(
        {
            "meta": {
                "date": "2026-11-15",
                "generated_at": "2026-11-15T00:00:00Z",
                "candidates_seen": 1,
                "probed": 1,
                "sources": {"google_trends": {"status": "ok"}},
            },
            "rows": [
                {
                    "term": "Vine Boom",
                    "hits": 2,
                    "hit_titles": ["Vine Boom [Original]"],
                    "action": action_for(2, ["x"]),
                    "sources": ["google_trends"],
                }
            ],
        }
    )
    assert "| 梗词 | 站内命中 | 动作 | 来源 |" in doc_md
    print("selftest OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=25, help="max candidates to probe")
    ap.add_argument("--api-base", default="https://soundbuttons.cc")
    ap.add_argument(
        "--out-dir",
        default=None,
        help="output dir (default data/meme-radar; GH workflow passes radar/ so the board is versioned)",
    )
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    doc, path = run(args.limit, args.api_base, out_dir=out_dir)
    statuses = doc["meta"]["sources"]
    ok = [k for k, v in statuses.items() if v["status"] == "ok"]
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(path),
                "candidates": doc["meta"]["candidates_seen"],
                "probed": doc["meta"]["probed"],
                "sources_ok": ok,
                "sources_failed": [k for k in statuses if k not in ok],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
