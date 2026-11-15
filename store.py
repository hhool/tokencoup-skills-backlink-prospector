#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backlink Prospector - persistent backlink pool (Python standard library only).

The pool accumulates every analysis run so the operator can run *periodic queries*
and keep expanding the address list over time. Each prospect is keyed by its
registrable domain and deduplicated; discovery count, first/last seen, best
validation status and latest priority are tracked.

A separate "acquired_domains" set records the operator's real existing backlinks
(imported from GSC / Ahrefs / self-hosted Common Crawl export). Anything in the
pool that is NOT acquired is the live "gap" to pursue.

Storage isolation: pools are now isolated per center domain (e.g., soundbuttons.cc.json,
balancebiketoddler.com.json) to avoid cross-contamination when switching domains.
"""
import copy
import csv
import datetime as dt
import hashlib
import json
import os
import re
import threading
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SEEDS_DIR = os.path.join(HERE, "seeds")  # image-baked, version-controlled inputs
STORE_PATH = os.path.join(DATA_DIR, "store.json")  # legacy default
CHANNELS_PATH = os.path.join(HERE, "channels.json")  # global channels config
PROFILES_PATH = os.path.join(HERE, "profiles.json")  # default keyword/competitor profiles
SCHEMA_VERSION = "1.0.0"


def _sanitize_domain(domain):
    """Convert a domain to a safe filename."""
    if not domain:
        return None
    # Lowercase and replace invalid filename chars with underscore
    safe = re.sub(r'[^a-z0-9._-]', '_', domain.lower())
    # Remove leading/trailing dots and limit length
    safe = safe.strip('.').strip('_')[:100]
    return safe if safe else None


def get_store_path(center_domain=None):
    """Get store path for a specific center domain."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if center_domain:
        safe_name = _sanitize_domain(center_domain)
        if safe_name:
            return os.path.join(DATA_DIR, f"store-{safe_name}.json")
    return STORE_PATH  # fallback to legacy default


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bare_domain(value):
    """Reduce a URL / host / stray paste to the registrable-looking host we key on.

    Accepts 'https://www.Example.com/x?y=1' and returns 'example.com'. Returns ""
    for anything that cannot be a host, so a typo can never enter the whitelist.
    """
    v = str(value or "").strip().lower()
    if not v:
        return ""
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = v.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    v = v.rsplit("@", 1)[-1].split(":")[0].strip(".")
    if v.startswith("www."):
        v = v[4:]
    if "." not in v or not re.match(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", v):
        return ""
    return v


def load_store(center_domain=None):
    """Load store for a specific center domain."""
    store_path = get_store_path(center_domain)
    try:
        with open(store_path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("domains", {})
        data.setdefault("acquired_domains", [])
        data.setdefault("placements", {})
        data.setdefault("suppressions", {})
        data.setdefault("whitelist", {})
        data.setdefault("settings", {})
        data.setdefault("runs", 0)
        data.setdefault("center_domain", center_domain)
        return data
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "updated_at": _now(),
                "domains": {}, "acquired_domains": [], "placements": {},
                "suppressions": {}, "whitelist": {}, "settings": {},
                "runs": 0, "center_domain": center_domain}


def save_store(store, center_domain=None):
    """Save store for a specific center domain."""
    store_path = get_store_path(center_domain)
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    store["updated_at"] = _now()
    if center_domain:
        store["center_domain"] = center_domain
    tmp = store_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, store_path)
    return store


def merge_result(store, result):
    """Merge an analysis result into the pool, dedup by domain."""
    now = _now()
    doms = store.setdefault("domains", {})
    acquired = set(store.get("acquired_domains", []))
    # A verified live link (delivered or imported) is ownership too: without the
    # union, every analysis run reset that flag to False and only the stats kept
    # telling the truth (they union with live_domains() at read time).
    live = {_norm_target(x) for x in live_domains(store) if x}
    merged = 0
    for p in result.get("prospects", []):
        d = p.get("domain")
        if not d:
            continue
        tranco = (p.get("authority") or {}).get("tranco_global_rank")
        if d in doms:
            e = doms[d]
            e["times_discovered"] = e.get("times_discovered", 1) + 1
            e["last_seen"] = now
            # keep latest valid status and best priority
            if p.get("valid"):
                e["valid"] = True
                e["http_status"] = p.get("http_status")
            e["priority"] = p.get("priority", e.get("priority", 0))
            e["last_priority"] = p.get("priority")
            e["authority_tier"] = p.get("authority_tier")
            e["is_competitor"] = bool(p.get("is_competitor")) or e.get("is_competitor", False)
            # Keep the competitor-backlink evidence across runs: "this site links
            # to compa.test" stays true even when a later seed-only run sees it.
            vias = set(e.get("via_competitors") or [])
            vias.update(p.get("via_competitors") or [])
            if vias:
                e["via_competitors"] = sorted(vias)
                e.setdefault("source", p.get("source") or "competitor_backlink")
            if p.get("evidence") and not e.get("evidence"):
                e["evidence"] = p.get("evidence")
            if tranco is not None:
                e.setdefault("authority", {})["tranco_global_rank"] = tranco
            e["acquired"] = (d in acquired) or (_norm_target(d) in live)
            merged += 1
        else:
            doms[d] = {
                "domain": d,
                "url": p.get("url"),
                "type_key": p.get("type_key"),
                "type_label_zh": p.get("type_label_zh"),
                "type_label_en": p.get("type_label_en"),
                "authority_tier": p.get("authority_tier"),
                "authority": {"tranco_global_rank": tranco},
                "priority": p.get("priority"),
                "relevance": p.get("relevance"),
                "authority_score": p.get("authority_score"),
                "obtainability": p.get("obtainability"),
                "valid": p.get("valid"),
                "http_status": p.get("http_status"),
                "first_seen": now,
                "last_seen": now,
                "times_discovered": 1,
                "note": p.get("note", ""),
                "is_competitor": bool(p.get("is_competitor")),
                "source": p.get("source", "seed"),
                "via_competitors": p.get("via_competitors") or [],
                "evidence": p.get("evidence"),
                "acquired": (d in acquired) or (_norm_target(d) in live),
            }
            merged += 1
    store["runs"] = store.get("runs", 0) + 1
    store["acquired_domains"] = sorted(acquired)
    return merged


def sync_existing(store, domains):
    """Record the operator's real existing backlinks (one domain per line/item)."""
    acquired = set(store.get("acquired_domains", []))
    added = 0
    for d in domains:
        d = (d or "").strip().lower()
        if d and d not in acquired:
            acquired.add(d)
            added += 1
    store["acquired_domains"] = sorted(acquired)
    for d in store.get("domains", {}):
        if d in acquired:
            store["domains"][d]["acquired"] = True
    return added


def unmark_existing(store, domains):
    """Revert domains to gap (remove from acquired_domains; keep pool entries)."""
    acquired = set(store.get("acquired_domains", []))
    removed = 0
    for d in domains:
        d = (d or "").strip().lower()
        if d and d in acquired:
            acquired.discard(d)
            removed += 1
    store["acquired_domains"] = sorted(acquired)
    for d in store.get("domains", {}):
        store["domains"][d]["acquired"] = d in acquired
    return removed


def sync_competitors(store, center_domain=None):
    """Reconcile the pool against the profile's competitor list.

    A prospect discovered before its host was named a competitor (or pushed in
    by an import) would keep posing as an available address. This pass marks
    every pool row matching a competitor host as `is_competitor`, so the
    counts stop counting a site you can never place a link on.

    Deliberately additive-only (naming a competitor then removing it does not
    un-mark rows — an old link prospect does not become placeable again), and
    deliberately NOT the whitelist: a competitor means "no placement possible",
    the whitelist means "exists but excluded from statistics". Conflating them
    would make the numbers mean two things at once.

    Returns the number of rows newly marked.
    """
    comps = {_bare_domain(c) for c in (load_profile(center_domain).get("competitors") or [])}
    comps.discard("")
    if not comps:
        return 0
    marked = 0
    for d, entry in (store.get("domains") or {}).items():
        if not isinstance(entry, dict) or entry.get("is_competitor"):
            continue
        host = _bare_domain(d)
        if not host:
            continue
        if any(host == c or host.endswith("." + c) for c in comps):
            entry["is_competitor"] = True
            entry["competitor_marked_at"] = _now()
            marked += 1
    return marked


# ---------------------------------------------------------------------------
# Run history: what actually changed since the last analysis.
#
# `times_discovered` cannot answer "what is new since yesterday" — it only says
# a domain was seen again. So every persisted run leaves a compact snapshot, and
# the diff between two snapshots is the answer an operator needs ("+12 new,
# 3 went 404, 1 recovered") before deciding whether tomorrow's batch is real.
# ---------------------------------------------------------------------------
RUN_LOG_KEEP = 10          # snapshots kept per center domain
RUN_SNAPSHOT_MAX = 20000   # domains per snapshot; beyond this only totals are kept


def _parse_ts(stamp):
    """Parse one of our own ISO timestamps into an aware UTC datetime."""
    s = str(stamp or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        v = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=dt.timezone.utc)
    return v


def record_run(store, label=""):
    """Snapshot the pool after a run, so the next run can be diffed against it."""
    doms = store.get("domains", {})
    names = sorted(doms)
    truncated = len(names) > RUN_SNAPSHOT_MAX
    snap = {
        "ts": _now(),
        "run": store.get("runs", 0),
        "label": str(label or "")[:80],
        "total": len(names),
        "valid": sum(1 for e in doms.values() if e.get("valid")),
        "acquired": sum(1 for e in doms.values() if e.get("acquired")),
        # The invalid list is small and buys the most useful diff line of all:
        # a domain that stopped verifying is a lost candidate, not a new one.
        "invalid": sorted(d for d, e in doms.items() if not e.get("valid")),
        "domains": [] if truncated else names,
        "total_only": truncated,
    }
    log = store.setdefault("run_log", [])
    if not isinstance(log, list):
        log = store["run_log"] = []
    log.append(snap)
    del log[:-RUN_LOG_KEEP]
    return snap


def run_diff(store, back=1):
    """Compare the latest run snapshot with the one `back` runs earlier."""
    log = [x for x in (store.get("run_log") or []) if isinstance(x, dict)]
    if len(log) < 2:
        return {"ok": True, "comparable": False, "runs": len(log),
                "reason": "need two recorded runs",
                "latest": log[-1] if log else None, "previous": None}
    try:
        back = max(1, min(len(log) - 1, int(back or 1)))
    except (TypeError, ValueError):
        back = 1
    cur, prev = log[-1], log[-1 - back]
    delta = {k: (cur.get(k) or 0) - (prev.get(k) or 0) for k in ("total", "valid", "acquired")}

    def brief(snap):
        # The snapshot stores a full name list for diffing; the response must not:
        # /api/store would otherwise grow by megabytes once a pool gets large.
        return {k: snap.get(k) for k in ("ts", "run", "label", "total", "valid",
                                         "acquired", "total_only")}

    base = {"ok": True, "runs": len(log), "latest": brief(cur), "previous": brief(prev),
            "back": back, "delta": delta}
    if cur.get("total_only") or prev.get("total_only"):
        # Refusing to invent a name diff is the honest answer: the snapshots
        # only kept totals, so report counts and say why.
        base.update({"comparable": False,
                     "reason": "snapshot truncated above %d domains" % RUN_SNAPSHOT_MAX})
        return base
    cur_set = set(cur.get("domains") or [])
    prev_set = set(prev.get("domains") or [])
    cur_bad = set(cur.get("invalid") or [])
    prev_bad = set(prev.get("invalid") or [])
    added = sorted(cur_set - prev_set)
    removed = sorted(prev_set - cur_set)
    # Status flips only mean something for domains present in both snapshots;
    # an addition that is already invalid is just a bad addition.
    newly_invalid = sorted((prev_set & cur_bad) - prev_bad)
    # Recovered = was invalid, now valid and still in the pool. It cannot be
    # "sorted(prev_bad - cur_bad)" alone: a domain dropped from the pool would
    # otherwise be reported as recovered.
    recovered = sorted((prev_bad & cur_set) - cur_bad)
    base.update({
        "comparable": True,
        "added": added[:200], "added_count": len(added),
        "removed": removed[:200], "removed_count": len(removed),
        "newly_invalid": newly_invalid[:200], "newly_invalid_count": len(newly_invalid),
        "recovered": recovered[:200], "recovered_count": len(recovered),
        "kept": len(cur_set & prev_set),
    })
    return base


# ---------------------------------------------------------------------------
# Whitelist: domains the operator does NOT want counted as backlink inventory.
#
# Why a separate concept from suppressions: suppressing says "never offer this
# slot again"; whitelisting says "this domain exists in my data but must not
# move any backlink number". Own-network sites, aggregators and mirrors land
# here. Whitelisted rows stay visible (so the toggle can be undone) yet they are
# invisible to the stats, to the gap and to the daily queue.
# ---------------------------------------------------------------------------
def whitelist_map(store):
    """Normalized {domain: {added_at, note}} view of the whitelist."""
    raw = store.get("whitelist")
    if isinstance(raw, (list, tuple)):
        raw = {d: {} for d in raw}
    out = {}
    for key, meta in (raw or {}).items():
        d = _bare_domain(key)
        if not d:
            continue
        out[d] = meta if isinstance(meta, dict) else {}
    return out


def whitelisted_domains(store):
    return set(whitelist_map(store))


def add_whitelist(store, domains, note=""):
    """Add hosts to the whitelist -> list of newly added domains."""
    if isinstance(domains, str):
        domains = re.split(r"[,\s\n]+", domains)
    wl = store.get("whitelist")
    if not isinstance(wl, dict):
        wl = {}
        store["whitelist"] = wl
    added = []
    for raw in (domains or []):
        d = _bare_domain(raw)
        if not d or d in wl:
            continue
        wl[d] = {"added_at": _now(), "note": str(note or "")[:200]}
        added.append(d)
    return added


def remove_whitelist(store, domains):
    """Remove hosts from the whitelist -> list of domains actually removed."""
    if isinstance(domains, str):
        domains = re.split(r"[,\s\n]+", domains)
    wl = store.get("whitelist")
    if not isinstance(wl, dict):
        return []
    removed = []
    for raw in (domains or []):
        d = _bare_domain(raw)
        if d and d in wl:
            wl.pop(d, None)
            removed.append(d)
    return removed


def whitelist_rows(store):
    """Whitelist as a list, annotated with what the pool knows about each host."""
    doms = store.get("domains", {})
    out = []
    for d, meta in whitelist_map(store).items():
        e = doms.get(d) or {}
        out.append({"domain": d,
                    "added_at": meta.get("added_at"),
                    "note": meta.get("note"),
                    "in_pool": d in doms,
                    "valid": bool(e.get("valid")),
                    "acquired": bool(e.get("acquired"))})
    out.sort(key=lambda r: r["domain"])
    return out


# ---------------------------------------------------------------------------
# Daily quota: a hard ceiling, configurable per center domain.
#
# The batch in daily_queue is a *plan*; this is the *gate*. Without it the pool's
# per-row "Use" button could claim 150 rows on a 100/day policy and nothing would
# complain. Enforcement therefore lives in claim_placement, not in the queue.
# ---------------------------------------------------------------------------
def _env_int(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


# Operator timezone: the quota day rolls at 00:00 there, not at UTC 00:00. The
# machine runs in UTC, so this is the one place that offset is declared.
QUOTA_TZ_OFFSET = _env_int("QUOTA_TZ_OFFSET", 8, -12, 14)
QUOTA_TZ = dt.timezone(dt.timedelta(hours=QUOTA_TZ_OFFSET))


def _quota_date():
    return dt.datetime.now(QUOTA_TZ).strftime("%Y-%m-%d")


def effective_quota(store):
    """Configured daily quota for this pool (never the raw, unvalidated value)."""
    raw = (store.get("settings") or {}).get("daily_quota")
    try:
        q = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DAILY_QUOTA
    return max(1, min(MAX_DAILY_QUOTA, q))


def set_daily_quota(store, value):
    """Persist a new daily quota -> (quota, error)."""
    try:
        q = int(value)
    except (TypeError, ValueError):
        return effective_quota(store), "daily_quota must be an integer"
    if q < 1 or q > MAX_DAILY_QUOTA:
        return effective_quota(store), "daily_quota must be between 1 and %d" % MAX_DAILY_QUOTA
    settings = store.setdefault("settings", {})
    if not isinstance(settings, dict):
        settings = {}
        store["settings"] = settings
    settings["daily_quota"] = q
    settings["daily_quota_updated_at"] = _now()
    return q, None


def _stamp_quota_date(stamp):
    """Placement timestamps are stored in UTC; the quota day is UTC+8.

    Slicing the first 10 chars would put anything claimed before 08:00 local
    into yesterday, so convert properly (and degrade gracefully on junk).
    """
    s = str(stamp or "")
    try:
        t = dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return t.astimezone(QUOTA_TZ).strftime("%Y-%m-%d")
    except ValueError:
        return s[:10]


def claimed_on(store, date=None):
    """Placements claimed on a given quota day (UTC+8 by default).

    Imported rows (verify_method="import:*") are skipped on purpose: they record
    links the operator already earned, so counting them would let one paste of a
    500-row export slam the hard daily gate shut and block the day's real work.
    """
    date = (date or _quota_date())[:10]
    n = 0
    for p in store.get("placements", {}).values():
        if p.get("state") not in tuple(ACTIVE_STATES) + ("live",):
            continue
        if _is_imported(p):
            continue
        stamp = p.get("claimed_at") or p.get("submitted_at") or p.get("live_at") or ""
        if _stamp_quota_date(stamp) == date:
            n += 1
    return n


def quota_state(store):
    """{quota, used, left} for the current quota day."""
    quota = effective_quota(store)
    used = claimed_on(store)
    return {"quota": quota, "used": used, "left": max(0, quota - used),
            "date": _quota_date(), "tz_offset": QUOTA_TZ_OFFSET}


LOST_WINDOW_DAYS = _env_int("LOST_WINDOW_DAYS", 7, 1, 90)


def lost_recent(store, days=None, limit=20):
    """Backlinks that died inside the window — the overview's todo strip.

    A survival recheck that writes `lost` and nobody ever looks at is the same
    as no recheck at all: the row leaves the ledger's happy path and the number
    just quietly drops. Surfacing them next to the queue makes the loss the
    first thing an operator sees, and gives them the domain to re-pitch.
    """
    days = LOST_WINDOW_DAYS if days is None else days
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=days)
    rows = []
    for p in store.get("placements", {}).values():
        if p.get("state") != "lost":
            continue
        when = _parse_ts(p.get("lost_at"))
        if when is None or when < cutoff:
            continue
        rows.append({
            "domain": p.get("target_domain") or "",
            "url": p.get("target_url") or "",
            "lost_at": p.get("lost_at"),
            "days_ago": max(0, int((now - when).total_seconds() // 86400)),
            "note": str((p.get("recheck") or {}).get("note") or "")[:140],
        })
    rows.sort(key=lambda x: x.get("lost_at") or "", reverse=True)
    return rows[:limit], len(rows)


def store_stats(store):
    doms = store.get("domains", {})
    # A live placement counts as owned even when the entry predates the
    # write-back in transition_placement (older ledgers must not stay stale).
    live = {_norm_target(x) for x in live_domains(store) if x}
    wl = whitelisted_domains(store)

    def owned(d, e):
        return bool(e.get("acquired")) or _norm_target(d) in live

    # Whitelisted hosts are visible in the pool but invisible to every number
    # below: they are neither discovered, nor owned, nor gap.
    counted = [(d, e) for d, e in doms.items() if d not in wl]
    total = len(counted)
    acquired = sum(1 for d, e in counted if owned(d, e))
    valid = sum(1 for d, e in counted if e.get("valid"))
    # Competitor domains are deliberately excluded, so they are neither
    # "acquired" nor a real "gap to pursue".
    competitors = sum(1 for d, e in counted if e.get("is_competitor"))
    # The names go with the count: the whitelist panel shows these as muted
    # read-only chips, so "auto-excluded" is something you can see and audit,
    # not just a number that quietly shrank.
    competitor_list = sorted(d for d, e in counted if e.get("is_competitor"))[:100]
    gap = sum(1 for d, e in counted
              if not owned(d, e) and not e.get("is_competitor"))
    gap_valid = sum(1 for d, e in counted
                    if (not owned(d, e)) and (not e.get("is_competitor")) and e.get("valid"))
    reciprocal = sum(1 for d, e in counted if e.get("type_key") == "reciprocal")
    reciprocal_ratio = round(reciprocal / total, 4) if total else 0.0
    by_type = {}
    for d, e in counted:
        tk = e.get("type_key", "unknown")
        bt = by_type.setdefault(tk, {"discovered": 0, "acquired": 0, "gap": 0})
        bt["discovered"] += 1
        if owned(d, e):
            bt["acquired"] += 1
        elif e.get("is_competitor"):
            pass  # excluded: neither acquired nor gap
        else:
            bt["gap"] += 1
    lost_list, lost_n = lost_recent(store)
    return {
        "total_discovered": total,
        "acquired": acquired,
        # Competitors are neither supply nor gap; surfacing the count keeps the
        # reconciliation visible instead of silently shrinking the numbers.
        "competitors": competitors,
        "competitor_list": competitor_list,
        "valid": valid,
        "gap": gap,
        "gap_valid": gap_valid,
        "reciprocal": reciprocal,
        "reciprocal_ratio": reciprocal_ratio,
        "reciprocal_ratio_warn": reciprocal_ratio > 0.30,
        "by_type": by_type,
        "whitelisted": len(wl),
        "whitelisted_in_pool": sum(1 for d in wl if d in doms),
        "runs": store.get("runs", 0),
        "updated_at": store.get("updated_at"),
        "acquired_domains": store.get("acquired_domains", []),
        "placements": placement_stats(store),
        "quota": quota_state(store),
        "lost_recent": lost_n,
        "lost_days": LOST_WINDOW_DAYS,
        "lost_list": lost_list,
    }


def domain_list(store):
    """Return pool domains as a flat list (sorted by priority desc)."""
    out = []
    idx = placement_index(store)
    sup = store.get("suppressions", {})
    wl = whitelisted_domains(store)
    live = {_norm_target(x) for x in live_domains(store) if x}
    for d, e in store.get("domains", {}).items():
        best = idx.get(_norm_target(d))
        acquired = bool(e.get("acquired")) or _norm_target(d) in live
        listed = d in wl
        out.append({
            "domain": d,
            "url": e.get("url"),
            "type_key": e.get("type_key"),
            "type_label_zh": e.get("type_label_zh"),
            "authority_tier": e.get("authority_tier"),
            "tranco_global_rank": (e.get("authority") or {}).get("tranco_global_rank"),
            "priority": e.get("priority"),
            "valid": e.get("valid"),
            "http_status": e.get("http_status"),
            "acquired": acquired,
            "is_gap": (not acquired) and (not listed),
            "whitelisted": listed,
            "is_competitor": bool(e.get("is_competitor")),
            "source": e.get("source", "seed"),
            "via_competitors": e.get("via_competitors") or [],
            "first_seen": e.get("first_seen"),
            "last_seen": e.get("last_seen"),
            "times_discovered": e.get("times_discovered", 1),
            "placement_state": best.get("state") if best else None,
            "placement_id": best.get("id") if best else None,
            "suppressed": _norm_target(d) in sup,
        })
    out.sort(key=lambda x: (-(x.get("priority") or 0), not x.get("valid")))
    return out


# ---------------------------------------------------------------------------
# Daily queue: a frozen batch of deliverable targets, quota per day.
#
# Why freeze instead of re-slicing every call: the pool used to hand back the
# same 39/51/20 rows on every run, so "50 a day" was really "the same 50 today
# and tomorrow". A frozen batch gives (a) a stable work list the operator can
# reload at noon without rows jumping around, (b) a hard daily quota, and
# (c) an auditable batch_id written onto every placement claimed from it, so
# "how much did we actually ship on 2026-11-15" is a ledger query, not a guess.
# ---------------------------------------------------------------------------
QUEUE_PREFIX = "queue-"
QUEUE_SCHEMA = "queue/1"
DEFAULT_DAILY_QUOTA = 100
MAX_DAILY_QUOTA = 2000
# Two concurrent page loads used to race on the same `.tmp` name and one of them
# failed with FileNotFoundError mid-replace. Serialise the read-modify-write and
# give every write its own temp file.
_QUEUE_LOCK = threading.Lock()


def _utc_date():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


QUEUE_KEEP_DAYS = 14


def _queue_path(center_domain, date=None):
    """One file per (center, day).

    A single rolling file meant a caller who forgot `date` (curl, monitoring, a
    second tab in another timezone) rewrote the freeze key and rebuilt the batch
    the operator was already working from. Dated files make that impossible.
    """
    safe = _sanitize_domain(center_domain)
    if not safe:
        return None
    if date:
        return os.path.join(DATA_DIR, "%s%s-%s.json"
                            % (QUEUE_PREFIX, safe, str(date).replace("-", "")))
    return os.path.join(DATA_DIR, "%s%s.json" % (QUEUE_PREFIX, safe))


def prune_queues(center_domain, keep_days=QUEUE_KEEP_DAYS):
    """Delete per-day queue files older than keep_days; returns the filenames."""
    safe = _sanitize_domain(center_domain)
    if not safe or not os.path.isdir(DATA_DIR):
        return []
    prefix = "%s%s-" % (QUEUE_PREFIX, safe)
    cutoff = (dt.datetime.now(QUOTA_TZ) - dt.timedelta(days=keep_days)).strftime("%Y%m%d")
    removed = []
    for name in os.listdir(DATA_DIR):
        if not name.startswith(prefix) or not name.endswith(".json"):
            continue
        stamp = name[len(prefix):-5]
        if len(stamp) == 8 and stamp.isdigit() and stamp < cutoff:
            try:
                os.remove(os.path.join(DATA_DIR, name))
                removed.append(name)
            except OSError:
                pass
    return removed


def queue_block_reason(store, domain, entry=None, whitelist=None):
    """Why this pool row cannot be handed out as a target today, or None."""
    entry = entry if entry is not None else (store.get("domains", {}).get(domain) or {})
    d = _norm_target(domain)
    if entry.get("acquired"):
        return "already have"
    if entry.get("is_competitor"):
        return "competitor"
    wl = whitelist if whitelist is not None else whitelisted_domains(store)
    if d in wl:
        return "whitelisted"
    if not entry.get("valid"):
        return "not verified"
    # placements / suppressions / cooldown / cadence rules all live in one place
    return placement_block_reason(store, d, entry.get("url") or ("https://" + d))


def _queue_row(domain, entry, store):
    return {
        "domain": domain,
        "url": entry.get("url") or ("https://" + domain),
        "priority": entry.get("priority"),
        "type_key": entry.get("type_key"),
        "type_label_zh": entry.get("type_label_zh"),
        "type_label_en": entry.get("type_label_en"),
        "authority_tier": entry.get("authority_tier"),
        "tranco_global_rank": (entry.get("authority") or {}).get("tranco_global_rank"),
        "valid": bool(entry.get("valid")),
        "http_status": entry.get("http_status"),
        "source": entry.get("source", "seed"),
        "via_competitors": entry.get("via_competitors") or [],
        "first_seen": entry.get("first_seen"),
    }


def daily_queue(store, center_domain, date=None, quota=None, refill=False, with_items=True):
    """Today's batch: up to `quota` verified, unclaimed, unsuppressed targets.

    Frozen per (center, date). `refill=True` tops the batch back up to quota with
    rows that appeared after the freeze — explicit, never automatic, so a batch
    cannot silently change size mid-day.
    """
    # Default to the *quota* day (UTC+8), so a caller that omits `date` (curl,
    # monitoring, the scheduler) lands on the same freeze key as the UI instead
    # of inventing a second, near-identical batch for the UTC day.
    date = (date or _quota_date())[:10]
    configured = effective_quota(store)
    if quota is None:
        quota = configured
    else:
        try:
            quota = int(quota)
        except (TypeError, ValueError):
            quota = configured
    quota = max(1, min(MAX_DAILY_QUOTA, quota))

    doms = store.get("domains", {})
    wl = whitelisted_domains(store)
    eligible = []
    for d, e in doms.items():
        if queue_block_reason(store, d, e, wl) is None:
            eligible.append((-(e.get("priority") or 0), d))
    eligible.sort()
    eligible_domains = [d for _, d in eligible]

    path = _queue_path(center_domain, date)
    with _QUEUE_LOCK:
        state = load_json_file(path, {}) if path else {}
        if not isinstance(state, dict) or state.get("center_domain") != center_domain \
                or state.get("date") != date:
            slug = _sanitize_domain(center_domain) or "default"
            prune_queues(center_domain)   # dated files accumulate; keep two weeks
            state = {"schema": QUEUE_SCHEMA, "center_domain": center_domain, "date": date,
                     "batch_id": "%s-%s" % (slug, date.replace("-", "")),
                     "quota": quota, "items": [], "created_at": _now()}

        frozen = [d for d in (state.get("items") or []) if isinstance(d, str)]
        before = list(frozen)
        if refill:
            have = set(frozen)
            for d in eligible_domains:
                if len(frozen) >= quota:
                    break
                if d not in have:
                    frozen.append(d)
                    have.add(d)
        elif not frozen:
            frozen = eligible_domains[:quota]

        # A lowered quota must not silently delete rows the operator already saw;
        # the batch keeps its size and only stops growing.
        changed = (frozen != before) or state.get("quota") != quota
        state["items"] = frozen
        state["quota"] = quota
        if changed:
            state["updated_at"] = _now()
        if path and changed:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
            except Exception:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise

    batch_id = state["batch_id"]
    available = []
    for d in frozen:
        e = doms.get(d)
        if e is None:
            continue
        if queue_block_reason(store, d, e) is None:
            available.append(d)

    claimed_today = 0
    for p in store.get("placements", {}).values():
        if p.get("batch_id") == batch_id and p.get("state") in tuple(ACTIVE_STATES) + ("live",):
            claimed_today += 1

    # Throughput for the day, regardless of which path claimed it: the pool's
    # single "Use" button does not go through the batch, so a batch-scoped count
    # alone would under-report what was actually worked on.
    claimed_day = 0
    for p in store.get("placements", {}).values():
        if p.get("state") not in tuple(ACTIVE_STATES) + ("live",):
            continue
        stamp = p.get("claimed_at") or p.get("submitted_at") or p.get("live_at") or ""
        if _stamp_quota_date(stamp) == date:
            claimed_day += 1

    out = {
        "date": date,
        "batch_id": batch_id,
        "quota": quota,
        "quota_used": claimed_on(store),
        # The claim gate uses the *configured* quota, so report that beside the
        # batch quota rather than letting an explicit query param look like headroom.
        "quota_gate": configured,
        "quota_left": max(0, configured - claimed_on(store)),
        "batch_size": len(frozen),
        "available": len(available),
        "claimed_today": claimed_today,
        "claimed_day": claimed_day,
        "inventory": len(eligible_domains),
        "supply_gap": max(0, quota - len(frozen)),
        "exhausted": len(available) == 0,
        "frozen": bool(frozen),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
    }
    if with_items:
        out["items"] = [_queue_row(d, doms[d], store) for d in available]
    return out


# ---------------------------------------------------------------------------
# Supply refill: the queue is a quota, the pool is the shelf behind it.
#
# A frozen batch of 100 is worth nothing if the shelf holds 12 candidates: the
# day after tomorrow the batch is short again. Refilling is therefore a supply
# problem, not a batch problem — and it costs network calls, so it is rate
# limited by a persisted cooldown rather than fired on every page load.
# ---------------------------------------------------------------------------
REFILL_THRESHOLD = _env_int("REFILL_THRESHOLD", 30, 1, 1000)
REFILL_COOLDOWN_H = _env_int("REFILL_COOLDOWN_H", 6, 1, 72)
REFILL_KEEP = 20


def inventory_count(store):
    """Claimable pool rows right now = what tomorrow's batch could be built from."""
    doms = store.get("domains", {})
    wl = whitelisted_domains(store)
    return sum(1 for d, e in doms.items()
               if queue_block_reason(store, d, e, wl) is None)


def refill_state(store, center_domain=None, quota=None, now=None):
    """Is the shelf low, and may we go shopping? (`due` is the only answer that acts.)"""
    configured = effective_quota(store)
    if quota is None:
        quota = configured
    inv = inventory_count(store)
    # The shelf exists to feed the daily batch, so its low-water mark must be
    # judged against the quota, not a small fixed constant: with the default
    # 100/day quota a fixed 30 threshold stops restocking at ~30 candidates and
    # the queue can then never actually claim 100. The env knob survives as a
    # floor for tiny quotas (and can still raise the target above the quota).
    threshold = max(REFILL_THRESHOLD, int(quota or 0))
    last = {}
    for rec in reversed(store.get("refills") or []):
        if isinstance(rec, dict) and rec.get("ts"):
            last = rec
            break
    # No-progress backoff. Free sources saturate: once the pool stops growing, a
    # refill every 6 hours is pure noise against other people's servers. Each
    # consecutive attempt that added nothing doubles the wait (capped at 8x),
    # and one productive attempt resets it.
    history = [x for x in (store.get("refills") or []) if isinstance(x, dict)]
    zero_streak = 0
    for rec in reversed(history):
        if rec.get("added") is None or (rec.get("added") or 0) > 0:
            break
        zero_streak += 1
    backoff = min(8, 2 ** zero_streak) if zero_streak else 1
    cooldown_h = REFILL_COOLDOWN_H * backoff
    cooldown_left = 0.0
    if last:
        when = _parse_ts(last.get("ts"))
        if when is not None:
            # Clamp at zero: a timestamp in the future (clock skew, a hand-edited
            # store) must not produce a cooldown longer than the configured one.
            age_h = max(0.0, (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600.0)
            cooldown_left = max(0.0, round(cooldown_h - age_h, 2))
    low = inv < threshold
    due = bool(low and cooldown_left <= 0)
    if not low:
        reason = "inventory %d >= threshold %d" % (inv, threshold)
    elif cooldown_left > 0:
        reason = "cooldown %.1fh left%s" % (cooldown_left,
                                            "" if backoff == 1 else " (x%d backoff)" % backoff)
    else:
        reason = "inventory %d < threshold %d" % (inv, threshold)
    return {
        "center_domain": center_domain,
        "inventory": inv,
        "quota": quota,
        "supply_gap": max(0, quota - inv),
        "threshold": threshold,
        "threshold_env": REFILL_THRESHOLD,
        "cooldown_h": cooldown_h,
        "base_cooldown_h": REFILL_COOLDOWN_H,
        "backoff": backoff,
        "zero_streak": zero_streak,
        "cooldown_left": cooldown_left,
        "low": low,
        "due": due,
        "reason": reason,
        "last": last or None,
        "history": history[-5:],
    }


def mark_refill(store, kind="auto", available=None, added=None, note="", reason="",
                threshold=None):
    """Book one refill attempt. Persisted so a restart cannot reset the cooldown."""
    rows = store.setdefault("refills", [])
    if not isinstance(rows, list):
        rows = store["refills"] = []
    rec = {"ts": _now(), "kind": str(kind or "auto")[:20],
           "available": available, "added": added,
           "threshold": int(threshold) if threshold else REFILL_THRESHOLD,
           "cooldown_h": REFILL_COOLDOWN_H,
           "reason": str(reason or "")[:140], "note": str(note or "")[:200]}
    rows.append(rec)
    del rows[:-REFILL_KEEP]
    return rec


def load_domain_channels(center_domain=None):
    """Load channel config for a specific domain (with overrides support)."""
    if not center_domain:
        # Load global channels
        try:
            with open(CHANNELS_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("channels", [])
        except Exception:
            return []
    
    # Try to load domain-specific channels
    safe_name = _sanitize_domain(center_domain)
    if not safe_name:
        return load_domain_channels(None)
    
    domain_channels_path = os.path.join(DATA_DIR, f"channels-{safe_name}.json")
    try:
        with open(domain_channels_path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("channels", [])
    except Exception:
        # Fallback to global channels if domain-specific doesn't exist
        return load_domain_channels(None)


def save_domain_channels(channels, center_domain):
    """Save domain-specific channel configuration."""
    if not center_domain:
        raise ValueError("center_domain is required")
    
    safe_name = _sanitize_domain(center_domain)
    if not safe_name:
        raise ValueError("Invalid domain name")
    
    domain_channels_path = os.path.join(DATA_DIR, f"channels-{safe_name}.json")
    os.makedirs(os.path.dirname(domain_channels_path), exist_ok=True)
    
    cfg = {
        "version": "1.0.0",
        "center_domain": center_domain,
        "note": f"Domain-specific channel overrides for {center_domain}",
        "channels": channels
    }
    
    tmp = domain_channels_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, domain_channels_path)
    return cfg


# --------------------------------------------------------------------------- #
# domain profiles: per-center-domain keyword / competitor profiles
# --------------------------------------------------------------------------- #
def _looks_like_domain(domain):
    """True when the value could be a real hostname (label[.label]+ with a TLD).

    Guards against half-typed input: the UI switches domains on a debounce, so
    typing "soundbuttons.click" char by char would otherwise persist profiles
    named "soundbuttons", "soundbuttons.c", ... carrying the previous domain's
    keywords.
    """
    d = (domain or "").strip().strip(".").lower()
    if not d or len(d) > 100 or " " in d:
        return False
    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", d):
        return False
    return len(d.rsplit(".", 1)[-1]) >= 2


def _profile_path(center_domain):
    if not _looks_like_domain(center_domain):
        return None
    safe = _sanitize_domain(center_domain)
    if not safe:
        return None
    return os.path.join(DATA_DIR, "profile-%s.json" % safe)


def _as_list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,\n]", v) if x.strip()]
    return []


def load_profile(center_domain):
    """Return the keyword/competitor profile for a center domain.

    Resolution order (first hit wins):
      1. data/profile-<domain>.json      - operator edits (saved, non-empty only)
      2. profiles.json -> profiles[domain] - shipped default
      3. empty profile                     - unknown domain

    An all-empty saved profile counts as "no opinion" and falls through to the
    shipped default: the UI writes the form on domain switch, so a visitor who
    never typed anything would otherwise pin a blank profile that shadows the
    default forever.

    Returns {keywords:[], competitors:[], note:"", source:"saved|default|none"}.
    """
    center_domain = (center_domain or "").strip().lower()
    if not center_domain:
        return {"keywords": [], "competitors": [], "note": "", "note_en": "", "source": "none"}

    p = _profile_path(center_domain)
    if p and os.path.isfile(p):
        d = load_json_file(p, None)
        if isinstance(d, dict):
            kws = _as_list(d.get("keywords"))
            comps = _as_list(d.get("competitors"))
            note = d.get("note") or ""
            note_en = d.get("note_en") or ""
            if kws or comps or note or note_en:
                return {"keywords": kws, "competitors": comps,
                        "note": note, "note_en": note_en, "source": "saved"}

    cfg = load_json_file(PROFILES_PATH, {})
    profs = (cfg or {}).get("profiles") or {}
    prof = profs.get(center_domain)
    if isinstance(prof, dict):
        return {"keywords": _as_list(prof.get("keywords")),
                "competitors": _as_list(prof.get("competitors")),
                "note": prof.get("note") or "",
                "note_en": prof.get("note_en") or "",
                "source": "default"}
    return {"keywords": [], "competitors": [], "note": "", "note_en": "", "source": "none"}


def save_profile(center_domain, keywords, competitors, note=None):
    """Persist an operator-edited profile for a center domain.

    An all-empty payload is a no-op (returns the existing view, writes nothing):
    a blank form means "no opinion", and persisting it would shadow the shipped
    default with an empty override.
    """
    center_domain = (center_domain or "").strip().lower()
    if not center_domain:
        raise ValueError("center_domain is required")
    p = _profile_path(center_domain)
    if not p:
        raise ValueError("invalid center_domain")
    kws, comps = _as_list(keywords), _as_list(competitors)
    if not (kws or comps or (note or "").strip()):
        return {"version": "1.0.0", "center_domain": center_domain,
                "keywords": kws, "competitors": comps, "note": "",
                "updated_at": _now(), "skipped": "empty"}
    os.makedirs(DATA_DIR, exist_ok=True)
    cfg = {
        "version": "1.0.0",
        "center_domain": center_domain,
        "keywords": kws,
        "competitors": comps,
        "note": (note or "")[:500],
        "updated_at": _now(),
    }
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return cfg


def list_profiles():
    """Return every known profile: defaults from profiles.json + saved overrides."""
    out = {}
    cfg = load_json_file(PROFILES_PATH, {}) or {}
    for dom, prof in ((cfg.get("profiles") or {}).items()):
        if isinstance(prof, dict):
            out[dom.lower()] = {"keywords": _as_list(prof.get("keywords")),
                                "competitors": _as_list(prof.get("competitors")),
                                "note": prof.get("note") or "", "source": "default"}
    try:
        for fn in os.listdir(DATA_DIR):
            if fn.startswith("profile-") and fn.endswith(".json"):
                d = load_json_file(os.path.join(DATA_DIR, fn), None)
                if isinstance(d, dict) and d.get("center_domain"):
                    dom = d["center_domain"].lower()
                    out[dom] = {"keywords": _as_list(d.get("keywords")),
                                "competitors": _as_list(d.get("competitors")),
                                "note": d.get("note") or "", "source": "saved"}
    except Exception:
        pass
    return out


def known_domains():
    """Every center domain this workspace knows about, for the UI picker.

    A free-text field is how the project ended up with two parallel pools
    (soundbuttons.cc vs soundbuttons.click) and no way to see which one is
    which. This aggregates every source of truth so the picker can show what
    actually exists, with the counts that distinguish them:

      profiles.json / data/profile-*.json : a keyword profile exists
      seeds/seed-*.json, data/seed-*.json : a curated seed library exists
      data/competitor-links-*.json        : a competitor harvest exists
      data/store-*.json                   : a pool exists (with its size)

    Returns a list of dicts sorted by "most data first", then alphabetically.
    """
    rows = {}

    def slot(dom):
        d = (dom or "").strip().lower()
        if not d or not _looks_like_domain(d):
            return None
        return rows.setdefault(d, {"domain": d, "sources": [], "keywords": [],
                                   "competitors": [], "pool_domains": 0,
                                   "seed_rows": 0, "competitor_links": 0,
                                   "placements_live": 0, "updated_at": None})

    # 1) shipped + saved profiles
    for dom, prof in list_profiles().items():
        s = slot(dom)
        if not s:
            continue
        s["keywords"] = prof.get("keywords") or []
        s["competitors"] = prof.get("competitors") or []
        s["sources"].append("profile")

    # 2) seed libraries (shipped and operator overrides)
    for base, tag in ((DATA_DIR, "seed"), (SEEDS_DIR, "seed")):
        try:
            names = os.listdir(base)
        except Exception:
            names = []
        for fn in names:
            if not (fn.startswith("seed-") and fn.endswith(".json")):
                continue
            dom = fn[len("seed-"):-len(".json")]
            s = slot(dom)
            if not s:
                continue
            data = load_json_file(os.path.join(base, fn), [])
            if isinstance(data, dict):
                data = data.get("sites") or data.get("items") or data.get("rows") or []
            n = len(data) if isinstance(data, list) else 0
            s["seed_rows"] = max(s["seed_rows"], n)
            if tag not in s["sources"]:
                s["sources"].append(tag)

    # 3) competitor harvests
    for fn in _listdir(DATA_DIR) + _listdir(SEEDS_DIR):
        if not (fn.startswith("competitor-links-") and fn.endswith(".json")):
            continue
        dom = fn[len("competitor-links-"):-len(".json")]
        s = slot(dom)
        if not s:
            continue
        data = load_json_file(os.path.join(DATA_DIR, fn), None) or \
            load_json_file(os.path.join(SEEDS_DIR, fn), None)
        n = 0
        if isinstance(data, dict):
            n = len(data.get("rows") or data.get("sites") or [])
        elif isinstance(data, list):
            n = len(data)
        s["competitor_links"] = max(s["competitor_links"], n)
        if "competitor_links" not in s["sources"]:
            s["sources"].append("competitor_links")

    # 4) pools
    for fn in _listdir(DATA_DIR):
        if not (fn.startswith("store-") and fn.endswith(".json")):
            continue
        dom = fn[len("store-"):-len(".json")]
        s = slot(dom)
        if not s:
            continue
        data = load_json_file(os.path.join(DATA_DIR, fn), {}) or {}
        s["pool_domains"] = len(data.get("domains") or {})
        s["placements_live"] = placement_stats(data).get("live", 0)
        s["updated_at"] = data.get("updated_at")
        if "pool" not in s["sources"]:
            s["sources"].append("pool")

    out = list(rows.values())
    for r in out:
        r["label"] = "%s · pool %d · seed %d" % (r["domain"], r["pool_domains"], r["seed_rows"])
    out.sort(key=lambda r: (r["updated_at"] or "", r["pool_domains"], r["seed_rows"],
                            r["domain"]), reverse=True)
    return out


def _listdir(path):
    try:
        return sorted(os.listdir(path))
    except Exception:
        return []



def load_json_file(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Placement ledger: the single source of truth for "already delivered".
#
# Two layers, deliberately NOT mixed:
#   domains{}      - "seen" candidates. Never an exclusion reason on its own.
#   placements{}   - delivery records. Only state == "live" (with evidence)
#                    counts as a successfully used backlink.
# center_domain is implied by the store file (store-<domain>.json), so ledger
# rows carry no center_domain field and cross-niche isolation stays intact.
# ---------------------------------------------------------------------------
PLACEMENT_STATES = ("registered", "claimed", "submitted", "live",
                    "rejected", "lost", "error")
ACTIVE_STATES = ("registered", "claimed", "submitted")
COOLDOWN_DAYS = 90
# How old a `live` row's last survival probe may get before it counts as due.
# 7 days: often enough to notice a removed link within a week, rare enough that a
# few hundred rows do not hammer other people's servers.
RECHECK_DAYS = _env_int("RECHECK_DAYS", 7, 1, 90)
_TS = "%Y-%m-%dT%H:%M:%SZ"

_ALLOWED_TRANSITIONS = {
    "registered": ("claimed",),
    # claimed -> live is allowed for backfilling a delivery that already went
    # live; it still requires landing_url + verify_method as evidence.
    "claimed": ("submitted", "live", "rejected", "error"),
    "submitted": ("live", "rejected", "error"),
    "live": ("lost",),
    "lost": ("submitted",),
    "rejected": (),
    "error": (),
}
_STATE_TS = {"submitted": "submitted_at", "live": "live_at", "lost": "lost_at",
             "rejected": "rejected_at", "error": "error_at"}


def _norm_target(value):
    """Normalize a URL or domain so the same slot always yields the same key."""
    v = (value or "").strip().lower().split("#", 1)[0]
    return v[:-1] if v.endswith("/") else v


def placement_key(target_domain, target_url, placement_type="link"):
    """Idempotency key for one delivery slot (never a whole domain)."""
    raw = "|".join((_norm_target(target_domain), _norm_target(target_url),
                    (placement_type or "link").strip().lower()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def live_domains(store):
    """Domains holding at least one verified live backlink."""
    return {p.get("target_domain") for p in store.get("placements", {}).values()
            if p.get("state") == "live" and p.get("target_domain")}


def owned_domains(store):
    """Domains that must be treated as 'already have' by gap analysis."""
    return live_domains(store) | set(store.get("acquired_domains", []))


def placement_block_reason(store, target_domain, target_url, placement_type="link"):
    """Why this slot must not be claimed, or None when claiming is allowed."""
    now = dt.datetime.now(dt.timezone.utc)
    d = _norm_target(target_domain)
    key = placement_key(d, target_url, placement_type)
    # A whitelisted host is excluded from every backlink number, so promoting a
    # new link on it would create work the ledger can never count.
    if _bare_domain(d) in whitelisted_domains(store):
        return "whitelisted: excluded from backlink stats (remove it first)"
    sup = store.get("suppressions", {})
    for scope in (d, key):
        if scope in sup:
            return "suppressed: " + str(sup[scope].get("reason") or "operator excluded")
    rows = store.get("placements", {})
    cur = rows.get(key)
    if cur:
        s = cur.get("state")
        if s == "live":
            return "slot already has a verified live backlink"
        if s in ACTIVE_STATES:
            return "slot already " + str(s)
        if s == "lost":
            return "link lost: manual review required before reuse"
        cd = cur.get("cooldown_until")
        if cd and cd > now.strftime(_TS):
            return "cooldown until " + cd
    cutoff = (now - dt.timedelta(days=COOLDOWN_DAYS)).strftime(_TS)
    for p in rows.values():
        if _norm_target(p.get("target_domain")) != d or p.get("state") not in ("live", "submitted"):
            continue
        stamp = p.get("live_at") or p.get("submitted_at") or ""
        if stamp and stamp >= cutoff:
            return "domain cadence: %d-day window after %s" % (COOLDOWN_DAYS, p.get("state"))
    return None


def claim_placement(store, params):
    """Claim one delivery slot. Idempotent by key -> (record, block_reason)."""
    d = _norm_target(params.get("target_domain"))
    u = _norm_target(params.get("target_url"))
    t = (params.get("placement_type") or "link").strip().lower()
    if not d or not u:
        return None, "target_domain and target_url are required"
    reason = placement_block_reason(store, d, u, t)
    if reason:
        return None, reason
    # Hard daily ceiling. The batch is only a plan; this is the gate that makes
    # "100/day" true even when rows are claimed one by one from the pool.
    quota = effective_quota(store)
    used = claimed_on(store)
    if used >= quota:
        return None, ("daily quota reached: %d/%d claimed today (quota day %s UTC+%d) "
                      "— raise it via POST /api/settings" %
                      (used, quota, _quota_date(), QUOTA_TZ_OFFSET))
    key = placement_key(d, u, t)
    rows = store.setdefault("placements", {})
    rec = rows.get(key) or {
        "id": key, "target_domain": d, "target_url": u, "placement_type": t,
        "created_at": _now(), "state": "registered", "evidence": [],
    }
    rec["state"] = "claimed"
    rec["claimed_at"] = _now()
    rec["batch_id"] = str(params.get("batch_id") or "").strip()[:120]
    rec["own_url"] = str(params.get("own_url") or rec.get("own_url") or "").strip()[:500]
    if params.get("note"):
        rec["note"] = str(params["note"])[:500]
    rows[key] = rec
    return rec, None


def claim_placements_batch(store, items):
    """Claim many placement slots at once; idempotent per slot key.

    items: list of param dicts (same keys as claim_placement). Each slot is
    claimed independently, so a blocked row never aborts the others. The daily
    quota is checked once up front and again per row in claim_placement, so a
    batch can never overshoot the configured ceiling. Returns
    {results:[{ok,target_domain,target_url,placement,reason}],claimed,blocked,
     quota_blocked,quota,remaining}.
    """
    results, claimed, blocked, quota_blocked = [], 0, 0, 0
    if not isinstance(items, list):
        return {"results": [{"ok": False, "reason": "items must be a list"}],
                "claimed": 0, "blocked": 1, "quota_blocked": 0,
                "quota": effective_quota(store), "remaining": 0}
    quota = effective_quota(store)
    for it in (items or []):
        if not isinstance(it, dict):
            results.append({"ok": False, "reason": "item must be an object"})
            blocked += 1
            continue
        rec, reason = claim_placement(store, it)
        results.append({"ok": rec is not None,
                        "target_domain": it.get("target_domain"),
                        "target_url": it.get("target_url"),
                        "placement": rec, "reason": reason})
        if reason:
            blocked += 1
            if reason.startswith("daily quota reached"):
                quota_blocked += 1
        else:
            claimed += 1
    return {"results": results, "claimed": claimed, "blocked": blocked,
            "quota_blocked": quota_blocked, "quota": quota,
            "remaining": max(0, quota - claimed_on(store))}


def transition_placement(store, params):
    """Advance a placement. Reaching 'live' requires verifiable evidence."""
    d = _norm_target(params.get("target_domain"))
    u = _norm_target(params.get("target_url"))
    t = (params.get("placement_type") or "link").strip().lower()
    key = str(params.get("id") or placement_key(d, u, t))
    rows = store.setdefault("placements", {})
    rec = rows.get(key)
    if not rec:
        return None, "placement not found: " + key
    nxt = str(params.get("state") or "").strip().lower()
    cur = rec.get("state")
    if nxt not in _ALLOWED_TRANSITIONS.get(cur, ()):
        return None, "illegal transition %s -> %s" % (cur, nxt)
    if nxt == "live":
        landing = str(params.get("landing_url") or "").strip()
        method = str(params.get("verify_method") or "").strip()
        if not landing or not method:
            return None, "live requires landing_url and verify_method as evidence"
        rec["verify"] = {
            "landing_url": landing[:500], "verify_method": method[:120],
            "observed_href": str(params.get("observed_href") or "")[:500],
            "rel": str(params.get("rel") or "")[:60],
            "anchor_text": str(params.get("anchor_text") or "")[:300],
            "verified_at": _now(),
        }
    rec["state"] = nxt
    if _STATE_TS.get(nxt):
        rec[_STATE_TS[nxt]] = _now()
    if nxt == "live":
        # A verified live backlink IS "acquired". Without this write-back the
        # pool kept showing a delivered domain as a gap (and the overview's
        # "Acquired" count never moved), which made the queue -> claim -> live
        # loop look broken from the operator's side.
        d0 = _norm_target(rec.get("target_domain"))
        entry = store.setdefault("domains", {}).get(d0)
        if entry is not None:
            entry["acquired"] = True
    if nxt in ("rejected", "error"):
        rec["failure_reason"] = str(params.get("failure_reason") or "")[:300]
        try:
            days = max(0, int(params.get("cooldown_days", COOLDOWN_DAYS)))
        except (TypeError, ValueError):
            days = COOLDOWN_DAYS
        rec["cooldown_until"] = (dt.datetime.now(dt.timezone.utc)
                                 + dt.timedelta(days=days)).strftime(_TS)
    if params.get("note"):
        rec.setdefault("evidence", []).append({"at": _now(), "note": str(params["note"])[:300]})
    rows[key] = rec
    return rec, None


def suppress_placement(store, params):
    """Permanently exclude a domain or one exact slot, or remove that exclusion."""
    scope = str(params.get("id") or "").strip() or _norm_target(params.get("target_domain"))
    if not scope:
        return None, "target_domain or id is required"
    sup = store.setdefault("suppressions", {})
    if params.get("remove"):
        sup.pop(scope, None)
        return {"scope": scope, "removed": True}, None
    reason = str(params.get("reason") or "operator excluded").strip()[:300]
    sup[scope] = {"reason": reason, "at": _now()}
    return {"scope": scope, "reason": reason}, None


# ---------------------------------------------------------------------------
# Import the links you already own (GSC / Ahrefs / Common Crawl export).
#
# Why import into the ledger instead of just flipping an "acquired" flag: an
# operator's export *is* evidence, and every number in this tool is supposed to
# carry its source. A row imported here becomes a `live` placement tagged
# verify_method="import:<source>" with verified_at="" (never probed), so
#   1) the gap shrinks by exactly the domains that export proves,
#   2) the per-domain cadence keeps those domains from being claimed again (no
#      quota burned on links you already have),
#   3) the survival recheck can later probe exactly the rows whose evidence is
#      an export rather than a live visit.
# It deliberately does NOT touch the daily quota: importing yesterday's links is
# bookkeeping, not today's work.
# ---------------------------------------------------------------------------
IMPORT_MAX_ROWS = 2000


def _import_cells(line):
    """Split one CSV/TSV line into cells, tolerating quoted commas."""
    if "," in line:
        try:
            return list(next(csv.reader([line])))
        except (csv.Error, StopIteration):
            pass
    return re.split(r"[\t;]", line)


def _parse_link_rows(text, limit=IMPORT_MAX_ROWS):
    """Extract (page_url, host) pairs from whatever the operator pastes.

    Accepts one URL per line, a bare host per line, or a CSV/TSV export where a
    single column holds the linking page and the others hold date / anchor /
    traffic numbers. The first cell that resolves to a real host wins, so
    "12,https://x.com/a,anchor" parses while a header row does not.
    """
    rows, invalid = [], 0
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if len(rows) >= limit:
            break
        page = host = ""
        for cell in _import_cells(line):
            cell = (cell or "").strip().strip('"').strip("'").strip()
            h = _bare_domain(cell)
            if h:
                page, host = cell, h
                break
        if not host:
            invalid += 1
            continue
        if not re.match(r"^[a-z][a-z0-9+.-]*://", page, re.I):
            page = "https://" + page.lstrip("/")
        rows.append({"page": page[:500], "host": host})
    return rows, invalid


def _is_imported(rec):
    """True when a ledger row came from an operator export, not from a visit."""
    if not isinstance(rec, dict):
        return False
    if rec.get("imported"):
        return True
    return str((rec.get("verify") or {}).get("verify_method") or "").startswith("import:")


def _sync_acquired_flags(store, domains=None):
    """Recompute each pool entry's acquired flag: manual mark OR a live placement.

    Without this, an import (or a removed import) leaves `acquired` disagreeing
    with the ledger in the raw JSON — the stats survive because they union with
    live_domains(), but every other reader of the flag would be lied to.
    """
    live = {_norm_target(x) for x in live_domains(store) if x}
    manual = set(store.get("acquired_domains", []))
    for d, e in store.get("domains", {}).items():
        if domains is not None and d not in domains:
            continue
        e["acquired"] = bool(d in manual or _norm_target(d) in live)


def _import_snapshot(store):
    s = store_stats(store)
    return {"total": s["total_discovered"], "acquired": s["acquired"],
            "gap": s["gap"], "gap_valid": s["gap_valid"],
            "records": s["placements"]["total"], "live": s["placements"]["live"]}


def import_placements(store, text="", source="operator-export", dry_run=False,
                      remove=False, own_url="", limit=IMPORT_MAX_ROWS):
    """Turn a pasted backlink export into `live` ledger rows; return a gap report.

    remove=True deletes the rows this feature created for the same hosts, which
    is how an operator undoes a bad paste (the gap comes back exactly).
    """
    rows, invalid = _parse_link_rows(text, limit)
    src = re.sub(r"[^A-Za-z0-9._:/-]", "", str(source or "operator-export")).strip()[:60] \
        or "operator-export"
    if dry_run:  # mutate a copy so the preview cannot lie or leak a write
        store = copy.deepcopy(store)
    center = _bare_domain(store.get("center_domain") or "")
    wl = whitelisted_domains(store)
    doms = store.setdefault("domains", {})
    places = store.setdefault("placements", {})
    sup = store.get("suppressions", {})
    before = _import_snapshot(store)
    now = _now()
    skipped = {"self": 0, "competitor": 0, "whitelisted": 0, "suppressed": 0,
               "existing": 0, "duplicate": 0}
    hosts, seen, accepted = set(), set(), []
    for r in rows:
        host, page = r["host"], r["page"]
        if center and (host == center or host.endswith("." + center)):
            skipped["self"] += 1
            continue
        if host in wl:
            skipped["whitelisted"] += 1
            continue
        if (doms.get(host) or {}).get("is_competitor"):
            skipped["competitor"] += 1
            continue
        if host in sup:
            skipped["suppressed"] += 1
            continue
        key = placement_key(host, page)
        if key in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(key)
        hosts.add(host)
        cur = places.get(key)
        if cur:
            skipped["duplicate" if cur.get("state") == "live" else "existing"] += 1
            continue
        accepted.append((key, host, page))

    removed = 0
    if remove:
        for key, rec in list(places.items()):
            if not _is_imported(rec):
                continue
            if _bare_domain(rec.get("target_domain")) not in hosts:
                continue
            places.pop(key, None)
            removed += 1
        _sync_acquired_flags(store, {h for h in hosts if h in doms})
    else:
        for key, host, page in accepted:
            places[key] = {
                "id": key, "target_domain": host, "target_url": page,
                "placement_type": "link", "created_at": now, "state": "live",
                "live_at": now, "imported": True, "imported_at": now,
                "import_source": src, "own_url": str(own_url or "")[:500],
                "batch_id": "",
                "verify": {"landing_url": page, "verify_method": "import:" + src,
                           "observed_href": "", "rel": "", "anchor_text": "",
                           "verified_at": ""},
                "evidence": [{"at": now, "note": "imported from export (%s)" % src}],
            }
        _sync_acquired_flags(store, {h for h in hosts if h in doms})

    in_pool = sorted(h for h in hosts if h in doms)
    out_pool = sorted(h for h in hosts if h not in doms)
    after = _import_snapshot(store)
    log = store.setdefault("imports", [])
    log.append({"at": now, "mode": "remove" if remove else "import", "source": src,
                "parsed": len(rows), "written": removed if remove else len(accepted),
                "dry_run": bool(dry_run), "domains": len(hosts)})
    store["imports"] = log[-20:]
    return {
        "ok": True, "dry_run": bool(dry_run), "mode": "remove" if remove else "import",
        "source": src, "parsed": len(rows), "invalid": invalid,
        "accepted": 0 if remove else len(accepted), "written": len(accepted),
        "removed": removed, "domains": len(hosts), "skipped": skipped,
        "in_pool": len(in_pool), "out_of_pool": len(out_pool),
        "in_pool_sample": in_pool[:20], "out_of_pool_sample": out_pool[:20],
        "before": before, "after": after,
        "gap_delta": after["gap"] - before["gap"],
        "acquired_delta": after["acquired"] - before["acquired"],
        "live_delta": after["live"] - before["live"],
        "quota_untouched": True,
    }


def placement_stats(store):
    by_state = {}
    for p in store.get("placements", {}).values():
        s = p.get("state", "unknown")
        by_state[s] = by_state.get(s, 0) + 1
    imported = sum(1 for p in store.get("placements", {}).values() if _is_imported(p))
    return {"total": len(store.get("placements", {})), "by_state": by_state,
            "live": by_state.get("live", 0),
            "in_progress": sum(by_state.get(s, 0) for s in ACTIVE_STATES),
            "suppressed": len(store.get("suppressions", {})),
            "imported": imported,
            "live_domains": len(live_domains(store))}


def placement_list(store):
    out = list(store.get("placements", {}).values())
    out.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return out


def placement_index(store):
    """target_domain -> best record, for O(n+m) pool-row decoration."""
    rank = {"live": 0, "submitted": 1, "claimed": 2, "registered": 3,
            "lost": 4, "rejected": 5, "error": 6}
    idx = {}
    for p in store.get("placements", {}).values():
        d = _norm_target(p.get("target_domain"))
        if not d:
            continue
        best = idx.get(d)
        if best is None or (rank.get(p.get("state"), 9), p.get("created_at") or "") < \
                           (rank.get(best.get("state"), 9), best.get("created_at") or ""):
            idx[d] = p
    return idx


if __name__ == "__main__":
    s = load_store()
    print(json.dumps(store_stats(s), ensure_ascii=False, indent=2))
