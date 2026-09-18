#!/usr/bin/env python3
"""
One-off (but re-runnable) importer: merges a Power Automate / Dataverse
"ChangeEvents" CSV export into data/changes.jsonl, so history collected
before this tool existed isn't thrown away.

Usage:
    python3 scripts/backfill_changes_from_export.py path/to/export.csv [more.csv ...]

Expected columns (Dataverse export naming): cr522_watersystemid,
cr522_watersystemname, cr522_county, cr522_dateofstatuschange,
cr522_fromstatus, cr522_tostatus. Any cr522_changeeventsid is used only for
dedup within a single import run, not stored.

This import has no field-level detail (no field_diffs) -- the source system
wasn't capturing which underlying criterion changed, only that the overall
status did. Those rows get field_diffs: {}, and every page that displays
field_diffs already has a graceful "no detail available" fallback for that.

Merging logic: keyed on (water_system_number, date, to_status). A row
already present in changes.jsonl with that key is left alone (so re-running
this after fetch_snapshot.py has started logging its own changes won't
duplicate anything); new rows are added and the whole file is rewritten
sorted by date.
"""
import csv
import json
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CHANGES_PATH = os.path.join(DATA_DIR, "changes.jsonl")


def load_existing():
    if not os.path.exists(CHANGES_PATH):
        return []
    with open(CHANGES_PATH, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_csv(path):
    events = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            date_str = (row.get("cr522_dateofstatuschange") or "").strip()
            if not date_str:
                continue
            date_only = date_str.split(" ")[0]  # "2026-09-18 00:00:00.0000000" -> "2026-09-18"
            from_status = (row.get("cr522_fromstatus") or "").strip()
            to_status = (row.get("cr522_tostatus") or "").strip()
            if not from_status or not to_status:
                continue
            events.append({
                "date": date_only,
                "water_system_number": (row.get("cr522_watersystemid") or "").strip(),
                "system_name": (row.get("cr522_watersystemname") or "").strip(),
                "county": (row.get("cr522_county") or "").strip(),
                "from_status": from_status,
                "to_status": to_status,
                "field_diffs": {},
            })
    return events


def main():
    if len(sys.argv) < 2:
        print("Usage: backfill_changes_from_export.py path/to/export.csv [more.csv ...]", file=sys.stderr)
        sys.exit(1)

    existing = load_existing()
    existing_keys = {(e["water_system_number"], e["date"], e["to_status"]) for e in existing}

    added = 0
    for csv_path in sys.argv[1:]:
        for event in parse_csv(csv_path):
            key = (event["water_system_number"], event["date"], event["to_status"])
            if key in existing_keys:
                continue
            existing_keys.add(key)
            existing.append(event)
            added += 1

    existing.sort(key=lambda e: (e["date"], e["water_system_number"]))

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CHANGES_PATH, "w", encoding="utf-8") as f:
        for e in existing:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")

    print(f"Added {added} new change event(s). Total in {CHANGES_PATH}: {len(existing)}")


if __name__ == "__main__":
    main()
