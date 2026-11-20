
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIDIS 2013 - Step 05: Final submission packaging / QA
NSS 70th Round | Schedule 18.2

Fast-track final stage:
- consumes validated Step-04 indicator cube
- runs structural and numeric QA
- verifies all 18 official controls are PASS
- writes a canonical All-India + State + District final CSV
- creates a compact submission ZIP with final outputs and validation evidence

No third-party packages are required.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
import sys
import zipfile
from pathlib import Path
from typing import List

SCRIPT_REVISION = "R1-FASTTRACK-FINAL-SUBMISSION-2026-08-27"
EXPECTED_CUBE_ROWS = 4609
EXPECTED_ALL_INDIA_ROWS = 7
EXPECTED_STATE_ROWS = 252
EXPECTED_DISTRICT_ROWS = 4350
EXPECTED_STATES = 36
EXPECTED_STATE_DISTRICTS = 634
EXPECTED_CONTROLS = 18

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = PROJECT_ROOT / "cache"
OUTPUT_DATA_DIR = PROJECT_ROOT / "output" / "data"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"
SUBMISSION_DIR = PROJECT_ROOT / "output" / "submission"
for p in (CONFIG_DIR, CACHE_DIR, OUTPUT_DATA_DIR, REPORT_DIR, SUBMISSION_DIR):
    p.mkdir(parents=True, exist_ok=True)

STEP04_LOCK = CONFIG_DIR / "aidis_2013_step04_lock.json"
CUBE_FILE = OUTPUT_DATA_DIR / "aidis_2013_indicator_cube.csv"
ALL_INDIA_FILE = OUTPUT_DATA_DIR / "aidis_2013_all_india_kpis.csv"
STATE_FILE = OUTPUT_DATA_DIR / "aidis_2013_state_kpis.csv"
DISTRICT_FILE = OUTPUT_DATA_DIR / "aidis_2013_district_kpis.csv"
STEP04_CHECKS = CACHE_DIR / "step04_indicator_cube_checks.csv"
STEP04_CONTROLS = CACHE_DIR / "step04_official_control_validation.csv"
STEP04_SUMMARY = REPORT_DIR / "step04_indicator_cube_summary.txt"

FINAL_CSV = SUBMISSION_DIR / "AIDIS_2013_All_India_State_District_Final.csv"
FINAL_ALL = SUBMISSION_DIR / "AIDIS_2013_All_India_Final.csv"
FINAL_STATE = SUBMISSION_DIR / "AIDIS_2013_State_Final.csv"
FINAL_DISTRICT = SUBMISSION_DIR / "AIDIS_2013_District_Final.csv"
FINAL_ZIP = SUBMISSION_DIR / "AIDIS_2013_Final_Submission.zip"
QA_FILE = CACHE_DIR / "step05_final_submission_checks.csv"
STEP05_LOCK = CONFIG_DIR / "aidis_2013_step05_lock.json"
SUMMARY_FILE = REPORT_DIR / "step05_final_submission_summary.txt"
MANIFEST_FILE = SUBMISSION_DIR / "AIDIS_2013_Submission_Manifest.txt"

checks: List[dict] = []
errors: List[str] = []
warnings: List[str] = []


def clean(v) -> str:
    return "" if v is None else str(v).strip()


def add_check(cid: str, description: str, expected, actual, passed: bool, severity="ERROR"):
    checks.append({
        "check_id": cid,
        "description": description,
        "expected": expected,
        "actual": actual,
        "status": "PASS" if passed else severity,
    })
    if not passed:
        msg = f"{cid}: {description} | expected={expected} actual={actual}"
        if severity == "WARNING":
            warnings.append(msg)
        else:
            errors.append(msg)


def require_file(path: Path, label: str):
    ok = path.exists() and path.is_file() and path.stat().st_size > 0
    add_check(f"FILE_{label}", f"Required file exists: {path.name}", "present", "present" if ok else "missing", ok)
    return ok


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        yield from csv.DictReader(fh)


def copy_exact(src: Path, dst: Path):
    shutil.copyfile(src, dst)


def validate_cube():
    print("\n[2] Validating final indicator cube")
    rows = list(read_csv(CUBE_FILE))
    n = len(rows)
    all_rows = [r for r in rows if clean(r.get("geo_level")) == "ALL_INDIA"]
    state_rows = [r for r in rows if clean(r.get("geo_level")) == "STATE"]
    district_rows = [r for r in rows if clean(r.get("geo_level")) == "DISTRICT"]

    add_check("CUBE_ROWS", "Final indicator cube row count", EXPECTED_CUBE_ROWS, n, n == EXPECTED_CUBE_ROWS)
    add_check("ALL_INDIA_ROWS", "All-India row count", EXPECTED_ALL_INDIA_ROWS, len(all_rows), len(all_rows) == EXPECTED_ALL_INDIA_ROWS)
    add_check("STATE_ROWS", "State row count", EXPECTED_STATE_ROWS, len(state_rows), len(state_rows) == EXPECTED_STATE_ROWS)
    add_check("DISTRICT_ROWS", "District row count", EXPECTED_DISTRICT_ROWS, len(district_rows), len(district_rows) == EXPECTED_DISTRICT_ROWS)

    key_cols = ["geo_level", "geo_code", "State", "District_id", "Sector", "household_group"]
    seen = set()
    dups = 0
    for r in rows:
        key = tuple(clean(r.get(c)) for c in key_cols)
        if key in seen:
            dups += 1
        else:
            seen.add(key)
    add_check("DUPLICATE_OUTPUT_KEYS", "Duplicate final output keys", 0, dups, dups == 0)

    states = {
        clean(r.get("geo_code")) for r in state_rows
        if clean(r.get("Sector")) == "All" and clean(r.get("household_group")) == "All"
    }
    districts = {
        clean(r.get("geo_code")) for r in district_rows
        if clean(r.get("Sector")) == "All" and clean(r.get("household_group")) == "All"
    }
    add_check("STATE_COUNT", "States/UTs in final output", EXPECTED_STATES, len(states), len(states) == EXPECTED_STATES)
    add_check("STATE_DISTRICT_COUNT", "State-district combinations in final output", EXPECTED_STATE_DISTRICTS, len(districts), len(districts) == EXPECTED_STATE_DISTRICTS)

    meta = set(["geo_level", "geo_code", "geo_name", "State", "District_id", "Sector", "household_group"])
    if rows:
        fields = list(rows[0].keys())
    else:
        fields = []
    numeric_fields = [c for c in fields if c not in meta]
    bad_numeric = 0
    nonfinite = 0
    negative_counts = 0
    for r in rows:
        for c in numeric_fields:
            s = clean(r.get(c))
            if not s:
                continue
            try:
                x = float(s.replace(",", ""))
            except ValueError:
                bad_numeric += 1
                continue
            if not math.isfinite(x):
                nonfinite += 1
            if c in {"sample_stock_n", "weighted_households_stock", "sample_flow_n", "weighted_households_flow"} and x < 0:
                negative_counts += 1
    add_check("NUMERIC_PARSE", "Non-numeric values in metric columns", 0, bad_numeric, bad_numeric == 0)
    add_check("FINITE_METRICS", "Non-finite metric values", 0, nonfinite, nonfinite == 0)
    add_check("NONNEGATIVE_BASES", "Negative sample/weighted household bases", 0, negative_counts, negative_counts == 0)

    print(f"  Cube rows                 : {n:,}")
    print(f"  All-India rows            : {len(all_rows):,}")
    print(f"  State rows                : {len(state_rows):,}")
    print(f"  District rows             : {len(district_rows):,}")
    print(f"  Duplicate output keys     : {dups:,}")
    print(f"  States/UTs                : {len(states):,}")
    print(f"  State-district combos     : {len(districts):,}")
    return rows


def validate_controls():
    print("\n[3] Rechecking Step-04 official controls")
    rows = list(read_csv(STEP04_CONTROLS))
    total = len(rows)
    passed = sum(1 for r in rows if clean(r.get("status")).upper() == "PASS")
    failed = [clean(r.get("control_id")) for r in rows if clean(r.get("status")).upper() != "PASS"]
    add_check("OFFICIAL_CONTROL_COUNT", "Official validation anchor count", EXPECTED_CONTROLS, total, total == EXPECTED_CONTROLS)
    add_check("OFFICIAL_CONTROL_PASS", "All official validation anchors pass", EXPECTED_CONTROLS, passed, total == EXPECTED_CONTROLS and passed == EXPECTED_CONTROLS)
    print(f"  Official anchors           : {total}")
    print(f"  Official anchors passed    : {passed}")
    if failed:
        print(f"  Failed controls            : {', '.join(failed)}")
    return total, passed


def write_checks():
    with QA_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        cols = ["check_id", "description", "expected", "actual", "status"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(checks)


def write_manifest(total_controls: int, passed_controls: int):
    text = "\n".join([
        "AIDIS 2013 - FINAL SUBMISSION MANIFEST",
        "NSS 70th Round | Schedule 18.2",
        "",
        f"Script revision: {SCRIPT_REVISION}",
        "",
        "PRIMARY SUBMISSION FILE",
        f"- {FINAL_CSV.name}",
        "",
        "SUPPORTING EXTRACTS",
        f"- {FINAL_ALL.name}",
        f"- {FINAL_STATE.name}",
        f"- {FINAL_DISTRICT.name}",
        "",
        "VALIDATION",
        f"- Official anchors: {total_controls}",
        f"- Official anchors passed: {passed_controls}",
        f"- Final QA failed checks: {len(errors)}",
        f"- Final QA warnings: {len(warnings)}",
        "",
        "ESTIMATION BASES",
        "- Stock indicators: Visit-1 universe, Visit-1 Weight_SC",
        "- Annual flow indicators: exact Visit-1/Visit-2 common panel, Visit-2 Weight_SC",
        "",
        "KEY VALIDATED UNIVERSES",
        "- Visit-1 households: 110,800",
        "- Common panel households: 108,421",
        "- States/UTs: 36",
        "- State-district combinations: 634",
        "",
        "STATUS",
        f"- {'PASS' if not errors else 'FAIL'}",
    ]) + "\n"
    MANIFEST_FILE.write_text(text, encoding="utf-8")


def build_zip():
    include = [
        FINAL_CSV, FINAL_ALL, FINAL_STATE, FINAL_DISTRICT, MANIFEST_FILE,
        STEP04_CONTROLS, STEP04_CHECKS, QA_FILE,
        CONFIG_DIR / "aidis_2013_methodology_lock.json",
        CONFIG_DIR / "aidis_2013_step02_lock.json",
        CONFIG_DIR / "aidis_2013_step03_lock.json",
        STEP04_LOCK,
        STEP04_SUMMARY,
    ]
    existing = [p for p in include if p.exists() and p.is_file()]
    with zipfile.ZipFile(FINAL_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in existing:
            if p.parent == SUBMISSION_DIR:
                arc = p.name
            elif p.parent == CONFIG_DIR:
                arc = f"validation/config/{p.name}"
            elif p.parent == CACHE_DIR:
                arc = f"validation/cache/{p.name}"
            elif p.parent == REPORT_DIR:
                arc = f"validation/reports/{p.name}"
            else:
                arc = p.name
            zf.write(p, arcname=arc)
    return len(existing)


def finish(total_controls: int, passed_controls: int, zip_files: int):
    status = "FAIL" if errors else ("PASS_WITH_WARNINGS" if warnings else "PASS")
    lock = {
        "step": "05",
        "name": "Final submission packaging / QA",
        "status": status,
        "script_revision": SCRIPT_REVISION,
        "project_root": str(PROJECT_ROOT),
        "official_controls": {"total": total_controls, "passed": passed_controls},
        "checks": {"total": len(checks), "failed": len(errors), "warnings": len(warnings)},
        "outputs": {
            "primary_final_csv": str(FINAL_CSV),
            "all_india": str(FINAL_ALL),
            "state": str(FINAL_STATE),
            "district": str(FINAL_DISTRICT),
            "manifest": str(MANIFEST_FILE),
            "submission_zip": str(FINAL_ZIP),
            "qa_checks": str(QA_FILE),
            "summary": str(SUMMARY_FILE),
        },
        "errors": errors,
        "warnings": warnings,
    }
    with STEP05_LOCK.open("w", encoding="utf-8") as fh:
        json.dump(lock, fh, indent=2)

    lines = [
        "=" * 78,
        "AIDIS 2013 - STEP 05 FINAL SUBMISSION / QA SUMMARY",
        "=" * 78,
        "",
        f"Project root              : {PROJECT_ROOT}",
        f"Script revision           : {SCRIPT_REVISION}",
        "",
        "FINAL QA",
        "--------",
        f"Checks                     : {len(checks)}",
        f"Failed checks              : {len(errors)}",
        f"Warnings                   : {len(warnings)}",
        f"Official anchors           : {total_controls}",
        f"Official anchors passed    : {passed_controls}",
        "",
        "SUBMISSION OUTPUTS",
        "------------------",
        f"Primary final CSV          : {FINAL_CSV}",
        f"All-India extract          : {FINAL_ALL}",
        f"State extract              : {FINAL_STATE}",
        f"District extract           : {FINAL_DISTRICT}",
        f"Manifest                   : {MANIFEST_FILE}",
        f"Submission ZIP             : {FINAL_ZIP}",
        f"Files packed in ZIP        : {zip_files}",
        f"Step-05 lock               : {STEP05_LOCK}",
    ]
    if warnings:
        lines += ["", "WARNINGS:"] + [f"  - {x}" for x in warnings]
    if errors:
        lines += ["", "ERRORS:"] + [f"  - {x}" for x in errors]
    lines += ["", f"STEP 05 STATUS: {status}", "=" * 78]
    text = "\n".join(lines)
    SUMMARY_FILE.write_text(text + "\n", encoding="utf-8")
    print("\n" + text)


def main():
    print("=" * 78)
    print("AIDIS 2013 - STEP 05 FINAL SUBMISSION PACKAGING / QA")
    print("NSS 70th Round | Schedule 18.2")
    print("=" * 78)
    print(f"Project root              : {PROJECT_ROOT}")
    print(f"Script revision           : {SCRIPT_REVISION}")

    print("\n[1] Validating Step-04 production outputs")
    needed = [
        (STEP04_LOCK, "STEP04_LOCK"), (CUBE_FILE, "CUBE"),
        (ALL_INDIA_FILE, "ALL_INDIA"), (STATE_FILE, "STATE"),
        (DISTRICT_FILE, "DISTRICT"), (STEP04_CHECKS, "STEP04_CHECKS"),
        (STEP04_CONTROLS, "STEP04_CONTROLS"),
    ]
    for p, label in needed:
        require_file(p, label)
    if not errors:
        with STEP04_LOCK.open("r", encoding="utf-8") as fh:
            lock = json.load(fh)
        s4 = clean(lock.get("status"))
        add_check("STEP04_STATUS", "Step-04 lock status", "PASS", s4, s4 == "PASS")
        print(f"  Step-04 status            : {s4}")

    if errors:
        write_checks()
        finish(0, 0, 0)
        return 2

    validate_cube()
    total_controls, passed_controls = validate_controls()

    print("\n[4] Writing final submission files")
    copy_exact(CUBE_FILE, FINAL_CSV)
    copy_exact(ALL_INDIA_FILE, FINAL_ALL)
    copy_exact(STATE_FILE, FINAL_STATE)
    copy_exact(DISTRICT_FILE, FINAL_DISTRICT)
    add_check("FINAL_CSV_WRITTEN", "Primary final CSV written", "present", "present" if FINAL_CSV.exists() else "missing", FINAL_CSV.exists())
    add_check("FINAL_CSV_SIZE", "Primary final CSV non-empty", ">0", FINAL_CSV.stat().st_size if FINAL_CSV.exists() else 0, FINAL_CSV.exists() and FINAL_CSV.stat().st_size > 0)

    write_checks()
    write_manifest(total_controls, passed_controls)
    zip_files = build_zip()
    add_check("SUBMISSION_ZIP", "Submission ZIP written", "present", "present" if FINAL_ZIP.exists() else "missing", FINAL_ZIP.exists())
    # rewrite QA after final ZIP check
    write_checks()

    finish(total_controls, passed_controls, zip_files)
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"\nFATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
