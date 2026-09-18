#!/usr/bin/env python3
"""
Derives a minimal data/latest.json from data/changes.jsonl alone, for use
until the real daily fetch_snapshot.py has run and produced a full current
snapshot from the live API.

Each system's "current" status is taken from the to_status of its most
recent change event. This only covers systems that appear in the change
log (i.e. that changed status at least once during the period covered by
that log) -- it is NOT a full statewide snapshot, and is clearly marked as
such via the `partial: true` flag so the dashboard pages could (and the
data/README does) note the difference. It gets overwritten the moment
fetch_snapshot.py runs for real.
"""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CHANGES_PATH = os.path.join(DATA_DIR, "changes.jsonl")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")


def main():
    if not os.path.exists(CHANGES_PATH):
        print("No changes.jsonl found; nothing to derive.")
        return
    if os.path.exists(LATEST_PATH):
        print(f"{LATEST_PATH} already exists -- not overwriting a real snapshot with a derived one.")
        return

    with open(CHANGES_PATH, "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]

    latest_by_system = {}
    for e in sorted(events, key=lambda e: e["date"]):
        latest_by_system[e["water_system_number"]] = e

    records = []
    max_date = max((e["date"] for e in events), default=None)
    for wsn, e in latest_by_system.items():
        records.append({
            "WATER_SYSTEM_NUMBER": wsn,
            "SYSTEM_NAME": e["system_name"],
            "COUNTY": e["county"],
            "FINAL_SAFER_STATUS": e["to_status"],
            "CURRENT_FAILING": "Y" if e["to_status"] == "Failing" else "N",
            "POPULATION": None,
            "FAILING_START_DATE": None,
            "REGULATING_AGENCY": None,
            "SERVICE_AREA_ECONOMIC_STATUS": None,
        })

    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "date": max_date,
            "partial": True,
            "partial_note": (
                "Derived from change-event history only, not a full statewide pull -- "
                "covers just the systems that changed status during the tracked period. "
                "Will be replaced by a complete snapshot the first time fetch_snapshot.py "
                "runs against the live API."
            ),
            "records": records,
        }, f, indent=2)

    print(f"Wrote {len(records)} derived records (partial snapshot) to {LATEST_PATH}")


if __name__ == "__main__":
    main()
