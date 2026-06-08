import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import capture


def test_format_line_has_date_kind_and_note():
    line = capture.format_line("2026-06-09", "verdict", "curry was a banger (Mike)")
    assert line == "- 2026-06-09 [verdict] curry was a banger (Mike)"


def test_format_line_defaults_kind_note_when_kind_omitted():
    line = capture.format_line("2026-06-09", "note", "we stopped eating pork")
    assert "[note]" in line and "we stopped eating pork" in line


def test_format_line_lesson_kind():
    line = capture.format_line("2026-06-08", "lesson", "脆皮要把皮徹底擦乾")
    assert line == "- 2026-06-08 [lesson] 脆皮要把皮徹底擦乾"


def test_append_creates_and_appends(tmp_path):
    f = tmp_path / "inbox.md"
    capture.append_note(f, "2026-06-09", "craving", "want 滷肉飯")
    capture.append_note(f, "2026-06-09", "verdict", "salmon banger")
    body = f.read_text()
    assert body.count("\n- ") == 2
    assert "want 滷肉飯" in body and "salmon banger" in body
    assert body.startswith("#")  # has a header when first created
