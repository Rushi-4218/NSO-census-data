#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIDIS 2013 - Step 06: Export in AIDIS 2003-compatible publication template
NSS 70th Round | Schedule 18.2

Purpose
-------
Transforms the validated Step-02/03/04 outputs into the same normalized/long
22-column publication layout used by the supplied AIDIS 2003 final CSV.

The calculation pipeline is NOT changed. This stage only adds publication
metrics that can be derived from the validated household layers and formats
all results into the target schema.

Output schema (exact order):
Survey_ID, Survey_NAME, Survey_GROUP_ID, GROUP_NAME, SUB_GROUP_ID,
SUB_GROUP_NAME, Year, FREQ_DESC, State_ID, State_Name, District_ID,
District_Name, Sector_code, Sector, Published_date, Extracted_Date,
Visit_ID, Col_ID, COL_DESC, DATA, Unit, Source

Groups reproduced from the reference template:
1. Household Assets and Debt
2. Assets by Component
3. Credit Distribution and Characteristics
4. Asset-Holding Deciles (All-India + State)
5. Capital Expenditure (All-India + State)
6. Asset Inequality (All-India + State)

Important 2013 methodology carried forward:
- Stock: Visit-1 Weight_SC, 110,800 households
- Flow: exact Visit-1/Visit-2 common panel, Visit-2 Weight_SC, 108,421 HH
- FCE: q4+q5+q6+q7 excluding only q4 on land items 1,4,5,14
- Purchase of land: q4 only on land items 1,4,5,14
- Consumer durables and bullion/ornaments are excluded from 2013 AVA per lock
- Block-10 released value field remains 0 / no imputation

No recalculation can alter Step-04 validated anchors.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

SCRIPT_REVISION = "R1-2003-TEMPLATE-COMPATIBLE-2026-08-27"

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = PROJECT_ROOT / "cache"
OUTPUT_DATA_DIR = PROJECT_ROOT / "output" / "data"
SUBMISSION_DIR = PROJECT_ROOT / "output" / "submission"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"
for d in (CONFIG_DIR, CACHE_DIR, OUTPUT_DATA_DIR, SUBMISSION_DIR, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

STOCK_FILE = OUTPUT_DATA_DIR / "aidis_2013_household_stock.csv"
FLOW_FILE = OUTPUT_DATA_DIR / "aidis_2013_household_flow.csv"
CUBE_FILE = OUTPUT_DATA_DIR / "aidis_2013_indicator_cube.csv"
STEP04_LOCK = CONFIG_DIR / "aidis_2013_step04_lock.json"
AGENCY_CODEBOOK = CONFIG_DIR / "aidis_2013_credit_agency_codebook.csv"
INTEREST_CODEBOOK = CONFIG_DIR / "aidis_2013_interest_codebook.csv"
PURPOSE_CODEBOOK = CONFIG_DIR / "aidis_2013_credit_purpose_codebook.csv"

FINAL_CSV = SUBMISSION_DIR / "AIDIS_2013_All_India_States_Districts_Final.csv"
FINAL_XLSX = SUBMISSION_DIR / "AIDIS_2013_All_India_States_Districts_Final.xlsx"
FINAL_ZIP = SUBMISSION_DIR / "AIDIS_2013_Reference_Template_Final.zip"
QA_FILE = CACHE_DIR / "step06_reference_template_checks.csv"
SUMMARY_FILE = REPORT_DIR / "step06_reference_template_summary.txt"
STEP06_LOCK = CONFIG_DIR / "aidis_2013_step06_lock.json"

SURVEY_ID = "AIDIS_70_2013"
SURVEY_NAME = "All India Debt and Investment Survey (AIDIS), NSS 70th Round"
YEAR = "2013"
FREQ_DESC = "Annual"
PUBLISHED_DATE = "19-Dec-14"
EXTRACTED_DATE = datetime.now().strftime("%d-%b-%y")
SOURCE_V1 = "https://microdata.gov.in/NADA/index.php/catalog/130"
SOURCE_V2 = "https://microdata.gov.in/NADA/index.php/catalog/132"

COLUMNS = [
    "Survey_ID", "Survey_NAME", "Survey_GROUP_ID", "GROUP_NAME",
    "SUB_GROUP_ID", "SUB_GROUP_NAME", "Year", "FREQ_DESC",
    "State_ID", "State_Name", "District_ID", "District_Name",
    "Sector_code", "Sector", "Published_date", "Extracted_Date",
    "Visit_ID", "Col_ID", "COL_DESC", "DATA", "Unit", "Source",
]

STATE_NAMES = {
    "1": "Jammu & Kashmir", "2": "Himachal Pradesh", "3": "Punjab",
    "4": "Chandigarh", "5": "Uttarakhand", "6": "Haryana",
    "7": "Delhi", "8": "Rajasthan", "9": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman & Diu", "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana",
}

GROUP_NAMES = {
    "1": "Household Assets and Debt",
    "2": "Assets by Component",
    "3": "Credit Distribution and Characteristics",
    "4": "Asset-Holding Deciles",
    "5": "Capital Expenditure",
    "6": "Asset Inequality",
}

checks: List[dict] = []
warnings: List[str] = []
errors: List[str] = []


def clean(v) -> str:
    return "" if v is None else str(v).strip()


def num(v, default=0.0) -> float:
    s = clean(v).replace(",", "")
    if not s:
        return default
    try:
        x = float(s)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def code(v) -> str:
    s = clean(v)
    if not s:
        return ""
    try:
        x = float(s)
        if x.is_integer():
            return str(int(x))
    except Exception:
        pass
    s2 = s.lstrip("0")
    return s2 or "0"


def fmt(v, unit="") -> str:
    if v is None:
        return ""
    try:
        x = float(v)
    except Exception:
        return clean(v)
    if not math.isfinite(x):
        return ""
    if unit == "Number" and abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    if abs(x) < 5e-13:
        x = 0.0
    return f"{x:.10f}".rstrip("0").rstrip(".")


def add_check(cid, desc, expected, actual, passed, severity="ERROR"):
    status = "PASS" if passed else severity
    checks.append({"check_id": cid, "description": desc, "expected": expected, "actual": actual, "status": status})
    if not passed:
        msg = f"{cid}: {desc} | expected={expected} actual={actual}"
        (warnings if severity == "WARNING" else errors).append(msg)


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        yield from csv.DictReader(fh)


def require_file(path: Path, label: str):
    ok = path.exists() and path.is_file() and path.stat().st_size > 0
    add_check(f"FILE_{label}", f"Required file exists: {path.name}", "present", "present" if ok else "missing", ok)
    return ok


def norm_sector(v) -> Tuple[str, str]:
    s = clean(v).lower()
    if s in {"1", "rural"}:
        return "1", "Rural"
    if s in {"2", "urban"}:
        return "2", "Urban"
    return "0", "Total"


def norm_occ(v) -> Tuple[str, str]:
    s = clean(v).lower().replace("_", " ")
    if s in {"", "all", "all hh", "all households"}:
        return "All HH", "All HH"
    if "non" in s and "cult" in s:
        return "Non-Cultivator HH", "Non-Cultivator HH"
    if "cult" in s:
        return "Cultivator HH", "Cultivator HH"
    if "self" in s:
        return "Self-employed", "Self-employed"
    if "other" in s:
        return "Others", "Others"
    return clean(v), clean(v)


def state_district_id(row: dict) -> str:
    sd = code(row.get("State_District"))
    if sd:
        return sd
    st = code(row.get("State"))
    di = code(row.get("District_id"))
    if st and di and st.isdigit() and di.isdigit():
        return str(int(st) * 100 + int(di))
    return f"{st}{di}"


def segment_keys_from_household(row: dict, include_district=True) -> List[tuple]:
    st = code(row.get("State"))
    sd = state_district_id(row)
    sec_code, _ = norm_sector(row.get("Sector"))
    occ, _ = norm_occ(row.get("household_group"))
    geos = [("ALL_INDIA", "0", "0"), ("STATE", st, "0")]
    if include_district:
        geos.append(("DISTRICT", st, sd))
    out = []
    for level, state_id, district_id in geos:
        out.append((level, state_id, district_id, "0", "All HH"))
        out.append((level, state_id, district_id, sec_code, "All HH"))
        if occ != "All HH":
            out.append((level, state_id, district_id, sec_code, occ))
    return out


def segment_key_from_cube(row: dict) -> tuple:
    level = clean(row.get("geo_level"))
    if level == "ALL_INDIA":
        st, di = "0", "0"
    elif level == "STATE":
        st, di = code(row.get("State") or row.get("geo_code")), "0"
    else:
        st, di = code(row.get("State")), code(row.get("geo_code"))
    sec_code, _ = norm_sector(row.get("Sector"))
    occ, _ = norm_occ(row.get("household_group"))
    return (level, st, di, sec_code, occ)


def metadata_for_key(key: tuple) -> dict:
    level, st, di, sec_code, occ = key
    if level == "ALL_INDIA":
        state_name = "All India"
        district_name = "All Districts"
    else:
        state_name = STATE_NAMES.get(st, f"State code {st}")
        if di == "0":
            district_name = "All Districts"
        else:
            local = ""
            if di.isdigit() and st.isdigit():
                # State_District convention is normally state*100 + local district code.
                local_num = int(di) - int(st) * 100
                if 0 <= local_num <= 99:
                    local = str(local_num)
            if not local:
                local = code(di[-2:]) if len(di) >= 2 else code(di)
            district_name = f"District code {int(local):02d}" if local.isdigit() else f"District code {local}"
    sector_name = {"0": "Total", "1": "Rural", "2": "Urban"}.get(sec_code, "Total")
    return {
        "State_ID": st, "State_Name": state_name,
        "District_ID": di, "District_Name": district_name,
        "Sector_code": sec_code, "Sector": sector_name,
        "SUB_GROUP_ID": occ, "SUB_GROUP_NAME": occ,
    }


def make_row(key: tuple, group_id: str, subgroup_id: str, subgroup_name: str,
             visit_id: str, col_id: str, desc: str, value, unit: str, source: str) -> dict:
    m = metadata_for_key(key)
    m["SUB_GROUP_ID"] = subgroup_id
    m["SUB_GROUP_NAME"] = subgroup_name
    return {
        "Survey_ID": SURVEY_ID,
        "Survey_NAME": SURVEY_NAME,
        "Survey_GROUP_ID": group_id,
        "GROUP_NAME": GROUP_NAMES[group_id],
        "SUB_GROUP_ID": subgroup_id,
        "SUB_GROUP_NAME": subgroup_name,
        "Year": YEAR,
        "FREQ_DESC": FREQ_DESC,
        "State_ID": m["State_ID"],
        "State_Name": m["State_Name"],
        "District_ID": m["District_ID"],
        "District_Name": m["District_Name"],
        "Sector_code": m["Sector_code"],
        "Sector": m["Sector"],
        "Published_date": PUBLISHED_DATE,
        "Extracted_Date": EXTRACTED_DATE,
        "Visit_ID": visit_id,
        "Col_ID": col_id,
        "COL_DESC": desc,
        "DATA": fmt(value, unit),
        "Unit": unit,
        "Source": source,
    }


# -----------------------------------------------------------------------------
# Step-02 helper import for XLSX streaming
# -----------------------------------------------------------------------------
def load_step02_helper():
    candidates = [SRC_DIR / "02_build_household_stock.py", SRC_DIR / "02_build_household_stock_r2.py"]
    for p in candidates:
        if p.exists():
            spec = importlib.util.spec_from_file_location("aidis_step02_helper", p)
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("02_build_household_stock.py / R2 helper not found in src")


# -----------------------------------------------------------------------------
# Group 1 + Group 2 + occupational Group 5 directly from validated Step-04 cube
# -----------------------------------------------------------------------------
GROUP1 = [
    ("AOD", "aod", "Average Amount of Debt (AOD) per HH", "Rs. per HH"),
    ("AODL", "aodl", "Average Amount of Debt per Indebted Household (AODL)", "Rs. per indebted HH"),
    ("AVA", "ava", "Average Value of Assets (AVA)", "Rs. per HH"),
    ("DAR", "__dar__", "Debt Asset Ratio (DAR)", "Ratio"),
    ("HH_SURVEYED", "sample_stock_n", "No. of Households Surveyed", "Number"),
    ("IOI", "ioi_pct", "Incidence of Indebtedness (IOI)", "Percent"),
]

GROUP2 = [
    ("AVA_COMPONENT_AGRICULTURAL_MACHINERY_EQUIPMENT", "avg_agricultural_machinery_value", "Average Value of Assets - Agricultural machinery & equipment", "Rs. per HH"),
    ("AVA_COMPONENT_BUILDINGS", "avg_building_value", "Average Value of Assets - Buildings", "Rs. per HH"),
    ("AVA_COMPONENT_DEPOSITS", "avg_financial_assets_value", "Average Value of Assets - Deposits and other financial assets", "Rs. per HH"),
    ("AVA_COMPONENT_FINANCIAL_ASSETS", "__financial_assets__", "Average Value of Assets - Financial assets", "Rs. per HH"),
    ("AVA_COMPONENT_LAND", "avg_land_value", "Average Value of Assets - Land", "Rs. per HH"),
    ("AVA_COMPONENT_LIVESTOCK_POULTRY", "avg_livestock_value", "Average Value of Assets - Livestock & poultry", "Rs. per HH"),
    ("AVA_COMPONENT_NON_FARM_BUSINESS_EQUIPMENT", "avg_nonfarm_equipment_value", "Average Value of Assets - Non-farm business equipment", "Rs. per HH"),
    ("AVA_COMPONENT_OTHERS", "__others__", "Average Value of Assets - Others (shares/debentures + loans receivable; consumer durables excluded in 2013 lock)", "Rs. per HH"),
    ("AVA_COMPONENT_PHYSICAL_ASSETS", "__physical_assets__", "Average Value of Assets - Physical assets", "Rs. per HH"),
    ("AVA_COMPONENT_TRANSPORT_EQUIPMENT", "avg_transport_value", "Average Value of Assets - Transport equipment", "Rs. per HH"),
]


def cube_value(r: dict, metric: str):
    if metric == "__dar__":
        ava, aod = num(r.get("ava")), num(r.get("aod"))
        return aod / ava if ava else None
    if metric == "__others__":
        return num(r.get("avg_shares_debentures_value")) + num(r.get("avg_receivable_value"))
    if metric == "__financial_assets__":
        return (num(r.get("avg_financial_assets_value")) + num(r.get("avg_shares_debentures_value")) + num(r.get("avg_receivable_value")))
    if metric == "__physical_assets__":
        return sum(num(r.get(c)) for c in [
            "avg_land_value", "avg_building_value", "avg_livestock_value",
            "avg_agricultural_machinery_value", "avg_nonfarm_equipment_value",
            "avg_transport_value",
        ])
    s = clean(r.get(metric))
    return None if not s else num(s)


def build_cube_rows(cube_rows: List[dict], final_rows: List[dict], cube_lookup: dict):
    for r in cube_rows:
        key = segment_key_from_cube(r)
        cube_lookup[key] = r
        occ = key[4]
        for col_id, metric, base_desc, unit in GROUP1:
            final_rows.append(make_row(key, "1", occ, occ, "1", col_id, f"{base_desc} - {occ}", cube_value(r, metric), unit, SOURCE_V1))
        for col_id, metric, base_desc, unit in GROUP2:
            final_rows.append(make_row(key, "2", occ, occ, "1", col_id, f"{base_desc} - {occ}", cube_value(r, metric), unit, SOURCE_V1))
        # Reference group 5 occupational rows exist only at All-India and State level.
        if key[0] in {"ALL_INDIA", "STATE"}:
            final_rows.append(make_row(key, "5", occ, occ, "2", "EPL",
                f"Average Expenditure on Purchase of Land per HH - Occupational Category: {occ}",
                cube_value(r, "avg_land_purchase"), "Rs. per HH", SOURCE_V2))
            final_rows.append(make_row(key, "5", occ, occ, "2", "FCE",
                f"Average Fixed Capital Expenditure per HH - Occupational Category: {occ}",
                cube_value(r, "avg_fce"), "Rs. per HH", SOURCE_V2))


# -----------------------------------------------------------------------------
# Load household layers and member lists (for Gini/deciles/interest IOI)
# -----------------------------------------------------------------------------
def load_households():
    stock = {}
    members = defaultdict(list)  # all-India + State only; reference groups 4-6
    for r in read_csv(STOCK_FILE):
        h = clean(r.get("HHID"))
        if not h:
            continue
        rec = dict(r)
        rec["_w"] = num(r.get("Weight_SC"))
        rec["_assets"] = num(r.get("total_assets"))
        rec["_debt"] = num(r.get("debt_outstanding"))
        stock[h] = rec
        for key in segment_keys_from_household(rec, include_district=False):
            members[key].append(h)
    flow = {}
    for r in read_csv(FLOW_FILE):
        h = clean(r.get("HHID"))
        if h:
            flow[h] = r
    return stock, flow, members


def weighted_decile_assignment(hhids: List[str], stock: dict) -> Dict[str, int]:
    vals = [(h, stock[h]["_assets"], stock[h]["_w"]) for h in hhids if stock[h]["_w"] > 0]
    vals.sort(key=lambda t: (t[1], t[0]))
    W = sum(w for _, _, w in vals)
    if W <= 0:
        return {}
    out = {}
    cum = 0.0
    for h, _, w in vals:
        midpoint = cum + 0.5 * w
        d = min(10, max(1, int(midpoint / W * 10.0) + 1))
        out[h] = d
        cum += w
    return out


def weighted_gini(hhids: List[str], stock: dict):
    vals = [(stock[h]["_assets"], stock[h]["_w"]) for h in hhids if stock[h]["_w"] > 0]
    if not vals:
        return None
    vals.sort(key=lambda t: t[0])
    W = sum(w for _, w in vals)
    X = sum(x * w for x, w in vals)
    if W <= 0 or X <= 0:
        return None
    prev_p = prev_l = 0.0
    cum_w = cum_x = area = 0.0
    for x, w in vals:
        cum_w += w
        cum_x += x * w
        p = cum_w / W
        l = cum_x / X
        area += 0.5 * (prev_l + l) * (p - prev_p)
        prev_p, prev_l = p, l
    return max(0.0, min(1.0, 1.0 - 2.0 * area))


def build_decile_gini_rows(stock: dict, flow: dict, members: dict, final_rows: List[dict]):
    print("\n[5] Building asset-decile, capital-expenditure-decile and Gini rows")
    decile_segment_count = 0
    for key in sorted(members, key=segment_sort_key):
        hhids = members[key]
        if not hhids:
            continue
        assignment = weighted_decile_assignment(hhids, stock)
        occ = key[4]
        # Group 6: one Gini per standard segment, all-India + State only.
        g = weighted_gini(hhids, stock)
        final_rows.append(make_row(key, "6", occ, occ, "1", "GINI_ASSET",
            f"Gini's Coefficient of Asset Holdings - {occ}", g, "Coefficient", SOURCE_V1))

        # Group 4: AVA/AOD/DAR by decile for every occupational segment.
        agg = {d: defaultdict(float) for d in range(1, 11)}
        for h in hhids:
            d = assignment.get(h)
            if not d:
                continue
            s = stock[h]
            w = s["_w"]
            agg[d]["w"] += w
            agg[d]["assets"] += w * s["_assets"]
            agg[d]["debt"] += w * s["_debt"]
        for d in range(1, 11):
            a = agg[d]
            w = a["w"]
            ava = a["assets"] / w if w else None
            aod = a["debt"] / w if w else None
            dar = aod / ava if ava not in (None, 0) else None
            sg = f"D{d}"
            sgn = f"Asset Decile {d}"
            final_rows.append(make_row(key, "4", sg, sgn, "1", f"DECILE_{d}_AOD",
                f"AOD by Asset-Holding Decile {d} - {occ}", aod, "Rs. per HH", SOURCE_V1))
            final_rows.append(make_row(key, "4", sg, sgn, "1", f"DECILE_{d}_AVA",
                f"AVA by Asset-Holding Decile {d} - {occ}", ava, "Rs. per HH", SOURCE_V1))
            final_rows.append(make_row(key, "4", sg, sgn, "1", f"DECILE_{d}_DAR",
                f"DAR by Asset-Holding Decile {d} - {occ}", dar, "Ratio", SOURCE_V1))

        # Group 5 deciles in the supplied reference are produced only for All HH
        # at Total/Rural/Urban sector level, not occupational subgroups.
        if occ == "All HH":
            fagg = {d: defaultdict(float) for d in range(1, 11)}
            for h in hhids:
                d = assignment.get(h)
                fr = flow.get(h)
                if not d or fr is None:
                    continue
                w2 = num(fr.get("Weight_SC_flow"))
                if w2 <= 0:
                    continue
                fagg[d]["w"] += w2
                fagg[d]["fce"] += w2 * num(fr.get("fce_annual"))
                fagg[d]["epl"] += w2 * num(fr.get("land_purchase_annual"))
            for d in range(1, 11):
                a = fagg[d]
                w = a["w"]
                fce = a["fce"] / w if w else None
                epl = a["epl"] / w if w else None
                sg = f"D{d}"
                sgn = f"Asset Decile {d}"
                final_rows.append(make_row(key, "5", sg, sgn, "2", f"DECILE_{d}_EPL",
                    f"Average Expenditure on Purchase of Land per HH - Asset Decile {d} - All HH",
                    epl, "Rs. per HH", SOURCE_V2))
                final_rows.append(make_row(key, "5", sg, sgn, "2", f"DECILE_{d}_FCE",
                    f"Average Fixed Capital Expenditure per HH - Asset Decile {d} - All HH",
                    fce, "Rs. per HH", SOURCE_V2))
        decile_segment_count += 1
    print(f"  All-India/State segments  : {decile_segment_count:,}")


# -----------------------------------------------------------------------------
# Group 3 detailed loan characteristics from Visit-1 Block 14
# -----------------------------------------------------------------------------
AGENCY_INFO = {
    "CREDIT_SOURCE_GOVERNMENT": ("Institutional", "Government"),
    "CREDIT_SOURCE_COOP_SOCIETY_BANK": ("Institutional", "Co-operative society / co-operative bank"),
    "CREDIT_SOURCE_COMMERCIAL_BANK_INCL_RRB": ("Institutional", "Commercial bank including regional rural bank"),
    "CREDIT_SOURCE_INSURANCE": ("Institutional", "Insurance"),
    "CREDIT_SOURCE_PROVIDENT_FUND": ("Institutional", "Provident fund"),
    "CREDIT_SOURCE_FINANCIAL_CORP_INSTITUTION": ("Institutional", "Financial corporation / institution"),
    "CREDIT_SOURCE_FINANCIAL_COMPANY": ("Institutional", "Financial company"),
    "CREDIT_SOURCE_OTHER_INSTITUTIONAL_AGENCIES": ("Institutional", "Other institutional agency"),
    "CREDIT_SOURCE_LANDLORD": ("Non-institutional", "Landlord"),
    "CREDIT_SOURCE_AGRICULTURIST_MONEYLENDER": ("Non-institutional", "Agriculturist money lender"),
    "CREDIT_SOURCE_PROFESSIONAL_MONEYLENDER": ("Non-institutional", "Professional money lender"),
    "CREDIT_SOURCE_TRADER": ("Non-institutional", "Trader"),
    "CREDIT_SOURCE_RELATIVES_FRIENDS": ("Non-institutional", "Relatives and friends"),
    "CREDIT_SOURCE_PROFESSIONALS": ("Non-institutional", "Doctors, lawyers and other professionals"),
    "CREDIT_SOURCE_OTHER_NON_INSTITUTIONAL_AGENCIES": ("Non-institutional", "Other agency"),
}

PURPOSE_LABELS = {
    "01": "Capital expenditure in farm business",
    "02": "Current/revenue expenditure in farm business",
    "03": "Capital expenditure in non-farm business",
    "04": "Current/revenue expenditure in non-farm business",
    "05": "Household expenditure",
    "06": "Litigation",
    "07": "Repayment of debt",
    "08": "Financial investment expenditure",
    "09": "Other purpose",
}

INTEREST_LABELS = {"1": "Interest-free", "2": "Simple interest", "3": "Compound interest", "4": "Concessional rate"}


def load_codebook(path: Path):
    return list(read_csv(path)) if path.exists() else []


def row_text(r: dict) -> str:
    return " ".join(clean(v) for v in r.values()).lower().replace("-", " ")


def agency_target(text: str, agency_class: str) -> str:
    t = text.lower().replace("-", " ")
    if "government" in t:
        return "CREDIT_SOURCE_GOVERNMENT"
    if "co operative" in t or "cooperative" in t:
        return "CREDIT_SOURCE_COOP_SOCIETY_BANK"
    if "commercial bank" in t or "regional rural" in t or "rrb" in t:
        return "CREDIT_SOURCE_COMMERCIAL_BANK_INCL_RRB"
    if "insurance" in t:
        return "CREDIT_SOURCE_INSURANCE"
    if "provident" in t:
        return "CREDIT_SOURCE_PROVIDENT_FUND"
    if "financial corporation" in t or "financial institution" in t:
        return "CREDIT_SOURCE_FINANCIAL_CORP_INSTITUTION"
    if "financial company" in t:
        return "CREDIT_SOURCE_FINANCIAL_COMPANY"
    if "landlord" in t:
        return "CREDIT_SOURCE_LANDLORD"
    if "agricultur" in t and ("money" in t or "lender" in t):
        return "CREDIT_SOURCE_AGRICULTURIST_MONEYLENDER"
    if "professional money" in t or ("money lender" in t and "agricultur" not in t):
        return "CREDIT_SOURCE_PROFESSIONAL_MONEYLENDER"
    if "trader" in t:
        return "CREDIT_SOURCE_TRADER"
    if "relative" in t or "friend" in t:
        return "CREDIT_SOURCE_RELATIVES_FRIENDS"
    if "doctor" in t or "lawyer" in t or "professional" in t:
        return "CREDIT_SOURCE_PROFESSIONALS"
    if agency_class == "Institutional":
        return "CREDIT_SOURCE_OTHER_INSTITUTIONAL_AGENCIES"
    return "CREDIT_SOURCE_OTHER_NON_INSTITUTIONAL_AGENCIES"


def build_agency_maps(helper):
    cls_map = {}
    target_map = {}
    for r in load_codebook(AGENCY_CODEBOOK):
        c = helper.agency_code(r.get("code"))
        if not c:
            continue
        cls = clean(r.get("agency_class"))
        if cls not in {"Institutional", "Non-institutional"}:
            txt = row_text(r)
            cls = "Non-institutional" if "non institutional" in txt else "Institutional"
        cls_map[c] = cls
        target_map[c] = agency_target(row_text(r), cls)
    return cls_map, target_map


def discover_debt_file() -> Path:
    candidates = []
    for p in PROJECT_ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() != ".xlsx":
            continue
        n = p.name.lower().replace("-", " ").replace("_", " ")
        if "visit 1" in n and "block 14" in n:
            candidates.append(p)
    if not candidates:
        raise FileNotFoundError("Could not locate Visit-1 Block 14 XLSX under project root")
    candidates.sort(key=lambda p: (len(str(p)), str(p)))
    return candidates[0]


def build_group3(stock: dict, cube_lookup: dict, final_rows: List[dict]):
    print("\n[6] Building detailed credit-source / interest / purpose rows")
    helper = load_step02_helper()
    debt_file = discover_debt_file()
    cls_map, target_map = build_agency_maps(helper)
    add_check("AGENCY_CODEBOOK_CLASSES", "Agency codes classified", ">0", len(cls_map), len(cls_map) > 0)

    # Weighted amount accumulators by publication segment.
    agg = defaultdict(lambda: defaultdict(float))
    interest_hh = defaultdict(set)  # HHID -> set of institutional interest type codes
    detail = positive = total99 = unknown_hhid = 0

    cols = ["HHID", "b14_q1", "b14_q6", "b14_q9", "b14_q11", "b14_q17"]
    for r in helper.xlsx_dict_rows(debt_file, cols):
        serial = helper.normalized_code(r.get("b14_q1"))
        if serial == "99":
            total99 += 1
            continue
        detail += 1
        h = clean(r.get("HHID"))
        s = stock.get(h)
        if s is None:
            unknown_hhid += 1
            continue
        amount = helper.numeric(r.get("b14_q17"), default=0.0)
        if amount <= 0:
            continue
        positive += 1
        ac = helper.agency_code(r.get("b14_q6"))
        cls = cls_map.get(ac)
        if cls not in {"Institutional", "Non-institutional"}:
            # Step 02 already proved there are no positive unknown-class agency rows;
            # retain a defensive fallback here.
            cls = "Non-institutional"
        target = target_map.get(ac) or agency_target("", cls)
        ic = helper.normalized_code(r.get("b14_q9"))
        pc = helper.normalized_code(r.get("b14_q11"))
        if pc and pc.isdigit():
            pc2 = f"{int(pc):02d}"
            if pc2 not in PURPOSE_LABELS:
                pc2 = "09"
        else:
            pc2 = "09"
        if cls == "Institutional" and ic in INTEREST_LABELS:
            interest_hh[h].add(ic)

        w = s["_w"]
        for key in segment_keys_from_household(s, include_district=True):
            a = agg[key]
            bucket = "inst_total" if cls == "Institutional" else "non_total"
            a[bucket] += w * amount
            a[target] += w * amount
            a[("purpose_inst_" if cls == "Institutional" else "purpose_non_") + pc2] += w * amount

    # Household incidence by interest nature, weighted by Visit-1 stock weight.
    for h, classes in interest_hh.items():
        s = stock[h]
        w = s["_w"]
        for key in segment_keys_from_household(s, include_district=True):
            for ic in classes:
                agg[key][f"interest_hh_{ic}"] += w

    print(f"  Debt detail rows           : {detail:,}")
    print(f"  Positive debt rows         : {positive:,}")
    print(f"  Explicit total rows skipped: {total99:,}")
    print(f"  Unknown HHID rows          : {unknown_hhid:,}")
    add_check("DEBT_UNKNOWN_HHID", "Positive/detail Block14 rows outside stock HH universe", 0, unknown_hhid, unknown_hhid == 0, severity="WARNING")

    for key, cr in cube_lookup.items():
        a = agg[key]
        occ = key[4]
        inst = a["inst_total"]
        non = a["non_total"]
        # Source distribution: reference denominators are separate within
        # institutional and non-institutional credit, hence each ALL row = 100.
        for cid, (cls, label) in AGENCY_INFO.items():
            den = inst if cls == "Institutional" else non
            value = 100.0 * a[cid] / den if den else None
            kind = "Institutional" if cls == "Institutional" else "Non-Institutional"
            final_rows.append(make_row(key, "3", occ, occ, "1", cid,
                f"Distribution of Outstanding {kind} Credit - {label} - {occ}", value, "Percent", SOURCE_V1))
        final_rows.append(make_row(key, "3", occ, occ, "1", "CREDIT_SOURCE_ALL_INSTITUTIONAL_SOURCES",
            f"Distribution of Outstanding Institutional Credit - All institutional sources - {occ}", 100.0 if inst else None, "Percent", SOURCE_V1))
        final_rows.append(make_row(key, "3", occ, occ, "1", "CREDIT_SOURCE_ALL_NON_INSTITUTIONAL_SOURCES",
            f"Distribution of Outstanding Non-Institutional Credit - All non-institutional sources - {occ}", 100.0 if non else None, "Percent", SOURCE_V1))

        total_w = num(cr.get("weighted_households_stock"))
        inst_ioi = cube_value(cr, "institutional_ioi_pct")
        final_rows.append(make_row(key, "3", occ, occ, "1", "INST_IOI_0",
            f"IOI for Institutional Credit - All institutional credit - {occ}", inst_ioi, "Percent", SOURCE_V1))
        for ic, label in INTEREST_LABELS.items():
            val = 100.0 * a[f"interest_hh_{ic}"] / total_w if total_w else None
            final_rows.append(make_row(key, "3", occ, occ, "1", f"INST_IOI_{ic}",
                f"IOI for Institutional Credit - {label} - {occ}", val, "Percent", SOURCE_V1))

        final_rows.append(make_row(key, "3", occ, occ, "1", "PURPOSE_INST_00",
            f"Distribution of Outstanding Institutional Credit - Purpose: All purposes - {occ}", 100.0 if inst else None, "Percent", SOURCE_V1))
        final_rows.append(make_row(key, "3", occ, occ, "1", "PURPOSE_NON_00",
            f"Distribution of Outstanding Non-Institutional Credit - Purpose: All purposes - {occ}", 100.0 if non else None, "Percent", SOURCE_V1))
        for pc, label in PURPOSE_LABELS.items():
            vi = 100.0 * a[f"purpose_inst_{pc}"] / inst if inst else None
            vn = 100.0 * a[f"purpose_non_{pc}"] / non if non else None
            final_rows.append(make_row(key, "3", occ, occ, "1", f"PURPOSE_INST_{pc}",
                f"Distribution of Outstanding Institutional Credit - Purpose: {label} - {occ}", vi, "Percent", SOURCE_V1))
            final_rows.append(make_row(key, "3", occ, occ, "1", f"PURPOSE_NON_{pc}",
                f"Distribution of Outstanding Non-Institutional Credit - Purpose: {label} - {occ}", vn, "Percent", SOURCE_V1))


# -----------------------------------------------------------------------------
# Sorting / output / QA
# -----------------------------------------------------------------------------
OCC_ORDER = {"All HH": 0, "Cultivator HH": 1, "Non-Cultivator HH": 2, "Others": 3, "Self-employed": 4}


def segment_sort_key(key):
    level, st, di, sec, occ = key
    return (
        {"ALL_INDIA": 0, "STATE": 1, "DISTRICT": 2}.get(level, 9),
        int(st) if st.isdigit() else 999,
        int(di) if di.isdigit() else 999999,
        int(sec) if sec.isdigit() else 9,
        OCC_ORDER.get(occ, 9),
    )


def row_sort_key(r):
    sg = clean(r["SUB_GROUP_ID"])
    if sg.startswith("D") and sg[1:].isdigit():
        sgord = 100 + int(sg[1:])
    else:
        sgord = OCC_ORDER.get(sg, 90)
    return (
        int(r["Survey_GROUP_ID"]),
        int(r["State_ID"]) if clean(r["State_ID"]).isdigit() else 999,
        int(r["District_ID"]) if clean(r["District_ID"]).isdigit() else 999999,
        int(r["Sector_code"]) if clean(r["Sector_code"]).isdigit() else 9,
        sgord,
        clean(r["Col_ID"]),
        clean(r["COL_DESC"]),
    )


def write_csv(rows: List[dict]):
    with FINAL_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)


def write_xlsx(rows: List[dict]):
    try:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Font, PatternFill, Alignment
    except Exception as e:
        warnings.append(f"XLSX output skipped because openpyxl is unavailable: {e}")
        return False
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("AIDIS_2013_Final")
    header = []
    for c in COLUMNS:
        cell = WriteOnlyCell(ws, value=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center")
        header.append(cell)
    ws.append(header)
    for r in rows:
        ws.append([r.get(c, "") for c in COLUMNS])
    ws.freeze_panes = "A2"
    wb.save(FINAL_XLSX)
    return True


def validate_final(rows: List[dict], cube_lookup: dict):
    add_check("OUTPUT_NONEMPTY", "Final normalized output has rows", ">0", len(rows), len(rows) > 0)
    dups = 0
    seen = set()
    for r in rows:
        k = tuple(r[c] for c in ["Survey_GROUP_ID", "SUB_GROUP_ID", "State_ID", "District_ID", "Sector_code", "Col_ID", "COL_DESC"])
        if k in seen:
            dups += 1
        seen.add(k)
    add_check("OUTPUT_DUPLICATES", "Duplicate publication keys", 0, dups, dups == 0)
    bad = 0
    for r in rows:
        s = clean(r.get("DATA"))
        if not s:
            continue
        try:
            x = float(s)
            if not math.isfinite(x):
                bad += 1
        except Exception:
            bad += 1
    add_check("OUTPUT_NUMERIC_DATA", "Non-numeric/non-finite DATA values", 0, bad, bad == 0)

    group_counts = defaultdict(int)
    for r in rows:
        group_counts[r["Survey_GROUP_ID"]] += 1
    for gid in "123456":
        add_check(f"GROUP_{gid}_ROWS", f"Group {gid} produced rows", ">0", group_counts[gid], group_counts[gid] > 0)

    # Anchor-preservation check against the validated Step-04 cube.
    for sec_code, sector, expected_key in [("1", "Rural", "ava"), ("2", "Urban", "ava")]:
        key = ("ALL_INDIA", "0", "0", sec_code, "All HH")
        cr = cube_lookup.get(key)
        if cr:
            expected = cube_value(cr, expected_key)
            matches = [r for r in rows if r["Survey_GROUP_ID"] == "1" and r["State_ID"] == "0" and r["Sector_code"] == sec_code and r["SUB_GROUP_ID"] == "All HH" and r["Col_ID"] == "AVA"]
            actual = num(matches[0]["DATA"], default=float("nan")) if matches else float("nan")
            ok = math.isfinite(actual) and expected is not None and abs(actual - expected) <= max(0.001, abs(expected) * 1e-9)
            add_check(f"ANCHOR_AVA_{sector.upper()}", f"Normalized {sector} AVA preserves Step-04 value", fmt(expected), fmt(actual), ok)

    print("\n[8] Final template QA")
    print(f"  Final rows                 : {len(rows):,}")
    for gid in "123456":
        print(f"  Group {gid} rows               : {group_counts[gid]:,}")
    print(f"  Duplicate publication keys: {dups:,}")
    print(f"  Invalid DATA values        : {bad:,}")
    return group_counts


def write_checks():
    with QA_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        cols = ["check_id", "description", "expected", "actual", "status"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(checks)


def main():
    print("=" * 78)
    print("AIDIS 2013 - STEP 06 REFERENCE-TEMPLATE EXPORT")
    print("NSS 70th Round | Schedule 18.2")
    print("=" * 78)
    print(f"Project root              : {PROJECT_ROOT}")
    print(f"Script revision           : {SCRIPT_REVISION}")

    print("\n[1] Validating production inputs")
    for p, label in [(STEP04_LOCK, "STEP04_LOCK"), (CUBE_FILE, "CUBE"), (STOCK_FILE, "STOCK"), (FLOW_FILE, "FLOW"), (AGENCY_CODEBOOK, "AGENCY_CODEBOOK")]:
        require_file(p, label)
    if errors:
        write_checks()
        print("\nSTEP 06 STATUS: FAIL")
        return 1
    with STEP04_LOCK.open("r", encoding="utf-8") as fh:
        lock = json.load(fh)
    status = clean(lock.get("status"))
    add_check("STEP04_STATUS", "Step-04 production lock", "PASS", status, status == "PASS")
    if errors:
        write_checks()
        print("\nSTEP 06 STATUS: FAIL")
        return 1

    print("\n[2] Loading validated Step-04 indicator cube")
    cube_rows = list(read_csv(CUBE_FILE))
    print(f"  Cube rows                 : {len(cube_rows):,}")
    final_rows: List[dict] = []
    cube_lookup = {}

    print("\n[3] Expanding validated cube to Groups 1, 2 and occupational Group 5")
    build_cube_rows(cube_rows, final_rows, cube_lookup)

    print("\n[4] Loading validated household stock/flow layers")
    stock, flow, members = load_households()
    print(f"  Stock households          : {len(stock):,}")
    print(f"  Flow households           : {len(flow):,}")
    add_check("STOCK_HH", "Visit-1 stock households", 110800, len(stock), len(stock) == 110800)
    add_check("FLOW_HH", "Common-panel flow households", 108421, len(flow), len(flow) == 108421)

    build_decile_gini_rows(stock, flow, members, final_rows)
    build_group3(stock, cube_lookup, final_rows)

    print("\n[7] Sorting and writing reference-template output")
    final_rows.sort(key=row_sort_key)
    write_csv(final_rows)
    xlsx_written = write_xlsx(final_rows)
    group_counts = validate_final(final_rows, cube_lookup)
    write_checks()

    final_status = "FAIL" if errors else ("PASS_WITH_WARNINGS" if warnings else "PASS")
    lock_out = {
        "step": "06",
        "name": "AIDIS 2013 reference-template publication export",
        "script_revision": SCRIPT_REVISION,
        "status": final_status,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_schema_reference": "AIDIS_2003_All_India_States_Districts_Final.csv",
        "output_columns": COLUMNS,
        "row_count": len(final_rows),
        "group_row_counts": dict(group_counts),
        "csv": str(FINAL_CSV),
        "xlsx": str(FINAL_XLSX) if xlsx_written else None,
        "qa": str(QA_FILE),
    }
    STEP06_LOCK.write_text(json.dumps(lock_out, indent=2), encoding="utf-8")

    summary = [
        "AIDIS 2013 - STEP 06 REFERENCE-TEMPLATE EXPORT SUMMARY",
        "=" * 70,
        f"Status                    : {final_status}",
        f"Final rows                : {len(final_rows):,}",
        f"Columns                   : {len(COLUMNS)}",
        f"Failed checks             : {len(errors)}",
        f"Warnings                  : {len(warnings)}",
        f"CSV                       : {FINAL_CSV}",
        f"XLSX                      : {FINAL_XLSX if xlsx_written else 'not written'}",
    ]
    for gid in "123456":
        summary.append(f"Group {gid} rows              : {group_counts[gid]:,}")
    if warnings:
        summary += ["", "WARNINGS:"] + [f"- {x}" for x in warnings]
    if errors:
        summary += ["", "ERRORS:"] + [f"- {x}" for x in errors]
    SUMMARY_FILE.write_text("\n".join(summary) + "\n", encoding="utf-8")

    # Small submission ZIP focused on the requested final-format outputs.
    with zipfile.ZipFile(FINAL_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(FINAL_CSV, arcname=FINAL_CSV.name)
        if xlsx_written and FINAL_XLSX.exists():
            zf.write(FINAL_XLSX, arcname=FINAL_XLSX.name)
        zf.write(QA_FILE, arcname=f"validation/{QA_FILE.name}")
        zf.write(STEP06_LOCK, arcname=f"validation/{STEP06_LOCK.name}")
        zf.write(SUMMARY_FILE, arcname=f"validation/{SUMMARY_FILE.name}")

    print("\n" + "=" * 78)
    print("AIDIS 2013 - STEP 06 REFERENCE-TEMPLATE EXPORT SUMMARY")
    print("=" * 78)
    print(f"Columns                    : {len(COLUMNS)} (matches supplied template)")
    print(f"Final rows                 : {len(final_rows):,}")
    for gid in "123456":
        print(f"Group {gid} rows               : {group_counts[gid]:,}")
    print(f"Failed checks              : {len(errors)}")
    print(f"Warnings                   : {len(warnings)}")
    print(f"CSV                        : {FINAL_CSV}")
    print(f"Excel                      : {FINAL_XLSX if xlsx_written else 'not written'}")
    print(f"ZIP                        : {FINAL_ZIP}")
    if warnings:
        print("\nWARNINGS:")
        for x in warnings:
            print(f"  - {x}")
    if errors:
        print("\nERRORS:")
        for x in errors:
            print(f"  - {x}")
    print(f"\nSTEP 06 STATUS: {final_status}")
    print("=" * 78)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())