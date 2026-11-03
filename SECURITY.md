# ความปลอดภัย — ANC Dashboard

| เรื่อง | มาตรการ |
|---|---|
| ข้อมูลส่วนบุคคล | หน้าแดชบอร์ด, `/api/data.json`, ไฟล์ส่งออก JPG/PDF, หน้า `/check` และแม่แบบ `village_pcu.csv` แสดงเฉพาะจำนวนนับ ไม่มี HN / ชื่อ / เลขบัตร |
| หน้ารายชื่อ `/list` + Excel | มีชื่อ/HN — ต้อง login บัญชีรายคน (pbkdf2:sha256) · ผู้ใช้ รพ.สต. เห็นเฉพาะเขตตัวเอง · ล็อกเมื่อรหัสผิด 10 ครั้ง/ชื่อ หรือ 30 ครั้ง/IP ใน 15 นาที · CSRF · cookie HttpOnly/SameSite=Lax (+Secure เมื่อ `ANC_COOKIE_SECURE=1`) · session 8 ชม. · `Cache-Control: no-store` · audit log ทุกการ login/เปิดดู/ส่งออก (`manage.py audit`) · ไม่ตั้ง `ANC_SECRET_KEY` = ปิดทั้งหมด · `ANC_LIST_LAN_ONLY=1` = เฉพาะใน รพ. |
| หน้า `/check` | เปิดเฉพาะเครื่องใน LAN (IP ภายใน หรือ `ANC_LAN_NETS`) · ผ่าน Cloudflare ต้องเป็น IP ใน `ANC_LAN_NETS` · `ANC_CHECK_OPEN=1` เปิดทุกที่ (ไม่แนะนำ) |
| SQL | `d1`/`d2` ต้องเป็นวันที่จริง · รหัสทุกตัวส่งเป็นพารามิเตอร์ · ชื่อคอลัมน์เวลา (`ANC_WAIT_*`) รับเฉพาะ `vsttime`/`service1–20` |
| ฐานข้อมูล | บัญชีอ่านอย่างเดียว + `SET SESSION TRANSACTION READ ONLY` + timeout (`ANC_DB_TIMEOUT`) · `setup_check.py` ขึ้น ✘ ถ้าบัญชีมีสิทธิ์เขียนบนฐาน HOSxP |
| ภาระฐานข้อมูล | ช่วงวันที่สูงสุด `ANC_MAX_DAYS` (731) · แคชผล `ANC_CACHE_SECONDS` (600) |
| ส่งออกไฟล์ | ทีละงานทั้งเครื่อง · chromium เปิดได้เฉพาะ `127.0.0.1` · ปิดได้ด้วย `ANC_EXPORT=0` |
| Header | nosniff, Referrer-Policy, X-Frame-Options, CSP (โหลดได้เฉพาะจากเว็บตัวเอง) · `X-Forwarded-Prefix` รับเฉพาะ path ภายใน |
| ความลับ | รหัสฐานข้อมูลและ `ANC_SECRET_KEY` อยู่ใน `.env` (chmod 600/640) · บัญชีผู้ใช้ใน `data/` — ไม่อยู่ใน repo/zip/image |

รายงานช่องโหว่: แจ้งผู้พัฒนาโดยตรง (ช่องทางท้ายหน้าแดชบอร์ด) ไม่เปิดเป็น issue สาธารณะ
