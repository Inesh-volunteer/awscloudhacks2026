/**
 * dashboard-logic.js
 * Pure functions and constants extracted from src/dashboard/index.html
 * for testability. DOM-dependent functions accept a `document` parameter.
 */

// ── CONSTANTS ────────────────────────────────────────────────────────────────

const LANES = ["OBJ_WEB_BYPASS", "OBJ_IDENTITY_ESCALATION", "OBJ_WAF_BYPASS"];
const POLL_INTERVAL_MS = 5000;
const MAX_ERRORS = 10;
const TERMINAL_STATUSES = new Set(["SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"]);

// ── PURE FUNCTIONS ───────────────────────────────────────────────────────────

/**
 * Returns the HTML string for a single lane card.
 * @param {string} laneId
 * @param {object|null} result
 * @returns {string}
 */
function renderLaneCard(laneId, result) {
  if (!result) {
    return `
        <div class="lane-card">
          <div class="lane-name">${laneId}</div>
          <div class="lane-status">Idle</div>
          <div class="lane-phi">φ —</div>
        </div>`;
  }

  const isTerminal = result.terminal_status === "TERMINAL_SUCCESS";
  const isFailed   = result.outcome === "FAILED";
  const cls = isTerminal ? "success" : isFailed ? "failed" : "";
  const badge = isTerminal
    ? `<span class="badge-success">✓ Terminal Success</span>`
    : isFailed
    ? `<span class="badge-failed">✗ Failed</span>`
    : "";
  const errorLine = isFailed && result.error
    ? `<div class="lane-error">${result.error}</div>`
    : "";

  return `
      <div class="lane-card ${cls}">
        <div class="lane-name">${laneId}</div>
        <div class="lane-status">${result.outcome || "—"}${badge}</div>
        <div class="lane-phi">φ ${result.phi_score != null ? Number(result.phi_score).toFixed(2) : "—"}</div>
        ${errorLine}
      </div>`;
}

/**
 * Renders the summary panel into the DOM.
 * @param {object} summary
 * @param {Document} doc
 */
function renderSummary(summary, doc) {
  const card = doc.getElementById("summaryCard");
  card.style.display = "block";

  doc.getElementById("summaryGrid").innerHTML = `
      <div class="summary-stat">
        <div class="val">${summary.lane_count ?? "—"}</div>
        <div class="lbl">Lanes</div>
      </div>
      <div class="summary-stat">
        <div class="val" style="color:#58a6ff">${summary.promotions ?? 0}</div>
        <div class="lbl">Promotions</div>
      </div>
      <div class="summary-stat">
        <div class="val" style="color:#3fb950">${summary.terminal_successes ?? 0}</div>
        <div class="lbl">Terminal Successes</div>
      </div>
      <div class="summary-stat">
        <div class="val" style="color:#f85149">${summary.failures ?? 0}</div>
        <div class="lbl">Failures</div>
      </div>
    `;

  doc.getElementById("runMeta").innerHTML = `
      Status: <span>${summary.status}</span> &nbsp;|&nbsp;
      Run ID: <span>${summary.run_id}</span> &nbsp;|&nbsp;
      Completed: <span>${summary.completed_at ? new Date(summary.completed_at).toLocaleString() : "—"}</span>
    `;
}

/**
 * Renders all lane cards into the DOM.
 * @param {Array|undefined} laneResults
 * @param {Document} doc
 */
function renderLanes(laneResults, doc) {
  const grid = doc.getElementById("lanesGrid");
  grid.innerHTML = LANES.map(laneId => {
    const r = laneResults ? laneResults.find(l => l.lane_id === laneId) : null;
    return renderLaneCard(laneId, r);
  }).join("");
}

/**
 * Sets the running state and updates the button disabled attribute.
 * @param {boolean} running
 * @param {object} state  — mutable state object
 * @param {Document} doc
 */
function setRunning(running, state, doc) {
  state.running = running;
  doc.getElementById("runBtn").disabled = running;
}

// ── POLLING LOGIC HELPERS ────────────────────────────────────────────────────

/**
 * Returns true if the given status should stop polling.
 * @param {string} status
 * @returns {boolean}
 */
function isTerminalStatus(status) {
  return TERMINAL_STATUSES.has(status);
}

/**
 * Given a consecutive error count, returns whether polling should stop.
 * Mirrors the logic: if (consecutiveErrors >= MAX_ERRORS) stopPolling()
 * @param {number} consecutiveErrors
 * @returns {boolean}
 */
function shouldStopOnErrors(consecutiveErrors) {
  return consecutiveErrors >= MAX_ERRORS;
}

// ── EXPORTS ──────────────────────────────────────────────────────────────────

module.exports = {
  LANES,
  POLL_INTERVAL_MS,
  MAX_ERRORS,
  TERMINAL_STATUSES,
  renderLaneCard,
  renderSummary,
  renderLanes,
  setRunning,
  isTerminalStatus,
  shouldStopOnErrors,
};
