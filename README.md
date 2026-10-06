# raebyzzuF Trait Mixer (Fuzzybear)

Fan demo that **stacks trait image files** to remix Fuzzybear / raebyzzuF (`sraebyzzuF`) looks.

> **Not affiliated with Fuzzybear.** Personal / educational fan demo only.
> Artwork © its creators — do not redistribute commercially without their permission.
> Trait plates are **derived** (consensus cutouts / pixel-diff) — not official sheets.

## Host on GitHub Pages

1. Push this folder to a public GitHub repo.
2. **Settings → Pages →** Deploy from branch `main` / folder `/`.
3. Open `https://<user>.github.io/<repo>/`.

```bash
cd fuzzybear-mixer
python3 -m http.server 8766
# → http://127.0.0.1:8766/
```

The live UI loads **only** `traits-manifest.json` + files under `assets/traits/`.
It never shows base/minted bear composites, edition IDs, or “closest match” UI.

## What you get

| Feature | Status |
|--------|--------|
| Assemble bear from trait files only | ✅ stack in layer order |
| ←/→ per category (rare→common) | ✅ trait files only |
| Search traits | ✅ |
| `?` randomize stack | ✅ |
| Custom upload layer | ✅ |
| PNG export of stacked layers | ✅ |
| Square preview frame + mobile | ✅ |
| Minted / closest / #edition UI | ❌ removed by design |

## Trait plates

Official separable trait PNGs were never published. Plates live under:

```text
assets/traits/
  Background/   # 8 solid XRPL colours (exact) + coded/vignette (approx)
  Fur/          # consensus chroma-key body cutouts (approx)
  Clothes/      # consensus pixel-diff overlays (approx)
  Mouth/
  Eyes/
  Headwear/
  Mask/
```

Baselines (`none` / `blue` / `normal`) have **no file** — skipped when stacking.

Regenerate:

```bash
python3 scripts/build_overlays.py   # ROI pixel-diff → assets/overlays/
python3 scripts/build_backgrounds.py
python3 scripts/build_traits.py     # → assets/traits/ + traits-manifest.json
```

`assets/bears/` composites are **build inputs only** (not used by the Pages UI).

## Project layout

```text
fuzzybear-mixer/
  index.html  css/  js/app.js
  traits-manifest.json      # file paths + counts (rare→common)
  assets/traits/<Category>/*.webp
  data/bears.json           # rebuild input (metadata)
  assets/bears/*.webp       # rebuild input (composites)
  assets/overlays/          # intermediate overlay plates
  scripts/build_traits.py
  scripts/build_overlays.py
  scripts/build_backgrounds.py
```

## Controls

- **← / →** cycle a category · **↑ / ↓** change focus
- **?** / **r** randomize · **Reset** body + empty accessories
- Double-click a trait row → jump to baseline / empty for that category
- Search by trait name
