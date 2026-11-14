#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backlink Prospector - analysis engine (Python standard library only).

Free / open data sources only (mirrors seo-page-snapshot's provider model):
  - seed_library : curated, manually-verified real prospects (no network)
  - bing_discovery : live free search via Bing RSS (no API key), real result URLs
  - tranco        : free popularity rank as a trust signal (no API key)
  - local_backlinks: operator-supplied CSV for a true gap diff (no network)

Commercial metrics (DR/DA) are NEVER estimated; emitted as status:unavailable.
"""
import base64
import concurrent.futures
import datetime as dt
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(HERE, "seed.json")
DATA_DIR = os.path.join(HERE, "data")
SEEDS_DIR = os.path.join(HERE, "seeds")  # image-baked per-domain seed libraries
PROVIDERS_PATH = os.path.join(HERE, "providers.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

SCHEMA_VERSION = "1.1.0"
SKILL = "backlink-prospector"

TYPE_LABEL_ZH = {
    "industry_media": "行业媒体/测评站",
    "guest": "客座博客(Guest Post)",
    "resource": "资源页/链接列表",
    "directory": "目录/导航站",
    "community": "社区/论坛/问答",
    "social": "社媒资料页",
    "partner": "互补品牌/合作站",
    "authority": "安全/权威机构(.gov/.org)",
    "digital_pr": "数字PR/新闻源",
    "reciprocal": "互链(双向交换)",
}
TYPE_LABEL_EN = {
    "industry_media": "Industry media / review",
    "guest": "Guest post",
    "resource": "Resource / link list",
    "directory": "Directory (one-way listing)",
    "community": "Community / forum / Q&A",
    "social": "Social profile",
    "partner": "Partner / complementary brand",
    "authority": "Safety / authority (.gov/.org)",
    "digital_pr": "Digital PR / news",
    "reciprocal": "Reciprocal link (mutual exchange)",
}

def note_en(c):
    """English text for the free-text operator note shown in the results table.

    Seed rows carry an explicit ``note_en``. Legacy / operator-supplied rows may
    not, so never fall back to a Chinese-only string in EN mode: a neutral
    type-based descriptor is used instead. Language-neutral notes pass through.
    """
    explicit = (c.get("note_en") or "").strip()
    if explicit:
        return explicit
    raw = (c.get("note") or "").strip()
    if raw and not any("\u4e00" <= ch <= "\u9fff" for ch in raw):
        return raw
    label = TYPE_LABEL_EN.get(c.get("type"), c.get("type") or "Backlink")
    return "%s candidate (operator note available in Chinese)" % label


TYPE_BASELINE = {  # neutral relevance baseline when no keyword supplied
    "industry_media": 20, "guest": 24, "resource": 26, "directory": 28,
    "community": 22, "social": 18, "partner": 24, "authority": 22, "digital_pr": 20,
    "reciprocal": 16,  # 单条价值最低：铺量兜底，非主力权重来源
}
AUTH_SCORE = {"High": 30, "Medium": 20, "Low": 10}
OBTAIN_SCORE = {
    "directory": 28, "resource": 26, "guest": 22, "community": 20, "social": 16,
    "partner": 18, "industry_media": 12, "authority": 8, "digital_pr": 10,
    "reciprocal": 29,  # 双方互利，最易谈成；但必须控比例
}
# 互链占比告警阈值（占外链池比例超过此值即提示风险）
RECIPROCAL_RATIO_WARN = 0.30
# 互链单条价值最低（铺量兜底，非主力权重来源）→ 排序优先级惩罚
RECIPROCAL_PRIORITY_PENALTY = 12
# Big aggregators to drop from live discovery noise
NOISE_DOMAINS = {
    "google.com", "bing.com", "microsoft.com", "msn.com", "yahoo.com", "wikipedia.org",
    "amazon.com", "facebook.com", "youtube.com", "pinterest.com", "instagram.com",
    "twitter.com", "x.com", "linkedin.com", "reddit.com", "quora.com", "tiktok.com",
    "baidu.com", "zhihu.com", "bilibili.com", "taobao.com", "apple.com", "gov.uk",
    "wikihow.com", "dictionary.com", "cambridge.org", "merriam-webster.com",
    "collinsdictionary.com", "thefreedictionary.com", "bestbuy.com", "walmart.com",
    "ebay.com", "etsy.com", "yelp.com", "tripadvisor.com",
}

# Adult / gambling / ad-redirect hosts must never enter a backlink pool.
# These surface constantly in poisoned search-cache responses, so they are
# filtered explicitly in addition to the keyword relevance gate.
BLOCKED_DOMAINS = {
    "pornhub.com", "youporn.com", "xvideos.com", "xhamster.com", "xnxx.com",
    "redtube.com", "tube8.com", "spankbang.com", "eporner.com", "fapello.com",
    "bokepindoh.xxx", "bokephot.net", "kongbokep.com", "ksatriabokep.com",
    "sebokep.com", "sextop1.house", "hihisex.men", "heosex.video", "phimheo.cool",
    "vn-phimsex.com", "crot.digital", "tiava.com", "phimsex.com",
    "bestsecret.com", "klipads.co", "propellerads.com", "adcash.com",
    "popads.net", "hilltopads.net", "lomb.co", "blackhatworth.com",
}

# --------------------------------------------------------------------------- #
# free discovery — multi-channel, rotated (see channels.json)
# --------------------------------------------------------------------------- #
CHANNELS_PATH = os.path.join(HERE, "channels.json")

# Domains whose presence signals a generic/low-value result, not a real prospect
EXTRA_NOISE = {
    "soundcloud.com", "pixabay.com", "poki.com", "onlinegames.io", "baike.baidu.com",
    "dictionary.cambridge.org", "merriam-webster.com", "collinsdictionary.com",
    "oxfordlearnersdictionaries.com", "thefreedictionary.com", "brainyquote.com",
    "bing.com", "bingquiz.com", "popularnowonbing.com", "pexels.com", "unsplash.com",
}


def load_channels():
    """Load discovery channels config; returns (rotation_cfg, [enabled channels])."""
    cfg = load_json(CHANNELS_PATH, {"channels": []})
    rot = cfg.get("rotation") or {}
    chans = [c for c in cfg.get("channels", []) if c.get("enabled", True)]
    return rot, chans


def _ddg_html(query, n=15, timeout=15):
    """DuckDuckGo HTML endpoint; returns real result URLs (uddg param decode)."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    html = urllib.request.urlopen(req, timeout=timeout, context=CTX).read().decode("utf-8", "replace")
    out = []
    for m in re.finditer(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"', html):
        href = m.group(1)
        um = re.search(r"uddg=([^&]+)", href)
        if um:
            out.append(urllib.parse.unquote(um.group(1)))
        elif href.startswith("http"):
            out.append(href)
    return out


def _bing_cite_domains(query, timeout=15):
    """Bing web HTML; extract real domains from <cite> elements (jump links are encrypted)."""
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": query, "cc": "us", "setlang": "en", "count": "20"})
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    html = urllib.request.urlopen(req, timeout=timeout, context=CTX).read().decode("utf-8", "replace")
    blocks = re.findall(r'<li class="b_algo".*?</li>', html, re.S)
    doms = []
    for b in blocks:
        c = re.search(r"<cite[^>]*>(.*?)</cite>", b, re.S)
        if not c:
            continue
        dom = re.sub(r"<[^>]+>", "", c.group(1)).strip()
        dom = re.sub(r"^https?://", "", dom).split(" ")[0].split("›")[0].strip().replace("www.", "")
        if dom and "." in dom and " " not in dom:
            doms.append(dom)
    return doms


def _bing_rss(query, n=20, timeout=15):
    """Bing RSS; returns real result URLs. Empty channel = rate-limited."""
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": query, "format": "rss", "count": str(n), "cc": "us", "setlang": "en"})
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    xml = urllib.request.urlopen(req, timeout=timeout, context=CTX).read().decode("utf-8", "replace")
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        l = re.search(r"<link>([^<]+)</link>", item)
        if l:
            out.append(l.group(1).strip())
    return out


CHANNEL_RUNNERS = {
    "bing_rss": lambda q, n: _bing_rss(q, n),
    "bing_cite": lambda q, n: _bing_cite_domains(q)[:n],
    "ddg_html": lambda q, n: _ddg_html(q, n)[:n],
}


def run_channel(ch, keywords, target_d, comp_domains, max_results, max_queries):
    """Execute one discovery channel; returns list of candidate dicts."""
    runner = CHANNEL_RUNNERS.get(ch.get("kind"))
    if not runner:
        return []
    # Accept a list OR a comma-separated string; a string must never be sliced
    # character-wise (that would query "ba" and pass every relevance gate).
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    keywords = [k for k in (keywords or []) if str(k).strip()]
    if not keywords:
        return []
    templates = ch.get("templates") or {}
    kws = keywords[:2]
    queries = []
    for kw in kws:
        for ttype, tmpls in templates.items():
            for tmpl in tmpls[:1]:
                queries.append((ttype, tmpl.format(kw=kw)))
    queries = queries[:max_queries]

    noise = NOISE_DOMAINS | EXTRA_NOISE
    # normalised keyword forms + significant single tokens for the relevance gate
    kw_norm = [_norm_text(k) for k in keywords]
    kw_tokens = set()
    for k in keywords:
        for tok in re.split(r"[^a-z0-9]+", k.lower()):
            if len(tok) >= 4:
                kw_tokens.add(tok)

    def fetch_one(item):
        ttype, q = item
        try:
            return [(ttype, q, link) for link in runner(q, max_results + 5)]
        except Exception:
            return []

    found = {}
    raw_seen = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for results in ex.map(fetch_one, queries):
            for ttype, q, link in results:
                try:
                    p = urllib.parse.urlparse(link)
                except Exception:
                    continue
                if p.scheme not in ("http", "https") or not p.hostname:
                    continue
                d = p.hostname.lower().replace("www.", "")
                if d in noise or is_blocked(d) or d == target_d or d in comp_domains:
                    continue
                if d in found:
                    continue
                raw_seen += 1
                low = link.lower()
                # relevance gate: the keyword must actually appear in the RESULT
                # URL. The previous version also accepted "keyword appears in the
                # query", which was always true (the query is built FROM the
                # keyword) and therefore let every off-topic hit through.
                low_n = _norm_text(low)
                strong = any(n and n in low_n for n in kw_norm)
                weak = any(tok in low for tok in kw_tokens)
                if not (strong or weak):
                    continue
                found[d] = {
                    "url": link, "type": ttype, "authorityTier": "Medium",
                    "tags": [q], "note": ch["name_zh"] + " 实时发现: " + q,
                    "note_en": (ch.get("name_en") or ch["name_zh"]) + " live discovery: " + q,
                    "source": ch["id"],
                    "kw_match": "strong" if strong else "weak",
                }
                if len(found) >= max_results:
                    break
            if len(found) >= max_results:
                break
    # raw_seen = hits returned by the channel; found = hits that passed the
    # relevance gate. A large gap means the channel served off-topic junk.
    found_list = list(found.values())
    for c in found_list:
        c["raw_seen"] = raw_seen
    return found_list, raw_seen


def discover_all(keywords, target_d, comp_domains, max_results=40, max_queries=8):
    """Poll every enabled channel in channels.json order; merge + dedup.

    Returns (candidates, channel_stats) where channel_stats records per-channel
    found counts and errors for the frontend data-source panel.
    """
    rot, chans = load_channels()
    delay = float(rot.get("inter_query_delay_seconds", 1.0))
    per_ch = int(rot.get("max_results_per_channel", max_results))
    max_q = int(rot.get("max_queries_per_channel", max_queries))

    merged, stats, seen = [], [], set()
    for ch in chans:
        try:
            found, raw = run_channel(ch, keywords, target_d, comp_domains, per_ch, max_q)
            err = None
        except Exception as exc:  # noqa: BLE001
            found, raw, err = [], 0, "%s: %s" % (type(exc).__name__, str(exc)[:120])
        added = 0
        for c in found:
            if c["url"] not in seen:
                merged.append(c)
                seen.add(c["url"])
                added += 1
        if found:
            status = "ok"
        elif raw:
            # channel answered but every hit was off-topic (junk / poisoned cache)
            status = "off-topic"
        elif err:
            status = "error"
        else:
            status = "empty"
        stats.append({"id": ch["id"], "name_zh": ch.get("name_zh", ch["id"]),
                      "enabled": True, "found": len(found), "raw": raw, "added": added,
                      "status": status,
                      "error": err})
    return merged, stats


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _norm_text(s):
    """Lowercase + strip every non-alphanumeric char ('balance bike' -> 'balancebike')."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def is_blocked(domain):
    """True when the host (or any parent of it) is blocklisted.

    Adult / gambling / ad-redirect hosts must never become prospects, no matter
    which channel surfaced them.
    """
    d = (domain or "").lower().replace("www.", "")
    if not d:
        return True
    if d in BLOCKED_DOMAINS:
        return True
    return any(d.endswith("." + b) for b in BLOCKED_DOMAINS)


def _merge_bilingual_seeds(rows, reference):
    """Backfill note / note_en from the versioned seed library.

    A Fly volume can carry an operator-uploaded data/seed-<domain>.json that
    predates the bilingual fields. URL-matched rows in the shipped seeds/ copy
    are the source of truth for those translations, so EN mode never falls back
    to a Chinese-only note just because a legacy override shadows the file.
    """
    by_url = {}
    for r in reference or []:
        if isinstance(r, dict) and r.get("url"):
            by_url[str(r["url"]).rstrip("/").lower()] = r
    for r in rows:
        if not isinstance(r, dict):
            continue
        ref = by_url.get(str(r.get("url") or "").rstrip("/").lower())
        if not ref:
            continue
        for key in ("note", "note_en"):
            if not r.get(key) and ref.get(key):
                r[key] = ref[key]
    return rows


def load_seed_for(target_domain):
    """Load seed candidates scoped to a center domain.

    Resolution order:
      1. data/seed-<domain>.json  - operator override (volume / local workspace)
      2. seeds/seed-<domain>.json - versioned per-domain library shipped with
                                     the service (survives volume mounts)
      3. seed.json rows whose "domains" list contains the center domain
      4. seed.json rows without a "domains" field (domain-agnostic / global)

    A seed row that belongs to another domain is never injected, so an analysis
    for a new domain can never surface prospects from an unrelated niche.

    Returns (candidates, scope_label).
    """
    safe = re.sub(r"[^a-z0-9._-]", "_", (target_domain or "").lower()).strip("._")[:100]
    if safe:
        for base, label in ((DATA_DIR, "data"), (SEEDS_DIR, "seeds")):
            p = os.path.join(base, "seed-%s.json" % safe)
            if os.path.isfile(p):
                data = load_json(p, [])
                if isinstance(data, dict):
                    data = data.get("sites") or data.get("items") or []
                if isinstance(data, list) and data:
                    if label == "data":
                        ref = load_json(os.path.join(SEEDS_DIR, "seed-%s.json" % safe), [])
                        if isinstance(ref, dict):
                            ref = ref.get("sites") or ref.get("items") or []
                        data = _merge_bilingual_seeds(data, ref if isinstance(ref, list) else [])
                    return data, "%s/seed-%s.json" % (label, safe)
    all_seed = load_json(SEED_PATH, [])
    if not isinstance(all_seed, list):
        all_seed = []
    if not target_domain:
        return all_seed, "seed.json (all)"
    scoped = [c for c in all_seed
              if not c.get("domains") or target_domain in (c.get("domains") or [])]
    return scoped, "seed.json (domains=%s)" % target_domain


def load_providers():
    cfg = load_json(PROVIDERS_PATH, {"providers": []})
    return {p["id"]: p for p in cfg.get("providers", [])}


def domain_of(url):
    try:
        h = urllib.parse.urlparse(url).hostname or url
        return h.lower().replace("www.", "")
    except Exception:
        return url.lower()


def split_list(s):
    return {domain_of(x) for x in re.split(r"[,\n]", s or "") if x.strip()}


# --------------------------------------------------------------------------- #
# live HTTP validation (proves "real and valid")
# --------------------------------------------------------------------------- #
def validate(url, timeout=9):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*", "Range": "bytes=0-1023"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            status = r.status
            ok = status < 400 or status in (401, 403, 429)
            return {"status": status, "ok": ok, "final_url": r.geturl(), "error": None}
    except urllib.error.HTTPError as e:
        status = e.code
        ok = status < 400 or status in (401, 403, 429)
        return {"status": status, "ok": ok, "final_url": url, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "ok": False, "final_url": url, "error": str(e)[:120]}


# --------------------------------------------------------------------------- #
# free authority signal: Tranco global rank
# --------------------------------------------------------------------------- #
def tranco_rank(domain, timeout=12):
    url = "https://tranco-list.eu/api/ranks/domain/" + domain
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        ranks = data.get("ranks") or []
        return ranks[0].get("rank") if ranks else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# free discovery: Bing HTML — legacy (superseded by Bing RSS above; kept unused)
# --------------------------------------------------------------------------- #
def _decode_bing(href):
    m = re.search(r"[?&]u=([^&]+)", href)
    if not m:
        return href if href.startswith("http") else None
    s = m.group(1)
    if s.startswith("a1"):
        s = s[2:]
    s = s + "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s).decode("utf-8", "replace")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def score(c, keywords):
    kws = [k.strip().lower() for k in (keywords or "").split(",") if k.strip()]
    hay = (c["url"] + " " + " ".join(c.get("tags", [])) + " " + c.get("note", "")).lower()
    hay_n = _norm_text(hay)
    if kws:
        # normalised match so 'balance bike' still matches 'forbalancebikes.com'
        matches = sum(1 for k in kws if k in hay or _norm_text(k) in hay_n)
        relevance = min(40, 15 + matches * 8)
    else:
        relevance = min(40, TYPE_BASELINE.get(c["type"], 20))
    authority = AUTH_SCORE.get(c.get("authorityTier"), 15)
    obtain = OBTAIN_SCORE.get(c["type"], 15)
    if re.search(r"write[- ]for[- ]us|contribute|guest|submit|contact", c["url"] + " " + c.get("note", ""), re.I):
        obtain = min(30, obtain + 4)
    total = relevance + authority + obtain
    # 互链：单条价值最低 + link scheme 风险 → 排序兜底
    if c.get("type") == "reciprocal":
        total = max(0, total - RECIPROCAL_PRIORITY_PENALTY)
    return relevance, authority, obtain, total


# --------------------------------------------------------------------------- #
# main analyze
# --------------------------------------------------------------------------- #
def analyze(input):
    input = input or {}
    domain = (input.get("domain") or "").strip()
    keywords = (input.get("keywords") or "").strip()
    competitors = input.get("competitors") or ""
    existing = input.get("existing") or ""
    use_bing = str(input.get("use_bing", "1")).lower() in ("1", "true", "yes", "on")
    use_tranco = str(input.get("use_tranco", "1")).lower() in ("1", "true", "yes", "on")

    prov = load_providers()
    seed_on = prov.get("seed_library", {}).get("enabled", True)
    bing_on = prov.get("bing_discovery", {}).get("enabled", True) and use_bing
    tranco_on = prov.get("tranco", {}).get("enabled", True) and use_tranco

    target_d = domain_of(domain) if domain else ""
    comp_domains = split_list(competitors)
    exist_domains = split_list(existing)

    # 1) seed candidates — scoped to the center domain so results from another
    #    niche can never leak into this analysis.
    candidates, seed_scope = [], "disabled"
    if seed_on:
        candidates, seed_scope = load_seed_for(target_d)
    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    if kws:
        def _kw_match(c):
            hay = (c["url"] + " " + " ".join(c.get("tags", [])) + " " + c.get("note", "")).lower()
            hay_n = _norm_text(hay)
            return any(k in hay or _norm_text(k) in hay_n for k in kws)

        # Authority / safety orgs and reciprocal (relationship) links are kept
        # without a literal keyword ONLY when the row is explicitly scoped to
        # this center domain; generic rows still have to match a keyword.
        candidates = [c for c in candidates
                      if _kw_match(c)
                      or (c.get("type") in ("authority", "reciprocal")
                          and target_d and target_d in (c.get("domains") or []))]

    # 2) live multi-channel discovery (rotated per channels.json)
    discovered, channel_stats = [], []
    if bing_on and kws:
        try:
            discovered, channel_stats = discover_all(kws, target_d, comp_domains)
        except Exception:
            discovered, channel_stats = [], []
    seen = {c["url"] for c in candidates}
    for d in discovered:
        if d["url"] not in seen:
            candidates.append(d)
            seen.add(d["url"])

    # 3) build base + concurrent validation
    base = []
    for c in candidates:
        d = domain_of(c["url"])
        if target_d and d == target_d:
            continue
        if is_blocked(d):
            continue
        rel, auth, obt, prio = score(c, keywords)
        is_comp = bool(c.get("isCompetitor")) or d in comp_domains
        base.append({"c": c, "d": d, "is_comp": is_comp, "rel": rel, "auth": auth,
                     "obt": obt, "prio": prio})

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {id(b): ex.submit(validate, b["c"]["url"]) for b in base}
        for b in base:
            b["val"] = futs[id(b)].result()

    # 4) authority signal (free Tranco), concurrent
    if tranco_on:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            tfuts = {id(b): ex.submit(tranco_rank, b["d"]) for b in base}
            for b in base:
                b["tranco"] = tfuts[id(b)].result()
    else:
        for b in base:
            b["tranco"] = None

    # 5) assemble
    prospects = []
    for b in base:
        c = b["c"]
        d = b["d"]
        already = d in exist_domains
        is_gap = (not b["is_comp"]) and (not already)
        tranco = b.get("tranco")
        prospects.append({
            "url": c["url"],
            "domain": d,
            "type_key": c["type"],
            "type_label_zh": TYPE_LABEL_ZH.get(c["type"], c["type"]),
            "type_label_en": TYPE_LABEL_EN.get(c["type"], c["type"]),
            "authority_tier": c.get("authorityTier"),
            "authority": {
                "tier": c.get("authorityTier"),
                "tranco_global_rank": tranco,
                "tranco_status": "ok" if tranco is not None else "unavailable",
                "domain_rating": {"value": None, "status": "unavailable",
                                  "reason": "commercial metric requires a paid API (Ahrefs/SEMrush/Moz); never estimated"},
            },
            "tags": c.get("tags", []),
            "relevance": b["rel"], "authority_score": b["auth"], "obtainability": b["obt"],
            "priority": b["prio"],
            "valid": b["val"]["ok"], "http_status": b["val"]["status"],
            "valid_error": b["val"]["error"], "final_url": b["val"]["final_url"],
            "is_competitor": bool(b["is_comp"]),
            "is_gap": is_gap, "already_have": already,
            "note": c.get("note", ""),
            "note_en": note_en(c),
            "source": c.get("source", "seed"),
        })
    prospects.sort(key=lambda p: (-p["priority"], not p["valid"]))

    gap_valid = [p for p in prospects if p["is_gap"] and p["valid"] and not p["is_competitor"]]
    result = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": {"input": domain, "registrable_domain": target_d},
        "query": {"keywords": keywords, "competitors": competitors,
                  "existing_domains_count": len(exist_domains)},
        "totals": {
            "candidates": len(prospects),
            "valid": sum(1 for p in prospects if p["valid"]),
            "gap": sum(1 for p in prospects if p["is_gap"]),
            "gap_valid": len(gap_valid),
        },
        "prospects": prospects,
        "data_sources": {
            "seed_library": {"enabled": seed_on, "status": "ok" if seed_on else "disabled",
                             "scope": seed_scope, "rows": len(candidates)},
            "discovery_channels": {
                "enabled": bing_on,
                "status": "ok" if (bing_on and discovered) else ("empty" if bing_on else "disabled"),
                "found": len(discovered),
                "channels": channel_stats,
            },
            "tranco": {"enabled": tranco_on, "status": "ok" if tranco_on else "disabled"},
            "local_backlinks": {"enabled": bool(exist_domains), "matched_domains": len(exist_domains)},
        },
        "limitations": [
            "Commercial DR/DA and backlink counts are NEVER estimated; emitted as status:unavailable.",
            "Live discovery rotates over free channels (Bing RSS / Bing cite / DuckDuckGo HTML) per channels.json; each is best-effort and degrades to empty when rate-limited.",
            "Gap is computed from supplied existing backlinks; without import, all non-competitor prospects are candidate gaps to pursue.",
            "Authority tier in seed.json is an editorial estimate; Tranco global rank is the only free quantitative signal used.",
            "The seed library is domain-scoped: only rows whose 'domains' contain the center domain (or a per-domain data/seed-<domain>.json) are injected, so one niche never leaks into another.",
            "Seen candidates are not owned backlinks: gap detection uses verified live placements, operator-marked acquisitions and the explicit existing-backlink import only. Pool membership alone never excludes a prospect.",
        ],
        # Chinese counterpart of the English-primary limitations above. The UI
        # picks this list in ZH mode; CSV / machine consumers keep `limitations`.
        "limitations_zh": [
            "商业 DR/DA 与外链数量一律不估算，统一标记为 status:unavailable。",
            "实时发现按 channels.json 在免费渠道（Bing RSS / Bing cite / DuckDuckGo HTML）间轮询；各渠道均为 best-effort，被限流时自动降级为空结果。",
            "缺口基于你导入的已有外链计算；未导入时，所有非竞品候选都视为待拓展缺口。",
            "seed.json 中的 authorityTier 是编辑判断；Tranco 全球排名是唯一使用的免费量化信号。",
            "种子库按域名隔离：仅注入 domains 含当前中心域名的行（或 data/seed-<domain>.json 覆盖文件），避免不同品类互相污染。",
            "见过不等于已拥有：缺口只与台账中已验证上线的投放记录、人工标记已拥有及显式导入的已有外链比对；仅出现在池里不会排除候选。",
        ],
    }
    return result


if __name__ == "__main__":
    import sys
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(analyze(payload), ensure_ascii=False, indent=2))
