import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
from discord_io import split_message


def test_short_message_is_single_chunk():
    assert split_message("hello") == ["hello"]


def test_splits_at_newline_before_limit():
    text = "a" * 1500 + "\n" + "b" * 1000
    chunks = split_message(text)
    assert chunks == ["a" * 1500, "b" * 1000]


def test_all_chunks_within_limit():
    text = ("line of recipe text\n" * 400).strip()
    assert all(len(c) <= 2000 for c in split_message(text))


def test_hard_split_when_no_newline():
    chunks = split_message("x" * 4500)
    assert [len(c) for c in chunks] == [2000, 2000, 500]


def test_empty_text_returns_no_chunks():
    assert split_message("") == []
