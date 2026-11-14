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


def section_g():
    """Daily queue: a frozen batch, a hard quota, and an honest supply gap.

    The point of this section is the distinction the operator asked for: 100 a
    day is a WORK quota, not a production rate. The batch freezes so the same
    day never reshuffles, claimed rows leave it, and anything the inventory
    cannot cover shows up as supply_gap instead of being invented.
    """
    print("\n=== G. daily queue: quota + frozen batch ===")
    center = TEST_DOMAIN

    def qstore(n):
        return {"domains": {("q%03d.example" % i): {"url": "https://q%03d.example" % i,
                                                   "priority": 200 - i, "valid": True,
                                                   "source": "seed"} for i in range(n)},
                "placements": {}, "suppressions": {}, "acquired_domains": []}

    try:
        s = qstore(120)
        s["domains"]["q000.example"]["acquired"] = True
        s["domains"]["q001.example"]["valid"] = False
        s["domains"]["q002.example"]["is_competitor"] = True
        s["suppressions"]["q003.example"] = {"reason": "operator excluded"}

        q = st.daily_queue(s, center, date="2026-01-02", quota=100)
        check("inventory excludes acquired / invalid / competitor / suppressed",
              q["inventory"] == 116, q["inventory"])
        check("batch is capped at the quota",
              (q["batch_size"], q["available"]) == (100, 100),
              (q["batch_size"], q["available"]))
        check("no gap when inventory covers the quota", q["supply_gap"] == 0, q["supply_gap"])
        check("batch id carries the day", q["batch_id"].endswith("20260102"), q["batch_id"])
        check("batch rows carry what outreach needs",
              all(r.get("domain") and r.get("url") and r.get("priority") is not None
                  for r in q["items"]), q["items"][:1])

        q2 = st.daily_queue(s, center, date="2026-01-02", quota=100)
        check("batch is frozen within the day",
              [i["domain"] for i in q2["items"]] == [i["domain"] for i in q["items"]])

        for it in q["items"][:3]:
            st.claim_placement(s, {"target_domain": it["domain"], "target_url": it["url"],
                                   "batch_id": q["batch_id"]})
        q3 = st.daily_queue(s, center, date="2026-01-02", quota=100)
        check("claimed rows leave the batch", q3["available"] == 97, q3["available"])
        check("claimed_today counts the batch id", q3["claimed_today"] == 3, q3["claimed_today"])

        q4 = st.daily_queue(s, center, date="2026-01-03", quota=100)
        check("a new day freezes a new batch",
              q4["batch_id"] != q["batch_id"] and q4["batch_size"] == 100,
              (q4["batch_id"], q4["batch_size"]))
        check("a claimed domain never returns",
              not ({i["domain"] for i in q4["items"]} & {i["domain"] for i in q["items"][:3]}))

        small = qstore(40)
        qs = st.daily_queue(small, center, date="2026-01-04", quota=100)
        check("short inventory reports a supply gap",
              (qs["batch_size"], qs["supply_gap"]) == (40, 60),
              (qs["batch_size"], qs["supply_gap"]))
        for i in range(40, 110):
            small["domains"]["q%03d.example" % i] = {"url": "https://q%03d.example" % i,
                                                     "priority": 1, "valid": True}
        qn = st.daily_queue(small, center, date="2026-01-04", quota=100)
        check("the batch never grows by itself", qn["batch_size"] == 40, qn["batch_size"])
        qr = st.daily_queue(small, center, date="2026-01-04", quota=100, refill=True)
        check("refill tops the batch up to the quota",
              (qr["batch_size"], qr["supply_gap"]) == (100, 0),
              (qr["batch_size"], qr["supply_gap"]))

        check("quota is clamped to a sane range",
              st.daily_queue(s, center, date="2026-01-05", quota=0)["quota"] >= 1
              and st.daily_queue(s, center, date="2026-01-05", quota=99999)["quota"] == st.MAX_DAILY_QUOTA)

        # Closing the loop: a verified live backlink must stop being a gap, and
        # a claim made outside the batch must still show up in today's throughput.
        lv = qstore(3)
        st.claim_placement(lv, {"target_domain": "q000.example",
                                "target_url": "https://q000.example", "batch_id": "t1"})
        lid = st.placement_key("q000.example", "https://q000.example", "link")
        st.transition_placement(lv, {"id": lid, "state": "live",
                                     "landing_url": "https://q000.example/post",
                                     "verify_method": "manual-check"})
        check("live writes acquired back into the pool",
              (lv["domains"].get("q000.example") or {}).get("acquired") is True)
        check("a delivered domain stops being a gap", st.store_stats(lv)["gap"] == 2,
              st.store_stats(lv)["gap"])
        check("live lands in owned_domains", "q000.example" in st.owned_domains(lv))

        z = qstore(5)
        st.claim_placement(z, {"target_domain": "q001.example",
                               "target_url": "https://q001.example"})  # no batch_id
        # claimed_day compares against the quota day (UTC+8), not the raw UTC day,
        # so a claim made at 00:30 local still belongs to today.
        qz = st.daily_queue(z, center, date=st._quota_date(), quota=100)
        check("claimed_day counts claims made outside the batch",
              (qz["claimed_day"], qz["claimed_today"]) == (1, 0),
              (qz["claimed_day"], qz["claimed_today"]))

        if not NO_WRITE:
            code, body = http("/api/queue?domain=%s&date=2026-01-02&quota=100" % center)
            qq = (body or {}).get("queue") or {}
            check("/api/queue ok", code == 200 and body.get("ok") is True, code)
            check("/api/queue exposes the counters",
                  all(k in qq for k in ("quota", "batch_size", "available", "claimed_today",
                                        "inventory", "supply_gap", "batch_id")), sorted(qq))
            code2, body2 = http("/api/store?domain=%s&date=2026-01-02" % center)
            check("/api/store carries the queue summary",
                  code2 == 200 and "queue" in (body2 or {}) and "items" not in body2["queue"],
                  sorted((body2 or {}).get("queue") or {}))
    finally:
        st.prune_queues(center, keep_days=-1)


def section_h():
    """Whitelist (excluded from stats) + the hard daily quota.

    Two rules the operator set explicitly: a whitelisted host must not move any
    backlink number, and 100/day is a ceiling that the server refuses to cross
    even when rows are claimed one by one from the pool.
    """
    print("\n=== H. whitelist + hard daily quota ===")
    center = TEST_DOMAIN + "-h"

    def wstore(n):
        return {"domains": {("w%03d.example" % i): {"url": "https://w%03d.example" % i,
                                                   "priority": 200 - i, "valid": True,
                                                   "type_key": "directory"} for i in range(n)},
                "placements": {}, "suppressions": {}, "acquired_domains": [],
                "whitelist": {}, "settings": {}}

    try:
        s = wstore(6)
        added = st.add_whitelist(s, ["https://www.W000.example/x?q=1", "w001.example",
                                     "not a host at all", ""])
        check("whitelist normalizes URL/www and rejects junk",
              added == ["w000.example", "w001.example"], added)
        check("whitelisting the same host twice is a no-op",
              st.add_whitelist(s, ["w000.example"]) == [])

        stats = st.store_stats(s)
        check("whitelisted rows leave the totals",
              (stats["total_discovered"], stats["gap"]) == (4, 4),
              (stats["total_discovered"], stats["gap"]))
        check("whitelist size is reported separately", stats["whitelisted"] == 2, stats["whitelisted"])
        check("whitelisted_in_pool counts only pool members",
              stats["whitelisted_in_pool"] == 2, stats["whitelisted_in_pool"])

        row = [r for r in st.domain_list(s) if r["domain"] == "w000.example"]
        check("a whitelisted row stays listed but is no longer a gap",
              bool(row) and row[0]["whitelisted"] is True and row[0]["is_gap"] is False,
              row[:1])

        q = st.daily_queue(s, center, date="2026-02-01", quota=100)
        batch = [i["domain"] for i in q["items"]]
        check("whitelisted rows never enter the queue",
              "w000.example" not in batch and "w001.example" not in batch, batch)
        check("queue block reason names the whitelist",
              st.queue_block_reason(s, "w000.example") == "whitelisted")

        rec, reason = st.claim_placement(s, {"target_domain": "w000.example",
                                             "target_url": "https://w000.example"})
        check("claiming a whitelisted slot is refused",
              rec is None and (reason or "").startswith("whitelisted"), reason)

        st.remove_whitelist(s, ["w000.example", "w001.example"])
        check("removing from the whitelist restores the numbers",
              st.store_stats(s)["total_discovered"] == 6, st.store_stats(s)["total_discovered"])

        # ---- hard quota --------------------------------------------------
        check("quota defaults to 100/day",
              st.effective_quota(wstore(1)) == st.DEFAULT_DAILY_QUOTA)
        quota, err = st.set_daily_quota(s, 3)
        check("quota is configurable", quota == 3 and err is None and st.effective_quota(s) == 3,
              (quota, err))
        check("out-of-range quota is rejected instead of clamped silently",
              bool(st.set_daily_quota(s, 0)[1]) and bool(st.set_daily_quota(s, 10 ** 6)[1])
              and st.effective_quota(s) == 3)

        items = [{"target_domain": "w%03d.example" % i,
                  "target_url": "https://w%03d.example" % i} for i in range(5)]
        out = st.claim_placements_batch(s, items)
        check("the batch stops exactly at the hard quota",
              (out["claimed"], out["blocked"], out["quota_blocked"]) == (3, 2, 2),
              (out["claimed"], out["blocked"], out["quota_blocked"]))
        check("the quota block explains itself",
              out["results"][-1]["reason"].startswith("daily quota reached"),
              out["results"][-1]["reason"])
        check("quota state reports the gate",
              (st.quota_state(s)["used"], st.quota_state(s)["left"]) == (3, 0),
              st.quota_state(s))

        st.set_daily_quota(s, 4)
        rec, reason = st.claim_placement(s, {"target_domain": "w004.example",
                                             "target_url": "https://w004.example"})
        check("raising the quota unblocks the next claim", rec is not None and reason is None, reason)

        st.set_daily_quota(s, 4)          # 4 used, 4 allowed -> full again
        rec2, reason2 = st.claim_placement(s, {"target_domain": "w005.example",
                                               "target_url": "https://w005.example"})
        check("the single pool 'Use' path is gated too",
              rec2 is None and (reason2 or "").startswith("daily quota reached"), reason2)
        check("a past day does not eat today's quota", st.claimed_on(s, "2020-01-01") == 0)

        # Per-day queue files: a caller that forgets `date` must not be able to
        # rebuild the batch someone is already working from.
        check("queue files are keyed by day",
              st._queue_path(center, "2026-03-01").endswith("-20260301.json"))
        q_auto = st.daily_queue(s, center)
        check("a date-less call lands on the quota day",
              q_auto["batch_id"].endswith(st._quota_date().replace("-", "")), q_auto["batch_id"])
        old_f, new_f = (st._queue_path(center, "2025-01-01"),
                        st._queue_path(center, st._quota_date()))
        for f in (old_f, new_f):
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("{}")
        st.prune_queues(center)
        check("old queue files are pruned, recent ones kept",
              (not os.path.exists(old_f)) and os.path.exists(new_f))

        # A claim made yesterday must not count against today.
        old = wstore(3)
        st.set_daily_quota(old, 2)
        st.claim_placement(old, {"target_domain": "w000.example",
                                 "target_url": "https://w000.example"})
        for p in old["placements"].values():
            p["claimed_at"] = "2026-01-01T03:00:00Z"
        check("yesterday's claims are outside today's window",
              st.quota_state(old)["used"] == 0 and st.quota_state(old)["left"] == 2,
              st.quota_state(old))

        if not NO_WRITE:
            code, body = http("/api/whitelist?domain=%s" % TEST_DOMAIN)
            check("/api/whitelist ok", code == 200 and body.get("ok") is True, code)
            code, body = http("/api/whitelist", {"center_domain": TEST_DOMAIN,
                                                 "domains": "https://www.Case-Test.example/x",
                                                 "action": "add", "note": "selftest"})
            check("/api/whitelist add normalizes the host",
                  code == 200 and body.get("changed") == ["case-test.example"],
                  (code, (body or {}).get("changed")))
            check("/api/whitelist is reflected in store stats",
                  (body or {}).get("stats", {}).get("whitelisted") == 1,
                  (body or {}).get("stats", {}).get("whitelisted"))
            code, body = http("/api/whitelist", {"center_domain": TEST_DOMAIN,
                                                 "domains": "case-test.example",
                                                 "action": "remove"})
            check("/api/whitelist remove works",
                  code == 200 and body.get("count") == 0 and body.get("changed") == ["case-test.example"],
                  (code, (body or {}).get("changed")))

            code, body = http("/api/settings", {"center_domain": TEST_DOMAIN, "daily_quota": 42})
            check("/api/settings saves the quota",
                  code == 200 and body.get("settings", {}).get("daily_quota") == 42,
                  (code, (body or {}).get("settings")))
            code, body = http("/api/settings", {"center_domain": TEST_DOMAIN, "daily_quota": 0})
            check("/api/settings rejects an impossible quota",
                  code == 400 and "between" in str((body or {}).get("error", "")),
                  (code, (body or {}).get("error")))
            code, body = http("/api/store?domain=%s" % TEST_DOMAIN)
            check("/api/store exposes settings + whitelist",
                  code == 200 and body.get("settings", {}).get("daily_quota") == 42
                  and isinstance(body.get("whitelist"), list),
                  (code, sorted((body or {}).keys())))
    finally:
        st.prune_queues(center, keep_days=-1)


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
    section_g()
    section_h()
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
