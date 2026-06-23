/**
 * Kaseya VSA Dashboard — Frontend Logic
 * Fetches data from backend and renders dashboard.
 */

// ── Config ──────────────────────────────────────────────
const API_BASE = "http://127.0.0.1:3000/api";
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

// ── State ───────────────────────────────────────────────
let dashboardData = null;
let currentTab = "all";
let lastFetchTime = null;
let refreshTimer = null;

// ── Helpers ─────────────────────────────────────────────
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function statusClass(status) {
  const s = (status || "").toLowerCase();
  if (["online", "1", "true", "active"].includes(s)) return "online";
  if (["offline", "0", "false", "inactive"].includes(s)) return "offline";
  return "warning";
}

function severityClass(sev) {
  const s = (sev || "").toLowerCase();
  if (["critical", "high", "error", "major"].includes(s)) return "critical";
  if (["warning", "medium", "minor"].includes(s)) return "warning";
  return "info";
}

function barClass(value) {
  const v = parseFloat(value);
  if (isNaN(v)) return "low";
  if (v >= 85) return "high";
  if (v >= 60) return "medium";
  return "low";
}

function timeAgo(dateStr) {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diff = Math.floor((now - d) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return dateStr;
  }
}

// ── API Calls ───────────────────────────────────────────
async function fetchDashboard() {
  showLoading(true);
  hideError();
  try {
    const resp = await fetch(`${API_BASE}/dashboard`);
    if (!resp.ok) {
      throw new Error(`Backend error: ${resp.status} ${resp.statusText}`);
    }
    dashboardData = await resp.json();
    lastFetchTime = new Date();
    renderAll();
    updateRefreshLabel();
  } catch (err) {
    showError(err.message);
  } finally {
    showLoading(false);
  }
}

// ── Render: Summary Cards ──────────────────────────────
function renderCards() {
  const agents = dashboardData?.agents || {};
  const alerts = dashboardData?.alerts || {};
  const monitor = dashboardData?.monitor || {};

  const total = agents.total || 0;
  const online = (agents.status_counts || {}).online || 0;
  const offline = (agents.status_counts || {}).offline || 0;
  const unknown = (agents.status_counts || {}).unknown || 0;
  const totalAlerts = alerts.total || 0;
  const critical = (alerts.severity_counts || {}).critical || 0;
  const warning = (alerts.severity_counts || {}).warning || 0;
  const totalCounters = monitor.total || 0;

  const html = `
    <div class="card blue">
      <div class="card-label">Total Agents</div>
      <div class="card-value">${total}</div>
      <div class="card-sub">Registered endpoints</div>
    </div>
    <div class="card green">
      <div class="card-label">🟢 Online</div>
      <div class="card-value">${online}</div>
      <div class="card-sub">${total > 0 ? Math.round((online / total) * 100) : 0}% of total</div>
    </div>
    <div class="card red">
      <div class="card-label">🔴 Offline</div>
      <div class="card-value">${offline}</div>
      <div class="card-sub">${unknown > 0 ? `+ ${unknown} unknown` : "Needs attention"}</div>
    </div>
    <div class="card orange">
      <div class="card-label">⚠️ Active Alerts</div>
      <div class="card-value">${totalAlerts}</div>
      <div class="card-sub">${critical} critical · ${warning} warning</div>
    </div>
    <div class="card blue">
      <div class="card-label">📊 Monitor Counters</div>
      <div class="card-value">${totalCounters}</div>
      <div class="card-sub">CPU / Disk / Memory data points</div>
    </div>
  `;
  $("#cards").innerHTML = html;
}

// ── Render: Agents Table ───────────────────────────────
function renderAgentsTable() {
  const agents = (dashboardData?.agents?.agents || []);
  const filter = currentTab;

  let filtered = agents;
  if (filter === "online") {
    filtered = agents.filter(a => statusClass(a.status) === "online");
  } else if (filter === "offline") {
    filtered = agents.filter(a => statusClass(a.status) === "offline");
  } else if (filter === "problem") {
    // Agents that are offline OR have alerts
    const alertAgents = new Set(
      (dashboardData?.alerts?.alerts || []).map(a => a.agent).filter(Boolean)
    );
    filtered = agents.filter(a =>
      statusClass(a.status) === "offline" || alertAgents.has(a.name) || alertAgents.has(a.id)
    );
  }

  if (filtered.length === 0) {
    $("#agents-table-wrap").innerHTML = `<div class="empty-state">No agents to display</div>`;
    return;
  }

  const rows = filtered.map(a => {
    const sc = statusClass(a.status);
    return `
      <tr>
        <td><strong>${a.name || a.id || "—"}</strong></td>
        <td>${a.group || "—"}</td>
        <td><span class="indicator ${sc}">● ${a.status || "unknown"}</span></td>
        <td>${a.os || "—"}</td>
        <td>${a.ip || "—"}</td>
        <td style="color: var(--text-dim); font-size: 0.8rem;">${timeAgo(a.lastCheckIn)}</td>
      </tr>
    `;
  }).join("");

  $("#agents-table-wrap").innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Agent Name</th>
            <th>Group</th>
            <th>Status</th>
            <th>OS</th>
            <th>IP Address</th>
            <th>Last Check-in</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

// ── Render: Alerts Table ───────────────────────────────
function renderAlertsTable() {
  const alerts = dashboardData?.alerts?.alerts || [];

  if (alerts.length === 0) {
    $("#alerts-table-wrap").innerHTML = `<div class="empty-state">✅ No active alerts</div>`;
    return;
  }

  const rows = alerts.slice(0, 50).map(a => {
    const sev = severityClass(a.severity);
    return `
      <tr>
        <td>${a.agent || "—"}</td>
        <td>${a.type || "—"}</td>
        <td><span class="indicator ${sev}">${a.severity || "info"}</span></td>
        <td>${a.message || "—"}</td>
        <td style="color: var(--text-dim); font-size: 0.8rem;">${timeAgo(a.timestamp)}</td>
      </tr>
    `;
  }).join("");

  $("#alerts-table-wrap").innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Type</th>
            <th>Severity</th>
            <th>Message</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

// ── Render: Monitor Counters ───────────────────────────
function renderMonitorTable() {
  const counters = dashboardData?.monitor?.counters || [];

  if (counters.length === 0) {
    $("#monitor-table-wrap").innerHTML = `<div class="empty-state">No monitor counter data available</div>`;
    return;
  }

  const rows = counters.slice(0, 50).map(c => {
    const bc = barClass(c.value);
    const val = parseFloat(c.value);
    const displayVal = isNaN(val) ? c.value : `${val.toFixed(1)}%`;
    return `
      <tr>
        <td>${c.agent || "—"}</td>
        <td>${c.counter || "—"}</td>
        <td>
          <div style="display:flex;align-items:center;gap:8px;">
            <div class="bar" style="width:100px;">
              <div class="bar-fill ${bc}" style="width:${isNaN(val) ? 0 : val}%;"></div>
            </div>
            <span style="font-weight:600;min-width:45px;">${displayVal}</span>
          </div>
        </td>
        <td style="color: var(--text-dim); font-size: 0.8rem;">${timeAgo(c.timestamp)}</td>
      </tr>
    `;
  }).join("");

  $("#monitor-table-wrap").innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Counter</th>
            <th>Value</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

// ── Tabs ───────────────────────────────────────────────
function initTabs() {
  $$(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      $$(".tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentTab = tab.dataset.tab;
      renderAgentsTable();
    });
  });
}

// ── UI Helpers ─────────────────────────────────────────
function showLoading(show) {
  const el = $("#loading");
  if (el) el.style.display = show ? "block" : "none";
}

function showError(msg) {
  const el = $("#error-box");
  if (el) {
    el.style.display = "block";
    el.innerHTML = `<strong>⚠️ Error:</strong> ${msg}<br><small>Make sure the backend is running on localhost:8080</small>`;
  }
}

function hideError() {
  const el = $("#error-box");
  if (el) el.style.display = "none";
}

function updateRefreshLabel() {
  const el = $("#last-refresh");
  if (el && lastFetchTime) {
    el.textContent = `Last updated: ${lastFetchTime.toLocaleTimeString()}`;
  }
}

function renderAll() {
  renderCards();
  renderAgentsTable();
  renderAlertsTable();
  renderMonitorTable();
}

// ── Auto-refresh ──────────────────────────────────────
function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(fetchDashboard, REFRESH_INTERVAL);
}

// ── Init ───────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  fetchDashboard();
  startAutoRefresh();

  $("#btn-refresh").addEventListener("click", () => {
    fetchDashboard();
  });
});
