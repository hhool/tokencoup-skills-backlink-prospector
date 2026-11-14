# Troubleshooting · Backlink Prospector

> 中文版：[TROUBLESHOOTING.zh.md](TROUBLESHOOTING.zh.md)

> The premise of the former "CACHE_CLEAR_GUIDE.md" ("the browser cached the old page")
> turned out to be **wrong**: the real root cause was `applyLang()` overwriting elements
> that carry `data-i18n` via `innerHTML`, destroying the `#chCount` badge node inside,
> which made `renderChannels()` hit its null guard and return — so the channel table
> stayed empty forever. Fixed, with regression protection added.

## 1. Empty channel table

| Symptom | What to check |
|---|---|
| No rows under "Discovery channels" | Open DevTools Console for `[loadChannels] Error:`; check that `/api/channels` returns 200 in the Network tab |
| `/api/channels` returns 200 with non-empty `channels`, but the table stays empty | The page script is stale. The server already sends `Cache-Control: no-store, no-cache, must-revalidate` on every response; if that is not enough, open a private window |

```bash
curl -s "https://backlink-prospector.fly.dev/api/channels?domain=<domain>" | python3 -m json.tool
```

## 2. Keywords/competitors don't change after a domain switch

The system works from per-domain profiles: `profiles.json` provides defaults; edits in
the UI are written to `data/profile-<domain>.json`.

```bash
curl -s "https://backlink-prospector.fly.dev/api/profiles?domain=balancebiketoddler.com" | python3 -m json.tool
```

- If it returns `source: "none"` → the domain has no profile yet; filling the keyword form once auto-saves it.
- If the form was filled but nothing changed → check the browser console for `[loadProfile]` errors.

## 3. Analysis results unrelated to the domain

**Results can no longer leak across niches**: seeds are injected scoped by `domains`,
and live-discovery results must match a keyword.

If results look irrelevant, check in order:

1. `data_sources.seed_library.scope` — should show `seeds/seed-<domain>.json` or `seed.json (domains=<domain>)`.
2. `data_sources.discovery_channels.channels[]` — `status: off-topic` means the channel returned only unrelated cache junk (rejected, not pooled); add seeds for that domain.
3. Whether the keywords are right: `GET /api/profiles?domain=<domain>`.

## 4. Junk domains in the pool

Historical data produced while the relevance gate was broken can be cleaned with the
migration tool — **quarantined, never deleted**:

```bash
flyctl ssh console -a backlink-prospector \
  -C "sh -c 'python3 tools/migrate_pools.py --domain <domain> --apply --sanitize-legacy'"
```

Removed entries go to `data/store.quarantine-<ts>.json`, auditable and reversible.

## 5. End-to-end selftest

```bash
python3 tools/selftest.py http://127.0.0.1:8787/
python3 tools/selftest.py https://backlink-prospector.fly.dev/
```

Covers: no console errors, ≥3 channel rows, domain switch swaps keywords, no cross-niche leak, sorting and tree filters.

## 6. Deployment notes

- `data/` is excluded by `.dockerignore` and mounted as a Fly volume → **`data/` inside
  the image is invisible**. Niche seed libraries shipped with the code therefore live in
  `seeds/` (baked into the image); `data/` holds runtime state only.
- `profiles.json`, `channels.json`, `seed.json` must appear in the Dockerfile `COPY`
  list, otherwise the app falls back to empty defaults.
- **A new `.py` module must be added to the Dockerfile too** — the `COPY` line is an
  explicit list, not `COPY . .`. Symptom: local runs and the selftest are green,
  `fly deploy` reports `smoke checks failed: the app appears to be crashing`, and
  `fly logs` shows `ModuleNotFoundError: No module named 'xxx'` (the machine boots,
  the module-level import fails).
- **`import server` starts a scheduler thread**: `server.py` builds `Scheduler` at
  module level and the constructor calls `start()`. A test or one-off script that
  imports it will run analyses (and even auto-refills) against the real
  `data/schedule.json`, writing into real stores. Set `BP_NO_SCHEDULER=1` or pass
  `Scheduler(..., autostart=False)`. The selftest does exactly that.

## 7. Auto refill / scheduled analysis never runs online

| Symptom | Cause and fix |
|---|---|
| Cooldown or interval elapses, nothing happens | Fly scales to zero: a stopped machine has no scheduler thread. Either visit the page to wake it, or deploy the external wake-up (see `USAGE.md` 3.15): `fly secrets set BDL_TRIGGER_TOKEN=...` plus the GitHub Actions job knocking on `POST /api/cron/tick` |
| `POST /api/cron/tick` returns `503` | The server has no `BDL_TRIGGER_TOKEN`. This is a **deliberate fail closed**: on a public address, no lock means anyone can spend your quota |
| Returns `401` / `403` | The `X-BDL-Trigger` header is missing or wrong; the value on Fly and the repository Actions secret must be the same |
| The GitHub Actions job retries and fails | `000/502/503/504` are retried (cold start); 4xx fails immediately — read the response body, it is usually a missing or wrong secret |
| The scheduled workflow silently stops firing | GitHub disables scheduled workflows after 60 days without a commit; one manual dispatch from the Actions page re-enables it |

## 8. Every API call suddenly 401 / 403

Once `BDL_API_TOKEN` is set, all `/api` calls except the pages, `/help`, `/api/health` and `/api/cron/tick` must carry the `X-BDL-Token` header.

| Symptom | Fix |
|---|---|
| The page opens a "this API is token-protected" prompt | Paste the `BDL_API_TOKEN` value (stored in localStorage, once); to fix a typo, clear `localStorage.bdlToken` and reload |
| 401 everywhere but no prompt | The prompt fires once per page load to avoid loops — reload the page |
| The selftest 401s across the board | Add `--token=<BDL_API_TOKEN>`; unnecessary for a local server without the variable |
| Health check failing, machine restarting | Should not happen — `/api/health` is always open; if it does, the deployed code is stale |
| Want auth off temporarily | `fly secrets unset BDL_API_TOKEN -a backlink-prospector` (back to open mode after restart) |
