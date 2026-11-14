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
import datetime as dt
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
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
        data.setdefault("runs", 0)
        data.setdefault("center_domain", center_domain)
        return data
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "updated_at": _now(),
                "domains": {}, "acquired_domains": [], "placements": {},
                "suppressions": {}, "runs": 0, "center_domain": center_domain}


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
            if tranco is not None:
                e.setdefault("authority", {})["tranco_global_rank"] = tranco
            e["acquired"] = d in acquired
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
                "acquired": d in acquired,
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


def store_stats(store):
    doms = store.get("domains", {})
    total = len(doms)
    acquired = sum(1 for d in doms.values() if d.get("acquired"))
    valid = sum(1 for d in doms.values() if d.get("valid"))
    # Competitor domains are deliberately excluded, so they are neither
    # "acquired" nor a real "gap to pursue".
    competitors = sum(1 for d in doms.values() if d.get("is_competitor"))
    gap = sum(1 for d in doms.values()
              if not d.get("acquired") and not d.get("is_competitor"))
    gap_valid = sum(1 for d in doms.values()
                    if (not d.get("acquired")) and (not d.get("is_competitor")) and d.get("valid"))
    reciprocal = sum(1 for d in doms.values() if d.get("type_key") == "reciprocal")
    reciprocal_ratio = round(reciprocal / total, 4) if total else 0.0
    by_type = {}
    for d in doms.values():
        tk = d.get("type_key", "unknown")
        bt = by_type.setdefault(tk, {"discovered": 0, "acquired": 0, "gap": 0})
        bt["discovered"] += 1
        if d.get("acquired"):
            bt["acquired"] += 1
        elif d.get("is_competitor"):
            pass  # excluded: neither acquired nor gap
        else:
            bt["gap"] += 1
    return {
        "total_discovered": total,
        "acquired": acquired,
        "valid": valid,
        "gap": gap,
        "gap_valid": gap_valid,
        "reciprocal": reciprocal,
        "reciprocal_ratio": reciprocal_ratio,
        "reciprocal_ratio_warn": reciprocal_ratio > 0.30,
        "by_type": by_type,
        "runs": store.get("runs", 0),
        "updated_at": store.get("updated_at"),
        "acquired_domains": store.get("acquired_domains", []),
        "placements": placement_stats(store),
    }


def domain_list(store):
    """Return pool domains as a flat list (sorted by priority desc)."""
    out = []
    idx = placement_index(store)
    sup = store.get("suppressions", {})
    for d, e in store.get("domains", {}).items():
        best = idx.get(_norm_target(d))
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
            "acquired": e.get("acquired", False),
            "is_gap": not e.get("acquired", False),
            "first_seen": e.get("first_seen"),
            "last_seen": e.get("last_seen"),
            "times_discovered": e.get("times_discovered", 1),
            "placement_state": best.get("state") if best else None,
            "placement_id": best.get("id") if best else None,
            "suppressed": _norm_target(d) in sup,
        })
    out.sort(key=lambda x: (-(x.get("priority") or 0), not x.get("valid")))
    return out


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
def _profile_path(center_domain):
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
      1. data/profile-<domain>.json      - operator edits (saved)
      2. profiles.json -> profiles[domain] - shipped default
      3. empty profile                     - unknown domain

    Returns {keywords:[], competitors:[], note:"", source:"saved|default|none"}.
    """
    center_domain = (center_domain or "").strip().lower()
    if not center_domain:
        return {"keywords": [], "competitors": [], "note": "", "note_en": "", "source": "none"}

    p = _profile_path(center_domain)
    if p and os.path.isfile(p):
        d = load_json_file(p, None)
        if isinstance(d, dict):
            return {"keywords": _as_list(d.get("keywords")),
                    "competitors": _as_list(d.get("competitors")),
                    "note": d.get("note") or "",
                    "note_en": d.get("note_en") or "",
                    "source": "saved"}

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
    """Persist an operator-edited profile for a center domain."""
    center_domain = (center_domain or "").strip().lower()
    if not center_domain:
        raise ValueError("center_domain is required")
    p = _profile_path(center_domain)
    if not p:
        raise ValueError("invalid center_domain")
    os.makedirs(DATA_DIR, exist_ok=True)
    cfg = {
        "version": "1.0.0",
        "center_domain": center_domain,
        "keywords": _as_list(keywords),
        "competitors": _as_list(competitors),
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


def placement_stats(store):
    by_state = {}
    for p in store.get("placements", {}).values():
        s = p.get("state", "unknown")
        by_state[s] = by_state.get(s, 0) + 1
    return {"total": len(store.get("placements", {})), "by_state": by_state,
            "live": by_state.get("live", 0),
            "in_progress": sum(by_state.get(s, 0) for s in ACTIVE_STATES),
            "suppressed": len(store.get("suppressions", {})),
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
