"""คัดกรองภาวะครรภ์เสี่ยง 27 ข้อ ตามสมุดบันทึกสุขภาพแม่และเด็ก (สมุดสีชมพู) — โค้ดล้วน ไม่แตะฐานข้อมูล

ฟอร์มคัดกรองใน HOSxP (person_anc_classifying_item) มีแค่ 18 ข้อ จึงรวมหลายแหล่งต่อข้อ:
  F = ฟอร์มคัดกรอง HOSxP (ติ๊ก 'Y')           C = คำนวณ (อายุ ส่วนสูง BMI visit แรก)
  D = Dx ICD-10 (OPD/IPD)                      T = ข้อความ HPI/PMH ใน opdscreen (ประมาณการ ตัดประโยคปฏิเสธออกก่อน)
ข้อที่ไม่มีแหล่งข้อมูลเลยจะไม่ถูกนับ (ไม่ใช่ 0 โดยปริยาย — ดูช่อง known / sources)
ผลเป็นจำนวนนับเท่านั้น ไม่มีข้อมูลรายคน
"""

from collections import Counter

GROUPS = (("age_body", "ปัจจัยด้านอายุและร่างกาย"), ("history", "ประวัติการตั้งครรภ์และการคลอดในอดีต"),
          ("medical", "โรคประจำตัวและภาวะอายุรกรรม"), ("current", "ภาวะแทรกซ้อนของการตั้งครรภ์ปัจจุบัน"))

#: (key, กลุ่ม, ชื่อ, ข้อของฟอร์ม HOSxP, คำนวณ?)
_DEF = (
    ("age_lt17", "age_body", "อายุต่ำกว่า 17 ปี", (), True),
    ("age_ge35", "age_body", "อายุ 35 ปีขึ้นไป", (), True),
    ("height_lt145", "age_body", "ส่วนสูงน้อยกว่า 145 ซม.", (), True),
    ("bmi_low", "age_body", "น้ำหนักน้อย (BMI < 18.5)", (), True),
    ("bmi_high", "age_body", "น้ำหนักมาก / อ้วน (BMI ≥ 25)", (), True),
    ("recurrent_abortion", "history", "เคยแท้งติดต่อกัน ≥ 2 ครั้ง", ("2",), False),
    ("fetal_death", "history", "เคยทารกเสียชีวิตในครรภ์ / แรกเกิด", ("1",), False),
    ("prev_lbw", "history", "เคยคลอดบุตรน้ำหนัก < 2,500 กรัม", ("3",), False),
    ("prev_macrosomia", "history", "เคยคลอดบุตรน้ำหนัก > 4,000 กรัม", ("4",), False),
    ("prev_preterm", "history", "เคยคลอดก่อนกำหนด (< 37 สัปดาห์)", (), False),
    ("prev_surgery", "history", "เคยผ่าตัดคลอด / ผ่าตัดเนื้องอกมดลูก", ("6",), False),
    ("ectopic_molar", "history", "เคยท้องนอกมดลูก / ไข่ปลาอุก", (), False),
    ("prev_pih", "history", "เคยครรภ์เป็นพิษ", ("5",), False),
    ("prev_pph", "history", "เคยตกเลือดหลังคลอด / รกติดแน่น", (), False),
    ("prev_anomaly", "history", "เคยคลอดบุตรพิการแต่กำเนิด / โรคพันธุกรรม", (), False),
    ("chronic_ht", "medical", "ความดันโลหิตสูงเรื้อรัง", (), False),
    ("pre_dm", "medical", "เบาหวาน (เป็นก่อนตั้งครรภ์)", ("14",), False),
    ("heart", "medical", "โรคหัวใจและหลอดเลือด", ("16",), False),
    ("ckd", "medical", "โรคไตเรื้อรัง", ("15",), False),
    ("blood", "medical", "โรคเลือด / ธาลัสซีเมียรุนแรง", (), False),
    ("infection", "medical", "ติดเชื้อเรื้อรัง (HIV, ตับอักเสบบี/ซี, ซิฟิลิส)", (), False),
    ("thyroid", "medical", "โรคต่อมไทรอยด์", (), False),
    ("neuro_psych", "medical", "ระบบประสาท / จิตเวช (ลมชัก, ซึมเศร้า)", (), False),
    ("autoimmune", "medical", "ภูมิแพ้ตนเอง (SLE)", (), False),
    ("twin", "current", "ครรภ์แฝด", ("7",), False),
    ("bleeding", "current", "เลือดออกทางช่องคลอด / รกเกาะต่ำ / รกลอกตัว", ("11",), False),
    ("fetal_abn", "current", "ทารกโตช้า / ท่าผิดปกติ / น้ำคร่ำผิดปกติ", (), False),
)
ITEMS = tuple({"num": n, "key": k, "group": g, "label": lab, "form": f, "calc": c}
              for n, (k, g, lab, f, c) in enumerate(_DEF, 1))

#: ข้อของฟอร์ม HOSxP ที่ไม่ตรงกับ 27 ข้อ — นับเข้า "มีความเสี่ยงอย่างน้อย 1 ข้อ" เท่านั้น
EXTRAS = (("extra_10", "10", "Rh Negative"), ("extra_12", "12", "ก้อนในอุ้งเชิงกราน"),
          ("extra_13", "13", "ความดัน Diastolic > 90 mmHg"), ("extra_17", "17", "ติดยาเสพติด / สุรา"),
          ("extra_18", "18", "โรคอายุรกรรมอื่น ๆ (โลหิตจาง ไทรอยด์ SLE ฯลฯ)"))

#: Dx ICD-10 รหัส 3 หรือ 4 หลักไม่มีจุด (ตั้งได้ด้วย ANC_RISK_DX_<KEY>)
DEFAULT_DX = {
    "ectopic_molar": ("O00", "O01"),
    "chronic_ht": ("I10", "I11", "I12", "I13", "I15", "O10"),
    "pre_dm": ("E10", "E11", "E12", "E13", "E14", "O240", "O241", "O242", "O243"),
    "heart": ("I05", "I06", "I07", "I08", "I09", "I20", "I21", "I25", "I42", "I48", "I50", "O994"),
    "ckd": ("N18", "N19", "O102"),
    "blood": ("D56", "D57", "D58", "D61"),
    "infection": ("B20", "B21", "B22", "B23", "B24", "Z21", "B16", "B17", "B18", "B19",
                  "A50", "A51", "A52", "A53", "O986"),
    "thyroid": ("E00", "E01", "E02", "E03", "E04", "E05", "E06", "E07"),
    "neuro_psych": ("G40", "G41", "F20", "F21", "F22", "F23", "F25", "F28", "F29",
                    "F30", "F31", "F32", "F33", "F34", "F38", "F39"),
    "autoimmune": ("M30", "M31", "M32", "M33", "M34", "M35"),
    "twin": ("O30",),
    "bleeding": ("O20", "O44", "O45", "O46"),
    "fetal_abn": ("O32", "O365", "O40", "O41"),
}

#: คำค้นใน HPI/PMH — regex ไม่สนตัวพิมพ์ ผ่าน REGEXP ของ MariaDB (ตั้งได้ด้วย ANC_RISK_TEXT_<KEY>)
DEFAULT_TEXT = {
    "recurrent_abortion": r"แท้งซ้ำ|แท้ง.{0,6}(ติดต่อ|[2-9] ?ครั้ง)|recurrent|habitual",
    "fetal_death": r"ตายในครรภ์|ตายคลอด|IUFD|stillbirth|เสียชีวิตแรกเกิด|neonatal death",
    "prev_preterm": r"ก่อนกำหนด|preterm|\bPTL\b|premature",
    "prev_surgery": r"\bC/S\b|\bLSCS\b|ผ่าตัดคลอด|ผ่าท้องคลอด|myomectomy|เนื้องอกมดลูก",
    "ectopic_molar": r"ท้องนอกมดลูก|ตั้งครรภ์นอกมดลูก|ectopic|\bEP\b|ไข่ปลาอุก|molar|\bGTD\b",
    "prev_pih": r"ครรภ์เป็นพิษ|\bPIH\b|pre-?eclampsia|eclampsia",
    "prev_pph": r"ตกเลือดหลังคลอด|\bPPH\b|รกค้าง|รกติด",
    "prev_anomaly": r"พิการแต่กำเนิด|congenital|ดาวน์|down syndrome|ปากแหว่ง|เพดานโหว่",
    "chronic_ht": r"\bCHT\b|ความดันโลหิตสูง|ความดันสูง|\bHT\b|hypertension",
    "pre_dm": r"\bDM\b|เบาหวาน|T2DM|T1DM",
    "heart": r"โรคหัวใจ|หัวใจ|\bCHF\b|valv|rheumatic|heart disease",
    "ckd": r"\bCKD\b|โรคไต|ไตวาย|\bCRF\b",
    "blood": r"ธาลัสซีเมีย|thalass|โลหิตจางรุนแรง|severe anemia|ซิกเคิล",
    "infection": r"\bHIV ?(positive|\+)|HIV\+|ซิฟิลิส|syphilis|ไวรัสตับอักเสบ|hepatitis|\bHBV\b|\bHCV\b|ตับอักเสบ|HBsAg ?(positive|pos|\+)",
    "thyroid": r"ไทรอยด์|thyroid|graves|hyperT|hypoT",
    "neuro_psych": r"ลมชัก|epilep|ซึมเศร้า|depress|จิตเวช|psych|schizo|ไบโพลาร์|bipolar|จิตเภท",
    "autoimmune": r"\bSLE\b|lupus|ภูมิแพ้ตนเอง|autoimmune",
    "twin": r"ครรภ์แฝด|twin|แฝด",
    "bleeding": r"รกเกาะต่ำ|previa|รกลอกตัว|abruption|\bAPH\b|เลือดออกทางช่องคลอด|PV bleed",
    "fetal_abn": r"IUGR|\bFGR\b|โตช้า|oligo|polyhydr|น้ำคร่ำ|ท่าก้น|breech|ท่าผิดปกติ|ท่าขวาง|transverse",
}

#: ตัดประโยคที่ถูกปฏิเสธออกก่อนค้นคำ ("ปฏิเสธโรคประจำตัว DM HT" ไม่นับว่าเป็น DM)
NEGATION = (r"(ปฏิเสธ|ไม่เคย|ไม่มี|ไม่พบ|ไม่ได้|ไม่|denied|denies|deny|\bno\b|\bnil\b|negative)[^\n;.]*")

#: ช่องข้อความที่ค้นของแต่ละหมวด: โรคประจำตัว = PMH เท่านั้น (HPI มักเป็นเรื่องตรวจคัดกรองครั้งนี้ เช่น "ตรวจเบาหวาน")
#: ประวัติอดีต = HPI + PMH (ประวัติครรภ์ก่อนมักเขียนใน HPI) · ภาวะปัจจุบัน = HPI
TEXT_FIELD = {"age_body": "all", "history": "all", "medical": "pmh", "current": "hpi"}

HEIGHT_OK = (100, 210)
WEIGHT_OK = (25, 200)
SOURCE_ORDER = ("F", "C", "D", "T")


def _pct(n, den):
    return round(100 * n / den, 1) if den else None


def _body(hits, anc_id):
    h, w = hits.get("body", {}).get(anc_id, (None, None))
    h = h if h is not None and HEIGHT_OK[0] <= h <= HEIGHT_OK[1] else None
    w = w if w is not None and WEIGHT_OK[0] <= w <= WEIGHT_OK[1] else None
    return h, w


def _calc(key, p, hits, cfg):
    """(พบ?, มีข้อมูลพอตัดสิน?) ของข้อที่คำนวณ"""
    if key in ("age_lt17", "age_ge35"):
        age = p.get("age")
        if age is None:
            return False, False
        return (age < cfg.risk_age_low if key == "age_lt17" else age >= cfg.risk_age_high), True
    h, w = _body(hits, p["anc_id"])
    if key == "height_lt145":
        return (h < cfg.risk_height_cm if h else False), h is not None
    if h is None or w is None:
        return False, False
    bmi = w / (h / 100) ** 2
    return (bmi < cfg.risk_bmi_low if key == "bmi_low" else bmi >= cfg.risk_bmi_high), True


def item_sources(it, p, hits, cfg):
    """(แหล่งที่พบข้อนี้ในครรภ์ p เช่น {"F", "D"}, มีข้อมูลพอตัดสิน?)"""
    i, key, src, known = p["anc_id"], it["key"], set(), True
    if it["calc"]:
        hit, known = _calc(key, p, hits, cfg)
        if hit:
            src.add("C")
    if it["form"] and hits["form"].get(i, set()) & set(it["form"]):
        src.add("F")
    dx_codes = set(cfg.risk_dx.get(key, ()))
    if dx_codes and hits["dx"].get(i, set()) & dx_codes:
        src.add("D")
    if key in hits["text"].get(i, set()) and cfg.risk_text.get(key):
        src.add("T")
    return src, known


def flags(pregs, hits, cfg):
    """{anc_id: {key: แหล่ง}} ข้อเสี่ยงที่พบรายครรภ์ (รวมข้อเสริมจากฟอร์ม · แหล่ง = "F") — ใช้ในหน้ารายชื่อ"""
    out = {}
    for p in pregs:
        found = {}
        for it in ITEMS:
            src, _ = item_sources(it, p, hits, cfg)
            if src:
                found[it["key"]] = src
        for key, fid, _ in EXTRAS:
            if fid in hits["form"].get(p["anc_id"], set()):
                found[key] = {"F"}
        out[p["anc_id"]] = found
    return out


LABELS = {**{it["key"]: it["label"] for it in ITEMS}, **{k: lab for k, _, lab in EXTRAS}}


def summarize(pregs, hits, cfg):
    """pregs = ครรภ์รายใหม่ในช่วง · hits = {"form","dx","text","body"} จาก queries.risk_hits"""
    den = len(pregs)
    thai = {p["anc_id"] for p in pregs if p.get("thai")}                # ที่เหลือ = ต่างชาติ (สัญชาติไม่ใช่ ANC_THAI_NATIONALITY)
    den_th = len(thai)
    split = lambda ids: (len(ids & thai), len(ids - thai))              # (ไทย, ต่างชาติ)
    flagged = {}                       # anc_id -> ชุด key ที่พบ
    items = []
    for it in ITEMS:
        key = it["key"]
        by = Counter()
        found, known = set(), 0
        for p in pregs:
            src, ok = item_sources(it, p, hits, cfg)
            known += ok
            if src:
                found.add(p["anc_id"])
                by.update(src)
                flagged.setdefault(p["anc_id"], set()).add(key)
        dx_codes = set(cfg.risk_dx.get(key, ()))
        avail = [s for s, on in (("F", it["form"]), ("C", it["calc"]), ("D", dx_codes),
                                 ("T", cfg.risk_text.get(key))) if on]
        n_th, n_fr = split(found)
        items.append({**it, "sources": avail, "n": len(found), "pct": _pct(len(found), den), "known": known,
                      "n_th": n_th, "n_fr": n_fr, "pct_th": _pct(n_th, den_th), "pct_fr": _pct(n_fr, den - den_th),
                      "by_source": {s: by[s] for s in SOURCE_ORDER if by[s]}})

    extras = []
    for key, fid, label in EXTRAS:
        ids = {p["anc_id"] for p in pregs if fid in hits["form"].get(p["anc_id"], set())}
        n_th, n_fr = split(ids)
        extras.append({"key": key, "label": label, "n": len(ids), "pct": _pct(len(ids), den),
                       "n_th": n_th, "n_fr": n_fr, "pct_th": _pct(n_th, den_th), "pct_fr": _pct(n_fr, den - den_th)})
        for i in ids:
            flagged.setdefault(i, set()).add(key)

    def tally(ids):
        n_th, n_fr = split(ids)
        return {"num": len(ids), "den": den, "pct": _pct(len(ids), den), "num_th": n_th, "num_fr": n_fr,
                "pct_th": _pct(n_th, den_th), "pct_fr": _pct(n_fr, den - den_th)}

    groups = []
    for gkey, glabel in GROUPS:
        keys = {it["key"] for it in ITEMS if it["group"] == gkey}
        groups.append({"key": gkey, "label": glabel, **tally({i for i, ks in flagged.items() if ks & keys})})
    top = sorted((x for x in items if x["n"]), key=lambda x: (-x["n"], x["num"]))[:10]
    return {"den": den, "den_th": den_th, "den_fr": den - den_th, "items": items, "extras": extras,
            "groups": groups, "top": top, "any": tally(set(flagged))}
