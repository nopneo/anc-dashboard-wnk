"""รายชื่อเบื้องหลังตัวเลขบนแดชบอร์ด — ใช้เงื่อนไขชุดเดียวกับ metrics.py / risk27.py (ห้ามเขียนเงื่อนไขซ้ำที่นี่)

members(key, ...) คืน {"key", "label", "kind", "ok_label", "rows": [(แถวข้อมูล, เข้าเกณฑ์?)]}
  kind = preg (ครรภ์) · infant (ทารกเกิดใน รพ.) · refer (การส่งต่อ)
  rows = ฐานของตัวเลขนั้น: อัตรา → ทั้งตัวหาร (ok = อยู่ในตัวตั้ง) · จำนวนนับ → เฉพาะรายที่นับ (ok = None)
ตัวกรอง pcu / age ใช้แบบเดียวกับตาราง รพ.สต. / กลุ่มอายุ (กรองครรภ์ก่อนแล้วคำนวณ)
tests/test_drill.py ตรวจว่าจำนวนแถวเท่ากับตัวเลขบนแดชบอร์ดทุกช่อง
"""

import metrics
import risk27
import ogtt
import sti
import anemia

_m = metrics

#: key → (ชื่อ, คำอธิบายคอลัมน์เข้าเกณฑ์) ของรายชื่อที่เป็นครรภ์
#: ชนิด OGTT ในรายชื่อ (all = รวมทุกชนิด นับคนละครั้ง)
OGTT_LABELS = {**ogtt.LABELS, "all": "OGTT (ทุกชนิดรวมกัน)"}

PREG = {
    "new": ("ฝากครรภ์รายใหม่ในช่วง", None),
    "early12": ("ฝากครรภ์ครั้งแรก ≤ 12 สัปดาห์ (ครรภ์ที่คลอดในช่วง)", "≤12 wk"),
    "visit5": ("ฝากครรภ์ครบ 5 ครั้งตามเกณฑ์ (ครรภ์ที่คลอดในช่วง)", "ครบ 5"),
    "visit8": ("ฝากครรภ์ครบ 8 ครั้งตามเกณฑ์ (ครรภ์ที่คลอดในช่วง)", "ครบ 8"),
    "postnatal": ("ดูแลหลังคลอดครบ 3 ครั้ง (คลอดและพ้น 42 วันแล้ว)", "ครบ 3"),
    "quality": ("ฝากครรภ์คุณภาพ ครบ 5 กิจกรรม (ครรภ์ที่คลอดในช่วง)", "ครบ"),
    "iodine": ("ได้ยาเม็ดเสริมไอโอดีน (มาฝากครรภ์ที่ รพ. ในช่วง)", "ได้ยา"),
    "dt": ("ได้วัคซีน dT (ครรภ์ที่คลอดในช่วง)", "ได้ dT"),
    "dental": ("ได้ตรวจช่องปาก (ครรภ์ที่คลอดในช่วง)", "ตรวจแล้ว"),
    "anemia": ("โลหิตจางใกล้คลอด (ครรภ์ที่คลอดและมีผล Hct)", "โลหิตจาง"),
    "teen_repeat": ("ตั้งครรภ์ซ้ำในหญิงอายุ < 20 ปี (ครรภ์ที่คลอด/แท้งในช่วง)", "ครรภ์ที่ ≥ 2"),
    "preterm": ("คลอดก่อนกำหนด < 37 สัปดาห์ (ครรภ์ที่คลอดและมี LMP)", "ก่อนกำหนด"),
    "place_here": ("สถานที่คลอด (ครรภ์ที่คลอดในช่วง)", "คลอดที่ รพ."),
    "maternal_death": ("มารดาเสียชีวิต", None),
    "open": ("หญิงตั้งครรภ์ที่กำลังติดตาม ณ วันสิ้นสุดช่วง", "≤12 wk"),
    "labor_due": ("ครรภ์ครบกำหนดแล้ว (LMP ≥ 42 สัปดาห์) — บันทึกวันคลอดใน person_anc", "ลงวันคลอดแล้ว"),
    **{k: (f"{label} (ครรภ์ที่คลอดในช่วง)", "ได้") for k, label in metrics.QUALITY_PARTS},
    **{k: (f"ภาวะแทรกซ้อน: {label} (ครรภ์ที่คลอดในช่วง)", "พบ") for k, label in metrics.COMPLICATIONS},
    "hct_tested": ("ได้เจาะ Hct ระหว่างตั้งครรภ์ (ครรภ์ที่คลอดในช่วง)", "เจาะแล้ว"),
    "hct_anemic": ("ซีดระหว่างตั้งครรภ์ (ครรภ์ที่คลอดและได้เจาะ Hct)", "ซีด"),
    **{f"hct_{k}": (f"ติดตามภาวะซีด: {label} (ครรภ์ที่คลอดในช่วง)", None) for k, label in anemia.GROUPS},
    **{f"sti_{k}_test": (f"ตรวจ{label} (ฝากครรภ์รายใหม่ในช่วง)", "ตรวจแล้ว") for k, label in sti.LABELS.items()},
    **{f"sti_{k}_pos": (f"ผลบวก {label} (ฝากครรภ์รายใหม่ที่ได้ตรวจ)", "ผลบวก") for k, label in sti.LABELS.items()},
    **{f"ogtt_{k}_test": (f"ตรวจ {label} (ใบสั่ง lab ในช่วง ระหว่างตั้งครรภ์)", "ผิดปกติ") for k, label in OGTT_LABELS.items()},
    **{f"ogtt_{k}_abn": (f"ผล {label} ผิดปกติตั้งแต่เกณฑ์ (ใบสั่ง lab ในช่วง ระหว่างตั้งครรภ์)", None)
       for k, label in OGTT_LABELS.items()},
}
INFANT = {
    "lbw": ("ทารกน้ำหนักแรกเกิดน้อย (เกิดมีชีพที่ชั่งน้ำหนัก)", "< 2,500 g"),
    "asphyxia": ("ทารกขาดออกซิเจนแรกเกิด (เกิดมีชีพ)", "ขาดออกซิเจน"),
    "stillbirth": ("ทารกตายคลอด / เสียชีวิต", None),
    "bba": ("คลอดก่อนถึงโรงพยาบาล (BBA)", None),
}
REFER = {"refer": ("ส่งต่อ (Refer) งานแม่และเด็ก", None)}


def keys():
    """ทุก key ที่ members รู้จัก (ใช้ในเทสต์)"""
    r27 = (["r27_any"] + ["r27_" + it["key"] for it in risk27.ITEMS] + ["r27g_" + g for g, _ in risk27.GROUPS]
           + ["r27_" + k for k, _, _ in risk27.EXTRAS])
    return list(PREG) + list(INFANT) + list(REFER) + r27


def _pcu_ok(village, pcu, pcu_map, cfg):
    return pcu is None or (pcu_map is not None and metrics.pcu_of(village, pcu_map, cfg)[0] == pcu)


def _age_ok(age, want):
    if want is None:
        return True
    if want in ("lt15", "15_19"):
        return metrics.teen_sub(age) == want
    return metrics.age_group(age) == want


def _r27(key):
    """r27_<ข้อ> / r27g_<กลุ่ม> / r27_any → (ชื่อ, ฟังก์ชันรับชุดข้อที่พบ → bool) · ไม่รู้จัก = None"""
    if key == "r27_any":
        return "ครรภ์เสี่ยง: พบอย่างน้อย 1 ข้อ (ฝากครรภ์รายใหม่ในช่วง)", bool
    if key.startswith("r27g_"):
        g = dict(risk27.GROUPS).get(key[5:])
        keys_ = {it["key"] for it in risk27.ITEMS if it["group"] == key[5:]}
        return (f"ครรภ์เสี่ยง: {g} (ฝากครรภ์รายใหม่ในช่วง)", lambda f: bool(set(f) & keys_)) if g else None
    k = key[4:]
    if key.startswith("r27_") and k in risk27.LABELS:
        return f"ครรภ์เสี่ยง: {risk27.LABELS[k]} (ฝากครรภ์รายใหม่ในช่วง)", lambda f: k in f
    return None


def members(key, data, d1, d2, cfg, area, pcu_map, pcu=None, age=None, nat=None):
    """data = {"pregs", "visits", "infants", "refers" (ผ่าน select_refers แล้ว), "pnc", "risk_hits", "sti", "hct", "ogtt"}"""
    if nat is not None and (key in INFANT or key in REFER):
        # ทารก/ส่งต่อไม่มีสัญชาติเอง → ใช้สัญชาติของครรภ์ที่ HN มารดาตรงกัน (ตรงกับที่แดชบอร์ดกรอง)
        hns = {p.get("hn") for p in data["pregs"] if bool(p.get("thai")) is (nat == "th")}
        data = dict(data, infants=[i for i in data["infants"] if i.get("hn") in hns],
                    refers=[r for r in data["refers"] if r.get("hn") in hns])
    if key in INFANT:
        return _infants(key, data, d1, d2, cfg, pcu_map, pcu)
    if key in REFER:
        rows = [(r, None) for r in data["refers"]
                if _pcu_ok(r.get("village"), pcu, pcu_map, cfg) and (age is None or r.get("group") == age)]
        return {"key": key, "label": REFER[key][0], "kind": "refer", "ok_label": None, "rows": rows}

    r27 = _r27(key) if key.startswith("r27") else None
    if key not in PREG and r27 is None:
        return None
    pregs = [p for p in data["pregs"] if _pcu_ok(p.get("village"), pcu, pcu_map, cfg) and _age_ok(p.get("age"), age)
             and (nat is None or bool(p.get("thai")) is (nat == "th"))]       # nat: th = หญิงไทย · fr = ต่างชาติ
    vmap = metrics._by_anc(data["visits"])
    vs = lambda p: vmap.get(p["anc_id"], [])
    new = [p for p in pregs if metrics._in(p.get("register_date"), d1, d2)]
    delivered = metrics._delivered(pregs, d1, d2, area)

    if r27:
        label, test = r27
        fl = risk27.flags(new, data["risk_hits"], cfg)
        base, ok = new, lambda p: test(fl.get(p["anc_id"], {}))
        return {"key": key, "label": label, "kind": "preg", "ok_label": "พบ", "rows": [(p, ok(p)) for p in base]}

    flag = lambda f: (lambda p: bool(p.get(f)))
    st = lambda p, k: sti.status(data.get("sti") or {}, p["anc_id"], k)
    og = lambda p, k: ogtt.status(data.get("ogtt") or {}, p["anc_id"], k, cfg)
    hg = lambda p: anemia.classify((data.get("hct") or {}).get(p["anc_id"]) or [], cfg)
    spec = {
        "new": lambda: (new, None),
        "early12": lambda: (delivered, lambda p: metrics.is_early12(p, vs(p))),
        "visit5": lambda: (delivered, lambda p: metrics._is_5visit(p, vs(p))),
        "visit8": lambda: (delivered, lambda p: metrics._is_8visit(p, vs(p))),
        "postnatal": lambda: metrics.postnatal_base([p for p in pregs if area is None or area(p)],
                                                    data["pnc"], d1, d2),
        "quality": lambda: (delivered, lambda p: all(p.get(k) for k, _ in metrics.QUALITY_PARTS)),
        "iodine": lambda: (metrics.iodine_base(pregs, data["visits"], d1, d2), flag("has_iodine")),
        "dt": lambda: (delivered, flag("has_dt")),
        "dental": lambda: (delivered, flag("has_dental")),
        "anemia": lambda: (metrics.anemia_base(delivered), lambda p: p["hct_late"] < cfg.hct_cutoff),
        "teen_repeat": lambda: (metrics.teen_repeat_base(delivered), metrics.is_repeat),
        "preterm": lambda: ([p for p in delivered if p.get("lmp")], metrics.is_preterm),
        "place_here": lambda: (delivered, lambda p: p.get("labour_hospcode") == cfg.hospcode),
        "maternal_death": lambda: ([p for p in pregs if metrics.died_in_window(p, d1, d2, cfg)], None),
        "open": lambda: ([p for p in pregs if metrics.pregnant_on(p, d2)], lambda p: metrics.is_early12(p, vs(p))),
        "labor_due": lambda: (metrics.labor_due(pregs, d1, d2), lambda p: p.get("labor_date") is not None),
        **{k: (lambda k=k: (delivered, flag(k))) for k, _ in metrics.QUALITY_PARTS},
        **{k: (lambda k=k: (delivered, flag(k))) for k, _ in metrics.COMPLICATIONS},
        "hct_tested": lambda: (delivered, lambda p: hg(p) is not None),
        "hct_anemic": lambda: ([p for p in delivered if hg(p) is not None], lambda p: hg(p) != "normal"),
        **{f"hct_{k}": (lambda k=k: ([p for p in delivered if hg(p) == k], None)) for k, _ in anemia.GROUPS},
        **{f"sti_{k}_test": (lambda k=k: (new, lambda p: st(p, k) is not None)) for k in sti.LABELS},
        **{f"sti_{k}_pos": (lambda k=k: ([p for p in new if st(p, k) is not None], lambda p: st(p, k) == "pos"))
           for k in sti.LABELS},
        **{f"ogtt_{k}_test": (lambda k=k: ([p for p in pregs if og(p, k) is not None], lambda p: og(p, k) == "abn"))
           for k in OGTT_LABELS},
        **{f"ogtt_{k}_abn": (lambda k=k: ([p for p in pregs if og(p, k) == "abn"], None)) for k in OGTT_LABELS},
    }
    base, ok = spec[key]()
    label, ok_label = PREG[key]
    return {"key": key, "label": label, "kind": "preg", "ok_label": ok_label, "d2": d2,
            "rows": [(p, ok(p) if ok else None) for p in base]}


def _infants(key, data, d1, d2, cfg, pcu_map, pcu):
    infants = [i for i in data["infants"] if _pcu_ok(i.get("village"), pcu, pcu_map, cfg)]
    born = [i for i in infants if metrics._in(i.get("birth_date"), d1, d2)]
    base, ok = {
        "lbw": lambda: (metrics.live_weighed(infants, d1, d2), lambda i: i["weight"] < cfg.lbw_grams),
        "asphyxia": lambda: ([i for i in born if i.get("alive")], lambda i: metrics.is_asphyxia(i, cfg)),
        "stillbirth": lambda: ([i for i in born if not i.get("alive")], None),
        "bba": lambda: ([i for i in born if str(i.get("delivery_type") or "") in cfg.bba_types], None),
    }[key]()
    label, ok_label = INFANT[key]
    return {"key": key, "label": label, "kind": "infant", "ok_label": ok_label,
            "rows": [(i, ok(i) if ok else None) for i in base]}
