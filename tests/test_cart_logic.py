import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import cart_logic as cl


def test_subtotal_sums_qty_times_price():
    items = [{"qty": 2, "price": 4.40}, {"qty": 1, "price": 3.60}]
    assert cl.subtotal(items) == 12.40


def test_under_threshold_reports_gap():
    s = cl.threshold_status(112.0, 130)
    assert s["met"] is False and s["gap"] == 18.0


def test_at_or_over_threshold_met():
    assert cl.threshold_status(96.4, 75)["met"] is True
    assert cl.threshold_status(75.0, 75)["met"] is True


def test_validate_pending_requires_core_keys():
    good = {"week_of": "2026-06-15", "status": "proposed",
            "woolies": {"items": [], "threshold": 75},
            "asianpantry": {"items": [], "threshold": 130, "permalink": None},
            "fresh_asian": []}
    cl.validate_pending(good)  # no raise


def test_validate_pending_rejects_missing_section():
    import pytest
    with pytest.raises(ValueError):
        cl.validate_pending({"week_of": "x", "status": "proposed"})


def test_validate_pending_rejects_bad_status():
    import pytest
    bad = {"week_of": "x", "status": "checkout",
           "woolies": {"items": [], "threshold": 75},
           "asianpantry": {"items": [], "threshold": 130, "permalink": None},
           "fresh_asian": []}
    with pytest.raises(ValueError):
        cl.validate_pending(bad)
