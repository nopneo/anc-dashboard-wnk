import pytest

from config import PcuMapError, load_config, load_village_pcu, village_code


def test_defaults():
    c = load_config({})
    assert c.dt_codes == ("201", "202", "203", "204", "205")
    assert c.hct_cutoff == 33 and c.hct_late_ga == 28 and c.lbw_grams == 2500
    assert c.postpartum_days == 42
    assert c.refer_dx_prefixes == ("O", "Z32", "Z33", "Z34", "Z35", "Z36")
    assert c.refer_dx_exclude == ("Z32", "Z34")
    assert load_config({"ANC_REFER_DX_EXCLUDE": "z34, Z32.9"}).refer_dx_exclude == ("Z34", "Z329")
    assert load_config({"ANC_REFER_DX_EXCLUDE": ""}).refer_dx_exclude == ()      # ว่าง = จัดอันดับทุกรหัส
    assert c.targets == {"early12": 75, "visit5": 75, "visit8": None, "dt": 90, "dental": 50, "anemia": 14, "lbw": 7,
                         "postnatal": 75, "quality": 70, "iodine": None, "asphyxia": 25, "teen_repeat": None}
    assert c.data_audited is False and not hasattr(c, "wait_from_col")
    assert c.sti_labs == {"syphilis": (), "hbv": (), "hiv": (), "amph": (), "nipt": ()} and c.sti_anc_labs["hiv"] == ()
    assert load_config({"ANC_STI_AMPH_LABS": "139"}).sti_labs["amph"] == ("139",)


def test_list_and_sti_codes():
    c = load_config({"ANC_DT_VACCINE_CODES": " 201, 101 ,", "ANC_STI_HIV_LABS": "362, 1978",
                     "ANC_STI_SYPHILIS_ANC_LABS": "1,x,2"})
    assert c.dt_codes == ("201", "101")
    assert c.sti_labs["hiv"] == ("362", "1978") and c.sti_anc_labs["syphilis"] == (1, 2)


def test_targets_and_flags_from_env():
    c = load_config({"ANC_TARGET_LBW": "6.5", "ANC_DATA_AUDITED": "1", "ANC_HCT_LAB_IDS": "3, 8"})
    assert c.targets["lbw"] == 6.5 and c.data_audited is True and c.hct_lab_ids == (3, 8)


HDR = "tmbpart,tambon,moo,village,hospcode,pcu\n"


def test_village_pcu_missing_returns_none(tmp_path):
    assert load_village_pcu(str(tmp_path / "none.csv"), "30", "25") is None


def test_village_pcu_mental_health_format(tmp_path):
    """รูปแบบเดียวกับ mental_health_dashboard: ตำบล + หมู่ → รหัส/ชื่อ รพ.สต. · ใช้ไฟล์เดียวกันได้"""
    p = tmp_path / "v.csv"
    p.write_text("﻿" + HDR + " 2 ,วังหมี, 1 ,บ้านวังหมี, 02842 , ท่าวังไทร \n"
                 "01,วังน้ำเขียว,10,บุตะโก,10894,รพ.วังน้ำเขียว\n"
                 "01,x,abc,x,1,x\n", encoding="utf-8")
    assert load_village_pcu(str(p), "30", "25") == {"30250201": ("02842", "ท่าวังไทร"),
                                                     "30250110": ("10894", "รพ.วังน้ำเขียว")}


def test_village_pcu_bad_header(tmp_path):
    p = tmp_path / "v.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(PcuMapError):
        load_village_pcu(str(p), "30", "25")


def test_village_code():
    assert village_code("30", "25", "1", "3") == "30250103"
    assert village_code("30", "25", None, "3") is None
    assert village_code("30", "25", "01", "") is None


def test_village_pcu_non_utf8_is_pcu_error(tmp_path):
    p = tmp_path / "v.csv"
    p.write_bytes((HDR + "01,วังน้ำเขียว,1,ศาลเจ้าพ่อ,02840,ศาลเจ้าพ่อ\n").encode("cp874"))
    with pytest.raises(PcuMapError, match="UTF-8"):
        load_village_pcu(str(p), "30", "25")


def test_district_defaults():
    c = load_config({})
    assert (c.chwpart, c.amppart, c.hospcode) == ("30", "25", "10894")
    assert c.village_csv.endswith("village_pcu.csv")
    assert load_config({"ANC_VILLAGE_CSV": "/x/v.csv"}).village_csv.replace("\\", "/").endswith("/x/v.csv")


def test_dead_dchstts_default():
    assert load_config({}).dead_dchstts == ("08", "09")


def test_kpi_folder_defaults():
    c = load_config({})
    assert c.iodine_didstd[0] == "201120320037726221781506" and len(c.iodine_didstd) == 7
    assert c.us_icd9 == ("8878", "5260700", "5260701")
    assert c.down_dx == ("Z360", "Z362") and c.dm_dx == ("Z131",)
    assert c.thal_export_codes == ("1", "2", "4")
    assert c.cbc_lab_codes == () and c.dm_lab_codes == ()          # ว่าง = เลือกจากชื่อรายการ lab
    assert c.targets["postnatal"] == 75 and c.targets["quality"] == 70 and c.targets["iodine"] is None
    assert load_config({"ANC_TARGET_IODINE": "80"}).targets["iodine"] == 80
