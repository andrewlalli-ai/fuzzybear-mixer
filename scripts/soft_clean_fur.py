#!/usr/bin/env python3
"""Soft-ellipse refill of fur accessory ROIs + tight blue/normal extract."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BEARS_DIR = ROOT / "assets" / "bears"
FUR_DIR = ROOT / "assets" / "traits" / "Fur"

ROI_EYES = (120, 148, 390, 268)
ROI_MOUTH = (140, 240, 370, 375)
ROI_CLOTHES_Y0 = 295
ROI_CROWN = (50, 0, 460, 120)
ROI_NOSE = (220, 225, 290, 278)


def soft_ellipse(h, w, roi):
    x0, y0, x1, y1 = roi
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rx, ry = (x1 - x0) / 2.0 * 1.05, (y1 - y0) / 2.0 * 1.05
    yy, xx = np.ogrid[0:h, 0:w]
    d = np.sqrt(((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2)
    m = np.zeros((h, w), dtype=np.float32)
    m[d <= 0.70] = 1.0
    band = (d > 0.70) & (d <= 1.08)
    m[band] = ((1.08 - d[band]) / (1.08 - 0.70)).astype(np.float32)
    return np.clip(m, 0, 1)


def sample_fur(arr):
    patches = [
        arr[200:245, 125:170],
        arr[200:245, 340:385],
        arr[280:320, 120:160],
        arr[280:320, 350:390],
    ]
    cols = []
    for p in patches:
        a = p[:, :, 3] >= 200
        if not a.any():
            continue
        rgb = p[:, :, :3][a]
        lum = rgb.max(1)
        k = (lum > 25) & (lum < 210)
        if k.any():
            cols.append(rgb[k])
    if cols:
        return np.median(np.concatenate(cols), 0).astype(np.float32)
    return np.array([100, 70, 50], np.float32)


def soft_fill(arr, weight, fur_rgb, seed=0):
    out = arr.astype(np.float32).copy()
    a = arr[:, :, 3] >= 30
    w = weight * a
    ys, xs = np.where(w > 0.05)
    if len(ys) == 0:
        return arr
    rng = np.random.default_rng(seed)
    cheeks = []
    for box in [
        (195, 250, 120, 175),
        (195, 250, 340, 390),
        (270, 320, 110, 160),
        (270, 320, 350, 400),
        (160, 190, 140, 175),
        (160, 190, 335, 370),
    ]:
        y0, y1, x0, x1 = box
        p = arr[y0:y1, x0:x1]
        aa = p[:, :, 3] >= 200
        if aa.any():
            cheeks.append(p[:, :, :3][aa].astype(np.float32))
    if cheeks:
        pool = np.concatenate(cheeks, 0)
        d = np.max(np.abs(pool - fur_rgb), 1)
        pool = pool[d < 60] if (d < 60).sum() > 40 else pool
        picks = pool[rng.integers(0, len(pool), len(ys))]
        picks = picks * 0.45 + fur_rgb * 0.55
        picks += rng.normal(0, 5, picks.shape)
    else:
        picks = np.broadcast_to(fur_rgb, (len(ys), 3)).astype(np.float32)
        picks += rng.normal(0, 6, picks.shape)
    ww = w[ys, xs][:, None]
    cur = out[ys, xs, :3]
    out[ys, xs, :3] = cur * (1 - ww) + np.clip(picks, 0, 255) * ww
    out[ys, xs, 3] = np.maximum(out[ys, xs, 3], ww[:, 0] * 255)
    return np.clip(out, 0, 255).astype(np.uint8)


def hard_alpha(arr, floor=140):
    keep = arr[:, :, 3] >= floor
    out = np.zeros_like(arr)
    out[keep, :3] = arr[keep, :3]
    out[keep, 3] = 255
    out[0, :, 3] = 0
    out[-1, :, 3] = 0
    out[:, 0, 3] = 0
    out[:, -1, 3] = 0
    return out


def clean_fur_file(path: Path) -> None:
    arr = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8).copy()
    h, w = arr.shape[:2]
    fur = sample_fur(arr)
    nose = soft_ellipse(h, w, ROI_NOSE)
    eyes = soft_ellipse(h, w, ROI_EYES) * (1.0 - nose * 0.9)
    mouth = soft_ellipse(h, w, ROI_MOUTH) * (1.0 - nose * 0.9)
    yy = np.linspace(0, 1, h)[:, None]
    xx = np.linspace(0, 1, w)[None, :]
    clothes = np.clip((yy - 0.56) / 0.12, 0, 1) * np.ones((1, w), dtype=np.float32)
    clothes *= np.clip((xx - 0.08) / 0.08, 0, 1) * np.clip((0.92 - xx) / 0.08, 0, 1)
    clothes = clothes.astype(np.float32)

    arr = soft_fill(arr, eyes, fur, seed=1)
    arr = soft_fill(arr, mouth, fur, seed=2)
    arr = soft_fill(arr, clothes, fur, seed=3)

    crown = soft_ellipse(h, w, ROI_CROWN)
    rgb = arr[:, :, :3].astype(np.float32)
    dist = np.max(np.abs(rgb - fur), axis=2)
    sat = rgb.max(2) - rgb.min(2)
    lum = rgb.max(2)
    if float(fur.max()) > 160:
        hat = (crown > 0.25) & ((dist > 48) | (sat > 42))
    else:
        hat = (crown > 0.25) & ((dist > 36) | (lum > 195))
    arr = soft_fill(arr, hat.astype(np.float32) * crown, fur, seed=4)
    arr = soft_fill(arr, eyes * 0.97, fur, seed=11)
    arr = soft_fill(arr, mouth * 0.92, fur, seed=12)
    arr = hard_alpha(arr)
    Image.fromarray(arr, "RGBA").save(path, "WEBP", quality=92, method=4)
    bright = int((arr[148:268, 120:390, :3].max(2) > 185).sum())
    print(f"  {path.name}: bright-in-eyes={bright}")


def chroma(arr):
    out = arr.copy()
    br, bg, bb = map(int, out[0, 0, :3])
    rgb = out[:, :, :3].astype(np.int16)
    dist = np.max(np.abs(rgb - np.array([br, bg, bb], np.int16)), 2)
    out[dist <= 32, 3] = 0
    return out


def load(ed):
    return np.asarray(Image.open(BEARS_DIR / f"{ed}.webp").convert("RGBA"), np.uint8).copy()


def _shift(a, dy, dx):
    o = np.zeros_like(a)
    y0s, y1s = max(0, dy), a.shape[0] + min(0, dy)
    x0s, x1s = max(0, dx), a.shape[1] + min(0, dx)
    y0d, y1d = max(0, -dy), a.shape[0] + min(0, -dy)
    x0d, x1d = max(0, -dx), a.shape[1] + min(0, -dx)
    o[y0d:y1d, x0d:x1d] = a[y0s:y1s, x0s:x1s]
    return o


def erode(mask, n=1):
    m = mask.copy()
    for _ in range(n):
        acc = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    acc &= _shift(m, dy, dx)
        m = acc
    return m


def dilate(mask, n=1):
    m = mask.copy()
    for _ in range(n):
        acc = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    acc |= _shift(m, dy, dx)
        m = acc
    return m


def extract_eyes_blue(bears):
    donors = [
        b
        for b in bears
        if b["traits"]["eyes"] == "blue" and b["traits"]["mask"] == "none"
    ]
    donors = sorted(
        donors,
        key=lambda b: -(
            (b["traits"]["headwear"] == "none") * 3
            + (b["traits"]["mouth"] == "normal")
            + (b["traits"]["clothes"] == "none")
        ),
    )[:32]
    h = w = 512
    count = np.zeros((h, w), np.uint16)
    suma = np.zeros((h, w, 3), np.uint32)
    x0, y0, x1, y1 = ROI_EYES
    for b in donors:
        if not (BEARS_DIR / f"{b['edition']}.webp").exists():
            continue
        cut = chroma(load(b["edition"]))
        roi = cut[y0:y1, x0:x1]
        rgb = roi[:, :, :3].astype(np.int16)
        a = roi[:, :, 3]
        white = (rgb.min(2) > 175) & (a >= 80)
        blue = (
            (rgb[:, :, 2] > 115)
            & (rgb[:, :, 2] > rgb[:, :, 0] + 18)
            & (rgb[:, :, 2] > rgb[:, :, 1] + 8)
            & (a >= 80)
        )
        core = white | blue
        core = dilate(core, 2)
        dark = (rgb.max(2) < 50) & (a >= 80)
        # dark only near dilated core
        near = dilate(core, 1)
        feat = (core | (dark & near))
        fur = sample_fur(cut)
        dist = np.max(np.abs(rgb.astype(np.float32) - fur), 2)
        feat = feat & (dist > 28)
        yy, xx = np.where(feat)
        if len(yy) == 0:
            continue
        gy, gx = yy + y0, xx + x0
        count[gy, gx] += 1
        suma[gy, gx] += cut[gy, gx, :3]
    thresh = max(3, int(len(donors) * 0.30))
    mask = erode(count >= thresh, 1)
    mask = dilate(mask, 1)
    out = np.zeros((h, w, 4), np.uint8)
    if not mask.any():
        return None
    c = np.maximum(count, 1).astype(np.uint32)
    out[mask, :3] = (suma // c[:, :, None]).astype(np.uint8)[mask]
    out[mask, 3] = 255
    return out


def extract_mouth_normal(bears):
    donors = [
        b
        for b in bears
        if b["traits"]["mouth"] == "normal" and b["traits"]["mask"] == "none"
    ]
    donors = sorted(
        donors,
        key=lambda b: -(
            (b["traits"]["headwear"] == "none") * 3
            + (b["traits"]["eyes"] == "blue")
            + (b["traits"]["clothes"] == "none")
        ),
    )[:32]
    h = w = 512
    count = np.zeros((h, w), np.uint16)
    suma = np.zeros((h, w, 3), np.uint32)
    x0, y0, x1, y1 = ROI_MOUTH
    for b in donors:
        if not (BEARS_DIR / f"{b['edition']}.webp").exists():
            continue
        cut = chroma(load(b["edition"]))
        roi = cut[y0:y1, x0:x1]
        rgb = roi[:, :, :3].astype(np.int16)
        a = roi[:, :, 3]
        white = (rgb.min(2) > 165) & (a >= 80)
        dark = (rgb.max(2) < 48) & (a >= 80)
        fur = sample_fur(cut)
        dist = np.max(np.abs(rgb.astype(np.float32) - fur), 2)
        feat = (white | dark) & (dist > 32)
        # keep only near white teeth cluster
        feat = feat & dilate(white, 3)
        yy, xx = np.where(feat)
        if len(yy) == 0:
            continue
        gy, gx = yy + y0, xx + x0
        count[gy, gx] += 1
        suma[gy, gx] += cut[gy, gx, :3]
    thresh = max(3, int(len(donors) * 0.30))
    mask = erode(count >= thresh, 1)
    out = np.zeros((h, w, 4), np.uint8)
    if not mask.any():
        return None
    c = np.maximum(count, 1).astype(np.uint32)
    out[mask, :3] = (suma // c[:, :, None]).astype(np.uint8)[mask]
    out[mask, 3] = 255
    return out


def main():
    print("=== Soft-clean fur plates ===")
    for path in sorted(FUR_DIR.glob("*.webp")):
        if path.stem in ("empty", "none"):
            continue
        clean_fur_file(path)

    bears = json.loads((ROOT / "data" / "bears.json").read_text())["bears"]
    print("=== Tight blue / normal ===")
    blue = extract_eyes_blue(bears)
    normal = extract_mouth_normal(bears)
    print("blue opaque", 0 if blue is None else int((blue[:, :, 3] > 40).sum()))
    print("normal opaque", 0 if normal is None else int((normal[:, :, 3] > 40).sum()))
    if blue is not None:
        Image.fromarray(blue, "RGBA").save(
            ROOT / "assets/overlays/eyes/blue.webp", "WEBP", quality=92, method=4
        )
        Image.fromarray(blue, "RGBA").save(
            ROOT / "assets/traits/Eyes/blue.webp", "WEBP", quality=92, method=4
        )
    if normal is not None:
        Image.fromarray(normal, "RGBA").save(
            ROOT / "assets/overlays/mouths/normal.webp", "WEBP", quality=92, method=4
        )
        Image.fromarray(normal, "RGBA").save(
            ROOT / "assets/traits/Mouth/normal.webp", "WEBP", quality=92, method=4
        )

    # peeks
    for name in ["brown", "polar", "honey", "dmt", "black", "golden"]:
        im = Image.open(FUR_DIR / f"{name}.webp").convert("RGBA").resize((256, 256))
        bg = Image.new("RGBA", (256, 256), (235, 235, 235, 255))
        bg.alpha_composite(im)
        bg.save(ROOT / "scripts" / f"_fur3_{name}.png")
    for name, folder in [("blue", "Eyes"), ("normal", "Mouth")]:
        p = ROOT / "assets" / "traits" / folder / f"{name}.webp"
        if p.exists():
            im = Image.open(p).convert("RGBA").resize((256, 256))
            bg = Image.new("RGBA", (256, 256), (150, 150, 150, 255))
            bg.alpha_composite(im)
            bg.save(ROOT / "scripts" / f"_feat3_{name}.png")
    print("done")


if __name__ == "__main__":
    main()
