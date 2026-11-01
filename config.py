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
TARGET_DEFAULTS = {"early12": 75, "visit5": 75, "dt": 90, "dental": 50, "anemia": 14, "lbw": 7}

PCU_HEADER = ["village_code", "pcu_hospcode", "pcu_name"]


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
    postpartum_days: int = 42
    refer_dx_prefixes: tuple = ("O", "Z32", "Z33", "Z34", "Z35", "Z36")
    wait_from_col: str = "vsttime"
    wait_to_col: str = "service5"
    wait_max_min: int = 240
    targets: dict = field(default_factory=lambda: dict(TARGET_DEFAULTS))
    pcu_map_path: str = os.path.join(HERE, "pcu_map.csv")
    data_audited: bool = False
    cache_seconds: int = 600


def _list(v):
    return tuple(x.strip() for x in (v or "").split(",") if x.strip())


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
    path = g("ANC_PCU_MAP") or d.pcu_map_path
    return Config(
        dt_codes=_list(g("ANC_DT_VACCINE_CODES")) or d.dt_codes,
        hct_lab_ids=tuple(int(x) for x in _list(g("ANC_HCT_LAB_IDS")) if x.isdigit()),
        hct_cutoff=_num(g("ANC_HCT_CUTOFF"), d.hct_cutoff),
        hct_late_ga=int(_num(g("ANC_HCT_LATE_GA"), d.hct_late_ga)),
        lbw_grams=int(_num(g("ANC_LBW_GRAMS"), d.lbw_grams)),
        dead_dchstts=_list(g("ANC_DEAD_DCHSTTS")) or d.dead_dchstts,
        postpartum_days=int(_num(g("ANC_POSTPARTUM_DAYS"), d.postpartum_days)),
        refer_dx_prefixes=tuple(x.upper() for x in _list(g("ANC_REFER_DX_PREFIXES"))) or d.refer_dx_prefixes,
        wait_from_col=_col(g("ANC_WAIT_FROM_COL"), d.wait_from_col),
        wait_to_col=_col(g("ANC_WAIT_TO_COL"), d.wait_to_col),
        wait_max_min=int(_num(g("ANC_WAIT_MAX_MIN"), d.wait_max_min)),
        targets={k: _num(g(f"ANC_TARGET_{k.upper()}" if k != "visit5" else "ANC_TARGET_5VISIT"), v)
                 for k, v in TARGET_DEFAULTS.items()},
        pcu_map_path=path if os.path.isabs(path) else os.path.join(HERE, path),
        data_audited=g("ANC_DATA_AUDITED", "0").strip() == "1",
        cache_seconds=int(_num(g("ANC_CACHE_SECONDS"), d.cache_seconds)),
    )


def village_code(chw, amp, tmb, moo):
    """รหัสหมู่บ้าน 8 หลัก (จังหวัด อำเภอ ตำบล หมู่ ส่วนละ 2 หลัก) แบบ VILLAGE ของ 43 แฟ้ม · ส่วนใดว่าง = None"""
    parts = [str(x).strip() if x is not None else "" for x in (chw, amp, tmb, moo)]
    if not all(p.isdigit() for p in parts):
        return None
    return "".join(p.zfill(2)[-2:] for p in parts)


def load_pcu_map(path):
    """village_code → (pcu_hospcode, pcu_name) · ไม่มีไฟล์ = None

    รับไฟล์ที่ผ่าน Excel มาแล้ว: มี BOM, ช่องว่างรอบค่า, เลข 0 หน้ารหัสหาย (7 หลัก → เติมเป็น 8)
    """
    if not os.path.exists(path):
        return None
    out = {}
    try:
        text = open(path, encoding="utf-8-sig", newline="").read()
    except UnicodeDecodeError:
        raise PcuMapError("ไฟล์ไม่ใช่ UTF-8 — ใน Excel ให้บันทึกเป็น \"CSV UTF-8 (Comma delimited)\"") from None
    rows = csv.reader(text.splitlines())
    header = [h.strip() for h in next(rows, [])]
    if header[:3] != PCU_HEADER:
        raise PcuMapError(f"หัวตารางต้องเป็น {','.join(PCU_HEADER)} (พบ {','.join(header)})")
    for n, row in enumerate(rows, start=2):
        row = [c.strip() for c in row] + ["", "", ""]
        code, hcode, name = row[:3]
        if not code and not hcode:
            continue
        if not code.isdigit() or len(code) not in (7, 8):
            raise PcuMapError(f"บรรทัด {n}: village_code '{code}' ต้องเป็นตัวเลข 8 หลัก")
        out[code.zfill(8)] = (hcode, name)
    return out
