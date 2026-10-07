/**
 * Fuzzybear / raebyzzuF Trait Mixer — trait-file stack edition.
 *
 * Preview = stack WebP/PNG layers from assets/traits/<Category>/ in layerOrder.
 * No base/minted bear composites, no edition IDs, no thumbnail strip.
 * Arrows cycle rare→common among trait FILES only.
 */
(() => {
  "use strict";

  const EXPORT_SIZE = 512;
  const ARROW_CATEGORIES = [
    "background", "fur", "clothes", "mouth", "eyes", "headwear", "mask",
  ];

  let manifest = null;
  const selection = {}; // catId -> trait index in getTraits()
  const customTraits = [];
  let renderToken = 0;
  let lastCat = null;
  /** @type {Map<string, HTMLImageElement|HTMLCanvasElement>} */
  const layerImgs = new Map(); // catId -> loaded image for current selection
  const imgCache = new Map();
  const els = {};

  async function init() {
    cacheDom();
    bindEvents();
    try {
      manifest = await fetch("traits-manifest.json").then((r) => {
        if (!r.ok) throw new Error("manifest " + r.status);
        return r.json();
      });
      buildArrowRows();
      // Default: Background+Fur with files; Eyes=Blue / Mouth=Normal if plates exist;
      // accessories start Empty so you see a bare bear.
      for (const catId of manifest.layerOrder) {
        const traits = getTraits(catId);
        let idx = 0;
        if (catId === "background" || catId === "fur") {
          idx = traits.findIndex((t) => t.file);
        } else if (catId === "eyes") {
          idx = traits.findIndex((t) => t.id === "blue" && t.file);
          if (idx < 0) idx = traits.findIndex((t) => t.empty || t.none);
        } else if (catId === "mouth") {
          idx = traits.findIndex((t) => t.id === "normal" && t.file);
          if (idx < 0) idx = traits.findIndex((t) => t.empty || t.none);
        } else {
          idx = traits.findIndex((t) => t.empty || t.none || t.baseline);
        }
        if (idx < 0) idx = 0;
        selection[catId] = idx;
      }
      const summary = manifest.summary || {};
      const parts = manifest.layerOrder.map((c) => {
        const s = summary[c] || {};
        const label = manifest.categories[c].label;
        return `${label} ${s.files ?? countFiles(c)}`;
      });
      els.catSummary.textContent = parts.join(" · ");
      const totalFiles = manifest.layerOrder.reduce(
        (n, c) => n + (summary[c]?.files ?? countFiles(c)),
        0
      );
      els.traitFileCount.textContent = String(totalFiles);
      await render();
      toast(`${totalFiles} trait files · stack ready`);
    } catch (err) {
      console.error(err);
      toast("Failed to load traits-manifest.json");
      els.archPlaceholder.textContent = "ERR";
      els.statusBadge.textContent = "Load failed";
    }
  }

  function countFiles(catId) {
    return (manifest.categories[catId]?.traits || []).filter((t) => t.file).length;
  }

  function cacheDom() {
    const $ = (id) => document.getElementById(id);
    Object.assign(els, {
      search: $("search"),
      searchResults: $("search-results"),
      btnRandom: $("btn-random"),
      canvas: $("preview-canvas"),
      archPlaceholder: $("arch-placeholder"),
      leftArrows: $("arrows-left"),
      rightArrows: $("arrows-right"),
      traitStrip: $("trait-strip"),
      btnExport: $("btn-export"),
      btnUpload: $("btn-upload"),
      btnReset: $("btn-reset"),
      modal: $("upload-modal"),
      uploadCat: $("upload-category"),
      uploadName: $("upload-name"),
      uploadFile: $("upload-file"),
      uploadConfirm: $("upload-confirm"),
      uploadCancel: $("upload-cancel"),
      toast: $("toast"),
      statusBadge: $("status-badge"),
      loading: $("arch-loading"),
      traitFileCount: $("trait-file-count"),
      catSummary: $("cat-summary"),
    });
    els.ctx = els.canvas.getContext("2d");
  }

  function bindEvents() {
    els.btnRandom.addEventListener("click", randomize);
    els.btnExport.addEventListener("click", exportPng);
    els.btnUpload.addEventListener("click", openUploadModal);
    els.btnReset.addEventListener("click", resetTraits);
    els.uploadCancel.addEventListener("click", closeUploadModal);
    els.uploadConfirm.addEventListener("click", confirmUpload);
    els.modal.addEventListener("click", (e) => {
      if (e.target === els.modal) closeUploadModal();
    });

    els.search.addEventListener("input", onSearch);
    els.search.addEventListener("focus", onSearch);
    els.search.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        els.searchResults.classList.remove("open");
        els.search.blur();
      }
      if (e.key === "Enter") {
        const f = els.searchResults.querySelector("button.search-item");
        if (f) f.click();
      }
    });
    document.addEventListener("click", (e) => {
      if (!els.search.contains(e.target) && !els.searchResults.contains(e.target)) {
        els.searchResults.classList.remove("open");
      }
    });

    let focusCat = 0;
    document.addEventListener("keydown", (e) => {
      if (!manifest || e.target.matches("input, select, textarea")) return;
      const cats = ARROW_CATEGORIES;
      if (e.key === "ArrowUp") {
        e.preventDefault();
        focusCat = (focusCat - 1 + cats.length) % cats.length;
        highlightFocus(cats[focusCat]);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        focusCat = (focusCat + 1) % cats.length;
        highlightFocus(cats[focusCat]);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        cycle(cats[focusCat], -1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        cycle(cats[focusCat], 1);
      } else if (e.key === "?" || e.key === "r") {
        randomize();
      }
    });
  }

  /** Traits for a category: rare→common (ascending count), Empty last, then customs. */
  function getTraits(catId) {
    const base = [...(manifest.categories[catId]?.traits || [])].sort((a, b) => {
      const ea = a.empty || a.none || a.quality === "empty" ? 1 : 0;
      const eb = b.empty || b.none || b.quality === "empty" ? 1 : 0;
      if (ea !== eb) return ea - eb; // Empty last
      const ca = a.count ?? 1e9;
      const cb = b.count ?? 1e9;
      if (ca !== cb) return ca - cb;
      return String(a.name || a.id).localeCompare(String(b.name || b.id));
    });
    const extras = customTraits
      .filter((c) => c.categoryId === catId)
      .map((c) => ({
        id: c.id,
        name: c.name,
        custom: true,
        img: c.img,
        file: null,
        quality: "custom",
      }));
    return [...base, ...extras];
  }

  function getSelectedTrait(catId) {
    return getTraits(catId)[selection[catId] ?? 0] || getTraits(catId)[0];
  }

  function setTrait(catId, traitId) {
    const idx = getTraits(catId).findIndex((t) => t.id === traitId);
    selection[catId] = idx >= 0 ? idx : 0;
  }

  function highlightFocus(catId) {
    els.traitStrip.querySelectorAll(".trait-row").forEach((r) => {
      r.classList.toggle("active", r.dataset.cat === catId);
    });
  }

  function buildArrowRows() {
    els.leftArrows.innerHTML = "";
    els.rightArrows.innerHTML = "";
    for (const catId of ARROW_CATEGORIES) {
      const label = manifest.categories[catId].label;
      for (const [col, dir, chev] of [
        [els.leftArrows, -1, "←"],
        [els.rightArrows, 1, "→"],
      ]) {
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
    if (!traits.length) return;
    let i = selection[catId] ?? 0;
    i = (i + dir + traits.length) % traits.length;
    selection[catId] = i;
    lastCat = catId;
    highlightFocus(catId);
    const t = traits[i];
    const q = t.quality === "solid" ? "" : t.empty || t.baseline || t.none || t.quality === "empty" ? " (empty)" : t.file || t.custom ? " · file" : "";
    toast(`${manifest.categories[catId].label} → ${t.name}${q}`);
    render();
  }

  function loadOne(src) {
    if (imgCache.has(src)) return imgCache.get(src);
    const p = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => {
        imgCache.delete(src);
        reject(new Error("Failed: " + src));
      };
      img.src = src;
    });
    imgCache.set(src, p);
    return p;
  }

  /**
   * Resolve the drawable for a category selection.
   * Baseline / none → null (skip). Custom → in-memory img. Else load file path.
   */
  async function resolveLayer(catId) {
    const t = getSelectedTrait(catId);
    if (!t) return null;
    if (t.custom && t.img) return t.img;
    if (t.none || t.baseline || !t.file) return null;
    try {
      return await loadOne(t.file);
    } catch (_) {
      return null;
    }
  }

  async function render() {
    if (!manifest) return;
    const token = ++renderToken;
    els.loading.textContent = "stacking…";
    els.loading.classList.add("show");

    const order = manifest.layerOrder || ARROW_CATEGORIES;
    const loaded = new Map();
    await Promise.all(
      order.map(async (catId) => {
        const img = await resolveLayer(catId);
        if (token !== renderToken) return;
        if (img) loaded.set(catId, img);
      })
    );
    if (token !== renderToken) return;

    layerImgs.clear();
    for (const [k, v] of loaded) layerImgs.set(k, v);

    els.loading.classList.remove("show");
    draw();
    updateStatus();
    updateTraitStrip();
  }

  function draw() {
    const ctx = els.ctx;
    const { width: W, height: H } = els.canvas;
    // Full clear + source-over so cycling traits never double-draws remnants
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, W, H);
    const order = manifest.layerOrder || ARROW_CATEGORIES;
    let any = false;
    const s = Math.min(W, H);
    const x = ((W - s) / 2) | 0;
    const y = ((H - s) / 2) | 0;

    for (const catId of order) {
      const img = layerImgs.get(catId);
      if (!img) continue;
      // Plates use hard alpha; draw once in layerOrder only
      ctx.drawImage(img, x, y, s, s);
      any = true;
    }
    ctx.restore();

    els.archPlaceholder.classList.toggle("hidden", any);
  }

  function updateStatus() {
    const bits = [];
    for (const catId of manifest.layerOrder) {
      const t = getSelectedTrait(catId);
      if (!t) continue;
      if (t.none || t.baseline) continue;
      bits.push(t.name);
    }
    const nLayers = layerImgs.size;
    els.statusBadge.className = "status-badge stack";
    els.statusBadge.textContent =
      nLayers === 0
        ? "No layers"
        : `◈ ${nLayers} layer${nLayers === 1 ? "" : "s"} · ${bits.slice(0, 4).join(" · ")}${bits.length > 4 ? "…" : ""}`;
  }

  function updateTraitStrip() {
    els.traitStrip.innerHTML = "";
    for (const catId of manifest.layerOrder) {
      const t = getSelectedTrait(catId);
      const row = document.createElement("div");
      const isApprox = t && t.quality === "approx";
      const isSolid = t && t.quality === "solid";
      const isEmpty = t && (t.empty || t.none || t.quality === "empty" || t.baseline || (!t.file && !t.custom));
      row.className =
        "trait-row" +
        (isApprox ? " layer-approx" : "") +
        (isSolid ? " layer" : "") +
        (lastCat === catId ? " active" : "");
      row.dataset.cat = catId;
      let val = escapeHtml(t?.name || "—");
      if (t?.custom) val += " ✦";
      if (isEmpty) val += ` <span class="has">(empty)</span>`;
      else if (isSolid) val += ` <span class="tag">solid</span>`;
      else if (isApprox) val += ` <span class="tag approx">approx</span>`;
      else if (t?.custom) val += ` <span class="tag">custom</span>`;
      row.innerHTML =
        `<span class="label">${manifest.categories[catId].label}</span>` +
        `<span class="value">${val}</span>`;
      row.title = `${manifest.categories[catId].label}: ${t?.name || ""} — ←/→ cycles trait files (rare→common)`;
      row.addEventListener("click", () => highlightFocus(catId));
      row.addEventListener("dblclick", () => {
        // Jump to baseline / first empty if any, else first trait
        const traits = getTraits(catId);
        const bi = traits.findIndex((x) => x.baseline || x.none);
        selection[catId] = bi >= 0 ? bi : 0;
        lastCat = catId;
        render();
      });
      els.traitStrip.appendChild(row);
    }
  }

  function randomize() {
    els.btnRandom.classList.remove("spin");
    void els.btnRandom.offsetWidth;
    els.btnRandom.classList.add("spin");
    for (const catId of manifest.layerOrder) {
      const traits = getTraits(catId);
      if (!traits.length) continue;
      // Prefer file-bearing traits ~80% of the time; allow baseline sometimes
      const withFile = traits
        .map((t, i) => ({ t, i }))
        .filter(({ t }) => t.file || t.custom);
      if (withFile.length && Math.random() < 0.85) {
        selection[catId] = withFile[Math.floor(Math.random() * withFile.length)].i;
      } else {
        selection[catId] = Math.floor(Math.random() * traits.length);
      }
    }
    lastCat = null;
    render();
    toast("Random trait stack");
  }

  function resetTraits() {
    for (const catId of manifest.layerOrder) {
      const traits = getTraits(catId);
      let i = 0;
      if (catId === "background" || catId === "fur") {
        i = traits.findIndex((t) => t.file);
      } else if (catId === "eyes") {
        i = traits.findIndex((t) => t.id === "blue" && t.file);
        if (i < 0) i = traits.findIndex((t) => t.empty || t.none);
      } else if (catId === "mouth") {
        i = traits.findIndex((t) => t.id === "normal" && t.file);
        if (i < 0) i = traits.findIndex((t) => t.empty || t.none);
      } else {
        i = traits.findIndex((t) => t.empty || t.none || t.baseline);
      }
      selection[catId] = i >= 0 ? i : 0;
    }
    lastCat = null;
    render();
    toast("Reset · bare bear + Empty accessories");
  }

  function exportPng() {
    if (!layerImgs.size) return toast("Nothing to export yet");
    const out = document.createElement("canvas");
    out.width = out.height = EXPORT_SIZE;
    const ctx = out.getContext("2d");
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, EXPORT_SIZE, EXPORT_SIZE);
    for (const catId of manifest.layerOrder) {
      const img = layerImgs.get(catId);
      if (img) ctx.drawImage(img, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    }
    try {
      out.toBlob((blob) => {
        if (!blob) return toast("Export failed");
        const a = document.createElement("a");
        const slug = manifest.layerOrder
          .map((c) => {
            const t = getSelectedTrait(c);
            if (!t || t.none || t.baseline) return null;
            return t.id;
          })
          .filter(Boolean)
          .slice(0, 5)
          .join("-");
        a.download = `raebyzzuF-mix-${slug || "stack"}.png`;
        a.href = URL.createObjectURL(blob);
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        toast("PNG downloaded");
      }, "image/png");
    } catch (e) {
      toast("Export failed");
    }
  }

  function onSearch() {
    const q = els.search.value.trim().toLowerCase();
    els.searchResults.innerHTML = "";
    if (!q) return els.searchResults.classList.remove("open");
    const hits = [];
    for (const catId of manifest.layerOrder) {
      const cat = manifest.categories[catId];
      getTraits(catId).forEach((t, idx) => {
        const hay = `${t.name} ${t.onChain || ""} ${t.id}`.toLowerCase();
        if (hay.includes(q) || cat.label.toLowerCase().includes(q)) {
          hits.push({ catId, idx, trait: t, name: t.name, label: cat.label });
        }
      });
    }
    if (!hits.length) {
      els.searchResults.innerHTML =
        `<div class="search-item"><span>No traits match “${escapeHtml(q)}”</span></div>`;
      return els.searchResults.classList.add("open");
    }
    hits.slice(0, 40).forEach((hit) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "search-item";
      const hl = escapeHtml(hit.name).replace(
        new RegExp(`(${escapeRegex(q)})`, "ig"),
        "<mark>$1</mark>"
      );
      const extra = hit.trait.count ? ` <small>×${hit.trait.count}</small>` : "";
      const qtag =
        hit.trait.quality === "solid"
          ? " · solid"
          : hit.trait.quality === "approx"
            ? " · approx"
            : hit.trait.baseline || hit.trait.none
              ? " · empty"
              : hit.trait.custom
                ? " · custom"
                : "";
      item.innerHTML =
        `<span>${hl}${hit.trait.custom ? " ✦" : ""}${extra}</span>` +
        `<span class="cat">${escapeHtml(hit.label)}${qtag}</span>`;
      item.addEventListener("click", () => {
        selection[hit.catId] = hit.idx;
        lastCat = hit.catId;
        highlightFocus(hit.catId);
        render();
        els.search.value = hit.name;
        els.searchResults.classList.remove("open");
        toast(`${hit.label}: ${hit.name}`);
      });
      els.searchResults.appendChild(item);
    });
    els.searchResults.classList.add("open");
  }

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
    const dataUrl = await new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(r.result);
      r.onerror = rej;
      r.readAsDataURL(file);
    });
    const img = await loadOne(dataUrl);
    const id = "custom-" + Date.now().toString(36);
    customTraits.push({ categoryId: catId, id, name, img });
    selection[catId] = getTraits(catId).length - 1;
    closeUploadModal();
    lastCat = catId;
    await render();
    toast(`Added “${name}” → ${manifest.categories[catId].label}`);
  }

  let toastTimer;
  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("show"), 1800);
  }
  const escapeHtml = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  init();
})();
