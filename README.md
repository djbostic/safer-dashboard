# CA SAFER Drinking Water Dashboard

## Why this exists

California's SAFER Dashboard only shows *current* status. It doesn't publish
a dated, public archive of daily snapshots. That's a real problem for water
systems and Technical Assistance Providers (TAPs): if a system's status
flips from Failing to Potentially At-Risk the week before a grant deadline,
there's no public record proving it *was* Failing, which is often exactly
what eligibility or prioritization depends on.

This project is that archive, built for free, plus a set of views on top of
it: it replaces the Power Automate flow (Recurrence -> Initialize variable ->
HTTP GET against data.ca.gov) and Power BI dashboard shown in the original
screenshots.

## How it works

```
GitHub Actions (daily cron)
  -> scripts/fetch_snapshot.py
  -> calls data.ca.gov's CKAN datastore_search_sql API (SELECT * -- see below)
  -> writes/updates:
       data/latest.json     (today's full pull, overwritten daily)
       data/summary.jsonl   (one small aggregate row per day, for trend charts)
       data/history.jsonl   (one line per day, full pull -- the long-term archive)
       data/changes.jsonl   (one line per detected FINAL_SAFER_STATUS change,
                             with a full field-level diff of everything else
                             that changed alongside it)
  -> commits and pushes the changes
GitHub Pages
  -> serves the four pages below, each of which fetches the relevant data/*
     file directly and renders client-side. No backend, no build step.
```

Every day's snapshot is both an explicit row in the `data/*.jsonl` files
**and** a git commit -- two independent layers of history, so "prove this
system was Failing on date X" has an actual, checkable, dated record behind
it (both the raw snapshot and the commit timestamp).

### Why `SELECT *` instead of a fixed field list

The resource this pulls from -- the CKAN resource id
`255887bb-5451-4c19-8e35-27899ae8c3ad`, publicly listed as the
[Drinking Water Risk Assessment Public Flat File](https://data.ca.gov/dataset/safer-failing-and-at-risk-drinking-water-systems/resource/255887bb-5451-4c19-8e35-27899ae8c3ad)
-- is a wide table. It carries both the Failing list (refreshed daily,
governed by the
[HR2W expanded Failing criteria](https://www.waterboards.ca.gov/water_issues/programs/hr2w/docs/hr2w_expanded_criteria.pdf):
MCL violations, E. coli violations, treatment technique violations,
monitoring/reporting violations, source capacity violations, each tied to
enforcement-action status) and the Risk Assessment (refreshed quarterly,
governed by the
[Risk Assessment methodology](https://www.waterboards.ca.gov/drinking_water/certlic/drinkingwater/documents/needs/2025/2025risk-assessment-pws-methodology.pdf):
Water Quality / Accessibility / Affordability / TMF Capacity category
scores and their underlying indicators). Pulling every column, rather than a
hand-picked handful, is what lets `scripts/fetch_snapshot.py` generically
diff a system's entire record day over day and surface *which specific
field* moved when its status changed -- without this script needing to be
kept in sync with the state's internal column names by hand.

## Backfilled history

`data/` currently holds real data, not placeholder data: **17 days of full
daily snapshots (Sep 2-18, 2026, ~3,190 systems/day)**, backfilled from a
Dataverse "SaferSnapshotHistory" export via
`scripts/backfill_from_snapshot_history.py`. That script rebuilds
`history.jsonl`, `summary.jsonl`, `latest.json`, and `changes.jsonl` from
scratch by treating the export as ground truth and diffing consecutive days
itself -- it's authoritative over the change-events-only import
(`scripts/backfill_changes_from_export.py`), which is kept for whenever a
newer change-events-only export shows up without a matching full-snapshot
export alongside it. See `data/README.md` for the details and for how to
re-run either one against a new export.

One real gap worth naming: this backfilled history has status, population,
economic status, and failing-start-date per day, but not the underlying
Failing-criteria fields (which specific violation, if any). That detail
only starts accumulating once `fetch_snapshot.py` runs for real against the
live wide flat file -- see "What Changed" on the dashboard for how that
shows up (or doesn't yet) in practice.

**Note on the resource ID**: the value visible in your original screenshot
(`25887bb-5451-4c19-8e35-27899ae8c3ad`) was missing a leading digit. I
verified the correct id (`255887bb-...`) independently against the dataset's
public listing on data.ca.gov, rather than by guessing -- but since I
couldn't call the live API from my own environment (blocked by network
policy there, not a problem for GitHub's servers), treat the first real
workflow run as the actual confirmation.

## The four pages

- **`index.html` -- Statewide trends.** Changes this week / trailing 12
  months, systems changed at least once, changes by month, a histogram of
  how many times systems change, most common status transitions, top
  counties, and a top-20-most-volatile-systems table.
- **`system-lookup.html` -- Look up a system.** Filter by county, current
  status, or name; see one system's status-over-time chart, its full change
  history, and stat tiles (first Failing date, most recent change, changes in
  the past 12 months, days since last change) -- mirrors your existing
  Power BI page. Each change row has a "What changed?" toggle showing the
  field-level diff behind it.
- **`failing-focus.html` -- Failing systems focus.** The view built first:
  failing-system counts and population-affected over time, status breakdown,
  top counties, and the current failing-systems table.
- **`what-changed.html` -- What changed.** Aggregates the field-level diffs
  across every tracked change to answer "what usually pushes a system into
  Failing" and "what usually resolves it," plus a filterable, drill-into-any-event
  table of recent changes statewide.

All four share `assets/style.css` and `assets/common.js`, and a nav bar links
between them.

## One real limitation, stated plainly

None of this can see the past. Status-change history, and the field-level
"what changed" diffs, only start accumulating from whenever the workflow
first runs -- there's no way to retroactively reconstruct what the state's
data looked like on a date before this tool existed. Every page says so
where it's showing example data. The earlier a TAP or water system starts
running this, the further back its proof extends.

## Setup

### 1. Create the GitHub repo

```bash
cd safer-dashboard
git init
git add .
git commit -m "Initial SAFER dashboard"
gh repo create safer-dashboard --public --source=. --push
# or: create the repo on github.com, then git remote add origin <url> && git push -u origin main
```

It needs to be a **public** repo for GitHub Pages to be free; a private repo
requires GitHub Pro ($4/mo) for Pages.

### 2. Seed real data (don't wait for tomorrow's cron)

In the repo on github.com: **Actions tab -> "Daily SAFER snapshot" -> Run workflow**.
This runs `fetch_snapshot.py` once immediately. Because change detection
needs a *previous* day to diff against, `data/changes.jsonl` will still be
empty after this first run -- run it again a day later (or just let the
schedule take over) to get your first real change event.

### 3. Turn on GitHub Pages

Repo **Settings -> Pages**:
- Source: "Deploy from a branch"
- Branch: `main`, folder: `/ (root)`

Your dashboard is now live at `https://<your-username>.github.io/safer-dashboard/`.

### 4. Point dashboard.darcybostic.com at it

Still in **Settings -> Pages**, under "Custom domain," enter
`dashboard.darcybostic.com` and save (the `CNAME` file in this repo already
has this value, so GitHub should pick it up automatically -- this step just
confirms it and lets GitHub provision HTTPS for it).

Then, wherever darcybostic.com's DNS is managed (a separate setting from
whatever platform the rest of the site is built on -- check your domain
registrar, e.g. Squarespace Domains, GoDaddy, Namecheap, Cloudflare, or
Google Domains), add:

| Type  | Host/Name    | Value                  |
|-------|--------------|-------------------------|
| CNAME | `dashboard`  | `<your-username>.github.io` |

DNS changes can take anywhere from a few minutes to a few hours to propagate.
Once it resolves, check "Enforce HTTPS" back in Settings -> Pages.

This doesn't touch or interfere with whatever's currently running the rest
of darcybostic.com -- it's a separate subdomain pointed at a separate,
independent site.

## Maintenance notes

- **Repo size**: `history.jsonl` now stores every column for every system,
  every day (previously just 9 fields), so it grows faster than the earlier
  version of this project. `summary.jsonl` and `changes.jsonl` stay small
  regardless and are what the dashboards actually depend on day to day, so
  if `history.jsonl` ever becomes a size concern, it can be pruned or moved
  to quarterly archives without breaking any of the four pages.
- **If a fetch fails** (data.ca.gov downtime, schema change, etc.), the
  workflow run fails and shows up in the Actions tab; the dashboard just
  keeps showing the last successful snapshot until the next run succeeds.
- **The Risk Assessment fields only change quarterly**, so most days'
  `field_diffs` will be empty or Failing-criteria-only even when a status
  changes -- that's expected, not a bug.
