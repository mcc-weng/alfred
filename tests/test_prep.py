import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import prep


def test_item_id_stable_and_distinct():
    assert prep.item_id("醃雞") == prep.item_id("醃雞")
    assert prep.item_id("醃雞") != prep.item_id("回溫")


def test_clock_to_due():
    assert prep.clock_to_due("2026-06-15", "17:50") == "2026-06-15T17:50:00"


def test_build_schedule():
    sched = prep.build_schedule(
        "2026-06-15", "18:30",
        [{"time": "09:00", "msg": "醃雞"}, {"time": "17:50", "msg": "回溫"}])
    assert sched["date"] == "2026-06-15"
    assert sched["cook_time"] == "18:30"
    assert len(sched["items"]) == 2
    assert sched["items"][0]["due"] == "2026-06-15T09:00:00"
    assert sched["items"][0]["sent"] is False
    assert sched["items"][0]["id"] == prep.item_id("醃雞")


def test_parse_plan_output_nothing():
    assert prep.parse_plan_output("NOTHING") == []
    assert prep.parse_plan_output("  nothing.\n") == []
    assert prep.parse_plan_output("") == []


def test_parse_plan_output_json():
    assert prep.parse_plan_output('[{"time":"09:00","msg":"醃雞"}]') == \
        [{"time": "09:00", "msg": "醃雞"}]


def test_parse_plan_output_fenced():
    out = '```json\n[{"time":"09:00","msg":"醃雞"}]\n```'
    assert prep.parse_plan_output(out) == [{"time": "09:00", "msg": "醃雞"}]


def test_due_items_grace_window():
    sched = prep.build_schedule("2026-06-15", "18:30",
                                [{"time": "17:50", "msg": "回溫"}])
    early = datetime.datetime(2026, 6, 15, 17, 30)   # 20m before → outside 15m grace
    within = datetime.datetime(2026, 6, 15, 17, 40)  # 10m before → inside grace
    assert prep.due_items(sched, early, 15) == []
    assert len(prep.due_items(sched, within, 15)) == 1


def test_due_items_skips_sent():
    sched = prep.build_schedule("2026-06-15", "18:30",
                                [{"time": "09:00", "msg": "醃雞"}])
    sched["items"][0]["sent"] = True
    now = datetime.datetime(2026, 6, 15, 9, 0)
    assert prep.due_items(sched, now, 15) == []
