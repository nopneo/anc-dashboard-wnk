"""จัดการผู้ใช้หน้ารายชื่อ (รันบนเครื่องที่มีไฟล์ data/anc.sqlite)

  python manage.py adduser <username> --display "ชื่อ" [--hospcode 03929] [--admin]
  python manage.py passwd <username>
  python manage.py passkey                 # ตั้ง/เปลี่ยนรหัสกลางของโหมด passkey (ANC_LIST_PASSKEY=1)
  python manage.py disable <username>      # ปิดบัญชี (ย้ายหน่วย/ลาออก) · enable = เปิดคืน
  python manage.py users
  python manage.py audit [--user somchai] [--limit 100]   # ใครเปิดดู/ส่งออกรายชื่อไหน เมื่อไร
"""

import argparse
import getpass
import sys

import store
from config import PcuMapError, load_config, load_village_pcu

if hasattr(sys.stdout, "reconfigure"):     # คอนโซล Windows (cp874) แสดงภาษาไทยเพี้ยน
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _ask_password():
    pw = getpass.getpass("รหัสผ่าน: ")
    if len(pw) < 8 or pw != getpass.getpass("ยืนยันรหัสผ่าน: "):
        sys.exit("รหัสผ่านต้องยาวอย่างน้อย 8 ตัวและพิมพ์ตรงกันทั้งสองครั้ง")
    return pw


def _pcu_codes():
    cfg = load_config()
    try:
        m = load_village_pcu(cfg.village_csv, cfg.chwpart, cfg.amppart) or {}
    except PcuMapError as e:
        sys.exit(f"อ่าน village_pcu.csv ไม่ได้: {e}")
    return {code for code, _ in m.values()} | {cfg.hospcode}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("adduser")
    a.add_argument("username")
    a.add_argument("--display", required=True)
    a.add_argument("--hospcode", default="all", help="'all' หรือรหัส รพ.สต. ใน village_pcu.csv เช่น 03929")
    a.add_argument("--admin", action="store_true")
    sub.add_parser("passkey")
    p = sub.add_parser("passwd")
    p.add_argument("username")
    for name in ("disable", "enable"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("users")
    au = sub.add_parser("audit")
    au.add_argument("--user")
    au.add_argument("--limit", type=int, default=100)
    args = ap.parse_args(argv)

    if args.cmd == "adduser":
        if args.hospcode != "all" and args.hospcode not in _pcu_codes():
            sys.exit("ไม่รู้จักรหัส รพ.สต. นี้ใน village_pcu.csv: " + args.hospcode)
        store.add_user(args.username, _ask_password(), args.display, args.hospcode, args.admin)
        print("เพิ่มผู้ใช้แล้ว")
    elif args.cmd == "passkey":
        pw = _ask_password()
        if store.set_password(store.PASSKEY_USER, pw):
            store.set_active(store.PASSKEY_USER, True)
            print("เปลี่ยนรหัส passkey แล้ว")
        else:
            store.add_user(store.PASSKEY_USER, pw, "ผู้ใช้ใน รพ. (passkey)")
            print("ตั้งรหัส passkey แล้ว")
    elif args.cmd == "passwd":
        if not store.set_password(args.username, _ask_password()):
            sys.exit("ไม่พบผู้ใช้นี้")
        print("เปลี่ยนรหัสผ่านแล้ว")
    elif args.cmd in ("disable", "enable"):
        if not store.set_active(args.username, args.cmd == "enable"):
            sys.exit("ไม่พบผู้ใช้นี้")
        print("ปิดบัญชีแล้ว" if args.cmd == "disable" else "เปิดบัญชีแล้ว")
    elif args.cmd == "audit":
        for r in store.audit(args.user, args.limit):
            print(f"{r['at']}  {r['username']:<16} {r['action']:<12} {r['ip'] or '':<15} {r['detail'] or ''}")
    else:
        for u in store.list_users():
            print(f"{u['username']:<16} {u['hospcode']:<6} {'admin' if u['is_admin'] else '':<6} "
                  f"{'' if u['active'] else '(ปิด)':<5} {u['display']}")


if __name__ == "__main__":
    main()
