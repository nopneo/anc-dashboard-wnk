# ANC Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** แดชบอร์ดงานฝากครรภ์ (Flask, ธีมชมพู) อ่าน HOSxP สด แสดงตัวชี้วัด ANC 10 ตัว แยกกลุ่มอายุ/รพ.สต. และสรุป refer รายเดือน พร้อมชุด "ตรวจก่อนใช้"

**Architecture:** แยกโครงจาก `E:\App\Hos 212\er_dashboard` (คัดลอก db/cache/render/PrefixMiddleware/ส่งออก) · `queries.py` ดึงแถวระดับครรภ์/visit/ทารก/refer เป็น dict ธรรมดา · `metrics.py` เป็นฟังก์ชันบริสุทธิ์ที่คำนวณทุกตัวเลข (ทดสอบโดยไม่มี DB) · `app.py` ประกอบ context ให้ Jinja

**Tech Stack:** Python 3.11+, Flask 3, PyMySQL, python-dotenv, Pillow, gunicorn/waitress, pytest · Chrome/Edge สำหรับส่งออก

**Spec:** `docs/superpowers/specs/2026-11-01-anc-dashboard-design.md`

## Global Constraints

- อ่านอย่างเดียว: ทุกการเชื่อมต่อ `SET SESSION TRANSACTION READ ONLY`; ห้าม INSERT/UPDATE/DELETE
- ห้ามแสดงชื่อ HN CID หรือข้อมูลรายคนในหน้าใด/ไฟล์ส่งออกใด/`/check`/แม่แบบ CSV
- ห้ามรหัสตายตัวใน SQL — รหัสทุกตัวมาจาก `config.Config` และส่งเป็นพารามิเตอร์ (`%%` สำหรับ `%` ตัวอักษร)
- ไม่เรียกบริการภายนอก: ฟอนต์/ไลบรารี/รูปอยู่ใน `static/`
- env prefix `ANC_` (ยกเว้น `DB_*`, `PORT`) · ค่าเริ่มต้นตาม spec §8
- กลุ่มอายุ: teen <20 (ย่อย lt15 <15, 15_19), repro 20–34, elder ≥35 — อายุเต็มปี ณ `anc_register_date`
- ช่วง GA ครบ 5 ครั้ง: (≤12), (13–20), (21–26), (27–32), (33–40) สัปดาห์
- เป้าเริ่มต้น: early12 ≥75 · visit5 ≥75 · dt ≥90 · dental ≥50 · anemia ≤14 · lbw ≤7 (%)
- ตัวหาร 0 → `None` → แสดง "—" · ตัวหาร < 5 → แสดงจาง + tooltip "ฐานน้อย ตีความระวัง"
- ธีม: `--pink-900:#880E4F --pink-700:#C2185B --pink-400:#F06292 --pink-100:#F8BBD0 --bg:#FFF5F8`
- VERSION เริ่ม `0.1.0` · LICENSE MIT · DEV_CONTACT เหมือน er_dashboard
- รันทดสอบ: `python -m pytest -q` จากโฟลเดอร์ `ANC_dashboard`

## Review Focus

1. ครรภ์ไม่มี LMP และ visit ไม่มี `pa_week` → GA = None, ไม่ล้ม, ไม่ตกช่วงใด (Task 2 `test_visit_without_ga_is_ignored`)
2. ผู้หญิงคนเดียวมี 2 ครรภ์ในฐาน และ refer ระหว่างครรภ์ที่ 2 → นับครั้งเดียว ใช้หน้าต่างของครรภ์ใดก็ได้ที่ครอบ (Task 3 `test_refer_counted_once_with_two_pregnancies`)
3. `pcu_map.csv` มี BOM/ช่องว่าง/รหัส 7 หลักที่ Excel ตัดเลข 0 หน้า → เติม 0 ให้ครบ 8 หลักและอ่านได้ (Task 1 `test_pcu_map_excel_quirks`)
4. ช่วงวันที่ไม่มีข้อมูลเลย → ทุกส่วนแสดง "—"/ว่าง ไม่ใช่ error 500 (Task 5 `test_dashboard_empty_range`)
5. คิวรีส่วน refer ล้ม (เช่น timeout) → ส่วนอื่นยังแสดง และส่วน refer แสดง "ดึงข้อมูลไม่ได้" (Task 5 `test_section_failure_isolated`)

---

### Task 1: โครงโปรเจกต์ + config

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt` (คัดลอกจาก er_dashboard; ตัด openpyxl), `db.py` (คัดลอก เปลี่ยน `ER_DB_MODE/ER_SSH_HOST/ER_DB_TIMEOUT` → `ANC_*`), `cache.py` (คัดลอก), `static/fonts/*`, `static/img/hospital_logo.png`, `static/img/logo.png` (คัดลอก), `config.py`, `pcu_map.example.csv`, `.env.example`, `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `config.Config` (frozen dataclass): `dt_codes: tuple[str,...]`, `hct_lab_ids: tuple[int,...]` (ว่างได้), `hct_cutoff: float`, `hct_late_ga: int`, `lbw_grams: int`, `postpartum_days: int`, `refer_dx_prefixes: tuple[str,...]`, `wait_from_col: str` (ค่าเริ่มต้น `"vsttime"`), `wait_to_col: str` (`"service5"`), `wait_max_min: int`, `targets: dict[str, float]` (คีย์ `early12 visit5 dt dental anemia lbw`), `pcu_map_path: str`, `data_audited: bool`, `cache_seconds: int`
  - `config.load_config(env: Mapping[str,str] = os.environ) -> Config`
  - `config.PcuMapError(Exception)`
  - `config.load_pcu_map(path: str) -> dict[str, tuple[str, str]] | None` — village_code(8) → (pcu_hospcode, pcu_name); ไฟล์ไม่มี → `None`
  - `config.village_code(chw, amp, tmb, moo) -> str | None` — ต่อเป็น 8 หลัก (เติม 0 ซ้ายทีละส่วน 2 หลัก) ส่วนใดว่าง → None

- [ ] **Step 1: เขียนเทสต์ที่ล้ม** ใน `tests/test_config.py`

```python
def test_defaults():
    c = load_config({})
    assert c.dt_codes == ("201","202","203","204","205")
    assert c.hct_cutoff == 33 and c.hct_late_ga == 28 and c.lbw_grams == 2500
    assert c.postpartum_days == 42
    assert c.refer_dx_prefixes == ("O","Z32","Z33","Z34","Z35","Z36")
    assert c.targets == {"early12":75,"visit5":75,"dt":90,"dental":50,"anemia":14,"lbw":7}
    assert c.wait_from_col == "vsttime" and c.wait_to_col == "service5"

def test_list_and_bad_col():
    c = load_config({"ANC_DT_VACCINE_CODES":" 201, 101 ,", "ANC_WAIT_TO_COL":"drop table"})
    assert c.dt_codes == ("201","101")
    assert c.wait_to_col == "service5"   # ไม่ผ่าน whitelist vsttime|service\d{1,2} → ค่าเริ่มต้น

def test_pcu_map_missing_returns_none(tmp_path):
    assert load_pcu_map(str(tmp_path/"none.csv")) is None

def test_pcu_map_excel_quirks(tmp_path):
    p = tmp_path/"m.csv"
    p.write_text("\ufeffvillage_code,pcu_hospcode,pcu_name\n 3025010 ,03929, รพ.สต.ไทยสามัคคี \n", encoding="utf-8")
    assert load_pcu_map(str(p)) == {"03025010": ("03929", "รพ.สต.ไทยสามัคคี")}

def test_pcu_map_bad_header(tmp_path):
    p = tmp_path/"m.csv"; p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(PcuMapError): load_pcu_map(str(p))

def test_village_code():
    assert village_code("30","25","1","3") == "30250103"
    assert village_code("30","25",None,"3") is None
```

- [ ] **Step 2:** `python -m pytest tests/test_config.py -q` → FAIL (ModuleNotFoundError: config)
- [ ] **Step 3:** สร้างไฟล์คัดลอกตามรายการ แล้วเขียน `config.py` ตาม Interfaces (`csv` + `encoding="utf-8-sig"`, `.strip()` ทุกช่อง, `zfill(8)` ให้ village_code ที่เป็นตัวเลข 7 หลัก) · `.env.example` ระบุทุกตัวแปรใน spec §8 พร้อมคำอธิบายภาษาไทย · `pcu_map.example.csv` มีหัว + 2 แถวตัวอย่าง · `tests/conftest.py` ใส่ path โฟลเดอร์โปรเจกต์ลง `sys.path`
- [ ] **Step 4:** `python -m pytest tests/test_config.py -q` → 6 passed
- [ ] **Step 5:** `git add -A && git commit -m "feat: project skeleton and config"`

---

### Task 2: metrics — ตัวชี้วัด ANC และกลุ่มอายุ

**Files:**
- Create: `metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `config.Config`
- Produces (แถวข้อมูลเป็น dict ที่ `queries.py` ใน Task 5 ต้องคืนให้ตรงคีย์):
  - Pregnancy: `{"anc_id":int, "hn":str, "age":int|None, "village":str|None, "register_date":date, "lmp":date|None, "labor_date":date|None, "hct_late":float|None, "has_dt":bool, "has_dental":bool}`
  - Visit: `{"anc_id":int, "date":date, "ga":int|None}` (รวม precare ที่อื่น)
  - Infant: `{"birth_date":date, "weight":int|None, "alive":bool, "village":str|None}` (village = หมู่บ้านของแม่ จาก `ipt_labour.hn`)
  - `age_group(age: int|None) -> str|None` → `"teen"|"repro"|"elder"`; `teen_sub(age) -> "lt15"|"15_19"|None`
  - `visit_ga(visit: dict, lmp: date|None) -> int|None` — `ga` ถ้ามี ไม่งั้น `(date-lmp).days // 7` ถ้ามี lmp ไม่งั้น None
  - `ga_bucket(week: int|None) -> int|None` → 0..4
  - `pct(num: int, den: int) -> float|None` (ปัด 1 ตำแหน่ง)
  - `months_in_range(d1: date, d2: date) -> float` — ผลรวม (วันในช่วงของเดือนนั้น / วันของเดือนนั้น)
  - `IND_KEYS = ("new","visits","per_month","early12","visit5","dt","dental","anemia","lbw","wait")`
  - `indicators(pregs, visits, infants, waits: list[float], d1, d2, cfg) -> dict[str, dict]` แต่ละค่า `{"num":…, "den":…|None, "value":float|None, "target":float|None, "ok":bool|None, "low_base":bool}` · `ok` ของ anemia/lbw = value ≤ target, ตัวอื่น ≥ target
  - `by_age(pregs, visits, d1, d2, cfg) -> dict[str, dict]` คีย์ `teen repro elder` แต่ละอัน `{"new":int, "share":float|None, "early12":dict, "visit5":dict, "anemia":dict, "lt15":int, "15_19":int}` (สองคีย์หลังมีเฉพาะ teen)
  - `tracking(pregs, visits, d2) -> {"open":int, "early12_so_far":int}` — ครรภ์ลงทะเบียนแล้วยังไม่คลอด ณ d2

- [ ] **Step 1: เขียนเทสต์ที่ล้ม** — สร้างตัวช่วย `preg(**kw)` / `visit(anc_id, d, ga)` ในไฟล์เทสต์ แล้ว:

```python
def test_age_groups():
    assert [age_group(a) for a in (14,19,20,34,35,None)] == ["teen","teen","repro","repro","elder",None]
    assert teen_sub(14)=="lt15" and teen_sub(15)=="15_19" and teen_sub(20) is None

def test_ga_bucket_edges():
    assert [ga_bucket(w) for w in (4,12,13,20,21,26,27,32,33,40,41,None)] == [0,0,1,1,2,2,3,3,4,4,None,None]

def test_visit_without_ga_is_ignored():
    assert visit_ga({"anc_id":1,"date":date(2026,3,1),"ga":None}, None) is None
    assert visit_ga({"anc_id":1,"date":date(2026,3,1),"ga":None}, date(2026,1,1)) == 8

def test_visit5_requires_all_buckets():
    # ครรภ์ 1 ครบ 5 ช่วง, ครรภ์ 2 ขาดช่วง 21–26 — ทั้งคู่คลอดในช่วง
    r = indicators(pregs, visits, [], [], D1, D2, CFG)["visit5"]
    assert (r["num"], r["den"], r["value"]) == (1, 2, 50.0)

def test_denominator_is_delivered_in_range():
    # ครรภ์ที่ labor_date อยู่นอกช่วง หรือ None ไม่อยู่ในตัวหาร early12/visit5/dt/dental
def test_early12_uses_earliest_visit_including_precare():
def test_anemia_denominator_only_with_result():
    # hct_late 32.5 → นับ, 35 → ไม่นับ, None → ไม่อยู่ในตัวหาร; ok เมื่อ value <= 14
def test_lbw_live_births_only():
    # weight 2499 alive → นับ, 2500 → ไม่, dead → ไม่อยู่ในตัวหาร, weight None → ไม่อยู่ในตัวหาร
def test_zero_denominator_is_none():
    r = indicators([], [], [], [], D1, D2, CFG)
    assert r["early12"]["value"] is None and r["early12"]["ok"] is None and r["wait"]["value"] is None
def test_low_base_flag():
    # den 4 → low_base True, den 5 → False
def test_months_in_range():
    assert months_in_range(date(2026,10,1), date(2026,10,31)) == 1.0
    assert round(months_in_range(date(2026,10,1), date(2026,11,15)),2) == 1.5
def test_by_age_split():
def test_tracking_open_pregnancies():
```

ทุกเทสต์ที่ระบุแค่ comment ให้เขียน assert ตัวเลข num/den/value จากข้อมูลที่สร้างในเทสต์นั้น

- [ ] **Step 2:** `python -m pytest tests/test_metrics.py -q` → FAIL
- [ ] **Step 3:** เขียน `metrics.py` ตาม Interfaces — visits ของครรภ์จัดกลุ่มด้วย `anc_id` ครั้งเดียว (`dict[int, list]`) · `wait` = ค่าเฉลี่ยของ `waits` (กรองแล้วใน queries) ปัด 1 ตำแหน่ง · `new` = ครรภ์ที่ `register_date` อยู่ในช่วง · `visits` = visit ในช่วงที่ไม่ใช่ precare (Visit มีคีย์เสริม `"precare":bool`)
- [ ] **Step 4:** `python -m pytest tests/test_metrics.py -q` → ผ่านทั้งหมด
- [ ] **Step 5:** `git commit -am "feat: ANC indicators and age groups"` (เพิ่มไฟล์ใหม่ด้วย `git add`)

---

### Task 3: metrics — refer และ รพ.สต.

**Files:**
- Modify: `metrics.py`
- Test: `tests/test_metrics_refer.py`, `tests/test_metrics_pcu.py`

**Interfaces:**
- Consumes: Pregnancy/Visit/Infant จาก Task 2, `load_pcu_map` ผลลัพธ์จาก Task 1
- Produces:
  - Refer row (จาก queries): `{"refer_id":int, "date":date, "hn":str, "pdx":str|None, "dx_name":str|None, "dest":str|None, "dest_name":str|None, "age":int|None, "village":str|None, "minutes":float|None}`
  - `select_refers(refers, pregs, cfg) -> list[dict]` — คืน refer ที่เข้าเงื่อนไข เพิ่มคีย์ `"reason": "registry"|"dx"|"both"` และ `"group": age_group(...)`; หน้าต่างครรภ์ = `[lmp, labor_date + postpartum_days]` หรือ `[lmp, lmp + 44*7 วัน]` ถ้ายังไม่คลอด; ครรภ์ไม่มี lmp → ใช้เงื่อนไข Dx อย่างเดียว; ไม่ซ้ำตาม `refer_id`
  - `refer_summary(refers_selected, d1, d2) -> {"monthly": list[{"month":"2026-10","teen":int,"repro":int,"elder":int,"unknown":int}], "top_dx": list[{"code3":str,"name":str|None,"n":int,"pct":float}] (≤10), "dest": list[{"code":str,"name":str,"n":int}], "table": list[{"month":str,"chapter":str,"dest_name":str,"n":int,"avg_min":float|None}], "total":int}` — `chapter` = `"O"` สำหรับ O*, `"Z3x"` สำหรับ Z32–Z36, อื่น ๆ = ตัวอักษรแรกของ pdx, ไม่มี pdx = `"ไม่ระบุ"`; ทุกเดือนในช่วงต้องมีแถวใน monthly แม้เป็น 0
  - `UNMAPPED = ("", "นอกเขต/ไม่ระบุ")`
  - `pcu_of(village: str|None, pcu_map: dict) -> tuple[str,str]`
  - `by_pcu(pregs, visits, infants, refers_selected, d1, d2, cfg, pcu_map) -> list[dict]` แต่ละแถว `{"hospcode","name","new","teen","repro","elder","early12":dict,"visit5":dict,"dt":dict,"anemia":dict,"lbw":dict,"refer":int}` เรียงตามชื่อ แถว UNMAPPED อยู่ท้ายเสมอ (แสดงแม้เป็น 0 เมื่อมีรายการ unmapped)
  - `unmapped_villages(pregs, pcu_map) -> list[tuple[str,int]]` (รหัสหมู่บ้าน, จำนวนครรภ์) เรียงจำนวนมากไปน้อย
  - `alerts(ind, pcu_rows, age, unmapped) -> list[{"level":"red"|"amber"|"info","text":str,"owner":str,"action":str}]` — ตัวชี้วัดที่ `ok is False` (red), รพ.สต. ที่ early12 หรือ visit5 ต่ำกว่าเป้าและ den ≥5 (amber), แม่อายุ <15 ≥1 ราย (red), unmapped ≥1 (info)

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

```python
def test_refer_registry_window_postpartum_42():
    # labor 2026-05-01: refer 2026-06-12 (วันที่ 42) นับ, 2026-06-13 ไม่นับ (pdx ไม่ใช่ O)
def test_refer_dx_only_not_in_registry():
    # hn ไม่อยู่ในทะเบียน pdx "O800" → reason "dx", group จาก age ของ refer
def test_refer_counted_once_with_two_pregnancies():
    # hn เดียว 2 ครรภ์ หน้าต่างซ้อนกัน + pdx O → คืน 1 แถว reason "both"
def test_refer_no_lmp_falls_back_to_dx():
def test_refer_summary_months_filled_and_chapters():
    # ช่วง ต.ค.–ธ.ค. มี refer เฉพาะ พ.ย. → monthly 3 แถว; chapter ของ "Z340" == "Z3x", "O14" == "O", None == "ไม่ระบุ"
def test_top_dx_limit_10_by_3char():
def test_pcu_unmapped_last():
def test_by_pcu_counts_and_rates():
def test_unmapped_villages_sorted():
def test_alerts_rules():
```

เขียน assert ตัวเลขจริงตามข้อมูลที่สร้างในแต่ละเทสต์

- [ ] **Step 2:** `python -m pytest tests/test_metrics_refer.py tests/test_metrics_pcu.py -q` → FAIL
- [ ] **Step 3:** เพิ่มฟังก์ชันใน `metrics.py` · `by_pcu` เรียก `indicators`-ย่อยเดิมต่อกลุ่ม (แยก helper `_rate_*` จาก Task 2 ให้ใช้ซ้ำได้ ไม่เขียนสูตรซ้ำ)
- [ ] **Step 4:** `python -m pytest -q` → ผ่านทั้งหมด
- [ ] **Step 5:** commit `"feat: refer selection, PCU breakdown, alerts"`

---

### Task 4: queries — SQL ดึงข้อมูลจาก HOSxP

**Files:**
- Create: `queries.py`
- Test: `tests/test_queries.py`

**Interfaces:**
- Consumes: `db.fetch(sql, args)`, `config.Config`, `config.village_code`
- Produces (ทุกตัวรับ `d1: date, d2: date, cfg: Config` และคืน list ของ dict ตาม Task 2/3 ด้วยชนิดที่แปลงแล้ว — date เป็น `datetime.date`, ตัวเลขผ่าน `db.num`):
  - `pregnancies(d1, d2, cfg)` — ครรภ์ที่ `anc_register_date <= d2` และ (`labor_date is null` หรือ `labor_date >= d1 - 44 สัปดาห์`) จาก `person_anc` join `person` join `patient` (`patient.hn = person.patient_hn`) · `age` = `timestampdiff(year, patient.birthday, anc_register_date)` · `village` ผ่าน `village_code(chwpart, amppart, tmbpart, moopart)` · `has_dt` = มี `vaccine_dtanc1..5_date` หรือมี `ovst_vaccine`→`person_vaccine.export_vaccine_code in cfg.dt_codes` ของ hn ระหว่าง lmp..coalesce(labor_date, d2) · `has_dental` = `dental_tx_date` หรือ `dtmain.pregnancy='Y'` ช่วงเดียวกัน · `hct_late` = ผลล่าสุดจาก `person_anc_lab` (`anc_lab_id in cfg.hct_lab_ids`, ว่าง → id จาก `anc_lab` ที่ชื่อ `like '%%hct%%'`) ของ `person_anc_service` ที่ `pa_week >= cfg.hct_late_ga`; ไม่พบ → แปลง `person_anc.blood_hct_result` เมื่อ `blood_check2_date` ไม่ null
  - `visits(anc_ids: list[int])` — `person_anc_service` (`ga = pa_week`) ∪ `person_anc_other_precare` (`ga = None`, `precare = True`) · แบ่งเป็นชุดละ 500 id
  - `infants(d1, d2)` — `ipt_labour_infant` ที่ `birth_date` ในช่วง · `alive` = ไม่มีบันทึกเสียชีวิตใน `ipt_newborn.dead` (join ด้วย `infant_an = an`) · `village` ของแม่จาก `ipt_labour.hn` → `patient`
  - `waits(d1, d2, cfg)` — นาทีจาก `cfg.wait_from_col` ถึง `cfg.wait_to_col` ของ `service_time` ที่ vn อยู่ใน `person_anc_service` ช่วงนั้น · กรอง 0 < นาที ≤ `cfg.wait_max_min` · ชื่อคอลัมน์ใส่ใน SQL ได้เพราะผ่าน whitelist ใน config แล้ว
  - `refers(d1, d2)` — `referout` ช่วง `refer_date` join `patient` (age ณ refer_date, village) left join `hospcode` (ชื่อปลายทาง, คีย์ `refer_hospcode`) left join `icd101` (ชื่อ Dx) · `minutes` = นาทีจาก `ovst.vsttime` ถึง `referout.refer_time` (null ถ้าติดลบ)

- [ ] **Step 1: เขียนเทสต์ที่ล้ม** — monkeypatch `db.fetch` ให้บันทึก (sql, args) และคืนแถวปลอมแบบโหมด ssh (ค่าเป็น str):

```python
def test_pregnancies_converts_types(fake_fetch):
    fake_fetch.rows = [{"anc_id":"7","hn":"0001","age":"19","chwpart":"30","amppart":"25","tmbpart":"01","moopart":"03",
        "register_date":"2026-01-05","lmp":"2025-11-20","labor_date":None,"hct_late":"31.5","has_dt":"1","has_dental":"0"}]
    r = queries.pregnancies(D1, D2, CFG)[0]
    assert r["village"]=="30250103" and r["age"]==19 and r["lmp"]==date(2025,11,20) and r["has_dt"] is True

def test_codes_are_parameters_not_literals(fake_fetch):
    queries.pregnancies(D1, D2, CFG)
    sql, args = fake_fetch.calls[0]
    assert "201" not in sql and args["dt"] == CFG.dt_codes

def test_visits_batches_of_500(fake_fetch):
    queries.visits(list(range(1201)))
    assert len(fake_fetch.calls) == 3

def test_waits_filters_range(fake_fetch):
def test_refers_maps_columns(fake_fetch):
```

- [ ] **Step 2:** `python -m pytest tests/test_queries.py -q` → FAIL
- [ ] **Step 3:** เขียน `queries.py` · ทุกคิวรีใช้ `where … between %(d1)s and %(d2)s` · หัวไฟล์อธิบายแหล่งข้อมูลแต่ละตัวชี้วัด ↔ แฟ้ม 43 (แบบ er_dashboard/queries.py)
- [ ] **Step 4:** `python -m pytest -q` → ผ่าน
- [ ] **Step 5: ทดสอบกับฐานจริง (อ่านอย่างเดียวผ่าน ssh)**

Run: `python -c "import queries,config,metrics,datetime as d;c=config.load_config();D1,D2=d.date(2025,10,1),d.date(2026,9,30);p=queries.pregnancies(D1,D2,c);print(len(p), metrics.indicators(p,queries.visits([x['anc_id'] for x in p]),queries.infants(D1,D2),queries.waits(D1,D2,c),D1,D2,c))"` (ต้องตั้ง `ANC_SSH_HOST` ใน `.env`)
Expected: ไม่มี error · `new` อยู่ราว 200 · ทารก ~84 · ค่า % อยู่ในช่วง 0–100 · ใช้เวลารวม < 60 วินาที — พิมพ์เฉพาะตัวเลขรวม ไม่พิมพ์แถวรายคน

- [ ] **Step 6:** commit `"feat: HOSxP queries"`

---

### Task 5: app + หน้า dashboard ธีมชมพู

**Files:**
- Create: `app.py`, `templates/base.html`, `templates/dashboard.html`, `static/style.css`, `static/img/hero.jpg` (คัดลอกจาก er_dashboard)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `queries.*`, `metrics.*`, `config.load_config`, `config.load_pcu_map`, `cache` (คัดลอกจาก er_dashboard)
- Produces:
  - `app.build_context(d1: date, d2: date) -> dict` คีย์: `d1 d2 fetched_at ind age tracking pcu pcu_missing:bool refer alerts unmapped errors:dict[str,str] audited:bool` — แต่ละส่วน (`ind/age/tracking`, `pcu`, `refer`) ห่อด้วย `_safe(name, fn)` ที่จับ exception เก็บใน `errors[name]` แล้วคืนค่าว่าง
  - routes: `/` (query `d1`,`d2` รูปแบบ `YYYY-MM-DD`, ค่าเริ่มต้น 1 ต.ค. ของปีงบประมาณปัจจุบัน ถึงวันนี้, สูงสุด `ANC_MAX_DAYS`=731 วัน), `/api/data.json`, `/healthz` (200 `ok` / 503 เมื่อ DB ต่อไม่ได้)
  - คัดลอกจาก er_dashboard/app.py: `PrefixMiddleware`, `_security_headers` + CSP, `hospital_name()`, `_branding`, `_parse_date`, `_range`, `_fy_start`, `_from_lan`, `LAN_NETS`, `TRUSTED_PROXIES`, `_client_ip` (เปลี่ยน env prefix เป็น `ANC_`) — ไม่เอาส่วน nurse
  - เทมเพลต: เรียงส่วน 1–10 ตาม spec §6 · กราฟวาดด้วย SVG/CSS ล้วนแบบ er_dashboard · แถบเตือน `.audit-banner` แสดงเมื่อ `not audited` และ JS ตรวจ localStorage `anc_audited_<hospcode>` · class `.no-export` ซ่อนแถบเตือนเมื่อ `?export=1` หรือ `@media print`

- [ ] **Step 1: เขียนเทสต์ที่ล้ม** — monkeypatch ฟังก์ชันใน `queries` ให้คืนข้อมูลปลอม

```python
def test_dashboard_renders_sections(client, fake_data):
    html = client.get("/?d1=2026-10-01&d2=2026-10-31").get_data(as_text=True)
    for title in ("ANC KPI Summary","ตัวชี้วัดคุณภาพ","กลุ่มอายุ","แยกตาม รพ.สต.","Refer รายเดือน","Top 10 Refer Diagnoses","Refer Destinations","Alert & Action"):
        assert title in html

def test_dashboard_empty_range(client, empty_data):
    r = client.get("/?d1=2026-10-01&d2=2026-10-31"); assert r.status_code == 200 and "—" in r.get_data(as_text=True)

def test_section_failure_isolated(client, fake_data, monkeypatch):
    monkeypatch.setattr(queries, "refers", lambda *a: (_ for _ in ()).throw(TimeoutError()))
    html = client.get("/").get_data(as_text=True)
    assert "ดึงข้อมูลไม่ได้" in html and "ANC KPI Summary" in html

def test_no_patient_identifiers(client, fake_data):
    html = client.get("/").get_data(as_text=True)
    assert "HN-SECRET" not in html          # fake_data ใส่ hn = "HN-SECRET"

def test_banner_hidden_in_export(client, fake_data):
    assert "audit-banner" not in client.get("/?export=1").get_data(as_text=True)

def test_prefix_middleware(client, fake_data):
    html = client.get("/", headers={"X-Forwarded-Prefix":"/anc"}).get_data(as_text=True)
    assert 'href="/anc/static/style.css' in html

def test_bad_date_falls_back(client, fake_data):
def test_healthz_503_when_db_down(client, monkeypatch):
def test_pcu_section_shows_setup_hint_without_map(client, fake_data):
```

- [ ] **Step 2:** `python -m pytest tests/test_app.py -q` → FAIL
- [ ] **Step 3:** เขียน `app.py` และเทมเพลต/สไตล์ (token สีตาม Global Constraints, โครงการ์ด/ส่วนเลขกำกับเหมือน er_dashboard) — ใช้ skill `artifact-design`/`impeccable` ไม่จำเป็น; ยึดหน้าตา er_dashboard
- [ ] **Step 4:** `python -m pytest -q` → ผ่าน
- [ ] **Step 5: ดูหน้าจริง** — เพิ่ม `.claude/launch.json` (`python app.py`, port จาก `.env` ค่าเริ่มต้น 6300) เปิดด้วย browser pane ช่วง 2025-10-01..2026-09-30 ตรวจ: ไม่มี error ใน console, ทุกส่วนมีตัวเลข, กว้าง 375px ไม่มี scroll แนวนอน
- [ ] **Step 6:** commit `"feat: pink ANC dashboard page"`

---

### Task 6: หน้า /check (Data Audit) + แม่แบบ pcu_map

**Files:**
- Create: `check.py`, `templates/check.html`
- Modify: `app.py` (route `/check`, `/check/pcu_map_template.csv`)
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `db.fetch`, `config`, `metrics.unmapped_villages`, `app._from_lan`
- Produces:
  - `check.audit(d1, d2, cfg, pcu_map) -> dict` คีย์ `items: list[{"key":str,"title":str,"app_uses":str,"found":list[{"code":str,"name":str,"n":int}],"status":"ok"|"warn"|"bad","env":str,"hint":str}]` และ `completeness: list[{"title":str,"pct":float|None,"status":str}]`
    - items: `dt_codes` (found = ทุก `export_vaccine_code` ของวัคซีนที่ชื่อมี dT/TT หรือรหัส 1xx/2xx ในช่วง; warn เมื่อพบรหัสนอก `cfg.dt_codes` ที่ให้กับหญิงอายุ 15–49 ≥ จำนวนที่ใช้), `hct_lab_ids` (found = `anc_lab` ทั้งหมด + จำนวนผลในช่วง; bad เมื่อ id ที่ใช้ไม่มีผลเลย), `anc_service_type` (found = ค่าที่พบ), `refer_dest_unnamed` (ปลายทางที่ไม่มีใน `hospcode`; warn เมื่อ >0), `refer_dx` (จำนวน refer ตามเหตุ registry/dx/both), `wait_cols` (สัดส่วน visit ANC ที่มีค่าในแต่ละคอลัมน์ `service1..20`; bad เมื่อคอลัมน์ที่ใช้ <10%), `pcu_map` (bad เมื่อไม่มีไฟล์, warn เมื่อ unmapped >5% ของครรภ์)
    - completeness: % ครรภ์มี LMP, % ครรภ์คลอดในช่วงที่มี labor_date, % ทารกมีน้ำหนัก, % ครรภ์คลอดที่มีผล Hct, % ครรภ์ที่ map รพ.สต. ได้ (warn <95, bad <80; Hct warn <50)
  - `/check` เปิดได้เมื่อ `_from_lan()` หรือ `ANC_CHECK_OPEN=1` ไม่งั้น 404 · ปุ่ม "ยืนยันว่าตรวจแล้ว" ตั้ง localStorage `anc_audited_<hospcode>`
  - `/check/pcu_map_template.csv` — คอลัมน์ `village_code,pcu_hospcode,pcu_name,tambon,moo,pregnancies` (UTF-8 BOM) เติม pcu ที่ map แล้ว · ไม่มีคอลัมน์รายคน

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

```python
def test_check_lan_only(client):  # REMOTE_ADDR 8.8.8.8 → 404, 192.168.1.5 (ANC_LAN_NETS) → 200
def test_audit_flags_missing_pcu_map(fake_fetch):
    a = check.audit(D1, D2, CFG, None)
    assert next(i for i in a["items"] if i["key"]=="pcu_map")["status"] == "bad"
def test_audit_dt_warns_on_other_codes(fake_fetch):  # พบ 101 มากกว่า 201–205 → warn และ hint กล่าวถึง ANC_DT_VACCINE_CODES
def test_audit_wait_col_low_is_bad(fake_fetch):
def test_template_csv_has_no_person_columns(client, fake_data):
    body = client.get("/check/pcu_map_template.csv", environ_base={"REMOTE_ADDR":"192.168.1.5"}).get_data(as_text=True)
    assert body.splitlines()[0].lstrip("\ufeff") == "village_code,pcu_hospcode,pcu_name,tambon,moo,pregnancies"
    assert "HN-SECRET" not in body
```

- [ ] **Step 2:** `python -m pytest tests/test_check.py -q` → FAIL
- [ ] **Step 3:** เขียน `check.py` (ใช้แบบ `_safe/_status/_dist` จาก er_dashboard/check.py), template, routes
- [ ] **Step 4:** `python -m pytest -q` → ผ่าน
- [ ] **Step 5:** เปิด `/check` กับฐานจริงใน browser pane ตรวจว่าเห็นรหัส 101 vs 201–205 และ % Hct ตามที่สำรวจไว้ใน spec §3
- [ ] **Step 6:** commit `"feat: data audit page and pcu_map template"`

---

### Task 7: ส่งออก JPG/PDF + setup_check.py

**Files:**
- Create: `render.py` (คัดลอกจาก er_dashboard; `HEIGHT` ปรับให้พอกับหน้า ANC), `setup_check.py`
- Modify: `app.py` (route `/export.<fmt>` คัดลอก `_RenderLock`, `export`, `EXPORT_*` จาก er_dashboard; URL ที่เรนเดอร์ต้องมี `export=1`)
- Test: `tests/test_setup_check.py`, เพิ่มใน `tests/test_app.py`

**Interfaces:**
- Produces:
  - `setup_check.run(fetch=db.fetch, cfg=None) -> list[tuple[str,str,str]]` (status `"ok"|"warn"|"bad"`, หัวข้อ, รายละเอียด) · `main()` พิมพ์ ✔/⚠/✘ และ `sys.exit(1)` เมื่อมี bad
  - รายการตรวจตาม spec §7 ตามลำดับ: Python ≥3.10 · ไลบรารีใน requirements · เขตเวลา Asia/Bangkok · Chrome/Edge (warn ถ้าไม่มี) · ต่อ DB · สิทธิ์อ่านอย่างเดียว (`show grants` นับเฉพาะฐาน `DB_NAME` และ `*.*`; bad ถ้ามี INSERT/UPDATE/DELETE/ALL) · ตารางใน spec §3 ครบ · ภาษาไทยอ่านได้ (ชื่อ `anc_lab` ไม่มี `�`) · visit ANC ล่าสุดไม่เกิน 30 วัน (warn) · `pcu_map.csv` (warn ถ้าไม่มี, bad ถ้ารูปแบบผิด) · สรุปสถานะจาก `check.audit` ช่วง 90 วันล่าสุด

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

```python
def test_write_grant_is_bad():
    rows = run(fetch=fake({"show grants": [{"g":"GRANT SELECT, INSERT ON `hos`.* TO x"}]}))
    assert ("bad" in [s for s,_,_ in rows])
def test_grant_on_other_db_ignored():   # INSERT บน `other_db`.* ไม่ทำให้ bad
def test_missing_table_is_bad():
def test_exit_code_1_on_bad(monkeypatch):
def test_export_disabled_returns_404(client, monkeypatch):  # ANC_EXPORT=0
```

- [ ] **Step 2:** `python -m pytest -q` → FAIL
- [ ] **Step 3:** คัดลอก/เขียนตาม Interfaces
- [ ] **Step 4:** `python -m pytest -q` → ผ่าน
- [ ] **Step 5:** รัน `python setup_check.py` กับฐานจริง → ไม่มี ✘ (⚠ ได้) และ `python render.py` หรือกด `/export.jpg` ได้ไฟล์ที่ไม่มีแถบเตือน
- [ ] **Step 6:** commit `"feat: export and setup_check"`

---

### Task 8: เอกสาร + ชุดติดตั้ง

**Files:**
- Create: `INSTALL.md`, `README.md`, `CHANGELOG.md` (0.1.0), `LICENSE` (MIT), `NOTICE.md`, `SECURITY.md` (ย่อจาก er_dashboard), `Dockerfile`, `.dockerignore`, `build_dist.py` (คัดลอก — รวม `setup_check.py`, `pcu_map.example.csv`), `.github/ISSUE_TEMPLATE/bug_report.yml`
- Test: `tests/test_docs.py`

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

```python
def test_install_has_section_0():
    t = open("INSTALL.md", encoding="utf-8").read()
    for s in ("ก่อนนำไปใช้", "setup_check.py", "ANC_DATA_AUDITED", "1–2 สัปดาห์", "MIT", "pcu_map.csv"):
        assert s in t
def test_bug_template_requires_setup_check_and_no_patient_data():
    t = open(".github/ISSUE_TEMPLATE/bug_report.yml", encoding="utf-8").read()
    assert "setup_check" in t and "required: true" in t and "ไม่มีข้อมูลผู้ป่วย" in t
def test_dockerfile_includes_setup_check():
    assert "setup_check.py" in open("Dockerfile", encoding="utf-8").read() or "COPY . ." in open("Dockerfile", encoding="utf-8").read()
def test_env_example_lists_all_config_keys():
    # ทุก ANC_* ที่ config.py อ่าน ต้องอยู่ใน .env.example
```

- [ ] **Step 2:** `python -m pytest tests/test_docs.py -q` → FAIL
- [ ] **Step 3:** เขียนเอกสาร (INSTALL.md ข้อ 0 ตาม spec §7 + ขั้นทำ `pcu_map.csv` จาก `/check`; README บอกนิยามตัวชี้วัด ↔ แฟ้ม 43 จาก spec §3–4)
- [ ] **Step 4:** `python -m pytest -q` → ผ่านทั้งหมด
- [ ] **Step 5:** commit `"docs: install guide, issue template, docker"`

Deploy ขึ้น `wnkhos.go.th/anc/` เป็นงานแยกหลังทดลองคู่ขนานผ่าน (สกิล `wnkhos-deploy`) — ไม่อยู่ในแผนนี้
