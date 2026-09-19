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

What it does, per run:
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
  4. Writes today's full pull to data/snapshots/<date>.json -- one file per
     day, so the dashboard can fetch a single past day's full system list on
     demand (e.g. when someone picks a month from a filter) without ever
     having to download one giant ever-growing file. This replaced an
     earlier design (data/history.jsonl, one appended line per day) that
     would have made every page load bigger by design, forever.
  5. Copies that same pull to data/latest.json (used by pages that always
     want "as of today": Look Up a System, the map, etc).
  6. Appends one aggregate summary row to data/summary.jsonl. This file
     stays small forever (one compact row per day) and carries everything
     the dashboard needs to make its statewide KPIs, status breakdown, and
     "Most Common High-Risk Attributes" panel *dynamic by month* without
     re-fetching full per-system data for every month someone might pick:
     total/failing counts, population, a per-status breakdown, a per-county
     breakdown (total + failing + population), HIGH-risk counts for each of
     the 21 individual risk-assessment attributes, and a risk-level
     distribution for each of the 4 risk categories (Water Quality,
     Accessibility, Affordability, TMF Capacity).

Why SELECT * instead of a fixed field list: the Failing list (updated daily)
and the Risk Assessment (Water Quality / Accessibility / Affordability / TMF
Capacity categories and their underlying indicators, refreshed quarterly) live
in the same flat file. Pulling everything, rather than a hand-picked handful
of fields, is what makes the "what specifically changed" comparison possible
without this script having to be kept in sync with the state's schema by
hand, and is also what lets summarize() compute the attribute/category
breakdowns below without a maintained field list drifting out of date.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import date, datetime, timezone

# --- Configuration -----------------------------------------------------

# CKAN resource id for the "Drinking Water Risk Assessment Public Flat File"
# (the SAFER Dashboard's Failing + At-Risk systems table). Confirmed twice:
# once against the dataset's public listing on data.ca.gov, and again
# against the OData 3.0 endpoint for this same resource
# (https://data.ca.gov/datastore/odata3.0/255887bb-5451-4c19-8e35-27899ae8c3ad)
# -- both point at the same resource id used here. This script sticks with
# CKAN's JSON datastore_search_sql API rather than that OData/XML interface:
# same underlying data, but JSON needs no XML parser or $skip/$top paging
# logic to consume.
RESOURCE_ID = os.environ.get("SAFER_RESOURCE_ID", "255887bb-5451-4c19-8e35-27899ae8c3ad")

BASE_URL = "https://data.ca.gov/api/3/action/datastore_search_sql"

# Columns that exist on every CKAN datastore row or that we add ourselves --
# never meaningful as a "this changed" diff, so excluded from field_diffs.
IGNORE_FIELDS = {"_id", "_full_text", "snapshot_date"}

# The 4 risk-assessment categories (Look Up a System's "Risk Categories &
# Failing Criteria" table, and this script's per-day category distribution).
# ASSESSIBILITY is the state's own spelling in the live schema, not a typo
# introduced here.
CATEGORY_RISK_FIELDS = {
    "Water Quality": "WATER_QUALITY_RISK_LEVEL",
    "Accessibility": "ASSESSIBILITY_RISK_LEVEL",
    "Affordability": "AFFORDABILITY_RISK_LEVEL",
    "TMF Capacity": "TMF_CAPACITY_RISK_LEVEL",
}

# The 21 individual risk-assessment attributes underneath those 4 categories
# (Failing System Details' "Most Common High-Risk Attributes" panel, and
# Look Up a System's per-system breakdown). Verified against a real export
# of this resource (SAFER_RA.csv, 3,190 rows / 140 columns) -- every one of
# these column names exists in the live data.
ATTRIBUTE_RISK_FIELDS = [
    "HISTORY_OF_E_COLI_PRESENCE_RISK_LEVEL",
    "INCREASING_PRESENCE_OF_WATER_QUALITY_TRENDS_TOWARD_MCL_RISK_LEVEL",
    "TREATMENT_TECHNIUQE_VIOLATIONS_RISK_LEVEL",
    "PAST_PRESENCE_ON_THE_FAILING_LIST_RISK_LEVEL",
    "CONSTITUENTS_OF_EMERGING_CONCERN_RISK_LEVEL",
    "PERCENTAGE_OF_SOURCES_EXCEEDING_AN_MCL_RISK_LEVEL",
    "NUMBER_OF_WATER_SOURCES_RISK_LEVEL",
    "ABESENCE_OF_INTERTIES_RISK_LEVEL",
    "SOURCE_CAPACITY_VIOLATION_RISK_LEVEL",
    "BOTTLED_WATER_OR_HAULED_WATER_RELIANCE_RISK_LEVEL",
    "DWR_DROUGHT_AND_WATER_SHORTAGE_RISK_ASSESSMENT_PERCENTILE_RISK_LEVEL",
    "CRITICALLY_OVERDRAFTED_GROUNDWATER_BASIN_RISK_LEVEL",
    "PERCENT_OF_MEDIAN_HOUSEHOLD_INCOME_MHI_RISK_LEVEL",
    "EXTREME_WATER_BILL_RISK_LEVEL",
    "HOUSEHOLD_SOCIOECONOMIC_BURDEN_RISK_LEVEL",
    "TOTAL_NET_ANNUAL_INCOME_RISK_LEVEL",
    "OPERATING_RATIO_RISK_LEVEL",
    "DAYS_CASH_ON_HAND_RISK_LEVEL",
    "OPERATOR_CERTIFICATION_VIOLATIONS_RISK_LEVEL",
    "MONITORING_AND_REPORTING_VIOLATIONS_RISK_LEVEL",
    "SIGNIFICANT_DEFICIENCIES_RISK_LEVEL",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")
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


def row_is_failing(r):
    """FINAL_SAFER_STATUS is the authoritative, plain-text signal (always
    exactly "Failing" for a failing system) and is what every SAFER data
    source agrees on regardless of how it encodes other fields.
    CURRENT_FAILING is checked only as a fallback, tolerant of the
    different encodings seen across sources ("Y"/"N" strings from a
    Dataverse export vs. e.g. booleans from the live CKAN API)."""
    status = (r.get("FINAL_SAFER_STATUS") or "").strip()
    if status == "Failing":
        return True
    v = r.get("CURRENT_FAILING")
    if v is True or v == 1:
        return True
    return str(v if v is not None else "").strip().lower() in ("y", "yes", "true", "1")


def to_int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def summarize(rows, snapshot_date):
    by_status = {}
    by_county = {}
    high_risk_attribute_counts = {f: 0 for f in ATTRIBUTE_RISK_FIELDS}
    category_risk_levels = {cat: {} for cat in CATEGORY_RISK_FIELDS}
    failing_count = 0
    population_in_failing = 0
    total_population = 0

    for r in rows:
        status = (r.get("FINAL_SAFER_STATUS") or "Unknown").strip()
        by_status[status] = by_status.get(status, 0) + 1

        county = (r.get("COUNTY") or "Unknown").strip() or "Unknown"
        pop = to_int(r.get("POPULATION"))
        total_population += pop
        c = by_county.setdefault(county, {"total": 0, "failing": 0, "population": 0, "population_failing": 0})
        c["total"] += 1
        c["population"] += pop

        failing = row_is_failing(r)
        if failing:
            failing_count += 1
            population_in_failing += pop
            c["failing"] += 1
            c["population_failing"] += pop

        for f in ATTRIBUTE_RISK_FIELDS:
            if (r.get(f) or "").strip().upper() == "HIGH":
                high_risk_attribute_counts[f] += 1

        for cat, field in CATEGORY_RISK_FIELDS.items():
            level = (r.get(field) or "Unknown").strip() or "Unknown"
            category_risk_levels[cat][level] = category_risk_levels[cat].get(level, 0) + 1

    return {
        "date": snapshot_date,
        "total_systems": len(rows),
        "currently_failing": failing_count,
        "total_population": total_population,
        "population_in_failing_systems": population_in_failing,
        "by_status": by_status,
        "by_county": by_county,
        "high_risk_attribute_counts": high_risk_attribute_counts,
        "category_risk_levels": category_risk_levels,
    }


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def drop_existing_date(path, snapshot_date, date_key="date"):
    """Remove any line already recorded for snapshot_date, so re-running the
    workflow twice in one day (e.g. a manual workflow_dispatch on the same
    day the backfill already covered) overwrites that day instead of
    appending a duplicate point that trend charts would then plot twice."""
    if not os.path.exists(path):
        return
    kept = []
    changed = False
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get(date_key) == snapshot_date:
                changed = True
                continue
            kept.append(line)
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))


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
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

    previous = load_previous_latest()
    # If latest.json is itself dated today (e.g. this is a same-day re-run),
    # diff against the day before instead so "changes" reflects a real
    # transition rather than comparing today's pull against itself. Since
    # snapshots/<date>.json is a plain overwrite (not an appended log), a
    # same-day re-run just replaces that one file -- no dedupe needed there.
    rerun_same_day = bool(previous) and previous.get("date") == snapshot_date

    # 1. Detect and log status-change events (must happen before latest.json
    #    is overwritten, since it diffs against yesterday's copy of it).
    changes = [] if rerun_same_day else detect_changes(previous, rows, snapshot_date)
    if rerun_same_day:
        drop_existing_date(CHANGES_PATH, snapshot_date)
    for change in changes:
        append_jsonl(CHANGES_PATH, change)

    # 2. Write today's full snapshot to its own dated file -- overwritten in
    #    place on a same-day re-run, never appended, so this can never grow
    #    into a duplicate-day problem or an ever-larger single download.
    snapshot_obj = {
        "date": snapshot_date,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "records": rows,
    }
    snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{snapshot_date}.json")
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_obj, f, separators=(",", ":"))

    # 3. Copy to "latest" for pages that always want today's view.
    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot_obj, f, indent=2)

    # 4. Append a small aggregate row for trend charts and the month
    #    filter -- replacing any earlier row already recorded for this date.
    drop_existing_date(SUMMARY_PATH, snapshot_date)
    append_jsonl(SUMMARY_PATH, summarize(rows, snapshot_date))

    print(f"OK: {len(rows)} records snapshotted for {snapshot_date}, {len(changes)} status change(s) detected")


if __name__ == "__main__":
    main()
