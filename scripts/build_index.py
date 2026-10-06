#!/usr/bin/env python3
"""Step 2: turn cached metadata into data/bears.json + traits-manifest.json.

The collection stores every string reversed ("seyE ratS" == "Star Eyes");
we un-reverse for display and keep the raw on-chain value too.
"""
import json, os, re
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "data", "meta-cache")
LAYER_ORDER = ["background", "fur", "clothes", "mouth", "eyes", "headwear", "mask"]
LABELS = {c: c.capitalize() for c in LAYER_ORDER}
NONE = "None"


def rev(s):
    return s[::-1]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


nfts = {n["nft_id"]: n for n in json.load(open(os.path.join(ROOT, "data", "issuer_nfts.json")))}
bears = []
for fn in sorted(os.listdir(META)):
    nid = fn[:-5]
    m = json.load(open(os.path.join(META, fn)))
    name = m.get("name", "")
    ed = re.search(r"#\s*(\d+)", name)
    if not ed or not m.get("image"):
        continue
    traits = {}
    for a in m.get("attributes", []):
        cat = rev(str(a.get("trait_type", ""))).strip().lower()
        if cat in LAYER_ORDER:
            traits[cat] = rev(str(a.get("value", ""))).strip() or NONE
    for c in LAYER_ORDER:
        traits.setdefault(c, NONE)
    n = nfts.get(nid, {})
    bears.append({
        "edition": int(ed.group(1)),
        "name": name,
        "nftId": nid,
        "serial": n.get("nft_serial"),
        "owner": n.get("owner"),
        "image": m["image"],
        "traits": {c: slug(traits[c]) for c in LAYER_ORDER},
    })
# dedupe by edition (keep first)
seen, uniq = set(), []
for b in sorted(bears, key=lambda b: b["edition"]):
    if b["edition"] not in seen:
        seen.add(b["edition"]); uniq.append(b)
bears = uniq

# trait catalog with counts
names = defaultdict(dict)
counts = defaultdict(Counter)
for fn in os.listdir(META):
    m = json.load(open(os.path.join(META, fn)))
    for a in m.get("attributes", []):
        cat = rev(str(a.get("trait_type", ""))).strip().lower()
        if cat in LAYER_ORDER:
            v = rev(str(a.get("value", ""))).strip() or NONE
            names[cat][slug(v)] = {"name": v, "raw": a.get("value")}
for b in bears:
    for c, t in b["traits"].items():
        counts[c][t] += 1
        names[c].setdefault(t, {"name": NONE, "raw": None})

categories = {}
for z, c in enumerate(LAYER_ORDER):
    traits = []
    for tid, cnt in sorted(counts[c].items(), key=lambda kv: (kv[0] != "none", -kv[1])):
        info = names[c][tid]
        traits.append({"id": tid, "name": info["name"], "onChain": info["raw"], "count": cnt,
                       "none": tid == "none"})
    categories[c] = {"id": c, "label": LABELS[c], "zIndex": z, "traits": traits}

manifest = {
    "collection": "sraebyzzuf",
    "displayName": "raebyzzuF (Fuzzybear)",
    "issuer": "r3NftTqH2hv3skuWAEDWKvqnxjtuqcFWYR",
    "description": "Trait catalog generated from on-chain IPFS metadata. Art = real composite PNGs (no separable layers exist publicly).",
    "canvasSize": 512,
    "layerOrder": LAYER_ORDER,
    "mode": "composites",
    "bearCount": len(bears),
    "categories": categories,
}
json.dump({"bears": bears}, open(os.path.join(ROOT, "data", "bears.json"), "w"), separators=(",", ":"))
json.dump(manifest, open(os.path.join(ROOT, "traits-manifest.json"), "w"), indent=1)
print(len(bears), "bears;", {c: len(v["traits"]) for c, v in categories.items()})
