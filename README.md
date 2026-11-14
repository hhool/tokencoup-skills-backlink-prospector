# Backlink Prospector

Find **real, reachable** backlink prospects for a given domain and run a **backlink-gap analysis**.
Backend service + CSV export + web UI. Zero third-party dependencies (pure Python standard library).
License: [MIT](LICENSE) · 中文文档：[README.zh.md](README.zh.md)

> **文档说明（该读哪份）**
> - **[USAGE.md](USAGE.md)**（中文 [USAGE.zh.md](USAGE.zh.md)）：**用户使用手册**——面向运营 / 推广人员，讲怎么用界面和接口完成"发现候选 → 算缺口 → 投放交付"的闭环。日常操作看这份。
> - **README.md**（本文）：**技术与架构文档**——模块设计、打分模型、多域名隔离、端点契约、CSV 字段、局限说明。二次开发或排障看这份。

> Architecturally modeled on `seo-page-snapshot`: free/open data sources only, commercial
> metrics (DR/DA) are **never estimated**, bilingual field labels, and missing data is
> always reported as `unavailable`.

---

## 1. Core Modules

| Requirement | Implementation |
|---|---|
| **1. Backlink types** | 10 types (`reciprocal` kept separate from `directory`): `industry_media`, `guest`, `resource`, `directory`, `community`, `social`, `partner`, `authority` (.gov/.org), `digital_pr`, `reciprocal` (two-way link exchange, a distinct type). Defined in `analyze.py` (`TYPE_LABEL_ZH/EN`) and `seed.json`'s `type` field. |
| **2. Priority scoring** | Each prospect scores `relevance`(0–40) + `authority_score`(0–30) + `obtainability`(0–30) = `priority`(0–100). Authority tier comes from seed annotation plus free Tranco ranking. The UI filters by type, minimum priority, gap-only, valid-only. |
| **3. Gap analysis** | Candidates = seed library (real, verified sites) + optional live Bing discovery + competitor backlink sources (offline host-graph harvest). Import existing backlinks (GSC/Ahrefs export); matched domains are marked `already_have=true`; every remaining prospect is a `is_gap` one. Competitor hosts (subdomains included) are dropped as rows entirely - never candidates, never validated, never counted - while sites that LINK TO a competitor are high-value candidates. |

---

## 2. Feature Summary (types / weights / reciprocal / scoring / periodic queries)

### A. Backlink types (10, defined in `analyze.py` + `seed.json`)

| Type key | Value weight | Obtainability (0–30) | Notes |
|---|---|---|---|
| `authority` | Highest trust | 8 | Industry bodies, .gov/.org guides; hardest to get, highest trust |
| `industry_media` | Highest | 12 | Review/media sites; in-content links carry high weight and relevance |
| `digital_pr` | Very high (if cited) | 10 | HARO / journalist requests traded for media or .edu links |
| `guest` | High | 22 | Guest posts in niche blogs; controllable and scalable |
| `resource` | High (best value) | 26 | Curated "best resources" pages naturally list outbound links |
| `partner` | Medium-high | 18 | Non-competing allies (adjacent tools/brands); exchanges and co-marketing |
| `directory` | Low per link | **28 (easiest)** | One-way directory listings; often low quality, tracked separately |
| `community` | Brand / traffic | 20 | Forums and Q&A; mostly nofollow, valued for traffic and brand |
| `social` | Brand | 16 | Pinterest / Instagram / YouTube profile pages |
| `reciprocal` | **Lowest** | **29 (easiest)** | Two-way link exchange; volume filler only; ratio must be controlled (see B) |

> **`directory` vs `reciprocal` are deliberately separated**: `directory` = listed
> one-way by a directory; `reciprocal` = mutual exchange. Both are counted separately
> in gap analysis and in the pool.

### B. Reciprocal links — the 10th, distinct type

- Reciprocal ("you link me, I link you") is counted **separately** from `directory` (one-way listing).
- Easiest to obtain (29/30), lowest per-link SEO value; use as volume filler only, never as the main weight source.
- ⚠️ Google classifies reciprocal linking done to manipulate PageRank as a **link scheme** — it can trigger demotion or penalties.
- **Ratio control**: a warning fires when reciprocal links exceed `RECIPROCAL_RATIO_WARN = 0.30` (30%) of the pool (live gauge on the Overview page).
- Practice: only exchange links with editorially curated vertical sites / complementary brands; keep the ratio natural, never mass-exchange.

### C. Priority scoring model (0–100)

```
priority = relevance(0–40) + authority(0–30) + obtainability(0–30)
```
- `relevance`: +8 per matched keyword (capped at 40); with no keywords, a per-type baseline applies (e.g. resource 26, directory 28, social 18).
- `authority`: `High`=30 / `Medium`=20 / `Low`=10 (seed annotation + free Tranco ranking).
- `obtainability`: table above; +4 extra when the URL contains `write for us / contribute / guest / submit`.
- Commercial DR/DA is **never estimated**; missing values are reported as `unavailable`.
- `reciprocal` prospects take an extra `RECIPROCAL_PRIORITY_PENALTY = 12` sort penalty, keeping them clearly in the "volume filler" tier.

### D. Periodic queries + existing/gap tracking (the pool)

- Every analysis is **merged into the backlink pool** by default (`persist=1`): deduplicated by domain, accumulating `times_discovered`, first/last seen, best validation status and latest priority.
- Repeated runs keep **growing the prospect list**.
- Import real existing backlinks (GSC / Ahrefs / a Common Crawl export, one domain per line) → those domains are marked `acquired`.
- **Seen is not owned.** Gap detection uses verified live placements, operator-marked acquisitions and the explicit import only; pool membership alone never excludes a prospect. See D7.
- The Pool panel shows stat cards (discovered / acquired / gap / gap & valid), a per-type distribution, and pool CSV export.

### D2. Backend scheduler (configurable in the UI)

Configured entirely from the "Backend · Scheduler" panel — no code changes:

- **Enable switch**: once on, a daemon thread runs every saved profile on the configured interval, merging results into the pool (dedup, accumulate).
- **Interval (hours)**: 0.05–8760 (about 3 minutes to 1 year); effective on save.
- **Profiles**: save multiple periodic targets (name / domain / keywords / Bing / Tranco toggles each). "Add current form as profile" stores the top form in one click; edit or delete in the panel.
- **Run now**: run all profiles immediately, ignoring the timer (for testing or catch-up).
- **Status & history**: enabled / running / last run / next run / latest error live, plus the last 15 runs (time, domain, ok/failed, candidates, pool total, error detail).
- **Persistence**: config in `data/schedule.json`, run history in `data/schedule_runs.json` (last 50).

> Implementation: `scheduler.py` (pure-stdlib daemon thread, 30s tick, atomic writes);
> `server.py` loads and starts it automatically. Config passes validation at `POST /api/schedule`
> (invalid profiles filtered, interval clamped).

### D3. Multi-domain architecture (profiles · seed scoping · relevance gate)

Every tab revolves around the "center domain"; data for different domains is **fully isolated**:

| Mechanism | Storage | Purpose |
|---|---|---|
| **Domain profile** | `profiles.json` (defaults) + `data/profile-<domain>.json` (overrides) | Each domain has its own `keywords` / `competitors`. Switching the center domain writes the form back to the **old** profile, then loads the **new** one — keywords and competitors follow the domain automatically. |
| **Pool isolation** | `data/store-<domain>.json` | One pool per domain; stats and CSV never mix. ⚠️ `server.py::run_analysis` must fall back to `params["center_domain"]`: the scheduler calls `run_fn(params)` without a positional argument, otherwise scheduled runs write into the legacy shared pool `data/store.json` and niches mix. |
| **Channel isolation** | `data/channels-<domain>.json` | Each domain enables/disables discovery channels independently. |
| **Seed scoping** | `domains` field in `seed.json` + `seeds/seed-<domain>.json` | Seed rows are injected **scoped by domain**: only rows whose `domains` contain the current domain (or the domain's own seed file). A niche's seeds never leak into another. |
| **Relevance gate** | `analyze.py::run_channel` | A live-discovered URL is accepted **only if it contains a keyword** (normalized comparison; `balance bike` matches `forbalancebikes.com`). The old implementation also accepted "keyword appears in the query" — and queries are built from keywords, so the gate was always true, letting search-cache junk pollute the pool. |
| **Channel health** | `data_sources.discovery_channels.channels[].status` | `ok` / `empty` / **`off-topic`** (results returned but all irrelevant) / `error`. The panel shows `✓ hits/raw`. |
| **Blocklist** | `analyze.py::BLOCKED_DOMAINS` | Adult / gambling / ad-redirect domains never become candidates (subdomains included). |

```bash
# Create a profile for a new domain (edit profiles.json, or just save the form in the UI)
# Maintain the verified per-domain seed library
seeds/seed-<domain>.json
# Clean a historical pool: migrate/isolate entries that don't belong to the domain
python3 tools/migrate_pools.py --domain <domain> --apply --sanitize-legacy
# End-to-end selftest (real Chrome: channel table / domain switch / no cross-niche leak / sorting)
python3 tools/selftest.py https://backlink-prospector.fly.dev/
# Bilingual audit of every runtime-built string (157 checks, incl. in-page language toggle)
python3 tools/i18n_audit.py https://backlink-prospector.fly.dev/
# Delivery ledger: idempotency / evidence gate / exclusion / gap semantics / bilingual UI
python3 tools/placement_selftest.py https://backlink-prospector.fly.dev/
```

> `tools/migrate_pools.py` only **migrates** and **quarantines** (dropped entries go to
> `data/store.quarantine-<ts>.json` for audit) — nothing is silently deleted.

### D4. Sortable lists everywhere (one shared engine)

Every list in the UI sorts by clicking its headers, driven by one shared engine
(`SORT_TABLES` registry + `sortRows()` comparator):

| Page | Table | Sortable columns |
|---|---|---|
| Analyze | Results | domain / type / authority (Tranco) / relevance / authority score / obtainability / priority / valid / gap / note |
| Tips | Type weights | type / value weight / obtainability |
| Pool | Main pool table | domain / type / authority / priority / valid / status / times / first·last seen |
| Pool | Type distribution | type / discovered / acquired / gap |
| Backend | Discovery channels | channel / kind / enabled / interval / last results |
| Backend | Run history | time / domain / result / candidates / pool total |

Design notes:

- **Sort state lives in a registry, not the DOM** → it survives data reloads, domain switches, language switches and filter changes, along with the header arrows.
- String columns use `localeCompare(..., {numeric:true})` (`a10` sorts after `a9`); numeric/boolean columns compare directly; missing values sort last.
- Clicking the same column flips direction; a new column uses its natural order (domain/type ascending, scores/counts descending).
- Headers carry `aria-sort` and a `⇅` hint; text labels like value weight are mapped to numeric ranks before sorting.

### D5. Pool type tree · multi-select · status filters

The Pool page includes a **type tree** that organizes backlinks by type and doubles as a filter:

```
▾ All sites                    44  0  42
  ▾ Content & Reviews          12  0  12
    • Industry media            5  0   5
    • Guest post                3  0   3
    • Digital PR                0  0   0
    • Resource                  4  0   4
  ▾ Authority & Community       4  0   4
  ▾ Partners & Marketplaces     5  0   5
  ▾ Reciprocal (distinct type)  3  0   3   ← separate from directory
```

- **Tree**: root "All sites" + 4 type groups + 10 type leaves; each node shows `total / acquired / gap`.
- **Multi-select types**: click a leaf to toggle it (multi-select), a group node toggles the whole group, the root clears everything. The chip row beside the table stays in sync.
- **Status filter**: `Acquired` / `Gap` toggles, usable alone or together; both off shows everything.
- **Faceted counts**: node counts follow the status facet but **not** the type facet itself (standard faceting), so a count always equals "rows you'd see by clicking".
- **Full taxonomy always visible**: a type with 0 entries (e.g. reciprocal) still renders (dimmed), making "nothing collected for this type yet" obvious.
- Filters affect **display only**; pool data is untouched. "Mark acquired / unmark" lives in the table's Edit column.

---

### D6. Bilingual UI — dynamic output

The UI is Chinese by default with a one-click `EN` toggle. Static chrome uses
`data-i18n` + `applyLang()`; **every string built at runtime by a render
function** is covered by one replay pass:

- `renderAllDynamic()` is the single entry point invoked by the language toggle.
  It replays analysis results, pool stats/tree/chips/rows, tips, channels,
  scheduler status/profiles/run history, overview SVG labels, sort tooltips,
  center-domain labels and cached transient messages. Any new LANG-dependent
  renderer **must** be registered there, otherwise the previous language
  survives until the next data reload.
- Cached state (`LAST`, `POOL`, `SCHED`, `LAST_CHANNELS`, `LAST_PROFILE`,
  `TIPS`) avoids refetching during replay. Profile cards are rebuilt from the
  DOM with `collectProfileCards()`, so unsaved operator edits survive a switch.
- Transient text (error banner, import badge, in-progress button labels) is
  stored as `{zh, en}` pairs and re-translated, rather than frozen in the
  language that happened to be active when the event fired.
- Free-text data is bilingual at the source: seed rows carry `note` +
  `note_en`, tips carry `value_weight` / `value_weight_en` and
  `reciprocal_note` / `reciprocal_note_en`, profiles carry `note` / `note_en`,
  and the analysis result carries `limitations` (EN) / `limitations_zh`.
  `analyze.py::note_en()` degrades to a neutral English descriptor for legacy
  rows, so a Chinese-only operator note can never leak into EN mode.
- Attribute-level copy is part of the same contract: `data-i18n-ph`,
  `data-i18n-title` and `data-i18n-aria` drive `placeholder`, `title` and
  `aria-label`, and `applyLang()` also sets `document.title`. An innerText-only
  audit cannot see these strings, which is how a Chinese form hint once
  survived a switch to English.
- Bilingual payload pairs (type labels `type_label_zh/en`, channel
  `name_zh/name_en`, tips `zh/en`) are language-aware rather than jointly
  displayed: EN renders English only, ZH renders the Chinese primary with the
  English secondary line. Raw server diagnostics live in `data-raw` instead of
  a visible Chinese tooltip.
- **EN mode is CJK-free across the entire DOM** (text nodes plus placeholder /
  title / aria-label / alt). The sole whitelist is `#langToggle`, which shows
  the target language (中), not a UI string.

`tools/i18n_audit.py` drives real Chrome, loads every tab, then audits
ZH → EN → ZH including runtime states (error/busy messages, unsaved edits),
attribute copy and the DOM-wide zero-CJK assertion (157 assertions).

### D7. Delivery ledger — built once per domain, never reused after success

The pool is a **candidate list** ("seen"), not a record of what has been used.
The ledger is the single source of truth for "already delivered":

| Layer | Stored in | Meaning | Who writes |
|---|---|---|---|
| Candidate pool | `domains{}` in `data/store-<center_domain>.json` | prospect was discovered | analysis runs (append-only by domain) |
| Delivery ledger | `placements{}` in the same file | one record per delivery slot | operator actions only |
| Exclusions | `suppressions{}` | domain or exact slot permanently excluded | operator actions only |

`center_domain` is implied by the store filename, so isolation is unchanged and
no new field crosses niches. A slot key is
`sha256(target_domain | target_url | placement_type)[:16]` — **not the domain**,
so different pages on the same site remain usable resources.

State machine: `registered → claimed → submitted → live → lost`, with
`rejected` / `error` as terminal states. Reaching `live` requires
`landing_url` + `verify_method` as evidence; "clicked submit" is never success.

Exclusion rules (evaluated on every claim, `409` with a reason when blocked):

1. The exact slot already has a verified live backlink → permanent lock.
2. The slot is `claimed` / `submitted` → idempotent, no duplicate row.
3. `lost` → manual review required, never auto-returned to the queue.
4. `rejected` / `error` → cooldown until `cooldown_until` (default 90 days).
5. Any `live` / `submitted` on the same `target_domain` within 90 days → cadence window (grouped by domain, never by URL).
6. Explicit `suppressions` entry (domain or slot) → permanent exclusion.

`gap` is now computed against `owned_domains = live placements ∪
acquired_domains ∪ explicit import`. The old "whole pool is the existing
library" behaviour is still reproducible with `use_pool_as_existing=1` for
comparison, but defaults to off; scheduled runs pass `0` explicitly.

Endpoints: `GET /api/placements`, `GET /api/placements/csv`,
`POST /api/placements/claim`, `/claim-batch`, `/transition`, `/suppress`. The ledger CSV is
separate from the pool CSV and carries evidence columns, so the two layers
cannot be confused in an operator handoff.

`tools/placement_selftest.py` is the regression guard (state machine, HTTP
409 contract, gap semantics, bilingual real-Chrome rendering):
`python3 tools/placement_selftest.py https://backlink-prospector.fly.dev/`
Add `--no-write` when auditing production so the mutating endpoint section is
skipped and no throwaway ledger file lands on the Fly volume.

---

### D8. Competitor model — the competitor is not a backlink site, its backlinks are

One operator-supplied "competitor" list feeds two completely different entities:

| Entity | Treatment | Counting |
|---|---|---|
| The competitor host **itself** (subdomains too, e.g. `blog.compa.test`) | Dropped before validation: no HTTP probe, no pool entry, no gap | Reported only as `totals.competitor_rows` |
| Sites that **link to** a competitor | Ordinary candidates, admitted by evidence and exempt from the keyword gate | Counted in `totals.candidates` / `valid` / `gap`, tagged `source=competitor_backlink` |

"More competitors -> more valid backlinks" is not an identity: what is guaranteed is that more of the inbound surface gets scanned; the net gain depends on dedup and the quality gate.

**Evidence source (offline harvest).** `tools/competitor_backlinks.py` streams the Web Data Commons / Common Crawl host (or domain) edge table and runs one reverse query: which hosts point at my competitors. The graph is tens of GB, the image is ~37 MB, so the harvest runs offline and ships a compact, reviewable file with the image:

```bash
# 1) download a WDC release (domain-ranks + domain-edges, same crawl window)
# 2) reverse query: who links to my competitors
python3 tools/competitor_backlinks.py \
  --center soundbuttons.click \
  --competitors myinstants.com,voicemod.net \
  --ranks /data/wdc/cc-main-2025-may-aug-domain-ranks.txt.gz \
  --edges /data/wdc/cc-main-2025-may-aug-domain-edges.txt.gz \
  --out   seeds/competitor-links-soundbuttons.click.json
```

- Three streaming passes: ranks -> competitor ids, edges -> inbound edges grouped by source, ranks again -> resolve source ids to hostnames. Memory grows with hits, not with the graph.
- Quality gate: competitor hosts and their subdomains, the center domain, `BLOCKED_DOMAINS` and `NOISE_DOMAINS` are dropped; `--min-links N` requires at least N links.
- The output IS the evidence: each row carries `via_competitors[]` and `evidence{graph, edges, per_competitor}`. `type` is guessed from the hostname and flagged `type_guess=true` for review.
- An already-extracted edge list (`source,target[,count]`) works via `--from-csv`; `--dry-run` reports without writing.

Resolution order: `data/competitor-links-<domain>.json` (operator override) then `seeds/competitor-links-<domain>.json` (image-baked). When neither exists, `data_sources.competitor_backlinks.status` is `empty` and behaviour is identical to before.

### D9. Daily quota — a gate, not a gauge

`100/day` (configurable per center domain, 1–2000 via `POST /api/settings`) is enforced where a claim is written, not where a batch is displayed: `claim_placement` refuses anything past the ceiling (`409 daily quota reached`), and `claim-batch` reports `quota_blocked` for the rows it had to drop. The pool's single "Use" button goes through the same gate, so the number cannot be sidestepped. The quota day rolls at 00:00 **UTC+8** (`QUOTA_TZ_OFFSET`) and placement timestamps (stored UTC) are converted before comparison — slicing the timestamp string would misfile every claim made before 08:00 local into yesterday.

### D10. Whitelist — keep the record, drop the number

A whitelist entry is not a suppression. A suppression says "never offer this slot again"; a whitelist entry says "this domain exists in my data but must not move any backlink number" (own network, aggregators, mirrors, link farms).

| Layer | Effect |
|---|---|
| `store_stats` | Excluded from discovered / acquired / gap / gap & valid / type distribution / reciprocal ratio; reported separately as `whitelisted` |
| `domain_list` | Row stays visible (`whitelisted: true`, dimmed) so the toggle can be undone; `is_gap` forced to `false` |
| `daily_queue` | Block reason `whitelisted`; never enters a batch |
| `claim_placement` | Refused: a link there can never be counted, so the work would be invisible |
| `analyze` | Prospects on whitelisted hosts are tagged `whitelisted` and are not counted as gap |

Hosts are normalized on the way in (`https://www.Foo.com/x` -> `foo.com`), junk is rejected rather than stored, and the list is per center domain (`whitelist` in `data/store-<domain>.json`). The UI exposes a toggle on every record — pool row, analysis row, ledger row — plus a bulk paste box in the Pool tab.

---

## 3. Free Data Sources (no API keys required)

| Source | Role | Notes |
|---|---|---|
| **seed_library** | Seed library of real prospects (manually verified, **injected per center domain**) | Primary channel; `domains` field in `seed.json` + `seeds/seed-<domain>.json`; every row HTTP-validated during analysis |
| **bing_rss / bing_cite / ddg_html** | Live keyword×type search for prospects | Free, no keys; **results must match keywords** to be accepted; channel status distinguishes `ok`/`off-topic`/`empty`/`error` |
| **tranco** | Free popularity ranking as an authority signal | `tranco_global_rank` field; commercial DR/DA reported as `unavailable` |
| **local_backlinks** | Import existing backlinks for a **true gap diff** | Paste GSC/Ahrefs/Common Crawl exports; zero network |

> Free live search behaves very differently per network: datacenter IPs frequently get
> Bing/DuckDuckGo **cached results unrelated to the query**. The gate therefore requires
> the keyword to appear in the result URL; junk is rejected and marked `off-topic`, and
> **never enters the pool**. The scoped seed library is the stable, primary channel; live
> search is a bonus.

---

## 4. Running

```bash
cd backlink-prospector
python3 server.py --port 8787
# open http://127.0.0.1:8787
```

- `POST /api/analyze` → JSON (`prospects[]`, `totals`, `data_sources`, `limitations`; with `pool_merged`/`pool_stats` when `persist=1`)
- `POST /api/analyze/csv` → CSV attachment
- `GET  /api/tips` → bilingual type/weight/reciprocal/scoring/periodic notes
- `GET  /api/store` → pool + stats (discovered / acquired / gap / gap & valid)
- `GET  /api/store/csv` → pool CSV attachment
- `POST /api/store/sync-existing` → import existing backlinks (body `{domains}`) to mark `acquired`
- `GET  /api/placements?domain=<domain>` → delivery ledger records + stats (D7)
- `GET  /api/placements/csv?domain=<domain>` → ledger CSV with evidence columns
- `POST /api/placements/claim` → claim one slot (`409` + reason when excluded)
- `POST /api/placements/claim-batch` → claim many slots at once (`center_domain` + `items[]`); idempotent per slot, blocked rows reported, not aborted
- `POST /api/placements/transition` → advance state; `live` requires evidence
- `POST /api/placements/suppress` → permanently exclude a domain or slot
- `GET  /api/profiles?domain=<domain>` → the domain's keyword/competitor profile
- `POST /api/profiles` → save a profile (body `{center_domain, keywords, competitors}`)
- `GET  /api/schedule` → scheduler state (config / status / runs)
- `POST /api/schedule` → save schedule (body `{enabled, interval_hours, profiles[]}`)
- `POST /api/schedule/run` → run all profiles now (body `{}`)
- `GET  /api/domains` -> every center domain this workspace knows (profiles / seeds / pools / competitor harvests), feeds the top-bar picker
- `GET  /api/health` · `GET /api/providers`
- `GET  /help` → standalone operator help page (`assets/help.html`; bilingual via
  `?lang=en|zh`). The app links to it from the top bar, and every tab carries its
  own `💡 Tips` toggle that expands the matching section inline.

Request body (`/api/analyze`):
```json
{
  "domain": "soundbuttons.cc",
  "center_domain": "soundbuttons.cc",
  "keywords": "soundboard, sound buttons, sound effects, meme soundboard, funny sounds",
  "competitors": "twowheelingtots.com\nrascalrides.com",
  "existing": "one existing-backlink domain per line (for this run's true gap diff)",
  "use_bing": "1", "use_tranco": "1", "persist": "1"
}
```

> `center_domain` decides which domain's pool the data lands in; empty `keywords` falls
> back to that domain's saved profile.

---

## 5. CSV Fields

**Analysis CSV (`/api/analyze/csv`)**:
`url, domain, type_key, type_label_zh, type_label_en, authority_tier, relevance, authority_score, obtainability, priority, valid, http_status, is_gap, is_competitor, already_have, tranco_global_rank, source, note, note_en`

- `valid`: real HTTP reachability at analysis time (`true` = reachable; 403/401/429 treated as existing-but-blocking; 404/timeout as dead).
- `source`: `seed` (seed library) or `bing_discovery` (live discovery).
- `note` / `note_en`: the Chinese and English operator note (both exported so a CSV is language-independent).

**Pool CSV (`/api/store/csv`)**:
`domain, url, type_key, type_label_zh, authority_tier, tranco_global_rank, priority, valid, http_status, acquired, is_gap, times_discovered, first_seen, last_seen`

- `acquired`: imported as a real existing backlink (`true` = owned).
- `is_gap`: still an open gap (`acquired` is `false`).

**Ledger CSV (`/api/placements/csv`)** — one row per delivery slot, kept
separate from the candidate list above:
`id, target_domain, target_url, placement_type, own_url, state, batch_id, created_at, claimed_at, submitted_at, live_at, lost_at, rejected_at, error_at, cooldown_until, failure_reason, verify_method, landing_url, observed_href, rel, anchor_text, verified_at, note`

- `state`: `live` means a verified backlink and permanently locks the slot.
- `verify_method` / `landing_url` / `verified_at`: the evidence that makes `live` auditable.

---

## 6. Honest Limitations

- Commercial metrics (DR/DA, backlink counts) are **never estimated**; missing values are `unavailable`.
- Gap analysis depends on **imported existing backlinks**; without an import, every non-competitor candidate counts as an open gap.
- Live discovery is best-effort: some egress IPs get **cached search results unrelated to the query**; these are rejected by the relevance gate (channel status `off-topic`) and **never enter the pool**; results then rely on the domain's scoped seed library.
- Extending candidates: add seed rows for the domain (`domains` field in `seed.json`) or create `seeds/seed-<domain>.json`; or enable more free providers in `providers.json` (e.g. a self-hosted Common Crawl web-graph service behind `local_backlinks`).
- The scheduler is a **daemon thread inside the server process**: it stops when the server stops (a single-host dev tool, not a distributed queue). For 24/7, run `python3 server.py --port 8787` under systemd / pm2 / nohup.
- Pool writes use atomic replace (`os.replace`), but two high-frequency concurrent writes have a tiny last-writer-wins window; irrelevant in normal use.

## 7. License

[MIT](LICENSE) © 2026 hhool
