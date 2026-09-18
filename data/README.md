This directory is normally populated automatically by the GitHub Actions
workflow (`.github/workflows/fetch-snapshot.yml`), which runs
`scripts/fetch_snapshot.py` once a day. Right now it contains real
backfilled data instead:

- `history.jsonl` — **17 real daily snapshots, September 2-18, 2026**
  (~3,190 systems/day: status, population, economic status, failing-start
  date), imported from a Dataverse "SaferSnapshotHistory" export via
  `scripts/backfill_from_snapshot_history.py`.
- `summary.jsonl` — the daily aggregate rows derived from that same import
  (total systems, currently-failing count, population in failing systems,
  breakdown by status) -- one real row per day, Sep 2-18.
- `latest.json` — the September 18 snapshot from that same import: a real,
  complete pull (3,190 systems), not the earlier 131-system partial one
  derived only from change events (that approach is retired now that a real
  snapshot exists; `scripts/derive_latest_from_changes.py` still exists as a
  fallback for the case where you only have a change-events export with no
  matching full-snapshot export).
- `changes.jsonl` — **134 real status-change events**, regenerated from
  scratch by diffing consecutive days in the snapshot-history import (this
  matches the count from the separate change-events export, which is a good
  cross-check that both sources agree). Each event's `field_diffs` covers
  what that import actually tracked -- status, population, economic status,
  failing-start-date -- but not the underlying violation-level criteria
  (the source system wasn't capturing those). Every change detected going
  forward by `fetch_snapshot.py` against the live wide flat file will
  include that fuller detail.

**The first real run of `fetch_snapshot.py` against the live API** appends
to `history.jsonl`/`summary.jsonl`/`changes.jsonl` and overwrites
`latest.json`, picking up right where this backfill leaves off (Sep 19
onward) -- it doesn't need to know or care that the earlier days came from
an import rather than its own runs.

## Re-running a backfill against a new export

If you get another export later:

- A **full snapshot-history export** (has a per-day `snapshotdate` column,
  one row per system per day) -- rebuild everything from it:
  ```bash
  python3 scripts/backfill_from_snapshot_history.py path/to/new_export.csv
  ```
  This treats the export as ground truth and **regenerates**
  `history.jsonl`/`summary.jsonl`/`changes.jsonl`/`latest.json` from
  scratch, so make sure the export covers the full period you want kept
  (it doesn't merge with what's already there).

- A **change-events-only export** (no per-day snapshot, just
  from-status/to-status/date rows) -- merge it in additively instead:
  ```bash
  python3 scripts/backfill_changes_from_export.py path/to/new_export.csv
  ```
  This one dedupes against what's already in `changes.jsonl` and only adds
  genuinely new rows, but it can't touch `history.jsonl`, `summary.jsonl`,
  or `latest.json` since it has no full-snapshot data to build those from.
