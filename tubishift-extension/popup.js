const API = "http://localhost:5000/api";

async function loadStatus() {
  try {
    const r = await fetch(`${API}/channel/extension/status`);
    const data = await r.json();
    showOnline(data);
  } catch {
    showOffline();
  }
}

function showOffline() {
  document.getElementById("offlineState").style.display = "block";
  document.getElementById("onlineState").style.display = "none";
}

function showOnline(data) {
  document.getElementById("offlineState").style.display = "none";
  const el = document.getElementById("onlineState");
  el.style.display = "flex";

  const toggle = document.getElementById("activeToggle");
  const dot    = document.getElementById("activeDot");
  const label  = document.getElementById("activeLabel");

  toggle.checked = data.active;
  dot.className  = "dot " + (data.active ? "green" : "red");
  label.textContent = data.active ? "Auto-advance ON" : "Auto-advance OFF";

  if (data.current) {
    const npBox = document.getElementById("nowPlayingBox");
    npBox.style.display = "block";
    document.getElementById("npShow").textContent = data.current.show_title || "";
    document.getElementById("npEp").textContent   = data.current.title || "";

    const qi = document.getElementById("queueInfoBox");
    qi.style.display = "block";
    document.getElementById("queuePos").textContent =
      `${(data.queue_index ?? 0) + 1} / ${data.queue_length ?? "?"}`;
    document.getElementById("queueRemaining").textContent =
      `${data.queue_length - (data.queue_index ?? 0) - 1} episodes`;
  }
}

// Toggle active
document.getElementById("activeToggle").addEventListener("change", async function () {
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
  }
});

// Retry button
document.getElementById("retryBtn").addEventListener("click", (e) => {
  e.preventDefault();
  loadStatus();
});

// Open app
document.getElementById("openAppBtn").addEventListener("click", () => {
  chrome.tabs.create({ url: "http://localhost:5000" });
});

loadStatus();
