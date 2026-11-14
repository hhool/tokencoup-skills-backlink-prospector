#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bilingual audit for DYNAMIC page output (headless Chrome).

Unlike a static data-i18n check, this exercises every string that a render
function builds at runtime: analysis results, pool rows/tree/chips, tips,
channels, scheduler profiles/status/run history, SVG chart labels, transient
error/import/busy messages and sort tooltips. The decisive case is an IN-PAGE
language toggle after all data has loaded, not a reload in the other language.

Usage: python3 tools/i18n_audit.py [base_url]
Exit code 0 = all checks passed, 1 = at least one failure.
"""
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787/"
CJK = re.compile(r"[\u3400-\u9fff]")
FAILS = []
CHECKS = 0


def check(name, cond, detail=""):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(name)
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           (" -> " + str(detail)[:160]) if detail else ""))


def has_cjk(s):
    return bool(CJK.search(s or ""))


# Regions rendered in exactly one language. zh_any / en_any: at least one of
# the alternatives must be present; the opposite alternatives must be absent.
STRICT = [
    ("overview center label", "#ovCenter",
     ["分析对象（中心域名）"], ["Analysis target (center domain)"]),
    ("scheduler center label", "#schedCenter",
     ["中心域名："], ["Center domain:"]),
    ("profile note", "#profileNote", ["档案 "], ["Profile "]),
    ("analysis type filter", "#f_type option:first-child", ["全部"], ["All"]),
    ("data sources line", "#src", ["数据源："], ["Data sources:"]),
    ("limitations list", "#lim", ["商业 DR/DA"], ["Commercial DR/DA"]),
    ("pool entry count", "#existingCount", ["共 "], ["Total "]),
    ("pool filter note", "#poolFilterNote", ["显示 "], ["Showing "]),
    ("pool tree root", "#poolTree", ["全部站点"], ["All sites"]),
    ("pool tree scope", "#treeScope", ["全部类型", "已选"], ["all types", "type(s) selected"]),
    ("type-distribution header", "#poolByType", ["类型"], ["Type"]),
    ("scheduler status", "#schedStatus", ["状态"], ["Status"]),
    ("scheduler profile labels", "#schedProfiles .sched-card", ["名称"], ["Name"]),
    ("run-history rows", "#schedRuns", ["池总数", "尚无运行记录"], ["pool:", "No runs yet"]),
    ("channel enabled count", "#chCount", ["启用 "], ["enabled "]),
    ("channel domain badge", "#chDomainBadge", ["域名："], ["Domain:"]),
    ("channel toggle buttons", "#chBody tr:first-child td:last-child",
     ["停用", "启用"], ["Disable", "Enable"]),
    ("overview SVG threshold", "#ovRecip", ["30% 阈值"], ["30% threshold"]),
]

# Single-language cells: ZH must contain Chinese, EN must contain no Chinese.
# Intentionally bilingual pairs (type_label_zh/en, channel name_zh/en, tips
# primary/secondary text) are deliberately excluded from this list.
CJK_FREE_IN_EN = [
    ("limitations items", "#lim li"),
    ("analysis note column", "#tbody tr td:last-child"),
    ("analysis status pills", "#tbody tr td:nth-child(9)"),
    ("pool type column", "#poolBody tr td:nth-child(2)"),
    ("pool action buttons", "#poolBody tr button"),
    ("pool status pills", "#poolBody tr td:nth-child(6)"),
    ("pool reciprocal warning", "#p_recip_note"),
    ("pool tree labels", "#poolTree .tree-node > span:nth-child(2)"),
    ("pool type chips", "#poolTypeChips .chip"),
    ("pool check message", "#existingMsg"),
    ("type-distribution labels", "#poolByType tbody td:first-child"),
    ("tips weight badges", "#tipsBody .badge"),
    ("tips warn boxes", "#tipsBody .warnbox"),
    ("scheduler status pills", "#schedStatus .pill"),
    ("scheduler profile field labels", "#schedProfiles .sched-card label"),
    ("run-history result pills", "#schedRuns .pill"),
    ("data source badges", "#src .badge"),
]


def text_of(page, selector, limit=None):
    return page.eval_on_selector_all(
        selector,
        "els => els.map(e => (e.innerText || e.textContent || '').trim()).join(' | ')",
    )


def audit_language(page, lang):
    print("\n--- %s ---" % ("ZH" if lang == "zh" else "EN"))

    for name, sel, zh_any, en_any in STRICT:
        txt = text_of(page, sel)
        want, other = (zh_any, en_any) if lang == "zh" else (en_any, zh_any)
        ok = any(w in txt for w in want) and not any(o in txt for o in other)
        check("strict: %s" % name, ok, repr(txt[:110]))

    for name, sel in CJK_FREE_IN_EN:
        txt = text_of(page, sel)
        if not txt.strip():
            check("cjk: %s (non-empty)" % name, False, "selector matched nothing")
        elif lang == "en":
            check("cjk-free EN: %s" % name, not has_cjk(txt), repr(txt[:110]))
        else:
            check("cjk-present ZH: %s" % name, has_cjk(txt), repr(txt[:110]))

    # Sort tooltips are set imperatively (th.title), not innerText.
    titles = page.eval_on_selector_all(
        "th.sortable[data-sort]", "els => els.map(e => e.title)")
    want_title = "点击表头排序" if lang == "zh" else "Click to sort"
    check("sort tooltips localized", bool(titles) and all(t == want_title for t in titles),
          sorted(set(titles)))

    # Static chrome hygiene.
    bare = page.eval_on_selector_all(
        "[data-i18n]",
        "els => els.filter(x => /^[a-z][a-zA-Z0-9_]+$/.test(x.innerText.trim())).map(x => x.dataset.i18n)")
    blank = page.eval_on_selector_all(
        "[data-i18n]", "els => els.filter(x => !x.innerText.trim()).map(x => x.dataset.i18n)")
    moji = page.evaluate("() => (document.body.innerText.match(/\uFFFD/g) || []).length")
    check("no bare i18n keys", not bare, bare)
    check("no empty i18n elements", not blank, blank)
    check("no replacement characters", moji == 0, moji)


def run(base):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.on("console", lambda m: errors.append("console: %s" % m.text)
                if m.type == "error" else None)

        print("=== setup: load every tab's dynamic state =====================")
        page.goto(base, wait_until="networkidle", timeout=90000)
        time.sleep(2)
        page.fill("#centerDomain", "balancebiketoddler.com")
        page.dispatch_event("#centerDomain", "change")
        time.sleep(2.5)
        page.click('[data-tab="pool"]')
        page.click("#poolLoad")
        page.wait_for_selector("#poolTable:not(.hidden)", timeout=90000)
        time.sleep(2)
        page.click('[data-tab="sched"]')
        time.sleep(1.5)
        page.click('[data-tab="analyze"]')
        page.uncheck("#use_bing")
        page.uncheck("#use_tranco")
        page.click("#run")
        page.wait_for_selector("#results:not(.hidden)", timeout=180000)
        time.sleep(2)
        check("analysis rows present",
              page.eval_on_selector_all("#tbody tr", "e => e.length") > 0)
        check("pool rows present",
              page.eval_on_selector_all("#poolBody tr", "e => e.length") > 0)
        check("run-history rows present",
              page.eval_on_selector_all("#schedRuns tr", "e => e.length") > 0)

        print("\n=== A. all dynamic regions, ZH -> EN -> ZH ====================")
        audit_language(page, "zh")
        page.click("#langToggle")
        time.sleep(1.8)
        audit_language(page, "en")
        page.click("#langToggle")
        time.sleep(1.8)
        audit_language(page, "zh")

        print("\n=== B. transient messages survive a language switch ==========")
        page.evaluate("() => { showErr('EN_ERR_MARK', 'ZH_ERR_MARK'); "
                      "setImportMsg('EN_IMP_MARK', 'ZH_IMP_MARK'); "
                      "setBusy('run', 'EN_BUSY_MARK', 'ZH_BUSY_MARK'); }")
        check("ZH error banner", page.inner_text("#err") == "ZH_ERR_MARK",
              page.inner_text("#err"))
        check("ZH import badge", page.inner_text("#importMsg2") == "ZH_IMP_MARK")
        check("ZH busy button", page.inner_text("#run") == "ZH_BUSY_MARK")
        page.click("#langToggle")
        time.sleep(1.5)
        check("EN error banner", page.inner_text("#err") == "EN_ERR_MARK",
              page.inner_text("#err"))
        check("EN import badge", page.inner_text("#importMsg2") == "EN_IMP_MARK")
        check("EN busy button", page.inner_text("#run") == "EN_BUSY_MARK")
        page.click("#langToggle")
        time.sleep(1.2)
        check("ZH error banner restored", page.inner_text("#err") == "ZH_ERR_MARK")
        check("ZH busy button restored", page.inner_text("#run") == "ZH_BUSY_MARK")
        # Clear the injected state so it cannot affect later checks.
        page.evaluate("() => { hideErr(); setImportMsg(null,null); setBusy('run',null); }")

        print("\n=== C. unsaved operator input survives a language switch =====")
        page.click('[data-tab="sched"]')
        first_name = "#schedProfiles .sched-card .p-name"
        if page.eval_on_selector_all(first_name, "e => e.length"):
            page.fill(first_name, "UNSAVED_EDIT_MARK")
            page.click("#langToggle")
            time.sleep(1.3)
            check("unsaved profile name kept", page.input_value(first_name) == "UNSAVED_EDIT_MARK",
                  page.input_value(first_name))
            page.click("#langToggle")
            time.sleep(1.0)
        else:
            check("profile card exists for edit test", False, "no .p-name found")

        print("\n=== D. console health ==========================================")
        check("no JS errors during audit", not errors, errors[:4])
        browser.close()

    print("\n" + ("ALL %d CHECKS PASSED" % CHECKS
                  if not FAILS else "FAILED %d/%d: %s" % (len(FAILS), CHECKS, ", ".join(FAILS))))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(run(BASE))
