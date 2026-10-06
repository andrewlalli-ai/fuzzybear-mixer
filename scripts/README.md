# Scripts

| Script | Purpose |
|--------|---------|
| `serve.py` | Optional static server + on-demand IPFS → WebP cache (`/bear-img/N.webp`, `/api/cached`) |
| `fetch_metadata.py` | List issuer NFTs (Clio) + download each IPFS metadata JSON |
| `build_index.py` | Un-reverse attributes → `data/bears.json` + `traits-manifest.json` |
| `precache_images.py [N]` | Warm composites into `assets/bears/` + write `assets/cached.json` |

For GitHub Pages / plain `python3 -m http.server`, precache what you need and
skip `serve.py`. Public IPFS gateways rate-limit; prefer filebase → pinata → dweb.

`build_backgrounds.py` — rebuild `assets/backgrounds/*.webp` + `data/backgrounds.json` from composites.
`build_overlays.py` — rebuild approx mask overlay plates in `assets/overlays/masks/` + `data/overlays.json`.
