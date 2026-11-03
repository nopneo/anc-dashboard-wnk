"""รายงานโรคติดเชื้อทางเพศสัมพันธ์ในหญิงตั้งครรภ์ (ซิฟิลิส · ไวรัสตับอักเสบบี · HIV) จากผล lab — ฟังก์ชันบริสุทธิ์

ผล lab ของ HOSxP พิมพ์มือ สะกดไม่ตรงกัน ("Non Recative", "Reactive titer 1:8", "Positive 3 Test") จึงจัดกลุ่มเป็น
  pos = Reactive / Positive · neg = Non-reactive / Negative · unclear = ว่าง / Inconclusive / ข้อความอื่น (ไม่นับเป็นลบ)
ครรภ์หนึ่งตรวจหลายครั้ง: พบบวกครั้งใด = บวก · ไม่งั้นมีผลลบ = ลบ · เหลือแต่ผลไม่ชัด = ไม่ชัด
รหัส lab ตั้งได้ด้วย env (ANC_STI_*_LABS / ANC_STI_*_ANC_LABS) · ไม่ตั้ง = เลือกจากชื่อรายการ — ตรวจที่หน้า /check
"""

import re

import metrics

#: (key, ชื่อ, regex ชื่อ lab_items, regex รหัส/ชื่อ anc_lab)
TESTS = (
    ("syphilis", "ซิฟิลิส (VDRL / TPHA)", r"^(vdrl|rpr|tpha|syphilis)\b", r"vdrl|rpr|tpha"),
    ("hbv", "ไวรัสตับอักเสบบี (HBs Ag)", r"^hbs\s*ag\b", r"hbs\s*ag"),
    ("hiv", "HIV (Anti-HIV)", r"^(anti-?\s*hiv|hiv\s*ag)\b", r"hiv"),
)
LABELS = {k: label for k, label, _, _ in TESTS}

_NEG = re.compile(r"non\W*r|neg", re.I)
_POS = re.compile(r"pos|r\w{0,2}e?a?c\w*tive|reac|rect", re.I)
_RANK = {"pos": 2, "neg": 1, "unclear": 0}


def classify(text):
    """ผล lab 1 ค่า → pos / neg / unclear (ตัดอักขระควบคุม/สระลอยที่ติดมาจากการพิมพ์ก่อน)"""
    s = re.sub(r"[^\x20-\x7eก-ฮเ-ๆ]", "", str(text or "")).strip()
    if not s:
        return "unclear"
    if _NEG.search(s):
        return "neg"
    if _POS.search(s):
        return "pos"
    return "unclear"


def merge(results):
    """[(สถานะ, ข้อความ)] ของครรภ์เดียว → (สถานะที่หนักสุด, ข้อความผลของสถานะนั้น)"""
    best = max((st for st, _ in results), key=_RANK.get)
    texts = []
    for st, t in results:
        t = re.sub(r"[\x00-\x1f]", "", str(t or "")).strip()
        if st == best and t and t not in texts:
            texts.append(t)
    return best, "; ".join(texts) or "-"


def _pick(rows, col):
    out = {}
    for key, _, name_rx, anc_rx in TESTS:
        rx = re.compile(name_rx if col == "name" else anc_rx, re.I)
        out[key] = tuple(c for c, n in rows if rx.search(str(n or "").strip()))
    return out


def pick_lab_codes(labs):
    """[(lab_items_code, lab_items_name)] → {test: (รหัส, ...)} เลือกจากชื่อรายการ"""
    return _pick([(str(c), n) for c, n in labs], "name")


def pick_anc_lab_ids(anc_labs):
    """[(anc_lab_id, anc_lab_code)] → {test: (id, ...)} ผลที่ลงไว้ในหน้า ANC (person_anc_lab)"""
    return {k: tuple(int(x) for x in v) for k, v in _pick(list(anc_labs), "anc").items()}


def status(res, anc_id, key):
    """สถานะของครรภ์สำหรับการตรวจ key · ไม่มีผลเลย = None (ยังไม่ได้ตรวจ)"""
    return (res.get(anc_id) or {}).get(key, (None, None))[0]


def summarize(new, res, cfg):
    """ครรภ์รายใหม่ในช่วง → ต่อการตรวจ: ได้ตรวจ (ของครรภ์ใหม่) · ผลบวก (ของที่ตรวจ) · ผลไม่ชัด · ยังไม่ตรวจ"""
    out = []
    for key, label, _, _ in TESTS:
        st = [status(res, p["anc_id"], key) for p in new]
        tested = [s for s in st if s is not None]
        out.append({"key": key, "label": label,
                    "tested": metrics._rate("sti_" + key + "_test", len(tested), len(new), cfg),
                    "pos": metrics._rate("sti_" + key + "_pos", tested.count("pos"), len(tested), cfg),
                    "unclear": tested.count("unclear"), "untested": len(new) - len(tested)})
    return out
