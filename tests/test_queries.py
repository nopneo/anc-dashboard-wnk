from datetime import date

import pytest

import db
import queries
from config import load_config

CFG = load_config({})
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)


class FakeFetch:
    def __init__(self):
        self.calls, self.rows = [], []

    def __call__(self, sql, args=None):
        db._bind(sql, args)                 # จับ % ที่ไม่ได้ escape / พารามิเตอร์หาย
        self.calls.append((sql, args))
        return list(self.rows)


@pytest.fixture
def fake_fetch(monkeypatch):
    f = FakeFetch()
    monkeypatch.setattr(queries, "fetch", f)
    return f


def test_pregnancies_converts_types(fake_fetch):
    fake_fetch.rows = [{"anc_id": "7", "hn": "0001", "age": "19", "chwpart": "30", "amppart": "25", "tmbpart": "01",
                        "moopart": "03", "register_date": "2026-01-05", "lmp": "2025-11-20", "labor_date": None,
                        "hct_lab": "", "hct_anc": "31.5", "has_dt": "1", "has_dental": "0"}]
    r = queries.pregnancies(D1, D2, CFG)[-1]
    assert r["village"] == "30250103" and r["age"] == 19 and r["lmp"] == date(2025, 11, 20)
    assert r["has_dt"] is True and r["has_dental"] is False and r["hct_late"] == 31.5 and r["labor_date"] is None


def test_hct_prefers_lab_result_and_rejects_text(fake_fetch):
    base = {"anc_id": "1", "hn": "1", "age": None, "chwpart": None, "amppart": None, "tmbpart": None,
            "moopart": None, "register_date": "2026-01-05", "lmp": None, "labor_date": None,
            "has_dt": "0", "has_dental": "0"}
    fake_fetch.rows = [dict(base, hct_lab="30", hct_anc="36"), dict(base, hct_lab=None, hct_anc="ปกติ")]
    rows = queries.pregnancies(D1, D2, load_config({"ANC_HCT_LAB_IDS": "6,7"}))
    assert [r["hct_late"] for r in rows] == [30.0, None] and rows[0]["village"] is None


def test_codes_are_parameters_not_literals(fake_fetch):
    queries.pregnancies(D1, D2, load_config({"ANC_HCT_LAB_IDS": "6,7"}))
    sql, args = fake_fetch.calls[-1]
    assert "201" not in sql and args["dt"] == CFG.dt_codes and args["hct"] == (6, 7)


def test_hct_ids_looked_up_when_not_set(fake_fetch):
    fake_fetch.rows = []
    queries.pregnancies(D1, D2, CFG)
    lookup, _ = fake_fetch.calls[0]
    assert "anc_lab" in lookup and fake_fetch.calls[-1][1]["hct"] == (-1,)


def test_visits_batches_of_500(fake_fetch):
    queries.visits(list(range(1201)))
    assert len(fake_fetch.calls) == 3
    assert queries.visits([]) == [] and len(fake_fetch.calls) == 3


def test_visits_types(fake_fetch):
    fake_fetch.rows = [{"anc_id": "1", "date": "2026-02-01", "ga": "0", "precare": "0"},
                       {"anc_id": "1", "date": "2026-01-01", "ga": None, "precare": "1"}]
    v = queries.visits([1])
    assert v[0] == {"anc_id": 1, "date": date(2026, 2, 1), "ga": None, "precare": False}
    assert v[1]["precare"] is True


def test_no_waits_query():
    assert not hasattr(queries, "waits")


def test_pregnancy_has_gravida_and_age_at_labor(fake_fetch):
    fake_fetch.rows = [{"anc_id": "7", "hn": "1", "age": "18", "age_labor": "19", "gravida": "2",
                        "register_date": "2026-01-05", "lmp": None, "labor_date": "2026-03-01"},
                       {"anc_id": "8", "hn": "2", "age": "18", "age_labor": None, "gravida": "",
                        "register_date": "2026-01-05", "lmp": None, "labor_date": None}]
    a, b = queries.pregnancies(D1, D2, CFG)
    assert (a["gravida"], a["age_labor"]) == (2, 19) and (b["gravida"], b["age_labor"]) == (None, None)


def test_sti_results_maps_codes_to_tests(fake_fetch):
    cfg = load_config({"ANC_STI_SYPHILIS_LABS": "365", "ANC_STI_HBV_LABS": "355", "ANC_STI_HIV_LABS": "362",
                       "ANC_STI_SYPHILIS_ANC_LABS": "1", "ANC_STI_HBV_ANC_LABS": "", "ANC_STI_HIV_ANC_LABS": "3"})
    fake_fetch.rows = [{"anc_id": "7", "code": "365", "result": "Non Reactive"},
                       {"anc_id": "7", "code": "anc:1", "result": "Reactive 1:8"},
                       {"anc_id": "7", "code": "355", "result": "Negative"},
                       {"anc_id": "8", "code": "362", "result": ""},
                       {"anc_id": "8", "code": "999", "result": "Positive"}]
    r = queries.sti_results(D1, D2, cfg)
    assert r[7]["syphilis"][0] == "pos" and "Reactive 1:8" in r[7]["syphilis"][1]
    assert r[7]["hbv"] == ("neg", "Negative") and r[8] == {"hiv": ("unclear", "-")}
    sql, args = fake_fetch.calls[-1]
    assert "365" not in sql and set(args["codes"]) == {"365", "355", "362"} and set(args["anc_ids"]) == {1, 3}


def test_infants_alive_and_village(fake_fetch):
    fake_fetch.rows = [{"birth_date": "2026-02-01", "weight": "2400", "dead": "N", "chwpart": "30",
                        "amppart": "25", "tmbpart": "02", "moopart": "11"},
                       {"birth_date": "2026-02-02", "weight": "0", "dead": "Y", "chwpart": None,
                        "amppart": None, "tmbpart": None, "moopart": None}]
    i = queries.infants(D1, D2)
    assert i[0] == {"birth_date": date(2026, 2, 1), "weight": 2400, "alive": True, "village": "30250211",
                    "apgar1": None, "asphyxia": False, "delivery_type": None, "hn": None}
    assert i[1]["alive"] is False and i[1]["weight"] is None


def test_refers_maps_columns(fake_fetch):
    fake_fetch.rows = [{"refer_id": "9", "date": "2026-03-01", "hn": "55", "pdx": "O149", "dx_name": "Pre-eclampsia",
                        "dest": "10666", "dest_name": "รพ.มหาราช", "age": "36", "chwpart": "30", "amppart": "25",
                        "tmbpart": "01", "moopart": "01", "minutes": "-5"}]
    r = queries.refers(D1, D2)[0]
    assert r["refer_id"] == 9 and r["date"] == date(2026, 3, 1) and r["age"] == 36
    assert r["village"] == "30250101" and r["minutes"] is None


def test_pregnancy_falls_back_to_person_village(fake_fetch):
    """ครรภ์ที่ person ไม่ผูก patient: ใช้รหัสหมู่บ้าน 8 หลักจาก village ของ person"""
    fake_fetch.rows = [{"anc_id": "1", "hn": None, "age": "22", "chwpart": None, "amppart": None, "tmbpart": None,
                        "moopart": None, "v_code": "30250105", "register_date": "2026-01-05", "lmp": None,
                        "labor_date": None, "hct_lab": None, "hct_anc": None, "has_dt": "0", "has_dental": "0"},
                       {"anc_id": "2", "hn": None, "age": None, "chwpart": None, "amppart": None, "tmbpart": None,
                        "moopart": None, "v_code": "3025", "register_date": "2026-01-05", "lmp": None,
                        "labor_date": None, "hct_lab": None, "hct_anc": None, "has_dt": "0", "has_dental": "0"}]
    rows = queries.pregnancies(D1, D2, load_config({"ANC_HCT_LAB_IDS": "6"}))
    assert [r["village"] for r in rows] == ["30250105", None]
    sql, _ = fake_fetch.calls[-1]
    assert "pe.birthdate" in sql and "v.village_code" in sql


def test_pregnancy_links_patient_by_cid_when_hn_missing(fake_fetch):
    queries.pregnancies(D1, D2, load_config({"ANC_HCT_LAB_IDS": "6"}))
    sql, _ = fake_fetch.calls[-1]
    assert "p2.cid = pe.cid" in " ".join(sql.split())


def test_refers_normalizes_9_digit_dest_codes(fake_fetch):
    """รหัส 9 หลัก (EA0010666) กับ 5 หลัก (10666) ของ รพ. เดียวกัน ต้องรวมเป็นปลายทางเดียว"""
    queries.refers(D1, D2)
    sql, _ = fake_fetch.calls[-1]
    assert "hospcode_5_digit" in sql


def test_infants_dead_by_discharge_status(fake_fetch):
    fake_fetch.rows = [{"birth_date": "2026-02-01", "weight": "1800", "dead": "N", "dchstts": "09",
                        "chwpart": None, "amppart": None, "tmbpart": None, "moopart": None}]
    assert queries.infants(D1, D2)[0]["alive"] is False
    sql, args = fake_fetch.calls[-1]
    assert "infant_dchstts" in sql and args["dead"] == ("08", "09")


# ---------- KPI จากโฟลเดอร์ kpi ----------

def test_lab_codes_by_name_when_not_set(fake_fetch):
    fake_fetch.rows = [{"code": c, "name": n} for c, n in [
        ("37", "Hemoglobin (HGB)"), ("38", "Hct (CBC)"), ("121", "Hemoglobin Typing"), ("2026", "Hemoglobin cast"),
        ("9", "CBC"), ("240", "OGTT 50 G"), ("287", "DTX"), ("297", "Fluid Glucose"), ("2016", "FBS"),
        ("2195", "Urine Glucose"), ("2032", "Glucose"), ("2258", "FBS(DTX)"), ("5", "GCT 50 g")]]
    cbc, dm = queries.lab_codes(CFG)
    assert cbc == ("37", "38", "9")
    assert dm == ("240", "287", "2016", "2032", "2258", "5")
    assert queries.lab_codes(load_config({"ANC_CBC_LAB_CODES": "1", "ANC_DM_LAB_CODES": "2"})) == (("1",), ("2",))


def test_pregnancy_kpi_flags(fake_fetch):
    base = {"anc_id": "1", "hn": "1", "age": "25", "chwpart": None, "amppart": None, "tmbpart": None, "moopart": None,
            "register_date": "2026-01-05", "lmp": "2025-11-01", "labor_date": None, "hct_lab": None, "hct_anc": None,
            "has_dt": "0", "has_dental": "0", "has_iodine": "1", "q_cbc": "1", "q_thal": "0", "q_us": "1",
            "q_down": "1", "q_dm": "0"}
    fake_fetch.rows = [base]
    r = queries.pregnancies(D1, D2, load_config({"ANC_HCT_LAB_IDS": "6", "ANC_CBC_LAB_CODES": "38",
                                                 "ANC_DM_LAB_CODES": "2016"}))[-1]
    assert (r["has_iodine"], r["q_cbc"], r["q_thal"], r["q_us"], r["q_down"], r["q_dm"]) == \
        (True, True, False, True, True, False)
    sql, args = fake_fetch.calls[-1]
    assert args["iod"] == CFG.iodine_didstd and args["us"] == CFG.us_icd9 and args["thal"] == ("1", "2", "4")
    assert args["cbc"] == ("38",) and args["dm"] == ("2016",) and args["down"] == ("Z360", "Z362")
    assert "8878" not in sql and "Z360" not in sql                  # รหัสเป็นพารามิเตอร์


def test_postnatal_dates(fake_fetch):
    fake_fetch.rows = [{"anc_id": "3", "date": "2026-03-05"}, {"anc_id": "3", "date": None}]
    assert queries.postnatal([3]) == [{"anc_id": 3, "date": date(2026, 3, 5)}]
    sql, _ = fake_fetch.calls[-1]
    assert "person_anc_preg_care" in sql and "post_labor_service1_date" in sql
    assert queries.postnatal([]) == []


def test_pregnancy_area_fields(fake_fetch):
    fake_fetch.rows = [{"anc_id": "1", "hn": "1", "age": "25", "chwpart": "30", "amppart": "25", "tmbpart": "01",
                        "moopart": "01", "register_date": "2026-01-05", "lmp": None, "labor_date": None,
                        "hct_lab": None, "hct_anc": None, "has_dt": "0", "has_dental": "0", "nationality": "48",
                        "labour_hospcode": "10894"}]
    r = queries.pregnancies(D1, D2, load_config({"ANC_HCT_LAB_IDS": "6", "ANC_CBC_LAB_CODES": "1",
                                                 "ANC_DM_LAB_CODES": "2"}))[-1]
    assert r["thai"] is False and r["labour_hospcode"] == "10894"
    assert queries.pregnancies(D1, D2, load_config({"ANC_HCT_LAB_IDS": "6", "ANC_CBC_LAB_CODES": "1",
                               "ANC_DM_LAB_CODES": "2", "ANC_THAI_NATIONALITY": "48"}))[-1]["thai"] is True


# ---------- ผลลัพธ์แม่และทารก ----------

def test_pregnancy_outcome_fields(fake_fetch):
    fake_fetch.rows = [{"anc_id": "1", "hn": "1", "age": "25", "chwpart": None, "amppart": None, "tmbpart": None,
                        "moopart": None, "register_date": "2026-01-05", "lmp": None, "labor_date": None,
                        "hct_lab": None, "hct_anc": None, "has_dt": "0", "has_dental": "0", "has_risk": "1",
                        "cx_htn": "1", "cx_gdm": "0", "cx_pph": "0", "cx_preterm": "1", "death_date": "2026-03-01",
                        "labour_place": "รพ.มทส."}]
    cfg = load_config({"ANC_HCT_LAB_IDS": "6", "ANC_CBC_LAB_CODES": "1", "ANC_DM_LAB_CODES": "2"})
    r = queries.pregnancies(D1, D2, cfg)[-1]
    assert (r["has_risk"], r["cx_htn"], r["cx_gdm"], r["cx_preterm"]) == (True, True, False, True)
    assert r["death_date"] == date(2026, 3, 1) and r["labour_place"] == "รพ.มทส."
    sql, args = fake_fetch.calls[-1]
    assert args["htn"] == CFG.dx_htn and args["pph"] == ("O72",) and "O72" not in sql and "iptdiag" in sql


def test_infant_outcome_fields(fake_fetch):
    fake_fetch.rows = [{"birth_date": "2026-02-01", "weight": "2900", "dead": "N", "dchstts": "05", "chwpart": None,
                        "amppart": None, "tmbpart": None, "moopart": None, "apgar1": "6", "asphyxia": "Y",
                        "delivery_type": "3"}]
    i = queries.infants(D1, D2)[0]
    assert (i["apgar1"], i["asphyxia"], i["delivery_type"]) == (6, True, "3")


def test_risk_types(fake_fetch):
    fake_fetch.rows = [{"name": "เคยผ่าคลอด", "n": "4"}]
    assert queries.risk_types(D1, D2) == [{"name": "เคยผ่าคลอด", "n": 4}]
    sql, args = fake_fetch.calls[-1]
    assert "person_anc_classifying" in sql and args == {"d1": D1, "d2": D2}


# ---------- คัดกรองครรภ์เสี่ยง 27 ข้อ ----------

def test_risk_form_hits(fake_fetch):
    fake_fetch.rows = [{"anc_id": "7", "item": "11"}, {"anc_id": "7", "item": "7"}, {"anc_id": "8", "item": "1"}]
    assert queries.risk_form_hits(D1, D2) == {7: {"11", "7"}, 8: {"1"}}
    sql, args = fake_fetch.calls[-1]
    assert "person_anc_classifying" in sql and "check_value = 'Y'" in sql and args == {"d1": D1, "d2": D2}


def test_risk_dx_hits_uses_codes_as_parameters(fake_fetch):
    fake_fetch.rows = [{"anc_id": "7", "c3": "O30", "c4": "O301"}, {"anc_id": "7", "c3": "O44", "c4": "O441"}]
    got = queries.risk_dx_hits(D1, D2, CFG)
    assert got == {7: {"O30", "O301", "O44", "O441"}}
    sql, args = fake_fetch.calls[-1]
    assert "ovstdiag" in sql and "iptdiag" in sql and "O30" in args["codes"] and "O30" not in sql
    assert args["d1"] == D1 and args["d2"] == D2


def test_risk_text_hits_and_body(fake_fetch):
    fake_fetch.rows = [{"anc_id": "7", "height": "158.5", "bw": "52", "t_twin": "1", "t_prev_preterm": "0",
                        "t_pre_dm": None},
                       {"anc_id": "8", "height": "", "bw": None, "t_twin": "0"}]
    got = queries.risk_text_hits(D1, D2, CFG)
    assert got["text"] == {7: {"twin"}}
    assert got["body"] == {7: (158.5, 52.0), 8: (None, None)}
    sql, args = fake_fetch.calls[-1]
    assert "regexp_replace" in sql and "opdscreen" in sql
    assert args["t_twin"].startswith("(?i)(") and "twin" in args["t_twin"] and "ครรภ์แฝด" not in sql
    assert "ปฏิเสธ" in args["neg"]


def test_risk_hits_bundles_all_sources(fake_fetch, monkeypatch):
    monkeypatch.setattr(queries, "risk_form_hits", lambda d1, d2: {1: {"7"}})
    monkeypatch.setattr(queries, "risk_dx_hits", lambda d1, d2, cfg: {1: {"O30"}})
    monkeypatch.setattr(queries, "risk_text_hits", lambda d1, d2, cfg: {"text": {1: {"twin"}}, "body": {1: (150.0, 50.0)}})
    assert queries.risk_hits(D1, D2, CFG) == {"form": {1: {"7"}}, "dx": {1: {"O30"}},
                                              "text": {1: {"twin"}}, "body": {1: (150.0, 50.0)}}


def test_risk_text_searches_the_field_that_fits_each_group(fake_fetch):
    fake_fetch.rows = []
    queries.risk_text_hits(D1, D2, CFG)
    sql, _ = fake_fetch.calls[-1]
    assert "q.pmh_txt regexp %(t_pre_dm)s" in sql        # โรคประจำตัว: PMH เท่านั้น (HPI มีคำว่าเบาหวานจากการตรวจคัดกรอง)
    assert "q.all_txt regexp %(t_prev_preterm)s" in sql  # ประวัติอดีต: HPI + PMH
    assert "q.hpi_txt regexp %(t_twin)s" in sql          # ภาวะปัจจุบัน: HPI


def test_infants_carry_mother_hn(fake_fetch):
    fake_fetch.rows = [{"birth_date": "2026-03-01", "weight": "3000", "dead": "N", "hn": "0001234"}]
    assert queries.infants(D1, D2)[0]["hn"] == "0001234"
    assert "il.hn" in fake_fetch.calls[0][0]


def test_names_batches_and_formats(fake_fetch):
    fake_fetch.rows = [{"hn": "001", "pname": "นาง", "fname": "สมศรี", "lname": "ใจดี", "addrpart": "12",
                        "moopart": "3"}]
    out = queries.names(["001", None, "001"] + [str(i) for i in range(600)])
    assert out["001"] == {"name": "นางสมศรี ใจดี", "addr": "12 ม.3"}
    assert len(fake_fetch.calls) == 2                      # ทีละ 500 HN · ตัด None และซ้ำ
    assert queries.names([]) == {}


def test_sql_has_no_line_comments():
    # โหมด ssh ต่อ SQL เป็นบรรทัดเดียว — "--" จะตัดส่วนที่เหลือทิ้งทั้งหมด
    for name in dir(queries):
        v = getattr(queries, name)
        if isinstance(v, str) and "select" in v.lower():
            assert "-- " not in v, name


def test_hct_series_parses_sorts_and_dedupes(fake_fetch):
    cfg = load_config({"ANC_HCT_SERIES_LABS": "38", "ANC_HCT_LAB_IDS": "6"})
    fake_fetch.rows = [
        {"anc_id": "7", "d": "2026-03-01", "lmp": "2025-09-01", "v": "34", "src": "lab"},
        {"anc_id": "7", "d": "2025-11-01", "lmp": "2025-09-01", "v": "29.5", "src": "lab"},
        {"anc_id": "7", "d": "2025-11-01", "lmp": "2025-09-01", "v": "30", "src": "anc"},    # วันเดียวกัน ใช้ผล lab
        {"anc_id": "7", "d": "2026-01-01", "lmp": "2025-09-01", "v": "ปกติ", "src": "anc"},  # ไม่ใช่ตัวเลข
        {"anc_id": "7", "d": "2026-01-02", "lmp": "2025-09-01", "v": "3", "src": "anc"},     # grade ไม่ใช่ % Hct
        {"anc_id": "8", "d": "2026-02-01", "lmp": None, "v": "31", "src": "lab"}]
    r = queries.hct_series(D1, D2, cfg)
    assert [(x["hct"], x["ga"]) for x in r[7]] == [(29.5, 8), (34.0, 25)]
    assert r[8] == [{"date": date(2026, 2, 1), "ga": None, "hct": 31.0}]
    sql, args = fake_fetch.calls[-1]
    assert "38" not in sql and args["codes"] == ("38",) and args["hct"] == (6,)
