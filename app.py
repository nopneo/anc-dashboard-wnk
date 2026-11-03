"""ANC Dashboard — แดชบอร์ดงานฝากครรภ์ (HOSxP · นิยามตาม 43 แฟ้ม)

รันเอง:      python app.py            → http://127.0.0.1:6300/
production:  gunicorn -b 0.0.0.0:6300 app:app   (ออกผ่าน sub-path เช่น /anc/)
"""

import csv
import io
import ipaddress
import json
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO
from urllib.parse import urlsplit

try:
    import fcntl                      # Linux/macOS — ล็อกไฟล์ข้ามโปรเซสของ gunicorn
except ImportError:                   # Windows
    fcntl = None

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request, send_file, session,
                   url_for)

import check
import db
import drill
import listing
import render
import metrics
import risk27
import queries
import sti
import store
from cache import TTLCache
from config import PcuMapError, load_config, load_village_pcu

_PREFIX_RE = re.compile(r"(/[A-Za-z0-9._~-]+)+/?")


class PrefixMiddleware:
    """อ่าน X-Forwarded-Prefix → SCRIPT_NAME และ X-Forwarded-Proto → url_scheme (sub-path หลัง proxy)"""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", "")
        # รับเฉพาะ path ภายใน เช่น /anc — กันคนส่ง header ปลอม (//evil.example) ให้ลิงก์ชี้ออกนอกเว็บ
        if prefix and _PREFIX_RE.fullmatch(prefix):
            environ["SCRIPT_NAME"] = prefix.rstrip("/")
            path = environ.get("PATH_INFO", "")
            if path.startswith(prefix):
                environ["PATH_INFO"] = path[len(prefix):] or "/"
        proto = environ.get("HTTP_X_FORWARDED_PROTO")
        if proto in ("http", "https"):
            environ["wsgi.url_scheme"] = proto
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = PrefixMiddleware(app.wsgi_app)
#: กุญแจ session ของหน้ารายชื่อ — ไม่ตั้ง = ปิดหน้ารายชื่อ/login ทั้งหมด (แดชบอร์ดตัวเลขยังใช้ได้)
#: สุ่มเองไม่ได้: gunicorn หลาย worker จะได้กุญแจคนละตัว และ login หลุดทุกครั้งที่ restart
app.secret_key = os.getenv("ANC_SECRET_KEY") or None
#: ชื่อ cookie ของตัวเอง — แอปอื่นบนโดเมนเดียวกันใช้ "session" (Path=/) ถ้าซ้ำ login ที่หนึ่งจะหลุดอีกที่
app.config.update(SESSION_COOKIE_NAME="anc_session", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("ANC_COOKIE_SECURE", "0") == "1",
                  PERMANENT_SESSION_LIFETIME=8 * 3600)

VERSION = "0.1.0"
DEV_CONTACT = "นายเผด็จชัย สิงหล โรงพยาบาลวังน้ำเขียว"

_HERE = os.path.dirname(os.path.abspath(__file__))
_hosp_cache = TTLCache(maxsize=1)
_cache = TTLCache(maxsize=32)
#: ข้อมูลดิบจาก HOSxP ต่อช่วงวันที่ — ใช้ร่วมกันระหว่างแดชบอร์ดกับหน้ารายชื่อ (ไม่ต้องดึงซ้ำ ~30 วินาที)
_raw = TTLCache(maxsize=24)

#: ช่วงวันที่ยาวสุดต่อครั้ง — กันการดึงหลายปีจนฐานข้อมูล HOSxP ช้าทั้งโรงพยาบาล
MAX_DAYS = int(os.getenv("ANC_MAX_DAYS", "731"))

TH_MONTHS = metrics.TH_MONTHS


def thai_date(d):
    return f"{d.day} {TH_MONTHS[d.month - 1]} {d.year + 543}" if d else "—"


TH_MONTHS_FULL = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
                  "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม")
TH_WEEKDAYS = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")


def thai_full_date(d):
    """date(2026, 10, 31) → 'วันเสาร์ที่ 31 ตุลาคม 2569'"""
    return f"วัน{TH_WEEKDAYS[d.weekday()]}ที่ {d.day} {TH_MONTHS_FULL[d.month - 1]} {d.year + 543}"


def range_presets(today=None):
    """ปุ่มช่วงเวลาบนหัวหน้า: เดือนนี้ · เดือนที่แล้ว · ปีงบนี้ · ปีงบที่แล้ว"""
    today = today or date.today()
    m1 = today.replace(day=1)
    pm_end = m1 - timedelta(days=1)
    fy = _fy_start(today)
    out = [("เดือนนี้", m1, today), ("เดือนที่แล้ว", pm_end.replace(day=1), pm_end),
           ("ปีงบนี้", fy, today), ("ปีงบที่แล้ว", fy.replace(year=fy.year - 1), fy - timedelta(days=1))]
    return [{"label": l, "d1": a.isoformat(), "d2": b.isoformat()} for l, a, b in out]


@app.template_filter("th_month")
def th_month(ym):
    """'2026-03' → 'มี.ค. 69'"""
    try:
        y, m = int(ym[:4]), int(ym[5:7])
    except (TypeError, ValueError):
        return ym
    return f"{TH_MONTHS[m - 1]} {str(y + 543)[-2:]}"


def hospital_name():
    """ชื่อโรงพยาบาล: env ANC_HOSPITAL_NAME > opdconfig.hospitalname ของ HOSxP > "โรงพยาบาล" """
    env = os.getenv("ANC_HOSPITAL_NAME")
    if env:
        return env
    hit = _hosp_cache.get("n", 3600)
    if hit:
        return hit
    try:
        name = (db.fetch_one("select hospitalname from opdconfig limit 1").get("hospitalname") or "").strip()
    except Exception:
        name = ""
    name = name or "โรงพยาบาล"
    _hosp_cache.set("n", name)
    return name


@app.context_processor
def _branding():
    img = lambda n: os.path.exists(os.path.join(_HERE, "static", "img", n))
    return {
        "hospital": hospital_name(),
        "hospital_en": os.getenv("ANC_HOSPITAL_NAME_EN", ""),
        "logo_url": url_for("static", filename="img/hospital_logo.png" if img("hospital_logo.png") else "img/logo.png"),
        "hero_url": url_for("static", filename="img/hero.jpg") if img("hero.jpg") else None,
        "version": VERSION,
        "contact": os.getenv("ANC_CONTACT", "ผู้ดูแลระบบสารสนเทศของโรงพยาบาล"),
        "dev_contact": os.getenv("ANC_DEV_CONTACT", DEV_CONTACT),
        "css_v": VERSION,
    }


#: ทุกอย่างโหลดจากเว็บตัวเองเท่านั้น (ไม่มี CDN)
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'self'")


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Content-Security-Policy", CSP)
    return resp


def _parse_date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def _fy_start(today=None):
    today = today or date.today()
    return date(today.year if today.month >= 10 else today.year - 1, 10, 1)


def _range_from(d1s, d2s, default_d1=None, max_days=None):
    """(d1, d2) ที่ผ่านการตรวจแล้ว · ค่าเริ่มต้น = ต้นปีงบประมาณถึงวันนี้"""
    max_days = max_days or MAX_DAYS
    today = date.today()
    d2 = min(_parse_date(d2s) or today, today)
    d1 = min(_parse_date(d1s) or default_d1 or _fy_start(today), d2)
    if (d2 - d1).days >= max_days:
        d1 = d2 - timedelta(days=max_days - 1)
    return d1, d2


def _safe(errors, name, fn, default):
    """รันส่วนหนึ่งของหน้า ล้มแล้วส่วนอื่นยังแสดงได้ · ข้อความ error ไม่แสดงรายละเอียดจากฐานข้อมูล"""
    try:
        return fn()
    except PcuMapError as e:
        errors[name] = f"ไฟล์ village_pcu.csv ไม่ถูกต้อง: {e}"
    except Exception:
        app.logger.exception("section %s failed", name)
        errors[name] = "ดึงข้อมูลไม่ได้"
    return default


SCOPES = {"area": "ในเขต (ตาม KPI)", "all": "ทั้งหมด"}


def _memo(name, d1, d2, cfg, fn):
    key = repr((name, d1, d2, cfg))
    hit = _raw.get(key, cfg.cache_seconds)
    if hit is None:
        hit = fn()
        _raw.set(key, hit)
    return hit


def _main_data(d1, d2, cfg):
    def fetch():
        pregs = queries.pregnancies(d1, d2, cfg)
        visits = queries.visits([p["anc_id"] for p in pregs])
        infants = queries.infants(d1, d2, cfg.dead_dchstts)
        pnc = queries.postnatal([p["anc_id"] for p in pregs if p.get("labor_date")])
        return pregs, visits, infants, pnc
    return _memo("main", d1, d2, cfg, fetch)


def _risk_hits(d1, d2, cfg):
    return _memo("risk", d1, d2, cfg, lambda: queries.risk_hits(d1, d2, cfg))


def _sti(d1, d2, cfg):
    return _memo("sti", d1, d2, cfg, lambda: queries.sti_results(d1, d2, cfg))


def _refers(d1, d2, cfg):
    return _memo("refers", d1, d2, cfg, lambda: queries.refers(d1, d2))


def load_data(d1, d2, cfg):
    """ข้อมูลดิบทั้งหมดของช่วง (สำหรับหน้ารายชื่อ) — ส่วนไหนดึงไม่ได้ให้ล้มทั้งหน้า ไม่แสดงรายชื่อที่ขาดไป"""
    pregs, visits, infants, pnc = _main_data(d1, d2, cfg)
    return {"pregs": pregs, "visits": visits, "infants": infants, "pnc": pnc,
            "refers": metrics.select_refers(_refers(d1, d2, cfg), pregs, cfg), "risk_hits": _risk_hits(d1, d2, cfg),
            "sti": _sti(d1, d2, cfg)}


def build_context(d1, d2, scope="area"):
    """scope = area: ตัวหาร KPI นับหญิงไทยที่อาศัยในอำเภอหรือมาคลอดที่ รพ. (นิยามเอกสาร KPI) · all: ทุกครรภ์ในทะเบียน"""
    cfg = load_config()
    scope = scope if scope in SCOPES else "area"
    area = (lambda p: metrics.in_area(p, cfg)) if scope == "area" else None
    key = (d1, d2, scope, cfg)
    hit = _cache.get(repr(key), cfg.cache_seconds)
    if hit:
        return hit
    errors = {}

    pregs, visits, infants, pnc = _safe(errors, "main", lambda: _main_data(d1, d2, cfg), ([], [], [], []))
    ind = metrics.indicators(pregs, visits, infants, d1, d2, cfg, pnc=pnc, area=area)
    age = metrics.by_age(pregs, visits, d1, d2, cfg, area=area)

    outcome = metrics.outcomes(pregs, infants, [], d1, d2, cfg, area=area)
    new = [p for p in pregs if p.get("register_date") and d1 <= p["register_date"] <= d2]
    risk27_res = _safe(errors, "risk27", lambda: risk27.summarize(new, _risk_hits(d1, d2, cfg), cfg), None)
    sti_res = _safe(errors, "sti", lambda: sti.summarize(new, _sti(d1, d2, cfg), cfg), None)
    refer_rows = _safe(errors, "refer", lambda: metrics.select_refers(_refers(d1, d2, cfg), pregs, cfg), [])
    refer = metrics.refer_summary(refer_rows, d1, d2)

    pcu_map = _safe(errors, "pcu", lambda: load_village_pcu(cfg.village_csv, cfg.chwpart, cfg.amppart), None)
    pcu = metrics.by_pcu(pregs, visits, infants, refer_rows, d1, d2, cfg, pcu_map, area=area) if pcu_map is not None else []
    unmapped = metrics.unmapped_villages(pregs, pcu_map, cfg) if pcu_map is not None else []

    ctx = {
        "d1": d1.isoformat(), "d2": d2.isoformat(), "period_label": f"{thai_date(d1)} – {thai_date(d2)}",
        "fetched_at": datetime.now().strftime("%d/%m/") + str(datetime.now().year + 543) + datetime.now().strftime(" %H:%M น."),
        "scope": scope, "scope_label": SCOPES[scope],
        "labor": dict(metrics.labor_completeness(pregs, d1, d2), warn_pct=cfg.labor_warn_pct),
        "ind": ind, "age": age, "tracking": metrics.tracking(pregs, visits, d2),
        "trend": metrics.monthly_trend(pregs, visits, d1, d2),
        "pcu": pcu, "pcu_missing": pcu_map is None and "pcu" not in errors,
        "unmapped": unmapped, "refer": refer,
        "outcome": outcome, "risk27": risk27_res, "risk_groups": risk27.GROUPS, "sti": sti_res,
        "alerts": metrics.alerts(ind, pcu, age, unmapped, outcome) if "main" not in errors else [],
        "errors": errors, "audited": cfg.data_audited, "cfg_targets": cfg.targets,
        "hct_cutoff": cfg.hct_cutoff, "hct_late_ga": cfg.hct_late_ga, "lbw_grams": cfg.lbw_grams,
        "postpartum_days": cfg.postpartum_days,
    }
    if not errors:
        _cache.set(repr(key), ctx)
    return ctx


# ---------------------------------------------------------------- LAN / proxy

TRUSTED_PROXIES = {x.strip() for x in os.getenv("ANC_TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if x.strip()}
_CF_DEFAULT = ("173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,108.162.192.0/18,"
               "190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,"
               "104.24.0.0/14,172.64.0.0/13,131.0.72.0/22,2400:cb00::/32,2606:4700::/32,2803:f800::/32,"
               "2405:b500::/32,2405:8100::/32,2a06:98c0::/29,2c0f:f248::/32")


def _nets(spec):
    out = []
    for x in spec.split(","):
        try:
            out.append(ipaddress.ip_network(x.strip(), strict=False))
        except ValueError:
            pass
    return out


CF_NETS = _nets(os.getenv("ANC_CF_RANGES", _CF_DEFAULT))
#: เครือข่ายเพิ่มเติมที่นับเป็น "ใน รพ." (เช่น IP สาธารณะของ รพ. เมื่อเข้าผ่าน Cloudflare)
LAN_NETS = _nets(os.getenv("ANC_LAN_NETS", ""))


def _is_cf(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in CF_NETS)


def _client_ip():
    """IP ผู้ใช้: ค่าท้ายสุดของ X-Forwarded-For (Apache ต่อท้ายเอง ปลอมไม่ได้) · ผ่าน Cloudflare จริงจึงเชื่อ CF-Connecting-IP"""
    peer = request.remote_addr
    if peer not in TRUSTED_PROXIES:
        return peer
    xff = [x.strip() for x in request.headers.get("X-Forwarded-For", "").split(",") if x.strip()]
    hop = xff[-1] if xff else peer
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    return cf if cf and _is_cf(hop) else hop


def _from_lan():
    """คำขอมาจากเครื่องใน รพ. หรือไม่ (แบบเดียวกับ er_dashboard) — ผ่าน Cloudflare นับเฉพาะ IP ใน ANC_LAN_NETS"""
    try:
        ip = ipaddress.ip_address((_client_ip() or "").strip())
    except ValueError:
        return False
    if any(ip in n for n in LAN_NETS):
        return True
    if request.headers.get("CF-Connecting-IP", "").strip():
        return False
    return ip.is_private or ip.is_loopback


def _check_allowed():
    """หน้าตรวจข้อมูลบอกโครงสร้างรหัสของ HOSxP — เปิดเฉพาะ LAN · ANC_CHECK_OPEN=1 = เปิดทุกที่"""
    return os.getenv("ANC_CHECK_OPEN", "0") == "1" or _from_lan()


@app.context_processor
def _audit_flags():
    return {"check_allowed": _check_allowed()}


# ---------------------------------------------------------------- login (หน้ารายชื่อ — แบบ mental_health_dashboard)

#: login ผิดเกินจำนวนนี้ใน LOGIN_WINDOW นาที → ปฏิเสธชั่วคราว (ตามชื่อผู้ใช้ / ตาม IP)
LOGIN_MAX_USER, LOGIN_MAX_IP, LOGIN_WINDOW = 10, 30, 15


PASSKEY_USER = store.PASSKEY_USER


def passkey_mode():
    """ANC_LIST_PASSKEY=1 = ใส่รหัสกลางตัวเดียว (ไม่มีชื่อผู้ใช้) · ตั้งรหัสด้วย python manage.py passkey"""
    return os.getenv("ANC_LIST_PASSKEY", "0") == "1"


def list_enabled():
    return bool(app.secret_key)


def _list_gate():
    """หน้ารายชื่อ/login: ปิดเมื่อไม่ตั้ง ANC_SECRET_KEY · ANC_LIST_LAN_ONLY=1 = เข้าได้เฉพาะเครื่องใน รพ."""
    if not list_enabled():
        abort(404)
    if os.getenv("ANC_LIST_LAN_ONLY", "0") == "1" and not _from_lan():
        abort(403)


def _load_user():
    uid = session.get("uid") if list_enabled() else None
    g.user = store.get_user(uid) if uid else None
    return g.user


def audit(action, detail=None):
    store.log(g.user["username"] if g.get("user") else None, action, detail, _client_ip())


def login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        _list_gate()
        if not _load_user():
            # script_root = sub-path หลัง proxy (เช่น /anc) — ไม่ใส่จะเด้งไปเว็บหลักของ รพ.
            return redirect(url_for("login", next=request.script_root + request.full_path))
        return f(*a, **kw)
    return wrap


def _csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def _check_csrf():
    # session ใหม่ไม่มี csrf → "" == "" ผ่านได้ จึงต้องมีค่าจริงด้วย
    sent, want = request.form.get("csrf", ""), session.get("csrf", "")
    if not want or not secrets.compare_digest(sent, want):
        abort(400)


@app.context_processor
def _list_ctx():
    return {"list_on": list_enabled(), "csrf_token": _csrf_token if list_enabled() else (lambda: ""),
            "user": g.get("user"), "passkey_mode": passkey_mode()}


def _safe_next(nxt):
    """next= หลัง login: รับเฉพาะ path ในแอป · ปฏิเสธอักขระควบคุมและ \\ (เบราว์เซอร์อ่าน "/\\evil" เป็น "//evil")"""
    if "\\" in nxt or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in nxt):
        return None
    parts = urlsplit(nxt)
    if parts.scheme or parts.netloc or nxt.startswith("//"):
        return None
    return nxt if nxt.startswith(request.script_root + "/") else None


@app.route("/login", methods=["GET", "POST"])
def login():
    _list_gate()
    if request.method == "POST":
        _check_csrf()
        username = PASSKEY_USER if passkey_mode() else request.form.get("username", "").strip()[:64]
        by_user, by_ip = store.recent_failures(username, _client_ip(), LOGIN_WINDOW)
        if by_user >= LOGIN_MAX_USER or by_ip >= LOGIN_MAX_IP:
            flash(f"ใส่รหัสผิดหลายครั้งเกินไป ลองใหม่อีก {LOGIN_WINDOW} นาที")
            return render_template("login.html"), 429
        u = store.check_login(username, request.form.get("password", ""))
        if u:
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            g.user = u
            audit("login")
            return redirect(_safe_next(request.args.get("next") or "") or url_for("dashboard"))
        store.log(username, "login_fail", ip=_client_ip())
        flash("รหัสไม่ถูกต้อง" if passkey_mode() else "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    _list_gate()
    _check_csrf()
    if _load_user():
        audit("logout")
    session.clear()
    return redirect(url_for("dashboard"))


@app.route("/")
def dashboard():
    d1, d2 = _range_from(request.args.get("d1"), request.args.get("d2"))
    return render_template("dashboard.html", d=build_context(d1, d2, request.args.get("scope", "area")),
                           labels=metrics.IND_LABELS, scopes=SCOPES,
                           print_mode=request.args.get("print") == "1", presets=range_presets(),
                           today_label=thai_full_date(date.today()))


@app.route("/api/data.json")
def api_data():
    d1, d2 = _range_from(request.args.get("d1"), request.args.get("d2"))
    ctx = build_context(d1, d2, request.args.get("scope", "area"))
    return app.response_class(json.dumps(ctx, ensure_ascii=False, default=str),
                              mimetype="application/json")


@app.route("/check")
def check_page():
    """Data Audit — รหัสที่แอปใช้เทียบกับข้อมูลของ รพ. นี้ (ค่าเริ่มต้น 90 วันล่าสุด) · เฉพาะจำนวนนับ"""
    if not _check_allowed():
        return render_template("check.html", lan_only=True), 403
    d1, d2 = _range_from(request.args.get("d1"), request.args.get("d2"),
                         default_d1=date.today() - timedelta(days=89), max_days=366)
    cfg = load_config()
    pcu_err = None
    try:
        pcu_map = load_village_pcu(cfg.village_csv, cfg.chwpart, cfg.amppart)
    except PcuMapError as e:
        pcu_map, pcu_err = None, str(e)
    return render_template("check.html", lan_only=False, c=check.audit(d1, d2, cfg, pcu_map), cfg=cfg,
                           d1=d1.isoformat(), d2=d2.isoformat(), period=f"{thai_date(d1)} – {thai_date(d2)}",
                           pcu_err=pcu_err)


@app.route("/check/village_pcu_template.csv")
def village_pcu_template():
    """แม่แบบ village_pcu.csv (รูปแบบเดียวกับ mental_health_dashboard) จากหมู่ในอำเภอที่พบในทะเบียนฝากครรภ์ 1 ปีล่าสุด
    รวมหมู่ที่จับคู่ไว้แล้ว · คอลัมน์ pregnancies เป็นจำนวนนับ (แอปไม่อ่าน) — ไม่มีข้อมูลรายคน"""
    if not _check_allowed():
        return {"error": "เปิดได้เฉพาะในเครือข่ายโรงพยาบาล"}, 403
    cfg = load_config()
    d2 = date.today()
    try:
        pcu_map = load_village_pcu(cfg.village_csv, cfg.chwpart, cfg.amppart)
    except PcuMapError:
        pcu_map = None
    try:
        pregs = queries.pregnancies(d2 - timedelta(days=364), d2, cfg)
    except Exception:
        app.logger.exception("village template failed")
        return {"error": "ดึงข้อมูลไม่ได้ — รัน setup_check.py"}, 503
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["tmbpart", "tambon", "moo", "village", "hospcode", "pcu", "pregnancies"])
    w.writerows(check.village_template(pregs, pcu_map, cfg))
    # BOM ให้ Excel เปิดภาษาไทยได้ · load_village_pcu อ่านไฟล์ที่มี BOM ได้
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=village_pcu_template.csv"})


# ---------------------------------------------------------------- ส่งออกไฟล์

class _RenderLock:
    """เรนเดอร์ทีละงานทั้งเครื่อง — chromium กินแรมสูง (ล็อกไฟล์ข้าม worker ของ gunicorn)"""

    def __init__(self, path):
        self._path = path
        self._thread = threading.Lock()
        self._fd = None

    def acquire(self, timeout):
        deadline = time.monotonic() + timeout
        got = self._thread.acquire(timeout=timeout) if timeout > 0 else self._thread.acquire(blocking=False)
        if not got:
            return False
        if fcntl is None:
            return True
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    self._thread.release()
                    return False
                time.sleep(0.5)

    def release(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self._thread.release()


_render_lock = _RenderLock(os.path.join(tempfile.gettempdir(), "anc_dashboard_render.lock"))
EXPORT_WAIT = int(os.getenv("ANC_EXPORT_WAIT", "0"))
EXPORT_CACHE_TTL = int(os.getenv("ANC_EXPORT_CACHE_TTL", "300"))
_export_cache = TTLCache(maxsize=8)
EXPORT_ENABLED = os.getenv("ANC_EXPORT", "1") != "0"
MIME = {"png": "image/png", "jpg": "image/jpeg", "pdf": "application/pdf"}


@app.context_processor
def _export_flag():
    return {"export_enabled": EXPORT_ENABLED}


@app.route("/export.<fmt>")
def export(fmt):
    """ส่งออกหน้าแดชบอร์ดเป็น PNG / JPG / PDF ด้วย chromium headless (เรียกหน้าเดิมด้วย ?print=1 — ไม่มีแถบเตือน)"""
    if fmt not in MIME or not EXPORT_ENABLED:
        return {"error": "รองรับเฉพาะ png, jpg, pdf" if EXPORT_ENABLED else "ปิดการส่งออกไฟล์"}, 404
    d1, d2 = _range_from(request.args.get("d1"), request.args.get("d2"))
    scope = request.args.get("scope") if request.args.get("scope") in SCOPES else "area"
    qs = urllib.parse.urlencode({"d1": d1.isoformat(), "d2": d2.isoformat(), "scope": scope, "print": "1"})
    url = f"http://127.0.0.1:{os.getenv('PORT', '6300')}/?{qs}"
    name = f"anc_{d1}_{d2}{'' if scope == 'area' else '_all'}.{fmt}"
    blob = _export_cache.get(name, EXPORT_CACHE_TTL)
    if blob is not None:
        return send_file(BytesIO(blob), mimetype=MIME[fmt], as_attachment=True, download_name=name)
    if not _render_lock.acquire(timeout=EXPORT_WAIT):
        return ({"error": "กำลังส่งออกไฟล์ของผู้ใช้อื่นอยู่ ลองใหม่ในอีกครู่"}, 503, {"Retry-After": "30"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, name)
            render.render_to(fmt, url, out)
            blob = open(out, "rb").read()
        _export_cache.set(name, blob)
        return send_file(BytesIO(blob), mimetype=MIME[fmt], as_attachment=True, download_name=name)
    except Exception as e:
        app.logger.exception("export failed")
        return {"error": f"ส่งออกไม่สำเร็จ: {type(e).__name__}"}, 500
    finally:
        _render_lock.release()


LIST_AGES = metrics.AGE_GROUPS + ("lt15", "15_19")


def _list_result():
    """อ่านตัวกรองจาก query string ตามสิทธิ์ผู้ใช้ → (ตัวกรอง, ผลของ drill, หัวตาราง, แถว) ใช้ทั้งหน้ารายชื่อและ Excel"""
    a = request.args
    d1, d2 = _range_from(a.get("d1"), a.get("d2"))
    scope = a.get("scope") if a.get("scope") in SCOPES else "area"
    pcu = a.get("pcu") if re.fullmatch(r"[0-9A-Za-z]{1,10}", a.get("pcu") or "") else None
    if g.user["hospcode"] not in ("all", ""):
        pcu = g.user["hospcode"]                       # ผู้ใช้ รพ.สต. เห็นเฉพาะเขตตัวเอง
    f = {"k": a.get("k") or "", "d1": d1, "d2": d2, "scope": scope, "pcu": pcu,
         "age": a.get("age") if a.get("age") in LIST_AGES else None,
         "only": a.get("only") if a.get("only") in ("in", "out") else None,
         "q": (a.get("q") or "").strip()[:40] or None}
    cfg = load_config()
    try:
        pcu_map = load_village_pcu(cfg.village_csv, cfg.chwpart, cfg.amppart)
    except PcuMapError:
        pcu_map = None
    data = load_data(d1, d2, cfg)
    area = (lambda p: metrics.in_area(p, cfg)) if scope == "area" else None
    m = drill.members(f["k"], data, d1, d2, cfg, area, pcu_map, pcu=pcu, age=f["age"])
    if m is None:
        abort(404)
    hns = [x.get("hn") for x, _ in m["rows"]]
    head, rows = listing.table(m, data, cfg, pcu_map, queries.names(hns))
    if f["only"]:
        rows = [r for r in rows if r["ok"] is (f["only"] == "in")]
    if f["q"]:
        rows = [r for r in rows if f["q"].lower() in r["search"].lower()]
    pcu_names = dict(metrics._pcu_order(pcu_map, cfg)) if pcu_map is not None else {}
    f["pcu_label"] = pcu_names.get(pcu, pcu) if pcu else None
    return f, m, head, rows, pcu_names


def _audit_detail(f, n):
    return " ".join(f"{k}={v}" for k, v in (("k", f["k"]), ("d", f"{f['d1']}..{f['d2']}"), ("scope", f["scope"]),
                                            ("pcu", f["pcu"]), ("age", f["age"]), ("only", f["only"]),
                                            ("q", f["q"]), ("n", n)) if v is not None)


def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store"     # มีชื่อผู้ป่วย — ห้ามแคชที่ proxy/เบราว์เซอร์
    return resp


@app.route("/list")
@login_required
def list_page():
    f, m, head, rows, pcu_names = _list_result()
    audit("view_list", _audit_detail(f, len(rows)))
    period = f"{thai_date(f['d1'])} – {thai_date(f['d2'])}"
    return _no_store(app.make_response(render_template(
        "list.html", f=f, m=m, head=head, rows=rows, period=period, scopes=SCOPES, pcu_names=pcu_names,
        ages={"teen": "< 20 ปี", "repro": "20–34 ปี", "elder": "≥ 35 ปี", "lt15": "< 15 ปี", "15_19": "15–19 ปี"})))


@app.route("/list/export.xlsx")
@login_required
def list_export():
    f, m, head, rows, _ = _list_result()
    by_pcu = request.args.get("by_pcu") == "1"
    audit("export_list", _audit_detail(f, len(rows)) + (" by_pcu" if by_pcu else ""))
    meta = [("รายชื่อ", m["label"]), ("ช่วงข้อมูล", f"{thai_date(f['d1'])} – {thai_date(f['d2'])}"),
            ("ตัวหาร", SCOPES[f["scope"]]), ("รพ.สต.", f["pcu_label"] or "ทั้งหมด"),
            ("กลุ่มอายุ", f["age"] or "ทั้งหมด"),
            ("เงื่อนไข", {"in": "เฉพาะเข้าเกณฑ์", "out": "เฉพาะไม่เข้าเกณฑ์"}.get(f["only"], "ทั้งหมด")),
            ("จำนวน", len(rows)), ("ส่งออกโดย", g.user["display"]), ("เวลา", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("หมายเหตุ", "มีข้อมูลส่วนบุคคลของผู้ป่วย — ใช้เพื่อการดูแล/ติดตามเท่านั้น ห้ามเผยแพร่")]
    buf = listing.workbook(head, rows, meta, by_pcu=by_pcu)
    name = f"anc_{f['k']}_{f['d1']}_{f['d2']}{'_' + f['pcu'] if f['pcu'] else ''}.xlsx"
    return _no_store(send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               as_attachment=True, download_name=name))


@app.route("/healthz")
def healthz():
    try:
        db.fetch("select 1")
    except Exception:
        return {"status": "db-down"}, 503
    return {"status": "ok"}


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1" if debug else os.getenv("ANC_HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "6300")), debug=debug)
