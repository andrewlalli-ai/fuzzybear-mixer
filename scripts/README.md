# Rebuild scripts

| Script | Output |
|--------|--------|
| `fetch_metadata.py` | `data/meta-cache/`, `data/issuer_nfts.json` |
| `build_index.py` | `data/bears.json` (+ seed traits-manifest) |
| `precache_images.py` | `assets/bears/*.webp` (build input only) |
| `build_backgrounds.py` | `assets/backgrounds/` + `data/backgrounds.json` |
| `build_overlays.py` | `assets/overlays/` + `data/overlays.json` |
| `build_traits.py` | `assets/traits/<Category>/` + final `traits-manifest.json` |

The Pages UI uses **only** `traits-manifest.json` and `assets/traits/`.
