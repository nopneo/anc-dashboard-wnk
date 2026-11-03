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


def run(pregs, visits=(), infants=(), cfg=CFG):
    return indicators(list(pregs), list(visits), list(infants), D1, D2, cfg)


def test_age_groups():
    assert [age_group(a) for a in (14, 19, 20, 34, 35, None)] == ["teen", "teen", "repro", "repro", "elder", None]
    assert teen_sub(14) == "lt15" and teen_sub(15) == "15_19" and teen_sub(20) is None


def test_ga_bucket_edges():
    # ตามเอกสาร KPI: ≤12 · 13–<20 · 20–<26 · 26–<32 · 32–40
    assert [ga_bucket(w) for w in (4, 12, 13, 19, 20, 25, 26, 31, 32, 40, 41, None)] == \
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


def test_counts_new_visits_per_month():
    pregs = [preg(1, reg=date(2026, 2, 1)), preg(2, reg=date(2025, 12, 31)), preg(3, reg=date(2026, 6, 30))]
    visits = [visit(1, 10, d=date(2026, 2, 1)), visit(1, 14, d=date(2026, 3, 1)),
              visit(2, 20, d=date(2025, 12, 31)), visit(1, 9, precare=True, d=date(2026, 1, 20))]
    r = run(pregs, visits)
    assert r["new"]["value"] == 2 and r["visits"]["value"] == 2
    assert r["per_month"]["value"] == round(2 / 6, 1)
    assert "wait" not in r


def test_zero_denominator_is_none():
    r = run([])
    assert r["early12"]["value"] is None and r["early12"]["ok"] is None
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


def test_monthly_trend():
    from metrics import monthly_trend
    pregs = [preg(1, reg=date(2026, 1, 5)), preg(2, reg=date(2026, 3, 9)), preg(3, reg=date(2025, 12, 1))]
    visits = [visit(1, 10, d=date(2026, 1, 5)), visit(1, 14, d=date(2026, 3, 1)),
              visit(2, 9, precare=True, d=date(2026, 3, 2))]
    t = monthly_trend(pregs, visits, D1, D2)
    assert [m["month"] for m in t] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert (t[0]["new"], t[0]["visits"], t[2]["new"], t[2]["visits"], t[1]["visits"]) == (1, 1, 1, 1, 0)
    assert t[0]["label"] == "ม.ค."


# ---------- KPI จากโฟลเดอร์ kpi ----------

def test_postnatal_three_windows():
    """ครั้งที่ 1 วันที่ 1–7 · ครั้งที่ 2 วันที่ 8–15 · ครั้งที่ 3 วันที่ 16–42 นับจากวันคลอด"""
    lab = date(2026, 3, 1)
    p = [preg(1, labor=lab), preg(2, labor=lab), preg(3, labor=lab), preg(4, labor=date(2026, 6, 20))]
    pnc = [{"anc_id": 1, "date": lab + timedelta(days=d)} for d in (3, 10, 30)] +           [{"anc_id": 2, "date": lab + timedelta(days=d)} for d in (0, 10, 30)] +           [{"anc_id": 3, "date": lab + timedelta(days=d)} for d in (7, 8, 42)] +           [{"anc_id": 4, "date": date(2026, 6, 22)}]
    r = indicators(p, [], [], D1, D2, CFG, pnc=pnc)["postnatal"]
    # ครรภ์ 4 คลอด 20 มิ.ย. ยังไม่พ้น 42 วัน ณ 30 มิ.ย. → ไม่อยู่ในตัวหาร · ครรภ์ 2 วันที่ 0 ไม่นับ
    assert (r["num"], r["den"], r["target"]) == (2, 3, 75)


def test_iodine_among_anc_attenders():
    p = [preg(1, labor=None), preg(2, labor=None), preg(3, labor=None), preg(4, labor=None)]
    p[0]["has_iodine"] = True
    p[3]["has_iodine"] = True
    v = [visit(1, 10, d=date(2026, 2, 1)), visit(2, 10, d=date(2026, 2, 1)),
         visit(3, 9, precare=True, d=date(2026, 2, 1)), visit(4, 10, d=date(2025, 12, 1))]
    r = indicators(p, v, [], D1, D2, CFG)["iodine"]
    # ตัวหาร = ครรภ์ที่มาฝากครรภ์ที่ รพ. ในช่วง (ครรภ์ 3 ฝากที่อื่น, ครรภ์ 4 มานอกช่วง)
    assert (r["num"], r["den"], r["value"], r["ok"]) == (1, 2, 50.0, None)


def test_quality_anc_all_five_activities():
    full = {"q_cbc": True, "q_thal": True, "q_us": True, "q_down": True, "q_dm": True}
    p = [dict(preg(1), **full), dict(preg(2), **dict(full, q_down=False)), dict(preg(3), **full)]
    ind = indicators(p, [], [], D1, D2, CFG)
    r = ind["quality"]
    assert (r["num"], r["den"], r["value"], r["target"]) == (2, 3, 66.7, 70) and r["ok"] is False
    comp = ind["quality_parts"]
    assert [c["key"] for c in comp] == ["q_cbc", "q_thal", "q_us", "q_down", "q_dm"]
    assert next(c for c in comp if c["key"] == "q_down")["rate"]["num"] == 2


# ---------- ตัวหารในเขต (นิยามเอกสาร KPI) ----------

def test_in_area_rule():
    """หญิงไทย และ (อยู่ในอำเภอ หรือ อยู่นอกเขตแต่มาคลอดที่ รพ.)"""
    from metrics import in_area
    base = dict(preg(1), thai=True, labour_hospcode="24060")
    assert in_area(dict(base, village="30250101"), CFG) is True
    assert in_area(dict(base, village="30210101"), CFG) is False                      # นอกอำเภอ คลอดที่อื่น
    assert in_area(dict(base, village="30210101", labour_hospcode="10894"), CFG) is True  # นอกเขต มาคลอดที่ รพ.
    assert in_area(dict(base, village=None, labour_hospcode=None), CFG) is False
    assert in_area(dict(base, village="30250101", thai=False), CFG) is False           # ไม่ใช่หญิงไทย


def test_area_filters_kpi_denominators_only():
    from metrics import in_area
    inside = dict(preg(1, reg=date(2026, 2, 1)), thai=True, labour_hospcode="10894", village="30250101", has_dt=True)
    outside = dict(preg(2, reg=date(2026, 2, 1)), thai=True, labour_hospcode="24060", village="30210101")
    area = lambda p: in_area(p, CFG)
    r = indicators([inside, outside], [], [], D1, D2, CFG, area=area)
    assert (r["dt"]["num"], r["dt"]["den"]) == (1, 1)              # ตัวหาร KPI นับเฉพาะในเขต
    assert r["new"]["value"] == 2                                   # ข้อมูลบริการนับทั้งหมด
    a = by_age([inside, outside], [], D1, D2, CFG, area=area)
    assert a["repro"]["new"] == 2 and a["repro"]["early12"]["den"] == 1
    assert indicators([inside, outside], [], [], D1, D2, CFG)["dt"]["den"] == 2   # ไม่ส่ง area = ทั้งหมด


def test_labor_completeness():
    from metrics import labor_completeness
    p = [preg(1, lmp=date(2025, 1, 1), labor=date(2025, 10, 1)),
         preg(2, lmp=date(2025, 1, 1), labor=None),
         preg(3, lmp=date(2026, 5, 1), labor=None),       # ยังไม่ครบ 42 wk ณ d2 → ไม่นับ
         preg(4, lmp=None, labor=None)]
    assert labor_completeness(p, D1, D2) == {"due": 2, "recorded": 1, "pct": 50.0}


# ---------- ฝากครรภ์ครบ 8 ครั้งตามเกณฑ์ (เอกสาร 1.7) ----------

def test_ga_bucket8_edges():
    from metrics import GA_BUCKETS_8, ga_bucket
    weeks = (12, 13, 20, 21, 26, 27, 30, 31, 34, 35, 36, 37, 38, 39, 40, 41, None)
    assert [ga_bucket(w, GA_BUCKETS_8) for w in weeks] == [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, None, None]


def test_visit8_needs_all_eight_windows():
    full = (8, 15, 24, 29, 33, 36, 38, 40)
    r = run([preg(1), preg(2), preg(3)],
            [visit(1, w) for w in full] + [visit(2, w) for w in full[:7]]
            + [visit(3, w) for w in (8, 15, 24, 29, 33, 36, 38, 40, 40)])["visit8"]
    assert (r["num"], r["den"], r["value"]) == (2, 3, 66.7)       # ครรภ์ 2 ขาดช่วง 39–40 wk


def test_visit8_target_follows_fiscal_year():
    from metrics import visit8_target
    assert visit8_target(date(2026, 9, 30), CFG) == 65          # ปีงบ 2569
    assert visit8_target(date(2026, 11, 2), CFG) == 70          # ปีงบ 2570
    assert visit8_target(date(2023, 12, 1), CFG) == 55          # ธ.ค. 2566 = ปีงบ 2567
    assert visit8_target(date(2020, 1, 1), CFG) == 50 and visit8_target(date(2030, 1, 1), CFG) == 70   # นอกตาราง = ค่าขอบ
    assert load_config({"ANC_TARGET_VISIT8": "80"}).targets["visit8"] == 80
    assert visit8_target(date(2026, 9, 30), load_config({"ANC_TARGET_VISIT8": "80"})) == 80
    r = run([preg(1)], [visit(1, w) for w in (8, 15, 24, 29, 33, 36, 38, 40)])["visit8"]
    assert r["target"] == 65 and r["ok"] is True


def teen(anc_id, age_labor, gravida, labor=date(2026, 3, 1), **kw):
    return dict(preg(anc_id, age=age_labor, labor=labor, **kw), age_labor=age_labor, gravida=gravida)


def test_teen_repeat_pregnancy():
    # เอกสาร 2.1: ครรภ์สิ้นสุด (คลอด/แท้ง) ในช่วง · อายุ ณ วันสิ้นสุด < 20 · ตัวตั้ง = ครรภ์ที่ ≥ 2
    pregs = [teen(1, 17, 2), teen(2, 19, 1), teen(3, 18, None), teen(4, 20, 3),
             teen(5, 16, 3, labor=date(2025, 12, 31)), teen(6, None, 2), teen(7, 15, 4)]
    r = run(pregs)["teen_repeat"]
    assert (r["num"], r["den"], r["value"]) == (2, 4, 50.0)
    assert r["target"] == 12.0 and r["ok"] is False          # ปีงบ 2569 · ยิ่งต่ำยิ่งดี


def test_teen_repeat_target_by_fiscal_year_or_env():
    from metrics import teen_repeat_target
    assert teen_repeat_target(date(2024, 10, 1), CFG) == 12.5        # ปีงบ 2568
    assert teen_repeat_target(date(2027, 9, 30), CFG) == 11.5        # ปีงบ 2570
    assert teen_repeat_target(date(2030, 1, 1), CFG) == 11.5         # นอกตาราง = ค่าขอบ
    assert teen_repeat_target(D2, load_config({"ANC_TARGET_TEEN_REPEAT": "10"})) == 10
    r = run([teen(1, 17, 1), teen(2, 18, 1)])["teen_repeat"]
    assert r["value"] == 0.0 and r["ok"] is True
