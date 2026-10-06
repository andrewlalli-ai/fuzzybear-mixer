# raebyzzuF Trait Mixer (Fuzzybear)

Fan demo that mixes & browses **real Fuzzybear / raebyzzuF (`sraebyzzuF`)** artwork on XRPL.

> **Not affiliated with Fuzzybear.** Personal / educational fan demo only.
> Artwork © its creators — do not redistribute commercially without their permission.
> Hosting this on GitHub Pages redistributes cached WebP composites for demo purposes;
> remove `assets/bears/` if you need a metadata-only demo that loads from IPFS at runtime.

## Host on GitHub Pages (static — no Python on the phone)

1. Push this folder to a public GitHub repo.
2. **Settings → Pages →** Deploy from branch `main` / folder `/` (or `/docs` if you move files).
3. Open `https://<user>.github.io/<repo>/`.

Works offline of any custom server: the app prefers `assets/bears/<edition>.webp`
when present, otherwise falls back to public IPFS gateways (CORS-friendly ones first).

```bash
# Local static check (same as Pages)
cd fuzzybear-mixer
python3 -m http.server 8766
# → http://127.0.0.1:8766/
```

## Optional: on-demand cache server

```bash
python3 scripts/serve.py          # http://127.0.0.1:8765
```

`scripts/serve.py` also proxies `GET /bear-img/<edition>.webp` (fetch+cache missing
editions) and `GET /api/cached`. Use it while developing if you have not precached
everything. Plain `http.server` / GitHub Pages do **not** need it when WebPs are
already under `assets/bears/`.

## What you get

| Feature | Status |
|--------|--------|
| Real collection composite art | ✅ Option C — attribute fingerprint → minted bear |
| Exact-match filter + nearest when not minted | ✅ |
| Browse matching minted bears (‹ › / thumbnails) | ✅ |
| Left / right arrows per trait category | ✅ |
| Search traits or `#edition` | ✅ |
| `?` randomize (real bear *or* random mix) | ✅ |
| Custom upload overlay | ✅ |
| PNG export of the shown real bear (+ overlays) | ✅ (same-origin cache recommended) |
| Background as true layer (chroma-key cutout) | ✅ plates in `assets/backgrounds/` |
| Mask / Headwear / Clothes / Eyes / Mouth approx overlays | ✅ derived plates in `assets/overlays/` |
| Fur as separable layer | ❌ whole-body recolor — nearest-match body |

## Approach (research summary)

- **Collection:** issuer `r3NftTqH2hv3skuWAEDWKvqnxjtuqcFWYR`, taxon 0, ~1,220 NFTs.
- **Official site:** [fuzzyxrp.com](https://fuzzyxrp.com) — no trait-layer download, no remix API.
- **Metadata:** each NFT URI is IPFS JSON (CID
  `bafybeigugctfhnilpjt2p2vfxbofcphnqty6jycro7jub6km3xrxgn6jg4`). Attributes and
  names are stored reversed (`seyE ratS` → `Star Eyes`). `image` points at a
  composite PNG CID (`bafybeid7c2wzlm6z6fhcruulavmqonlqqdkzdvhaw54lygwxyr24zbtfki`).
- **APIs used:** XRPL Clio `nfts_by_issuer` (Ripple public nodes) + public IPFS
  gateways (filebase / pinata / dweb). Marketplace UIs (bithomp, xrp.cafe)
  only expose the same metadata.
- **Layers:** no open trait sheet found. **Background** is a true layer (plates +
  chroma-key cutout). **Mask, Headwear, Clothes, Eyes, Mouth** use approximate
  overlay plates derived by consensus pixel-diff of composites that share a base
  but differ on one trait (labeled “approx” in UI). **Fur** nearest-matches a
  minted body (whole-body recolor — not an overlay).
- **Licensing / ToS:** [fuzzyxrp.com/terms-of-use](https://fuzzyxrp.com/terms-of-use)
  covers the $FUZZY token site; there is **no published NFT remix / commercial-use
  license**. This app is a fan demo that uses publicly linked IPFS metadata and
  optionally caches WebPs for static hosting. Do not use commercially without
  rights from the creators. 3% transfer fee on-chain.

## How matching / layers work

1. Pick a value per category (or leave **Any**).
2. **Background ←/→** swaps only the backdrop plate under a chroma-keyed cutout of
   the current base bear — the character does **not** jump to another NFT.
3. **Clothes / Eyes / Mouth / Headwear / Mask ←/→** apply approximate derived
   overlay plates and prefer a stable baseline base (e.g. none headwear, blue
   eyes, normal mouth, none mask) so the body stays put (UI tags them **approx**).
4. **Fur** finds minted bears by body fingerprint. Exact fur hits → green
   “✓ Minted”; else amber nearest.
5. When Background or any approx overlay differs from the base → “◈ Layer remix”.
6. Thumbnails + ‹ › cycle base bears (layer selections are kept).
7. **＋ Custom** — Background + overlay-cat uploads become plates; Fur is a body overlay.
8. Regenerate: `python3 scripts/build_backgrounds.py` · `python3 scripts/build_overlays.py`

## Regenerating data

```bash
python3 scripts/fetch_metadata.py        # XRPL list + IPFS JSON (~1 KB each)
python3 scripts/build_index.py           # → data/bears.json + traits-manifest.json
python3 scripts/precache_images.py 1220  # warm assets/bears/ + assets/cached.json
```

Aim: keep `assets/bears/` under ~50 MB for a comfortable GitHub Pages clone.
All ~1220 editions usually fit (~35–45 MB WebP).

## Project layout

```text
fuzzybear-mixer/
  index.html  css/  js/app.js
  traits-manifest.json      # trait catalog + counts from real metadata
  data/bears.json           # 1220 bears: edition, traits, IPFS image, nftId
  data/meta-cache/          # raw IPFS metadata JSON (rebuild input)
  assets/bears/*.webp       # 512px cached composites for static hosting
  assets/backgrounds/*.webp # extracted/approx Background plates (layer remix)
  data/backgrounds.json    # plate catalogue (colour / kind / path)
  assets/overlays/{masks,headwear,clothes,eyes,mouths}/  # approx overlay plates
  data/overlays.json        # overlay catalogue (baselines + plates)
  assets/cached.json        # list of precached editions (no server API needed)
  scripts/serve.py          # optional: static + /bear-img + /api/cached
  scripts/fetch_metadata.py
  scripts/build_index.py
  scripts/precache_images.py
```

## Controls

- **← / →** cycle a category · **↑ / ↓** change focus · **[ / ]** prev/next match
- **?** / **r** randomize · **Any** set every category to wildcard
- Double-click a trait row → set that category to Any
- Search by trait name or `#56`
