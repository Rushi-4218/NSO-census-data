from pathlib import Path
import argparse
import csv
import hashlib
import math
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime


# =============================================================================
# AIDIS 2003 - STEP 06 FINAL DELIVERY QA
# NSS 59th Round, Schedule 18.2
#
# Final gate for the Step05 long-format client delivery. This step does NOT
# recalculate the survey from raw detail blocks. It independently validates the
# exported file, reconciles internal KPI identities, confirms the prior QA chain,
# records known non-blocking source limitations, hashes delivery artifacts, and
# creates a delivery package.
# =============================================================================


# =============================================================================
# FIXED DELIVERY CONTRACT FROM STEP 05
# =============================================================================

EXPECTED_FINAL_ROWS = 241_896
EXPECTED_FINAL_COLUMNS = 22
EXPECTED_COL_IDS = 111
EXPECTED_STATE_COUNT = 35
EXPECTED_DISTRICT_COUNT = 584
EXPECTED_STOCK_DOMAINS = 3_990
EXPECTED_DECILE_GINI_DOMAINS = 252
EXPECTED_FLOW_DECILE_DOMAINS = 108

EXPECTED_FINAL_FIELDS = [
    "Survey_ID", "Survey_NAME", "Survey_GROUP_ID", "GROUP_NAME",
    "SUB_GROUP_ID", "SUB_GROUP_NAME", "Year", "FREQ_DESC",
    "State_ID", "State_Name", "District_ID", "District_Name",
    "Sector_code", "Sector", "Published_date", "Extracted_Date",
    "Visit_ID", "Col_ID", "COL_DESC", "DATA", "Unit", "Source",
]

EXPECTED_SURVEY_ID = "AIDIS_59_2003"
EXPECTED_SURVEY_NAME = "All India Debt and Investment Survey (AIDIS), NSS 59th Round"
EXPECTED_YEAR = "2003"
EXPECTED_FREQ = "Annual"
EXPECTED_SOURCE = "https://microdata.gov.in/NADA/index.php/catalog/103"

GROUP_NAMES = {
    "1": "Household Assets and Debt",
    "2": "Assets by Component",
    "3": "Credit Distribution and Characteristics",
    "4": "Asset-Holding Deciles",
    "5": "Capital Expenditure",
    "6": "Asset Inequality",
}

EXPECTED_GROUP_ROWS = {
    "1": 23_940,
    "2": 39_900,
    "3": 167_580,
    "4": 7_560,
    "5": 2_664,
    "6": 252,
}

EXPECTED_GROUP_COLS = {
    "1": 6,
    "2": 10,
    "3": 42,
    "4": 30,
    "5": 22,
    "6": 1,
}

STATE_NAMES_2003 = {
    "1": "Jammu & Kashmir",
    "2": "Himachal Pradesh",
    "3": "Punjab",
    "4": "Chandigarh",
    "5": "Uttaranchal",
    "6": "Haryana",
    "7": "Delhi",
    "8": "Rajasthan",
    "9": "Uttar Pradesh",
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

CORE_COLS = {"HH_SURVEYED", "AVA", "AOD", "AODL", "IOI", "DAR"}
COMPONENT_COLS = {
    "AVA_COMPONENT_PHYSICAL_ASSETS",
    "AVA_COMPONENT_FINANCIAL_ASSETS",
    "AVA_COMPONENT_LAND",
    "AVA_COMPONENT_BUILDINGS",
    "AVA_COMPONENT_DEPOSITS",
    "AVA_COMPONENT_LIVESTOCK_POULTRY",
    "AVA_COMPONENT_AGRICULTURAL_MACHINERY_EQUIPMENT",
    "AVA_COMPONENT_TRANSPORT_EQUIPMENT",
    "AVA_COMPONENT_NON_FARM_BUSINESS_EQUIPMENT",
    "AVA_COMPONENT_OTHERS",
}

DETAIL_COMPONENT_COLS = [
    "AVA_COMPONENT_LAND",
    "AVA_COMPONENT_BUILDINGS",
    "AVA_COMPONENT_DEPOSITS",
    "AVA_COMPONENT_LIVESTOCK_POULTRY",
    "AVA_COMPONENT_AGRICULTURAL_MACHINERY_EQUIPMENT",
    "AVA_COMPONENT_TRANSPORT_EQUIPMENT",
    "AVA_COMPONENT_NON_FARM_BUSINESS_EQUIPMENT",
    "AVA_COMPONENT_OTHERS",
]

INSTITUTIONAL_SOURCE_DETAIL = [
    "CREDIT_SOURCE_GOVERNMENT",
    "CREDIT_SOURCE_COOP_SOCIETY_BANK",
    "CREDIT_SOURCE_COMMERCIAL_BANK_INCL_RRB",
    "CREDIT_SOURCE_INSURANCE",
    "CREDIT_SOURCE_PROVIDENT_FUND",
    "CREDIT_SOURCE_FINANCIAL_CORP_INSTITUTION",
    "CREDIT_SOURCE_FINANCIAL_COMPANY",
    "CREDIT_SOURCE_OTHER_INSTITUTIONAL_AGENCIES",
]
NONINSTITUTIONAL_SOURCE_DETAIL = [
    "CREDIT_SOURCE_LANDLORD",
    "CREDIT_SOURCE_AGRICULTURIST_MONEYLENDER",
    "CREDIT_SOURCE_PROFESSIONAL_MONEYLENDER",
    "CREDIT_SOURCE_TRADER",
    "CREDIT_SOURCE_RELATIVES_FRIENDS",
    "CREDIT_SOURCE_PROFESSIONALS",
    "CREDIT_SOURCE_OTHER_NON_INSTITUTIONAL_AGENCIES",
]
PURPOSE_INST_DETAIL = [f"PURPOSE_INST_{i:02d}" for i in range(1, 10)]
PURPOSE_NON_DETAIL = [f"PURPOSE_NON_{i:02d}" for i in range(1, 10)]

EXPECTED_PRIOR_SUMMARIES = [
    ("output/reports/step01_production_lock_summary.txt", "STEP 01D STATUS: PASS"),
    ("output/reports/step01b_resolution_summary.txt", "STEP 01B-B STATUS: PASS"),
    ("output/reports/step01bc_methodology_lock_summary.txt", "STEP 01B-C STATUS: PASS"),
    ("output/reports/step02_household_base_summary.txt", "STEP 02 STATUS: PASS"),
    ("output/reports/step03_asset_facts_summary.txt", "STEP 03 STATUS: PASS"),
    ("output/reports/step04_debt_credit_summary.txt", "STEP 04 STATUS: PASS"),
    ("output/reports/step05_kpi_export_summary.txt", "STEP 05 STATUS: PASS"),
]

EXPECTED_STATUS_CSVS = [
    "cache/step01bc_methodology_checks.csv",
    "cache/step02_household_base_checks.csv",
    "cache/step03_asset_block_audit.csv",
    "cache/step03_asset_ava_controls.csv",
    "cache/step04_debt_credit_checks.csv",
    "cache/step04_debt_controls.csv",
    "cache/step05_flow_controls.csv",
    "cache/step05_export_checks.csv",
]

# Independent final-output official controls. These are QA only.
# Type REL uses relative tolerance; ABS uses absolute tolerance.
FINAL_OFFICIAL_CONTROLS = [
    ("All India", "AVA", 306_967.0, 0.001, "REL"),
    ("Rural", "AVA", 265_606.0, 0.001, "REL"),
    ("Urban", "AVA", 417_158.0, 0.001, "REL"),
    ("Rural", "AOD", 7_539.0, 0.005, "REL"),
    ("Urban", "AOD", 11_771.0, 0.005, "REL"),
    ("Rural", "AODL", 28_449.0, 0.005, "REL"),
    ("Urban", "AODL", 66_129.0, 0.005, "REL"),
    ("Rural", "IOI", 26.5, 0.15, "ABS"),
    ("Urban", "IOI", 17.8, 0.15, "ABS"),
    ("Rural", "FCE", 2_719.0, 0.01, "REL"),
    ("Rural", "EPL", 391.0, 0.01, "REL"),
    ("Urban", "FCE", 5_925.0, 0.01, "REL"),
    ("Urban", "EPL", 348.0, 0.01, "REL"),
]


# =============================================================================
# HELPERS
# =============================================================================


def clean(value):
    return "" if value is None else str(value).strip()


def as_float(value):
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        if abs(value) < 5e-14:
            value = 0.0
        return f"{value:.10f}".rstrip("0").rstrip(".")
    return str(value)


def near(a, b, abs_tol=1e-6, rel_tol=1e-9):
    if a is None or b is None:
        return False
    return math.isclose(float(a), float(b), abs_tol=abs_tol, rel_tol=rel_tol)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def add_check(checks, section, name, expected, observed, passed, severity="FATAL", note=""):
    checks.append({
        "section": section,
        "check": name,
        "expected": str(expected),
        "observed": str(observed),
        "severity": severity,
        "status": "PASS" if passed else ("WARN" if severity != "FATAL" else "FAIL"),
        "note": note,
    })


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path, root):
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def read_small_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def status_column(fieldnames):
    for field in fieldnames or []:
        if clean(field).casefold() == "status":
            return field
    return None


def add_invalid_sample(samples, row_number, issue, row):
    if len(samples) >= 250:
        return
    samples.append({
        "row_number": row_number,
        "issue": issue,
        "Survey_GROUP_ID": clean(row.get("Survey_GROUP_ID")),
        "State_ID": clean(row.get("State_ID")),
        "District_ID": clean(row.get("District_ID")),
        "Sector_code": clean(row.get("Sector_code")),
        "SUB_GROUP_NAME": clean(row.get("SUB_GROUP_NAME")),
        "Col_ID": clean(row.get("Col_ID")),
        "COL_DESC": clean(row.get("COL_DESC")),
        "DATA": clean(row.get("DATA")),
    })


# =============================================================================
# PRIOR QA CHAIN
# =============================================================================


def validate_prior_chain(root, checks):
    print("\n[1] Prior-step QA chain")

    for relative, marker in EXPECTED_PRIOR_SUMMARIES:
        path = root / relative
        exists = path.exists() and path.is_file()
        text = path.read_text(encoding="utf-8", errors="replace") if exists else ""
        passed = exists and marker in text
        add_check(
            checks,
            "Prior QA chain",
            relative,
            marker,
            marker if passed else ("MISSING" if not exists else "PASS marker not found"),
            passed,
        )
        print(f"{relative:58s}: {'PASS' if passed else 'FAIL'}")

    # Production manifest is the source lock.
    manifest = root / "cache" / "step01_production_manifest.csv"
    if manifest.exists():
        rows = read_small_csv(manifest)
        bad = [r for r in rows if clean(r.get("status")).upper() != "PASS"]
        passed = len(rows) == 42 and not bad
        add_check(checks, "Prior QA chain", "production_manifest", "42 PASS rows", f"{len(rows)} rows; {len(bad)} non-PASS", passed)
        print(f"{'cache/step01_production_manifest.csv':58s}: {'PASS' if passed else 'FAIL'} ({len(rows)}/42)")
    else:
        add_check(checks, "Prior QA chain", "production_manifest", "42 PASS rows", "MISSING", False)
        print(f"{'cache/step01_production_manifest.csv':58s}: FAIL (missing)")

    for relative in EXPECTED_STATUS_CSVS:
        path = root / relative
        if not path.exists():
            add_check(checks, "Prior QA chain", relative, "all status rows PASS", "MISSING", False)
            print(f"{relative:58s}: FAIL (missing)")
            continue

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            status_field = status_column(reader.fieldnames)
            rows = list(reader)

        if status_field is None:
            add_check(checks, "Prior QA chain", relative, "status column", "missing status column", False)
            print(f"{relative:58s}: FAIL (no status column)")
            continue

        bad = [r for r in rows if clean(r.get(status_field)).upper() != "PASS"]
        passed = len(rows) > 0 and not bad
        add_check(
            checks,
            "Prior QA chain",
            relative,
            "all status rows PASS",
            f"{len(rows)} rows; {len(bad)} non-PASS",
            passed,
        )
        print(f"{relative:58s}: {'PASS' if passed else 'FAIL'} ({len(rows)} rows)")


# =============================================================================
# KPI CATALOG / DISTRICT TEMPLATE / COVERAGE
# =============================================================================


def load_catalog(root, checks):
    path = root / "cache" / "step05_kpi_catalog.csv"
    if not path.exists():
        add_check(checks, "Step05 support", "KPI catalog", "present", "MISSING", False)
        return {}, []

    rows = read_small_csv(path)
    catalog = {clean(r.get("Col_ID")): r for r in rows if clean(r.get("Col_ID"))}
    available = {k for k, r in catalog.items() if clean(r.get("availability")).startswith("AVAILABLE")}
    unavailable = {k for k, r in catalog.items() if clean(r.get("availability")) == "UNAVAILABLE_NOT_FABRICATED"}

    add_check(checks, "Step05 support", "KPI catalog rows", 112, len(rows), len(rows) == 112)
    add_check(checks, "Step05 support", "available KPI catalog rows", 111, len(available), len(available) == 111)
    add_check(
        checks,
        "Step05 support",
        "adult bank-account KPI unavailable",
        {"ADULT_BANK_ACCOUNT_TOTAL_MALE_FEMALE"},
        unavailable,
        unavailable == {"ADULT_BANK_ACCOUNT_TOTAL_MALE_FEMALE"},
    )
    return catalog, rows


def load_district_template(root, checks):
    path = root / "cache" / "step05_district_lookup_template.csv"
    if not path.exists():
        add_check(checks, "Step05 support", "district lookup template", "present", "MISSING", False)
        return {}, 0, 0

    rows = read_small_csv(path)
    by_id = {}
    supplied = 0
    for r in rows:
        did = clean(r.get("District_ID"))
        if did:
            by_id[did] = r
        if clean(r.get("District_Name")):
            supplied += 1

    add_check(checks, "Step05 support", "district template rows", EXPECTED_DISTRICT_COUNT, len(rows), len(rows) == EXPECTED_DISTRICT_COUNT)
    return by_id, supplied, len(rows)


def validate_coverage(root, checks, disclosures, strict_district_names=False, strict_published_date=False):
    path = root / "output" / "reports" / "step05_coverage_report.csv"
    if not path.exists():
        add_check(checks, "Coverage", "Step05 coverage report", "present", "MISSING", False)
        return

    rows = read_small_csv(path)
    by_area = {clean(r.get("area")): r for r in rows}
    add_check(checks, "Coverage", "coverage report rows", 9, len(rows), len(rows) == 9)

    adult = by_area.get("Adult population having bank deposit account - Total/Male/Female", {})
    adult_ok = clean(adult.get("status")) == "UNAVAILABLE_NOT_FABRICATED"
    add_check(checks, "Coverage", "adult bank-account limitation recorded", "UNAVAILABLE_NOT_FABRICATED", clean(adult.get("status")), adult_ok)
    if adult_ok:
        disclosures.append("Adult bank deposit-account ownership by Total/Male/Female is unavailable in the supplied 2003 person-level data and is not fabricated.")

    district = by_area.get("District names", {})
    district_status = clean(district.get("status"))
    district_complete = district_status == "COMPLETE"
    if district_complete:
        add_check(checks, "Coverage", "survey-era district names", "COMPLETE", district_status, True)
    else:
        add_check(
            checks,
            "Coverage",
            "survey-era district names",
            "COMPLETE or documented code fallback",
            district_status or "MISSING",
            False if strict_district_names else True,
            severity="FATAL" if strict_district_names else "DISCLOSURE",
            note=clean(district.get("coverage")),
        )
        disclosures.append(
            "Survey-era district names are incomplete; final data preserves original 2003 district codes and uses code-based fallback names where no authoritative name is supplied."
        )

    published = by_area.get("Published_date metadata", {})
    published_status = clean(published.get("status"))
    if strict_published_date:
        # Actual blank/nonblank check is performed on final rows later.
        add_check(checks, "Coverage", "Published_date coverage rule", "nonblank delivery date", published_status, True)
    elif published_status:
        add_check(checks, "Coverage", "Published_date policy recorded", "USER_OVERRIDE_OR_BLANK", published_status, published_status == "USER_OVERRIDE_OR_BLANK")


# =============================================================================
# FINAL CSV SCAN
# =============================================================================


def expected_col_count(group_id, col_id):
    if group_id in ("1", "2", "3"):
        return EXPECTED_STOCK_DOMAINS
    if group_id == "4":
        return EXPECTED_DECILE_GINI_DOMAINS
    if group_id == "6":
        return EXPECTED_DECILE_GINI_DOMAINS
    if group_id == "5":
        if col_id in ("FCE", "EPL"):
            return EXPECTED_DECILE_GINI_DOMAINS
        if re.fullmatch(r"DECILE_(?:[1-9]|10)_(?:FCE|EPL)", col_id):
            return EXPECTED_FLOW_DECILE_DOMAINS
    return None


def subgroup_sector_valid(group_id, subgroup_name, sector_code):
    if subgroup_name in ("Cultivator HH", "Non-Cultivator HH"):
        return sector_code == "1"
    if subgroup_name in ("Self-employed", "Others"):
        return sector_code == "2"
    if subgroup_name == "All HH":
        return sector_code in ("0", "1", "2")
    if group_id in ("4", "5") and re.fullmatch(r"Asset Decile (?:[1-9]|10)", subgroup_name):
        return sector_code in ("0", "1", "2")
    return False


def scan_final(root, catalog, district_template, checks, invalid_samples, duplicate_samples, disclosures, strict_published_date=False):
    final_path = root / "output" / "final" / "AIDIS_2003_All_India_States_Districts_Final.csv"
    if not final_path.exists():
        add_check(checks, "Final CSV", "final file exists", "present", "MISSING", False)
        return None

    group_rows = Counter()
    group_cols = defaultdict(set)
    col_rows = Counter()
    col_groups = defaultdict(set)
    state_ids = set()
    district_ids = set()
    observed_district_pairs = set()
    survey_ids = set()
    survey_names = set()
    years = set()
    freqs = set()
    sources = set()
    published_dates = set()
    extracted_dates = set()
    visit_ids = set()

    blank_data = 0
    nonfinite_data = 0
    blank_critical = 0
    metadata_errors = 0
    catalog_errors = 0
    duplicate_count = 0
    sort_violations = 0
    percent_out_of_bounds = 0
    gini_out_of_standard_range = 0
    district_name_fallback_rows = 0
    district_name_fallback_ids = set()

    seen_identity = set()
    previous_sort_key = None

    core = defaultdict(dict)
    components = defaultdict(dict)
    credit = defaultdict(dict)
    official_final_values = {}

    required_nonblank = [
        "Survey_ID", "Survey_NAME", "Survey_GROUP_ID", "GROUP_NAME",
        "SUB_GROUP_ID", "SUB_GROUP_NAME", "Year", "FREQ_DESC",
        "State_ID", "State_Name", "District_ID", "District_Name",
        "Sector_code", "Sector", "Extracted_Date", "Visit_ID",
        "Col_ID", "COL_DESC", "DATA", "Unit", "Source",
    ]

    print("\n[2] Final CSV structural / metadata scan")

    with final_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        header_ok = header == EXPECTED_FINAL_FIELDS
        add_check(checks, "Final CSV", "exact 22-column schema", EXPECTED_FINAL_FIELDS, header, header_ok)

        for row_number, row in enumerate(reader, start=2):
            n = row_number - 1
            gid = clean(row.get("Survey_GROUP_ID"))
            col_id = clean(row.get("Col_ID"))
            state_id = clean(row.get("State_ID"))
            district_id = clean(row.get("District_ID"))
            sector_code = clean(row.get("Sector_code"))
            subgroup_id = clean(row.get("SUB_GROUP_ID"))
            subgroup_name = clean(row.get("SUB_GROUP_NAME"))
            visit_id = clean(row.get("Visit_ID"))
            col_desc = clean(row.get("COL_DESC"))

            group_rows[gid] += 1
            group_cols[gid].add(col_id)
            col_rows[(gid, col_id)] += 1
            col_groups[col_id].add(gid)

            survey_ids.add(clean(row.get("Survey_ID")))
            survey_names.add(clean(row.get("Survey_NAME")))
            years.add(clean(row.get("Year")))
            freqs.add(clean(row.get("FREQ_DESC")))
            sources.add(clean(row.get("Source")))
            published_dates.add(clean(row.get("Published_date")))
            extracted_dates.add(clean(row.get("Extracted_Date")))
            visit_ids.add(visit_id)

            if state_id != "0":
                state_ids.add(state_id)
            if district_id != "0":
                district_ids.add(district_id)
                observed_district_pairs.add((state_id, district_id))

            issue_on_row = False

            for field in required_nonblank:
                if clean(row.get(field)) == "":
                    blank_critical += 1
                    issue_on_row = True
                    add_invalid_sample(invalid_samples, row_number, f"blank critical field: {field}", row)
                    break

            value = as_float(row.get("DATA"))
            if clean(row.get("DATA")) == "":
                blank_data += 1
            if value is None or not math.isfinite(value):
                nonfinite_data += 1
                if not issue_on_row:
                    add_invalid_sample(invalid_samples, row_number, "DATA is non-numeric/non-finite", row)

            # Fixed metadata contract.
            expected_group_name = GROUP_NAMES.get(gid)
            expected_sector_name = SECTOR_NAMES.get(sector_code)
            expected_visit = "2" if gid == "5" else "1"

            row_metadata_ok = True
            if clean(row.get("Survey_ID")) != EXPECTED_SURVEY_ID:
                row_metadata_ok = False
            if clean(row.get("Survey_NAME")) != EXPECTED_SURVEY_NAME:
                row_metadata_ok = False
            if clean(row.get("Year")) != EXPECTED_YEAR:
                row_metadata_ok = False
            if clean(row.get("FREQ_DESC")) != EXPECTED_FREQ:
                row_metadata_ok = False
            if expected_group_name is None or clean(row.get("GROUP_NAME")) != expected_group_name:
                row_metadata_ok = False
            if expected_sector_name is None or clean(row.get("Sector")) != expected_sector_name:
                row_metadata_ok = False
            if visit_id != expected_visit:
                row_metadata_ok = False
            if clean(row.get("Source")) != EXPECTED_SOURCE:
                row_metadata_ok = False
            if not subgroup_sector_valid(gid, subgroup_name, sector_code):
                row_metadata_ok = False

            # Geography consistency.
            if state_id == "0":
                if clean(row.get("State_Name")) != "All India" or district_id != "0" or clean(row.get("District_Name")) != "All Districts":
                    row_metadata_ok = False
            else:
                expected_state_name = STATE_NAMES_2003.get(state_id)
                if expected_state_name is None or clean(row.get("State_Name")) != expected_state_name:
                    row_metadata_ok = False
                if district_id == "0":
                    if clean(row.get("District_Name")) != "All Districts":
                        row_metadata_ok = False
                else:
                    try:
                        district_num = int(district_id)
                        if district_num // 100 != int(state_id):
                            row_metadata_ok = False
                    except Exception:
                        row_metadata_ok = False
                    template = district_template.get(district_id)
                    if template and clean(template.get("State")):
                        try:
                            template_state = str(int(clean(template.get("State"))))
                        except Exception:
                            template_state = clean(template.get("State"))
                        if template_state != state_id:
                            row_metadata_ok = False
                    if clean(row.get("District_Name")).startswith("District code "):
                        district_name_fallback_rows += 1
                        district_name_fallback_ids.add(district_id)

            if not row_metadata_ok:
                metadata_errors += 1
                add_invalid_sample(invalid_samples, row_number, "metadata / geography contract mismatch", row)

            # Catalog consistency.
            c = catalog.get(col_id)
            catalog_ok = c is not None
            if catalog_ok:
                catalog_ok = (
                    clean(c.get("availability")).startswith("AVAILABLE")
                    and clean(c.get("Survey_GROUP_ID")) == gid
                    and clean(c.get("GROUP_NAME")) == clean(row.get("GROUP_NAME"))
                    and clean(c.get("Unit")) == clean(row.get("Unit"))
                )
            if not catalog_ok:
                catalog_errors += 1
                add_invalid_sample(invalid_samples, row_number, "KPI catalog mismatch", row)

            # Exact metric identity. COL_DESC is included because decile output can
            # carry the occupational slice in the description while SUB_GROUP is
            # the decile label.
            identity = (
                gid, state_id, district_id, sector_code,
                subgroup_id, subgroup_name, visit_id, col_id, col_desc,
            )
            if identity in seen_identity:
                duplicate_count += 1
                if len(duplicate_samples) < 250:
                    duplicate_samples.append({
                        "row_number": row_number,
                        "Survey_GROUP_ID": gid,
                        "State_ID": state_id,
                        "District_ID": district_id,
                        "Sector_code": sector_code,
                        "SUB_GROUP_ID": subgroup_id,
                        "SUB_GROUP_NAME": subgroup_name,
                        "Visit_ID": visit_id,
                        "Col_ID": col_id,
                        "COL_DESC": col_desc,
                    })
            else:
                seen_identity.add(identity)

            # Stable Step05 ordering.
            try:
                sort_key = (
                    int(gid or 0), int(state_id or 0), int(district_id or 0),
                    int(sector_code or 0), subgroup_name, col_id,
                )
                if previous_sort_key is not None and sort_key < previous_sort_key:
                    sort_violations += 1
                    add_invalid_sample(invalid_samples, row_number, "final row ordering violation", row)
                previous_sort_key = sort_key
            except Exception:
                sort_violations += 1

            # Percentage bounds.
            if value is not None and math.isfinite(value):
                unit = clean(row.get("Unit"))
                if unit == "Percent" and not (-1e-8 <= value <= 100.0 + 1e-8):
                    percent_out_of_bounds += 1
                    add_invalid_sample(invalid_samples, row_number, "percent DATA outside [0,100]", row)
                if col_id == "GINI_ASSET" and not (0.0 <= value <= 1.0):
                    # Negative asset values can make a conventional [0,1] Gini
                    # interpretation less straightforward, so this is disclosure
                    # only rather than a fatal error.
                    gini_out_of_standard_range += 1

            domain = (state_id, district_id, sector_code, subgroup_name)
            if gid == "1" and col_id in CORE_COLS and value is not None:
                core[domain][col_id] = value
            elif gid == "2" and col_id in COMPONENT_COLS and value is not None:
                components[domain][col_id] = value
            elif gid == "3" and value is not None:
                credit[domain][col_id] = value

            # Pull specific official-control rows from the final export.
            if state_id == "0" and district_id == "0" and subgroup_name == "All HH" and value is not None:
                scope = "All India" if sector_code == "0" else "Rural" if sector_code == "1" else "Urban" if sector_code == "2" else ""
                if scope and gid == "1" and col_id in ("AVA", "AOD", "AODL", "IOI", "HH_SURVEYED"):
                    official_final_values[(scope, col_id)] = value
                if scope in ("Rural", "Urban") and gid == "5" and col_id in ("FCE", "EPL"):
                    official_final_values[(scope, col_id)] = value

    total_rows = sum(group_rows.values())

    print(f"Final rows                 : {total_rows:,}")
    print(f"Final columns              : {len(EXPECTED_FINAL_FIELDS)}")
    print(f"Distinct Col_ID            : {len(col_groups):,}")
    print(f"States/UTs                 : {len(state_ids):,}")
    print(f"Observed districts         : {len(district_ids):,}")
    print(f"Duplicate metric identities: {duplicate_count:,}")
    print(f"Blank DATA                 : {blank_data:,}")
    print(f"Non-finite DATA            : {nonfinite_data:,}")
    print(f"Metadata contract errors   : {metadata_errors:,}")
    print(f"Catalog mapping errors     : {catalog_errors:,}")

    # Main structural checks.
    add_check(checks, "Final CSV", "final row count", EXPECTED_FINAL_ROWS, total_rows, total_rows == EXPECTED_FINAL_ROWS)
    add_check(checks, "Final CSV", "distinct final Col_ID", EXPECTED_COL_IDS, len(col_groups), len(col_groups) == EXPECTED_COL_IDS)
    add_check(checks, "Final CSV", "state/UT count", EXPECTED_STATE_COUNT, len(state_ids), len(state_ids) == EXPECTED_STATE_COUNT)
    add_check(checks, "Final CSV", "observed district count", EXPECTED_DISTRICT_COUNT, len(district_ids), len(district_ids) == EXPECTED_DISTRICT_COUNT)
    add_check(checks, "Final CSV", "blank DATA", 0, blank_data, blank_data == 0)
    add_check(checks, "Final CSV", "non-finite/non-numeric DATA", 0, nonfinite_data, nonfinite_data == 0)
    add_check(checks, "Final CSV", "blank critical metadata fields", 0, blank_critical, blank_critical == 0)
    add_check(checks, "Final CSV", "metadata/geography contract errors", 0, metadata_errors, metadata_errors == 0)
    add_check(checks, "Final CSV", "KPI catalog mapping errors", 0, catalog_errors, catalog_errors == 0)
    add_check(checks, "Final CSV", "duplicate metric identities", 0, duplicate_count, duplicate_count == 0)
    add_check(checks, "Final CSV", "stable-order violations", 0, sort_violations, sort_violations == 0)
    add_check(checks, "Final CSV", "percent values outside [0,100]", 0, percent_out_of_bounds, percent_out_of_bounds == 0)

    add_check(checks, "Final CSV", "Survey_ID values", {EXPECTED_SURVEY_ID}, survey_ids, survey_ids == {EXPECTED_SURVEY_ID})
    add_check(checks, "Final CSV", "Survey_NAME values", {EXPECTED_SURVEY_NAME}, survey_names, survey_names == {EXPECTED_SURVEY_NAME})
    add_check(checks, "Final CSV", "Year values", {EXPECTED_YEAR}, years, years == {EXPECTED_YEAR})
    add_check(checks, "Final CSV", "FREQ_DESC values", {EXPECTED_FREQ}, freqs, freqs == {EXPECTED_FREQ})
    add_check(checks, "Final CSV", "Source values", {EXPECTED_SOURCE}, sources, sources == {EXPECTED_SOURCE})
    add_check(checks, "Final CSV", "Visit_ID values", {"1", "2"}, visit_ids, visit_ids == {"1", "2"})
    add_check(checks, "Final CSV", "Extracted_Date cardinality", "1 nonblank value", extracted_dates, len(extracted_dates) == 1 and "" not in extracted_dates)

    # Published date is deliberately optional, but it must be consistent across
    # the whole export. A mixture of blank/nonblank dates is not acceptable.
    add_check(checks, "Final CSV", "Published_date cardinality", "one consistent value (blank allowed)", published_dates, len(published_dates) == 1)
    only_published = next(iter(published_dates)) if len(published_dates) == 1 else ""
    if only_published == "":
        if strict_published_date:
            add_check(checks, "Final CSV", "Published_date nonblank", "nonblank", "blank", False)
        else:
            add_check(
                checks,
                "Final CSV",
                "Published_date nonblank",
                "optional",
                "blank by locked Step05 policy",
                False,
                severity="DISCLOSURE",
            )
            disclosures.append("Published_date is blank by design because Reports 500, 501 and 504 do not share one safely assumed publication date.")

    if district_name_fallback_ids:
        disclosures.append(
            f"{len(district_name_fallback_ids)} observed district code(s) use code-based District_Name fallbacks in the final CSV."
        )

    if gini_out_of_standard_range:
        add_check(
            checks,
            "Final CSV",
            "Gini outside conventional [0,1] range",
            0,
            gini_out_of_standard_range,
            False,
            severity="DISCLOSURE",
            note="Signed household asset values are retained; no coercion is performed.",
        )
        disclosures.append(
            f"{gini_out_of_standard_range} Gini output row(s) fall outside the conventional [0,1] range because signed asset values are retained."
        )
    else:
        add_check(checks, "Final CSV", "Gini outside conventional [0,1] range", 0, 0, True)

    return {
        "path": final_path,
        "rows": total_rows,
        "group_rows": group_rows,
        "group_cols": group_cols,
        "col_rows": col_rows,
        "col_groups": col_groups,
        "state_ids": state_ids,
        "district_ids": district_ids,
        "core": core,
        "components": components,
        "credit": credit,
        "official_final_values": official_final_values,
        "published_dates": published_dates,
        "extracted_dates": extracted_dates,
        "fallback_district_ids": district_name_fallback_ids,
    }


# =============================================================================
# KPI FAMILY / COLUMN COUNTS
# =============================================================================


def validate_family_counts(scan, checks, family_rows_out, col_counts_out):
    print("\n[3] KPI family / Col_ID completeness")
    if scan is None:
        return

    for gid in sorted(EXPECTED_GROUP_ROWS, key=int):
        observed_rows = scan["group_rows"].get(gid, 0)
        observed_cols = len(scan["group_cols"].get(gid, set()))
        expected_rows = EXPECTED_GROUP_ROWS[gid]
        expected_cols = EXPECTED_GROUP_COLS[gid]
        status = "PASS" if observed_rows == expected_rows and observed_cols == expected_cols else "FAIL"
        family_rows_out.append({
            "Survey_GROUP_ID": gid,
            "GROUP_NAME": GROUP_NAMES[gid],
            "expected_rows": expected_rows,
            "observed_rows": observed_rows,
            "expected_distinct_Col_ID": expected_cols,
            "observed_distinct_Col_ID": observed_cols,
            "status": status,
        })
        add_check(checks, "KPI families", f"group {gid} row count", expected_rows, observed_rows, observed_rows == expected_rows)
        add_check(checks, "KPI families", f"group {gid} Col_ID count", expected_cols, observed_cols, observed_cols == expected_cols)
        print(f"Group {gid} | rows={observed_rows:>7,}/{expected_rows:>7,} | Col_ID={observed_cols:>2}/{expected_cols:>2} | {status}")

    # No Group 7 rows should exist; its single catalog item is explicitly unavailable.
    group7_rows = scan["group_rows"].get("7", 0)
    add_check(checks, "KPI families", "Group 7 unavailable KPI rows", 0, group7_rows, group7_rows == 0)

    bad_col_counts = 0
    for (gid, col_id), observed in sorted(scan["col_rows"].items(), key=lambda x: (int(x[0][0]), x[0][1])):
        expected = expected_col_count(gid, col_id)
        passed = expected is not None and observed == expected
        if not passed:
            bad_col_counts += 1
        col_counts_out.append({
            "Survey_GROUP_ID": gid,
            "Col_ID": col_id,
            "expected_rows": "" if expected is None else expected,
            "observed_rows": observed,
            "status": "PASS" if passed else "FAIL",
        })

    add_check(checks, "KPI families", "per-Col_ID row count mismatches", 0, bad_col_counts, bad_col_counts == 0)


# =============================================================================
# INTERNAL RECONCILIATIONS
# =============================================================================


def validate_internal_reconciliations(scan, checks, reconciliation_rows, invalid_samples, disclosures):
    print("\n[4] Internal KPI reconciliation")
    if scan is None:
        return

    core = scan["core"]
    components = scan["components"]
    credit = scan["credit"]

    avapf_errors = 0
    avadetail_errors = 0
    aod_identity_errors = 0
    dar_identity_errors = 0
    missing_core_component_domains = 0

    for domain, c in core.items():
        comp = components.get(domain, {})
        if not CORE_COLS.issubset(c) or not COMPONENT_COLS.issubset(comp):
            missing_core_component_domains += 1
            continue

        ava = c["AVA"]
        physical = comp["AVA_COMPONENT_PHYSICAL_ASSETS"]
        financial = comp["AVA_COMPONENT_FINANCIAL_ASSETS"]
        detail_sum = sum(comp[k] for k in DETAIL_COMPONENT_COLS)

        if not near(ava, physical + financial, abs_tol=0.02, rel_tol=2e-9):
            avapf_errors += 1
        if not near(ava, detail_sum, abs_tol=0.02, rel_tol=2e-9):
            avadetail_errors += 1

        aod = c["AOD"]
        aodl = c["AODL"]
        ioi = c["IOI"]
        dar = c["DAR"]

        expected_aod = aodl * ioi / 100.0
        if not near(aod, expected_aod, abs_tol=0.02, rel_tol=2e-8):
            aod_identity_errors += 1

        if abs(ava) > 1e-12:
            expected_dar = aod / ava
            if not near(dar, expected_dar, abs_tol=2e-9, rel_tol=2e-8):
                dar_identity_errors += 1
        elif abs(aod) > 1e-9 or abs(dar) > 1e-9:
            dar_identity_errors += 1

    reconciliation_rows.extend([
        {"reconciliation": "AVA = Physical assets + Financial assets", "domains_checked": len(core), "errors": avapf_errors, "status": "PASS" if avapf_errors == 0 else "FAIL"},
        {"reconciliation": "AVA = detailed non-overlapping client components", "domains_checked": len(core), "errors": avadetail_errors, "status": "PASS" if avadetail_errors == 0 else "FAIL"},
        {"reconciliation": "AOD = AODL * IOI / 100", "domains_checked": len(core), "errors": aod_identity_errors, "status": "PASS" if aod_identity_errors == 0 else "FAIL"},
        {"reconciliation": "DAR = AOD / AVA", "domains_checked": len(core), "errors": dar_identity_errors, "status": "PASS" if dar_identity_errors == 0 else "FAIL"},
        {"reconciliation": "Core/component domains complete", "domains_checked": len(core), "errors": missing_core_component_domains, "status": "PASS" if missing_core_component_domains == 0 else "FAIL"},
    ])

    add_check(checks, "Reconciliation", "core stock domains", EXPECTED_STOCK_DOMAINS, len(core), len(core) == EXPECTED_STOCK_DOMAINS)
    add_check(checks, "Reconciliation", "AVA physical+financial balance errors", 0, avapf_errors, avapf_errors == 0)
    add_check(checks, "Reconciliation", "AVA detailed-component balance errors", 0, avadetail_errors, avadetail_errors == 0)
    add_check(checks, "Reconciliation", "AOD/AODL/IOI identity errors", 0, aod_identity_errors, aod_identity_errors == 0)
    add_check(checks, "Reconciliation", "DAR/AOD/AVA identity errors", 0, dar_identity_errors, dar_identity_errors == 0)
    add_check(checks, "Reconciliation", "missing core/component domains", 0, missing_core_component_domains, missing_core_component_domains == 0)

    # Credit shares must close to 100 when the corresponding all-category marker
    # is 100, and to 0 when there is no debt in that category.
    credit_missing = 0
    inst_source_errors = 0
    non_source_errors = 0
    inst_purpose_errors = 0
    non_purpose_errors = 0
    inst_purpose_residuals = 0
    non_purpose_residuals = 0
    max_inst_purpose_residual = 0.0
    max_non_purpose_residual = 0.0

    for domain, values in credit.items():
        required = set(INSTITUTIONAL_SOURCE_DETAIL + NONINSTITUTIONAL_SOURCE_DETAIL + PURPOSE_INST_DETAIL + PURPOSE_NON_DETAIL)
        required.update({
            "CREDIT_SOURCE_ALL_INSTITUTIONAL_SOURCES",
            "CREDIT_SOURCE_ALL_NON_INSTITUTIONAL_SOURCES",
            "PURPOSE_INST_00",
            "PURPOSE_NON_00",
        })
        if not required.issubset(values):
            credit_missing += 1
            continue

        def close_distribution(all_key, detail_keys):
            marker = values[all_key]
            total = sum(values[k] for k in detail_keys)
            target = 100.0 if marker > 0.0 else 0.0
            return near(marker, target, abs_tol=1e-7, rel_tol=1e-9) and near(total, target, abs_tol=2e-6, rel_tol=1e-8)

        if not close_distribution("CREDIT_SOURCE_ALL_INSTITUTIONAL_SOURCES", INSTITUTIONAL_SOURCE_DETAIL):
            inst_source_errors += 1
        if not close_distribution("CREDIT_SOURCE_ALL_NON_INSTITUTIONAL_SOURCES", NONINSTITUTIONAL_SOURCE_DETAIL):
            non_source_errors += 1

        # Purpose detail is intentionally not renormalised. Step05 uses all
        # institutional/non-institutional debt as the denominator, while only
        # official B15_2_q11 purpose codes 1-9 are emitted as detail rows.
        # Therefore blank/unmapped source purpose creates a legitimate residual
        # below 100. Over-closure remains a fatal arithmetic error.
        def purpose_state(all_key, detail_keys):
            marker = values[all_key]
            total = sum(values[k] for k in detail_keys)
            target = 100.0 if marker > 0.0 else 0.0
            marker_ok = near(marker, target, abs_tol=1e-7, rel_tol=1e-9)
            overclosed = (not marker_ok) or (total > target + 2e-6)
            residual = max(0.0, target - total)
            return overclosed, residual

        overclosed, residual = purpose_state("PURPOSE_INST_00", PURPOSE_INST_DETAIL)
        if overclosed:
            inst_purpose_errors += 1
        if residual > 2e-6:
            inst_purpose_residuals += 1
            max_inst_purpose_residual = max(max_inst_purpose_residual, residual)

        overclosed, residual = purpose_state("PURPOSE_NON_00", PURPOSE_NON_DETAIL)
        if overclosed:
            non_purpose_errors += 1
        if residual > 2e-6:
            non_purpose_residuals += 1
            max_non_purpose_residual = max(max_non_purpose_residual, residual)

    reconciliation_rows.extend([
        {"reconciliation": "Institutional source distribution closes", "domains_checked": len(credit), "errors": inst_source_errors, "status": "PASS" if inst_source_errors == 0 else "FAIL"},
        {"reconciliation": "Non-institutional source distribution closes", "domains_checked": len(credit), "errors": non_source_errors, "status": "PASS" if non_source_errors == 0 else "FAIL"},
        {"reconciliation": "Institutional purpose distribution does not over-close", "domains_checked": len(credit), "errors": inst_purpose_errors, "status": "PASS" if inst_purpose_errors == 0 else "FAIL"},
        {"reconciliation": "Non-institutional purpose distribution does not over-close", "domains_checked": len(credit), "errors": non_purpose_errors, "status": "PASS" if non_purpose_errors == 0 else "FAIL"},
        {"reconciliation": "Institutional purpose residual domains", "domains_checked": len(credit), "errors": inst_purpose_residuals, "status": "DISCLOSURE" if inst_purpose_residuals else "PASS"},
        {"reconciliation": "Non-institutional purpose residual domains", "domains_checked": len(credit), "errors": non_purpose_residuals, "status": "DISCLOSURE" if non_purpose_residuals else "PASS"},
        {"reconciliation": "Credit domains complete", "domains_checked": len(credit), "errors": credit_missing, "status": "PASS" if credit_missing == 0 else "FAIL"},
    ])

    add_check(checks, "Reconciliation", "credit domains", EXPECTED_STOCK_DOMAINS, len(credit), len(credit) == EXPECTED_STOCK_DOMAINS)
    add_check(checks, "Reconciliation", "institutional source closure errors", 0, inst_source_errors, inst_source_errors == 0)
    add_check(checks, "Reconciliation", "non-institutional source closure errors", 0, non_source_errors, non_source_errors == 0)
    add_check(checks, "Reconciliation", "institutional purpose over-closure errors", 0, inst_purpose_errors, inst_purpose_errors == 0)
    add_check(checks, "Reconciliation", "non-institutional purpose over-closure errors", 0, non_purpose_errors, non_purpose_errors == 0)
    add_check(
        checks, "Reconciliation", "institutional purpose residual domains",
        0, inst_purpose_residuals, inst_purpose_residuals == 0,
        severity="DISCLOSURE",
        note="Residual is retained when B15_2_q11 purpose is blank/unmapped; classified shares are not renormalised.",
    )
    add_check(
        checks, "Reconciliation", "non-institutional purpose residual domains",
        0, non_purpose_residuals, non_purpose_residuals == 0,
        severity="DISCLOSURE",
        note="Residual is retained when B15_2_q11 purpose is blank/unmapped; classified shares are not renormalised.",
    )
    add_check(checks, "Reconciliation", "incomplete credit domains", 0, credit_missing, credit_missing == 0)

    purpose_residual_total = inst_purpose_residuals + non_purpose_residuals
    if purpose_residual_total:
        disclosures.append(
            f"Credit-purpose detail has source-classification residuals in {purpose_residual_total} "
            "domain/class combination(s). The denominator includes all class debt, while exported "
            "purpose detail contains only official B15_2_q11 codes 1-9. Missing/unmapped purpose "
            "is not reassigned to code 9 and the classified shares are not renormalised."
        )

    print(f"AVA physical+financial errors : {avapf_errors}")
    print(f"AVA detailed balance errors   : {avadetail_errors}")
    print(f"AOD identity errors           : {aod_identity_errors}")
    print(f"DAR identity errors           : {dar_identity_errors}")
    print(f"Credit source closure errors  : {inst_source_errors + non_source_errors}")
    print(f"Purpose over-closure errors   : {inst_purpose_errors + non_purpose_errors}")
    print(f"Purpose residual domains      : {purpose_residual_total} (DISCLOSURE)")
    print(f"Max institutional residual    : {max_inst_purpose_residual:.6f}%")
    print(f"Max non-institutional residual: {max_non_purpose_residual:.6f}%")


# =============================================================================
# FINAL OFFICIAL CONTROL RECHECK
# =============================================================================


def validate_final_official_controls(scan, checks, control_rows):
    print("\n[5] Final-output official control recheck")
    if scan is None:
        return

    values = scan["official_final_values"]

    # Unweighted household count controls.
    hh_controls = [
        ("All India", 143_285.0),
        ("Rural", 91_192.0),
        ("Urban", 52_093.0),
    ]
    for scope, expected in hh_controls:
        observed = values.get((scope, "HH_SURVEYED"))
        passed = observed is not None and near(observed, expected, abs_tol=1e-9, rel_tol=0.0)
        control_rows.append({
            "scope": scope,
            "metric": "HH_SURVEYED",
            "official_value": fmt(expected),
            "final_value": fmt(observed),
            "difference": fmt(None if observed is None else observed - expected),
            "tolerance": "exact",
            "status": "PASS" if passed else "FAIL",
        })
        add_check(checks, "Official controls", f"{scope} HH_SURVEYED", expected, observed, passed)

    for scope, metric, expected, tolerance, mode in FINAL_OFFICIAL_CONTROLS:
        observed = values.get((scope, metric))
        if observed is None:
            passed = False
            diff = None
        else:
            diff = observed - expected
            if mode == "ABS":
                passed = abs(diff) <= tolerance
            else:
                passed = abs(diff / expected) <= tolerance if expected else abs(diff) <= tolerance

        tol_text = f"+/- {tolerance}" if mode == "ABS" else f"+/- {100*tolerance:.3f}%"
        control_rows.append({
            "scope": scope,
            "metric": metric,
            "official_value": fmt(expected),
            "final_value": fmt(observed),
            "difference": fmt(diff),
            "tolerance": tol_text,
            "status": "PASS" if passed else "FAIL",
        })
        add_check(checks, "Official controls", f"{scope} {metric}", expected, observed, passed, note=tol_text)
        print(
            f"{'PASS' if passed else 'FAIL':4s} | {scope:9s} | {metric:11s} | "
            f"official={expected:>12,.3f} | final={observed if observed is not None else float('nan'):>12,.3f}"
        )


# =============================================================================
# MANIFEST / README / PACKAGE
# =============================================================================


def make_readme(root, status, readiness, disclosures, final_sha, qa_summary_path):
    final_file = root / "output" / "final" / "AIDIS_2003_All_India_States_Districts_Final.csv"
    path = root / "output" / "final" / "README_AIDIS_2003_Delivery.txt"
    lines = [
        "AIDIS 2003 - NSS 59th Round Delivery",
        "=" * 60,
        f"Step 06 status       : {status}",
        f"Delivery readiness   : {readiness}",
        f"Final data file       : {final_file.name}",
        f"Final rows            : {EXPECTED_FINAL_ROWS:,}",
        f"Final columns         : {EXPECTED_FINAL_COLUMNS}",
        f"Distinct Col_ID       : {EXPECTED_COL_IDS}",
        f"SHA256                : {final_sha}",
        "",
        "Coverage",
        "--------",
        "Core stock KPIs, AVA components and credit classifications are exported for All India, State and District domains.",
        "Asset deciles, FCE/EPL and Gini follow the Step05 aggregate scopes documented in the coverage report.",
        "",
        "Non-blocking disclosures",
        "------------------------",
    ]
    if disclosures:
        lines.extend(f"- {x}" for x in disclosures)
    else:
        lines.append("- None")
    lines += [
        "",
        "QA",
        "--",
        f"See: {relative_path(qa_summary_path, root)}",
        "See: output/reports/step06_delivery_manifest.csv",
        "See: output/reports/step05_coverage_report.csv",
        "",
        "Important 2003 classifications",
        "------------------------------",
        "- Commercial bank code 03 includes regional rural banks; no SCB/RRB split is fabricated.",
        "- Co-operative society/bank code 02 is combined in the source schedule.",
        "- Financial company code 07 is retained as labelled in the 2003 schedule.",
        "- Block14 loans receivable are assets, not payable household debt.",
        "- Part2-only Block15.2 orphan loan records remain excluded from core payable debt.",
        "- Purpose shares are not renormalised when B15_2_q11 is blank/unmapped; any residual is disclosed by Step06.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_manifest(root, manifest_path, files_to_hash):
    rows = []
    for path, role in files_to_hash:
        if path.exists() and path.is_file():
            rows.append({
                "role": role,
                "relative_path": relative_path(path, root),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    write_csv(manifest_path, ["role", "relative_path", "size_bytes", "sha256"], rows)
    return rows


def create_package(root, package_path, files_to_package):
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, arcname in files_to_package:
            if path.exists() and path.is_file():
                zf.write(path, arcname=arcname)
    return package_path


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="AIDIS 2003 Step06 final delivery QA")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="AIDIS_2003_All_India_Pipeline project root",
    )
    parser.add_argument(
        "--skip-package",
        action="store_true",
        help="Run QA but do not create the final ZIP delivery package",
    )
    parser.add_argument(
        "--strict-district-names",
        action="store_true",
        help="Fail Step06 when an authoritative survey-era District_Name is not supplied for every observed district",
    )
    parser.add_argument(
        "--strict-published-date",
        action="store_true",
        help="Fail Step06 when Published_date is blank",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cache_dir = root / "cache"
    report_dir = root / "output" / "reports"
    final_dir = root / "output" / "final"
    cache_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    checks_file = cache_dir / "step06_final_qa_checks.csv"
    family_file = cache_dir / "step06_kpi_family_counts.csv"
    col_counts_file = cache_dir / "step06_col_id_counts.csv"
    reconciliation_file = cache_dir / "step06_reconciliation_checks.csv"
    control_file = cache_dir / "step06_final_official_controls.csv"
    duplicate_file = cache_dir / "step06_duplicate_metric_keys.csv"
    invalid_file = cache_dir / "step06_invalid_row_samples.csv"
    summary_file = report_dir / "step06_final_qa_summary.txt"
    manifest_file = report_dir / "step06_delivery_manifest.csv"
    package_file = final_dir / "AIDIS_2003_Delivery_Package.zip"
    checksum_file = report_dir / "step06_package_checksum.txt"

    print("=" * 78)
    print("AIDIS 2003 - STEP 06 FINAL DELIVERY QA [V2 PURPOSE RESIDUAL QA]")
    print("Validate final client CSV + prior QA chain + reconciliations + delivery package")
    print("=" * 78)
    print(f"Project root              : {root}")

    checks = []
    disclosures = []
    invalid_samples = []
    duplicate_samples = []
    family_rows = []
    col_count_rows = []
    reconciliation_rows = []
    official_control_rows = []

    # 1. Prior QA chain.
    validate_prior_chain(root, checks)

    # 2. Step05 support material and coverage.
    catalog, catalog_rows = load_catalog(root, checks)
    district_template, supplied_district_names, district_template_count = load_district_template(root, checks)
    validate_coverage(
        root,
        checks,
        disclosures,
        strict_district_names=args.strict_district_names,
        strict_published_date=args.strict_published_date,
    )

    # 3. Final data scan.
    scan = scan_final(
        root,
        catalog,
        district_template,
        checks,
        invalid_samples,
        duplicate_samples,
        disclosures,
        strict_published_date=args.strict_published_date,
    )

    # 4. KPI family completeness and identities.
    validate_family_counts(scan, checks, family_rows, col_count_rows)
    validate_internal_reconciliations(scan, checks, reconciliation_rows, invalid_samples, disclosures)
    validate_final_official_controls(scan, checks, official_control_rows)

    # Write detailed QA tables before status resolution.
    write_csv(
        family_file,
        ["Survey_GROUP_ID", "GROUP_NAME", "expected_rows", "observed_rows", "expected_distinct_Col_ID", "observed_distinct_Col_ID", "status"],
        family_rows,
    )
    write_csv(col_counts_file, ["Survey_GROUP_ID", "Col_ID", "expected_rows", "observed_rows", "status"], col_count_rows)
    write_csv(reconciliation_file, ["reconciliation", "domains_checked", "errors", "status"], reconciliation_rows)
    write_csv(control_file, ["scope", "metric", "official_value", "final_value", "difference", "tolerance", "status"], official_control_rows)
    write_csv(
        duplicate_file,
        ["row_number", "Survey_GROUP_ID", "State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "SUB_GROUP_NAME", "Visit_ID", "Col_ID", "COL_DESC"],
        duplicate_samples,
    )
    write_csv(
        invalid_file,
        ["row_number", "issue", "Survey_GROUP_ID", "State_ID", "District_ID", "Sector_code", "SUB_GROUP_NAME", "Col_ID", "COL_DESC", "DATA"],
        invalid_samples,
    )

    # District completeness is a disclosure by default, but expose exact count.
    if district_template_count:
        add_check(
            checks,
            "Delivery metadata",
            "survey-era district names supplied",
            district_template_count,
            supplied_district_names,
            supplied_district_names == district_template_count,
            severity="FATAL" if args.strict_district_names else "DISCLOSURE",
            note="Original district codes remain preserved even when names fall back to code labels.",
        )

    # Final check table.
    write_csv(
        checks_file,
        ["section", "check", "expected", "observed", "severity", "status", "note"],
        checks,
    )

    fatal_failures = [x for x in checks if x["severity"] == "FATAL" and x["status"] == "FAIL"]
    nonblocking = [x for x in checks if x["severity"] != "FATAL" and x["status"] == "WARN"]

    step_status = "PASS" if not fatal_failures else "FAIL"
    readiness = "PASS_WITH_DISCLOSURES" if step_status == "PASS" and disclosures else ("PASS" if step_status == "PASS" else "NOT_READY")

    final_path = root / "output" / "final" / "AIDIS_2003_All_India_States_Districts_Final.csv"
    final_sha = sha256_file(final_path) if final_path.exists() else ""

    # Summary is written before manifest/package so it can itself be hashed.
    summary_lines = [
        "=" * 78,
        "AIDIS 2003 - STEP 06 FINAL DELIVERY QA SUMMARY",
        "=" * 78,
        f"Project root                   : {root}",
        f"Final CSV                      : {final_path}",
        f"Final CSV SHA256               : {final_sha}",
        f"Final rows                     : {scan['rows'] if scan else 0:,}",
        f"Final columns                  : {EXPECTED_FINAL_COLUMNS if scan else 0}",
        f"Distinct Col_ID                : {len(scan['col_groups']) if scan else 0}",
        f"Observed states/UTs            : {len(scan['state_ids']) if scan else 0}",
        f"Observed districts             : {len(scan['district_ids']) if scan else 0}",
        f"Survey-era district names      : {supplied_district_names}/{district_template_count}",
        f"Validation checks              : {len(checks)}",
        f"Fatal failed checks            : {len(fatal_failures)}",
        f"Nonblocking check disclosures  : {len(nonblocking)}",
        f"Delivery disclosures           : {len(disclosures)}",
        f"Delivery readiness             : {readiness}",
        "",
        "KPI FAMILY COUNTS:",
    ]
    for row in family_rows:
        summary_lines.append(
            f"  Group {row['Survey_GROUP_ID']} {row['GROUP_NAME']}: "
            f"rows={row['observed_rows']}/{row['expected_rows']}; "
            f"Col_ID={row['observed_distinct_Col_ID']}/{row['expected_distinct_Col_ID']}; {row['status']}"
        )

    summary_lines += ["", "DISCLOSURES:"]
    if disclosures:
        summary_lines.extend(f"  - {x}" for x in dict.fromkeys(disclosures))
    else:
        summary_lines.append("  - None")

    if fatal_failures:
        summary_lines += ["", "FATAL FAILURES:"]
        summary_lines.extend(f"  - [{x['section']}] {x['check']}: observed={x['observed']}" for x in fatal_failures[:100])

    summary_lines += [
        "",
        f"Checks CSV                     : {checks_file}",
        f"KPI family counts              : {family_file}",
        f"Col_ID counts                  : {col_counts_file}",
        f"Reconciliation checks          : {reconciliation_file}",
        f"Final official controls        : {control_file}",
        f"Duplicate metric keys          : {duplicate_file}",
        f"Invalid row samples            : {invalid_file}",
        f"Delivery manifest              : {manifest_file}",
        "",
        f"STEP 06 STATUS: {step_status}",
        "=" * 78,
    ]
    summary_file.write_text("\n".join(summary_lines), encoding="utf-8")

    readme_file = make_readme(root, step_status, readiness, list(dict.fromkeys(disclosures)), final_sha, summary_file)

    # Manifest of delivery/QA artifacts.
    manifest_inputs = [
        (final_path, "FINAL_DATA"),
        (root / "output" / "reports" / "step05_coverage_report.csv", "COVERAGE"),
        (root / "cache" / "step05_kpi_catalog.csv", "KPI_CATALOG"),
        (root / "cache" / "step05_district_lookup_template.csv", "DISTRICT_LOOKUP_TEMPLATE"),
        (root / "cache" / "step03_asset_ava_controls.csv", "ASSET_OFFICIAL_QA"),
        (root / "cache" / "step04_debt_controls.csv", "DEBT_OFFICIAL_QA"),
        (root / "cache" / "step05_flow_controls.csv", "FLOW_OFFICIAL_QA"),
        (checks_file, "STEP06_CHECKS"),
        (family_file, "STEP06_KPI_FAMILY_COUNTS"),
        (col_counts_file, "STEP06_COL_ID_COUNTS"),
        (reconciliation_file, "STEP06_RECONCILIATION"),
        (control_file, "STEP06_FINAL_CONTROLS"),
        (summary_file, "STEP06_SUMMARY"),
        (readme_file, "DELIVERY_README"),
    ]
    manifest_rows = write_manifest(root, manifest_file, manifest_inputs)

    package_sha = ""
    if not args.skip_package and step_status == "PASS":
        package_inputs = [
            (final_path, "data/AIDIS_2003_All_India_States_Districts_Final.csv"),
            (readme_file, "README_AIDIS_2003_Delivery.txt"),
            (manifest_file, "qa/step06_delivery_manifest.csv"),
            (summary_file, "qa/step06_final_qa_summary.txt"),
            (checks_file, "qa/step06_final_qa_checks.csv"),
            (family_file, "qa/step06_kpi_family_counts.csv"),
            (col_counts_file, "qa/step06_col_id_counts.csv"),
            (reconciliation_file, "qa/step06_reconciliation_checks.csv"),
            (control_file, "qa/step06_final_official_controls.csv"),
            (root / "output" / "reports" / "step05_coverage_report.csv", "qa/step05_coverage_report.csv"),
            (root / "cache" / "step05_kpi_catalog.csv", "qa/step05_kpi_catalog.csv"),
            (root / "cache" / "step05_district_lookup_template.csv", "qa/step05_district_lookup_template.csv"),
        ]
        create_package(root, package_file, package_inputs)
        package_sha = sha256_file(package_file)
        checksum_file.write_text(
            f"SHA256  {package_sha}  {package_file.name}\n",
            encoding="utf-8",
        )

    print("\n" + "=" * 78)
    print("AIDIS 2003 - STEP 06 SUMMARY")
    print("=" * 78)
    print(f"Final rows                 : {scan['rows'] if scan else 0:,}")
    print(f"Final columns              : {EXPECTED_FINAL_COLUMNS if scan else 0}")
    print(f"Distinct Col_ID            : {len(scan['col_groups']) if scan else 0}")
    print(f"States/UTs                 : {len(scan['state_ids']) if scan else 0}")
    print(f"Observed districts         : {len(scan['district_ids']) if scan else 0}")
    print(f"District names supplied    : {supplied_district_names}/{district_template_count}")
    print(f"Validation checks          : {len(checks)}")
    print(f"Fatal failed checks        : {len(fatal_failures)}")
    print(f"Delivery disclosures       : {len(disclosures)}")
    print(f"Delivery readiness         : {readiness}")
    print(f"Final CSV SHA256           : {final_sha}")
    print(f"QA summary                 : {summary_file}")
    print(f"Delivery manifest          : {manifest_file}")
    if not args.skip_package and step_status == "PASS":
        print(f"Delivery package           : {package_file}")
        print(f"Package SHA256             : {package_sha}")
    elif args.skip_package:
        print("Delivery package           : SKIPPED (--skip-package)")
    else:
        print("Delivery package           : NOT CREATED (Step06 failed)")
    print()
    print(f"STEP 06 STATUS: {step_status}")
    print("=" * 78)

    return 0 if step_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())