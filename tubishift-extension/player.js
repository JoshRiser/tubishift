/**
 * player.js — TubiShift player controller
 * Runs only on tubitv.com/tv-shows/* pages.
 *
 * Responsibilities:
 *   - Watch video currentTime and advance at the credits timestamp
 *   - Suppress Tubi's autoplay overlay via CSS
 *   - Show advance/end/re-enable banners
 *   - Respond to navigation events from navigate.js
 */

const ADVANCE_AT_REMAINING_SECS = 8;

let advanceScheduled = false;
let advanceTimeout = null;
let videoWatcherInterval = null;
let autoPlayAt = null;

// ─── HELPERS ──────────────────────────────────────────────────────────────────

function getVideoId() {
  const m = location.pathname.match(/^\/tv-shows\/(\d+)/);
  return m ? m[1] : null;
}

function sendMsg(type, payload = {}) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type, ...payload }, (response) => {
      if (chrome.runtime.lastError) resolve(null);
      else resolve(response);
    });
  });
}

// ─── CSS SUPPRESSION ──────────────────────────────────────────────────────────

function suppressTubiAutoplay() {
  if (document.getElementById("tubishift-suppress")) return;
  const style = document.createElement("style");
  style.id = "tubishift-suppress";
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
      opacity: 0 !important;
    }
  `;
  document.head.appendChild(style);
}

// ─── VIDEO WATCHER ────────────────────────────────────────────────────────────

function startWatching() {
  if (videoWatcherInterval) clearInterval(videoWatcherInterval);
  advanceScheduled = false;
  autoPlayAt = null;

  document.addEventListener("playing", e => {
    if (e.target.tagName !== "VIDEO" || e.target.dataset.id !== "videoPlayerComponent") return;
    const video = e.target;

    if (autoPlayAt === null) {
      sendMsg("GET_CREDITS_SECS", { current_video_id: getVideoId() }).then((response) => {
        if (response?.credits_secs) {
          autoPlayAt = response.credits_secs - 1;
          console.log(`[TubiShift/player] Will advance at ${autoPlayAt}s`);
        } else {
          autoPlayAt = -ADVANCE_AT_REMAINING_SECS;
          console.log(`[TubiShift/player] No credits_secs, using ${ADVANCE_AT_REMAINING_SECS}s-remaining fallback`);
        }
      });
    }

    if (videoWatcherInterval) clearInterval(videoWatcherInterval);
    videoWatcherInterval = setInterval(() => {
      if (!video || video.paused || video.ended) return;
      if (video.duration <= 0 || autoPlayAt === null) return;

      const threshold = autoPlayAt < 0
        ? video.duration + autoPlayAt
        : autoPlayAt;

      if (!advanceScheduled && video.currentTime >= threshold) {
        advanceScheduled = true;
        doAdvance();
      }
    }, 500);
  }, true);
}

function stopWatching() {
  clearInterval(videoWatcherInterval);
  clearTimeout(advanceTimeout);
  videoWatcherInterval = null;
  advanceScheduled = false;
  autoPlayAt = null;
  removeBanner();
}

async function doAdvance() {
  const videoId = getVideoId();
  console.log("[TubiShift/player] Requesting advance for video:", videoId);

  const response = await sendMsg("ADVANCE", { current_video_id: videoId });
  console.log("[TubiShift/player] Advance response:", response);

  if (response?.status === "ok" && response.next_url) {
    const nextId = response.next_url.match(/\/tv-shows\/(\d+)/)?.[1];
    if (nextId && window.__tubiShiftNav) {
      window.__tubiShiftNav.updateQueueVideoId(nextId);
    }
    showAdvanceBanner(response);
    advanceTimeout = setTimeout(() => {
      location.href = response.next_url;
    }, 3000);
  } else if (response?.status === "inactive") {
    console.log("[TubiShift/player] Auto-advance is off");
  } else if (response?.status === "queue_ended") {
    showEndBanner();
  }
}

// ─── VIDEO ATTACHMENT ─────────────────────────────────────────────────────────

function attachToVideo(video) {
  if (video._tubiShiftAttached) return;
  video._tubiShiftAttached = true;
  console.log("[TubiShift/player] Attached to <video>");
  suppressTubiAutoplay();
  startWatching();
}

function findAndAttach() {
  const video = document.querySelector("video[data-id='videoPlayerComponent']");
  if (video) { attachToVideo(video); return true; }
  return false;
}

if (!findAndAttach()) {
  const obs = new MutationObserver(() => {
    if (findAndAttach()) obs.disconnect();
  });
  obs.observe(document.body, { childList: true, subtree: true });
}

// ─── NAVIGATION EVENTS FROM navigate.js ──────────────────────────────────────

window.addEventListener("tubishift:away", () => {
  stopWatching();
});

window.addEventListener("tubishift:back", () => {
  showReenableBanner();
});

// ─── BANNERS ──────────────────────────────────────────────────────────────────

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
    stopWatching();
    advanceScheduled = true;
    removeBanner();
  };
}

function showReenableBanner() {
  removeBanner();
  const el = document.createElement("div");
  el.id = "tubishift-banner";
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="font-size:20px;">📺</div>
      <div style="flex:1;">
        <div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;opacity:.7;margin-bottom:2px;">TubiShift</div>
        <div style="font-weight:600;font-size:14px;">Resume auto-advance?</div>
        <div style="font-size:12px;opacity:.8;">You're back on your queue episode</div>
      </div>
      <button id="tubishift-reenable"
        style="background:rgba(255,255,255,.25);border:none;color:white;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;font-weight:600;margin-right:4px;">
        Yes
      </button>
      <button id="tubishift-cancel"
        style="background:rgba(255,255,255,.1);border:none;color:white;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;">
        No
      </button>
    </div>`;
  applyBannerStyles(el);
  document.body.appendChild(el);

  document.getElementById("tubishift-reenable").onclick = async () => {
    removeBanner();
    await sendMsg("NAVIGATED_BACK");
    advanceScheduled = false;
    autoPlayAt = null;
    console.log("[TubiShift/player] Re-enabled by user");
  };
  document.getElementById("tubishift-cancel").onclick = () => {
    if (window.__tubiShiftNav) window.__tubiShiftNav.disableTracking();
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