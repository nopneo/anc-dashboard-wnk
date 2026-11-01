from datetime import date

import pytest

import app as appmod
import check
import db
import queries
from config import load_config

CFG = load_config({})
D1, D2 = date(2026, 1, 1), date(2026, 6, 30)
LAN = {"REMOTE_ADDR": "192.168.1.5"}


class Router:
    """fetch ปลอม: คืนแถวตามคำใน SQL (คำแรกที่ตรง) · ไม่ตรงคืน []"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, sql, args=None):
        db._bind(sql, args)
        self.calls.append(sql)
        flat = " ".join(sql.split())
        for key, rows in self.routes.items():
            if key in flat:
                return [dict(r) for r in rows]
        return []


def _preg(i, village="30250101", labor=date(2026, 3, 1), lmp=date(2025, 6, 1), hct=None):
    return {"anc_id": i, "hn": "HN-SECRET", "age": 25, "village": village, "register_date": date(2026, 1, 2),
            "lmp": lmp, "labor_date": labor, "hct_late": hct, "has_dt": False, "has_dental": False}


@pytest.fixture
def data(monkeypatch):
    monkeypatch.setattr(queries, "pregnancies", lambda d1, d2, cfg: [_preg(1), _preg(2, "11111111"), _preg(3, None)])
    monkeypatch.setattr(queries, "infants", lambda d1, d2, *a: [{"birth_date": D1, "weight": 3000, "alive": True,
                                                             "village": None}])
    monkeypatch.setattr(queries, "refers", lambda d1, d2: [])
    monkeypatch.setattr(queries, "hct_lab_ids", lambda cfg: (6, 7))


def _item(a, key):
    return next(i for i in a["items"] if i["key"] == key)


def test_audit_flags_missing_pcu_map(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({}))
    a = check.audit(D1, D2, CFG, None)
    assert _item(a, "pcu_map")["status"] == "bad"
    assert "HN-SECRET" not in repr(a)


def test_audit_pcu_map_unmapped_warns(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({}))
    a = check.audit(D1, D2, CFG, {"30250102": ("03929", "รพ.สต.ก")})
    assert _item(a, "pcu_map")["status"] == "warn"      # 30250101 กับครรภ์ไม่มีที่อยู่ = ในอำเภอ ไม่ทราบหมู่


def test_audit_dt_warns_on_other_codes(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({"from ovst_vaccine": [
        {"code": "201", "name": "dTANC1", "n": "5", "women": "5"},
        {"code": "101", "name": "TT1/dT1", "n": "300", "women": "120"}]}))
    it = _item(check.audit(D1, D2, CFG, None), "dt_codes")
    assert it["status"] == "warn" and "ANC_DT_VACCINE_CODES" in it["env"]
    assert [f["code"] for f in it["found"]] == ["101", "201"]


def test_audit_dt_ok_when_codes_used(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({"from ovst_vaccine": [
        {"code": "201", "name": "dTANC1", "n": "50", "women": "50"},
        {"code": "101", "name": "TT1/dT1", "n": "30", "women": "3"}]}))
    assert _item(check.audit(D1, D2, CFG, None), "dt_codes")["status"] == "ok"


def test_audit_hct_bad_when_no_results(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({"from anc_lab": [
        {"code": "6", "name": "HCT1", "n": "0"}, {"code": "7", "name": "HCT2", "n": "0"},
        {"code": "8", "name": "HB", "n": "40"}]}))
    assert _item(check.audit(D1, D2, CFG, None), "hct_lab_ids")["status"] == "bad"


def test_audit_wait_col_low_is_bad(monkeypatch, data):
    row = {"total": "100", "vsttime": "100", **{f"service{i}": "0" for i in range(1, 21)}}
    row["service3"] = "90"
    monkeypatch.setattr(check, "fetch", Router({"from service_time": [row]}))
    it = _item(check.audit(D1, D2, CFG, None), "wait_cols")
    assert it["status"] == "bad" and "service3" in it["hint"]


def test_audit_refer_dest_unnamed_and_duplicate(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({"from referout": [
        {"code": "24060", "name": "รพ.มทส.", "n": "70"}, {"code": "FA0024060", "name": "รพ.มทส.", "n": "1"},
        {"code": "99999", "name": None, "n": "2"}]}))
    it = _item(check.audit(D1, D2, CFG, None), "refer_dest")
    assert it["status"] == "warn" and "99999" in it["hint"] and "รพ.มทส." in it["hint"]


def test_completeness(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({}))
    c = {x["title"]: x for x in check.audit(D1, D2, CFG, None)["completeness"]}
    assert c["ครรภ์ที่มี LMP"]["pct"] == 100.0
    assert c["ทารกที่มีน้ำหนักแรกเกิด"]["pct"] == 100.0
    assert c["ครรภ์ที่คลอดแล้วมีผล Hct ใกล้คลอด"]["status"] == "bad"


def test_section_query_failure_does_not_break_audit(monkeypatch, data):
    def boom(sql, args=None):
        raise RuntimeError("no table")
    monkeypatch.setattr(check, "fetch", boom)
    a = check.audit(D1, D2, CFG, None)
    assert _item(a, "dt_codes")["status"] == "warn" and "ตรวจไม่ได้" in _item(a, "dt_codes")["hint"]


# ---------- routes ----------

@pytest.fixture
def client(monkeypatch, tmp_path, data):
    m = tmp_path / "village_pcu.csv"
    m.write_text("tmbpart,tambon,moo,village,hospcode,pcu\n01,วังน้ำเขียว,1,บ้านก,03929,รพ.สต.ก\n", encoding="utf-8")
    monkeypatch.setenv("ANC_VILLAGE_CSV", str(m))
    monkeypatch.delenv("ANC_CHECK_OPEN", raising=False)
    monkeypatch.setattr(check, "fetch", Router({"from thaiaddress": [{"addressid": "302501", "name": "ไทยสามัคคี"}]}))
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_check_lan_only(client):
    assert client.get("/check", environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403
    r = client.get("/check", environ_base=LAN)
    assert r.status_code == 200 and "ยืนยันว่าตรวจแล้ว" in r.get_data(as_text=True)


def test_check_open_env(client, monkeypatch):
    monkeypatch.setenv("ANC_CHECK_OPEN", "1")
    assert client.get("/check", environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 200


def test_template_csv_is_village_pcu_format(client):
    """แม่แบบเป็นรูปแบบ village_pcu.csv ของ mental_health_dashboard (+ จำนวนครรภ์) เฉพาะหมู่ในอำเภอ ไม่มีข้อมูลรายคน"""
    r = client.get("/check/village_pcu_template.csv", environ_base=LAN)
    body = r.get_data(as_text=True)
    lines = body.splitlines()
    assert lines[0].lstrip("﻿") == "tmbpart,tambon,moo,village,hospcode,pcu,pregnancies"
    assert "01,ไทยสามัคคี,1,,03929,รพ.สต.ก,1" in lines            # ชื่อหมู่บ้านมาจากตาราง village ของ HOSxP
    assert not any(l.startswith("11,") for l in lines[1:])          # 11111111 อยู่นอกอำเภอ
    assert "HN-SECRET" not in body and r.mimetype == "text/csv"


def test_template_csv_lan_only(client):
    assert client.get("/check/village_pcu_template.csv", environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403


def test_audit_leap_day_start(monkeypatch, data):
    monkeypatch.setattr(check, "fetch", Router({}))
    check.audit(date(2028, 2, 29), date(2028, 3, 31), CFG, None)       # ต้องไม่ ValueError


def test_audit_reports_main_query_failure(monkeypatch, data):
    def boom(d1, d2, cfg):
        raise RuntimeError("Unknown column")
    monkeypatch.setattr(queries, "pregnancies", boom)
    monkeypatch.setattr(check, "fetch", Router({}))
    it = _item(check.audit(D1, D2, CFG, None), "main_query")
    assert it["status"] == "bad" and "RuntimeError" in it["hint"]
