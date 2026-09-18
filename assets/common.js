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
  return String(r.CURRENT_FAILING || "").trim().toLowerCase().startsWith("y");
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
    { href: "index.html", label: "Statewide trends" },
    { href: "system-lookup.html", label: "Look up a system" },
    { href: "failing-focus.html", label: "Failing systems focus" },
    { href: "what-changed.html", label: "What changed" },
  ];
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = pages
    .map(p => `<a href="${p.href}" class="${p.href === current ? "active" : ""}">${p.label}</a>`)
    .join("");
}
