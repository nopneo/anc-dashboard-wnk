# Changelog

## 0.1.0 — 2569-11-01

- เริ่มต้น: แดชบอร์ดงานฝากครรภ์ 10 ส่วน ธีมชมพู · ตัวชี้วัด ANC 10 ตัวตามนิยาม 43 แฟ้ม
- แยกกลุ่มอายุ Teenage / วัยเจริญพันธุ์ / Elderly gravida และแยกตาม รพ.สต. ผ่าน `village_pcu.csv` (แบบ mental_health_dashboard)
- สรุป refer รายเดือน: Dx, ปลายทาง (รวมรหัส 5/9 หลักของ รพ. เดียวกัน), เวลาจากรับบริการถึง refer
- ชุดตรวจก่อนใช้: `setup_check.py`, หน้า `/check` + แม่แบบ `village_pcu.csv`, แถบเตือนจนกว่า `ANC_DATA_AUDITED=1`
- ส่งออก JPG/PNG/PDF, Docker, ชุดติดตั้ง `build_dist.py`
