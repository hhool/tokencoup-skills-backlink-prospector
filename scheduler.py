#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backlink Prospector - periodic query scheduler (Python standard library only).

A lightweight, dependency-free background scheduler. It runs analysis *profiles*
on a fixed interval and merges every result into the persistent backlink pool,
so the operator can keep expanding the address list over time without manual runs.

Design notes:
  - Runs as a daemon thread inside the HTTP server process. If the server stops,
    scheduled runs stop too (this is a single-host dev tool, not a distributed job
    queue).
  - Config lives in data/schedule.json: {enabled, interval_hours, profiles[]}.
  - Run history lives in data/schedule_runs.json (last 50 runs).
  - `run_fn(profile_params) -> result` is injected by server.py so the scheduler
    never imports the analysis engine directly (keeps the dependency one-way).
"""
import datetime as dt
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SCHED_PATH = os.path.join(DATA_DIR, "schedule.json")
RUNS_PATH = os.path.join(DATA_DIR, "schedule_runs.json")

DEFAULT_CONFIG = {"enabled": False, "interval_hours": 24, "profiles": [],
                  # Probe due `live` rows after each profile run: a delivered link
                  # is only "valid" while the page still carries it.
                  "recheck": True, "recheck_limit": 20,
                  # Restock an empty shelf between runs. The daily batch is useless
                  # if the pool behind it ran dry, and waiting for the next interval
                  # can mean a whole day of an empty queue.
                  "auto_refill": True}
MIN_INTERVAL_H = 0.05   # ~3 minutes, allows quick testing
MAX_INTERVAL_H = 8760   # 1 year
TICK_SECONDS = 30
# Tests (and one-off tooling) import server.py, which builds a Scheduler at module
# level. Without this escape hatch that import would start running real analyses
# against real data in the test process.
NO_AUTOSTART = str(os.environ.get("BP_NO_SCHEDULER", "")).strip().lower() in ("1", "true", "yes")


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Scheduler:
    def __init__(self, run_fn, recheck_fn=None, refill_fn=None, refill_check_fn=None,
                 autostart=None):
        self.run_fn = run_fn
        # Injected by server.py for the same reason as run_fn: the scheduler stays
        # free of network policy, it only decides when to call.
        self.recheck_fn = recheck_fn
        self.refill_fn = refill_fn
        # Answers "is the shelf low enough, and may we go shopping yet?" — the
        # cooldown lives in the store, so a restart cannot reset it.
        self.refill_check_fn = refill_check_fn
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.config = self._load_config()
        self.runs = self._load_runs()
        self.status = {"running": False, "last_error": None, "next_run": None,
                       "started_at": _now()}
        self._recompute_next()
        # Auto-start the loop thread (daemon: dies with the process).
        start_now = (not NO_AUTOSTART) if autostart is None else bool(autostart)
        if start_now:
            self.start()

    # ---------- persistence ----------
    def _load_config(self):
        try:
            with open(SCHED_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = dict(DEFAULT_CONFIG)
        cfg.setdefault("enabled", False)
        cfg.setdefault("interval_hours", 24)
        cfg.setdefault("profiles", [])
        cfg.setdefault("last_run", None)
        return cfg

    def _load_runs(self):
        try:
            with open(RUNS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_config(self):
        _atomic_write(SCHED_PATH, self.config)

    def _save_runs(self):
        _atomic_write(RUNS_PATH, self.runs[:50])

    # ---------- public API ----------
    def save_config(self, new_cfg):
        """Merge a partial config (enabled / interval_hours / profiles)."""
        if "enabled" in new_cfg:
            self.config["enabled"] = bool(new_cfg["enabled"])
        if "interval_hours" in new_cfg:
            try:
                ih = float(new_cfg["interval_hours"])
            except (TypeError, ValueError):
                ih = 24
            self.config["interval_hours"] = max(MIN_INTERVAL_H, min(MAX_INTERVAL_H, ih))
        if "auto_refill" in new_cfg:
            self.config["auto_refill"] = bool(new_cfg["auto_refill"])
        if "recheck" in new_cfg:
            self.config["recheck"] = bool(new_cfg["recheck"])
        if "recheck_limit" in new_cfg:
            try:
                rl = int(new_cfg["recheck_limit"])
            except (TypeError, ValueError):
                rl = 20
            self.config["recheck_limit"] = max(1, min(100, rl))
        if "profiles" in new_cfg and isinstance(new_cfg["profiles"], list):
            clean = []
            for p in new_cfg["profiles"]:
                if isinstance(p, dict) and p.get("domain"):
                    clean.append({
                        "name": str(p.get("name") or p["domain"])[:80],
                        "domain": str(p["domain"])[:300],
                        "keywords": str(p.get("keywords") or "")[:2000],
                        "competitors": str(p.get("competitors") or "")[:4000],
                        "existing": str(p.get("existing") or "")[:4000],
                        "use_bing": bool(p.get("use_bing", False)),
                        "use_tranco": bool(p.get("use_tranco", True)),
                    })
            self.config["profiles"] = clean
        self._save_config()
        self._recompute_next()
        return self.config

    def run_now(self):
        """Trigger an immediate execution of all profiles (ignores the timer)."""
        self._execute_all()
        return {"ok": True, "last_run": self.config.get("last_run"),
                "status": self.status, "runs": self.runs[:20]}

    def snapshot(self):
        return {"config": self.config, "status": self.status, "runs": self.runs[:20]}

    # ---------- internals ----------
    def _recompute_next(self):
        if not (self.config.get("enabled") and self.config.get("profiles")):
            self.status["next_run"] = None
            return
        last = self.config.get("last_run")
        interval = self.config["interval_hours"] * 3600
        if not last:
            self.status["next_run"] = _now()  # due now, will fire on next tick
            return
        try:
            lt = dt.datetime.fromisoformat(last).timestamp()
            nx = lt + interval
            self.status["next_run"] = dt.datetime.fromtimestamp(nx).isoformat()
        except Exception:
            self.status["next_run"] = None

    def _is_due(self):
        last = self.config.get("last_run")
        interval = self.config["interval_hours"] * 3600
        if not last:
            return True
        try:
            lt = dt.datetime.fromisoformat(last).timestamp()
        except Exception:
            return True
        return (time.time() - lt) >= interval

    def _profile_to_params(self, prof):
        return {
            "domain": prof.get("domain", ""),
            "center_domain": (prof.get("domain") or "").strip().lower(),
            "keywords": prof.get("keywords", ""),
            "competitors": prof.get("competitors", ""),
            "existing": prof.get("existing", ""),
            "use_bing": "1" if prof.get("use_bing") else "0",
            "use_tranco": "1" if prof.get("use_tranco", True) else "0",
            "persist": "1",  # scheduled runs feed the CANDIDATE pool only
            # Explicit: discovery must never be mistaken for "already have".
            # The ledger (state == live), not the pool, decides gap membership.
            "use_pool_as_existing": "0",
        }

    def _execute_all(self):
        with self.lock:
            if self.status["running"]:
                return
            self.status["running"] = True
        try:
            for prof in list(self.config.get("profiles", [])):
                params = self._profile_to_params(prof)
                rec = {"ts": _now(), "profile": prof.get("name", ""),
                       "domain": prof.get("domain", ""),
                       "ok": False, "candidates": None,
                       "pool_total": None, "pool_merged": None, "error": None}
                try:
                    res = self.run_fn(params)
                    r = res.get("result", res)
                    rec["ok"] = True
                    rec["candidates"] = (r.get("totals") or {}).get("candidates")
                    rec["pool_merged"] = r.get("pool_merged")
                    rec["pool_total"] = (r.get("pool_stats") or {}).get("total_discovered")
                    rec["error"] = None
                    if self.recheck_fn and self.config.get("recheck", True):
                        try:
                            rk = self.recheck_fn(params.get("center_domain") or "",
                                                 limit=int(self.config.get("recheck_limit") or 20))
                            rec["recheck"] = {k: rk.get(k) for k in
                                              ("checked", "alive", "gone", "unknown", "remaining_due")}
                            if rk.get("gone"):
                                rec["recheck_lost"] = [x.get("target_domain")
                                                       for x in (rk.get("lost") or [])][:10]
                        except Exception as exc:  # noqa: BLE001 — never fail the run
                            rec["recheck_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
                    self.status["last_error"] = rec["error"]
                self.runs.insert(0, rec)
                self.runs = self.runs[:50]
                self._save_runs()
            self.config["last_run"] = _now()
            self._save_config()
        finally:
            self.status["running"] = False
        self._recompute_next()

    def _maybe_refill(self):
        """Restock one profile when its pool is below the threshold.

        Runs at most one refill per tick and only when nothing else is running:
        two concurrent analyses would double the network cost and fight over the
        same store file.
        """
        if not (self.config.get("enabled") and self.config.get("profiles")):
            return None
        if not self.config.get("auto_refill", True):
            return None
        if not (self.refill_fn and self.refill_check_fn):
            return None
        if self.status.get("running"):
            return None
        for prof in list(self.config.get("profiles", [])):
            center = (prof.get("domain") or "").strip().lower()
            if not center:
                continue
            try:
                state = self.refill_check_fn(center)
            except Exception as exc:  # noqa: BLE001 — a check must never kill the loop
                self.status["last_error"] = "refill check failed: %s: %s" % (
                    type(exc).__name__, str(exc)[:200])
                continue
            if not state.get("due"):
                continue
            params = self._profile_to_params(prof)
            rec = {"ts": _now(), "profile": prof.get("name", ""), "domain": center,
                   "refill": True, "ok": False, "inventory": state.get("inventory"),
                   "threshold": state.get("threshold"), "reason": state.get("reason"),
                   "added": None, "error": None}
            try:
                self.status["running"] = True
                res = self.refill_fn(params)
                rec["ok"] = True
                rec["inventory_after"] = res.get("inventory_after")
                rec["added"] = res.get("added")
                rec["candidates"] = res.get("candidates")
            except Exception as exc:  # noqa: BLE001
                rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
                self.status["last_error"] = rec["error"]
            finally:
                self.status["running"] = False
            self.runs.insert(0, rec)
            self.runs = self.runs[:50]
            self._save_runs()
            return rec
        return None

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._maybe_refill()
            except Exception as exc:  # noqa: BLE001 — the loop must survive anything
                self.status["last_error"] = "auto refill: %s: %s" % (
                    type(exc).__name__, str(exc)[:200])
            if self.config.get("enabled") and self.config.get("profiles") and self._is_due():
                self._execute_all()
            self._stop.wait(TICK_SECONDS)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()


if __name__ == "__main__":
    # smoke test: dummy run_fn
    def _dummy(p):
        return {"result": {"totals": {"candidates": 3},
                           "pool_stats": {"total_discovered": 3}}}
    s = Scheduler(_dummy)
    s.save_config({"enabled": True, "interval_hours": 24,
                  "profiles": [{"name": "test", "domain": "example.com"}]})
    print("config:", s.config)
    print("snapshot:", s.snapshot())
