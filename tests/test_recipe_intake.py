import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import recipe_intake as ri

MILK_MOCHI_DESC = (
    "【年菜挑戰EP4 — 鮮奶麻糬甜湯】\n"
    "甜湯（減糖版）\n- 黑糖 30g\n- 水300g\n- 薑3-4片\n"
    "麻糬（減糖版）\n- 牛奶300g\n- 地瓜粉30g\n- 糖20g\n"
)


def test_extract_fields_full():
    info = {"title": "Milk Mochi", "uploader": "Selina",
            "duration": 32.8, "description": MILK_MOCHI_DESC}
    out = ri.extract_fields(info)
    assert out == {"title": "Milk Mochi", "uploader": "Selina",
                   "duration": 32.8, "description": MILK_MOCHI_DESC}


def test_extract_fields_falls_back_to_channel():
    info = {"title": "X", "channel": "Chef Bob", "duration": 0, "description": ""}
    assert ri.extract_fields(info)["uploader"] == "Chef Bob"


def test_is_thin_true_for_short_or_no_digits():
    assert ri.is_thin("") is True
    assert ri.is_thin("好吃！推薦給大家 yummy delicious enjoy") is True  # no digits


def test_is_thin_false_for_real_recipe():
    assert ri.is_thin(MILK_MOCHI_DESC) is False


def test_frame_timestamps_bounded_and_increasing():
    ts = ri.frame_timestamps(32.8, max_frames=8)
    assert len(ts) == 8
    assert ts == sorted(ts)
    assert all(0 < t < 32.8 for t in ts)


def test_frame_timestamps_short_clip():
    ts = ri.frame_timestamps(2.0, max_frames=10)
    assert len(ts) >= 1
    assert all(0 < t < 2.0 for t in ts)


def test_frame_timestamps_zero_duration():
    assert ri.frame_timestamps(0) == [0.0]


def test_frame_timestamps_sub_three_second_clip():
    # int(1.5 // 3) == 0, so the `or 1` guard must yield exactly one frame
    ts = ri.frame_timestamps(1.5, max_frames=10)
    assert ts == [0.75]


def test_is_thin_long_no_digit_is_thin():
    # 60+ chars but no digits → still thin (a recipe needs quantities)
    assert ri.is_thin("這是一段很長的純文字描述完全沒有任何數字只是介紹這道料理多好吃多美味多適合全家一起享用真的很棒喔") is True
