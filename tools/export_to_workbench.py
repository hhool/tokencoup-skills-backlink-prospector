#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export backlink-prospector's pool as backlink-workbench candidates.

One-way bridge: reads a per-domain prospector store (data/store-<domain>.json)
and emits a candidates JSON file that `blw add --file` can import. The
prospector pool is a discovery cache; workbench's targets.jsonl stays the
single source of truth. Nothing here writes back to prospector or BDL.

Field contract: backlink-unified-architecture.md §3.

Usage:
    python3 tools/export_to_workbench.py --center-domain soundbuttons.cc \
        --out /tmp/soundbuttons.cc.candidates.json
    python3 tools/export_to_workbench.py --center-domain soundbuttons.cc \
        --out out.json --dry-run            # print summary, write nothing
    python3 tools/export_to_workbench.py --list-domains   # show available pools

Then import into the matching workbench site:
    python3 ~/.workbuddy/skills/backlink-workbench/scripts/blw.py \
        --workspace ~/seo add --file /tmp/soundbuttons.cc.candidates.json

Zero third-party dependencies (stdlib only), matching both tools.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import store as st  # noqa: E402

TYPE_MAP = {
    "directory": "directory",
    "community": "community", "forum": "community",
    "resource": "resource", "link_list": "resource", "linklist": "resource",
    "qna": "qna", "question": "qna",
    "news": "news", "press": "news", "media": "news",
    "social": "social",
    "bookmark": "bookmark",
    "launch": "launch", "startup": "launch",
    "blog": "other", "guest_post": "other", "article": "other",
}
VALID_CATEGORIES = {"directory", "community", "launch", "commercial", "news",
                    "qna", "bookmark", "resource", "social", "other"}


def _norm_url(value):
    """Minimal URL normalization for export (workbench re-normalizes on import)."""
    v = str(value or "").strip()
    if not v:
        return ""
    if "://" not in v:
        v = "https://" + v
    return v.rstrip("/") or v


def _source(row):
    src = row.get("source") or "seed"
    if src == "competitor_backlink" or row.get("via_competitors"):
        return "prospector:competitor_backlink"
    if src in ("bing_discovery", "bing", "ddg", "live_search"):
        return "prospector:bing"
    return "prospector:seed"


def _note(row):
    """Fold provenance / evidence into a human-readable note (never overwritten
    into workbench's structured score fields)."""
    bits = []
    if row.get("type_label_zh"):
        bits.append("类型: %s" % row["type_label_zh"])
    if row.get("authority_tier"):
        bits.append("权重层级: %s" % row["authority_tier"])
    if row.get("priority") is not None:
        bits.append("发现打分: %s" % row["priority"])
    tranco = (row.get("authority") or {}).get("tranco_global_rank")
    if tranco:
        bits.append("Tranco: %s" % tranco)
    vias = row.get("via_competitors") or []
    if vias:
        bits.append("竞品反链证据: %s" % ", ".join(vias[:8]))
    if row.get("source") == "competitor_backlink" and not vias:
        bits.append("来源: 竞品反链图谱(WDC)")
    for k in ("times_discovered", "first_seen", "last_seen"):
        if row.get(k) is not None:
            bits.append("%s=%s" % (k, row[k]))
    base = str(row.get("note") or "").strip()
    if base:
        bits.insert(0, base)
    return " | ".join(bits)[:800]


def _candidate(row):
    cat = TYPE_MAP.get(str(row.get("type_key") or "").lower(), "other")
    if cat not in VALID_CATEGORIES:
        cat = "other"
    acquired = bool(row.get("acquired"))
    cand = {
        "url": _norm_url(row.get("url") or row.get("domain")),
        "domain": row.get("domain"),
        "title": str(row.get("type_label_zh") or row.get("domain") or "")[:200],
        "note": _note(row),
        "category": cat,
        "found_by": _source(row),
        "status": "done" if acquired else "pending",
        "link_http_status": row.get("http_status"),
        "tags": ["prospector", "discovered"],
    }
    if row.get("via_competitors"):
        cand["tags"].append("competitor_backlink")
    return cand


def load_relevance(keywords_file):
    """Build a relevance filter from an extracted-keywords JSON file.

    Returns a callable(row)->bool, or None when no file is given.
    A row is relevant when EITHER:
      * it carries via_competitors evidence (it linked to a curated competitor
        in the target niche — strongest signal), OR
      * its domain tokens overlap the extracted category keywords.
    Rows already owned (acquired) always pass: they are evidence, not prospects.
    """
    if not keywords_file:
        return None
    data = json.load(open(keywords_file, encoding="utf-8"))
    tokens = set()
    for c in data.get("categories") or []:
        for phrase in c.get("keywords") or []:
            for t in str(phrase).lower().split():
                if len(t) > 2:
                    tokens.add(t)
    comps = set(str(x).lower() for x in (data.get("competitors") or []))

    def is_relevant(row):
        if row.get("acquired"):
            return True
        vias = set(str(x).lower() for x in (row.get("via_competitors") or []))
        if vias and (not comps or (vias & comps)):
            return True
        dom = re.sub(r"[^a-z0-9]+", " ", str(row.get("domain") or "").lower())
        return bool(tokens & set(dom.split()))

    return is_relevant


def export(store_data, only_valid=False, relevance=None):
    """Return (candidates, skipped_stats) from a loaded prospector store.

    only_valid=True drops rows whose live HTTP check failed — a WDC harvest of
    a 2012 graph yields thousands of dead hosts, and importing those into the
    workbench ledger wastes operator attention. Rows already owned
    (acquired=True) are kept regardless: they are evidence, not prospects.

    relevance, when given, is a callable(row)->bool (see load_relevance).
    """
    cands, skipped = [], {"competitor": 0, "no_url": 0, "suppressed": 0,
                          "invalid": 0, "irrelevant": 0}
    sup = store_data.get("suppressions", {})
    for domain, row in (store_data.get("domains", {}) or {}).items():
        if not isinstance(row, dict):
            continue
        if row.get("is_competitor"):
            skipped["competitor"] += 1
            continue
        if st._norm_target(domain) in sup:
            skipped["suppressed"] += 1
            continue
        if only_valid and not row.get("valid") and not row.get("acquired"):
            skipped["invalid"] += 1
            continue
        if relevance is not None and not relevance(row):
            skipped["irrelevant"] += 1
            continue
        cand = _candidate(row)
        if not cand["url"] or not cand["domain"]:
            skipped["no_url"] += 1
            continue
        cands.append(cand)
    cands.sort(key=lambda c: (c["status"] != "pending", c["domain"] or ""))
    return cands, skipped


def selftest():
    """Assert the field contract without touching disk or network. Returns 0/1."""
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))

    fake = {
        "domains": {
            "good.org": {
                "url": "https://good.org/", "domain": "good.org",
                "type_key": "resource", "type_label_zh": "资源页",
                "authority_tier": "High", "priority": 88, "valid": True,
                "http_status": 200, "acquired": False, "is_competitor": False,
                "source": "seed", "note": "note",
                "authority": {"tranco_global_rank": 1234},
                "via_competitors": [],
            },
            "comp.com": {
                "url": "https://comp.com", "domain": "comp.com",
                "is_competitor": True, "source": "seed",
            },
            "via.org": {
                "url": "https://via.org", "domain": "via.org",
                "type_key": "directory", "is_competitor": False,
                "source": "competitor_backlink",
                "via_competitors": ["myinstants.com"], "acquired": True,
            },
            "owned.org": {
                "url": "https://owned.org", "domain": "owned.org",
                "is_competitor": False, "acquired": True, "source": "seed",
            },
            "dead.org": {
                "url": "https://dead.org", "domain": "dead.org",
                "type_key": "resource", "is_competitor": False,
                "valid": False, "http_status": 502,
                "source": "competitor_backlink", "via_competitors": ["myinstants.com"],
            },
        },
        "suppressions": {},
    }
    cands, skipped = export(fake)
    by_domain = {c["domain"]: c for c in cands}

    ck("competitor host dropped", "comp.com" not in by_domain)
    ck("competitor counted", skipped["competitor"] == 1)
    ck("competitor backlink admitted", "via.org" in by_domain)
    ck("competitor tag set", "competitor_backlink" in by_domain["via.org"]["tags"])
    ck("competitor found_by", by_domain["via.org"]["found_by"] == "prospector:competitor_backlink")
    ck("acquired -> done", by_domain["owned.org"]["status"] == "done")
    ck("gap -> pending", by_domain["good.org"]["status"] == "pending")
    ck("category mapped", by_domain["good.org"]["category"] == "resource")
    ck("unknown type -> other", by_domain["owned.org"]["category"] == "other")
    ck("provenance in note", "发现打分: 88" in by_domain["good.org"]["note"])
    ck("tranco in note", "Tranco: 1234" in by_domain["good.org"]["note"])
    ck("url normalized", by_domain["good.org"]["url"] == "https://good.org")
    ck("http status carried", by_domain["good.org"]["link_http_status"] == 200)
    ck("no fit_score field", "fit_score" not in by_domain["good.org"])

    # --only-valid: dead rows out, owned rows kept regardless
    cands_v, skipped_v = export(fake, only_valid=True)
    by_v = {c["domain"]: c for c in cands_v}
    ck("only_valid drops dead", "dead.org" not in by_v)
    ck("only_valid counts invalid", skipped_v["invalid"] == 1)
    ck("only_valid keeps acquired", "owned.org" in by_v)
    ck("only_valid keeps valid", "good.org" in by_v)

    # relevance: via-competitor evidence and domain keyword match pass
    # (good.org has no via + no keyword -> filtered; via.org has via evidence)
    def rel(row):
        if row.get("acquired"):
            return True
        vias = set(str(x).lower() for x in (row.get("via_competitors") or []))
        if vias:
            return True
        dom = re.sub(r"[^a-z0-9]+", " ", str(row.get("domain") or "").lower())
        return bool(set(dom.split()) & {"good", "via"})

    cands_r, skipped_r = export(fake, relevance=rel)
    by_r = {c["domain"]: c for c in cands_r}
    ck("relevance keeps via evidence", "via.org" in by_r)
    ck("relevance keeps domain match", "good.org" in by_r)
    ck("relevance keeps acquired", "owned.org" in by_r)
    ck("relevance counts skipped", "comp.com" not in by_r)

    failed = [n for n, ok in checks if not ok]
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
    print("%d PASS / %d FAIL" % (len(checks) - len(failed), len(failed)))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--center-domain", help="prospector center domain, e.g. soundbuttons.cc")
    ap.add_argument("--out", help="output candidates JSON path")
    ap.add_argument("--dry-run", action="store_true", help="do not write the file")
    ap.add_argument("--only-valid", action="store_true",
                    help="drop rows whose live HTTP check failed (dead links); "
                         "already-owned rows are always kept")
    ap.add_argument("--relevance", metavar="KEYWORDS_JSON",
                    help="path to an extracted-keywords JSON; drop candidates "
                         "with no category relevance (via-competitor evidence "
                         "or domain keyword match)")
    ap.add_argument("--list-domains", action="store_true",
                    help="list per-domain pools found under data/")
    ap.add_argument("--selftest", action="store_true",
                    help="run field-contract assertions, no disk/network writes")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    data_dir = st.DATA_DIR
    if args.list_domains:
        found = []
        for name in sorted(os.listdir(data_dir)):
            if name.startswith("store-") and name.endswith(".json"):
                dom = name[len("store-"):-len(".json")]
                found.append(dom)
        print("Available pools in %s:" % data_dir)
        for dom in found:
            print("  " + dom)
        if not found:
            print("  (none)")
        return 0

    if not args.center_domain:
        ap.error("--center-domain is required (or use --list-domains)")

    store_data = st.load_store(args.center_domain)
    relevance = load_relevance(args.relevance) if args.relevance else None
    cands, skipped = export(store_data, only_valid=args.only_valid,
                            relevance=relevance)
    payload = {
        "candidates": cands,
        "meta": {
            "center_domain": args.center_domain,
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_store": os.path.basename(st.get_store_path(args.center_domain)),
            "count": len(cands),
            "skipped": skipped,
            "note": "Import with: blw --workspace ~/seo add --file <this file>",
        },
    }

    if args.dry_run or not args.out:
        print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))
        print("Sample candidate:")
        if cands:
            print(json.dumps(cands[0], ensure_ascii=False, indent=2))
        print("(dry-run: no file written)" if args.dry_run else "(no --out: preview only)")
        return 0

    out_path = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("Exported %d candidates -> %s" % (len(cands), out_path))
    print("Skipped: %s" % json.dumps(skipped, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
