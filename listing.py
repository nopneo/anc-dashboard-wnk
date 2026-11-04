"""ตารางรายชื่อ (หน้า /list) และไฟล์ Excel — แปลงผลของ drill.members เป็นหัวตาราง + แถวที่ใช้ร่วมกันทั้งสองแบบ

แถว = {"cells": [...], "ok": True/False/None, "pcu": ชื่อ รพ.สต., "search": ข้อความสำหรับค้นชื่อ/HN}
"""

import re
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

import metrics
import risk27
import ogtt
import sti
import anemia

TH_MONTHS = metrics.TH_MONTHS


def thai_date(d):
    return f"{d.day} {TH_MONTHS[d.month - 1]} {d.year + 543}" if d else "-"


def mark(ok):
    return "-" if ok is None else "✔" if ok else "✘"


def _pcu_name(village, pcu_map, cfg):
    return metrics.pcu_of(village, pcu_map or {}, cfg)[1]


def _extra(key, data, cfg, d2=None):
    """คอลัมน์เพิ่มเฉพาะบางรายชื่อ → [(หัวคอลัมน์, ฟังก์ชันรับครรภ์)]"""
    if key == "labor_due" and d2:
        return [("GA ณ วันสิ้นสุดช่วง (สัปดาห์)", lambda p: (d2 - p["lmp"]).days // 7)]
    if key == "teen_repeat":
        dash = lambda v: "-" if v is None else v
        return [("อายุ ณ วันสิ้นสุดครรภ์", lambda p: dash(p.get("age_labor"))),
                ("ครรภ์ที่", lambda p: dash(p.get("gravida")))]
    if (key or "").startswith("hct_"):
        ser = lambda p: (data.get("hct") or {}).get(p["anc_id"]) or []

        def delta(p):
            c = anemia.change(ser(p))
            return "-" if c is None else f"{c:+.1f}"
        return [("Hct ตามลำดับ (GA สัปดาห์)", lambda p: anemia.trail(ser(p))), ("เปลี่ยนไป", delta),
                ("ผลติดตาม", lambda p: anemia.LABELS.get(anemia.classify(ser(p), cfg), "ยังไม่ได้เจาะ"))]
    o = re.fullmatch(r"ogtt_(\w+?)_(test|abn)", key or "")
    if o and o.group(1) in (*ogtt.LABELS, "all"):
        res, k = data.get("ogtt") or {}, o.group(1)

        def last(p):
            d = max((s["date"] for s in (res.get(p["anc_id"]) or {}).values() if s.get("date")), default=None)
            return thai_date(d)
        return [("ผล OGTT (mg/dL · * = ผิดปกติ)", lambda p: ogtt.detail(res, p["anc_id"], k, cfg)),
                ("วันที่ตรวจล่าสุด", last)]
    t = re.fullmatch(r"sti_(\w+?)_(test|pos)", key or "")
    if t and t.group(1) in sti.LABELS:
        res = data.get("sti") or {}
        k = t.group(1)
        return [(f"ผลตรวจ {sti.LABELS[k]}", lambda p: ((res.get(p["anc_id"]) or {}).get(k) or (None, "-"))[1])]
    return []


def table(m, data, cfg, pcu_map, names):
    """(หัวตาราง, แถว) ของรายชื่อ m = drill.members(...)"""
    kind, ok_label = m["kind"], m["ok_label"]
    who = lambda hn: names.get(hn) or {"name": "-", "addr": ""}
    rows = []
    if kind == "preg":
        vmap = metrics._by_anc(data["visits"])
        buckets = {"visit5": metrics.GA_BUCKETS, "visit8": metrics.GA_BUCKETS_8}.get(m["key"])
        flags = risk27.flags([p for p, _ in m["rows"]], data["risk_hits"], cfg)
        extra = _extra(m["key"], data, cfg, m.get("d2"))
        head = ["ชื่อ-สกุล", "HN", "อายุ", "ที่อยู่", "รพ.สต.", "วันลงทะเบียน", "LMP", "GA ครั้งแรก",
                "ฝากครรภ์ (ที่ รพ./ที่อื่น)"] + (["ช่วงที่ยังขาด (สัปดาห์)"] if buckets else []) + \
               ["วันคลอด", "สถานที่คลอด"] + [h for h, _ in extra] + ([ok_label] if ok_label else []) +                ["ข้อเสี่ยงที่พบ (27 ข้อ)"]
        for p, ok in m["rows"]:
            vs = vmap.get(p["anc_id"], [])
            ga = metrics._first_ga(p, vs)
            here = sum(1 for v in vs if not v.get("precare"))
            w = who(p.get("hn"))
            pcu = _pcu_name(p.get("village"), pcu_map, cfg)
            cells = [w["name"], p.get("hn") or "-", p.get("age") if p.get("age") is not None else "-", w["addr"] or "-",
                     pcu, thai_date(p.get("register_date")), thai_date(p.get("lmp")),
                     ga if ga is not None else "-", f"{here}/{len(vs) - here}"]
            if buckets:
                cells.append(", ".join(metrics.missing_buckets(p, vs, buckets)) or "-")
            cells += [thai_date(p.get("labor_date")),
                      ("รพ.นี้" if p.get("labour_hospcode") == cfg.hospcode else p.get("labour_place")
                       or p.get("labour_hospcode") or "-") if p.get("labor_date") else "-"]
            cells += [f(p) for _, f in extra]
            if ok_label:
                cells.append(mark(ok))
            cells.append(", ".join(risk27.LABELS[k] for k in flags.get(p["anc_id"], {})) or "-")
            rows.append({"cells": cells, "ok": ok, "pcu": pcu, "search": f"{w['name']} {p.get('hn') or ''}"})
    elif kind == "infant":
        head = ["ชื่อมารดา", "HN มารดา", "ที่อยู่", "รพ.สต.", "วันเกิด", "น้ำหนัก (กรัม)", "Apgar 1 นาที",
                "มีชีพ"] + ([ok_label] if ok_label else [])
        for i, ok in m["rows"]:
            w = who(i.get("hn"))
            pcu = _pcu_name(i.get("village"), pcu_map, cfg)
            cells = [w["name"], i.get("hn") or "-", w["addr"] or "-", pcu, thai_date(i.get("birth_date")),
                     i.get("weight") or "-", i.get("apgar1") if i.get("apgar1") is not None else "-",
                     mark(bool(i.get("alive")))] + ([mark(ok)] if ok_label else [])
            rows.append({"cells": cells, "ok": ok, "pcu": pcu, "search": f"{w['name']} {i.get('hn') or ''}"})
    else:
        head = ["ชื่อ-สกุล", "HN", "อายุ", "รพ.สต.", "วันที่ส่งต่อ", "Dx หลัก", "ส่งไป"]
        for r, ok in m["rows"]:
            w = who(r.get("hn"))
            pcu = _pcu_name(r.get("village"), pcu_map, cfg)
            dx = " ".join(x for x in (r.get("pdx"), r.get("dx_name")) if x) or "-"
            cells = [w["name"], r.get("hn") or "-", r.get("age") if r.get("age") is not None else "-", pcu,
                     thai_date(r.get("date")), dx, r.get("dest_name") or r.get("dest") or "-"]
            rows.append({"cells": cells, "ok": ok, "pcu": pcu, "search": f"{w['name']} {r.get('hn') or ''}"})
    rows.sort(key=lambda r: (r["pcu"], r["search"]))
    return head, rows


def _sheet_name(name, used):
    """ชื่อชีท Excel ≤31 ตัวอักษร ห้ามมีอักขระ : \\ / ? * [ ] และห้ามซ้ำ"""
    s = re.sub(r'[:\\/?*\[\]]', '', name)[:31] or "sheet"
    base, i = s, 2
    while s in used:
        suffix = f" ({i})"
        s = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(s)
    return s


def _write(ws, head, rows):
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r["cells"])
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 8), 50)
    ws.freeze_panes = "A2"


def workbook(head, rows, meta, by_pcu=False):
    """ไฟล์ Excel (BytesIO) — ชีทแรก = รายชื่อทั้งหมด · by_pcu = เพิ่มชีทแยก รพ.สต. · ชีทท้าย = ที่มาของรายชื่อ"""
    wb = Workbook()
    ws = wb.active
    used = set()
    ws.title = _sheet_name("รวม", used)
    _write(ws, head, rows)
    if by_pcu:
        for pcu in sorted({r["pcu"] for r in rows}):
            _write(wb.create_sheet(_sheet_name(pcu, used)), head, [r for r in rows if r["pcu"] == pcu])
    info = wb.create_sheet(_sheet_name("ที่มา", used))
    for k, v in meta:
        info.append([k, v])
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 70
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
