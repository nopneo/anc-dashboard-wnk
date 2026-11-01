"""ANC Dashboard — แดชบอร์ดงานฝากครรภ์ (HOSxP · นิยามตาม 43 แฟ้ม)

รันเอง:      python app.py            → http://127.0.0.1:6300/
production:  gunicorn -b 0.0.0.0:6300 app:app   (ออกผ่าน sub-path เช่น /anc/)
"""

import json
import os
import re
from datetime import date, datetime, timedelta

from flask import Flask, render_template, request, url_for

import db
import metrics
import queries
from cache import TTLCache
from config import PcuMapError, load_config, load_pcu_map

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

VERSION = "0.1.0"
DEV_CONTACT = "นายเผด็จชัย สิงหล โรงพยาบาลวังน้ำเขียว"

_HERE = os.path.dirname(os.path.abspath(__file__))
_hosp_cache = TTLCache(maxsize=1)
_cache = TTLCache(maxsize=32)

#: ช่วงวันที่ยาวสุดต่อครั้ง — กันการดึงหลายปีจนฐานข้อมูล HOSxP ช้าทั้งโรงพยาบาล
MAX_DAYS = int(os.getenv("ANC_MAX_DAYS", "731"))

TH_MONTHS = metrics.TH_MONTHS


def thai_date(d):
    return f"{d.day} {TH_MONTHS[d.month - 1]} {d.year + 543}" if d else "—"


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
        errors[name] = f"ไฟล์ pcu_map.csv ไม่ถูกต้อง: {e}"
    except Exception:
        app.logger.exception("section %s failed", name)
        errors[name] = "ดึงข้อมูลไม่ได้"
    return default


def build_context(d1, d2):
    cfg = load_config()
    key = (d1, d2, cfg)
    hit = _cache.get(repr(key), cfg.cache_seconds)
    if hit:
        return hit
    errors = {}

    def main():
        pregs = queries.pregnancies(d1, d2, cfg)
        visits = queries.visits([p["anc_id"] for p in pregs])
        infants = queries.infants(d1, d2)
        waits = queries.waits(d1, d2, cfg)
        return pregs, visits, infants, waits

    pregs, visits, infants, waits = _safe(errors, "main", main, ([], [], [], []))
    ind = metrics.indicators(pregs, visits, infants, waits, d1, d2, cfg)
    age = metrics.by_age(pregs, visits, d1, d2, cfg)

    refer_rows = _safe(errors, "refer", lambda: metrics.select_refers(queries.refers(d1, d2), pregs, cfg), [])
    refer = metrics.refer_summary(refer_rows, d1, d2)

    pcu_map = _safe(errors, "pcu", lambda: load_pcu_map(cfg.pcu_map_path), None)
    pcu = metrics.by_pcu(pregs, visits, infants, refer_rows, d1, d2, cfg, pcu_map) if pcu_map else []
    unmapped = metrics.unmapped_villages(pregs, pcu_map) if pcu_map else []

    ctx = {
        "d1": d1.isoformat(), "d2": d2.isoformat(), "period_label": f"{thai_date(d1)} – {thai_date(d2)}",
        "fetched_at": datetime.now().strftime("%d/%m/") + str(datetime.now().year + 543) + datetime.now().strftime(" %H:%M น."),
        "ind": ind, "age": age, "tracking": metrics.tracking(pregs, visits, d2),
        "trend": metrics.monthly_trend(pregs, visits, d1, d2),
        "pcu": pcu, "pcu_missing": pcu_map is None and "pcu" not in errors,
        "unmapped": unmapped, "refer": refer,
        "alerts": metrics.alerts(ind, pcu, age, unmapped) if "main" not in errors else [],
        "errors": errors, "audited": cfg.data_audited, "cfg_targets": cfg.targets,
        "hct_cutoff": cfg.hct_cutoff, "hct_late_ga": cfg.hct_late_ga, "lbw_grams": cfg.lbw_grams,
        "postpartum_days": cfg.postpartum_days,
    }
    if not errors:
        _cache.set(repr(key), ctx)
    return ctx


@app.route("/")
def dashboard():
    d1, d2 = _range_from(request.args.get("d1"), request.args.get("d2"))
    return render_template("dashboard.html", d=build_context(d1, d2), labels=metrics.IND_LABELS,
                           print_mode=request.args.get("print") == "1")


@app.route("/api/data.json")
def api_data():
    d1, d2 = _range_from(request.args.get("d1"), request.args.get("d2"))
    return app.response_class(json.dumps(build_context(d1, d2), ensure_ascii=False, default=str),
                              mimetype="application/json")


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
