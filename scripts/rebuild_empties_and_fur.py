#!/usr/bin/env python3
"""Add Empty to every slot + rebuild bare Fur plates (aggressive strip)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BEARS_DIR = ROOT / "assets" / "bears"
TRAITS_ROOT = ROOT / "assets" / "traits"
OVERLAYS_ROOT = ROOT / "assets" / "overlays"
MANIFEST_OUT = ROOT / "traits-manifest.json"
OVERLAYS_META = ROOT / "data" / "overlays.json"

FOLDER = {
    "background": "Background", "fur": "Fur", "clothes": "Clothes",
    "mouth": "Mouth", "eyes": "Eyes", "headwear": "Headwear", "mask": "Mask",
}
LAYER_ORDER = ["background", "fur", "clothes", "mouth", "eyes", "headwear", "mask"]
SOLID_BGS = {
    "xrpl-orange", "xrpl-magenta", "xrpl-yellow", "xrpl-red-purple",
    "xrpl-blue-purple", "xrpl-green", "xrpl-grey", "xrpl-blue",
}

ROI_EYES = (130, 155, 380, 258)
ROI_MOUTH = (145, 248, 365, 365)
ROI_CLOTHES = (75, 300, 435, 512)
ROI_CROWN = (55, 0, 455, 115)
ROI_NOSE = (225, 228, 285, 272)


def load_rgba(ed: int) -> np.ndarray:
    return np.asarray(Image.open(BEARS_DIR / f"{ed}.webp").convert("RGBA"), dtype=np.uint8).copy()


def bg_kind(bg_id: str) -> str:
    if bg_id == "coded":
        return "coded"
    if bg_id == "vignette":
        return "gradient"
    return "solid"


def chroma_key(arr: np.ndarray, kind: str = "solid") -> np.ndarray:
    out = arr.copy()
    br, bg, bb = int(out[0, 0, 0]), int(out[0, 0, 1]), int(out[0, 0, 2])
    h, w = out.shape[:2]
    rgb = out[:, :, :3].astype(np.int16)
    if kind == "solid":
        dist = np.max(np.abs(rgb - np.array([br, bg, bb], dtype=np.int16)), axis=2)
        out[dist <= 32, 3] = 0
        soft = (dist > 32) & (dist < 48)
        out[soft, 3] = ((dist[soft] - 32) * (255 / 16)).astype(np.uint8)
        return out
    tol = 50 if kind == "coded" else 42
    visited = np.zeros((h, w), dtype=np.uint8)
    stack = [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)]
    stack += [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]
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


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(a)
    y0s, y1s = max(0, dy), a.shape[0] + min(0, dy)
    x0s, x1s = max(0, dx), a.shape[1] + min(0, dx)
    y0d, y1d = max(0, -dy), a.shape[0] + min(0, -dy)
    x0d, x1d = max(0, -dx), a.shape[1] + min(0, -dx)
    out[y0d:y1d, x0d:x1d] = a[y0s:y1s, x0s:x1s]
    return out


def binary_erode(mask: np.ndarray, n: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    for _ in range(n):
        acc = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    acc &= _shift(m, dy, dx)
        m = acc
    return m


def binary_dilate(mask: np.ndarray, n: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    for _ in range(n):
        acc = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    acc |= _shift(m, dy, dx)
        m = acc
    return m


def opaque_count(arr: np.ndarray) -> int:
    return int(np.count_nonzero(arr[:, :, 3] > 40))


def fur_donor_score(t: dict) -> int:
    s = 0
    if t["headwear"] == "none":
        s += 50
    if t["mask"] == "none":
        s += 40
    if t["clothes"] == "none":
        s += 60
    elif t["clothes"] == "snappy-casual":
        s += 12
    if t["eyes"] == "blue":
        s += 25
    if t["mouth"] == "normal":
        s += 25
    if t["background"] in SOLID_BGS:
        s += 8
    return s


def sample_fur_rgb(arr: np.ndarray) -> np.ndarray:
    patches = [
        arr[200:245, 125:170],
        arr[200:245, 340:385],
        arr[275:315, 115:155],
        arr[275:315, 355:395],
        arr[145:175, 155:185],
        arr[145:175, 325:355],
    ]
    cols = []
    for patch in patches:
        a = patch[:, :, 3] >= 200
        if not a.any():
            continue
        rgb = patch[:, :, :3][a]
        lum = rgb.astype(np.int16).max(axis=1)
        keep = (lum > 28) & (lum < 200)
        if keep.any():
            cols.append(rgb[keep])
    if cols:
        return np.median(np.concatenate(cols, axis=0), axis=0).astype(np.float32)
    return np.array([120.0, 80.0, 50.0], dtype=np.float32)


def recolor_to_fur(src: np.ndarray, target_rgb: np.ndarray) -> np.ndarray:
    out = src.copy()
    a = out[:, :, 3] >= 40
    if not a.any():
        return out
    src_med = np.maximum(sample_fur_rgb(out), 1.0)
    scale = target_rgb / src_med
    rgb = out[:, :, :3].astype(np.float32)
    rgb[a] = np.clip(rgb[a] * scale, 0, 255)
    out[:, :, :3] = rgb.astype(np.uint8)
    return out


def roi_mask(h, w, roi):
    x0, y0, x1, y1 = roi
    m = np.zeros((h, w), dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def fill_region_with_fur(arr: np.ndarray, region: np.ndarray, fur_rgb: np.ndarray, seed: int = 0) -> np.ndarray:
    """Nuclear fill: every opaque pixel in region becomes fur-textured."""
    out = arr.copy()
    target = region & (out[:, :, 3] >= 30)
    ys, xs = np.where(target)
    if len(ys) == 0:
        return out
    # Build a texture atlas from cheek patches
    cheeks = []
    for y0, y1, x0, x1 in [
        (200, 245, 125, 170), (200, 245, 340, 385),
        (275, 315, 115, 155), (275, 315, 355, 395),
    ]:
        patch = out[y0:y1, x0:x1]
        a = patch[:, :, 3] >= 200
        if a.any():
            cheeks.append(patch[:, :, :3][a])
    rng = np.random.default_rng(seed)
    if cheeks:
        pool = np.concatenate(cheeks, axis=0).astype(np.float32)
        # bias pool toward fur_rgb median
        picks = pool[rng.integers(0, len(pool), size=len(ys))]
        # blend toward fur_rgb to kill leftover color cast
        picks = picks * 0.55 + fur_rgb[None, :] * 0.45
        picks += rng.normal(0, 4, picks.shape)
    else:
        picks = np.broadcast_to(fur_rgb, (len(ys), 3)).astype(np.float32)
        picks += rng.normal(0, 6, picks.shape)
    out[ys, xs, :3] = np.clip(picks, 0, 255).astype(np.uint8)
    out[ys, xs, 3] = 255
    return out


def hard_alpha(arr: np.ndarray, floor: int = 150) -> np.ndarray:
    keep = arr[:, :, 3] >= floor
    nbs = np.zeros(keep.shape, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                nbs += _shift(keep, dy, dx).astype(np.uint8)
    keep = keep & (nbs >= 2)
    keep = binary_dilate(binary_erode(keep, 1), 1)
    out = np.zeros_like(arr)
    out[keep, :3] = arr[keep, :3]
    out[keep, 3] = 255
    out[0, :, 3] = 0
    out[-1, :, 3] = 0
    out[:, 0, 3] = 0
    out[:, -1, 3] = 0
    return out


def extract_bare_fur(bears: list, fur_id: str, n: int = 18):
    donors = [b for b in bears if b["traits"]["fur"] == fur_id]
    donors.sort(key=lambda b: (-fur_donor_score(b["traits"]), b["edition"]))
    picked, seen = [], set()
    for b in donors:
        t = b["traits"]
        if not (BEARS_DIR / f"{b['edition']}.webp").exists():
            continue
        sig = (t["clothes"], t["headwear"], t["mask"], t["eyes"], t["mouth"])
        if sig in seen and len(picked) >= 8:
            continue
        seen.add(sig)
        picked.append(b)
        if len(picked) >= n:
            break
    if len(picked) < 2:
        for b in donors:
            if b not in picked and (BEARS_DIR / f"{b['edition']}.webp").exists():
                picked.append(b)
            if len(picked) >= 4:
                break
    if not picked:
        return None, [], {}

    h = w = 512
    count = np.zeros((h, w), dtype=np.uint16)
    suma = np.zeros((h, w, 3), dtype=np.uint32)
    crown_c = np.zeros((h, w), dtype=np.uint16)
    crown_s = np.zeros((h, w, 3), dtype=np.uint32)
    crown_n = 0
    torso_c = np.zeros((h, w), dtype=np.uint16)
    torso_s = np.zeros((h, w, 3), dtype=np.uint32)
    torso_n = 0
    fur_samples = []

    for b in picked:
        t = b["traits"]
        cut = chroma_key(load_rgba(b["edition"]), bg_kind(t["background"]))
        opaque = cut[:, :, 3] >= 50
        count += opaque.astype(np.uint16)
        suma[opaque] += cut[:, :, :3][opaque]
        if t["headwear"] == "none" and t["mask"] == "none":
            crown_n += 1
            crown_c += opaque.astype(np.uint16)
            crown_s[opaque] += cut[:, :, :3][opaque]
        if t["clothes"] == "none" and t["mask"] == "none":
            torso_n += 1
            torso_c += opaque.astype(np.uint16)
            torso_s[opaque] += cut[:, :, :3][opaque]
        fur_samples.append(sample_fur_rgb(cut))

    fur_target = np.median(np.stack(fur_samples), axis=0) if fur_samples else np.array([120, 80, 50], dtype=np.float32)

    if torso_n < 2:
        extras = [
            b for b in bears
            if b["traits"]["clothes"] == "none"
            and b["traits"]["mask"] == "none"
            and b["traits"]["fur"] != fur_id
            and (BEARS_DIR / f"{b['edition']}.webp").exists()
        ]
        extras.sort(key=lambda b: (-fur_donor_score(b["traits"]), b["edition"]))
        for b in extras[:8]:
            cut = recolor_to_fur(
                chroma_key(load_rgba(b["edition"]), bg_kind(b["traits"]["background"])),
                fur_target,
            )
            opaque = cut[:, :, 3] >= 50
            torso_n += 1
            torso_c += opaque.astype(np.uint16)
            torso_s[opaque] += cut[:, :, :3][opaque]

    thresh = max(2, int(round(len(picked) * 0.45)))
    mask = count >= thresh
    crown_zone = roi_mask(h, w, ROI_CROWN)
    if crown_n >= 2:
        ct = max(1, int(round(crown_n * 0.45)))
        use_c = crown_zone & (crown_c >= ct)
        mask = (mask & ~crown_zone) | use_c | (mask & crown_zone & (crown_c > 0))

    out = np.zeros((h, w, 4), dtype=np.uint8)
    if mask.any():
        c = np.maximum(count, 1).astype(np.uint32)
        mean_rgb = (suma // c[:, :, None]).astype(np.uint8)
        out[mask, :3] = mean_rgb[mask]
        out[mask, 3] = 255
        if crown_n >= 2:
            ct = max(1, int(round(crown_n * 0.45)))
            cc = np.maximum(crown_c, 1).astype(np.uint32)
            crown_rgb = (crown_s // cc[:, :, None]).astype(np.uint8)
            use = crown_zone & (crown_c >= ct) & mask
            out[use, :3] = crown_rgb[use]
        torso_zone = roi_mask(h, w, ROI_CLOTHES)
        if torso_n >= 1:
            tt = max(1, int(round(max(torso_n, 1) * 0.30)))
            tc = np.maximum(torso_c, 1).astype(np.uint32)
            torso_rgb = (torso_s // tc[:, :, None]).astype(np.uint8)
            use = torso_zone & (torso_c >= tt)
            out[use, :3] = torso_rgb[use]
            out[use, 3] = 255

    # NO face-zone rectangular override — that caused box ghosts
    fur_rgb = sample_fur_rgb(out)
    nose = roi_mask(h, w, ROI_NOSE)

    # Nuclear fills for accessory ROIs (preserve nose)
    out = fill_region_with_fur(out, roi_mask(h, w, ROI_EYES) & ~nose, fur_rgb, seed=1)
    out = fill_region_with_fur(out, roi_mask(h, w, ROI_MOUTH) & ~nose, fur_rgb, seed=2)
    out = fill_region_with_fur(out, roi_mask(h, w, ROI_CLOTHES), fur_rgb, seed=3)
    # Crown: only strip non-fur-colored hat pixels (ears stay)
    crown = roi_mask(h, w, ROI_CROWN) & (out[:, :, 3] >= 40)
    rgb = out[:, :, :3].astype(np.float32)
    dist = np.max(np.abs(rgb - fur_rgb[None, None, :]), axis=2)
    lum = rgb.max(axis=2)
    hatish = crown & ((dist > 40) | (lum > 200) | ((lum < 25) & (dist > 20)))
    out = fill_region_with_fur(out, hatish, fur_rgb, seed=4)

    # Kill any remaining bright teeth/eyes anywhere in mid-face
    face_band = roi_mask(h, w, (125, 150, 385, 370)) & (out[:, :, 3] >= 40) & ~nose
    bright = face_band & (out[:, :, :3].max(axis=2) > 185)
    out = fill_region_with_fur(out, bright, fur_rgb, seed=5)

    out = hard_alpha(out, floor=150)
    meta = {
        "donors": [d["edition"] for d in picked],
        "crown_n": crown_n,
        "torso_n": torso_n,
        "fur_rgb": [float(x) for x in fur_rgb],
    }
    return out, picked, meta


def extract_feature_plate(bears, cat, trait_id, roi, n=24, min_dist=48, min_opaque=180):
    """Tight feature extract: only strong non-fur pixels in ROI, then erode hard."""
    x0, y0, x1, y1 = roi
    donors = []
    for b in bears:
        t = b["traits"]
        if t[cat] != trait_id or t["mask"] != "none":
            continue
        if not (BEARS_DIR / f"{b['edition']}.webp").exists():
            continue
        donors.append((fur_donor_score(t), b))
    donors.sort(key=lambda x: -x[0])
    donors = [b for _, b in donors[:n]]
    if len(donors) < 4:
        return None

    h = w = 512
    count = np.zeros((h, w), dtype=np.uint16)
    suma = np.zeros((h, w, 3), dtype=np.uint32)
    for b in donors:
        cut = chroma_key(load_rgba(b["edition"]), bg_kind(b["traits"]["background"]))
        fur = sample_fur_rgb(cut)
        roi_a = cut[y0:y1, x0:x1]
        rgb = roi_a[:, :, :3].astype(np.float32)
        alpha = roi_a[:, :, 3]
        dist = np.max(np.abs(rgb - fur[None, None, :]), axis=2)
        lum = rgb.max(axis=2)
        # Strong feature only: far from fur AND (bright OR dark cavity OR chromatic)
        sat = rgb.max(axis=2) - rgb.min(axis=2)
        feat = (alpha >= 80) & (dist >= min_dist) & ((lum > 90) | (lum < 45) | (sat > 40))
        yy, xx = np.where(feat)
        if len(yy) == 0:
            continue
        gy, gx = yy + y0, xx + x0
        count[gy, gx] += 1
        suma[gy, gx] += cut[gy, gx, :3]

    thresh = max(3, int(round(len(donors) * 0.40)))
    mask = count >= thresh
    mask = binary_erode(mask, 1)
    mask = binary_dilate(mask, 1)
    # Drop tiny speckles via neighbor count
    nbs = np.zeros(mask.shape, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                nbs += _shift(mask, dy, dx).astype(np.uint8)
    mask = mask & (nbs >= 3)

    out = np.zeros((h, w, 4), dtype=np.uint8)
    if not mask.any():
        return None
    c = np.maximum(count, 1).astype(np.uint32)
    out[mask, :3] = (suma // c[:, :, None]).astype(np.uint8)[mask]
    out[mask, 3] = 255
    if opaque_count(out) < min_opaque:
        return None
    return out


def empty_trait(cat: str) -> dict:
    return {
        "id": "empty",
        "name": "Empty",
        "onChain": None,
        "count": 10**9,
        "none": True,
        "baseline": True,
        "file": None,
        "quality": "empty",
        "empty": True,
    }


def normalize_existing_none(trait: dict) -> dict:
    t = dict(trait)
    if t.get("id") == "none" or t.get("none"):
        t["name"] = "Empty"
        t["none"] = True
        t["baseline"] = True
        t["file"] = None
        t["quality"] = "empty"
        t["empty"] = True
        t["count"] = 10**9
    return t


def main() -> None:
    bears = json.loads((ROOT / "data" / "bears.json").read_text())["bears"]
    manifest = json.loads(MANIFEST_OUT.read_text())
    overlay_meta = json.loads(OVERLAYS_META.read_text()) if OVERLAYS_META.exists() else {"layers": {}}

    print("=== Rebuild bare Fur plates (v2 nuclear strip) ===")
    (TRAITS_ROOT / "Fur").mkdir(parents=True, exist_ok=True)
    fur_quality = {}
    for trait in list(manifest["categories"]["fur"]["traits"]):
        tid = trait["id"]
        if tid in ("empty", "none"):
            continue
        print(f"  Fur/{tid}…", flush=True)
        arr, donors, meta = extract_bare_fur(bears, tid)
        if arr is None or opaque_count(arr) < 5000:
            print(f"    FAIL opaque={opaque_count(arr) if arr is not None else 0}")
            fur_quality[tid] = {"ok": False}
            continue
        rel = f"assets/traits/Fur/{tid}.webp"
        Image.fromarray(arr, "RGBA").save(ROOT / rel, "WEBP", quality=92, method=4)
        trait["file"] = rel
        trait["quality"] = "approx"
        trait["derivedFrom"] = len(donors)
        trait["opaque"] = opaque_count(arr)
        trait["donors"] = meta.get("donors", [])[:8]
        trait["bareMeta"] = {k: meta[k] for k in ("crown_n", "torso_n", "fur_rgb")}
        fur_quality[tid] = {
            "ok": True,
            "opaque": opaque_count(arr),
            "donors": len(donors),
            "crown_n": meta["crown_n"],
            "torso_n": meta["torso_n"],
        }
        print(f"    ok opaque={opaque_count(arr)} crown={meta['crown_n']} torso={meta['torso_n']}")

    print("=== Extract Blue eyes + Normal mouth (tight) ===")
    (OVERLAYS_ROOT / "eyes").mkdir(parents=True, exist_ok=True)
    (OVERLAYS_ROOT / "mouths").mkdir(parents=True, exist_ok=True)
    (TRAITS_ROOT / "Eyes").mkdir(parents=True, exist_ok=True)
    (TRAITS_ROOT / "Mouth").mkdir(parents=True, exist_ok=True)

    blue = extract_feature_plate(bears, "eyes", "blue", ROI_EYES, n=28, min_dist=45, min_opaque=200)
    if blue is not None:
        rel = "assets/overlays/eyes/blue.webp"
        Image.fromarray(blue, "RGBA").save(ROOT / rel, "WEBP", quality=92, method=4)
        shutil.copy2(ROOT / rel, TRAITS_ROOT / "Eyes" / "blue.webp")
        print(f"  blue eyes opaque={opaque_count(blue)}")
        overlay_meta.setdefault("layers", {}).setdefault("eyes", {}).setdefault("traits", {})["blue"] = {
            "id": "blue", "name": "Blue", "file": rel, "none": False, "baseline": False,
            "opaque": opaque_count(blue), "approx": True,
        }
    else:
        print("  blue eyes FAILED")

    normal = extract_feature_plate(bears, "mouth", "normal", ROI_MOUTH, n=28, min_dist=42, min_opaque=200)
    if normal is not None:
        rel = "assets/overlays/mouths/normal.webp"
        Image.fromarray(normal, "RGBA").save(ROOT / rel, "WEBP", quality=92, method=4)
        shutil.copy2(ROOT / rel, TRAITS_ROOT / "Mouth" / "normal.webp")
        print(f"  normal mouth opaque={opaque_count(normal)}")
        overlay_meta.setdefault("layers", {}).setdefault("mouth", {}).setdefault("traits", {})["normal"] = {
            "id": "normal", "name": "Normal", "file": rel, "none": False, "baseline": False,
            "opaque": opaque_count(normal), "approx": True,
        }
    else:
        print("  normal mouth FAILED")

    for trait in manifest["categories"]["eyes"]["traits"]:
        if trait["id"] == "blue" and blue is not None:
            trait.update({
                "file": "assets/traits/Eyes/blue.webp", "quality": "approx",
                "none": False, "baseline": False, "opaque": opaque_count(blue),
            })
            trait.pop("empty", None)
    for trait in manifest["categories"]["mouth"]["traits"]:
        if trait["id"] == "normal" and normal is not None:
            trait.update({
                "file": "assets/traits/Mouth/normal.webp", "quality": "approx",
                "none": False, "baseline": False, "opaque": opaque_count(normal),
            })
            trait.pop("empty", None)

    print("=== Inject Empty into every category ===")
    for cat in LAYER_ORDER:
        traits = [normalize_existing_none(t) for t in manifest["categories"][cat]["traits"]]
        traits = [t for t in traits if t.get("id") != "empty"]
        has_none = any(t.get("id") == "none" for t in traits)
        if not has_none:
            traits.append(empty_trait(cat))
        traits.sort(key=lambda t: (
            int(t["count"]) if t.get("count") is not None else 10**9,
            str(t.get("name") or t.get("id")),
        ))
        manifest["categories"][cat]["traits"] = traits
        print(f"  {cat}: {len(traits)} last={traits[-1]['id']}/{traits[-1]['name']}")

    manifest["baselines"] = {
        "background": "empty", "fur": "empty", "clothes": "none",
        "mouth": "empty", "eyes": "empty", "headwear": "none", "mask": "none",
    }
    manifest["qualityNote"] = {
        "solid": "Exact extracted colour / plate",
        "approx": "Consensus cutout / pixel-diff — bare fur plates strip accessories",
        "empty": "Empty — no file; layer skipped when stacking",
        "baseline": "Legacy alias of empty",
    }
    manifest["description"] = (
        "Trait-file mixer: stacks layers from assets/traits/ only. "
        "Every slot has Empty (no overlay). Fur plates are bare-body cutouts "
        "(clothes/eyes/mouth/headwear/mask stripped). Blue eyes & Normal mouth "
        "are real plates. Traits ordered rare → common, Empty last."
    )
    summary = {}
    for cat, info in manifest["categories"].items():
        summary[cat] = {
            "files": sum(1 for t in info["traits"] if t.get("file")),
            "empty": sum(1 for t in info["traits"] if t.get("none") or t.get("empty") or t.get("quality") == "empty"),
            "solid": sum(1 for t in info["traits"] if t.get("quality") == "solid"),
            "approx": sum(1 for t in info["traits"] if t.get("quality") == "approx"),
        }
    manifest["summary"] = summary
    for cat in ("eyes", "mouth"):
        if cat in overlay_meta.get("layers", {}):
            overlay_meta["layers"][cat]["baseline"] = "empty"
    OVERLAYS_META.write_text(json.dumps(overlay_meta, indent=2) + "\n")
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2) + "\n")
    (ROOT / "data" / "fur_rebuild_report.json").write_text(
        json.dumps({"fur": fur_quality, "blue": blue is not None, "normal": normal is not None, "summary": summary}, indent=2) + "\n"
    )
    print("\nDone")
    for cat, s in summary.items():
        print(f"  {FOLDER[cat]}: {s['files']} files, {s['empty']} empty")


if __name__ == "__main__":
    main()
