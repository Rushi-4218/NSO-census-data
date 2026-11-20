from pathlib import Path
import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime


# =============================================================================
# AIDIS 2003 - STEP 05 KPI BUILD + FINAL EXPORT
# NSS 59th Round, Schedule 18.2
#
# Builds:
#   1) full-year FCE/EPL household flow facts from combined Block 17.2
#   2) stock KPIs from Steps 02-04
#   3) credit agency / interest / purpose KPIs
#   4) asset-holding deciles
#   5) FCE/EPL by occupation and asset decile
#   6) weighted Gini of household assets
#   7) final long-format client export
#
# Important production policies:
#   - 2019/client files are STRUCTURAL references only, never production inputs.
#   - Stock KPIs use Visit-1 household Weight once per household.
#   - Full-year flow KPIs use the paired panel and one household Weight after
#     Visit-1/Visit-2 expenditure rows are consolidated to PANEL_HHID.
#   - Part2-only Block15.2 orphan loans remain excluded from core debt because
#     Step04 V2 marks Included_In_Core_Debt_Indicator=0.
#   - 2003 credit categories are preserved. Commercial banks cannot be split
#     from RRBs; co-operative society cannot be split from co-operative bank.
#   - Adult bank-account ownership by sex is NOT fabricated because the locked
#     2003 methodology says the required individual-level ownership field is not
#     directly available in the provided package.
#   - Original 2003 State/District codes are preserved. District names fall back
#     to code labels unless a 2003 survey-era lookup is supplied.
# =============================================================================


# =============================================================================
# PATHS / CONSTANTS
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
CONFIG_DIR = ROOT / "config"
WORK_DIR = ROOT / "work"
FINAL_DIR = ROOT / "output" / "final"
REPORT_DIR = ROOT / "output" / "reports"

PRODUCTION_MANIFEST = CACHE_DIR / "step01_production_manifest.csv"
METHODOLOGY_FILE = CONFIG_DIR / "aidis_2003_methodology_lock.json"

STOCK_BASE_FILE = WORK_DIR / "step02_household_base_stock.csv"
PANEL_BASE_FILE = WORK_DIR / "step02_household_base_panel.csv"
ASSET_FACT_FILE = WORK_DIR / "step03_household_asset_facts.csv"
DEBT_FACT_FILE = WORK_DIR / "step04_household_debt_facts.csv"
LOAN_FACT_FILE = WORK_DIR / "step04_cash_loan_facts.csv"

FLOW_FACT_FILE = WORK_DIR / "step05_household_flow_facts.csv"
FLOW_CONTROLS_FILE = CACHE_DIR / "step05_flow_controls.csv"
EXPORT_CHECKS_FILE = CACHE_DIR / "step05_export_checks.csv"
DISTRICT_TEMPLATE_FILE = CACHE_DIR / "step05_district_lookup_template.csv"
DOMAIN_INVENTORY_FILE = CACHE_DIR / "step05_domain_inventory.csv"
KPI_CATALOG_FILE = CACHE_DIR / "step05_kpi_catalog.csv"

FINAL_FILE = FINAL_DIR / "AIDIS_2003_All_India_States_Districts_Final.csv"
COVERAGE_FILE = REPORT_DIR / "step05_coverage_report.csv"
SUMMARY_FILE = REPORT_DIR / "step05_kpi_export_summary.txt"

EXPECTED_STOCK_HH = 143_285
EXPECTED_PANEL_HH = 139_039
EXPECTED_BLOCK17_2_ROWS = 106_364
EXPECTED_STATE_COUNT = 35

SURVEY_ID = "AIDIS_59_2003"
SURVEY_NAME = "All India Debt and Investment Survey (AIDIS), NSS 59th Round"
SURVEY_YEAR = "2003"
FREQ_DESC = "Annual"
DEFAULT_SOURCE_URL = "https://microdata.gov.in/NADA/index.php/catalog/103"

FINAL_FIELDS = [
    "Survey_ID", "Survey_NAME", "Survey_GROUP_ID", "GROUP_NAME",
    "SUB_GROUP_ID", "SUB_GROUP_NAME", "Year", "FREQ_DESC",
    "State_ID", "State_Name", "District_ID", "District_Name",
    "Sector_code", "Sector", "Published_date", "Extracted_Date",
    "Visit_ID", "Col_ID", "COL_DESC", "DATA", "Unit", "Source",
]

# Survey-era names. Preserve the period terminology instead of modernising it.
STATE_NAMES_2003 = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttaranchal",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Orissa",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman & Diu",
    "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra",
    "28": "Andhra Pradesh",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Pondicherry",
    "35": "Andaman & Nicobar Islands",
}

SECTOR_NAMES = {"0": "Total", "1": "Rural", "2": "Urban"}

HOUSEHOLD_GROUP_EXPORT = {
    "Rural Cultivator": "Cultivator HH",
    "Rural Non-cultivator": "Non-Cultivator HH",
    "Urban Self-employed": "Self-employed",
    "Urban Others": "Others",
}

# Report 504 / Schedule 18.2 Block 17.1 item codes representing purchase of land
# or land rights. These are EPL, not FCE.
EPL_ITEM_CODES = {"101", "201", "202", "301"}
FCE_PURPOSE_CODES = {"1", "2", "3", "4"}
NORMAL_REPAIR_PURPOSE_CODE = "5"

# Official Report 504 broad rural/urban controls (rounded publication values).
FLOW_OFFICIAL_CONTROLS = {
    "Rural": {"FCE": 2719.0, "EPL": 391.0},
    "Urban": {"FCE": 5925.0, "EPL": 348.0},
}
FLOW_CONTROL_REL_TOL = 0.01  # 1%; publication values are rounded and edited.

# Final stock QA controls already reproduced in Steps 03 and 04. Recheck them
# after the Step05 joins/aggregation so export construction cannot silently drift.
STOCK_FINAL_CONTROLS = {
    ("All India", "AVA"): (306967.0, 0.001),
    ("Rural", "AVA"): (265606.0, 0.001),
    ("Urban", "AVA"): (417158.0, 0.001),
    ("Rural", "AOD"): (7539.0, 0.005),
    ("Urban", "AOD"): (11771.0, 0.005),
    ("Rural", "IOI"): (26.5, 0.15),  # absolute percentage-point tolerance
    ("Urban", "IOI"): (17.8, 0.15),
}

# Client-requested component set. "Others" is a non-overlapping residual of the
# Step03 component facts not separately listed by the client request.
ASSET_COMPONENTS = [
    ("AVA_COMPONENT_PHYSICAL_ASSETS", "Physical assets", ["Physical_Assets_Rs"]),
    ("AVA_COMPONENT_FINANCIAL_ASSETS", "Financial assets", ["Financial_Assets_Rs"]),
    ("AVA_COMPONENT_LAND", "Land", ["Land_Asset_Rs"]),
    ("AVA_COMPONENT_BUILDINGS", "Buildings", ["Buildings_Asset_Rs"]),
    ("AVA_COMPONENT_DEPOSITS", "Deposits and other financial assets", ["Deposits_Other_Financial_Assets_Rs"]),
    ("AVA_COMPONENT_LIVESTOCK_POULTRY", "Livestock & poultry", ["Livestock_Poultry_Asset_Rs"]),
    ("AVA_COMPONENT_AGRICULTURAL_MACHINERY_EQUIPMENT", "Agricultural machinery & equipment", ["Agricultural_Machinery_Asset_Rs"]),
    ("AVA_COMPONENT_TRANSPORT_EQUIPMENT", "Transport equipment", ["Transport_Equipment_Asset_Rs"]),
    ("AVA_COMPONENT_NON_FARM_BUSINESS_EQUIPMENT", "Non-farm business equipment", ["Nonfarm_Business_Equipment_Asset_Rs"]),
    (
        "AVA_COMPONENT_OTHERS",
        "Others (durable assets + shares/debentures + loans receivable)",
        ["Durable_Assets_Rs", "Shares_Debentures_Asset_Rs", "Loans_Receivable_Asset_Rs"],
    ),
]

AGENCY_LABELS = {
    "01": "Government",
    "02": "Co-operative society / co-operative bank",
    "03": "Commercial bank including regional rural bank",
    "04": "Insurance",
    "05": "Provident fund",
    "06": "Financial corporation / institution",
    "07": "Financial company",
    "08": "Other institutional agency",
    "09": "Landlord",
    "10": "Agriculturist money lender",
    "11": "Professional money lender",
    "12": "Trader",
    "13": "Relatives and friends",
    "14": "Doctors, lawyers and other professionals",
    "99": "Other agency",
}
INSTITUTIONAL_CODES = ["01", "02", "03", "04", "05", "06", "07", "08"]
NONINSTITUTIONAL_CODES = ["09", "10", "11", "12", "13", "14", "99"]

AGENCY_COL_IDS = {
    "01": "CREDIT_SOURCE_GOVERNMENT",
    "02": "CREDIT_SOURCE_COOP_SOCIETY_BANK",
    "03": "CREDIT_SOURCE_COMMERCIAL_BANK_INCL_RRB",
    "04": "CREDIT_SOURCE_INSURANCE",
    "05": "CREDIT_SOURCE_PROVIDENT_FUND",
    "06": "CREDIT_SOURCE_FINANCIAL_CORP_INSTITUTION",
    "07": "CREDIT_SOURCE_FINANCIAL_COMPANY",
    "08": "CREDIT_SOURCE_OTHER_INSTITUTIONAL_AGENCIES",
    "09": "CREDIT_SOURCE_LANDLORD",
    "10": "CREDIT_SOURCE_AGRICULTURIST_MONEYLENDER",
    "11": "CREDIT_SOURCE_PROFESSIONAL_MONEYLENDER",
    "12": "CREDIT_SOURCE_TRADER",
    "13": "CREDIT_SOURCE_RELATIVES_FRIENDS",
    "14": "CREDIT_SOURCE_PROFESSIONALS",
    "99": "CREDIT_SOURCE_OTHER_NON_INSTITUTIONAL_AGENCIES",
}

INTEREST_LABELS = {
    "0": "All institutional credit",
    "1": "Interest-free",
    "2": "Simple interest",
    "3": "Compound interest",
    "4": "Concessional rate",
}

PURPOSE_LABELS = {
    "1": "Capital expenditure in farm business",
    "2": "Current/revenue expenditure in farm business",
    "3": "Capital expenditure in non-farm business",
    "4": "Current/revenue expenditure in non-farm business",
    "5": "Household expenditure",
    "6": "Litigation",
    "7": "Repayment of debt",
    "8": "Financial investment expenditure",
    "9": "Other purpose",
}

# Files searched in the Step01D production manifest.
BLOCK17_2_NAMES = ["Visit1and2_CB_17pt2", "Visit1and2_CB_17_2"]


# =============================================================================
# BASIC HELPERS
# =============================================================================


def clean(v):
    return "" if v is None else str(v).strip()


def norm_name(v):
    return re.sub(r"[^a-z0-9]+", "", clean(v).casefold())


def as_float(v, blank_zero=False):
    t = clean(v).replace(",", "")
    if not t:
        return 0.0 if blank_zero else None
    return float(t)


def fmt(v):
    if v is None:
        return ""
    if abs(float(v)) < 5e-12:
        v = 0.0
    return f"{float(v):.10f}".rstrip("0").rstrip(".")


def code(v, width=None):
    t = clean(v)
    if not t:
        return ""
    try:
        n = float(t)
        if n.is_integer():
            t = str(int(n))
    except ValueError:
        pass
    if width and t.isdigit():
        t = t.zfill(width)
    return t


def safe_div(num, den):
    return num / den if den else 0.0


def open_csv(path):
    last = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            h = path.open("r", encoding=enc, newline="")
            r = csv.DictReader(h)
            if not r.fieldnames:
                h.close()
                raise ValueError("empty CSV header")
            return h, r, enc
        except UnicodeDecodeError as exc:
            last = exc
        except Exception as exc:
            last = exc
            break
    raise RuntimeError(f"Unable to read {path.name}: {last}")


def require_fields(fieldnames, required, label):
    present = {norm_name(x): x for x in (fieldnames or [])}
    missing = [x for x in required if norm_name(x) not in present]
    if missing:
        raise ValueError(f"{label}: missing fields {missing}")


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def add_check(checks, name, expected, observed, passed, note=""):
    checks.append({
        "check": name,
        "expected": str(expected),
        "observed": str(observed),
        "status": "PASS" if passed else "FAIL",
        "note": note,
    })


def derive_panel_hhid(hhid, visit_no):
    hhid = clean(hhid)
    visit_no = code(visit_no)
    if len(hhid) != 10:
        return None
    if hhid[7] != visit_no:
        return None
    return hhid[:7] + hhid[8:]


def state_name(state_code):
    return STATE_NAMES_2003.get(code(state_code, 2), f"State code {code(state_code, 2)}")


def composite_district_id(state_code, district_code):
    s = code(state_code, 2)
    d = code(district_code, 2)
    if not s or not d:
        return ""
    return str(int(s) * 100 + int(d))


# =============================================================================
# PREREQUISITES / MANIFEST
# =============================================================================


def load_methodology():
    if not METHODOLOGY_FILE.exists():
        raise FileNotFoundError(f"Missing methodology lock: {METHODOLOGY_FILE}")
    data = json.loads(METHODOLOGY_FILE.read_text(encoding="utf-8"))
    if data.get("methodology_lock_status") != "LOCKED":
        raise ValueError("Step 01B-C methodology is not LOCKED")
    if data.get("estimation", {}).get("locked_weight_field") != "Weight":
        raise ValueError("Methodology does not lock Weight as estimator weight")
    if data.get("survey", {}).get("stock_reference_date") != "2002-06-30":
        raise ValueError("Unexpected stock reference date in methodology")
    return data


def load_manifest():
    if not PRODUCTION_MANIFEST.exists():
        raise FileNotFoundError(f"Missing manifest: {PRODUCTION_MANIFEST}")
    with PRODUCTION_MANIFEST.open("r", encoding="utf-8-sig", newline="") as h:
        rows = list(csv.DictReader(h))
    if len(rows) != 42 or any(clean(r.get("status")).upper() != "PASS" for r in rows):
        raise ValueError("Step01D production manifest is not 42/42 PASS")
    return rows


def manifest_source(manifest, logical_names):
    targets = {norm_name(x) for x in logical_names}
    rows = [r for r in manifest if norm_name(r.get("logical_dataset")) in targets]
    if len(rows) != 1:
        raise RuntimeError(f"Expected exactly one manifest match for {logical_names}; found {len(rows)}")
    p = Path(rows[0]["source_path"])
    if not p.exists():
        raise FileNotFoundError(f"Manifest source missing: {p}")
    return p


# =============================================================================
# LOAD STEP 02 / 03 / 04 HOUSEHOLD DATA
# =============================================================================


def load_stock_master():
    required_base = [
        "HHID", "Sector", "State_Region", "State", "District",
        "Household_Group", "Group_Classification_Status", "Weight",
    ]
    required_asset = [
        "HHID", "Land_Asset_Rs", "Buildings_Asset_Rs", "Livestock_Poultry_Asset_Rs",
        "Agricultural_Machinery_Asset_Rs", "Nonfarm_Business_Equipment_Asset_Rs",
        "Transport_Equipment_Asset_Rs", "Durable_Assets_Rs", "Shares_Debentures_Asset_Rs",
        "Deposits_Other_Financial_Assets_Rs", "Loans_Receivable_Asset_Rs",
        "Physical_Assets_Rs", "Financial_Assets_Rs", "Total_Assets_Rs",
    ]
    required_debt = [
        "HHID", "Cash_Debt_2002_Rs", "Indebted_Indicator",
        "Institutional_Debt_Rs", "NonInstitutional_Debt_Rs", "Total_Assets_Rs",
    ]

    for p in (STOCK_BASE_FILE, ASSET_FACT_FILE, DEBT_FACT_FILE):
        if not p.exists():
            raise FileNotFoundError(f"Missing prerequisite: {p}")

    master = {}
    order = []

    h, r, _ = open_csv(STOCK_BASE_FILE)
    try:
        require_fields(r.fieldnames, required_base, STOCK_BASE_FILE.name)
        for row in r:
            hhid = clean(row.get("HHID"))
            if not hhid or hhid in master:
                raise ValueError(f"Invalid/duplicate stock HHID: {hhid!r}")
            w = as_float(row.get("Weight"))
            if w is None or w < 0:
                raise ValueError(f"Invalid stock Weight for HHID={hhid}")
            master[hhid] = {
                "HHID": hhid,
                "Sector": code(row.get("Sector")),
                "Sector_Name": clean(row.get("Sector_Name")) or SECTOR_NAMES.get(code(row.get("Sector")), ""),
                "State_Region": clean(row.get("State_Region")),
                "State": code(row.get("State"), 2),
                "District": code(row.get("District"), 2),
                "Household_Group": clean(row.get("Household_Group")),
                "Group_Classification_Status": clean(row.get("Group_Classification_Status")),
                "Weight": w,
            }
            order.append(hhid)
    finally:
        h.close()

    if len(master) != EXPECTED_STOCK_HH:
        raise ValueError(f"Step02 stock rows expected {EXPECTED_STOCK_HH:,}; found {len(master):,}")

    asset_seen = set()
    h, r, _ = open_csv(ASSET_FACT_FILE)
    try:
        require_fields(r.fieldnames, required_asset, ASSET_FACT_FILE.name)
        for row in r:
            hhid = clean(row.get("HHID"))
            if hhid not in master or hhid in asset_seen:
                raise ValueError(f"Step03 invalid/duplicate HHID: {hhid!r}")
            asset_seen.add(hhid)
            for f in required_asset[1:]:
                master[hhid][f] = as_float(row.get(f), blank_zero=True)
    finally:
        h.close()

    debt_seen = set()
    h, r, _ = open_csv(DEBT_FACT_FILE)
    try:
        require_fields(r.fieldnames, required_debt, DEBT_FACT_FILE.name)
        for row in r:
            hhid = clean(row.get("HHID"))
            if hhid not in master or hhid in debt_seen:
                raise ValueError(f"Step04 invalid/duplicate HHID: {hhid!r}")
            debt_seen.add(hhid)
            master[hhid]["Cash_Debt_2002_Rs"] = as_float(row.get("Cash_Debt_2002_Rs"), blank_zero=True)
            master[hhid]["Indebted_Indicator"] = 1 if code(row.get("Indebted_Indicator")) == "1" else 0
            master[hhid]["Institutional_Debt_Rs"] = as_float(row.get("Institutional_Debt_Rs"), blank_zero=True)
            master[hhid]["NonInstitutional_Debt_Rs"] = as_float(row.get("NonInstitutional_Debt_Rs"), blank_zero=True)
    finally:
        h.close()

    if len(asset_seen) != EXPECTED_STOCK_HH or len(debt_seen) != EXPECTED_STOCK_HH:
        raise ValueError(
            f"Household join incomplete: assets={len(asset_seen):,}, debt={len(debt_seen):,}"
        )

    # Step03/Step04 asset value should agree exactly enough for production use.
    return master, order


def load_panel_base():
    required = [
        "PANEL_HHID", "HHID_Visit1", "HHID_Visit2", "Sector", "State_Region",
        "State", "District", "Household_Group", "Group_Classification_Status", "Weight",
    ]
    if not PANEL_BASE_FILE.exists():
        raise FileNotFoundError(f"Missing Step02 panel base: {PANEL_BASE_FILE}")

    panel = {}
    order = []
    h, r, _ = open_csv(PANEL_BASE_FILE)
    try:
        require_fields(r.fieldnames, required, PANEL_BASE_FILE.name)
        for row in r:
            pid = clean(row.get("PANEL_HHID"))
            if not pid or pid in panel:
                raise ValueError(f"Invalid/duplicate PANEL_HHID: {pid!r}")
            w = as_float(row.get("Weight"))
            if w is None or w < 0:
                raise ValueError(f"Invalid panel Weight for PANEL_HHID={pid}")
            panel[pid] = {
                "PANEL_HHID": pid,
                "HHID_Visit1": clean(row.get("HHID_Visit1")),
                "HHID_Visit2": clean(row.get("HHID_Visit2")),
                "Sector": code(row.get("Sector")),
                "Sector_Name": clean(row.get("Sector_Name")) or SECTOR_NAMES.get(code(row.get("Sector")), ""),
                "State_Region": clean(row.get("State_Region")),
                "State": code(row.get("State"), 2),
                "District": code(row.get("District"), 2),
                "Household_Group": clean(row.get("Household_Group")),
                "Group_Classification_Status": clean(row.get("Group_Classification_Status")),
                "Weight": w,
            }
            order.append(pid)
    finally:
        h.close()

    if len(panel) != EXPECTED_PANEL_HH:
        raise ValueError(f"Panel rows expected {EXPECTED_PANEL_HH:,}; found {len(panel):,}")
    return panel, order


# =============================================================================
# STEP 05A - FULL-YEAR FLOW FACTS FROM BLOCK 17.2
# =============================================================================


def build_flow_facts(block17_path, panel, panel_order, stock_master):
    required = [
        "HHID", "Sector", "State", "District", "Visit_no", "B17_2_q1", "B17_2_q3",
        "B17_2_q4", "B17_2_q5", "B17_2_q6", "B17_2_q7", "B17_2_q8", "B17_2_q9",
        "B17_2_q10", "Weight",
    ]

    acc = defaultdict(lambda: {
        "FCE_Rs": 0.0,
        "EPL_Rs": 0.0,
        "Normal_Repairs_Rs": 0.0,
        "Unclassified_Expenditure_Rs": 0.0,
        "Block17_2_Total_Rs": 0.0,
        "Rows": 0,
    })

    stats = Counter()
    bad_examples = []

    h, r, _ = open_csv(block17_path)
    try:
        require_fields(r.fieldnames, required, block17_path.name)
        for row in r:
            stats["rows"] += 1
            visit = code(row.get("Visit_no"))
            pid = derive_panel_hhid(row.get("HHID"), visit)
            if not pid:
                stats["panel_format_errors"] += 1
                if len(bad_examples) < 10:
                    bad_examples.append(f"invalid panel key: HHID={row.get('HHID')} visit={visit}")
                continue
            if pid not in panel:
                stats["unmatched_panel"] += 1
                if len(bad_examples) < 10:
                    bad_examples.append(f"unmatched PANEL_HHID={pid}")
                continue

            meta = panel[pid]
            for f in ("Sector", "State", "District"):
                if code(row.get(f), 2 if f in ("State", "District") else None) != meta[f]:
                    stats["core_mismatch"] += 1
                    break

            rw = as_float(row.get("Weight"))
            if rw is None or not math.isclose(rw, meta["Weight"], rel_tol=1e-9, abs_tol=5e-7):
                stats["weight_mismatch"] += 1

            item = code(row.get("B17_2_q1"))
            purpose = code(row.get("B17_2_q3"))
            total = as_float(row.get("B17_2_q10"), blank_zero=True)
            components = sum(as_float(row.get(f"B17_2_q{i}"), blank_zero=True) for i in range(4, 10))

            if total < 0:
                stats["negative_q10"] += 1
            if not math.isclose(total, components, rel_tol=0, abs_tol=0.5):
                stats["q10_component_mismatch"] += 1

            x = acc[pid]
            x["Rows"] += 1
            x["Block17_2_Total_Rs"] += total

            if purpose == "1" and item in EPL_ITEM_CODES:
                x["EPL_Rs"] += total
                stats["epl_rows"] += 1
            elif purpose in FCE_PURPOSE_CODES:
                x["FCE_Rs"] += total
                stats["fce_rows"] += 1
            elif purpose == NORMAL_REPAIR_PURPOSE_CODE:
                x["Normal_Repairs_Rs"] += total
                stats["repair_rows"] += 1
            else:
                x["Unclassified_Expenditure_Rs"] += total
                stats["unclassified_rows"] += 1
                stats["unclassified_amount"] += total
    finally:
        h.close()

    fields = [
        "PANEL_HHID", "HHID_Visit1", "HHID_Visit2", "Sector", "Sector_Name",
        "State_Region", "State", "District", "Household_Group",
        "Group_Classification_Status", "Weight", "Total_Assets_Rs",
        "FCE_Rs", "EPL_Rs", "Normal_Repairs_Rs", "Unclassified_Expenditure_Rs",
        "Block17_2_Total_Rs", "Block17_2_Row_Count", "Flow_Reference_Start",
        "Flow_Reference_End",
    ]

    flow = {}
    with FLOW_FACT_FILE.open("w", encoding="utf-8", newline="") as out:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        for pid in panel_order:
            meta = panel[pid]
            x = acc.get(pid, {})
            visit1_hhid = meta["HHID_Visit1"]
            if visit1_hhid not in stock_master:
                raise ValueError(f"Panel Visit1 HHID not in stock master: {visit1_hhid}")
            asset = stock_master[visit1_hhid]["Total_Assets_Rs"]
            row = {
                **meta,
                "Total_Assets_Rs": asset,
                "FCE_Rs": float(x.get("FCE_Rs", 0.0)),
                "EPL_Rs": float(x.get("EPL_Rs", 0.0)),
                "Normal_Repairs_Rs": float(x.get("Normal_Repairs_Rs", 0.0)),
                "Unclassified_Expenditure_Rs": float(x.get("Unclassified_Expenditure_Rs", 0.0)),
                "Block17_2_Total_Rs": float(x.get("Block17_2_Total_Rs", 0.0)),
                "Block17_2_Row_Count": int(x.get("Rows", 0)),
            }
            flow[pid] = row
            w.writerow({
                "PANEL_HHID": pid,
                "HHID_Visit1": meta["HHID_Visit1"],
                "HHID_Visit2": meta["HHID_Visit2"],
                "Sector": meta["Sector"],
                "Sector_Name": meta["Sector_Name"],
                "State_Region": meta["State_Region"],
                "State": meta["State"],
                "District": meta["District"],
                "Household_Group": meta["Household_Group"],
                "Group_Classification_Status": meta["Group_Classification_Status"],
                "Weight": fmt(meta["Weight"]),
                "Total_Assets_Rs": fmt(asset),
                "FCE_Rs": fmt(row["FCE_Rs"]),
                "EPL_Rs": fmt(row["EPL_Rs"]),
                "Normal_Repairs_Rs": fmt(row["Normal_Repairs_Rs"]),
                "Unclassified_Expenditure_Rs": fmt(row["Unclassified_Expenditure_Rs"]),
                "Block17_2_Total_Rs": fmt(row["Block17_2_Total_Rs"]),
                "Block17_2_Row_Count": row["Block17_2_Row_Count"],
                "Flow_Reference_Start": "2002-07-01",
                "Flow_Reference_End": "2003-06-30",
            })

    stats["panel_households_with_rows"] = len(acc)
    stats["flow_fact_rows"] = len(flow)
    return flow, stats, bad_examples


def flow_sector_metrics(flow):
    acc = defaultdict(lambda: defaultdict(float))
    for row in flow.values():
        sec = row["Sector_Name"]
        w = row["Weight"]
        x = acc[sec]
        x["weight"] += w
        x["fce"] += w * row["FCE_Rs"]
        x["epl"] += w * row["EPL_Rs"]

    out = {}
    for sec in ("Rural", "Urban"):
        x = acc[sec]
        out[sec] = {
            "FCE": safe_div(x["fce"], x["weight"]),
            "EPL": safe_div(x["epl"], x["weight"]),
        }
    return out


def validate_flow_controls(flow):
    observed = flow_sector_metrics(flow)
    rows = []
    failed = 0
    for sec in ("Rural", "Urban"):
        for metric in ("FCE", "EPL"):
            expected = FLOW_OFFICIAL_CONTROLS[sec][metric]
            actual = observed[sec][metric]
            diff = actual - expected
            pdiff = 100.0 * diff / expected if expected else 0.0
            passed = abs(diff / expected) <= FLOW_CONTROL_REL_TOL if expected else abs(diff) < 1e-9
            failed += int(not passed)
            rows.append({
                "sector": sec,
                "metric": metric,
                "official_value": fmt(expected),
                "microdata_value": fmt(actual),
                "difference": fmt(diff),
                "percent_difference": fmt(pdiff),
                "tolerance": f"+/- {FLOW_CONTROL_REL_TOL*100:.1f}%",
                "status": "PASS" if passed else "FAIL",
            })
    write_csv(
        FLOW_CONTROLS_FILE,
        ["sector", "metric", "official_value", "microdata_value", "difference", "percent_difference", "tolerance", "status"],
        rows,
    )
    return rows, failed


# =============================================================================
# DOMAIN MODEL
# =============================================================================


def subgroup_export_label(hh_group):
    return HOUSEHOLD_GROUP_EXPORT.get(clean(hh_group), "")


def domain_keys_for_row(row, include_district=True):
    """
    Return domain keys a household contributes to.

    key = (geo_level, state, district, sector, subgroup)
    subgroup is the client-facing household category label.
    """
    state = row["State"]
    district = row["District"]
    sector = row["Sector"]
    subgroup = subgroup_export_label(row.get("Household_Group"))

    geo_keys = [("ALL", "00", "00"), ("STATE", state, "00")]
    if include_district:
        geo_keys.append(("DISTRICT", state, district))

    keys = []
    for geo_level, s, d in geo_keys:
        keys.append((geo_level, s, d, "0", "All HH"))
        if sector in ("1", "2"):
            keys.append((geo_level, s, d, sector, "All HH"))
            if subgroup:
                keys.append((geo_level, s, d, sector, subgroup))
    return keys


def aggregate_stock_domains(stock_master, stock_order):
    acc = defaultdict(lambda: defaultdict(float))
    component_fields = sorted({f for _, _, fields in ASSET_COMPONENTS for f in fields})

    for hhid in stock_order:
        row = stock_master[hhid]
        w = row["Weight"]
        for key in domain_keys_for_row(row, include_district=True):
            x = acc[key]
            x["n"] += 1
            x["weight"] += w
            x["weighted_assets"] += w * row["Total_Assets_Rs"]
            x["weighted_debt"] += w * row["Cash_Debt_2002_Rs"]
            if row["Indebted_Indicator"]:
                x["indebted_n"] += 1
                x["indebted_weight"] += w
            for f in component_fields:
                x[f] += w * row[f]
    return acc


def stock_metrics(cell):
    w = cell["weight"]
    iw = cell["indebted_weight"]
    wa = cell["weighted_assets"]
    wd = cell["weighted_debt"]
    return {
        "HH_SURVEYED": int(cell["n"]),
        "AVA": safe_div(wa, w),
        "AOD": safe_div(wd, w),
        "AODL": safe_div(wd, iw),
        "IOI": 100.0 * safe_div(iw, w),
        "DAR": safe_div(wd, wa),
    }


# =============================================================================
# DISTRICT NAMES / EXPORT METADATA
# =============================================================================


def read_optional_district_lookup(path):
    lookup = {}
    if path is None or not path.exists():
        return lookup

    h, r, _ = open_csv(path)
    try:
        fields = {norm_name(x): x for x in (r.fieldnames or [])}
        for row in r:
            name = clean(row.get(fields.get("districtname", "")))
            if not name:
                continue
            if "state" in fields and "district" in fields:
                s = code(row.get(fields["state"]), 2)
                d = code(row.get(fields["district"]), 2)
                if s and d:
                    lookup[(s, d)] = name
            elif "districtid" in fields:
                did = code(row.get(fields["districtid"]))
                if did.isdigit() and len(did) >= 3:
                    n = int(did)
                    lookup[(str(n // 100).zfill(2), str(n % 100).zfill(2))] = name
    finally:
        h.close()
    return lookup


def build_district_template(stock_master, district_lookup):
    combos = sorted({(r["State"], r["District"]) for r in stock_master.values()})
    rows = []
    for s, d in combos:
        rows.append({
            "State": s,
            "State_Name": state_name(s),
            "District": d,
            "District_ID": composite_district_id(s, d),
            "District_Name": district_lookup.get((s, d), ""),
            "Fallback_Name": f"District code {d}",
        })
    write_csv(
        DISTRICT_TEMPLATE_FILE,
        ["State", "State_Name", "District", "District_ID", "District_Name", "Fallback_Name"],
        rows,
    )
    return combos


def export_geo(key, district_lookup):
    geo_level, state, district, sector, subgroup = key
    if geo_level == "ALL":
        return {
            "State_ID": "0",
            "State_Name": "All India",
            "District_ID": "0",
            "District_Name": "All Districts",
        }
    if geo_level == "STATE":
        return {
            "State_ID": str(int(state)),
            "State_Name": state_name(state),
            "District_ID": "0",
            "District_Name": "All Districts",
        }
    return {
        "State_ID": str(int(state)),
        "State_Name": state_name(state),
        "District_ID": composite_district_id(state, district),
        "District_Name": district_lookup.get((state, district), f"District code {district}"),
    }


# =============================================================================
# FINAL ROW FACTORY / CATALOG
# =============================================================================


def final_row(
    args,
    group_id,
    group_name,
    subgroup_id,
    subgroup_name,
    domain_key,
    district_lookup,
    visit_id,
    col_id,
    col_desc,
    data,
    unit,
    source_note,
):
    geo = export_geo(domain_key, district_lookup)
    sector = domain_key[3]
    return {
        "Survey_ID": SURVEY_ID,
        "Survey_NAME": SURVEY_NAME,
        "Survey_GROUP_ID": str(group_id),
        "GROUP_NAME": group_name,
        "SUB_GROUP_ID": subgroup_id,
        "SUB_GROUP_NAME": subgroup_name,
        "Year": SURVEY_YEAR,
        "FREQ_DESC": FREQ_DESC,
        **geo,
        "Sector_code": sector,
        "Sector": SECTOR_NAMES.get(sector, ""),
        "Published_date": args.published_date,
        "Extracted_Date": args.extracted_date,
        "Visit_ID": str(visit_id),
        "Col_ID": col_id,
        "COL_DESC": col_desc,
        "DATA": fmt(data),
        "Unit": unit,
        "Source": DEFAULT_SOURCE_URL,
    }


def catalog_add(catalog, row, availability="AVAILABLE", note=""):
    key = row["Col_ID"]
    if key not in catalog:
        catalog[key] = {
            "Col_ID": key,
            "Survey_GROUP_ID": row["Survey_GROUP_ID"],
            "GROUP_NAME": row["GROUP_NAME"],
            "COL_DESC_example": row["COL_DESC"],
            "Unit": row["Unit"],
            "availability": availability,
            "note": note,
        }


# =============================================================================
# GROUP 1 / 2 STOCK EXPORT
# =============================================================================


def emit_core_and_components(args, stock_acc, district_lookup, catalog):
    rows = []
    core_defs = [
        ("HH_SURVEYED", "No. of Households Surveyed", "Number"),
        ("AVA", "Average Value of Assets (AVA)", "Rs. per HH"),
        ("AOD", "Average Amount of Debt (AOD) per HH", "Rs. per HH"),
        ("AODL", "Average Amount of Debt per Indebted Household (AODL)", "Rs. per indebted HH"),
        ("IOI", "Incidence of Indebtedness (IOI)", "Percent"),
        ("DAR", "Debt Asset Ratio (DAR)", "Ratio"),
    ]

    for key in sorted(stock_acc, key=domain_sort_key):
        subgroup = key[4]
        m = stock_metrics(stock_acc[key])
        for col_id, label, unit in core_defs:
            row = final_row(
                args, 1, "Household Assets and Debt", subgroup, subgroup,
                key, district_lookup, 1, col_id,
                f"{label} - {subgroup}", m[col_id], unit,
                "MoSPI/NSSO AIDIS 2003 microdata; Reports 500 and 501 used for QA",
            )
            rows.append(row)
            catalog_add(catalog, row)

        for col_id, label, source_fields in ASSET_COMPONENTS:
            weighted = sum(stock_acc[key][f] for f in source_fields)
            value = safe_div(weighted, stock_acc[key]["weight"])
            row = final_row(
                args, 2, "Assets by Component", subgroup, subgroup,
                key, district_lookup, 1, col_id,
                f"Average Value of Assets - {label} - {subgroup}", value, "Rs. per HH",
                "MoSPI/NSSO AIDIS 2003 microdata; Report 500 methodology",
            )
            rows.append(row)
            catalog_add(catalog, row)

    return rows


# =============================================================================
# GROUP 3 CREDIT FACTS
# =============================================================================


def load_and_aggregate_credit(stock_master):
    required = [
        "HHID", "Included_In_Core_Debt_Indicator", "Cash_Debt_2002_06_30_Rs",
        "Credit_Agency_Code", "Credit_Agency_Class", "Nature_Interest_Code", "Purpose_Code",
    ]
    if not LOAN_FACT_FILE.exists():
        raise FileNotFoundError(f"Missing Step04 loan facts: {LOAN_FACT_FILE}")

    # Each dimension store is indexed by domain key.
    agency_debt = defaultdict(lambda: defaultdict(float))
    purpose_debt = defaultdict(lambda: defaultdict(float))
    inst_hh_sets = defaultdict(lambda: defaultdict(set))
    stats = Counter()

    h, r, _ = open_csv(LOAN_FACT_FILE)
    try:
        require_fields(r.fieldnames, required, LOAN_FACT_FILE.name)
        for row in r:
            stats["loan_rows"] += 1
            if code(row.get("Included_In_Core_Debt_Indicator")) != "1":
                stats["excluded_orphan_rows"] += 1
                continue
            debt = as_float(row.get("Cash_Debt_2002_06_30_Rs"), blank_zero=True)
            if debt <= 0:
                continue
            hhid = clean(row.get("HHID"))
            if hhid not in stock_master:
                stats["unmatched_hhid"] += 1
                continue
            stats["core_positive_rows"] += 1
            meta = stock_master[hhid]
            agency = code(row.get("Credit_Agency_Code"), 2)
            interest = code(row.get("Nature_Interest_Code"))
            purpose = code(row.get("Purpose_Code"))
            wdebt = meta["Weight"] * debt

            for dkey in domain_keys_for_row(meta, include_district=True):
                agency_debt[dkey][agency] += wdebt
                if agency in INSTITUTIONAL_CODES:
                    purpose_debt[dkey][("INST", purpose)] += wdebt
                    inst_hh_sets[dkey]["0"].add(hhid)
                    inst_hh_sets[dkey][interest].add(hhid)
                elif agency in NONINSTITUTIONAL_CODES:
                    purpose_debt[dkey][("NON", purpose)] += wdebt
    finally:
        h.close()

    return agency_debt, purpose_debt, inst_hh_sets, stats


def emit_credit(args, stock_acc, stock_master, district_lookup, catalog):
    agency_debt, purpose_debt, inst_hh_sets, stats = load_and_aggregate_credit(stock_master)
    rows = []

    for dkey in sorted(stock_acc, key=domain_sort_key):
        subgroup = dkey[4]
        household_weight = stock_acc[dkey]["weight"]
        a = agency_debt[dkey]
        inst_total = sum(a[c] for c in INSTITUTIONAL_CODES)
        non_total = sum(a[c] for c in NONINSTITUTIONAL_CODES)

        # Institutional source distribution.
        definitions = [
            ("CREDIT_SOURCE_ALL_INSTITUTIONAL_SOURCES", "All institutional sources", 100.0 if inst_total else 0.0),
        ]
        for c in INSTITUTIONAL_CODES:
            definitions.append((AGENCY_COL_IDS[c], AGENCY_LABELS[c], 100.0 * safe_div(a[c], inst_total)))

        # Non-institutional source distribution.
        definitions.append(("CREDIT_SOURCE_ALL_NON_INSTITUTIONAL_SOURCES", "All non-institutional sources", 100.0 if non_total else 0.0))
        for c in NONINSTITUTIONAL_CODES:
            definitions.append((AGENCY_COL_IDS[c], AGENCY_LABELS[c], 100.0 * safe_div(a[c], non_total)))

        for col_id, label, value in definitions:
            kind = "Institutional" if "NON_INSTITUTIONAL" not in col_id and col_id not in [AGENCY_COL_IDS[c] for c in NONINSTITUTIONAL_CODES] else "Non-Institutional"
            row = final_row(
                args, 3, "Credit Distribution and Characteristics", subgroup, subgroup,
                dkey, district_lookup, 1, col_id,
                f"Distribution of Outstanding {kind} Credit - {label} - {subgroup}",
                value, "Percent",
                "MoSPI/NSSO AIDIS 2003 Block 15.2; Report 501 classification",
            )
            rows.append(row)
            catalog_add(catalog, row)

        # Institutional IOI by nature of interest. Use unique indebted households
        # and the domain's full household-weight denominator.
        for ic in ("0", "1", "2", "3", "4"):
            hhs = inst_hh_sets[dkey].get(ic, set())
            hh_weight = sum(stock_master[hhid]["Weight"] for hhid in hhs)
            value = 100.0 * safe_div(hh_weight, household_weight)
            row = final_row(
                args, 3, "Credit Distribution and Characteristics", subgroup, subgroup,
                dkey, district_lookup, 1, f"INST_IOI_{ic}",
                f"IOI for Institutional Credit - {INTEREST_LABELS[ic]} - {subgroup}",
                value, "Percent",
                "MoSPI/NSSO AIDIS 2003 Block 15.2; nature-of-interest codes",
            )
            rows.append(row)
            catalog_add(catalog, row)

        # Purpose distribution within institutional and non-institutional debt.
        for klass, prefix, total in (("INST", "PURPOSE_INST", inst_total), ("NON", "PURPOSE_NON", non_total)):
            class_label = "Institutional" if klass == "INST" else "Non-Institutional"
            all_row = final_row(
                args, 3, "Credit Distribution and Characteristics", subgroup, subgroup,
                dkey, district_lookup, 1, f"{prefix}_00",
                f"Distribution of Outstanding {class_label} Credit - Purpose: All purposes - {subgroup}",
                100.0 if total else 0.0, "Percent",
                "MoSPI/NSSO AIDIS 2003 Block 15.2; loan-purpose codes",
            )
            rows.append(all_row)
            catalog_add(catalog, all_row)
            for pc in sorted(PURPOSE_LABELS):
                value = 100.0 * safe_div(purpose_debt[dkey][(klass, pc)], total)
                row = final_row(
                    args, 3, "Credit Distribution and Characteristics", subgroup, subgroup,
                    dkey, district_lookup, 1, f"{prefix}_{int(pc):02d}",
                    f"Distribution of Outstanding {class_label} Credit - Purpose: {PURPOSE_LABELS[pc]} - {subgroup}",
                    value, "Percent",
                    "MoSPI/NSSO AIDIS 2003 Block 15.2; loan-purpose codes",
                )
                rows.append(row)
                catalog_add(catalog, row)

    return rows, stats


# =============================================================================
# WEIGHTED DECILES / GINI
# =============================================================================


def geo_aggregate_keys_for_decile(row, include_subgroups=True):
    """All-India + State aggregate only; no district-level decile/Gini output."""
    state = row["State"]
    sector = row["Sector"]
    subgroup = subgroup_export_label(row.get("Household_Group"))
    keys = []
    for geo_level, s in (("ALL", "00"), ("STATE", state)):
        keys.append((geo_level, s, "00", "0", "All HH"))
        keys.append((geo_level, s, "00", sector, "All HH"))
        if include_subgroups and subgroup:
            keys.append((geo_level, s, "00", sector, subgroup))
    return keys


def weighted_decile_assign(rows):
    """
    rows: list of dicts with Weight and Total_Assets_Rs.
    Returns list of 10 lists using cumulative-weight midpoint assignment.
    """
    buckets = [[] for _ in range(10)]
    if not rows:
        return buckets
    ordered = sorted(rows, key=lambda r: (r["Total_Assets_Rs"], r.get("HHID", r.get("PANEL_HHID", ""))))
    total_w = sum(r["Weight"] for r in ordered)
    if total_w <= 0:
        return buckets
    cum = 0.0
    for r in ordered:
        w = r["Weight"]
        midpoint = cum + w / 2.0
        dec = int(math.floor((midpoint / total_w) * 10.0)) + 1
        dec = max(1, min(10, dec))
        buckets[dec - 1].append(r)
        cum += w
    return buckets


def weighted_gini(rows):
    if not rows:
        return 0.0
    ordered = sorted(rows, key=lambda r: (r["Total_Assets_Rs"], r.get("HHID", r.get("PANEL_HHID", ""))))
    W = sum(r["Weight"] for r in ordered)
    Y = sum(r["Weight"] * r["Total_Assets_Rs"] for r in ordered)
    if W <= 0 or Y <= 0:
        return 0.0
    cum = 0.0
    num = 0.0
    for r in ordered:
        w = r["Weight"]
        x = r["Total_Assets_Rs"]
        cum += w
        num += w * (2.0 * cum - w - W) * x
    return num / (W * Y)


def build_stock_decile_sets(stock_master, stock_order):
    sets = defaultdict(list)
    for hhid in stock_order:
        row = stock_master[hhid]
        for key in geo_aggregate_keys_for_decile(row, include_subgroups=True):
            sets[key].append(row)
    return sets


def emit_asset_deciles_and_gini(args, stock_master, stock_order, district_lookup, catalog):
    sets = build_stock_decile_sets(stock_master, stock_order)
    decile_rows = []
    gini_rows = []
    empty_deciles = 0
    negative_gini_domains = 0

    for dkey in sorted(sets, key=domain_sort_key):
        members = sets[dkey]
        subgroup = dkey[4]
        buckets = weighted_decile_assign(members)

        for i, bucket in enumerate(buckets, start=1):
            if not bucket:
                empty_deciles += 1
                ava = aod = dar = 0.0
            else:
                W = sum(r["Weight"] for r in bucket)
                WA = sum(r["Weight"] * r["Total_Assets_Rs"] for r in bucket)
                WD = sum(r["Weight"] * r["Cash_Debt_2002_Rs"] for r in bucket)
                ava = safe_div(WA, W)
                aod = safe_div(WD, W)
                dar = safe_div(WD, WA)

            for suffix, label, value, unit in (
                ("AVA", "AVA", ava, "Rs. per HH"),
                ("AOD", "AOD", aod, "Rs. per HH"),
                ("DAR", "DAR", dar, "Ratio"),
            ):
                row = final_row(
                    args, 4, "Asset-Holding Deciles", f"D{i}", f"Asset Decile {i}",
                    dkey, district_lookup, 1, f"DECILE_{i}_{suffix}",
                    f"{label} by Asset-Holding Decile {i} - {subgroup}", value, unit,
                    "Derived from AIDIS 2003 household asset/debt microdata using weighted asset deciles",
                )
                decile_rows.append(row)
                catalog_add(catalog, row)

        if any(r["Total_Assets_Rs"] < 0 for r in members):
            negative_gini_domains += 1
        g = weighted_gini(members)
        row = final_row(
            args, 6, "Asset Inequality", subgroup, subgroup,
            dkey, district_lookup, 1, "GINI_ASSET",
            f"Gini's Coefficient of Asset Holdings - {subgroup}", g, "Coefficient",
            "Derived weighted Gini from AIDIS 2003 household total assets",
        )
        gini_rows.append(row)
        catalog_add(catalog, row)

    return decile_rows, gini_rows, empty_deciles, negative_gini_domains


# =============================================================================
# GROUP 5 CAPITAL EXPENDITURE
# =============================================================================


def flow_geo_sets(flow, panel_order):
    occupation_sets = defaultdict(list)
    decile_sets = defaultdict(list)

    for pid in panel_order:
        row = flow[pid]
        state = row["State"]
        sector = row["Sector"]
        subgroup = subgroup_export_label(row.get("Household_Group"))

        for geo_level, s in (("ALL", "00"), ("STATE", state)):
            # Occupational categories.
            occupation_sets[(geo_level, s, "00", "0", "All HH")].append(row)
            occupation_sets[(geo_level, s, "00", sector, "All HH")].append(row)
            if subgroup:
                occupation_sets[(geo_level, s, "00", sector, subgroup)].append(row)

            # Decile FCE/EPL: Total/Rural/Urban All-HH only, matching the client
            # structural convention that "by decile" and "by occupation" are
            # separate cuts rather than a decile x occupation cross-product.
            decile_sets[(geo_level, s, "00", "0", "All HH")].append(row)
            decile_sets[(geo_level, s, "00", sector, "All HH")].append(row)

    return occupation_sets, decile_sets


def emit_flow_kpis(args, flow, panel_order, district_lookup, catalog):
    occupation_sets, decile_sets = flow_geo_sets(flow, panel_order)
    rows = []
    empty_deciles = 0

    # Occupational categories.
    for dkey in sorted(occupation_sets, key=domain_sort_key):
        members = occupation_sets[dkey]
        subgroup = dkey[4]
        W = sum(r["Weight"] for r in members)
        fce = safe_div(sum(r["Weight"] * r["FCE_Rs"] for r in members), W)
        epl = safe_div(sum(r["Weight"] * r["EPL_Rs"] for r in members), W)
        for cid, label, value in (
            ("FCE", "Average Fixed Capital Expenditure per HH", fce),
            ("EPL", "Average Expenditure on Purchase of Land per HH", epl),
        ):
            row = final_row(
                args, 5, "Capital Expenditure", subgroup, subgroup,
                dkey, district_lookup, 2, cid,
                f"{label} - Occupational Category: {subgroup}", value, "Rs. per HH",
                "MoSPI/NSSO AIDIS 2003 combined Visits 1+2; Report 504 methodology",
            )
            rows.append(row)
            catalog_add(catalog, row)

    # Asset-decile cuts.
    for dkey in sorted(decile_sets, key=domain_sort_key):
        members = decile_sets[dkey]
        buckets = weighted_decile_assign(members)
        for i, bucket in enumerate(buckets, start=1):
            if not bucket:
                empty_deciles += 1
                fce = epl = 0.0
            else:
                W = sum(r["Weight"] for r in bucket)
                fce = safe_div(sum(r["Weight"] * r["FCE_Rs"] for r in bucket), W)
                epl = safe_div(sum(r["Weight"] * r["EPL_Rs"] for r in bucket), W)
            for cid, label, value in (
                (f"DECILE_{i}_FCE", "Average Fixed Capital Expenditure per HH", fce),
                (f"DECILE_{i}_EPL", "Average Expenditure on Purchase of Land per HH", epl),
            ):
                row = final_row(
                    args, 5, "Capital Expenditure", f"D{i}", f"Asset Decile {i}",
                    dkey, district_lookup, 2, cid,
                    f"{label} - Asset Decile {i} - All HH", value, "Rs. per HH",
                    "MoSPI/NSSO AIDIS 2003 combined Visits 1+2; weighted asset-decile flow estimate",
                )
                rows.append(row)
                catalog_add(catalog, row)

    return rows, empty_deciles


# =============================================================================
# FINAL QA / COVERAGE
# =============================================================================


def domain_sort_key(key):
    geo_level, state, district, sector, subgroup = key
    geo_rank = {"ALL": 0, "STATE": 1, "DISTRICT": 2}.get(geo_level, 9)
    subgroup_rank = {
        "All HH": 0,
        "Cultivator HH": 1,
        "Non-Cultivator HH": 2,
        "Self-employed": 1,
        "Others": 2,
    }.get(subgroup, 9)
    return (geo_rank, int(state or 0), int(district or 0), int(sector or 0), subgroup_rank, subgroup)


def validate_final_stock_controls(stock_acc):
    observations = {}
    observations[("All India", "AVA")] = stock_metrics(stock_acc[("ALL", "00", "00", "0", "All HH")])["AVA"]
    observations[("Rural", "AVA")] = stock_metrics(stock_acc[("ALL", "00", "00", "1", "All HH")])["AVA"]
    observations[("Urban", "AVA")] = stock_metrics(stock_acc[("ALL", "00", "00", "2", "All HH")])["AVA"]
    observations[("Rural", "AOD")] = stock_metrics(stock_acc[("ALL", "00", "00", "1", "All HH")])["AOD"]
    observations[("Urban", "AOD")] = stock_metrics(stock_acc[("ALL", "00", "00", "2", "All HH")])["AOD"]
    observations[("Rural", "IOI")] = stock_metrics(stock_acc[("ALL", "00", "00", "1", "All HH")])["IOI"]
    observations[("Urban", "IOI")] = stock_metrics(stock_acc[("ALL", "00", "00", "2", "All HH")])["IOI"]

    result = []
    for key, (expected, tol) in STOCK_FINAL_CONTROLS.items():
        actual = observations[key]
        if key[1] == "IOI":
            passed = abs(actual - expected) <= tol
            note = f"absolute tolerance {tol} percentage points"
        else:
            passed = abs((actual - expected) / expected) <= tol
            note = f"relative tolerance {tol*100:.3f}%"
        result.append((key, expected, actual, passed, note))
    return result


def make_coverage_report(district_lookup_count, district_count):
    return [
        {
            "area": "Core stock KPIs",
            "status": "AVAILABLE",
            "coverage": "All India + State + District; Total/Rural/Urban and locked household groups",
            "note": "HH surveyed, AVA, AOD, AODL, IOI, DAR from Steps 02-04.",
        },
        {
            "area": "AVA components",
            "status": "AVAILABLE",
            "coverage": "All India + State + District",
            "note": "Others is a non-overlapping residual: durable assets + shares/debentures + loans receivable.",
        },
        {
            "area": "Credit agency / interest / purpose",
            "status": "AVAILABLE_WITH_2003_CLASSIFICATION",
            "coverage": "All India + State + District",
            "note": "2003 code 03 combines commercial banks incl. RRBs; code 02 combines co-op society/bank; no fabricated splits.",
        },
        {
            "area": "Asset-holding deciles",
            "status": "AVAILABLE",
            "coverage": "All India + State aggregate; Total/Rural/Urban + household groups",
            "note": "Weighted midpoint cumulative-weight deciles; district-level deciles intentionally not emitted.",
        },
        {
            "area": "FCE / EPL",
            "status": "AVAILABLE",
            "coverage": "All India + State aggregate; occupation categories and Total/Rural/Urban asset deciles",
            "note": "Full-year 01-07-2002 to 30-06-2003 from paired Visits 1+2 Block17.2; purpose 5 normal repairs excluded from FCE.",
        },
        {
            "area": "Gini of asset holdings",
            "status": "AVAILABLE_DERIVED",
            "coverage": "All India + State aggregate; Total/Rural/Urban + household groups",
            "note": "Weighted Gini derived from household total assets; signed asset values retained rather than coerced.",
        },
        {
            "area": "Adult population having bank deposit account - Total/Male/Female",
            "status": "UNAVAILABLE_NOT_FABRICATED",
            "coverage": "No output rows",
            "note": "Locked 2003 methodology: provided person-level Block4 does not directly supply individual bank-account ownership.",
        },
        {
            "area": "District names",
            "status": "COMPLETE" if district_lookup_count == district_count else "PARTIAL_CODE_FALLBACK",
            "coverage": f"{district_lookup_count}/{district_count} observed State-District codes have supplied survey-era names",
            "note": "Unmapped names are emitted as 'District code XX'; original 2003 codes are preserved. Do not substitute modern district geography.",
        },
        {
            "area": "Published_date metadata",
            "status": "USER_OVERRIDE_OR_BLANK",
            "coverage": "Single optional --published-date value",
            "note": "Left blank by default rather than guessing one date across Reports 500/501/504.",
        },
    ]


def write_domain_inventory(stock_acc, district_lookup):
    rows = []
    for key in sorted(stock_acc, key=domain_sort_key):
        geo = export_geo(key, district_lookup)
        m = stock_metrics(stock_acc[key])
        rows.append({
            "geo_level": key[0],
            **geo,
            "Sector_code": key[3],
            "Sector": SECTOR_NAMES.get(key[3], ""),
            "SUB_GROUP_NAME": key[4],
            "sample_households": int(stock_acc[key]["n"]),
            "weight_sum": fmt(stock_acc[key]["weight"]),
            "AVA": fmt(m["AVA"]),
            "AOD": fmt(m["AOD"]),
            "IOI": fmt(m["IOI"]),
            "DAR": fmt(m["DAR"]),
        })
    write_csv(
        DOMAIN_INVENTORY_FILE,
        [
            "geo_level", "State_ID", "State_Name", "District_ID", "District_Name",
            "Sector_code", "Sector", "SUB_GROUP_NAME", "sample_households", "weight_sum",
            "AVA", "AOD", "IOI", "DAR",
        ],
        rows,
    )
    return rows


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="AIDIS 2003 Step05 KPI + final export")
    parser.add_argument(
        "--district-lookup",
        default=str(CONFIG_DIR / "aidis_2003_district_lookup.csv"),
        help="Optional survey-era district lookup CSV",
    )
    parser.add_argument(
        "--published-date",
        default="",
        help="Optional final Published_date metadata; blank by default to avoid guessing",
    )
    parser.add_argument(
        "--extracted-date",
        default=datetime.now().strftime("%d-%b-%y"),
        help="Final Extracted_Date metadata",
    )
    args = parser.parse_args()
    args.district_lookup = Path(args.district_lookup) if args.district_lookup else None

    print("=" * 78)
    print("AIDIS 2003 - STEP 05 KPI BUILD + FINAL EXPORT")
    print("Stock KPIs + credit + deciles + FCE/EPL + Gini + client-format CSV")
    print("=" * 78)

    for d in (CACHE_DIR, WORK_DIR, FINAL_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    errors = []
    warnings = []
    checks = []
    catalog = {}

    # -------------------------------------------------------------------------
    # 1. Prerequisites
    # -------------------------------------------------------------------------
    print("\n[1] Step prerequisites")
    try:
        methodology = load_methodology()
        manifest = load_manifest()
        block17_path = manifest_source(manifest, BLOCK17_2_NAMES)
        stock_master, stock_order = load_stock_master()
        panel, panel_order = load_panel_base()

        state_count = len({r["State"] for r in stock_master.values()})
        district_count = len({(r["State"], r["District"]) for r in stock_master.values()})

        print("Methodology lock          : PASS")
        print(f"Production manifest       : PASS ({len(manifest)}/42)")
        print(f"Stock household master    : {len(stock_master):,}")
        print(f"Paired flow panel         : {len(panel):,}")
        print(f"Observed states/UTs       : {state_count}")
        print(f"Observed State-Districts  : {district_count}")
        print(f"Combined Block17.2        : {block17_path.name}")

        add_check(checks, "stock_household_rows", EXPECTED_STOCK_HH, len(stock_master), len(stock_master) == EXPECTED_STOCK_HH)
        add_check(checks, "panel_household_rows", EXPECTED_PANEL_HH, len(panel), len(panel) == EXPECTED_PANEL_HH)
        add_check(checks, "state_count", EXPECTED_STATE_COUNT, state_count, state_count == EXPECTED_STATE_COUNT)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print("\nSTEP 05 STATUS: FAIL")
        return 1

    # -------------------------------------------------------------------------
    # 2. Build full-year FCE/EPL flow fact
    # -------------------------------------------------------------------------
    print("\n[2] Build paired full-year FCE/EPL facts")
    flow = None
    flow_controls = []
    flow_failed_controls = 0
    try:
        flow, flow_stats, flow_bad_examples = build_flow_facts(block17_path, panel, panel_order, stock_master)
        print(f"Block17.2 source rows      : {flow_stats['rows']:,}")
        print(f"FCE source rows            : {flow_stats['fce_rows']:,}")
        print(f"EPL source rows            : {flow_stats['epl_rows']:,}")
        print(f"Normal-repair rows         : {flow_stats['repair_rows']:,}")
        print(f"Unclassified rows          : {flow_stats['unclassified_rows']:,}")
        print(f"Panel format errors        : {flow_stats['panel_format_errors']}")
        print(f"Unmatched panel rows       : {flow_stats['unmatched_panel']}")
        print(f"Core geography mismatches  : {flow_stats['core_mismatch']}")
        print(f"Weight mismatches          : {flow_stats['weight_mismatch']}")
        print(f"q10 component mismatches   : {flow_stats['q10_component_mismatch']}")
        print(f"Household flow fact rows   : {len(flow):,}")

        flow_checks = [
            ("block17_2_rows", EXPECTED_BLOCK17_2_ROWS, flow_stats["rows"]),
            ("flow_fact_rows", EXPECTED_PANEL_HH, len(flow)),
            ("flow_panel_format_errors", 0, flow_stats["panel_format_errors"]),
            ("flow_unmatched_panel_rows", 0, flow_stats["unmatched_panel"]),
            ("flow_core_mismatches", 0, flow_stats["core_mismatch"]),
            ("flow_weight_mismatches", 0, flow_stats["weight_mismatch"]),
            ("flow_negative_q10", 0, flow_stats["negative_q10"]),
            ("flow_q10_component_mismatches", 0, flow_stats["q10_component_mismatch"]),
        ]
        for name, exp, obs in flow_checks:
            ok = exp == obs
            add_check(checks, name, exp, obs, ok)
            if not ok:
                errors.append(f"{name}: expected {exp}, observed {obs}")

        if flow_stats["unclassified_rows"]:
            warnings.append(
                f"Block17.2 contains {flow_stats['unclassified_rows']} row(s) outside purpose codes 1-5; "
                f"their total amount={flow_stats['unclassified_amount']:.6f} is retained in flow audit but excluded from FCE/EPL."
            )

        flow_controls, flow_failed_controls = validate_flow_controls(flow)
        for row in flow_controls:
            print(
                f"{row['status']:4s} | {row['sector']:5s} | {row['metric']:3s} | "
                f"official={float(row['official_value']):>10,.3f} | "
                f"microdata={float(row['microdata_value']):>10,.3f}"
            )
        add_check(
            checks, "official_report504_flow_controls", len(flow_controls),
            len(flow_controls) - flow_failed_controls, flow_failed_controls == 0,
            f"{flow_failed_controls} failed",
        )
        if flow_failed_controls:
            errors.append(f"{flow_failed_controls} Report504 flow control(s) failed")
    except Exception as exc:
        errors.append(f"Flow fact build failed: {type(exc).__name__}: {exc}")

    # -------------------------------------------------------------------------
    # 3. District lookup / stock-domain aggregation
    # -------------------------------------------------------------------------
    print("\n[3] Geography + stock domain aggregation")
    try:
        district_lookup = read_optional_district_lookup(args.district_lookup)
        district_combos = build_district_template(stock_master, district_lookup)
        mapped_districts = sum(1 for x in district_combos if x in district_lookup)
        stock_acc = aggregate_stock_domains(stock_master, stock_order)
        domain_rows = write_domain_inventory(stock_acc, district_lookup)

        print(f"Stock reporting domains    : {len(stock_acc):,}")
        print(f"District names supplied    : {mapped_districts}/{len(district_combos)}")
        print(f"District lookup template   : {DISTRICT_TEMPLATE_FILE}")

        if mapped_districts < len(district_combos):
            warnings.append(
                f"Survey-era district names are incomplete ({mapped_districts}/{len(district_combos)} supplied). "
                "Final output uses code-based fallback names while preserving original 2003 codes."
            )

        stock_control_results = validate_final_stock_controls(stock_acc)
        stock_control_fail = 0
        for (scope, metric), exp, obs, ok, note in stock_control_results:
            stock_control_fail += int(not ok)
            add_check(checks, f"final_stock_control_{scope}_{metric}", exp, fmt(obs), ok, note)
            print(
                f"{'PASS' if ok else 'FAIL':4s} | {scope:9s} | {metric:3s} | "
                f"official={exp:>12,.3f} | microdata={obs:>12,.3f}"
            )
        if stock_control_fail:
            errors.append(f"{stock_control_fail} final stock control(s) failed")
    except Exception as exc:
        errors.append(f"Stock domain aggregation failed: {type(exc).__name__}: {exc}")
        district_lookup = {}
        stock_acc = {}
        mapped_districts = 0
        district_combos = []

    # -------------------------------------------------------------------------
    # 4. Generate final KPI rows
    # -------------------------------------------------------------------------
    print("\n[4] Generate final KPI families")
    final_rows = []
    credit_stats = Counter()
    stock_empty_deciles = 0
    flow_empty_deciles = 0
    gini_negative_domains = 0

    if stock_acc and flow is not None:
        try:
            core_component_rows = emit_core_and_components(args, stock_acc, district_lookup, catalog)
            final_rows.extend(core_component_rows)
            print(f"Core + AVA component rows : {len(core_component_rows):,}")

            credit_rows, credit_stats = emit_credit(args, stock_acc, stock_master, district_lookup, catalog)
            final_rows.extend(credit_rows)
            print(f"Credit KPI rows            : {len(credit_rows):,}")
            print(f"Core positive loan rows    : {credit_stats['core_positive_rows']:,}")
            print(f"Excluded Step04 orphans    : {credit_stats['excluded_orphan_rows']:,}")
            if credit_stats["unmatched_hhid"]:
                errors.append(f"Credit facts unmatched HHID count: {credit_stats['unmatched_hhid']}")

            decile_rows, gini_rows, stock_empty_deciles, gini_negative_domains = emit_asset_deciles_and_gini(
                args, stock_master, stock_order, district_lookup, catalog
            )
            final_rows.extend(decile_rows)
            final_rows.extend(gini_rows)
            print(f"Asset-decile rows          : {len(decile_rows):,}")
            print(f"Asset-Gini rows            : {len(gini_rows):,}")

            flow_rows, flow_empty_deciles = emit_flow_kpis(args, flow, panel_order, district_lookup, catalog)
            final_rows.extend(flow_rows)
            print(f"FCE/EPL rows               : {len(flow_rows):,}")

            if stock_empty_deciles:
                warnings.append(
                    f"{stock_empty_deciles} stock weighted-decile bucket(s) are empty in very small domains; "
                    "their exported estimates are 0."
                )
            if flow_empty_deciles:
                warnings.append(
                    f"{flow_empty_deciles} flow weighted-decile bucket(s) are empty in very small domains; "
                    "their exported estimates are 0."
                )
            if gini_negative_domains:
                warnings.append(
                    f"{gini_negative_domains} Gini reporting domain(s) include one or more of the four retained "
                    "negative net-asset households; signed values are retained and disclosed rather than coerced."
                )
        except Exception as exc:
            errors.append(f"Final KPI generation failed: {type(exc).__name__}: {exc}")

    # -------------------------------------------------------------------------
    # 5. Write coverage / KPI catalog / final CSV
    # -------------------------------------------------------------------------
    print("\n[5] Final export + coverage")
    coverage = make_coverage_report(mapped_districts, len(district_combos))
    write_csv(COVERAGE_FILE, ["area", "status", "coverage", "note"], coverage)

    # Add explicitly unavailable client KPI to catalog so absence is auditable.
    catalog["ADULT_BANK_ACCOUNT_TOTAL_MALE_FEMALE"] = {
        "Col_ID": "ADULT_BANK_ACCOUNT_TOTAL_MALE_FEMALE",
        "Survey_GROUP_ID": "7",
        "GROUP_NAME": "Financial Inclusion",
        "COL_DESC_example": "Adult Population (%) having deposit account in bank - Total/Male/Female",
        "Unit": "Percent",
        "availability": "UNAVAILABLE_NOT_FABRICATED",
        "note": "No directly supported individual bank-account ownership field in provided NSS59 person-level data.",
    }

    write_csv(
        KPI_CATALOG_FILE,
        ["Col_ID", "Survey_GROUP_ID", "GROUP_NAME", "COL_DESC_example", "Unit", "availability", "note"],
        [catalog[k] for k in sorted(catalog)],
    )

    # Stable long-format order.
    def final_sort_key(r):
        return (
            int(r["Survey_GROUP_ID"] or 0),
            int(r["State_ID"] or 0),
            int(r["District_ID"] or 0),
            int(r["Sector_code"] or 0),
            r["SUB_GROUP_NAME"],
            r["Col_ID"],
        )

    final_rows.sort(key=final_sort_key)

    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    with FINAL_FILE.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FINAL_FIELDS)
        w.writeheader()
        w.writerows(final_rows)

    blank_data = sum(1 for r in final_rows if clean(r.get("DATA")) == "")
    nonfinite_data = 0
    for r in final_rows:
        try:
            v = float(r["DATA"])
            if not math.isfinite(v):
                nonfinite_data += 1
        except Exception:
            nonfinite_data += 1

    state_ids = {r["State_ID"] for r in final_rows if r["State_ID"] != "0"}
    district_ids = {r["District_ID"] for r in final_rows if r["District_ID"] != "0"}
    col_ids = {r["Col_ID"] for r in final_rows}

    add_check(checks, "final_rows_positive", ">0", len(final_rows), len(final_rows) > 0)
    add_check(checks, "final_columns", len(FINAL_FIELDS), len(FINAL_FIELDS), True)
    add_check(checks, "final_blank_DATA", 0, blank_data, blank_data == 0)
    add_check(checks, "final_nonfinite_DATA", 0, nonfinite_data, nonfinite_data == 0)
    add_check(checks, "final_state_count", EXPECTED_STATE_COUNT, len(state_ids), len(state_ids) == EXPECTED_STATE_COUNT)
    add_check(checks, "final_observed_district_count", len(district_combos), len(district_ids), len(district_ids) == len(district_combos))
    add_check(checks, "final_has_HH_SURVEYED", True, "HH_SURVEYED" in col_ids, "HH_SURVEYED" in col_ids)
    add_check(checks, "final_has_FCE", True, "FCE" in col_ids, "FCE" in col_ids)
    add_check(checks, "final_has_GINI", True, "GINI_ASSET" in col_ids, "GINI_ASSET" in col_ids)
    add_check(
        checks,
        "adult_bank_account_not_fabricated",
        "No ADULT_BANK_* final rows",
        sum(1 for x in col_ids if x.startswith("ADULT_BANK")),
        not any(x.startswith("ADULT_BANK") for x in col_ids),
        "Known NSS59 source limitation recorded in coverage report/catalog",
    )

    write_csv(EXPORT_CHECKS_FILE, ["check", "expected", "observed", "status", "note"], checks)
    failed_checks = sum(1 for x in checks if x["status"] != "PASS")

    print(f"Final rows                 : {len(final_rows):,}")
    print(f"Final columns              : {len(FINAL_FIELDS)}")
    print(f"Distinct Col_ID            : {len(col_ids)}")
    print(f"States/UTs                 : {len(state_ids)}")
    print(f"Observed districts         : {len(district_ids)}")
    print(f"Blank DATA                 : {blank_data}")
    print(f"Non-finite DATA            : {nonfinite_data}")
    print(f"Coverage report            : {COVERAGE_FILE}")
    print(f"Final CSV                  : {FINAL_FILE}")

    # -------------------------------------------------------------------------
    # 6. Summary
    # -------------------------------------------------------------------------
    if args.published_date == "":
        warnings.append(
            "Published_date is blank by default because Reports 500, 501 and 504 do not share one safely assumed publication date; "
            "use --published-date only when a delivery rule supplies the desired metadata date."
        )

    status = "PASS" if not errors and failed_checks == 0 else "FAIL"

    summary = [
        "=" * 78,
        "AIDIS 2003 - STEP 05 KPI BUILD + FINAL EXPORT SUMMARY",
        "=" * 78,
        f"Stock household rows          : {len(stock_master):,}",
        f"Paired flow household rows    : {len(panel):,}",
        f"Block17.2 source rows         : {flow_stats['rows'] if flow is not None else 0:,}",
        f"Flow official controls        : {len(flow_controls)}",
        f"Failed flow controls          : {flow_failed_controls}",
        f"Stock reporting domains       : {len(stock_acc):,}",
        f"Observed states/UTs           : {len(state_ids)}",
        f"Observed State-District codes : {len(district_combos)}",
        f"District names supplied       : {mapped_districts}/{len(district_combos)}",
        f"Final rows                    : {len(final_rows):,}",
        f"Final columns                 : {len(FINAL_FIELDS)}",
        f"Distinct Col_ID               : {len(col_ids)}",
        f"Blank DATA                    : {blank_data}",
        f"Non-finite DATA               : {nonfinite_data}",
        f"Validation checks             : {len(checks)}",
        f"Failed validation checks      : {failed_checks}",
        f"Warnings                      : {len(warnings)}",
        f"Errors                        : {len(errors)}",
        "",
        "DELIVERY COVERAGE:",
        "  - Core stock KPIs: All India + State + District.",
        "  - AVA components: All India + State + District.",
        "  - Credit agency/interest/purpose: All India + State + District using 2003 categories.",
        "  - Asset deciles: All India + State aggregate.",
        "  - FCE/EPL: All India + State aggregate, occupation + asset-decile cuts.",
        "  - Gini: All India + State aggregate.",
        "  - Adult deposit-account Total/Male/Female: unavailable in supplied 2003 person data; not fabricated.",
        "",
        "IMPORTANT 2003 CREDIT DISCLOSURES:",
        "  - Code 03 combines commercial banks including RRBs; no SCB/RRB split is fabricated.",
        "  - Code 02 combines co-operative society and co-operative bank.",
        "  - Code 07 is labelled financial company; it is not silently relabelled NBFC.",
        "",
        "FCE/EPL METHOD:",
        "  - Full-year reference period: 01-07-2002 to 30-06-2003.",
        "  - EPL: Block17.2 q10 for purpose=1 and item codes 101,201,202,301.",
        "  - FCE: Block17.2 q10 for purpose codes 1-4, excluding those EPL item codes.",
        "  - Purpose=5 normal repair/maintenance is excluded from FCE.",
        "",
        f"Household flow facts          : {FLOW_FACT_FILE}",
        f"Flow controls                 : {FLOW_CONTROLS_FILE}",
        f"District lookup template      : {DISTRICT_TEMPLATE_FILE}",
        f"Domain inventory              : {DOMAIN_INVENTORY_FILE}",
        f"KPI catalog                   : {KPI_CATALOG_FILE}",
        f"Coverage report               : {COVERAGE_FILE}",
        f"Export checks                 : {EXPORT_CHECKS_FILE}",
        f"Final CSV                     : {FINAL_FILE}",
        "",
    ]

    if warnings:
        summary.append("WARNINGS:")
        summary.extend(f"  - {x}" for x in warnings)
        summary.append("")
    if errors:
        summary.append("ERRORS:")
        summary.extend(f"  - {x}" for x in errors)
        summary.append("")

    summary.extend([f"STEP 05 STATUS: {status}", "=" * 78])
    SUMMARY_FILE.write_text("\n".join(summary), encoding="utf-8")

    print("\n" + "=" * 78)
    print("AIDIS 2003 - STEP 05 SUMMARY")
    print("=" * 78)
    print(f"Stock household rows       : {len(stock_master):,}")
    print(f"Panel household rows       : {len(panel):,}")
    print(f"Flow controls              : {len(flow_controls)}")
    print(f"Failed flow controls       : {flow_failed_controls}")
    print(f"Stock reporting domains    : {len(stock_acc):,}")
    print(f"Final rows                 : {len(final_rows):,}")
    print(f"Distinct Col_ID            : {len(col_ids)}")
    print(f"States/UTs                 : {len(state_ids)}")
    print(f"Observed districts         : {len(district_ids)}")
    print(f"District names supplied    : {mapped_districts}/{len(district_combos)}")
    print(f"Validation checks          : {len(checks)}")
    print(f"Failed validation checks   : {failed_checks}")
    print(f"Warnings                   : {len(warnings)}")
    print(f"Errors                     : {len(errors)}")
    print(f"Final CSV                  : {FINAL_FILE}")
    print(f"Coverage report            : {COVERAGE_FILE}")
    print(f"Summary                    : {SUMMARY_FILE}")
    print()
    print(f"STEP 05 STATUS: {status}")
    print("=" * 78)

    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())