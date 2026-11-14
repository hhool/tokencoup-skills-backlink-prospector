#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean and migrate the legacy backlink pool into per-center-domain stores.

Why this exists: before the domain-scoped seed library and the strict keyword
relevance gate, poisoned search-cache responses injected off-topic and even
adult/gambling domains into the pool. The legacy `data/store.json` therefore
contains entries that are worthless or unsafe for the domain.

This tool:
  * keeps only entries that are (a) not blocklisted and (b) actually relevant to
    the target domain's own keyword profile;
  * writes the survivors into the domain-isolated store (data/store-<domain>.json);
  * quarantines everything it dropped into data/store.quarantine-<ts>.json so the
    removal is auditable and reversible (nothing is silently deleted).

Usage:
    python3 tools/migrate_pools.py --domain soundbuttons.cc [--apply]
    python3 tools/migrate_pools.py --domain balancebiketoddler.com --apply
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import analyze as an  # noqa: E402
import store as st  # noqa: E402


def relevant(domain, url, keywords, seed_domains):
    """A legacy entry survives only if it belongs to the domain's own scope.

    Two accepted proofs:
      1. the host is part of the domain-scoped seed library (curated + verified);
      2. the host/url/note actually matches the domain's keyword profile
         (i.e. it came from a live discovery hit that passed the relevance gate).
    """
    if seed_domains and domain in seed_domains:
        return True
    if not keywords:
        return False
    hay = an._norm_text(" ".join([domain or "", url or ""]))
    for k in keywords:
        nk = an._norm_text(k)
        if nk and nk in hay:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, help="center domain, e.g. soundbuttons.cc")
    ap.add_argument("--apply", action="store_true", help="write the result (default: dry run)")
    ap.add_argument("--sanitize-legacy", action="store_true",
                    help="also scrub the legacy data/store.json in place")
    args = ap.parse_args()

    domain = args.domain.strip().lower()
    legacy = st.load_store(None)
    target = st.load_store(domain)
    prof = st.load_profile(domain)
    keywords = prof.get("keywords") or []
    print("center domain : %s" % domain)
    print("profile source: %s (%d keywords)" % (prof.get("source"), len(keywords)))
    print("legacy pool   : %d entries" % len(legacy.get("domains", {})))
    print("target pool   : %d entries" % len(target.get("domains", {})))
    if not keywords:
        print("!! no keyword profile for this domain - refusing to migrate")
        return 2

    keep, drop = {}, {}
    seed_rows, _scope = an.load_seed_for(domain)
    seed_domains = {an.domain_of(r.get("url", "")) for r in seed_rows}
    print("seed scope    : %d curated hosts" % len(seed_domains))
    for d, e in legacy.get("domains", {}).items():
        if an.is_blocked(d):
            drop[d] = {"reason": "blocklist", "url": e.get("url")}
        elif not relevant(d, e.get("url"), keywords, seed_domains):
            drop[d] = {"reason": "off-niche", "url": e.get("url")}
        else:
            keep[d] = e

    print("\nkeep %d / drop %d" % (len(keep), len(drop)))
    if drop:
        print("dropped (sample):")
        for d, info in list(drop.items())[:20]:
            print("   %-34s %s" % (d, info["reason"]))

    if not args.apply:
        print("\n(dry run - pass --apply to write)")
        return 0

    merged = dict(target.get("domains", {}))
    merged.update(keep)
    target["domains"] = merged
    target["acquired_domains"] = sorted(set(target.get("acquired_domains", []))
                                        | set(legacy.get("acquired_domains", [])))
    for d in target["acquired_domains"]:
        if d in target["domains"]:
            target["domains"][d]["acquired"] = True
    st.save_store(target, domain)

    if drop:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        qpath = os.path.join(st.DATA_DIR, "store.quarantine-%s.json" % ts)
        with open(qpath, "w", encoding="utf-8") as f:
            json.dump({"quarantined_at": ts, "center_domain": domain,
                       "reason": "off-niche / blocklisted entries removed by tools/migrate_pools.py",
                       "entries": drop}, f, ensure_ascii=False, indent=2)
        print("\nquarantine file: %s" % qpath)

    print("target pool now: %d entries" % len(target["domains"]))

    if args.sanitize_legacy:
        # The legacy store is still reachable via /api/store without a domain
        # parameter, so scrub it too: keep only the migrated survivors and move
        # the rest into the same quarantine file.
        legacy["domains"] = dict(keep)
        legacy["acquired_domains"] = sorted(set(legacy.get("acquired_domains", []))
                                            & set(keep))
        st.save_store(legacy, None)
        print("legacy pool sanitized: %d entries" % len(legacy["domains"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
