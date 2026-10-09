"use strict";

// Everything from the server is inserted with textContent, never innerHTML,
// so values stored in the database cannot run script in the browser.

const $ = (id) => document.getElementById(id);
const fmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

const TIME_COL = /(^|_)(year|month|quarter|week|day|date|period)(_|$)/i;
const ID_COL = /(^|_)id$/i;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const BAR_LIMIT = 30;
const LINE_LIMIT = 200;

let chart = null;
let current = null;   // { data, plan, measure }
let history = [];     // [{ id, question, data, at }]
let activeId = null;
let timer = null;

Chart.defaults.font.family = '"Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif';
Chart.defaults.font.size = 12;

// ---------- helpers ----------

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function pretty(name) {
  const s = String(name).replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function isNum(v) {
  return v !== null && v !== "" && Number.isFinite(Number(v));
}
function shortLabel(v) {
  if (v === null) return "(none)";
  return String(v).replace(/[ T]00:00:00(\.0+)?([+-]\d\d(:\d\d)?)?$/, "");
}
function axisLabel(v, colName) {
  if (/(^|_)month(_|$)/i.test(colName) && isNum(v)) {
    const m = Number(v);
    if (Number.isInteger(m) && m >= 1 && m <= 12) return MONTHS[m - 1];
  }
  return shortLabel(v);
}
function truncate(s, n) {
  s = String(s);
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
function show(el, on) { el.hidden = !on; }

// Display only: start each top-level clause on its own line. Text inside
// brackets or quotes is left alone, so EXTRACT(MONTH FROM x) stays intact.
const SQL_CLAUSE = /^(?:(?:LEFT|RIGHT|INNER|FULL|CROSS) JOIN|JOIN|FROM|WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|UNION ALL|UNION)\b/;
function formatSql(sql) {
  sql = String(sql);
  let out = "", depth = 0, quote = null;
  for (let i = 0; i < sql.length; i++) {
    const ch = sql[i];
    if (quote) { out += ch; if (ch === quote) quote = null; continue; }
    if (ch === "'" || ch === '"') { quote = ch; out += ch; continue; }
    if (ch === "(") depth++;
    if (ch === ")") depth = Math.max(0, depth - 1);
    if (depth === 0 && /\s/.test(ch)) {
      let k = i;
      while (k < sql.length && /\s/.test(sql[k])) k++;
      const m = sql.slice(k).match(SQL_CLAUSE);
      if (m && out.length) {
        out += "\n" + m[0];
        i = k + m[0].length - 1;
        continue;
      }
    }
    out += ch;
  }
  return out;
}

// ---------- choosing a form from the shape of the result ----------

function planViz(columns, rows) {
  if (!rows.length) return { kind: "none" };
  if (columns.length === 1 && columns[0] === "message") return { kind: "none" };

  const numeric = columns
    .map((_, i) => i)
    .filter((i) => rows.some((r) => r[i] !== null) && rows.every((r) => r[i] === null || isNum(r[i])));
  const timeIdx = columns.findIndex((c) => TIME_COL.test(c));
  const measures = numeric.filter((i) => !ID_COL.test(columns[i]) && i !== timeIdx);
  if (!measures.length) return { kind: "table" };

  const textCols = columns.map((_, i) => i).filter((i) => !numeric.includes(i));
  const nameCol = textCols.find((i) => !ID_COL.test(columns[i]));
  const labelIdx = nameCol ?? textCols[0] ?? numeric.find((i) => ID_COL.test(columns[i])) ?? -1;

  if (rows.length === 1) return { kind: "stat", measures, labelIdx };
  if (timeIdx >= 0) return { kind: "line", measures, labelIdx: timeIdx };
  if (labelIdx < 0) return { kind: "table" };
  return { kind: "bar", measures, labelIdx };
}

// ---------- table, CSV ----------

function measureColumns(columns, rows) {
  return columns.map((c, i) => rows.length > 0 && !ID_COL.test(c) && !TIME_COL.test(c)
    && rows.every((r) => r[i] === null || isNum(r[i])));
}

function renderTable(columns, rows) {
  const table = $("table");
  table.replaceChildren();
  const numeric = measureColumns(columns, rows);

  const head = table.createTHead().insertRow();
  columns.forEach((c, i) => {
    const th = document.createElement("th");
    th.textContent = pretty(c);
    if (numeric[i]) th.className = "num";
    head.appendChild(th);
  });

  const body = table.createTBody();
  rows.forEach((r) => {
    const tr = body.insertRow();
    r.forEach((v, i) => {
      const td = tr.insertCell();
      td.textContent = v === null ? "" : numeric[i] ? fmt.format(Number(v)) : shortLabel(v);
      if (numeric[i]) td.className = "num";
    });
  });
  $("row-count").textContent = String(rows.length);
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  let s = String(v);
  // Stop spreadsheet apps from treating a value as a formula.
  if (/^[=+\-@\t\r]/.test(s) && !isNum(s)) s = "'" + s;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function downloadCsv() {
  if (!current) return;
  const { columns, rows } = current.data;
  const text = [columns, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "sql-insight-result.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function copySql() {
  const btn = $("copy-sql");
  try {
    await navigator.clipboard.writeText($("sql").textContent);
    btn.textContent = "Copied";
  } catch {
    btn.textContent = "Copy failed";
  }
  setTimeout(() => { btn.textContent = "Copy SQL"; }, 1500);
}

// ---------- tabs ----------

function selectTab(which) {
  const isData = which === "data";
  $("tab-data").setAttribute("aria-selected", String(isData));
  $("tab-sql").setAttribute("aria-selected", String(!isData));
  $("tab-data").tabIndex = isData ? 0 : -1;
  $("tab-sql").tabIndex = isData ? -1 : 0;
  show($("panel-data"), isData);
  show($("panel-sql"), !isData);
}

// ---------- chart ----------

function renderViz() {
  const { data, plan, measure } = current;
  const { columns, rows } = data;

  if (chart) { chart.destroy(); chart = null; }
  const visual = ["stat", "bar", "line"].includes(plan.kind);
  show($("viz"), visual);
  show($("stat"), plan.kind === "stat");
  show($("chart-box"), plan.kind === "bar" || plan.kind === "line");
  show($("viz-note"), false);
  if (!visual) return;

  // Several measures: let the reader switch rather than drawing a second axis.
  const picker = $("measure");
  picker.replaceChildren();
  plan.measures.forEach((i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = pretty(columns[i]);
    opt.selected = i === measure;
    picker.appendChild(opt);
  });
  show($("measure-picker"), plan.measures.length > 1);

  const measureName = pretty(columns[measure]);

  if (plan.kind === "stat") {
    const row = rows[0];
    $("viz-title").textContent = measureName;
    $("stat-value").textContent = row[measure] === null ? "No value" : fmt.format(Number(row[measure]));
    $("stat-label").textContent = plan.labelIdx >= 0 ? shortLabel(row[plan.labelIdx]) : "";
    return;
  }

  const horizontal = plan.kind === "bar";
  const limit = horizontal ? BAR_LIMIT : LINE_LIMIT;
  const shown = rows.slice(0, limit);
  const labels = shown.map((r) => axisLabel(r[plan.labelIdx], columns[plan.labelIdx]));
  const values = shown.map((r) => (r[measure] === null ? null : Number(r[measure])));

  $("viz-title").textContent = `${measureName} by ${pretty(columns[plan.labelIdx]).toLowerCase()}`;
  if (rows.length > limit) {
    $("viz-note").textContent = `The chart shows the first ${limit} rows. The Data tab has all ${rows.length}.`;
    show($("viz-note"), true);
  }

  const box = $("chart-box");
  box.style.height = horizontal ? `${Math.max(140, shown.length * 32 + 40)}px` : "300px";

  const c = {
    series: css("--series-1"), surface: css("--surface"), ink: css("--ink"), ink2: css("--ink-2"),
    muted: css("--muted"), grid: css("--grid"), axis: css("--axis"),
  };

  const canvas = $("chart");
  canvas.setAttribute("aria-label", `${$("viz-title").textContent}. Full values are in the Data tab.`);

  chart = new Chart(canvas, {
    type: horizontal ? "bar" : "line",
    data: {
      labels,
      datasets: [{
        label: measureName,
        data: values,
        backgroundColor: c.series,
        borderColor: c.series,
        borderWidth: horizontal ? 0 : 2,
        borderRadius: horizontal ? 4 : 0,
        borderSkipped: "start",
        barPercentage: 0.72,
        categoryPercentage: 0.9,
        maxBarThickness: 22,
        pointRadius: shown.length > 40 ? 0 : 4,
        pointHoverRadius: 6,
        pointBackgroundColor: c.series,
        pointBorderColor: c.surface,
        pointBorderWidth: 2,
        tension: 0,
      }],
    },
    options: {
      indexAxis: horizontal ? "y" : "x",
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      layout: { padding: { right: 12, top: 6 } },
      interaction: horizontal
        ? { mode: "nearest", axis: "y", intersect: false }
        : { mode: "index", intersect: false },
      plugins: {
        legend: { display: false }, // one series: the title names it
        tooltip: {
          backgroundColor: c.surface,
          titleColor: c.ink,
          bodyColor: c.ink2,
          borderColor: c.axis,
          borderWidth: 1,
          padding: 10,
          cornerRadius: 6,
          displayColors: false,
          callbacks: {
            label: (ctx) => `${measureName}: ${fmt.format(horizontal ? ctx.parsed.x : ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: horizontal ? c.grid : "transparent", drawTicks: false },
          border: { color: c.axis },
          ticks: horizontal
            ? { color: c.muted, padding: 8, callback: (v) => fmt.format(v) }
            : { color: c.muted, padding: 8, maxRotation: 0, autoSkip: true },
        },
        y: {
          beginAtZero: true,
          grid: { color: horizontal ? "transparent" : c.grid, drawTicks: false },
          border: { color: c.axis },
          ticks: horizontal
            ? { color: c.ink2, padding: 8, autoSkip: false,
                callback: function (v) { return truncate(this.getLabelForValue(v), box.clientWidth < 480 ? 14 : 30); } }
            : { color: c.muted, padding: 8, callback: (v) => fmt.format(v) },
        },
      },
    },
  });
}

// ---------- result ----------

// Show "X are A; B; and C." as a lead sentence plus a bullet list.
function renderAnswer(text) {
  const el = $("answer");
  el.replaceChildren();
  const parts = text.split(/;\s+/);
  if (parts.length < 3) { el.textContent = text; return; }

  let first = parts[0];
  const lead = first.match(/^(.*\b(?:are|were|is|was)\b|.*:)\s+(.+)$/);
  if (lead) {
    const p = document.createElement("div");
    p.textContent = lead[1].replace(/:$/, "") + ":";
    el.appendChild(p);
    first = lead[2];
  }
  const ul = document.createElement("ul");
  [first, ...parts.slice(1)].forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item.replace(/^and\s+/i, "").replace(/\.$/, "");
    ul.appendChild(li);
  });
  el.appendChild(ul);
}

function renderResult(entry) {
  const { data, question } = entry;
  const { columns = [], rows = [] } = data;
  const plan = planViz(columns, rows);
  current = { data, plan, measure: plan.measures ? plan.measures[0] : -1 };
  activeId = entry.id;

  show($("welcome"), false);
  $("asked").textContent = question;
  renderAnswer(data.answer || "Here is what the query returned.");
  $("sql").textContent = formatSql(data.sql || "");

  const refused = columns.length === 1 && columns[0] === "message";
  show($("details"), !refused);
  if (!refused) renderTable(columns, rows);
  $("download-csv").disabled = refused || rows.length === 0;
  selectTab("data");

  const secs = (data.latency_ms / 1000).toFixed(1);
  const attempts = data.attempts === 1 ? "first attempt" : `${data.attempts} attempts`;
  $("meta").textContent = `Answered in ${secs} s using ${fmt.format(data.tokens)} tokens, ${attempts}. Read-only query.`;

  show($("result"), true);
  renderViz();
  renderHistory();
}

function renderHistory() {
  const list = $("history-list");
  list.replaceChildren();
  show($("history-empty"), history.length === 0);
  history.forEach((h) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "history-item";
    if (h.id === activeId) b.setAttribute("aria-current", "true");
    b.textContent = h.question;
    const t = document.createElement("span");
    t.className = "history-time";
    t.textContent = timeFmt.format(h.at);
    b.appendChild(t);
    b.addEventListener("click", () => { clearStatus(); renderResult(h); });
    li.appendChild(b);
    list.appendChild(li);
  });
}

// ---------- status ----------

const ICONS = {
  warning: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 1.5 15 14H1L8 1.5Zm-.75 4.5v4h1.5V6h-1.5Zm0 5.25v1.5h1.5v-1.5h-1.5Z"/></svg>',
  blocked: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 1.5a5.5 5.5 0 0 1 4.38 8.83L4.67 3.62A5.48 5.48 0 0 1 8 2.5ZM3.62 4.67l7.71 7.71A5.5 5.5 0 0 1 3.62 4.67Z"/></svg>',
};

function setStatus(kind, title, detail) {
  const el = $("status");
  el.className = "status" + (kind === "error" ? " is-error" : kind === "blocked" ? " is-blocked" : "");
  el.replaceChildren();
  if (kind === "error" || kind === "blocked") {
    const holder = document.createElement("span");
    holder.innerHTML = ICONS[kind === "blocked" ? "blocked" : "warning"]; // static, trusted markup
    el.appendChild(holder.firstChild);
  }
  const text = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = title;
  text.appendChild(strong);
  if (detail) {
    const p = document.createElement("div");
    p.textContent = detail;
    text.appendChild(p);
  }
  el.appendChild(text);
  show(el, true);
}
function clearStatus() { show($("status"), false); }

// ---------- asking ----------

async function ask(question) {
  const button = $("ask-button");
  button.disabled = true;
  show($("progress"), true);
  show($("welcome"), false);
  show($("result"), false);

  const started = Date.now();
  const detail = "Writing the query, running it against the database, and summarising the result.";
  setStatus("progress", "Working on it", detail);
  timer = setInterval(() => {
    setStatus("progress", `Working on it, ${Math.round((Date.now() - started) / 1000)} s`, detail);
  }, 1000);

  try {
    const res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (res.status === 422) {
      setStatus("error", "Check the question", "Questions need between 3 and 500 characters.");
      return;
    }
    if (!res.ok) {
      setStatus("error", "The service didn't respond correctly", `Status ${res.status}. Try again in a moment.`);
      return;
    }
    const data = await res.json();
    if (data.blocked) {
      setStatus("blocked", "Blocked by the safety policy",
        "This request would have changed data or read system information, so it was not run.");
      return;
    }
    if (data.error) {
      setStatus("error", "Couldn't answer that question",
        "The generated query failed. Try rephrasing, or name the table or measure you mean.");
      return;
    }
    clearStatus();
    const entry = { id: Date.now(), question, data, at: new Date() };
    history.unshift(entry);
    history = history.slice(0, 20);
    renderResult(entry);
  } catch {
    setStatus("error", "Couldn't reach the service", "Check your connection and try again.");
  } finally {
    clearInterval(timer);
    show($("progress"), false);
    button.disabled = false;
  }
}

// ---------- wiring ----------

$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("question").value.trim();
  if (q.length >= 3) ask(q);
});

document.querySelectorAll(".example").forEach((b) => {
  b.addEventListener("click", () => {
    $("question").value = b.textContent;
    ask(b.textContent);
  });
});

$("measure").addEventListener("change", (e) => {
  if (!current) return;
  current.measure = Number(e.target.value);
  renderViz();
});

$("tab-data").addEventListener("click", () => selectTab("data"));
$("tab-sql").addEventListener("click", () => selectTab("sql"));
$("tab-data").parentElement.addEventListener("keydown", (e) => {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const toSql = $("tab-data").getAttribute("aria-selected") === "true";
  selectTab(toSql ? "sql" : "data");
  (toSql ? $("tab-sql") : $("tab-data")).focus();
});

$("download-csv").addEventListener("click", downloadCsv);
$("copy-sql").addEventListener("click", copySql);

// Redraw with the other palette when the system theme changes.
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (current) renderViz();
});
