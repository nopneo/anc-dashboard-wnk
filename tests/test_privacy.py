"""หน้าสาธารณะ (คนนอก รพ. ไม่ได้ login) ต้องไม่ให้ย้อนหาผลตรวจ/อายุของคนคนเดียวจากตัวเลขรวม"""

import json
from datetime import date

import pytest

import app as appmod
import privacy
import queries
from test_app import _patch, client  # noqa: F401  (fixture)

PUBLIC = {"REMOTE_ADDR": "8.8.8.8"}
LAN = {"REMOTE_ADDR": "192.168.1.5"}


def _p(i, reg, age=25, thai=True):
    return {"anc_id": i, "hn": f"HN{i}", "age": age, "village": "30250101", "register_date": reg,
            "lmp": date(2025, 11, 1), "labor_date": None, "thai": thai, "labour_hospcode": "24060"}


@pytest.fixture
def one_case(monkeypatch):
    """4 รายใหม่ใน ก.พ. 2569 · รายที่ 7 (ต่างชาติ อายุ 14) มาวันที่ 3 และผล HIV บวก"""
    pregs = [_p(5, date(2026, 2, 1)), _p(6, date(2026, 2, 2)), _p(7, date(2026, 2, 3), age=14, thai=False),
             _p(8, date(2026, 2, 4))]

    def by_range(d1, d2, cfg):
        return [p for p in pregs if d1 <= p["register_date"] <= d2]
    _patch(monkeypatch, sti={5: {"hiv": ("neg", "")}, 6: {"hiv": ("neg", "")}, 7: {"hiv": ("pos", "")},
                             8: {"hiv": ("neg", "")}})
    monkeypatch.setattr(queries, "pregnancies", by_range)


def _json(client, qs, env):
    r = client.get("/api/data.json?" + qs, environ_base=env)
    assert r.status_code == 200
    return json.loads(r.get_data(as_text=True))


def _hiv(d):
    return next(t for t in d["sti"] if t["key"] == "hiv")


def test_lan_sees_exact_single_day(client, one_case):
    d = _json(client, "d1=2026-02-03&d2=2026-02-03&scope=all", LAN)
    assert d["d1"] == d["d2"] == "2026-02-03"
    assert _hiv(d)["pos"]["num"] == 1 and d["age"]["teen"]["lt15"] == 1
    assert "public_privacy" not in d


def test_public_window_snapped_to_whole_month(client, one_case):
    d = _json(client, "d1=2026-02-03&d2=2026-02-03&scope=all", PUBLIC)
    assert (d["d1"], d["d2"]) == ("2026-02-01", "2026-02-28")
    # วันเดียว / ช่วงซ้อนกัน ได้ผลเดียวกันทุกครั้ง → ลบกันไม่ได้
    assert _json(client, "d1=2026-02-01&d2=2026-02-02&scope=all", PUBLIC)["d1"] == "2026-02-01"
    assert _json(client, "d1=2026-02-01&d2=2026-02-02&scope=all", PUBLIC)["d2"] == "2026-02-28"


def test_public_suppresses_small_sensitive_cells(client, one_case):
    d = _json(client, "d1=2026-02-03&d2=2026-02-03&scope=all&nat=fr", PUBLIC)
    hiv = _hiv(d)
    assert hiv["pos"]["num"] == privacy.HIDDEN and hiv["pos"]["value"] is None       # ตรวจ 1 ราย → ซ่อนทั้งช่อง
    assert d["age"]["teen"]["lt15"] == "<5"
    assert d["age"]["teen"]["15_19"] is None                    # teen.new − 15_19 = lt15 → ต้องซ่อนด้วย
    assert all("ต่ำกว่า 15 ปี 1 ราย" not in a["text"] for a in d["alerts"])
    assert any("ต่ำกว่า 15 ปี <5 ราย" in a["text"] for a in d["alerts"])
    whole = _json(client, "scope=all", PUBLIC)
    assert _hiv(whole)["pos"]["num"] in ("<5", privacy.HIDDEN, 0)


def test_public_cache_not_polluted(client, one_case):
    """ctx ใน cache ใช้ร่วมกับเครื่องใน รพ. — หน้าสาธารณะต้องไม่ไปแก้ตัวเลขของ LAN"""
    _json(client, "d1=2026-02-01&d2=2026-02-28&scope=all", PUBLIC)
    d = _json(client, "d1=2026-02-01&d2=2026-02-28&scope=all", LAN)
    assert _hiv(d)["pos"]["num"] == 1 and d["age"]["teen"]["lt15"] == 1


def test_public_html_notice_and_no_exact_count(client, one_case):
    html = client.get("/?d1=2026-02-03&d2=2026-02-03&scope=all", environ_base=PUBLIC).get_data(as_text=True)
    assert "ข้อมูลสาธารณะ" in html and "&lt;5" in html
    assert "ต่ำกว่า 15 ปี 1 ราย" not in html
    lan = client.get("/?d1=2026-02-03&d2=2026-02-03&scope=all", environ_base=LAN).get_data(as_text=True)
    assert "ข้อมูลสาธารณะ" not in lan


def test_public_flag_forces_public_even_from_loopback(client, one_case):
    d = _json(client, "d1=2026-02-03&d2=2026-02-03&scope=all&public=1", {"REMOTE_ADDR": "127.0.0.1"})
    assert d["d1"] == "2026-02-01" and d["age"]["teen"]["lt15"] == "<5"


def test_export_passes_public_and_separate_cache(client, one_case, monkeypatch):
    seen = []

    def fake_render(fmt, url, out):
        seen.append(url)
        open(out, "wb").write(b"x")
    monkeypatch.setattr(appmod.render, "render_to", fake_render)
    monkeypatch.setattr(appmod, "EXPORT_ENABLED", True)
    appmod._export_cache._data.clear()
    assert client.get("/export.png?d1=2026-02-03&d2=2026-02-03", environ_base=LAN).status_code == 200
    assert client.get("/export.png?d1=2026-02-01&d2=2026-02-28", environ_base=PUBLIC).status_code == 200
    assert "public=1" not in seen[0] and "d1=2026-02-03" in seen[0]
    assert "public=1" in seen[1] and "d1=2026-02-01" in seen[1] and "d2=2026-02-28" in seen[1]
    # LAN ขอช่วงเดียวกับที่คนนอกได้ → ต้องเรนเดอร์ใหม่ ไม่ใช้ไฟล์ฉบับสาธารณะ (และกลับกัน)
    assert client.get("/export.png?d1=2026-02-01&d2=2026-02-28", environ_base=LAN).status_code == 200
    assert len(seen) == 3 and "public=1" not in seen[2]


def test_logged_in_user_sees_exact(client, one_case, monkeypatch, tmp_path):
    import store
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "anc.sqlite"))
    monkeypatch.setattr(store, "_ready", False, raising=False)
    monkeypatch.setattr(appmod.app, "secret_key", "test-secret-key-for-privacy")
    store.add_user("nurse1", "password-123", "พยาบาล")
    uid = store.check_login("nurse1", "password-123")["id"]
    with client.session_transaction(environ_base=PUBLIC) as s:
        s["uid"] = uid
    d = _json(client, "d1=2026-02-03&d2=2026-02-03&scope=all", PUBLIC)
    assert d["d1"] == "2026-02-03" and d["age"]["teen"]["lt15"] == 1


def test_month_window_clamps_to_today():
    assert privacy.month_window(date(2026, 2, 3), date(2026, 2, 3), today=date(2026, 2, 10)) == \
        (date(2026, 2, 1), date(2026, 2, 10))
    assert privacy.month_window(date(2025, 10, 15), date(2026, 1, 9), today=date(2026, 6, 1)) == \
        (date(2025, 10, 1), date(2026, 1, 31))


def test_disabled_with_zero(monkeypatch, client, one_case):
    monkeypatch.setattr(privacy, "MIN_CELL", 0)
    d = _json(client, "d1=2026-02-03&d2=2026-02-03&scope=all", PUBLIC)
    assert d["d1"] == "2026-02-03" and _hiv(d)["pos"]["num"] == 1
