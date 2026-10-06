#!/usr/bin/env python3
"""Build assets/overlays/<cat>/*.webp + data/overlays.json from composite diffs.

Official trait-layer PNGs were never published. Overlay plates are approximate,
derived by consensus pixel-diff of composites that share a base but differ on
one trait (same method as masks). Suitable for demo layer remix, not exact art.

Categories:
  mask      — vs none (face band)
  headwear  — vs none (crown / hat band)
  clothes   — vs none (torso)
  eyes      — vs blue (eye band)
  mouth     — vs normal (mouth band; prop mouths work best)
Fur is not extracted (whole-body recolor; not an overlay).
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
# roi: (x0, y0, x1, y1) inclusive-exclusive pixel window
# z: draw order (matches collection layerOrder-ish)
CATS = {
    "mask": {
        "baseline": "none",
        "roi": (105, 128, 405, 298),
        "z": 7,
        "n": 15,
        "dist": 38,
        "thresh_frac": 0.28,
        "min_score": 8,
        "min_opaque": 800,
        "require_fur": False,  # historic mask script did not hard-require fur
        "score_weights": {"fur": 5, "headwear": 3, "clothes": 2, "eyes": 2, "mouth": 2},
    },
    "headwear": {
        "baseline": "none",
        "roi": (50, 5, 460, 195),
        "z": 6,
        "n": 12,
        "dist": 32,
        "thresh_frac": 0.35,
        "min_score": 8,
        "min_opaque": 2500,
        "require_fur": True,
        "score_weights": {"eyes": 3, "mouth": 3, "clothes": 3, "mask": 3},
    },
    "clothes": {
        "baseline": "none",
        "roi": (70, 295, 440, 512),
        "z": 3,
        "n": 12,
        "dist": 32,
        "thresh_frac": 0.35,
        "min_score": 8,
        "min_opaque": 1800,
        "require_fur": True,
        "score_weights": {"headwear": 3, "eyes": 3, "mouth": 3, "mask": 3},
    },
    "eyes": {
        "baseline": "blue",
        "roi": (110, 150, 400, 260),
        "z": 5,
        "n": 12,
        "dist": 32,
        "thresh_frac": 0.35,
        "min_score": 8,
        "min_opaque": 1200,
        "require_fur": True,
        "score_weights": {"headwear": 3, "mouth": 3, "clothes": 3, "mask": 3},
    },
    "mouth": {
        "baseline": "normal",
        "roi": (130, 240, 380, 370),
        "z": 4,
        "n": 12,
        "dist": 32,
        "thresh_frac": 0.35,
        "min_score": 8,
        "min_opaque": 1500,
        "require_fur": True,
        "score_weights": {"headwear": 3, "eyes": 3, "clothes": 3, "mask": 3},
    },
}


def load_rgba(ed: int) -> np.ndarray:
    """Return HxWx4 uint8 array (chroma-keyed)."""
    im = Image.open(BEARS_DIR / f"{ed}.webp").convert("RGBA")
    arr = np.asarray(im, dtype=np.uint8).copy()
    br, bg, bb = arr[2, 2, :3].astype(np.int16)
    rgb = arr[:, :, :3].astype(np.int16)
    dist = np.max(np.abs(rgb - np.array([br, bg, bb], dtype=np.int16)), axis=2)
    arr[dist <= 28, 3] = 0
    return arr


def clean_isolated(arr: np.ndarray, min_nbs: int = 3) -> np.ndarray:
    """Drop isolated opaque pixels (neighbourhood filter)."""
    a = arr[:, :, 3] > 0
    # count opaque 8-neighbours via shifts
    nbs = np.zeros(a.shape, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            shifted = np.zeros_like(a)
            y0s, y1s = max(0, dy), a.shape[0] + min(0, dy)
            x0s, x1s = max(0, dx), a.shape[1] + min(0, dx)
            y0d, y1d = max(0, -dy), a.shape[0] + min(0, -dy)
            x0d, x1d = max(0, -dx), a.shape[1] + min(0, -dx)
            shifted[y0d:y1d, x0d:x1d] = a[y0s:y1s, x0s:x1s]
            nbs += shifted.astype(np.uint8)
    keep = a & (nbs >= min_nbs)
    out = arr.copy()
    out[~keep] = 0
    # clear 1px border leftovers
    out[0, :, 3] = 0
    out[-1, :, 3] = 0
    out[:, 0, 3] = 0
    out[:, -1, 3] = 0
    return out


def best_baseline(bears: list, target: dict, cat: str, cfg: dict, require_fur: bool):
    baseline = cfg["baseline"]
    weights = cfg["score_weights"]
    best = None
    for b in bears:
        if b["traits"][cat] != baseline:
            continue
        if require_fur and b["traits"]["fur"] != target["traits"]["fur"]:
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
    if len(donors) < 3 and cfg["require_fur"]:
        relaxed = True
        donors = []
        for d in bears:
            if d["traits"][cat] != trait_id:
                continue
            r = best_baseline(bears, d, cat, cfg, require_fur=False)
            if r and r[0] >= cfg["min_score"]:
                donors.append((r[0], d["edition"], r[1]["edition"]))
        donors.sort(key=lambda t: (-t[0], t[1]))
        donors = donors[: cfg["n"]]
    if len(donors) < 2:
        return None, donors, relaxed

    w = h = 512
    count = np.zeros((h, w), dtype=np.uint16)
    suma = np.zeros((h, w, 3), dtype=np.uint32)

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
        valid = d_a >= 40
        same = (b_a >= 40) & (
            np.max(np.abs(d_rgb - b_rgb), axis=2) <= cfg["dist"]
        )
        diff = valid & ~same
        yy, xx = np.where(diff)
        gy = yy + y0
        gx = xx + x0
        count[gy, gx] += 1
        suma[gy, gx] += d_roi[yy, xx, :3]

    thresh = max(2, int(round(len(donors) * cfg["thresh_frac"])))
    mask = count >= thresh
    out = np.zeros((h, w, 4), dtype=np.uint8)
    if mask.any():
        c = count[mask].astype(np.uint32)
        rgb = (suma[mask] // c[:, None]).astype(np.uint8)
        alpha = np.minimum(
            255, 175 + (80 * c // max(len(donors), 1))
        ).astype(np.uint8)
        out[mask, :3] = rgb
        out[mask, 3] = alpha

    out = clean_isolated(out, 3)
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
            "composites that share a base but differ on one trait. Not official "
            "trait sheets — best-effort plates for layer remix. Fur is not "
            "extracted (whole-body recolor)."
        ),
        "baselines": {c: cfg["baseline"] for c, cfg in CATS.items()},
        "layers": {},
    }

    for cat, cfg in CATS.items():
        out_dir = OUT_ROOT / f"{cat}s" if cat != "clothes" else OUT_ROOT / "clothes"
        # Prefer plural folder names matching existing masks/
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
            }
            print(
                f"  {tid}: {out_path.stat().st_size} B from {len(donors)} pairs "
                f"opaque={opaque} bbox={bbox}{' [relaxed fur]' if relaxed else ''}"
            )

        meta["layers"][cat] = layer

    META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"\nWrote {META_OUT}")
    # summary
    for cat, layer in meta["layers"].items():
        n_ok = sum(1 for t in layer["traits"].values() if t.get("file"))
        n_skip = sum(1 for t in layer["traits"].values() if t.get("skipped"))
        n_base = sum(1 for t in layer["traits"].values() if t.get("baseline"))
        print(f"  {cat}: {n_ok} plates, {n_base} baseline, {n_skip} skipped")


if __name__ == "__main__":
    main()
