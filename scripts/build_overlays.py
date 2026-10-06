#!/usr/bin/env python3
"""Build assets/overlays/masks/*.webp + data/overlays.json from composite diffs.

Official trait-layer PNGs were never published. Mask plates are approximate
overlays derived by consensus pixel-diff of same-headwear masked vs unmasked
composites (face band only). Suitable for demo layer remix, not exact art.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BEARS_DIR = ROOT / "assets" / "bears"
OUT_DIR = ROOT / "assets" / "overlays" / "masks"
META_OUT = ROOT / "data" / "overlays.json"


def load(ed: int) -> Image.Image:
    return Image.open(BEARS_DIR / f"{ed}.webp").convert("RGBA")


def chroma_cut(im: Image.Image, tol: int = 28) -> Image.Image:
    px = im.load()
    w, h = im.size
    br, bg, bb = px[2, 2][:3]
    out = im.copy()
    op = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if max(abs(r - br), abs(g - bg), abs(b - bb)) <= tol:
                op[x, y] = (0, 0, 0, 0)
    return out


def best_none(bears: list, target: dict):
    best = None
    for b in bears:
        if b["traits"]["mask"] != "none":
            continue
        if b["traits"]["headwear"] != target["traits"]["headwear"]:
            continue
        score = 3  # same headwear
        if b["traits"]["fur"] == target["traits"]["fur"]:
            score += 5
        for c in ("clothes", "eyes", "mouth"):
            if b["traits"][c] == target["traits"][c]:
                score += 2
        if best is None or score > best[0]:
            best = (score, b)
    return best


def clean_isolated(im: Image.Image, min_nbs: int = 3) -> Image.Image:
    w, h = im.size
    op = im.load()
    clean = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cp = clean.load()
    nbrs = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1))
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if op[x, y][3] == 0:
                continue
            if sum(1 for dx, dy in nbrs if op[x + dx, y + dy][3] > 0) >= min_nbs:
                cp[x, y] = op[x, y]
    return clean


def extract_consensus(
    bears: list,
    mask_id: str,
    n: int = 15,
    y0: int = 128,
    y1: int = 298,
    dist: int = 38,
    thresh_frac: float = 0.28,
):
    donors = []
    for d in bears:
        if d["traits"]["mask"] != mask_id:
            continue
        r = best_none(bears, d)
        if r and r[0] >= 8:
            donors.append((r[0], d["edition"], r[1]["edition"]))
    donors.sort(key=lambda t: (-t[0], t[1]))
    donors = donors[:n]
    w = h = 512
    count = [[0] * w for _ in range(h)]
    suma = [[[0, 0, 0] for _ in range(w)] for _ in range(h)]
    for _sc, de, be in donors:
        da = chroma_cut(load(de))
        ba = chroma_cut(load(be))
        pd, pb = da.load(), ba.load()
        for y in range(y0, y1):
            for x in range(105, 405):
                r, g, b, a = pd[x, y]
                if a < 40:
                    continue
                rb, gb, bb, ab = pb[x, y]
                if ab >= 40 and max(abs(r - rb), abs(g - gb), abs(b - bb)) <= dist:
                    continue
                count[y][x] += 1
                suma[y][x][0] += r
                suma[y][x][1] += g
                suma[y][x][2] += b
    thresh = max(2, int(round(len(donors) * thresh_frac)))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    op = out.load()
    for y in range(h):
        for x in range(w):
            c = count[y][x]
            if c >= thresh:
                r = suma[y][x][0] // c
                g = suma[y][x][1] // c
                b = suma[y][x][2] // c
                a = min(255, 160 + int(95 * c / max(len(donors), 1)))
                op[x, y] = (r, g, b, a)
    return clean_isolated(out, 3), donors


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bears = json.loads((ROOT / "data" / "bears.json").read_text())["bears"]
    manifest = json.loads((ROOT / "traits-manifest.json").read_text())

    meta = {
        "size": 512,
        "note": "Approximate mask overlays derived by consensus pixel-diff of "
        "same-headwear masked vs unmasked composites. Not official trait sheets.",
        "layers": {
            "mask": {
                "kind": "overlay",
                "z": 6,
                "trueLayer": True,
                "approx": True,
                "traits": {},
            }
        },
    }

    for trait in manifest["categories"]["mask"]["traits"]:
        tid = trait["id"]
        if tid == "none" or trait.get("none"):
            meta["layers"]["mask"]["traits"][tid] = {
                "id": tid,
                "name": trait["name"],
                "file": None,
                "none": True,
                "count": trait["count"],
            }
            print(f"{tid}: none (no plate)")
            continue
        im, donors = extract_consensus(bears, tid)
        out = OUT_DIR / f"{tid}.webp"
        im.save(out, "WEBP", quality=92, method=4)
        meta["layers"]["mask"]["traits"][tid] = {
            "id": tid,
            "name": trait["name"],
            "file": f"assets/overlays/masks/{tid}.webp",
            "none": False,
            "count": trait["count"],
            "derivedFrom": len(donors),
            "approx": True,
        }
        print(f"{tid}: {out.stat().st_size} B from {len(donors)} pairs bbox={im.getbbox()}")

    META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {META_OUT}")


if __name__ == "__main__":
    main()
