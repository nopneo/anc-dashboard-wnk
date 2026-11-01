from datetime import date

from config import load_config
from metrics import UNMAPPED, alerts, by_pcu, indicators, pcu_of, unmapped_villages, by_age

CFG = load_config({})
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)
MAP = {"30250101": ("03929", "รพ.สต.ก"), "30250102": ("03929", "รพ.สต.ก"), "30250201": ("03930", "รพ.สต.ข"),
       "30250301": ("03931", "รพ.สต.ค")}


def preg(anc_id, village, age=25, reg=date(2026, 2, 1), labor=date(2026, 5, 1), dt=False, hct=None):
    return {"anc_id": anc_id, "hn": f"h{anc_id}", "age": age, "village": village, "register_date": reg,
            "lmp": date(2025, 8, 1), "labor_date": labor, "hct_late": hct, "has_dt": dt, "has_dental": False}


def test_pcu_of():
    assert pcu_of("30250101", MAP) == ("03929", "รพ.สต.ก")
    assert pcu_of("99999999", MAP) == UNMAPPED and pcu_of(None, MAP) == UNMAPPED


def test_by_pcu_counts_and_rates():
    pregs = [preg(1, "30250101", age=17, dt=True), preg(2, "30250102", age=36), preg(3, "30250201"),
             preg(4, "30250201", reg=date(2025, 11, 1), dt=True)]
    infants = [{"birth_date": date(2026, 3, 1), "weight": 2000, "alive": True, "village": "30250101"},
               {"birth_date": date(2026, 3, 1), "weight": 3000, "alive": True, "village": "30250101"}]
    refers = [{"refer_id": 1, "village": "30250201"}, {"refer_id": 2, "village": "30250201"}]
    rows = by_pcu(pregs, [], infants, refers, D1, D2, CFG, MAP)
    a = next(r for r in rows if r["name"] == "รพ.สต.ก")
    assert (a["hospcode"], a["new"], a["teen"], a["repro"], a["elder"]) == ("03929", 2, 1, 0, 1)
    assert (a["dt"]["num"], a["dt"]["den"]) == (1, 2) and (a["lbw"]["num"], a["lbw"]["den"]) == (1, 2)
    assert a["refer"] == 0
    b = next(r for r in rows if r["name"] == "รพ.สต.ข")
    assert b["new"] == 1 and b["dt"]["den"] == 2 and b["refer"] == 2
    c = next(r for r in rows if r["name"] == "รพ.สต.ค")      # รพ.สต. ที่ไม่มีข้อมูลก็ยังแสดง
    assert c["new"] == 0 and c["dt"]["value"] is None


def test_pcu_unmapped_last():
    rows = by_pcu([preg(1, "11111111"), preg(2, "30250201")], [], [], [], D1, D2, CFG, MAP)
    assert rows[-1]["name"] == UNMAPPED[1] and rows[-1]["new"] == 1
    assert [r["name"] for r in rows[:-1]] == ["รพ.สต.ก", "รพ.สต.ข", "รพ.สต.ค"]
    assert by_pcu([preg(1, "30250201")], [], [], [], D1, D2, CFG, MAP)[-1]["name"] != UNMAPPED[1]


def test_unmapped_villages_sorted():
    pregs = [preg(1, "11111111"), preg(2, "22222222"), preg(3, "22222222"), preg(4, None), preg(5, "30250101")]
    assert unmapped_villages(pregs, MAP) == [("22222222", 2), ("", 1), ("11111111", 1)]


def test_alerts_rules():
    pregs = [preg(i, "30250101", age=14 if i == 1 else 25, dt=i < 3) for i in range(1, 7)]
    ind = indicators(pregs, [], [], [], D1, D2, CFG)
    age = by_age(pregs, [], D1, D2, CFG)
    rows = by_pcu(pregs, [], [], [], D1, D2, CFG, MAP)
    al = alerts(ind, rows, age, [("11111111", 2)])
    levels = [a["level"] for a in al]
    texts = " ".join(a["text"] for a in al)
    assert "red" in levels and "amber" in levels and "info" in levels
    assert "dT" in texts and "อายุต่ำกว่า 15 ปี" in texts and "รพ.สต.ก" in texts and "1 หมู่บ้าน" in texts
    for a in al:
        assert set(a) == {"level", "text", "owner", "action"}
    clean = alerts(indicators([], [], [], [], D1, D2, CFG), [], by_age([], [], D1, D2, CFG), [])
    assert clean == []
