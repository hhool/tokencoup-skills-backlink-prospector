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
- Fill **target domain** (e.g. `soundbuttons.click`) and **keywords** (comma-separated, e.g. `soundboard, sound effects, meme sounds`).
- "Add current form as profile" saves the config; switching domains later reloads it automatically.
- Different domains are **fully isolated** — no cross-contamination.

### Step 2 · Analyze for candidates (🔍 Analyze)
- Fill the form, click **Analyze**.
- Candidate sources: ① the domain's **seed library** (`seeds/seed-<domain>.json`, baked into the image, stable & reliable); ② optional Bing live discovery (datacenter egress often returns off-topic cached results, rejected by the relevance gate — bonus channel only).
- Results are sorted by **priority (0–100) = relevance + authority + obtainability**; click any header to sort; filter by type / min priority / gap-only / valid-only.
- Default `persist=1` auto-merges results into the pool (dedup + accumulate).

### Step 3 · View the pool, see the real gap (🗃 Pool)
- Stat cards: **discovered / acquired / gap / gap & valid**.
- The left **type tree** organizes candidates by the 10 backlink types with multi-select filtering; toggle **Acquired / Gap** status top-right.
- **Export pool CSV** downloads the candidate list.
- Until you import existing backlinks, every non-competitor candidate counts as a gap (normal intermediate state).

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
