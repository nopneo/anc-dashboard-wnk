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


# ---------- refer ----------

def _dx_match(pdx, prefixes):
    code = (pdx or "").replace(".", "").strip().upper()
    return bool(code) and code.startswith(tuple(prefixes))


def _windows(pregs, cfg):
    """hn → [(วันเริ่ม, วันสิ้นสุด, อายุแม่)] ช่วงที่นับ refer เป็นงานแม่และเด็ก · ครรภ์ไม่มี LMP ไม่มีหน้าต่าง"""
    out = defaultdict(list)
    for p in pregs:
        lmp = p.get("lmp")
        if lmp is None or not p.get("hn"):
            continue
        end = (p["labor_date"] + timedelta(days=cfg.postpartum_days) if p.get("labor_date")
               else lmp + timedelta(days=MAX_PREG_DAYS))
        out[p["hn"]].append((lmp, end, p.get("age")))
    return out


def select_refers(refers, pregs, cfg):
    win = _windows(pregs, cfg)
    seen, out = set(), []
    for r in refers:
        if r["refer_id"] in seen:
            continue
        hit = next((w for w in win.get(r.get("hn"), []) if r.get("date") and w[0] <= r["date"] <= w[1]), None)
        dx = _dx_match(r.get("pdx"), cfg.refer_dx_prefixes)
        if not hit and not dx:
            continue
        seen.add(r["refer_id"])
        age = hit[2] if hit and hit[2] is not None else r.get("age")
        out.append(dict(r, reason="both" if hit and dx else "registry" if hit else "dx", group=age_group(age)))
    return out


def dx_chapter(pdx):
    code = (pdx or "").replace(".", "").strip().upper()
    if not code:
        return "ไม่ระบุ"
    if code.startswith("O"):
        return "O"
    if code[:3] in ("Z32", "Z33", "Z34", "Z35", "Z36"):
        return "Z3x"
    return code[0]


def _months(d1, d2):
    out, y, m = [], d1.year, d1.month
    while (y, m) <= (d2.year, d2.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def refer_summary(refers, d1, d2):
    monthly = {m: {"month": m, "teen": 0, "repro": 0, "elder": 0, "unknown": 0} for m in _months(d1, d2)}
    dx, dest, table = {}, {}, defaultdict(list)
    for r in refers:
        month = r["date"].strftime("%Y-%m")
        if month in monthly:
            monthly[month][r.get("group") or "unknown"] += 1
        code = (r.get("pdx") or "").replace(".", "").strip().upper()[:3]
        if code:
            d = dx.setdefault(code, {"code3": code, "name": r.get("dx_name"), "n": 0})
            d["n"] += 1
            d["name"] = d["name"] or r.get("dx_name")
        dcode = r.get("dest") or ""
        dname = r.get("dest_name") or dcode or "ไม่ระบุ"
        dest.setdefault(dcode, {"code": dcode, "name": dname, "n": 0})["n"] += 1
        table[(month, dx_chapter(r.get("pdx")), dname)].append(r.get("minutes"))
    total = len(refers)
    top = sorted(dx.values(), key=lambda d: (-d["n"], d["code3"]))[:10]
    for d in top:
        d["pct"] = pct(d["n"], total)
    rows = []
    for (month, chapter, dname), mins in sorted(table.items()):
        m = [x for x in mins if x is not None]
        rows.append({"month": month, "chapter": chapter, "dest_name": dname, "n": len(mins),
                     "avg_min": round(sum(m) / len(m), 1) if m else None})
    return {"monthly": list(monthly.values()), "top_dx": top,
            "dest": sorted(dest.values(), key=lambda d: (-d["n"], d["code"])), "table": rows, "total": total}


# ---------- รพ.สต. ----------

UNMAPPED = ("", "นอกเขต/ไม่ระบุ")


def pcu_of(village, pcu_map):
    return pcu_map.get(village, UNMAPPED) if village else UNMAPPED


def by_pcu(pregs, visits, infants, refers, d1, d2, cfg, pcu_map):
    vmap = _by_anc(visits)
    groups = {pcu: {"pregs": [], "infants": [], "refer": 0} for pcu in set(pcu_map.values())}

    def bucket(village):
        return groups.setdefault(pcu_of(village, pcu_map), {"pregs": [], "infants": [], "refer": 0})

    for p in pregs:
        bucket(p.get("village"))["pregs"].append(p)
    for i in infants:
        bucket(i.get("village"))["infants"].append(i)
    for r in refers:
        bucket(r.get("village"))["refer"] += 1

    rows = []
    for (hcode, name), g in groups.items():
        new = [p for p in g["pregs"] if _in(p.get("register_date"), d1, d2)]
        delivered = _delivered(g["pregs"], d1, d2)
        row = {"hospcode": hcode, "name": name, "new": len(new),
               "early12": rate_early12(delivered, vmap, cfg), "visit5": rate_visit5(delivered, vmap, cfg),
               "dt": rate_flag("dt", "has_dt", delivered, cfg), "anemia": rate_anemia(delivered, cfg),
               "lbw": rate_lbw(g["infants"], d1, d2, cfg), "refer": g["refer"]}
        for a in AGE_GROUPS:
            row[a] = sum(1 for p in new if age_group(p.get("age")) == a)
        rows.append(row)
    rows.sort(key=lambda r: (r["name"] == UNMAPPED[1], r["name"]))
    return rows


def unmapped_villages(pregs, pcu_map):
    n = defaultdict(int)
    for p in pregs:
        v = p.get("village") or ""
        if v not in pcu_map:
            n[v] += 1
    return sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))


# ---------- Alert ----------

IND_LABELS = {"early12": "ฝากครรภ์ก่อน 12 wk", "visit5": "ANC ครบ 5 ครั้ง", "dt": "วัคซีน dT",
              "dental": "ตรวจช่องปาก", "anemia": "โลหิตจางใกล้คลอด", "lbw": "ทารก LBW"}
_ACTIONS = {"early12": "ค้นหาหญิงตั้งครรภ์ในชุมชนร่วมกับ อสม.", "visit5": "ติดตามนัด ANC ตามช่วงอายุครรภ์",
            "dt": "ตรวจการบันทึกวัคซีน dT / ฉีดตามนัด", "dental": "ส่งตรวจฟันในวันฝากครรภ์ครั้งแรก",
            "anemia": "ติดตามยาเสริมธาตุเหล็กและตรวจ Hct ซ้ำ", "lbw": "ทบทวนรายที่คลอดน้ำหนักน้อย"}


def alerts(ind, pcu_rows, age, unmapped):
    out = []
    for key, label in IND_LABELS.items():
        r = ind.get(key) or {}
        if r.get("ok") is False:
            sign = "≤" if key in LOWER_BETTER else "≥"
            out.append({"level": "red", "text": f"{label} {r['value']}% (เป้า {sign} {r['target']}%)",
                        "owner": "งานฝากครรภ์", "action": _ACTIONS[key]})
    lt15 = (age.get("teen") or {}).get("lt15", 0)
    if lt15:
        out.append({"level": "red", "text": f"แม่อายุต่ำกว่า 15 ปี {lt15} ราย", "owner": "งานแม่และเด็ก / ทีมสหวิชาชีพ",
                    "action": "ประเมินความปลอดภัยและส่งต่อทีมคุ้มครองเด็ก"})
    for row in pcu_rows:
        if row["name"] == UNMAPPED[1]:
            continue
        low = [IND_LABELS[k] for k in ("early12", "visit5")
               if row[k].get("ok") is False and (row[k].get("den") or 0) >= LOW_BASE]
        if low:
            out.append({"level": "amber", "text": f"{row['name']}: {' / '.join(low)} ต่ำกว่าเป้า",
                        "owner": row["name"], "action": "ทบทวนรายชื่อร่วมกับ รพ.สต."})
    if unmapped:
        out.append({"level": "info", "text": f"ยังไม่ได้จับคู่ รพ.สต. {len(unmapped)} หมู่บ้าน",
                    "owner": "ผู้ดูแลระบบ", "action": "เติมไฟล์ pcu_map.csv จากหน้า /check"})
    return out


TH_MONTHS = ("ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.")


def monthly_trend(pregs, visits, d1, d2):
    """รายเดือน: ฝากครรภ์รายใหม่ และครั้งบริการ ANC ที่ รพ. (ไม่นับ precare)"""
    rows = {m: {"month": m, "label": TH_MONTHS[int(m[5:]) - 1], "new": 0, "visits": 0} for m in _months(d1, d2)}
    for p in pregs:
        if _in(p.get("register_date"), d1, d2):
            rows[p["register_date"].strftime("%Y-%m")]["new"] += 1
    for v in visits:
        if not v.get("precare") and _in(v.get("date"), d1, d2):
            rows[v["date"].strftime("%Y-%m")]["visits"] += 1
    return list(rows.values())
