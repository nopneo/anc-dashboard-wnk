from io import BytesIO

import pytest
from openpyxl import load_workbook

import app as appmod
import queries
import store
from test_app import _patch, _preg
from test_list_auth import _csrf, login

Q = "d1=2026-01-01&d2=2026-06-30&scope=all"


@pytest.fixture
def client(monkeypatch, tmp_path):
    m = tmp_path / "village_pcu.csv"
    m.write_text("tmbpart,tambon,moo,village,hospcode,pcu\n01,วังน้ำเขียว,1,ศาลเจ้าพ่อ,03929,รพ.สต.ทดสอบ\n",
                 encoding="utf-8")
    monkeypatch.setenv("ANC_VILLAGE_CSV", str(m))
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "anc.sqlite"))
    monkeypatch.setattr(store, "_ready", False)
    monkeypatch.setattr(appmod.app, "secret_key", "test-secret")
    monkeypatch.delenv("ANC_LIST_LAN_ONLY", raising=False)
    appmod._cache._data.clear()
    appmod._raw._data.clear()
    appmod.app.config["TESTING"] = True
    store.add_user("nurse1", "secret-pass", "พยาบาล 1")
    store.add_user("pcu1", "secret-pass", "รพ.สต. 1", "03929")
    pregs = [dict(_preg(i, a, v), hn=f"HN{i}")
             for i, (a, v) in enumerate([(14, "30250101"), (25, "30250101"), (37, "99999999"),
                                          (18, "30250101"), (30, None), (22, "30250101")], 1)]
    visits = [{"anc_id": 1, "date": pregs[0]["lmp"].replace(month=10, day=20), "ga": 7, "precare": False}]
    _patch(monkeypatch, pregs, visits)
    monkeypatch.setattr(queries, "names", lambda hns: {h: {"name": f"นางทดสอบ {h}", "addr": "1 ม.1"} for h in hns})
    return appmod.app.test_client()


def page(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.status_code
    return r.get_data(as_text=True)


def test_list_shows_whole_denominator_with_names(client):
    login(client)
    html = page(client, f"/list?k=early12&{Q}")
    assert html.count('class="row"') == 6                 # ตัวหาร = ครรภ์ที่คลอดในช่วงทั้ง 6
    assert "นางทดสอบ HN1" in html and "HN6" in html
    assert "ฝากครรภ์ครั้งแรก ≤ 12 สัปดาห์" in html
    a = store.audit()[0]
    assert a["action"] == "view_list" and "k=early12" in a["detail"] and "n=6" in a["detail"]
    assert client.get(f"/list?k=early12&{Q}").headers["Cache-Control"] == "no-store"


def test_only_filter_and_search(client):
    login(client)
    assert page(client, f"/list?k=early12&only=in&{Q}").count('class="row"') == 1
    assert page(client, f"/list?k=early12&only=out&{Q}").count('class="row"') == 5
    assert page(client, f"/list?k=early12&q=HN2&{Q}").count('class="row"') == 1


def test_pcu_user_sees_only_own_area(client):
    login(client, "pcu1")
    html = page(client, f"/list?k=new&{Q}&pcu=out")       # ขอเขตอื่นก็ได้เฉพาะเขตตัวเอง
    assert html.count('class="row"') == 4 and "HN3" not in html


def test_unknown_key_is_404(client):
    login(client)
    assert client.get(f"/list?k=bogus&{Q}").status_code == 404


def test_visit_lists_show_missing_ga_ranges(client):
    login(client)
    assert "ช่วงที่ยังขาด" in page(client, f"/list?k=visit5&{Q}")
    assert "ช่วงที่ยังขาด" not in page(client, f"/list?k=dt&{Q}")


def test_excel_export_matches_list_and_is_audited(client):
    login(client)
    r = client.get(f"/list/export.xlsx?k=early12&only=out&{Q}")
    assert r.status_code == 200 and r.mimetype.endswith("spreadsheetml.sheet")
    assert r.headers["Cache-Control"] == "no-store"
    ws = load_workbook(BytesIO(r.data)).worksheets[0]
    rows = list(ws.values)
    assert rows[0][0] == "ชื่อ-สกุล" and len(rows) == 1 + 5
    assert store.audit()[0]["action"] == "export_list"


def test_excel_by_pcu_has_sheet_per_unit(client):
    login(client)
    r = client.get(f"/list/export.xlsx?k=new&by_pcu=1&{Q}")
    names = load_workbook(BytesIO(r.data)).sheetnames
    assert names[0] == "รวม" and "รพ.สต.ทดสอบ" in names and "นอกเขตอำเภอ" in names


def test_export_requires_login(client):
    assert client.get(f"/list/export.xlsx?k=new&{Q}").status_code == 302


def test_dashboard_numbers_link_to_list_but_not_in_print_mode(client):
    html = page(client, f"/?{Q}")
    assert 'href="/list?k=early12&amp;d1=2026-01-01' in html
    assert "/list?" not in page(client, f"/?{Q}&print=1")
    assert "นางทดสอบ" not in html                          # ชื่อไม่มีบนแดชบอร์ด


def test_no_links_when_list_disabled(client, monkeypatch):
    monkeypatch.setattr(appmod.app, "secret_key", None)
    assert "/list?" not in page(client, f"/?{Q}")


def test_logout_button_shown_on_list(client):
    login(client)
    html = page(client, f"/list?k=new&{Q}")
    assert "พยาบาล 1" in html and 'action="/logout"' in html and _csrf(client) in html


def test_sti_list_shows_result_column(client, monkeypatch):
    monkeypatch.setattr(queries, "sti_results", lambda d1, d2, cfg: {1: {"syphilis": ("pos", "Reactive 1:8")},
                                                                    2: {"syphilis": ("neg", "Non Reactive")}})
    appmod._raw._data.clear()
    login(client)
    html = page(client, f"/list?k=sti_syphilis_pos&{Q}")
    assert html.count('class="row"') == 2 and "ผลตรวจ" in html and "Reactive 1:8" in html


def test_teen_repeat_list_shows_gravida(client, monkeypatch):
    pregs = [dict(_preg(1, 17, "30250101"), hn="HN1", age_labor=18, gravida=2),
             dict(_preg(2, 25, "30250101"), hn="HN2", age_labor=25, gravida=1)]
    monkeypatch.setattr(queries, "pregnancies", lambda d1, d2, cfg: pregs)
    appmod._raw._data.clear()
    login(client)
    html = page(client, f"/list?k=teen_repeat&{Q}")
    assert html.count('class="row"') == 1 and "ครรภ์ที่" in html and "อายุ ณ วันสิ้นสุดครรภ์" in html


def test_labor_card_after_refer_links_to_missing_list(client, monkeypatch):
    pregs = [dict(_preg(1, 25, "30250101", labor=None), hn="HN1"), dict(_preg(2, 25, "30250101"), hn="HN2")]
    monkeypatch.setattr(queries, "pregnancies", lambda d1, d2, cfg: pregs)
    appmod._raw._data.clear()
    html = page(client, f"/?{Q}")
    i = html.index('class="kpis"')
    kpis = html[i:html.index("</section>", i)]
    assert kpis.index("ส่งต่อ (Refer)") < kpis.index("บันทึกวันคลอด")
    assert "k=labor_due" in kpis and "only=out" in kpis
    banner = html[html.index("บันทึกวันคลอดในทะเบียน") - 300:html.index("บันทึกวันคลอดในทะเบียน") + 600]
    assert "k=labor_due" in banner


def test_labor_due_list_shows_ga_column(client, monkeypatch):
    from datetime import date
    pregs = [dict(_preg(1, 25, "30250101", labor=None), hn="HN1", lmp=date(2025, 3, 1)),
             dict(_preg(2, 25, "30250101"), hn="HN2", lmp=date(2025, 3, 1))]
    monkeypatch.setattr(queries, "pregnancies", lambda d1, d2, cfg: pregs)
    appmod._raw._data.clear()
    login(client)
    html = page(client, f"/list?k=labor_due&only=out&{Q}")
    assert html.count('class="row"') == 1 and "HN1" in html and "GA ณ วันสิ้นสุดช่วง" in html


def test_hct_list_shows_trail_and_change(client, monkeypatch):
    from datetime import date
    monkeypatch.setattr(queries, "hct_series", lambda d1, d2, cfg: {
        1: [{"date": date(2025, 11, 1), "ga": 9, "hct": 29.0}, {"date": date(2026, 3, 1), "ga": 26, "hct": 34.0}]})
    appmod._raw._data.clear()
    login(client)
    html = page(client, f"/list?k=hct_recovered&{Q}")
    assert html.count('class="row"') == 1 and "29.0 (9) → 34.0 (26)" in html and "+5.0" in html


def test_amph_positive_list_shows_result(client, monkeypatch):
    monkeypatch.setattr(queries, "sti_results", lambda d1, d2, cfg: {
        1: {"amph": ("pos", "Positive")}, 2: {"amph": ("neg", "Negative")}})
    appmod._raw._data.clear()
    login(client)
    html = page(client, f"/list?k=sti_amph_pos&{Q}")
    assert html.count('class="row"') == 2 and "ผลตรวจ ปัสสาวะ Amphetamine" in html and "Positive" in html
    html = page(client, f"/list?k=sti_amph_test&only=out&{Q}")
    assert html.count('class="row"') == 4                          # 6 รายใหม่ ตรวจแล้ว 2 · ยังไม่ตรวจ 4
