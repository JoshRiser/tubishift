/**
 * background.js — TubiShift service worker
 * Acts as a proxy between content scripts (https) and the local http server.
 * Content scripts cannot fetch http://localhost directly from https pages.
 */

const API = "http://localhost:5000/api";

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === "ADVANCE") {
    fetch(`${API}/channel/advance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_video_id: msg.current_video_id }),
    })
      .then(r => r.json())
      .then(data => sendResponse(data))
      .catch(err => sendResponse({ status: "error", error: err.message }));
    return true; // keep message channel open for async response
  }

  if (msg.type === "CHECK_STATUS") {
    fetch(`${API}/channel/extension/status`)
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, ...data }))
      .catch(() => sendResponse({ ok: false, error: "Server offline" }));
    return true;
  }

  if (msg.type === "SET_ACTIVE") {
    fetch(`${API}/channel/extension/active`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: msg.active }),
    })
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, ...data }))
      .catch(() => sendResponse({ ok: false }));
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
      .catch(err => sendResponse({ status: "error", error: err.message }));
    return true; // keep message channel open for async response
  }

});
