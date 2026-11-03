from datetime import date

from config import load_config
from metrics import OUT, UNK, alerts, by_age, by_pcu, indicators, pcu_of, unmapped_villages

CFG = load_config({})              # อำเภอ 30/25 · รพ. 10894
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)
# รูปแบบเดียวกับ village_pcu.csv ของ mental_health_dashboard (โหลดแล้ว): หมู่บ้าน 8 หลัก → (รหัส, ชื่อ)
MAP = {"30250101": ("02849", "ไทยสามัคคี"), "30250102": ("02849", "ไทยสามัคคี"), "30250201": ("02842", "ท่าวังไทร"),
       "30250301": ("02840", "ศาลเจ้าพ่อ"), "30250110": ("10894", "รพ.วังน้ำเขียว")}


def preg(anc_id, village, age=25, reg=date(2026, 2, 1), labor=date(2026, 5, 1), dt=False, hct=None):
    return {"anc_id": anc_id, "hn": f"h{anc_id}", "age": age, "village": village, "register_date": reg,
            "lmp": date(2025, 8, 1), "labor_date": labor, "hct_late": hct, "has_dt": dt, "has_dental": False}


def test_pcu_of_like_mental_health():
    assert pcu_of("30250101", MAP, CFG) == ("02849", "ไทยสามัคคี")
    assert pcu_of("30250999", MAP, CFG) == UNK            # ในอำเภอ แต่หมู่ไม่อยู่ในไฟล์
    assert pcu_of("30210101", MAP, CFG) == OUT            # อำเภออื่น
    assert pcu_of(None, MAP, CFG) == UNK
    assert UNK[1] == "ในอำเภอ ไม่ทราบหมู่" and OUT[1] == "นอกเขตอำเภอ"


def test_by_pcu_counts_and_rates():
    pregs = [preg(1, "30250101", age=17, dt=True), preg(2, "30250102", age=36), preg(3, "30250201"),
             preg(4, "30250201", reg=date(2025, 11, 1), dt=True)]
    infants = [{"birth_date": date(2026, 3, 1), "weight": 2000, "alive": True, "village": "30250101"},
               {"birth_date": date(2026, 3, 1), "weight": 3000, "alive": True, "village": "30250101"}]
    refers = [{"refer_id": 1, "village": "30250201"}, {"refer_id": 2, "village": "30250201"}]
    rows = by_pcu(pregs, [], infants, refers, D1, D2, CFG, MAP)
    a = next(r for r in rows if r["name"] == "ไทยสามัคคี")
    assert (a["hospcode"], a["new"], a["teen"], a["repro"], a["elder"]) == ("02849", 2, 1, 0, 1)
    assert (a["dt"]["num"], a["dt"]["den"]) == (1, 2) and (a["lbw"]["num"], a["lbw"]["den"]) == (1, 2)
    b = next(r for r in rows if r["name"] == "ท่าวังไทร")
    assert b["new"] == 1 and b["dt"]["den"] == 2 and b["refer"] == 2
    c = next(r for r in rows if r["name"] == "ศาลเจ้าพ่อ")      # รพ.สต. ที่ไม่มีข้อมูลก็ยังแสดง
    assert c["new"] == 0 and c["dt"]["value"] is None


def test_pcu_order_like_mental_health():
    """ลำดับเหมือน mental_health_dashboard: รพ.สต. ตามชื่อ → เขต รพ. → ในอำเภอ ไม่ทราบหมู่ → นอกเขตอำเภอ"""
    rows = by_pcu([preg(1, "30250999"), preg(2, "30210101"), preg(3, "30250110")], [], [], [], D1, D2, CFG, MAP)
    assert [r["name"] for r in rows] == ["ท่าวังไทร", "ศาลเจ้าพ่อ", "ไทยสามัคคี", "รพ.วังน้ำเขียว",
                                         UNK[1], OUT[1]]
    assert [r["new"] for r in rows[-3:]] == [1, 1, 1]


def test_hospital_row_named_when_not_in_csv():
    m = {k: v for k, v in MAP.items() if v[0] != "10894"}
    rows = by_pcu([], [], [], [], D1, D2, CFG, m)
    assert rows[-3]["hospcode"] == "10894" and rows[-3]["name"] == "เขต รพ."


def test_unmapped_villages_only_in_district():
    pregs = [preg(1, "30250999"), preg(2, "30250888"), preg(3, "30250888"), preg(4, None), preg(5, "30210101"),
             preg(6, "30250101")]
    assert unmapped_villages(pregs, MAP, CFG) == [("30250888", 2), ("", 1), ("30250999", 1)]


def test_alerts_rules():
    pregs = [preg(i, "30250101", age=14 if i == 1 else 25, dt=i < 3) for i in range(1, 7)]
    ind = indicators(pregs, [], [], D1, D2, CFG)
    age = by_age(pregs, [], D1, D2, CFG)
    rows = by_pcu(pregs + [preg(9, "30250999")] * 6, [], [], [], D1, D2, CFG, MAP)
    al = alerts(ind, rows, age, [("30250999", 2)])
    levels = [a["level"] for a in al]
    texts = " ".join(a["text"] for a in al)
    assert "red" in levels and "amber" in levels and "info" in levels
    assert "dT" in texts and "อายุต่ำกว่า 15 ปี" in texts and "ไทยสามัคคี" in texts and "1 หมู่บ้าน" in texts
    assert UNK[1] not in texts                      # แถวรวม (ไม่ทราบหมู่ / นอกเขต) ไม่ขึ้น alert ราย รพ.สต.
    for a in al:
        assert set(a) == {"level", "text", "owner", "action"}
    clean = alerts(indicators([], [], [], D1, D2, CFG), [], by_age([], [], D1, D2, CFG), [])
    assert clean == []
