# Scripts

| Script | Purpose |
|--------|---------|
| `serve.py` | Static server + on-demand IPFS → WebP cache (`/bear-img/N.webp`, `/api/cached`) |
| `fetch_metadata.py` | List issuer NFTs (Clio) + download each IPFS metadata JSON |
| `build_index.py` | Un-reverse attributes → `data/bears.json` + `traits-manifest.json` |
| `precache_images.py [N]` | Warm a trait-diverse sample of composites into `assets/bears/` |

Public IPFS gateways rate-limit; `serve.py` retries with backoff. Prefer
filebase → pinata → cloudflare.
