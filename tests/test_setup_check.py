from datetime import date, datetime

import setup_check

TABLES = setup_check.TABLES


def fake(over=None, tables=None):
    routes = {
        "version()": [{"v": "10.5.22-MariaDB", "n": datetime.now().isoformat(sep=" "), "d": "hos"}],
        "show grants": [{"g": "GRANT SELECT ON `hos`.* TO `ro`@`%`"}],
        "information_schema.tables": [{"t": t} for t in (TABLES if tables is None else tables)],
        "from anc_lab": [{"name": "Hct ครั้งที่ 1"}],
        "max(anc_service_date)": [{"d": date.today().isoformat()}],
    }
    routes.update(over or {})

    def fetch(sql, args=None):
        flat = " ".join(sql.split())
        for k, rows in routes.items():
            if k in flat:
                return rows
        return []
    return fetch


def statuses(rows):
    return [s for s, _, _ in rows]


def test_all_good_has_no_bad():
    rows = setup_check.run(fetch=fake(), audit=False)
    assert "bad" not in statuses(rows), [r for r in rows if r[0] == "bad"]
    assert any("SELECT" in d or "อ่านอย่างเดียว" in t for _, t, d in rows)


def test_write_grant_is_bad():
    rows = setup_check.run(fetch=fake({"show grants": [{"g": "GRANT SELECT, INSERT ON `hos`.* TO x"}]}), audit=False)
    bad = [r for r in rows if r[0] == "bad"]
    assert bad and "INSERT" in bad[0][2]


def test_grant_on_other_db_ignored():
    rows = setup_check.run(fetch=fake({"show grants": [{"g": "GRANT SELECT ON `hos`.* TO x"},
                                                        {"g": "GRANT ALL PRIVILEGES ON `other_db`.* TO x"}]}),
                           audit=False)
    assert "bad" not in statuses(rows)


def test_missing_table_is_bad():
    rows = setup_check.run(fetch=fake(tables=[t for t in TABLES if t != "person_anc"]), audit=False)
    assert any(s == "bad" and "person_anc" in d for s, _, d in rows)


def test_db_down_is_bad_and_stops():
    def down(sql, args=None):
        raise ConnectionError("refused")
    rows = setup_check.run(fetch=down, audit=False)
    assert rows[-1][0] == "bad" and "ต่อฐานข้อมูลไม่ได้" in rows[-1][1]


def test_stale_visits_warn():
    rows = setup_check.run(fetch=fake({"max(anc_service_date)": [{"d": "2025-01-01"}]}), audit=False)
    assert any(s == "warn" and "ANC ล่าสุด" in t for s, t, _ in rows)


def test_pcu_map_states(tmp_path, monkeypatch):
    monkeypatch.setenv("ANC_PCU_MAP", str(tmp_path / "none.csv"))
    rows = setup_check.run(fetch=fake(), audit=False)
    assert any(s == "warn" and "pcu_map" in t for s, t, _ in rows)
    bad = tmp_path / "bad.csv"
    bad.write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("ANC_PCU_MAP", str(bad))
    rows = setup_check.run(fetch=fake(), audit=False)
    assert any(s == "bad" and "pcu_map" in t for s, t, _ in rows)


def test_exit_code_1_on_bad(monkeypatch):
    monkeypatch.setattr(setup_check, "run", lambda **kw: [("ok", "a", ""), ("bad", "b", "c")])
    monkeypatch.setattr("sys.argv", ["setup_check.py", "--no-audit"])
    assert setup_check.main() == 1
    monkeypatch.setattr(setup_check, "run", lambda **kw: [("ok", "a", ""), ("warn", "b", "c")])
    assert setup_check.main() == 0


def test_audit_findings_are_warnings_not_failures(monkeypatch):
    """ปัญหาข้อมูล (Data Audit) เป็น ⚠ ให้ไปดูหน้า /check · ✘ ใช้กับสภาพแวดล้อม/การเชื่อมต่อเท่านั้น
    และข้อ pcu_map ไม่ซ้ำกับข้อไฟล์ pcu_map.csv ด้านบน"""
    import check
    monkeypatch.setattr(check, "audit", lambda d1, d2, cfg, m: {
        "items": [{"key": "pcu_map", "title": "จับคู่", "status": "bad", "hint": "x"},
                  {"key": "dt_codes", "title": "dT", "status": "bad", "hint": "y"}],
        "completeness": [{"title": "Hct", "pct": 5.0, "n": 1, "den": 20, "status": "bad"}], "n_pregs": 1})
    rows = setup_check.run(fetch=fake(), audit=True)
    audit = [r for r in rows if r[1].startswith(("Data Audit", "ความครบ"))]
    assert [r[0] for r in audit] == ["warn", "warn"] and not any("จับคู่" in r[1] for r in audit)
