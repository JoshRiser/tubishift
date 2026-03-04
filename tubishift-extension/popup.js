const API = "http://localhost:5000/api";

let pollInterval = null;
let isUserToggling = false; // prevent poll from overwriting a toggle mid-flight

async function loadStatus() {
  try {
    const r = await fetch(`${API}/channel/extension/status`);
    const data = await r.json();
    console.log("[TubiShift] Status:", data);
    
    showOnline(data);
  } catch {
    showOffline();
  }
}

function showOffline() {
  document.getElementById("offlineState").style.display = "block";
  document.getElementById("onlineState").style.display = "none";
  stopPolling();
}

function showOnline(data) {
  document.getElementById("offlineState").style.display = "none";
  const el = document.getElementById("onlineState");
  el.style.display = "flex";

  // Don't update the toggle while the user is actively changing it
  if (!isUserToggling) {
    const toggle = document.getElementById("activeToggle");
    const dot    = document.getElementById("activeDot");
    const label  = document.getElementById("activeLabel");

    toggle.checked = data.active;
    dot.className  = "dot " + (data.active ? "green" : "red");
    label.textContent = data.active ? "Auto-advance ON" : "Auto-advance OFF";
  }

  const npBox = document.getElementById("nowPlayingBox");
  const qi    = document.getElementById("queueInfoBox");

  if (data.current) {
    npBox.style.display = "block";
    document.getElementById("npShow").textContent = data.current.show_title || "";
    document.getElementById("npEp").textContent   = data.current.title || "";

    qi.style.display = "block";
    document.getElementById("queuePos").textContent =
      `${(data.queue_index ?? 0) + 1} / ${data.queue_length ?? "?"}`;
    document.getElementById("queueRemaining").textContent =
      `${data.queue_length - (data.queue_index ?? 0) - 1} episodes`;
  } else {
    npBox.style.display = "none";
    qi.style.display    = "none";
  }
}

function startPolling() {
  if (pollInterval) return;
  pollInterval = setInterval(loadStatus, 1000);
}

function stopPolling() {
  clearInterval(pollInterval);
  pollInterval = null;
}

// Toggle active
document.getElementById("activeToggle").addEventListener("change", async function () {
  isUserToggling = true;
  try {
    const r = await fetch(`${API}/channel/extension/active`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: this.checked }),
    });
    const data = await r.json();
    showOnline(data);
  } catch {
    this.checked = !this.checked; // revert on failure
  } finally {
    isUserToggling = false;
  }
});

// Retry button
document.getElementById("retryBtn").addEventListener("click", (e) => {
  e.preventDefault();
  loadStatus().then(startPolling);
});

// Open app
document.getElementById("openAppBtn").addEventListener("click", () => {
  chrome.tabs.create({ url: "http://localhost:5000" });
});

// Initial load then start polling
loadStatus().then(startPolling);

console.log("[TubiShift] Popup loaded");