// content.js
// ----------
// Chrome automatically injects this script into every YouTube watch page.
// It runs in the context of the YouTube page — it can access the DOM,
// the video element, and the URL. But it cannot directly access Chrome
// extension APIs except chrome.runtime.
//
// This script:
//   1. Reads the video ID from the URL
//   2. Creates a sidebar iframe panel on the right side of the page
//   3. Creates a toggle button to show/hide the sidebar
//   4. Listens for messages from the sidebar to seek the video
//   5. Watches for YouTube navigation (SPA) and updates the sidebar when
//      the user clicks a different video

// ── Prevent double injection ──────────────────────────────────────────────────
// YouTube sometimes triggers the content script multiple times.
// This guard ensures we only inject the sidebar once.
if (document.getElementById("yt-sem-search-container")) {
  // Already injected — do nothing
} else {
  initExtension();
}

function initExtension() {

  // ── Helper: extract video ID from current URL ───────────────────────────────
  // YouTube URLs look like: https://www.youtube.com/watch?v=dQw4w9WgXcQ
  // URLSearchParams parses the query string (?v=...) for us
  function getVideoId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("v"); // returns "dQw4w9WgXcQ" or null if not a video page
  }

  const videoId = getVideoId();
  
  // If we can't find a video ID, this isn't a video page — stop here
  if (!videoId) return;

  // ── Create the sidebar container div ───────────────────────────────────────
  // We use a div that holds an iframe. The iframe loads our sidebar.html.
  // Using an iframe is best practice because:
  // - It has its own HTML/CSS scope, so our styles don't clash with YouTube's
  // - It's isolated — YouTube's JavaScript can't accidentally break our UI
  const container = document.createElement("div");
  container.id = "yt-sem-search-container";

  // Position it as a fixed panel on the right side of the screen
  // position: fixed means it stays in place even when the user scrolls
  Object.assign(container.style, {
    position:   "fixed",
    top:        "56px",              // YouTube's top nav is 56px tall
    right:      "0",
    width:      "380px",
    height:     "calc(100vh - 56px)", // full height minus nav bar
    zIndex:     "9999",              // on top of everything on the page
    border:     "none",
    boxShadow:  "-4px 0 24px rgba(0,0,0,0.18)",
    transition: "transform 0.3s cubic-bezier(0.4,0,0.2,1)", // smooth animation
    background: "#fff",
  });

  // ── Create the iframe ───────────────────────────────────────────────────────
  // chrome.runtime.getURL() converts a relative path like "sidebar.html"
  // into the full extension URL: chrome-extension://[id]/sidebar.html
  // We also pass the videoId as a URL parameter so sidebar.js can read it
  const iframe = document.createElement("iframe");
  iframe.src = chrome.runtime.getURL("sidebar.html") + "?videoId=" + videoId;
  
  Object.assign(iframe.style, {
    width:  "100%",
    height: "100%",
    border: "none",
  });

  container.appendChild(iframe);
  document.body.appendChild(container);

  // ── Create the toggle button ────────────────────────────────────────────────
  // A small tab button that sticks out from the left edge of the sidebar.
  // Clicking it slides the sidebar in/out.
  const toggleBtn = document.createElement("button");
  toggleBtn.id = "yt-sem-search-toggle";
  toggleBtn.innerHTML = `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="8"/>
      <line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  `;
  toggleBtn.title = "Toggle Semantic Search";

  Object.assign(toggleBtn.style, {
    position:     "fixed",
    top:          "80px",
    right:        "380px",          // sits just to the left of the sidebar
    zIndex:       "10000",
    background:   "#ff0000",        // YouTube red
    border:       "none",
    borderRadius: "8px 0 0 8px",    // rounded on left, flush on right
    padding:      "10px 8px",
    cursor:       "pointer",
    boxShadow:    "-3px 0 12px rgba(0,0,0,0.2)",
    transition:   "right 0.3s cubic-bezier(0.4,0,0.2,1)",
    display:      "flex",
    alignItems:   "center",
    justifyContent: "center",
  });

  document.body.appendChild(toggleBtn);

  // ── Toggle sidebar visibility ───────────────────────────────────────────────
  let sidebarVisible = true;

  toggleBtn.addEventListener("click", () => {
    sidebarVisible = !sidebarVisible;

    if (sidebarVisible) {
      // Slide sidebar back into view
      container.style.transform = "translateX(0)";
      toggleBtn.style.right     = "380px";
    } else {
      // Slide sidebar off the right edge of the screen
      container.style.transform = "translateX(380px)";
      toggleBtn.style.right     = "0px";
    }
  });

  // ── Listen for seek messages from the sidebar ───────────────────────────────
  // When the user clicks a result in the sidebar, sidebar.js sends:
  //   window.parent.postMessage({ type: "YT_SEMANTIC_SEEK", seconds: 5025 }, "*")
  //
  // This listener receives that message and seeks the YouTube video.
  // postMessage is the standard way for an iframe to communicate with its parent.
  window.addEventListener("message", (event) => {
    // Safety check: only handle our own messages
    if (!event.data || event.data.type !== "YT_SEMANTIC_SEEK") return;

    const seconds = parseFloat(event.data.seconds);
    if (isNaN(seconds)) return;

    // Find the YouTube video element
    // YouTube uses a standard HTML5 <video> element
    const video = document.querySelector("video");
    if (!video) return;

    video.currentTime = seconds; // seek to the timestamp
    video.play();                // resume playback

    // Smoothly scroll the video into view if the user has scrolled down
    video.closest(".html5-video-container")?.scrollIntoView({
      behavior: "smooth",
      block:    "start"
    });
  });

  // ── Handle YouTube SPA navigation ──────────────────────────────────────────
  // YouTube is a Single Page Application — when you click on a different video,
  // the URL changes but the PAGE DOES NOT RELOAD. So our content.js doesn't
  // re-run. We need to watch for URL changes ourselves.
  //
  // MutationObserver watches for DOM changes and fires a callback.
  // We use it to detect when YouTube updates the URL (which also updates
  // the document title and some DOM elements).
  let lastUrl = location.href;

  new MutationObserver(() => {
    const currentUrl = location.href;
    if (currentUrl === lastUrl) return; // URL hasn't changed, ignore
    
    lastUrl = currentUrl;
    const newVideoId = getVideoId();

    if (newVideoId && newVideoId !== videoId) {
      // User navigated to a different video — update the iframe's URL
      // so the sidebar shows the correct video's search state
      iframe.src = chrome.runtime.getURL("sidebar.html") + "?videoId=" + newVideoId;
    }
  }).observe(document.body, {
    subtree:   true,   // watch all descendant elements, not just direct children
    childList: true    // watch for elements being added/removed
  });

} // end initExtension()