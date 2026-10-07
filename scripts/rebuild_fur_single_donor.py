#!/usr/bin/env python3
"""Rebuild each Fur plate from the single best bare-ish donor + soft strip."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BEARS_DIR = ROOT / "assets" / "bears"
FUR_DIR = ROOT / "assets" / "traits" / "Fur"
MANIFEST = ROOT / "traits-manifest.json"

SOLID_BGS = {
    "xrpl-orange", "xrpl-magenta", "xrpl-yellow", "xrpl-red-purple",
    "xrpl-blue-purple", "xrpl-green", "xrpl-grey", "xrpl-blue",
}
ROI_EYES = (118, 145, 392, 270)
ROI_MOUTH = (138, 238, 372, 378)
ROI_NOSE = (218, 222, 292, 280)
ROI_CROWN = (48, 0, 462, 125)


def score(t):
    s = 0
    if t["headwear"] == "none":
        s += 50
    if t["mask"] == "none":
        s += 40
    if t["clothes"] == "none":
        s += 55
    elif t["clothes"] == "snappy-casual":
        s += 10
    if t["eyes"] == "blue":
        s += 20
    if t["mouth"] == "normal":
        s += 20
    if t["background"] in SOLID_BGS:
        s += 10
    return s


def load(ed):
    return np.asarray(Image.open(BEARS_DIR / f"{ed}.webp").convert("RGBA"), np.uint8).copy()


def chroma(arr, bg_id):
    out = arr.copy()
    br, bg, bb = map(int, out[0, 0, :3])
    rgb = out[:, :, :3].astype(np.int16)
    seed = np.array([br, bg, bb], np.int16)
    if bg_id in SOLID_BGS or bg_id.startswith("xrpl"):
        dist = np.max(np.abs(rgb - seed), 2)
        out[dist <= 34, 3] = 0
        soft = (dist > 34) & (dist < 50)
        out[soft, 3] = ((dist[soft] - 34) * (255 / 16)).astype(np.uint8)
        return out
    # edge flood for patterned
    h, w = out.shape[:2]
    tol = 52 if bg_id == "coded" else 44
    visited = np.zeros((h, w), np.uint8)
    stack = [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)]
    stack += [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]
    while stack:
        y, x = stack.pop()
        if not (0 <= y < h and 0 <= x < w) or visited[y, x]:
            continue
        visited[y, x] = 1
        if abs(int(out[y, x, 0]) - br) > tol or abs(int(out[y, x, 1]) - bg) > tol or abs(int(out[y, x, 2]) - bb) > tol:
            continue
        out[y, x, 3] = 0
        stack.extend([(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)])
    return out


def soft_ellipse(h, w, roi):
    x0, y0, x1, y1 = roi
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rx, ry = (x1 - x0) / 2.0 * 1.08, (y1 - y0) / 2.0 * 1.08
    yy, xx = np.ogrid[0:h, 0:w]
    d = np.sqrt(((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2)
    m = np.zeros((h, w), np.float32)
    m[d <= 0.68] = 1.0
    band = (d > 0.68) & (d <= 1.1)
    m[band] = ((1.1 - d[band]) / (1.1 - 0.68)).astype(np.float32)
    return np.clip(m, 0, 1)


def sample_fur(arr):
    patches = [
        arr[205:250, 120:170],
        arr[205:250, 340:390],
        arr[285:325, 115:160],
        arr[285:325, 350:395],
        arr[155:185, 150:180],
        arr[155:185, 330:360],
    ]
    cols = []
    for p in patches:
        a = p[:, :, 3] >= 200
        if not a.any():
            continue
        rgb = p[:, :, :3][a]
        lum = rgb.max(1)
        k = (lum > 20) & (lum < 230)
        if k.any():
            cols.append(rgb[k])
    if cols:
        return np.median(np.concatenate(cols), 0).astype(np.float32)
    return np.array([100, 70, 50], np.float32)


def soft_fill(arr, weight, fur_rgb, seed=0):
    out = arr.astype(np.float32).copy()
    a = arr[:, :, 3] >= 25
    w = weight * a
    ys, xs = np.where(w > 0.04)
    if len(ys) == 0:
        return arr
    rng = np.random.default_rng(seed)
    cheeks = []
    for box in [
        (200, 255, 115, 175),
        (200, 255, 335, 395),
        (275, 330, 105, 165),
        (275, 330, 345, 405),
    ]:
        y0, y1, x0, x1 = box
        p = arr[y0:y1, x0:x1]
        aa = p[:, :, 3] >= 200
        if aa.any():
            rgb = p[:, :, :3][aa].astype(np.float32)
            d = np.max(np.abs(rgb - fur_rgb), 1)
            rgb = rgb[d < 70] if (d < 70).sum() > 30 else rgb
            if len(rgb):
                cheeks.append(rgb)
    if cheeks:
        pool = np.concatenate(cheeks, 0)
        picks = pool[rng.integers(0, len(pool), len(ys))]
        picks = picks * 0.4 + fur_rgb * 0.6 + rng.normal(0, 4, (len(ys), 3))
    else:
        picks = fur_rgb + rng.normal(0, 5, (len(ys), 3))
    ww = w[ys, xs][:, None]
    out[ys, xs, :3] = out[ys, xs, :3] * (1 - ww) + np.clip(picks, 0, 255) * ww
    out[ys, xs, 3] = np.maximum(out[ys, xs, 3], ww[:, 0] * 255)
    return np.clip(out, 0, 255).astype(np.uint8)


def hard_alpha(arr, floor=120):
    keep = arr[:, :, 3] >= floor
    out = np.zeros_like(arr)
    out[keep, :3] = arr[keep, :3]
    out[keep, 3] = 255
    out[0, :, 3] = 0
    out[-1, :, 3] = 0
    out[:, 0, 3] = 0
    out[:, -1, 3] = 0
    return out


def recolor(src, target):
    out = src.copy()
    a = out[:, :, 3] >= 40
    med = np.maximum(sample_fur(out), 1.0)
    scale = target / med
    rgb = out[:, :, :3].astype(np.float32)
    rgb[a] = np.clip(rgb[a] * scale, 0, 255)
    out[:, :, :3] = rgb.astype(np.uint8)
    return out


def build_fur(bears, fur_id):
    same = [b for b in bears if b["traits"]["fur"] == fur_id]
    same = [b for b in same if (BEARS_DIR / f"{b['edition']}.webp").exists()]
    same.sort(key=lambda b: (-score(b["traits"]), b["edition"]))
    if not same:
        return None, None

    # Primary: best same-fur donor
    primary = same[0]
    arr = chroma(load(primary["edition"]), primary["traits"]["background"])
    fur_rgb = sample_fur(arr)

    # If primary has clothes, paste torso from best clothes=none (any fur, recolored)
    if primary["traits"]["clothes"] != "none":
        torso_donors = [
            b
            for b in bears
            if b["traits"]["clothes"] == "none"
            and b["traits"]["mask"] == "none"
            and (BEARS_DIR / f"{b['edition']}.webp").exists()
        ]
        # prefer same fur
        torso_donors.sort(
            key=lambda b: (
                -(b["traits"]["fur"] == fur_id) * 100 - score(b["traits"]),
                b["edition"],
            )
        )
        if torso_donors:
            td = torso_donors[0]
            tarr = chroma(load(td["edition"]), td["traits"]["background"])
            if td["traits"]["fur"] != fur_id:
                tarr = recolor(tarr, fur_rgb)
            # paste lower body
            y0 = 290
            region = tarr[y0:, :, 3] >= 80
            arr[y0:][region] = tarr[y0:][region]

    # If primary has headwear, try crown from hatless same-fur
    if primary["traits"]["headwear"] != "none":
        hatless = [b for b in same if b["traits"]["headwear"] == "none" and b["traits"]["mask"] == "none"]
        if hatless:
            hd = hatless[0]
            harr = chroma(load(hd["edition"]), hd["traits"]["background"])
            y1 = 140
            region = harr[:y1, :, 3] >= 80
            arr[:y1][region] = harr[:y1][region]
            fur_rgb = sample_fur(arr)

    h, w = arr.shape[:2]
    nose = soft_ellipse(h, w, ROI_NOSE)
    eyes = soft_ellipse(h, w, ROI_EYES) * (1 - nose * 0.92)
    mouth = soft_ellipse(h, w, ROI_MOUTH) * (1 - nose * 0.92)
    yy = np.linspace(0, 1, h)[:, None] * np.ones((1, w))
    xx = np.linspace(0, 1, w)[None, :] * np.ones((h, 1))
    clothes = np.clip((yy - 0.55) / 0.14, 0, 1)
    clothes *= np.clip((xx - 0.07) / 0.08, 0, 1) * np.clip((0.93 - xx) / 0.08, 0, 1)

    # Always strip eyes/mouth/clothes aggressively for bare plate
    arr = soft_fill(arr, eyes, fur_rgb, 1)
    arr = soft_fill(arr, mouth, fur_rgb, 2)
    if primary["traits"]["clothes"] != "none":
        arr = soft_fill(arr, clothes.astype(np.float32), fur_rgb, 3)
    else:
        # light clothes strip only for residual logos
        rgb = arr[:, :, :3].astype(np.float32)
        dist = np.max(np.abs(rgb - fur_rgb), 2)
        odd = (clothes > 0.5) & (dist > 45) & (arr[:, :, 3] >= 40)
        arr = soft_fill(arr, odd.astype(np.float32), fur_rgb, 3)

    crown = soft_ellipse(h, w, ROI_CROWN)
    rgb = arr[:, :, :3].astype(np.float32)
    dist = np.max(np.abs(rgb - fur_rgb), 2)
    sat = rgb.max(2) - rgb.min(2)
    lum = rgb.max(2)
    if float(fur_rgb.max()) > 155:
        hat = (crown > 0.2) & ((dist > 45) | (sat > 40))
    else:
        hat = (crown > 0.2) & ((dist > 34) | (lum > 200))
    arr = soft_fill(arr, hat.astype(np.float32) * crown, fur_rgb, 4)

    # second pass
    arr = soft_fill(arr, eyes * 0.98, fur_rgb, 11)
    arr = soft_fill(arr, mouth * 0.95, fur_rgb, 12)
    arr = hard_alpha(arr, floor=100)
    return arr, primary


def main():
    bears = json.loads((ROOT / "data" / "bears.json").read_text())["bears"]
    manifest = json.loads(MANIFEST.read_text())
    report = {}
    print("=== Single-donor bare fur ===")
    for trait in manifest["categories"]["fur"]["traits"]:
        tid = trait["id"]
        if tid in ("empty", "none"):
            continue
        arr, primary = build_fur(bears, tid)
        if arr is None:
            print(f"  {tid}: FAIL")
            report[tid] = {"ok": False}
            continue
        rel = f"assets/traits/Fur/{tid}.webp"
        Image.fromarray(arr, "RGBA").save(ROOT / rel, "WEBP", quality=92, method=4)
        opaque = int((arr[:, :, 3] > 40).sum())
        trait["file"] = rel
        trait["quality"] = "approx"
        trait["opaque"] = opaque
        trait["derivedFrom"] = 1
        trait["donors"] = [primary["edition"]]
        trait["bareMeta"] = {
            "primary": primary["edition"],
            "traits": primary["traits"],
            "score": score(primary["traits"]),
        }
        report[tid] = {
            "ok": True,
            "opaque": opaque,
            "edition": primary["edition"],
            "traits": primary["traits"],
            "score": score(primary["traits"]),
        }
        t = primary["traits"]
        print(
            f"  {tid}: ed#{primary['edition']} clothes={t['clothes']} hat={t['headwear']} "
            f"eyes={t['eyes']} mouth={t['mouth']} opaque={opaque}"
        )

    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    (ROOT / "data" / "fur_rebuild_report.json").write_text(json.dumps(report, indent=2) + "\n")

    for name in ["brown", "polar", "honey", "dmt", "black", "golden", "ghost", "panda"]:
        p = FUR_DIR / f"{name}.webp"
        if not p.exists():
            continue
        im = Image.open(p).convert("RGBA").resize((256, 256))
        bg = Image.new("RGBA", (256, 256), (230, 230, 230, 255))
        bg.alpha_composite(im)
        bg.save(ROOT / "scripts" / f"_fur4_{name}.png")
    print("done")


if __name__ == "__main__":
    main()
