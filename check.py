"""ตรวจความพร้อมของข้อมูล HOSxP ก่อนใช้ ANC Dashboard (หน้า /check และ setup_check.py)

รหัสใน HOSxP ของแต่ละโรงพยาบาลไม่เหมือนกัน ถ้าไม่ตรง ตัวเลขบนแดชบอร์ดจะเพี้ยนโดยไม่มีข้อความเตือน
หน้านี้เทียบ "แอปใช้ vs พบในข้อมูล" ของรหัสทุกตัวที่ตั้งได้ด้วย env (config.py) และความครบของข้อมูล
แสดงเฉพาะจำนวนนับและชื่อรหัส ไม่มีข้อมูลรายคน
"""

import metrics
import queries
from db import fetch, num

#: คอลัมน์เวลาที่ใช้มีข้อมูลน้อยกว่านี้ (% ของ visit ANC) → bad และเสนอคอลัมน์อื่น
TIME_LOW_PCT = 10.0
#: ครรภ์ที่จับคู่ รพ.สต. ไม่ได้เกินนี้ (%) → warn
UNMAPPED_WARN_PCT = 5.0
TIME_COLS = ["vsttime"] + [f"service{i}" for i in range(1, 21)]


def _status(bad, warn):
    return "bad" if bad else "warn" if warn else "ok"


def _item(key, title, app_uses, found, status, env, hint):
    return {"key": key, "title": title, "app_uses": app_uses, "found": found, "status": status,
            "env": env, "hint": hint}


def _guard(key, title, env, fn):
    """ตารางบางตัวไม่มีในบางรุ่นของ HOSxP / ไม่ได้รับสิทธิ์ → ข้อนั้นเป็น warn ไม่ให้ทั้งหน้าล้ม"""
    try:
        return fn()
    except Exception as e:
        return _item(key, title, "", [], "warn", env, f"ตรวจไม่ได้ ({type(e).__name__}) — ตรวจสิทธิ์อ่านตาราง/รุ่น HOSxP")


def _found(rows):
    return [{"code": str(r.get("code") if r.get("code") is not None else ""), "name": r.get("name") or "",
             "n": int(num(r.get("n")))} for r in rows]


def _dt(d1, d2, cfg):
    rows = fetch("""
select pv.export_vaccine_code code, pv.vaccine_name name, count(*) n,
       sum(pt.sex = '2' and timestampdiff(year, pt.birthday, o.vstdate) between 15 and 49) women
  from ovst_vaccine ov
  join person_vaccine pv on pv.person_vaccine_id = ov.person_vaccine_id
  join ovst o on o.vn = ov.vn
  left join patient pt on pt.hn = o.hn
 where o.vstdate between %(d1)s and %(d2)s and pv.export_vaccine_code regexp '^(10|20)[0-9]$'
 group by pv.export_vaccine_code, pv.vaccine_name""", {"d1": d1, "d2": d2})
    used = sum(num(r.get("n")) for r in rows if str(r.get("code")) in cfg.dt_codes)
    other = sum(num(r.get("women")) for r in rows if str(r.get("code")) not in cfg.dt_codes)
    warn = other >= max(used, 1)
    hint = ("พบวัคซีนรหัสอื่น (เช่น 101 TT1/dT1) ที่ให้กับหญิงอายุ 15–49 ปี มากกว่ารหัสที่แอปนับ — "
            "ถ้า รพ. บันทึก dT หญิงตั้งครรภ์ด้วยรหัสนั้น ให้เพิ่มใน ANC_DT_VACCINE_CODES" if warn
            else "รหัสที่แอปนับมีการใช้จริง")
    return _item("dt_codes", "วัคซีน dT หญิงตั้งครรภ์ (EPI.VACCINETYPE)", ", ".join(cfg.dt_codes),
                 sorted(_found(rows), key=lambda f: f["code"]), _status(False, warn), "ANC_DT_VACCINE_CODES", hint)


def _hct(d1, d2, cfg):
    rows = fetch("""
select a.anc_lab_id code, a.anc_lab_code name, count(s.person_anc_service_id) n
  from anc_lab a
  left join person_anc_lab l on l.anc_lab_id = a.anc_lab_id
  left join person_anc_service s on s.person_anc_service_id = l.person_anc_service_id
        and s.anc_service_date between %(d1)s and %(d2)s
 group by a.anc_lab_id, a.anc_lab_code""", {"d1": d1, "d2": d2})
    ids = queries.hct_lab_ids(cfg)
    used = sum(num(r.get("n")) for r in rows if int(num(r.get("code"))) in ids)
    return _item("hct_lab_ids", "ผล Hct ของ ANC (PRENATAL.HCT_RESULT)", ", ".join(map(str, ids)),
                 _found(rows), _status(used == 0, False), "ANC_HCT_LAB_IDS",
                 "ไม่มีผลจากรายการที่แอปใช้ในช่วงนี้ — เลือก anc_lab_id ของ Hct จากตาราง" if used == 0
                 else "มีผล Hct จากรายการที่แอปใช้ (ถ้าไม่มี แอปใช้ person_anc.blood_hct_result แทน)")


def _service_types(d1, d2):
    rows = fetch("""
select anc_service_type_id code, count(*) n from person_anc_service
 where anc_service_date between %(d1)s and %(d2)s group by anc_service_type_id""", {"d1": d1, "d2": d2})
    return _item("anc_service_type", "ประเภทบริการ ANC ที่พบ", "นับทุกประเภท", _found(rows), "ok", "",
                 "แอปนับทุกแถวใน person_anc_service เป็นครั้งบริการ ANC")


def _refer_dest(d1, d2):
    rows = fetch("""
select coalesce(nullif(r.refer_hospcode, ''), r.hospcode) code, h.name name, count(*) n
  from referout r
  left join hospcode h on h.hospcode = coalesce(nullif(r.refer_hospcode, ''), r.hospcode)
 where r.refer_date between %(d1)s and %(d2)s
 group by coalesce(nullif(r.refer_hospcode, ''), r.hospcode), h.name""", {"d1": d1, "d2": d2})
    found = sorted(_found(rows), key=lambda f: -f["n"])
    unnamed = [f["code"] for f in found if not f["name"]]
    names = {}
    for f in found:
        if f["name"]:
            names.setdefault(f["name"], []).append(f["code"])
    dup = {n: c for n, c in names.items() if len(c) > 1}
    hint = []
    if unnamed:
        hint.append("ปลายทางไม่มีชื่อในตาราง hospcode: " + ", ".join(unnamed))
    if dup:
        hint.append("ชื่อเดียวกันหลายรหัส (นับแยกแถว): " + "; ".join(f"{n} = {', '.join(c)}" for n, c in dup.items()))
    return _item("refer_dest", "ปลายทาง refer (REFER_HISTORY.HOSPCODE_DEST)", "referout.refer_hospcode",
                 found[:15], _status(False, bool(hint)), "", " · ".join(hint) or "ทุกปลายทางมีชื่อ")


def _refer_dx(d1, d2, cfg, pregs):
    sel = metrics.select_refers(queries.refers(d1, d2), pregs, cfg)
    by = {}
    for r in sel:
        by[r["reason"]] = by.get(r["reason"], 0) + 1
    names = {"registry": "อยู่ในทะเบียนฝากครรภ์เท่านั้น", "dx": "Dx หลักตรงเท่านั้น", "both": "ทั้งสองเงื่อนไข"}
    return _item("refer_dx", "refer ที่นับเป็นงานแม่และเด็ก", ", ".join(cfg.refer_dx_prefixes),
                 [{"code": k, "name": v, "n": by.get(k, 0)} for k, v in names.items()], "ok",
                 "ANC_REFER_DX_PREFIXES · ANC_POSTPARTUM_DAYS",
                 f"ทะเบียนฝากครรภ์ถึงหลังคลอด {cfg.postpartum_days} วัน หรือ Dx หลักขึ้นต้นด้วยรหัสที่ตั้ง")


def _wait_cols(d1, d2, cfg):
    cols = ", ".join(f"count(st.{c}) {c}" for c in TIME_COLS)
    rows = fetch(f"""
select count(*) total, {cols}
  from service_time st
 where st.vn in (select vn from person_anc_service where anc_service_date between %(d1)s and %(d2)s)""",
                 {"d1": d1, "d2": d2})
    r = rows[0] if rows else {}
    total = num(r.get("total"))
    pct = {c: metrics.pct(num(r.get(c)), total) or 0.0 for c in TIME_COLS}
    used = min(pct[cfg.wait_from_col], pct[cfg.wait_to_col])
    found = [{"code": c, "name": "", "n": int(num(r.get(c)))} for c in TIME_COLS if num(r.get(c))]
    best = max((c for c in TIME_COLS if c not in ("vsttime", cfg.wait_from_col)), key=lambda c: pct[c])
    bad = total > 0 and used < TIME_LOW_PCT
    hint = (f"คอลัมน์ที่ใช้มีข้อมูล {used}% ของ visit ANC — คอลัมน์ที่มีข้อมูลมากสุดคือ {best} ({pct[best]}%)"
            if bad else f"คอลัมน์ที่ใช้มีข้อมูล {used}% ของ visit ANC ({int(total)} visit)")
    return _item("wait_cols", "เวลารอคอย (service_time — นอก 43 แฟ้ม)", f"{cfg.wait_from_col} → {cfg.wait_to_col}",
                 found, _status(bad, total == 0), "ANC_WAIT_FROM_COL · ANC_WAIT_TO_COL", hint)


def _pcu_item(pregs, pcu_map):
    if pcu_map is None:
        return _item("pcu_map", "จับคู่หมู่บ้าน → รพ.สต. (pcu_map.csv)", "ไม่มีไฟล์", [], "bad", "ANC_PCU_MAP",
                     "ดาวน์โหลดแม่แบบด้านล่าง เติม pcu_hospcode/pcu_name แล้ววางไว้ที่ pcu_map.csv")
    un = metrics.unmapped_villages(pregs, pcu_map)
    n_un = sum(n for _, n in un)
    share = metrics.pct(n_un, len(pregs)) or 0.0
    return _item("pcu_map", "จับคู่หมู่บ้าน → รพ.สต. (pcu_map.csv)", f"{len(pcu_map)} หมู่บ้าน",
                 [{"code": v or "(ไม่มีที่อยู่)", "name": "", "n": n} for v, n in un[:15]],
                 _status(False, share > UNMAPPED_WARN_PCT), "ANC_PCU_MAP",
                 f"ครรภ์ที่ไม่ได้จับคู่ {n_un} ราย ({share}%) — นับเป็น 'นอกเขต/ไม่ระบุ'")


def _comp(title, n, den, warn=95.0, bad=80.0):
    p = metrics.pct(n, den)
    return {"title": title, "pct": p, "n": n, "den": den,
            "status": "warn" if p is None else _status(p < bad, p < warn)}


def completeness(pregs, infants, d1, d2, pcu_map):
    new = [p for p in pregs if p.get("register_date") and d1 <= p["register_date"] <= d2]
    due = [p for p in pregs if p.get("lmp") and (d2 - p["lmp"]).days >= 42 * 7 and p["lmp"] >= d1.replace(year=d1.year - 1)]
    delivered = [p for p in pregs if p.get("labor_date") and d1 <= p["labor_date"] <= d2]
    born = [i for i in infants if i.get("birth_date") and d1 <= i["birth_date"] <= d2]
    out = [_comp("ครรภ์ที่มี LMP", sum(1 for p in new if p.get("lmp")), len(new)),
           _comp("ครรภ์ครบกำหนดที่บันทึกวันคลอด", sum(1 for p in due if p.get("labor_date")), len(due)),
           _comp("ทารกที่มีน้ำหนักแรกเกิด", sum(1 for i in born if i.get("weight")), len(born)),
           _comp("ครรภ์ที่คลอดแล้วมีผล Hct ใกล้คลอด", sum(1 for p in delivered if p.get("hct_late") is not None),
                 len(delivered), warn=50.0, bad=20.0)]
    if pcu_map is not None:
        out.append(_comp("ครรภ์ที่จับคู่ รพ.สต. ได้", sum(1 for p in new if p.get("village") in pcu_map), len(new)))
    return out


def audit(d1, d2, cfg, pcu_map):
    try:
        pregs = queries.pregnancies(d1, d2, cfg)
        infants = queries.infants(d1, d2)
    except Exception:
        pregs, infants = [], []
    new = [p for p in pregs if p.get("register_date") and d1 <= p["register_date"] <= d2]
    items = [
        _guard("dt_codes", "วัคซีน dT หญิงตั้งครรภ์", "ANC_DT_VACCINE_CODES", lambda: _dt(d1, d2, cfg)),
        _guard("hct_lab_ids", "ผล Hct ของ ANC", "ANC_HCT_LAB_IDS", lambda: _hct(d1, d2, cfg)),
        _guard("anc_service_type", "ประเภทบริการ ANC", "", lambda: _service_types(d1, d2)),
        _guard("refer_dest", "ปลายทาง refer", "", lambda: _refer_dest(d1, d2)),
        _guard("refer_dx", "refer ที่นับเป็นงานแม่และเด็ก", "ANC_REFER_DX_PREFIXES",
               lambda: _refer_dx(d1, d2, cfg, pregs)),
        _guard("wait_cols", "เวลารอคอย", "ANC_WAIT_FROM_COL · ANC_WAIT_TO_COL", lambda: _wait_cols(d1, d2, cfg)),
        _pcu_item(new, pcu_map),
    ]
    return {"items": items, "completeness": completeness(pregs, infants, d1, d2, pcu_map),
            "n_pregs": len(new)}


def pcu_template(pregs, pcu_map):
    """แถวแม่แบบ pcu_map.csv: รหัสหมู่บ้านที่พบ + ชื่อตำบล + หมู่ + จำนวนครรภ์ · ไม่มีข้อมูลรายคน"""
    pcu_map = pcu_map or {}
    counts = {}
    for p in pregs:
        if p.get("village"):
            counts[p["village"]] = counts.get(p["village"], 0) + 1
    for v in pcu_map:
        counts.setdefault(v, 0)
    tambon = {}
    ids = tuple(sorted({v[:6] for v in counts}))
    if ids:
        try:
            tambon = {str(r["addressid"]): r.get("name") or ""
                      for r in fetch("select addressid, name from thaiaddress where addressid in %(ids)s", {"ids": ids})}
        except Exception:
            tambon = {}
    rows = []
    for v in sorted(counts):
        hcode, name = pcu_map.get(v, ("", ""))
        rows.append([v, hcode, name, tambon.get(v[:6], ""), v[6:], counts[v]])
    return rows
