import pytest

from config import PcuMapError, load_config, load_pcu_map, village_code


def test_defaults():
    c = load_config({})
    assert c.dt_codes == ("201", "202", "203", "204", "205")
    assert c.hct_cutoff == 33 and c.hct_late_ga == 28 and c.lbw_grams == 2500
    assert c.postpartum_days == 42
    assert c.refer_dx_prefixes == ("O", "Z32", "Z33", "Z34", "Z35", "Z36")
    assert c.targets == {"early12": 75, "visit5": 75, "dt": 90, "dental": 50, "anemia": 14, "lbw": 7}
    assert c.wait_from_col == "vsttime" and c.wait_to_col == "service5"
    assert c.wait_max_min == 240 and c.data_audited is False


def test_list_and_bad_col():
    c = load_config({"ANC_DT_VACCINE_CODES": " 201, 101 ,", "ANC_WAIT_TO_COL": "drop table"})
    assert c.dt_codes == ("201", "101")
    assert c.wait_to_col == "service5"


def test_targets_and_flags_from_env():
    c = load_config({"ANC_TARGET_LBW": "6.5", "ANC_DATA_AUDITED": "1", "ANC_HCT_LAB_IDS": "3, 8"})
    assert c.targets["lbw"] == 6.5 and c.data_audited is True and c.hct_lab_ids == (3, 8)


def test_pcu_map_missing_returns_none(tmp_path):
    assert load_pcu_map(str(tmp_path / "none.csv")) is None


def test_pcu_map_excel_quirks(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("﻿village_code,pcu_hospcode,pcu_name\n 3025010 ,03929, รพ.สต.ไทยสามัคคี \n,,\n", encoding="utf-8")
    assert load_pcu_map(str(p)) == {"03025010": ("03929", "รพ.สต.ไทยสามัคคี")}


def test_pcu_map_bad_header(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(PcuMapError):
        load_pcu_map(str(p))


def test_pcu_map_bad_code(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("village_code,pcu_hospcode,pcu_name\nabc,1,x\n", encoding="utf-8")
    with pytest.raises(PcuMapError):
        load_pcu_map(str(p))


def test_village_code():
    assert village_code("30", "25", "1", "3") == "30250103"
    assert village_code("30", "25", None, "3") is None
    assert village_code("30", "25", "01", "") is None
