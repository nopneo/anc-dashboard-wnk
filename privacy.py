"""ป้องกันการย้อนหาตัวบุคคลจากตัวเลขรวมในหน้าสาธารณะ (คนนอก รพ. ที่ไม่ได้ login)

ปัญหา: ถ้าเลือกช่วงวันที่ได้อิสระ (แคบถึง 1 วัน หรือช่วงซ้อนกันแล้วลบกัน) และช่องที่มีจำนวนน้อยแสดงตัวเลขจริง
คนที่รู้ว่าใครมาฝากครรภ์วันไหนจะอ่านผล HIV / ซิฟิลิส / ตับอักเสบบี / สารเสพติด หรือการตั้งครรภ์อายุต่ำกว่า 15 ปี
ของคนนั้นได้จากตัวเลขรวม

มาตรการ (เฉพาะหน้าสาธารณะ — เครื่องใน รพ. และผู้ที่ login แล้วเห็นตัวเลขเต็มเหมือนเดิม):
1. ช่วงข้อมูลปัดเป็นเดือนเต็ม: วันเริ่ม = วันที่ 1 ของเดือน · วันสิ้นสุด = สิ้นเดือน (เดือนปัจจุบันถึงวันนี้)
2. ช่องที่เป็นข้อมูลสุขภาพอ่อนไหว ถ้ามีจำนวน 1 ถึง MIN_CELL-1 แสดงเป็น "<5" และไม่แสดงร้อยละ
   ถ้าตัวหารน้อยกว่า MIN_CELL ซ่อนทั้งช่อง (รวมค่า 0) เพราะ 0/1 ก็บอกผลของคนคนเดียว

ANC_PUBLIC_MIN_CELL = ขนาดช่องขั้นต่ำ (ค่าเริ่มต้น 5) · 0 = ปิดมาตรการทั้งหมด (ไม่แนะนำ)
"""

import calendar
import copy
import os
from datetime import date

MIN_CELL = max(int(os.getenv("ANC_PUBLIC_MIN_CELL", "5") or 0), 0)

#: ความเสี่ยงใน 27 ข้อ / ฟอร์มเพิ่มเติมที่เป็นข้อมูลอ่อนไหวพิเศษ
SENSITIVE_RISK = {"age_lt17", "infection", "neuro_psych", "extra_17"}

#: ช่องที่ซ่อนทั้งหมด (ตัวหารน้อย) — แสดงแบบเดียวกับค่าว่างของหน้า
HIDDEN = "—"


def enabled():
    return MIN_CELL > 0


def label():
    return f"<{MIN_CELL}"


def month_window(d1, d2, today=None):
    """ปัดช่วงเป็นเดือนเต็ม · วันสิ้นสุดไม่เกินวันนี้ (ช่วงที่ผ่านการตรวจจาก _range_from แล้ว)"""
    today = today or date.today()
    end = d2.replace(day=calendar.monthrange(d2.year, d2.month)[1])
    return d1.replace(day=1), min(end, today)


def _small(n):
    return isinstance(n, int) and not isinstance(n, bool) and 0 < n < MIN_CELL


def count(n):
    """จำนวนนับของเหตุการณ์อ่อนไหว → "<5" ถ้า 1–4"""
    return label() if _small(n) else n


def _rate(r):
    """{"num","den","value",...} → ซ่อนเมื่อตัวหารน้อย หรือตัวตั้ง 1–4"""
    if not isinstance(r, dict):
        return r
    num, den = r.get("num"), r.get("den")
    if _small(den):
        return {**r, "num": HIDDEN, "den": label(), "value": None, "ok": None, "low_base": False, "suppressed": "den"}
    if _small(num):
        return {**r, "num": label(), "value": None, "ok": None, "low_base": False, "suppressed": "num"}
    return r


def _pct_pair(row, n_key, pct_key):
    if _small(row.get(n_key)):
        row[n_key], row[pct_key] = label(), None


def public_ctx(ctx, rebuild_alerts):
    """สำเนาของ ctx (ctx ต้นฉบับอยู่ใน cache ที่ใช้ร่วมกับเครื่องใน รพ. ห้ามแก้) ที่ซ่อนช่องอ่อนไหวแล้ว

    rebuild_alerts(ctx) → รายการแจ้งเตือนใหม่จากค่าที่ซ่อนแล้ว (ข้อความ "แม่อายุต่ำกว่า 15 ปี" / "มารดาเสียชีวิต")
    """
    if not enabled():
        return ctx
    c = copy.deepcopy(ctx)
    c["public_privacy"] = True

    for t in c.get("sti") or []:                       # ผล HIV / ซิฟิลิส / ตับอักเสบบี / สารเสพติด
        t["pos"] = _rate(t.get("pos"))
        t["unclear"] = HIDDEN if t["pos"].get("suppressed") == "den" else count(t.get("unclear"))

    teen = (c.get("age") or {}).get("teen")
    if teen:
        if _small(teen.get("lt15")):
            # teen.new = lt15 + 15_19 → ซ่อน 15_19 ด้วย ไม่งั้นลบกันได้ค่า lt15 (15_19 ไม่ได้แสดงในหน้าเว็บ มีแค่ใน JSON)
            teen["lt15"], teen["15_19"] = label(), None

    o = c.get("outcome")
    if o:
        o["maternal_death"] = count(o.get("maternal_death"))
        o["stillbirth"] = count(o.get("stillbirth"))

    r = c.get("risk27")
    if r:
        for it in list(r.get("items") or []) + list(r.get("extras") or []):
            if it.get("key") in SENSITIVE_RISK:
                _pct_pair(it, "n", "pct")
                _pct_pair(it, "n_th", "pct_th")
                _pct_pair(it, "n_fr", "pct_fr")
        # top เป็นอ็อบเจ็กต์เดียวกับใน items (deepcopy คงการอ้างอิงร่วม) → ตัดรายการอ่อนไหวที่ถูกซ่อนออกจากอันดับ
        r["top"] = [x for x in r.get("top") or [] if x.get("n") != label()]

    if "main" not in (c.get("errors") or {}):
        c["alerts"] = rebuild_alerts(c)
    return c
