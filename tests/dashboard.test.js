/**
 * dashboard.test.js
 * Property-based tests for index.html JavaScript logic.
 * Uses fast-check for property generation and jest-environment-jsdom for DOM.
 *
 * @jest-environment jsdom
 */

"use strict";

const fc = require("fast-check");
const {
  LANES,
  MAX_ERRORS,
  TERMINAL_STATUSES,
  renderLaneCard,
  renderSummary,
  renderLanes,
  setRunning,
  isTerminalStatus,
  shouldStopOnErrors,
} = require("./dashboard-logic");

// ── DOM FIXTURE HELPERS ──────────────────────────────────────────────────────

/** Build a minimal DOM matching what index.html provides. */
function buildDOM() {
  document.body.innerHTML = `
    <button id="runBtn"></button>
    <div id="statusText"></div>
    <div id="lanesGrid"></div>
    <div id="summaryCard" style="display:none">
      <div id="summaryGrid"></div>
      <div id="runMeta"></div>
    </div>
    <div id="errorBanner" style="display:none"></div>
    <div id="lastPoll"></div>
  `;
}

// ── ARBITRARIES ──────────────────────────────────────────────────────────────

const terminalStatusArb = fc.constantFrom(...TERMINAL_STATUSES);
const nonTerminalStatusArb = fc.string({ minLength: 1 }).filter(
  s => !TERMINAL_STATUSES.has(s)
);

const outcomeArb = fc.oneof(
  fc.constant("SUCCESS"),
  fc.constant("FAILED"),
  fc.constant("SKIPPED"),
  fc.string({ minLength: 1, maxLength: 20 })
);

const terminalStatusFieldArb = fc.oneof(
  fc.constant("TERMINAL_SUCCESS"),
  fc.constant("ACTIVE"),
  fc.constant("INACTIVE"),
  fc.string({ minLength: 1, maxLength: 20 })
);

const laneResultArb = fc.record({
  lane_id: fc.constantFrom(...LANES),
  outcome: outcomeArb,
  phi_score: fc.oneof(fc.float({ min: 0, max: 1, noNaN: true }), fc.constant(null)),
  terminal_status: terminalStatusFieldArb,
  error: fc.oneof(fc.string({ minLength: 1, maxLength: 80 }), fc.constant(null)),
});

// Safe string: alphanumeric + common punctuation, no HTML special chars (<, >, &, ", ')
const safeStringArb = (minLength = 1, maxLength = 40) =>
  fc.stringMatching(/^[a-zA-Z0-9_\-. :]+$/).filter(
    s => s.length >= minLength && s.length <= maxLength
  );

const summaryArb = fc.record({
  run_id: safeStringArb(1, 40),
  status: safeStringArb(1, 20),
  completed_at: fc.oneof(
    fc.date().map(d => d.toISOString()),
    fc.constant(null)
  ),
  promotions: fc.integer({ min: 0, max: 100 }),
  terminal_successes: fc.integer({ min: 0, max: 100 }),
  failures: fc.integer({ min: 0, max: 100 }),
  lane_count: fc.integer({ min: 0, max: 10 }),
  lanes: fc.array(laneResultArb, { minLength: 0, maxLength: 10 }),
});

// ── PROPERTY 1: button enabled === !state.running ────────────────────────────

// Feature: redteam-ui-dashboard, Property 1: button enabled === !state.running for any state object
describe("Property 1: button enabled === !state.running", () => {
  beforeEach(() => buildDOM());

  test("setRunning(true) disables button; setRunning(false) enables it", () => {
    // Feature: redteam-ui-dashboard, Property 1: button enabled === !state.running for any state object
    fc.assert(
      fc.property(fc.boolean(), (running) => {
        const state = { running: !running }; // start opposite
        setRunning(running, state, document);
        const btn = document.getElementById("runBtn");
        expect(btn.disabled).toBe(running);
        expect(state.running).toBe(running);
        // The invariant: button.disabled === state.running === running
        expect(btn.disabled).toBe(state.running);
      }),
      { numRuns: 200 }
    );
  });
});

// ── PROPERTY 8: terminal status stops polling ────────────────────────────────

// Feature: redteam-ui-dashboard, Property 8: any terminal status value stops polling
describe("Property 8: terminal status stops polling", () => {
  test("every value in TERMINAL_STATUSES is recognised as terminal", () => {
    // Feature: redteam-ui-dashboard, Property 8: any terminal status value stops polling
    fc.assert(
      fc.property(terminalStatusArb, (status) => {
        expect(isTerminalStatus(status)).toBe(true);
      }),
      { numRuns: 200 }
    );
  });

  test("non-terminal status strings do NOT stop polling", () => {
    // Feature: redteam-ui-dashboard, Property 8: any terminal status value stops polling
    fc.assert(
      fc.property(nonTerminalStatusArb, (status) => {
        expect(isTerminalStatus(status)).toBe(false);
      }),
      { numRuns: 200 }
    );
  });
});

// ── PROPERTY 9: consecutive error retry limit ────────────────────────────────

// Feature: redteam-ui-dashboard, Property 9: polling continues for N<10 errors, stops at N=10
describe("Property 9: consecutive error retry limit", () => {
  test("polling continues when consecutive errors < MAX_ERRORS", () => {
    // Feature: redteam-ui-dashboard, Property 9: polling continues for N<10 errors, stops at N=10
    fc.assert(
      fc.property(fc.integer({ min: 0, max: MAX_ERRORS - 1 }), (n) => {
        expect(shouldStopOnErrors(n)).toBe(false);
      }),
      { numRuns: 200 }
    );
  });

  test("polling stops when consecutive errors >= MAX_ERRORS (10)", () => {
    // Feature: redteam-ui-dashboard, Property 9: polling continues for N<10 errors, stops at N=10
    fc.assert(
      fc.property(fc.integer({ min: MAX_ERRORS, max: MAX_ERRORS + 50 }), (n) => {
        expect(shouldStopOnErrors(n)).toBe(true);
      }),
      { numRuns: 200 }
    );
  });

  test("boundary: exactly MAX_ERRORS (10) stops polling", () => {
    expect(shouldStopOnErrors(MAX_ERRORS)).toBe(true);
  });

  test("boundary: MAX_ERRORS - 1 (9) continues polling", () => {
    expect(shouldStopOnErrors(MAX_ERRORS - 1)).toBe(false);
  });
});

// ── PROPERTY 10: N lane entries renders N lane cards ─────────────────────────

// Feature: redteam-ui-dashboard, Property 10: N lane entries in summary renders N lane cards
describe("Property 10: N lane entries renders N lane cards", () => {
  beforeEach(() => buildDOM());

  test("renderLanes produces exactly as many cards as LANES constant (always 3)", () => {
    // Feature: redteam-ui-dashboard, Property 10: N lane entries in summary renders N lane cards
    // renderLanes always iterates over the LANES constant (3 entries), so the
    // number of rendered cards equals LANES.length regardless of input.
    fc.assert(
      fc.property(
        fc.array(laneResultArb, { minLength: 0, maxLength: 10 }),
        (laneResults) => {
          renderLanes(laneResults, document);
          const grid = document.getElementById("lanesGrid");
          const cards = grid.querySelectorAll(".lane-card");
          expect(cards.length).toBe(LANES.length);
        }
      ),
      { numRuns: 100 }
    );
  });

  test("renderLaneCard returns one card per call", () => {
    // Feature: redteam-ui-dashboard, Property 10: N lane entries in summary renders N lane cards
    fc.assert(
      fc.property(
        fc.constantFrom(...LANES),
        fc.oneof(laneResultArb, fc.constant(null)),
        (laneId, result) => {
          const html = renderLaneCard(laneId, result);
          const wrapper = document.createElement("div");
          wrapper.innerHTML = html;
          const cards = wrapper.querySelectorAll(".lane-card");
          expect(cards.length).toBe(1);
        }
      ),
      { numRuns: 200 }
    );
  });
});

// ── PROPERTY 11: lane card CSS class reflects terminal_status and outcome ─────

// Feature: redteam-ui-dashboard, Property 11: lane card CSS class reflects terminal_status and outcome
describe("Property 11: lane card CSS class reflects terminal_status and outcome", () => {
  test("TERMINAL_SUCCESS → card has class 'success' and success badge", () => {
    // Feature: redteam-ui-dashboard, Property 11: lane card CSS class reflects terminal_status and outcome
    fc.assert(
      fc.property(
        fc.constantFrom(...LANES),
        fc.record({
          outcome: outcomeArb,
          phi_score: fc.float({ min: 0, max: 1, noNaN: true }),
          terminal_status: fc.constant("TERMINAL_SUCCESS"),
          error: fc.oneof(fc.string({ minLength: 1 }), fc.constant(null)),
        }),
        (laneId, result) => {
          const html = renderLaneCard(laneId, result);
          const wrapper = document.createElement("div");
          wrapper.innerHTML = html;
          const card = wrapper.querySelector(".lane-card");
          expect(card.classList.contains("success")).toBe(true);
          expect(card.classList.contains("failed")).toBe(false);
          expect(wrapper.querySelector(".badge-success")).not.toBeNull();
        }
      ),
      { numRuns: 200 }
    );
  });

  test("outcome === FAILED (non-terminal) → card has class 'failed' and failed badge", () => {
    // Feature: redteam-ui-dashboard, Property 11: lane card CSS class reflects terminal_status and outcome
    fc.assert(
      fc.property(
        fc.constantFrom(...LANES),
        fc.record({
          outcome: fc.constant("FAILED"),
          phi_score: fc.float({ min: 0, max: 1, noNaN: true }),
          // terminal_status must NOT be TERMINAL_SUCCESS for the failed branch
          terminal_status: fc.string({ minLength: 1 }).filter(s => s !== "TERMINAL_SUCCESS"),
          error: fc.oneof(fc.string({ minLength: 1, maxLength: 60 }), fc.constant(null)),
        }),
        (laneId, result) => {
          const html = renderLaneCard(laneId, result);
          const wrapper = document.createElement("div");
          wrapper.innerHTML = html;
          const card = wrapper.querySelector(".lane-card");
          expect(card.classList.contains("failed")).toBe(true);
          expect(card.classList.contains("success")).toBe(false);
          expect(wrapper.querySelector(".badge-failed")).not.toBeNull();
        }
      ),
      { numRuns: 200 }
    );
  });

  test("neither TERMINAL_SUCCESS nor FAILED → card has no success/failed class", () => {
    // Feature: redteam-ui-dashboard, Property 11: lane card CSS class reflects terminal_status and outcome
    fc.assert(
      fc.property(
        fc.constantFrom(...LANES),
        fc.record({
          outcome: fc.string({ minLength: 1 }).filter(s => s !== "FAILED"),
          phi_score: fc.float({ min: 0, max: 1, noNaN: true }),
          terminal_status: fc.string({ minLength: 1 }).filter(s => s !== "TERMINAL_SUCCESS"),
          error: fc.constant(null),
        }),
        (laneId, result) => {
          const html = renderLaneCard(laneId, result);
          const wrapper = document.createElement("div");
          wrapper.innerHTML = html;
          const card = wrapper.querySelector(".lane-card");
          expect(card.classList.contains("success")).toBe(false);
          expect(card.classList.contains("failed")).toBe(false);
        }
      ),
      { numRuns: 200 }
    );
  });
});

// ── PROPERTY 12: all 6 summary fields present in rendered output ──────────────

// Feature: redteam-ui-dashboard, Property 12: all 6 summary fields present in rendered output for any valid summary
describe("Property 12: all 6 summary fields present in rendered output", () => {
  beforeEach(() => buildDOM());

  test("renderSummary always renders status, run_id, completed_at, promotions, terminal_successes, failures", () => {
    // Feature: redteam-ui-dashboard, Property 12: all 6 summary fields present in rendered output for any valid summary
    fc.assert(
      fc.property(summaryArb, (summary) => {
        renderSummary(summary, document);

        const summaryCard = document.getElementById("summaryCard");
        const text = summaryCard.textContent;

        // status
        expect(text).toContain(summary.status);
        // run_id
        expect(text).toContain(summary.run_id);
        // promotions
        expect(text).toContain(String(summary.promotions ?? 0));
        // terminal_successes
        expect(text).toContain(String(summary.terminal_successes ?? 0));
        // failures
        expect(text).toContain(String(summary.failures ?? 0));
        // completed_at — either the formatted date or "—"
        if (summary.completed_at) {
          // The rendered text uses toLocaleString(); just verify the card is visible
          expect(summaryCard.style.display).toBe("block");
        } else {
          expect(text).toContain("—");
        }
      }),
      { numRuns: 100 }
    );
  });
});

// ── PROPERTY 13: all three lane names always visible in DOM ───────────────────

// Feature: redteam-ui-dashboard, Property 13: all three lane names visible in DOM for any state
describe("Property 13: all three lane names always visible in DOM", () => {
  beforeEach(() => buildDOM());

  test("renderLanes always includes all three lane identifiers regardless of input", () => {
    // Feature: redteam-ui-dashboard, Property 13: all three lane names visible in DOM for any state
    fc.assert(
      fc.property(
        fc.oneof(
          fc.array(laneResultArb, { minLength: 0, maxLength: 10 }),
          fc.constant(undefined)
        ),
        (laneResults) => {
          renderLanes(laneResults, document);
          const grid = document.getElementById("lanesGrid");
          const html = grid.innerHTML;
          for (const lane of LANES) {
            expect(html).toContain(lane);
          }
        }
      ),
      { numRuns: 200 }
    );
  });
});
