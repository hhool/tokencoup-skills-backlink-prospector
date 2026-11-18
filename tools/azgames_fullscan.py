#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""azgames 全量重扫：把本地所有语料汇成一个候选池，一次跑完。

语料（只读，不改任何来源）：
  1. WDC 2012 PLD 图  → data/competitor-links-azgames.poki2.online.json
     证据强度最高：host 在 Common Crawl 里真的链向过游戏门户（≥2 家才算）。
  2. submitlist 全量目录 → ~/seo/_sources/submitlist.json（3477 条）
     带 domain_rating / pricing / type，能直接判权威度与一次性可行性。
  3. 已有种子 → seeds/seed-azgames-midtail.json 等
  4. 现有台账 → ~/seo/azgames.poki2.online/targets.jsonl（用于去重，不重复入池）

处理：规范化 → 平台黑名单 → 相关性打分 → 去重（同域 + 台账）→ 分档。
输出：reports/azgames-fullscan-candidates.json / .csv + 控制台摘要。

口径纪律：
  * authority 只用可观测值（submitlist 的 domain_rating 或台账 authority_score）；
    没有就记 unknown，不猜、不冒充实测 DR。
  * WDC 的 2012 年边只作「品类相邻」证据，不作存活证据；存活由探测阶段判。
  * 任何一行都带 source + evidence，报告里可逐条回溯。

用法：
  python3 tools/azgames_fullscan.py
  python3 tools/azgames_fullscan.py --min-via 2 --limit 800 --top 300
"""
import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path.home() / "seo" / "azgames.poki2.online" / "targets.jsonl"
SUBMITLIST = Path.home() / "seo" / "_sources" / "submitlist.json"
WDC = ROOT / "data" / "competitor-links-azgames.poki2.online.json"
SEEDS = [ROOT / "seeds" / "seed-azgames-midtail.json"]

# 平台/聚合站：不是"可投递的外链位"，或者根本没有提交入口
PLATFORM_RE = re.compile(
    r"(?i)(^|\.)(blogspot\.|wordpress\.|tumblr\.|livejournal\.|weebly\.|wixsite\.|"
    r"jimdo\.|webnode\.|yolasite\.|webs\.com|angelfire\.|tripod\.|50webs\.|"
    r"google\.|youtube\.|facebook\.|twitter\.|x\.com|instagram\.|pinterest\.|"
    r"tiktok\.|reddit\.|medium\.com|substack\.com|quora\.com|linkedin\.|"
    r"apple\.com|microsoft\.com|amazon\.|ebay\.|archive\.org|wikipedia\.|"
    r"fandom\.com|wikia\.com|blogspot\.|typepad\.|over-blog\.|canalblog\.)")

# 明显不是外链位的形态：CDN / 统计 / 静态资源 / 邮箱域
JUNK_RE = re.compile(
    r"(?i)(^|\.)(cdn|static|img|images|js|css|fonts?|analytics|tracker|"
    r"doubleclick|googleapis|gstatic|cloudflare|akamai|fastly|jsdelivr|"
    r"gravatar|w3\.org|schema\.org|adobe\.com|java\.com|macromedia\.com)\.")

# 关键词一律加词边界：早期版本用裸子串，"display" 命中 "play"、
# "function" 命中 "fun"，把一堆无关目录误判成 strong。
GAME_STRONG = re.compile(
    r"(?i)\b(games?|gaming|gamers?|arcade|arcades|esports?|html5|flash|"
    r"play|playable|plays|puzzle|puzzles|quiz|quizzes|"
    r"jeux|juegos|giochi|spiele|igrice|gry|hry|"
    r"fun|bored|kids?|children|toys?|"
    r"indie|unity|godot|gamemaker|rpg|platformer|shooter|retro|"
    r"videogames?|gamedev|game-?dev)\b")
GAME_WEAK = re.compile(
    r"(?i)\b(dev|code|coding|web|design|digital|media|entertainment|"
    r"review|reviews|blog|list|directory|links|tools|tech|creative|art|"
    r"music|collect|portal|apps?|software)\b")

NEG = re.compile(
    r"(?i)(casino|betting|porn|sex|adult|xxx|pharma|loan|insurance|crypto|"
    r"forex|rehab|escort|dating|gambling|slot)")

# submitlist 里"能落到一个提交动作"的类型（其余是 subreddit/github，需要账号）
ONESHOT_TYPES = {"directory", "citation", "marketplace", "community",
                 "product-launch-site", "newsletter"}

CST = timezone(timedelta(hours=8))


def now():
    return datetime.now(CST).isoformat(timespec="seconds")


def bare_domain(value):
    v = str(value or "").strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = v.split("/")[0].split("?")[0]
    if v.startswith("www."):
        v = v[4:]
    return v


def load_ledger_domains():
    out = {}
    if not LEDGER.exists():
        return out
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        d = bare_domain(r.get("domain") or r.get("url"))
        if d:
            out[d] = r
    return out


def guess_submit_type(host, hint=""):
    h = (host + " " + (hint or "")).lower()
    if re.search(r"submit|add[-_]?(site|url|link)|suggest", h):
        return "listing"
    if re.search(r"directory|dir\.|links|linklist|web-?dir", h):
        return "listing"
    if re.search(r"forum|board|community|discuss", h):
        return "posting"
    if re.search(r"blog", h):
        return "guest_post"
    if re.search(r"news|press", h):
        return "pr"
    return "unknown"


def score_row(r):
    """0-100 机会分：证据（谁链过他）> 权威度 > 相关性 > 形态。"""
    s = 0.0
    via = len(r.get("via_competitors") or [])
    s += min(via, 6) * 6.0                     # ≤36：几家游戏门户的共同反链
    inb = r.get("inbound") or 0
    if inb:
        s += min(math.log10(inb + 1) * 6.0, 14.0)   # ≤14
    dr = r.get("domain_rating")
    if dr is not None:
        s += 12.0 if 20 <= dr <= 80 else (6.0 if dr < 20 else 2.0)
    if r.get("relevance") == "strong":
        s += 20.0
    elif r.get("relevance") == "weak":
        s += 8.0
    if r.get("oneshot_hint"):
        s += 8.0
    if r.get("pricing") == "free":
        s += 4.0
    return round(min(s, 100.0), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-via", type=int, default=2, help="WDC 至少几家竞品共同反链")
    ap.add_argument("--limit", type=int, default=0, help="WDC 最多取多少行（0=不限）")
    ap.add_argument("--out", default="reports/azgames-fullscan-candidates")
    args = ap.parse_args()

    ledger = load_ledger_domains()
    seen, rows, stats = set(), [], {}

    def add(r):
        d = r["domain"]
        if not d or d in seen:
            return False
        if PLATFORM_RE.search(d) or JUNK_RE.search(d) or NEG.search(d):
            stats["dropped_junk"] = stats.get("dropped_junk", 0) + 1
            return False
        seen.add(d)
        rows.append(r)
        return True

    # ---- 1. WDC 竞品反链
    wdc = {"file": str(WDC.relative_to(ROOT)), "exists": WDC.exists(),
           "competitors": [], "rows": 0, "used": 0}
    if WDC.exists():
        data = json.loads(WDC.read_text(encoding="utf-8"))
        wdc["competitors"] = (data.get("meta") or {}).get("competitors") or []
        src = data.get("rows") or []
        wdc["rows"] = len(src)
        if args.limit:
            src = src[:args.limit]
        for x in src:
            host = bare_domain(x.get("url"))
            via = x.get("via_competitors") or []
            if len(via) < args.min_via:
                continue
            rel = ("strong" if GAME_STRONG.search(host)
                   else ("weak" if GAME_WEAK.search(host) else "none"))
            stype = guess_submit_type(host)
            ok = add({
                "domain": host, "url": "https://%s/" % host,
                "source": "wdc", "via_competitors": via,
                "inbound": x.get("inbound") or 0,
                "relevance": rel,
                "submit_type": stype,
                "oneshot_hint": stype == "listing",
                "domain_rating": None, "pricing": "unknown",
                "evidence": "WDC2012: %d 家游戏门户反链 (%s)" % (
                    len(via), ", ".join(via[:3])),
            })
            if ok:
                wdc["used"] += 1
    stats["wdc"] = wdc["used"]

    # ---- 2. submitlist 全量目录
    sl = {"file": str(SUBMITLIST), "exists": SUBMITLIST.exists(),
          "rows": 0, "used": 0}
    if SUBMITLIST.exists():
        items = json.loads(SUBMITLIST.read_text(encoding="utf-8")).get("destinations") or []
        sl["rows"] = len(items)
        for x in items:
            if x.get("type") not in ONESHOT_TYPES:
                continue
            host = bare_domain(x.get("website_url") or x.get("submission_url"))
            if not host:
                continue
            text = " ".join([x.get("name") or "", x.get("description") or "",
                             " ".join(x.get("categories") or [])])
            rel = ("strong" if GAME_STRONG.search(text + " " + host)
                   else ("weak" if GAME_WEAK.search(text) else "none"))
            ok = add({
                "domain": host, "url": x.get("submission_url") or ("https://%s/" % host),
                "source": "submitlist", "via_competitors": [], "inbound": 0,
                "relevance": rel,
                "submit_type": "listing",
                "oneshot_hint": True,
                "domain_rating": x.get("domain_rating"),
                "pricing": x.get("pricing") or "unknown",
                "evidence": "submitlist %s / DR %s / %s" % (
                    x.get("type"), x.get("domain_rating"), x.get("pricing")),
                "entry_url": x.get("submission_url") or "",
                "notes": (x.get("description") or "")[:200],
            })
            if ok:
                sl["used"] += 1
    stats["submitlist"] = sl["used"]

    # ---- 3. 种子
    sd = {"files": [], "used": 0}
    for f in SEEDS:
        if not f.exists():
            continue
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        items = items.get("candidates") if isinstance(items, dict) else items
        sd["files"].append(f.name)
        for x in items or []:
            host = bare_domain(x.get("url") or x.get("domain"))
            if not host:
                continue
            ok = add({
                "domain": host, "url": x.get("url") or ("https://%s/" % host),
                "source": "seed", "via_competitors": [], "inbound": 0,
                "relevance": "strong" if GAME_STRONG.search(host + (x.get("note") or "")) else "weak",
                "submit_type": x.get("submit_type") or guess_submit_type(host),
                "oneshot_hint": True,
                "domain_rating": None,
                "pricing": x.get("cost") or "unknown",
                "evidence": "seed:%s" % f.name,
                "entry_url": x.get("url") or "",
                "notes": (x.get("note") or "")[:200],
            })
            if ok:
                sd["used"] += 1
    stats["seed"] = sd["used"]

    # ---- 4. 去重 + 打分
    dup_ledger, kept = 0, []
    for r in rows:
        if r["domain"] in ledger:
            dup_ledger += 1
            continue
        r["score"] = score_row(r)
        kept.append(r)
    kept.sort(key=lambda r: (-r["score"], -len(r["via_competitors"] or []), r["domain"]))

    bands = {"strong": 0, "weak": 0, "none": 0}
    for r in kept:
        bands[r["relevance"]] += 1

    out_json = ROOT / (args.out + ".json")
    out_csv = ROOT / (args.out + ".csv")
    out_json.write_text(json.dumps({
        "generated_at": now(),
        "center": "azgames.poki2.online",
        "inputs": {"wdc": wdc, "submitlist": sl, "seed": sd},
        "stats": {"pool": len(rows), "dedup_against_ledger": dup_ledger,
                  "kept": len(kept), "relevance": bands,
                  "dropped_junk": stats.get("dropped_junk", 0)},
        "rows": kept,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["score", "domain", "source", "relevance", "submit_type",
                    "domain_rating", "pricing", "via", "inbound", "url", "evidence"])
        for r in kept:
            w.writerow([r["score"], r["domain"], r["source"], r["relevance"],
                        r["submit_type"], r.get("domain_rating") or "",
                        r.get("pricing") or "",
                        len(r.get("via_competitors") or []), r.get("inbound") or 0,
                        r.get("url") or "", r.get("evidence") or ""])

    print("语料：WDC %s 行 → 用 %d；submitlist %d 行 → 用 %d；种子 %d" % (
        wdc["rows"], wdc["used"], sl["rows"], sl["used"], sd["used"]))
    print("池 %d 条 → 台账已存在 %d → 新候选 %d" % (len(rows), dup_ledger, len(kept)))
    print("相关性：strong %d / weak %d / none %d" % (
        bands["strong"], bands["weak"], bands["none"]))
    print("→ %s\n→ %s" % (out_json.relative_to(ROOT), out_csv.relative_to(ROOT)))
    print("\n得分前 15：")
    for r in kept[:15]:
        print("  %5.1f  %-32s %-10s %-6s via=%d dr=%s" % (
            r["score"], r["domain"], r["source"], r["relevance"],
            len(r.get("via_competitors") or []), r.get("domain_rating")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
