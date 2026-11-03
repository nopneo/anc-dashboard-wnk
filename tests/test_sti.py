from datetime import date

import pytest

import sti
from config import load_config

CFG = load_config({})


@pytest.mark.parametrize("text,want", [
    ("Non Reactive", "neg"), ("Non-reactive", "neg"), ("Non Recative", "neg"), ("Non Raective", "neg"),
    ("Non Rreactive", "neg"), ("\x02Non Reactive", "neg"), ("ืNon Reactive", "neg"), ("Negative", "neg"),
    ("Negtaive", "neg"), ("Negative   \x02", "neg"), ("์Negative", "neg"),
    ("Reactive titer 1:4", "pos"), ("Rective 1: 4", "pos"), ("Reactive1:64", "pos"), ("Positive", "pos"),
    ("Weakly Positive", "pos"), ("Positive X 3 Day", "pos"), ("Positive (3 วิธี)", "pos"), ("reactive titer 1:8", "pos"),
    ("Inconclusive", "unclear"), ("", "unclear"), (None, "unclear"), ("ดูผล OUT LAB", "unclear"),
    ("Positve", "pos"), ("Posiitive", "pos"), ("Positive", "pos"),          # Amphetamine พิมพ์ผิดจริงในฐาน
    ("No Urine", "unclear"), ("สิ่งส่งตรวจเป็นน้ำเปล่า", "unclear"), ("Non Reactive   Negative", "neg"),
])
def test_classify(text, want):
    assert sti.classify(text) == want


def test_merge_positive_wins_then_negative():
    assert sti.merge([("unclear", ""), ("neg", "Negative")]) == ("neg", "Negative")
    assert sti.merge([("neg", "Non Reactive"), ("pos", "Reactive 1:8")])[0] == "pos"
    assert sti.merge([("unclear", "")]) == ("unclear", "-")


def test_summarize_counts_per_test():
    new = [{"anc_id": i} for i in range(1, 6)]
    res = {1: {"syphilis": ("pos", "Reactive"), "hiv": ("neg", "Negative")},
           2: {"syphilis": ("neg", "Non Reactive")},
           3: {"syphilis": ("unclear", "-")},
           99: {"syphilis": ("pos", "x")}}                     # ไม่ใช่ครรภ์รายใหม่ในช่วง ไม่นับ
    out = {t["key"]: t for t in sti.summarize(new, res, CFG)}
    s = out["syphilis"]
    assert (s["tested"]["num"], s["tested"]["den"]) == (3, 5)
    assert (s["pos"]["num"], s["pos"]["den"], s["pos"]["value"]) == (1, 3, 33.3)
    assert s["unclear"] == 1 and s["untested"] == 2
    assert out["hbv"]["tested"]["num"] == 0 and out["hbv"]["pos"]["value"] is None
    assert [t["key"] for t in sti.summarize(new, res, CFG)] == ["syphilis", "hbv", "hiv", "amph"]


def test_name_pickers_follow_lab_names():
    labs = [("365", "VDRL ครั้งที่ 1"), ("366", "TPHA"), ("355", "HBs Ag"), ("2244", "HBs Ag ฟรี"),
            ("356", "Anti-HBs"), ("1976", "Hbs Ab (PHA)"), ("362", "Anti-HIV (ไม่ด่วน) ครั้งที่ 1"),
            ("1978", "Anti-HIV (rapid test)"), ("2048", "HIV-PCR"), ("1951", "Anti-HCV"),
            ("139", "Methamphetamine"), ("2104", "Methamphetamine ฟรี"), ("952", "Ampicillin เชื้อ 1"),
            ("81", "Metamyelocyte")]
    got = sti.pick_lab_codes(labs)
    assert got == {"syphilis": ("365", "366"), "hbv": ("355", "2244"), "hiv": ("362", "1978"),
                   "amph": ("139", "2104")}                    # Ampicillin / Metamyelocyte ต้องไม่ติด
    anc = [("1", "VDRL1"), ("2", "VDRL2"), ("3", "HIV1"), ("4", "HIV2"), ("6", "HCT1")]
    assert sti.pick_anc_lab_ids(anc) == {"syphilis": (1, 2), "hbv": (), "hiv": (3, 4), "amph": ()}
