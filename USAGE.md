# Usage Guide · Backlink Prospector

A hands-on manual for operators / outreach teams. For technical detail see [README.md](README.md).

---

## 0. What this is

A tool that finds **real, usable backlink prospects** for a site (the **center domain**, e.g. `soundbuttons.click`) and runs a **gap analysis**. It keeps three layers of data:

| Layer | Meaning | Who writes it |
|---|---|---|
| **Pool (candidates)** | sites ever discovered — the "seen" list | auto-merged on every analysis |
| **Acquired library** | backlinks you already truly own (imported from GSC / Ahrefs etc.) | you, via import |
| **Delivery ledger** | per-slot records of outreach / submission / go-live — the single source of truth for "delivered" | you, via claim & transition |
| **Gap** | in the pool but neither imported as acquired nor live on the ledger | computed by the system |

> Key idea: **"seen" is not "owned."** A prospect leaves the gap only when it is imported as acquired or verified live on the ledger.

---

## 1. Start

```bash
cd backlink-prospector
python3 server.py --port 8787
# open http://127.0.0.1:8787
```

Live deploy: `https://backlink-prospector.fly.dev/` (prod data lives on the Fly volume; local data in `data/` — both isolated, neither committed to git).

Top-right has a `中 / EN` toggle for one-click bilingual UI.

---

## 2. Standard workflow (5-step loop)

### Step 1 · Pick the center domain + keywords
- The **center domain** in the top bar is a typable dropdown: it lists every domain this workspace knows with `pool N · seed M · comp-links K`, so near-identical hosts (`.cc` vs `.click`) are distinguishable and you no longer open the wrong pool. Typing a new domain still works.
- The app remembers your **last used domain**, so a reload does not snap back to the default.
- **Keywords** (comma-separated, e.g. `soundboard, sound effects, meme sounds`) drive relevance scoring.
- "Add current form as profile" saves the config; switching domains later reloads it automatically.
- Different domains are **fully isolated** — no cross-contamination.

### Step 2 · Analyze for candidates (🔍 Analyze)
- Fill the form, click **Analyze**.
- Candidate sources: ① the domain's **seed library** (`seeds/seed-<domain>.json`, baked into the image, stable & reliable); ② optional Bing live discovery (datacenter egress often returns off-topic cached results, rejected by the relevance gate — bonus channel only).
- Candidate source ③: **competitor backlinks** (`seeds/competitor-links-<domain>.json`, produced by the offline host-graph harvest). These rows are admitted by evidence, exempt from the keyword gate, and tagged `via competitor: <domain>` in the table.
- **Competitor hosts themselves** (subdomains included) are not candidates, are not HTTP-validated, and never count toward the gap; they are only reported under the cards (e.g. "2 competitor host(s) excluded · 27 candidate(s) came from competitor backlinks").
- Results are sorted by **priority (0–100) = relevance + authority + obtainability**; click any header to sort; filter by type / min priority / gap-only / valid-only.
- Default `persist=1` auto-merges results into the pool (dedup + accumulate).

### Step 3 · View the pool, see the real gap (🗃 Pool)
- Stat cards: **discovered / acquired / gap / gap & valid**.
- The left **type tree** organizes candidates by the 10 backlink types with multi-select filtering; toggle **Acquired / Gap** status top-right.
- **Export pool CSV** downloads the candidate list.
- Until you import existing backlinks, every candidate counts as a gap (normal intermediate state).

### Step 4 · Import existing backlinks → compute the true gap
Paste your real existing backlink domains (one per line, from GSC / Ahrefs / your own records) into the "import existing" box and click import. Those domains are marked `acquired` and the gap recomputes immediately (e.g. 5 candidates, import 2 → gap drops 5→3).
- A bad import can be reverted with "unmark existing" in the same box — candidates are not lost.

### Step 5 · Turn candidates into deliveries (Delivery ledger, inside the Pool panel)
For each target you act on:
1. **Claim / batch-claim**: reserve a slot. Single claim or paste multiple rows to batch-claim.
2. Advance the state machine: `registered → claimed → submitted → live → lost` (`rejected` / `error` are terminal).
3. Going `live` **requires evidence**: supply `landing_url` + `verify_method` (e.g. `manual_check`); the slot then locks permanently.
4. For targets you won't pursue, **suppress** the domain or exact slot permanently.
5. **Export ledger CSV** (with evidence columns) for handoff / records.

> Exclusion rules (re-checked on every claim, returns a reason when blocked): live slot locks forever; in-progress is idempotent (no dup row); `lost` needs manual review; `rejected`/`error` cool down 90 days; same `target_domain` with a `live`/`submitted` within 90 days hits the cadence window; explicit suppressions are permanent.

---

## 3. Panel quick reference

| Tab | Purpose |
|---|---|
| 📊 Overview | stat cards, reciprocal-ratio monitor, type distribution |
| 🔍 Analyze | run analysis, view candidates, sort/filter, export analysis CSV |
| 📖 Types & Weights | 10 backlink types, value weights, reciprocal-link risk, scoring model |
| 🗃 Pool | candidate pool, type-tree filter, import/unmark existing, **delivery ledger**, pool CSV / ledger CSV |
| ⚙ Backend · Scheduler | enable auto-runs, set interval, manage profiles, run now, view run history |

**In-app help (no doc needed)**
- Every tab has a **💡 Tips** button at the top of the view; it expands that view's guidance in place and collapses again on a second click.
- The top bar's **? Help** button opens a standalone help page: `http://127.0.0.1:8787/help` locally, `https://backlink-prospector.fly.dev/help` in production. Add `?lang=en` for English; the page can also switch language in place.
- It is organised in seven sections: what it is / five-step loop / panel map / states &amp; rules / API cheatsheet / data &amp; backup / FAQ.

---

## 3.5 Where competitor backlinks come from (offline harvest)

Sites that link to your competitors are the highest-value candidate source, but they need one offline pass: the Web Data Commons / Common Crawl host graph is tens of GB and cannot live in the service image.

```bash
# 1) download one WDC release (domain-ranks + domain-edges, same crawl window)
# 2) reverse query: who links to my competitors (3 streaming passes, memory grows with hits only)
python3 tools/competitor_backlinks.py \
  --center soundbuttons.click \
  --competitors myinstants.com,voicemod.net \
  --ranks /data/wdc/cc-main-2025-may-aug-domain-ranks.txt.gz \
  --edges /data/wdc/cc-main-2025-may-aug-domain-edges.txt.gz \
  --out   seeds/competitor-links-soundbuttons.click.json
```

- The output ships with the image (`seeds/` is in git) and is read directly in production; `data/` also works as a machine-local override (not in git, not on the server).
- Stricter gate: `--min-links 3`; inspect without writing: `--dry-run`.
- Already have an extracted edge list (`source,target[,count]`)? Use `--from-csv` instead of the full graph.
- Every row carries evidence (`via_competitors[]`, `evidence{graph, edges, per_competitor}`); `type` is guessed from the hostname (`type_guess=true`) and should be reviewed before outreach.

> Note: more competitors means more inbound surface scanned, but "more competitors -> more valid backlinks" is not an identity — dedup, suppressions and the quality gate all cut the net gain.

---

## 4. CLI / API quick reference (for bulk & automation)

All calls work against local `8787` or the live host.

**Analyze**
```bash
curl -s -X POST http://127.0.0.1:8787/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","keywords":"soundboard, sound effects",
       "competitors":"","use_bing":"0","use_tranco":"1","persist":"1"}'
```

**Import existing backlinks (mark acquired, recompute gap)**
```bash
curl -s -X POST http://127.0.0.1:8787/api/store/sync-existing \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","domains":"reddit.com\nnews.ycombinator.com"}'
```

**Revert existing backlinks (back to gap)**
```bash
curl -s -X POST http://127.0.0.1:8787/api/store/unmark-existing \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","domains":"reddit.com"}'
```

**Batch-claim placement slots**
```bash
curl -s -X POST http://127.0.0.1:8787/api/placements/claim-batch \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","items":[
        {"target_domain":"a.com","target_url":"https://a.com/post","placement_type":"guest_post"},
        {"target_domain":"b.com","target_url":"https://b.com/page","placement_type":"resource"}
      ]}'
```

**Advance a slot to live (evidence required)**
```bash
curl -s -X POST http://127.0.0.1:8787/api/placements/transition \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","id":"<record-id>","state":"live",
       "landing_url":"https://a.com/post","verify_method":"manual_check"}'
```

**Export CSV / view ledger**
```bash
curl -s "http://127.0.0.1:8787/api/store/csv?domain=soundbuttons.click" -o pool.csv
curl -s "http://127.0.0.1:8787/api/placements/csv?domain=soundbuttons.click" -o ledger.csv
curl -s "http://127.0.0.1:8787/api/placements?domain=soundbuttons.click"
```

---

## 5. Data & backup

- One store per domain: `data/store-<center_domain>.json` (holds `domains`, `acquired_domains`, `placements`, `suppressions`).
- Scheduler config: `data/schedule.json`; run history: `data/schedule_runs.json`; channel toggles: `data/channels-<domain>.json`.
- All under `data/` are **git-ignored**; local and live (Fly volume) are independent.
- **Seed library** `seeds/seed-<domain>.json` **is version-controlled and baked into the image** — controlled input; edit requires a commit.
- Backup: just copy the whole `data/` directory.

---

## 6. FAQ

**Q: I clicked Analyze and got nothing?**
A: 9 times out of 10 there's no seed library or Bing is blocked. Check the Pool stat cards — if 0, the domain has no `seeds/seed-<domain>.json`; create one (one candidate per row: `url/type/tags/domains/note`). Live Bing egress is often blocked — normal; the seed library is the primary channel.

**Q: Why does every candidate show as "gap"?**
A: Because you haven't imported the acquired library yet. Import it (Step 4) and the gap shrinks.

**Q: Can I undo a bad import?**
A: Yes. Use "unmark existing" or `/api/store/unmark-existing`; candidates are not lost.

**Q: I can't set a slot to "live"?**
A: Going `live` requires both `landing_url` and `verify_method` evidence. "Clicked submit" alone is not success.

**Q: Will data from different sites mix?**
A: No. Each center domain has isolated storage and seed scoping; switching domains isolates automatically.

**Q: Will scheduled tasks run forever?**
A: The scheduler is a daemon thread inside the server process; it stops when the server stops. For 24/7, run the start command under systemd / pm2 / nohup.
