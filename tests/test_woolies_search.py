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
    assert ranked[0]["stockcode"] in (144329, 144336)
    assert ranked[-1]["stockcode"] == 38904


def test_rank_empty_query_returns_input_order():
    items = ws.parse_products(SAMPLE)
    assert [p["stockcode"] for p in ws.rank(items, "")] == [144329, 144336, 38904]
