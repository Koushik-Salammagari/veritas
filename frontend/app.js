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
const explainerFrame = document.getElementById("explainer-frame");
const explainerFullscreenLink = document.getElementById("explainer-fullscreen-link");

let activeTab = "youtube";
let currentClaims = [];
let investigatedCount = 0;
let totalToInvestigate = 0;

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
  explainerFrame.src = "about:blank";
}

function renderExplainer(explainerUrl) {
  if (!explainerUrl) {
    explainerSection.hidden = true;
    return;
  }
  explainerFrame.src = explainerUrl;
  explainerFullscreenLink.href = explainerUrl;
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

function sourcesHtml(sources) {
  if (!sources || sources.length === 0) {
    return '<span class="no-sources">No sources</span>';
  }
  return sources
    .map((s) => `<a href="${s.url}" target="_blank" rel="noopener noreferrer">${s.title || s.url}</a>`)
    .join("");
}

function renderVerdicts(verdicts) {
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
      card.innerHTML = `
        <div class="verdict-card-header">
          <span class="claim-number">#${v.claim_index + 1}</span>
          <span class="verdict-badge verdict-badge-${v.verdict}">${v.verdict}</span>
          <span class="confidence">${Math.round(v.confidence * 100)}% confidence</span>
          ${techniqueBadge}
        </div>
        <p class="claim-text">"${claim ? claim.exact_wording : ""}"</p>
        <p class="explanation">${v.explanation}</p>
        <div class="sources"><span class="sources-label">Sources:</span>${sourcesHtml(v.sources)}</div>
      `;
      verdictsContainer.appendChild(card);
      setStatusCell(v.claim_index, "judged", "status-done");
    });
  verdictsSection.hidden = verdicts.length === 0;
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

    case "done":
      renderVideoVerdict(evt.result.video_verdict);
      summaryText.textContent = evt.result.what_actually_happened;
      summarySection.hidden = !evt.result.what_actually_happened;
      renderVerdicts(evt.result.verdicts || []);
      renderExplainer(evt.result.explainer_url);
      setStatus("Analysis complete.");
      break;

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
