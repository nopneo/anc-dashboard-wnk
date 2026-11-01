from datetime import date, timedelta

from config import load_config
from metrics import (age_group, by_age, ga_bucket, indicators, months_in_range, pct, teen_sub,
                     tracking, visit_ga)

CFG = load_config({})
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)
LMP = date(2025, 9, 1)


def preg(anc_id, age=25, reg=date(2025, 10, 1), lmp=LMP, labor=date(2026, 5, 1), hct=None, dt=False, dental=False,
         village="30250101", hn=None):
    return {"anc_id": anc_id, "hn": hn or f"h{anc_id}", "age": age, "village": village, "register_date": reg,
            "lmp": lmp, "labor_date": labor, "hct_late": hct, "has_dt": dt, "has_dental": dental}


def visit(anc_id, ga, lmp=LMP, precare=False, d=None):
    return {"anc_id": anc_id, "date": d or lmp + timedelta(weeks=ga), "ga": None if precare else ga,
            "precare": precare}


def run(pregs, visits=(), infants=(), waits=()):
    return indicators(list(pregs), list(visits), list(infants), list(waits), D1, D2, CFG)


def test_age_groups():
    assert [age_group(a) for a in (14, 19, 20, 34, 35, None)] == ["teen", "teen", "repro", "repro", "elder", None]
    assert teen_sub(14) == "lt15" and teen_sub(15) == "15_19" and teen_sub(20) is None


def test_ga_bucket_edges():
    assert [ga_bucket(w) for w in (4, 12, 13, 20, 21, 26, 27, 32, 33, 40, 41, None)] == \
        [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, None, None]


def test_visit_without_ga_is_ignored():
    assert visit_ga({"anc_id": 1, "date": date(2026, 3, 1), "ga": None}, None) is None
    assert visit_ga({"anc_id": 1, "date": date(2026, 3, 1), "ga": None}, date(2026, 1, 1)) == 8
    # visit ที่ GA ไม่รู้ ไม่ทำให้ล้ม และไม่ตกช่วงใด
    r = run([preg(1, lmp=None)], [{"anc_id": 1, "date": date(2026, 1, 5), "ga": None, "precare": False}])
    assert r["visit5"]["num"] == 0 and r["visit5"]["den"] == 1 and r["early12"]["num"] == 0


def test_visit5_requires_all_buckets():
    pregs = [preg(1), preg(2)]
    visits = [visit(1, w) for w in (8, 15, 24, 30, 36)] + [visit(2, w) for w in (8, 15, 30, 36)]
    r = run(pregs, visits)["visit5"]
    assert (r["num"], r["den"], r["value"]) == (1, 2, 50.0)


def test_visit5_counts_precare_from_lmp():
    visits = [visit(1, 8, precare=True)] + [visit(1, w) for w in (15, 24, 30, 36)]
    assert run([preg(1)], visits)["visit5"]["num"] == 1


def test_denominator_is_delivered_in_range():
    pregs = [preg(1), preg(2, labor=date(2026, 8, 1)), preg(3, labor=None), preg(4, labor=date(2025, 12, 31))]
    visits = [visit(i, 8) for i in (1, 2, 3, 4)]
    r = run(pregs, visits)
    for k in ("early12", "visit5", "dt", "dental"):
        assert r[k]["den"] == 1, k
    assert r["early12"]["num"] == 1 and r["early12"]["value"] == 100.0


def test_early12_uses_earliest_visit_including_precare():
    # precare ที่อื่น GA 10 มาก่อน visit ที่ รพ. GA 16
    visits = [visit(1, 10, precare=True), visit(1, 16), visit(2, 16)]
    r = run([preg(1), preg(2)], visits)["early12"]
    assert (r["num"], r["den"]) == (1, 2)


def test_dt_and_dental():
    r = run([preg(1, dt=True, dental=True), preg(2, dt=True), preg(3)])
    assert (r["dt"]["num"], r["dt"]["den"], r["dt"]["value"]) == (2, 3, 66.7)
    assert (r["dental"]["num"], r["dental"]["value"]) == (1, 33.3)
    assert r["dt"]["ok"] is False and r["dental"]["ok"] is False


def test_anemia_denominator_only_with_result():
    r = run([preg(1, hct=32.5), preg(2, hct=35), preg(3, hct=None), preg(4, hct=33)])["anemia"]
    assert (r["num"], r["den"], r["value"]) == (1, 3, 33.3)
    assert r["ok"] is False
    ok = run([preg(i, hct=36) for i in range(1, 8)])["anemia"]
    assert ok["value"] == 0.0 and ok["ok"] is True


def test_lbw_live_births_only():
    inf = [{"birth_date": date(2026, 2, 1), "weight": 2499, "alive": True},
           {"birth_date": date(2026, 2, 1), "weight": 2500, "alive": True},
           {"birth_date": date(2026, 2, 1), "weight": 1800, "alive": False},
           {"birth_date": date(2026, 2, 1), "weight": None, "alive": True},
           {"birth_date": date(2025, 12, 1), "weight": 2000, "alive": True}]
    r = run([], infants=inf)["lbw"]
    assert (r["num"], r["den"], r["value"]) == (1, 2, 50.0)


def test_counts_new_visits_per_month_wait():
    pregs = [preg(1, reg=date(2026, 2, 1)), preg(2, reg=date(2025, 12, 31)), preg(3, reg=date(2026, 6, 30))]
    visits = [visit(1, 10, d=date(2026, 2, 1)), visit(1, 14, d=date(2026, 3, 1)),
              visit(2, 20, d=date(2025, 12, 31)), visit(1, 9, precare=True, d=date(2026, 1, 20))]
    r = run(pregs, visits, waits=[10, 20, 31])
    assert r["new"]["value"] == 2 and r["visits"]["value"] == 2
    assert r["per_month"]["value"] == round(2 / 6, 1)
    assert r["wait"]["value"] == 20.3 and r["wait"]["den"] == 3


def test_zero_denominator_is_none():
    r = run([])
    assert r["early12"]["value"] is None and r["early12"]["ok"] is None and r["wait"]["value"] is None
    assert r["lbw"]["value"] is None and r["new"]["value"] == 0


def test_low_base_flag():
    assert run([preg(i) for i in range(1, 5)])["dt"]["low_base"] is True
    assert run([preg(i) for i in range(1, 6)])["dt"]["low_base"] is False


def test_pct():
    assert pct(1, 3) == 33.3 and pct(0, 0) is None and pct(2, 2) == 100.0


def test_months_in_range():
    assert months_in_range(date(2026, 10, 1), date(2026, 10, 31)) == 1.0
    assert round(months_in_range(date(2026, 10, 1), date(2026, 11, 15)), 2) == 1.5


def test_by_age_split():
    pregs = [preg(1, age=14, reg=date(2026, 2, 1)), preg(2, age=17, reg=date(2026, 2, 1)),
             preg(3, age=25, reg=date(2026, 2, 1)), preg(4, age=36, reg=date(2026, 2, 1)),
             preg(5, age=17, reg=date(2025, 10, 1))]
    visits = [visit(1, 8), visit(2, 16), visit(5, 8)]
    a = by_age(pregs, visits, D1, D2, CFG)
    assert a["teen"]["new"] == 2 and a["teen"]["lt15"] == 1 and a["teen"]["15_19"] == 1
    assert a["teen"]["share"] == 50.0 and a["repro"]["new"] == 1 and a["elder"]["new"] == 1
    # อัตราของกลุ่มคิดจากครรภ์ที่คลอดในช่วง (ครรภ์ 1, 2, 5 เป็น teen)
    assert (a["teen"]["early12"]["num"], a["teen"]["early12"]["den"]) == (2, 3)
    assert "lt15" not in a["repro"]


def test_tracking_open_pregnancies():
    pregs = [preg(1, labor=None, lmp=date(2026, 4, 1), reg=date(2026, 5, 1)),
             preg(2, labor=None, lmp=date(2026, 3, 1), reg=date(2026, 5, 1)),
             preg(3, labor=date(2026, 7, 5), lmp=date(2025, 10, 1)),       # คลอดหลัง d2 = ยังตั้งครรภ์ ณ d2
             preg(4, labor=None, lmp=date(2024, 1, 1), reg=date(2024, 2, 1)),  # ค้างในทะเบียนเกิน 44 wk ไม่นับ
             preg(5, labor=date(2026, 3, 1))]
    visits = [visit(1, 8, lmp=date(2026, 4, 1)), visit(2, 14, lmp=date(2026, 3, 1))]
    assert tracking(pregs, visits, D2) == {"open": 3, "early12_so_far": 1}
