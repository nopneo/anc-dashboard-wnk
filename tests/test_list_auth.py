import re

import pytest

import app as appmod
import store


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "anc.sqlite"))
    monkeypatch.setattr(store, "_ready", False)
    monkeypatch.setattr(appmod.app, "secret_key", "test-secret")
    monkeypatch.delenv("ANC_LIST_LAN_ONLY", raising=False)
    appmod.app.config["TESTING"] = True
    store.add_user("nurse1", "secret-pass", "พยาบาล 1")
    return appmod.app.test_client()


def _csrf(client):
    html = client.get("/login").get_data(as_text=True)
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def login(client, username="nurse1", password="secret-pass", next_=None):
    url = "/login" + (f"?next={next_}" if next_ else "")
    return client.post(url, data={"csrf": _csrf(client), "username": username, "password": password})


def test_list_requires_login(client):
    r = client.get("/list?k=early12")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_success_redirects_to_next_and_is_audited(client):
    r = login(client, next_="/list%3Fk%3Dearly12")
    assert r.status_code == 302 and r.headers["Location"].endswith("/list?k=early12")
    assert [a["action"] for a in store.audit()] == ["login"]


def test_login_rejects_offsite_next(client):
    r = login(client, next_="//evil.example/x")
    assert r.status_code == 302 and "evil" not in r.headers["Location"]


def test_wrong_password_is_logged_and_rate_limited(client):
    for _ in range(appmod.LOGIN_MAX_USER):
        r = login(client, password="bad")
        assert r.status_code == 200 and "ไม่ถูกต้อง" in r.get_data(as_text=True)
    r = login(client)                 # รหัสถูกก็ยังถูกล็อกชั่วคราว
    assert r.status_code == 429


def test_login_without_csrf_is_rejected(client):
    r = client.post("/login", data={"username": "nurse1", "password": "secret-pass"})
    assert r.status_code == 400


def test_logout(client):
    login(client)
    r = client.post("/logout", data={"csrf": _csrf(client)})
    assert r.status_code == 302
    assert client.get("/list?k=new").status_code == 302


def test_list_disabled_without_secret_key(client, monkeypatch):
    monkeypatch.setattr(appmod.app, "secret_key", None)
    assert client.get("/login").status_code == 404
    assert client.get("/list?k=new").status_code == 404


def test_lan_only_option_blocks_outside(client, monkeypatch):
    monkeypatch.setenv("ANC_LIST_LAN_ONLY", "1")
    r = client.get("/login", environ_base={"REMOTE_ADDR": "8.8.8.8"})
    assert r.status_code == 403
    assert client.get("/login", environ_base={"REMOTE_ADDR": "192.168.1.5"}).status_code == 200
