import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import listener


def test_ritual_trigger_detection():
    assert listener.is_ritual_trigger("ok alfred, plan the week!")
    assert listener.is_ritual_trigger("Alfred Plan please")
    assert not listener.is_ritual_trigger("planning to eat out")


def test_sentinel_detection_and_strip():
    text = "All posted. Enjoy the week!\n<<<RITUAL_COMPLETE>>>"
    assert listener.ritual_complete(text)
    assert "<<<" not in listener.strip_sentinel(text)
    assert not listener.ritual_complete("normal reply")


def test_transcript_roundtrip(tmp_path):
    t = listener.Transcript(tmp_path / "ritual.json")
    assert not t.active()
    t.append("user", "Mike: plan the week")
    t.append("assistant", "Here's what I see…")
    t2 = listener.Transcript(tmp_path / "ritual.json")
    assert t2.active() and len(t2.turns()) == 2
    t2.clear()
    assert not listener.Transcript(tmp_path / "ritual.json").active()


def test_transcript_history_format():
    turns = [{"role": "user", "content": "Mike: hi"},
             {"role": "assistant", "content": "Hello!"}]
    rendered = listener.render_turns(turns)
    assert rendered == "Mike: hi\nAlfred: Hello!"
