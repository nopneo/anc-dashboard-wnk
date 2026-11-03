# ติดตั้ง ANC Dashboard สำหรับโรงพยาบาลที่ใช้ HOSxP

แดชบอร์ดงานฝากครรภ์แบบเว็บ (Flask) อ่านข้อมูลสดจากฐานข้อมูล HOSxP (MariaDB/MySQL) **อ่านอย่างเดียว**
นิยามตัวชี้วัดยึดฟิลด์ของ **43 แฟ้ม** (ANC, PRENATAL, LABOR, NEWBORN, EPI, DENTAL, REFER_HISTORY) — ดู [README.md](README.md)

**ขั้นตอนโดยย่อ:** ติดตั้ง (ข้อ 2 หรือ 3) → ใส่ค่าฐานข้อมูลใน `.env` → **`python setup_check.py`**
→ เปิดหน้า **`/check`** จากเครื่องในโรงพยาบาล → ตั้งรหัส `ANC_*` ตามที่หน้านั้นแจ้ง และวางไฟล์ `village_pcu.csv` (ข้อ 5)
→ เทียบตัวเลขกับรายงานงานฝากครรภ์เดิม 1–2 สัปดาห์ → `ANC_DATA_AUDITED=1`

## 0. ก่อนนำไปใช้ — อ่านก่อนติดตั้ง

โปรแกรมนี้แจกฟรีจากโรงพยาบาลวังน้ำเขียว ทดสอบกับข้อมูลจริงของ รพ.วังน้ำเขียว
แต่ **HOSxP ของแต่ละโรงพยาบาลบันทึกและตั้งรหัสไม่เหมือนกัน** (รหัสส่งออกวัคซีน dT, รายการ lab Hct ใน `anc_lab`,
การบันทึกวันคลอด, คอลัมน์เวลาใน `service_time`, หมู่บ้านในเขตของแต่ละ รพ.สต. …)
ถ้าไม่ตรง แดชบอร์ดยังแสดงตัวเลขได้ตามปกติ **แต่ตัวเลขจะเพี้ยนจากความจริงโดยไม่มีข้อความเตือน**
ผู้ที่นำไปใช้จึงต้องตรวจข้อมูลของตัวเองก่อนนำตัวเลขไปรายงานหรือตัดสินใจ

| # | ทำอะไร | เครื่องมือ |
|---|---|---|
| 1 | ตรวจสภาพแวดล้อม: Python ไลบรารี เขตเวลา Chrome การเชื่อมต่อฐานข้อมูล สิทธิ์อ่านอย่างเดียว ตารางที่ต้องใช้ ภาษาไทย visit ANC ล่าสุด ไฟล์ `village_pcu.csv` | `python setup_check.py` |
| 2 | Data Audit: รหัสที่แอปใช้ เทียบกับรหัสและจำนวนในข้อมูลจริง + ค่า `ANC_*` ที่ควรตั้ง · ความครบของ LMP / วันคลอด / น้ำหนักทารก / ผล Hct | หน้า **`/check`** (ข้อ 5) |
| 3 | ทดลองใช้คู่กับรายงานเดิมของงานฝากครรภ์ **อย่างน้อย 1–2 สัปดาห์** — เทียบฝากครรภ์รายใหม่ ฝากก่อน 12 wk ครบ 5 ครั้ง และยอด refer | แดชบอร์ด + รายงานเดิม |
| 4 | ตรวจแล้วตัวเลขตรง → ตั้ง `ANC_DATA_AUDITED=1` (ซ่อนแถบเตือน “ตัวเลขยังไม่ได้ตรวจกับข้อมูลของโรงพยาบาลนี้”) | `.env` |

**เงื่อนไขการใช้:** สัญญาอนุญาต MIT ([LICENSE](LICENSE)) — ใช้ แก้ไข แจกต่อได้ โดยคงข้อความลิขสิทธิ์ไว้ ·
โปรแกรมให้ “ตามสภาพ” **ไม่มีการรับประกัน** ความถูกต้องของตัวเลขในโรงพยาบาลของท่าน เป็นความรับผิดชอบของผู้นำไปใช้ (ข้อ 1–4) ·
ส่วนประกอบของผู้อื่นดู [NOTICE.md](NOTICE.md)

**แจ้งปัญหา:** รัน `python setup_check.py` แล้วแก้ข้อ ✘ ก่อน — ถ้ายังไม่หาย แจ้งผู้พัฒนา (ช่องทางท้ายหน้าแดชบอร์ด)
หรือเปิด issue ของ repo นี้ตามแบบฟอร์ม พร้อมผลของ `setup_check.py` และเวอร์ชันที่ใช้ —
**ห้ามแนบข้อมูลผู้ป่วย** (HN ชื่อ เลขบัตร) หรือรหัสผ่าน

## 1. สิ่งที่ต้องมี

- เครื่องที่ต่อถึงฐานข้อมูล HOSxP ได้ (แนะนำ Slave/Replica)
- Python 3.10 ขึ้นไป · Chrome/Edge/Chromium ถ้าจะใช้ปุ่มส่งออก JPG/PDF
- บัญชีฐานข้อมูล **SELECT อย่างเดียว** (แอปตั้ง session เป็น READ ONLY ให้อีกชั้น)
- งานฝากครรภ์บันทึกผ่านระบบ ANC ของ HOSxP (`person_anc`, `person_anc_service`)

```sql
CREATE USER 'anc_ro'@'%' IDENTIFIED BY '<รหัสผ่านยาว ๆ>';
GRANT SELECT ON hos.* TO 'anc_ro'@'%';      -- จำกัด host ให้แคบที่สุดเท่าที่ทำได้
```

## 2. ติดตั้งบน Linux

```bash
unzip anc_dashboard-0.1.0.zip -d /opt && cd /opt/anc_dashboard
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env && nano .env      # ใส่ DB_HOST / DB_USER / DB_PASS
.venv/bin/python setup_check.py                          # แก้ข้อ ✘ ก่อน
.venv/bin/python app.py                                  # ทดลอง: http://127.0.0.1:6300/ แล้วเปิด /check
```

systemd — `/etc/systemd/system/anc-dashboard.service`:

```ini
[Unit]
Description=ANC Dashboard
After=network.target

[Service]
User=ancdash
Group=ancdash
WorkingDirectory=/opt/anc_dashboard
ExecStart=/opt/anc_dashboard/.venv/bin/gunicorn --bind 0.0.0.0:6300 --workers 2 --threads 8 --timeout 120 \
  --access-logfile - --access-logformat '%(t)s %(m)s %(U)s %(s)s %(L)ss' app:app
Restart=always
Environment=HOME=/var/lib/ancdash
StateDirectory=ancdash
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
useradd -r -s /sbin/nologin ancdash
chown root:ancdash /opt/anc_dashboard/.env && chmod 640 /opt/anc_dashboard/.env
systemctl daemon-reload && systemctl enable --now anc-dashboard
```

## 3. ติดตั้งบน Windows

```powershell
python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env ; notepad .env
.venv\Scripts\python setup_check.py
.venv\Scripts\waitress-serve --listen=0.0.0.0:6300 app:app
```

## 4. ตั้งค่า (.env)

ทุกค่าอธิบายไว้ใน `.env.example` · ค่าที่มักต้องปรับต่อ รพ.:

| ค่า | ความหมาย |
|---|---|
| `ANC_DT_VACCINE_CODES` | รหัสส่งออกวัคซีน dT หญิงตั้งครรภ์ (ค่าเริ่มต้น 201–205 = dTANC1–5) |
| `ANC_HCT_LAB_IDS` | `anc_lab_id` ของผล Hct (ว่าง = หาจากชื่อ) |
| `ANC_WAIT_FROM_COL`, `ANC_WAIT_TO_COL` | คอลัมน์เวลาใน `service_time` ของเวลารอคอย (ค่าเริ่มต้น `vsttime` → `service5`) |
| `ANC_TARGET_*` | เป้าหมายตัวชี้วัด (%) |
| `ANC_VILLAGE_CSV` | ไฟล์หมู่บ้าน → รพ.สต. (ค่าเริ่มต้น `village_pcu.csv`) — รูปแบบเดียวกับ mental_health_dashboard |
| `ANC_CHWPART`, `ANC_AMPPART` | จังหวัด/อำเภอของ รพ. (ค่าเริ่มต้น 30/25) — ที่อยู่นอกอำเภอนับเป็น “นอกเขตอำเภอ” |
| `ANC_HOSPCODE` | รหัส 5 หลักของ รพ. (ค่าเริ่มต้น 10894) — หมู่ที่ รพ. ดูแลเองเป็นแถว “เขต รพ.” |
| `ANC_LAN_NETS`, `ANC_CHECK_OPEN` | ใครเปิดหน้า `/check` ได้ |

### หน้ารายชื่อ (ไม่บังคับ)

ตัวเลขบนแดชบอร์ดกดดูรายชื่อและส่งออก Excel ได้เมื่อเปิดใช้ — **มีข้อมูลส่วนบุคคล** ใช้บัญชีรายคนเท่านั้น

```bash
python -c "import secrets; print(secrets.token_hex(32))"     # ใส่ใน .env เป็น ANC_SECRET_KEY=...
python manage.py adduser somchai --display "สมชาย ใจดี"                    # เห็นทุก รพ.สต.
python manage.py adduser pcu02840 --display "รพ.สต.ศาลเจ้าพ่อ" --hospcode 02840   # เห็นเฉพาะเขตตัวเอง
python manage.py users | passwd <ชื่อ> | disable <ชื่อ> | audit --user <ชื่อ>
```

- บัญชีและ audit log อยู่ที่ `data/anc.sqlite` (`ANC_DATA_DIR`) — สำรองไฟล์นี้ · ผู้ใช้ที่รัน service ต้องเขียนโฟลเดอร์นี้ได้
- **โหมด passkey** (รหัสกลางตัวเดียว ไม่ต้องมีบัญชีรายคน): ตั้ง `ANC_LIST_PASSKEY=1` + `ANC_LIST_LAN_ONLY=1` แล้ว `python manage.py passkey`
  — audit log บันทึกเป็น `passkey` + IP เท่านั้น ระบุตัวคนไม่ได้ · เปลี่ยนรหัสเมื่อมีคนย้ายออก (รันคำสั่งเดิมซ้ำ)
- เปิดผ่าน https ให้ตั้ง `ANC_COOKIE_SECURE=1` · อยากให้เปิดได้เฉพาะใน รพ. ตั้ง `ANC_LIST_LAN_ONLY=1`
- Docker: mount `data/` เป็น volume (`-v anc-data:/app/data`) ไม่งั้นบัญชีหายเมื่อสร้าง container ใหม่
- ไม่ตั้ง `ANC_SECRET_KEY` = ไม่มีหน้า login/รายชื่อ แดชบอร์ดตัวเลขใช้ได้ตามเดิม

## 5. ปรับให้ตรงกับข้อมูลของโรงพยาบาล (หน้า `/check`)

เปิด `http://<เครื่อง>:6300/check` จากเครื่องในโรงพยาบาล หน้านี้แสดงเฉพาะจำนวนนับ ไม่มีข้อมูลรายคน

1. ทุกข้อที่เป็น ⚠ / ✘ อ่านคำแนะนำในแถว แล้วแก้ค่า env ที่ระบุใน `.env` → รีสตาร์ตแอป
2. **ไฟล์ `village_pcu.csv`** (หมู่บ้าน → รพ.สต.) ใช้รูปแบบเดียวกับ **mental_health_dashboard** —
   ถ้า รพ. มีไฟล์นี้อยู่แล้วให้คัดลอกมาวางในโฟลเดอร์แอปได้เลย แถวละ 1 หมู่:

   ```csv
   tmbpart,tambon,moo,village,hospcode,pcu
   01,วังน้ำเขียว,10,บุตะโก,10894,รพ.วังน้ำเขียว
   01,วังน้ำเขียว,1,ศาลเจ้าพ่อ,02840,ศาลเจ้าพ่อ
   ```

   `tmbpart` = รหัสตำบลตาม `patient.tmbpart` · `moo` = เลขหมู่ · `hospcode` = รหัส รพ.สต. (หมู่ที่ รพ. ดูแลเองใส่ `ANC_HOSPCODE`)
   · `pcu` = ชื่อที่แสดง · ยังไม่มีไฟล์ กด “แม่แบบ village_pcu.csv” ที่หน้า `/check` จะได้หมู่ในอำเภอที่พบในทะเบียนฝากครรภ์
   แล้วเติม `hospcode` / `pcu` บันทึกเป็น CSV UTF-8
   แถวบนแดชบอร์ดเรียงเหมือน mental_health_dashboard: รพ.สต. → เขต รพ. → **ในอำเภอ ไม่ทราบหมู่** (หมู่ที่ไม่อยู่ในไฟล์
   หรือไม่มีที่อยู่) → **นอกเขตอำเภอ**
3. ดูตาราง “ความครบของข้อมูล” — ถ้าวันคลอด (`person_anc.labor_date`) หรือผล Hct บันทึกไม่ครบ
   ตัวชี้วัดที่ใช้ “ครรภ์ที่คลอดในช่วง” เป็นตัวหารจะต่ำหรือสูงกว่าความจริง ให้แก้การบันทึกที่ต้นทาง
4. ตรวจแล้วกด “ยืนยันว่าตรวจแล้ว” (เฉพาะเบราว์เซอร์นั้น) หรือตั้ง `ANC_DATA_AUDITED=1` (ทุกคน)

## 6. เปิดผ่าน reverse proxy (sub-path)

แอปรองรับ `X-Forwarded-Prefix` เช่นเปิดที่ `https://<โดเมน>/anc/` (Apache):

```apache
ProxyPass        /anc/ http://127.0.0.1:6300/
ProxyPassReverse /anc/ http://127.0.0.1:6300/
<Location /anc/>
  RequestHeader set X-Forwarded-Prefix "/anc"
  RequestHeader set X-Forwarded-Proto "https"
</Location>
```

## 7. Docker

```bash
docker build -t anc-dashboard .                       # ไม่มีปุ่มส่งออก (image เล็ก)
docker build --target export -t anc-dashboard-export . # มี chromium สำหรับปุ่มส่งออก
docker run -p 8080:8080 --env-file .env -v $PWD/village_pcu.csv:/app/village_pcu.csv:ro anc-dashboard
docker exec <ชื่อ container> python setup_check.py
```
