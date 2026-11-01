# ANC Dashboard — แดชบอร์ดงานฝากครรภ์ (HOSxP · นิยามตาม 43 แฟ้ม)

หน้า infographic เดียวโทนชมพู (รูปแบบเดียวกับ ER Dashboard) อ่านข้อมูลสดจาก HOSxP แบบอ่านอย่างเดียว
แสดงเฉพาะจำนวนนับ ไม่มีข้อมูลรายคน — วิธีติดตั้งและ **ขั้นตอนตรวจก่อนใช้** ดู [INSTALL.md](INSTALL.md)

## หน้าจอ

1. ANC KPI Summary · 2. แนวโน้มรายเดือน · 3. ตัวชี้วัดคุณภาพ 10 ตัว (ผลงาน/เป้า/ผ่าน)
4. กลุ่มอายุ Teenage (< 20; ย่อย < 15, 15–19) · วัยเจริญพันธุ์ (20–34) · Elderly gravida (≥ 35) — อายุ ณ วันลงทะเบียนฝากครรภ์
5. แยกตาม รพ.สต. (จัดตามหมู่บ้านที่อยู่ของแม่ ผ่าน `pcu_map.csv`)
6–9. Refer รายเดือน: กลุ่มอายุ · Top 10 Dx · ปลายทาง · ตารางเดือน × กลุ่ม Dx × ปลายทาง · 10. Alert & Action
หน้า `/check` = Data Audit · ปุ่มส่งออก JPG/PDF

## นิยามตัวชี้วัด (หน่วยนับ = ครรภ์)

| ตัวชี้วัด | นิยาม | 43 แฟ้ม | ตาราง HOSxP |
|---|---|---|---|
| ฝากครรภ์รายใหม่ | ลงทะเบียนครรภ์ในช่วง | ANC | `person_anc.anc_register_date` |
| ครั้งบริการ ANC / เฉลี่ยต่อเดือน | visit ANC ที่ รพ. ในช่วง | ANC | `person_anc_service` |
| ฝากครรภ์ก่อน 12 wk | ANC ครั้งแรก (รวมที่อื่น) GA ≤ 12 ÷ ครรภ์ที่คลอดในช่วง | ANC.GA | `person_anc_service.pa_week`, `person_anc_other_precare` |
| ANC ครบ 5 ครั้ง | มี visit ทุกช่วง GA ≤12, 13–20, 21–26, 27–32, 33–40 ÷ ครรภ์ที่คลอด | ANC.GA + LABOR | เหมือนข้างบน |
| วัคซีน dT | ได้ dT (รหัส `ANC_DT_VACCINE_CODES`) ระหว่าง LMP–คลอด ÷ ครรภ์ที่คลอด | EPI | `ovst_vaccine`, `person_vaccine`, `person_anc.vaccine_dtanc*_date` |
| ตรวจช่องปาก | ตรวจฟันระหว่างตั้งครรภ์ ÷ ครรภ์ที่คลอด | DENTAL | `dtmain.pregnancy='Y'`, `person_anc.dental_tx_date` |
| โลหิตจางใกล้คลอด | Hct < 33% ที่ GA ≥ 28 ÷ ครรภ์ที่คลอดและมีผล | PRENATAL.HCT_RESULT | `person_anc_lab`, `person_anc.blood_hct_result` |
| ทารก LBW | น้ำหนักแรกเกิด < 2,500 g ÷ เกิดมีชีพใน รพ. | NEWBORN.BWEIGHT | `ipt_labour_infant` |
| เวลารอคอยเฉลี่ย | มาถึง → เริ่มตรวจ (นาที) | **นอก 43 แฟ้ม** | `service_time` |
| Refer | อยู่ในทะเบียนฝากครรภ์ช่วง LMP ถึงหลังคลอด 42 วัน **หรือ** Dx หลัก O00–O99 / Z32–Z36 | REFER_HISTORY | `referout` |

ตัวหาร 0 แสดง “—” · ตัวหาร < 5 แสดงจาง (ฐานน้อย ตีความระวัง) · ค่าทุกตัวตั้งได้ใน `.env` (ดู `.env.example`)

## พัฒนา

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python app.py            # http://127.0.0.1:6300/
python render.py --fmt jpg
python build_dist.py     # dist/anc_dashboard-<version>.zip
```

โครงสร้าง: `queries.py` ดึงแถวระดับครรภ์/visit/ทารก/refer · `metrics.py` คำนวณทุกตัวเลข (ไม่แตะฐานข้อมูล ทดสอบได้)
· `check.py` Data Audit · `config.py` ค่าตั้ง · `app.py` หน้าเว็บ · spec/แผนอยู่ใน `docs/superpowers/`
