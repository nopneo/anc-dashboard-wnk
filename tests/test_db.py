import subprocess

import db


class _Proc:
    returncode = 0
    stderr = b""

    def __init__(self, out):
        self.stdout = out


def test_ssh_sends_thai_sql_as_tis620_on_stdin(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        return _Proc("n\n3\n".encode("tis-620"))

    monkeypatch.setattr(db, "SSH_HOST", "h")
    monkeypatch.setattr(subprocess, "run", fake_run)
    rows = db._fetch_ssh("select count(*) n from t where x like %(k)s", {"k": "%แท้ง%"})
    assert rows == [{"n": "3"}]
    assert "แท้ง".encode("tis-620") in seen["input"]
    assert not any("แท้ง" in part for part in seen["cmd"])
