#!/usr/bin/env python3
"""
Rebuilds data/history.jsonl, data/summary.jsonl, data/latest.json, and
data/changes.jsonl from a Dataverse "SaferSnapshotHistory" CSV export --
a genuine day-by-day archive (one row per system per day), as opposed to
the changes-only export handled by backfill_changes_from_export.py.

This is authoritative where it overlaps with anything already in data/: a
real daily snapshot beats a status derived only from change events, so this
script REPLACES latest.json (dropping the earlier "partial": true one) and
REGENERATES changes.jsonl from scratch by diffing consecutive days in the
export, rather than merging change-by-change. If you later re-run
backfill_changes_from_export.py against a newer export, re-run this script
first (or after) -- just don't assume the two merge automatically; regenerate
in whichever order gives you the fullest picture and check the result.

Usage:
    python3 scripts/backfill_from_snapshot_history.py path/to/snapshot_history.csv

Expected columns (Dataverse export naming): cr522_watersystemid,
cr522_watersystemname, cr522_county, cr522_population, cr522_saferstatus,
cr522_currentfailing, cr522_failingstatusstartdate, cr522_economicstatus,
cr522_snapshotdate.

Note: this export does not carry the underlying failing-criteria detail
(the specific violation/indicator fields) -- only the fields above. So
field_diffs on the regenerated changes.jsonl will show things like
FAILING_START_DATE or ECONOMIC_STATUS moving alongside a status change, but
not which violation caused it. That level of detail only starts
accumulating once fetch_snapshot.py runs against the live wide flat file.
"""
import csv
import json
import os
import sys
from datetime import date, datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")
SUMMARY_PATH = os.path.join(DATA_DIR, "summary.jsonl")
CHANGES_PATH = os.path.join(DATA_DIR, "changes.jsonl")

IGNORE_FIELDS = {"snapshot_date"}


def date_only(s):
    return (s or "").strip().split(" ")[0] or None


def load_csv(path):
    by_date = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            snap_date = date_only(row.get("cr522_snapshotdate"))
            if not snap_date:
                continue
            record = {
                "WATER_SYSTEM_NUMBER": (row.get("cr522_watersystemid") or "").strip(),
                "SYSTEM_NAME": (row.get("cr522_watersystemname") or "").strip(),
                "COUNTY": (row.get("cr522_county") or "").strip(),
                "POPULATION": int(row["cr522_population"]) if (row.get("cr522_population") or "").strip().isdigit() else None,
                "FINAL_SAFER_STATUS": (row.get("cr522_saferstatus") or "").strip(),
                "CURRENT_FAILING": "Y" if (row.get("cr522_currentfailing") or "").strip().lower() == "failing" else "N",
                "FAILING_START_DATE": date_only(row.get("cr522_failingstatusstartdate")),
                "SERVICE_AREA_ECONOMIC_STATUS": (row.get("cr522_economicstatus") or "").strip() or None,
                "REGULATING_AGENCY": None,
                "snapshot_date": snap_date,
            }
            by_date.setdefault(snap_date, []).append(record)
    return by_date


def summarize(records, snapshot_date):
    by_status = {}
    failing_count = 0
    population_in_failing = 0
    for r in records:
        status = r["FINAL_SAFER_STATUS"] or "Unknown"
        by_status[status] = by_status.get(status, 0) + 1
        if r["CURRENT_FAILING"] == "Y":
            failing_count += 1
            population_in_failing += r["POPULATION"] or 0
    return {
        "date": snapshot_date,
        "total_systems": len(records),
        "currently_failing": failing_count,
        "population_in_failing_systems": population_in_failing,
        "by_status": by_status,
    }


def field_diffs(prev_row, new_row):
    keys = (set(prev_row.keys()) | set(new_row.keys())) - IGNORE_FIELDS
    diffs = {}
    for k in keys:
        old_val, new_val = prev_row.get(k), new_row.get(k)
        if str(old_val) != str(new_val):
            diffs[k] = {"from": old_val, "to": new_val}
    return diffs


def detect_changes(prev_records, new_records, snapshot_date):
    if prev_records is None:
        return []
    prev_by_id = {r["WATER_SYSTEM_NUMBER"]: r for r in prev_records}
    changes = []
    for r in new_records:
        prev_row = prev_by_id.get(r["WATER_SYSTEM_NUMBER"])
        if prev_row is None:
            continue
        old_status, new_status = prev_row["FINAL_SAFER_STATUS"], r["FINAL_SAFER_STATUS"]
        if old_status and new_status and old_status != new_status:
            changes.append({
                "date": snapshot_date,
                "water_system_number": r["WATER_SYSTEM_NUMBER"],
                "system_name": r["SYSTEM_NAME"],
                "county": r["COUNTY"],
                "from_status": old_status,
                "to_status": new_status,
                "field_diffs": field_diffs(prev_row, r),
            })
    return changes


def main():
    if len(sys.argv) != 2:
        print("Usage: backfill_from_snapshot_history.py path/to/snapshot_history.csv", file=sys.stderr)
        sys.exit(1)

    by_date = load_csv(sys.argv[1])
    dates = sorted(by_date.keys())
    if not dates:
        print("No rows with a usable snapshot date found.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)

    all_changes = []
    all_summaries = []
    prev_records = None
    with open(HISTORY_PATH, "w", encoding="utf-8") as hist_f:
        for d in dates:
            records = by_date[d]
            hist_f.write(json.dumps({"date": d, "records": records}, separators=(",", ":")) + "\n")
            all_summaries.append(summarize(records, d))
            all_changes.extend(detect_changes(prev_records, records, d))
            prev_records = records

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        for s in all_summaries:
            f.write(json.dumps(s, separators=(",", ":")) + "\n")

    all_changes.sort(key=lambda c: (c["date"], c["water_system_number"]))
    with open(CHANGES_PATH, "w", encoding="utf-8") as f:
        for c in all_changes:
            f.write(json.dumps(c, separators=(",", ":")) + "\n")

    latest_date = dates[-1]
    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "date": latest_date,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "records": by_date[latest_date],
        }, f, indent=2)

    print(f"Wrote {len(dates)} days of history ({dates[0]} to {latest_date}), "
          f"{len(all_changes)} change events, latest.json with {len(by_date[latest_date])} systems.")


if __name__ == "__main__":
    main()
