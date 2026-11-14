#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backlink Prospector - local HTTP service (Python standard library only).

Aligned with seo-page-snapshot's service contract style:
  - stdlib http.server, no third-party deps
  - JSON envelope {ok, ...}, bilingual, free-provider-only
  - never exposes a public interface by default (loopback bind)

Endpoints (all JSON except GET /):
    GET  /                       frontend page (assets/index.html)
    GET  /help                   standalone operator help page (assets/help.html, ?lang=en|zh)
    GET  /api/health            service metadata
    POST /api/analyze           body={domain,keywords,competitors,existing,use_bing,use_tranco,persist}
    POST /api/analyze/csv       same body -> CSV attachment
    GET  /api/providers         free provider configuration (no secrets)
    GET  /api/channels          discovery channel list (rotated live search)
    POST /api/channels          body={id, enabled} toggle a discovery channel
    GET  /api/profiles          body/query={domain} keyword+competitor profile
    POST /api/profiles          body={center_domain, keywords, competitors} save profile
    GET  /api/tips              bilingual type / weight / reciprocal-linking tips
    GET  /api/store             persistent backlink pool + stats (discovered / acquired / gap)
    GET  /api/domains           every center domain this workspace knows (picker source)
    GET  /api/store/csv         pool exported as CSV attachment
    POST /api/store/sync-existing  body={domains|existing} mark real backlinks acquired
    POST /api/store/unmark-existing body={domains} revert domains to gap (unmark acquired)
    GET  /api/placements       delivery ledger (query: domain) + stats
    GET  /api/queue            today's frozen batch + quota accounting
                               query: domain, date=YYYY-MM-DD (operator's local day),
                               quota (batch override; the hard gate is the configured
                               daily_quota), refill=1 to top the batch back up
    GET  /api/whitelist        domains excluded from every backlink number
    POST /api/whitelist        body={center_domain,domains,action:add|remove,note}
    POST /api/settings         body={center_domain,daily_quota} hard daily ceiling
    GET  /api/placements/csv   ledger exported as CSV attachment (evidence included)
    POST /api/placements/claim      body={target_domain,target_url,placement_type,own_url,batch_id}
    POST /api/placements/claim-batch body={center_domain,items:[{target_domain,target_url,placement_type,own_url,batch_id}]} claim many slots
    POST /api/placements/transition body={id,state,...} advance a slot; live needs evidence
    POST /api/placements/suppress   body={target_domain|id,reason} permanently exclude
    GET  /api/schedule         periodic-query scheduler state (config / status / runs)
    POST /api/schedule         body={enabled,interval_hours,profiles[]} save schedule
    POST /api/schedule/run     trigger an immediate run of all profiles

Usage:
    python3 server.py --port 8787
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
PROVIDERS_PATH = os.path.join(HERE, "providers.json")
TIPS_PATH = os.path.join(HERE, "tips.json")
HOST, PORT = "127.0.0.1", 8787

sys.path.insert(0, HERE)
import analyze as an  # noqa: E402
import store as st  # noqa: E402
import scheduler as sch  # noqa: E402

# Allow common whitespace (tab / LF / CR) in multi-line textarea fields;
# only block genuinely unsafe control characters.
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def utc_stamp():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_text(value, limit=300):
    v = (value or "").strip()
    if not v or len(v) > limit or CONTROL_RE.search(v):
        raise ValueError("field is empty, too long, or contains control characters")
    return v


# CSV column order
CSV_COLS = [
    ("url", "url"), ("domain", "domain"), ("type_key", "type_key"),
    ("type_label_zh", "type_label_zh"), ("type_label_en", "type_label_en"),
    ("authority_tier", "authority_tier"), ("relevance", "relevance"),
    ("authority_score", "authority_score"), ("obtainability", "obtainability"),
    ("priority", "priority"), ("valid", "valid"), ("http_status", "http_status"),
    ("is_gap", "is_gap"), ("is_competitor", "is_competitor"),
    ("already_have", "already_have"),
    ("tranco_global_rank", "authority.tranco_global_rank"),
    ("source", "source"), ("note", "note"), ("note_en", "note_en"),
]


def build_csv(result):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[0] for c in CSV_COLS])
    for p in result.get("prospects", []):
        row = []
        for _, path in CSV_COLS:
            if "." in path:
                a, b = path.split(".", 1)
                row.append(p.get(a, {}).get(b, ""))
            else:
                row.append(p.get(path, ""))
        w.writerow(row)
    return "﻿" + buf.getvalue()  # BOM for Excel


# CSV column order for the persistent pool
STORE_CSV_COLS = [
    "domain", "url", "type_key", "type_label_zh", "authority_tier",
    "tranco_global_rank", "priority", "valid", "http_status",
    "acquired", "is_gap", "whitelisted", "times_discovered", "first_seen", "last_seen",
]


def build_store_csv(domains):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(STORE_CSV_COLS)
    for d in domains:
        w.writerow([d.get(c, "") for c in STORE_CSV_COLS])
    return "﻿" + buf.getvalue()  # BOM for Excel


# Placement ledger CSV: evidence-bearing delivery records, separate from the
# candidate list above so the two layers can never be confused in a handoff.
PLACEMENT_CSV_COLS = [
    "id", "target_domain", "target_url", "placement_type", "own_url", "state",
    "batch_id", "created_at", "claimed_at", "submitted_at", "live_at",
    "lost_at", "rejected_at", "error_at", "cooldown_until", "failure_reason",
    "verify_method", "landing_url", "observed_href", "rel", "anchor_text",
    "verified_at", "note",
]

_VERIFY_FIELDS = ("verify_method", "landing_url", "observed_href", "rel",
                  "anchor_text", "verified_at")


def build_placements_csv(store):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(PLACEMENT_CSV_COLS)
    for p in st.placement_list(store):
        row = dict(p)
        row.update({k: (p.get("verify") or {}).get(k, "") for k in _VERIFY_FIELDS})
        w.writerow([row.get(c, "") for c in PLACEMENT_CSV_COLS])
    return "﻿" + buf.getvalue()  # BOM for Excel


def run_analysis(params, center_domain=None):
    """Execute an analysis and (by default) persist into the backlink pool.

    Shared by the interactive /api/analyze endpoint and the periodic scheduler,
    so a scheduled run and a manual run have identical side effects.

    Deduplication: "already have" now comes from the placement ledger (state
    == live, with evidence), operator-marked acquisitions and the explicit
    existing-backlink import. Merely having SEEN a domain in the pool is no
    longer treated as owning a backlink there. The legacy behaviour that fed
    the whole pool into `existing` is still available behind
    use_pool_as_existing=1, but defaults to off.

    Storage isolation: uses domain-specific pool when center_domain is provided.

    IMPORTANT: the scheduler calls run_fn(params) without a positional
    center_domain, so the domain MUST also be resolved from params here.
    Otherwise every scheduled run writes into the legacy shared pool and
    mixes niches together (balance-bike entries landing next to sound ones).
    """
    if not center_domain:
        center_domain = (params.get("center_domain") or "").strip().lower()
    pool = st.load_store(center_domain)
    legacy = str(params.get("use_pool_as_existing", "0")).lower() in ("1", "true", "yes", "on")
    owned = sorted(st.owned_domains(pool))
    seen = list(pool.get("domains", {}).keys()) if legacy else []
    params["existing"] = "\n".join(
        part for part in ("\n".join(owned), "\n".join(seen), params.get("existing") or "") if part)
    # Keyword fallback: an empty keyword box falls back to the center domain's
    # own profile, so a domain switch can never run with the previous niche.
    if not (params.get("keywords") or "").strip() and center_domain:
        prof = st.load_profile(center_domain)
        if prof.get("keywords"):
            params["keywords"] = ", ".join(prof["keywords"])
    result = an.analyze(params)
    # Report the real existing-library coverage in the result envelope.
    result["existing_library"] = {
        "size": len(owned) + len(seen),
        "acquired": len(pool.get("acquired_domains", [])),
        "live_placements": st.placement_stats(pool)["live"],
        "seen": len(pool.get("domains", {})),
        "pool_used_as_existing": legacy,
        "matched_domains": sum(1 for p in result.get("prospects", []) if p.get("already_have")),
    }
    if str(params.get("persist", "1")).lower() in ("1", "true", "yes", "on"):
        merged = st.merge_result(pool, result)
        st.save_store(pool, center_domain)
        result["pool_merged"] = merged
        result["pool_stats"] = st.store_stats(pool)
    return result


# Start the periodic-query scheduler (daemon thread). It loads data/schedule.json
# and runs any enabled profiles on the configured interval, merging into the pool.
SCHED = sch.Scheduler(run_analysis)


class Handler(BaseHTTPRequestHandler):
    server_version = "BacklinkProspector/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False))

    def _error(self, status, message):
        self._json(status, {"ok": False, "error": message})

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                idx = os.path.join(ASSETS, "index.html")
                if not os.path.isfile(idx):
                    return self._error(500, "frontend asset missing")
                # Inject a cache-busting version into the HTML so browsers always
                # fetch the latest inline script (avoids stale cached pages).
                html = open(idx, encoding="utf-8").read()
                ver = str(int(os.path.getmtime(idx)))
                html = html.replace("<head>", '<head><meta name="build" content="%s">' % ver, 1)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if path in ("/help", "/help.html"):
                # Standalone operator help page (bilingual, ?lang=en|zh). Served
                # as a real document so it can be linked, bookmarked and read
                # without the SPA's runtime.
                hp = os.path.join(ASSETS, "help.html")
                if not os.path.isfile(hp):
                    return self._error(500, "help asset missing")
                out = open(hp, encoding="utf-8").read()
                ver = str(int(os.path.getmtime(hp)))
                out = out.replace("<head>", '<head><meta name="build" content="%s">' % ver, 1)
                return self._send(200, out.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if path == "/api/health":
                return self._json(200, {"ok": True, "skill": an.SKILL,
                                        "schema_version": an.SCHEMA_VERSION,
                                        "endpoints": ["/api/health", "/api/analyze",
                                                      "/api/analyze/csv", "/api/providers",
                                                      "/api/tips", "/api/store",
                                                      "/api/domains",
                                                      "/api/queue",
                                                      "/api/whitelist",
                                                      "/api/settings",
                                                      "/api/store/csv",
                                                      "/api/store/sync-existing",
                                                      "/api/placements/claim-batch",
                                                      "/api/placements/import",
                                                      "/api/profiles",
                                                      "/api/schedule",
                                                      "/api/schedule/run",
                                                      "/help"]})
            if path == "/api/providers":
                try:
                    with open(PROVIDERS_PATH, encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                return self._json(200, {"ok": True, "config_path": PROVIDERS_PATH,
                                        "providers": cfg.get("providers", [])})
            if path == "/api/channels":
                # Support domain query parameter for domain-specific channels
                center_domain = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("domain", [None])[0]
                channels = st.load_domain_channels(center_domain)
                # Load rotation config from global channels.json
                try:
                    with open(an.CHANNELS_PATH, encoding="utf-8") as f:
                        global_cfg = json.load(f)
                    rotation = global_cfg.get("rotation", {})
                except Exception:
                    rotation = {}
                return self._json(200, {"ok": True,
                                        "config_path": an.CHANNELS_PATH,
                                        "rotation": rotation,
                                        "channels": channels,
                                        "center_domain": center_domain})
            if path == "/api/tips":
                try:
                    with open(TIPS_PATH, encoding="utf-8") as f:
                        tips = json.load(f)
                except Exception as exc:
                    return self._error(500, "tips.json missing: %s" % exc)
                return self._json(200, {"ok": True, "tips": tips})
            if path == "/api/domains":
                # Everything this workspace knows, so the center-domain picker
                # offers real choices instead of relying on free-text memory.
                return self._json(200, {"ok": True, "domains": st.known_domains()})
            if path == "/api/queue":
                # Today's frozen batch + quota accounting. `date` comes from the
                # client so "today" means the operator's day, not the UTC day of
                # a machine in sin.
                qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                center_domain = qs.get("domain", [None])[0]
                date = qs.get("date", [None])[0]
                quota = qs.get("quota", [None])[0]
                refill = str(qs.get("refill", ["0"])[0]).lower() in ("1", "true", "yes")
                pool = st.load_store(center_domain)
                return self._json(200, {"ok": True,
                                        "queue": st.daily_queue(pool, center_domain, date=date,
                                                                quota=quota, refill=refill),
                                        "center_domain": center_domain})
            if path == "/api/whitelist":
                center_domain = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("domain", [None])[0]
                pool = st.load_store(center_domain)
                return self._json(200, {"ok": True,
                                        "whitelist": st.whitelist_rows(pool),
                                        "count": len(st.whitelist_map(pool)),
                                        "center_domain": center_domain})
            if path == "/api/store":
                # Support domain query parameter for multi-domain isolation
                qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                center_domain = qs.get("domain", [None])[0]
                date = qs.get("date", [None])[0]
                pool = st.load_store(center_domain)
                return self._json(200, {"ok": True,
                                        "stats": st.store_stats(pool),
                                        "domains": st.domain_list(pool),
                                        "whitelist": st.whitelist_rows(pool),
                                        "settings": {"daily_quota": st.effective_quota(pool)},
                                        "queue": st.daily_queue(pool, center_domain,
                                                                date=date, with_items=False),
                                        "center_domain": center_domain})
            if path == "/api/store/csv":
                # Support domain query parameter for multi-domain isolation
                center_domain = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("domain", [None])[0]
                pool = st.load_store(center_domain)
                csv_text = build_store_csv(st.domain_list(pool))
                domain_part = center_domain or "pool"
                fname = "backlink-pool-%s-%s.csv" % (domain_part.replace(".", "_"), utc_stamp())
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % fname)
                self.send_header("Content-Length", str(len(csv_text.encode("utf-8"))))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(csv_text.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if path == "/api/placements":
                center_domain = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("domain", [None])[0]
                pool = st.load_store(center_domain)
                return self._json(200, {"ok": True,
                                        "placements": st.placement_list(pool),
                                        "stats": st.placement_stats(pool),
                                        "center_domain": center_domain})
            if path == "/api/placements/csv":
                center_domain = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("domain", [None])[0]
                pool = st.load_store(center_domain)
                csv_text = build_placements_csv(pool)
                fname = "backlink-placements-%s-%s.csv" % (
                    (center_domain or "pool").replace(".", "_"), utc_stamp())
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % fname)
                self.send_header("Content-Length", str(len(csv_text.encode("utf-8"))))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(csv_text.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if path == "/api/schedule":
                return self._json(200, {"ok": True, "snapshot": SCHED.snapshot()})
            if path == "/api/profiles":
                center_domain = urllib.parse.parse_qs(parsed.query).get("domain", [None])[0]
                if center_domain:
                    prof = st.load_profile(center_domain)
                    prof["domain"] = center_domain
                    return self._json(200, {"ok": True, "profile": prof,
                                            "center_domain": center_domain})
                return self._json(200, {"ok": True, "profiles": st.list_profiles()})
            return self._error(404, "unknown path: %s" % path)
        except Exception as exc:  # noqa: BLE001
            return self._error(500, "%s: %s" % (type(exc).__name__, str(exc)[:300]))

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path not in ("/api/analyze", "/api/analyze/csv", "/api/store/sync-existing",
                        "/api/store/unmark-existing", "/api/channels",
                        "/api/profiles", "/api/schedule", "/api/schedule/run",
                        "/api/placements/claim", "/api/placements/claim-batch",
                        "/api/placements/import",
                        "/api/placements/transition",
                        "/api/placements/suppress",
                        "/api/whitelist", "/api/settings"):
            return self._error(404, "unknown path")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(length, 256_000)) if length else b"{}"
            params = json.loads(raw.decode("utf-8", "replace") or "{}")
            if not isinstance(params, dict):
                raise ValueError("JSON body must be an object")

            if path == "/api/store/sync-existing":
                text = (params.get("domains") or params.get("existing") or "")
                if not isinstance(text, str):
                    raise ValueError("domains field must be a string")
                safe_text(text, 8000)
                center_domain = params.get("center_domain")
                pool = st.load_store(center_domain)
                added = st.sync_existing(pool, re.split(r"[,\n]", text))
                st.save_store(pool, center_domain)
                return self._json(200, {"ok": True, "added": added,
                                        "stats": st.store_stats(pool),
                                        "center_domain": center_domain})

            if path == "/api/store/unmark-existing":
                text = params.get("domains")
                if not isinstance(text, str):
                    raise ValueError("domains field must be a string")
                safe_text(text, 8000)
                center_domain = params.get("center_domain")
                pool = st.load_store(center_domain)
                removed = st.unmark_existing(pool, re.split(r"[,\n]", text))
                st.save_store(pool, center_domain)
                # A live placement (delivered or imported) outranks a manual mark:
                # reporting the removal as done while the domain stays owned would
                # be a lie, so name the domains that need the ledger instead.
                live = {st._norm_target(x) for x in st.live_domains(pool) if x}
                still_live = sorted({st._bare_domain(d) for d in re.split(r"[,\n]", text)
                                     if st._bare_domain(d) in live})
                return self._json(200, {"ok": True, "removed": removed,
                                        "still_live": still_live,
                                        "stats": st.store_stats(pool),
                                        "center_domain": center_domain})

            if path == "/api/whitelist":
                center_domain = (params.get("center_domain") or params.get("domain") or "").strip().lower() or None
                action = str(params.get("action") or "add").strip().lower()
                raw = params.get("domains")
                if raw is None:
                    raw = params.get("domain")
                if isinstance(raw, str):
                    domains = [x for x in re.split(r"[,\s\n]+", raw) if x]
                elif isinstance(raw, list):
                    domains = [str(x) for x in raw if isinstance(x, (str, int))]
                else:
                    domains = []
                if not domains:
                    raise ValueError("domains (string or array) is required")
                if len(domains) > 200:
                    raise ValueError("too many domains (max 200)")
                for d in domains:
                    safe_text(d, 300)
                note = str(params.get("note") or "")[:200]
                pool = st.load_store(center_domain)
                if action == "remove":
                    changed = st.remove_whitelist(pool, domains)
                elif action == "add":
                    changed = st.add_whitelist(pool, domains, note=note)
                else:
                    raise ValueError("action must be 'add' or 'remove'")
                st.save_store(pool, center_domain)
                return self._json(200, {"ok": True, "action": action,
                                        "changed": changed,
                                        "whitelist": st.whitelist_rows(pool),
                                        "count": len(st.whitelist_map(pool)),
                                        "stats": st.store_stats(pool),
                                        "center_domain": center_domain})

            if path == "/api/settings":
                center_domain = (params.get("center_domain") or params.get("domain") or "").strip().lower() or None
                pool = st.load_store(center_domain)
                if "daily_quota" in params:
                    quota, err = st.set_daily_quota(pool, params.get("daily_quota"))
                    if err:
                        return self._error(400, err)
                    st.save_store(pool, center_domain)
                else:
                    quota = st.effective_quota(pool)
                return self._json(200, {"ok": True,
                                        "settings": {"daily_quota": quota},
                                        "quota": st.quota_state(pool),
                                        "center_domain": center_domain})

            if path in ("/api/placements/claim", "/api/placements/transition",
                        "/api/placements/suppress"):
                center_domain = (params.get("center_domain") or params.get("domain") or "").strip().lower()
                for f in ("target_domain", "target_url", "placement_type", "batch_id",
                          "own_url", "landing_url", "verify_method", "observed_href",
                          "rel", "anchor_text", "failure_reason", "note", "reason",
                          "id", "state"):
                    if params.get(f) not in (None, ""):
                        safe_text(str(params[f]), 800)
                pool = st.load_store(center_domain or None)
                if path.endswith("/claim"):
                    out, reason = st.claim_placement(pool, params)
                elif path.endswith("/transition"):
                    out, reason = st.transition_placement(pool, params)
                else:
                    out, reason = st.suppress_placement(pool, params)
                if reason:
                    return self._error(409, reason)
                st.save_store(pool, center_domain or None)
                return self._json(200, {"ok": True, "placement": out,
                                        "stats": st.placement_stats(pool),
                                        "center_domain": center_domain})

            if path == "/api/placements/claim-batch":
                center_domain = (params.get("center_domain") or params.get("domain") or "").strip().lower()
                items = params.get("items")
                if not isinstance(items, list) or not items:
                    raise ValueError("items must be a non-empty array")
                if len(items) > 500:
                    raise ValueError("too many items (max 500)")
                for it in items:
                    if isinstance(it, dict):
                        for f in ("target_domain", "target_url", "placement_type",
                                  "batch_id", "own_url", "note"):
                            if it.get(f) not in (None, ""):
                                safe_text(str(it[f]), 800)
                pool = st.load_store(center_domain or None)
                out = st.claim_placements_batch(pool, items)
                st.save_store(pool, center_domain or None)
                return self._json(200, {"ok": True, "claimed": out["claimed"],
                                        "blocked": out["blocked"],
                                        "quota_blocked": out.get("quota_blocked", 0),
                                        "quota": out.get("quota"),
                                        "remaining": out.get("remaining"),
                                        "results": out["results"],
                                        "stats": st.placement_stats(pool),
                                        "center_domain": center_domain})

            if path == "/api/placements/import":
                # Turn a GSC / Ahrefs / Common Crawl export into live ledger rows
                # (and therefore into "already owned"). dry_run previews the exact
                # gap delta without writing; remove undoes a bad paste.
                center_domain = (params.get("center_domain") or params.get("domain") or "").strip().lower() or None
                text = params.get("text")
                if text is None:
                    text = params.get("links")
                if not isinstance(text, str):
                    raise ValueError("text must be a string (paste one URL per line or a CSV export)")
                # 240KB ~= 2000 rows; the request body itself is capped at 256KB.
                text = safe_text(text, 240000)
                source = params.get("source") or "operator-export"
                if not isinstance(source, str):
                    raise ValueError("source must be a string")
                own_url = params.get("own_url") or ""
                if not isinstance(own_url, str):
                    raise ValueError("own_url must be a string")
                pool = st.load_store(center_domain)
                report = st.import_placements(
                    pool, text, source=source,
                    dry_run=bool(params.get("dry_run")),
                    remove=bool(params.get("remove")),
                    own_url=own_url)
                if not report["dry_run"]:
                    st.save_store(pool, center_domain)
                report["placements"] = st.placement_list(pool)
                report["stats"] = st.store_stats(pool)
                report["center_domain"] = center_domain
                return self._json(200, report)

            if path == "/api/channels":
                # POST to toggle a channel or save domain-specific config
                center_domain = params.get("center_domain")
                
                # If saving full config for a domain
                if params.get("channels") and center_domain:
                    cfg = st.save_domain_channels(params["channels"], center_domain)
                    return self._json(200, {"ok": True,
                                            "channels": cfg.get("channels", []),
                                            "center_domain": center_domain})
                
                # Legacy: toggle single channel in global config
                cid = params.get("id")
                if not cid:
                    raise ValueError("channel id required")
                with open(an.CHANNELS_PATH, encoding="utf-8") as f:
                    cfg = json.load(f)
                hit = False
                for ch in cfg.get("channels", []):
                    if ch.get("id") == cid:
                        ch["enabled"] = bool(params.get("enabled", True))
                        hit = True
                        break
                if not hit:
                    raise ValueError("unknown channel id: %s" % cid)
                
                # If center_domain is provided, save to domain-specific config
                if center_domain:
                    # Load or create domain channels
                    domain_channels = st.load_domain_channels(center_domain)
                    if not domain_channels:
                        # Use global channels as base
                        with open(an.CHANNELS_PATH, encoding="utf-8") as f:
                            global_cfg = json.load(f)
                        domain_channels = global_cfg.get("channels", [])
                    
                    # Update the specific channel
                    for ch in domain_channels:
                        if ch.get("id") == cid:
                            ch["enabled"] = bool(params.get("enabled", True))
                            break
                    
                    cfg = st.save_domain_channels(domain_channels, center_domain)
                    return self._json(200, {"ok": True,
                                            "channels": cfg.get("channels", []),
                                            "center_domain": center_domain})
                else:
                    # Legacy: save to global config
                    tmp = an.CHANNELS_PATH + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, ensure_ascii=False, indent=2)
                    os.replace(tmp, an.CHANNELS_PATH)
                    return self._json(200, {"ok": True, "channels": cfg.get("channels", [])})

            if path == "/api/profiles":
                center_domain = (params.get("center_domain") or "").strip().lower()
                if not center_domain:
                    raise ValueError("center_domain is required")
                if params.get("keywords") is None and params.get("competitors") is None:
                    raise ValueError("keywords or competitors required")
                cfg = st.save_profile(center_domain,
                                      params.get("keywords") or [],
                                      params.get("competitors") or [],
                                      params.get("note"))
                # Re-read so "source" tells the truth: an all-empty payload is a
                # no-op, and the domain keeps resolving to its shipped default.
                prof = st.load_profile(center_domain)
                prof["domain"] = center_domain
                if cfg.get("skipped"):
                    prof["skipped"] = cfg["skipped"]
                return self._json(200, {"ok": True, "profile": prof,
                                        "center_domain": center_domain})

            if path == "/api/schedule":
                cfg = SCHED.save_config(params)
                return self._json(200, {"ok": True, "config": cfg, "status": SCHED.status})

            if path == "/api/schedule/run":
                out = SCHED.run_now()
                return self._json(200, {"ok": out.get("ok", False),
                                        "last_run": SCHED.config.get("last_run"),
                                        "status": SCHED.status,
                                        "runs": SCHED.runs[:20],
                                        "error": out.get("error")})

            # light validation on the free-text inputs
            if params.get("domain"):
                safe_text(params["domain"], 300)
            if params.get("keywords"):
                safe_text(params["keywords"], 2000)
            if params.get("competitors"):
                safe_text(params["competitors"], 4000)
            if params.get("existing"):
                safe_text(params["existing"], 4000)

            center_domain = (params.get("center_domain") or params.get("domain") or "").strip().lower()
            result = run_analysis(params, center_domain or None)

            if path == "/api/analyze/csv":
                csv_text = build_csv(result)
                fname = "backlink-prospects-%s-%s.csv" % (
                    (result["target"].get("registrable_domain") or "domain"), utc_stamp())
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % fname)
                self.send_header("Content-Length", str(len(csv_text.encode("utf-8"))))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(csv_text.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            return self._json(200, {"ok": True, "result": result})
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._error(500, "%s: %s" % (type(exc).__name__, str(exc)[:300]))


def main():
    global HOST, PORT
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    HOST, PORT = args.host, args.port
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: binding to a non-loopback interface exposes a URL-fetching endpoint.",
              file=sys.stderr)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("backlink-prospector service: http://%s:%d" % (HOST, PORT), file=sys.stderr)
    print("POST /api/analyze  body={domain,keywords,competitors,existing}", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
