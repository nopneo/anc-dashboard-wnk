"""ติดตามภาวะซีดรายครรภ์จากผล Hct หลายครั้ง (ครรภ์ที่คลอดในช่วง) — ฟังก์ชันบริสุทธิ์

ชุดผล = [{"date", "ga", "hct"}] เรียงตามวัน (LMP ถึงวันคลอด) · ซีด = Hct < ANC_HCT_CUTOFF
(ไตรมาส 2 GA 14–27 ใช้ ANC_HCT_CUTOFF_T2 ได้ เพราะ Hct ลดลงเองจากเลือดเจือจาง)
กลุ่ม (เทียบครั้งแรกกับครั้งล่าสุด):
  normal ปกติตลอด · single ซีดแต่เจาะครั้งเดียว · recovered ครั้งล่าสุดไม่ซีดแล้ว
  improving ยังซีดแต่เพิ่ม ≥ ANC_HCT_IMPROVE จุด · not_improved ยังซีดและเพิ่มไม่ถึง · new ครั้งแรกปกติแต่ล่าสุดซีด
"""

import metrics

#: กลุ่มของครรภ์ที่ซีด (ลำดับบนแดชบอร์ด) → ชื่อ
GROUPS = (("recovered", "หายซีด"), ("improving", "ดีขึ้นแต่ยังซีด"), ("not_improved", "ซีดไม่ดีขึ้น"),
          ("new", "ซีดใหม่ระหว่างตั้งครรภ์"), ("single", "ซีด · เจาะครั้งเดียว"))
LABELS = dict(GROUPS, normal="ไม่ซีด")


def cutoff(ga, cfg):
    return cfg.hct_cutoff_t2 if ga is not None and 14 <= ga <= 27 else cfg.hct_cutoff


def is_anemic(x, cfg):
    return x["hct"] < cutoff(x.get("ga"), cfg)


def classify(series, cfg):
    """ชุดผลของครรภ์ → กลุ่ม · ไม่มีผล = None"""
    if not series:
        return None
    if not any(is_anemic(x, cfg) for x in series):
        return "normal"
    if len(series) == 1:
        return "single"
    first, last = series[0], series[-1]
    if not is_anemic(last, cfg):
        return "recovered"
    if not is_anemic(first, cfg):
        return "new"
    return "improving" if last["hct"] - first["hct"] >= cfg.hct_improve else "not_improved"


def change(series):
    """Hct ครั้งล่าสุด − ครั้งแรก · เจาะครั้งเดียว = None"""
    return round(series[-1]["hct"] - series[0]["hct"], 1) if len(series) >= 2 else None


def trail(series):
    """"29.0 (12) → 34.0 (32)" — Hct (GA สัปดาห์) ตามลำดับ"""
    return " → ".join(f"{x['hct']:.1f} ({x['ga'] if x.get('ga') is not None else '?'})" for x in series) or "-"


def summarize(delivered, series, cfg):
    """ครรภ์ที่คลอดในช่วง → ได้เจาะ Hct · ซีด · จำนวนต่อกลุ่ม"""
    got = [classify(series.get(p["anc_id"]) or [], cfg) for p in delivered]
    tested = [g for g in got if g is not None]
    return {"tested": metrics._rate("hct_tested", len(tested), len(delivered), cfg),
            "untested": len(delivered) - len(tested),
            "anemic": sum(1 for g in tested if g != "normal"),
            "normal": tested.count("normal"),
            "groups": [{"key": k, "label": label, "n": tested.count(k)} for k, label in GROUPS]}
