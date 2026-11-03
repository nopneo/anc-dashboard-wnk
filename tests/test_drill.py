"""รายชื่อเบื้องหลังตัวเลขต้องนับได้เท่ากับตัวเลขบนแดชบอร์ดทุกช่อง — ข้อมูลสุ่ม (seed คงที่) หลายรูปแบบ"""

import random
from datetime import date, timedelta

import pytest

import drill
import metrics
import risk27
from config import load_config

CFG = load_config({})
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)
H = CFG.hospcode
PCU_MAP = {"30250101": ("03929", "รพ.สต.ก"), "30250102": ("03930", "รพ.สต.ข"), "30250201": (H, "เขต รพ.")}
VILLAGES = ["30250101", "30250102", "30250201", "30250301", "99999999", None]


def _day(rng, a, b):
    return a + timedelta(days=rng.randint(0, (b - a).days))


def dataset(seed):
    rng = random.Random(seed)
    pregs, visits, pnc, infants, refers = [], [], [], [], []
    for i in range(1, 121):
        reg = _day(rng, date(2025, 3, 1), date(2026, 6, 30))
        lmp = reg - timedelta(weeks=rng.randint(4, 24)) if rng.random() < .9 else None
        start = lmp or reg
        labor = start + timedelta(weeks=rng.randint(33, 41)) if rng.random() < .7 else None
        p = {"anc_id": i, "hn": f"h{i}", "age": rng.choice([None, 13, 14, 16, 17, 19, 22, 28, 34, 35, 38, 42]),
             "village": rng.choice(VILLAGES), "register_date": reg, "lmp": lmp, "labor_date": labor,
             "hct_late": rng.choice([None, 29.0, 31.0, 33.0, 36.0]), "thai": rng.random() < .9,
             "labour_hospcode": rng.choice([H, H, "10666", None]), "labour_place": "รพ.อื่น",
             "death_date": (labor or reg) + timedelta(days=3) if rng.random() < .03 else None}
        for f in ("has_dt", "has_dental", "has_iodine", "q_cbc", "q_thal", "q_us", "q_down", "q_dm", "has_risk",
                  "cx_htn", "cx_gdm", "cx_pph", "cx_preterm"):
            p[f] = rng.random() < .6
        pregs.append(p)
        for _ in range(rng.randint(0, 9)):
            ga = rng.randint(4, 41)
            pre = rng.random() < .2
            visits.append({"anc_id": i, "date": start + timedelta(weeks=ga) if rng.random() < .95 else None,
                           "ga": None if pre or rng.random() < .1 else ga, "precare": pre})
        if labor:
            for _ in range(rng.randint(0, 3)):
                pnc.append({"anc_id": i, "date": labor + timedelta(days=rng.randint(0, 45))})
            refers.append({"refer_id": i, "date": _day(rng, D1, D2), "hn": p["hn"], "pdx": "O149",
                           "dx_name": "x", "dest": "10666", "dest_name": "y", "age": p["age"],
                           "village": p["village"], "minutes": 30, "reason": "dx",
                           "group": metrics.age_group(p["age"])})
    for j in range(40):
        infants.append({"birth_date": _day(rng, date(2025, 12, 1), date(2026, 7, 30)),
                        "weight": rng.choice([None, 1800, 2400, 2600, 3200]), "alive": rng.random() < .9,
                        "village": rng.choice(VILLAGES), "apgar1": rng.choice([None, 5, 8, 9]),
                        "asphyxia": rng.random() < .1, "delivery_type": rng.choice(["1", "5", None]),
                        "hn": f"h{j}"})
    hits = {"form": {}, "dx": {}, "text": {}, "body": {}}
    for p in pregs:
        i = p["anc_id"]
        if rng.random() < .3:
            hits["form"][i] = set(rng.sample([str(n) for n in range(1, 19)], 2))
        if rng.random() < .3:
            hits["dx"][i] = {rng.choice(["O30", "I10", "E11", "O365", "O36"])}
        if rng.random() < .3:
            hits["text"][i] = {rng.choice([it["key"] for it in risk27.ITEMS])}
        if rng.random() < .7:
            hits["body"][i] = (rng.choice([None, 140, 150, 160]), rng.choice([None, 40, 55, 80]))
    return {"pregs": pregs, "visits": visits, "pnc": pnc, "infants": infants, "refers": refers, "risk_hits": hits}


AREAS = {"all": None, "area": lambda p: metrics.in_area(p, CFG)}


def M(data, key, area=None, **f):
    m = drill.members(key, data, D1, D2, CFG, area, PCU_MAP, **f)
    return len(m["rows"]), sum(1 for _, ok in m["rows"] if ok)


def check_rate(data, key, r, area=None, **f):
    den, num = M(data, key, area, **f)
    assert (num, den) == (r["num"], r["den"]), (key, f)


def check_count(data, key, n, area=None, **f):
    assert M(data, key, area, **f)[0] == n, (key, f)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("scope", ["all", "area"])
def test_indicators_match(seed, scope):
    data, area = dataset(seed), AREAS[scope]
    ind = metrics.indicators(data["pregs"], data["visits"], data["infants"], [], D1, D2, CFG,
                             pnc=data["pnc"], area=area)
    check_count(data, "new", ind["new"]["value"], area)
    for key in ("early12", "visit5", "visit8", "postnatal", "quality", "iodine", "dt", "dental", "anemia", "lbw"):
        check_rate(data, key, ind[key], area)
    for part in ind["quality_parts"]:
        check_rate(data, part["key"], part["rate"], area)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("scope", ["all", "area"])
def test_outcomes_match(seed, scope):
    data, area = dataset(seed), AREAS[scope]
    out = metrics.outcomes(data["pregs"], data["infants"], [], D1, D2, CFG, area=area)
    check_rate(data, "preterm", out["preterm"], area)
    check_rate(data, "asphyxia", out["asphyxia"], area)
    den, here = M(data, "place_here", area)
    assert (here, den) == (out["place"]["here"], out["place"]["den"])
    for key in ("bba", "stillbirth", "maternal_death"):
        check_count(data, key, out[key], area)
    for c in out["complications"]:
        check_rate(data, c["key"], c, area)
    t = metrics.tracking(data["pregs"], data["visits"], D2)
    assert M(data, "open", area) == (t["open"], t["early12_so_far"])
    check_count(data, "refer", len(data["refers"]), area)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("scope", ["all", "area"])
def test_age_and_pcu_tables_match(seed, scope):
    data, area = dataset(seed), AREAS[scope]
    age = metrics.by_age(data["pregs"], data["visits"], D1, D2, CFG, area=area)
    for g, row in age.items():
        check_count(data, "new", row["new"], area, age=g)
        for key in ("early12", "visit5", "anemia"):
            check_rate(data, key, row[key], area, age=g)
    check_count(data, "new", age["teen"]["lt15"], area, age="lt15")
    check_count(data, "new", age["teen"]["15_19"], area, age="15_19")

    rows = metrics.by_pcu(data["pregs"], data["visits"], data["infants"], data["refers"], D1, D2, CFG, PCU_MAP,
                          area=area)
    for row in rows:
        pcu = row["hospcode"]
        check_count(data, "new", row["new"], area, pcu=pcu)
        check_count(data, "refer", row["refer"], area, pcu=pcu)
        for key in ("early12", "visit5", "dt", "anemia", "lbw"):
            check_rate(data, key, row[key], area, pcu=pcu)
        for g in metrics.AGE_GROUPS:
            check_count(data, "new", row[g], area, pcu=pcu, age=g)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_risk27_match(seed):
    data = dataset(seed)
    new = [p for p in data["pregs"] if D1 <= p["register_date"] <= D2]
    res = risk27.summarize(new, data["risk_hits"], CFG)
    check_count(data, "r27_any", res["den"])
    assert M(data, "r27_any")[1] == res["any"]["num"]
    for it in res["items"]:
        assert M(data, "r27_" + it["key"])[1] == it["n"], it["key"]
    for gr in res["groups"]:
        assert M(data, "r27g_" + gr["key"])[1] == gr["num"], gr["key"]
    for ex in res["extras"]:
        assert M(data, "r27_" + ex["key"])[1] == ex["n"], ex["key"]


def test_unknown_key_returns_none():
    assert drill.members("nope", dataset(1), D1, D2, CFG, None, PCU_MAP) is None
    assert drill.members("r27_nope", dataset(1), D1, D2, CFG, None, PCU_MAP) is None


def test_every_key_has_a_label():
    for key in drill.keys():
        m = drill.members(key, dataset(1), D1, D2, CFG, None, PCU_MAP)
        assert m["label"] and m["kind"] in ("preg", "infant", "refer"), key


def test_pcu_filter_without_map_does_not_crash():
    m = drill.members("new", dataset(1), D1, D2, CFG, None, None, pcu="03929")
    assert m["rows"] == []
