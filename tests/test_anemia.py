from datetime import date, timedelta

import pytest

import anemia
from config import load_config

CFG = load_config({})
LMP = date(2025, 6, 1)


def s(*pairs):
    """(GA สัปดาห์, Hct) → ชุดผลเรียงตามวัน"""
    return [{"date": LMP + timedelta(weeks=ga), "ga": ga, "hct": v} for ga, v in pairs]


@pytest.mark.parametrize("series,want", [
    (s((12, 29), (24, 31.5), (32, 34)), "recovered"),
    (s((12, 28), (32, 31.5)), "improving"),            # +3.5 แต่ยัง < 33
    (s((10, 30), (28, 29.5)), "not_improved"),
    (s((10, 30), (28, 32.9)), "not_improved"),          # +2.9 ไม่ถึง 3 จุด
    (s((10, 36), (30, 31)), "new"),
    (s((10, 36), (20, 31), (34, 35)), "recovered"),      # ซีดกลางทางแล้วหาย
    (s((30, 30)), "single"),
    (s((10, 36), (30, 34)), "normal"),
    ([], None),
])
def test_classify(series, want):
    assert anemia.classify(series, CFG) == want


def test_second_trimester_cutoff():
    cfg = load_config({"ANC_HCT_CUTOFF_T2": "32"})
    assert anemia.classify(s((20, 32.5), (30, 34)), cfg) == "normal"     # ไตรมาส 2 ใช้ < 32
    assert anemia.classify(s((20, 32.5), (30, 34)), CFG) == "recovered"  # ค่าเริ่มต้น < 33 ทุกไตรมาส


def test_improve_threshold_from_env():
    cfg = load_config({"ANC_HCT_IMPROVE": "2"})
    assert anemia.classify(s((10, 30), (28, 32.5)), cfg) == "improving"


def test_summarize_and_trail():
    delivered = [{"anc_id": i} for i in range(1, 7)]
    series = {1: s((12, 29), (32, 34)), 2: s((12, 28), (32, 31.5)), 3: s((10, 30), (28, 30)),
              4: s((30, 30)), 5: s((10, 36), (30, 34)), 99: s((10, 20))}
    r = anemia.summarize(delivered, series, CFG)
    assert (r["tested"]["num"], r["tested"]["den"]) == (5, 6) and r["untested"] == 1
    assert r["anemic"] == 4
    assert {g["key"]: g["n"] for g in r["groups"]} == {"recovered": 1, "improving": 1, "not_improved": 1,
                                                       "new": 0, "single": 1}
    assert anemia.trail(series[1]) == "29.0 (12) → 34.0 (32)"
    assert anemia.change(series[1]) == 5.0 and anemia.change(series[4]) is None
