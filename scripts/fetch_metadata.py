#!/usr/bin/env python3
"""Step 1: list every sraebyzzuF NFT via XRPL Clio `nfts_by_issuer`, then fetch
each token's IPFS metadata JSON (text only, ~1 KB each). Resumable.

Output: data/issuer_nfts.json, data/meta-cache/<nft_id>.json
"""
import json, os, time, urllib.parse, urllib.request, concurrent.futures as cf
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUER = "r3NftTqH2hv3skuWAEDWKvqnxjtuqcFWYR"
CLIO = "https://s1.ripple.com:51234"
GW = ["https://ipfs.filebase.io/ipfs/", "https://gateway.pinata.cloud/ipfs/", "https://cloudflare-ipfs.com/ipfs/"]
META = os.path.join(ROOT, "data", "meta-cache")
os.makedirs(META, exist_ok=True)


def list_nfts():
    out, marker = [], None
    while True:
        p = {"issuer": ISSUER, "limit": 400}
        if marker:
            p["marker"] = marker
        req = urllib.request.Request(CLIO, json.dumps({"method": "nfts_by_issuer", "params": [p]}).encode(),
                                     {"content-type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=60))["result"]
        out += r.get("nfts", [])
        marker = r.get("marker")
        if not marker:
            break
    for n in out:
        n["uri_str"] = bytes.fromhex(n.get("uri", "")).decode(errors="replace")
    json.dump(out, open(os.path.join(ROOT, "data", "issuer_nfts.json"), "w"))
    return out


def fetch(n):
    fn = os.path.join(META, n["nft_id"] + ".json")
    if os.path.exists(fn):
        return "cached"
    path = urllib.parse.quote(n["uri_str"].replace("ipfs://", ""))
    for attempt in range(4):
        for g in GW:
            try:
                raw = urllib.request.urlopen(urllib.request.Request(g + path, headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read()
                json.loads(raw)
                open(fn, "wb").write(raw)
                return "ok"
            except Exception:
                pass
        time.sleep(3 * (attempt + 1))
    return "fail"


if __name__ == "__main__":
    nfts = [n for n in list_nfts() if not n["is_burned"]]
    print(len(nfts), "live NFTs")
    c = Counter()
    with cf.ThreadPoolExecutor(6) as ex:
        for i, r in enumerate(ex.map(fetch, nfts)):
            c[r] += 1
            if i % 100 == 0:
                print(i, dict(c), flush=True)
    print("done", dict(c))
