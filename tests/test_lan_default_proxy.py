"""หน้ารายชื่อเฉพาะใน รพ. เป็นค่าเริ่มต้น · header จาก proxy เชื่อเฉพาะเครื่องเดียวกัน · ช่วง IP ภายในระบุเอง"""
import pytest

import app as app_mod

CF = {"X-Forwarded-For": "1.2.3.4, 162.158.1.1", "CF-Connecting-IP": "1.2.3.4"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_mod.app, "secret_key", "test-secret")
    monkeypatch.delenv("ANC_LIST_LAN_ONLY", raising=False)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_list_lan_only_by_default(client):
    assert client.get("/login", headers=CF, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 403
    assert client.get("/list", headers=CF, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 403
    lan = client.get("/login", headers={"X-Forwarded-For": "192.168.11.9"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert lan.status_code == 200


def test_list_lan_only_opt_out(client, monkeypatch):
    monkeypatch.setenv("ANC_LIST_LAN_ONLY", "0")
    assert client.get("/login", headers=CF, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 200


@pytest.mark.parametrize("ip, lan", [
    ("192.168.11.5", True), ("10.1.2.3", True), ("172.20.0.1", True), ("127.0.0.1", True),
    ("198.18.0.1", False), ("203.0.113.7", False), ("100.64.1.1", False), ("8.8.8.8", False),
    ("::ffff:192.168.1.1", True), ("::ffff:8.8.8.8", False)])
def test_from_lan_explicit_ranges(ip, lan):
    with app_mod.app.test_request_context("/", environ_base={"REMOTE_ADDR": ip}):
        assert app_mod._from_lan() is lan


def test_prefix_only_from_trusted_proxy(client):
    html = client.get("/login", headers={"X-Forwarded-Prefix": "/evil"},
                      environ_base={"REMOTE_ADDR": "192.168.1.5"}).get_data(as_text=True)
    assert "/evil/" not in html
    html = client.get("/login", headers={"X-Forwarded-Prefix": "/anc"},
                      environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_data(as_text=True)
    assert "/anc/" in html
