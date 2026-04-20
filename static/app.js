const tvList = document.getElementById("tv-list");
const scanBtn = document.getElementById("scan");
const remote = document.getElementById("remote");
const remoteName = document.getElementById("remote-name");
const remoteMeta = document.getElementById("remote-meta");
const closeRemote = document.getElementById("close-remote");
const powerBtn = document.getElementById("power");
const statusEl = document.getElementById("status");
const addForm = document.getElementById("add-form");

let activeTv = null;
let statusTimer = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(error.error || `HTTP ${response.status}`);
  }
  return response.json();
}

function showStatus(message, kind = "ok") {
  statusEl.textContent = message;
  statusEl.className = `status ${kind}`;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    statusEl.textContent = "";
    statusEl.className = "status";
  }, 4000);
}

function renderTvs(tvs) {
  tvList.innerHTML = "";
  if (!tvs.length) {
    tvList.innerHTML = `<div class="empty">No TVs yet. Tap <b>Scan</b> while your TV is on, or add one manually.</div>`;
    return;
  }
  for (const tv of tvs) {
    const card = document.createElement("div");
    card.className = "tv";
    card.innerHTML = `
      <div>
        <div class="tv-name">${escapeHtml(tv.name || tv.ip)}</div>
        <div class="tv-meta">
          ${escapeHtml(tv.ip)}${tv.mac ? " · " + escapeHtml(tv.mac) : ""}
          ${tv.model ? " · " + escapeHtml(tv.model) : ""}
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        <span class="badge">${escapeHtml(tv.brand || "generic")}</span>
        <button class="delete" data-ip="${escapeHtml(tv.ip)}" title="Remove">×</button>
      </div>
    `;
    card.addEventListener("click", (event) => {
      if (event.target.classList.contains("delete")) {
        event.stopPropagation();
        removeTv(tv.ip);
        return;
      }
      openRemote(tv);
    });
    tvList.appendChild(card);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
  );
}

async function loadTvs() {
  try {
    const tvs = await api("/api/tvs");
    renderTvs(tvs);
  } catch (error) {
    showStatus(error.message, "err");
  }
}

async function scan() {
  scanBtn.disabled = true;
  scanBtn.textContent = "Scanning…";
  try {
    const result = await api("/api/discover", { method: "POST" });
    renderTvs(result.all);
    showStatus(
      result.found.length
        ? `Found ${result.found.length} TV${result.found.length === 1 ? "" : "s"}`
        : "No new TVs found. Ensure the TV is on for discovery."
    );
  } catch (error) {
    showStatus(error.message, "err");
  } finally {
    scanBtn.disabled = false;
    scanBtn.textContent = "Scan";
  }
}

async function removeTv(ip) {
  if (!confirm(`Remove TV at ${ip}?`)) return;
  await api(`/api/tvs/${encodeURIComponent(ip)}`, { method: "DELETE" });
  await loadTvs();
}

function openRemote(tv) {
  activeTv = tv;
  remoteName.textContent = tv.name || tv.ip;
  remoteMeta.textContent = `${tv.ip} · ${tv.brand || "generic"}${tv.mac ? " · " + tv.mac : " · no MAC"}`;
  remote.classList.remove("hidden");
}

closeRemote.addEventListener("click", () => {
  remote.classList.add("hidden");
  activeTv = null;
});

powerBtn.addEventListener("click", async () => {
  if (!activeTv) return;
  powerBtn.disabled = true;
  try {
    const result = await api(`/api/tvs/${encodeURIComponent(activeTv.ip)}/power-on`, {
      method: "POST",
    });
    showStatus(result.ok ? `Power on sent (${result.method})` : result.detail, result.ok ? "ok" : "err");
  } catch (error) {
    showStatus(error.message, "err");
  } finally {
    powerBtn.disabled = false;
  }
});

remote.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-key]");
  if (!button || !activeTv) return;
  const key = button.dataset.key;
  try {
    const result = await api(`/api/tvs/${encodeURIComponent(activeTv.ip)}/key`, {
      method: "POST",
      body: JSON.stringify({ key }),
    });
    showStatus(result.ok ? `${key} → ${result.detail}` : result.detail, result.ok ? "ok" : "err");
  } catch (error) {
    showStatus(error.message, "err");
  }
});

addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(addForm).entries());
  try {
    await api("/api/tvs", { method: "POST", body: JSON.stringify(data) });
    addForm.reset();
    await loadTvs();
    showStatus("TV saved");
  } catch (error) {
    showStatus(error.message, "err");
  }
});

scanBtn.addEventListener("click", scan);

document.getElementById("shutdown").addEventListener("click", async () => {
  if (!confirm("Stop the server? You'll need to rerun `python server.py` in a-Shell to start it again.")) return;
  try {
    await fetch("/api/shutdown", { method: "POST" });
    showStatus("Server stopped. Reopen a-Shell and run python server.py to restart.");
  } catch {
    showStatus("Server stopped.");
  }
});

loadTvs();
