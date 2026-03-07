/**
 * background.js — TubiShift service worker
 * Acts as a proxy between content scripts (https) and the local http server.
 * Content scripts cannot fetch http://localhost directly from https pages.
 *
 * Uses webNavigation.onHistoryStateUpdated to reliably track SPA navigation
 * within Tubi (React Router pushState calls).
 */

const API = "http://localhost:5000/api";

function setActive(active) {
  return fetch(`${API}/channel/extension/active`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active }),
  }).catch(() => {});
}

// ─── TAB LIFECYCLE ────────────────────────────────────────────────────────────

let tubiTabId = null;
let currentQueueVideoId = null;

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === tubiTabId) {
    tubiTabId = null;
    currentQueueVideoId = null;
    setActive(false);
  }
});

// ─── SPA NAVIGATION TRACKING ─────────────────────────────────────────────────

chrome.webNavigation.onHistoryStateUpdated.addListener((details) => {
  if (details.tabId !== tubiTabId) return;

  const url = details.url;
  const m = url.match(/tubitv\.com\/tv-shows\/(\d+)/);
  const videoId = m ? m[1] : null;

  if (!videoId) {
    // Navigated away from an episode page
    setActive(false);
    chrome.tabs.sendMessage(tubiTabId, { type: "INTERNAL_NAVIGATED_AWAY" }).catch(() => {});
    console.log("[TubiShift/bg] Navigated away →", url);
    return;
  }

  if (currentQueueVideoId && videoId === currentQueueVideoId) {
    // Back on the queue episode — offer re-enable via content script
    chrome.tabs.sendMessage(tubiTabId, { type: "INTERNAL_NAVIGATED_BACK" }).catch(() => {});
    console.log("[TubiShift/bg] Back on queue episode →", videoId);
    return;
  }

  if (currentQueueVideoId && videoId !== currentQueueVideoId) {
    // On a different episode — still away
    setActive(false);
    chrome.tabs.sendMessage(tubiTabId, { type: "INTERNAL_NAVIGATED_AWAY" }).catch(() => {});
    console.log("[TubiShift/bg] Navigated to different episode →", videoId);
  }
}, { url: [{ hostContains: "tubitv.com" }] });

// ─── MESSAGE HANDLER ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === "KEEPALIVE") {
    sendResponse({ ok: true });
    return;
  }

  if (msg.type === "LAUNCHED_FROM_APP") {
    tubiTabId = sender.tab?.id ?? null;
    currentQueueVideoId = msg.current_video_id ?? null;
    setActive(true).then(() => sendResponse({ ok: true }));
    return true;
  }

  if (msg.type === "NAVIGATED_BACK") {
    tubiTabId = sender.tab?.id ?? null;
    setActive(true).then(() => sendResponse({ ok: true }));
    return true;
  }

  if (msg.type === "UPDATE_QUEUE_VIDEO_ID") {
    currentQueueVideoId = msg.video_id ?? null;
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "ADVANCE") {
    fetch(`${API}/channel/advance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_video_id: msg.current_video_id }),
    })
      .then(r => r.json())
      .then(data => sendResponse(data))
      .catch(err => sendResponse({ status: "error", error: err.message }));
    return true;
  }

  if (msg.type === "GET_CREDITS_SECS") {
    fetch(`${API}/channel/extension/get_credits_secs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_video_id: msg.current_video_id }),
    })
      .then(r => r.json())
      .then(data => sendResponse(data))
      .catch(() => sendResponse({ credits_secs: null }));
    return true;
  }

  if (msg.type === "CHECK_STATUS") {
    fetch(`${API}/channel/extension/status`)
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, ...data }))
      .catch(() => sendResponse({ ok: false, error: "Server offline" }));
    return true;
  }

  if (msg.type === "SET_ACTIVE") {
    setActive(msg.active)
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, ...data }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

});