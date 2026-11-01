"""คำนวณตัวชี้วัด ANC จากแถวข้อมูลที่ queries.py ดึงมา — ฟังก์ชันบริสุทธิ์ ไม่แตะฐานข้อมูล

หน่วยนับหลัก = ครรภ์ (person_anc_id) · นิยามตาม spec §4 และฟิลด์ 43 แฟ้ม
  Pregnancy {anc_id, hn, age, village, register_date, lmp, labor_date, hct_late, has_dt, has_dental}
  Visit     {anc_id, date, ga, precare}       (precare = ฝากครรภ์ที่ หน่วยบริการอื่น)
  Infant    {birth_date, weight, alive, village}
ตัวหารของอัตราส่วนใหญ่ = ครรภ์ที่คลอดในช่วง (ต้องดูย้อนทั้งครรภ์) · ตัวหาร 0 → None
"""

import calendar
from collections import defaultdict
from datetime import timedelta

#: ช่วงอายุครรภ์ (สัปดาห์) ของ ANC ครบ 5 ครั้งคุณภาพ
GA_BUCKETS = ((0, 12), (13, 20), (21, 26), (27, 32), (33, 40))
IND_KEYS = ("new", "visits", "per_month", "early12", "visit5", "dt", "dental", "anemia", "lbw", "wait")
AGE_GROUPS = ("teen", "repro", "elder")
#: ตัวชี้วัดที่ค่ายิ่งต่ำยิ่งดี
LOWER_BETTER = {"anemia", "lbw"}
LOW_BASE = 5
#: ครรภ์ที่ไม่ปิดในทะเบียนเกินนี้ (นับจาก LMP) ไม่ถือว่ากำลังตั้งครรภ์
MAX_PREG_DAYS = 44 * 7


def age_group(age):
    if age is None:
        return None
    return "teen" if age < 20 else "repro" if age < 35 else "elder"


def teen_sub(age):
    if age is None or age >= 20:
        return None
    return "lt15" if age < 15 else "15_19"


def visit_ga(visit, lmp):
    if visit.get("ga") is not None:
        return int(visit["ga"])
    if lmp is None or visit.get("date") is None:
        return None
    return (visit["date"] - lmp).days // 7


def ga_bucket(week):
    if week is None:
        return None
    for i, (lo, hi) in enumerate(GA_BUCKETS):
        if lo <= week <= hi:
            return i
    return None


def pct(num, den):
    return round(num * 100 / den, 1) if den else None


def months_in_range(d1, d2):
    total, d = 0.0, d1
    while d <= d2:
        dim = calendar.monthrange(d.year, d.month)[1]
        end = min(d2, d.replace(day=dim))
        total += ((end - d).days + 1) / dim
        d = end + timedelta(days=1)
    return total


def _in(d, d1, d2):
    return d is not None and d1 <= d <= d2


def _count(n):
    return {"num": n, "den": None, "value": n, "target": None, "ok": None, "low_base": False}


def _rate(key, num, den, cfg):
    value = pct(num, den)
    target = cfg.targets.get(key)
    ok = None
    if value is not None and target is not None:
        ok = value <= target if key in LOWER_BETTER else value >= target
    return {"num": num, "den": den, "value": value, "target": target, "ok": ok,
            "low_base": 0 < den < LOW_BASE}


def _by_anc(visits):
    out = defaultdict(list)
    for v in visits:
        out[v["anc_id"]].append(v)
    return out


def _delivered(pregs, d1, d2):
    return [p for p in pregs if _in(p.get("labor_date"), d1, d2)]


def _first_ga(p, vs):
    """GA ของการฝากครรภ์ครั้งแรก (รวมที่หน่วยบริการอื่น) · ไม่มีวันที่ = None"""
    dated = [v for v in vs if v.get("date") is not None]
    if not dated:
        return None
    return visit_ga(min(dated, key=lambda v: v["date"]), p.get("lmp"))


def _is_5visit(p, vs):
    return {ga_bucket(visit_ga(v, p.get("lmp"))) for v in vs} >= set(range(len(GA_BUCKETS)))


def rate_early12(delivered, vmap, cfg):
    num = sum(1 for p in delivered if (g := _first_ga(p, vmap.get(p["anc_id"], []))) is not None and g <= 12)
    return _rate("early12", num, len(delivered), cfg)


def rate_visit5(delivered, vmap, cfg):
    return _rate("visit5", sum(1 for p in delivered if _is_5visit(p, vmap.get(p["anc_id"], []))), len(delivered), cfg)


def rate_flag(key, flag, delivered, cfg):
    return _rate(key, sum(1 for p in delivered if p.get(flag)), len(delivered), cfg)


def rate_anemia(delivered, cfg):
    tested = [p["hct_late"] for p in delivered if p.get("hct_late") is not None]
    return _rate("anemia", sum(1 for h in tested if h < cfg.hct_cutoff), len(tested), cfg)


def rate_lbw(infants, d1, d2, cfg):
    live = [i["weight"] for i in infants
            if _in(i.get("birth_date"), d1, d2) and i.get("alive") and i.get("weight")]
    return _rate("lbw", sum(1 for w in live if w < cfg.lbw_grams), len(live), cfg)


def indicators(pregs, visits, infants, waits, d1, d2, cfg):
    vmap = _by_anc(visits)
    delivered = _delivered(pregs, d1, d2)
    n_visits = sum(1 for v in visits if not v.get("precare") and _in(v.get("date"), d1, d2))
    waits = [w for w in waits if w is not None]
    months = months_in_range(d1, d2)
    wait = _count(round(sum(waits) / len(waits), 1) if waits else None)
    wait["den"] = len(waits)
    return {
        "new": _count(sum(1 for p in pregs if _in(p.get("register_date"), d1, d2))),
        "visits": _count(n_visits),
        "per_month": _count(round(n_visits / months, 1) if months else None),
        "early12": rate_early12(delivered, vmap, cfg),
        "visit5": rate_visit5(delivered, vmap, cfg),
        "dt": rate_flag("dt", "has_dt", delivered, cfg),
        "dental": rate_flag("dental", "has_dental", delivered, cfg),
        "anemia": rate_anemia(delivered, cfg),
        "lbw": rate_lbw(infants, d1, d2, cfg),
        "wait": wait,
    }


def by_age(pregs, visits, d1, d2, cfg):
    vmap = _by_anc(visits)
    new = [p for p in pregs if _in(p.get("register_date"), d1, d2)]
    delivered = _delivered(pregs, d1, d2)
    out = {}
    for g in AGE_GROUPS:
        gnew = [p for p in new if age_group(p.get("age")) == g]
        gdel = [p for p in delivered if age_group(p.get("age")) == g]
        row = {"new": len(gnew), "share": pct(len(gnew), len(new)),
               "early12": rate_early12(gdel, vmap, cfg), "visit5": rate_visit5(gdel, vmap, cfg),
               "anemia": rate_anemia(gdel, cfg)}
        if g == "teen":
            row["lt15"] = sum(1 for p in gnew if teen_sub(p.get("age")) == "lt15")
            row["15_19"] = sum(1 for p in gnew if teen_sub(p.get("age")) == "15_19")
        out[g] = row
    return out


def _pregnant_on(p, day):
    start = p.get("lmp") or p.get("register_date")
    if start is None or p.get("register_date") is None or p["register_date"] > day:
        return False
    if p.get("labor_date") is not None and p["labor_date"] <= day:
        return False
    return (day - start).days <= MAX_PREG_DAYS


def tracking(pregs, visits, d2):
    vmap = _by_anc(visits)
    open_ = [p for p in pregs if _pregnant_on(p, d2)]
    early = sum(1 for p in open_ if (g := _first_ga(p, vmap.get(p["anc_id"], []))) is not None and g <= 12)
    return {"open": len(open_), "early12_so_far": early}
