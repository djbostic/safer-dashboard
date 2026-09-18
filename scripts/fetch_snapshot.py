#!/usr/bin/env python3
"""
Daily snapshot fetcher for the CA SAFER drinking water dataset (data.ca.gov).

Replaces the Power Automate flow (Recurrence -> Initialize variable -> HTTP GET)
shown in the original screenshot. Run by the GitHub Actions workflow in
.github/workflows/fetch-snapshot.yml on a daily schedule.

Why this exists: the state does not publish a dated, public archive of daily
SAFER status -- only the current snapshot. That makes it hard for water
systems and Technical Assistance Providers to *prove* a system was Failing
(or wasn't) on a specific past date for grant eligibility purposes. This
script builds that archive, one commit at a time.

What it does:
  1. Queries the CKAN datastore_search_sql API for the full SAFER risk
     assessment flat file (SELECT * -- see note below on why).
  2. Tags every row with today's snapshot date.
  3. Diffs today's pull against yesterday's (data/latest.json, before it gets
     overwritten), system by system, and:
       - whenever FINAL_SAFER_STATUS changes, logs a change event to
         data/changes.jsonl
       - attaches a generic field-level diff to that event (every column
         whose value differs between yesterday and today for that system) --
         this is what identifies *which specific criterion* moved a system
         across a status boundary, without this script needing to know the
         state's internal column names ahead of time.
  4. Appends one line (a JSON array of all rows for that day) to data/history.jsonl.
  5. Overwrites data/latest.json with the freshest pull (used by the dashboard
     for "as of today" views).
  6. Appends one aggregate summary row to data/summary.jsonl (small file, used
     for the trend-over-time charts).

Why SELECT * instead of a fixed field list: the Failing list (updated daily)
and the Risk Assessment (Water Quality / Accessibility / Affordability / TMF
Capacity categories and their underlying indicators, refreshed quarterly) live
in the same flat file. Pulling everything, rather than a hand-picked handful
of fields, is what makes the "what specifically changed" comparison possible
without this script having to be kept in sync with the state's schema by
hand. It costs a bit more storage; see README for the tradeoff.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import date, datetime, timezone

# --- Configuration -----------------------------------------------------

# CKAN resource id for the "Drinking Water Risk Assessment Public Flat File"
# (the SAFER Dashboard's Failing + At-Risk systems table). Verified against
# the dataset's public listing on data.ca.gov -- this corrects a transcription
# error from the original screenshot (which was missing a leading digit:
# "25887bb-..." rather than "255887bb-...").
RESOURCE_ID = os.environ.get("SAFER_RESOURCE_ID", "255887bb-5451-4c19-8e35-27899ae8c3ad")

BASE_URL = "https://data.ca.gov/api/3/action/datastore_search_sql"

# Columns that exist on every CKAN datastore row or that we add ourselves --
# never meaningful as a "this changed" diff, so excluded from field_diffs.
IGNORE_FIELDS = {"_id", "_full_text", "snapshot_date"}

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")
SUMMARY_PATH = os.path.join(DATA_DIR, "summary.jsonl")
CHANGES_PATH = os.path.join(DATA_DIR, "changes.jsonl")


def fetch_rows():
    sql = f'SELECT * FROM "{RESOURCE_ID}"'
    url = f"{BASE_URL}?{urllib.parse.urlencode({'sql': sql})}"

    req = urllib.request.Request(url, headers={"User-Agent": "safer-dashboard-snapshot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if not payload.get("success"):
        raise RuntimeError(f"CKAN API returned an error: {payload}")

    return payload["result"]["records"]


def load_previous_latest():
    if not os.path.exists(LATEST_PATH):
        return None
    with open(LATEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def field_diffs(prev_row, new_row):
    """Every column whose value differs between the two rows, excluding
    housekeeping fields. Returns {field: {"from": ..., "to": ...}}."""
    keys = (set(prev_row.keys()) | set(new_row.keys())) - IGNORE_FIELDS
    diffs = {}
    for k in keys:
        old_val = prev_row.get(k)
        new_val = new_row.get(k)
        if str(old_val) != str(new_val):
            diffs[k] = {"from": old_val, "to": new_val}
    return diffs


def detect_changes(previous, rows, snapshot_date):
    """Compare today's rows to yesterday's latest.json. Returns a list of
    per-system FINAL_SAFER_STATUS change events, each carrying a full
    field-level diff of everything else that changed alongside it."""
    if not previous:
        return []

    prev_by_id = {r["WATER_SYSTEM_NUMBER"]: r for r in previous.get("records", [])}
    changes = []
    for r in rows:
        wsn = r.get("WATER_SYSTEM_NUMBER")
        prev_row = prev_by_id.get(wsn)
        if prev_row is None:
            continue  # system newly appearing in the dataset; no "from" status to diff against
        old_status = (prev_row.get("FINAL_SAFER_STATUS") or "").strip()
        new_status = (r.get("FINAL_SAFER_STATUS") or "").strip()
        if old_status and new_status and old_status != new_status:
            changes.append({
                "date": snapshot_date,
                "water_system_number": wsn,
                "system_name": r.get("SYSTEM_NAME"),
                "county": r.get("COUNTY"),
                "from_status": old_status,
                "to_status": new_status,
                "field_diffs": field_diffs(prev_row, r),
            })
    return changes


def summarize(rows, snapshot_date):
    by_status = {}
    failing_count = 0
    population_in_failing = 0
    for r in rows:
        status = (r.get("FINAL_SAFER_STATUS") or "Unknown").strip()
        by_status[status] = by_status.get(status, 0) + 1
        if str(r.get("CURRENT_FAILING", "")).strip().lower() in ("y", "yes", "true", "1"):
            failing_count += 1
            try:
                population_in_failing += int(r.get("POPULATION") or 0)
            except (TypeError, ValueError):
                pass

    return {
        "date": snapshot_date,
        "total_systems": len(rows),
        "currently_failing": failing_count,
        "population_in_failing_systems": population_in_failing,
        "by_status": by_status,
    }


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def main():
    snapshot_date = os.environ.get("SNAPSHOT_DATE_OVERRIDE") or date.today().isoformat()

    try:
        rows = fetch_rows()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR fetching SAFER data: {exc}", file=sys.stderr)
        sys.exit(1)

    for r in rows:
        r["snapshot_date"] = snapshot_date

    os.makedirs(DATA_DIR, exist_ok=True)

    previous = load_previous_latest()

    # 1. Detect and log status-change events (must happen before latest.json
    #    is overwritten, since it diffs against yesterday's copy of it).
    changes = detect_changes(previous, rows, snapshot_date)
    for change in changes:
        append_jsonl(CHANGES_PATH, change)

    # 2. Append today's full snapshot to the running history log.
    append_jsonl(HISTORY_PATH, {"date": snapshot_date, "records": rows})

    # 3. Overwrite "latest" for the dashboard's current-state views.
    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"date": snapshot_date, "fetched_at": datetime.now(timezone.utc).isoformat(), "records": rows},
            f,
            indent=2,
        )

    # 4. Append a small aggregate row for trend charts.
    append_jsonl(SUMMARY_PATH, summarize(rows, snapshot_date))

    print(f"OK: {len(rows)} records snapshotted for {snapshot_date}, {len(changes)} status change(s) detected")


if __name__ == "__main__":
    main()
