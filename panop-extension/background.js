// Panop Bookmark Bridge — writes queued bookmarks live via chrome.bookmarks API,
// and actively dedupes the Panop folder tree on every run.

const PANOP_BASE = "http://127.0.0.1:8000";
const PANOP_ROOT_NAME = "KMS Output";
const POLL_MINUTES = 0.5;            // MV3 minimum is 0.5 min
const BATCH_SIZE = 40;
const DRAIN_ITERATIONS = 50;         // per trigger, can clear up to 2000 items

// ── URL canonicalization (mirrors the backend) ──────────────────────────────
const TRACKING_RE = /^(utm_|fbclid|gclid|mc_|ref_|_ga|_hs|ref$|src$|source$)/i;
function canon(u) {
  if (!u) return "";
  try {
    const url = new URL(u);
    let host = url.hostname.toLowerCase().replace(/^www\./, "").replace(/^m\./, "").replace(/^mobile\./, "");
    // arxiv /pdf/XXXX(.pdf) → /abs/XXXX
    let path = url.pathname;
    if (host === "arxiv.org") {
      path = path.replace(/^\/pdf\//, "/abs/").replace(/\.pdf$/i, "");
    }
    path = path.replace(/\/+$/, "") || "/";
    const params = [];
    for (const [k, v] of url.searchParams) {
      if (!TRACKING_RE.test(k)) params.push([k, v]);
    }
    params.sort((a, b) => a[0].localeCompare(b[0]));
    const qs = params.map(([k, v]) => `${k}=${v}`).join("&");
    return `${url.protocol}//${host}${path}${qs ? "?" + qs : ""}`;
  } catch (_) {
    return (u || "").toLowerCase().trim();
  }
}

// ── tree helpers ────────────────────────────────────────────────────────────
async function findChildFolder(parentId, name) {
  const kids = await chrome.bookmarks.getChildren(parentId);
  return kids.find(k => !k.url && k.title === name);
}

async function findOrCreateFolder(parentId, name) {
  const found = await findChildFolder(parentId, name);
  if (found) return found;
  return await chrome.bookmarks.create({ parentId, title: name });
}

async function getOtherBookmarksId() {
  try {
    const byId = await chrome.bookmarks.get("2");
    if (byId && byId[0]) return byId[0].id;
  } catch (_) {}
  const tree = await chrome.bookmarks.getTree();
  return tree[0].children[1].id;
}

// Build a canonical-URL → node map for a folder (one-pass, cheap).
async function indexFolder(folderId) {
  const kids = await chrome.bookmarks.getChildren(folderId);
  const map = new Map();
  for (const k of kids) {
    if (!k.url) continue;
    const c = canon(k.url);
    if (!map.has(c)) map.set(c, []);
    map.get(c).push(k);
  }
  return { kids, map };
}

// Keep the bookmark with the longest non-generic title; delete the rest.
const GENERIC_TITLES = new Set(["", "untitled", "new tab", "google"]);
function pickBest(nodes) {
  let best = nodes[0];
  for (const n of nodes) {
    const bt = (best.title || "").trim();
    const nt = (n.title || "").trim();
    const bGeneric = GENERIC_TITLES.has(bt.toLowerCase());
    const nGeneric = GENERIC_TITLES.has(nt.toLowerCase());
    if (bGeneric && !nGeneric) best = n;
    else if (!bGeneric && !nGeneric && nt.length > bt.length + 3) best = n;
  }
  return best;
}

async function dedupeFolder(folderId) {
  const { map } = await indexFolder(folderId);
  let removed = 0;
  for (const nodes of map.values()) {
    if (nodes.length < 2) continue;
    const keep = pickBest(nodes);
    for (const n of nodes) {
      if (n.id === keep.id) continue;
      try { await chrome.bookmarks.remove(n.id); removed++; } catch (_) {}
    }
  }
  return removed;
}

// Walk Panop folder tree, dedupe every subfolder, and also merge duplicates
// that span sibling category folders (keeping the one already in place).
async function dedupePanopTree() {
  const otherId = await getOtherBookmarksId();
  const panop = await findChildFolder(otherId, PANOP_ROOT_NAME);
  if (!panop) return { removed: 0, cats: 0 };
  const cats = await chrome.bookmarks.getChildren(panop.id);
  let removed = 0;
  const seenAcross = new Map(); // canon → {catId, nodeId}
  for (const cat of cats) {
    if (cat.url) continue;
    removed += await dedupeFolder(cat.id);
    // cross-folder pass
    const kids = await chrome.bookmarks.getChildren(cat.id);
    for (const k of kids) {
      if (!k.url) continue;
      const c = canon(k.url);
      const prior = seenAcross.get(c);
      if (prior && prior.catId !== cat.id) {
        try { await chrome.bookmarks.remove(k.id); removed++; } catch (_) {}
      } else if (!prior) {
        seenAcross.set(c, { catId: cat.id, nodeId: k.id });
      }
    }
  }
  return { removed, cats: cats.length };
}

// ── backend I/O ─────────────────────────────────────────────────────────────
async function fetchPending() {
  const res = await fetch(`${PANOP_BASE}/api/v1/bookmarks/pending`, { cache: "no-store" });
  if (!res.ok) throw new Error(`pending ${res.status}`);
  return await res.json();
}

async function ackBackend(items) {
  if (!items.length) return true;
  const res = await fetch(`${PANOP_BASE}/api/v1/bookmarks/ack`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items })
  });
  return res.ok;
}

// ── main sync ───────────────────────────────────────────────────────────────
async function processOnce() {
  let data;
  try {
    data = await fetchPending();
  } catch (e) {
    await setStatus({ online: false, error: String(e), lastRun: Date.now() });
    return { remaining: 0, online: false };
  }

  const pending = data.pending || [];
  if (!pending.length) {
    await setStatus({ online: true, pending: 0, lastRun: Date.now(), error: "" });
    return { remaining: 0, online: true };
  }

  const otherId = await getOtherBookmarksId();
  const panopFolder = await findOrCreateFolder(otherId, PANOP_ROOT_NAME);

  const batch = pending.slice(0, BATCH_SIZE);
  const acked = [];
  let ok = 0, fail = 0;
  // Per-run cache of category folders + their indexed URL maps.
  const catCache = new Map();  // name → {folder, urlMap}

  for (const item of batch) {
    const url = item.url || "";
    const title = item.title || url;
    const category = item.category || "Uncategorized";
    if (!url) { acked.push({ url, category }); continue; }
    try {
      let entry = catCache.get(category);
      if (!entry) {
        const folder = await findOrCreateFolder(panopFolder.id, category);
        const { map } = await indexFolder(folder.id);
        entry = { folder, urlMap: map };
        catCache.set(category, entry);
      }
      const c = canon(url);
      const existingArr = entry.urlMap.get(c);
      if (existingArr && existingArr.length) {
        const existing = existingArr[0];
        const cur = (existing.title || "").trim();
        const nt = (title || "").trim();
        const curGeneric = GENERIC_TITLES.has(cur.toLowerCase());
        if (nt && !GENERIC_TITLES.has(nt.toLowerCase()) &&
            (curGeneric || nt.length > cur.length + 3)) {
          try { await chrome.bookmarks.update(existing.id, { title: nt }); } catch (_) {}
        }
      } else {
        const node = await chrome.bookmarks.create({ parentId: entry.folder.id, title, url });
        entry.urlMap.set(c, [node]);
      }
      ok++;
      acked.push({ url, category });
    } catch (e) {
      fail++;
    }
  }

  const ackOk = await ackBackend(acked).catch(() => false);
  const remaining = Math.max(0, pending.length - batch.length);
  await setStatus({
    online: true,
    pending: remaining,
    lastOk: ok, lastFail: fail,
    lastRun: Date.now(),
    error: ackOk ? "" : "ack failed — will retry"
  });
  return { remaining: ackOk ? remaining : pending.length, online: true };
}

async function drain() {
  for (let i = 0; i < DRAIN_ITERATIONS; i++) {
    const r = await processOnce();
    if (!r.online || r.remaining === 0) break;
  }
}

async function setStatus(patch) {
  const cur = (await chrome.storage.local.get("panopStatus")).panopStatus || {};
  await chrome.storage.local.set({ panopStatus: { ...cur, ...patch } });
}

// ── top-level init: runs whenever the service worker wakes ──────────────────
(async () => {
  // Ensure alarm is armed (persists across SW restarts, but cheap to re-assert).
  const a = await chrome.alarms.get("panop-poll");
  if (!a) await chrome.alarms.create("panop-poll", { periodInMinutes: POLL_MINUTES });
  // One-shot dedupe + drain immediately on wake.
  try { await dedupePanopTree(); } catch (_) {}
  drain();
})();

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.alarms.create("panop-poll", { periodInMinutes: POLL_MINUTES });
  try { await dedupePanopTree(); } catch (_) {}
  drain();
});
chrome.runtime.onStartup.addListener(() => { drain(); });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "panop-poll") return;
  // Periodic: dedupe first (cheap — single walk), then drain queue.
  try { await dedupePanopTree(); } catch (_) {}
  await drain();
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg) return;
  if (msg.type === "panop-sync-now") {
    (async () => { await dedupePanopTree().catch(() => {}); await drain(); sendResponse({ done: true }); })();
    return true;
  }
  if (msg.type === "panop-dedupe-now") {
    (async () => {
      const r = await dedupePanopTree().catch(() => ({ removed: 0, cats: 0 }));
      await setStatus({ lastDedup: Date.now(), lastRemoved: r.removed });
      sendResponse(r);
    })();
    return true;
  }
});
