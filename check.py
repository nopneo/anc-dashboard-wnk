"""ตรวจความพร้อมของข้อมูล HOSxP ก่อนใช้ ANC Dashboard (หน้า /check และ setup_check.py)

รหัสใน HOSxP ของแต่ละโรงพยาบาลไม่เหมือนกัน ถ้าไม่ตรง ตัวเลขบนแดชบอร์ดจะเพี้ยนโดยไม่มีข้อความเตือน
หน้านี้เทียบ "แอปใช้ vs พบในข้อมูล" ของรหัสทุกตัวที่ตั้งได้ด้วย env (config.py) และความครบของข้อมูล
แสดงเฉพาะจำนวนนับและชื่อรหัส ไม่มีข้อมูลรายคน
"""

from datetime import timedelta

import metrics
import queries
import risk27
import sti
from db import fetch, num

#: ครรภ์ที่จับคู่ รพ.สต. ไม่ได้เกินนี้ (%) → warn
UNMAPPED_WARN_PCT = 5.0


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


def _hct_series(d1, d2, cfg):
    codes = queries.hct_series_labs(cfg)
    rows = fetch("""
select lo.lab_items_code code, li.lab_items_name name, count(*) n,
       sum(lo.lab_order_result regexp '^[[:space:]]*[0-9]+([.][0-9]+)?[[:space:]]*$') num_ok /* hct_series */
  from lab_head lh
  join lab_order lo on lo.lab_order_number = lh.lab_order_number
  join lab_items li on li.lab_items_code = lo.lab_items_code
 where lh.order_date between %(d1)s and %(d2)s and lo.lab_items_code in %(codes)s
 group by lo.lab_items_code, li.lab_items_name""", {"d1": d1, "d2": d2, "codes": tuple(codes) or ("-",)})
    n = sum(int(num(r.get("n"))) for r in rows)
    ok_n = sum(int(num(r.get("num_ok"))) for r in rows)
    p = metrics.pct(ok_n, n)
    warn = not codes or n == 0 or (p or 0) < 90
    hint = ("ไม่พบผล Hct จากรหัสที่ใช้ในช่วงนี้ — ตั้ง ANC_HCT_SERIES_LABS เป็นรหัส lab Hct ของ รพ." if n == 0 else
            f"{n} ผลในช่วง · เป็นตัวเลข {p}% (ที่ไม่ใช่ตัวเลขถูกตัดออก) · ผลที่ลงในหน้า ANC ใช้ ANC_HCT_LAB_IDS")
    return _item("hct_series", "ติดตามภาวะซีด: ผล Hct หลายครั้ง (LABFU)", ", ".join(codes) or "-", _found(rows),
                 _status(False, warn), "ANC_HCT_SERIES_LABS · ANC_HCT_CUTOFF_T2 · ANC_HCT_IMPROVE", hint)


#: ผลตรวจโรคติดเชื้อที่จัดกลุ่มไม่ได้ (ว่าง / ข้อความอื่น) เกินนี้ (%) → warn
STI_UNCLEAR_WARN_PCT = 20.0
#: ชื่อ lab ที่อาจเกี่ยวกับโรคติดเชื้อ — แสดงให้เห็นรายการที่แอปไม่ได้เลือก
STI_CANDIDATES = "vdrl|^rpr|tpha|syphil|hbs|hiv|hcv|hepatitis|amphetamine"


def _sti(d1, d2, cfg):
    labs, anc = queries.sti_codes(cfg)
    used = {c for k in sti.LABELS for c in labs[k]}
    rows = fetch("""
select lo.lab_items_code code, li.lab_items_name name, lo.lab_order_result result, count(*) n
  from lab_head lh
  join lab_order lo on lo.lab_order_number = lh.lab_order_number
  join lab_items li on li.lab_items_code = lo.lab_items_code
 where lh.order_date between %(d1)s and %(d2)s
   and (lo.lab_items_code in %(codes)s or lower(li.lab_items_name) regexp %(rx)s)
 group by lo.lab_items_code, li.lab_items_name, lo.lab_order_result""",
                 {"d1": d1, "d2": d2, "codes": tuple(used) or ("-",), "rx": STI_CANDIDATES})
    by_code, names = {}, {}
    for r in rows:
        c = str(r.get("code"))
        names[c] = r.get("name") or ""
        n, unclear = by_code.get(c, (0, 0))
        by_code[c] = (n + int(num(r.get("n"))), unclear + (int(num(r.get("n"))) if sti.classify(r.get("result")) == "unclear" else 0))
    found = sorted(({"code": c, "name": names[c] + ("" if c in used else " (แอปไม่ได้ใช้)"), "n": n}
                    for c, (n, _) in by_code.items()), key=lambda f: -f["n"])
    notes, warn = [], False
    for k, label in sti.LABELS.items():
        n = sum(by_code.get(str(c), (0, 0))[0] for c in labs[k])
        unclear = sum(by_code.get(str(c), (0, 0))[1] for c in labs[k])
        u = metrics.pct(unclear, n)
        bad_k = not labs[k] or n == 0 or (u or 0) >= STI_UNCLEAR_WARN_PCT
        warn = warn or bad_k
        notes.append(f"{label}: " + ("ไม่มีรหัส lab" if not labs[k] else f"{n} ผล ในช่วง · ผลไม่ชัด {u or 0}%")
                     + (" ⚠" if bad_k else ""))
    uses = " · ".join(f"{label} " + (", ".join(labs[k]) or "-") + (f" + ANC {', '.join(map(str, anc[k]))}" if anc[k] else "")
                      for k, label in sti.LABELS.items())
    hint = " · ".join(notes) + (" — ตรวจรหัส lab ของ รพ. (ตั้ง ANC_STI_*_LABS) หรือแก้การบันทึกผลให้เป็น Reactive/Non-reactive, "
                                "Positive/Negative" if warn else "")
    return _item("sti_codes", "โรคติดเชื้อทางเพศสัมพันธ์ + ปัสสาวะ Amphetamine (LABFU)", uses, found,
                 _status(False, warn), "ANC_STI_SYPHILIS_LABS · ANC_STI_HBV_LABS · ANC_STI_HIV_LABS · ANC_STI_AMPH_LABS (+ _ANC_LABS)", hint)


def _pcu_item(pregs, pcu_map, cfg):
    title = "จับคู่หมู่บ้าน → รพ.สต. (village_pcu.csv)"
    if pcu_map is None:
        return _item("pcu_map", title, "ไม่มีไฟล์", [], "bad", "ANC_VILLAGE_CSV",
                     "ใช้ไฟล์ village_pcu.csv ชุดเดียวกับ mental_health_dashboard ได้เลย หรือดาวน์โหลดแม่แบบด้านล่าง")
    un = metrics.unmapped_villages(pregs, pcu_map, cfg)
    n_un = sum(n for _, n in un)
    share = metrics.pct(n_un, len(pregs)) or 0.0
    return _item("pcu_map", title, f"{len(pcu_map)} หมู่ · อำเภอ {cfg.chwpart}{cfg.amppart}",
                 [{"code": v or "(ไม่มีที่อยู่)", "name": "", "n": n} for v, n in un[:15]],
                 _status(False, share > UNMAPPED_WARN_PCT), "ANC_VILLAGE_CSV · ANC_CHWPART · ANC_AMPPART",
                 f"ครรภ์ในอำเภอที่หมู่ไม่อยู่ในไฟล์ {n_un} ราย ({share}%) — นับเป็น 'ในอำเภอ ไม่ทราบหมู่'")


def _comp(title, n, den, warn=95.0, bad=80.0):
    p = metrics.pct(n, den)
    return {"title": title, "pct": p, "n": n, "den": den,
            "status": "warn" if p is None else _status(p < bad, p < warn)}


def completeness(pregs, infants, d1, d2, pcu_map, cfg):
    new = [p for p in pregs if p.get("register_date") and d1 <= p["register_date"] <= d2]
    due = [p for p in pregs if p.get("lmp") and (d2 - p["lmp"]).days >= 42 * 7 and p["lmp"] >= d1 - timedelta(days=365)]
    delivered = [p for p in pregs if p.get("labor_date") and d1 <= p["labor_date"] <= d2]
    born = [i for i in infants if i.get("birth_date") and d1 <= i["birth_date"] <= d2]
    out = [_comp("ครรภ์ที่มี LMP", sum(1 for p in new if p.get("lmp")), len(new)),
           _comp("ครรภ์ครบกำหนดที่บันทึกวันคลอด", sum(1 for p in due if p.get("labor_date")), len(due)),
           _comp("ทารกที่มีน้ำหนักแรกเกิด", sum(1 for i in born if i.get("weight")), len(born)),
           _comp("ครรภ์ที่คลอดแล้วมีผล Hct ใกล้คลอด", sum(1 for p in delivered if p.get("hct_late") is not None),
                 len(delivered), warn=50.0, bad=20.0),
           _comp("ครรภ์ที่คลอด/แท้งมีลำดับครรภ์ (preg_no)", sum(1 for p in delivered if p.get("gravida") is not None),
                 len(delivered))]
    if pcu_map is not None:
        out.append(_comp("ครรภ์ที่จัดเข้า รพ.สต. / เขต รพ. / นอกอำเภอ ได้",
                         sum(1 for p in new if metrics.pcu_of(p.get("village"), pcu_map, cfg) != metrics.UNK), len(new)))
    return out


def _iodine(d1, d2, cfg):
    rows = fetch("""
select di.did code, di.name name, count(op.icode) n
  from drugitems di
  left join opitemrece op on op.icode = di.icode and op.vstdate between %(d1)s and %(d2)s
 where di.did in %(iod)s
 group by di.did, di.name""", {"d1": d1, "d2": d2, "iod": tuple(cfg.iodine_didstd)})
    found = sorted(_found(rows), key=lambda f: -f["n"])
    used = sum(f["n"] for f in found)
    return _item("iodine_did", "ยาเม็ดที่มีไอโอดีน (DRUG_OPD.DIDSTD)", f"{len(cfg.iodine_didstd)} รหัสยา 24 หลัก", found,
                 _status(False, not found or used == 0), "ANC_IODINE_DIDSTD",
                 "ไม่พบยาตามรหัส 24 หลักใน drugitems.did หรือไม่มีการจ่ายในช่วงนี้ — ตรวจรหัสยาเสริมธาตุเหล็ก+ไอโอดีนของ รพ."
                 if not found or used == 0 else "พบยาที่มีไอโอดีนและมีการจ่ายในช่วงนี้")


def _quality_codes(d1, d2, cfg):
    cbc, dm = queries.lab_codes(cfg)
    rows = fetch("""
select concat('ICD9 ', replace(d.icd9, '.', '')) code, '' name, count(*) n
  from doctor_operation d join ovst o on o.vn = d.vn
 where o.vstdate between %(d1)s and %(d2)s and replace(d.icd9, '.', '') in %(us)s group by replace(d.icd9, '.', '')
union all
select concat('Dx ', icd10), '', count(*) from ovstdiag
 where vstdate between %(d1)s and %(d2)s and icd10 in %(dx)s group by icd10""",
                 {"d1": d1, "d2": d2, "us": tuple(cfg.us_icd9), "dx": tuple(cfg.down_dx) + tuple(cfg.dm_dx)})
    found = _found(rows)
    missing = [k for k, codes in (("อัลตราซาวด์", cfg.us_icd9), ("คัดกรองดาวน์", cfg.down_dx))
               if not any(f["code"].split(" ", 1)[1] in codes for f in found)]
    return _item("quality_codes", "ฝากครรภ์คุณภาพ: lab / หัตถการ / Dx",
                 f"CBC {', '.join(cbc) or '—'} · เบาหวาน {', '.join(dm) or '—'}", found,
                 _status(not cbc or not dm, bool(missing)), "ANC_CBC_LAB_CODES · ANC_DM_LAB_CODES · ANC_US_ICD9 · ANC_DOWN_DX · ANC_DM_DX",
                 ("ไม่พบในช่วงนี้: " + ", ".join(missing) + " — ตรวจรหัสที่ รพ. ใช้บันทึก") if missing
                 else "รหัส lab เลือกจากชื่อรายการเมื่อไม่ได้ตั้ง env — ตรวจว่าตรงกับรายการที่ใช้จริง")


def _thal(d1, d2, cfg):
    rows = fetch("""
select tr.thalassaemia_result_export code, tr.thalassaemia_result_name name, count(a.person_anc_id) n
  from thalassaemia_result tr
  left join person_anc a on a.thalassaemia_result_id = tr.thalassaemia_result_id
        and a.labor_date between %(d1)s and %(d2)s
 group by tr.thalassaemia_result_export, tr.thalassaemia_result_name""", {"d1": d1, "d2": d2})
    found = _found(rows)
    hit = any(f["code"] in cfg.thal_export_codes for f in found)
    return _item("thal_codes", "คัดกรองธาลัสซีเมีย (PRENATAL.THALASSEMIA)", ", ".join(cfg.thal_export_codes), found,
                 _status(False, not hit), "ANC_THAL_EXPORT_CODES",
                 "นับครรภ์ที่ thalassaemia_result_export อยู่ในรหัสที่ตั้ง" if hit
                 else "ไม่พบรหัสผลคัดกรองที่ตรงกับค่าที่ตั้ง")


def _outcome_codes(d1, d2, cfg):
    infants = fetch("""
select concat('Apgar1 < ', %(ap)s) code, '' name, sum(apgar_score_min1 < %(ap)s) n from ipt_labour_infant
 where birth_date between %(d1)s and %(d2)s
union all
select concat('BBA (type ', infant_delivery_type_id, ')'), '', count(*) from ipt_labour_infant
 where birth_date between %(d1)s and %(d2)s and infant_delivery_type_id in %(bba)s group by infant_delivery_type_id""",
                    {"d1": d1, "d2": d2, "ap": cfg.asphyxia_apgar, "bba": tuple(cfg.bba_types)})
    codes = tuple(cfg.dx_htn) + tuple(cfg.dx_gdm) + tuple(cfg.dx_pph) + tuple(cfg.dx_preterm)
    dx = fetch("""
select left(icd10, 3) code, '' name, count(*) n from iptdiag y join ipt on ipt.an = y.an
 where ipt.dchdate between %(d1)s and %(d2)s and (left(icd10, 3) in %(c)s or left(icd10, 4) in %(c)s)
 group by left(icd10, 3)""", {"d1": d1, "d2": d2, "c": codes})
    found = _found(infants) + sorted(_found(dx), key=lambda f: f["code"])
    return _item("outcome_codes", "ผลลัพธ์แม่และทารก: Apgar / BBA / Dx ภาวะแทรกซ้อน (IPD)",
                 f"Apgar1 < {cfg.asphyxia_apgar} · BBA {', '.join(cfg.bba_types)} · Dx {', '.join(codes)}", found, "ok",
                 "ANC_ASPHYXIA_APGAR · ANC_BBA_TYPES · ANC_DX_HTN · ANC_DX_GDM · ANC_DX_PPH · ANC_DX_PRETERM",
                 "ผ่าตัดคลอดไม่ได้แสดง (ไม่พบรหัส O82 / หัตถการ 74.x ในข้อมูล) · GA คลอดคำนวณจาก LMP ใน person_anc")


def _risk27(new, d1, d2, cfg):
    res = risk27.summarize(new, queries.risk_hits(d1, d2, cfg), cfg)
    names = {"F": "ฟอร์ม", "C": "คำนวณ", "D": "Dx", "T": "HPI/PMH"}
    found = [{"code": f"ข้อ {it['num']}", "n": it["n"],
              "name": it["label"] + " · " + (" ".join(f"{names[s]} {n}" for s, n in it["by_source"].items()) or "ไม่พบ")}
             for it in res["items"]]
    cx = [it for it in res["items"] if it["key"] in ("height_lt145", "bmi_low")]
    hint = (f"ครรภ์รายใหม่ {res['den']} ราย · เข้าอย่างน้อย 1 ข้อ {res['any']['num']} ราย · "
            f"มีส่วนสูง/น้ำหนักพอคำนวณ BMI {cx[-1]['known'] if cx else 0} ราย · "
            "คำค้น HPI/PMH ตัดประโยคปฏิเสธออกก่อน จึงเป็นค่าประมาณ — ตรวจรายข้อว่ารหัส/คำค้นตรงกับการบันทึกของ รพ. นี้")
    return _item("risk27", "คัดกรองครรภ์เสี่ยง 27 ข้อ: ฟอร์ม · Dx · คำค้น HPI/PMH · ส่วนสูง/BMI",
                 "risk27.py: รหัส Dx และ regex ต่อข้อ · เกณฑ์อายุ/ส่วนสูง/BMI", found, "ok",
                 "ANC_RISK_DX_<ข้อ> · ANC_RISK_TEXT_<ข้อ> · ANC_RISK_AGE_LOW/HIGH · ANC_RISK_HEIGHT_CM · ANC_RISK_BMI_LOW/HIGH",
                 hint)


def _dchstts(d1, d2, cfg):
    rows = fetch("""
select infant_dchstts code, count(*) n from ipt_labour_infant
 where birth_date between %(d1)s and %(d2)s group by infant_dchstts""", {"d1": d1, "d2": d2})
    return _item("dead_dchstts", "สถานะจำหน่ายทารก — รหัสที่นับเป็นเสียชีวิต (ตัดออกจากตัวหาร LBW)",
                 ", ".join(cfg.dead_dchstts), _found(rows), "ok", "ANC_DEAD_DCHSTTS",
                 "ทารกตายคลอดต้องไม่อยู่ในตัวหาร LBW — ตรวจว่ารหัสเสียชีวิตของ รพ. ตรงกับค่าที่ตั้ง")


def audit(d1, d2, cfg, pcu_map):
    main_err = None
    try:
        pregs = queries.pregnancies(d1, d2, cfg)
        infants = queries.infants(d1, d2, cfg.dead_dchstts)
    except Exception as e:
        pregs, infants, main_err = [], [], type(e).__name__
    new = [p for p in pregs if p.get("register_date") and d1 <= p["register_date"] <= d2]
    items = [_item("main_query", "ดึงทะเบียนครรภ์ / ทารก (คิวรีหลักของแดชบอร์ด)", "queries.pregnancies · infants", [],
                   "bad", "", f"ล้ม ({main_err}) — ตารางหรือคอลัมน์ของ HOSxP รุ่นนี้ไม่ตรง ทั้งแดชบอร์ดจะไม่มีตัวเลข")]         if main_err else []
    items += [
        _guard("dt_codes", "วัคซีน dT หญิงตั้งครรภ์", "ANC_DT_VACCINE_CODES", lambda: _dt(d1, d2, cfg)),
        _guard("hct_lab_ids", "ผล Hct ของ ANC", "ANC_HCT_LAB_IDS", lambda: _hct(d1, d2, cfg)),
        _guard("anc_service_type", "ประเภทบริการ ANC", "", lambda: _service_types(d1, d2)),
        _guard("refer_dest", "ปลายทาง refer", "", lambda: _refer_dest(d1, d2)),
        _guard("refer_dx", "refer ที่นับเป็นงานแม่และเด็ก", "ANC_REFER_DX_PREFIXES",
               lambda: _refer_dx(d1, d2, cfg, pregs)),
        _guard("dead_dchstts", "สถานะจำหน่ายทารก", "ANC_DEAD_DCHSTTS", lambda: _dchstts(d1, d2, cfg)),
        _guard("iodine_did", "ยาเม็ดที่มีไอโอดีน", "ANC_IODINE_DIDSTD", lambda: _iodine(d1, d2, cfg)),
        _guard("quality_codes", "ฝากครรภ์คุณภาพ: lab / หัตถการ / Dx", "ANC_CBC_LAB_CODES · ANC_DM_LAB_CODES",
               lambda: _quality_codes(d1, d2, cfg)),
        _guard("thal_codes", "คัดกรองธาลัสซีเมีย", "ANC_THAL_EXPORT_CODES", lambda: _thal(d1, d2, cfg)),
        _guard("outcome_codes", "ผลลัพธ์แม่และทารก", "ANC_ASPHYXIA_APGAR", lambda: _outcome_codes(d1, d2, cfg)),
        _guard("hct_series", "ติดตามภาวะซีด", "ANC_HCT_SERIES_LABS", lambda: _hct_series(d1, d2, cfg)),
        _guard("sti_codes", "โรคติดเชื้อทางเพศสัมพันธ์", "ANC_STI_*_LABS", lambda: _sti(d1, d2, cfg)),
        _guard("risk27", "คัดกรองครรภ์เสี่ยง 27 ข้อ", "ANC_RISK_DX_* · ANC_RISK_TEXT_*", lambda: _risk27(new, d1, d2, cfg)),
        _pcu_item(new, pcu_map, cfg),
    ]
    return {"items": items, "completeness": completeness(pregs, infants, d1, d2, pcu_map, cfg),
            "n_pregs": len(new)}


def village_template(pregs, pcu_map, cfg):
    """แถวแม่แบบ village_pcu.csv: หมู่ในอำเภอที่พบในทะเบียนครรภ์ + หมู่ที่จับคู่ไว้แล้ว
    [tmbpart, tambon, moo, village, hospcode, pcu, pregnancies] · ไม่มีข้อมูลรายคน"""
    pcu_map = pcu_map or {}
    district = cfg.chwpart + cfg.amppart
    counts = {}
    for p in pregs:
        v = p.get("village")
        if v and v.startswith(district):
            counts[v] = counts.get(v, 0) + 1
    for v in pcu_map:
        counts.setdefault(v, 0)
    tambon, vname = {}, {}
    if counts:
        try:
            tambon = {str(r["addressid"]): r.get("name") or "" for r in fetch(
                "select addressid, name from thaiaddress where addressid in %(ids)s",
                {"ids": tuple(sorted({v[:6] for v in counts}))})}
        except Exception:
            tambon = {}
        try:
            vname = {str(r["village_code"]): r.get("village_name") or "" for r in fetch(
                "select village_code, village_name from village where village_code in %(ids)s",
                {"ids": tuple(sorted(counts))})}
        except Exception:
            vname = {}
    rows = []
    for v in sorted(counts):
        hcode, name = pcu_map.get(v, ("", ""))
        rows.append([v[4:6], tambon.get(v[:6], ""), int(v[6:8]), vname.get(v, ""), hcode, name, counts[v]])
    return rows
