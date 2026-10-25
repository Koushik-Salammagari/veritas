const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");
const form = document.getElementById("claim-form");
const statusEl = document.getElementById("status");
const submitBtn = document.getElementById("submit-btn");
const resultsSection = document.getElementById("results");
const claimsBody = document.querySelector("#claims-table tbody");

let activeTab = "youtube";

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

function renderClaims(claims) {
  claimsBody.innerHTML = "";
  claims.forEach((claim, i) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${i + 1}</td>
      <td>${claim.timestamp}</td>
      <td>${claim.speaker}</td>
      <td>${claim.exact_wording}</td>
      <td><span class="badge badge-${claim.claim_type}">${claim.claim_type}</span></td>
    `;
    claimsBody.appendChild(row);
  });
  resultsSection.hidden = claims.length === 0;
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
  resultsSection.hidden = true;
  setStatus("Gemini 4 Argon is watching the video and extracting claims. This can take a minute or two...");

  try {
    const response = await fetch("/api/extract-claims", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }

    const data = await response.json();
    setStatus(`Found ${data.claims.length} claim(s).`);
    renderClaims(data.claims);
  } catch (err) {
    setStatus(err.message || "Something went wrong.", true);
  } finally {
    submitBtn.disabled = false;
  }
});
