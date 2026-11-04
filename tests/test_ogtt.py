import random
from datetime import date

import pytest

import check
import drill
import ogtt
import queries
from config import load_config

CFG = load_config({})
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)


def _set(vals, d=date(2026, 3, 1)):
    return {"date": d, "vals": vals}


@pytest.mark.parametrize("text,want", [("98", 98.0), ("190 H", 190.0), ("<70", 70.0), ("105.5", 105.5),
                                       ("", None), (None, None), ("งดตรวจ", None), ("5", None), ("9999", None)])
def test_parse(text, want):
    assert ogtt.parse(text) == want


LAB_ITEMS = [("2066", "OGTT 100 G ก่อนกิน"), ("2108", "OGTT 100 G หลังกิน 1 ชั่งโมง"),
             ("2111", "OGTT 100 G หลังกิน 2 ชั่งโมง"), ("2113", "OGTT 100 G หลังกิน 3 ชั่งโมง"),
             ("2100", "OGTT 100 g"), ("240", "OGTT 50 G"), ("2092", "OGTT 75 g ก่อนกิน"), ("2218", "OGTT 75 g"),
             ("2222", "OGTT 75 g หลังกิน 1 ชั่งโมง"), ("2224", "OGTT 75 g หลังกิน 2 ชั่งโมง")]


def test_pick_codes_by_name_in_point_order():
    assert ogtt.pick_codes(LAB_ITEMS[::-1]) == {"g100": ("2066", "2108", "2111", "2113"),
                                                "g75": ("2092", "2222", "2224")}
    assert ogtt.pick_codes([("240", "OGTT 50 G")]) == {"g100": (None,) * 4, "g75": (None,) * 3}


def test_abnormal_counts_values_at_or_above_cutoff():
    assert ogtt.abnormal([95, 180, 155, 140], "g100", CFG) == 4              # เท่ากับเกณฑ์ = ผิดปกติ
    assert ogtt.abnormal([94, 179, 154, 139], "g100", CFG) == 0
    assert ogtt.abnormal([98, None, 160, None], "g100", CFG) == 2            # ค่าที่ไม่มี ไม่นับ
    assert ogtt.abnormal([92, 180, 153], "g75", CFG) == 3


def test_status_threshold_and_best_of_types():
    res = {1: {"g100": _set([98, 170, 140, 120])},                              # 1 ค่า
           2: {"g100": _set([98, 190, 140, 120])},                              # 2 ค่า
           3: {"g100": _set([80, 150, 140, 120]), "g75": _set([93, 185, 150])},  # g100 ปกติ · g75 2 ค่า
           4: {"g100": _set([80, 150, 140, 120])}}
    st = lambda i, k: ogtt.status(res, i, k, CFG)
    assert [st(i, "g100") for i in (1, 2, 3, 4)] == ["one", "abn", "ok", "ok"]
    assert [st(i, "all") for i in (1, 2, 3, 4)] == ["one", "abn", "abn", "ok"]
    assert st(3, "g75") == "abn" and st(1, "g75") is None and st(9, "all") is None
    one = load_config({"ANC_OGTT_MIN_ABN": "1"})
    assert ogtt.status(res, 1, "g100", one) == "abn"


def test_custom_cutoff_must_match_point_count():
    cfg = load_config({"ANC_OGTT_G100_CUT": "105,190,165,145", "ANC_OGTT_G75_CUT": "90,180"})
    assert ogtt.abnormal([98, 185, 160, 140], "g100", cfg) == 0              # NDDG
    assert ogtt._cut("g75", cfg) == (92, 180, 153)                           # จำนวนไม่ตรง → ใช้ค่ามาตรฐาน


def test_summarize_counts_people():
    pregs = [{"anc_id": i} for i in range(1, 6)]
    res = {1: {"g100": _set([98, 190, 140, 120])}, 2: {"g100": _set([98, 170, 140, 120])},
           3: {"g75": _set([93, 185, 150])}, 99: {"g100": _set([200, 200, 200, 200])}}     # 99 ไม่อยู่ในทะเบียน
    out = {t["key"]: t for t in ogtt.summarize(pregs, res, CFG)["rows"]}
    assert (out["g100"]["tested"], out["g100"]["abn"], out["g100"]["one"]) == (2, 1, 1)
    assert (out["g75"]["tested"], out["g75"]["abn"]) == (1, 1)
    assert (out["all"]["tested"], out["all"]["abn"]) == (3, 2)
    assert out["all"]["rate"]["num"] == 2 and out["all"]["rate"]["den"] == 3


def test_detail_marks_abnormal_values():
    res = {1: {"g100": _set([98, 170, 160, None])}}
    s = ogtt.detail(res, 1, "all", CFG)
    assert "ก่อนกิน 98*" in s and "1 ชม. 170" in s and "2 ชม. 160*" in s and "3 ชม. -" in s
    assert "ผิดปกติ 2/4 ค่า" in s and ogtt.detail(res, 2, "all", CFG) == "-"


# ---------- ดึงข้อมูล ----------

class FakeFetch:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, sql, args=None):
        self.calls.append((sql, args))
        if "from lab_items" in sql:
            return [{"code": c, "name": n} for c, n in LAB_ITEMS]
        return self.rows


def test_ogtt_results_groups_by_order_and_keeps_latest(monkeypatch):
    rows = [{"anc_id": "7", "ord": "A1", "d": "2026-02-01", "code": "2066", "v": "90"},
            {"anc_id": "7", "ord": "A1", "d": "2026-02-01", "code": "2108", "v": "200"},
            {"anc_id": "7", "ord": "A2", "d": "2026-03-01", "code": "2066", "v": "99"},   # ใบหลังสุดของครรภ์นี้
            {"anc_id": "7", "ord": "A2", "d": "2026-03-01", "code": "2113", "v": "150"},
            {"anc_id": "8", "ord": "B1", "d": "2026-03-05", "code": "2092", "v": "93"},
            {"anc_id": "8", "ord": "B1", "d": "2026-03-05", "code": "2224", "v": "160 H"},
            {"anc_id": "9", "ord": "C1", "d": "2026-03-06", "code": "2066", "v": ""},       # ไม่มีตัวเลข ไม่นับว่าตรวจ
            {"anc_id": "9", "ord": "C1", "d": "2026-03-06", "code": "2108", "v": "งด"}]
    fake = FakeFetch(rows)
    monkeypatch.setattr(queries, "fetch", fake)
    r = queries.ogtt_results(D1, D2, CFG)
    assert r[7]["g100"]["vals"] == [99.0, None, None, 150.0] and r[7]["g100"]["date"] == date(2026, 3, 1)
    assert r[8]["g75"]["vals"] == [93.0, None, 160.0] and 9 not in r
    assert set(fake.calls[-1][1]["codes"]) == {"2066", "2108", "2111", "2113", "2092", "2222", "2224"}   # ไม่เอา 50 g


def test_ogtt_codes_from_env_override_lab_items(monkeypatch):
    monkeypatch.setattr(queries, "fetch", FakeFetch([]))
    cfg = load_config({"ANC_OGTT_G100_LABS": "1,2,3,4", "ANC_OGTT_G75_LABS": "5,6"})      # g75 ระบุไม่ครบ → เลือกจากชื่อ
    assert queries.ogtt_codes(cfg) == {"g100": ("1", "2", "3", "4"), "g75": ("2092", "2222", "2224")}


def test_audit_item_flags_missing_point(monkeypatch):
    monkeypatch.setattr(queries, "ogtt_codes", lambda cfg: {"g100": ("2066", "2108", None, "2113"),
                                                            "g75": ("2092", "2222", "2224")})
    monkeypatch.setattr(check, "fetch", lambda sql, args=None: [
        {"code": "2066", "name": "OGTT 100 G ก่อนกิน", "result": "90", "n": "5"},
        {"code": "2092", "name": "OGTT 75 g ก่อนกิน", "result": "ผลหาย", "n": "3"},
        {"code": "240", "name": "OGTT 50 G", "result": "150", "n": "9"}])
    it = check._ogtt(D1, D2, CFG)
    assert it["status"] == "warn" and "ไม่พบรหัสจุด 2 ชม." in it["hint"] and "อ่านไม่ได้ 100.0%" in it["hint"]
    assert any(f["code"] == "240" and "แอปไม่ได้ใช้" in f["name"] for f in it["found"])


# ---------- รายชื่อ = ตัวเลขบนแดชบอร์ด ----------

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_drill_lists_match_summary(seed):
    rng = random.Random(seed)
    pregs = [{"anc_id": i, "hn": f"h{i}", "age": 25, "village": None, "register_date": D1, "lmp": D1, "labor_date": None}
             for i in range(1, 80)]
    res = {}
    for p in pregs:
        if rng.random() < .5:
            res.setdefault(p["anc_id"], {})["g100"] = _set([rng.choice([85, 98, 110]), rng.choice([150, 185, 210]),
                                                           rng.choice([140, 160]), rng.choice([120, 150])])
        if rng.random() < .2:
            res.setdefault(p["anc_id"], {})["g75"] = _set([rng.choice([85, 95]), rng.choice([150, 185]),
                                                          rng.choice([140, 160])])
    data = {"pregs": pregs, "visits": [], "infants": [], "refers": [], "pnc": [], "risk_hits": {}, "ogtt": res}
    for t in ogtt.summarize(pregs, res, CFG)["rows"]:
        m = drill.members(f"ogtt_{t['key']}_test", data, D1, D2, CFG, None, {})
        assert len(m["rows"]) == t["tested"] and sum(1 for _, ok in m["rows"] if ok) == t["abn"]
        m = drill.members(f"ogtt_{t['key']}_abn", data, D1, D2, CFG, None, {})
        assert len(m["rows"]) == t["abn"]
