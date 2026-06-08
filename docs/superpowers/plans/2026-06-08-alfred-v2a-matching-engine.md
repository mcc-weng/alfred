# Alfred v2a — Cart Matching & Proposal Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the Sunday ritual, 小當家 matches every shopping-list line to a real product, runs the free-delivery threshold optimizer, proposes both carts in Discord, posts a working Asian Pantry cart permalink, and writes `state/carts/pending.json` for the (Plan B) fill to consume.

**Architecture:** Three pure-ish units behind the existing daemon — `woolies_search.py` (HTTP product search), `asianpantry.py` (Shopify catalog + permalink), `cart_logic.py` (threshold math + cart assembly) — orchestrated by a new `cart` brain mode the listener spawns. No browser in this plan: Woolies is read-only HTTP search; Asian Pantry fulfillment is a permalink URL. The Woolies *fill* is Plan B.

**Tech Stack:** Python 3.11+ stdlib (`urllib`) via `uv run`, pytest, the existing `brain.py`/`listener.py`/`discord_io.py` from v1.5.

**Spec:** `docs/superpowers/specs/2026-06-08-alfred-v2-two-cart-design.md`

---

## Shared data contract — `state/carts/pending.json`

Both plans use this. Written by `cart` mode (this plan), consumed by the fill (Plan B).

```json
{
  "week_of": "2026-06-15",
  "created": "2026-06-08T12:00:00",
  "status": "proposed",
  "woolies": {
    "fulfillment": "delivery-trial",
    "threshold": 75,
    "est_subtotal": 96.40,
    "items": [
      {"stockcode": 144329, "name": "Onion Brown each", "qty": 1,
       "price": 0.63, "matched_from": "1 brown onion", "confidence": "high"}
    ],
    "fill_result": null
  },
  "asianpantry": {
    "threshold": 130,
    "est_subtotal": 112.00,
    "permalink": "https://asianpantry.com.au/cart/12345:2,67890:1",
    "items": [
      {"variant_id": 12345, "title": "Erawan Tapioca Starch 500g", "qty": 2,
       "price": 4.40, "matched_from": "樹薯粉", "confidence": "high"}
    ]
  },
  "fresh_asian": ["豬血 ~250g", "胡椒鹽"]
}
```

`status`: `proposed` → `approved` (Plan A) → `filled` | `failed` (Plan B).

---

## File structure

```
alfred/
├── scripts/
│   ├── woolies_search.py      # HTTP product search → ranked candidates
│   ├── asianpantry.py         # Shopify search + cart permalink builder
│   └── cart_logic.py          # threshold optimizer + pending.json assembly/validate
├── prompts/cart.md            # the `cart` brain-mode prompt
├── state/
│   ├── asianpantry.md         # learned ingredient → variant map
│   ├── buffer.md              # standing top-up candidates (humans edit)
│   └── carts/                 # pending.json lives here (gitignored content, dir kept)
├── tests/
│   ├── test_woolies_search.py
│   ├── test_asianpantry.py
│   └── test_cart_logic.py
└── (modified) config.json, scripts/brain.py, scripts/listener.py,
    .claude/skills/plan-week/SKILL.md, .claude/settings.json, .gitignore
```

---

### Task 1: Config, state scaffolding, `.env` hardening

**Files:**
- Modify: `config.json`, `.gitignore`
- Create: `state/buffer.md`, `state/asianpantry.md`, `state/carts/.gitkeep`,
  `.claude/settings.json` (or modify if exists)

- [ ] **Step 1: Add config keys** — in `config.json`, after `"ritual_timeout_hours"`:

```json
  "thresholds": {"woolies": 75, "asianpantry": 130},
  "woolies_fulfillment": "delivery-trial"
```

- [ ] **Step 2: Create `state/buffer.md`:**

```markdown
# Top-up buffer — standing candidates 小當家 may PROPOSE to reach free-delivery
<!-- Humans edit freely. Never auto-added; only proposed when a cart is under
     threshold, and only with a Discord yes. Prefer non-perishable / always-used. -->

## Woolworths
- Jasmine rice 5kg · olive oil · free-range eggs · milk · paper towels

## Asian Pantry
- 醬油(soy) · 蠔油(oyster) · 麻油(sesame oil) · 米酒(shaoxing) · 冷凍餛飩 · 乾香菇
```

- [ ] **Step 3: Create `state/asianpantry.md`:**

```markdown
# Asian Pantry product map (Shopify)
<!-- Learned from corrections. ingredient → variant_id | title | notes -->

| Ingredient | variant_id | Product title | Notes |
|---|---|---|---|
| 樹薯粉 | 32916083015779 | Erawan Tapioca Starch 500g | example — replace |
```

- [ ] **Step 4: Create `state/carts/.gitkeep`** (empty) and add to `.gitignore`:

```gitignore
state/carts/pending.json
```

- [ ] **Step 5: Harden `.claude/settings.json`** — deny brains read access to secrets. If the file exists, merge the `deny` entry; else create:

```json
{
  "permissions": {
    "deny": ["Read(./.env)", "Read(.env)"]
  }
}
```

- [ ] **Step 6: Commit**

```bash
mkdir -p state/carts && touch state/carts/.gitkeep
git add config.json .gitignore state/buffer.md state/asianpantry.md state/carts/.gitkeep .claude/settings.json
git commit -m "feat(v2a): config thresholds, buffer/asianpantry maps, carts dir, deny brain .env read"
```

---

### Task 2: `woolies_search.py` — HTTP product search (TDD the parser/ranker)

**Files:**
- Create: `scripts/woolies_search.py`
- Test: `tests/test_woolies_search.py`

Network calls aren't unit-tested; the **parse + rank** logic is. A captured API
response fixture drives the tests.

- [ ] **Step 1: Write failing tests** — `tests/test_woolies_search.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import woolies_search as ws

# Minimal shape of the real /apis/ui/Search/products response (verified 2026-06-08)
SAMPLE = {"Products": [
    {"Products": [{"Stockcode": 144329, "DisplayName": "Onion Brown each",
                   "Price": 0.63, "PackageSize": "each", "IsAvailable": True}]},
    {"Products": [{"Stockcode": 144336, "DisplayName": "Woolworths Onion Brown Bag 1kg",
                   "Price": 3.6, "PackageSize": "1kg", "IsAvailable": True}]},
    {"Products": [{"Stockcode": 38904, "DisplayName": "Gravox Brown Onion Gravy Mix Tin 120g",
                   "Price": 3.5, "PackageSize": "120g", "IsAvailable": True}]},
]}


def test_parse_extracts_flat_products():
    items = ws.parse_products(SAMPLE)
    assert len(items) == 3
    assert items[0] == {"stockcode": 144329, "name": "Onion Brown each",
                        "price": 0.63, "pack": "each", "available": True}


def test_parse_skips_unavailable():
    data = {"Products": [{"Products": [
        {"Stockcode": 1, "DisplayName": "X", "Price": 1, "PackageSize": "ea", "IsAvailable": False}]}]}
    assert ws.parse_products(data) == []


def test_rank_prefers_name_token_overlap_over_gravy():
    items = ws.parse_products(SAMPLE)
    ranked = ws.rank(items, "brown onion")
    # gravy mix must not outrank actual onions
    assert ranked[0]["stockcode"] in (144329, 144336)
    assert ranked[-1]["stockcode"] == 38904


def test_rank_empty_query_returns_input_order():
    items = ws.parse_products(SAMPLE)
    assert [p["stockcode"] for p in ws.rank(items, "")] == [144329, 144336, 38904]
```

- [ ] **Step 2: Run, verify fail** — `uv run --with pytest pytest tests/test_woolies_search.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Create `scripts/woolies_search.py`:**

```python
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
# down-rank obvious non-ingredient matches (sauces/mixes when you wanted produce)
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
```

- [ ] **Step 4: Run tests** — `uv run --with pytest pytest tests/test_woolies_search.py -v` → 4 passed

- [ ] **Step 5: Live smoke** — `uv run scripts/woolies_search.py "brown onion" --limit 3` → JSON with real onion SKUs (onions ranked above gravy). If the API returns Access-Denied HTML, report it (the read path may need the browser; that escalates to Plan B) — do not retry >2×.

- [ ] **Step 6: Commit**

```bash
git add scripts/woolies_search.py tests/test_woolies_search.py
git commit -m "feat(v2a): woolworths http product search with tested parse+rank"
```

---

### Task 3: `asianpantry.py` — Shopify search + permalink (TDD)

**Files:**
- Create: `scripts/asianpantry.py`
- Test: `tests/test_asianpantry.py`

- [ ] **Step 1: Write failing tests** — `tests/test_asianpantry.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import asianpantry as ap

SUGGEST = {"resources": {"results": {"products": [
    {"title": "Erawan Tapioca Starch 500g", "handle": "erawan-tapioca-starch-500g"},
    {"title": "Acecook Maruuma Wonton Noodle 58g", "handle": "acecook-wonton"},
]}}}


def test_parse_suggest_titles():
    items = ap.parse_suggest(SUGGEST)
    assert items[0]["title"] == "Erawan Tapioca Starch 500g"
    assert items[0]["handle"] == "erawan-tapioca-starch-500g"


def test_permalink_single_item():
    assert ap.permalink([(12345, 2)]) == "https://asianpantry.com.au/cart/12345:2"


def test_permalink_multi_item():
    url = ap.permalink([(12345, 2), (67890, 1)])
    assert url == "https://asianpantry.com.au/cart/12345:2,67890:1"


def test_permalink_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        ap.permalink([])
```

- [ ] **Step 2: Run, verify fail** — `uv run --with pytest pytest tests/test_asianpantry.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Create `scripts/asianpantry.py`:**

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Asian Pantry (Shopify) catalog client + cart permalink builder. stdlib.

Usage:
  uv run scripts/asianpantry.py search "tapioca starch" [--limit 5]
  uv run scripts/asianpantry.py permalink 12345:2 67890:1
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

BASE = "https://asianpantry.com.au"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1"


def _get(path: str):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def parse_suggest(data: dict) -> list[dict]:
    prods = data.get("resources", {}).get("results", {}).get("products", []) or []
    return [{"title": p["title"], "handle": p["handle"]} for p in prods]


def search(term: str, limit: int = 5) -> list[dict]:
    q = urllib.parse.quote(term)
    data = _get(f"/search/suggest.json?q={q}&resources[type]=product&resources[limit]={limit}")
    items = parse_suggest(data)
    # enrich with first variant id + price via the product .js endpoint
    out = []
    for it in items:
        try:
            pj = _get(f"/products/{it['handle']}.js")
            v = pj["variants"][0]
            out.append({"variant_id": v["id"], "title": pj["title"],
                        "price": float(v["price"]) / 100, "available": v["available"]})
        except Exception:
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
```

- [ ] **Step 4: Run tests** — `uv run --with pytest pytest tests/test_asianpantry.py -v` → 4 passed

- [ ] **Step 5: Live smoke** — `uv run scripts/asianpantry.py search "tapioca starch" --limit 3` → JSON with variant_id + price; `uv run scripts/asianpantry.py permalink 32916083015779:2` → a `/cart/...` URL.

- [ ] **Step 6: Commit**

```bash
git add scripts/asianpantry.py tests/test_asianpantry.py
git commit -m "feat(v2a): asian pantry shopify search + cart permalink builder"
```

---

### Task 4: `cart_logic.py` — threshold optimizer + pending.json (TDD)

**Files:**
- Create: `scripts/cart_logic.py`
- Test: `tests/test_cart_logic.py`

- [ ] **Step 1: Write failing tests** — `tests/test_cart_logic.py`:

```python
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import cart_logic as cl


def test_subtotal_sums_qty_times_price():
    items = [{"qty": 2, "price": 4.40}, {"qty": 1, "price": 3.60}]
    assert cl.subtotal(items) == 12.40


def test_under_threshold_reports_gap():
    s = cl.threshold_status(112.0, 130)
    assert s["met"] is False and s["gap"] == 18.0


def test_at_or_over_threshold_met():
    assert cl.threshold_status(96.4, 75)["met"] is True
    assert cl.threshold_status(75.0, 75)["met"] is True


def test_validate_pending_requires_core_keys():
    good = {"week_of": "2026-06-15", "status": "proposed",
            "woolies": {"items": [], "threshold": 75},
            "asianpantry": {"items": [], "threshold": 130, "permalink": None},
            "fresh_asian": []}
    cl.validate_pending(good)  # no raise


def test_validate_pending_rejects_missing_section():
    import pytest
    with pytest.raises(ValueError):
        cl.validate_pending({"week_of": "x", "status": "proposed"})


def test_validate_pending_rejects_bad_status():
    import pytest
    bad = {"week_of": "x", "status": "checkout",  # forbidden
           "woolies": {"items": [], "threshold": 75},
           "asianpantry": {"items": [], "threshold": 130, "permalink": None},
           "fresh_asian": []}
    with pytest.raises(ValueError):
        cl.validate_pending(bad)
```

- [ ] **Step 2: Run, verify fail** — `uv run --with pytest pytest tests/test_cart_logic.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Create `scripts/cart_logic.py`:**

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pure cart logic: subtotal, threshold status, pending.json validation.

No I/O beyond the optional load/save helpers. Imported by `cart` mode and Plan B.
"""
import json
import pathlib

VALID_STATUS = {"proposed", "approved", "filled", "failed"}
REQUIRED = ("week_of", "status", "woolies", "asianpantry", "fresh_asian")


def subtotal(items: list[dict]) -> float:
    return round(sum(i["qty"] * i["price"] for i in items), 2)


def threshold_status(sub: float, threshold: int) -> dict:
    met = sub >= threshold
    return {"met": met, "gap": round(max(0.0, threshold - sub), 2)}


def validate_pending(p: dict) -> None:
    missing = [k for k in REQUIRED if k not in p]
    if missing:
        raise ValueError(f"pending.json missing keys: {missing}")
    if p["status"] not in VALID_STATUS:
        raise ValueError(f"bad status {p['status']!r}; allowed {sorted(VALID_STATUS)}")
    for section in ("woolies", "asianpantry"):
        if "items" not in p[section] or "threshold" not in p[section]:
            raise ValueError(f"{section} needs items + threshold")


def save_pending(p: dict, path: pathlib.Path) -> None:
    validate_pending(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p, ensure_ascii=False, indent=1))


def load_pending(path: pathlib.Path) -> dict:
    p = json.loads(path.read_text())
    validate_pending(p)
    return p
```

- [ ] **Step 4: Run tests** — `uv run --with pytest pytest tests/test_cart_logic.py -v` → 6 passed; full suite `uv run --with pytest --with discord.py pytest tests/ -v` still green.

- [ ] **Step 5: Commit**

```bash
git add scripts/cart_logic.py tests/test_cart_logic.py
git commit -m "feat(v2a): pure cart logic — subtotal, threshold status, pending.json schema"
```

---

### Task 5: `cart` brain mode — prompt + brain wiring + listener routing

**Files:**
- Create: `prompts/cart.md`
- Modify: `scripts/brain.py` (mode args), `scripts/listener.py` (routing + trigger)
- Test: extend `tests/test_listener.py`

- [ ] **Step 1: Create `prompts/cart.md`:**

```markdown
你是「小當家」🔥,進入「裝購物車」模式。剛鎖定的菜單採買清單已分好 channel
標籤(woolies / asianpantry / fresh-asian)。你的任務(全程繁體中文回覆):

1. 對每個 `woolies` 項目:先查 `state/woolworths.md`;沒有就跑
   `uv run scripts/woolies_search.py "<英文搜尋詞>" --limit 5`,選最合適的真實
   商品(對的份量/包裝)。把不確定的標記出來。
2. 對每個 `asianpantry` 項目:先查 `state/asianpantry.md`;沒有就跑
   `uv run scripts/asianpantry.py search "<詞>" --limit 5`,選最合適的 variant。
3. 算兩邊的 est_subtotal,跟門檻比(config 的 thresholds;woolies 若
   fulfillment=pickup 則只需 $50)。不足門檻 → 從 `state/buffer.md` + 本週聊天
   裡「快用完了」的東西,**提案**加購到剛好過門檻,問 Mike 要不要(只提案,
   絕不自動加)。
4. Asian Pantry:用 `uv run scripts/asianpantry.py permalink <vid:qty> …` 產生
   購物車連結。
5. 把結果寫進 `state/carts/pending.json`(用 cart_logic 的 schema,status:
   先 "proposed",Mike 同意加購後改 "approved")。fresh-asian 原樣放進
   fresh_asian 陣列。
6. 回報到 #小當家的廚房(stdout 即回覆):兩個 cart 的品項數、est 小計、門檻狀態、
   不確定的對應、加購提案、以及 Asian Pantry 的 permalink(可直接手機點)。
   Woolies 的實際裝車是分開的(Plan B);這裡只到「提案+寫檔」。

規則:絕不結帳。絕不自動加購。看不懂的對應就標記讓 Mike 決定。採買清單品項名
保持英文(Woolies app 搜尋用)。
```

- [ ] **Step 2: Add `cart` mode to `brain.py`** — in `mode_args`, before the chat default:

```python
    if mode == "cart":
        return ["--model", cfg.get("cart_model", cfg.get("ritual_model", "sonnet")),
                "--allowedTools",
                "Read,Glob,Grep,Write,Edit,"
                "Bash(uv run scripts/woolies_search.py:*),"
                "Bash(uv run scripts/asianpantry.py:*)"]
```

Add `"nudge"`/`"cart"` to the `TIMEOUT` dict: `"cart": 900`.

- [ ] **Step 3: Add cart trigger + routing to `listener.py`** — extend the trigger regex and add a cart branch. Add near `TRIGGER`:

```python
CART_TRIGGER = re.compile(r"裝車|裝購物車|fill the cart", re.IGNORECASE)


def is_cart_trigger(text: str) -> bool:
    return bool(CART_TRIGGER.search(text))
```

In `_handle`, before the ritual/chat branch, add (mirrors `_ritual_reply` but one-shot, no transcript):

```python
        if any(is_cart_trigger(l["content"]) for l in lines):
            reply = await asyncio.to_thread(
                brain.run_brain, "cart",
                await self._recent_history(channel, exclude={m.id for m in batch}),
                lines)
            for chunk in split_message(reply):
                await channel.send(chunk)
            self._mark_seen(batch[-1].id)
            return
```

- [ ] **Step 4: Add tests to `tests/test_listener.py`:**

```python
def test_cart_trigger_detection():
    assert listener.is_cart_trigger("小當家 裝車")
    assert listener.is_cart_trigger("fill the cart please")
    assert not listener.is_cart_trigger("車子壞了")
```

- [ ] **Step 5: Run tests** — `uv run --with pytest --with discord.py pytest tests/ -v` → all green (prior + new cart trigger test).

- [ ] **Step 6: Commit**

```bash
git add prompts/cart.md scripts/brain.py scripts/listener.py tests/test_listener.py
git commit -m "feat(v2a): cart brain mode — match, optimize, propose, write pending.json"
```

---

### Task 6: Ritual channel-split tagging

**Files:**
- Modify: `.claude/skills/plan-week/SKILL.md`

- [ ] **Step 1: Add tagging to the shopping-list step.** In SKILL.md's shopping-list section (Step 6), append:

```markdown
**Channel tags (v2):** tag every shopping-list line with its source channel —
`[woolies]` (mainstream groceries), `[asianpantry]` (dry/frozen Asian pantry —
sauces, starches, noodles, 米, 冷凍餛飩), or `[fresh-asian]` (same-day fresh or
not sold online — 豬血, fresh 油條, live seafood → human Box Hill trip). When
unsure between woolies and asianpantry, prefer `[asianpantry]` for Asian-specific
SKUs, `[woolies]` for everything mainstream. These tags drive `cart` mode's
matching; fresh-asian items are listed for a human pickup, never auto-matched.
```

- [ ] **Step 2: Verify** — `grep -c "Channel tags" .claude/skills/plan-week/SKILL.md` → 1; frontmatter + the 3 format fences still intact (`grep -c '^## Step' …` unchanged).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/plan-week/SKILL.md
git commit -m "feat(v2a): ritual tags shopping lines woolies/asianpantry/fresh-asian"
```

---

### Task 7: Live acceptance (with Mike)

No new files — exercises the whole engine against the real APIs.

- [ ] **Step 1: Restart daemon** to load the new mode: `pkill -f listener.py`, wait 40s, `grep -c READY .runtime/listener.log` increased, `.runtime/listener.err` clean.

- [ ] **Step 2: Trigger cart mode** — using this week's existing plan (`state/plans/2026-06-07.md`), post 「裝車」in `#小當家的廚房`. Within ~1–2 min expect a reply with: Woolies item count + est subtotal + threshold status; Asian Pantry items + a **tappable permalink**; any low-confidence matches flagged; top-up proposal if under threshold.

- [ ] **Step 3: Verify the permalink** — tap the Asian Pantry link on a phone; confirm it opens a pre-filled cart with the right items/qtys.

- [ ] **Step 4: Verify pending.json** — `uv run --with pytest python -c "import sys; sys.path.insert(0,'scripts'); import cart_logic, pathlib; cart_logic.load_pending(pathlib.Path('state/carts/pending.json')); print('valid')"` → `valid`.

- [ ] **Step 5: Spec-criteria check** — Asian Pantry is fully usable end-to-end now (criterion: 亞超 trips reduced); Woolies has a correct SKU list awaiting Plan B's fill. Note any mismatches → they become `state/woolworths.md` / `state/asianpantry.md` corrections (harvested next ritual).

- [ ] **Step 6: Commit any map seeds**

```bash
git add state/
git commit -m "ritual: v2a acceptance — first cart proposal + AP permalink"
```

---

## Self-review (spec coverage)

| Spec element | Task |
|---|---|
| Autonomous matching (Woolies HTTP search) | Task 2 |
| Asian Pantry Shopify search + permalink | Task 3 |
| Threshold optimizer (live for AP; est for Woolies) | Task 4 + cart prompt (Task 5) |
| `pending.json` shared contract | Task 4 (schema) + Task 5 (writer) |
| Propose-first top-ups from buffer/chat | Task 1 (buffer.md) + Task 5 (prompt) |
| `cart` brain mode + trigger | Task 5 |
| Channel split tags | Task 6 |
| `.env` denied to brains | Task 1 |
| Learned maps (woolworths/asianpantry) | Task 1 + existing harvest loop |
| **Woolies fill / dark-wake / launchd** | **Plan B (separate)** |
