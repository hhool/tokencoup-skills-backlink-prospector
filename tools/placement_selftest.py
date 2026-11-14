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
    E  in-app help: per-view tips toggles + the standalone /help page
    F  competitor semantics (excluded hosts vs. admitted competitor backlinks)
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
    # Position-independent: limitations is an append-friendly list, so assert on
    # content rather than a hardcoded index.
    check("EN limitation states the new rule",
          any("Seen candidates are not owned" in x for x in nr["limitations"]))
    check("ZH limitation states the new rule",
          any("见过不等于已拥有" in x for x in nr["limitations_zh"]))


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


def section_e():
    """In-app tips + the standalone /help page.

    Read-only: it opens pages, clicks toggles and reads text. Nothing is written,
    so it also runs under --no-write against production.
    """
    print("\n=== E. in-app help ===")
    cjk = lambda s: any("\u4e00" <= c <= "\u9fff" for c in (s or ""))

    code, body = 0, ""
    try:
        body = http_text("/help")
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    check("/help returns 200", code == 200, code)
    check("/help ships both language blocks",
          'class="doc-zh"' in body and 'class="doc-en"' in body)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/", wait_until="networkidle")
        time.sleep(1.5)

        # one tip toggle per view (the types tab has its own richer tips body)
        for tab in ("ov", "analyze", "pool", "sched"):
            pg.click('[data-tab="%s"]' % tab)
            time.sleep(0.3)
            check("tip toggle present on %s" % tab,
                  pg.eval_on_selector_all('[data-tipbtn="%s"]' % tab, "e=>e.length") == 1)

        pg.click('[data-tab="ov"]')
        time.sleep(0.3)
        check("tip body starts hidden", pg.is_hidden("#tip-ov"))
        pg.click('[data-tipbtn="ov"]')
        time.sleep(0.4)
        check("clicking the tip reveals it", pg.is_visible("#tip-ov"))
        check("tip sets aria-expanded",
              pg.get_attribute('[data-tipbtn="ov"]', "aria-expanded") == "true")
        check("ZH tip copy is meaningful", "缺口" in pg.inner_text("#tip-ov"))

        # language switch must flip the tip copy too, with no CJK left in EN
        pg.click("#langToggle")
        time.sleep(1.2)
        en_tip = pg.inner_text("#tip-ov")
        check("EN tip copy is CJK-free", not cjk(en_tip), en_tip[:80])
        check("EN help link carries lang",
              "lang=en" in (pg.get_attribute("#helpBtn", "href") or ""))

        # the standalone page, opened the way the app links it
        pg2 = b.new_page(viewport={"width": 1200, "height": 900})
        errs2 = []
        pg2.on("pageerror", lambda e: errs2.append(str(e)))
        pg2.goto(BASE + "/help?lang=en", wait_until="networkidle")
        time.sleep(1.0)
        # The language switcher itself reads "中文" in EN mode by design (a
        # switcher names the language it switches to), same convention as the
        # app's own #langToggle exclusion in tools/i18n_audit.py.
        pg2.eval_on_selector("#langBtn", "e=>e.style.visibility='hidden'")
        visible = pg2.inner_text("body")
        pg2.eval_on_selector("#langBtn", "e=>e.style.visibility=''")
        check("help EN page is CJK-free", not cjk(visible), [c for c in visible if cjk(c)][:5])
        check("help EN page renders the loop", "Five-step loop" in visible)
        pg2.click("#langBtn")
        time.sleep(0.6)
        check("help toggles back to ZH", "五步闭环" in pg2.inner_text("body"))
        check("help page updates the URL", "lang=zh" in pg2.url, pg2.url)
        check("no JS errors (help)", not errs2, errs2[:3])
        check("no JS errors (app)", not errs, errs[:3])
        b.close()


def section_f():
    """Competitor semantics: a competitor is never a target, its backlinks are.

    Also covers the domain picker endpoint, which exists because free-text
    entry produced two parallel pools (.cc vs .click) nobody could tell apart.
    """
    print("\n=== F. competitor semantics & domain picker ===")

    st_code, st_body = http("/api/domains")
    check("/api/domains ok", st_code == 200 and st_body.get("ok") is True, st_code)
    doms = st_body.get("domains") or []
    check("/api/domains returns rows", bool(doms), len(doms))
    check("/api/domains rows are complete",
          all(d.get("domain") and d.get("label") and d.get("sources") for d in doms),
          doms[:1])

    if NO_WRITE:
        print("  (harvest + analyze checks skipped: --no-write)")
        return

    harvest = os.path.join(ROOT, "tools", "competitor_backlinks.py")
    ranks = os.path.join(ROOT, "tools", "testdata", "wdc-domain-ranks.txt")
    edges = os.path.join(ROOT, "tools", "testdata", "wdc-domain-edges.txt")
    out = os.path.join(ROOT, "data", "competitor-links-%s.json" % TEST_DOMAIN)
    seed = os.path.join(ROOT, "data", "seed-%s.json" % TEST_DOMAIN)
    try:
        import subprocess
        proc = subprocess.run([sys.executable, harvest, "--center", TEST_DOMAIN,
                               "--competitors", "compa.test,compb.test",
                               "--ranks", ranks, "--edges", edges, "--out", out],
                              capture_output=True, text=True)
        check("harvest tool exits 0", proc.returncode == 0, proc.stderr[-160:])
        payload = json.load(open(out, encoding="utf-8"))
        rows, meta = payload["rows"], payload["meta"]
        check("harvest emits the 4 real sources", len(rows) == 4,
              [r["url"] for r in rows])
        check("noise host is dropped", all("youtube" not in r["url"] for r in rows))
        check("competitor subdomain is not a source",
              all("compa.test" not in r["url"] for r in rows))
        check("multi-competitor host keeps both vias",
              any(len(r["via_competitors"]) == 2 for r in rows),
              [r["via_competitors"] for r in rows])
        check("rows carry edge evidence",
              all(r["evidence"]["edges"] >= 1 for r in rows))
        check("harvest meta is self-describing",
              meta.get("center_domain") == TEST_DOMAIN and meta.get("rows") == len(rows))

        # A competitor row in the seed library must never become a candidate.
        json.dump([
            {"url": "https://compa.test/tools", "type": "resource", "tags": ["sound"],
             "authorityTier": "High", "domains": [TEST_DOMAIN],
             "note": "竞品自己", "note_en": "competitor itself"},
            {"url": "https://seed-good.test/list", "type": "directory", "tags": ["sound"],
             "authorityTier": "Medium", "domains": [TEST_DOMAIN],
             "note": "正常种子", "note_en": "normal seed"},
            # Deliberately overlaps the harvest output: the row must be enriched
            # with the evidence, never duplicated.
            {"url": "https://fansite.test/links", "type": "resource", "tags": ["sound"],
             "authorityTier": "Low", "domains": [TEST_DOMAIN],
             "note": "种子也在竞品外链里", "note_en": "seed that is also a competitor backlink"},
        ], open(seed, "w", encoding="utf-8"), ensure_ascii=False)

        code, d = http("/api/analyze", {"center_domain": TEST_DOMAIN, "domain": TEST_DOMAIN,
                                        "competitors": "compa.test", "use_bing": "0",
                                        "use_tranco": "0", "persist": "0"})
        r = d.get("result") or {}
        tot = r.get("totals") or {}
        pros = r.get("prospects") or []
        check("analyze ok", code == 200 and bool(pros), code)
        check("competitor host is not a candidate",
              all(p["domain"] != "compa.test" for p in pros),
              [p["domain"] for p in pros if p["domain"] == "compa.test"])
        check("competitor hosts are reported separately",
              tot.get("competitor_rows") >= 1 and
              any(c["domain"] == "compa.test" for c in (r.get("competitor_rows") or [])),
              tot.get("competitor_rows"))
        check("candidate count excludes competitor rows",
              tot.get("candidates") == len(pros), (tot.get("candidates"), len(pros)))
        check("competitor-backlink rows are admitted",
              tot.get("from_competitors") == 3, tot.get("from_competitors"))
        check("no duplicate row per domain",
              len({p["domain"] for p in pros}) == len(pros),
              [p["domain"] for p in pros])
        enriched = [p for p in pros if p["domain"] == "fansite.test"]
        check("overlapping seed row is enriched, not duplicated",
              len(enriched) == 1 and enriched[0]["source"] == "seed"
              and enriched[0]["via_competitors"],
              (enriched[0]["source"], enriched[0]["via_competitors"]) if enriched else None)
        check("enriched row scores evidence-relevance",
              enriched and enriched[0]["relevance"] >= 29,
              enriched[0]["relevance"] if enriched else None)
        cb = [p for p in pros if p.get("source") == "competitor_backlink"]
        check("evidence rows carry via_competitors",
              cb and all(p.get("via_competitors") for p in cb),
              [p.get("via_competitors") for p in cb][:2])
        check("evidence rows are still ordinary gaps",
              all(p["is_gap"] for p in cb))
        src = (r.get("data_sources") or {}).get("competitor_backlinks") or {}
        check("data_sources reports the harvest",
              src.get("status") == "ok" and src.get("rows") == 4, src)
        check("zh limitations explain competitor exclusion",
              any("竞品" in x for x in (r.get("limitations_zh") or [])))
        check("en limitations explain competitor exclusion",
              any("Competitor" in x for x in (r.get("limitations") or [])))

        # The picker must now offer the throwaway domain with its counts.
        code2, d2 = http("/api/domains")
        mine = [x for x in (d2.get("domains") or []) if x["domain"] == TEST_DOMAIN]
        check("picker lists the analyzed domain", bool(mine), TEST_DOMAIN)
        if mine:
            check("picker reports the competitor harvest",
                  mine[0].get("competitor_links") == 4, mine[0])
    finally:
        for p in (out, seed):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    print("placement_selftest -> %s" % BASE)
    section_a()
    if NO_WRITE:
        print("\n=== B. HTTP endpoints === (skipped: --no-write)")
    else:
        section_b()
    section_c()
    section_d()
    section_e()
    section_f()
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
