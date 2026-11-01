# ANC Dashboard — Design Spec

วันที่: 1 พ.ย. 2569 · สถานะ: รอผู้ใช้ตรวจ · ผู้ใช้งาน: งานฝากครรภ์ / ผู้บริหาร รพ.วังน้ำเขียว และ รพ. อื่นที่ใช้ HOSxP

## 1. เป้าหมาย

แดชบอร์ดงานฝากครรภ์แบบ infographic หน้าเดียว (รูปแบบเดียวกับ `er_dashboard`) โทนชมพู แสดง

- ตัวชี้วัด ANC 10 ตัว (ตามรูป `S__33751045.jpg`)
- แยกตาม **รพ.สต.** (จัดตามหมู่บ้านที่อยู่ของแม่) และตาม **กลุ่มอายุ** Teenage (<20; ย่อย <15, 15–19) · วัยเจริญพันธุ์ (20–34) · Elderly gravida (≥35) — อายุ ณ วันลงทะเบียนฝากครรภ์
- สรุป refer รายเดือน: Dx อะไร ส่งไปที่ไหน

นิยามทุกตัวยึดฟิลด์ **43 แฟ้ม** (ANC, PRENATAL, LABOR, NEWBORN, EPI, DENTAL, REFER_HISTORY) เพื่อให้ รพ. อื่นตีความเหมือนกัน
แต่คำนวณจาก **ตาราง HOSxP สด** ของ รพ. (ตาราง `james_f43_*` เป็นภาพนิ่ง 16 ก.ค. 2569 — ไม่ใช้)

**ความสำเร็จ:** ตัวเลขตรงกับรายงานเดิมของงานฝากครรภ์ในช่วงทดลองคู่ขนาน 1–2 สัปดาห์ · รพ. อื่นติดตั้งแล้วรู้ได้จาก `/check` ว่ารหัสไหนไม่ตรง

**นอกขอบเขต:** ข้อมูลที่บันทึกใน HOSxP/JHCIS ของ รพ.สต. เอง (ผู้ใช้เลือกใช้ HOSxP รพ. อย่างเดียว), รายชื่อรายคน, การแก้ข้อมูลใน HOSxP

## 2. สถาปัตยกรรม (แยกโครงจาก `er_dashboard`)

```
ANC_dashboard/
  app.py           Flask + PrefixMiddleware + route /, /check, /export, /healthz
  db.py            คัดลอกจาก er_dashboard (direct/ssh, tis620, READ ONLY) เปลี่ยน prefix env เป็น ANC_
  cache.py         คัดลอกจาก er_dashboard
  config.py        อ่าน env ทั้งหมด (รหัส เกณฑ์ เป้า) + โหลด pcu_map.csv
  queries.py       SQL ดึงข้อมูลดิบระดับ "ครรภ์" และ "refer" (ไม่มีการคำนวณ %)
  metrics.py       ฟังก์ชันบริสุทธิ์: ครรภ์ → ตัวชี้วัด/กลุ่มอายุ/รพ.สต./refer (ทดสอบได้โดยไม่ต้องมี DB)
  check.py         Data Audit สำหรับหน้า /check
  render.py        ส่งออก JPG/PDF (คัดลอกแนวทางจาก er_dashboard)
  setup_check.py   ตรวจสภาพแวดล้อม ✔/⚠/✘ exit 1 เมื่อมี ✘
  pcu_map.example.csv
  templates/ dashboard.html, check.html     static/ style.css (ธีมชมพู), fonts, img
  tests/           pytest ของ metrics.py และ config.py
  INSTALL.md README.md CHANGELOG.md LICENSE(MIT) Dockerfile .env.example
  .github/ISSUE_TEMPLATE/bug_report.yml
```

แยก `queries.py` (ดึงแถวระดับครรภ์) ออกจาก `metrics.py` (คำนวณ) เพราะกฎ "ครบ 5 ช่วง GA", ขอบเขต refer หลังคลอด 42 วัน และการจัดกลุ่ม ทดสอบด้วยข้อมูลจำลองได้ง่ายกว่าเขียนใน SQL

## 3. แหล่งข้อมูล HOSxP (ตรวจกับฐาน `hos` จริงแล้ว 1 พ.ย. 2569 — ผลเป็นจำนวนนับ)

| ใช้ทำอะไร | ตาราง HOSxP | แฟ้ม 43 ที่สอดคล้อง | สภาพข้อมูลที่ รพ.วังน้ำเขียว |
|---|---|---|---|
| ทะเบียนครรภ์ (1 แถว/ครรภ์) | `person_anc` (person_id, preg_no, anc_register_date, lmp, edc, labor_date, labour_hospcode, blood_hct_result, blood_check2_date, vaccine_dtanc1-5_date, dental_tx_date) | PRENATAL | ~200 ครรภ์/ปี · LMP ครบ ~99% · Hct มีเพียง ~15–20% |
| visit ANC | `person_anc_service` (anc_service_date, pa_week, vn, anc_service_type_id) | ANC (DATE_SERV, GA, SEQ) | 1,089 visit ตั้งแต่ ต.ค. 68 · pa_week ครบ |
| ANC ที่อื่น | `person_anc_other_precare` (precare_date, precare_hospcode) | ANC (HOSPCODE อื่น) | นับเป็นครั้งฝากครรภ์ได้ (สำหรับครบ 5 ครั้ง) |
| ผลแล็บ ANC | `person_anc_lab` + `anc_lab` (anc_lab_id → lab_items_code) | PRENATAL (HCT_RESULT) | ใช้ `ANC_HCT_LAB_IDS` |
| วัคซีน dT | `ovst_vaccine` + `person_vaccine` (export_vaccine_code) | EPI (VACCINETYPE 201–205 = dTANC1–5) | ใช้รหัส 201–205 · มี `101 (TT1/dT1)` จำนวนมาก ต้องตรวจใน /check ว่าเป็นหญิงตั้งครรภ์หรือไม่ |
| ตรวจฟัน | `dtmain.pregnancy='Y'` และ/หรือ `person_anc.dental_tx_date` | DENTAL (DENTTYPE=1) | 376 visit ตั้งแต่ ต.ค. 68 |
| คลอด / ทารก | `ipt_labour` + `ipt_labour_infant` (birth_weight) ; `person_labour` สำหรับคลอดที่อื่น | LABOR, NEWBORN (BWEIGHT) | 84 ทารก ตั้งแต่ ต.ค. 68 (LBW 12) |
| refer | `referout` (refer_date, refer_time, refer_hospcode, pdx, vn, hn) + `hospcode` (ชื่อ) | REFER_HISTORY (HOSPCODE_DEST, DIAGFIRST) | pdx ครบ ~99.5% |
| ที่อยู่ → รพ.สต. | `person` → `patient` (chwpart, amppart, tmbpart, moopart) | PERSON/HOME (VILLAGE 8 หลัก) | อ.วังน้ำเขียว 5 ตำบล 51 หมู่ที่มีหญิงตั้งครรภ์ |
| เวลารอคอย | `service_time` (service1..N) | **ไม่มีใน 43 แฟ้ม** | ป้าย "นอก 43 แฟ้ม" |

ชื่อคอลัมน์ข้างต้นตรวจจาก `information_schema` แล้ว ส่วนเลขคอลัมน์ `service_time` ที่หมายถึง "ส่งตรวจ" และ "พบแพทย์" ตั้งด้วย env (ดู er_dashboard เป็นแนว)

## 4. นิยามตัวชี้วัด

หน่วยนับหลัก = **ครรภ์** (`person_anc_id`) · ช่วงเวลา = ช่วงวันที่ที่ผู้ใช้เลือก (ค่าเริ่มต้น ปีงบประมาณปัจจุบัน)

| # | ตัวชี้วัด | ตัวตั้ง | ตัวหาร |
|---|---|---|---|
| 1 | ฝากครรภ์รายใหม่ (ราย) | ครรภ์ที่ `anc_register_date` อยู่ในช่วง | — |
| 2 | ครั้งบริการ ANC (ครั้ง) | visit ใน `person_anc_service` ที่อยู่ในช่วง | — |
| 3 | เฉลี่ยครั้ง/เดือน | ข้อ 2 | จำนวนเดือนในช่วง (นับเดือนบางส่วนเป็นสัดส่วนวัน) |
| 4 | ฝากครรภ์ก่อน 12 wk (%) | ครรภ์ที่ ANC ครั้งแรก (รวม precare) มี GA ≤ 12 wk | ครรภ์ที่ **คลอดในช่วง** |
| 5 | ANC ครบ 5 ครั้ง (%) | มีอย่างน้อย 1 visit ในทุกช่วง GA: ≤12, 13–20, 21–26, 27–32, 33–40 wk | ครรภ์ที่คลอดในช่วง |
| 6 | วัคซีน dT (%) | ได้วัคซีนรหัสใน `ANC_DT_VACCINE_CODES` ระหว่าง LMP ถึงวันคลอด หรือมี `vaccine_dtanc*_date` | ครรภ์ที่คลอดในช่วง |
| 7 | ตรวจช่องปาก (%) | มี `dtmain.pregnancy='Y'` ระหว่าง LMP ถึงวันคลอด หรือมี `dental_tx_date` | ครรภ์ที่คลอดในช่วง |
| 8 | โลหิตจางใกล้คลอด (%) | ผล Hct ครั้งสุดท้ายที่ GA ≥ `ANC_HCT_LATE_GA` (28) < `ANC_HCT_CUTOFF` (33) | ครรภ์ที่คลอดในช่วงและมีผล Hct ช่วงนั้น |
| 9 | ทารก LBW (%) | ทารกเกิดมีชีพ `birth_weight` < `ANC_LBW_GRAMS` (2500) | ทารกเกิดมีชีพใน รพ. ในช่วง |
| 10 | เวลารอคอยเฉลี่ย (นาที) | ค่าเฉลี่ย (พบแพทย์ − ส่งตรวจ) ของ visit ANC ตัดค่า <0 และ > `ANC_WAIT_MAX_MIN` (240) | visit ANC ที่มีเวลาครบ |

- GA ของ visit = `pa_week` ถ้ามี ไม่งั้นคำนวณจาก LMP · "คลอดในช่วง" = `person_anc.labor_date` อยู่ในช่วง
- ครรภ์ที่ยังไม่คลอด แสดงแยกเป็น "กำลังติดตาม" (จำนวน · ฝากก่อน 12 wk ไปแล้ว) ไม่นำเข้าตัวหาร
- ตัวหาร = 0 แสดง "—" ไม่แสดง 0%
- เป้าหมายตั้งด้วย env ค่าเริ่มต้น: ก่อน 12 wk ≥75 · ครบ 5 ครั้ง ≥75 · dT ≥90 · ช่องปาก ≥50 · โลหิตจาง ≤14 · LBW ≤7 (%)

### Refer (ส่วน 6–9 ของหน้า)

refer ที่นับ = `referout` ในช่วง ที่เข้าเงื่อนไขอย่างใดอย่างหนึ่ง

1. ผู้ป่วยมีครรภ์ใน `person_anc` และวัน refer อยู่ระหว่าง LMP ถึงวันคลอด + `ANC_POSTPARTUM_DAYS` (42) หรือยังไม่คลอดและไม่เกิน LMP + 44 wk
2. `pdx` ขึ้นต้นด้วยช่วงใน `ANC_REFER_DX_PREFIXES` (ค่าเริ่มต้น `O,Z32,Z33,Z34,Z35,Z36`)

ไม่นับซ้ำ (1 `referout_id` = 1 ครั้ง) · รายที่ผ่านข้อ 2 แต่ไม่อยู่ในทะเบียน → กลุ่มอายุคำนวณจาก `patient.birthday` ณ วัน refer, รพ.สต. จากที่อยู่ patient
สรุป: รายเดือน × กลุ่มอายุ, Top 10 Dx (ICD-10 3 หลัก + ชื่อ), ปลายทาง (ชื่อ รพ.), ตาราง เดือน × บท Dx × ปลายทาง

## 5. การจับคู่ รพ.สต.

- คีย์ = รหัสหมู่บ้าน 8 หลัก `chwpart+amppart+tmbpart+moopart` จาก `patient` (ตรงกับ VILLAGE ของ 43 แฟ้ม)
- ไฟล์ `pcu_map.csv`: `village_code,pcu_hospcode,pcu_name` (ไม่อยู่ใน git — มี `pcu_map.example.csv`)
- ไม่พบใน map → "นอกเขต/ไม่ระบุ" · ถ้าไม่มีไฟล์เลย → ส่วนแยก รพ.สต. แสดงข้อความให้ไปตั้งค่าที่ `/check` แทนตาราง
- `/check` มีปุ่ม "ดาวน์โหลดแม่แบบ" = รหัสหมู่บ้านที่พบในทะเบียนครรภ์ + ชื่อตำบล/หมู่ + จำนวน + คอลัมน์ รพ.สต. ที่ map ไว้แล้ว (ไม่มีข้อมูลรายคน)

## 6. หน้า dashboard (`/`)

ลำดับตามที่ตกลง: หัวหน้า (แถบชมพู โลโก้ ช่วงวันที่ เวลาดึง) → 1 KPI 7 การ์ด → 2 Trend รายเดือน → 3 ตารางตัวชี้วัด 10 ตัว (ค่า/เป้า/สถานะ/แถบ) → 4 กลุ่มอายุ 3 การ์ด → 5 ตาราง รพ.สต. (ช่องต่ำกว่าเป้าเป็นแดง) → 6 Refer รายเดือน (stacked ตามกลุ่มอายุ) → 7 Top 10 Refer Dx → 8 Refer Destinations → 9 ตารางสรุป refer รายเดือน → 10 Alert & Action → ท้ายหน้า แหล่งข้อมูล (ชื่อแฟ้ม 43 + ตาราง HOSxP)

- ธีม: token สีบน `:root` — primary ชมพูเข้ม `#C2185B`, ไล่ไป `#F06292` / `#F8BBD0`, พื้นหลังขาวอมชมพู · กลุ่มอายุใช้ 3 สีที่แยกกันชัดและผ่านการตรวจ contrast
- ฟอนต์/ไอคอน/ปุ่มส่งออก JPG-PDF/โลโก้: ใช้ของ er_dashboard
- ทุกส่วนเป็นจำนวนนับ/ร้อยละ ไม่มีชื่อ HN CID
- เซลล์ที่ตัวหาร < 5 แสดงตัวเลขเป็นสีจาง + tooltip "ฐานน้อย ตีความระวัง"

## 7. ตรวจก่อนใช้ (ตาม CLAUDE.md, ต้นแบบ `opd_dashboard` v1.4.0)

**`/check`** (LAN หรือโหมด bms เท่านั้น) แสดง "แอปใช้ vs พบในข้อมูล" ของ:
`ANC_DT_VACCINE_CODES` (พร้อมรหัสวัคซีนกลุ่ม dT/TT ทั้งหมดที่พบ เช่น 101) · `ANC_HCT_LAB_IDS` (รายการ `anc_lab` ทั้งหมด) · `anc_service_type_id` ที่พบ · ปลายทาง refer ที่ไม่มีชื่อใน `hospcode` · `ANC_REFER_DX_PREFIXES` (จำนวน refer ที่ตกแต่ละเงื่อนไข) · คอลัมน์ `service_time` ที่ใช้
ความครบถ้วน: % ครรภ์มี LMP · % คลอดมี labor_date · % ทารกมีน้ำหนัก · % ครรภ์มีผล Hct · % ครรภ์ที่ map รพ.สต. ได้
ปุ่ม "ยืนยันว่าตรวจแล้ว" (localStorage แยกตาม HOSPCODE) หรือ env `ANC_DATA_AUDITED=1`

**แถบเตือน** บนหน้าหลัก "ตัวเลขยังไม่ได้ตรวจกับข้อมูลของโรงพยาบาลนี้" จนกว่ายืนยัน — ไม่ติดไปในไฟล์ส่งออก/โหมดพิมพ์

**`setup_check.py`**: Python/ไลบรารี · เขตเวลา · Chrome (ส่งออก) · ต่อ DB ได้ · สิทธิ์อ่านอย่างเดียว (นับเฉพาะฐาน HOSxP + `*.*`) · ตารางใน §3 ครบ · ภาษาไทยอ่านได้ · visit ANC ล่าสุด · `pcu_map.csv` มีและรูปแบบถูก · สรุป Data Audit · exit 1 เมื่อมี ✘

**เอกสาร**: INSTALL.md ข้อ 0 "ก่อนนำไปใช้" (ตรวจ → ทดลองคู่รายงานเดิม 1–2 สัปดาห์ → ตั้ง DATA_AUDITED, MIT ไม่รับประกัน, วิธีแจ้งปัญหา) · `bug_report.yml` บังคับแนบผล setup_check และยืนยันไม่มีข้อมูลผู้ป่วย · `setup_check.py` อยู่ในชุด deploy/Docker

## 8. env (ทั้งหมดมีค่าเริ่มต้น)

`DB_HOST DB_PORT DB_NAME DB_USER DB_PASS PORT ANC_DB_MODE ANC_SSH_HOST ANC_DB_TIMEOUT`
`ANC_DT_VACCINE_CODES=201,202,203,204,205` · `ANC_HCT_LAB_IDS=` (ว่าง = หาจาก `anc_lab` ชื่อมี Hct) · `ANC_HCT_CUTOFF=33` · `ANC_HCT_LATE_GA=28`
`ANC_LBW_GRAMS=2500` · `ANC_POSTPARTUM_DAYS=42` · `ANC_REFER_DX_PREFIXES=O,Z32,Z33,Z34,Z35,Z36`
`ANC_WAIT_FROM_COL / ANC_WAIT_TO_COL` (คอลัมน์ service_time — ค่าเริ่มต้นเดียวกับที่ er_dashboard ใช้คำนวณเวลารอแพทย์) · `ANC_WAIT_MAX_MIN=240`
`ANC_TARGET_EARLY12=75 ANC_TARGET_5VISIT=75 ANC_TARGET_DT=90 ANC_TARGET_DENTAL=50 ANC_TARGET_ANEMIA=14 ANC_TARGET_LBW=7`
`ANC_PCU_MAP=pcu_map.csv` · `ANC_DATA_AUDITED=0` · `ANC_CACHE_SECONDS=600`

## 9. ข้อผิดพลาดและความเป็นส่วนตัว

- DB ต่อไม่ได้ → หน้า error ภาษาไทยพร้อมคำแนะนำให้รัน `setup_check.py` (ไม่แสดง stack trace) · `/healthz` คืน 503
- คิวรีส่วนใดล้ม → ส่วนนั้นแสดง "ดึงข้อมูลไม่ได้" ส่วนอื่นยังแสดงได้
- การเชื่อมต่อ `SET SESSION TRANSACTION READ ONLY` · ไม่มีข้อมูลรายคนในหน้าใด · ไม่เรียกบริการภายนอก (ฟอนต์/ไลบรารีเก็บใน static)

## 10. การทดสอบ

- `tests/test_metrics.py` (pytest, ไม่ใช้ DB): ช่วง GA ครบ 5 ช่วง (ขอบ 12/13, 20/21 …), GA จาก LMP เมื่อไม่มี pa_week, กลุ่มอายุ (19/20, 34/35, <15), ตัวหารคลอดในช่วง, ตัวหาร 0 → None, refer ช่วงหลังคลอด 42/43 วัน, refer Dx O ที่ไม่อยู่ในทะเบียน, ไม่นับ refer ซ้ำ, map รพ.สต. ไม่พบ → นอกเขต
- `tests/test_config.py`: parse env list/ตัวเลข, โหลด pcu_map ผิดรูปแบบ → error ชัดเจน
- รัน `setup_check.py` กับฐานจริงก่อนส่งมอบ แล้วเทียบตัวเลขเดือน ต.ค. 2569 กับรายงานงานฝากครรภ์

## 11. Deploy

`/opt/anc_dashboard` + `.venv` + `.env`(600) + gunicorn/systemd ที่พอร์ตว่าง (ตรวจตอน deploy) · sub-path `/anc/` ใน ssl.conf ก่อน catch-all · ทำตามสกิล `wnkhos-deploy` — แยกเป็นงานหลังแอปผ่านการตรวจ
