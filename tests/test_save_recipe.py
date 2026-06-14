import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import save_recipe as sr


def test_slugify_basic():
    assert sr.slugify("Milk-Mochi Dessert Soup") == "milk-mochi-dessert-soup"


def test_slugify_strips_punct_and_case():
    assert sr.slugify("  Beef Chow Mein!! ") == "beef-chow-mein"


def test_slugify_cjk_returns_empty():
    # Non-Latin titles slug to empty; main() then requires an explicit --slug.
    assert sr.slugify("鮮奶麻糬甜湯") == ""


def test_cookbook_markdown_structure():
    body = "dessert · ~15 min · serves 2\n\n**Ingredients:** 黑糖 30g\n\n**Steps:** 1. 煮。"
    md = sr.cookbook_markdown(
        "鮮奶麻糬甜湯", body,
        "https://www.instagram.com/reel/DUNy6_ADXyp/",
        "ball", "IG reel", "2026-06-10",
    )
    assert md.startswith("# 鮮奶麻糬甜湯\n")
    assert "**Ingredients:** 黑糖 30g" in md
    assert "**Source:** https://www.instagram.com/reel/DUNy6_ADXyp/ (IG reel, shared by ball) · saved 2026-06-10" in md
    assert md.rstrip().endswith("## Verdicts")


def test_craving_note_points_at_cookbook():
    note = sr.craving_note("鮮奶麻糬甜湯", "milk-mochi-dessert-soup", "ball", "IG reel")
    assert note == "想做鮮奶麻糬甜湯 — 已存 cookbook/milk-mochi-dessert-soup.md (ball, IG reel)"


def test_variant_skips_craving(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sr.capture, "append_note", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(sr, "COOKBOOK", tmp_path)
    monkeypatch.setattr(sys, "argv",
        ["save_recipe.py", "--title", "T", "--slug", "t-variant",
         "--source", "s", "--variant"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("body"))
    sr.main()
    assert calls == []                       # variant → NO craving queued
    assert (tmp_path / "t-variant.md").exists()


def test_nonvariant_queues_craving(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sr.capture, "append_note", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(sr, "COOKBOOK", tmp_path)
    monkeypatch.setattr(sys, "argv",
        ["save_recipe.py", "--title", "T", "--slug", "t-normal", "--source", "s"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("body"))
    sr.main()
    assert len(calls) == 1                    # normal → craving queued
