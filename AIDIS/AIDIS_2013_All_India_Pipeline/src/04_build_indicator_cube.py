#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIDIS 2013 - Step 04: Weighted KPI / estimation cube
NSS 70th Round | Schedule 18.2

Fast-track production stage:
- consumes validated Step-02 stock and Step-03 flow household layers
- computes one reusable indicator cube for All-India, State and District
- keeps stock estimates on Visit-1 weights/universe
- keeps annual flow estimates on common-panel Visit-2 weights/universe
- writes All-India, State and District extracts in the same run

No third-party packages are required.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

SCRIPT_REVISION = "R1-FASTTRACK-INDICATOR-CUBE-2026-08-27"
EXPECTED_STOCK_HH = 110_800
EXPECTED_FLOW_HH = 108_421
EXPECTED_STATES = 36
EXPECTED_STATE_DISTRICTS = 634

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = PROJECT_ROOT / "cache"
OUTPUT_DATA_DIR = PROJECT_ROOT / "output" / "data"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"
for p in (CONFIG_DIR, CACHE_DIR, OUTPUT_DATA_DIR, REPORT_DIR):
    p.mkdir(parents=True, exist_ok=True)

STOCK_FILE = OUTPUT_DATA_DIR / "aidis_2013_household_stock.csv"
FLOW_FILE = OUTPUT_DATA_DIR / "aidis_2013_household_flow.csv"
STEP02_LOCK = CONFIG_DIR / "aidis_2013_step02_lock.json"
STEP03_LOCK = CONFIG_DIR / "aidis_2013_step03_lock.json"

CUBE_FILE = OUTPUT_DATA_DIR / "aidis_2013_indicator_cube.csv"
ALL_INDIA_FILE = OUTPUT_DATA_DIR / "aidis_2013_all_india_kpis.csv"
STATE_FILE = OUTPUT_DATA_DIR / "aidis_2013_state_kpis.csv"
DISTRICT_FILE = OUTPUT_DATA_DIR / "aidis_2013_district_kpis.csv"
CHECKS_FILE = CACHE_DIR / "step04_indicator_cube_checks.csv"
CONTROL_FILE = CACHE_DIR / "step04_official_control_validation.csv"
STEP04_LOCK = CONFIG_DIR / "aidis_2013_step04_lock.json"
SUMMARY_FILE = REPORT_DIR / "step04_indicator_cube_summary.txt"

errors: List[str] = []
warnings: List[str] = []
checks: List[dict] = []


def clean(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def num(v, default=0.0) -> float:
    s = clean(v).replace(",", "")
    if not s:
        return default
    try:
        x = float(s)
    except ValueError:
        return default
    return x if math.isfinite(x) else default


def disp(v: float, digits: int = 6) -> str:
    if not math.isfinite(v):
        return ""
    if abs(v) < 0.5 * 10 ** (-digits):
        v = 0.0
    return f"{v:.{digits}f}".rstrip("0").rstrip(".")


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        yield from csv.DictReader(fh)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


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


def sector_label(code: str) -> str:
    return "Rural" if code == "1" else "Urban" if code == "2" else "Unknown"


def geo_keys(row: dict) -> List[Tuple[str, str, str, str, str]]:
    state = clean(row.get("State"))
    district = clean(row.get("District_id"))
    sd = clean(row.get("State_District")) or (f"{state}-{district}" if state or district else "")
    return [
        ("ALL_INDIA", "ALL", "All India", "", ""),
        ("STATE", state, state, state, ""),
        ("DISTRICT", sd, sd, state, district),
    ]


def segment_keys(row: dict) -> List[Tuple[str, str]]:
    sec = sector_label(clean(row.get("Sector")))
    group = clean(row.get("household_group")) or "Unclassified"
    return [
        ("All", "All"),
        (sec, "All"),
        (sec, group),
    ]


STOCK_VALUE_FIELDS = [
    "land_value", "building_value", "livestock_value", "agricultural_machinery_value",
    "nonfarm_equipment_value", "transport_value", "shares_debentures_value",
    "financial_assets_value", "receivable_value", "total_assets",
]


def new_stock_acc():
    d = defaultdict(float)
    d["n"] = 0
    return d


def update_stock(acc: dict, r: dict):
    w = num(r.get("Weight_SC"))
    acc["n"] += 1
    acc["w"] += w
    for f in STOCK_VALUE_FIELDS:
        acc[f] += w * num(r.get(f))
    debt = num(r.get("debt_outstanding"))
    inst = num(r.get("institutional_debt"))
    noninst = num(r.get("noninstitutional_debt"))
    indebted = 1.0 if num(r.get("is_indebted")) > 0 else 0.0
    has_inst = 1.0 if num(r.get("has_institutional_debt")) > 0 else 0.0
    has_noninst = 1.0 if num(r.get("has_noninstitutional_debt")) > 0 else 0.0
    acc["debt"] += w * debt
    acc["inst_debt"] += w * inst
    acc["noninst_debt"] += w * noninst
    acc["borrower_w"] += w * indebted
    acc["inst_borrower_w"] += w * has_inst
    acc["noninst_borrower_w"] += w * has_noninst
    acc["bank_w"] += w * (1.0 if clean(r.get("bank_account")) == "1" else 0.0)
    acc["post_w"] += w * (1.0 if clean(r.get("post_office_account")) == "1" else 0.0)


def safe_div(a, b):
    return a / b if b else float("nan")


def stock_metrics(acc: dict) -> dict:
    w = acc["w"]
    out = {
        "sample_stock_n": int(acc["n"]),
        "weighted_households_stock": w,
        "ava": safe_div(acc["total_assets"], w),
        "ioi_pct": 100.0 * safe_div(acc["borrower_w"], w),
        "aod": safe_div(acc["debt"], w),
        "aodl": safe_div(acc["debt"], acc["borrower_w"]),
        "institutional_ioi_pct": 100.0 * safe_div(acc["inst_borrower_w"], w),
        "noninstitutional_ioi_pct": 100.0 * safe_div(acc["noninst_borrower_w"], w),
        "institutional_aod": safe_div(acc["inst_debt"], w),
        "noninstitutional_aod": safe_div(acc["noninst_debt"], w),
        "institutional_aodl": safe_div(acc["inst_debt"], acc["inst_borrower_w"]),
        "noninstitutional_aodl": safe_div(acc["noninst_debt"], acc["noninst_borrower_w"]),
        "bank_account_pct": 100.0 * safe_div(acc["bank_w"], w),
        "post_office_account_pct": 100.0 * safe_div(acc["post_w"], w),
    }
    for f in STOCK_VALUE_FIELDS[:-1]:
        out[f"avg_{f}"] = safe_div(acc[f], w)
    return out


def new_flow_acc():
    d = defaultdict(float)
    d["n"] = 0
    return d


def update_flow(acc: dict, r: dict):
    w = num(r.get("Weight_SC_flow"))
    acc["n"] += 1
    acc["w"] += w
    for stem in ("fce", "land_purchase", "normal_repairs", "disposals"):
        value = num(r.get(f"{stem}_annual"))
        has = 1.0 if value > 0 else 0.0
        acc[f"{stem}_amount"] += w * value
        acc[f"{stem}_participant_w"] += w * has


def flow_metrics(acc: dict) -> dict:
    w = acc["w"]
    out = {
        "sample_flow_n": int(acc["n"]),
        "weighted_households_flow": w,
    }
    for stem in ("fce", "land_purchase", "normal_repairs", "disposals"):
        amt = acc[f"{stem}_amount"]
        pw = acc[f"{stem}_participant_w"]
        out[f"{stem}_incidence_pct"] = 100.0 * safe_div(pw, w)
        out[f"avg_{stem}"] = safe_div(amt, w)
        out[f"avg_{stem}_among_participants"] = safe_div(amt, pw)
    return out


def key_for(g, s):
    level, geo_code, geo_name, state, district = g
    sector, group = s
    return (level, geo_code, geo_name, state, district, sector, group)


def build_accumulators():
    stock_acc: Dict[tuple, dict] = defaultdict(new_stock_acc)
    flow_acc: Dict[tuple, dict] = defaultdict(new_flow_acc)
    stock_hh_geo: Dict[str, Tuple[str, str, str]] = {}
    stock_count = 0
    stock_dups = 0
    seen_stock = set()

    print("\n[2] Aggregating Visit-1 stock indicators")
    for r in read_csv(STOCK_FILE):
        hhid = clean(r.get("HHID"))
        if hhid in seen_stock:
            stock_dups += 1
            continue
        seen_stock.add(hhid)
        stock_count += 1
        stock_hh_geo[hhid] = (clean(r.get("Sector")), clean(r.get("State")), clean(r.get("District_id")))
        gs = geo_keys(r)
        ss = segment_keys(r)
        for g in gs:
            for s in ss:
                update_stock(stock_acc[key_for(g, s)], r)

    print(f"  Stock households          : {stock_count:,}")
    print(f"  Duplicate stock HHIDs     : {stock_dups:,}")

    flow_count = 0
    flow_dups = 0
    flow_outside_stock = 0
    geo_mismatches = 0
    seen_flow = set()
    print("\n[3] Aggregating common-panel annual flow indicators")
    for r in read_csv(FLOW_FILE):
        hhid = clean(r.get("HHID"))
        if hhid in seen_flow:
            flow_dups += 1
            continue
        seen_flow.add(hhid)
        flow_count += 1
        if hhid not in stock_hh_geo:
            flow_outside_stock += 1
        else:
            a = stock_hh_geo[hhid]
            b = (clean(r.get("Sector")), clean(r.get("State")), clean(r.get("District_id")))
            if a != b:
                geo_mismatches += 1
        gs = geo_keys(r)
        ss = segment_keys(r)
        for g in gs:
            for s in ss:
                update_flow(flow_acc[key_for(g, s)], r)

    print(f"  Flow households           : {flow_count:,}")
    print(f"  Duplicate flow HHIDs      : {flow_dups:,}")
    print(f"  Flow HH outside stock     : {flow_outside_stock:,}")
    print(f"  Geography mismatches      : {geo_mismatches:,}")

    add_check("STOCK_COUNT", "Validated stock household count", EXPECTED_STOCK_HH, stock_count, stock_count == EXPECTED_STOCK_HH)
    add_check("STOCK_DUP", "Duplicate stock HHID", 0, stock_dups, stock_dups == 0)
    add_check("FLOW_COUNT", "Validated common-panel household count", EXPECTED_FLOW_HH, flow_count, flow_count == EXPECTED_FLOW_HH)
    add_check("FLOW_DUP", "Duplicate flow HHID", 0, flow_dups, flow_dups == 0)
    add_check("FLOW_SUBSET", "Flow HHID outside stock universe", 0, flow_outside_stock, flow_outside_stock == 0)
    add_check("FLOW_GEO_MATCH", "Stock/flow geography mismatch", 0, geo_mismatches, geo_mismatches == 0)

    states = {k[1] for k in stock_acc if k[0] == "STATE" and k[5] == "All" and k[6] == "All"}
    districts = {k[1] for k in stock_acc if k[0] == "DISTRICT" and k[5] == "All" and k[6] == "All"}
    print(f"  Observed states/UTs       : {len(states):,}")
    print(f"  State-district combos     : {len(districts):,}")
    add_check("STATE_COUNT", "Observed states/UTs", EXPECTED_STATES, len(states), len(states) == EXPECTED_STATES)
    add_check("DISTRICT_COUNT", "Observed state-district combinations", EXPECTED_STATE_DISTRICTS, len(districts), len(districts) == EXPECTED_STATE_DISTRICTS)

    return stock_acc, flow_acc


META_COLUMNS = ["geo_level", "geo_code", "geo_name", "State", "District_id", "Sector", "household_group"]
STOCK_COLUMNS = [
    "sample_stock_n", "weighted_households_stock", "ava", "ioi_pct", "aod", "aodl",
    "institutional_ioi_pct", "noninstitutional_ioi_pct", "institutional_aod", "noninstitutional_aod",
    "institutional_aodl", "noninstitutional_aodl", "bank_account_pct", "post_office_account_pct",
] + [f"avg_{f}" for f in STOCK_VALUE_FIELDS[:-1]]
FLOW_COLUMNS = ["sample_flow_n", "weighted_households_flow"] + [
    f"{stem}_{suffix}"
    for stem in ("fce", "land_purchase", "normal_repairs", "disposals")
    for suffix in ("incidence_pct",)
] + [
    f"avg_{stem}" for stem in ("fce", "land_purchase", "normal_repairs", "disposals")
] + [
    f"avg_{stem}_among_participants" for stem in ("fce", "land_purchase", "normal_repairs", "disposals")
]
OUTPUT_COLUMNS = META_COLUMNS + STOCK_COLUMNS + FLOW_COLUMNS


def combine_rows(stock_acc, flow_acc):
    keys = sorted(set(stock_acc) | set(flow_acc), key=lambda k: ("ALL_INDIA", "STATE", "DISTRICT").index(k[0]) * 10**9 if k[0] in {"ALL_INDIA","STATE","DISTRICT"} else 9*10**9)
    # deterministic richer sort
    keys = sorted(set(stock_acc) | set(flow_acc), key=lambda k: (
        {"ALL_INDIA": 0, "STATE": 1, "DISTRICT": 2}.get(k[0], 9),
        k[3], k[4], {"All": 0, "Rural": 1, "Urban": 2}.get(k[5], 9), k[6]
    ))
    rows = []
    for k in keys:
        level, geo_code, geo_name, state, district, sector, group = k
        row = {
            "geo_level": level,
            "geo_code": geo_code,
            "geo_name": geo_name,
            "State": state,
            "District_id": district,
            "Sector": sector,
            "household_group": group,
        }
        if k in stock_acc:
            row.update(stock_metrics(stock_acc[k]))
        if k in flow_acc:
            row.update(flow_metrics(flow_acc[k]))
        rows.append(row)
    return rows


def write_rows(path: Path, rows: Iterable[dict]):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        wr.writeheader()
        for src in rows:
            row = {}
            for c in OUTPUT_COLUMNS:
                v = src.get(c, "")
                if isinstance(v, float):
                    v = disp(v)
                row[c] = v
            wr.writerow(row)


def validate_controls(rows: List[dict]):
    print("\n[5] Validating All-India KPI anchors")
    lookup = {(r["geo_level"], r["Sector"], r["household_group"]): r for r in rows if r["geo_level"] == "ALL_INDIA"}

    # (id, sector, metric, published, absolute tolerance)
    anchors = [
        ("AVA_RURAL", "Rural", "ava", 1006985.0, 0.02 * 1006985.0),
        ("AVA_URBAN", "Urban", "ava", 2285135.0, 0.02 * 2285135.0),
        ("IOI_RURAL", "Rural", "ioi_pct", 31.44, 0.10),
        ("AOD_RURAL", "Rural", "aod", 32522.0, 10.0),
        ("AODL_RURAL", "Rural", "aodl", 103457.0, 25.0),
        ("IOI_URBAN", "Urban", "ioi_pct", 22.37, 0.10),
        ("AOD_URBAN", "Urban", "aod", 84625.0, 20.0),
        ("AODL_URBAN", "Urban", "aodl", 378238.0, 50.0),
        ("INST_IOI_RURAL", "Rural", "institutional_ioi_pct", 17.2, 0.10),
        ("NONINST_IOI_RURAL", "Rural", "noninstitutional_ioi_pct", 19.0, 0.10),
        ("INST_IOI_URBAN", "Urban", "institutional_ioi_pct", 14.8, 0.10),
        ("NONINST_IOI_URBAN", "Urban", "noninstitutional_ioi_pct", 10.3, 0.10),
        ("FCE_INCIDENCE_RURAL", "Rural", "fce_incidence_pct", 31.1, 0.50),
        ("FCE_INCIDENCE_URBAN", "Urban", "fce_incidence_pct", 15.2, 0.50),
        ("FCE_AVG_RURAL", "Rural", "avg_fce", 10717.0, 0.02 * 10717.0),
        ("FCE_AVG_URBAN", "Urban", "avg_fce", 14493.0, 0.02 * 14493.0),
        ("LAND_AVG_RURAL", "Rural", "avg_land_purchase", 795.0, 40.0),
        ("LAND_AVG_URBAN", "Urban", "avg_land_purchase", 1441.0, 75.0),
    ]
    validation = []
    for cid, sec, metric, published, tol in anchors:
        r = lookup.get(("ALL_INDIA", sec, "All"), {})
        actual = r.get(metric, float("nan"))
        passed = isinstance(actual, (int, float)) and math.isfinite(actual) and abs(actual - published) <= tol
        validation.append({
            "control_id": cid, "sector": sec, "metric": metric,
            "published_value": disp(published), "computed_value": disp(actual) if isinstance(actual, (int,float)) else "",
            "absolute_tolerance": disp(tol), "difference": disp(actual-published) if isinstance(actual,(int,float)) and math.isfinite(actual) else "",
            "status": "PASS" if passed else "FAIL",
        })
        add_check(f"CONTROL_{cid}", f"All-India {sec} {metric}", published, disp(actual, 3) if isinstance(actual,(int,float)) else "", passed)
        print(f"  {cid:24s} | computed={actual:12,.3f} | published={published:12,.3f} | {'PASS' if passed else 'FAIL'}")

    with CONTROL_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        cols = ["control_id", "sector", "metric", "published_value", "computed_value", "difference", "absolute_tolerance", "status"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader(); wr.writerows(validation)
    return validation


def write_checks():
    with CHECKS_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        cols = ["check_id", "description", "expected", "actual", "status"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader(); wr.writerows(checks)


def main():
    print("=" * 78)
    print("AIDIS 2013 - STEP 04 WEIGHTED KPI / INDICATOR CUBE")
    print("NSS 70th Round | Schedule 18.2")
    print("=" * 78)
    print(f"Project root              : {PROJECT_ROOT}")
    print(f"Script revision           : {SCRIPT_REVISION}")

    print("\n[1] Validating upstream locks")
    for p, label in [(STOCK_FILE,"STOCK"),(FLOW_FILE,"FLOW"),(STEP02_LOCK,"STEP02_LOCK"),(STEP03_LOCK,"STEP03_LOCK")]:
        require_file(p, label)
    if errors:
        finish([], [])
        return 2

    l2 = read_json(STEP02_LOCK)
    l3 = read_json(STEP03_LOCK)
    s2 = clean(l2.get("status"))
    s3 = clean(l3.get("status"))
    ok2 = s2 in {"PASS", "PASS_WITH_DISCLOSURES"}
    ok3 = s3 == "PASS"
    add_check("STEP02_STATUS", "Step-02 lock status", "PASS/PASS_WITH_DISCLOSURES", s2, ok2)
    add_check("STEP03_STATUS", "Step-03 lock status", "PASS", s3, ok3)
    print(f"  Step-02 status            : {s2}")
    print(f"  Step-03 status            : {s3}")
    if errors:
        finish([], [])
        return 2

    stock_acc, flow_acc = build_accumulators()
    print("\n[4] Building All-India / State / District indicator cube")
    rows = combine_rows(stock_acc, flow_acc)
    all_rows = [r for r in rows if r["geo_level"] == "ALL_INDIA"]
    state_rows = [r for r in rows if r["geo_level"] == "STATE"]
    district_rows = [r for r in rows if r["geo_level"] == "DISTRICT"]
    print(f"  Cube rows                 : {len(rows):,}")
    print(f"  All-India rows            : {len(all_rows):,}")
    print(f"  State rows                : {len(state_rows):,}")
    print(f"  District rows             : {len(district_rows):,}")
    add_check("CUBE_NONEMPTY", "Indicator cube has rows", ">0", len(rows), len(rows) > 0)

    validation = validate_controls(rows)

    print("\n[6] Writing Step-04 outputs")
    write_rows(CUBE_FILE, rows)
    write_rows(ALL_INDIA_FILE, all_rows)
    write_rows(STATE_FILE, state_rows)
    write_rows(DISTRICT_FILE, district_rows)
    write_checks()

    finish(rows, validation)
    return 1 if errors else 0


def finish(rows: List[dict], validation: List[dict]):
    status = "FAIL" if errors else ("PASS_WITH_WARNINGS" if warnings else "PASS")
    hard_pass = sum(1 for r in validation if r.get("status") == "PASS")
    lock = {
        "step": "04",
        "name": "Weighted KPI / All-India-State-District indicator cube",
        "status": status,
        "script_revision": SCRIPT_REVISION,
        "project_root": str(PROJECT_ROOT),
        "estimation": {
            "stock_universe": "Visit-1 household universe",
            "stock_weight": "Visit-1 Weight_SC",
            "flow_universe": "Exact Visit-1/Visit-2 common panel",
            "flow_weight": "Visit-2 Weight_SC",
        },
        "rows": {
            "cube": len(rows),
            "all_india": sum(1 for r in rows if r.get("geo_level") == "ALL_INDIA"),
            "state": sum(1 for r in rows if r.get("geo_level") == "STATE"),
            "district": sum(1 for r in rows if r.get("geo_level") == "DISTRICT"),
        },
        "official_controls": {"total": len(validation), "passed": hard_pass},
        "errors": errors,
        "warnings": warnings,
        "outputs": {
            "indicator_cube": str(CUBE_FILE),
            "all_india": str(ALL_INDIA_FILE),
            "state": str(STATE_FILE),
            "district": str(DISTRICT_FILE),
            "checks": str(CHECKS_FILE),
            "controls": str(CONTROL_FILE),
            "summary": str(SUMMARY_FILE),
        },
    }
    with STEP04_LOCK.open("w", encoding="utf-8") as fh:
        json.dump(lock, fh, indent=2)

    lines = [
        "=" * 78,
        "AIDIS 2013 - STEP 04 WEIGHTED KPI / INDICATOR CUBE SUMMARY",
        "=" * 78,
        "",
        f"Project root              : {PROJECT_ROOT}",
        f"Script revision           : {SCRIPT_REVISION}",
        "",
        "ESTIMATION BASES",
        "----------------",
        "Stock universe             : Visit-1 / 110,800 households",
        "Stock weight               : Visit-1 Weight_SC",
        "Annual flow universe       : Common panel / 108,421 households",
        "Annual flow weight         : Visit-2 Weight_SC",
        "",
        "OUTPUTS",
        "-------",
        f"Indicator cube rows        : {len(rows):,}",
        f"All-India rows             : {sum(1 for r in rows if r.get('geo_level') == 'ALL_INDIA'):,}",
        f"State rows                 : {sum(1 for r in rows if r.get('geo_level') == 'STATE'):,}",
        f"District rows              : {sum(1 for r in rows if r.get('geo_level') == 'DISTRICT'):,}",
        "",
        "VALIDATION",
        "----------",
        f"Official anchors           : {len(validation)}",
        f"Official anchors passed    : {hard_pass}",
        f"Checks                     : {len(checks)}",
        f"Failed checks              : {len(errors)}",
        f"Warnings                   : {len(warnings)}",
        "",
        f"Indicator cube             : {CUBE_FILE}",
        f"All-India KPIs             : {ALL_INDIA_FILE}",
        f"State KPIs                 : {STATE_FILE}",
        f"District KPIs              : {DISTRICT_FILE}",
        f"Step-04 lock               : {STEP04_LOCK}",
    ]
    if warnings:
        lines += ["", "WARNINGS:"] + [f"  - {x}" for x in warnings]
    if errors:
        lines += ["", "ERRORS:"] + [f"  - {x}" for x in errors]
    lines += ["", f"STEP 04 STATUS: {status}", "=" * 78]
    text = "\n".join(lines)
    SUMMARY_FILE.write_text(text + "\n", encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"\nFATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
