"""SQL ดึงข้อมูลงานฝากครรภ์จาก HOSxP — คืนแถวระดับครรภ์/visit/ทารก/refer ให้ metrics.py คำนวณ

ตาราง HOSxP ↔ แฟ้ม 43 ที่สอดคล้อง (ตรวจกับฐานจริง 1 พ.ย. 2569)
  person_anc                  ↔ PRENATAL     ทะเบียนครรภ์ 1 แถว/ครรภ์ (LMP, วันคลอด, ผล Hct, วันที่ได้ dT)
  person_anc_service          ↔ ANC          visit ฝากครรภ์ที่ รพ. (pa_week = GA)
  person_anc_other_precare    ↔ ANC          ฝากครรภ์ที่หน่วยบริการอื่น (นับครบ 5 ครั้ง / ก่อน 12 wk)
  person_anc_lab + anc_lab    ↔ PRENATAL.HCT_RESULT
  ovst_vaccine+person_vaccine ↔ EPI.VACCINETYPE (dTANC1–5 = 201–205)
  dtmain.pregnancy='Y'        ↔ DENTAL (DENTTYPE = หญิงตั้งครรภ์)
  ipt_labour(_infant)         ↔ LABOR / NEWBORN.BWEIGHT
  referout                    ↔ REFER_HISTORY
  service_time                — ไม่มีใน 43 แฟ้ม (เวลารอคอย)
รหัสทุกตัวมาจาก config.Config ส่งเป็นพารามิเตอร์ · % ตัวอักษรใน SQL ต้องเขียน %%
ไม่ดึงชื่อ/CID — hn ใช้จับคู่ refer กับทะเบียนครรภ์ภายในโปรเซสเท่านั้น ไม่แสดงผล
"""

from datetime import date, datetime, timedelta

from config import village_code
from db import fetch, num

#: ครรภ์ที่ลงทะเบียนก่อนต้นช่วงเกินนี้ คลอดในช่วงไม่ได้แล้ว
REG_LOOKBACK_DAYS = 44 * 7
BATCH = 500


def _date(v):
    if v is None or v == "" or str(v).startswith("0000"):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _float(v):
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _int_or_none(v):
    return int(num(v)) if v not in (None, "") else None


def _village(r):
    """หมู่บ้าน 8 หลักจากที่อยู่ใน patient · ไม่มี patient ใช้ village.village_code ของ person (ถ้าครบ 8 หลัก)"""
    code = village_code(r.get("chwpart"), r.get("amppart"), r.get("tmbpart"), r.get("moopart"))
    v = str(r.get("v_code") or "").strip()
    return code or (v if len(v) == 8 and v.isdigit() else None)


def _flag(v):
    return str(v).strip() not in ("", "0", "None", "N")


def hct_lab_ids(cfg):
    """anc_lab_id ของผล Hct: ตั้งใน env หรือหาจากรหัส/ชื่อใน anc_lab · ไม่พบ = (-1,) ให้ IN () ไม่พัง"""
    if cfg.hct_lab_ids:
        return tuple(cfg.hct_lab_ids)
    rows = fetch("select anc_lab_id from anc_lab where anc_lab_code like '%%hct%%' or anc_lab_name like '%%hct%%'")
    ids = tuple(int(num(r["anc_lab_id"])) for r in rows if r.get("anc_lab_id") not in (None, ""))
    return ids or (-1,)


PREGNANCIES = """
select a.person_anc_id anc_id, pt.hn,
       timestampdiff(year, coalesce(pt.birthday, pe.birthdate), a.anc_register_date) age,
       pt.chwpart, pt.amppart, pt.tmbpart, pt.moopart, v.village_code v_code,
       a.anc_register_date register_date, a.lmp, a.labor_date,
       (select l.anc_lab_result from person_anc_lab l
          join person_anc_service s on s.person_anc_service_id = l.person_anc_service_id
         where s.person_anc_id = a.person_anc_id and l.anc_lab_id in %(hct)s and s.pa_week >= %(late)s
         order by s.anc_service_date desc limit 1) hct_lab,
       case when a.blood_check2_date is not null then a.blood_hct_result end hct_anc,
       (a.vaccine_dtanc1_date is not null or a.vaccine_dtanc2_date is not null or a.vaccine_dtanc3_date is not null
        or a.vaccine_dtanc4_date is not null or a.vaccine_dtanc5_date is not null
        or exists (select 1 from ovst_vaccine ov
                     join person_vaccine pv on pv.person_vaccine_id = ov.person_vaccine_id
                     join ovst o on o.vn = ov.vn
                    where o.hn = pt.hn and pv.export_vaccine_code in %(dt)s
                      and o.vstdate between coalesce(a.lmp, a.anc_register_date) and coalesce(a.labor_date, %(d2)s))
       ) has_dt,
       (a.dental_tx_date is not null
        or exists (select 1 from dtmain t where t.hn = pt.hn and t.pregnancy = 'Y'
                      and t.vstdate between coalesce(a.lmp, a.anc_register_date) and coalesce(a.labor_date, %(d2)s))
       ) has_dental
  from person_anc a
  join person pe on pe.person_id = a.person_id
  left join patient pt on pt.hn = coalesce(nullif(pe.patient_hn, ''),
        (select p2.hn from patient p2 where p2.cid = pe.cid and pe.cid <> '' limit 1))
  left join village v on v.village_id = pe.village_id
 where a.anc_register_date between %(rmin)s and %(d2)s
"""


def pregnancies(d1, d2, cfg):
    args = {"hct": hct_lab_ids(cfg), "late": cfg.hct_late_ga, "dt": tuple(cfg.dt_codes), "d2": d2,
            "rmin": d1 - timedelta(days=REG_LOOKBACK_DAYS)}
    out = []
    for r in fetch(PREGNANCIES, args):
        out.append({"anc_id": int(num(r["anc_id"])), "hn": r.get("hn"), "age": _int_or_none(r.get("age")),
                    "village": _village(r), "register_date": _date(r.get("register_date")),
                    "lmp": _date(r.get("lmp")), "labor_date": _date(r.get("labor_date")),
                    "hct_late": _float(r.get("hct_lab")) or _float(r.get("hct_anc")),
                    "has_dt": _flag(r.get("has_dt")), "has_dental": _flag(r.get("has_dental"))})
    return out


VISITS = """
select person_anc_id anc_id, anc_service_date date, pa_week ga, 0 precare
  from person_anc_service where person_anc_id in %(ids)s
union all
select person_anc_id, precare_date, null, 1
  from person_anc_other_precare where person_anc_id in %(ids)s
"""


def visits(anc_ids):
    out = []
    ids = list(anc_ids)
    for i in range(0, len(ids), BATCH):
        for r in fetch(VISITS, {"ids": tuple(ids[i:i + BATCH])}):
            ga = _int_or_none(r.get("ga"))
            out.append({"anc_id": int(num(r["anc_id"])), "date": _date(r.get("date")),
                        "ga": ga if ga else None, "precare": _flag(r.get("precare"))})
    return out


INFANTS = """
select i.birth_date, i.birth_weight weight, coalesce(n.dead, 'N') dead, i.infant_dchstts dchstts,
       pt.chwpart, pt.amppart, pt.tmbpart, pt.moopart
  from ipt_labour_infant i
  join ipt_labour il on il.ipt_labour_id = i.ipt_labour_id
  left join ipt on ipt.an = il.an
  left join patient pt on pt.hn = coalesce(nullif(il.hn, ''), ipt.hn)
  left join ipt_newborn n on n.an = i.infant_an
 where i.birth_date between %(d1)s and %(d2)s
"""


def infants(d1, d2, dead_dchstts=("08", "09")):
    """ทารกเกิดใน รพ. · ตาย = ipt_newborn.dead='Y' หรือสถานะจำหน่ายทารกเป็นรหัสตาย (ANC_DEAD_DCHSTTS)
    — ipt_newborn มีเฉพาะทารกที่ได้ AN จึงใช้ infant_dchstts จับรายตายคลอดด้วย"""
    dead = tuple(dead_dchstts)
    return [{"birth_date": _date(r.get("birth_date")), "weight": _int_or_none(r.get("weight")) or None,
             "alive": str(r.get("dead") or "N").upper() != "Y" and str(r.get("dchstts") or "").strip() not in dead,
             "village": _village(r)}
            for r in fetch(INFANTS, {"d1": d1, "d2": d2, "dead": dead})]


def waits(d1, d2, cfg):
    # ชื่อคอลัมน์ผ่าน whitelist ใน config แล้ว (vsttime / service1–20) จึงใส่ลง SQL ได้
    a, b = cfg.wait_from_col, cfg.wait_to_col
    sql = f"""
select timestampdiff(minute, timestamp(st.vstdate, st.{a}), timestamp(st.vstdate, st.{b})) m
  from service_time st
 where st.vn in (select vn from person_anc_service
                  where anc_service_date between %(d1)s and %(d2)s and vn is not null and vn <> '')
   and st.{a} is not null and st.{b} is not null
"""
    out = []
    for r in fetch(sql, {"d1": d1, "d2": d2}):
        m = num(r.get("m"), None)
        if m is not None and 0 < m <= cfg.wait_max_min:
            out.append(m)
    return out


REFERS = """
select r.referout_id refer_id, r.refer_date date, r.hn, r.pdx, i.name dx_name,
       coalesce(nullif(h.hospcode_5_digit, ''), nullif(r.refer_hospcode, ''), r.hospcode) dest, h.name dest_name,
       timestampdiff(year, pt.birthday, r.refer_date) age,
       pt.chwpart, pt.amppart, pt.tmbpart, pt.moopart,
       timestampdiff(minute, timestamp(o.vstdate, o.vsttime), timestamp(r.refer_date, r.refer_time)) minutes
  from referout r
  left join patient pt on pt.hn = r.hn
  left join hospcode h on h.hospcode = coalesce(nullif(r.refer_hospcode, ''), r.hospcode)
  left join icd101 i on i.code = r.pdx
  left join ovst o on o.vn = r.vn
 where r.refer_date between %(d1)s and %(d2)s
"""


def refers(d1, d2):
    out = []
    for r in fetch(REFERS, {"d1": d1, "d2": d2}):
        m = num(r.get("minutes"), None)
        out.append({"refer_id": int(num(r["refer_id"])), "date": _date(r.get("date")), "hn": r.get("hn"),
                    "pdx": r.get("pdx") or None, "dx_name": r.get("dx_name") or None, "dest": r.get("dest") or None,
                    "dest_name": r.get("dest_name") or None, "age": _int_or_none(r.get("age")),
                    "village": _village(r), "minutes": m if m is not None and m >= 0 else None})
    return out
