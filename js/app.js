/**
 * Fuzzybear / raebyzzuF Trait Mixer — REAL collection art edition.
 *
 * No separable layer sheets exist publicly, so the mixer works on the real
 * composite PNGs from the collection's IPFS metadata:
 *   - you pick a trait per category (arrows / search / ?)
 *   - we find minted bears with that exact fingerprint, or the nearest ones
 *   - the canvas shows the real artwork of the best match
 *   - custom uploads are drawn as overlay layers on top of the real bear
 */
(() => {
  "use strict";

  const EXPORT_SIZE = 512;
  const ARROW_CATEGORIES = ["background", "fur", "clothes", "eyes", "mouth", "headwear", "mask"];
  const ANY = { id: "*", name: "Any", any: true };
  /** Public IPFS gateways known to send Access-Control-Allow-Origin (filebase first). */
  const IPFS_GATEWAYS = [
    "https://ipfs.filebase.io/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
    "https://dweb.link/ipfs/",
    "https://ipfs.io/ipfs/",
  ];
  /** Visual weight of a category when ranking "closest" bears. */
  const WEIGHT = { fur: 1.3, headwear: 1.2, eyes: 1.1, clothes: 1.1, mouth: 1, background: 0.9, mask: 1 };

  let manifest = null;
  let bears = [];
  let cachedSet = new Set();
  let hasProxy = false;
  const selection = {}; // catId -> index into getTraits(catId)
  const customTraits = []; // { categoryId, id, name, img }
  let matches = []; // [{bear, score, exact, diffs}]
  let matchPos = 0;
  let currentImg = null;
  let currentBear = null;
  let renderToken = 0;
  let lastCat = null; // category the user just changed → must show in closest match
  const imgCache = new Map();
  const els = {};

  async function init() {
    cacheDom();
    bindEvents();
    try {
      const [m, b] = await Promise.all([
        fetch("traits-manifest.json").then((r) => r.json()),
        fetch("data/bears.json").then((r) => r.json()),
      ]);
      manifest = m;
      bears = b.bears;
      try {
        const c = await fetch("api/cached").then((r) => (r.ok ? r.json() : null));
        if (c && c.server) { hasProxy = true; cachedSet = new Set(c.cached); }
      } catch (_) { /* no serve.py proxy */ }
      if (!hasProxy) {
        try {
          const c = await fetch("assets/cached.json").then((r) => (r.ok ? r.json() : null));
          if (c && Array.isArray(c.cached)) cachedSet = new Set(c.cached);
        } catch (_) { /* discover local assets on demand via candidate URLs */ }
      }
      buildArrowRows();
      els.bearCount.textContent = bears.length;
      // Start on a random real (already cached) bear
      const pool = bears.filter((x) => cachedSet.has(x.edition));
      adoptBear((pool.length ? pool : bears)[Math.floor(Math.random() * (pool.length || bears.length))]);
      toast(`${bears.length} real bears loaded`);
    } catch (err) {
      console.error(err);
      toast("Failed to load collection data");
      els.archPlaceholder.textContent = "ERR";
    }
  }

  function cacheDom() {
    const $ = (id) => document.getElementById(id);
    Object.assign(els, {
      search: $("search"), searchResults: $("search-results"), btnRandom: $("btn-random"),
      canvas: $("preview-canvas"), archPlaceholder: $("arch-placeholder"),
      leftArrows: $("arrows-left"), rightArrows: $("arrows-right"), traitStrip: $("trait-strip"),
      btnExport: $("btn-export"), btnUpload: $("btn-upload"), btnReset: $("btn-reset"),
      modal: $("upload-modal"), uploadCat: $("upload-category"), uploadName: $("upload-name"),
      uploadFile: $("upload-file"), uploadConfirm: $("upload-confirm"), uploadCancel: $("upload-cancel"),
      toast: $("toast"), matchBadge: $("match-badge"), matchPrev: $("match-prev"), matchNext: $("match-next"),
      matchStrip: $("match-strip"), matchTitle: $("match-title"), bearCount: $("bear-count"),
      loading: $("arch-loading"),
    });
    els.ctx = els.canvas.getContext("2d");
  }

  function bindEvents() {
    els.btnRandom.addEventListener("click", randomize);
    els.btnExport.addEventListener("click", exportPng);
    els.btnUpload.addEventListener("click", openUploadModal);
    els.btnReset.addEventListener("click", resetAny);
    els.uploadCancel.addEventListener("click", closeUploadModal);
    els.uploadConfirm.addEventListener("click", confirmUpload);
    els.modal.addEventListener("click", (e) => { if (e.target === els.modal) closeUploadModal(); });
    els.matchPrev.addEventListener("click", () => stepMatch(-1));
    els.matchNext.addEventListener("click", () => stepMatch(1));

    els.search.addEventListener("input", onSearch);
    els.search.addEventListener("focus", onSearch);
    els.search.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { els.searchResults.classList.remove("open"); els.search.blur(); }
      if (e.key === "Enter") { const f = els.searchResults.querySelector("button.search-item"); if (f) f.click(); }
    });
    document.addEventListener("click", (e) => {
      if (!els.search.contains(e.target) && !els.searchResults.contains(e.target)) els.searchResults.classList.remove("open");
    });

    let focusCat = 0;
    document.addEventListener("keydown", (e) => {
      if (!manifest || e.target.matches("input, select, textarea")) return;
      const cats = ARROW_CATEGORIES;
      if (e.key === "ArrowUp") { e.preventDefault(); focusCat = (focusCat - 1 + cats.length) % cats.length; highlightFocus(cats[focusCat]); }
      else if (e.key === "ArrowDown") { e.preventDefault(); focusCat = (focusCat + 1) % cats.length; highlightFocus(cats[focusCat]); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); cycle(cats[focusCat], -1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); cycle(cats[focusCat], 1); }
      else if (e.key === "?" || e.key === "r") randomize();
      else if (e.key === "[") stepMatch(-1);
      else if (e.key === "]") stepMatch(1);
    });
  }

  // ---------- traits ----------
  function getTraits(catId) {
    const base = manifest.categories[catId]?.traits || [];
    const extras = customTraits.filter((c) => c.categoryId === catId)
      .map((c) => ({ id: c.id, name: c.name, custom: true, img: c.img }));
    return [ANY, ...base, ...extras];
  }
  const getSelectedTrait = (catId) => getTraits(catId)[selection[catId] ?? 0] || ANY;
  function setTrait(catId, traitId) {
    const idx = getTraits(catId).findIndex((t) => t.id === traitId);
    selection[catId] = idx >= 0 ? idx : 0;
  }
  const traitName = (catId, id) => manifest.categories[catId].traits.find((t) => t.id === id)?.name || id;

  function highlightFocus(catId) {
    els.traitStrip.querySelectorAll(".trait-row").forEach((r) => r.classList.toggle("active", r.dataset.cat === catId));
  }

  function buildArrowRows() {
    els.leftArrows.innerHTML = "";
    els.rightArrows.innerHTML = "";
    for (const catId of ARROW_CATEGORIES) {
      const label = manifest.categories[catId].label;
      for (const [col, dir, chev] of [[els.leftArrows, -1, "←"], [els.rightArrows, 1, "→"]]) {
        const slot = document.createElement("div");
        slot.className = "arrow-slot";
        const btn = document.createElement("button");
        btn.className = "arrow-btn";
        btn.type = "button";
        btn.setAttribute("aria-label", `${dir < 0 ? "Previous" : "Next"} ${label}`);
        btn.innerHTML = `<span class="chev">${chev}</span>`;
        btn.addEventListener("click", () => cycle(catId, dir));
        const hint = document.createElement("div");
        hint.className = "cat-hint";
        hint.textContent = label.slice(0, 4);
        slot.append(btn, hint);
        col.appendChild(slot);
      }
    }
  }

  function cycle(catId, dir) {
    const traits = getTraits(catId);
    // skip the "Any" wildcard while cycling (still reachable via Reset/search)
    let i = selection[catId] ?? 0;
    do { i = (i + dir + traits.length) % traits.length; } while (traits[i].any && traits.length > 1);
    selection[catId] = i;
    lastCat = catId;
    highlightFocus(catId);
    update();
  }

  /** Set selection to exactly a real bear's traits and show it. */
  function adoptBear(bear) {
    lastCat = null;
    for (const c of manifest.layerOrder) {
      const cur = getSelectedTrait(c);
      if (!cur.custom) setTrait(c, bear.traits[c]);
    }
    update(bear.edition);
  }

  // ---------- matching ----------
  function computeMatches() {
    const want = {};
    let wanted = 0;
    for (const c of manifest.layerOrder) {
      const t = getSelectedTrait(c);
      if (!t.any && !t.custom) { want[c] = t.id; wanted++; }
    }
    const res = bears.map((bear) => {
      let score = 0, hits = 0;
      const diffs = [];
      for (const c in want) {
        if (bear.traits[c] === want[c]) { score += (WEIGHT[c] || 1) + (c === lastCat ? 10 : 0); hits++; }
        else diffs.push(c);
      }
      return { bear, score, hits, wanted, exact: hits === wanted, diffs };
    });
    res.sort((a, b) => b.score - a.score
      || (cachedSet.has(b.bear.edition) - cachedSet.has(a.bear.edition))
      || a.bear.edition - b.bear.edition);
    const exact = res.filter((r) => r.exact);
    return exact.length ? exact : res.slice(0, 30);
  }

  function update(preferEdition) {
    matches = computeMatches();
    matchPos = 0;
    if (preferEdition != null) {
      const i = matches.findIndex((m) => m.bear.edition === preferEdition);
      if (i >= 0) matchPos = i;
    }
    renderMatchStrip();
    showMatch();
  }

  function stepMatch(dir) {
    if (!matches.length) return;
    matchPos = (matchPos + dir + matches.length) % matches.length;
    showMatch();
  }

  // ---------- images ----------
  /** Ordered URL candidates for a bear: proxy → local asset → public IPFS gateways. */
  function bearSrcCandidates(bear) {
    if (hasProxy) return [`bear-img/${bear.edition}.webp`];
    const local = `assets/bears/${bear.edition}.webp`;
    const cid = encodeURI(bear.image.replace("ipfs://", "")).replace(/#/g, "%23");
    const gateways = IPFS_GATEWAYS.map((g) => g + cid);
    // Prefer local file when known-cached; skip 404 probe when manifest says missing
    if (cachedSet.has(bear.edition)) return [local, ...gateways];
    if (cachedSet.size > 0) return gateways;
    return [local, ...gateways];
  }

  /** Best single URL for thumbs / hints (local when known-cached, else first candidate). */
  function bearSrc(bear) {
    if (hasProxy) return `bear-img/${bear.edition}.webp`;
    if (cachedSet.has(bear.edition)) return `assets/bears/${bear.edition}.webp`;
    return bearSrcCandidates(bear)[0];
  }

  function loadOne(src, cors) {
    if (imgCache.has(src)) return imgCache.get(src);
    const p = new Promise((resolve, reject) => {
      const img = new Image();
      if (cors) img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => { imgCache.delete(src); reject(new Error("Failed: " + src)); };
      img.src = src;
    });
    imgCache.set(src, p);
    return p;
  }

  /** Try candidates in order until one loads. Local same-origin; IPFS needs CORS. */
  async function loadBearImage(bear) {
    const urls = bearSrcCandidates(bear);
    let lastErr;
    for (let i = 0; i < urls.length; i++) {
      const src = urls[i];
      const cors = !hasProxy && !src.startsWith("assets/");
      try {
        const img = await loadOne(src, cors);
        if (src.startsWith("assets/") || hasProxy) cachedSet.add(bear.edition);
        return img;
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error("no image source");
  }

  async function showMatch() {
    const m = matches[matchPos];
    if (!m) return;
    const token = ++renderToken;
    currentBear = m.bear;
    updateBadge(m);
    updateTraitStrip(m);
    markActiveThumb();
    const local = cachedSet.has(m.bear.edition);
    els.loading.textContent = local ? "" : "fetching from IPFS…";
    els.loading.classList.toggle("show", !local);
    try {
      const img = await loadBearImage(m.bear);
      if (token !== renderToken) return;
      currentImg = img;
      els.loading.classList.remove("show");
      draw();
      const nxt = matches[(matchPos + 1) % matches.length];
      if (nxt && nxt !== m) loadBearImage(nxt.bear).catch(() => {});
    } catch (e) {
      if (token !== renderToken) return;
      els.loading.textContent = "IPFS fetch failed — try → for another";
      els.loading.classList.add("show");
    }
  }

  function overlays() {
    return manifest.layerOrder.map(getSelectedTrait).filter((t) => t.custom).map((t) => t.img);
  }

  function draw() {
    const ctx = els.ctx;
    const { width: W, height: H } = els.canvas;
    ctx.clearRect(0, 0, W, H);
    if (!currentImg) { els.archPlaceholder.classList.remove("hidden"); return; }
    // Fill arch with the bear's own background colour, square art anchored bottom
    const s = Math.min(W, H);
    const y = H - s;
    ctx.drawImage(currentImg, 0, 0, 4, 4, 0, 0, W, y + 2); // stretch top-left pixel = bg colour
    ctx.drawImage(currentImg, 0, y, s, s);
    for (const o of overlays()) ctx.drawImage(o, 0, y, s, s);
    els.archPlaceholder.classList.add("hidden");
  }

  // ---------- UI pieces ----------
  function updateBadge(m) {
    const b = m.bear;
    const link = `https://bithomp.com/nft/${b.nftId}`;
    let cls, text;
    if (m.wanted === 0) { cls = "any"; text = `Browsing all bears · ${matches.length}`; }
    else if (m.exact) { cls = "exact"; text = `✓ Minted · ${matches.length} match${matches.length > 1 ? "es" : ""}`; }
    else { cls = "near"; text = `✗ Not minted · closest ${m.hits}/${m.wanted} traits`; }
    els.matchBadge.className = "match-badge " + cls;
    els.matchBadge.innerHTML = `${text} — <a href="${link}" target="_blank" rel="noopener">${escapeHtml(b.name)}</a> <span class="pos">${matchPos + 1}/${matches.length}</span>`;
    els.matchTitle.textContent = m.exact && m.wanted ? `Real bears with this mix (${matches.length})` : (m.wanted ? "Closest real bears" : "Real bears");
  }

  function updateTraitStrip(m) {
    els.traitStrip.innerHTML = "";
    for (const catId of manifest.layerOrder) {
      const t = getSelectedTrait(catId);
      const real = m.bear.traits[catId];
      const off = !t.any && !t.custom && real !== t.id;
      const row = document.createElement("div");
      row.className = "trait-row" + (off ? " diff" : "");
      row.dataset.cat = catId;
      let val = t.custom ? `${escapeHtml(t.name)} ✦` : t.any ? `<em>Any</em> · ${escapeHtml(traitName(catId, real))}` : escapeHtml(t.name);
      if (off) val += ` <span class="has">(bear: ${escapeHtml(traitName(catId, real))})</span>`;
      row.innerHTML = `<span class="label">${manifest.categories[catId].label}</span><span class="value">${val}</span>`;
      row.title = "Double-click to set this category to Any (wildcard)";
      row.addEventListener("click", () => { highlightFocus(catId); });
      row.addEventListener("dblclick", () => { selection[catId] = 0; update(); });
      els.traitStrip.appendChild(row);
    }
  }

  function renderMatchStrip() {
    els.matchStrip.innerHTML = "";
    matches.slice(0, 40).forEach((m, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "thumb" + (m.exact ? "" : " near");
      b.title = `${m.bear.name}${m.wanted ? ` · ${m.hits}/${m.wanted}` : ""} — click to load all its traits`;
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = m.bear.name;
      // only auto-load thumbs that are cached (or first few) so we don't hammer IPFS
      if (cachedSet.has(m.bear.edition) || i < 6) img.src = bearSrc(m.bear);
      else { img.dataset.src = bearSrc(m.bear); b.classList.add("lazy"); }
      const cap = document.createElement("span");
      cap.textContent = "#" + m.bear.edition;
      b.append(img, cap);
      b.addEventListener("click", () => {
        if (img.dataset.src && !img.src) img.src = img.dataset.src;
        matchPos = i;
        if (!m.exact) adoptBear(m.bear); else showMatch();
      });
      els.matchStrip.appendChild(b);
    });
    if (matches.length > 40) {
      const more = document.createElement("div");
      more.className = "thumb-more";
      more.textContent = `+${matches.length - 40} more (use ‹ ›)`;
      els.matchStrip.appendChild(more);
    }
  }

  function markActiveThumb() {
    [...els.matchStrip.querySelectorAll(".thumb")].forEach((t, i) => {
      t.classList.toggle("active", i === matchPos);
      if (i === matchPos) {
        const img = t.querySelector("img");
        if (img.dataset.src && !img.src) img.src = img.dataset.src;
        t.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    });
  }

  function randomize() {
    els.btnRandom.classList.remove("spin");
    void els.btnRandom.offsetWidth;
    els.btnRandom.classList.add("spin");
    if (Math.random() < 0.5) {
      // a real minted bear
      adoptBear(bears[Math.floor(Math.random() * bears.length)]);
      toast("Random real bear");
    } else {
      // a random mix (probably not minted → closest real bear)
      lastCat = null;
      for (const c of manifest.layerOrder) {
        const t = getTraits(c);
        selection[c] = 1 + Math.floor(Math.random() * (t.length - 1));
      }
      update();
      toast(matches[0]?.exact ? "Random mix — it exists!" : "Random mix — closest real bear");
    }
  }

  function resetAny() {
    for (const c of manifest.layerOrder) selection[c] = 0;
    update();
    toast("All traits = Any · browsing collection");
  }

  // ---------- export ----------
  function exportPng() {
    if (!currentImg) return toast("Nothing to export yet");
    const out = document.createElement("canvas");
    out.width = out.height = EXPORT_SIZE;
    const ctx = out.getContext("2d");
    ctx.drawImage(currentImg, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    for (const o of overlays()) ctx.drawImage(o, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    try {
      out.toBlob((blob) => {
        if (!blob) return toast("Export failed");
        const a = document.createElement("a");
        const custom = overlays().length ? "-custom" : "";
        a.download = `raebyzzuF-${currentBear.edition}${custom}.png`;
        a.href = URL.createObjectURL(blob);
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        toast("PNG downloaded");
      }, "image/png");
    } catch (e) {
      toast("Export blocked (cross-origin) — use a cached local bear or serve.py");
    }
  }

  // ---------- search ----------
  function onSearch() {
    const q = els.search.value.trim().toLowerCase();
    els.searchResults.innerHTML = "";
    if (!q) return els.searchResults.classList.remove("open");
    const hits = [];
    const num = q.replace(/^#/, "");
    if (/^\d+$/.test(num)) {
      bears.filter((b) => String(b.edition).startsWith(num)).slice(0, 8)
        .forEach((b) => hits.push({ kind: "bear", bear: b, name: b.name, label: "Bear" }));
    }
    for (const catId of manifest.layerOrder) {
      const cat = manifest.categories[catId];
      getTraits(catId).forEach((t, idx) => {
        if (t.any) return;
        const hay = `${t.name} ${t.onChain || ""}`.toLowerCase();
        if (hay.includes(q) || cat.label.toLowerCase().includes(q)) hits.push({ kind: "trait", catId, idx, trait: t, name: t.name, label: cat.label });
      });
    }
    if (!hits.length) {
      els.searchResults.innerHTML = `<div class="search-item"><span>No traits match “${escapeHtml(q)}”</span></div>`;
      return els.searchResults.classList.add("open");
    }
    hits.slice(0, 40).forEach((hit) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "search-item";
      const hl = escapeHtml(hit.name).replace(new RegExp(`(${escapeRegex(q)})`, "ig"), "<mark>$1</mark>");
      const extra = hit.kind === "trait" && hit.trait.count ? ` <small>×${hit.trait.count}</small>` : "";
      item.innerHTML = `<span>${hl}${hit.trait?.custom ? " ✦" : ""}${extra}</span><span class="cat">${escapeHtml(hit.label)}</span>`;
      item.addEventListener("click", () => {
        if (hit.kind === "bear") adoptBear(hit.bear);
        else { selection[hit.catId] = hit.idx; lastCat = hit.catId; highlightFocus(hit.catId); update(); }
        els.search.value = hit.name;
        els.searchResults.classList.remove("open");
        toast(`${hit.label}: ${hit.name}`);
      });
      els.searchResults.appendChild(item);
    });
    els.searchResults.classList.add("open");
  }

  // ---------- custom upload ----------
  function openUploadModal() {
    els.uploadCat.innerHTML = "";
    for (const catId of manifest.layerOrder) {
      const opt = document.createElement("option");
      opt.value = catId;
      opt.textContent = manifest.categories[catId].label;
      els.uploadCat.appendChild(opt);
    }
    els.uploadName.value = "";
    els.uploadFile.value = "";
    els.modal.classList.add("open");
  }
  const closeUploadModal = () => els.modal.classList.remove("open");

  async function confirmUpload() {
    const catId = els.uploadCat.value;
    const file = els.uploadFile.files?.[0];
    let name = els.uploadName.value.trim();
    if (!file) return toast("Pick an image file");
    if (!/^image\//.test(file.type)) return toast("Need an image (PNG/SVG/WebP/JPEG)");
    if (!name) name = file.name.replace(/\.[^.]+$/, "");
    const dataUrl = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
    const img = await loadOne(dataUrl, false);
    const id = "custom-" + Date.now().toString(36);
    customTraits.push({ categoryId: catId, id, name, img });
    selection[catId] = getTraits(catId).length - 1;
    closeUploadModal();
    update(currentBear?.edition);
    toast(`Added “${name}” overlay to ${manifest.categories[catId].label}`);
  }

  // ---------- utils ----------
  let toastTimer;
  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("show"), 1800);
  }
  const escapeHtml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
