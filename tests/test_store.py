import pytest

import store


@pytest.fixture(autouse=True)
def tmp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "anc.sqlite"))
    monkeypatch.setattr(store, "_ready", False)


def test_add_user_and_check_login_uses_pbkdf2():
    store.add_user("nurse1", "secret-pass", "พยาบาล 1", "03929")
    u = store.check_login("nurse1", "secret-pass")
    assert u["display"] == "พยาบาล 1" and u["hospcode"] == "03929"
    assert u["pw_hash"].startswith("pbkdf2:sha256")
    assert store.check_login("nurse1", "wrong") is None
    assert store.get_user(u["id"])["username"] == "nurse1"


def test_disabled_user_cannot_login_or_keep_session():
    store.add_user("nurse1", "secret-pass", "พยาบาล 1")
    uid = store.check_login("nurse1", "secret-pass")["id"]
    assert store.set_active("nurse1", False) == 1
    assert store.check_login("nurse1", "secret-pass") is None
    assert store.get_user(uid) is None


def test_set_password():
    store.add_user("nurse1", "secret-pass", "พยาบาล 1")
    store.set_password("nurse1", "new-pass-123")
    assert store.check_login("nurse1", "new-pass-123")


def test_audit_log_and_recent_failures():
    store.log("nurse1", "login_fail", ip="10.0.0.1")
    store.log("nurse1", "login_fail", ip="10.0.0.2")
    store.log("nurse1", "view_list", detail="k=early12")
    assert store.recent_failures("nurse1", "10.0.0.1", 15) == (2, 1)
    rows = store.audit(username="nurse1")
    assert [r["action"] for r in rows] == ["view_list", "login_fail", "login_fail"]
