"""ค่าตั้งของแอป — อ่านจาก env ทั้งหมด (ค่าเริ่มต้น = รหัสมาตรฐาน HOSxP / 43 แฟ้ม)

รหัสทุกตัวที่ SQL ใช้มาจากที่นี่ แล้วส่งเป็นพารามิเตอร์ — ห้ามเขียนรหัสตายตัวใน SQL
แต่ละ รพ. ตรวจว่าค่าตรงกับข้อมูลจริงได้ที่หน้า /check
"""

import csv
import os
import re
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

#: คอลัมน์เวลาใน service_time ที่ยอมให้ใส่ลง SQL ได้ (ชื่อคอลัมน์ส่งเป็นพารามิเตอร์ไม่ได้)
_TIME_COL = re.compile(r"vsttime|service([1-9]|1[0-9]|20)")

#: เป้าหมายตัวชี้วัด (%) · anemia และ lbw ยิ่งต่ำยิ่งดี
TARGET_DEFAULTS = {"early12": 75, "visit5": 75, "dt": 90, "dental": 50, "anemia": 14, "lbw": 7,
                   # เอกสาร KPI: หลังคลอด 3 ครั้ง ≥75 · ฝากครรภ์คุณภาพ (HDC) ปีงบ 2570 ≥70 · ไอโอดีนไม่กำหนดเป้า
                   "postnatal": 75, "quality": 70, "iodine": None,
                   # ทารกแรกเกิดขาดออกซิเจน ไม่เกิน 25 ต่อ 1,000 เกิดมีชีพ (ตัวชี้วัดกระทรวง)
                   "asphyxia": 25}

#: ยาเม็ดที่มีไอโอดีน (รหัสยา 24 หลัก DIDSTD ตามเอกสาร KPI: Triferdine 150, Obimin-az, Iodine GPO,
#: Nataral, Nataral EF, Prenamed, Iolic)
IODINE_DIDSTD = ("201120320037726221781506", "201110100019999920381199", "101110000003082121781506",
                 "201110100019999920381341", "201110100019999921881341", "202030120019999920381252",
                 "202030220017745221781506")

#: คอลัมน์ที่ต้องมีใน village_pcu.csv (รูปแบบเดียวกับ mental_health_dashboard)
PCU_COLUMNS = ("tmbpart", "moo", "hospcode", "pcu")


class PcuMapError(Exception):
    """ไฟล์ pcu_map.csv รูปแบบไม่ถูกต้อง"""


@dataclass(frozen=True)
class Config:
    dt_codes: tuple = ("201", "202", "203", "204", "205")
    hct_lab_ids: tuple = ()
    hct_cutoff: float = 33
    hct_late_ga: int = 28
    lbw_grams: int = 2500
    dead_dchstts: tuple = ("08", "09")
    iodine_didstd: tuple = IODINE_DIDSTD
    #: ฝากครรภ์คุณภาพ: lab CBC/Hct/Hb และ lab คัดกรองเบาหวาน (lab_items_code · ว่าง = เลือกจากชื่อรายการ)
    cbc_lab_codes: tuple = ()
    dm_lab_codes: tuple = ()
    us_icd9: tuple = ("8878", "5260700", "5260701")
    down_dx: tuple = ("Z360", "Z362")
    dm_dx: tuple = ("Z131",)
    #: thalassaemia_result.thalassaemia_result_export ที่นับว่าคัดกรองแล้ว (PRENATAL.THALASSEMIA 1, 2, 4)
    thal_export_codes: tuple = ("1", "2", "4")
    #: ผลลัพธ์แม่และทารก: Apgar 1 นาทีต่ำกว่านี้ = ขาดออกซิเจน · infant_delivery_type ที่เป็นคลอดก่อนถึง รพ. (BBA)
    asphyxia_apgar: int = 7
    bba_types: tuple = ("3",)
    #: Dx ภาวะแทรกซ้อนระหว่างตั้งครรภ์ถึงหลังคลอด 42 วัน (รหัส 3 หรือ 4 หลัก ไม่มีจุด)
    dx_htn: tuple = ("O10", "O11", "O13", "O14", "O15", "O16")
    dx_gdm: tuple = ("O244",)
    dx_pph: tuple = ("O72",)
    dx_preterm: tuple = ("O60",)
    postpartum_days: int = 42
    refer_dx_prefixes: tuple = ("O", "Z32", "Z33", "Z34", "Z35", "Z36")
    wait_from_col: str = "vsttime"
    wait_to_col: str = "service5"
    wait_max_min: int = 240
    targets: dict = field(default_factory=lambda: dict(TARGET_DEFAULTS))
    village_csv: str = os.path.join(HERE, "village_pcu.csv")
    chwpart: str = "30"
    amppart: str = "25"
    hospcode: str = "10894"
    #: สัญชาติไทย (person.nationality / patient.nationality) — ตัวหาร KPI นับเฉพาะหญิงไทย
    thai_nationality: str = "99"
    #: บันทึกวันคลอดน้อยกว่านี้ (% ของครรภ์ที่ครบกำหนดแล้ว) → ขึ้นเตือนบนแดชบอร์ด
    labor_warn_pct: float = 80
    data_audited: bool = False
    cache_seconds: int = 600


def _list(v):
    return tuple(x.strip() for x in (v or "").split(",") if x.strip())


def _dx(v):
    return tuple(x.replace(".", "").upper() for x in _list(v))


def _num(v, default):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f == int(f) else f


def _col(v, default):
    v = (v or "").strip()
    return v if _TIME_COL.fullmatch(v) else default


def load_config(env=os.environ):
    d = Config()
    g = env.get
    path = g("ANC_VILLAGE_CSV") or d.village_csv
    return Config(
        dt_codes=_list(g("ANC_DT_VACCINE_CODES")) or d.dt_codes,
        hct_lab_ids=tuple(int(x) for x in _list(g("ANC_HCT_LAB_IDS")) if x.isdigit()),
        hct_cutoff=_num(g("ANC_HCT_CUTOFF"), d.hct_cutoff),
        hct_late_ga=int(_num(g("ANC_HCT_LATE_GA"), d.hct_late_ga)),
        lbw_grams=int(_num(g("ANC_LBW_GRAMS"), d.lbw_grams)),
        dead_dchstts=_list(g("ANC_DEAD_DCHSTTS")) or d.dead_dchstts,
        iodine_didstd=_list(g("ANC_IODINE_DIDSTD")) or d.iodine_didstd,
        cbc_lab_codes=_list(g("ANC_CBC_LAB_CODES")),
        dm_lab_codes=_list(g("ANC_DM_LAB_CODES")),
        us_icd9=tuple(x.replace(".", "") for x in _list(g("ANC_US_ICD9"))) or d.us_icd9,
        down_dx=tuple(x.replace(".", "").upper() for x in _list(g("ANC_DOWN_DX"))) or d.down_dx,
        dm_dx=tuple(x.replace(".", "").upper() for x in _list(g("ANC_DM_DX"))) or d.dm_dx,
        thal_export_codes=_list(g("ANC_THAL_EXPORT_CODES")) or d.thal_export_codes,
        asphyxia_apgar=int(_num(g("ANC_ASPHYXIA_APGAR"), d.asphyxia_apgar)),
        bba_types=_list(g("ANC_BBA_TYPES")) or d.bba_types,
        dx_htn=_dx(g("ANC_DX_HTN")) or d.dx_htn,
        dx_gdm=_dx(g("ANC_DX_GDM")) or d.dx_gdm,
        dx_pph=_dx(g("ANC_DX_PPH")) or d.dx_pph,
        dx_preterm=_dx(g("ANC_DX_PRETERM")) or d.dx_preterm,
        postpartum_days=int(_num(g("ANC_POSTPARTUM_DAYS"), d.postpartum_days)),
        refer_dx_prefixes=tuple(x.upper() for x in _list(g("ANC_REFER_DX_PREFIXES"))) or d.refer_dx_prefixes,
        wait_from_col=_col(g("ANC_WAIT_FROM_COL"), d.wait_from_col),
        wait_to_col=_col(g("ANC_WAIT_TO_COL"), d.wait_to_col),
        wait_max_min=int(_num(g("ANC_WAIT_MAX_MIN"), d.wait_max_min)),
        targets={k: _num(g(f"ANC_TARGET_{k.upper()}" if k != "visit5" else "ANC_TARGET_5VISIT"), v)
                 for k, v in TARGET_DEFAULTS.items()},
        village_csv=path if os.path.isabs(path) else os.path.join(HERE, path),
        chwpart=(g("ANC_CHWPART") or d.chwpart).strip().zfill(2),
        amppart=(g("ANC_AMPPART") or d.amppart).strip().zfill(2),
        hospcode=(g("ANC_HOSPCODE") or d.hospcode).strip(),
        thai_nationality=(g("ANC_THAI_NATIONALITY") or d.thai_nationality).strip(),
        labor_warn_pct=_num(g("ANC_LABOR_WARN_PCT"), d.labor_warn_pct),
        data_audited=g("ANC_DATA_AUDITED", "0").strip() == "1",
        cache_seconds=int(_num(g("ANC_CACHE_SECONDS"), d.cache_seconds)),
    )


def village_code(chw, amp, tmb, moo):
    """รหัสหมู่บ้าน 8 หลัก (จังหวัด อำเภอ ตำบล หมู่ ส่วนละ 2 หลัก) แบบ VILLAGE ของ 43 แฟ้ม · ส่วนใดว่าง = None"""
    parts = [str(x).strip() if x is not None else "" for x in (chw, amp, tmb, moo)]
    if not all(p.isdigit() for p in parts):
        return None
    return "".join(p.zfill(2)[-2:] for p in parts)


def load_village_pcu(path, chw, amp):
    """village_pcu.csv (ไฟล์เดียวกับ mental_health_dashboard: tmbpart,tambon,moo,village,hospcode,pcu)
    → {หมู่บ้าน 8 หลัก: (hospcode, ชื่อ รพ.สต.)} ของอำเภอ chw/amp · ไม่มีไฟล์ = None

    แถวละ 1 หมู่ · หมู่ที่ รพ. ดูแลเองใส่ hospcode ของ รพ. · รับไฟล์ที่ผ่าน Excel (BOM ช่องว่าง เลข 0 หน้าหาย)
    แถวที่ตำบล/หมู่ไม่ใช่ตัวเลขข้ามไป (เหมือน mental_health_dashboard)
    """
    if not os.path.exists(path):
        return None
    try:
        text = open(path, encoding="utf-8-sig", newline="").read()
    except UnicodeDecodeError:
        raise PcuMapError("ไฟล์ไม่ใช่ UTF-8 — ใน Excel ให้บันทึกเป็น \"CSV UTF-8 (Comma delimited)\"") from None
    rows = csv.DictReader(text.splitlines())
    cols = [c.strip() for c in (rows.fieldnames or [])]
    missing = [c for c in PCU_COLUMNS if c not in cols]
    if missing:
        raise PcuMapError(f"ไม่มีคอลัมน์ {', '.join(missing)} — หัวตารางต้องเป็น tmbpart,tambon,moo,village,hospcode,pcu")
    out = {}
    for r in rows:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        code = village_code(chw, amp, r["tmbpart"], r["moo"])
        if code and r["hospcode"]:
            out[code] = (r["hospcode"], r["pcu"])
    return out
