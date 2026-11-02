# ANC Dashboard — แดชบอร์ดงานฝากครรภ์ (HOSxP · นิยามตาม 43 แฟ้ม)

หน้า infographic เดียวโทนชมพู (รูปแบบเดียวกับ ER Dashboard) อ่านข้อมูลสดจาก HOSxP แบบอ่านอย่างเดียว
แสดงเฉพาะจำนวนนับ ไม่มีข้อมูลรายคน — วิธีติดตั้งและ **ขั้นตอนตรวจก่อนใช้** ดู [INSTALL.md](INSTALL.md)

## หน้าจอ

1. ANC KPI Summary · 2. แนวโน้มรายเดือน · 3. ตัวชี้วัดคุณภาพ 10 ตัว (ผลงาน/เป้า/ผ่าน)
4. กลุ่มอายุ Teenage (< 20; ย่อย < 15, 15–19) · วัยเจริญพันธุ์ (20–34) · Elderly gravida (≥ 35) — อายุ ณ วันลงทะเบียนฝากครรภ์
5. แยกตาม รพ.สต. (ตำบล + หมู่ของแม่ ผ่าน `village_pcu.csv` แบบเดียวกับ mental_health_dashboard)
6–9. Refer รายเดือน: กลุ่มอายุ · Top 10 Dx · ปลายทาง · ตารางเดือน × กลุ่ม Dx × ปลายทาง · 10. Alert & Action
หน้า `/check` = Data Audit · ปุ่มส่งออก JPG/PDF

## นิยามตัวชี้วัด (หน่วยนับ = ครรภ์)

**ข้อมูลบริการ** (การ์ดด้านบน ไม่ใช่ตัวชี้วัด): ฝากครรภ์รายใหม่ (`person_anc.anc_register_date` ในช่วง) ·
ครั้งบริการ ANC และเฉลี่ยต่อเดือน (`person_anc_service` ในช่วง)

ตัวชี้วัด 5 ตัวแรกตามเอกสารในโฟลเดอร์ `kpi/` (กรมอนามัย / HDC)

**ตัวหารในเขต (ค่าเริ่มต้น)** ตามเอกสาร KPI: หญิงไทย (`ANC_THAI_NATIONALITY`) ที่อาศัยในอำเภอ (`ANC_CHWPART`/`ANC_AMPPART`)
หรืออยู่นอกเขตแต่มาคลอดที่ รพ. (`person_anc.labour_hospcode` = `ANC_HOSPCODE`) · ปุ่ม "ตัวหาร: ทั้งหมด" = ทุกครรภ์ในทะเบียน
· ใช้กับ KPI ที่หารด้วยครรภ์ที่คลอด ส่วนข้อมูลบริการ ไอโอดีน (Workload) LBW และ refer นับทั้งหมด
· ถ้าบันทึกวันคลอดใน `person_anc` น้อยกว่า `ANC_LABOR_WARN_PCT` (80%) ของครรภ์ที่ครบกำหนด จะขึ้นเตือนบนแดชบอร์ด

| ตัวชี้วัด | นิยาม | เป้า | 43 แฟ้ม | ตาราง HOSxP |
|---|---|---|---|---|
| ฝากครรภ์ครั้งแรก ≤ 12 wk | ANC ครั้งแรก (รวมที่อื่น) GA ≤ 12 ÷ ครรภ์ที่คลอดในช่วง | ≥ 75 | ANC.GA | `person_anc_service.pa_week`, `person_anc_other_precare` |
| ANC ครบ 5 ครั้งตามเกณฑ์ | มี visit ทุกช่วง GA ≤12, 13–<20, 20–<26, 26–<32, 32–40 ÷ ครรภ์ที่คลอด | ≥ 75 | ANC.GA + LABOR | เหมือนข้างบน |
| ANC ครบ 8 ครั้งตามเกณฑ์ (เอกสาร 1.7) | มี visit ทุกช่วง GA ≤12 · 13–20 · 21–26 · 27–30 · 31–34 · 35–36 · 37–38 · 39–40 สัปดาห์ ÷ ครรภ์ที่คลอด | ตามปีงบ: 2566 = 50 · 2567 = 55 · 2568 = 60 · **2569 = 65** · 2570 = 70 (ตั้งเองด้วย `ANC_TARGET_VISIT8`) | ANC.GA + LABOR | เหมือนข้างบน |
| ดูแลหลังคลอดครบ 3 ครั้ง | ได้ดูแลวันที่ 1–7, 8–15, 16–42 หลังคลอดครบ ÷ คลอดในช่วงและพ้น 42 วัน | ≥ 75 | POSTNATAL | `person_anc_preg_care.care_date`, `person_anc.post_labor_service1–3_date` |
| ฝากครรภ์คุณภาพ (HDC) | ครบ 5 กิจกรรม: CBC/Hct/Hb · ธาลัสซีเมีย · อัลตราซาวด์ 88.78 · ดาวน์ Z36.0/Z36.2 · เบาหวาน (GCT/OGTT/FBS/DTX หรือ Z13.1) ÷ ครรภ์ที่คลอด | ≥ 70 (ปีงบ 2570) | LABFU, PRENATAL, PROCEDURE_OPD, DIAGNOSIS_OPD | `lab_head`/`lab_order`, `person_anc_lab`, `thalassaemia_result`, `doctor_operation`, `ovstdiag` |
| ยาเม็ดไอโอดีน (Workload) | ได้ยาที่มีไอโอดีน (รหัสยา 24 หลัก `ANC_IODINE_DIDSTD`) ระหว่างตั้งครรภ์ ÷ ครรภ์ที่มาฝากครรภ์ที่ รพ. ในช่วง | ไม่กำหนด | DRUG_OPD.DIDSTD | `opitemrece`, `drugitems.did` |
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
