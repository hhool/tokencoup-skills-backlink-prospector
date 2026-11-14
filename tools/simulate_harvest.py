#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local simulation of the competitor-backlink pipeline. No network, no WDC download.

What it does
------------
1. Generates a synthetic WDC-shaped graph (domain ranks + domain edges, gzipped)
   at a configurable scale. Every host is under the reserved .example TLD, so a
   row produced here can never be mistaken for a real prospect.
2. Runs tools/competitor_backlinks.py against it once per competitor-count
   (1, 2, 3, ...), exactly as an operator would on a real release.
3. Feeds each evidence file back through analyze.analyze() with the live HTTP
   probe stubbed out (a simulation must not claim a host answered), and prints
   how candidate / valid / competitor counts move as the competitor list grows.
4. Asserts the contract:
     - competitor hosts and their subdomains never appear in candidates/valid
     - evidence rows are admitted without a keyword match, with evidence
     - a seed row that is also a harvest row is enriched, never duplicated
     - more competitors => more candidates and more valid backlink targets

Usage
-----
  python3 tools/simulate_harvest.py                    # medium: 120k hosts / 600k edges
  python3 tools/simulate_harvest.py --preset big       # 400k hosts / 2M edges (perf run)
  python3 tools/simulate_harvest.py --preset tiny --keep --verbose

Two different scales on purpose: production only needs to surface 50 valid
targets a day, so the shipped evidence file is capped (--max-rows) and small;
the local run has no quota, so a multi-GB-class graph is only ever worth
processing on an operator machine. `--daily-target` turns the harvest output
into a runway number: how many days of 50/day one release can feed.

The generated graph lands in a temp dir and is deleted unless --keep is passed.
Python standard library only.
"""
import argparse
import gzip
import json
import os
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(HERE, "competitor_backlinks.py")
sys.path.insert(0, ROOT)

CENTER = "sim-center.example"
COMPS = ["sim-comp-a.example", "sim-comp-b.example", "sim-comp-c.example"]

PRESETS = {              # hosts, edges, per-competitor source pool
    "tiny": (6_000, 24_000, 15),
    "medium": (120_000, 600_000, 200),
    "big": (400_000, 2_000_000, 500),
}


def log(msg=""):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
# phase 1 — synthetic graph
# --------------------------------------------------------------------------- #
def gen_graph(workdir, hosts, edges, seed=20261115, per=None, verbose=False):
    """Write <workdir>/ranks.txt.gz and edges.txt.gz in WDC column shape.

    Shape used: ranks = `id <TAB> name <TAB> ...`, edges = `from <TAB> to <TAB> count`.
    Each competitor gets its own disjoint source pool (plus one shared host that
    links to all three) so "more competitors" has a measurable, deterministic
    effect instead of random noise.
    """
    rnd = random.Random(seed)
    t0 = time.time()

    special = [CENTER, "fansim.example", "bad..example", "www.youtube.com",
               "pornhub.com", "blog." + COMPS[0]] + COMPS
    names = ["sim-site-%06d.example" % i for i in range(hosts)] + special

    ids = list(range(1, len(names) + 1))
    rnd.shuffle(ids)                       # real ids are dense but not host-ordered
    host_id = dict(zip(names, ids))
    id_host = dict(zip(ids, names))

    # source pools: N hosts per competitor, +a few shared by all, +a seed-only row.
    # Pool size is the supply knob: production needs 50/day, so 30 days of runway
    # means ~1500 admitted sources across the competitor set.
    if not per:
        per = max(8, min(60, hosts // 400))
    pools = {c: names[i * per:(i + 1) * per] for i, c in enumerate(COMPS)}
    shared = names[3 * per:3 * per + max(4, per // 6)]
    fansim = "fansim.example"

    plan = []                              # (from_id, to_id, count)
    weights = [0.5, 0.3, 0.2]
    for comp, pool in pools.items():
        for src in pool:
            plan.append((host_id[src], host_id[comp], rnd.randint(1, 5)))
            if rnd.random() < 0.25:        # a second link from the same host
                plan.append((host_id[src], host_id[comp], rnd.randint(1, 3)))
    for src in shared:
        for comp in COMPS:
            plan.append((host_id[src], host_id[comp], rnd.randint(1, 4)))
    plan.append((host_id[fansim], host_id[COMPS[0]], 9))
    # competitor subdomain as a SOURCE — must be dropped, never a prospect
    plan.append((host_id["blog." + COMPS[0]], host_id[COMPS[1]], 7))
    # blocked / noise sources — must be dropped by the quality gate
    plan.append((host_id["pornhub.com"], host_id[COMPS[0]], 40))
    plan.append((host_id["www.youtube.com"], host_id[COMPS[0]], 40))
    # a source that is not a registrable host
    plan.append((host_id["bad..example"], host_id[COMPS[2]], 2))
    # ordinary crawl edges: sources linking to the center and to random hosts,
    # so the reverse grouping has to filter ~everything out
    linked = [s for pool in pools.values() for s in pool] + shared
    while len(plan) < edges:
        src = rnd.choice(linked) if rnd.random() < 0.7 else names[rnd.randrange(hosts)]
        if rnd.random() < 0.02:
            dst = CENTER
        else:
            dst = names[rnd.randrange(hosts)]
        plan.append((host_id[src], host_id[dst], rnd.randint(1, 2)))
    plan.sort()

    rp = os.path.join(workdir, "sim-domain-ranks.txt.gz")
    ep = os.path.join(workdir, "sim-domain-edges.txt.gz")
    with gzip.open(rp, "wt", encoding="utf-8", compresslevel=4) as f:
        for i in range(1, len(names) + 1):
            f.write("%d\t%s\tx\t1\n" % (i, id_host[i]))
    with gzip.open(ep, "wt", encoding="utf-8", compresslevel=4) as f:
        for a, b, c in plan:
            f.write("%d\t%d\t%d\n" % (a, b, c))
    if verbose:
        log("  graph: %d hosts, %d edge rows, ranks %.1f MB, edges %.1f MB (%.1fs)"
            % (len(names), len(plan), os.path.getsize(rp) / 1e6,
               os.path.getsize(ep) / 1e6, time.time() - t0))
    return rp, ep, len(names), len(plan)


# --------------------------------------------------------------------------- #
# phase 2 — harvest, once per competitor count
# --------------------------------------------------------------------------- #
def child_peak_mb():
    v = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return v / (1024.0 * 1024.0) if sys.platform == "darwin" else v / 1024.0


def harvest(ranks, edges, comps, out, max_rows=2000, verbose=False):
    cmd = [sys.executable, TOOL, "--center", CENTER,
           "--competitors", ",".join(comps),
           "--ranks", ranks, "--edges", edges,
           "--out", out, "--max-rows", str(max_rows)]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    if proc.returncode != 0:
        log(proc.stderr)
        raise SystemExit("harvest failed (rc=%d) for %d competitors" % (proc.returncode, len(comps)))
    data = json.load(open(out, encoding="utf-8"))
    meta = data.get("meta") or {}
    if verbose:
        for line in proc.stderr.strip().splitlines():
            log("    | " + line)
    return {"path": out, "rows": data.get("rows") or [], "meta": meta,
            "seconds": dt, "peak_mb": child_peak_mb(),
            "counters": meta.get("counters") or {}, "dropped": meta.get("dropped") or {}}


# --------------------------------------------------------------------------- #
# phase 3 — analyze, with the HTTP probe stubbed
# --------------------------------------------------------------------------- #
def stub_probe(url, timeout=9):
    """Simulated liveness: ~1 in 9 hosts does not answer, the rest return 200.

    Deliberately not "always true": valid < candidates must stay visible, and the
    competitor rows must be absent from BOTH numbers.
    """
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    if host.startswith("fansim") or host == CENTER:
        return {"status": 200, "ok": True, "final_url": url, "error": None}
    n = sum(ord(ch) for ch in host)
    if n % 9 == 0:
        return {"status": 404, "ok": False, "final_url": url, "error": None}
    return {"status": 200, "ok": True, "final_url": url, "error": None}


def analyze_sim(comps, evidence_path, seed_path=None):
    import analyze as A
    A.validate = stub_probe
    A.tranco_rank = lambda d, timeout=12: None

    data_dir = A.DATA_DIR
    target = os.path.join(data_dir, A.COMPETITOR_LINKS_PREFIX + CENTER + ".json")
    made = []
    try:
        if evidence_path:
            shutil.copyfile(evidence_path, target)
            made.append(target)
        if seed_path:
            made.append(seed_path)
        res = A.analyze({
            "domain": CENTER,
            "keywords": "",             # no keywords: evidence alone must admit rows
            "competitors": ",".join(comps),
            "existing": "",
            "use_bing": "0",
            "use_tranco": "0",
        })
    finally:
        for p in made:
            if os.path.isfile(p):
                os.remove(p)
        for p in os.listdir(data_dir):
            if p.startswith("tmp") or p.endswith(".tmp"):
                pass
    return res


def write_seed(path):
    rows = [
        {"url": "https://fansim.example", "type": "community", "tags": ["soundboard"],
         "domains": [CENTER], "note": "seed row that also appears in the harvest"},
        {"url": "https://sim-seed-one.example", "type": "blog", "tags": ["meme"],
         "domains": [CENTER], "note": "seed only"},
        {"url": "https://sim-seed-two.example", "type": "tool", "tags": ["audio"],
         "domains": [CENTER], "note": "seed only"},
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    return path


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="Simulate the competitor-backlink pipeline locally.")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="medium")
    ap.add_argument("--hosts", type=int, help="override host count")
    ap.add_argument("--edges", type=int, help="override edge row count")
    ap.add_argument("--per-competitor", type=int, dest="per_competitor",
                    help="synthetic linking hosts per competitor (default: from preset)")
    ap.add_argument("--keep", action="store_true", help="keep the generated graph + evidence files")
    ap.add_argument("--verbose", action="store_true", help="show harvest logs")
    ap.add_argument("--skip-analyze", action="store_true", help="harvest only")
    ap.add_argument("--daily-target", type=int, default=50,
                    help="valid targets production needs per day (default 50)")
    args = ap.parse_args(argv)

    hosts, edges, per = PRESETS[args.preset]
    hosts = args.hosts or hosts
    edges = args.edges or edges
    per = args.per_competitor or per
    workdir = tempfile.mkdtemp(prefix="bp-sim-")
    failures = []

    try:
        log("=" * 78)
        log("SIMULATION  center=%s  competitors=%s" % (CENTER, ", ".join(COMPS)))
        log("workdir     %s" % workdir)
        log("=" * 78)
        log("[1/3] synthetic WDC release")
        ranks, edgefile, n_hosts, n_edges = gen_graph(workdir, hosts, edges, per=per, verbose=True)
        rank_mb = os.path.getsize(ranks) / 1e6
        edge_mb = os.path.getsize(edgefile) / 1e6

        log("[2/3] harvest, one run per competitor count")
        runs = []
        for k in range(1, len(COMPS) + 1):
            out = os.path.join(workdir, "competitor-links-k%d.json" % k)
            r = harvest(ranks, edgefile, COMPS[:k], out, verbose=args.verbose)
            runs.append(r)
            log("  k=%d  rows=%-4d  %.2fs  peakRSS=%.0f MB  matched_edges=%s  dropped=%s"
                % (k, len(r["rows"]), r["seconds"], r["peak_mb"],
                   r["counters"].get("matched_edges"), json.dumps(r["dropped"], ensure_ascii=False)))
            if not r["rows"]:
                failures.append("k=%d produced no rows" % k)

        if args.skip_analyze:
            log("skip-analyze: harvest only")
        else:
            log("[3/3] analyze (HTTP probe stubbed — simulated liveness)")
            seed = write_seed(os.path.join(workdir, "seed-%s.json" % CENTER))
            import analyze as A
            seed_copy = os.path.join(A.DATA_DIR, "seed-%s.json" % CENTER)
            shutil.copyfile(seed, seed_copy)
            try:
                base = analyze_sim([], None)
            finally:
                if os.path.isfile(seed_copy):
                    os.remove(seed_copy)
            log("  k=0  candidates=%-4d valid=%-4d competitor_rows=%d from_competitors=%d"
                % (base["totals"]["candidates"], base["totals"]["valid"],
                   base["totals"]["competitor_rows"], base["totals"].get("from_competitors", 0)))

            prev_c = prev_v = -1
            table = [base]
            for k, r in enumerate(runs, 1):
                res = analyze_sim(COMPS[:k], r["path"])
                t = res["totals"]
                log("  k=%d  candidates=%-4d valid=%-4d competitor_rows=%-2d from_competitors=%-4d seed_scope=%s"
                    % (k, t["candidates"], t["valid"], t["competitor_rows"],
                       t.get("from_competitors", 0), res.get("data_sources", {}).get("seed_library", {}).get("scope")))
                table.append(res)
                if t["candidates"] <= prev_c:
                    failures.append("k=%d candidates did not grow (%d <= %d)" % (k, t["candidates"], prev_c))
                if t["valid"] <= prev_v:
                    failures.append("k=%d valid did not grow (%d <= %d)" % (k, t["valid"], prev_v))
                prev_c, prev_v = t["candidates"], t["valid"]

                comps_now = {c.lower() for c in COMPS[:k]}
                for p in res["prospects"]:
                    d = p["domain"].lower()
                    if any(d == c or d.endswith("." + c) for c in comps_now):
                        failures.append("competitor %s leaked into prospects (k=%d)" % (d, k))
                if any(rr["url"].split("//", 1)[-1].split("/", 1)[0].lower().endswith("." + c)
                       or rr["url"].split("//", 1)[-1].split("/", 1)[0].lower() == c
                       for c in COMPS[:k] for rr in r["rows"]):
                    failures.append("competitor host leaked into the evidence file (k=%d)" % k)
                if k == len(COMPS):
                    last = res
            # evidence contract on the last (widest) run
            fan = [p for p in last["prospects"] if p["domain"] == "fansim.example"]
            if len(fan) != 1:
                failures.append("seed row fansim.example duplicated: found %d rows" % len(fan))
            elif not fan[0].get("via_competitors") or not fan[0].get("evidence"):
                failures.append("seed row fansim.example was not enriched with evidence")
            elif fan[0]["relevance"] < 20:
                failures.append("evidence relevance not applied to enriched seed row (%s)"
                                % fan[0]["relevance"])
            else:
                log("  enrich  fansim.example  rows=1  via=%s  relevance=%d  source=%s"
                    % (",".join(fan[0].get("via_competitors") or []), fan[0]["relevance"],
                       (fan[0].get("source") or fan[0].get("pool_source") or "?")))
            shared = [p for p in last["prospects"] if len(p.get("via_competitors") or []) == len(COMPS)]
            log("  multi   %d rows cited by all %d competitors" % (len(shared), len(COMPS)))

            # supply math: production only ever needs --daily-target per day, so
            # what matters is how many days one release can feed before the pool
            # is exhausted (rows are static; dedupe cannot manufacture new ones).
            t_last = last["totals"]
            target = max(1, args.daily_target)
            runway = t_last["valid"] // target
            need30 = target * 30
            log("  supply  valid=%d  target=%d/day  runway=%d day(s) from one release"
                % (t_last["valid"], target, runway))
            log("          30-day runway needs ~%d valid rows (max-rows ~%d, file ~%.1f MB)"
                % (need30, int(need30 / 0.9), need30 * 600 / 1e6))
            if args.preset != "tiny":
                if t_last["valid"] < target:
                    failures.append("one-day supply below target: %d valid < %d"
                                    % (t_last["valid"], target))
                if runway < 7:
                    log("  WARN    runway under a week: raise --max-rows or add competitors")
            else:
                log("  note    tiny preset is a mechanics run, not a production volume model")

        log("=" * 78)
        log("perf: %d hosts / %d edges  (ranks %.1f MB, edges %.1f MB gz)" % (n_hosts, n_edges, rank_mb, edge_mb))
        if args.keep:
            log("kept        %s" % workdir)
        if failures:
            for f in failures:
                log("FAIL  " + f)
            log("RESULT  FAILED (%d)" % len(failures))
            return 1
        log("RESULT  SIMULATION PASSED")
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
