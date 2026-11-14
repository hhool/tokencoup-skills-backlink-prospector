#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Link survival recheck: is a "live" backlink still on the page?

The ledger is a claim; a backlink is only "有效" while the page still carries it.
Nothing in this tool ever re-visited a delivered link, so `live` meant "it was
live the day we typed it in" — including rows imported from an export, which were
never visited at all (`verified_at` is empty on purpose).

This module is the probe half of that loop. It stays out of store.py so the data
layer keeps no network code:

    status "ok"      page answered 2xx AND our link is still in the HTML
    status "gone"    404/410, or 2xx with our link no longer present
    status "unknown" network error / 429 / 403 / 5xx — never treated as gone

`gone` moves the row to `lost` (and the domain back to "gap"); `unknown` only
records an attempt, because a bot wall or a timeout must not delete a backlink
you actually own.
"""
import concurrent.futures
import copy
import datetime as dt
import re
import ssl
import urllib.error
import urllib.request

import store as st

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

MAX_BYTES = 600_000          # enough for the article, not the whole video page
GONE_STATUS = (404, 410)
HARD_BLOCK_STATUS = (401, 403, 429, 999)


def _norm_target(value):
    v = (value or "").strip().lower().split("#", 1)[0]
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    if v.startswith("www."):
        v = v[4:]
    return v.rstrip("/")


def needles_for(rec):
    """What counts as "our link" on the landing page, strongest signal first.

    An absolute href is exact; a bare path is weaker (it can appear in navigation)
    so it is only used when the stronger form misses, and the match is labelled.
    """
    verify = rec.get("verify") or {}
    own = str(rec.get("own_url") or verify.get("observed_href") or "").strip()
    out = []
    absn = _norm_target(own)
    if absn:
        out.append(("href", absn))
        if "/" in absn:
            path = absn.split("/", 1)[1]
            if path:
                # A relative href is the common case on real pages, and a short
                # path ("guide") is too generic to search for on its own — but
                # 'href="/guide"' is unambiguous, so match the attribute form.
                for attr in ('href="/%s"' % path, "href='/%s'" % path,
                             'href="/%s/' % path, "href='/%s/" % path):
                    out.append(("href_attr", attr))
                if len(path) >= 6:
                    out.append(("path", path))
    dom = st._bare_domain(own)
    if dom:
        out.append(("domain", dom))
    return out


def probe_link(url, needles, timeout=10):
    """Fetch one landing page and answer ok / gone / unknown."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Cache-Control": "no-cache",
    }, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            status = r.status
            final_url = r.geturl()
            body = r.read(MAX_BYTES).decode("utf-8", "replace").lower()
    except urllib.error.HTTPError as e:
        if e.code in GONE_STATUS:
            return {"status": "gone", "http": e.code, "found": None,
                    "note": "HTTP %d" % e.code, "final_url": url}
        return {"status": "unknown", "http": e.code, "found": None,
                "note": "HTTP %d (not proof of removal)" % e.code, "final_url": url}
    except Exception as exc:  # noqa: BLE001 — timeout, DNS, TLS, reset
        return {"status": "unknown", "http": 0, "found": None,
                "note": "%s: %s" % (type(exc).__name__, str(exc)[:100]), "final_url": url}

    if status in HARD_BLOCK_STATUS or status >= 500:
        return {"status": "unknown", "http": status, "found": None,
                "note": "HTTP %d (blocked or server error, retry later)" % status,
                "final_url": final_url}
    if not needles:
        return {"status": "ok", "http": status, "found": None,
                "note": "HTTP %d; no own URL recorded so only reachability was checked" % status,
                "final_url": final_url}
    for kind, needle in needles:
        if needle and needle in body:
            return {"status": "ok", "http": status, "found": kind,
                    "note": "link present (%s match)" % kind, "final_url": final_url}
    return {"status": "gone", "http": status, "found": None,
            "note": "page loads but the link is gone", "final_url": final_url}


def _stamp(rec):
    return str((rec.get("recheck") or {}).get("at") or "")


def is_due(rec, days, now=None):
    """A live row is due when it was never checked or the last check is old."""
    stamp = _stamp(rec)
    if not stamp:
        return True
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        at = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return True
    return (now - at) >= dt.timedelta(days=days)


def candidates(store, days=None):
    """Live rows that need a probe: never-checked first, then oldest check."""
    days = st.RECHECK_DAYS if days is None else int(days)
    rows = []
    for rec in store.get("placements", {}).values():
        if rec.get("state") != "live":
            continue
        landing = str((rec.get("verify") or {}).get("landing_url") or "").strip()
        if not landing:
            continue          # nothing to probe: no evidence of a page at all
        if not is_due(rec, days):
            continue
        rows.append(rec)
    rows.sort(key=lambda r: (bool(_stamp(r)), _stamp(r)))
    return rows


def due_count(store, days=None):
    return len(candidates(store, days=days))


def never_checked(store):
    """Live rows nothing ever probed — every imported row starts here."""
    return sum(1 for rec in store.get("placements", {}).values()
               if rec.get("state") == "live"
               and str((rec.get("verify") or {}).get("landing_url") or "").strip()
               and not _stamp(rec))


def _apply(store, rec, result, now):
    """Record the attempt, and move the row to `lost` only on hard evidence."""
    verify = rec.setdefault("verify", {})
    entry = {"at": now, "status": result["status"], "http": result.get("http"),
             "found": result.get("found"), "note": result.get("note"),
             "checked_url": result.get("final_url") or verify.get("landing_url")}
    rec["recheck"] = dict(entry)
    checks = rec.setdefault("checks", [])
    checks.append(entry)
    rec["checks"] = checks[-5:]
    if result["status"] == "gone":
        rec["state"] = "lost"
        rec["lost_at"] = now
        rec["failure_reason"] = "link gone: " + str(result.get("note") or "")
        rec.setdefault("evidence", []).append(
            {"at": now, "note": "recheck: %s (HTTP %s)" % (result.get("note"), result.get("http"))})
    # `lost` must put the domain back into the gap, `ok` must not change a number.
    st._sync_acquired_flags(store, {st._bare_domain(rec.get("target_domain"))})


def run(store, limit=20, days=None, dry_run=False, timeout=10, workers=6,
        only_unprobed=False):
    """Probe due live rows and apply the result. Returns a report.

    dry_run still performs the HTTP probes (that is the point of a preview) but
    every write lands on a deep copy, so the store is untouched.
    """
    days = st.RECHECK_DAYS if days is None else int(days)
    work = copy.deepcopy(store) if dry_run else store
    todo = candidates(work, days=days)
    if only_unprobed:
        todo = [r for r in todo if not _stamp(r)]
    todo = todo[:max(0, int(limit))]

    now = st._now()
    # "alive" not "ok": every API response already uses ok for the envelope, and
    # a shared key made the count read as a boolean in the UI.
    report = {"checked": 0, "alive": 0, "gone": 0, "unknown": 0, "lost": [],
              "dry_run": bool(dry_run), "days": days, "limit": limit,
              "quota_untouched": True,
              "before": {"live": st.placement_stats(work)["live"]}}
    if not todo:
        report["remaining_due"] = 0
        report["after"] = dict(report["before"])
        return report

    def one(rec):
        url = str((rec.get("verify") or {}).get("landing_url") or "").strip()
        try:
            return rec, probe_link(url, needles_for(rec), timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — one probe must never abort the batch
            return rec, {"status": "unknown", "http": 0, "found": None,
                         "note": "%s: %s" % (type(exc).__name__, str(exc)[:100]),
                         "final_url": url}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as ex:
        for rec, result in list(ex.map(one, todo)):
            report["checked"] += 1
            key = "alive" if result["status"] == "ok" else result["status"]
            report[key] = report.get(key, 0) + 1
            if result["status"] == "gone":
                report["lost"].append({
                    "target_domain": rec.get("target_domain"),
                    "target_url": (rec.get("verify") or {}).get("landing_url"),
                    "http": result.get("http"), "note": result.get("note")})
            _apply(work, rec, result, now)

    report["after"] = {"live": st.placement_stats(work)["live"]}
    report["remaining_due"] = due_count(work, days=days)
    return report
