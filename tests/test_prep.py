import datetime
import json
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


def test_plan_idempotent_by_date(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sched_file.write_text(json.dumps({"date": today, "cook_time": "18:30", "items": []}))
    monkeypatch.setattr(prep, "SCHED", sched_file)
    called = []
    monkeypatch.setattr(prep.brain, "run_brain", lambda *a, **k: called.append(1) or "NOTHING")
    prep.plan()
    assert called == []  # existing today schedule → brain NOT called


def test_tick_posts_due_then_marks_sent(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sched = {"date": today, "cook_time": "18:30", "plan_hash": "match",
             "items": [{"id": "a1", "due": f"{today}T00:00:00", "msg": "醃雞", "sent": False}]}
    sched_file.write_text(json.dumps(sched))
    monkeypatch.setattr(prep, "SCHED", sched_file)
    monkeypatch.setattr(prep, "_plan_hash", lambda: "match")
    posts = []
    monkeypatch.setattr(prep.subprocess, "run", lambda *a, **k: posts.append(a))
    prep.tick()
    assert len(posts) == 1                       # posted once
    after = json.loads(sched_file.read_text())
    assert after["items"][0]["sent"] is True     # marked sent
    posts.clear()
    prep.tick()
    assert posts == []                           # second run: no double-post


# --- _plan_hash ---

def test_plan_hash_empty_when_no_plans(tmp_path):
    assert prep._plan_hash(plans_dir=tmp_path) == ""


def test_plan_hash_returns_consistent_value(tmp_path):
    (tmp_path / "2026-06-15.md").write_text("some plan content")
    h = prep._plan_hash(plans_dir=tmp_path)
    assert h != ""
    assert prep._plan_hash(plans_dir=tmp_path) == h


def test_plan_hash_changes_with_content(tmp_path):
    p = tmp_path / "2026-06-15.md"
    p.write_text("content A")
    h1 = prep._plan_hash(plans_dir=tmp_path)
    p.write_text("content B")
    h2 = prep._plan_hash(plans_dir=tmp_path)
    assert h1 != h2


def test_plan_hash_picks_latest_file(tmp_path):
    import hashlib
    (tmp_path / "2026-06-07.md").write_text("old")
    (tmp_path / "2026-06-15.md").write_text("new")
    assert prep._plan_hash(plans_dir=tmp_path) == hashlib.sha1(b"new").hexdigest()


# --- _replan ---

def test_replan_marks_past_due_as_sent(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    monkeypatch.setattr(prep, "SCHED", sched_file)
    monkeypatch.setattr(prep, "_plan_hash", lambda **_: "abc")
    monkeypatch.setattr(prep, "_config", lambda: {"cook_time": "18:30"})
    monkeypatch.setattr(prep.brain, "run_brain",
                        lambda *a, **k: '[{"time":"09:00","msg":"morning prep"}]')
    sched = prep._replan(datetime.datetime(2026, 6, 21, 16, 0))
    assert sched is not None
    assert sched["items"][0]["sent"] is True   # 09:00 item past at 16:00


def test_replan_keeps_future_items_unsent(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    monkeypatch.setattr(prep, "SCHED", sched_file)
    monkeypatch.setattr(prep, "_plan_hash", lambda **_: "abc")
    monkeypatch.setattr(prep, "_config", lambda: {"cook_time": "18:30"})
    monkeypatch.setattr(prep.brain, "run_brain",
                        lambda *a, **k: '[{"time":"21:00","msg":"thaw steak"}]')
    sched = prep._replan(datetime.datetime(2026, 6, 21, 16, 0))
    assert sched is not None
    assert sched["items"][0]["sent"] is False  # 21:00 item still future at 16:00


def test_replan_returns_none_on_brain_failure(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    monkeypatch.setattr(prep, "SCHED", sched_file)
    monkeypatch.setattr(prep, "_plan_hash", lambda **_: "abc")
    monkeypatch.setattr(prep, "_config", lambda: {"cook_time": "18:30"})
    monkeypatch.setattr(prep.brain, "run_brain",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    assert prep._replan(datetime.datetime(2026, 6, 21, 16, 0)) is None


# --- tick replan integration ---

def test_tick_replans_on_hash_mismatch(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sched = {"date": today, "cook_time": "18:30", "plan_hash": "old",
             "items": [{"id": "x1", "due": f"{today}T23:00:00",
                        "msg": "wrong dish", "sent": False}]}
    sched_file.write_text(json.dumps(sched))
    monkeypatch.setattr(prep, "SCHED", sched_file)
    monkeypatch.setattr(prep, "_plan_hash", lambda: "new")
    replanned = []
    monkeypatch.setattr(prep, "_replan",
                        lambda now: replanned.append(now) or {"date": today, "items": []})
    monkeypatch.setattr(prep.subprocess, "run", lambda *a, **k: None)
    prep.tick()
    assert replanned


def test_tick_no_replan_when_hash_matches(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sched = {"date": today, "cook_time": "18:30", "plan_hash": "same", "items": []}
    sched_file.write_text(json.dumps(sched))
    monkeypatch.setattr(prep, "SCHED", sched_file)
    monkeypatch.setattr(prep, "_plan_hash", lambda: "same")
    replanned = []
    monkeypatch.setattr(prep, "_replan", lambda now: replanned.append(now))
    prep.tick()
    assert not replanned
