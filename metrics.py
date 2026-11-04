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

from config import TEEN_REPEAT_TARGETS, VISIT8_TARGETS

#: ช่วงอายุครรภ์ (สัปดาห์) ของ ANC ครบ 5 ครั้งตามเกณฑ์ (เอกสาร KPI): ≤12 · 13–<20 · 20–<26 · 26–<32 · 32–40
GA_BUCKETS = ((0, 12), (13, 19), (20, 25), (26, 31), (32, 40))
#: ฝากครรภ์ครบ 8 ครั้งตามเกณฑ์ (เอกสาร 1.7) — อายุครรภ์เป็นสัปดาห์เต็ม: ≤12+6 · 13–20+6 · 21–26+6 · 27–30+6 · 31–34+6 · 35–36+6 · 37–38+6 · 39–40+6
GA_BUCKETS_8 = ((0, 12), (13, 20), (21, 26), (27, 30), (31, 34), (35, 36), (37, 38), (39, 40))
#: ดูแลหลังคลอดครบ 3 ครั้ง: วันที่ 1–7 · 8–15 · 16–42 นับจากวันคลอด
PNC_WINDOWS = ((1, 7), (8, 15), (16, 42))
#: กิจกรรมฝากครรภ์คุณภาพ (HDC) — คีย์ใน Pregnancy
QUALITY_PARTS = (("q_cbc", "CBC / Hct / Hb"), ("q_thal", "คัดกรองธาลัสซีเมีย"), ("q_us", "อัลตราซาวด์"),
                 ("q_down", "คัดกรองดาวน์"), ("q_dm", "คัดกรองเบาหวาน"))
IND_KEYS = ("new", "visits", "per_month", "early12", "visit5", "visit8", "postnatal", "quality", "iodine",
            "dt", "dental", "anemia", "lbw", "teen_repeat")
AGE_GROUPS = ("teen", "repro", "elder")
#: ตัวชี้วัดที่ค่ายิ่งต่ำยิ่งดี
LOWER_BETTER = {"anemia", "lbw", "asphyxia", "teen_repeat"}
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


def ga_bucket(week, buckets=GA_BUCKETS):
    if week is None:
        return None
    for i, (lo, hi) in enumerate(buckets):
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


def _delivered(pregs, d1, d2, area=None):
    """ครรภ์ที่คลอดในช่วง = ตัวหารของ KPI · area = เงื่อนไข "ในเขต" (None = ทั้งหมด)"""
    return [p for p in pregs if _in(p.get("labor_date"), d1, d2) and (area is None or area(p))]


def in_area(p, cfg):
    """ตัวหารตามเอกสาร KPI: หญิงไทย และ (อาศัยในอำเภอ หรือ อาศัยนอกเขตแต่มาคลอดที่ รพ.)"""
    if not p.get("thai"):
        return False
    resident = (p.get("village") or "").startswith(cfg.chwpart + cfg.amppart)
    return resident or p.get("labour_hospcode") == cfg.hospcode


def labor_due(pregs, d1, d2):
    """ครรภ์ที่ LMP ครบ 42 สัปดาห์ ณ d2 (LMP ไม่เกิน 1 ปีก่อน d1) — ควรมีวันคลอดในทะเบียนแล้ว"""
    return [p for p in pregs if p.get("lmp") and (d2 - p["lmp"]).days >= 42 * 7
            and p["lmp"] >= d1 - timedelta(days=365)]


def labor_completeness(pregs, d1, d2):
    """ครรภ์ครบกำหนด (labor_due) มีวันคลอดในทะเบียนกี่ % — ต่ำ = ตัวหาร KPI ขาด"""
    due = labor_due(pregs, d1, d2)
    rec = sum(1 for p in due if p.get("labor_date"))
    return {"due": len(due), "recorded": rec, "pct": pct(rec, len(due))}


def _first_ga(p, vs):
    """GA ของการฝากครรภ์ครั้งแรก (รวมที่หน่วยบริการอื่น) · ไม่มีวันที่ = None"""
    dated = [v for v in vs if v.get("date") is not None]
    if not dated:
        return None
    return visit_ga(min(dated, key=lambda v: v["date"]), p.get("lmp"))


def _is_5visit(p, vs):
    return {ga_bucket(visit_ga(v, p.get("lmp"))) for v in vs} >= set(range(len(GA_BUCKETS)))


def _is_8visit(p, vs):
    return {ga_bucket(visit_ga(v, p.get("lmp")), GA_BUCKETS_8) for v in vs} >= set(range(len(GA_BUCKETS_8)))


def missing_buckets(p, vs, buckets=GA_BUCKETS):
    """ช่วงอายุครรภ์ (สัปดาห์) ที่ยังไม่มีการฝากครรภ์ เช่น ["13–19", "26–31"] — ใช้ในหน้ารายชื่อ"""
    have = {ga_bucket(visit_ga(v, p.get("lmp")), buckets) for v in vs}
    return [f"{lo}–{hi}" if lo else f"≤{hi}" for i, (lo, hi) in enumerate(buckets) if i not in have]


def is_early12(p, vs):
    g = _first_ga(p, vs)
    return g is not None and g <= 12


def rate_early12(delivered, vmap, cfg):
    num = sum(1 for p in delivered if is_early12(p, vmap.get(p["anc_id"], [])))
    return _rate("early12", num, len(delivered), cfg)


def rate_visit5(delivered, vmap, cfg):
    return _rate("visit5", sum(1 for p in delivered if _is_5visit(p, vmap.get(p["anc_id"], []))), len(delivered), cfg)


def _fy_target(key, table, d2, cfg):
    """เป้าที่ตั้งใน env หรือตามปีงบประมาณของวันสิ้นสุดช่วง (นอกตารางใช้ค่าขอบ)"""
    if cfg.targets.get(key) is not None:
        return cfg.targets[key]
    fy = (d2.year + 1 if d2.month >= 10 else d2.year) + 543
    return table[min(max(fy, min(table)), max(table))]


def visit8_target(d2, cfg):
    return _fy_target("visit8", VISIT8_TARGETS, d2, cfg)


def teen_repeat_target(d2, cfg):
    return _fy_target("teen_repeat", TEEN_REPEAT_TARGETS, d2, cfg)


def rate_visit8(delivered, vmap, d2, cfg):
    num = sum(1 for p in delivered if _is_8visit(p, vmap.get(p["anc_id"], [])))
    r = _rate("visit8", num, len(delivered), cfg)
    r["target"] = visit8_target(d2, cfg)
    r["ok"] = None if r["value"] is None else r["value"] >= r["target"]
    return r


def rate_flag(key, flag, delivered, cfg):
    return _rate(key, sum(1 for p in delivered if p.get(flag)), len(delivered), cfg)


def teen_repeat_base(delivered):
    """เอกสาร 2.1: ครรภ์ที่สิ้นสุด (คลอด/แท้ง) ในช่วงและแม่อายุ < 20 ปี ณ วันสิ้นสุดครรภ์"""
    return [p for p in delivered if p.get("age_labor") is not None and p["age_labor"] < 20]


def is_repeat(p):
    return (p.get("gravida") or 0) >= 2


def rate_teen_repeat(delivered, d2, cfg):
    base = teen_repeat_base(delivered)
    r = _rate("teen_repeat", sum(1 for p in base if is_repeat(p)), len(base), cfg)
    r["target"] = teen_repeat_target(d2, cfg)
    r["ok"] = None if r["value"] is None else r["value"] <= r["target"]
    return r


def anemia_base(delivered):
    return [p for p in delivered if p.get("hct_late") is not None]


def rate_anemia(delivered, cfg):
    tested = anemia_base(delivered)
    return _rate("anemia", sum(1 for p in tested if p["hct_late"] < cfg.hct_cutoff), len(tested), cfg)


def live_weighed(infants, d1, d2):
    return [i for i in infants if _in(i.get("birth_date"), d1, d2) and i.get("alive") and i.get("weight")]


def rate_lbw(infants, d1, d2, cfg):
    live = live_weighed(infants, d1, d2)
    return _rate("lbw", sum(1 for i in live if i["weight"] < cfg.lbw_grams), len(live), cfg)


def postnatal_base(pregs, pnc, d1, d2):
    """(ตัวหาร, ฟังก์ชันตัวตั้ง) — ตัวหาร = คลอดในช่วงและพ้นหลังคลอด 42 วัน ณ d2 · ตัวตั้ง = ได้ดูแลครบทั้ง 3 ช่วง"""
    days = defaultdict(set)
    by = {p["anc_id"]: p for p in pregs}
    for c in pnc:
        p = by.get(c["anc_id"])
        if p and p.get("labor_date") and c.get("date"):
            days[c["anc_id"]].add((c["date"] - p["labor_date"]).days)
    den = [p for p in _delivered(pregs, d1, d2) if (d2 - p["labor_date"]).days >= PNC_WINDOWS[-1][1]]
    return den, lambda p: all(any(lo <= x <= hi for x in days[p["anc_id"]]) for lo, hi in PNC_WINDOWS)


def rate_postnatal(pregs, pnc, d1, d2, cfg):
    den, ok = postnatal_base(pregs, pnc, d1, d2)
    return _rate("postnatal", sum(1 for p in den if ok(p)), len(den), cfg)


def iodine_base(pregs, visits, d1, d2):
    """ครรภ์ที่มาฝากครรภ์ที่ รพ. ในช่วง (Workload)"""
    came = {v["anc_id"] for v in visits if not v.get("precare") and _in(v.get("date"), d1, d2)}
    return [p for p in pregs if p["anc_id"] in came]


def rate_iodine(pregs, visits, d1, d2, cfg):
    """ตัวหาร = ครรภ์ที่มาฝากครรภ์ที่ รพ. ในช่วง (Workload) · ตัวตั้ง = ได้ยาเม็ดที่มีไอโอดีนระหว่างตั้งครรภ์"""
    den = iodine_base(pregs, visits, d1, d2)
    return _rate("iodine", sum(1 for p in den if p.get("has_iodine")), len(den), cfg)


def quality(delivered, cfg):
    """ฝากครรภ์คุณภาพ (HDC): ได้ครบทั้ง 5 กิจกรรม · คืน (อัตรารวม, [อัตรารายกิจกรรม])"""
    keys = [k for k, _ in QUALITY_PARTS]
    total = _rate("quality", sum(1 for p in delivered if all(p.get(k) for k in keys)), len(delivered), cfg)
    parts = [{"key": k, "label": label, "rate": _rate(k, sum(1 for p in delivered if p.get(k)), len(delivered), cfg)}
             for k, label in QUALITY_PARTS]
    return total, parts


def indicators(pregs, visits, infants, d1, d2, cfg, pnc=(), area=None):
    """area = เงื่อนไขตัวหารในเขต (ใช้กับ KPI ที่หารด้วยครรภ์ที่คลอด) · ข้อมูลบริการ / ไอโอดีน (Workload) นับทั้งหมด"""
    vmap = _by_anc(visits)
    delivered = _delivered(pregs, d1, d2, area)
    n_visits = sum(1 for v in visits if not v.get("precare") and _in(v.get("date"), d1, d2))
    months = months_in_range(d1, d2)
    q_total, q_parts = quality(delivered, cfg)
    return {
        "new": _count(sum(1 for p in pregs if _in(p.get("register_date"), d1, d2))),
        "visits": _count(n_visits),
        "per_month": _count(round(n_visits / months, 1) if months else None),
        "early12": rate_early12(delivered, vmap, cfg),
        "visit5": rate_visit5(delivered, vmap, cfg),
        "visit8": rate_visit8(delivered, vmap, d2, cfg),
        "postnatal": rate_postnatal([p for p in pregs if area is None or area(p)], pnc, d1, d2, cfg),
        "quality": q_total,
        "quality_parts": q_parts,
        "iodine": rate_iodine(pregs, visits, d1, d2, cfg),
        "dt": rate_flag("dt", "has_dt", delivered, cfg),
        "dental": rate_flag("dental", "has_dental", delivered, cfg),
        "anemia": rate_anemia(delivered, cfg),
        "lbw": rate_lbw(infants, d1, d2, cfg),
        "teen_repeat": rate_teen_repeat(delivered, d2, cfg),
    }


def by_age(pregs, visits, d1, d2, cfg, area=None):
    vmap = _by_anc(visits)
    new = [p for p in pregs if _in(p.get("register_date"), d1, d2)]
    delivered = _delivered(pregs, d1, d2, area)
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


def pregnant_on(p, day):
    start = p.get("lmp") or p.get("register_date")
    if start is None or p.get("register_date") is None or p["register_date"] > day:
        return False
    if p.get("labor_date") is not None and p["labor_date"] <= day:
        return False
    return (day - start).days <= MAX_PREG_DAYS


def tracking(pregs, visits, d2):
    vmap = _by_anc(visits)
    open_ = [p for p in pregs if pregnant_on(p, d2)]
    early = sum(1 for p in open_ if is_early12(p, vmap.get(p["anc_id"], [])))
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


#: ชื่อหมวด ICD-10 ตามตัวอักษรแรกของรหัส (D, H มี 2 หมวดในตัวอักษรเดียว)
CHAPTER_NAMES = {
    "A": "โรคติดเชื้อและปรสิต", "B": "โรคติดเชื้อและปรสิต", "C": "เนื้องอก",
    "D": "เนื้องอก / โรคเลือดและภูมิคุ้มกัน", "E": "โรคต่อมไร้ท่อ โภชนาการ และเมแทบอลิซึม",
    "F": "ความผิดปกติทางจิตและพฤติกรรม", "G": "โรคระบบประสาท", "H": "โรคตาและหู",
    "I": "โรคระบบไหลเวียนเลือด", "J": "โรคระบบหายใจ", "K": "โรคระบบย่อยอาหาร", "L": "โรคผิวหนัง",
    "M": "โรคระบบกล้ามเนื้อและกระดูก", "N": "โรคระบบสืบพันธุ์และทางเดินปัสสาวะ", "O": "ตั้งครรภ์/คลอด",
    "P": "ภาวะในระยะปริกำเนิด", "Q": "รูปผิดปกติแต่กำเนิด", "R": "อาการและอาการแสดงผิดปกติ",
    "S": "การบาดเจ็บ", "T": "การบาดเจ็บ / การเป็นพิษ", "U": "รหัสใช้เป็นการเฉพาะ",
    "V": "สาเหตุภายนอก", "W": "สาเหตุภายนอก", "X": "สาเหตุภายนอก", "Y": "สาเหตุภายนอก",
    "Z": "ปัจจัยที่มีผลต่อสถานะสุขภาพ", "Z3x": "ดูแลครรภ์ (Z32–Z36)", "ไม่ระบุ": "ไม่มี Dx หลัก",
}


def chapter_name(chapter):
    return CHAPTER_NAMES.get(chapter, chapter)


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


def refer_summary(refers, d1, d2, exclude=()):
    """exclude = รหัสที่ไม่จัดอันดับใน Top 10 Dx (เช่น Z34 มาฝากครรภ์ ไม่ใช่ Dx ตอน refer) — ยังนับใน total และตาราง"""
    monthly = {m: {"month": m, "teen": 0, "repro": 0, "elder": 0, "unknown": 0} for m in _months(d1, d2)}
    dx, dest, table = {}, {}, defaultdict(list)
    excluded = 0
    for r in refers:
        month = r["date"].strftime("%Y-%m")
        if month in monthly:
            monthly[month][r.get("group") or "unknown"] += 1
        code = (r.get("pdx") or "").replace(".", "").strip().upper()[:3]
        if code and _dx_match(code, exclude):
            excluded += 1
        elif code:
            d = dx.setdefault(code, {"code3": code, "name": r.get("dx_name"), "n": 0})
            d["n"] += 1
            d["name"] = d["name"] or r.get("dx_name")
        dcode = r.get("dest") or ""
        dname = r.get("dest_name") or dcode or "ไม่ระบุ"
        dest.setdefault(dcode, {"code": dcode, "name": dname, "n": 0})["n"] += 1
        table[(month, dx_chapter(r.get("pdx")), dname)].append(r)
    total = len(refers)
    top = sorted(dx.values(), key=lambda d: (-d["n"], d["code3"]))[:10]
    for d in top:
        d["pct"] = pct(d["n"], total - excluded)
    rows = []
    for (month, chapter, dname), rs in sorted(table.items()):
        m = [r["minutes"] for r in rs if r.get("minutes") is not None]
        codes = {}
        for r in rs:
            c3 = (r.get("pdx") or "").replace(".", "").strip().upper()[:3]
            if c3:
                d = codes.setdefault(c3, {"code3": c3, "name": r.get("dx_name"), "n": 0})
                d["n"] += 1
                d["name"] = d["name"] or r.get("dx_name")
        rows.append({"month": month, "chapter": chapter, "chapter_name": chapter_name(chapter),
                     "dx": sorted(codes.values(), key=lambda d: (-d["n"], d["code3"])),
                     "dest_name": dname, "n": len(rs), "avg_min": round(sum(m) / len(m), 1) if m else None})
    return {"monthly": list(monthly.values()), "top_dx": top,
            "dest": sorted(dest.values(), key=lambda d: (-d["n"], d["code"])), "table": rows, "total": total,
            "dx_excluded": excluded, "dx_exclude": tuple(exclude)}


# ---------- รพ.สต. (แบบเดียวกับ mental_health_dashboard) ----------

#: หมู่ในอำเภอที่ไม่อยู่ใน village_pcu.csv (รวมครรภ์ที่ไม่มีที่อยู่) · ที่อยู่นอกอำเภอ
UNK = ("unk", "ในอำเภอ ไม่ทราบหมู่")
OUT = ("out", "นอกเขตอำเภอ")


def pcu_of(village, pcu_map, cfg):
    """หมู่บ้าน 8 หลัก → (รหัส, ชื่อ) ของ รพ.สต. · นอกอำเภอ cfg.chwpart/amppart = OUT · หมู่ที่ไม่อยู่ในไฟล์ = UNK"""
    if not village:
        return UNK
    if village[:4] != cfg.chwpart + cfg.amppart:
        return OUT
    return pcu_map.get(village, UNK)


def _pcu_order(pcu_map, cfg):
    """ลำดับแถว: รพ.สต. ตามชื่อ → เขต รพ. → ในอำเภอ ไม่ทราบหมู่ → นอกเขตอำเภอ"""
    names = dict(pcu_map.values())
    pcus = sorted(((c, n) for c, n in names.items() if c != cfg.hospcode), key=lambda x: x[1])
    return pcus + [(cfg.hospcode, names.get(cfg.hospcode) or "เขต รพ."), UNK, OUT]


def by_pcu(pregs, visits, infants, refers, d1, d2, cfg, pcu_map, area=None):
    vmap = _by_anc(visits)
    order = _pcu_order(pcu_map, cfg)
    groups = {code: {"pregs": [], "infants": [], "refer": 0} for code, _ in order}

    def bucket(village):
        return groups[pcu_of(village, pcu_map, cfg)[0]]

    for p in pregs:
        bucket(p.get("village"))["pregs"].append(p)
    for i in infants:
        bucket(i.get("village"))["infants"].append(i)
    for r in refers:
        bucket(r.get("village"))["refer"] += 1

    rows = []
    for hcode, name in order:
        g = groups[hcode]
        new = [p for p in g["pregs"] if _in(p.get("register_date"), d1, d2)]
        delivered = _delivered(g["pregs"], d1, d2, area)
        row = {"hospcode": hcode, "name": name, "new": len(new),
               "early12": rate_early12(delivered, vmap, cfg), "visit5": rate_visit5(delivered, vmap, cfg),
               "dt": rate_flag("dt", "has_dt", delivered, cfg), "anemia": rate_anemia(delivered, cfg),
               "lbw": rate_lbw(g["infants"], d1, d2, cfg), "refer": g["refer"]}
        for a in AGE_GROUPS:
            row[a] = sum(1 for p in new if age_group(p.get("age")) == a)
        rows.append(row)
    return rows


def unmapped_villages(pregs, pcu_map, cfg):
    """หมู่ในอำเภอที่ยังไม่อยู่ใน village_pcu.csv ('' = ไม่มีที่อยู่) พร้อมจำนวนครรภ์ เรียงมากไปน้อย"""
    n = defaultdict(int)
    for p in pregs:
        if pcu_of(p.get("village"), pcu_map, cfg) == UNK:
            n[p.get("village") or ""] += 1
    return sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))


# ---------- Alert ----------

IND_LABELS = {"early12": "ฝากครรภ์ก่อน 12 wk", "visit5": "ANC ครบ 5 ครั้ง", "visit8": "ANC ครบ 8 ครั้ง", "postnatal": "ดูแลหลังคลอดครบ 3 ครั้ง",
              "quality": "ฝากครรภ์คุณภาพ", "iodine": "ยาเม็ดไอโอดีน", "dt": "วัคซีน dT",
              "dental": "ตรวจช่องปาก", "anemia": "โลหิตจางใกล้คลอด", "lbw": "ทารก LBW",
              "teen_repeat": "ตั้งครรภ์ซ้ำในวัยรุ่น"}
_ACTIONS = {"early12": "ค้นหาหญิงตั้งครรภ์ในชุมชนร่วมกับ อสม.", "visit5": "ติดตามนัด ANC ตามช่วงอายุครรภ์",
            "visit8": "นัด ANC ให้ครบ 8 ช่วงอายุครรภ์ (≤12 · 13–20 · 21–26 · 27–30 · 31–34 · 35–36 · 37–38 · 39–40 wk)",
            "postnatal": "นัดเยี่ยมหลังคลอดวันที่ 1–7, 8–15, 16–42 ร่วมกับ รพ.สต.",
            "quality": "ตรวจกิจกรรมที่ขาด (lab / อัลตราซาวด์ / ดาวน์ / เบาหวาน)",
            "iodine": "จ่ายยาเม็ดเสริมไอโอดีนทุกครั้งที่ฝากครรภ์",
            "dt": "ตรวจการบันทึกวัคซีน dT / ฉีดตามนัด", "dental": "ส่งตรวจฟันในวันฝากครรภ์ครั้งแรก",
            "anemia": "ติดตามยาเสริมธาตุเหล็กและตรวจ Hct ซ้ำ", "lbw": "ทบทวนรายที่คลอดน้ำหนักน้อย",
            "teen_repeat": "ให้คำปรึกษาและคุมกำเนิดกึ่งถาวรหลังคลอด/แท้งในวัยรุ่น"}


def alerts(ind, pcu_rows, age, unmapped, outcome=None):
    out = []
    if outcome:
        if outcome.get("maternal_death"):
            out.append({"level": "red", "text": f"มารดาเสียชีวิต {outcome['maternal_death']} ราย",
                        "owner": "งานแม่และเด็ก / ทีมนำทางคลินิก", "action": "ทบทวนกรณีเสียชีวิต (Dead case conference)"})
        a = outcome.get("asphyxia") or {}
        if a.get("ok") is False:
            out.append({"level": "red", "text": f"ทารกแรกเกิดขาดออกซิเจน {a['value']} ต่อ 1,000 เกิดมีชีพ "
                                                f"(เป้า ≤ {a['target']})",
                        "owner": "ห้องคลอด", "action": "ทบทวนการเฝ้าระวังระหว่างคลอดและการกู้ชีพทารกแรกเกิด"})
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
        if row["hospcode"] in (UNK[0], OUT[0]):
            continue
        low = [IND_LABELS[k] for k in ("early12", "visit5")
               if row[k].get("ok") is False and (row[k].get("den") or 0) >= LOW_BASE]
        if low:
            out.append({"level": "amber", "text": f"{row['name']}: {' / '.join(low)} ต่ำกว่าเป้า",
                        "owner": row["name"], "action": "ทบทวนรายชื่อร่วมกับ รพ.สต."})
    if unmapped:
        out.append({"level": "info", "text": f"ยังไม่ได้จับคู่ รพ.สต. {len(unmapped)} หมู่บ้าน",
                    "owner": "ผู้ดูแลระบบ", "action": "เติมหมู่ที่ขาดใน village_pcu.csv (ดูหน้า /check)"})
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


# ---------- ผลลัพธ์แม่และทารก ----------

#: ภาวะแทรกซ้อน (คีย์ใน Pregnancy, ชื่อ) — Dx ระหว่าง LMP ถึงหลังคลอด 42 วัน
COMPLICATIONS = (("cx_htn", "ความดันโลหิตสูง / ครรภ์เป็นพิษ"), ("cx_gdm", "เบาหวานขณะตั้งครรภ์"),
                 ("cx_preterm", "เจ็บครรภ์คลอดก่อนกำหนด"), ("cx_pph", "ตกเลือดหลังคลอด"))
PRETERM_DAYS = 37 * 7


def is_preterm(p):
    return (p["labor_date"] - p["lmp"]).days < PRETERM_DAYS


def is_asphyxia(i, cfg):
    return bool(i.get("asphyxia") or (i.get("apgar1") is not None and i["apgar1"] < cfg.asphyxia_apgar))


def died_in_window(p, d1, d2, cfg):
    """มารดาเสียชีวิตระหว่างตั้งครรภ์ถึงหลังคลอด cfg.postpartum_days วัน และตายในช่วง d1–d2"""
    dd, lab = p.get("death_date"), p.get("labor_date")
    start = p.get("lmp") or p.get("register_date")
    end = lab + timedelta(days=cfg.postpartum_days) if lab else None
    return bool(dd and start and start <= dd and (end is None or dd <= end) and _in(dd, d1, d2))


def outcomes(pregs, infants, risk_types, d1, d2, cfg, area=None):
    """ผลลัพธ์ในช่วง: ครรภ์เสี่ยง (ในรายใหม่) · ผลที่ใช้ครรภ์ที่คลอดเป็นฐาน (ตาม area) · ทารกเกิดใน รพ.

    risk_types = [{"name", "n"}] ประเภทความเสี่ยงของครรภ์รายใหม่ (queries.risk_types)
    """
    new = [p for p in pregs if _in(p.get("register_date"), d1, d2)]
    delivered = _delivered(pregs, d1, d2, area)
    dated = [p for p in delivered if p.get("lmp")]
    preterm = _rate("preterm", sum(1 for p in dated if is_preterm(p)), len(dated), cfg)

    born = [i for i in infants if _in(i.get("birth_date"), d1, d2)]
    live = [i for i in born if i.get("alive")]
    asph = sum(1 for i in live if is_asphyxia(i, cfg))
    per1000 = round(asph * 1000 / len(live), 1) if live else None
    target = cfg.targets.get("asphyxia")
    asphyxia = {"num": asph, "den": len(live), "value": per1000, "target": target,
                "ok": None if per1000 is None or target is None else per1000 <= target,
                "low_base": 0 < len(live) < LOW_BASE}

    here = [p for p in delivered if p.get("labour_hospcode") == cfg.hospcode]
    places = {}
    for p in delivered:
        code = p.get("labour_hospcode")
        if code and code != cfg.hospcode:
            places.setdefault(code, {"code": code, "name": p.get("labour_place") or code, "n": 0})["n"] += 1

    return {
        "risk": _rate("risk", sum(1 for p in new if p.get("has_risk")), len(new), cfg),
        "risk_types": sorted(risk_types, key=lambda r: -r["n"])[:5],
        "preterm": preterm,
        "asphyxia": asphyxia,
        "place": {"here": len(here), "den": len(delivered), "pct_here": pct(len(here), len(delivered)),
                  "top": sorted(places.values(), key=lambda x: (-x["n"], x["code"]))[:5]},
        "bba": sum(1 for i in born if str(i.get("delivery_type") or "") in cfg.bba_types),
        "stillbirth": sum(1 for i in born if not i.get("alive")),
        "maternal_death": sum(1 for p in pregs if died_in_window(p, d1, d2, cfg)),
        "complications": [{"key": k, "label": label, **_rate(k, sum(1 for p in delivered if p.get(k)), len(delivered), cfg)}
                          for k, label in COMPLICATIONS],
    }
