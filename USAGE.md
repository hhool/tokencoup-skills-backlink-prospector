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

## 3.6 Local simulation (no network, no download)

Before spending gigabytes on a real WDC release, run the whole chain on a synthetic graph. Every host sits under the reserved `.example` TLD, so nothing produced here can be mistaken for a real prospect; the HTTP probe is stubbed (about 1 in 9 hosts does not answer), which keeps `valid < candidates` visible.

```bash
python3 tools/simulate_harvest.py                  # medium: 120k hosts / 600k edges
python3 tools/simulate_harvest.py --preset big      # 400k hosts / 2M edges, perf run
python3 tools/simulate_harvest.py --preset tiny --keep --verbose   # keep artefacts
```

It does three things and asserts each contract:

1. generates `*-domain-ranks` / `*-domain-edges` (gz, same column shape as WDC, shuffled ids);
2. runs harvest once per competitor count (1 -> 2 -> 3) and prints rows, wall time, peak RSS, drop reasons;
3. feeds every evidence file back into `analyze()` and prints `candidates / valid / competitor_rows / from_competitors`, checking that competitor hosts and their subdomains never become candidates, that evidence rows are admitted without a keyword match, and that a seed row sharing a domain with an evidence row is merged rather than duplicated.

**Is 50 valid per day enough?** Supply is finite: one release only yields as many addresses as the file holds, then it is spent.

| Competitors | Valid rows per release (simulated) | Days at 50/day |
|---|---|---|
| 1 | ~520 | ~10 |
| 2 | ~960 | ~19 |
| 3 | ~1400 | ~28 |

For a steady 50/day online, ship with `--max-rows` around 1500 (~0.9 MB, trivial for the image) and treat each WDC release as a scheduled task. A real niche has a much thinner inbound surface than these synthetic pools, so harvest is a periodic top-up, not a daily source — the day-to-day gap still comes from the seed library plus live discovery.

## 3.7 Daily quota and the batch queue (100/day by default)

"100 a day" is a **work quota**, not a production rate. The overview page carries a "Daily queue" bar:

| Number | Meaning |
|---|---|
| Daily quota | Max rows deliverable per day, **editable in the queue bar** (100 by default, capped at 2000, stored per center domain) |
| In batch | Rows in today's batch that are still unclaimed |
| Claimed today | `used/quota`; used = rows newly claimed today (UTC+8), including single claims made from the pool |
| Supply gap | `quota − batch`: the part inventory cannot cover, with a **Get more** button beside it |
| Pool inventory | Every pool domain that is valid, not owned, not a competitor, not suppressed, not whitelisted, and has no active placement or cooldown |

Four rules, all deliberate:

1. **Frozen per day.** The first page load slices the batch and writes `data/queue-<domain>-<YYYYMMDD>.json` — **one file per day**. That separation is deliberate: a curl or a monitor that forgets `date` only ever touches its own day and can never rebuild the batch you are working from. Files older than 14 days are pruned.
2. **Claimed rows leave the batch.** "Claim batch" writes every remaining row into the delivery ledger as `claimed` and stamps the `batch_id`; rows blocked by the ledger, suppressions or cooldown are counted separately.
3. **No automatic refill.** Short inventory shows up as a gap — never padded with duplicates. Closing it takes a fresh analysis (the **Get more** button runs one in place) or a harvest file (see 3.5). Lowering the quota never deletes rows already handed to you; raising it tops today's batch up to the new quota.
4. **The quota is a hard gate.** Claims beyond it are rejected by the server (`409 daily quota reached`), including single claims from the pool — otherwise "100/day" is just a slogan. The quota day rolls at 00:00 **UTC+8** (`QUOTA_TZ_OFFSET`), not UTC.

## 3.8 Whitelist (excluded from backlink stats)

Some pool domains must never move a number: your own network, aggregators, mirrors, known link farms. This is deliberately *not* the same as a suppression — a **suppression** means "never offer me this slot again", a **whitelist entry** means "keep the record, just don't count it".

- Every record (pool row, analysis row, ledger row) carries an **Add to whitelist / Un-whitelist** button.
- Whitelisted domains stay in the pool (otherwise the toggle would disappear and the decision would be irreversible) but are removed from: discovered, acquired, gap, gap & valid, type distribution, reciprocal ratio and the daily queue.
- The Pool tab has a whitelist block: paste several hosts at once (`example.com`, `https://www.foo.com/x` both work — scheme, `www` and path are stripped), and remove any entry with `×`.
- Claiming a placement on a whitelisted host is refused (`409 whitelisted`): it can never be counted, so the work would be invisible.
- The whitelist is isolated per center domain and stored in `whitelist` inside `data/store-<domain>.json`.

API:

- `GET /api/whitelist?domain=`
- `POST /api/whitelist` body `{center_domain, domains|domain, action:"add"|"remove", note}`
- `POST /api/settings` body `{center_domain, daily_quota}` (1–2000, out of range → 400)
- `GET /api/queue?domain=&date=YYYY-MM-DD` (`&refill=1` tops the batch up explicitly; the `quota` param only sizes this batch, the **hard gate always uses the configured value**)

The client sends its local date, so "today" is your today, not the UTC day of the machine.

---

## 3.9 Importing existing backlinks (export → ledger → gap report)

"Acquired" has three sources: verified live ledger rows, manual marks, and **imported existing backlinks**. The third one is the easy one to forget and the one that makes the gap wrong — you may already have 300 backlinks while the pool calls every one of them a gap.

The paste format is forgiving:

```
https://www.reddit.com/r/foo/comments/abc/     # a full URL
example.org                                     # a bare host
Linking page,Anchor,Date                        # a CSV header (skipped)
12,https://listicle.example/best,2026-10-08     # CSV with a leading rank column
```

What an import actually does (it is not "just a flag"):

- Every row becomes a **`live` ledger record** with `verify_method = import:<source>` and an empty `verified_at` — meaning "backed by an export, never probed". Label the source (`ahrefs-2026-11`, `gsc`, `cc-2026-10`) so a later survival recheck can start with exactly the unprobed rows.
- In-pool domains: the gap drops by that many rows and **Acquired** goes up with it.
- Out-of-pool domains: **never injected into the pool** (that would inflate "discovered"), but they are booked and fall under the 90-day per-domain cadence, so no quota is spent chasing a site that already links to you.
- **No daily quota is consumed**: importing is bookkeeping, not today's work. A 500-row paste cannot slam the day's gate shut.
- Automatically skipped: your own domain (incl. subdomains), competitors, whitelisted hosts, suppressed hosts, duplicates (idempotent per delivery slot).

Three buttons:

| Button | What it does |
|---|---|
| Preview | `dry_run`: reports what the gap would become, writes nothing |
| Import as owned | Writes for real; the report shows gap X→Y, owned P→Q, in-pool/out-of-pool counts and skip reasons |
| Undo this batch | Deletes only the rows **this feature created** for those hosts; the gap comes back exactly. Manual marks and genuinely delivered rows are untouched |

API: `POST /api/placements/import` with `{center_domain, text, source, dry_run?, remove?, own_url?}`. The response carries `before/after/gap_delta/acquired_delta/skipped/in_pool_sample/out_of_pool_sample` — enough to paste straight into a report.

---

## 3.10 Survival recheck (is the link still there?)

A `live` row in the ledger is a claim. A backlink is only valid while the page still carries it, so every live row gets revisited on a schedule. Default window: 7 days (`RECHECK_DAYS`, 1–90).

Three verdicts, only two of which change state:

| Verdict | Evidence | Effect |
|---|---|---|
| Alive | 2xx **and** our link is still in the HTML (absolute href / relative href / domain) | Nothing changes; the attempt is recorded |
| Gone | 404 / 410, or the page loads without our link | `state=lost`, the domain **returns to the gap** (reuse needs a human decision) |
| Inconclusive | timeout, DNS/TLS failure, 403, 429, 5xx | Only the attempt is recorded — **never deletes a row**. A bot wall or a timeout is not proof of removal |

Notes:

- **Imported rows go first**: those with an empty `verified_at` (from an export, never actually visited) are the least certain, so they are probed before anything else.
- **No daily quota is consumed**: rechecking is verification, not today's work.
- Each probe is stored on the row as `recheck` (latest) and `checks` (last 5), with the HTTP status, what matched, and the URL actually fetched.
- Every scheduled analysis run also rechecks 20 rows (`recheck` / `recheck_limit` config), so as long as the machine is awake a dead link is caught within a week.

```bash
# Preview: really probes, writes nothing
curl -s -X POST http://127.0.0.1:8787/api/placements/recheck \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","limit":20,"dry_run":true}'

# Real recheck (limit 1-100, days 1-90, timeout 3-30)
curl -s -X POST http://127.0.0.1:8787/api/placements/recheck \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click","limit":20,"days":7}'

# How many rows are due
curl -s "http://127.0.0.1:8787/api/placements?domain=soundbuttons.click" | jq .recheck
```

---

## 3.11 Entry discovery (submission form / contact address)

The delivery loop needs two values the pool does not carry: **where** a site accepts
a submission, and **who** to mail. Both are observable from outside without sending
anything, so `tools/discover_entry.py` observes them once and writes an overlay.

```bash
# what would be visited (no network)
python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json --dry-run --limit 10

# observe 10 domains, honouring robots.txt, cached for 30 days
python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json \
    --limit 10 --out data/enrichment-soundbuttons.cc.json

# continue a long run without re-fetching what is already done
python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json \
    --out data/enrichment-soundbuttons.cc.json --resume

# offline self check
python3 tools/discover_entry.py --selftest
```

What it decides, and why:

| Question | Rule |
|---|---|
| Which pages get read? | home, then same-host links scored by a path lexicon (`/submit`, `/guest-post`, `/write-for-us`, `/advertise`, `/contact`), then at most 3 unlinked probe paths if nothing was found |
| Is this a submission form? | it must be able to carry **words** (textarea, or a message/subject field) **and** a target (a URL field or an email). `email + website` with no message is a signup box and is rejected |
| Search / login / newsletter? | rejected: a `q`/`search` form, a password field, or a single-field box |
| Which field is "your name"? | the field *name* when it means something, otherwise the `<label>`. WPForms writes `wpforms[fields][0]`; the label says "Your Name" |
| What is a `shape`? | `sha256(method + sorted semantic slots)` with hidden tokens and honeypots excluded. Two sites running the same plugin produce the **same shape**, so one reviewed mapping serves both |
| Which address? | `mailto:` and Cloudflare `data-cfemail` first, then page prose; on-domain and role addresses rank higher; `noreply@` and placeholder domains are dropped |
| What if nothing is found? | recorded as observed, with the page count. A miss inside a page budget is **not** a negative - `--max-pages` is the lever, not a conclusion |

Output (`data/enrichment-<center>.json`) is an overlay, not a store rewrite: the
store stays the source of truth for prospects, and the overlay is folded in at
export time (`bin/delivery export-snapshot --enrichment ...`) as contract C 1.1.0.

Safety: every request is a `GET`. Nothing is posted, no form is submitted, no mail
is sent, robots.txt is obeyed (`pages_blocked` counts refusals), and the HTML that
produced each decision stays in `data/cache/` for audit.

## 3.12 Run diff (what the last run actually added)

Watching "discovered: 55" tells you nothing: it cannot separate three genuinely new domains from the same three being seen again. So every persisted run leaves a **snapshot**, and the difference between two snapshots is the answer.

A snapshot holds the domain list, the invalid-domain list and the total/valid/acquired counts. The last 10 are kept; above 20k domains only totals are stored (the diff then says "totals only" instead of inventing a name diff).

Four lines come out:

| Field | Meaning |
|---|---|
| `added` / `added_count` | domains that were not in the previous snapshot |
| `removed` / `removed_count` | domains the previous snapshot had and the pool no longer does |
| `newly_invalid` | in both snapshots, but failed verification this time (site down / bot wall / 404) |
| `recovered` | invalid before, verifies again now |

```bash
# diff of the two most recent runs
curl -s "http://127.0.0.1:8787/api/runs/diff?domain=soundbuttons.click" | jq .diff

# against the run 3 runs ago (back= 1..9)
curl -s "http://127.0.0.1:8787/api/runs/diff?domain=soundbuttons.click&back=3" | jq '.diff.added_count'
```

The dashed strip at the bottom of the overview is exactly this: `Last run changed · new N · went invalid N · back to valid N · pool total N`, followed by a few example domains. `/api/analyze` also returns `run_diff`, so a run immediately shows what it contributed.

---

## 3.13 Auto refill (restock when the shelf runs low)

The queue is "how much work today"; the pool is "what is on the shelf". A 100-row frozen batch is just a number when the shelf holds 12. So besides the manual **Get more** button, the backend restocks by itself:

- **Trigger**: claimable candidates (`inventory` — in-pool, not claimed, not owned, not excluded, verified) below `REFILL_THRESHOLD` (default 30).
- **Action**: one full analysis using the domain's saved profile (keywords / competitors), merged straight into the pool.
- **Cooldown**: 6 hours by default (`REFILL_COOLDOWN_H`), persisted in the store so a restart cannot reset it.
- **No-progress backoff**: if the last refill added nothing, the cooldown doubles (6h → 12h → 24h → 48h, capped at 8x); one productive refill resets it to 6h. Free sources saturate, and one wasted run is enough — there is no reason to hit other people's servers every six hours.

| Switch | Where | Notes |
|---|---|---|
| `auto_refill` | `data/schedule.json` / `POST /api/schedule` | default `true`; turn it off to keep only the manual button |
| `REFILL_THRESHOLD` | env var | low-water mark, default 30 |
| `REFILL_COOLDOWN_H` | env var | base cooldown in hours, default 6 |

```bash
# refill now, using the saved profile (400 tells you to save keywords first)
curl -s -X POST http://127.0.0.1:8787/api/refill \
  -H 'Content-Type: application/json' \
  -d '{"center_domain":"soundbuttons.click"}' | jq '{inventory_before,inventory_after,added}'

# inventory / cooldown / backoff state
curl -s "http://127.0.0.1:8787/api/store?domain=soundbuttons.click" | jq .refill
```

The small "auto-refill" cell in the queue bar shows the current state: `due` (may restock now), `12h` (cooling down), `stocked` (enough inventory).

---

## 3.14 Dead-link todo (somebody has to notice)

The survival recheck moves a dead row to `lost` and hands the domain back to the gap — but if nobody looks, that result just sits in the ledger. So the overview opens with a red todo strip that **only appears when something died in the last 7 days**:

- count plus the first five domains;
- **Open ledger** jumps to the ledger, where the `Lost` pill and the recheck evidence (HTTP status, what matched) live;
- the window is `LOST_WINDOW_DAYS` (default 7, 1–90).

After a loss the domain is back in the gap, and lifting the 90-day per-domain cadence needs a human decision (`lost -> submitted` is allowed), so this todo is really a "time to re-pitch" list.

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
