#!/usr/bin/env python3
"""Build assets/traits/<Category>/*.webp + traits-manifest.json (file paths only).

Assembles separable trait plates so the UI can stack layers with zero base-bear
references. Official trait sheets were never published — plates are derived:

  Background — solid XRPL colours (exact) + reconstructed coded/vignette
  Fur        — consensus chroma-key cutouts across same-fur donors (approx)
  Clothes / Mouth / Eyes / Headwear / Mask — consensus pixel-diff overlays (approx)

Baselines (none / blue / normal) get no file (transparent / skip in stack).
"""
from __future__ import annotations

import json
import math
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BEARS_DIR = ROOT / "assets" / "bears"
TRAITS_ROOT = ROOT / "assets" / "traits"
MANIFEST_OUT = ROOT / "traits-manifest.json"
OVERLAYS_META = ROOT / "data" / "overlays.json"
BACKGROUNDS_META = ROOT / "data" / "backgrounds.json"

# Display folder name per category id
FOLDER = {
    "background": "Background",
    "fur": "Fur",
    "clothes": "Clothes",
    "mouth": "Mouth",
    "eyes": "Eyes",
    "headwear": "Headwear",
    "mask": "Mask",
}

LAYER_ORDER = ["background", "fur", "clothes", "mouth", "eyes", "headwear", "mask"]

# Overlay cats already built by build_overlays.py — map to source folders
OVERLAY_SRC = {
    "mask": ROOT / "assets" / "overlays" / "masks",
    "headwear": ROOT / "assets" / "overlays" / "headwear",
    "clothes": ROOT / "assets" / "overlays" / "clothes",
    "eyes": ROOT / "assets" / "overlays" / "eyes",
    "mouth": ROOT / "assets" / "overlays" / "mouths",
}

BASELINES = {
    "mask": "none",
    "headwear": "none",
    "clothes": "none",
    "eyes": "blue",
    "mouth": "normal",
}

SOLID_BGS = {
    "xrpl-orange", "xrpl-magenta", "xrpl-yellow", "xrpl-red-purple",
    "xrpl-blue-purple", "xrpl-green", "xrpl-grey", "xrpl-blue",
}


def load_rgba(ed: int) -> np.ndarray:
    im = Image.open(BEARS_DIR / f"{ed}.webp").convert("RGBA")
    return np.asarray(im, dtype=np.uint8).copy()


def chroma_key(arr: np.ndarray, kind: str = "solid") -> np.ndarray:
    """Make background transparent. kind: solid | coded | gradient."""
    out = arr.copy()
    br, bg, bb = int(out[2, 2, 0]), int(out[2, 2, 1]), int(out[2, 2, 2])
    # Prefer top-left corner (less bear fringe)
    br, bg, bb = int(out[0, 0, 0]), int(out[0, 0, 1]), int(out[0, 0, 2])
    h, w = out.shape[:2]
    rgb = out[:, :, :3].astype(np.int16)
    seed = np.array([br, bg, bb], dtype=np.int16)

    if kind == "solid":
        dist = np.max(np.abs(rgb - seed), axis=2)
        out[dist <= 30, 3] = 0
        soft = (dist > 30) & (dist < 46)
        out[soft, 3] = ((dist[soft] - 30) * (255 / 16)).astype(np.uint8)
        return out

    # Flood-fill from edges for patterned / vignette
    tol = 48 if kind == "coded" else 40
    visited = np.zeros((h, w), dtype=np.uint8)
    stack = []
    for x in range(w):
        stack.append((0, x))
        stack.append((h - 1, x))
    for y in range(h):
        stack.append((y, 0))
        stack.append((y, w - 1))
    while stack:
        y, x = stack.pop()
        if y < 0 or y >= h or x < 0 or x >= w or visited[y, x]:
            continue
        visited[y, x] = 1
        if abs(int(out[y, x, 0]) - br) > tol or abs(int(out[y, x, 1]) - bg) > tol or abs(int(out[y, x, 2]) - bb) > tol:
            continue
        out[y, x, 3] = 0
        stack.extend([(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)])
    return out


def clean_isolated(arr: np.ndarray, min_nbs: int = 2) -> np.ndarray:
    a = arr[:, :, 3] > 0
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
    out[0, :, 3] = 0
    out[-1, :, 3] = 0
    out[:, 0, 3] = 0
    out[:, -1, 3] = 0
    return out


def fur_donor_score(t: dict) -> int:
    s = 0
    if t["headwear"] == "none":
        s += 12
    if t["mask"] == "none":
        s += 12
    if t["clothes"] == "none":
        s += 8
    elif t["clothes"] == "snappy-casual":
        s += 3  # relatively minimal
    if t["eyes"] == "blue":
        s += 6
    if t["mouth"] == "normal":
        s += 6
    if t["background"] in SOLID_BGS:
        s += 5
    elif t["background"] == "vignette":
        s += 1
    return s


def bg_kind(bg_id: str) -> str:
    if bg_id == "coded":
        return "coded"
    if bg_id == "vignette":
        return "gradient"
    return "solid"


def extract_fur_consensus(bears: list, fur_id: str, n: int = 14, thresh_frac: float = 0.40) -> tuple[np.ndarray | None, list]:
    """Consensus body cutout for one fur — keeps pixels shared across many donors."""
    donors = [b for b in bears if b["traits"]["fur"] == fur_id]
    donors.sort(key=lambda b: (-fur_donor_score(b["traits"]), b["edition"]))
    # Prefer variety in accessories so unique hats/clothes fall out of consensus
    picked = []
    seen_sig = set()
    for b in donors:
        t = b["traits"]
        if not (BEARS_DIR / f"{b['edition']}.webp").exists():
            continue
        sig = (t["clothes"], t["headwear"], t["mask"], t["eyes"], t["mouth"])
        # Always take high-score uniques first, then fill
        if sig in seen_sig and len(picked) >= 4:
            continue
        seen_sig.add(sig)
        picked.append(b)
        if len(picked) >= n:
            break
    # Top up if needed
    if len(picked) < min(6, len(donors)):
        for b in donors:
            if b in picked:
                continue
            if (BEARS_DIR / f"{b['edition']}.webp").exists():
                picked.append(b)
            if len(picked) >= n:
                break

    if len(picked) < 2:
        # Single donor fallback
        if not picked and donors:
            for b in donors:
                if (BEARS_DIR / f"{b['edition']}.webp").exists():
                    picked = [b]
                    break
        if not picked:
            return None, []
        arr = chroma_key(load_rgba(picked[0]["edition"]), bg_kind(picked[0]["traits"]["background"]))
        return clean_isolated(arr, 2), picked

    h = w = 512
    count = np.zeros((h, w), dtype=np.uint16)
    suma = np.zeros((h, w, 3), dtype=np.uint32)

    for b in picked:
        raw = load_rgba(b["edition"])
        cut = chroma_key(raw, bg_kind(b["traits"]["background"]))
        opaque = cut[:, :, 3] >= 40
        count += opaque.astype(np.uint16)
        suma[opaque] += cut[:, :, :3][opaque]

    thresh = max(2, int(round(len(picked) * thresh_frac)))
    mask = count >= thresh
    out = np.zeros((h, w, 4), dtype=np.uint8)
    if mask.any():
        c = count[mask].astype(np.uint32)
        out[mask, :3] = (suma[mask] // c[:, None]).astype(np.uint8)
        # Higher consensus → more opaque
        out[mask, 3] = np.minimum(255, 160 + (95 * c // max(len(picked), 1))).astype(np.uint8)

    out = clean_isolated(out, 2)
    return out, picked


def sample_edge_color(path: Path, n: int = 16) -> tuple[int, int, int]:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    samples = []
    step = max(1, w // n)
    for x in range(0, w, step):
        samples.append(im.getpixel((x, 2))[:3])
        samples.append(im.getpixel((x, h - 3))[:3])
    corner = im.getpixel((0, 0))[:3]
    close = [s for s in samples if sum(abs(s[i] - corner[i]) for i in range(3)) < 40] or samples
    return tuple(sum(c[i] for c in close) // len(close) for i in range(3))  # type: ignore


def solid_plate(color: tuple[int, int, int], size=(512, 512)) -> Image.Image:
    return Image.new("RGBA", size, color + (255,))


def vignette_plate(size=(512, 512)) -> Image.Image:
    outer, inner = (56, 26, 8), (10, 12, 16)
    im = Image.new("RGBA", size)
    px = im.load()
    cx, cy = size[0] // 2, int(size[1] * 0.52)
    maxd = math.sqrt((size[0] / 2) ** 2 + (size[1] * 0.55) ** 2)
    for y in range(size[1]):
        for x in range(size[0]):
            t = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / maxd
            t = max(0.0, min(1.0, t))
            t = t * t * (3 - 2 * t)
            r = int(inner[0] * (1 - t) + outer[0] * t)
            g = int(inner[1] * (1 - t) + outer[1] * t)
            b = int(inner[2] * (1 - t) + outer[2] * t)
            px[x, y] = (r, g, b, 255)
    return im


def coded_plate(bears_by_bg: dict, size=(512, 512)) -> Image.Image:
    src = None
    for b in bears_by_bg.get("coded", []):
        p = BEARS_DIR / f"{b['edition']}.webp"
        if p.exists():
            src = p
            break
    if not src:
        return Image.new("RGBA", size, (2, 2, 2, 255))
    im = Image.open(src).convert("RGBA")
    band_h = 40
    bands = [im.crop((0, y0, 512, y0 + band_h)) for y0 in range(0, 160, band_h)]
    plate = Image.new("RGBA", size, (2, 2, 2, 255))
    y = i = 0
    while y < size[1]:
        b = bands[i % len(bands)]
        shift = (i * 71) % size[0]
        plate.paste(b, (-shift, y))
        plate.paste(b, (size[0] - shift, y))
        y += band_h - 2
        i += 1
    return plate


def opaque_count(arr: np.ndarray) -> int:
    return int(np.count_nonzero(arr[:, :, 3] > 40))


def ensure_overlays_built() -> dict:
    """Use existing overlays.json; rebuild if missing."""
    if not OVERLAYS_META.exists() or not (ROOT / "assets" / "overlays" / "clothes").exists():
        print("Overlays missing — run build_overlays.py first")
        raise SystemExit(1)
    return json.loads(OVERLAYS_META.read_text())


def build_backgrounds(bears: list, manifest: dict) -> dict:
    out_dir = TRAITS_ROOT / "Background"
    out_dir.mkdir(parents=True, exist_ok=True)
    by_bg: dict[str, list] = defaultdict(list)
    for b in bears:
        by_bg[b["traits"]["background"]].append(b)

    # Prefer existing plates if present
    old = {}
    if BACKGROUNDS_META.exists():
        old = json.loads(BACKGROUNDS_META.read_text()).get("backgrounds", {})

    result = {}
    for trait in manifest["categories"]["background"]["traits"]:
        tid = trait["id"]
        dest = out_dir / f"{tid}.webp"
        rel = f"assets/traits/Background/{tid}.webp"

        # Copy from old backgrounds folder if present
        legacy = ROOT / "assets" / "backgrounds" / f"{tid}.webp"
        if legacy.exists() and not dest.exists():
            shutil.copy2(legacy, dest)
        elif legacy.exists():
            shutil.copy2(legacy, dest)

        if not dest.exists():
            path = None
            for b in by_bg.get(tid, []):
                p = BEARS_DIR / f"{b['edition']}.webp"
                if p.exists():
                    path = p
                    break
            if tid == "vignette":
                plate, color, kind = vignette_plate(), (56, 26, 8), "gradient"
            elif tid == "coded":
                plate, color, kind = coded_plate(by_bg), (2, 2, 2), "pattern"
            else:
                color = sample_edge_color(path) if path else (128, 128, 128)
                plate, kind = solid_plate(color), "solid"
            plate.save(dest, "WEBP", quality=90)
        else:
            info = old.get(tid, {})
            color = tuple(info.get("color") or [128, 128, 128])
            kind = info.get("kind") or ("solid" if tid.startswith("xrpl") else "approx")

        quality = "solid" if kind == "solid" else "approx"
        result[tid] = {
            "id": tid,
            "name": trait["name"],
            "onChain": trait.get("onChain"),
            "count": trait["count"],
            "none": False,
            "file": rel,
            "quality": quality,
            "kind": kind,
            "color": list(color) if isinstance(color, (list, tuple)) else color,
        }
        print(f"  Background/{tid}: {quality} ({dest.stat().st_size} B)")
    return result


def build_fur(bears: list, manifest: dict) -> dict:
    out_dir = TRAITS_ROOT / "Fur"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for trait in manifest["categories"]["fur"]["traits"]:
        tid = trait["id"]
        print(f"  Fur/{tid}: extracting…", flush=True)
        arr, donors = extract_fur_consensus(bears, tid)
        if arr is None or opaque_count(arr) < 8000:
            print(f"    SKIP opaque={opaque_count(arr) if arr is not None else 0}")
            result[tid] = {
                "id": tid,
                "name": trait["name"],
                "onChain": trait.get("onChain"),
                "count": trait["count"],
                "none": False,
                "file": None,
                "quality": "missing",
                "skipped": "insufficient cutout",
            }
            continue
        rel = f"assets/traits/Fur/{tid}.webp"
        dest = ROOT / rel
        Image.fromarray(arr, "RGBA").save(dest, "WEBP", quality=92, method=4)
        result[tid] = {
            "id": tid,
            "name": trait["name"],
            "onChain": trait.get("onChain"),
            "count": trait["count"],
            "none": False,
            "file": rel,
            "quality": "approx",
            "derivedFrom": len(donors),
            "opaque": opaque_count(arr),
            "donors": [d["edition"] for d in donors[:8]],
        }
        print(f"    ok opaque={opaque_count(arr)} from {len(donors)} donors → {dest.stat().st_size} B")
    return result


def copy_overlay_cat(cat: str, manifest: dict, overlay_meta: dict) -> dict:
    folder = FOLDER[cat]
    out_dir = TRAITS_ROOT / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    src_dir = OVERLAY_SRC[cat]
    layer = overlay_meta["layers"][cat]
    baseline = BASELINES[cat]
    result = {}
    for trait in manifest["categories"][cat]["traits"]:
        tid = trait["id"]
        info = layer["traits"].get(tid, {})
        is_none = bool(trait.get("none")) or tid == "none" or tid == baseline
        if is_none or info.get("baseline") or info.get("none"):
            result[tid] = {
                "id": tid,
                "name": trait["name"],
                "onChain": trait.get("onChain"),
                "count": trait["count"],
                "none": True if (tid == "none" or trait.get("none")) else False,
                "baseline": tid == baseline,
                "file": None,
                "quality": "baseline",
            }
            print(f"  {folder}/{tid}: baseline (no plate)")
            continue
        src = src_dir / f"{tid}.webp"
        if not src.exists() or not info.get("file"):
            result[tid] = {
                "id": tid,
                "name": trait["name"],
                "onChain": trait.get("onChain"),
                "count": trait["count"],
                "none": False,
                "file": None,
                "quality": "missing",
                "skipped": info.get("skipped", "no source plate"),
            }
            print(f"  {folder}/{tid}: MISSING")
            continue
        dest = out_dir / f"{tid}.webp"
        shutil.copy2(src, dest)
        rel = f"assets/traits/{folder}/{tid}.webp"
        result[tid] = {
            "id": tid,
            "name": trait["name"],
            "onChain": trait.get("onChain"),
            "count": trait["count"],
            "none": False,
            "file": rel,
            "quality": "approx",
            "derivedFrom": info.get("derivedFrom"),
            "opaque": info.get("opaque"),
        }
        print(f"  {folder}/{tid}: approx ({dest.stat().st_size} B)")
    return result


def main() -> None:
    bears = json.loads((ROOT / "data" / "bears.json").read_text())["bears"]
    old_manifest = json.loads(MANIFEST_OUT.read_text())
    overlay_meta = ensure_overlays_built()

    print("=== Background ===")
    bg_traits = build_backgrounds(bears, old_manifest)
    print("=== Fur ===")
    fur_traits = build_fur(bears, old_manifest)
    overlay_traits = {}
    for cat in ["clothes", "mouth", "eyes", "headwear", "mask"]:
        print(f"=== {FOLDER[cat]} ===")
        overlay_traits[cat] = copy_overlay_cat(cat, old_manifest, overlay_meta)

    categories = {}
    all_maps = {
        "background": bg_traits,
        "fur": fur_traits,
        **overlay_traits,
    }
    for i, cat in enumerate(LAYER_ORDER):
        traits_map = all_maps[cat]
        # Preserve rare→common order from old manifest
        ordered = []
        for t in old_manifest["categories"][cat]["traits"]:
            entry = traits_map[t["id"]]
            ordered.append(entry)
        categories[cat] = {
            "id": cat,
            "label": FOLDER[cat],
            "folder": FOLDER[cat],
            "zIndex": i,
            "traits": ordered,
        }

    # Counts
    summary = {}
    for cat, info in categories.items():
        n_files = sum(1 for t in info["traits"] if t.get("file"))
        n_base = sum(1 for t in info["traits"] if t.get("baseline") or (t.get("none") and not t.get("file")))
        n_solid = sum(1 for t in info["traits"] if t.get("quality") == "solid")
        n_approx = sum(1 for t in info["traits"] if t.get("quality") == "approx")
        summary[cat] = {"files": n_files, "baseline": n_base, "solid": n_solid, "approx": n_approx}

    manifest = {
        "collection": old_manifest.get("collection", "sraebyzzuf"),
        "displayName": old_manifest.get("displayName", "raebyzzuF (Fuzzybear)"),
        "issuer": old_manifest.get("issuer"),
        "description": (
            "Trait-file mixer: preview stacks PNG/WebP layers from assets/traits/ only. "
            "No base/minted bear composites in the UI. Background solids are exact; "
            "Fur / Clothes / Mouth / Eyes / Headwear / Mask plates are approximate "
            "consensus cutouts. Traits listed most-rare → least-rare (ascending count)."
        ),
        "canvasSize": 512,
        "layerOrder": LAYER_ORDER,
        "mode": "trait-file-stack",
        "baselines": BASELINES,
        "qualityNote": {
            "solid": "Exact extracted colour / plate",
            "approx": "Consensus pixel-diff or cutout — best-effort, not official sheets",
            "baseline": "Default / empty — no file; skipped when stacking",
        },
        "bearCount": old_manifest.get("bearCount", len(bears)),
        "summary": summary,
        "categories": categories,
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nWrote {MANIFEST_OUT}")
    for cat, s in summary.items():
        print(f"  {FOLDER[cat]}: {s['files']} files ({s['solid']} solid, {s['approx']} approx), {s['baseline']} baseline")


if __name__ == "__main__":
    main()
