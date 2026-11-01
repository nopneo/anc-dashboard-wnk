from datetime import date

import pytest

import app as appmod
import queries

LMP = date(2025, 9, 1)


def _preg(i, age, village, labor=date(2026, 5, 1)):
    return {"anc_id": i, "hn": "HN-SECRET", "age": age, "village": village, "register_date": date(2026, 1, 10),
            "lmp": LMP, "labor_date": labor, "hct_late": 31.0 if i % 2 else 36.0, "has_dt": i % 2 == 0,
            "has_dental": True, "thai": i != 4, "labour_hospcode": "24060"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    m = tmp_path / "village_pcu.csv"
    m.write_text("tmbpart,tambon,moo,village,hospcode,pcu\n01,วังน้ำเขียว,1,ศาลเจ้าพ่อ,03929,รพ.สต.ทดสอบ\n",
                 encoding="utf-8")
    monkeypatch.setenv("ANC_VILLAGE_CSV", str(m))
    monkeypatch.delenv("ANC_DATA_AUDITED", raising=False)
    appmod._cache._data.clear()
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _patch(monkeypatch, pregs=(), visits=(), infants=(), waits=(), refers=()):
    monkeypatch.setattr(queries, "pregnancies", lambda d1, d2, cfg: list(pregs))
    monkeypatch.setattr(queries, "visits", lambda ids: list(visits))
    monkeypatch.setattr(queries, "infants", lambda d1, d2, *a: list(infants))
    monkeypatch.setattr(queries, "waits", lambda d1, d2, cfg: list(waits))
    monkeypatch.setattr(queries, "refers", lambda d1, d2: list(refers))
    monkeypatch.setattr(queries, "postnatal", lambda ids: [])


@pytest.fixture
def fake_data(monkeypatch):
    pregs = [_preg(i, a, v) for i, (a, v) in enumerate([(14, "30250101"), (25, "30250101"), (37, "99999999"),
                                                        (18, "30250101"), (30, None), (22, "30250101")], 1)]
    visits = [{"anc_id": 1, "date": date(2026, 1, 10), "ga": 10, "precare": False}]
    infants = [{"birth_date": date(2026, 5, 1), "weight": 2300, "alive": True, "village": "30250101"}]
    refers = [{"refer_id": 1, "date": date(2026, 3, 2), "hn": "HN-SECRET", "pdx": "O149", "dx_name": "Pre-eclampsia",
               "dest": "10666", "dest_name": "รพ.มหาราชนครราชสีมา", "age": 25, "village": "30250101",
               "minutes": 70}]
    _patch(monkeypatch, pregs, visits, infants, [25, 35], refers)


@pytest.fixture
def empty_data(monkeypatch):
    _patch(monkeypatch)


def _html(client, url="/?d1=2026-01-01&d2=2026-06-30", **kw):
    r = client.get(url, **kw)
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_dashboard_renders_sections(client, fake_data):
    html = _html(client)
    for title in ("ANC KPI Summary", "ตัวชี้วัดคุณภาพ", "กลุ่มอายุ", "แยกตาม รพ.สต.", "Refer รายเดือน",
                  "Top 10 Refer Diagnoses", "Refer Destinations", "สรุป Refer รายเดือน", "Alert &amp; Action"):
        assert title in html, title
    assert "รพ.สต.ทดสอบ" in html and "นอกเขตอำเภอ" in html and "รพ.มหาราชนครราชสีมา" in html and "O14" in html
    assert "43 แฟ้ม" not in html                     # แหล่งข้อมูลคือ HOSxP — แสดงชื่อตาราง HOSxP
    assert "HOSxP: person_anc_service.pa_week" in html and "HOSxP: ipt_labour_infant" in html
    assert ">มี.ค. 69</td>" in html             # เดือนในตาราง refer เป็นภาษาไทย


def test_dashboard_empty_range(client, empty_data):
    html = _html(client)
    assert "—" in html and "ANC KPI Summary" in html


def test_section_failure_isolated(client, fake_data, monkeypatch):
    def boom(d1, d2):
        raise TimeoutError("db slow")
    monkeypatch.setattr(queries, "refers", boom)
    html = _html(client)
    assert "ดึงข้อมูลไม่ได้" in html and "ANC KPI Summary" in html and "db slow" not in html


def test_no_patient_identifiers(client, fake_data):
    assert "HN-SECRET" not in _html(client)
    assert "HN-SECRET" not in client.get("/api/data.json?d1=2026-01-01&d2=2026-06-30").get_data(as_text=True)


def test_banner_shown_then_hidden_in_print_and_audited(client, fake_data, monkeypatch):
    assert "audit-bar" in _html(client)
    assert "audit-bar" not in _html(client, "/?d1=2026-01-01&d2=2026-06-30&print=1")
    monkeypatch.setenv("ANC_DATA_AUDITED", "1")
    appmod._cache._data.clear()
    assert "audit-bar" not in _html(client)


def test_prefix_middleware(client, fake_data):
    html = _html(client, headers={"X-Forwarded-Prefix": "/anc"})
    assert 'href="/anc/static/style.css' in html


def test_bad_date_falls_back(client, fake_data):
    html = _html(client, "/?d1=2026-13-40&d2=garbage")
    assert "ANC KPI Summary" in html


def test_range_capped(client, fake_data):
    d1, d2 = appmod._range_from("2020-01-01", "2026-06-30")
    assert (d2 - d1).days == appmod.MAX_DAYS - 1


def test_healthz_503_when_db_down(client, monkeypatch):
    def down(sql, args=None):
        raise ConnectionError("x")
    monkeypatch.setattr(appmod.db, "fetch", down)
    assert client.get("/healthz").status_code == 503
    monkeypatch.setattr(appmod.db, "fetch", lambda sql, args=None: [{"1": 1}])
    assert client.get("/healthz").status_code == 200


def test_pcu_section_shows_setup_hint_without_map(client, fake_data, monkeypatch, tmp_path):
    monkeypatch.setenv("ANC_VILLAGE_CSV", str(tmp_path / "missing.csv"))
    html = _html(client)
    assert "ยังไม่ได้ตั้งค่าการจับคู่หมู่บ้าน" in html


def test_bad_pcu_map_is_section_error(client, fake_data, monkeypatch, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("x,y\n", encoding="utf-8")
    monkeypatch.setenv("ANC_VILLAGE_CSV", str(bad))
    html = _html(client)
    assert "village_pcu.csv" in html and "ANC KPI Summary" in html


def test_export_disabled_returns_404(client, monkeypatch):
    monkeypatch.setattr(appmod, "EXPORT_ENABLED", False)
    assert client.get("/export.jpg").status_code == 404
    assert client.get("/export.exe").status_code == 404


def test_export_renders_print_url(client, monkeypatch):
    seen = {}

    def fake_render(fmt, url, out):
        seen["url"] = url
        open(out, "wb").write(b"JPEGDATA")
    monkeypatch.setattr(appmod.render, "render_to", fake_render)
    appmod._export_cache._data.clear()
    r = client.get("/export.jpg?d1=2026-01-01&d2=2026-01-31")
    assert r.status_code == 200 and r.data == b"JPEGDATA" and "print=1" in seen["url"]
    assert "anc_2026-01-01_2026-01-31.jpg" in r.headers["Content-Disposition"]


def test_refer_table_not_clipped_in_print(client, fake_data):
    """ไฟล์ส่งออก (?print=1) ต้องเห็นตาราง refer ครบ ไม่ใช่กรอบเลื่อน"""
    assert "scroll-y" in _html(client)
    assert "scroll-y" not in _html(client, "/?d1=2026-01-01&d2=2026-06-30&print=1")


# ---------- final review fixes ----------

def test_main_failure_shows_error_not_zeros(client, fake_data, monkeypatch):
    def boom(d1, d2, cfg):
        raise RuntimeError("Unknown column")
    monkeypatch.setattr(queries, "pregnancies", boom)
    html = _html(client)
    assert "setup_check.py" in html and "ANC KPI Summary" not in html and "Unknown column" not in html


def test_refer_failure_shows_dash_not_zero(client, fake_data, monkeypatch):
    def boom(d1, d2):
        raise TimeoutError()
    monkeypatch.setattr(queries, "refers", boom)
    html = _html(client)
    assert "ไม่มี refer ในช่วงนี้" not in html
    assert html.count("ดึงข้อมูลไม่ได้") >= 4          # ส่วน 6, 7, 8, 9
    assert '<div class="v">—</div><div class="u">ครั้ง</div>' in html


# ---------- DB_color redesign ----------

def test_thai_full_date():
    assert appmod.thai_full_date(date(2026, 10, 31)) == "วันเสาร์ที่ 31 ตุลาคม 2569"


def test_range_presets():
    p = appmod.range_presets(date(2026, 11, 15))
    assert [x["label"] for x in p] == ["เดือนนี้", "เดือนที่แล้ว", "ปีงบนี้", "ปีงบที่แล้ว"]
    assert (p[0]["d1"], p[0]["d2"]) == ("2026-11-01", "2026-11-15")
    assert (p[1]["d1"], p[1]["d2"]) == ("2026-10-01", "2026-10-31")
    assert (p[2]["d1"], p[3]["d1"], p[3]["d2"]) == ("2026-10-01", "2025-10-01", "2026-09-30")


def test_active_preset_pill(client, fake_data):
    html = _html(client)                                   # 2026-01-01..2026-06-30 ไม่ตรง preset ใด
    assert html.count('class="pill on"') == 1             # มีแค่ปุ่มตัวหาร
    p = appmod.range_presets(date.today())[2]
    html = _html(client, f"/?d1={p['d1']}&d2={p['d2']}")
    assert html.count('class="pill on"') == 2
    assert f'class="pill on" href="?d1={p["d1"]}&amp;d2={p["d2"]}&amp;scope=area">ปีงบนี้</a>' in html


def test_quick_menu_hidden_in_print(client, fake_data):
    assert "เมนูด่วน" in _html(client)
    assert "เมนูด่วน" not in _html(client, "/?d1=2026-01-01&d2=2026-06-30&print=1")


# ---------- KPI จากโฟลเดอร์ kpi ----------

def test_indicator_table_has_kpis_not_service_counts(client, fake_data):
    html = _html(client)
    table = html[html.index("ตัวชี้วัดคุณภาพ"):html.index("Refer Destinations")]
    for label in ("ดูแลหลังคลอดครบ 3 ครั้ง", "ฝากครรภ์คุณภาพ", "ยาเม็ดไอโอดีน", "คัดกรองดาวน์", "อัลตราซาวด์"):
        assert label in table, label
    for label in ("ฝากครรภ์รายใหม่รวม", "ครั้งบริการ ANC รวม", "เฉลี่ยครั้ง/เดือน"):
        assert label not in table, label            # ย้ายไปเป็นข้อมูลบริการ (การ์ดด้านบน)
    assert "ครั้งบริการ ANC" in html               # ยังอยู่บนการ์ด


def test_postnatal_rows_reach_metrics(client, fake_data, monkeypatch):
    seen = {}

    def pnc(ids):
        seen["ids"] = sorted(ids)
        return []
    monkeypatch.setattr(queries, "postnatal", pnc)
    _html(client)
    assert seen["ids"] == [1, 2, 3, 4, 5, 6]


def test_section_order(client, fake_data):
    """Top 10 Dx ต่อใต้ Refer Destinations (คอลัมน์ขวาของตัวชี้วัด) · Refer รายเดือนก่อนแยกตาม รพ.สต.
    · Alert & Action อยู่ท้ายสุด (ก่อนเมนูด่วน)"""
    html = _html(client)
    pos = lambda t: html.index(t)
    assert pos("<h3>ตัวชี้วัดคุณภาพ") < pos("<h3>Refer Destinations") < pos("<h3>Top 10 Refer Diagnoses")         < pos("<h3>Refer รายเดือน") < pos("<h3>แยกตาม รพ.สต.")
    assert pos("<h3>สรุป Refer รายเดือน") < pos("<h3>Alert &amp; Action") < pos("เมนูด่วน")


# ---------- ตัวหารในเขต ----------

def test_scope_default_is_area_with_toggle(client, fake_data):
    html = _html(client)
    assert "ตัวหาร:" in html and 'class="pill on" href="?d1=2026-01-01&amp;d2=2026-06-30&amp;scope=area"' in html
    assert 'href="?d1=2026-01-01&amp;d2=2026-06-30&amp;scope=all"' in html
    assert "ตัวหารในเขต" in html


def test_scope_all_changes_denominator(client, fake_data, monkeypatch):
    import json
    get = lambda q: json.loads(client.get("/api/data.json?d1=2026-01-01&d2=2026-06-30" + q).get_data(as_text=True))
    area, all_ = get(""), get("&scope=all")
    assert area["scope"] == "area" and all_["scope"] == "all"
    # fake_data: 6 ครรภ์คลอด · ไม่ใช่ไทย/นอกอำเภอบางราย → ตัวหารในเขตน้อยกว่า
    assert area["ind"]["dt"]["den"] < all_["ind"]["dt"]["den"] == 6
    assert area["ind"]["new"]["value"] == all_["ind"]["new"]["value"]


def test_labor_warning_on_dashboard(client, fake_data):
    html = _html(client)
    assert "บันทึกวันคลอด" in html
