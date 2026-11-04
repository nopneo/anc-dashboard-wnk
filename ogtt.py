"""รายงานผล OGTT (ตรวจความทนต่อกลูโคส) ในหญิงตั้งครรภ์ — ฟังก์ชันบริสุทธิ์

OGTT แต่ละใบสั่งมีหลายค่า (ก่อนกิน / หลังกิน 1, 2, 3 ชั่วโมง) แต่ละค่าเป็น lab_items คนละรหัส
  g100 = OGTT 100 g  4 ค่า · เกณฑ์ Carpenter-Coustan  ≥ 95 / 180 / 155 / 140 mg/dL
  g75  = OGTT 75 g   3 ค่า · เกณฑ์ IADPSG / WHO 2013  ≥ 92 / 180 / 153 mg/dL
ผิดปกติ = ค่าที่ตั้งแต่เกณฑ์ขึ้นไป · ครรภ์ที่ผิดปกติ ≥ ANC_OGTT_MIN_ABN ค่า (ค่าเริ่มต้น 2) = เข้าเกณฑ์วินิจฉัยเบาหวานขณะตั้งครรภ์
ครรภ์หนึ่งตรวจซ้ำได้ → ใช้ชุดล่าสุดของแต่ละชนิดในช่วง (ชุด = ใบสั่ง lab ใบเดียวกัน)
รหัส lab / เกณฑ์ตั้งได้ด้วย env (ANC_OGTT_G100_LABS · ANC_OGTT_G100_CUT …) — ตรวจที่หน้า /check
"""

import re

import metrics

#: (key, ชื่อ, [(ชื่อจุดเจาะ, regex ชื่อ lab_items)], เกณฑ์ผิดปกติ mg/dL ต่อจุด)
TYPES = (
    ("g100", "OGTT 100 g",
     (("ก่อนกิน", r"^ogtt\s*100\s*g\s*ก่อนกิน"), ("1 ชม.", r"^ogtt\s*100\s*g\s*หลังกิน\s*1(?!\d)"),
      ("2 ชม.", r"^ogtt\s*100\s*g\s*หลังกิน\s*2(?!\d)"), ("3 ชม.", r"^ogtt\s*100\s*g\s*หลังกิน\s*3(?!\d)")),
     (95, 180, 155, 140)),
    ("g75", "OGTT 75 g",
     (("ก่อนกิน", r"^ogtt\s*75\s*g\s*ก่อนกิน"), ("1 ชม.", r"^ogtt\s*75\s*g\s*หลังกิน\s*1(?!\d)"),
      ("2 ชม.", r"^ogtt\s*75\s*g\s*หลังกิน\s*2(?!\d)")),
     (92, 180, 153)),
)
LABELS = {k: label for k, label, _, _ in TYPES}
POINTS = {k: tuple(p for p, _ in pts) for k, _, pts, _ in TYPES}
DEFAULT_CUT = {k: cut for k, _, _, cut in TYPES}
#: ค่ากลูโคสที่เชื่อได้ — นอกช่วงนี้ถือว่าพิมพ์ผิด/ไม่ใช่ตัวเลข
VALUE_RANGE = (20.0, 800.0)


def parse(text):
    """ผล lab (พิมพ์มือ เช่น "98", "<70", "190 H") → ตัวเลข mg/dL · ใช้ไม่ได้ = None"""
    m = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    if not m:
        return None
    v = float(m.group())
    return v if VALUE_RANGE[0] <= v <= VALUE_RANGE[1] else None


def pick_codes(labs):
    """[(lab_items_code, lab_items_name)] → {ชนิด: (รหัสจุดที่ 1, 2, …)} · จุดที่หาไม่เจอ = None"""
    out = {}
    for key, _, pts, _ in TYPES:
        row = []
        for _, rx in pts:
            rx = re.compile(rx, re.I)
            row.append(next((str(c) for c, n in labs if rx.search(str(n or "").strip())), None))
        out[key] = tuple(row)
    return out


def _cut(key, cfg):
    cut = tuple(cfg.ogtt_cut.get(key) or ())
    return cut if len(cut) == len(DEFAULT_CUT[key]) else DEFAULT_CUT[key]


def abnormal(vals, key, cfg):
    """ค่าต่อจุด [float|None] → จำนวนจุดที่ผิดปกติ"""
    return sum(1 for v, c in zip(vals, _cut(key, cfg)) if v is not None and v >= c)


def _set(res, anc_id, key):
    return (res.get(anc_id) or {}).get(key)


def status(res, anc_id, key, cfg):
    """สถานะของครรภ์ · key = g100 / g75 / all · ไม่ได้ตรวจ = None · abn (ผิดปกติ ≥ ค่าต่ำสุดที่ตั้ง) / one (1 ค่า) / ok"""
    keys = LABELS if key == "all" else (key,)
    best = None
    for k in keys:
        s = _set(res, anc_id, k)
        if not s:
            continue
        n = abnormal(s["vals"], k, cfg)
        st = "abn" if n >= cfg.ogtt_min_abn else "one" if n else "ok"
        best = st if best is None or ["ok", "one", "abn"].index(st) > ["ok", "one", "abn"].index(best) else best
    return best


def detail(res, anc_id, key, cfg):
    """"ก่อนกิน 98 · 1 ชม. 190* · 2 ชม. 140  — ผิดปกติ 1/3 ค่า (วันที่ …)" · * = ผิดปกติ · key = all → ต่อทุกชนิดที่ตรวจ"""
    out = []
    for k in (LABELS if key == "all" else (key,)):
        s = _set(res, anc_id, k)
        if not s:
            continue
        cut = _cut(k, cfg)
        cells = " · ".join(f"{name} {'-' if v is None else format(v, 'g') + ('*' if v >= c else '')}"
                           for name, v, c in zip(POINTS[k], s["vals"], cut))
        out.append(f"{LABELS[k]}: {cells} — ผิดปกติ {abnormal(s['vals'], k, cfg)}/{len(cut)} ค่า")
    return " | ".join(out) or "-"


def summarize(pregs, res, cfg):
    """ครรภ์ทั้งหมดที่มีผล OGTT ในช่วง → ต่อชนิด (+ รวม): ตรวจแล้ว · ผิดปกติ ≥ n ค่า · ผิดปกติ 1 ค่า"""
    out = []
    for key, label in (*LABELS.items(), ("all", "รวมทุกชนิด (นับคนละครั้ง)")):
        st = [status(res, p["anc_id"], key, cfg) for p in pregs]
        tested = [s for s in st if s is not None]
        out.append({"key": key, "label": label, "tested": len(tested), "abn": tested.count("abn"),
                    "one": tested.count("one"),
                    "rate": metrics._rate("ogtt_" + key, tested.count("abn"), len(tested), cfg)})
    return {"rows": out, "min_abn": cfg.ogtt_min_abn,
            "cuts": {k: _cut(k, cfg) for k in LABELS}, "points": POINTS}
