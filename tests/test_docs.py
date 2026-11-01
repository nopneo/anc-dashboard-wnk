import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    return open(os.path.join(ROOT, p), encoding="utf-8").read()


def test_install_has_section_0():
    t = read("INSTALL.md")
    assert "## 0. ก่อนนำไปใช้" in t
    for s in ("setup_check.py", "ANC_DATA_AUDITED", "1–2 สัปดาห์", "MIT", "pcu_map.csv", "/check", "ไม่มีการรับประกัน"):
        assert s in t, s


def test_bug_template_requires_setup_check_and_no_patient_data():
    t = read(".github/ISSUE_TEMPLATE/bug_report.yml")
    assert "setup_check" in t and "required: true" in t and "ไม่มีข้อมูลผู้ป่วย" in t


def test_dockerfile_ships_setup_check():
    d = read("Dockerfile")
    assert "COPY . ." in d and "setup_check.py" not in read(".dockerignore")
    assert "ANC_DB_MODE=direct" in d and "TZ=Asia/Bangkok" in d


def test_dist_includes_setup_check_and_example_map():
    t = read("build_dist.py")
    assert '"setup_check.py"' in t and '"pcu_map.example.csv"' in t and '"metrics.py"' in t and '"config.py"' in t


def test_env_example_lists_all_config_keys():
    used = set()
    for f in ("config.py", "app.py", "db.py", "render.py", "setup_check.py"):
        used |= set(re.findall(r'"(ANC_[A-Z0-9_]+)"', read(f)))
    used |= {f"ANC_TARGET_{k}" for k in ("EARLY12", "5VISIT", "DT", "DENTAL", "ANEMIA", "LBW")}
    example = read(".env.example")
    missing = sorted(k for k in used if k not in example)
    assert not missing, missing


def test_no_secrets_committed():
    assert not os.path.exists(os.path.join(ROOT, ".env")) or ".env" in read(".gitignore").split()
    assert "pcu_map.csv" in read(".gitignore").split()
