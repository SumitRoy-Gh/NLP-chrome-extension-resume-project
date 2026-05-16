// sidebar.js
// ----------
// Runs inside the sidebar iframe (sidebar.html).
// Responsible for:
//   1. Reading the video ID from the iframe URL
//   2. Checking with Flask whether the video is already ingested
//   3. Triggering ingestion when user clicks "Process this video"
//   4. Sending search queries to Flask and rendering results
//   5. Seeking the YouTube video when user clicks a result timestamp

// ── Configuration ────────────────────────────────────────────────────────────
// This is the address of your Docker Flask server.
// If you ever deploy the backend to a cloud server, change this URL.
const FLASK_URL = "http://localhost:5000";

// ── Read video ID from iframe URL ─────────────────────────────────────────────
// content.js loaded this iframe with: sidebar.html?videoId=dQw4w9WgXcQ
// We read that parameter here.
const urlParams = new URLSearchParams(window.location.search);
const videoId   = urlParams.get("videoId");

// ── DOM references ────────────────────────────────────────────────────────────
// We grab all the elements we need to update once here,
// rather than calling document.getElementById() repeatedly.
const videoIdDisplay = document.getElementById("video-id-display");
const statusText     = document.getElementById("status-text");
const btnIngest      = document.getElementById("btn-ingest");
const progressWrap   = document.getElementById("progress-wrap");
const progressLabel  = document.getElementById("progress-label");
const searchInput    = document.getElementById("search-input");
const btnSearch      = document.getElementById("btn-search");
const resultsArea    = document.getElementById("results-area");

// ── Initialise on load ────────────────────────────────────────────────────────
// As soon as the sidebar loads, check if the video is already ingested.
if (videoId) {
  videoIdDisplay.textContent = videoId;
  checkStatus();
} else {
  setStatus("No video detected.", "error");
}

// ── Check ingestion status ────────────────────────────────────────────────────
// Calls GET /status/<video_id> on Flask to see if this video's chunks
// are already stored in ChromaDB. If yes, enable search immediately.
// If no, show the "Process this video" button.
async function checkStatus() {
  setStatus("Checking...", "loading");

  try {
    const res  = await fetch(`${FLASK_URL}/status/${videoId}`);
    const data = await res.json();

    if (data.ingested) {
      // Already processed — enable search right away
      setStatus(`✓ Ready — ${data.chunks} chunks indexed`, "ready");
      enableSearch();
    } else {
      // Not processed yet — show the ingest button
      setStatus("This video hasn't been processed yet.", "");
      btnIngest.style.display = "block";
    }
  } catch (err) {
    // Flask isn't reachable — Docker might not be running
    setStatus("⚠ Cannot reach backend. Is Docker running?", "error");
  }
}

// ── Ingest button click ───────────────────────────────────────────────────────
// When user clicks "Process this video", we POST the YouTube URL to /ingest.
// This will take several minutes — we show the animated progress bar meanwhile.
btnIngest.addEventListener("click", async () => {
  // Disable button so user can't click twice
  btnIngest.disabled    = true;
  btnIngest.textContent = "Processing...";

  // Show animated progress bar
  progressWrap.classList.add("visible");
  setStatus("Downloading audio and transcribing...", "loading");

  const youtubeUrl = `https://www.youtube.com/watch?v=${videoId}`;

  try {
    // This fetch will block for several minutes — that's expected
    // Ingestion is a long-running task (Whisper is slow on CPU)
    const res  = await fetch(`${FLASK_URL}/ingest`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ url: youtubeUrl }),
    });

    const data = await res.json();

    // Hide progress bar
    progressWrap.classList.remove("visible");

    if (res.ok) {
      // Success!
      btnIngest.style.display = "none";
      setStatus(`✓ Done — ${data.chunks} chunks indexed`, "ready");
      enableSearch();

      // Save to chrome.storage.local so next time we don't need to re-check
      // chrome.storage persists across browser sessions
      chrome.storage.local.set({ [`ingested_${videoId}`]: true });
    } else {
      // Flask returned an error
      setStatus(`Error: ${data.error}`, "error");
      btnIngest.disabled    = false;
      btnIngest.textContent = "⚙ Retry processing";
    }
  } catch (err) {
    progressWrap.classList.remove("visible");
    setStatus("Request failed. Is Docker running?", "error");
    btnIngest.disabled    = false;
    btnIngest.textContent = "⚙ Retry processing";
  }
});

// ── Enable search ─────────────────────────────────────────────────────────────
// Called once we confirm the video is ingested.
// Unlocks the search input and button.
function enableSearch() {
  searchInput.disabled = false;
  btnSearch.disabled   = false;
  searchInput.focus();
  showStateMsg("🔍", "Type a concept above and press Search.");
}

// ── Search flow ───────────────────────────────────────────────────────────────
// Triggered by clicking Search or pressing Enter in the input.

async function doSearch() {
  const query = searchInput.value.trim();
  if (!query) return; // ignore empty queries

  // Show spinner while waiting for Flask
  resultsArea.innerHTML = `
    <div class="spinner-wrap">
      <div class="spinner"></div>
      <div>Searching...</div>
    </div>
  `;

  btnSearch.disabled = true;

  try {
    const res  = await fetch(`${FLASK_URL}/search`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ query, video_id: videoId }),
    });

    const data = await res.json();

    if (!res.ok) {
      showError(data.error || "Search failed.");
      return;
    }

    renderResults(data.results, data.message);

  } catch (err) {
    showError("Cannot reach backend. Is Docker running?");
  } finally {
    // Re-enable search button regardless of success or failure
    btnSearch.disabled = false;
  }
}

// Click handler
btnSearch.addEventListener("click", doSearch);

// Enter key handler — pressing Enter in the input triggers search
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSearch();
});

// ── Render results ────────────────────────────────────────────────────────────
// Takes the array of result objects from Flask and builds the result cards.
function renderResults(results, message) {
  // No results case
  if (!results || results.length === 0) {
    showStateMsg("🔍", message || "No results found. Try a different search term.");
    return;
  }

  // Build HTML string for all result cards
  // We use a template literal to create the HTML structure for each result
  const cardsHtml = results.map((r, index) => {
    // Escape HTML to prevent XSS attacks
    // Never inject raw API text into innerHTML without escaping
    const safeText = escapeHtml(r.text);
    
    // Format score to 2 decimal places for display
    const score = typeof r.rerank_score === "number"
      ? r.rerank_score.toFixed(2)
      : "";

    return `
      <div class="result-card" data-seconds="${r.start_seconds}">
        <div class="timestamp">${r.timestamp_display}</div>
        <div class="snippet">${safeText}</div>
        ${score ? `<div class="score">score: ${score}</div>` : ""}
      </div>
    `;
  }).join("");

  // Render everything into the results area
  resultsArea.innerHTML = `
    <div class="result-count">
      ${results.length} result${results.length !== 1 ? "s" : ""} · click to jump
    </div>
    ${cardsHtml}
  `;

  // Attach click handlers AFTER inserting into DOM
  // We can't attach handlers before the elements exist
  resultsArea.querySelectorAll(".result-card").forEach(card => {
    card.addEventListener("click", () => {
      const seconds = parseFloat(card.dataset.seconds);
      seekVideo(seconds);

      // Visual feedback — briefly highlight the clicked card
      card.style.background = "#fff0f0";
      setTimeout(() => { card.style.background = ""; }, 600);
    });
  });
}

// ── Seek the YouTube video ────────────────────────────────────────────────────
// The sidebar is inside an iframe. The video player is in the parent page.
// We use postMessage to communicate across the iframe boundary.
// content.js (in the parent page) listens for this message and seeks the video.
function seekVideo(seconds) {
  window.parent.postMessage(
    { type: "YT_SEMANTIC_SEEK", seconds: seconds },
    "*"  // send to any origin (safe here because we control both sides)
  );
}

// ── UI helper functions ───────────────────────────────────────────────────────

// Update the status text below the video ID
function setStatus(text, type) {
  statusText.textContent = text;
  statusText.className   = "status-text" + (type ? ` ${type}` : "");
}

// Show a centered state message with an icon in the results area
function showStateMsg(icon, text) {
  resultsArea.innerHTML = `
    <div class="state-msg">
      <div class="icon">${icon}</div>
      ${escapeHtml(text)}
    </div>
  `;
}

// Show an error box in the results area
function showError(message) {
  resultsArea.innerHTML = `<div class="error-box">⚠ ${escapeHtml(message)}</div>`;
}

// Escape HTML special characters to prevent XSS
// This converts < > & " ' into safe HTML entities
// NEVER inject untrusted text into innerHTML without running it through this first
function escapeHtml(text) {
  const div       = document.createElement("div");
  div.textContent = text;  // textContent handles escaping automatically
  return div.innerHTML;    // returns the escaped HTML string
}