/**
 * Fuzzybear / raebyzzuF Trait Mixer — LAYER remix edition.
 *
 * Official separable trait PNGs were never published.
 * - Background: solid/pattern plates + chroma-key cutout (true layer).
 * - Mask / Headwear / Clothes / Eyes / Mouth: approx overlay plates derived
 *   from consensus composite diffs (honest "approx" in UI).
 * - Fur: nearest-match body (whole-body recolor — not an overlay).
 */
(() => {
  "use strict";

  const EXPORT_SIZE = 512;
  const ARROW_CATEGORIES = ["background", "fur", "clothes", "eyes", "mouth", "headwear", "mask"];
  /** Overlay cats that can keep the base body stable when a plate exists. */
  const OVERLAY_CATS = ["clothes", "mouth", "eyes", "headwear", "mask"];
  /** Preferred base trait when applying an overlay (stable body). */
  const OVERLAY_BASELINES = {
    mask: "none",
    headwear: "none",
    clothes: "none",
    eyes: "blue",
    mouth: "normal",
  };
  /** True / approx layer categories — cycling these prefers keeping the base bear. */
  const LAYER_CATEGORIES = ["background", ...OVERLAY_CATS];
  /** Categories that drive which base bear is shown (layers applied separately). */
  const BODY_CATEGORIES = ["fur"];
  const ANY = { id: "*", name: "Any", any: true };
  const IPFS_GATEWAYS = [
    "https://ipfs.filebase.io/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
    "https://dweb.link/ipfs/",
    "https://ipfs.io/ipfs/",
  ];
  const WEIGHT = { fur: 1.3, headwear: 1.2, eyes: 1.1, clothes: 1.1, mouth: 1, mask: 1, background: 0.4 };
  const KEY_TOL = 30;
  const KEY_SOFT = 16;

  let manifest = null;
  let bgMeta = null; // data/backgrounds.json
  let overlayMeta = null; // data/overlays.json
  let bears = [];
  let cachedSet = new Set();
  let hasProxy = false;
  const selection = {};
  const customTraits = [];
  let matches = [];
  let matchPos = 0;
  let currentImg = null;      // raw composite of base bear
  let currentCutout = null;   // canvas with transparent bg
  let currentBgImg = null;    // background plate image
  let currentOverlays = [];   // [{cat,z,img}] approx plates in z-order
  let currentBear = null;     // base bear (character)
  let renderToken = 0;
  let lastCat = null;
  const imgCache = new Map();
  const cutoutCache = new Map(); // edition -> canvas
  const overlayPlateCache = new Map(); // `${cat}:${id}` -> image
  const els = {};

  async function init() {
    cacheDom();
    bindEvents();
    try {
      const [m, b, bg, ov] = await Promise.all([
        fetch("traits-manifest.json").then((r) => r.json()),
        fetch("data/bears.json").then((r) => r.json()),
        fetch("data/backgrounds.json").then((r) => r.json()).catch(() => null),
        fetch("data/overlays.json").then((r) => r.json()).catch(() => null),
      ]);
      manifest = m;
      bears = b.bears;
      bgMeta = bg;
      overlayMeta = ov;
      try {
        const c = await fetch("api/cached").then((r) => (r.ok ? r.json() : null));
        if (c && c.server) { hasProxy = true; cachedSet = new Set(c.cached); }
      } catch (_) { /* no proxy */ }
      if (!hasProxy) {
        try {
          const c = await fetch("assets/cached.json").then((r) => (r.ok ? r.json() : null));
          if (c && Array.isArray(c.cached)) cachedSet = new Set(c.cached);
        } catch (_) { /* discover on demand */ }
      }
      buildArrowRows();
      els.bearCount.textContent = bears.length;
      const pool = bears.filter((x) => cachedSet.has(x.edition));
      adoptBear((pool.length ? pool : bears)[Math.floor(Math.random() * (pool.length || bears.length))]);
      toast(`${bears.length} bears · bg + overlay layers on`);
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
    let i = selection[catId] ?? 0;
    do { i = (i + dir + traits.length) % traits.length; } while (traits[i].any && traits.length > 1);
    selection[catId] = i;
    lastCat = catId;
    highlightFocus(catId);
    if (LAYER_CATEGORIES.includes(catId)) {
      cycleLayer(catId);
    } else {
      update();
    }
  }

  /** Layer remix: keep body stable; swap plate/overlay. */
  function cycleLayer(catId) {
    const t = getSelectedTrait(catId);
    const label = manifest.categories[catId].label;

    if (catId === "background") {
      updateBadgeForLayer();
      updateTraitStrip(matches[matchPos] || { bear: currentBear, exact: false, wanted: 1, hits: 0 });
      showMatch({ keepBear: true });
      toast(`${label} → ${t.name} (layer)`);
      return;
    }

    // Overlay category: prefer a baseline-trait base so the body does not jump.
    if (OVERLAY_CATS.includes(catId)) {
      const baseline = overlayBaseline(catId);
      const needsBaselineBase = (() => {
        if (!currentBear) return true;
        if (t.any) return false;
        if (t.custom) return false;
        // Selecting baseline (e.g. none / blue / normal): want a base that already has it.
        if (t.id === baseline) return currentBear.traits[catId] !== baseline;
        // Selecting a plate trait: overlay looks best on a baseline base.
        if (hasOverlayPlate(catId, t.id)) return currentBear.traits[catId] !== baseline;
        // No plate → fall through to body match via update()
        return true;
      })();

      if (needsBaselineBase) {
        update();
        toast(`${label} → ${t.name} (approx · stable body)`);
        return;
      }

      updateBadgeForLayer();
      updateTraitStrip(matches[matchPos] || { bear: currentBear, exact: false, wanted: 1, hits: 0 });
      showMatch({ keepBear: true });
      const approx = t.id !== baseline && hasOverlayPlate(catId, t.id);
      toast(`${label} → ${t.name}${approx ? " (approx layer)" : ""}`);
      return;
    }

    update();
  }

  function overlayBaseline(catId) {
    return overlayMeta?.baselines?.[catId] || OVERLAY_BASELINES[catId] || "none";
  }

  function hasOverlayPlate(catId, traitId) {
    if (!traitId) return false;
    const info = overlayMeta?.layers?.[catId]?.traits?.[traitId];
    return !!(info && info.file && !info.none);
  }

  function overlayInfo(catId, traitId) {
    return overlayMeta?.layers?.[catId]?.traits?.[traitId] || null;
  }

  function overlayActive(catId) {
    const t = getSelectedTrait(catId);
    if (t.any || t.custom) return false;
    const baseline = overlayBaseline(catId);
    if (t.id === baseline) return false;
    return hasOverlayPlate(catId, t.id);
  }

  function adoptBear(bear) {
    lastCat = null;
    for (const c of manifest.layerOrder) {
      const cur = getSelectedTrait(c);
      if (!cur.custom) setTrait(c, bear.traits[c]);
    }
    update(bear.edition);
  }

  // ---------- matching (fur drives body; overlay cats prefer baselines) ----------
  function computeMatches() {
    const want = {};
    let wanted = 0;
    for (const c of BODY_CATEGORIES) {
      const t = getSelectedTrait(c);
      if (!t.any && !t.custom) { want[c] = t.id; wanted++; }
    }
    // Overlay cats without a usable plate still drive body matching.
    for (const c of OVERLAY_CATS) {
      const t = getSelectedTrait(c);
      if (t.any || t.custom) continue;
      const baseline = overlayBaseline(c);
      if (t.id === baseline) continue; // prefer baseline via soft score below
      if (hasOverlayPlate(c, t.id)) continue; // plate handles it
      want[c] = t.id;
      wanted++;
    }

    const bgT = getSelectedTrait("background");
    const res = bears.map((bear) => {
      let score = 0, hits = 0;
      const diffs = [];
      for (const c in want) {
        if (bear.traits[c] === want[c]) {
          score += (WEIGHT[c] || 1) + (c === lastCat ? 10 : 0);
          hits++;
        } else diffs.push(c);
      }
      // Soft preference for native bg match
      if (!bgT.any && !bgT.custom && bear.traits.background === bgT.id) score += 0.15;

      // Prefer baseline trait on base when an overlay plate is active (or baseline selected)
      for (const c of OVERLAY_CATS) {
        const t = getSelectedTrait(c);
        if (t.any || t.custom) continue;
        const baseline = overlayBaseline(c);
        const active = overlayActive(c);
        const wantBase = active || t.id === baseline;
        if (wantBase && bear.traits[c] === baseline) {
          // Clothes-none is rare — keep boost modest so fur stability still wins
          score += c === "clothes" ? 0.35 : 0.85;
        } else if (!wantBase && bear.traits[c] === t.id) {
          score += 0.25; // soft native match when not overlaying
        }
      }

      // Body stability: keep current fur when cycling accessories
      if (currentBear && bear.traits.fur === currentBear.traits.fur) score += 0.55;
      if (currentBear && bear.edition === currentBear.edition) score += 0.05;
      return { bear, score, hits, wanted, exact: hits === wanted && wanted > 0, diffs };
    });
    res.sort((a, b) => b.score - a.score
      || (cachedSet.has(b.bear.edition) - cachedSet.has(a.bear.edition))
      || a.bear.edition - b.bear.edition);
    if (wanted === 0) return res.slice(0, 40); // browsing
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
    showMatch(); // keeps selected Background layer on the newly shown base bear
  }

  // ---------- images ----------
  function bearSrcCandidates(bear) {
    if (hasProxy) return [`bear-img/${bear.edition}.webp`];
    const local = `assets/bears/${bear.edition}.webp`;
    const cid = encodeURI(bear.image.replace("ipfs://", "")).replace(/#/g, "%23");
    const gateways = IPFS_GATEWAYS.map((g) => g + cid);
    if (cachedSet.has(bear.edition)) return [local, ...gateways];
    if (cachedSet.size > 0) return gateways;
    return [local, ...gateways];
  }

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

  function bgInfo(bgId) {
    return bgMeta?.backgrounds?.[bgId] || null;
  }

  function bgColorForBear(bear) {
    const info = bgInfo(bear.traits.background);
    if (info?.color) return info.color;
    return null;
  }

  async function loadBgPlate(bgId) {
    const info = bgInfo(bgId);
    if (!info) return null;
    try {
      return await loadOne(info.file, false);
    } catch (_) {
      // Fallback: solid colour canvas
      const c = document.createElement("canvas");
      c.width = c.height = EXPORT_SIZE;
      const ctx = c.getContext("2d");
      const [r, g, b] = info.color || [40, 40, 40];
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(0, 0, c.width, c.height);
      return c;
    }
  }

  async function loadOverlayPlate(catId, traitId) {
    if (!traitId) return null;
    const info = overlayInfo(catId, traitId);
    if (!info || info.none || info.baseline || !info.file) return null;
    const key = `${catId}:${traitId}`;
    if (overlayPlateCache.has(key)) return overlayPlateCache.get(key);
    try {
      const img = await loadOne(info.file, false);
      overlayPlateCache.set(key, img);
      return img;
    } catch (_) {
      return null;
    }
  }

  /** Chroma-key composite → transparent cutout (cached per edition). */
  function makeCutout(img, bear) {
    const key = bear.edition;
    if (cutoutCache.has(key)) return cutoutCache.get(key);

    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);

    // Sample corner as seed colour (more accurate than catalog if compression drifts)
    const sample = ctx.getImageData(0, 0, 1, 1).data;
    let br = sample[0], bg = sample[1], bb = sample[2];
    const catalog = bgColorForBear(bear);
    // Prefer catalog for solid XRPL; for patterned use corner sample
    const kind = bgInfo(bear.traits.background)?.kind || "solid";
    if (kind === "solid" && catalog) {
      br = catalog[0]; bg = catalog[1]; bb = catalog[2];
    }

    const id = ctx.getImageData(0, 0, w, h);
    const d = id.data;

    if (kind === "solid") {
      for (let i = 0; i < d.length; i += 4) {
        const dist = Math.max(Math.abs(d[i] - br), Math.abs(d[i + 1] - bg), Math.abs(d[i + 2] - bb));
        if (dist <= KEY_TOL) d[i + 3] = 0;
        else if (dist < KEY_TOL + KEY_SOFT) d[i + 3] = Math.round(255 * (dist - KEY_TOL) / KEY_SOFT);
      }
    } else {
      // Flood-fill from edges for patterned / gradient backgrounds
      const tol = kind === "coded" ? 48 : 40;
      const visited = new Uint8Array(w * h);
      const stack = [];
      for (let x = 0; x < w; x++) { stack.push(x); stack.push((h - 1) * w + x); }
      for (let y = 0; y < h; y++) { stack.push(y * w); stack.push(y * w + (w - 1)); }
      while (stack.length) {
        const idx = stack.pop();
        if (idx < 0 || idx >= w * h || visited[idx]) continue;
        visited[idx] = 1;
        const p = idx * 4;
        if (Math.abs(d[p] - br) > tol || Math.abs(d[p + 1] - bg) > tol || Math.abs(d[p + 2] - bb) > tol) continue;
        d[p + 3] = 0;
        const x = idx % w, y = (idx / w) | 0;
        if (x + 1 < w) stack.push(idx + 1);
        if (x > 0) stack.push(idx - 1);
        if (y + 1 < h) stack.push(idx + w);
        if (y > 0) stack.push(idx - w);
      }
      // Soften fringe: any remaining near-bg pixel with neighbours keyed → reduce alpha
      for (let y = 1; y < h - 1; y++) {
        for (let x = 1; x < w - 1; x++) {
          const i = (y * w + x) * 4;
          if (d[i + 3] === 0) continue;
          const dist = Math.max(Math.abs(d[i] - br), Math.abs(d[i + 1] - bg), Math.abs(d[i + 2] - bb));
          if (dist < tol + 20) {
            let keyed = 0;
            for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
              if (d[((y + dy) * w + (x + dx)) * 4 + 3] === 0) keyed++;
            }
            if (keyed) d[i + 3] = Math.max(0, d[i + 3] - keyed * 60);
          }
        }
      }
    }

    ctx.putImageData(id, 0, 0);
    cutoutCache.set(key, c);
    return c;
  }

  async function resolveBgPlate() {
    const bgT = getSelectedTrait("background");
    if (bgT.custom && bgT.img) return bgT.img;
    const bgId = (!bgT.any && !bgT.custom) ? bgT.id : currentBear?.traits?.background;
    if (!bgId) return null;
    return loadBgPlate(bgId);
  }

  async function resolveOverlays() {
    const out = [];
    for (const catId of OVERLAY_CATS) {
      const t = getSelectedTrait(catId);
      const z = overlayMeta?.layers?.[catId]?.z ?? 5;
      if (t.custom && t.img) {
        out.push({ cat: catId, z, img: t.img });
        continue;
      }
      if (t.any) continue;
      const baseline = overlayBaseline(catId);
      if (t.id === baseline) continue;
      // Native art on base — skip plate
      if (currentBear && currentBear.traits[catId] === t.id) continue;
      const img = await loadOverlayPlate(catId, t.id);
      if (img) out.push({ cat: catId, z, img });
    }
    out.sort((a, b) => a.z - b.z);
    return out;
  }

  async function showMatch(opts = {}) {
    const m = matches[matchPos];
    if (!m && !currentBear) return;
    const token = ++renderToken;
    if (!opts.keepBear && m) currentBear = m.bear;
    if (!currentBear) return;

    if (m) {
      updateBadge(m);
      updateTraitStrip(m);
      markActiveThumb();
    } else {
      updateBadgeForLayer();
      updateTraitStrip({ bear: currentBear, exact: false, wanted: 0, hits: 0 });
    }

    const local = cachedSet.has(currentBear.edition);
    els.loading.textContent = local ? "" : "fetching from IPFS…";
    els.loading.classList.toggle("show", !local);

    try {
      const img = await loadBearImage(currentBear);
      if (token !== renderToken) return;
      currentImg = img;
      currentCutout = makeCutout(img, currentBear);
      currentBgImg = await resolveBgPlate();
      currentOverlays = await resolveOverlays();
      if (token !== renderToken) return;
      els.loading.classList.remove("show");
      draw();
      const nxt = matches[(matchPos + 1) % Math.max(matches.length, 1)];
      if (nxt && nxt.bear !== currentBear) loadBearImage(nxt.bear).catch(() => {});
    } catch (e) {
      if (token !== renderToken) return;
      els.loading.textContent = "IPFS fetch failed — try → for another";
      els.loading.classList.add("show");
    }
  }

  function customBodyOverlays() {
    // Custom uploads for fur (non-overlay categories)
    return BODY_CATEGORIES.map(getSelectedTrait).filter((t) => t.custom && t.img).map((t) => t.img);
  }

  function draw() {
    const ctx = els.ctx;
    const { width: W, height: H } = els.canvas;
    ctx.clearRect(0, 0, W, H);
    if (!currentImg && !currentCutout) { els.archPlaceholder.classList.remove("hidden"); return; }

    const s = Math.min(W, H);
    const x = ((W - s) / 2) | 0;
    const y = ((H - s) / 2) | 0;

    // 1) Background plate
    if (currentBgImg) {
      ctx.drawImage(currentBgImg, x, y, s, s);
    } else if (currentImg) {
      ctx.drawImage(currentImg, x, y, s, s);
    }

    // 2) Bear cutout
    const bearLayer = currentCutout || currentImg;
    if (bearLayer) ctx.drawImage(bearLayer, x, y, s, s);

    // 3) Approx overlay plates in z-order (clothes → mouth → eyes → headwear → mask)
    for (const o of currentOverlays) ctx.drawImage(o.img, x, y, s, s);

    // 4) Custom fur overlays
    for (const o of customBodyOverlays()) ctx.drawImage(o, x, y, s, s);
    els.archPlaceholder.classList.add("hidden");
  }

  // ---------- UI pieces ----------
  function selectedBgId() {
    const t = getSelectedTrait("background");
    if (!t.any && !t.custom) return t.id;
    return currentBear?.traits?.background || null;
  }

  function selectedTraitId(catId) {
    const t = getSelectedTrait(catId);
    if (!t.any && !t.custom) return t.id;
    return currentBear?.traits?.[catId] || null;
  }

  function bgIsRemixed(m) {
    const bgId = selectedBgId();
    return bgId && m?.bear && m.bear.traits.background !== bgId;
  }

  function overlayIsRemixed(catId, m) {
    const t = getSelectedTrait(catId);
    if (t.any || t.custom) return false;
    if (!m?.bear) return false;
    if (m.bear.traits[catId] === t.id) return false;
    const baseline = overlayBaseline(catId);
    if (t.id === baseline) return m.bear.traits[catId] !== baseline;
    return hasOverlayPlate(catId, t.id) || t.id !== m.bear.traits[catId];
  }

  function layerRemixParts(m) {
    const parts = [];
    if (bgIsRemixed(m)) parts.push("bg");
    for (const c of OVERLAY_CATS) {
      if (overlayIsRemixed(c, m)) parts.push(c + "≈");
    }
    return parts;
  }

  function updateBadge(m) {
    const b = m.bear;
    const link = `https://bithomp.com/nft/${b.nftId}`;
    const parts = layerRemixParts(m);
    const remixed = parts.length > 0;
    const approx = parts.some((p) => p.includes("≈"));
    let cls, text;
    if (m.wanted === 0) {
      cls = remixed ? (approx ? "layer-approx" : "layer") : "any";
      text = remixed ? `Layer remix · ${parts.join(" + ")}` : `Browsing all bears · ${matches.length}`;
    } else if (m.exact && !remixed) {
      cls = "exact";
      text = `✓ Minted · ${matches.length} match${matches.length > 1 ? "es" : ""}`;
    } else if (m.exact && remixed) {
      cls = approx ? "layer-approx" : "layer";
      text = `◈ Layer remix · ${parts.join(" + ")}`;
    } else {
      cls = remixed ? (approx ? "layer-approx" : "layer") : "near";
      text = remixed
        ? `◈ Layer + closest body ${m.hits}/${m.wanted}`
        : `✗ Not minted · closest ${m.hits}/${m.wanted} traits`;
    }
    els.matchBadge.className = "match-badge " + cls;
    els.matchBadge.innerHTML = `${text} — <a href="${link}" target="_blank" rel="noopener">${escapeHtml(b.name)}</a> <span class="pos">${matchPos + 1}/${matches.length || 1}</span>`;
    els.matchTitle.textContent = remixed
      ? `Base bear (${parts.join(" + ")} layered separately)`
      : (m.exact && m.wanted ? `Real bears with this mix (${matches.length})` : (m.wanted ? "Closest real bears" : "Real bears"));
  }

  function updateBadgeForLayer() {
    if (!currentBear) return;
    const m = matches[matchPos] || { bear: currentBear, exact: true, wanted: BODY_CATEGORIES.length, hits: BODY_CATEGORIES.length };
    // Ensure matches still references current bear for badge
    updateBadge({ ...m, bear: currentBear });
  }

  function updateTraitStrip(m) {
    els.traitStrip.innerHTML = "";
    for (const catId of manifest.layerOrder) {
      const t = getSelectedTrait(catId);
      const real = m.bear.traits[catId];
      const isLayer = LAYER_CATEGORIES.includes(catId);
      const isApprox = OVERLAY_CATS.includes(catId);
      const remixed = isLayer && !t.any && !t.custom && real !== t.id;
      const off = !isLayer && !t.any && !t.custom && real !== t.id;
      const row = document.createElement("div");
      row.className = "trait-row"
        + (off ? " diff" : "")
        + (remixed ? (isApprox ? " layer layer-approx" : " layer") : "");
      row.dataset.cat = catId;
      let val;
      if (t.custom) val = `${escapeHtml(t.name)} ✦`;
      else if (t.any) val = `<em>Any</em> · ${escapeHtml(traitName(catId, real))}`;
      else val = escapeHtml(t.name);
      if (remixed) {
        val += ` <span class="has">(${isApprox ? "approx layer" : "layer"} · base had ${escapeHtml(traitName(catId, real))})</span>`;
      } else if (off) {
        val += ` <span class="has">(bear: ${escapeHtml(traitName(catId, real))})</span>`;
      }
      if (catId === "background" && !t.any) {
        val += ` <span class="tag">layer</span>`;
      } else if (isApprox && !t.any && !t.custom && (t.id !== overlayBaseline(catId) || remixed)) {
        val += ` <span class="tag approx">approx</span>`;
      }
      row.innerHTML = `<span class="label">${manifest.categories[catId].label}</span><span class="value">${val}</span>`;
      row.title = catId === "background"
        ? "Background is a true layer — cycling keeps this bear and swaps only the backdrop"
        : isApprox
          ? `${manifest.categories[catId].label} uses an approximate derived overlay plate — cycling prefers a stable base body`
          : catId === "fur"
            ? "Fur nearest-matches a minted body (whole-body recolor — not an overlay)"
            : "Double-click to set this category to Any (wildcard)";
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
      b.title = `${m.bear.name}${m.wanted ? ` · body ${m.hits}/${m.wanted}` : ""} — click to load body (keeps layer selections)`;
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = m.bear.name;
      if (cachedSet.has(m.bear.edition) || i < 6) img.src = bearSrc(m.bear);
      else { img.dataset.src = bearSrc(m.bear); b.classList.add("lazy"); }
      const cap = document.createElement("span");
      cap.textContent = "#" + m.bear.edition;
      b.append(img, cap);
      b.addEventListener("click", () => {
        if (img.dataset.src && !img.src) img.src = img.dataset.src;
        // Keep selected layer traits; adopt fur (body) from this bear
        const keep = {};
        for (const c of LAYER_CATEGORIES) keep[c] = getSelectedTrait(c);
        for (const c of BODY_CATEGORIES) {
          const cur = getSelectedTrait(c);
          if (!cur.custom) setTrait(c, m.bear.traits[c]);
        }
        // Also adopt overlay-cat traits that were "Any"
        for (const c of OVERLAY_CATS) {
          if (keep[c].any) setTrait(c, m.bear.traits[c]);
        }
        if (keep.background?.any) setTrait("background", m.bear.traits.background);
        lastCat = null;
        update(m.bear.edition);
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
    const r = Math.random();
    if (r < 0.40) {
      adoptBear(bears[Math.floor(Math.random() * bears.length)]);
      toast("Random real bear");
    } else if (r < 0.55 && currentBear) {
      // Keep bear, randomize background only
      const bgs = getTraits("background");
      selection.background = 1 + Math.floor(Math.random() * (bgs.length - 1));
      lastCat = "background";
      highlightFocus("background");
      cycleLayer("background");
    } else if (r < 0.82 && currentBear) {
      // Keep body, randomize one overlay category
      const cats = OVERLAY_CATS.filter((c) => overlayMeta?.layers?.[c]);
      const catId = cats[Math.floor(Math.random() * cats.length)] || "mask";
      const traits = getTraits(catId);
      selection[catId] = 1 + Math.floor(Math.random() * (traits.length - 1));
      lastCat = catId;
      highlightFocus(catId);
      cycleLayer(catId);
    } else {
      lastCat = null;
      for (const c of manifest.layerOrder) {
        const t = getTraits(c);
        selection[c] = 1 + Math.floor(Math.random() * (t.length - 1));
      }
      update();
      toast(matches[0]?.exact ? "Random mix — body exists!" : "Random mix — closest body + layers");
    }
  }

  function resetAny() {
    for (const c of manifest.layerOrder) selection[c] = 0;
    update();
    toast("All traits = Any · browsing collection");
  }

  // ---------- export ----------
  function exportPng() {
    if (!currentCutout && !currentImg) return toast("Nothing to export yet");
    const out = document.createElement("canvas");
    out.width = out.height = EXPORT_SIZE;
    const ctx = out.getContext("2d");
    if (currentBgImg) ctx.drawImage(currentBgImg, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    else if (currentImg) ctx.drawImage(currentImg, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    const bearLayer = currentCutout || currentImg;
    if (bearLayer) ctx.drawImage(bearLayer, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    for (const o of currentOverlays) ctx.drawImage(o.img, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    for (const o of customBodyOverlays()) ctx.drawImage(o, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    try {
      out.toBlob((blob) => {
        if (!blob) return toast("Export failed");
        const a = document.createElement("a");
        const bgId = selectedBgId() || "bg";
        const bits = OVERLAY_CATS
          .filter((c) => overlayIsRemixed(c, { bear: currentBear }))
          .map((c) => selectedTraitId(c) || c);
        const remix = bits.length ? "-" + bits.join("-") : "";
        const custom = customBodyOverlays().length ? "-custom" : "";
        a.download = `raebyzzuF-${currentBear.edition}-${bgId}${remix}${custom}.png`;
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
        if (hay.includes(q) || cat.label.toLowerCase().includes(q)) {
          hits.push({ kind: "trait", catId, idx, trait: t, name: t.name, label: cat.label });
        }
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
      const layerTag = hit.catId === "background" ? " · layer"
        : OVERLAY_CATS.includes(hit.catId) ? " · approx" : "";
      item.innerHTML = `<span>${hl}${hit.trait?.custom ? " ✦" : ""}${extra}</span><span class="cat">${escapeHtml(hit.label)}${layerTag}</span>`;
      item.addEventListener("click", () => {
        if (hit.kind === "bear") adoptBear(hit.bear);
        else if (LAYER_CATEGORIES.includes(hit.catId)) {
          selection[hit.catId] = hit.idx;
          lastCat = hit.catId;
          highlightFocus(hit.catId);
          cycleLayer(hit.catId);
        } else {
          selection[hit.catId] = hit.idx;
          lastCat = hit.catId;
          highlightFocus(hit.catId);
          update();
        }
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
      opt.textContent = manifest.categories[catId].label
        + (catId === "background" ? " (layer)"
          : OVERLAY_CATS.includes(catId) ? " (approx overlay)"
          : catId === "fur" ? " (body)" : "");
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
    const dataUrl = await new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(r.result);
      r.onerror = rej;
      r.readAsDataURL(file);
    });
    const img = await loadOne(dataUrl, false);
    const id = "custom-" + Date.now().toString(36);

    if (catId === "background") {
      customTraits.push({ categoryId: catId, id, name, img, plate: true });
      selection[catId] = getTraits(catId).length - 1;
      closeUploadModal();
      currentBgImg = img;
      updateBadgeForLayer();
      updateTraitStrip(matches[matchPos] || { bear: currentBear, exact: false, wanted: 0, hits: 0 });
      draw();
      toast(`Added “${name}” as Background layer`);
      return;
    }

    if (OVERLAY_CATS.includes(catId)) {
      customTraits.push({ categoryId: catId, id, name, img, plate: true });
      selection[catId] = getTraits(catId).length - 1;
      closeUploadModal();
      showMatch({ keepBear: true });
      toast(`Added “${name}” as ${manifest.categories[catId].label} overlay`);
      return;
    }

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
