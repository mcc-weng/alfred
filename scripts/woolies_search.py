# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Woolworths product search (public API, stdlib). Read-only, no auth.

Usage: uv run scripts/woolies_search.py "brown onion" [--limit 5]
Prints ranked candidates as JSON. Used by `cart` mode to match list lines → SKUs.
"""
import argparse
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request

API = "https://www.woolworths.com.au/apis/ui/Search/products"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _opener():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", UA), ("Accept", "application/json, text/plain, */*")]
    return op


def fetch(term: str, page_size: int = 24) -> dict:
    op = _opener()
    op.open("https://www.woolworths.com.au/", timeout=25)  # prime cookies
    url = f"{API}?searchTerm={urllib.parse.quote(term)}&pageSize={page_size}"
    with op.open(url, timeout=25) as r:
        return json.load(r)


def parse_products(data: dict) -> list[dict]:
    out = []
    for group in data.get("Products") or []:
        for p in group.get("Products") or []:
            if not p.get("IsAvailable"):
                continue
            out.append({"stockcode": p.get("Stockcode"),
                        "name": (p.get("DisplayName") or "").strip(),
                        "price": p.get("Price"),
                        "pack": p.get("PackageSize"),
                        "available": True})
    return out


_TOKEN = re.compile(r"[a-z0-9]+")
_NOISE = ("gravy", "mix", "flavour", "flavoured", "stock", "seasoning", "chips", "snack")


def _score(name: str, terms: list[str]) -> float:
    toks = set(_TOKEN.findall(name.lower()))
    overlap = sum(1 for t in terms if t in toks)
    noise = sum(1 for n in _NOISE if n in name.lower())
    return overlap - 0.5 * noise


def rank(items: list[dict], query: str) -> list[dict]:
    terms = _TOKEN.findall(query.lower())
    if not terms:
        return list(items)
    return sorted(items, key=lambda p: _score(p["name"], terms), reverse=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("term")
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()
    ranked = rank(parse_products(fetch(a.term)), a.term)[: a.limit]
    json.dump(ranked, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
