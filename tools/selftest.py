#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end self test for the backlink prospector (headless Chrome).

Covers the three reported defects:
  1. the discovery-channel table must render its rows (badge no longer destroyed
     by the i18n innerHTML swap);
  2. switching the center domain must swap the niche keywords / competitors;
  3. an analysis for the switched domain must return domain-relevant prospects.

Usage: python3 tools/selftest.py [base_url]
"""
import json
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787/"
FAILS = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        FAILS.append(name)
    print("  [%s] %s%s" % (mark, name, (" -> " + str(detail)) if detail else ""))


def col_values(page, selector, idx):
    """Values of one column of a table body (anchor text when present)."""
    return page.eval_on_selector_all(
        selector + " tr",
        """els => els.map(e => {
            const c = e.querySelectorAll('td')[%d];
            if (!c) return '';
            const a = c.querySelector('a');
            return (a ? a.textContent : c.innerText).replace(/\\s+/g,' ').trim();
        })""" % idx)


def _num(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group(0)) if m else -1.0


def is_sorted(vals, desc=False, numeric=False):
    """True when vals are in the requested order."""
    if len(vals) < 2:
        return True
    for i in range(len(vals) - 1):
        a, b = vals[i], vals[i + 1]
        if numeric:
            a, b = _num(a), _num(b)
        else:
            a, b = a.lower(), b.lower()
        ok = (b <= a) if desc else (b >= a)
        if not ok:
            return False
    return True


def run(base):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 950})
        errors = []
        page.on("console", lambda m: errors.append("%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

        print("\n=== 1. load & console health ===============================")
        page.goto(base, wait_until="networkidle")
        time.sleep(1.2)
        check("no JS console errors", not errors, "; ".join(errors[:4]))

        print("\n=== 2. discovery channel table renders =======================")
        # switch to the backend tab
        page.click('[data-tab="sched"]')
        time.sleep(0.4)
        rows = page.eval_on_selector_all(
            "#chBody tr", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
        check("channel table has >=3 rows", len(rows) >= 3, "%d rows" % len(rows))
        body_txt = page.inner_text("#chBody")
        for cid in ("bing_rss", "bing_cite", "duckduckgo_html"):
            check("channel %s listed" % cid, cid in body_txt)
        badge = page.inner_text("#chCount")
        check("channel badge rendered", bool(badge.strip()), repr(badge))
        check("badge not destroyed by i18n",
              page.eval_on_selector("#chCount", "e => !!e"))

        print("\n=== 3. domain switch swaps the niche profile ================")
        before_kw = page.input_value("#keywords")
        page.fill("#centerDomain", "balancebiketoddler.com")
        page.dispatch_event("#centerDomain", "change")
        time.sleep(1.5)
        after_kw = page.input_value("#keywords")
        check("keywords changed after domain switch",
              after_kw != before_kw, "%r -> %r" % (before_kw[:40], after_kw[:60]))
        check("keywords are balance-bike related",
              "balance bike" in after_kw.lower(), after_kw[:80])
        check("no soundboard keyword leaked",
              "soundboard" not in after_kw.lower(), after_kw[:80])
        check("target domain follows center domain",
              page.input_value("#domain") == "balancebiketoddler.com")
        note = page.inner_text("#profileNote")
        check("profile note shown", "balancebiketoddler.com" in note, note[:70])

        print("\n=== 4. channel rows still present after switch =============")
        rows2 = page.eval_on_selector_all(
            "#chBody tr", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
        check("channel table still has rows after switch", len(rows2) >= 3,
              "%d rows" % len(rows2))

        print("\n=== 5. analysis returns domain-relevant prospects ===========")
        page.click('[data-tab="analyze"]')
        time.sleep(0.3)
        page.uncheck("#use_bing")     # isolate the seed pipeline from live search
        page.click("#run")
        page.wait_for_selector("#results:not(.hidden)", timeout=180000)
        time.sleep(1.0)
        domains = page.eval_on_selector_all(
            "#tbody tr td:first-child a", "els => els.map(e => e.textContent.trim())")
        check("analysis produced prospects", len(domains) > 0, "%d rows" % len(domains))
        leak = [d for d in domains if any(
            x in d.lower() for x in ("freesound", "mixkit", "looperman", "99sounds",
                                     "myinstants", "voicemod", "head-fi", "mashable"))]
        check("no cross-niche leak in results", not leak, leak[:5])
        print("     sample:", domains[:6])

        print("\n=== 6. every list is sortable ============================")
        # ---- 6.1 analysis results ----
        page.click('[data-tab="analyze"]')
        time.sleep(0.3)
        res_hdrs = page.eval_on_selector_all(
            "#resTable th.sortable", "els => els.map(e => e.dataset.sort)")
        check("analysis table exposes sortable headers", len(res_hdrs) >= 8, res_hdrs)

        page.click('#resTable th[data-sort="domain"]')
        time.sleep(0.4)
        d1 = col_values(page, "#tbody", 0)
        check("analysis sorted by domain (asc)", is_sorted(d1), d1[:4])
        page.click('#resTable th[data-sort="domain"]')
        time.sleep(0.4)
        d2 = col_values(page, "#tbody", 0)
        check("analysis domain sort flips to desc", is_sorted(d2, desc=True), d2[:4])
        check("sort indicator on the active header",
              page.eval_on_selector_all("#resTable th.sorted-desc",
                                        "els => els.length") == 1)

        page.click('#resTable th[data-sort="priority"]')
        time.sleep(0.4)
        pr = col_values(page, "#tbody", 6)
        check("analysis sorted by priority (desc)",
              is_sorted(pr, desc=True, numeric=True), pr[:5])

        # a filter change must not wipe the sort
        page.check("#f_gap")
        time.sleep(0.4)
        pr2 = col_values(page, "#tbody", 6)
        check("sort kept after filter change",
              is_sorted(pr2, desc=True, numeric=True), pr2[:5])
        page.uncheck("#f_gap")
        time.sleep(0.3)

        # ---- 6.2 pool ----
        page.click('[data-tab="pool"]')
        time.sleep(0.3)
        page.click("#poolLoad")
        page.wait_for_selector("#poolTable:not(.hidden)", timeout=60000)
        time.sleep(1.0)
        pool_hdrs = page.eval_on_selector_all(
            "#poolTable th.sortable", "els => els.map(e => e.dataset.sort)")
        check("pool table exposes sortable headers", len(pool_hdrs) >= 8, pool_hdrs)

        page.click('#poolTable th[data-sort="domain"]')
        time.sleep(0.4)
        pd = col_values(page, "#poolBody", 0)
        check("pool sorted by domain (asc)", is_sorted(pd), pd[:4])
        page.click('#poolTable th[data-sort="times"]')
        time.sleep(0.4)
        pt = col_values(page, "#poolBody", 6)
        check("pool sorted by times (desc)",
              is_sorted(pt, desc=True, numeric=True), pt[:4])

        # the sort state must survive a full data reload (state lives in the
        # sort registry, not in the DOM)
        page.click("#poolLoad")
        time.sleep(1.2)
        pt2 = col_values(page, "#poolBody", 6)
        check("pool sort survives data reload",
              is_sorted(pt2, desc=True, numeric=True), pt2[:4])

        tt_hdrs = page.eval_on_selector_all(
            "#poolTypeTable th.sortable", "els => els.map(e => e.dataset.sort)")
        check("type-distribution table sortable", len(tt_hdrs) >= 4, tt_hdrs)
        page.click('#poolTypeTable th[data-sort="gap"]')
        time.sleep(0.4)
        gaps = col_values(page, "#poolTypeTable tbody", 3)
        check("type distribution sorted by gap (desc)",
              is_sorted(gaps, desc=True, numeric=True), gaps[:4])

        # ---- 6.3 discovery channels ----
        page.click('[data-tab="sched"]')
        time.sleep(0.4)
        ch_hdrs = page.eval_on_selector_all(
            "#chTable th.sortable", "els => els.map(e => e.dataset.sort)")
        check("channel table exposes sortable headers", len(ch_hdrs) >= 5, ch_hdrs)
        page.click('#chTable th[data-sort="kind"]')
        time.sleep(0.4)
        kinds = page.eval_on_selector_all(
            "#chBody tr",
            "els => els.map(e => {const c=e.querySelectorAll('td')[1]"
            ".querySelector('code'); return c ? c.textContent.trim() : '';})")
        check("channels sorted by kind (asc)", is_sorted(kinds), kinds)
        page.click('#chTable th[data-sort="interval"]')
        time.sleep(0.4)
        iv = col_values(page, "#chBody", 3)
        check("channels sorted by interval (asc)", is_sorted(iv, numeric=True), iv)

        # ---- 6.4 tips ----
        page.click('[data-tab="tips"]')
        time.sleep(0.3)
        if page.eval_on_selector("#tipsBody", "e => e.classList.contains('hidden')"):
            page.click("#tipsToggle")
        time.sleep(1.2)
        tips_hdrs = page.eval_on_selector_all(
            "#tipsTable th.sortable", "els => els.map(e => e.dataset.sort)")
        check("tips table exposes sortable headers", len(tips_hdrs) >= 3, tips_hdrs)
        page.click('#tipsTable th[data-sort="obtain"]')
        time.sleep(0.4)
        ob = col_values(page, "#tipsTable tbody", 2)
        check("tips sorted by obtain score (desc)",
              is_sorted(ob, desc=True, numeric=True), ob)

        # ---- 6.5 run history ----
        rh_hdrs = page.eval_on_selector_all(
            "#runsTable th.sortable", "els => els.map(e => e.dataset.sort)")
        check("run-history table exposes sortable headers", len(rh_hdrs) >= 5, rh_hdrs)

        print("\n=== 7. type tree + faceted filters =========================")
        page.click('[data-tab="pool"]')
        time.sleep(0.3)
        page.click("#poolLoad")
        page.wait_for_selector("#poolTable:not(.hidden)", timeout=60000)
        time.sleep(1.2)

        tree_nodes = page.eval_on_selector_all(
            "#poolTree .tree-node", "els => els.map(e => e.dataset.act + ':' "
                                    "+ (e.dataset.type || e.dataset.group || 'all'))")
        check("type tree rendered", len(tree_nodes) >= 5, tree_nodes)
        check("tree has a reciprocal branch",
              any(n == "type:reciprocal" for n in tree_nodes), tree_nodes)

        type_nodes = page.eval_on_selector_all(
            "#poolTree .tree-node[data-act='type']",
            "els => els.map(e => ({t: e.dataset.type, "
            "n: parseInt(e.querySelector('.cnt b').textContent, 10)}))")
        check("tree lists type branches", len(type_nodes) >= 3, type_nodes)
        target = next((x for x in type_nodes if x["n"] > 0), None)
        check("tree exposes a non-empty type branch", target is not None, target)
        if target:
            page.click('#poolTree .tree-node[data-act="type"][data-type="%s"]' % target["t"])
            time.sleep(0.5)
            shown = len(col_values(page, "#poolBody", 0))
            check("tree selection filters the table by type",
                  shown == target["n"], "%d rows vs branch count %d" % (shown, target["n"]))
            check("selected branch is highlighted",
                  page.eval_on_selector(
                      '#poolTree .tree-node[data-act="type"][data-type="%s"]' % target["t"],
                      "e => e.classList.contains('active')"))
            page.click('#poolTree .tree-node[data-act="all"]')
            time.sleep(0.4)

        all_rows = len(col_values(page, "#poolBody", 0))
        page.uncheck(".st-gap")
        time.sleep(0.5)
        acq_only = len(col_values(page, "#poolBody", 0))
        acq_total = page.eval_on_selector(
            "#poolTree .tree-node[data-act='all'] .cnt .c-acq", "e => parseInt(e.textContent, 10)")
        check("status filter keeps only acquired rows",
              acq_only == acq_total, "%d rows vs acquired %s" % (acq_only, acq_total))
        page.uncheck(".st-acq")
        page.check(".st-gap")
        time.sleep(0.5)
        gap_only = len(col_values(page, "#poolBody", 0))
        gap_total = page.eval_on_selector(
            "#poolTree .tree-node[data-act='all'] .cnt .c-gap", "e => parseInt(e.textContent, 10)")
        check("status filter keeps only gap rows",
              gap_only == gap_total, "%d rows vs gap %s" % (gap_only, gap_total))
        page.click("#poolFilterReset")
        time.sleep(0.5)
        check("reset restores the full list",
              len(col_values(page, "#poolBody", 0)) == all_rows)

        print("\n=== 8. no JS errors during the whole run ====================")
        check("still no JS errors", not errors, "; ".join(errors[:4]))

        browser.close()


if __name__ == "__main__":
    run(BASE)
    print("\n" + "=" * 62)
    if FAILS:
        print("FAILED (%d): %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("ALL CHECKS PASSED")
