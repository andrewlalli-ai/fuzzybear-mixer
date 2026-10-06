#!/usr/bin/env python3
"""Step 3 (optional): warm assets/bears/ with N real composites (512px WebP).
Picks a trait-diverse sample so every trait value has at least one cached bear.
  python3 scripts/precache_images.py 150
Remaining bears are fetched lazily by scripts/serve.py on first view.
"""
import json, os, sys, random, concurrent.futures as cf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve  # noqa: E402  (reuses fetch/cache logic)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 150
bears = list(serve.BEARS.values())
random.seed(321)
random.shuffle(bears)
pick, covered = [], set()
for b in bears:  # greedy: cover every (category, trait) first
    keys = {(c, t) for c, t in b["traits"].items()}
    if keys - covered:
        pick.append(b); covered |= keys
for b in bears:
    if len(pick) >= N:
        break
    if b not in pick:
        pick.append(b)
pick = pick[:max(N, 0)] if len(pick) > N else pick
print(f"caching {len(pick)} bears")
ok = 0
with cf.ThreadPoolExecutor(2) as ex:
    for i, r in enumerate(ex.map(lambda b: serve.ensure_cached(str(b["edition"])), pick)):
        ok += bool(r)
        if i % 20 == 0:
            print(i, "ok", ok, flush=True)
print("done", ok, "/", len(pick))
# Static hosting manifest: editions present under assets/bears/
eds = sorted(int(f[:-5]) for f in os.listdir(serve.CACHE) if f.endswith(".webp"))
manifest = {"cached": eds, "count": len(eds)}
out = os.path.join(serve.ROOT, "assets", "cached.json")
with open(out, "w") as f:
    json.dump(manifest, f, separators=(",", ":"))
print("wrote", out, "count", len(eds))
