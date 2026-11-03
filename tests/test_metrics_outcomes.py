from datetime import date

from config import load_config
from metrics import outcomes

CFG = load_config({})
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)
LMP = date(2025, 7, 1)


def preg(i, labor=date(2026, 3, 1), lmp=LMP, reg=date(2026, 2, 1), **kw):
    p = {"anc_id": i, "hn": f"h{i}", "age": 25, "village": "30250101", "register_date": reg, "lmp": lmp,
         "labor_date": labor, "thai": True, "labour_hospcode": "10894", "labour_place": "รพ.วังน้ำเขียว",
         "has_risk": False, "cx_htn": False, "cx_gdm": False, "cx_pph": False, "cx_preterm": False,
         "death_date": None}
    p.update(kw)
    return p


def infant(apgar1=9, alive=True, asph=False, dtype="1", d=date(2026, 3, 1)):
    return {"birth_date": d, "weight": 3000, "alive": alive, "village": None, "apgar1": apgar1,
            "asphyxia": asph, "delivery_type": dtype}


def test_high_risk_share_of_new():
    o = outcomes([preg(1, has_risk=True), preg(2), preg(3, reg=date(2025, 12, 1), has_risk=True)], [], [], D1, D2, CFG)
    assert (o["risk"]["num"], o["risk"]["den"], o["risk"]["value"]) == (1, 2, 50.0)


def test_preterm_from_lmp_to_delivery():
    # 2025-07-01 + 36 wk 6 d = 2026-03-16 (preterm) · + 37 wk = 2026-03-17 (term)
    p = [preg(1, labor=date(2026, 3, 16)), preg(2, labor=date(2026, 3, 17)), preg(3, lmp=None)]
    r = outcomes(p, [], [], D1, D2, CFG)["preterm"]
    assert (r["num"], r["den"]) == (1, 2)


def test_birth_asphyxia_per_1000_live_births():
    inf = [infant(6), infant(7), infant(9, asph=True), infant(3, alive=False)] + [infant(9) for _ in range(36)]
    r = outcomes([], inf, [], D1, D2, CFG)["asphyxia"]
    # Apgar 1 นาที < 7 หรือบันทึก birth asphyxia · ตัวหาร = เกิดมีชีพ 39
    assert (r["num"], r["den"], r["value"], r["target"], r["ok"]) == (2, 39, 51.3, 25, False)


def test_delivery_place_and_bba_and_deaths():
    p = [preg(1), preg(2, labour_hospcode="24060", labour_place="รพ.มทส."), preg(3, labour_hospcode="24060",
         labour_place="รพ.มทส."), preg(4, death_date=date(2026, 3, 20)), preg(5, death_date=date(2026, 6, 1))]
    inf = [infant(dtype="3"), infant(alive=False), infant()]
    o = outcomes(p, inf, [], D1, D2, CFG)
    assert (o["place"]["here"], o["place"]["den"], o["place"]["pct_here"]) == (3, 5, 60.0)
    assert o["place"]["top"][0] == {"code": "24060", "name": "รพ.มทส.", "n": 2}
    assert o["bba"] == 1 and o["stillbirth"] == 1
    assert o["maternal_death"] == 1          # เสียชีวิตภายใน 42 วันหลังคลอด (รายที่ 5 เกิน 42 วัน)


def test_complications_and_risk_types():
    p = [preg(1, cx_htn=True, cx_pph=True), preg(2, cx_gdm=True), preg(3), preg(4, labor=None, cx_htn=True)]
    o = outcomes(p, [], [{"name": "ครรภ์แรกอายุ < 17 ปี", "n": 5}, {"name": "เคยผ่าคลอด", "n": 2}], D1, D2, CFG)
    cx = {c["key"]: c for c in o["complications"]}
    assert (cx["cx_htn"]["num"], cx["cx_htn"]["den"]) == (1, 3) and cx["cx_gdm"]["num"] == 1 and cx["cx_pph"]["num"] == 1
    assert o["risk_types"][0]["name"] == "ครรภ์แรกอายุ < 17 ปี"


def test_area_applies_to_delivered_based_outcomes():
    p = [preg(1, labor=date(2026, 3, 1)), preg(2, thai=False, labor=date(2026, 3, 1))]
    o = outcomes(p, [], [], D1, D2, CFG, area=lambda x: x["thai"])
    assert o["preterm"]["den"] == 1 and o["place"]["den"] == 1 and o["risk"]["den"] == 2


def test_alerts_for_outcomes():
    from metrics import alerts, by_age, indicators
    inf = [infant(5)] + [infant(9) for _ in range(9)]
    out = outcomes([preg(1, death_date=date(2026, 3, 5))], inf, [], D1, D2, CFG)
    al = alerts(indicators([], [], [], D1, D2, CFG), [], by_age([], [], D1, D2, CFG), [], out)
    texts = " ".join(a["text"] for a in al)
    assert "มารดาเสียชีวิต 1 ราย" in texts and "ทารกแรกเกิดขาดออกซิเจน 100.0 ต่อ 1,000" in texts
    assert all(a["level"] == "red" for a in al)
