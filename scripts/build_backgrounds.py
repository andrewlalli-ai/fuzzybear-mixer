#!/usr/bin/env python3
"""Build assets/backgrounds/*.webp + data/backgrounds.json from composite samples.

Official trait-layer PNGs were never published. Solid XRPL backgrounds are exact
corner colours; coded/vignette are reconstructed plates for layer remix demos.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BEARS_DIR = ROOT / "assets" / "bears"
OUT_DIR = ROOT / "assets" / "backgrounds"
META_OUT = ROOT / "data" / "backgrounds.json"


def sample_edge_color(path: Path, n: int = 16) -> tuple[int, int, int]:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    samples = []
    step = max(1, w // n)
    for x in range(0, w, step):
        samples.append(im.getpixel((x, 2))[:3])
        samples.append(im.getpixel((x, h - 3))[:3])
    for y in range(0, h, max(1, h // n)):
        samples.append(im.getpixel((2, y))[:3])
        samples.append(im.getpixel((w - 3, y))[:3])
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
    """Tile clean top strips from a coded composite (bear sits lower in frame)."""
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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bears = json.loads((ROOT / "data" / "bears.json").read_text())["bears"]
    manifest = json.loads((ROOT / "traits-manifest.json").read_text())
    by_bg: dict[str, list] = defaultdict(list)
    for b in bears:
        by_bg[b["traits"]["background"]].append(b)

    meta = {
        "size": 512,
        "note": "Extracted/approximated background plates for layer remix. "
                "Solid XRPL colours are exact; coded/vignette are reconstructed.",
        "backgrounds": {},
    }

    for trait in manifest["categories"]["background"]["traits"]:
        tid = trait["id"]
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

        out = OUT_DIR / f"{tid}.webp"
        plate.save(out, "WEBP", quality=90)
        meta["backgrounds"][tid] = {
            "id": tid,
            "name": trait["name"],
            "file": f"assets/backgrounds/{tid}.webp",
            "color": list(color),
            "hex": "#{:02x}{:02x}{:02x}".format(*color),
            "kind": kind,
            "count": trait["count"],
        }
        print(f"{tid}: {kind} {meta['backgrounds'][tid]['hex']} ({out.stat().st_size} B)")

    META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {META_OUT}")


if __name__ == "__main__":
    main()
