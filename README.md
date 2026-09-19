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
       data/snapshots/<date>.json  (that day's full pull, one file per day --
                                    never appended to, so looking up a past
                                    month never means downloading every day
                                    ever recorded)
       data/latest.json            (a copy of the newest snapshot file)
       data/summary.jsonl          (one small, compact aggregate row per day
                                    -- by-status counts, by-county totals,
                                    HIGH-risk counts per attribute, and a
                                    risk-level distribution per category.
                                    Stays small forever; this is what the
                                    month filter on every page actually reads,
                                    so picking a month never re-downloads
                                    full per-system data)
       data/changes.jsonl          (one line per detected FINAL_SAFER_STATUS
                                    change, with a full field-level diff of
                                    everything else that changed alongside it)
  -> commits and pushes the changes
GitHub Pages
  -> serves the five pages below, each of which fetches the relevant data/*
     file(s) directly and renders client-side. No backend, no build step.
```

Every day's snapshot is both its own dated file under `data/snapshots/`
**and** a git commit -- two independent layers of history, so "prove this
system was Failing on date X" has an actual, checkable, dated record behind
it (both the raw snapshot and the commit timestamp).

### The month filter

Statewide Trends and Failing System Details both have a "Viewing" dropdown.
Picking a month doesn't just relabel the page -- every KPI, the status
breakdown, the most-common-high-risk-attributes list, and the
currently-failing table all recompute from that month's actual recorded
data (`data/summary.jsonl` for the aggregates, a lazy on-demand fetch of
that one day's `data/snapshots/<date>.json` for the system-level table).
Nothing about those numbers is hardcoded to "today" -- they're genuinely
derived from whichever month is selected, the same way "today's" numbers
are.

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

`data/snapshots/` currently holds real data, not placeholder data: **17 days
of full daily snapshots (Sep 2-18, 2026, ~3,190 systems/day)**, backfilled
from a Dataverse "SaferSnapshotHistory" export via
`scripts/backfill_from_snapshot_history.py`. That script rebuilds the
`snapshots/` files, `summary.jsonl`, `latest.json`, and `changes.jsonl` from
scratch by treating the export as ground truth and diffing consecutive days
itself -- it's authoritative over the change-events-only import
(`scripts/backfill_changes_from_export.py`), which is kept for whenever a
newer change-events-only export shows up without a matching full-snapshot
export alongside it. See `data/README.md` for the details and for how to
re-run either one against a new export.

One real gap worth naming: this backfilled history has status, population,
economic status, and failing-start-date per day, but not the underlying
Failing-criteria fields (which specific violation, if any), the risk-
assessment attribute/category detail, or system locations. That detail only
starts accumulating once `fetch_snapshot.py` runs for real against the live
wide flat file -- pages that depend on it (Most Common High-Risk Attributes,
Risk Categories & Failing Criteria, the location maps) say so plainly for
any date that predates it, rather than showing misleading zeros.

**Note on the resource ID**: the value visible in your original screenshot
(`25887bb-5451-4c19-8e35-27899ae8c3ad`) was missing a leading digit. I
verified the correct id (`255887bb-...`) independently against the dataset's
public listing on data.ca.gov, rather than by guessing -- but since I
couldn't call the live API from my own environment (blocked by network
policy there, not a problem for GitHub's servers), treat the first real
workflow run as the actual confirmation.

## The five pages

- **`system-lookup.html` -- Look up a system.** Filter by county, current
  status, economic status, or name; see one system's status-over-time
  timeline, its full change history, stat tiles (first Failing date, most
  recent change, changes in the past 12 months, days since last change), its
  Risk Categories & Failing Criteria breakdown (the 4 SAFER risk categories
  and their 21 underlying indicators), and an approximate map of its
  location. Each change row has a "What changed?" toggle showing the
  field-level diff behind it.
- **`index.html` -- Statewide trends.** KPI tiles, changes by month, a
  histogram of how many times systems change, most common status
  transitions, top counties, the statewide status breakdown (count + percent
  per status), a top-systems-by-changes table, and a location map colored by
  status. Has the month filter -- see above.
- **`failing-focus.html` -- Failing System Details.** 4 KPI cards (systems
  failing, share of systems, share of population, counties affected),
  failing-systems-and-population-affected over time, the real Most Common
  High-Risk Attributes ranking, and the current failing-systems table. Has
  the month filter -- see above.
- **`what-changed.html` -- Deeper dive on changes.** Aggregates the field-level diffs
  across every tracked change to answer "what usually pushes a system into
  Failing" and "what usually resolves it," plus a filterable, drill-into-any-event
  table of recent changes statewide.
- **`about.html` -- About this page.** What the tool does, what the four
  statuses mean, how it's built, real coverage numbers (system count, dates
  tracked since), and data-quality caveats.

All five share `assets/style.css` and `assets/common.js`, and a nav bar links
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

- **Repo size**: each `data/snapshots/<date>.json` file stores every column
  for every system for that one day (~5-6 MB per day once the live API is
  the source, since it's a wide ~140-column table). That adds up over a
  year, but unlike the old single-ever-growing-file design, no page load
  ever has to download more than one day's worth of it -- `summary.jsonl`
  (small, one compact row per day, forever) is what every KPI, chart, and
  the month filter actually depend on day to day. If `data/snapshots/`
  becomes a repo-size concern down the line, older files can be moved to a
  separate archive branch or storage without breaking anything: no page
  reads more than the latest snapshot plus whichever one date the month
  filter is currently showing.
- **If a fetch fails** (data.ca.gov downtime, schema change, etc.), the
  workflow run fails and shows up in the Actions tab; the dashboard just
  keeps showing the last successful snapshot until the next run succeeds.
- **The Risk Assessment fields only change quarterly**, so most days'
  `field_diffs` will be empty or Failing-criteria-only even when a status
  changes -- that's expected, not a bug.
