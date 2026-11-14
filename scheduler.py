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

DEFAULT_CONFIG = {"enabled": False, "interval_hours": 24, "profiles": []}
MIN_INTERVAL_H = 0.05   # ~3 minutes, allows quick testing
MAX_INTERVAL_H = 8760   # 1 year
TICK_SECONDS = 30


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Scheduler:
    def __init__(self, run_fn):
        self.run_fn = run_fn
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.config = self._load_config()
        self.runs = self._load_runs()
        self.status = {"running": False, "last_error": None, "next_run": None,
                       "started_at": _now()}
        self._recompute_next()
        # Auto-start the loop thread (daemon: dies with the process).
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

    def _loop(self):
        while not self._stop.is_set():
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
