async function render() {
  const { panopStatus } = await chrome.storage.local.get("panopStatus");
  const s = panopStatus || {};
  document.getElementById("server").textContent = s.online ? "online" : "offline";
  document.getElementById("server").className = s.online ? "ok" : "bad";
  document.getElementById("pending").textContent = (s.pending ?? "—");
  document.getElementById("last").textContent =
    (s.lastOk != null) ? `${s.lastOk} ok / ${s.lastFail || 0} fail` : "—";
  document.getElementById("when").textContent =
    s.lastRun ? new Date(s.lastRun).toLocaleTimeString() : "—";
  document.getElementById("err").textContent = s.error || "";
}

document.getElementById("sync").addEventListener("click", () => {
  document.getElementById("sync").textContent = "Syncing…";
  chrome.runtime.sendMessage({ type: "panop-sync-now" }, () => {
    document.getElementById("sync").textContent = "Sync now";
    render();
  });
});

document.getElementById("dedup").addEventListener("click", () => {
  const b = document.getElementById("dedup");
  b.textContent = "Deduping…";
  chrome.runtime.sendMessage({ type: "panop-dedupe-now" }, (r) => {
    b.textContent = r ? `Removed ${r.removed || 0}` : "Dedupe tree";
    setTimeout(() => { b.textContent = "Dedupe tree"; render(); }, 2500);
  });
});

render();
setInterval(render, 1500);
