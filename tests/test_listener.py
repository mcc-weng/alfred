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


def test_transcript_custom_timeout(tmp_path, monkeypatch):
    t = listener.Transcript(tmp_path / "chat.json", timeout=-1)  # always-expired
    t.append("user", "hi")
    assert not t.active()  # custom timeout honored, independent of RITUAL_TIMEOUT


def test_transcript_default_timeout_still_ritual(tmp_path, monkeypatch):
    t = listener.Transcript(tmp_path / "r.json")  # no timeout arg → ritual default
    t.append("user", "hi")
    monkeypatch.setattr(listener, "RITUAL_TIMEOUT", 3 * 3600)
    assert t.active()


def test_approve_trigger_detection():
    assert listener.is_approve_trigger("裝吧")
    assert listener.is_approve_trigger("全加,送出")
    assert listener.is_approve_trigger("approve cart")
    assert not listener.is_approve_trigger("我在想要不要")
    assert not listener.is_approve_trigger("我把照片送出去了")


def test_ritual_reply_returns_tuple_shape():
    """_ritual_reply is async/Discord-bound so we just verify the sentinel logic
    that underpins the tuple's second element."""
    # done=True path
    text_done = "Great plan!\n<<<RITUAL_COMPLETE>>>"
    assert listener.ritual_complete(text_done) is True
    assert "<<<" not in listener.strip_sentinel(text_done)
    # done=False path
    text_mid = "What time works for dinner?"
    assert listener.ritual_complete(text_mid) is False


def test_extract_recipe_url_instagram():
    url = "https://www.instagram.com/reel/DYXDnWfPROW/?igsh=NnBqcTR1cjVxNTky"
    assert listener.extract_recipe_url(f"看這個 {url}") == url


def test_extract_recipe_url_youtube():
    assert listener.extract_recipe_url("recipe https://youtu.be/abc123 yum") == \
        "https://youtu.be/abc123"
    assert listener.extract_recipe_url("https://www.youtube.com/shorts/xY9_z") == \
        "https://www.youtube.com/shorts/xY9_z"


def test_extract_recipe_url_none_for_non_recipe_links():
    assert listener.extract_recipe_url("今晚吃什麼?") is None
    assert listener.extract_recipe_url("see https://example.com/foo") is None


def test_format_caption_injection_carries_recipe_and_anti_anchor_guard():
    cap = {"title": "家常鹽水雞", "description": "雞腿1支、香菇、薑片", "is_thin": False}
    out = listener.format_caption_injection("https://insta/reel/x", cap)
    assert "家常鹽水雞" in out and "雞腿1支" in out      # the actual fetched recipe
    assert "聊天記錄" in out                              # anti-history-anchoring guard


def test_format_caption_injection_error_tells_brain_to_fall_back():
    out = listener.format_caption_injection("https://insta/reel/x", {"error": "login wall"})
    assert "frames" in out or "截圖" in out               # frames / ask-for-screenshot fallback


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
