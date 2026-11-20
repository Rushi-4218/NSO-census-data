from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Tuple


# =============================================================================
# AIDIS 2013 - STEP 02
# CANONICAL VISIT-1 HOUSEHOLD STOCK LAYER
#
# NSS 70th Round - Schedule 18.2
#
# PURPOSE
# -------
# Consume the Step-01 / Step-01B / Step-01C locks and construct exactly one
# Visit-1 record per household containing:
#
#   - survey geography and Visit-1 final combined weight
#   - household classification fields
#   - 9 locked asset components as on 30-06-2012
#   - total household assets
#   - cash debt outstanding as on 30-06-2012
#   - institutional / non-institutional debt
#   - indebtedness flags
#
# IMPORTANT
# ---------
# 1. One-to-many raw records are aggregated to HHID BEFORE weighting.
# 2. Asset blocks contain explicit household total rows. Step 02 uses those
#    total rows and never adds detail rows to the total row.
# 3. Land is the sum of Block 5.1 and Block 5.2 household totals. The blocks
#    describe land types; they are not filtered by household residence sector.
# 4. Visit-1 Block 10 (non-farm business equipment) is retained as a locked
#    component. In the released source used by this project, b10_q3 is blank/
#    zero for the total rows; this is disclosed, never imputed.
# 5. Official rural/urban controls are hard validation checks. Occupational
#    subgroup controls are diagnostic in Step 02 because subgroup reconciliation
#    is intentionally investigated separately before later publication stages.
# 6. Block 16/FCE is NOT built here. It belongs to Step 03.
# =============================================================================


SCRIPT_REVISION = "R2-NEGATIVE-ASSET-WARNING-2026-08-27"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_DIR = PROJECT_ROOT / "input"
RAW_V1_ROOT = INPUT_DIR / "raw" / "visit1"
CACHE_DIR = PROJECT_ROOT / "cache"
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DATA_DIR = PROJECT_ROOT / "output" / "data"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"

for folder in [CACHE_DIR, CONFIG_DIR, OUTPUT_DATA_DIR, REPORT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


# =============================================================================
# UPSTREAM LOCKS
# =============================================================================

STEP01_SUMMARY = REPORT_DIR / "step01_production_lock_summary.txt"
STEP01B_SUMMARY = REPORT_DIR / "step01b_variable_mapping_summary.txt"
STEP01C_SUMMARY = REPORT_DIR / "step01c_methodology_lock_summary.txt"
STEP01_HOUSEHOLD_UNIVERSE = CACHE_DIR / "step01_household_universe.csv"
METHODOLOGY_JSON = CONFIG_DIR / "aidis_2013_methodology_lock.json"
OFFICIAL_CONTROLS_FILE = CONFIG_DIR / "aidis_2013_official_controls.csv"
AGENCY_CODEBOOK_FILE = CONFIG_DIR / "aidis_2013_credit_agency_codebook.csv"


# =============================================================================
# STEP 02 OUTPUTS
# =============================================================================

HOUSEHOLD_STOCK_FILE = OUTPUT_DATA_DIR / "aidis_2013_household_stock.csv"
CHECKS_FILE = CACHE_DIR / "step02_household_stock_checks.csv"
CONTROL_VALIDATION_FILE = CACHE_DIR / "step02_official_control_validation.csv"
ASSET_SUMMARY_FILE = CACHE_DIR / "step02_asset_component_summary.csv"
STEP02_LOCK_FILE = CONFIG_DIR / "aidis_2013_step02_lock.json"
SUMMARY_FILE = REPORT_DIR / "step02_household_stock_summary.txt"


EXPECTED_VISIT1_HOUSEHOLDS = 110800


# =============================================================================
# VERIFIED RAW FILES + TOTAL-ROW IMPLEMENTATION
# =============================================================================

RAW_FILES = {
    "identification": "Visit 1_Block 12_Identification of sample household and particulars of field operations.xlsx",
    "household_characteristics": "Visit 1_Block 3_Household Characteristics.xlsx",
    "land_51": "Visit 1_Block 5pt1_Details of land owned by the household as on 30_06_12.xlsx",
    "land_52": "Visit 1_Block 5pt2_Details of land owned by the household as on 30_06_12.xlsx",
    "buildings": "Visit 1_Block 6_Buildings and other constructions owned by the household as on 30_06_2012.xlsx",
    "livestock": "Visit 1_Block 7_Livestock and poultry owned by the household on 30_06_2012.xlsx",
    "transport": "Visit 1_Block 8_Transport equipment owned by the household on 30_06_2012.xlsx",
    "agricultural_machinery": "Visit 1_Block 9_Agricultural machinery and implements owned by the household on 30_06_2012.xlsx",
    "nonfarm_equipment": "Visit 1_Block 10_Non-farm business equipment owned by the household as on 30_06_2012.xlsx",
    "shares": "Visit 1_Block 11_.xlsx",
    "financial_assets": "Visit 1_Block 12.xlsx",
    "receivable": "Visit 1_Block 13.xlsx",
    "debt": "Visit 1_Block 14.xlsx",
}

# source_key -> (item variable, total-row code, value variable, output column)
ASSET_TOTAL_ROWS = {
    "land_51": ("b5_1_1", "99", "b5_1_6", "land_rural_type_value"),
    "land_52": ("b5_2_1", "99", "b5_2_6", "land_urban_type_value"),
    "buildings": ("b6_q3", "11", "b6_q6", "building_value"),
    "livestock": ("b7_q2", "22", "b7_q5", "livestock_value"),
    "transport": ("b8_q2", "8", "b8_q5", "transport_value"),
    "agricultural_machinery": ("b9_q2", "8", "b9_q4", "agricultural_machinery_value"),
    "nonfarm_equipment": ("b10_q2", "15", "b10_q3", "nonfarm_equipment_value"),
    "shares": ("b11_q1", "5", "b11_q6", "shares_debentures_value"),
    "financial_assets": ("b12_q1", "11", "b12_q3", "financial_assets_value"),
    "receivable": ("b13_q2", "7", "b13_q4", "receivable_value"),
}


# =============================================================================
# STATE
# =============================================================================

errors: List[str] = []
warnings: List[str] = []
disclosures: List[str] = []
checks: List[dict] = []


# =============================================================================
# BASIC HELPERS
# =============================================================================

def clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"[-+]?\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def numeric(value, default: float = 0.0) -> float:
    text = clean(value).replace(",", "")
    if text == "":
        return default
    try:
        result = float(text)
    except ValueError:
        return default
    if not math.isfinite(result):
        return default
    return result


def normalized_code(value) -> str:
    text = clean(value)
    if text == "":
        return ""
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return text.lstrip("0") or "0"


def agency_code(value) -> str:
    code = normalized_code(value)
    if code == "":
        return ""
    if code.isdigit():
        return code.zfill(2)
    return code


def display_number(value: float, digits: int = 6) -> str:
    if abs(value) < 0.5 * 10 ** (-digits):
        value = 0.0
    rounded = round(value, digits)
    if float(rounded).is_integer():
        return str(int(rounded))
    return f"{rounded:.{digits}f}".rstrip("0").rstrip(".")


def read_csv(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: Iterable[dict], fieldnames: List[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)


def add_check(
    check_id: str,
    check_name: str,
    expected,
    actual,
    passed: bool,
    severity: str = "ERROR",
    note: str = "",
) -> None:
    status = "PASS" if passed else ("WARN" if severity == "WARNING" else "FAIL")
    row = {
        "check_id": check_id,
        "check_name": check_name,
        "expected": clean(expected),
        "actual": clean(actual),
        "status": status,
        "severity": severity,
        "note": note,
    }
    checks.append(row)
    if not passed:
        message = f"{check_id}: {check_name} | expected={expected} actual={actual}"
        if severity == "ERROR":
            errors.append(message)
        else:
            warnings.append(message)


def require_file(path: Path, label: str) -> None:
    add_check(
        f"UPSTREAM_{label}",
        f"Required upstream file exists: {path.name}",
        "exists",
        "exists" if path.is_file() else "missing",
        path.is_file(),
    )


def find_raw_file(expected_name: str) -> Path:
    matches = [p for p in RAW_V1_ROOT.rglob(expected_name) if p.is_file()]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one Visit-1 raw file named {expected_name!r}; found {len(matches)}"
        )
    return matches[0]


# =============================================================================
# ROBUST XLSX STREAMING READER
# =============================================================================

# These files are the same NSS XLSX inputs already audited by Step 01. Some have
# broken worksheet dimensions, so reset_dimensions() is mandatory in read-only
# mode. This deliberately follows the Step-01 v2 reader behavior.


def xlsx_dict_rows(path: Path, required_columns: List[str]) -> Iterator[Dict[str, object]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required. Install it with: pip install openpyxl") from exc

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    selected_sheet = None
    header = None
    indexes = None

    try:
        for sheet_name in workbook.sheetnames:
            ws = workbook[sheet_name]
            try:
                ws.reset_dimensions()
            except Exception:
                pass

            for values in ws.iter_rows(values_only=True):
                row_values = list(values)
                cleaned = [clean(v) for v in row_values]
                if "HHID" not in cleaned:
                    continue

                missing = [column for column in required_columns if column not in cleaned]
                if missing:
                    continue

                selected_sheet = ws
                header = cleaned
                indexes = {column: header.index(column) for column in required_columns}
                break

            if selected_sheet is not None:
                break

        if selected_sheet is None or indexes is None:
            raise RuntimeError(
                f"Could not find a worksheet containing required columns in {path.name}: "
                + ", ".join(required_columns)
            )

        # Restart the selected worksheet because the first scan consumed rows.
        try:
            selected_sheet.reset_dimensions()
        except Exception:
            pass

        header_seen = False
        for values in selected_sheet.iter_rows(values_only=True):
            row_values = list(values)
            cleaned = [clean(v) for v in row_values]

            if not header_seen:
                if "HHID" in cleaned and all(c in cleaned for c in required_columns):
                    header_seen = True
                continue

            if not any(cleaned):
                continue

            yield {
                column: (row_values[indexes[column]] if indexes[column] < len(row_values) else None)
                for column in required_columns
            }

    finally:
        workbook.close()


# =============================================================================
# UPSTREAM VALIDATION
# =============================================================================


def validate_upstream() -> dict:
    print("\n[1] Validating upstream locks")

    for path, label in [
        (STEP01_SUMMARY, "STEP01_SUMMARY"),
        (STEP01B_SUMMARY, "STEP01B_SUMMARY"),
        (STEP01C_SUMMARY, "STEP01C_SUMMARY"),
        (STEP01_HOUSEHOLD_UNIVERSE, "STEP01_HOUSEHOLDS"),
        (METHODOLOGY_JSON, "METHODOLOGY_JSON"),
        (OFFICIAL_CONTROLS_FILE, "OFFICIAL_CONTROLS"),
        (AGENCY_CODEBOOK_FILE, "AGENCY_CODEBOOK"),
    ]:
        require_file(path, label)

    if errors:
        return {}

    with METHODOLOGY_JSON.open("r", encoding="utf-8") as fh:
        methodology = json.load(fh)

    expected = methodology.get("survey", {}).get("visit1_sample_households")
    add_check(
        "LOCK_V1_HOUSEHOLDS",
        "Step 01C Visit-1 household count",
        EXPECTED_VISIT1_HOUSEHOLDS,
        expected,
        int(expected or -1) == EXPECTED_VISIT1_HOUSEHOLDS,
    )

    debt = methodology.get("debt", {})
    add_check(
        "LOCK_DEBT_FIELD",
        "Locked debt outstanding variable",
        "b14_q17",
        debt.get("outstanding_variable", ""),
        debt.get("outstanding_variable") == "b14_q17",
    )

    weighting = methodology.get("weighting", {}).get("stock_visit1", {})
    add_check(
        "LOCK_STOCK_WEIGHT",
        "Locked stock weight",
        "Weight_SC",
        weighting.get("weight_variable", ""),
        weighting.get("weight_variable") == "Weight_SC",
    )

    return methodology


# =============================================================================
# HOUSEHOLD BACKBONE
# =============================================================================


def build_household_backbone(path: Path) -> Tuple[Dict[str, dict], List[str]]:
    print("\n[2] Building Visit-1 household backbone")

    columns = [
        "HHID",
        "Sector",
        "State",
        "District_id",
        "State_District",
        "Visit_no",
        "Weight_SC",
    ]

    households: Dict[str, dict] = {}
    order: List[str] = []
    duplicates = 0
    invalid_weight = 0
    invalid_visit = 0

    for row in xlsx_dict_rows(path, columns):
        hhid = clean(row["HHID"])
        if not hhid:
            continue
        if hhid in households:
            duplicates += 1
            continue

        weight = numeric(row["Weight_SC"], default=float("nan"))
        if not math.isfinite(weight) or weight <= 0:
            invalid_weight += 1
            weight = 0.0

        visit = normalized_code(row["Visit_no"])
        if visit != "1":
            invalid_visit += 1

        households[hhid] = {
            "HHID": hhid,
            "Sector": normalized_code(row["Sector"]),
            "State": clean(row["State"]),
            "District_id": clean(row["District_id"]),
            "State_District": clean(row["State_District"]),
            "Visit_no": visit,
            "Weight_SC": weight,
            "HH_type_raw": "",
            "HH_type_normalized": "",
            "b3q4_land_operated_yn": "",
            "b3q5_land_operated_area_ha": 0.0,
            "bank_account": "",
            "post_office_account": "",
            "household_group": "",
        }
        order.append(hhid)

    add_check(
        "HH_COUNT",
        "Canonical Visit-1 household count",
        EXPECTED_VISIT1_HOUSEHOLDS,
        len(households),
        len(households) == EXPECTED_VISIT1_HOUSEHOLDS,
    )
    add_check("HH_DUPLICATES", "Duplicate HHID in household backbone", 0, duplicates, duplicates == 0)
    add_check("HH_INVALID_WEIGHT", "Invalid/non-positive Visit-1 Weight_SC", 0, invalid_weight, invalid_weight == 0)
    add_check("HH_INVALID_VISIT", "Identification rows with Visit_no != 1", 0, invalid_visit, invalid_visit == 0)

    print(f"  Households                 : {len(households):,}")
    print(f"  Duplicate HHIDs            : {duplicates:,}")
    print(f"  Invalid weights            : {invalid_weight:,}")

    return households, order


# =============================================================================
# HOUSEHOLD CHARACTERISTICS / CLASSIFICATION
# =============================================================================


def normalize_urban_hh_type(raw_value) -> str:
    code = normalized_code(raw_value)
    # Released Visit-1 data encode sector into HH_type (21/22/23/29 for urban).
    if len(code) >= 2 and code.startswith("2") and code[-1] in {"1", "2", "3", "9"}:
        return code[-1]
    return code


def attach_household_characteristics(path: Path, households: Dict[str, dict]) -> None:
    print("\n[3] Attaching household characteristics")

    columns = ["HHID", "HH_type", "b3q4", "b3q5", "b3q8", "b3q10"]
    seen = set()
    duplicate = 0
    unknown_hhid = 0
    invalid_urban_type = 0

    for row in xlsx_dict_rows(path, columns):
        hhid = clean(row["HHID"])
        if not hhid:
            continue
        if hhid in seen:
            duplicate += 1
            continue
        seen.add(hhid)

        hh = households.get(hhid)
        if hh is None:
            unknown_hhid += 1
            continue

        raw_type = normalized_code(row["HH_type"])
        normalized_type = normalize_urban_hh_type(row["HH_type"])
        operated_area = numeric(row["b3q5"], 0.0)

        if hh["Sector"] == "1":
            group = "Cultivator" if operated_area >= 0.002 else "Non-cultivator"
        elif hh["Sector"] == "2":
            if normalized_type == "1":
                group = "Self-employed"
            elif normalized_type in {"2", "3", "9"}:
                group = "Others"
            else:
                group = "Unclassified"
                invalid_urban_type += 1
        else:
            group = "Unclassified"

        hh.update(
            {
                "HH_type_raw": raw_type,
                "HH_type_normalized": normalized_type,
                "b3q4_land_operated_yn": normalized_code(row["b3q4"]),
                "b3q5_land_operated_area_ha": operated_area,
                "bank_account": normalized_code(row["b3q8"]),
                "post_office_account": normalized_code(row["b3q10"]),
                "household_group": group,
            }
        )

    missing = len(set(households) - seen)

    add_check("HHCHAR_DUPLICATES", "Duplicate HHID in Block 3", 0, duplicate, duplicate == 0)
    add_check("HHCHAR_UNKNOWN_HHID", "Block-3 HHID outside backbone", 0, unknown_hhid, unknown_hhid == 0)
    add_check("HHCHAR_MISSING", "Backbone HHID missing from Block 3", 0, missing, missing == 0)
    add_check(
        "HHCHAR_URBAN_TYPE",
        "Urban households with unclassified HH_type",
        0,
        invalid_urban_type,
        invalid_urban_type == 0,
        severity="WARNING",
        note="Urban HH_type 21/22/23/29 is normalized to 1/2/3/9.",
    )

    print(f"  Block-3 matched households : {len(seen):,}")
    print(f"  Missing Block-3 households : {missing:,}")
    print(f"  Unclassified urban HH type : {invalid_urban_type:,}")


# =============================================================================
# ASSET EXTRACTION
# =============================================================================


def extract_asset_total(
    path: Path,
    item_variable: str,
    total_code: str,
    value_variable: str,
    households: Dict[str, dict],
) -> Tuple[Dict[str, float], dict]:
    values: Dict[str, float] = {}
    selected_rows = 0
    duplicate_total_rows = 0
    unknown_hhid = 0
    blank_selected_values = 0
    negative_values = 0
    negative_raw_sum = 0.0
    negative_raw_min = None
    negative_example_hhids: List[str] = []
    nonzero_values = 0

    wanted = normalized_code(total_code)

    for row in xlsx_dict_rows(path, ["HHID", item_variable, value_variable]):
        if normalized_code(row[item_variable]) != wanted:
            continue

        selected_rows += 1
        hhid = clean(row["HHID"])
        if hhid not in households:
            unknown_hhid += 1
            continue
        if hhid in values:
            duplicate_total_rows += 1
            continue

        raw_value = clean(row[value_variable])
        if raw_value == "":
            blank_selected_values += 1
        amount = numeric(raw_value, 0.0)
        if amount < 0:
            # Asset-stock valuation fields cannot represent a negative asset value.
            # Preserve the anomaly in the audit, but use 0 in the canonical stock
            # layer rather than allowing a source error/sentinel to reduce assets.
            negative_values += 1
            negative_raw_sum += amount
            negative_raw_min = amount if negative_raw_min is None else min(negative_raw_min, amount)
            if len(negative_example_hhids) < 10:
                negative_example_hhids.append(hhid)
            amount = 0.0
        if amount != 0:
            nonzero_values += 1
        values[hhid] = amount

    summary = {
        "source_file": path.name,
        "item_variable": item_variable,
        "total_code": total_code,
        "value_variable": value_variable,
        "selected_total_rows": selected_rows,
        "households_with_total_row": len(values),
        "duplicate_total_rows": duplicate_total_rows,
        "unknown_hhid": unknown_hhid,
        "blank_selected_values": blank_selected_values,
        "nonzero_selected_values": nonzero_values,
        "negative_selected_values": negative_values,
        "negative_raw_sum": negative_raw_sum,
        "negative_raw_min": "" if negative_raw_min is None else negative_raw_min,
        "negative_example_hhids": ";".join(negative_example_hhids),
        "negative_values_cleaned_to_zero": negative_values,
        "unweighted_total_value": sum(values.values()),
    }
    return values, summary


def build_assets(raw_paths: Dict[str, Path], households: Dict[str, dict]) -> List[dict]:
    print("\n[4] Building household asset components")

    summaries: List[dict] = []
    extracted: Dict[str, Dict[str, float]] = {}

    for source_key, (item_var, total_code, value_var, output_col) in ASSET_TOTAL_ROWS.items():
        values, summary = extract_asset_total(
            raw_paths[source_key], item_var, total_code, value_var, households
        )
        extracted[output_col] = values
        summary["component_key"] = output_col
        summaries.append(summary)

        add_check(
            f"ASSET_{source_key.upper()}_DUP_TOTAL",
            f"Duplicate household total rows: {source_key}",
            0,
            summary["duplicate_total_rows"],
            summary["duplicate_total_rows"] == 0,
        )
        add_check(
            f"ASSET_{source_key.upper()}_UNKNOWN_HH",
            f"Asset total rows outside Visit-1 universe: {source_key}",
            0,
            summary["unknown_hhid"],
            summary["unknown_hhid"] == 0,
        )
        add_check(
            f"ASSET_{source_key.upper()}_NEGATIVE",
            f"Negative selected asset totals: {source_key}",
            0,
            summary["negative_selected_values"],
            summary["negative_selected_values"] == 0,
            severity="WARNING",
            note="Negative source asset values are invalid for stock valuation; retained in audit and cleaned to 0 in the canonical household layer.",
        )
        if summary["negative_selected_values"]:
            disclosures.append(
                f"{source_key}: {summary['negative_selected_values']} negative selected asset total(s) "
                f"were found in the released source and cleaned to 0 in the canonical stock layer; "
                f"raw sum={summary['negative_raw_sum']:.3f}, minimum={summary['negative_raw_min']}."
            )

        print(
            f"  {output_col:32s} | total rows={summary['selected_total_rows']:>7,} "
            f"| nonzero={summary['nonzero_selected_values']:>7,}"
        )

    # Explicit source disclosure for the released Block-10 value-column issue.
    nf = next(row for row in summaries if row["component_key"] == "nonfarm_equipment_value")
    if nf["nonzero_selected_values"] == 0:
        disclosures.append(
            "Visit-1 Block 10 b10_q3 has no non-zero household total values in the released source; "
            "non-farm equipment is retained as a component with value 0 and is not imputed."
        )

    for hhid, hh in households.items():
        for output_col, value_map in extracted.items():
            hh[output_col] = value_map.get(hhid, 0.0)

        hh["land_value"] = hh["land_rural_type_value"] + hh["land_urban_type_value"]
        hh["total_assets"] = (
            hh["land_value"]
            + hh["building_value"]
            + hh["livestock_value"]
            + hh["agricultural_machinery_value"]
            + hh["nonfarm_equipment_value"]
            + hh["transport_value"]
            + hh["shares_debentures_value"]
            + hh["financial_assets_value"]
            + hh["receivable_value"]
        )

    negative_total_assets = sum(1 for hh in households.values() if hh["total_assets"] < 0)
    add_check(
        "ASSET_TOTAL_NEGATIVE",
        "Households with negative total assets",
        0,
        negative_total_assets,
        negative_total_assets == 0,
    )

    return summaries


# =============================================================================
# DEBT EXTRACTION
# =============================================================================


def load_agency_classes() -> Tuple[set, set]:
    institutional = set()
    noninstitutional = set()

    for row in read_csv(AGENCY_CODEBOOK_FILE):
        code = agency_code(row.get("code"))
        cls = clean(row.get("agency_class"))
        if cls == "Institutional":
            institutional.add(code)
        elif cls == "Non-institutional":
            noninstitutional.add(code)

    add_check(
        "DEBT_AGENCY_OVERLAP",
        "Institutional/non-institutional agency code overlap",
        0,
        len(institutional & noninstitutional),
        not (institutional & noninstitutional),
    )
    return institutional, noninstitutional


def build_debt(path: Path, households: Dict[str, dict]) -> dict:
    print("\n[5] Building household debt stock")

    institutional_codes, noninstitutional_codes = load_agency_classes()

    total = defaultdict(float)
    institutional = defaultdict(float)
    noninstitutional = defaultdict(float)
    unknown = defaultdict(float)
    loan_count = defaultdict(int)

    explicit_total_rows = 0
    detail_rows = 0
    positive_detail_rows = 0
    unknown_hhid = 0
    negative_amount_rows = 0
    positive_unknown_agency_rows = 0

    columns = ["HHID", "b14_q1", "b14_q6", "b14_q17"]

    for row in xlsx_dict_rows(path, columns):
        serial = normalized_code(row["b14_q1"])
        if serial == "99":
            explicit_total_rows += 1
            continue

        detail_rows += 1
        hhid = clean(row["HHID"])
        if hhid not in households:
            unknown_hhid += 1
            continue

        amount = numeric(row["b14_q17"], 0.0)
        if amount < 0:
            negative_amount_rows += 1

        # Official 30-06-2012 debt stock is positive outstanding cash debt.
        if amount <= 0:
            continue

        positive_detail_rows += 1
        total[hhid] += amount
        loan_count[hhid] += 1

        code = agency_code(row["b14_q6"])
        if code in institutional_codes:
            institutional[hhid] += amount
        elif code in noninstitutional_codes:
            noninstitutional[hhid] += amount
        else:
            unknown[hhid] += amount
            positive_unknown_agency_rows += 1

    for hhid, hh in households.items():
        hh["debt_outstanding"] = total.get(hhid, 0.0)
        hh["institutional_debt"] = institutional.get(hhid, 0.0)
        hh["noninstitutional_debt"] = noninstitutional.get(hhid, 0.0)
        hh["unknown_agency_debt"] = unknown.get(hhid, 0.0)
        hh["positive_cash_loan_count"] = loan_count.get(hhid, 0)
        hh["is_indebted"] = 1 if hh["debt_outstanding"] > 0 else 0
        hh["has_institutional_debt"] = 1 if hh["institutional_debt"] > 0 else 0
        hh["has_noninstitutional_debt"] = 1 if hh["noninstitutional_debt"] > 0 else 0

    reconciliation_fail = sum(
        1
        for hh in households.values()
        if abs(
            hh["debt_outstanding"]
            - hh["institutional_debt"]
            - hh["noninstitutional_debt"]
            - hh["unknown_agency_debt"]
        ) > 0.01
    )

    add_check("DEBT_UNKNOWN_HH", "Debt records outside Visit-1 universe", 0, unknown_hhid, unknown_hhid == 0)
    add_check("DEBT_NEGATIVE_ROWS", "Negative b14_q17 detail values", 0, negative_amount_rows, negative_amount_rows == 0)
    add_check(
        "DEBT_UNKNOWN_AGENCY",
        "Positive debt rows with unclassified credit agency",
        0,
        positive_unknown_agency_rows,
        positive_unknown_agency_rows == 0,
    )
    add_check(
        "DEBT_RECONCILIATION",
        "HH debt = institutional + non-institutional + unknown",
        0,
        reconciliation_fail,
        reconciliation_fail == 0,
    )

    print(f"  Detail loan rows            : {detail_rows:,}")
    print(f"  Positive stock loan rows    : {positive_detail_rows:,}")
    print(f"  Explicit total rows skipped : {explicit_total_rows:,}")
    print(f"  Unknown-agency positive rows: {positive_unknown_agency_rows:,}")

    return {
        "detail_rows": detail_rows,
        "positive_detail_rows": positive_detail_rows,
        "explicit_total_rows_skipped": explicit_total_rows,
        "positive_unknown_agency_rows": positive_unknown_agency_rows,
    }


# =============================================================================
# WEIGHTED ESTIMATION + OFFICIAL CONTROLS
# =============================================================================


def weighted_metrics(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    denominator = sum(hh["Weight_SC"] for hh in rows)
    if denominator <= 0:
        return {
            "AVA": float("nan"),
            "IOI": float("nan"),
            "AOD": float("nan"),
            "AODL": float("nan"),
            "Institutional IOI": float("nan"),
            "Non-institutional IOI": float("nan"),
            "sample_households": len(rows),
            "weight_sum": denominator,
        }

    asset_numerator = sum(hh["Weight_SC"] * hh["total_assets"] for hh in rows)
    debt_numerator = sum(hh["Weight_SC"] * hh["debt_outstanding"] for hh in rows)
    indebted_weight = sum(hh["Weight_SC"] * hh["is_indebted"] for hh in rows)
    inst_weight = sum(hh["Weight_SC"] * hh["has_institutional_debt"] for hh in rows)
    noninst_weight = sum(hh["Weight_SC"] * hh["has_noninstitutional_debt"] for hh in rows)

    return {
        "AVA": asset_numerator / denominator,
        "IOI": 100.0 * indebted_weight / denominator,
        "AOD": debt_numerator / denominator,
        "AODL": debt_numerator / indebted_weight if indebted_weight > 0 else float("nan"),
        "Institutional IOI": 100.0 * inst_weight / denominator,
        "Non-institutional IOI": 100.0 * noninst_weight / denominator,
        "sample_households": len(rows),
        "weight_sum": denominator,
    }


def group_rows(households: Dict[str, dict], sector: str, household_group: str) -> List[dict]:
    sector_code = {"Rural": "1", "Urban": "2"}.get(sector)
    result = []
    for hh in households.values():
        if sector_code and hh["Sector"] != sector_code:
            continue
        if household_group != "All" and hh["household_group"] != household_group:
            continue
        result.append(hh)
    return result


def parse_tolerance(text: str, published: float) -> Tuple[str, float]:
    value = clean(text).lower()
    if value == "exact":
        return "absolute", 0.0
    m = re.match(r"([0-9.]+)%$", value)
    if m:
        return "absolute", abs(published) * float(m.group(1)) / 100.0
    m = re.match(r"([0-9.]+)\s*percentage point", value)
    if m:
        return "absolute", float(m.group(1))
    raise ValueError(f"Unsupported control tolerance: {text!r}")


def validate_official_controls(households: Dict[str, dict]) -> List[dict]:
    print("\n[6] Validating official stock/debt controls")

    computed: Dict[Tuple[str, str, str, str], float] = {}
    metric_cache: Dict[Tuple[str, str], dict] = {}

    for sector, group in [
        ("Rural", "All"),
        ("Rural", "Cultivator"),
        ("Rural", "Non-cultivator"),
        ("Urban", "All"),
        ("Urban", "Self-employed"),
        ("Urban", "Others"),
    ]:
        metrics = weighted_metrics(group_rows(households, sector, group))
        metric_cache[(sector, group)] = metrics
        for metric in ["AVA", "IOI", "AOD", "AODL", "Institutional IOI", "Non-institutional IOI"]:
            family = (
                "Assets"
                if metric == "AVA"
                else "Debt Source"
                if metric in {"Institutional IOI", "Non-institutional IOI"}
                else "Debt"
            )
            computed[(family, sector, group, metric)] = metrics[metric]

    validation_rows: List[dict] = []
    hard_failures = 0

    for control in read_csv(OFFICIAL_CONTROLS_FILE):
        family = clean(control.get("family"))
        sector = clean(control.get("sector"))
        group = clean(control.get("household_group"))
        metric = clean(control.get("metric"))

        if family not in {"Assets", "Debt", "Debt Source"}:
            continue
        if sector not in {"Rural", "Urban"}:
            continue

        key = (family, sector, group, metric)
        if key not in computed:
            continue

        published = numeric(control.get("published_value"), float("nan"))
        actual = computed[key]
        _, allowed = parse_tolerance(clean(control.get("tolerance")), published)
        difference = actual - published
        passed = math.isfinite(actual) and abs(difference) <= allowed + 1e-12

        # Step-02 hard controls are sector totals. Occupational groups remain
        # diagnostic until their released-microdata classification discrepancy
        # is resolved and explicitly locked in a later methodology revision.
        hard = group == "All"
        if hard and not passed:
            hard_failures += 1

        status = (
            "PASS" if hard and passed else
            "FAIL" if hard and not passed else
            "DIAGNOSTIC_PASS" if passed else
            "DIAGNOSTIC_DIFF"
        )

        validation_rows.append(
            {
                "control_id": clean(control.get("control_id")),
                "family": family,
                "sector": sector,
                "household_group": group,
                "metric": metric,
                "published_value": display_number(published),
                "computed_value": display_number(actual),
                "difference": display_number(difference),
                "absolute_tolerance": display_number(allowed),
                "source_tolerance": clean(control.get("tolerance")),
                "validation_mode": "HARD" if hard else "DIAGNOSTIC",
                "status": status,
            }
        )

    add_check(
        "OFFICIAL_HARD_CONTROLS",
        "Failed hard rural/urban official controls",
        0,
        hard_failures,
        hard_failures == 0,
    )

    diagnostic_diffs = sum(1 for r in validation_rows if r["status"] == "DIAGNOSTIC_DIFF")
    if diagnostic_diffs:
        disclosures.append(
            f"{diagnostic_diffs} occupational subgroup official controls differ from the released microdata "
            "under the Step-01C documented classification; Step 02 records them as diagnostic, not fatal."
        )

    # Compact console output for the hard controls.
    for row in validation_rows:
        if row["validation_mode"] == "HARD":
            print(
                f"  {row['control_id']:26s} | computed={float(row['computed_value']):>12,.3f} "
                f"| published={float(row['published_value']):>12,.3f} | {row['status']}"
            )

    return validation_rows


# =============================================================================
# OUTPUT WRITERS
# =============================================================================

HOUSEHOLD_COLUMNS = [
    "HHID",
    "Sector",
    "State",
    "District_id",
    "State_District",
    "Visit_no",
    "Weight_SC",
    "HH_type_raw",
    "HH_type_normalized",
    "b3q4_land_operated_yn",
    "b3q5_land_operated_area_ha",
    "bank_account",
    "post_office_account",
    "household_group",
    "land_rural_type_value",
    "land_urban_type_value",
    "land_value",
    "building_value",
    "livestock_value",
    "agricultural_machinery_value",
    "nonfarm_equipment_value",
    "transport_value",
    "shares_debentures_value",
    "financial_assets_value",
    "receivable_value",
    "total_assets",
    "positive_cash_loan_count",
    "debt_outstanding",
    "institutional_debt",
    "noninstitutional_debt",
    "unknown_agency_debt",
    "is_indebted",
    "has_institutional_debt",
    "has_noninstitutional_debt",
]

NUMERIC_OUTPUT_COLUMNS = {
    "Weight_SC",
    "b3q5_land_operated_area_ha",
    "land_rural_type_value",
    "land_urban_type_value",
    "land_value",
    "building_value",
    "livestock_value",
    "agricultural_machinery_value",
    "nonfarm_equipment_value",
    "transport_value",
    "shares_debentures_value",
    "financial_assets_value",
    "receivable_value",
    "total_assets",
    "debt_outstanding",
    "institutional_debt",
    "noninstitutional_debt",
    "unknown_agency_debt",
}


def write_household_output(households: Dict[str, dict], order: List[str]) -> None:
    with HOUSEHOLD_STOCK_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HOUSEHOLD_COLUMNS)
        writer.writeheader()
        for hhid in order:
            source = households[hhid]
            row = {}
            for col in HOUSEHOLD_COLUMNS:
                value = source.get(col, "")
                if col in NUMERIC_OUTPUT_COLUMNS:
                    value = display_number(float(value or 0.0))
                row[col] = value
            writer.writerow(row)


def build_step02_lock(
    methodology: dict,
    raw_paths: Dict[str, Path],
    households: Dict[str, dict],
    asset_summaries: List[dict],
    control_rows: List[dict],
    debt_summary: dict,
    final_status: str,
) -> dict:
    hard_controls = [r for r in control_rows if r["validation_mode"] == "HARD"]
    return {
        "step": "02",
        "name": "Canonical Visit-1 household stock layer",
        "status": final_status,
        "project_root": str(PROJECT_ROOT),
        "input_lock": {
            "visit1_households": EXPECTED_VISIT1_HOUSEHOLDS,
            "stock_weight": methodology.get("weighting", {}).get("stock_visit1", {}).get("weight_variable"),
            "asset_reference_date": methodology.get("reference_periods", {}).get("asset_stock", {}).get("reference_date"),
            "debt_reference_date": methodology.get("reference_periods", {}).get("debt_stock", {}).get("reference_date"),
        },
        "raw_files": {key: str(path) for key, path in raw_paths.items()},
        "asset_total_row_selectors": {
            key: {
                "item_variable": item_var,
                "total_code": total_code,
                "value_variable": value_var,
                "output_column": output_col,
            }
            for key, (item_var, total_code, value_var, output_col) in ASSET_TOTAL_ROWS.items()
        },
        "asset_method": {
            "land": "Block 5.1 total + Block 5.2 total for every household",
            "total_assets_components": 9,
            "consumer_durables_included": False,
            "bullion_ornaments_included": False,
            "block10_imputed": False,
        },
        "debt_method": {
            "source": "Visit 1 Block 14",
            "outstanding_variable": "b14_q17",
            "explicit_total_row_code_excluded": "99",
            "kind_loans_included": False,
            "positive_outstanding_rule": "b14_q17 > 0",
        },
        "household_output_rows": len(households),
        "asset_component_audit": asset_summaries,
        "debt_audit": debt_summary,
        "hard_official_controls": hard_controls,
        "errors": errors,
        "warnings": warnings,
        "disclosures": disclosures,
        "outputs": {
            "household_stock": str(HOUSEHOLD_STOCK_FILE),
            "checks": str(CHECKS_FILE),
            "official_control_validation": str(CONTROL_VALIDATION_FILE),
            "asset_component_summary": str(ASSET_SUMMARY_FILE),
            "summary": str(SUMMARY_FILE),
        },
    }


def write_summary(final_status: str, households: Dict[str, dict], control_rows: List[dict]) -> None:
    hard = [r for r in control_rows if r["validation_mode"] == "HARD"]
    hard_pass = sum(1 for r in hard if r["status"] == "PASS")
    diagnostic = [r for r in control_rows if r["validation_mode"] == "DIAGNOSTIC"]
    diagnostic_diff = sum(1 for r in diagnostic if r["status"] == "DIAGNOSTIC_DIFF")

    rural = weighted_metrics(hh for hh in households.values() if hh["Sector"] == "1")
    urban = weighted_metrics(hh for hh in households.values() if hh["Sector"] == "2")

    lines = [
        "==============================================================================",
        "AIDIS 2013 - STEP 02 HOUSEHOLD STOCK BUILD SUMMARY",
        "==============================================================================",
        "",
        f"Project root              : {PROJECT_ROOT}",
        "",
        "HOUSEHOLD LAYER",
        "---------------",
        f"Visit-1 expected          : {EXPECTED_VISIT1_HOUSEHOLDS:,}",
        f"Output households         : {len(households):,}",
        f"Duplicate HHIDs           : {next((c['actual'] for c in checks if c['check_id']=='HH_DUPLICATES'), 'NA')}",
        "",
        "ASSET STOCK - 30-06-2012",
        "-------------------------",
        "Included components      : 9",
        "Land                     : Block 5.1 total + Block 5.2 total",
        "Consumer durables        : EXCLUDED",
        "Bullion / ornaments      : EXCLUDED",
        "Block-10 imputation      : NONE",
        f"Rural AVA computed        : {rural['AVA']:,.3f}",
        f"Urban AVA computed        : {urban['AVA']:,.3f}",
        "",
        "DEBT STOCK - 30-06-2012",
        "------------------------",
        "Source                   : Visit-1 Block 14",
        "Outstanding field        : b14_q17",
        "Explicit row 99          : EXCLUDED from detail aggregation",
        "Kind loans Block 15      : EXCLUDED",
        f"Rural IOI computed        : {rural['IOI']:.6f}%",
        f"Rural AOD computed        : {rural['AOD']:,.3f}",
        f"Rural AODL computed       : {rural['AODL']:,.3f}",
        f"Urban IOI computed        : {urban['IOI']:.6f}%",
        f"Urban AOD computed        : {urban['AOD']:,.3f}",
        f"Urban AODL computed       : {urban['AODL']:,.3f}",
        "",
        "OFFICIAL CONTROL VALIDATION",
        "---------------------------",
        f"Hard controls             : {len(hard)}",
        f"Hard controls passed      : {hard_pass}",
        f"Diagnostic controls       : {len(diagnostic)}",
        f"Diagnostic differences    : {diagnostic_diff}",
        "",
        f"Checks                    : {len(checks)}",
        f"Failed checks             : {sum(1 for c in checks if c['status']=='FAIL')}",
        f"Warnings                  : {len(warnings)}",
        f"Disclosures               : {len(disclosures)}",
        "",
        f"Household stock           : {HOUSEHOLD_STOCK_FILE}",
        f"Checks                    : {CHECKS_FILE}",
        f"Official controls         : {CONTROL_VALIDATION_FILE}",
        f"Asset audit               : {ASSET_SUMMARY_FILE}",
        f"Step-02 lock              : {STEP02_LOCK_FILE}",
        "",
    ]

    if disclosures:
        lines.extend(["DISCLOSURES:"])
        lines.extend([f"  - {item}" for item in disclosures])
        lines.append("")

    if warnings:
        lines.extend(["WARNINGS:"])
        lines.extend([f"  - {item}" for item in warnings])
        lines.append("")

    if errors:
        lines.extend(["ERRORS:"])
        lines.extend([f"  - {item}" for item in errors])
        lines.append("")

    lines.extend(
        [
            f"STEP 02 STATUS: {final_status}",
            "==============================================================================",
        ]
    )

    text = "\n".join(lines) + "\n"
    SUMMARY_FILE.write_text(text, encoding="utf-8")
    print("\n" + text)


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    print("==============================================================================")
    print("AIDIS 2013 - STEP 02 HOUSEHOLD STOCK BUILD")
    print("NSS 70th Round | Schedule 18.2")
    print("==============================================================================")
    print(f"Project root              : {PROJECT_ROOT}")
    print(f"Script revision           : {SCRIPT_REVISION}")

    methodology = validate_upstream()
    if errors:
        write_csv(CHECKS_FILE, checks, ["check_id", "check_name", "expected", "actual", "status", "severity", "note"])
        write_summary("FAIL", {}, [])
        return 1

    print("\n[1b] Resolving locked Visit-1 raw files")
    raw_paths: Dict[str, Path] = {}
    for key, file_name in RAW_FILES.items():
        try:
            raw_paths[key] = find_raw_file(file_name)
            print(f"  PASS | {key:24s} | {file_name}")
        except Exception as exc:
            errors.append(str(exc))
            print(f"  FAIL | {key:24s} | {file_name}")

    if errors:
        write_csv(CHECKS_FILE, checks, ["check_id", "check_name", "expected", "actual", "status", "severity", "note"])
        write_summary("FAIL", {}, [])
        return 1

    households, order = build_household_backbone(raw_paths["identification"])
    attach_household_characteristics(raw_paths["household_characteristics"], households)
    asset_summaries = build_assets(raw_paths, households)
    debt_summary = build_debt(raw_paths["debt"], households)
    control_rows = validate_official_controls(households)

    # Final exact household integrity after all joins/aggregations.
    add_check(
        "FINAL_HH_COUNT",
        "Final Step-02 output household count",
        EXPECTED_VISIT1_HOUSEHOLDS,
        len(households),
        len(households) == EXPECTED_VISIT1_HOUSEHOLDS,
    )

    final_status = "FAIL" if errors else ("PASS_WITH_DISCLOSURES" if disclosures or warnings else "PASS")

    print("\n[7] Writing Step-02 outputs")
    write_household_output(households, order)
    write_csv(
        CHECKS_FILE,
        checks,
        ["check_id", "check_name", "expected", "actual", "status", "severity", "note"],
    )
    write_csv(
        CONTROL_VALIDATION_FILE,
        control_rows,
        [
            "control_id",
            "family",
            "sector",
            "household_group",
            "metric",
            "published_value",
            "computed_value",
            "difference",
            "absolute_tolerance",
            "source_tolerance",
            "validation_mode",
            "status",
        ],
    )
    write_csv(
        ASSET_SUMMARY_FILE,
        asset_summaries,
        [
            "component_key",
            "source_file",
            "item_variable",
            "total_code",
            "value_variable",
            "selected_total_rows",
            "households_with_total_row",
            "duplicate_total_rows",
            "unknown_hhid",
            "blank_selected_values",
            "nonzero_selected_values",
            "negative_selected_values",
            "negative_raw_sum",
            "negative_raw_min",
            "negative_example_hhids",
            "negative_values_cleaned_to_zero",
            "unweighted_total_value",
        ],
    )

    step02_lock = build_step02_lock(
        methodology,
        raw_paths,
        households,
        asset_summaries,
        control_rows,
        debt_summary,
        final_status,
    )
    write_json(STEP02_LOCK_FILE, step02_lock)
    write_summary(final_status, households, control_rows)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
