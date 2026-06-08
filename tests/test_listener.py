import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import listener


def test_ritual_trigger_detection():
    assert listener.is_ritual_trigger("ok alfred, plan the week!")
    assert listener.is_ritual_trigger("Alfred Plan please")
    assert not listener.is_ritual_trigger("planning to eat out")


def test_ritual_trigger_detection_chinese():
    assert listener.is_ritual_trigger("小當家,排菜單!")
    assert listener.is_ritual_trigger("我們來規劃這週的菜吧")
    assert not listener.is_ritual_trigger("我想規劃一下人生")
    assert not listener.is_ritual_trigger("今晚吃什麼")


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


def test_transcript_expiry(tmp_path, monkeypatch):
    t = listener.Transcript(tmp_path / "ritual.json")
    t.append("user", "hello")
    monkeypatch.setattr(listener, "RITUAL_TIMEOUT", -1)
    assert not t.active()


def test_cart_trigger_detection():
    assert listener.is_cart_trigger("小當家 裝車")
    assert listener.is_cart_trigger("fill the cart please")
    assert not listener.is_cart_trigger("車子壞了")


def test_stale_transcript_cleared_on_fresh_start(tmp_path, monkeypatch):
    t = listener.Transcript(tmp_path / "ritual.json")
    t.append("user", "old ritual turn")
    monkeypatch.setattr(listener, "RITUAL_TIMEOUT", -1)  # expire it
    assert not t.active()
    t.clear()                      # what _ritual_reply now does on fresh trigger
    monkeypatch.setattr(listener, "RITUAL_TIMEOUT", 3 * 3600)
    t.append("user", "new ritual turn")
    assert t.active()              # started was reset — second turn will route to ritual
    assert len(t.turns()) == 1     # no leaked history
