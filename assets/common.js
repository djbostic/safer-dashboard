// Shared helpers for all three SAFER dashboard pages.

const fmt = new Intl.NumberFormat("en-US");

const STATUS_ORDER = ["Not At-Risk", "Potentially At-Risk", "At-Risk", "Failing"];
const STATUS_SEVERITY = { "Not At-Risk": 0, "Potentially At-Risk": 1, "At-Risk": 2, "Failing": 3 };

function getVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function statusColor(status) {
  const map = {
    "Failing": getVar("--critical"),
    "At-Risk": getVar("--warning"),
    "Potentially At-Risk": getVar("--serious"),
    "Not At-Risk": getVar("--good"),
  };
  return map[status] || getVar("--muted");
}

function statusClass(status) {
  return String(status || "Unknown").trim().replace(/\s+/g, "-");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function loadJson(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// Loads via loaderFn(); on any failure (missing file, bad JSON, etc.) falls
// back to exampleValue instead. Each data file is loaded independently this
// way, so a missing/partial file never discards a DIFFERENT file that did
// load successfully (the earlier all-or-nothing Promise.all approach threw
// real data away whenever just one fetch failed).
async function loadOrExample(loaderFn, exampleValue) {
  try {
    const data = await loaderFn();
    return { data, isExample: false };
  } catch (err) {
    console.warn("Falling back to example data:", err);
    return { data: exampleValue, isExample: true };
  }
}

async function loadJsonl(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  const text = await res.text();
  return text.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
}

function isFailing(r) {
  // FINAL_SAFER_STATUS is the authoritative, plain-text signal (always
  // exactly "Failing" for a failing system) and is what every SAFER data
  // source agrees on. CURRENT_FAILING is a secondary flag whose encoding
  // has varied by source (e.g. "Y"/"N" strings in one export, booleans
  // from the live API) -- checked as a fallback only, tolerant of both.
  if (String(r.FINAL_SAFER_STATUS || "").trim() === "Failing") return true;
  const v = r.CURRENT_FAILING;
  if (v === true || v === 1) return true;
  return String(v ?? "").trim().toLowerCase().startsWith("y") || String(v ?? "").trim() === "1";
}

function prettyField(name) {
  return String(name)
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, c => c.toUpperCase());
}

function renderFieldDiffs(diffs) {
  const keys = Object.keys(diffs || {});
  if (keys.length === 0) {
    return '<span class="empty-state" style="padding:4px 0;display:inline-block;">No other fields changed alongside the status (or this event predates field-level tracking).</span>';
  }
  return `<table><thead><tr><th>Field</th><th>From</th><th>To</th></tr></thead><tbody>` +
    keys.sort().map(k => `<tr><td>${escapeHtml(prettyField(k))}</td><td>${escapeHtml(diffs[k].from ?? "—")}</td><td>${escapeHtml(diffs[k].to ?? "—")}</td></tr>`).join("") +
    `</tbody></table>`;
}

function daysBetween(a, b) {
  const ms = new Date(b) - new Date(a);
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

function monthsAgo(n) {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d;
}

// Renders the shared nav bar into a container, marking `current` active.
// pages: [{ href, label }]
function renderNav(containerId, current) {
  const pages = [
    { href: "system-lookup.html", label: "Look up a system" },
    { href: "index.html", label: "Statewide trends" },
    { href: "failing-focus.html", label: "Failing system details" },
    { href: "what-changed.html", label: "Deeper dive on changes" },
    { href: "about.html", label: "About this page" },
  ];
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = pages
    .map(p => `<a href="${p.href}" class="${p.href === current ? "active" : ""}">${p.label}</a>`)
    .join("");
}

function titleCase(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/\b\w/g, c => c.toUpperCase());
}

// --- Month filter support ------------------------------------------------
// data/summary.jsonl carries one compact row per day, forever (by_status,
// by_county, high_risk_attribute_counts, category_risk_levels -- see
// fetch_snapshot.py's summarize()). Every dynamic-by-month view on the
// dashboard is driven off this file: picking a month never re-downloads
// full per-system data, it just picks a different row out of this file.
// Only the actual system-level table (e.g. "which systems are failing this
// month") needs full per-system rows, and that's lazy-loaded per date via
// loadSnapshotForDate() only when someone actually looks at that table.

function monthKey(dateStr) {
  return String(dateStr || "").slice(0, 7);
}

function monthLabel(key) {
  if (!key) return "";
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { year: "numeric", month: "long" });
}

// Sorted ascending list of month keys ("2026-07") present in summary rows.
function availableMonths(summaryRows) {
  return [...new Set(summaryRows.map(r => monthKey(r.date)))].sort();
}

// The most recent summary row within a given month key, or (month === "")
// the most recent row overall. This is the row used to answer "what did
// things look like as of that month" -- there's normally one row a day, so
// this is effectively "state of the world at month's end" once a month is
// fully tracked, and "state of the world so far" for the current month.
function summaryRowForMonth(summaryRows, month) {
  const candidates = month ? summaryRows.filter(r => monthKey(r.date) === month) : summaryRows;
  if (candidates.length === 0) return null;
  return candidates.slice().sort((a, b) => a.date.localeCompare(b.date)).pop();
}

// Fills a <select> with an "All months" option plus one option per month
// present in summaryRows, most recent first. Keeps the element's current
// value selected if it's still a valid option.
function populateMonthSelect(selectEl, summaryRows, allLabel) {
  const months = availableMonths(summaryRows).reverse();
  const previous = selectEl.value;
  selectEl.innerHTML = `<option value="">${allLabel || "All months"}</option>` +
    months.map(m => `<option value="${m}">${monthLabel(m)}</option>`).join("");
  if (months.includes(previous)) selectEl.value = previous;
}

// Lazy-loads one day's full per-system record set (data/snapshots/<date>.json).
// Returns null (never throws) if that file isn't available -- e.g. a date
// backfilled before this per-day-file layout existed, or a network hiccup --
// so callers can fall back to "detail not available for this date" instead
// of breaking the whole page.
async function loadSnapshotForDate(dateStr) {
  if (!dateStr) return null;
  try {
    return await loadJson(`data/snapshots/${dateStr}.json`);
  } catch (err) {
    console.warn(`No per-system snapshot file for ${dateStr}:`, err);
    return null;
  }
}

// Human-readable labels for the 21 individual risk-assessment attribute
// fields (see fetch_snapshot.py's ATTRIBUTE_RISK_FIELDS) -- corrects a
// couple of typos present in the state's own column names (TECHNIUQE,
// ABESENCE) rather than reproducing them on-screen.
const ATTRIBUTE_LABELS = {
  HISTORY_OF_E_COLI_PRESENCE_RISK_LEVEL: "History of E. coli Presence",
  INCREASING_PRESENCE_OF_WATER_QUALITY_TRENDS_TOWARD_MCL_RISK_LEVEL: "Water Quality Trending Toward an MCL",
  TREATMENT_TECHNIUQE_VIOLATIONS_RISK_LEVEL: "Treatment Technique Violations",
  PAST_PRESENCE_ON_THE_FAILING_LIST_RISK_LEVEL: "Past Presence on the Failing List",
  CONSTITUENTS_OF_EMERGING_CONCERN_RISK_LEVEL: "Constituents of Emerging Concern",
  PERCENTAGE_OF_SOURCES_EXCEEDING_AN_MCL_RISK_LEVEL: "% of Sources Exceeding an MCL",
  NUMBER_OF_WATER_SOURCES_RISK_LEVEL: "Number of Water Sources",
  ABESENCE_OF_INTERTIES_RISK_LEVEL: "Absence of Interties",
  SOURCE_CAPACITY_VIOLATION_RISK_LEVEL: "Source Capacity Violations",
  BOTTLED_WATER_OR_HAULED_WATER_RELIANCE_RISK_LEVEL: "Bottled/Hauled Water Reliance",
  DWR_DROUGHT_AND_WATER_SHORTAGE_RISK_ASSESSMENT_PERCENTILE_RISK_LEVEL: "Drought & Water Shortage Risk",
  CRITICALLY_OVERDRAFTED_GROUNDWATER_BASIN_RISK_LEVEL: "Critically Overdrafted Groundwater Basin",
  PERCENT_OF_MEDIAN_HOUSEHOLD_INCOME_MHI_RISK_LEVEL: "% of Median Household Income (MHI)",
  EXTREME_WATER_BILL_RISK_LEVEL: "Extreme Water Bill",
  HOUSEHOLD_SOCIOECONOMIC_BURDEN_RISK_LEVEL: "Household Socioeconomic Burden",
  TOTAL_NET_ANNUAL_INCOME_RISK_LEVEL: "Total Net Annual Income",
  OPERATING_RATIO_RISK_LEVEL: "Operating Ratio",
  DAYS_CASH_ON_HAND_RISK_LEVEL: "Days Cash on Hand",
  OPERATOR_CERTIFICATION_VIOLATIONS_RISK_LEVEL: "Operator Certification Violations",
  MONITORING_AND_REPORTING_VIOLATIONS_RISK_LEVEL: "Monitoring & Reporting Violations",
  SIGNIFICANT_DEFICIENCIES_RISK_LEVEL: "Significant Deficiencies",
};

// Which of the 4 risk categories each attribute belongs to, in the order
// the state's own schema groups them (verified against the column order in
// a real export of this resource: 6 Water Quality + 6 Accessibility + 6
// Affordability + 3 TMF Capacity = all 21 attributes).
const CATEGORY_ATTRIBUTES = {
  "Water Quality": [
    "HISTORY_OF_E_COLI_PRESENCE_RISK_LEVEL",
    "INCREASING_PRESENCE_OF_WATER_QUALITY_TRENDS_TOWARD_MCL_RISK_LEVEL",
    "TREATMENT_TECHNIUQE_VIOLATIONS_RISK_LEVEL",
    "PAST_PRESENCE_ON_THE_FAILING_LIST_RISK_LEVEL",
    "CONSTITUENTS_OF_EMERGING_CONCERN_RISK_LEVEL",
    "PERCENTAGE_OF_SOURCES_EXCEEDING_AN_MCL_RISK_LEVEL",
  ],
  "Accessibility": [
    "NUMBER_OF_WATER_SOURCES_RISK_LEVEL",
    "ABESENCE_OF_INTERTIES_RISK_LEVEL",
    "SOURCE_CAPACITY_VIOLATION_RISK_LEVEL",
    "BOTTLED_WATER_OR_HAULED_WATER_RELIANCE_RISK_LEVEL",
    "DWR_DROUGHT_AND_WATER_SHORTAGE_RISK_ASSESSMENT_PERCENTILE_RISK_LEVEL",
    "CRITICALLY_OVERDRAFTED_GROUNDWATER_BASIN_RISK_LEVEL",
  ],
  "Affordability": [
    "PERCENT_OF_MEDIAN_HOUSEHOLD_INCOME_MHI_RISK_LEVEL",
    "EXTREME_WATER_BILL_RISK_LEVEL",
    "HOUSEHOLD_SOCIOECONOMIC_BURDEN_RISK_LEVEL",
    "TOTAL_NET_ANNUAL_INCOME_RISK_LEVEL",
    "OPERATING_RATIO_RISK_LEVEL",
    "DAYS_CASH_ON_HAND_RISK_LEVEL",
  ],
  "TMF Capacity": [
    "OPERATOR_CERTIFICATION_VIOLATIONS_RISK_LEVEL",
    "MONITORING_AND_REPORTING_VIOLATIONS_RISK_LEVEL",
    "SIGNIFICANT_DEFICIENCIES_RISK_LEVEL",
  ],
};

// The per-record field holding each category's own overall risk level.
const CATEGORY_FIELD = {
  "Water Quality": "WATER_QUALITY_RISK_LEVEL",
  "Accessibility": "ASSESSIBILITY_RISK_LEVEL",
  "Affordability": "AFFORDABILITY_RISK_LEVEL",
  "TMF Capacity": "TMF_CAPACITY_RISK_LEVEL",
};

// Approximate California bounding box, used to project lat/long onto a
// simple SVG scatter (an equirectangular projection, not a true basemap --
// good enough to show roughly where systems are without any map-tile
// dependency or network call).
const CA_BOUNDS = { latMin: 32.4, latMax: 42.1, lonMin: -124.6, lonMax: -113.9 };

function projectPoint(lat, lon, width, height) {
  const x = ((lon - CA_BOUNDS.lonMin) / (CA_BOUNDS.lonMax - CA_BOUNDS.lonMin)) * width;
  const y = ((CA_BOUNDS.latMax - lat) / (CA_BOUNDS.latMax - CA_BOUNDS.latMin)) * height;
  return { x, y };
}

// Renders `points` ({lat, lon, color, r, title}[]) as an SVG scatter into
// container (a DOM element). Returns true if it drew anything.
function renderPointMap(container, points, { width = 480, height = 420 } = {}) {
  const usable = points.filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  if (usable.length === 0) {
    container.innerHTML = `<div class="empty-state">No location data available for this view.</div>`;
    return false;
  }
  const circles = usable.map(p => {
    const { x, y } = projectPoint(p.lat, p.lon, width, height);
    const r = p.r || 3;
    const title = p.title ? `<title>${escapeHtml(p.title)}</title>` : "";
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="${p.color || getVar('--series-1')}" fill-opacity="0.85">${title}</circle>`;
  }).join("");
  container.innerHTML = `<svg class="point-map" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">${circles}</svg>`;
  return true;
}

function riskLevelColor(level) {
  const map = {
    HIGH: getVar("--critical"),
    MEDIUM: getVar("--warning"),
    LOW: getVar("--good"),
    NONE: getVar("--muted"),
  };
  return map[String(level || "").toUpperCase()] || getVar("--muted");
}
