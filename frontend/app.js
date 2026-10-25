const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");
const form = document.getElementById("claim-form");
const statusEl = document.getElementById("status");
const submitBtn = document.getElementById("submit-btn");
const resultsSection = document.getElementById("results");
const claimsBody = document.querySelector("#claims-table tbody");
const summarySection = document.getElementById("summary-section");
const summaryText = document.getElementById("summary-text");
const verdictsSection = document.getElementById("verdicts-section");
const verdictsContainer = document.getElementById("verdicts");
const videoVerdictBanner = document.getElementById("video-verdict-banner");
const videoVerdictBannerInner = videoVerdictBanner.querySelector(".verdict-banner");
const videoVerdictLabel = document.getElementById("video-verdict-label");
const videoVerdictExplanation = document.getElementById("video-verdict-explanation");
const videoVerdictTechniques = document.getElementById("video-verdict-techniques");
const explainerSection = document.getElementById("explainer-section");
const explainerVersionsContainer = document.getElementById("explainer-versions");
const agentSection = document.getElementById("agent-section");
const agentStatusEl = document.getElementById("agent-status");
const agentDownloadLink = document.getElementById("agent-download-link");
const agentSourcesSummary = document.getElementById("agent-sources-summary");
const traceSection = document.getElementById("trace-section");
const traceGrid = document.getElementById("trace-grid");
const traceSummaryLine = document.getElementById("trace-summary-line");
const traceToggleBtn = document.getElementById("trace-toggle-btn");
const replayBanner = document.getElementById("replay-banner");
const replayBannerDate = document.getElementById("replay-banner-date");
const replayBannerClose = document.getElementById("replay-banner-close");
const pastRunsEmpty = document.getElementById("past-runs-empty");
const pastRunsList = document.getElementById("past-runs-list");
const pastRunsRefreshBtn = document.getElementById("past-runs-refresh-btn");
const stepButtons = document.querySelectorAll(".step-indicator .step");
const screens = document.querySelectorAll(".screen");
const traceStatusEl = document.getElementById("trace-status");
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let activeTab = "youtube";
let currentClaims = [];
let currentVerdicts = [];
let isReplaying = false;
let investigatedCount = 0;
let totalToInvestigate = 0;
let agentPollHandle = null;

// --- Three-screen flow: Start -> Investigation -> Report. Live runs and replays both ---
// --- drive the same screens through the same handleEvent() dispatcher. ---
const SCREEN_ORDER = ["start", "investigation", "report"];
let currentScreen = "start";
let investigationReady = false;
let reportReady = false;

function screenReachable(step) {
  if (step === "start") return true;
  if (step === "investigation") return investigationReady;
  if (step === "report") return reportReady;
  return false;
}

function updateStepIndicator() {
  stepButtons.forEach((btn) => {
    const step = btn.dataset.step;
    const reachable = screenReachable(step);
    btn.disabled = !reachable;
    btn.classList.toggle("active", step === currentScreen);
    btn.classList.toggle("done", SCREEN_ORDER.indexOf(step) < SCREEN_ORDER.indexOf(currentScreen) && reachable);
  });
}

function showScreen(name) {
  currentScreen = name;
  screens.forEach((s) => {
    s.hidden = s.dataset.screen !== name;
  });
  updateStepIndicator();
  window.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : "smooth" });
}

stepButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    if (!btn.disabled) showScreen(btn.dataset.step);
  });
});

// --- Live trace panel: one card per real pipeline step/agent call. ---
const traceCards = new Map();
let traceOrder = [];
let traceStartTime = null;
let traceTimerHandle = null;
let tracePipelineDone = false;
let traceAgentStarted = false;
let traceAgentSettled = false;
let traceCollapsed = false;
let traceSummaryCache = null;

function truncate(str, maxLen) {
  if (!str) return "";
  return str.length > maxLen ? `${str.slice(0, maxLen - 1)}…` : str;
}

function formatElapsed(ms) {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

function resetTrace() {
  traceCards.clear();
  traceOrder = [];
  traceGrid.innerHTML = "";
  traceStartTime = Date.now();
  tracePipelineDone = false;
  traceAgentStarted = false;
  traceAgentSettled = false;
  traceCollapsed = false;
  traceSummaryCache = null;
  traceSection.hidden = false;
  traceGrid.hidden = false;
  traceSummaryLine.hidden = true;
  traceToggleBtn.hidden = false;
  traceToggleBtn.textContent = "Collapse";
  if (traceTimerHandle) clearInterval(traceTimerHandle);
  traceTimerHandle = setInterval(updateTraceElapsedTimes, 1000);
}

// --- Investigation-team icons: one per agent role, monoline SVG, no external assets. ---
const ROLE_ICONS = {
  extractor:
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"/><circle cx="12" cy="12" r="3"/>',
  investigator: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  judge:
    '<path d="M12 3v18M5 7h14M9 3h6"/><path d="M7 7l-4 8a4 4 0 0 0 8 0L7 7Z"/><path d="M17 7l-4 8a4 4 0 0 0 8 0l-4-8Z"/>',
  explainer:
    '<rect x="3" y="6" width="18" height="14" rx="1.5"/><path d="M3 10h18M7 6 5 10m6-4-2 4m6-4-2 4"/>',
  critic: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16 9.5"/>',
  fixer:
    '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l2.6-2.6a4 4 0 0 1-5.3 5.3L6.7 20.3a2 2 0 1 1-2.8-2.8L12.2 9a4 4 0 0 1 5.3-5.3l-2.6 2.6Z"/>',
  agent: '<path d="M12 2 4 5v6c0 5 3.5 9 8 11 4.5-2 8-6 8-11V5l-8-3Z"/>',
  narrator: '<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/>',
};

function roleIconSvg(role) {
  const path = ROLE_ICONS[role] || ROLE_ICONS.investigator;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
}

function createTraceCard(id, title, modelLabel, modelClass, role) {
  if (traceCards.has(id)) return traceCards.get(id);
  const el = document.createElement("div");
  el.className = "trace-card status-waiting";
  el.innerHTML = `
    <div class="trace-card-title-row">
      <span class="trace-card-icon role-${role}">${roleIconSvg(role)}</span>
      <span class="trace-card-title">${title}</span>
    </div>
    <span class="model-badge ${modelClass}">${modelLabel}</span>
    <div class="trace-card-status-row">
      <span class="trace-card-status-label">waiting</span>
      <span class="trace-card-elapsed"></span>
    </div>
    <div class="trace-card-logs"></div>
  `;
  traceGrid.appendChild(el);
  const card = { el, status: "waiting", startedAt: null, elapsedMs: 0, logs: [], modelLabel };
  traceCards.set(id, card);
  traceOrder.push(id);
  return card;
}

function updateCardElapsedDisplay(id) {
  const card = traceCards.get(id);
  if (!card) return;
  const el = card.el.querySelector(".trace-card-elapsed");
  if (card.status === "running" && card.startedAt) {
    el.textContent = formatElapsed(Date.now() - card.startedAt);
  } else if (card.status === "done" || card.status === "failed") {
    el.textContent = formatElapsed(card.elapsedMs);
  } else {
    el.textContent = "";
  }
}

function updateTraceElapsedTimes() {
  traceOrder.forEach((id) => {
    const card = traceCards.get(id);
    if (card && card.status === "running") updateCardElapsedDisplay(id);
  });
}

function addTraceLog(id, text) {
  const card = traceCards.get(id);
  if (!card || !text) return;
  card.logs.push(text);
  if (card.logs.length > 3) card.logs = card.logs.slice(-3);
  card.el.querySelector(".trace-card-logs").innerHTML = card.logs.map((l) => `<div>${l}</div>`).join("");
}

function setTraceStatus(id, status, log) {
  const card = traceCards.get(id);
  if (!card) return;
  card.status = status;
  card.el.className = `trace-card status-${status}`;
  if (status === "running" && !card.startedAt) {
    card.startedAt = Date.now();
  }
  if ((status === "done" || status === "failed") && card.startedAt) {
    card.elapsedMs = Date.now() - card.startedAt;
  }
  const labelEl = card.el.querySelector(".trace-card-status-label");
  if (status === "running") {
    labelEl.innerHTML = '<span class="spinner-inline"></span> running';
  } else {
    labelEl.textContent = status;
  }
  if (log) addTraceLog(id, log);
  updateCardElapsedDisplay(id);
}

function computeTraceSummary() {
  const totalCards = traceOrder.length;
  const models = new Set();
  let criticRounds = 0;
  traceOrder.forEach((id) => {
    const card = traceCards.get(id);
    if (card && card.modelLabel) models.add(card.modelLabel);
    if (id.startsWith("critic-")) criticRounds += 1;
  });
  const totalElapsed = formatElapsed(Date.now() - traceStartTime);
  return `${totalCards} agent${totalCards === 1 ? "" : "s"} · ${models.size} model${models.size === 1 ? "" : "s"} · ${criticRounds} critic round${criticRounds === 1 ? "" : "s"} · ${totalElapsed}`;
}

function setTraceCollapsed(collapsed) {
  traceCollapsed = collapsed;
  traceGrid.hidden = collapsed;
  traceToggleBtn.textContent = collapsed ? "Expand" : "Collapse";
  traceSummaryLine.hidden = !(collapsed && traceSummaryCache);
  if (collapsed && traceSummaryCache) {
    traceSummaryLine.textContent = traceSummaryCache;
  }
}

function checkTraceSettled() {
  if (tracePipelineDone && (!traceAgentStarted || traceAgentSettled)) {
    if (traceTimerHandle) {
      clearInterval(traceTimerHandle);
      traceTimerHandle = null;
    }
    traceSummaryCache = computeTraceSummary();
    setTraceCollapsed(true);
    if (!isReplaying && typeof loadPastRuns === "function") {
      loadPastRuns();
    }
  }
}

traceToggleBtn.addEventListener("click", () => setTraceCollapsed(!traceCollapsed));

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    activeTab = btn.dataset.tab;
    tabButtons.forEach((b) => b.classList.toggle("active", b === btn));
    tabPanels.forEach((p) => (p.hidden = p.dataset.panel !== activeTab));
  });
});

function setStatus(message, isError = false) {
  [statusEl, traceStatusEl].forEach((el) => {
    if (!el) return;
    el.hidden = !message;
    el.textContent = message;
    el.classList.toggle("error", isError);
  });
}

function resetResults() {
  currentClaims = [];
  currentVerdicts = [];
  investigatedCount = 0;
  totalToInvestigate = 0;
  claimsBody.innerHTML = "";
  verdictsContainer.innerHTML = "";
  summaryText.textContent = "";
  resultsSection.hidden = true;
  summarySection.hidden = true;
  verdictsSection.hidden = true;
  videoVerdictBanner.hidden = true;
  explainerSection.hidden = true;
  explainerVersionsContainer.innerHTML = "";
  agentSection.hidden = true;
  agentStatusEl.textContent = "";
  agentStatusEl.classList.remove("agent-error");
  agentDownloadLink.hidden = true;
  agentSourcesSummary.innerHTML = "";
  if (agentPollHandle) {
    clearTimeout(agentPollHandle);
    agentPollHandle = null;
  }
}

function renderExplainerVersions(versions) {
  explainerVersionsContainer.innerHTML = "";
  if (!versions || versions.length === 0) {
    explainerSection.hidden = true;
    return;
  }
  versions.forEach((v) => {
    const card = document.createElement("div");
    card.className = `version-card ${v.approved ? "version-approved" : "version-rejected"}`;
    const statusLabel = v.approved ? "✓ Approved" : `${v.issues.length} issue${v.issues.length === 1 ? "" : "s"}`;
    const checksHtml = (v.checks || [])
      .map(
        (c) =>
          `<div class="check-row ${c.passed ? "pass" : "fail"}">${c.passed ? "✓" : "✗"} ${c.check.replace(/_/g, " ")}</div>`
      )
      .join("");
    const issuesHtml =
      v.issues && v.issues.length
        ? `<ul class="issues-list">${v.issues
            .map(
              (i) =>
                `<li><span class="issue-slide">${i.slide}</span> (${i.timestamp}): ${i.description}</li>`
            )
            .join("")}</ul>`
        : "";
    card.innerHTML = `
      <div class="version-card-header">
        <span class="version-badge">v${v.version}</span>
        <span class="version-status ${v.approved ? "approved" : "rejected"}">${statusLabel}</span>
      </div>
      <div class="explainer-frame-wrap">
        <iframe src="${v.url}" title="Explainer v${v.version}" loading="lazy"></iframe>
      </div>
      <a class="explainer-link" href="${v.url}" target="_blank" rel="noopener noreferrer">Open full screen ↗</a>
      <div class="critic-notes">
        <div class="checks-list">${checksHtml}</div>
        ${issuesHtml}
      </div>
    `;
    explainerVersionsContainer.appendChild(card);
  });
  explainerSection.hidden = false;
}

function renderClaimsTable(claims) {
  currentClaims = claims;
  claimsBody.innerHTML = "";
  claims.forEach((claim, i) => {
    const row = document.createElement("tr");
    row.id = `claim-row-${i}`;
    const repeatedBadge =
      claim.timestamps.length > 1 ? `<span class="repeated-badge">repeated ${claim.timestamps.length}x</span>` : "";
    row.innerHTML = `
      <td>${i + 1}</td>
      <td>${claim.timestamps.join(", ")}${repeatedBadge}</td>
      <td>${claim.speaker}</td>
      <td>${claim.exact_wording}</td>
      <td><span class="badge badge-${claim.claim_type}">${claim.claim_type}</span></td>
      <td class="status-cell" id="status-cell-${i}">pending</td>
    `;
    claimsBody.appendChild(row);
  });
  resultsSection.hidden = claims.length === 0;
}

function renderVideoVerdict(videoVerdict) {
  if (!videoVerdict) {
    videoVerdictBanner.hidden = true;
    return;
  }
  videoVerdictBannerInner.className = `verdict-banner banner-${videoVerdict.verdict}`;
  videoVerdictLabel.textContent = videoVerdict.verdict;
  videoVerdictExplanation.textContent = videoVerdict.explanation;
  videoVerdictTechniques.innerHTML = (videoVerdict.techniques || [])
    .map((t) => `<span class="technique-badge">${t}</span>`)
    .join("");
  videoVerdictBanner.hidden = false;
}

function setAllStatusCells(label, cssClass) {
  currentClaims.forEach((_, i) => setStatusCell(i, label, cssClass));
}

function setStatusCell(index, label, cssClass) {
  const cell = document.getElementById(`status-cell-${index}`);
  if (!cell) return;
  cell.className = `status-cell ${cssClass || ""}`.trim();
  cell.innerHTML = cssClass === "status-investigating" ? `<span class="spinner"></span>${label}` : label;
}

function sourcesHtml(sources, claimIndex) {
  if (!sources || sources.length === 0) {
    return '<span class="no-sources">No sources</span>';
  }
  return sources
    .map(
      (s) =>
        `<a href="${s.url}" target="_blank" rel="noopener noreferrer" data-source-key="${claimIndex}|${s.url}">${s.title || s.url}</a>`
    )
    .join("");
}

function renderVerdicts(verdicts) {
  currentVerdicts = verdicts;
  verdictsContainer.innerHTML = "";
  verdicts
    .sort((a, b) => a.claim_index - b.claim_index)
    .forEach((v) => {
      const claim = currentClaims[v.claim_index];
      const card = document.createElement("div");
      card.className = `verdict-card verdict-${v.verdict}`;
      const techniqueBadge = v.misleading_technique
        ? `<span class="technique-badge">${v.misleading_technique}</span>`
        : "";
      const attributionBadge = v.attribution
        ? `<span class="attribution-badge attribution-${v.attribution}">attribution: ${v.attribution}</span>`
        : "";
      card.innerHTML = `
        <div class="verdict-card-header">
          <span class="claim-number">Case #${v.claim_index + 1}</span>
          <span class="confidence">${Math.round(v.confidence * 100)}% confidence</span>
          ${techniqueBadge}
          ${attributionBadge}
        </div>
        <p class="claim-text">"${claim ? claim.exact_wording : ""}"</p>
        <p class="explanation">${v.explanation}</p>
        <div class="sources"><span class="sources-label">Sources:</span>${sourcesHtml(v.sources, v.claim_index)}</div>
        <span class="verdict-stamp stamp-${v.verdict}" aria-label="Verdict: ${v.verdict}">${v.verdict}</span>
      `;
      verdictsContainer.appendChild(card);
      setStatusCell(v.claim_index, "judged", "status-done");
    });
  verdictsSection.hidden = verdicts.length === 0;
}

function startAgentTask(runId, filename) {
  agentSection.hidden = false;
  agentStatusEl.classList.remove("agent-error");
  agentStatusEl.innerHTML = '<span class="spinner-inline"></span> Managed Agent working in sandbox...';

  traceAgentStarted = true;
  const totalSources = currentVerdicts.reduce((sum, v) => sum + (v.sources ? v.sources.length : 0), 0);
  createTraceCard("agent", "Managed Agent", "Managed Agent", "model-agent", "agent");
  setTraceStatus("agent", "running", `Rendering MP4 and verifying ${totalSources} source(s) in sandbox...`);

  fetch("/api/agent-tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, filename, claims: currentClaims, verdicts: currentVerdicts }),
  })
    .then((res) => {
      if (!res.ok) throw new Error(`Failed to start agent task (${res.status})`);
      return res.json();
    })
    .then((data) => pollAgentTask(data.task_id))
    .catch((err) => {
      agentStatusEl.textContent = `Managed Agent could not start: ${err.message || err}`;
      agentStatusEl.classList.add("agent-error");
      setTraceStatus("agent", "failed", truncate(String(err.message || err), 60));
      traceAgentSettled = true;
      checkTraceSettled();
    });
}

function pollAgentTask(taskId) {
  fetch(`/api/agent-tasks/${taskId}`)
    .then((res) => {
      if (!res.ok) throw new Error(`Lost track of agent task (${res.status})`);
      return res.json();
    })
    .then((task) => {
      if (task.status === "working") {
        agentPollHandle = setTimeout(() => pollAgentTask(taskId), 8000);
      } else if (task.status === "done") {
        renderAgentResult(task.result);
        traceAgentSettled = true;
        checkTraceSettled();
      } else if (task.status === "failed") {
        agentStatusEl.textContent = `Managed Agent failed: ${task.error || "unknown error"}. Everything else above is unaffected.`;
        agentStatusEl.classList.add("agent-error");
        setTraceStatus("agent", "failed", truncate(task.error || "unknown error", 60));
        traceAgentSettled = true;
        checkTraceSettled();
      }
    })
    .catch((err) => {
      agentStatusEl.textContent = `Lost track of the Managed Agent: ${err.message || err}`;
      agentStatusEl.classList.add("agent-error");
      setTraceStatus("agent", "failed", "Lost track of agent task");
      traceAgentSettled = true;
      checkTraceSettled();
    });
}

function renderAgentResult(result) {
  agentStatusEl.classList.remove("agent-error");
  agentStatusEl.textContent = "Managed Agent finished.";

  if (result.video_url) {
    agentDownloadLink.href = result.video_url;
    agentDownloadLink.hidden = false;
  } else {
    agentDownloadLink.hidden = true;
  }

  const verifications = result.source_verifications || [];
  const counts = { verified: 0, broken: 0, blocked: 0, unsupported: 0, not_checked: 0 };
  verifications.forEach((v) => {
    counts[v.status] = (counts[v.status] || 0) + 1;
  });

  const countLabels = {
    verified: "verified",
    broken: "broken (404/not found)",
    blocked: "blocked (403/406/paywall)",
    unsupported: "don't support claim",
    not_checked: "not checked",
  };
  const countsHtml = `
    <div class="agent-summary-counts">
      ${Object.keys(countLabels)
        .filter((status) => counts[status] > 0)
        .map((status) => `<span class="agent-count-pill count-${status}">${counts[status]} ${countLabels[status]}</span>`)
        .join("")}
    </div>
  `;
  const rowsHtml = verifications
    .map(
      (v) => `
        <div class="agent-source-row status-${v.status}">
          <a href="${v.url}" target="_blank" rel="noopener noreferrer">${v.title || v.url}</a> — claim #${v.claim_index + 1}
          <div class="agent-source-notes">${v.notes}</div>
        </div>
      `
    )
    .join("");
  agentSourcesSummary.innerHTML = `${countsHtml}<div class="agent-sources-list">${rowsHtml}</div>`;

  applySourceFlags(verifications);

  const summaryParts = Object.keys(countLabels)
    .filter((status) => counts[status] > 0)
    .map((status) => `${counts[status]} ${status}`);
  const doneLog = `${result.video_url ? "Rendered MP4" : "No video"} · ${summaryParts.join(", ") || "no sources"}`;
  setTraceStatus("agent", "done", doneLog);
}

const SOURCE_FLAG_LABELS = {
  broken: "broken",
  blocked: "blocked",
  unsupported: "doesn't support",
  not_checked: "not checked",
};

function applySourceFlags(verifications) {
  verifications
    .filter((v) => v.status !== "verified")
    .forEach((v) => {
      const key = `${v.claim_index}|${v.url}`;
      document.querySelectorAll(".sources a").forEach((a) => {
        const alreadyFlagged = a.nextElementSibling && a.nextElementSibling.classList.contains("source-flag");
        if (a.dataset.sourceKey === key && !alreadyFlagged) {
          const flag = document.createElement("span");
          flag.className = `source-flag status-${v.status}`;
          flag.textContent = SOURCE_FLAG_LABELS[v.status] || v.status;
          a.after(flag);
        }
      });
    });
}

function handleEvent(evt) {
  switch (evt.stage) {
    case "extracting":
      setStatus("Gemini 4 Argon is watching the video and extracting claims. This can take a minute or two...");
      createTraceCard("extractor", "Claim Extractor", "gemini-4-argon", "model-argon", "extractor");
      setTraceStatus("extractor", "running", "Watching video and extracting claims...");
      break;

    case "claims_extracted":
      renderClaimsTable(evt.claims);
      setStatus(`Found ${evt.claims.length} claim(s). Starting investigation...`);
      setTraceStatus("extractor", "done", `Found ${evt.claims.length} claim(s)`);
      evt.claims.forEach((_, i) => {
        createTraceCard(`investigator-${i}`, `Investigator #${i + 1}`, "gemini-3.8-flash", "model-flash", "investigator");
      });
      break;

    case "investigating_start":
      totalToInvestigate = evt.total;
      investigatedCount = 0;
      setAllStatusCells("investigating...", "status-investigating");
      setStatus(`Investigating ${evt.total} claim(s) in parallel with Gemini 3.8 Flash + Google Search...`);
      for (let i = 0; i < evt.total; i++) {
        setTraceStatus(`investigator-${i}`, "running", "Researching via Google Search...");
      }
      break;

    case "investigated": {
      investigatedCount += 1;
      setStatusCell(evt.claim_index, "investigated", "status-done");
      setStatus(`Investigated ${investigatedCount}/${totalToInvestigate} claim(s)...`);
      const sources = (evt.finding && evt.finding.sources) || [];
      let log;
      if (sources.length === 0) {
        log = "No reliable sources found";
      } else {
        const titles = sources.slice(0, 2).map((s) => s.title || s.url);
        const more = sources.length > 2 ? ` +${sources.length - 2} more` : "";
        log = `Found: ${titles.join(", ")}${more}`;
      }
      setTraceStatus(`investigator-${evt.claim_index}`, "done", log);
      break;
    }

    case "judging":
      setStatus("Gemini 4 Argon is weighing the evidence and judging each claim...");
      createTraceCard("judge", "Judge", "gemini-4-argon", "model-argon", "judge");
      setTraceStatus("judge", "running", "Weighing evidence and judging each claim...");
      break;

    case "judged": {
      const verdictLabel = evt.result.video_verdict.verdict.toUpperCase();
      setTraceStatus("judge", "done", `Verdict: ${verdictLabel} · ${evt.result.verdicts.length} claim(s)`);
      // Show the verdict as soon as it's ready, without waiting for the explainer/critic loop.
      renderVideoVerdict(evt.result.video_verdict);
      summaryText.textContent = evt.result.what_actually_happened;
      summarySection.hidden = !evt.result.what_actually_happened;
      renderVerdicts(evt.result.verdicts || []);
      setStatus("Verdict ready. Writing the narration script...");
      break;
    }

    case "narrating":
      createTraceCard("narrator", "Narrator", "gemini-4-argon + tts", "model-argon", "narrator");
      setTraceStatus("narrator", "running", "Writing narration script and recording voiceover...");
      break;

    case "narrated":
      setTraceStatus("narrator", "done", `Recorded ${evt.segments.length} narration segment(s)`);
      setStatus("Narration ready. Generating a shareable explainer...");
      break;

    case "generating_explainer":
      setStatus("Gemini 4 Argon is generating an animated explainer of the results...");
      createTraceCard("explainer", "Explainer Generator", "gemini-4-argon", "model-argon", "explainer");
      setTraceStatus("explainer", "running", "Writing animated HTML explainer...");
      break;

    case "explainer_generated":
      setTraceStatus("explainer", "done", "Explainer HTML generated");
      break;

    case "rendering": {
      setStatus(`Rendering v${evt.version} in a headless browser...`);
      const fixerId = `fixer-v${evt.version - 1}`;
      if (traceCards.has(fixerId)) {
        setTraceStatus(fixerId, "done", "Regenerated explainer");
      }
      const criticId = `critic-v${evt.version}`;
      createTraceCard(criticId, `Critic · v${evt.version}`, "gemini-4-argon", "model-argon", "critic");
      setTraceStatus(criticId, "running", `Rendering v${evt.version} in headless browser...`);
      break;
    }

    case "critiquing":
      setStatus(`Critic is reviewing v${evt.version}...`);
      setTraceStatus(`critic-v${evt.version}`, "running", `Critic reviewing v${evt.version}...`);
      break;

    case "critique_result": {
      if (evt.approved) {
        setStatus(`v${evt.version} approved.`);
      } else {
        setStatus(`Found ${evt.issues.length} issue(s) in v${evt.version}.`);
      }
      const log = evt.approved
        ? "Approved"
        : `Found ${evt.issues.length} issue(s)${evt.issues[0] ? `: ${truncate(evt.issues[0].description, 50)}` : ""}`;
      setTraceStatus(`critic-v${evt.version}`, "done", log);
      break;
    }

    case "fixing": {
      setStatus(`Fixing v${evt.from_version} to produce v${evt.to_version}...`);
      const fixerId = `fixer-v${evt.from_version}`;
      createTraceCard(fixerId, `Fixer · v${evt.from_version}→v${evt.to_version}`, "gemini-4-argon", "model-argon", "fixer");
      setTraceStatus(fixerId, "running", `Fixing v${evt.from_version} → v${evt.to_version}...`);
      break;
    }

    case "done": {
      renderVideoVerdict(evt.result.video_verdict);
      summaryText.textContent = evt.result.what_actually_happened;
      summarySection.hidden = !evt.result.what_actually_happened;
      renderVerdicts(evt.result.verdicts || []);
      renderExplainerVersions(evt.result.versions);
      if (!isReplaying) setStatus("Analysis complete.");

      reportReady = true;
      showScreen("report");

      tracePipelineDone = true;
      if (!isReplaying) {
        const versions = evt.result.versions || [];
        const lastVersion = versions[versions.length - 1];
        if (lastVersion && lastVersion.approved && evt.result.run_id) {
          startAgentTask(evt.result.run_id, lastVersion.filename);
        } else {
          checkTraceSettled();
        }
      }
      break;
    }

    case "agent_started":
      agentSection.hidden = false;
      agentStatusEl.classList.remove("agent-error");
      agentStatusEl.innerHTML = '<span class="spinner-inline"></span> Managed Agent working in sandbox...';
      traceAgentStarted = true;
      createTraceCard("agent", "Managed Agent", "Managed Agent", "model-agent", "agent");
      setTraceStatus("agent", "running", `Rendering MP4 and verifying ${evt.total_sources} source(s) in sandbox...`);
      break;

    case "agent_done":
      renderAgentResult(evt.result);
      traceAgentSettled = true;
      if (!isReplaying) checkTraceSettled();
      break;

    case "agent_failed":
      agentStatusEl.textContent = `Managed Agent failed: ${evt.error || "unknown error"}. Everything else above is unaffected.`;
      agentStatusEl.classList.add("agent-error");
      setTraceStatus("agent", "failed", truncate(evt.error || "unknown error", 60));
      traceAgentSettled = true;
      if (!isReplaying) checkTraceSettled();
      break;

    case "error":
      setStatus(evt.message || "Something went wrong.", true);
      traceOrder.forEach((id) => {
        const card = traceCards.get(id);
        if (card && card.status === "running") {
          setTraceStatus(id, "failed", truncate(evt.message || "Pipeline error", 60));
        }
      });
      tracePipelineDone = true;
      if (!isReplaying) checkTraceSettled();
      break;

    default:
      break;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function showReplayBanner(createdAt) {
  replayBanner.hidden = false;
  replayBannerDate.textContent = createdAt ? new Date(createdAt).toLocaleString() : "an earlier run";
}

function hideReplayBanner() {
  replayBanner.hidden = true;
}

replayBannerClose.addEventListener("click", () => {
  hideReplayBanner();
  isReplaying = false;
  resetResults();
  resetTrace();
  setStatus("");
  investigationReady = false;
  reportReady = false;
  showScreen("start");
});

async function replayRun(runId, speed) {
  isReplaying = true;
  submitBtn.disabled = true;
  resetResults();
  resetTrace();
  setStatus(speed ? "Loading replay..." : "Loading saved run...");
  investigationReady = true;
  reportReady = false;
  showScreen("investigation");

  try {
    const [eventsRes, metaRes] = await Promise.all([
      fetch(`/explainers/${runId}/events.ndjson`),
      fetch(`/explainers/${runId}/meta.json`),
    ]);
    if (!eventsRes.ok) throw new Error(`Could not load run ${runId} (${eventsRes.status})`);
    const text = await eventsRes.text();
    const events = text
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => JSON.parse(l));
    const meta = metaRes.ok ? await metaRes.json() : null;
    showReplayBanner(meta ? meta.created_at : null);
    setStatus(speed ? `Replaying pipeline trace at ${speed}x...` : "Replaying pipeline trace...");

    let prevT = events.length && typeof events[0].t === "number" ? events[0].t : 0;
    for (const evt of events) {
      if (speed && typeof evt.t === "number") {
        const delayMs = Math.max(0, (evt.t - prevT) / speed) * 1000;
        if (delayMs > 20) await sleep(delayMs);
      }
      if (typeof evt.t === "number") prevT = evt.t;
      handleEvent(evt);
    }
    setStatus("Replay complete.");
  } catch (err) {
    setStatus(err.message || "Could not replay this run.", true);
  } finally {
    checkTraceSettled();
    submitBtn.disabled = false;
  }
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "";
  return formatElapsed(seconds * 1000);
}

function renderPastRunRow(meta) {
  const row = document.createElement("div");
  const verdictClass = meta.error ? "verdict-error" : meta.video_verdict ? `verdict-${meta.video_verdict}` : "";
  row.className = `past-run-row ${verdictClass}`;
  const dateStr = meta.created_at ? new Date(meta.created_at).toLocaleString() : "unknown time";
  const verdictLabel = meta.error ? "ERROR" : (meta.video_verdict || "n/a").toUpperCase();
  const agentNote = meta.agent
    ? meta.agent.status === "done"
      ? " · agent ✓"
      : meta.agent.status === "failed"
        ? " · agent ✗"
        : ""
    : "";
  row.innerHTML = `
    <span class="past-run-date">${dateStr}</span>
    <span class="past-run-source" title="${meta.source || ""}">${meta.source || "unknown source"}</span>
    <span class="past-run-meta">${verdictLabel} · ${meta.claim_count || 0} claim(s) · ${formatDuration(meta.duration_seconds)}${agentNote}</span>
    <div class="past-run-actions">
      <button type="button" data-action="load">View final result</button>
      <button type="button" data-action="replay1">▶ Replay (real pace)</button>
      <button type="button" data-action="replay4">▶▶ Replay (4x)</button>
    </div>
  `;
  row.querySelector('[data-action="load"]').addEventListener("click", () => replayRun(meta.run_id, null));
  row.querySelector('[data-action="replay1"]').addEventListener("click", () => replayRun(meta.run_id, 1));
  row.querySelector('[data-action="replay4"]').addEventListener("click", () => replayRun(meta.run_id, 4));
  return row;
}

function loadPastRuns() {
  fetch("/api/runs")
    .then((res) => res.json())
    .then((data) => {
      const runs = data.runs || [];
      pastRunsList.innerHTML = "";
      pastRunsEmpty.hidden = runs.length > 0;
      runs.forEach((meta) => pastRunsList.appendChild(renderPastRunRow(meta)));
    })
    .catch(() => {
      /* Past runs are a convenience; ignore failures to load the list. */
    });
}

pastRunsRefreshBtn.addEventListener("click", loadPastRuns);
loadPastRuns();
showScreen("start");

async function streamAnalysis(formData) {
  const response = await fetch("/api/analyze", { method: "POST", body: formData });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex;
    while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (!line) continue;
      handleEvent(JSON.parse(line));
    }
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const formData = new FormData();
  if (activeTab === "youtube") {
    const url = document.getElementById("youtube-url").value.trim();
    if (!url) {
      setStatus("Paste a YouTube link first.", true);
      return;
    }
    formData.append("youtube_url", url);
  } else {
    const file = document.getElementById("video-file").files[0];
    if (!file) {
      setStatus("Choose a video file first.", true);
      return;
    }
    formData.append("video", file);
  }

  submitBtn.disabled = true;
  isReplaying = false;
  hideReplayBanner();
  resetResults();
  resetTrace();
  setStatus("Starting...");
  investigationReady = true;
  reportReady = false;
  showScreen("investigation");

  try {
    await streamAnalysis(formData);
    loadPastRuns();
  } catch (err) {
    setStatus(err.message || "Something went wrong.", true);
    traceOrder.forEach((id) => {
      const card = traceCards.get(id);
      if (card && card.status === "running") {
        setTraceStatus(id, "failed", truncate(err.message || "Connection error", 60));
      }
    });
    tracePipelineDone = true;
    checkTraceSettled();
    loadPastRuns();
  } finally {
    submitBtn.disabled = false;
  }
});
