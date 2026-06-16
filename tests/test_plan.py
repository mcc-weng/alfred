import datetime
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import plan

PLAN = """# 週菜單 Jun 15–21, 2026

| 天 | 料理 | 模式 | 時間 | 每份營養* |
|---|---|---|---|---|
| 週一 Mon | 蔥香雞腿 + 番茄炒蛋 | fast | 35分 | ~42P / 640kcal |
| 週二 Tue | 三杯雞 + 白飯 | play | 35分 | ~50P / 810kcal |
| 週三 Wed | 牛排 | play | 30分 | ~46P / 540kcal |
| 週日 Sun | 外食 | — | — | — |

## Reasoning
- 週一: fast 開週，清爽暖場
- 週二: play — 三杯雞，本週絕學：收汁與醬感判斷
- 週三: play — 牛排，上週 banger 技巧重現
"""


def test_swap_table_rows_exchanges_content_keeps_labels():
    out = plan.swap_text(PLAN, "週二", "週三")
    lines = out.split("\n")
    tue = next(l for l in lines if l.startswith("| 週二 Tue"))
    wed = next(l for l in lines if l.startswith("| 週三 Wed"))
    # day labels stay put; content swapped
    assert "牛排" in tue and "30分" in tue and "~46P / 540kcal" in tue
    assert "三杯雞" in wed and "35分" in wed and "~50P / 810kcal" in wed


def test_swap_leaves_other_days_untouched():
    out = plan.swap_text(PLAN, "週二", "週三")
    lines = out.split("\n")
    assert "| 週一 Mon | 蔥香雞腿 + 番茄炒蛋 | fast | 35分 | ~42P / 640kcal |" in lines
    assert "| 週日 Sun | 外食 | — | — | — |" in lines


def test_swap_exchanges_reasoning_bullets():
    out = plan.swap_text(PLAN, "週二", "週三")
    lines = out.split("\n")
    r_tue = next(l for l in lines if l.startswith("- 週二:"))
    r_wed = next(l for l in lines if l.startswith("- 週三:"))
    assert "牛排" in r_tue and "banger" in r_tue
    assert "三杯雞" in r_wed and "收汁" in r_wed


def test_swap_then_swap_back_is_identity():
    once = plan.swap_text(PLAN, "週二", "週三")
    twice = plan.swap_text(once, "週二", "週三")
    assert twice == PLAN


def test_selector_by_dish_substring():
    out = plan.swap_text(PLAN, "牛排", "三杯雞")
    tue = next(l for l in out.split("\n") if l.startswith("| 週二 Tue"))
    assert "牛排" in tue


def test_selector_english_full_name():
    out = plan.swap_text(PLAN, "Tuesday", "Wednesday")
    wed = next(l for l in out.split("\n") if l.startswith("| 週三 Wed"))
    assert "三杯雞" in wed


def test_selector_unknown_raises():
    with pytest.raises(ValueError, match="找不到"):
        plan.swap_text(PLAN, "週六", "週二")


def test_selector_ambiguous_raises():
    # "雞" appears in both 週一 蔥香雞腿 and 週二 三杯雞
    with pytest.raises(ValueError, match="不只一天"):
        plan.swap_text(PLAN, "雞", "週三")


def test_selector_same_row_raises():
    with pytest.raises(ValueError, match="同一天"):
        plan.swap_text(PLAN, "週二", "三杯雞")


def _write_plan(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


def test_latest_plan_path_picks_newest(tmp_path):
    _write_plan(tmp_path, "2026-06-07.md", "old")
    _write_plan(tmp_path, "2026-06-15.md", "new")
    assert plan.latest_plan_path(tmp_path).name == "2026-06-15.md"


def test_plan_date_parses_filename(tmp_path):
    p = _write_plan(tmp_path, "2026-06-15.md", "x")
    assert plan.plan_date(p) == datetime.date(2026, 6, 15)


def test_swap_writes_swapped_content_no_commit(tmp_path):
    _write_plan(tmp_path, "2026-06-15.md", PLAN)
    plan.swap("週二", "週三", plans_dir=tmp_path,
              today=datetime.date(2026, 6, 16), do_commit=False)
    out = (tmp_path / "2026-06-15.md").read_text()
    tue = next(l for l in out.split("\n") if l.startswith("| 週二 Tue"))
    assert "牛排" in tue


def test_swap_refuses_stale_plan(tmp_path):
    _write_plan(tmp_path, "2026-06-01.md", PLAN)
    with pytest.raises(SystemExit):
        plan.swap("週二", "週三", plans_dir=tmp_path,
                  today=datetime.date(2026, 6, 30), do_commit=False)


def test_main_requires_three_args(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["plan.py", "swap", "週二"])
    with pytest.raises(SystemExit):
        plan.main()


def test_main_unknown_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["plan.py", "frobnicate"])
    with pytest.raises(SystemExit):
        plan.main()
