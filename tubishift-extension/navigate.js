/**
 * navigate.js — TubiShift navigation observer
 * Runs on all tubitv.com pages at document_idle.
 *
 * Responsibilities:
 *   - Detect launch via ?tubishift=1 and notify background
 *   - Relay INTERNAL_NAVIGATED_AWAY / INTERNAL_NAVIGATED_BACK messages
 *     from background.js to player.js via CustomEvents
 *
 * URL change tracking is handled entirely in background.js via
 * chrome.webNavigation.onHistoryStateUpdated — no pushState patching needed.
 */

function sendMsg(type, payload = {}) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type, ...payload }, (response) => {
      if (chrome.runtime.lastError) resolve(null);
      else resolve(response);
    });
  });
}

// ─── LAUNCH DETECTION ─────────────────────────────────────────────────────────

async function checkLaunchParam() {
  const params = new URLSearchParams(location.search);
  if (!params.has("tubishift")) return;

  // Get the current queue episode from the server so background can track it
  const status = await sendMsg("CHECK_STATUS");
  const currentVideoId = status?.current
    ? String(status.current.content_id)
    : null;

  await sendMsg("LAUNCHED_FROM_APP", { current_video_id: currentVideoId });
  console.log("[TubiShift/nav] Launched from app, queue video id:", currentVideoId);
}

// ─── RELAY MESSAGES FROM BACKGROUND → PLAYER ─────────────────────────────────
// background.js sends INTERNAL_* messages directly to the tab via
// chrome.tabs.sendMessage. We receive them here and re-dispatch as
// CustomEvents so player.js (same page) can react without needing its
// own chrome.runtime.onMessage listener.

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "INTERNAL_NAVIGATED_AWAY") {
    console.log("[TubiShift/nav] Relaying: navigated away");
    window.dispatchEvent(new CustomEvent("tubishift:away"));
  }
  if (msg.type === "INTERNAL_NAVIGATED_BACK") {
    console.log("[TubiShift/nav] Relaying: back on queue episode");
    window.dispatchEvent(new CustomEvent("tubishift:back"));
  }
});

// Expose so player.js can tell background when the queue video ID changes
window.__tubiShiftNav = {
  updateQueueVideoId(id) {
    sendMsg("UPDATE_QUEUE_VIDEO_ID", { video_id: String(id) });
  },
  disableTracking() {
    sendMsg("LAUNCHED_FROM_APP", { current_video_id: null }); // clears tubiTabId state
  },
};

// ─── INIT ─────────────────────────────────────────────────────────────────────

checkLaunchParam();