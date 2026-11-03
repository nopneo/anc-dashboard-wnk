"""ฐานข้อมูลของแอปเอง (SQLite) — บัญชีผู้ใช้หน้ารายชื่อ และบันทึกการเข้าดู (audit log)

ไม่เขียนอะไรลง HOSxP · ไฟล์อยู่ที่ ANC_DATA_DIR (default: ./data/anc.sqlite) — แบบเดียวกับ mental_health_dashboard
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

_HERE = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv     # store อาจถูก import ก่อน db — โหลด .env เองให้ ANC_DATA_DIR มีผล

    load_dotenv(os.path.join(_HERE, ".env"))
except ImportError:
    pass

DATA_DIR = os.getenv("ANC_DATA_DIR") or os.path.join(_HERE, "data")
DB_PATH = os.path.join(DATA_DIR, "anc.sqlite")

_init_lock = threading.Lock()
_ready = False

SCHEMA = """
create table if not exists users (
  id integer primary key,
  username text unique not null,
  pw_hash text not null,
  display text not null,
  hospcode text not null default 'all',   -- 'all' = เห็นทุก รพ.สต. · ไม่งั้นรหัส รพ.สต.
  is_admin integer not null default 0,
  active integer not null default 1,
  created_at text not null
);
create table if not exists audit_log (
  id integer primary key,
  at text not null,
  username text not null,
  action text not null,          -- view_list / export_list / login / login_fail / logout
  detail text,
  ip text
);
create index if not exists ix_audit_at on audit_log(at);
"""


@contextmanager
def conn():
    global _ready
    if not _ready:
        with _init_lock:
            if not _ready:
                os.makedirs(DATA_DIR, exist_ok=True)
                c = sqlite3.connect(DB_PATH)
                c.executescript(SCHEMA)
                c.close()
                _ready = True
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- users

def add_user(username, password, display, hospcode="all", is_admin=False):
    # pbkdf2:sha256 — scrypt ค่า default verify ไม่ผ่านบน AlmaLinux/OpenSSL ของเซิร์ฟเวอร์ รพ.
    with conn() as c:
        c.execute("insert into users(username, pw_hash, display, hospcode, is_admin, created_at) "
                  "values (?, ?, ?, ?, ?, ?)",
                  (username, generate_password_hash(password, method="pbkdf2:sha256"),
                   display, hospcode, int(is_admin), _now()))


def set_password(username, password):
    with conn() as c:
        return c.execute("update users set pw_hash = ? where username = ?",
                         (generate_password_hash(password, method="pbkdf2:sha256"), username)).rowcount


def set_active(username, active):
    with conn() as c:
        return c.execute("update users set active = ? where username = ?", (int(active), username)).rowcount


def check_login(username, password):
    with conn() as c:
        u = c.execute("select * from users where username = ? and active = 1", (username,)).fetchone()
    if u and check_password_hash(u["pw_hash"], password):
        return dict(u)
    return None


def get_user(user_id):
    with conn() as c:
        u = c.execute("select * from users where id = ? and active = 1", (user_id,)).fetchone()
    return dict(u) if u else None


def list_users():
    with conn() as c:
        return [dict(r) for r in c.execute("select id, username, display, hospcode, is_admin, active "
                                           "from users order by username")]


# ---------------------------------------------------------------- audit log (PDPA: ใครเปิดดูรายชื่อไหน เมื่อไร)

def log(username, action, detail=None, ip=None):
    with conn() as c:
        c.execute("insert into audit_log(at, username, action, detail, ip) values (?, ?, ?, ?, ?)",
                  (_now(), username or "", action, (detail or "")[:200] or None, ip))


def audit(username=None, limit=100):
    sql, args = "select * from audit_log where 1 = 1", []
    if username:
        sql += " and username = ?"
        args.append(username)
    with conn() as c:
        return [dict(r) for r in c.execute(sql + " order by id desc limit ?", (*args, limit))]


def recent_failures(username, ip, minutes):
    """จำนวนครั้งที่ login ผิดใน N นาทีล่าสุด (ตามชื่อผู้ใช้, ตาม IP) — เก็บใน SQLite เพราะ gunicorn มีหลาย worker"""
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with conn() as c:
        q = "select count(*) from audit_log where action = 'login_fail' and at >= ? and {} = ?"
        by_user = c.execute(q.format("username"), (since, username)).fetchone()[0]
        by_ip = c.execute(q.format("ip"), (since, ip)).fetchone()[0] if ip else 0
    return by_user, by_ip
