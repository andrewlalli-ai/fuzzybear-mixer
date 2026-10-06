#!/usr/bin/env python3
"""
Static server + on-demand IPFS image cache for the raebyzzuF mixer.

  python3 scripts/serve.py            # serves on 0.0.0.0:8765

GET /bear-img/<edition>.webp  -> real collection composite (512px WebP).
   Served from assets/bears/ when cached; otherwise fetched once from a
   public IPFS gateway (CID listed in data/bears.json), resized, cached.
Everything else is served as static files from the project root.
"""
import io, json, os, re, sys, threading, urllib.parse, urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "assets", "bears")
GATEWAYS = [
    "https://ipfs.filebase.io/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
    "https://ipfs.io/ipfs/",
]
SIZE = 512
os.makedirs(CACHE, exist_ok=True)

with open(os.path.join(ROOT, "data", "bears.json")) as f:
    BEARS = {str(b["edition"]): b for b in json.load(f)["bears"]}

_locks = {}
_remote = threading.BoundedSemaphore(2)  # be gentle with public gateways
_locks_guard = threading.Lock()


def cache_path(edition):
    return os.path.join(CACHE, f"{edition}.webp")


def fetch_and_cache(edition):
    """Download the composite PNG for an edition, resize, store as WebP."""
    from PIL import Image  # pillow required only for on-demand fetches
    bear = BEARS[edition]
    ipfs_path = bear["image"].replace("ipfs://", "")
    quoted = urllib.parse.quote(ipfs_path)
    last = None
    import time
    for attempt in range(3):
        for gw in GATEWAYS:
            try:
                req = urllib.request.Request(gw + quoted, headers={"User-Agent": "fuzzybear-mixer/1.0"})
                raw = urllib.request.urlopen(req, timeout=45).read()
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                im = im.resize((SIZE, SIZE), Image.LANCZOS)
                tmp = cache_path(edition) + ".tmp"
                im.save(tmp, "WEBP", quality=86, method=4)
                os.replace(tmp, cache_path(edition))
                return True
            except Exception as e:
                last = e
                if "429" in str(e) or "Too Many" in str(e):
                    time.sleep(2 * (attempt + 1))
        time.sleep(1.5 * (attempt + 1))
    print(f"[bear-img] #{edition} failed: {last}", file=sys.stderr)
    return False


def ensure_cached(edition):
    p = cache_path(edition)
    if os.path.exists(p):
        return True
    with _locks_guard:
        lock = _locks.setdefault(edition, threading.Lock())
    with lock:
        if os.path.exists(p):
            return True
        with _remote:
            return fetch_and_cache(edition)


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/api/cached":
            eds = sorted(int(f[:-5]) for f in os.listdir(CACHE) if f.endswith(".webp"))
            body = json.dumps({"cached": eds, "server": "serve.py"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        m = re.match(r"^/bear-img/(\d+)\.webp$", self.path.split("?")[0])
        if m:
            ed = m.group(1)
            if ed not in BEARS:
                return self.send_error(404, "unknown edition")
            if not ensure_cached(ed):
                return self.send_error(502, "IPFS fetch failed")
            with open(cache_path(ed), "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/webp")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=604800")
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def end_headers(self):
        if not self.path.startswith("/bear-img/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "/bear-img/" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("0.0.0.0", port), partial(Handler, directory=ROOT))
    print(f"raebyzzuF mixer on http://127.0.0.1:{port}/  ({len(BEARS)} bears indexed)")
    srv.serve_forever()
