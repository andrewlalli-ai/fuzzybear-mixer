#!/usr/bin/env python3
"""Build assets/overlays/<cat>/*.webp + data/overlays.json from composite diffs.

Official trait-layer PNGs were never published. Overlay plates are approximate,
derived by consensus pixel-diff of composites that share a base but differ on
one trait. Suitable for demo layer remix, not exact art.

v2 — anti-ghost: tighter ROIs, stronger same-pixel dist, higher consensus,
hard alpha, morphological open + fringe erode, drop tiny components / low-
confidence fringe so stacked layers don't leave silhouettes of other traits.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BEARS_DIR = ROOT / "assets" / "bears"
OUT_ROOT = ROOT / "assets" / "overlays"
META_OUT = ROOT / "data" / "overlays.json"

# Per-category extraction config.
# baseline: trait id treated as "empty" / default for pairing
# roi: (x0, y0, x1, y1) inclusive-exclusive pixel window — kept tight so
# neighbouring traits (collar in mouth, forehead in eyes, ears-only fringe)
# are less likely to leak into the plate.
CATS = {
    "mask": {
        "baseline": "none",
        "roi": (120, 140, 390, 290),
        "z": 7,
        "n": 14,
        "dist": 46,
        "thresh_frac": 0.42,
        "min_score": 9,
        "min_opaque": 500,
        "require_fur": False,
        "hard_match": ["eyes"],
        "score_weights": {"fur": 5, "headwear": 3, "clothes": 2, "eyes": 3, "mouth": 2},
        "morph_open": 1,
        "erode_fringe": 0,
        "min_component": 40,
        "max_components": 6,
        "alpha_floor": 200,
    },
    "headwear": {
        "baseline": "none",
        "roi": (55, 2, 455, 188),
        "z": 6,
        "n": 12,
        "dist": 44,
        "thresh_frac": 0.42,
        "min_score": 9,
        "min_opaque": 1200,
        "require_fur": True,
        "hard_match": ["mask"],
        "score_weights": {"eyes": 3, "mouth": 3, "clothes": 3, "mask": 4},
        "morph_open": 1,
        "erode_fringe": 0,
        "min_component": 60,
        "max_components": 8,
        "alpha_floor": 200,
    },
    "clothes": {
        "baseline": "none",
        "roi": (75, 308, 435, 512),
        "z": 3,
        "n": 12,
        "dist": 44,
        "thresh_frac": 0.42,
        "min_score": 9,
        "min_opaque": 1200,
        "require_fur": True,
        "hard_match": ["mask"],
        "score_weights": {"headwear": 3, "eyes": 3, "mouth": 3, "mask": 3},
        "morph_open": 1,
        "erode_fringe": 0,
        "min_component": 80,
        "max_components": 6,
        "alpha_floor": 200,
    },
    "eyes": {
        "baseline": "blue",
        "roi": (135, 160, 375, 255),
        "z": 5,
        "n": 14,
        "dist": 36,
        "thresh_frac": 0.42,
        "min_score": 8,
        "min_opaque": 250,
        "require_fur": True,
        "hard_match": ["mask"],
        "score_weights": {"headwear": 3, "mouth": 4, "clothes": 3, "mask": 4},
        "morph_open": 1,
        "erode_fringe": 1,
        "min_component": 25,
        "max_components": 10,
        "alpha_floor": 220,
    },
    "mouth": {
        "baseline": "normal",
        "roi": (145, 250, 365, 360),
        "z": 4,
        "n": 14,
        "dist": 44,
        "thresh_frac": 0.38,
        "min_score": 8,
        "min_opaque": 280,
        "require_fur": True,
        "hard_match": ["mask"],
        "score_weights": {"headwear": 3, "eyes": 4, "clothes": 3, "mask": 4},
        "morph_open": 1,
        "erode_fringe": 0,
        "min_component": 25,
        "max_components": 10,
        "alpha_floor": 200,
    },
}



def load_rgba(ed: int) -> np.ndarray:
    """Return HxWx4 uint8 array with solid-ish background keyed out."""
    im = Image.open(BEARS_DIR / f"{ed}.webp").convert("RGBA")
    arr = np.asarray(im, dtype=np.uint8).copy()
    br, bg, bb = int(arr[0, 0, 0]), int(arr[0, 0, 1]), int(arr[0, 0, 2])
    rgb = arr[:, :, :3].astype(np.int16)
    dist = np.max(np.abs(rgb - np.array([br, bg, bb], dtype=np.int16)), axis=2)
    arr[dist <= 28, 3] = 0
    soft = (dist > 28) & (dist < 40)
    arr[soft, 3] = ((dist[soft] - 28) * (255 / 12)).astype(np.uint8)
    return arr


def _shift_or(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(a)
    y0s, y1s = max(0, dy), a.shape[0] + min(0, dy)
    x0s, x1s = max(0, dx), a.shape[1] + min(0, dx)
    y0d, y1d = max(0, -dy), a.shape[0] + min(0, -dy)
    x0d, x1d = max(0, -dx), a.shape[1] + min(0, -dx)
    out[y0d:y1d, x0d:x1d] = a[y0s:y1s, x0s:x1s]
    return out


def binary_erode(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    for _ in range(iterations):
        acc = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                acc &= _shift_or(m, dy, dx)
        m = acc
    return m


def binary_dilate(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    for _ in range(iterations):
        acc = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                acc |= _shift_or(m, dy, dx)
        m = acc
    return m


def binary_open(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    return binary_dilate(binary_erode(mask, iterations), iterations)


def label_components(mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """4-connected component labels. Returns label map + sizes (index 0 unused)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    sizes: list[int] = [0]
    cur = 0
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or labels[y, x]:
                continue
            cur += 1
            stack = [(y, x)]
            labels[y, x] = cur
            n = 0
            while stack:
                cy, cx = stack.pop()
                n += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = cur
                        stack.append((ny, nx))
            sizes.append(n)
    return labels, sizes


def keep_largest_components(
    mask: np.ndarray, min_size: int = 60, max_components: int = 8
) -> np.ndarray:
    """Drop tiny islands. Uses a fast skip when the mask is a single solid body."""
    if not mask.any():
        return mask
    # Fast path: morphological open already killed most speckles; only run CC
    # when there are likely multiple blobs (low fill relative to bbox).
    ys, xs = np.where(mask)
    area = int(mask.sum())
    bbox_area = (int(ys.max()) - int(ys.min()) + 1) * (int(xs.max()) - int(xs.min()) + 1)
    if area >= min_size and area > 0.55 * max(bbox_area, 1):
        return mask  # one dominant blob
    labels, sizes = label_components(mask)
    if len(sizes) <= 1:
        return mask
    ranked = sorted(range(1, len(sizes)), key=lambda i: sizes[i], reverse=True)
    keep_ids = {i for i in ranked[:max_components] if sizes[i] >= min_size}
    if not keep_ids and ranked:
        keep_ids = {ranked[0]}
    out = np.zeros_like(mask)
    for i in keep_ids:
        out |= labels == i
    return out


def clean_plate(arr: np.ndarray, cfg: dict) -> np.ndarray:
    """Morphological cleanup + mostly-hard alpha + drop low-confidence fringe.

    Core pixels get alpha 255. A 1px dilated ring gets alpha ~160 so edges
    aren't stair-stepped while still rejecting soft ghost silhouettes.
    """
    alpha_floor = int(cfg.get("alpha_floor", 200))
    keep = arr[:, :, 3] >= alpha_floor
    nbs = np.zeros(keep.shape, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nbs += _shift_or(keep, dy, dx).astype(np.uint8)
    keep = keep & (nbs >= 3)

    open_n = int(cfg.get("morph_open", 1))
    if open_n:
        keep = binary_open(keep, open_n)
    erode_n = int(cfg.get("erode_fringe", 0))
    if erode_n:
        keep = binary_erode(keep, erode_n)

    keep = keep_largest_components(
        keep,
        min_size=int(cfg.get("min_component", 60)),
        max_components=int(cfg.get("max_components", 8)),
    )

    out = np.zeros_like(arr)
    out[keep, :3] = arr[keep, :3]
    out[keep, 3] = 255  # hard alpha only — soft AA rings read as grey ghost fringe
    out[0, :, 3] = 0
    out[-1, :, 3] = 0
    out[:, 0, 3] = 0
    out[:, -1, 3] = 0
    return out


def best_baseline(bears: list, target: dict, cat: str, cfg: dict, require_fur: bool):
    baseline = cfg["baseline"]
    weights = cfg["score_weights"]
    hard = cfg.get("hard_match") or []
    best = None
    for b in bears:
        if b["traits"][cat] != baseline:
            continue
        if require_fur and b["traits"]["fur"] != target["traits"]["fur"]:
            continue
        # Hard constraints: must match listed cats (reduces cross-trait bleed)
        skip = False
        for c in hard:
            if c == cat:
                continue
            if b["traits"].get(c) != target["traits"].get(c):
                skip = True
                break
        if skip:
            continue
        score = 5 if (b["traits"]["fur"] == target["traits"]["fur"]) else 0
        for c, w in weights.items():
            if c == cat:
                continue
            if b["traits"].get(c) == target["traits"].get(c):
                score += w
        if best is None or score > best[0]:
            best = (score, b)
    return best


def extract_consensus(bears: list, cat: str, trait_id: str, cfg: dict, cache: dict):
    x0, y0, x1, y1 = cfg["roi"]
    donors = []
    for d in bears:
        if d["traits"][cat] != trait_id:
            continue
        r = best_baseline(bears, d, cat, cfg, require_fur=cfg["require_fur"])
        if r and r[0] >= cfg["min_score"]:
            donors.append((r[0], d["edition"], r[1]["edition"]))
    donors.sort(key=lambda t: (-t[0], t[1]))
    donors = donors[: cfg["n"]]
    relaxed = False
    # Relax hard_match then fur if too few donors
    if len(donors) < 3:
        relaxed = True
        donors = []
        soft_cfg = dict(cfg)
        soft_cfg["hard_match"] = []
        for d in bears:
            if d["traits"][cat] != trait_id:
                continue
            r = best_baseline(
                bears, d, cat, soft_cfg, require_fur=cfg["require_fur"]
            )
            if r and r[0] >= max(6, cfg["min_score"] - 3):
                donors.append((r[0], d["edition"], r[1]["edition"]))
        donors.sort(key=lambda t: (-t[0], t[1]))
        donors = donors[: cfg["n"]]
    if len(donors) < 3 and cfg["require_fur"]:
        relaxed = True
        donors = []
        soft_cfg = dict(cfg)
        soft_cfg["hard_match"] = []
        for d in bears:
            if d["traits"][cat] != trait_id:
                continue
            r = best_baseline(bears, d, cat, soft_cfg, require_fur=False)
            if r and r[0] >= max(6, cfg["min_score"] - 3):
                donors.append((r[0], d["edition"], r[1]["edition"]))
        donors.sort(key=lambda t: (-t[0], t[1]))
        donors = donors[: cfg["n"]]
    if len(donors) < 2:
        return None, donors, relaxed

    w = h = 512
    count = np.zeros((h, w), dtype=np.uint16)
    suma = np.zeros((h, w, 3), dtype=np.uint32)
    # Track per-pixel colour range across donors for variance gate
    minc = np.full((h, w, 3), 255, dtype=np.uint8)
    maxc = np.zeros((h, w, 3), dtype=np.uint8)

    for _sc, de, be in donors:
        if de not in cache:
            cache[de] = load_rgba(de)
        if be not in cache:
            cache[be] = load_rgba(be)
        da = cache[de]
        ba = cache[be]
        d_roi = da[y0:y1, x0:x1]
        b_roi = ba[y0:y1, x0:x1]
        d_a = d_roi[:, :, 3]
        b_a = b_roi[:, :, 3]
        d_rgb = d_roi[:, :, :3].astype(np.int16)
        b_rgb = b_roi[:, :, :3].astype(np.int16)
        valid = d_a >= 50
        same = (b_a >= 50) & (
            np.max(np.abs(d_rgb - b_rgb), axis=2) <= cfg["dist"]
        )
        diff = valid & ~same
        yy, xx = np.where(diff)
        gy = yy + y0
        gx = xx + x0
        count[gy, gx] += 1
        rgb = d_roi[yy, xx, :3]
        suma[gy, gx] += rgb
        # update min/max for variance
        cur_min = minc[gy, gx]
        cur_max = maxc[gy, gx]
        minc[gy, gx] = np.minimum(cur_min, rgb)
        maxc[gy, gx] = np.maximum(cur_max, rgb)

    thresh = max(2, int(round(len(donors) * cfg["thresh_frac"])))
    mask = count >= thresh
    # Drop high colour-variance pixels (other co-occurring traits)
    if mask.any():
        spread = np.max(maxc.astype(np.int16) - minc.astype(np.int16), axis=2)
        # Only apply variance where we saw enough samples
        mask &= (count < 2) | (spread <= 70)

    out = np.zeros((h, w, 4), dtype=np.uint8)
    if mask.any():
        c = count[mask].astype(np.uint32)
        rgb = (suma[mask] // c[:, None]).astype(np.uint8)
        # Provisional alpha from consensus strength; clean_plate hardens it
        alpha = np.where(
            c >= thresh,
            255,
            np.minimum(255, 160 + (95 * c // max(len(donors), 1))),
        ).astype(np.uint8)
        out[mask, :3] = rgb
        out[mask, 3] = alpha

    out = clean_plate(out, cfg)
    return out, donors, relaxed


def opaque_count(arr: np.ndarray) -> int:
    return int(np.count_nonzero(arr[:, :, 3] > 40))


def main() -> None:
    bears = json.loads((ROOT / "data" / "bears.json").read_text())["bears"]
    manifest = json.loads((ROOT / "traits-manifest.json").read_text())
    cache: dict[int, np.ndarray] = {}

    meta = {
        "size": 512,
        "note": (
            "Approximate overlay plates derived by consensus pixel-diff of "
            "composites that share a base but differ on one trait. Anti-ghost "
            "v2: tight ROIs, hard alpha, morph cleanup, variance gate. Not "
            "official trait sheets. Fur is not extracted here."
        ),
        "baselines": {c: cfg["baseline"] for c, cfg in CATS.items()},
        "layers": {},
        "antiGhost": True,
    }

    for cat, cfg in CATS.items():
        folder = {
            "mask": "masks",
            "headwear": "headwear",
            "clothes": "clothes",
            "eyes": "eyes",
            "mouth": "mouths",
        }[cat]
        out_dir = OUT_ROOT / folder
        out_dir.mkdir(parents=True, exist_ok=True)

        layer = {
            "kind": "overlay",
            "z": cfg["z"],
            "trueLayer": True,
            "approx": True,
            "baseline": cfg["baseline"],
            "roi": list(cfg["roi"]),
            "traits": {},
        }

        traits = manifest["categories"][cat]["traits"]
        print(f"\n=== {cat} (baseline={cfg['baseline']}, roi={cfg['roi']}) ===")
        for trait in traits:
            tid = trait["id"]
            if tid == cfg["baseline"] or trait.get("none"):
                layer["traits"][tid] = {
                    "id": tid,
                    "name": trait["name"],
                    "file": None,
                    "none": tid == "none" or bool(trait.get("none")),
                    "baseline": True,
                    "count": trait["count"],
                }
                print(f"  {tid}: baseline (no plate)")
                continue

            arr, donors, relaxed = extract_consensus(bears, cat, tid, cfg, cache)
            if arr is None:
                layer["traits"][tid] = {
                    "id": tid,
                    "name": trait["name"],
                    "file": None,
                    "none": False,
                    "count": trait["count"],
                    "skipped": "insufficient donors",
                }
                print(f"  {tid}: SKIP insufficient donors")
                continue

            opaque = opaque_count(arr)
            if opaque < cfg["min_opaque"]:
                layer["traits"][tid] = {
                    "id": tid,
                    "name": trait["name"],
                    "file": None,
                    "none": False,
                    "count": trait["count"],
                    "skipped": f"low opaque ({opaque})",
                    "derivedFrom": len(donors),
                }
                print(f"  {tid}: SKIP opaque={opaque} < {cfg['min_opaque']}")
                continue

            rel = f"assets/overlays/{folder}/{tid}.webp"
            out_path = ROOT / rel
            Image.fromarray(arr, "RGBA").save(out_path, "WEBP", quality=92, method=4)
            bbox = Image.fromarray(arr, "RGBA").getbbox()
            layer["traits"][tid] = {
                "id": tid,
                "name": trait["name"],
                "file": rel,
                "none": False,
                "count": trait["count"],
                "derivedFrom": len(donors),
                "opaque": opaque,
                "approx": True,
                "relaxedFur": relaxed,
                "bbox": list(bbox) if bbox else None,
            }
            print(
                f"  {tid}: {out_path.stat().st_size} B from {len(donors)} pairs "
                f"opaque={opaque} bbox={bbox}{' [relaxed]' if relaxed else ''}"
            )

        # Remove stale overlay files not produced this run
        wanted = {Path(t["file"]).name for t in layer["traits"].values() if t.get("file")}
        for oldf in out_dir.glob("*.webp"):
            if oldf.name not in wanted:
                oldf.unlink()
                print(f"  removed stale {oldf.name}")

        meta["layers"][cat] = layer

    META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"\nWrote {META_OUT}")
    for cat, layer in meta["layers"].items():
        n_ok = sum(1 for t in layer["traits"].values() if t.get("file"))
        n_skip = sum(1 for t in layer["traits"].values() if t.get("skipped"))
        n_base = sum(1 for t in layer["traits"].values() if t.get("baseline"))
        print(f"  {cat}: {n_ok} plates, {n_base} baseline, {n_skip} skipped")


if __name__ == "__main__":
    main()
