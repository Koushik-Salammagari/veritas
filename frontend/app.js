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

let activeTab = "youtube";
let currentClaims = [];
let currentVerdicts = [];
let investigatedCount = 0;
let totalToInvestigate = 0;
let agentPollHandle = null;

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    activeTab = btn.dataset.tab;
    tabButtons.forEach((b) => b.classList.toggle("active", b === btn));
    tabPanels.forEach((p) => (p.hidden = p.dataset.panel !== activeTab));
  });
});

function setStatus(message, isError = false) {
  statusEl.hidden = !message;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
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
          <span class="claim-number">#${v.claim_index + 1}</span>
          <span class="verdict-badge verdict-badge-${v.verdict}">${v.verdict}</span>
          <span class="confidence">${Math.round(v.confidence * 100)}% confidence</span>
          ${techniqueBadge}
          ${attributionBadge}
        </div>
        <p class="claim-text">"${claim ? claim.exact_wording : ""}"</p>
        <p class="explanation">${v.explanation}</p>
        <div class="sources"><span class="sources-label">Sources:</span>${sourcesHtml(v.sources, v.claim_index)}</div>
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
      } else if (task.status === "failed") {
        agentStatusEl.textContent = `Managed Agent failed: ${task.error || "unknown error"}. Everything else above is unaffected.`;
        agentStatusEl.classList.add("agent-error");
      }
    })
    .catch((err) => {
      agentStatusEl.textContent = `Lost track of the Managed Agent: ${err.message || err}`;
      agentStatusEl.classList.add("agent-error");
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
  const counts = { verified: 0, broken: 0, unsupported: 0 };
  verifications.forEach((v) => {
    counts[v.status] = (counts[v.status] || 0) + 1;
  });

  const countsHtml = `
    <div class="agent-summary-counts">
      <span class="agent-count-pill count-verified">${counts.verified} verified</span>
      <span class="agent-count-pill count-broken">${counts.broken} broken</span>
      <span class="agent-count-pill count-unsupported">${counts.unsupported} don't support claim</span>
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
}

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
          flag.textContent = v.status === "broken" ? "broken" : "doesn't support";
          a.after(flag);
        }
      });
    });
}

function handleEvent(evt) {
  switch (evt.stage) {
    case "extracting":
      setStatus("Gemini 4 Argon is watching the video and extracting claims. This can take a minute or two...");
      break;

    case "claims_extracted":
      renderClaimsTable(evt.claims);
      setStatus(`Found ${evt.claims.length} claim(s). Starting investigation...`);
      break;

    case "investigating_start":
      totalToInvestigate = evt.total;
      investigatedCount = 0;
      setAllStatusCells("investigating...", "status-investigating");
      setStatus(`Investigating ${evt.total} claim(s) in parallel with Gemini 3.8 Flash + Google Search...`);
      break;

    case "investigated":
      investigatedCount += 1;
      setStatusCell(evt.claim_index, "investigated", "status-done");
      setStatus(`Investigated ${investigatedCount}/${totalToInvestigate} claim(s)...`);
      break;

    case "judging":
      setStatus("Gemini 4 Argon is weighing the evidence and judging each claim...");
      break;

    case "generating_explainer":
      setStatus("Gemini 4 Argon is generating an animated explainer of the results...");
      break;

    case "rendering":
      setStatus(`Rendering v${evt.version} in a headless browser...`);
      break;

    case "critiquing":
      setStatus(`Critic is reviewing v${evt.version}...`);
      break;

    case "critique_result":
      if (evt.approved) {
        setStatus(`v${evt.version} approved.`);
      } else {
        setStatus(`Found ${evt.issues.length} issue(s) in v${evt.version}.`);
      }
      break;

    case "fixing":
      setStatus(`Fixing v${evt.from_version} to produce v${evt.to_version}...`);
      break;

    case "done": {
      renderVideoVerdict(evt.result.video_verdict);
      summaryText.textContent = evt.result.what_actually_happened;
      summarySection.hidden = !evt.result.what_actually_happened;
      renderVerdicts(evt.result.verdicts || []);
      renderExplainerVersions(evt.result.versions);
      setStatus("Analysis complete.");

      const versions = evt.result.versions || [];
      const lastVersion = versions[versions.length - 1];
      if (lastVersion && lastVersion.approved && evt.result.run_id) {
        startAgentTask(evt.result.run_id, lastVersion.filename);
      }
      break;
    }

    case "error":
      setStatus(evt.message || "Something went wrong.", true);
      break;

    default:
      break;
  }
}

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
  resetResults();
  setStatus("Starting...");

  try {
    await streamAnalysis(formData);
  } catch (err) {
    setStatus(err.message || "Something went wrong.", true);
  } finally {
    submitBtn.disabled = false;
  }
});
