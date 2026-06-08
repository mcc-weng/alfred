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
