import pytest

import app as appmod
import manage
import store


@pytest.fixture(autouse=True)
def tmp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "anc.sqlite"))
    monkeypatch.setattr(store, "_ready", False)


def test_passkey_command_creates_then_changes(monkeypatch):
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt="": "first-key-1")
    manage.main(["passkey"])
    u = store.check_login(appmod.PASSKEY_USER, "first-key-1")
    assert u and u["hospcode"] == "all" and not u["is_admin"]
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt="": "second-key-2")
    manage.main(["passkey"])
    assert store.check_login(appmod.PASSKEY_USER, "second-key-2")
    assert len([x for x in store.list_users() if x["username"] == appmod.PASSKEY_USER]) == 1
