from datetime import date

from config import load_config
from metrics import refer_summary, select_refers

CFG = load_config({})


def preg(anc_id, hn, lmp=date(2025, 8, 1), labor=date(2026, 5, 1), age=25):
    return {"anc_id": anc_id, "hn": hn, "age": age, "village": None, "register_date": lmp, "lmp": lmp,
            "labor_date": labor, "hct_late": None, "has_dt": False, "has_dental": False}


def ref(rid, d, hn="x", pdx="J189", age=40, dest="10666", dest_name="รพ.มหาราช", minutes=None, dx_name=None):
    return {"refer_id": rid, "date": d, "hn": hn, "pdx": pdx, "dx_name": dx_name, "dest": dest,
            "dest_name": dest_name, "age": age, "village": None, "minutes": minutes}


def test_refer_registry_window_postpartum_42():
    pregs = [preg(1, "h1")]
    out = select_refers([ref(1, date(2026, 6, 12), "h1"), ref(2, date(2026, 6, 13), "h1"),
                         ref(3, date(2025, 7, 31), "h1")], pregs, CFG)
    assert [r["refer_id"] for r in out] == [1]
    assert out[0]["reason"] == "registry" and out[0]["group"] == "repro"


def test_refer_dx_only_not_in_registry():
    out = select_refers([ref(1, date(2026, 3, 1), "other", pdx="O800", age=17),
                         ref(2, date(2026, 3, 1), "other", pdx="Z340", age=38),
                         ref(3, date(2026, 3, 1), "other", pdx="Z30", age=38)], [], CFG)
    assert [(r["refer_id"], r["reason"], r["group"]) for r in out] == [(1, "dx", "teen"), (2, "dx", "elder")]


def test_refer_counted_once_with_two_pregnancies():
    pregs = [preg(1, "h1", lmp=date(2025, 1, 1), labor=date(2025, 10, 1)),
             preg(2, "h1", lmp=date(2025, 10, 1), labor=None)]
    out = select_refers([ref(1, date(2025, 10, 20), "h1", pdx="O149"),
                         ref(1, date(2025, 10, 20), "h1", pdx="O149")], pregs, CFG)
    assert len(out) == 1 and out[0]["reason"] == "both"


def test_refer_open_pregnancy_window_44_weeks():
    pregs = [preg(1, "h1", lmp=date(2026, 1, 1), labor=None)]
    out = select_refers([ref(1, date(2026, 11, 5), "h1"), ref(2, date(2026, 11, 6), "h1")], pregs, CFG)
    assert [r["refer_id"] for r in out] == [1]       # lmp + 308 วัน = 2026-11-05


def test_refer_no_lmp_falls_back_to_dx():
    pregs = [preg(1, "h1", lmp=None)]
    out = select_refers([ref(1, date(2026, 3, 1), "h1"), ref(2, date(2026, 3, 1), "h1", pdx="O200")], pregs, CFG)
    assert [(r["refer_id"], r["reason"]) for r in out] == [(2, "dx")]


def test_refer_group_uses_pregnancy_age_when_in_registry():
    out = select_refers([ref(1, date(2026, 3, 1), "h1", age=20)], [preg(1, "h1", age=19)], CFG)
    assert out[0]["group"] == "teen"


def test_refer_summary_months_filled_and_chapters():
    rows = [dict(ref(1, date(2026, 11, 3), pdx="Z340", minutes=30), group="teen", reason="dx"),
            dict(ref(2, date(2026, 11, 9), pdx="O14", minutes=50), group="elder", reason="dx"),
            dict(ref(3, date(2026, 11, 9), pdx=None), group=None, reason="registry")]
    s = refer_summary(rows, date(2026, 10, 1), date(2026, 12, 31))
    assert [m["month"] for m in s["monthly"]] == ["2026-10", "2026-11", "2026-12"]
    assert s["monthly"][1] == {"month": "2026-11", "teen": 1, "repro": 0, "elder": 1, "unknown": 1}
    assert s["monthly"][0]["teen"] == 0 and s["total"] == 3
    chapters = {r["chapter"] for r in s["table"]}
    assert chapters == {"Z3x", "O", "ไม่ระบุ"}
    o = next(r for r in s["table"] if r["chapter"] == "O")
    assert o["n"] == 1 and o["avg_min"] == 50.0 and o["dest_name"] == "รพ.มหาราช"


def test_top_dx_limit_10_by_3char():
    rows = []
    for i in range(12):
        for k in range(i + 1):
            rows.append(dict(ref(len(rows), date(2026, 10, 1), pdx=f"O{10 + i}{k % 10}", dx_name=f"dx{i}"),
                             group="repro", reason="dx"))
    s = refer_summary(rows, date(2026, 10, 1), date(2026, 10, 31))
    assert len(s["top_dx"]) == 10
    assert s["top_dx"][0] == {"code3": "O21", "name": "dx11", "n": 12, "pct": round(12 * 100 / len(rows), 1)}


def test_dest_sorted_and_unnamed():
    rows = [dict(ref(1, date(2026, 10, 1), dest="A", dest_name=None), group=None, reason="dx"),
            dict(ref(2, date(2026, 10, 1), dest="B", dest_name="รพ.บี"), group=None, reason="dx"),
            dict(ref(3, date(2026, 10, 2), dest="B", dest_name="รพ.บี"), group=None, reason="dx")]
    s = refer_summary(rows, date(2026, 10, 1), date(2026, 10, 31))
    assert s["dest"] == [{"code": "B", "name": "รพ.บี", "n": 2}, {"code": "A", "name": "A", "n": 1}]
