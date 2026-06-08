# /// script
# requires-python = ">=3.11"
# dependencies = ["certifi"]
# ///
"""Asian Pantry (Shopify) catalog client + cart permalink builder.

Usage:
  uv run scripts/asianpantry.py search "tapioca starch" [--limit 5]
  uv run scripts/asianpantry.py permalink 12345:2 67890:1
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://asianpantry.com.au"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1"

# macOS: use certifi certs if available, else fall back to default context
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()


def _get(path: str):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as r:
        return json.load(r)


def parse_suggest(data: dict) -> list[dict]:
    prods = data.get("resources", {}).get("results", {}).get("products", []) or []
    return [{"title": p["title"], "handle": p["handle"]} for p in prods]


def search(term: str, limit: int = 5) -> list[dict]:
    q = urllib.parse.quote(term)
    data = _get(f"/search/suggest.json?q={q}&resources[type]=product&resources[limit]={limit}")
    items = parse_suggest(data)
    out = []
    for it in items:
        try:
            pj = _get(f"/products/{it['handle']}.js")
            v = pj["variants"][0]
            out.append({"variant_id": v["id"], "title": pj["title"],
                        "price": float(v["price"]) / 100, "available": v["available"]})
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, ValueError):
            continue
    return out


def permalink(pairs: list[tuple[int, int]]) -> str:
    if not pairs:
        raise ValueError("permalink needs at least one (variant_id, qty)")
    body = ",".join(f"{vid}:{qty}" for vid, qty in pairs)
    return f"{BASE}/cart/{body}"


def main() -> None:
    ap_ = argparse.ArgumentParser()
    sub = ap_.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("term"); s.add_argument("--limit", type=int, default=5)
    p = sub.add_parser("permalink"); p.add_argument("pairs", nargs="+", help="variant:qty …")
    a = ap_.parse_args()
    if a.cmd == "search":
        json.dump(search(a.term, a.limit), sys.stdout, ensure_ascii=False, indent=1); print()
    else:
        pairs = [(int(x.split(":")[0]), int(x.split(":")[1])) for x in a.pairs]
        print(permalink(pairs))


if __name__ == "__main__":
    main()
