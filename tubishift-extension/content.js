/**
 * content.js — TubiShift content script
 * - Advances to next queue episode with 5 seconds remaining (beats Tubi autoplay)
 * - Suppresses Tubi's "Up Next" autoplay overlay so it can't race us
 */

const ADVANCE_AT_REMAINING_SECS = 8;

let advanceScheduled = false;
let advanceTimer = null;
let videoWatcherInterval = null;
let advanceTimeout = null;
let autoPlayAt = null;

// ─── HELPERS ──────────────────────────────────────────────────────────────────

function getVideoId() {
  const m = location.pathname.match(/^\/tv-shows\/(\d+)/);
  return m ? m[1] : null;
}

// ─── TUBI AUTOPLAY SUPPRESSION ────────────────────────────────────────────────
// Tubi's "Up Next" overlay has a countdown that auto-navigates. We hide it
// and also intercept the history/pushState navigation it uses.

function suppressTubiAutoplay() {
  // Inject a style to hide Tubi's autoplay overlay
  if (!document.getElementById("tubishift-suppress")) {
    const style = document.createElement("style");
    style.id = "tubishift-suppress";
    // Target Tubi's autoplay next-episode card by common class patterns
    style.textContent = `
      [class*="KiBYW"],
      [class*="AutoPlay"],
      [class*="autoplay"],
      [class*="auto-play"],
      [class*="NextEpisode"],
      [class*="next-episode"],
      [class*="UpNext"],
      [class*="up-next"],
      [class*="CountdownOverlay"],
      [class*="countdown-overlay"],
      [data-testid*="autoplay"],
      [data-testid*="up-next"],
      [data-testid*="next-episode"] {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
      }
    `;
    document.head.appendChild(style);
  }
}

// ─── VIDEO TIME WATCHER ───────────────────────────────────────────────────────

function startWatching() {
  if (videoWatcherInterval) clearInterval(videoWatcherInterval);
  advanceScheduled = false;

  document.addEventListener("pause", e => {
    if (e.target.tagName === "VIDEO" && e.target.dataset.id === "videoPlayerComponent") {
      if (videoWatcherInterval) clearInterval(videoWatcherInterval);
    }
  }, true);

  document.addEventListener("playing", e => {
    if (e.target.tagName === "VIDEO" && e.target.dataset.id === "videoPlayerComponent") {
      const video = e.target;

      if (!autoPlayAt) {
        const videoId = getVideoId();
        chrome.runtime.sendMessage(
          { type: "GET_CREDITS_SECS", current_video_id: videoId },
          (response) => {
            if (chrome.runtime.lastError) {
              console.log("[TubiShift] Extension error:", chrome.runtime.lastError.message);
              return;
            }
            if (response.credits_secs) {
              autoPlayAt = response.credits_secs - 1;
            }
          }
        );
      }

      videoWatcherInterval = setInterval(() => {
        if (!video || video.paused || video.ended) return;
        if (video.duration <= 0) return;

        if (!advanceScheduled && video.currentTime >= autoPlayAt) {
          advanceScheduled = true;
          doAdvance();
        }
      }, 500);
    }
  }, true);
}

function doAdvance() {
  const videoId = getVideoId();
  console.log("[TubiShift] Requesting advance for video id:", videoId);

  chrome.runtime.sendMessage(
    { type: "ADVANCE", current_video_id: videoId },
    (response) => {
      if (chrome.runtime.lastError) {
        console.log("[TubiShift] Extension error:", chrome.runtime.lastError.message);
        return;
      }
      console.log("[TubiShift] Advance response:", response);
      if (response?.status === "ok" && response.next_url) {
        showAdvanceBanner(response);
        // Navigate after a short delay so the banner is visible
        advanceTimeout = setTimeout(() => { location.href = response.next_url; }, 3000);
      } else if (response?.status === "inactive") {
        console.log("[TubiShift] Auto-advance is off");
      } else if (response?.status === "queue_ended") {
        showEndBanner();
      } else {
        console.log("[TubiShift] No next episode:", response?.status);
      }
    }
  );
}

// ─── VIDEO ATTACHMENT ─────────────────────────────────────────────────────────

function attachToVideo(video) {
  if (video._tubiShiftAttached) return;
  video._tubiShiftAttached = true;
  console.log("[TubiShift] Attached to <video>");
  suppressTubiAutoplay();
  startWatching(video);
}

function findAndAttach() {
  const video = document.querySelector("video[data-id='videoPlayerComponent']");
  if (video) { attachToVideo(video); return true; }
  return false;
}

if (!findAndAttach()) {
  const vidObserver = new MutationObserver(() => {
    if (findAndAttach()) vidObserver.disconnect();
  });
  vidObserver.observe(document.body, { childList: true, subtree: true });
}

// ─── BANNER ───────────────────────────────────────────────────────────────────

function showAdvanceBanner({ next_title, next_show }) {
  removeBanner();
  const el = document.createElement("div");
  el.id = "tubishift-banner";
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="font-size:20px;">📺</div>
      <div style="flex:1;">
        <div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;opacity:.7;margin-bottom:2px;">Up Next — TubiShift</div>
        <div style="font-weight:600;font-size:14px;">${next_show || ""}</div>
        <div style="font-size:12px;opacity:.8;">${next_title || ""}</div>
      </div>
      <button id="tubishift-cancel"
        style="background:rgba(255,255,255,.15);border:none;color:white;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;">
        Cancel
      </button>
    </div>`;
  applyBannerStyles(el);
  document.body.appendChild(el);
  document.getElementById("tubishift-cancel").onclick = () => {
    clearInterval(videoWatcherInterval);
    clearTimeout(advanceTimeout);
    advanceScheduled = true; // prevent re-trigger
    removeBanner();
  };
}

function showEndBanner() {
  removeBanner();
  const el = document.createElement("div");
  el.id = "tubishift-banner";
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="font-size:20px;">✅</div>
      <div>
        <div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;opacity:.7;margin-bottom:2px;">TubiShift</div>
        <div style="font-weight:600;font-size:14px;">Channel complete!</div>
      </div>
    </div>`;
  applyBannerStyles(el);
  document.body.appendChild(el);
  setTimeout(removeBanner, 5000);
}

function applyBannerStyles(el) {
  Object.assign(el.style, {
    position: "fixed", bottom: "80px", right: "24px",
    background: "linear-gradient(135deg, #ff5a1f, #ff9a3c)",
    color: "white", padding: "14px 18px", borderRadius: "12px",
    zIndex: "99999", boxShadow: "0 8px 32px rgba(0,0,0,.5)",
    fontFamily: "system-ui, sans-serif",
    minWidth: "260px", maxWidth: "340px",
    animation: "tubishift-slidein .3s ease",
  });
  if (!document.getElementById("tubishift-styles")) {
    const s = document.createElement("style");
    s.id = "tubishift-styles";
    s.textContent = `@keyframes tubishift-slidein {
      from { transform:translateY(20px); opacity:0 }
      to   { transform:translateY(0);   opacity:1 }
    }`;
    document.head.appendChild(s);
  }
}

function removeBanner() {
  document.getElementById("tubishift-banner")?.remove();
}