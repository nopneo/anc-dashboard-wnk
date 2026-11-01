"""ตั้งค่าร่วมของ test — ไม่ต่อฐานข้อมูลจริง"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANC_HOSPITAL_NAME", "โรงพยาบาลทดสอบ")     # ไม่ต้องอ่าน opdconfig
