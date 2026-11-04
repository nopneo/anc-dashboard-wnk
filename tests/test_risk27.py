import re

import risk27
from config import Config, load_config

CFG = Config()


def preg(i, age=25):
    return {"anc_id": i, "age": age}


def hits(form=None, dx=None, text=None, body=None):
    return {"form": form or {}, "dx": dx or {}, "text": text or {}, "body": body or {}}


def item(res, key):
    return next(x for x in res["items"] if x["key"] == key)


def test_there_are_27_items_in_four_groups():
    assert len(risk27.ITEMS) == 27
    assert [g for g, _ in risk27.GROUPS] == ["age_body", "history", "medical", "current"]
    assert {i["group"] for i in risk27.ITEMS} == {g for g, _ in risk27.GROUPS}


def test_age_is_computed_not_taken_from_the_form():
    res = risk27.summarize([preg(1, 16), preg(2, 36), preg(3, 25)], hits(form={3: {"8", "9"}}), CFG)
    # ฟอร์มติ๊ก "อายุ<17" และ ">35" ให้รายอายุ 25 แต่ไม่นับ — ใช้อายุจริงเท่านั้น
    assert item(res, "age_lt17")["n"] == 1
    assert item(res, "age_ge35")["n"] == 1


def test_height_and_bmi_from_first_visit_body():
    body = {1: (144, 60), 2: (160, 40), 3: (160, 60), 4: (None, None)}
    res = risk27.summarize([preg(i) for i in (1, 2, 3, 4)], hits(body=body), CFG)
    assert item(res, "height_lt145")["n"] == 1
    assert item(res, "bmi_high")["n"] == 1      # 60 / 1.44^2 = 28.9
    assert item(res, "bmi_low")["n"] == 1       # 40 / 1.6^2 = 15.6
    assert item(res, "bmi_low")["known"] == 3   # รายที่ไม่มีส่วนสูง/น้ำหนักไม่นับในฐาน


def test_implausible_body_values_are_ignored():
    res = risk27.summarize([preg(1)], hits(body={1: (16, 900)}), CFG)
    assert item(res, "height_lt145")["n"] == 0 and item(res, "height_lt145")["known"] == 0


def test_sources_are_combined_without_double_counting():
    h = hits(form={1: {"7"}, 2: {"7"}}, dx={1: {"O30", "O301"}, 3: {"O30"}}, text={1: {"twin"}})
    res = risk27.summarize([preg(1), preg(2), preg(3)], h, CFG)
    twin = item(res, "twin")
    assert twin["n"] == 3
    assert twin["by_source"] == {"F": 2, "D": 2, "T": 1}


def test_dx_matches_three_or_four_character_codes():
    res = risk27.summarize([preg(1), preg(2)], hits(dx={1: {"O365"}, 2: {"O36"}}), CFG)
    assert item(res, "fetal_abn")["n"] == 1  # O36 เฉยๆ ไม่ใช่ O36.5


def test_groups_and_any_count_each_pregnancy_once():
    h = hits(form={1: {"7", "11"}}, text={1: {"prev_preterm"}, 2: {"prev_preterm"}})
    res = risk27.summarize([preg(1), preg(2), preg(3)], h, CFG)
    assert res["any"]["num"] == 2 and res["any"]["den"] == 3
    cur = next(g for g in res["groups"] if g["key"] == "current")
    assert cur["num"] == 1
    assert next(g for g in res["groups"] if g["key"] == "history")["num"] == 2


def test_extra_form_items_count_toward_any_risk_only():
    res = risk27.summarize([preg(1)], hits(form={1: {"10"}}), CFG)
    assert res["any"]["num"] == 1
    assert [e["n"] for e in res["extras"]] == [1, 0, 0, 0, 0]
    assert all(item(res, x["key"])["n"] == 0 for x in risk27.ITEMS)


def test_top_lists_only_items_found_most_first():
    h = hits(text={1: {"prev_preterm"}, 2: {"prev_preterm"}, 3: {"twin"}})
    res = risk27.summarize([preg(1), preg(2), preg(3)], h, CFG)
    assert [t["key"] for t in res["top"]] == ["prev_preterm", "twin"]


def test_empty_input():
    res = risk27.summarize([], hits(), CFG)
    assert res["any"]["num"] == 0 and res["any"]["pct"] is None


def test_every_text_pattern_compiles_and_has_defaults():
    for it in risk27.ITEMS:
        pat = risk27.DEFAULT_TEXT.get(it["key"])
        if pat:
            re.compile(pat, re.I)
    assert load_config({}).risk_text == risk27.DEFAULT_TEXT


def test_env_overrides_for_dx_and_text_and_thresholds():
    cfg = load_config({"ANC_RISK_DX_TWIN": "O30,O31", "ANC_RISK_TEXT_TWIN": "twin|แฝด3",
                       "ANC_RISK_AGE_LOW": "18", "ANC_RISK_HEIGHT_CM": "150"})
    assert cfg.risk_dx["twin"] == ("O30", "O31")
    assert cfg.risk_text["twin"] == "twin|แฝด3"
    assert (cfg.risk_age_low, cfg.risk_height_cm) == (18, 150)
    assert cfg.risk_dx["pre_dm"] == risk27.DEFAULT_DX["pre_dm"]


def test_split_thai_and_foreign():
    pregs = [dict(preg(1, 16), thai=True), dict(preg(2, 16), thai=False), dict(preg(3, 25), thai=True),
             dict(preg(4, 36), thai=False)]
    res = risk27.summarize(pregs, hits(form={4: {"7"}}), CFG)
    assert (res["den"], res["den_th"], res["den_fr"]) == (4, 2, 2)
    young = item(res, "age_lt17")
    assert (young["n"], young["n_th"], young["n_fr"]) == (2, 1, 1) and young["pct_th"] == 50.0
    twin = item(res, "twin")
    assert (twin["n_th"], twin["n_fr"]) == (0, 1)
    assert (res["any"]["num"], res["any"]["num_th"], res["any"]["num_fr"]) == (3, 1, 2)
    g = next(x for x in res["groups"] if x["key"] == "age_body")
    assert g["num"] == g["num_th"] + g["num_fr"]
