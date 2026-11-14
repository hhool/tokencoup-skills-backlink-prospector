#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression guard for the delivery-ledger contract.

The candidate pool and the delivery ledger are two different layers. This
suite asserts the invariants that keep "already delivered, never reused"
true, plus the bilingual UI that exposes them.

Usage:
    python3 tools/placement_selftest.py http://127.0.0.1:8787/
    python3 tools/placement_selftest.py https://backlink-prospector.fly.dev/

Sections:
    A  store-level state machine (no HTTP, no persistent writes)
    B  HTTP endpoints (uses a throwaway center domain)
    C  gap semantics: seen != owned, legacy switch still reproducible
    D  real-Chrome rendering of the ledger in ZH / EN / ZH
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import store as st  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787/").rstrip("/")
# `--no-write` skips the mutating HTTP section, so a production run against
# Fly leaves no throwaway ledger file on the persistent volume.
NO_WRITE = "--no-write" in sys.argv[2:]
# A fresh center domain per run keeps section B idempotent: the ledger is
# append-only by design, so replaying against the same domain must not be
# mistaken for a regression.
TEST_DOMAIN = "placement-selftest-%d.example" % os.getpid()
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
FAILS = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name, (" -> " + str(detail)) if detail else ""))
    if not cond:
        FAILS.append(name)


def http(path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with OPENER.open(req, timeout=240) as f:
            return f.status, json.load(f)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def http_text(path):
    with OPENER.open(BASE + path, timeout=60) as f:
        return f.read().decode("utf-8-sig")


def fresh():
    return {"domains": {}, "placements": {}, "suppressions": {}, "acquired_domains": []}


SLOT = {"target_domain": "parents.com", "target_url": "https://parents.com/guest-post",
        "placement_type": "guest_post", "own_url": "https://own.example/guide"}


def section_a():
    print("\n=== A. store-level state machine ===")
    s = fresh()
    rec, why = st.claim_placement(s, SLOT)
    check("claim succeeds", rec is not None and rec["state"] == "claimed", why)
    check("claim is idempotent by slot key",
          st.claim_placement(s, SLOT)[1] is not None)
    check("key normalizes case / trailing slash / type case",
          st.placement_key("Parents.com", "https://parents.com/guest-post/", "Guest_Post")
          == st.placement_key(*(SLOT[k] for k in ("target_domain", "target_url", "placement_type"))))
    check("live without evidence is rejected",
          st.transition_placement(s, {"id": rec["id"], "state": "live"})[1] is not None)
    live, why = st.transition_placement(s, {
        "id": rec["id"], "state": "live",
        "landing_url": SLOT["target_url"], "verify_method": "manual-anchor-check",
        "anchor_text": "balance bike guide", "rel": "dofollow"})
    check("live with evidence is accepted", live is not None and live["state"] == "live", why)
    check("evidence is persisted", bool(live and live["verify"]["verified_at"]))
    check("live domain enters owned_domains", "parents.com" in st.owned_domains(s))
    check("live slot cannot be claimed again",
          "live" in (st.claim_placement(s, SLOT)[1] or ""))
    other = dict(SLOT, target_url="https://parents.com/resource-page")
    check("same domain respects the 90-day cadence",
          "cadence" in (st.claim_placement(s, other)[1] or ""))
    check("illegal transition is rejected",
          st.transition_placement(s, {"id": rec["id"], "state": "submitted"})[1] is not None)
    st.suppress_placement(s, {"target_domain": "blocked.com", "reason": "explicit refusal"})
    check("suppression blocks a claim",
          "suppressed" in (st.claim_placement(s, {
              "target_domain": "blocked.com", "target_url": "https://blocked.com/x"})[1] or ""))
    st.transition_placement(s, {"id": rec["id"], "state": "lost"})
    check("lost link requires manual review",
          "manual review" in (st.claim_placement(s, SLOT)[1] or ""))
    s2 = fresh()
    s2["domains"] = {"parents.com": {"domain": "parents.com", "priority": 5}}
    r, _ = st.claim_placement(s2, SLOT)
    st.transition_placement(s2, {"id": r["id"], "state": "live",
                                 "landing_url": SLOT["target_url"], "verify_method": "manual"})
    rows = st.domain_list(s2)
    check("pool rows are decorated with placement_state",
          rows and rows[0]["placement_state"] == "live", rows[:1])
    check("stats expose live / in_progress / suppressed",
          all(k in st.placement_stats(s2) for k in ("live", "in_progress", "suppressed")))
    # P2: batch claim
    s3 = fresh()
    batch = [
        {"target_domain": "a.com", "target_url": "https://a.com/p1", "placement_type": "guest_post"},
        {"target_domain": "b.com", "target_url": "https://b.com/p2", "placement_type": "resource"},
        {"target_domain": "a.com", "target_url": "https://a.com/p1", "placement_type": "guest_post"},  # dup
    ]
    out = st.claim_placements_batch(s3, batch)
    check("batch claims distinct slots", out["claimed"] == 2, out)
    check("batch dedupes repeated slot", out["blocked"] == 1, out)
    st.suppress_placement(s3, {"target_domain": "b.com", "reason": "refused"})
    out2 = st.claim_placements_batch(s3, [{"target_domain": "b.com", "target_url": "https://b.com/p2"}])
    check("batch reports blocked by suppression",
          out2["blocked"] == 1 and out2["claimed"] == 0, out2)
    check("batch rejects non-array input",
          st.claim_placements_batch(s3, "not-a-list")["blocked"] == 1)


def section_b():
    print("\n=== B. HTTP endpoints ===")
    status, d = http("/api/placements?domain=" + TEST_DOMAIN)
    check("GET /api/placements", status == 200 and d.get("ok") is True, status)
    code, d = http("/api/placements/claim", dict(SLOT, center_domain=TEST_DOMAIN))
    check("POST claim", code == 200 and d["placement"]["state"] == "claimed", code)
    code, d = http("/api/placements/claim", dict(SLOT, center_domain=TEST_DOMAIN))
    check("duplicate claim -> 409", code == 409, code)
    code, d = http("/api/placements/transition",
                   dict(SLOT, center_domain=TEST_DOMAIN, state="live"))
    check("live without evidence -> 409", code == 409, code)
    code, d = http("/api/placements/transition", dict(
        SLOT, center_domain=TEST_DOMAIN, state="live",
        landing_url=SLOT["target_url"], verify_method="manual-anchor-check", rel="dofollow"))
    check("live with evidence -> 200", code == 200 and d["placement"]["state"] == "live", code)
    code, d = http("/api/placements/claim", dict(SLOT, center_domain=TEST_DOMAIN))
    check("reuse of live slot -> 409", code == 409, code)
    code, d = http("/api/placements/suppress", {"center_domain": TEST_DOMAIN,
                                                "target_domain": "blocked.com", "reason": "refused"})
    check("POST suppress", code == 200, code)
    status, d = http("/api/placements?domain=" + TEST_DOMAIN)
    check("ledger stats reflect live", d["stats"]["live"] == 1, d["stats"])
    csv_text = http_text("/api/placements/csv?domain=" + TEST_DOMAIN)
    head = csv_text.splitlines()[0]
    check("ledger CSV has evidence columns",
          all(c in head for c in ("landing_url", "verify_method", "verified_at")), head[:120])
    check("ledger CSV contains the record", len(csv_text.strip().splitlines()) >= 2)
    items = [
        {"target_domain": "batch1.com", "target_url": "https://batch1.com/post", "placement_type": "guest_post"},
        {"target_domain": "batch2.com", "target_url": "https://batch2.com/page", "placement_type": "resource"},
    ]
    code, d = http("/api/placements/claim-batch", {"center_domain": TEST_DOMAIN, "items": items})
    check("POST claim-batch", code == 200 and d["claimed"] == 2 and d["blocked"] == 0,
          (code, d.get("claimed"), d.get("blocked")))
    code, d = http("/api/placements/claim-batch", {"center_domain": TEST_DOMAIN,
              "items": [{"target_domain": "batch1.com", "target_url": "https://batch1.com/post",
                         "placement_type": "guest_post"},
                        {"target_domain": "batch3.com", "target_url": "https://batch3.com/x",
                         "placement_type": "resource"}]})
    check("claim-batch idempotent on dup", code == 200 and d["claimed"] == 1 and d["blocked"] == 1,
          (code, d.get("claimed"), d.get("blocked")))


def section_c():
    print("\n=== C. gap semantics (seen is not owned) ===")
    body = {"domain": "balancebiketoddler.com", "keywords": "balance bike",
            "competitors": "", "existing": "", "center_domain": "balancebiketoddler.com",
            "use_bing": "0", "use_tranco": "0", "persist": "0"}
    code, new = http("/api/analyze", body)
    code2, legacy = http("/api/analyze", dict(body, use_pool_as_existing="1"))
    check("analyze endpoints reachable", code == 200 and code2 == 200, (code, code2))
    nr, lr = new["result"], legacy["result"]
    gaps = lambda t: sum(1 for p in t["prospects"] if p.get("is_gap"))
    owned = lambda t: sum(1 for p in t["prospects"] if p.get("already_have"))
    check("default: pool membership does not mark already_have",
          owned(nr) == 0 and gaps(nr) > 0, "gaps=%d owned=%d" % (gaps(nr), owned(nr)))
    check("envelope separates owned from seen (no pool-as-existing)",
          nr["existing_library"]["seen"] > 0
          and nr["existing_library"]["pool_used_as_existing"] is False
          and nr["existing_library"]["size"] != nr["existing_library"]["seen"],
          nr["existing_library"])
    check("legacy switch still reproduces old behaviour",
          gaps(lr) == 0 and owned(lr) > 0, "gaps=%d owned=%d" % (gaps(lr), owned(lr)))
    check("EN limitation states the new rule",
          "Seen candidates are not owned" in nr["limitations"][5])
    check("ZH limitation states the new rule", "见过不等于已拥有" in nr["limitations_zh"][5])


def section_d():
    print("\n=== D. real-Chrome ledger rendering ===")
    from playwright.sync_api import sync_playwright
    cjk = lambda s: any("\u4e00" <= c <= "\u9fff" for c in (s or ""))
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/", wait_until="networkidle")
        time.sleep(1.5)
        pg.click('[data-tab="pool"]')
        time.sleep(0.6)
        pg.click("#poolLoad")
        pg.wait_for_selector("#poolTable:not(.hidden)", timeout=90000)
        pg.wait_for_selector("#plTable:not(.hidden)", timeout=60000)
        time.sleep(0.8)
        check("ZH ledger title localized", "投放台账" in pg.inner_text("#tab-pool"))
        check("ZH pool rows show placement column",
              pg.eval_on_selector_all("#poolTable thead th", "els=>els.some(e=>e.innerText.trim()==='投放')"))
        pg.click("#langToggle")
        time.sleep(1.2)
        check("EN ledger title localized",
              "Delivery ledger" in pg.inner_text("#tab-pool"))
        en_text = pg.inner_text("#tab-pool")
        ledger_part = en_text.split("Delivery ledger", 1)[-1]
        check("EN ledger copy is CJK-free", not cjk(ledger_part), ledger_part[:120])
        check("EN ledger summary rendered", "Records" in pg.inner_text("#plSummary"))
        pg.click("#langToggle")
        time.sleep(1.0)
        check("ZH restored after roundtrip", "投放台账" in pg.inner_text("#tab-pool"))
        check("no JS errors", not errs, errs[:3])
        b.close()


if __name__ == "__main__":
    print("placement_selftest -> %s" % BASE)
    section_a()
    if NO_WRITE:
        print("\n=== B. HTTP endpoints === (skipped: --no-write)")
    else:
        section_b()
    section_c()
    section_d()
    # Remove only this run's throwaway store file when the server is local.
    # data/ is gitignored machine-local state; nothing versioned is touched.
    try:
        path = st.get_store_path(TEST_DOMAIN)
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    print("\n" + ("ALL CHECKS PASSED" if not FAILS else "FAILED %d: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
