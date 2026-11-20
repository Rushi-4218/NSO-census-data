from pathlib import Path
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict

from openpyxl import load_workbook


# =============================================================================
# AIDIS 2003 - STEP 03 ASSET FACTS / AVA
# NSS 59th Round, Schedule 18.2
#
# Production principles:
#   * Use the Step 02 Visit-1 stock household universe (143,285 households).
#   * Use the schedule-provided 30-06-2002 stock value fields.
#   * Use the official total/control row for each asset block; do not sum detail
#     rows together with the total row (that would double count assets).
#   * Aggregate asset facts to HHID before any estimator is applied.
#   * Carry Weight once per household from Step 02; never from asset detail rows.
#   * Block 14 is loans RECEIVABLE and therefore belongs on the asset side.
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
WORK_DIR = ROOT / "work"
CONFIG_DIR = ROOT / "config"
REPORT_DIR = ROOT / "output" / "reports"

PRODUCTION_MANIFEST = CACHE_DIR / "step01_production_manifest.csv"
METHODOLOGY_FILE = CONFIG_DIR / "aidis_2003_methodology_lock.json"
STOCK_BASE_FILE = WORK_DIR / "step02_household_base_stock.csv"
STEP02_SUMMARY_FILE = REPORT_DIR / "step02_household_base_summary.txt"

ASSET_FACT_FILE = WORK_DIR / "step03_household_asset_facts.csv"
BLOCK_AUDIT_FILE = CACHE_DIR / "step03_asset_block_audit.csv"
AVA_CONTROL_FILE = CACHE_DIR / "step03_asset_ava_controls.csv"
COMPONENT_ESTIMATES_FILE = CACHE_DIR / "step03_asset_component_estimates.csv"
SUMMARY_FILE = REPORT_DIR / "step03_asset_facts_summary.txt"

EXPECTED_STOCK_HOUSEHOLDS = 143_285
AVA_REL_TOLERANCE = 0.005  # 0.5%; published controls are rounded estimates.


# -----------------------------------------------------------------------------
# Official Report No. 500 controls, all-India, as on 30-06-2002.
# These are deliberately used only as QA controls, not as production inputs.
# -----------------------------------------------------------------------------
OFFICIAL_AVA_CONTROLS = [
    {
        "control": "All India",
        "expected_sample_households": 143_285,
        "expected_ava_rs": 306_967.0,
        "selector": "ALL",
    },
    {
        "control": "Rural - all households",
        "expected_sample_households": 91_192,
        "expected_ava_rs": 265_606.0,
        "selector": "RURAL_ALL",
    },
    {
        "control": "Rural - cultivator",
        "expected_sample_households": 54_195,
        "expected_ava_rs": 372_632.0,
        "selector": "RURAL_CULTIVATOR",
    },
    {
        # Official table is exhaustive: non-cultivator is the residual to
        # cultivator. This includes Step-02 rows retained as unclassified rather
        # than silently rewriting their client-facing subgroup code.
        "control": "Rural - non-cultivator (official residual QA)",
        "expected_sample_households": 36_997,
        "expected_ava_rs": 107_230.0,
        "selector": "RURAL_NONCULTIVATOR_RESIDUAL",
    },
    {
        "control": "Urban - all households",
        "expected_sample_households": 52_093,
        "expected_ava_rs": 417_158.0,
        "selector": "URBAN_ALL",
    },
    {
        "control": "Urban - self-employed",
        "expected_sample_households": 19_986,
        "expected_ava_rs": 554_844.0,
        "selector": "URBAN_SELF_EMPLOYED",
    },
    {
        # Official table is exhaustive: others is the residual to self-employed.
        "control": "Urban - others (official residual QA)",
        "expected_sample_households": 32_107,
        "expected_ava_rs": 339_002.0,
        "selector": "URBAN_OTHERS_RESIDUAL",
    },
]


# -----------------------------------------------------------------------------
# Schedule total/control rows and direct 30-06-2002 stock fields.
# q1 values below are the official total rows printed in Schedule 18.2.
# -----------------------------------------------------------------------------
ASSET_BLOCKS = [
    {
        "key": "land",
        "label": "Land",
        "logical_names": ["Visit1_Block_5"],
        "expected_rows": 366_157,
        "item_field": "B5_q1",
        "total_code": "99",
        "stock_field": "B5_q11",
        "current_field": "B5_q5",
        "acquisition_field": "B5_q7",
        "disposal_field": "B5_q9",
        "output_field": "Land_Asset_Rs",
        "class": "physical",
    },
    {
        "key": "buildings",
        "label": "Buildings and other constructions",
        "logical_names": ["Visit1_Block_6_part2"],
        "support_logical_names": ["Visit1_Block_6"],
        "expected_rows": 285_146,
        "support_expected_rows": 286_847,
        "item_field": "B6_q1",
        "total_code": "11",
        "stock_field": "B6_q14",
        "disposal_field": "B6_q12",
        "support_current_field": "B6_q4",
        "support_acquisition_field": "B6_q8",
        "output_field": "Buildings_Asset_Rs",
        "class": "physical",
    },
    {
        "key": "livestock",
        "label": "Livestock and poultry",
        "logical_names": ["Visit1_Block_7"],
        "expected_rows": 296_885,
        "item_field": "B7_q1",
        "total_code": "44",
        "stock_field": "B7_q10",
        "current_field": "B7_q4",
        "acquisition_field": "B7_q6",
        "disposal_field": "B7_q8",
        "output_field": "Livestock_Poultry_Asset_Rs",
        "class": "physical",
    },
    {
        "key": "agricultural_machinery",
        "label": "Agricultural machinery and implements",
        "logical_names": ["Visit1_Block_8"],
        "expected_rows": 248_368,
        "item_field": "B8_q1",
        "total_code": "17",
        "stock_field": "B8_q10",
        "current_field": "B8_q4",
        "acquisition_field": "B8_q6",
        "disposal_field": "B8_q8",
        "output_field": "Agricultural_Machinery_Asset_Rs",
        "class": "physical",
    },
    {
        "key": "nonfarm_equipment",
        "label": "Non-farm business equipment",
        "logical_names": ["Visit1_Block_9"],
        "expected_rows": 94_603,
        "item_field": "B9_q1",
        "total_code": "21",
        "stock_field": "B9_q10",
        "current_field": "B9_q4",
        "acquisition_field": "B9_q6",
        "disposal_field": "B9_q8",
        "output_field": "Nonfarm_Business_Equipment_Asset_Rs",
        "class": "physical",
    },
    {
        "key": "transport",
        "label": "Transport equipment",
        "logical_names": ["Visit1_Block_10"],
        "expected_rows": 165_169,
        "item_field": "B10_q1",
        "total_code": "10",
        "stock_field": "B10_q10",
        "current_field": "B10_q4",
        "acquisition_field": "B10_q6",
        "disposal_field": "B10_q8",
        "output_field": "Transport_Equipment_Asset_Rs",
        "class": "physical",
    },
    {
        "key": "durables",
        "label": "Durable household assets",
        "logical_names": ["Visit 1_Block_11", "Visit1_Block_11"],
        "expected_rows": 1_123_774,
        "item_field": "B11_q1",
        "total_code": "15",
        "stock_field": "B11_q10",
        "current_field": "B11_q4",
        "acquisition_field": "B11_q6",
        "disposal_field": "B11_q8",
        "output_field": "Durable_Assets_Rs",
        "class": "physical",
    },
    {
        "key": "shares",
        "label": "Shares and debentures",
        "logical_names": ["Visit1_Block_12"],
        "expected_rows": 20_428,
        "item_field": "B12_q1",
        "total_code": "8",
        "stock_field": "B12_q6",
        "current_field": "B12_q3",
        "acquisition_field": "B12_q4",
        "disposal_field": "B12_q5",
        "output_field": "Shares_Debentures_Asset_Rs",
        "class": "financial",
    },
    {
        "key": "other_financial",
        "label": "Deposits and other financial assets",
        "logical_names": ["Visit1_Block_13"],
        "expected_rows": 346_612,
        "item_field": "B13_q1",
        "total_code": "13",
        "stock_field": "B13_q8",
        "stock_sign_field": "B13_q7",
        "current_field": "B13_q4",
        "current_sign_field": "B13_q3",
        "acquisition_field": "B13_q5",
        "disposal_field": "B13_q6",
        "output_field": "Deposits_Other_Financial_Assets_Rs",
        "class": "financial",
    },
    {
        "key": "loans_receivable",
        "label": "Loans receivable",
        "logical_names": ["Visit1_Block_14"],
        "expected_rows": 7_272,
        "item_field": "B14_q1",
        "total_code": "8",
        "stock_field": "B14_q6",
        "current_field": "B14_q3",
        "acquisition_field": "B14_q4",   # lent out
        "disposal_field": "B14_q5",      # received as repayment
        "output_field": "Loans_Receivable_Asset_Rs",
        "class": "financial",
    },
]


# =============================================================================
# HELPERS
# =============================================================================

def clean(value):
    return "" if value is None else str(value).strip()


def norm_name(value):
    return re.sub(r"[^a-z0-9]+", "", clean(value).casefold())


def canonical_code(value):
    text = clean(value)
    if not text:
        return ""
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except Exception:
        pass
    return text.lstrip("0") or "0"


def as_float(value, blank_zero=False):
    text = clean(value).replace(",", "")
    if not text:
        return 0.0 if blank_zero else None
    return float(text)


def signed_value(sign_value, raw_value, blank_zero=True):
    value = as_float(raw_value, blank_zero=blank_zero)
    if value is None:
        return None
    # Schedule footnote: sign=1 means the absolute value stored in the value
    # column is negative.
    if canonical_code(sign_value) == "1":
        return -abs(value)
    return value


def nearly_equal(a, b, abs_tol=0.5, rel_tol=1e-9):
    return math.isclose(float(a), float(b), abs_tol=abs_tol, rel_tol=rel_tol)


def format_number(value):
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def require_fields(fieldnames, required, label):
    present = {norm_name(x): x for x in fieldnames or []}
    missing = [x for x in required if norm_name(x) not in present]
    if missing:
        raise ValueError(f"{label}: missing fields {missing}")


def read_manifest():
    if not PRODUCTION_MANIFEST.exists():
        raise FileNotFoundError(f"Missing production manifest: {PRODUCTION_MANIFEST}")
    with PRODUCTION_MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 42:
        raise ValueError(f"Production manifest must contain 42 rows; found {len(rows)}")
    failed = [r for r in rows if clean(r.get("status")).upper() != "PASS"]
    if failed:
        raise ValueError(f"Production manifest contains {len(failed)} non-PASS row(s)")
    return rows


def find_manifest_source(manifest, logical_names):
    targets = {norm_name(x) for x in logical_names}
    matches = [r for r in manifest if norm_name(r.get("logical_dataset")) in targets]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one source for {logical_names}; found "
            f"{[(r.get('logical_dataset'), r.get('source_path')) for r in matches]}"
        )
    path = Path(matches[0]["source_path"])
    if not path.exists():
        raise FileNotFoundError(f"Manifest source missing: {path}")
    return path, matches[0]


def validate_methodology_lock():
    if not METHODOLOGY_FILE.exists():
        raise FileNotFoundError(f"Missing methodology lock: {METHODOLOGY_FILE}")
    config = json.loads(METHODOLOGY_FILE.read_text(encoding="utf-8"))
    if config.get("methodology_lock_status") != "LOCKED":
        raise ValueError("Methodology configuration is not LOCKED")
    if config.get("survey", {}).get("stock_reference_date") != "2002-06-30":
        raise ValueError("Methodology stock reference date is not 2002-06-30")
    if config.get("estimation", {}).get("locked_weight_field") != "Weight":
        raise ValueError("Methodology does not lock Weight as estimator field")
    return config


def check_step02_pass():
    if not STEP02_SUMMARY_FILE.exists():
        raise FileNotFoundError(f"Missing Step 02 summary: {STEP02_SUMMARY_FILE}")
    text = STEP02_SUMMARY_FILE.read_text(encoding="utf-8", errors="replace")
    if "STEP 02 STATUS: PASS" not in text:
        raise ValueError("Step 02 summary does not contain PASS status")
    if not STOCK_BASE_FILE.exists():
        raise FileNotFoundError(f"Missing Step 02 stock base: {STOCK_BASE_FILE}")


def load_stock_base():
    base = {}
    order = []
    sector_counts = Counter()
    group_counts = Counter()
    weight_errors = 0

    with STOCK_BASE_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = [
            "HHID", "Sector", "Sector_Name", "State", "District", "State_Region",
            "Weight", "Household_Group_Code", "Household_Group",
            "Group_Classification_Status",
        ]
        require_fields(reader.fieldnames, required, STOCK_BASE_FILE.name)

        for row in reader:
            hhid = clean(row.get("HHID"))
            if not hhid:
                raise ValueError("Blank HHID found in Step 02 stock base")
            if hhid in base:
                raise ValueError(f"Duplicate HHID in Step 02 stock base: {hhid}")

            try:
                weight = as_float(row.get("Weight"))
            except Exception:
                weight = None
            if weight is None or weight <= 0:
                weight_errors += 1

            meta = {
                "HHID": hhid,
                "Sector": clean(row.get("Sector")),
                "Sector_Name": clean(row.get("Sector_Name")),
                "State_Region": clean(row.get("State_Region")),
                "State": clean(row.get("State")),
                "District": clean(row.get("District")),
                "Weight": weight,
                "Household_Group_Code": clean(row.get("Household_Group_Code")),
                "Household_Group": clean(row.get("Household_Group")),
                "Group_Classification_Status": clean(row.get("Group_Classification_Status")),
            }
            base[hhid] = meta
            order.append(hhid)
            sector_counts[meta["Sector"]] += 1
            group_counts[meta["Household_Group_Code"]] += 1

    if weight_errors:
        raise ValueError(f"Step 02 stock base has {weight_errors} invalid Weight value(s)")
    if len(base) != EXPECTED_STOCK_HOUSEHOLDS:
        raise ValueError(
            f"Step 02 stock base should contain {EXPECTED_STOCK_HOUSEHOLDS:,} households; "
            f"found {len(base):,}"
        )
    return base, order, sector_counts, group_counts


def csv_row_iterator(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            handle = path.open("r", encoding=encoding, newline="")
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                handle.close()
                raise ValueError("empty CSV header")
            return handle, reader, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
            break
    raise RuntimeError(f"Unable to open CSV {path}: {last_error}")


def find_xlsx_header(ws):
    for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
        values = [clean(x) for x in row]
        if any(norm_name(x) == norm_name("HHID") for x in values):
            return row_number, values
        if row_number >= 20:
            break
    raise ValueError(f"Could not locate HHID header in worksheet {ws.title}")


def audit_geo_weight(row, base_row, stats):
    if clean(row.get("Sector")) and clean(row.get("Sector")) != base_row["Sector"]:
        stats["core_mismatches"] += 1
    if clean(row.get("State")) and clean(row.get("State")) != base_row["State"]:
        stats["core_mismatches"] += 1
    if clean(row.get("District")) and clean(row.get("District")) != base_row["District"]:
        stats["core_mismatches"] += 1

    raw_weight = clean(row.get("Weight"))
    if raw_weight:
        try:
            if not nearly_equal(float(raw_weight), base_row["Weight"], abs_tol=5e-7):
                stats["weight_mismatches"] += 1
        except Exception:
            stats["weight_mismatches"] += 1


def scan_regular_block(path, spec, base):
    required = ["HHID", spec["item_field"], spec["stock_field"]]
    for key in ("current_field", "acquisition_field", "disposal_field", "stock_sign_field", "current_sign_field"):
        if spec.get(key):
            required.append(spec[key])

    values = {}
    stats = {
        "source_rows": 0,
        "total_rows": 0,
        "unique_total_hh": 0,
        "blank_stock_values": 0,
        "negative_stock_values": 0,
        "unmatched_total_hh": 0,
        "duplicate_total_rows": 0,
        "core_mismatches": 0,
        "weight_mismatches": 0,
        "reconstruction_checked": 0,
        "reconstruction_mismatches": 0,
        "encoding_or_sheet": "",
    }

    def process(row):
        stats["source_rows"] += 1
        if canonical_code(row.get(spec["item_field"])) != canonical_code(spec["total_code"]):
            return

        stats["total_rows"] += 1
        hhid = clean(row.get("HHID"))
        if hhid not in base:
            stats["unmatched_total_hh"] += 1
            return
        if hhid in values:
            stats["duplicate_total_rows"] += 1
            return

        raw_stock = clean(row.get(spec["stock_field"]))
        if not raw_stock:
            stats["blank_stock_values"] += 1

        if spec.get("stock_sign_field"):
            stock = signed_value(row.get(spec["stock_sign_field"]), row.get(spec["stock_field"]), blank_zero=True)
        else:
            stock = as_float(row.get(spec["stock_field"]), blank_zero=True)

        if stock < 0:
            stats["negative_stock_values"] += 1

        values[hhid] = stock
        audit_geo_weight(row, base[hhid], stats)

        if spec.get("current_field"):
            if spec.get("current_sign_field"):
                current = signed_value(row.get(spec["current_sign_field"]), row.get(spec["current_field"]), blank_zero=True)
            else:
                current = as_float(row.get(spec["current_field"]), blank_zero=True)
            acq = as_float(row.get(spec["acquisition_field"]), blank_zero=True)
            disp = as_float(row.get(spec["disposal_field"]), blank_zero=True)
            reconstructed = current - acq + disp
            stats["reconstruction_checked"] += 1
            if not nearly_equal(reconstructed, stock):
                stats["reconstruction_mismatches"] += 1

    suffix = path.suffix.casefold()
    if suffix == ".csv":
        handle, reader, encoding = csv_row_iterator(path)
        stats["encoding_or_sheet"] = f"encoding={encoding}"
        try:
            require_fields(reader.fieldnames, required, path.name)
            for row in reader:
                process(row)
        finally:
            handle.close()

    elif suffix == ".xlsx":
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            header_row, header = find_xlsx_header(ws)
            require_fields(header, required, path.name)
            stats["encoding_or_sheet"] = f"sheet={ws.title};header_row={header_row}"
            for values_row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                row = {header[i]: values_row[i] if i < len(values_row) else None for i in range(len(header))}
                process(row)
        finally:
            wb.close()
    else:
        raise ValueError(f"Unsupported source type for Step 03: {path}")

    stats["unique_total_hh"] = len(values)
    return values, stats


def scan_building_support(path, spec, base):
    required = [
        "HHID", spec["item_field"], spec["support_current_field"],
        spec["support_acquisition_field"],
    ]
    support = {}
    stats = {
        "source_rows": 0,
        "total_rows": 0,
        "unique_total_hh": 0,
        "duplicate_total_rows": 0,
        "unmatched_total_hh": 0,
        "encoding_or_sheet": "",
    }

    def process(row):
        stats["source_rows"] += 1
        if canonical_code(row.get(spec["item_field"])) != canonical_code(spec["total_code"]):
            return
        stats["total_rows"] += 1
        hhid = clean(row.get("HHID"))
        if hhid not in base:
            stats["unmatched_total_hh"] += 1
            return
        if hhid in support:
            stats["duplicate_total_rows"] += 1
            return
        support[hhid] = (
            as_float(row.get(spec["support_current_field"]), blank_zero=True),
            as_float(row.get(spec["support_acquisition_field"]), blank_zero=True),
        )

    suffix = path.suffix.casefold()
    if suffix == ".csv":
        handle, reader, encoding = csv_row_iterator(path)
        stats["encoding_or_sheet"] = f"encoding={encoding}"
        try:
            require_fields(reader.fieldnames, required, path.name)
            for row in reader:
                process(row)
        finally:
            handle.close()
    elif suffix == ".xlsx":
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            header_row, header = find_xlsx_header(ws)
            require_fields(header, required, path.name)
            stats["encoding_or_sheet"] = f"sheet={ws.title};header_row={header_row}"
            for values_row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                row = {header[i]: values_row[i] if i < len(values_row) else None for i in range(len(header))}
                process(row)
        finally:
            wb.close()
    else:
        raise ValueError(f"Unsupported building support source: {path}")

    stats["unique_total_hh"] = len(support)
    return support, stats


def scan_building_stock(path, spec, base, support):
    required = ["HHID", spec["item_field"], spec["stock_field"], spec["disposal_field"]]
    values = {}
    stats = {
        "source_rows": 0,
        "total_rows": 0,
        "unique_total_hh": 0,
        "blank_stock_values": 0,
        "negative_stock_values": 0,
        "unmatched_total_hh": 0,
        "duplicate_total_rows": 0,
        "core_mismatches": 0,
        "weight_mismatches": 0,
        "support_missing_for_total": 0,
        "reconstruction_checked": 0,
        "reconstruction_mismatches": 0,
        "encoding_or_sheet": "",
    }

    def process(row):
        stats["source_rows"] += 1
        if canonical_code(row.get(spec["item_field"])) != canonical_code(spec["total_code"]):
            return
        stats["total_rows"] += 1
        hhid = clean(row.get("HHID"))
        if hhid not in base:
            stats["unmatched_total_hh"] += 1
            return
        if hhid in values:
            stats["duplicate_total_rows"] += 1
            return

        raw_stock = clean(row.get(spec["stock_field"]))
        if not raw_stock:
            stats["blank_stock_values"] += 1
        stock = as_float(row.get(spec["stock_field"]), blank_zero=True)
        if stock < 0:
            stats["negative_stock_values"] += 1
        values[hhid] = stock
        audit_geo_weight(row, base[hhid], stats)

        if hhid in support:
            current, acq = support[hhid]
            disp = as_float(row.get(spec["disposal_field"]), blank_zero=True)
            reconstructed = current - acq + disp
            stats["reconstruction_checked"] += 1
            if not nearly_equal(reconstructed, stock):
                stats["reconstruction_mismatches"] += 1
        else:
            stats["support_missing_for_total"] += 1

    suffix = path.suffix.casefold()
    if suffix == ".csv":
        handle, reader, encoding = csv_row_iterator(path)
        stats["encoding_or_sheet"] = f"encoding={encoding}"
        try:
            require_fields(reader.fieldnames, required, path.name)
            for row in reader:
                process(row)
        finally:
            handle.close()
    elif suffix == ".xlsx":
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            header_row, header = find_xlsx_header(ws)
            require_fields(header, required, path.name)
            stats["encoding_or_sheet"] = f"sheet={ws.title};header_row={header_row}"
            for values_row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                row = {header[i]: values_row[i] if i < len(values_row) else None for i in range(len(header))}
                process(row)
        finally:
            wb.close()
    else:
        raise ValueError(f"Unsupported building stock source: {path}")

    stats["unique_total_hh"] = len(values)
    return values, stats


def selector_match(meta, selector):
    sector = meta["Sector"]
    group = meta["Household_Group_Code"]
    if selector == "ALL":
        return True
    if selector == "RURAL_ALL":
        return sector == "1"
    if selector == "RURAL_CULTIVATOR":
        return sector == "1" and group == "R_CULTIVATOR"
    if selector == "RURAL_NONCULTIVATOR_RESIDUAL":
        return sector == "1" and group != "R_CULTIVATOR"
    if selector == "URBAN_ALL":
        return sector == "2"
    if selector == "URBAN_SELF_EMPLOYED":
        return sector == "2" and group == "U_SELF_EMPLOYED"
    if selector == "URBAN_OTHERS_RESIDUAL":
        return sector == "2" and group != "U_SELF_EMPLOYED"
    return False


def component_group_key(meta):
    sector = meta["Sector"]
    group = meta["Household_Group"] or "Unclassified"
    if sector == "1":
        return f"Rural | {group}"
    if sector == "2":
        return f"Urban | {group}"
    return f"Unknown Sector | {group}"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 78)
    print("AIDIS 2003 - STEP 03 ASSET FACTS / AVA")
    print("Build 30-06-2002 household assets from Visit-1 asset blocks")
    print("=" * 78)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    errors = []
    warnings = []
    block_audit_rows = []

    # -------------------------------------------------------------------------
    # 1. Prerequisites
    # -------------------------------------------------------------------------
    print("\n[1] Step prerequisites")
    try:
        methodology = validate_methodology_lock()
        check_step02_pass()
        manifest = read_manifest()
        base, base_order, sector_counts, group_counts = load_stock_base()
        print("Methodology lock          : PASS")
        print("Step 02 stock base        : PASS")
        print(f"Stock households          : {len(base):,}")
        print(f"Stock rural / urban       : {sector_counts['1']:,} / {sector_counts['2']:,}")
        print("Production manifest       : PASS (42/42)")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print("\nSTEP 03 STATUS: FAIL")
        return 1

    # Asset dictionary: one dictionary per component keyed by HHID.
    component_values = {}

    # -------------------------------------------------------------------------
    # 2. Read official total rows from each asset block
    # -------------------------------------------------------------------------
    print("\n[2] Asset block extraction")

    for idx, spec in enumerate(ASSET_BLOCKS, start=1):
        try:
            path, manifest_row = find_manifest_source(manifest, spec["logical_names"])

            if spec["key"] == "buildings":
                support_path, _ = find_manifest_source(manifest, spec["support_logical_names"])
                support, support_stats = scan_building_support(support_path, spec, base)
                if support_stats["source_rows"] != spec["support_expected_rows"]:
                    errors.append(
                        f"Buildings part1 row count expected {spec['support_expected_rows']:,}; "
                        f"got {support_stats['source_rows']:,}"
                    )
                if support_stats["duplicate_total_rows"]:
                    errors.append(
                        f"Buildings part1 has {support_stats['duplicate_total_rows']} duplicate total row(s)"
                    )
                if support_stats["unmatched_total_hh"]:
                    errors.append(
                        f"Buildings part1 has {support_stats['unmatched_total_hh']} unmatched total HHID(s)"
                    )

                values, stats = scan_building_stock(path, spec, base, support)
                block_audit_rows.append({
                    "block_key": "buildings_part1_support",
                    "asset_component": "Buildings and other constructions - part1 support",
                    "source_file": support_path.name,
                    "source_path": str(support_path),
                    "source_rows": support_stats["source_rows"],
                    "expected_source_rows": spec["support_expected_rows"],
                    "total_code": spec["total_code"],
                    "total_rows": support_stats["total_rows"],
                    "unique_total_hh": support_stats["unique_total_hh"],
                    "blank_stock_values": "",
                    "negative_stock_values": "",
                    "unmatched_total_hh": support_stats["unmatched_total_hh"],
                    "duplicate_total_rows": support_stats["duplicate_total_rows"],
                    "core_mismatches": "",
                    "weight_mismatches": "",
                    "reconstruction_checked": "",
                    "reconstruction_mismatches": "",
                    "read_info": support_stats["encoding_or_sheet"],
                    "status": "PASS" if not (support_stats["duplicate_total_rows"] or support_stats["unmatched_total_hh"]) else "FAIL",
                })
            else:
                values, stats = scan_regular_block(path, spec, base)

            component_values[spec["output_field"]] = values

            # Fatal structural checks.
            if stats["source_rows"] != spec["expected_rows"]:
                errors.append(
                    f"{spec['label']}: source row count expected {spec['expected_rows']:,}; "
                    f"got {stats['source_rows']:,}"
                )
            if stats["total_rows"] == 0:
                errors.append(f"{spec['label']}: no official total rows found (code {spec['total_code']})")
            if stats["unmatched_total_hh"]:
                errors.append(f"{spec['label']}: {stats['unmatched_total_hh']} total row HHID(s) not in Step 02 base")
            if stats["duplicate_total_rows"]:
                errors.append(f"{spec['label']}: {stats['duplicate_total_rows']} duplicate total row(s) by HHID")
            if stats["core_mismatches"]:
                errors.append(f"{spec['label']}: {stats['core_mismatches']} geography/core mismatch(es)")
            if stats["weight_mismatches"]:
                errors.append(f"{spec['label']}: {stats['weight_mismatches']} Weight mismatch(es)")

            # Negative net Block-13 values are possible by schedule design. Other
            # asset-block total values must not be negative.
            if spec["key"] != "other_financial" and stats["negative_stock_values"]:
                errors.append(f"{spec['label']}: {stats['negative_stock_values']} negative stock total(s)")

            if stats["blank_stock_values"]:
                warnings.append(
                    f"{spec['label']}: {stats['blank_stock_values']} official total row(s) have blank "
                    "30-06-2002 value and are treated as zero."
                )
            if stats["reconstruction_mismatches"]:
                warnings.append(
                    f"{spec['label']}: {stats['reconstruction_mismatches']} total row(s) do not exactly "
                    "reconcile current - acquisition + disposal to the supplied 30-06-2002 field; "
                    "the direct schedule stock field remains authoritative."
                )
            if spec["key"] == "buildings" and stats.get("support_missing_for_total"):
                warnings.append(
                    f"Buildings: {stats['support_missing_for_total']} part2 total row(s) have no matching "
                    "part1 total row for reconstruction QA; direct B6_q14 is retained."
                )

            status = "PASS"
            block_audit_rows.append({
                "block_key": spec["key"],
                "asset_component": spec["label"],
                "source_file": path.name,
                "source_path": str(path),
                "source_rows": stats["source_rows"],
                "expected_source_rows": spec["expected_rows"],
                "total_code": spec["total_code"],
                "total_rows": stats["total_rows"],
                "unique_total_hh": stats["unique_total_hh"],
                "blank_stock_values": stats["blank_stock_values"],
                "negative_stock_values": stats["negative_stock_values"],
                "unmatched_total_hh": stats["unmatched_total_hh"],
                "duplicate_total_rows": stats["duplicate_total_rows"],
                "core_mismatches": stats["core_mismatches"],
                "weight_mismatches": stats["weight_mismatches"],
                "reconstruction_checked": stats["reconstruction_checked"],
                "reconstruction_mismatches": stats["reconstruction_mismatches"],
                "read_info": stats["encoding_or_sheet"],
                "status": status,
            })

            print(
                f"[{idx:02d}/10] PASS | rows={stats['source_rows']:>9,} | "
                f"totalHH={stats['unique_total_hh']:>7,} | blank={stats['blank_stock_values']:>5,} | "
                f"{spec['label']}"
            )

        except Exception as exc:
            msg = f"{spec['label']}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(f"[{idx:02d}/10] FAIL | {msg}")

    # Save block audit even if a later step fails.
    audit_fields = [
        "block_key", "asset_component", "source_file", "source_path",
        "source_rows", "expected_source_rows", "total_code", "total_rows",
        "unique_total_hh", "blank_stock_values", "negative_stock_values",
        "unmatched_total_hh", "duplicate_total_rows", "core_mismatches",
        "weight_mismatches", "reconstruction_checked",
        "reconstruction_mismatches", "read_info", "status",
    ]
    with BLOCK_AUDIT_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=audit_fields)
        writer.writeheader()
        writer.writerows(block_audit_rows)

    if len(component_values) != len(ASSET_BLOCKS):
        errors.append(
            f"Expected {len(ASSET_BLOCKS)} asset components; successfully loaded {len(component_values)}"
        )

    # -------------------------------------------------------------------------
    # 3. Build one-row-per-household asset facts
    # -------------------------------------------------------------------------
    print("\n[3] Build household asset facts")

    physical_fields = [x["output_field"] for x in ASSET_BLOCKS if x["class"] == "physical"]
    financial_fields = [x["output_field"] for x in ASSET_BLOCKS if x["class"] == "financial"]
    component_fields = [x["output_field"] for x in ASSET_BLOCKS]

    fact_fields = [
        "HHID", "Sector", "Sector_Name", "State_Region", "State", "District",
        "Household_Group_Code", "Household_Group", "Group_Classification_Status",
        "Weight",
    ] + component_fields + [
        "Physical_Assets_Rs", "Financial_Assets_Rs", "Total_Assets_Rs",
        "Has_Positive_Assets", "Stock_Reference_Date",
    ]

    # Aggregates needed for controls and component estimates.
    control_acc = {
        c["selector"]: {"n": 0, "weight": 0.0, "weighted_assets": 0.0}
        for c in OFFICIAL_AVA_CONTROLS
    }
    estimate_acc = defaultdict(
        lambda: defaultdict(lambda: {"n": 0, "weight": 0.0, "weighted_value": 0.0, "reporting_n": 0, "reporting_weight": 0.0})
    )

    negative_total_assets = 0
    fact_rows_written = 0
    balance_errors = 0

    try:
        with ASSET_FACT_FILE.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fact_fields)
            writer.writeheader()

            for hhid in base_order:
                meta = base[hhid]
                row = {
                    "HHID": hhid,
                    "Sector": meta["Sector"],
                    "Sector_Name": meta["Sector_Name"],
                    "State_Region": meta["State_Region"],
                    "State": meta["State"],
                    "District": meta["District"],
                    "Household_Group_Code": meta["Household_Group_Code"],
                    "Household_Group": meta["Household_Group"],
                    "Group_Classification_Status": meta["Group_Classification_Status"],
                    "Weight": format_number(meta["Weight"]),
                }

                numeric_components = {}
                for field in component_fields:
                    value = component_values.get(field, {}).get(hhid, 0.0)
                    numeric_components[field] = value
                    row[field] = format_number(value)

                physical = sum(numeric_components[f] for f in physical_fields)
                financial = sum(numeric_components[f] for f in financial_fields)
                total = physical + financial

                if not nearly_equal(total, physical + financial, abs_tol=1e-7):
                    balance_errors += 1
                if total < 0:
                    negative_total_assets += 1

                row["Physical_Assets_Rs"] = format_number(physical)
                row["Financial_Assets_Rs"] = format_number(financial)
                row["Total_Assets_Rs"] = format_number(total)
                row["Has_Positive_Assets"] = "1" if total > 0 else "0"
                row["Stock_Reference_Date"] = "2002-06-30"
                writer.writerow(row)
                fact_rows_written += 1

                weight = meta["Weight"]

                # Official controls.
                for control in OFFICIAL_AVA_CONTROLS:
                    if selector_match(meta, control["selector"]):
                        acc = control_acc[control["selector"]]
                        acc["n"] += 1
                        acc["weight"] += weight
                        acc["weighted_assets"] += weight * total

                # Component estimates for useful downstream groups.
                group_labels = ["All India"]
                if meta["Sector"] == "1":
                    group_labels.append("Rural - all")
                elif meta["Sector"] == "2":
                    group_labels.append("Urban - all")
                group_labels.append(component_group_key(meta))

                estimate_values = dict(numeric_components)
                estimate_values["Physical_Assets_Rs"] = physical
                estimate_values["Financial_Assets_Rs"] = financial
                estimate_values["Total_Assets_Rs"] = total

                for group_label in group_labels:
                    for field, value in estimate_values.items():
                        a = estimate_acc[group_label][field]
                        a["n"] += 1
                        a["weight"] += weight
                        a["weighted_value"] += weight * value
                        if value > 0:
                            a["reporting_n"] += 1
                            a["reporting_weight"] += weight

    except Exception as exc:
        errors.append(f"Household asset fact build failed: {type(exc).__name__}: {exc}")

    if fact_rows_written != EXPECTED_STOCK_HOUSEHOLDS:
        errors.append(
            f"Household asset fact should contain {EXPECTED_STOCK_HOUSEHOLDS:,} rows; "
            f"wrote {fact_rows_written:,}"
        )
    if balance_errors:
        errors.append(f"Physical + financial balance errors: {balance_errors}")
    if negative_total_assets:
        warnings.append(
            f"{negative_total_assets} household(s) have negative net total assets. "
            "These are retained as reported/reconstructed because Block 13 permits "
            "signed financial-asset values. They are not coerced to zero or absolute values."
        )

    print(f"Household asset rows       : {fact_rows_written:,}")
    print(f"Negative total assets      : {negative_total_assets}")
    print(f"Component balance errors   : {balance_errors}")

    # -------------------------------------------------------------------------
    # 4. Official Report No. 500 AVA controls
    # -------------------------------------------------------------------------
    print("\n[4] Official Report No. 500 AVA controls")
    ava_rows = []
    failed_controls = 0

    for control in OFFICIAL_AVA_CONTROLS:
        acc = control_acc[control["selector"]]
        observed = acc["weighted_assets"] / acc["weight"] if acc["weight"] else None
        expected = control["expected_ava_rs"]
        abs_diff = observed - expected if observed is not None else None
        pct_diff = (100.0 * abs_diff / expected) if observed is not None and expected else None
        count_ok = acc["n"] == control["expected_sample_households"]
        ava_ok = observed is not None and abs(pct_diff) <= (AVA_REL_TOLERANCE * 100.0)
        passed = count_ok and ava_ok
        if not passed:
            failed_controls += 1
            errors.append(
                f"AVA control failed for {control['control']}: expected n={control['expected_sample_households']}, "
                f"AVA={expected}; observed n={acc['n']}, AVA={observed}"
            )

        ava_rows.append({
            "control": control["control"],
            "selector": control["selector"],
            "expected_sample_households": control["expected_sample_households"],
            "observed_sample_households": acc["n"],
            "expected_ava_rs": f"{expected:.2f}",
            "observed_ava_rs": "" if observed is None else f"{observed:.6f}",
            "difference_rs": "" if abs_diff is None else f"{abs_diff:.6f}",
            "difference_percent": "" if pct_diff is None else f"{pct_diff:.6f}",
            "tolerance_percent": f"{AVA_REL_TOLERANCE * 100:.3f}",
            "status": "PASS" if passed else "FAIL",
            "note": "Official residual group used only for Report 500 QA" if "residual" in control["selector"].casefold() else "",
        })

        obs_text = "n/a" if observed is None else f"{observed:,.2f}"
        diff_text = "n/a" if pct_diff is None else f"{pct_diff:+.3f}%"
        print(
            f"{'PASS' if passed else 'FAIL':4s} | {control['control']:<45s} | "
            f"official={expected:>10,.0f} | microdata={obs_text:>12s} | {diff_text}"
        )

    with AVA_CONTROL_FILE.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "control", "selector", "expected_sample_households",
            "observed_sample_households", "expected_ava_rs", "observed_ava_rs",
            "difference_rs", "difference_percent", "tolerance_percent", "status", "note",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ava_rows)

    # -------------------------------------------------------------------------
    # 5. Component estimates for downstream Step 05
    # -------------------------------------------------------------------------
    component_label_map = {x["output_field"]: x["label"] for x in ASSET_BLOCKS}
    component_label_map.update({
        "Physical_Assets_Rs": "Physical assets - total",
        "Financial_Assets_Rs": "Financial assets - total",
        "Total_Assets_Rs": "All assets",
    })

    component_rows = []
    for group_label in sorted(estimate_acc):
        for field in component_fields + ["Physical_Assets_Rs", "Financial_Assets_Rs", "Total_Assets_Rs"]:
            a = estimate_acc[group_label][field]
            ava = a["weighted_value"] / a["weight"] if a["weight"] else None
            reporting_per_1000 = 1000.0 * a["reporting_weight"] / a["weight"] if a["weight"] else None
            component_rows.append({
                "group": group_label,
                "component_field": field,
                "component": component_label_map[field],
                "sample_households": a["n"],
                "weight_sum": f"{a['weight']:.6f}",
                "sample_households_reporting_positive": a["reporting_n"],
                "weighted_reporting_per_1000": "" if reporting_per_1000 is None else f"{reporting_per_1000:.6f}",
                "average_value_per_household_rs": "" if ava is None else f"{ava:.6f}",
            })

    with COMPONENT_ESTIMATES_FILE.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "group", "component_field", "component", "sample_households", "weight_sum",
            "sample_households_reporting_positive", "weighted_reporting_per_1000",
            "average_value_per_household_rs",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(component_rows)

    # -------------------------------------------------------------------------
    # 6. Summary
    # -------------------------------------------------------------------------
    status = "PASS" if not errors else "FAIL"

    summary_lines = [
        "=" * 78,
        "AIDIS 2003 - STEP 03 ASSET FACTS / AVA SUMMARY",
        "=" * 78,
        f"Stock household universe      : {len(base):,}",
        f"Household asset fact rows     : {fact_rows_written:,}",
        f"Asset components              : {len(ASSET_BLOCKS)}",
        f"Official AVA controls         : {len(OFFICIAL_AVA_CONTROLS)}",
        f"Failed AVA controls           : {failed_controls}",
        f"Negative total assets         : {negative_total_assets}",
        f"Component balance errors      : {balance_errors}",
        f"Warnings                      : {len(warnings)}",
        f"Errors                        : {len(errors)}",
        "",
        "LOCKED ASSET RULES:",
        "  - Reference date: 30-06-2002.",
        "  - Use Visit-1 stock household base.",
        "  - Use official asset-block total/control rows only.",
        "  - Use direct schedule 30-06-2002 value fields as authoritative.",
        "  - Block 14 is loans receivable and remains on the asset side.",
        "  - Weight is applied once per household only after asset aggregation.",
        "  - B13 sign=1 is interpreted as a negative absolute value per schedule footnote.",
        "",
        f"Household asset facts         : {ASSET_FACT_FILE}",
        f"Block audit                   : {BLOCK_AUDIT_FILE}",
        f"AVA controls                  : {AVA_CONTROL_FILE}",
        f"Component estimates           : {COMPONENT_ESTIMATES_FILE}",
        f"Summary                       : {SUMMARY_FILE}",
    ]

    if warnings:
        summary_lines.append("")
        summary_lines.append("WARNINGS (NONBLOCKING):")
        summary_lines.extend(f"  - {x}" for x in warnings)

    if errors:
        summary_lines.append("")
        summary_lines.append("ERRORS:")
        summary_lines.extend(f"  - {x}" for x in errors)

    summary_lines.extend(["", f"STEP 03 STATUS: {status}", "=" * 78])
    SUMMARY_FILE.write_text("\n".join(summary_lines), encoding="utf-8")

    print("\n" + "=" * 78)
    print("AIDIS 2003 - STEP 03 SUMMARY")
    print("=" * 78)
    print(f"Stock household universe     : {len(base):,}")
    print(f"Household asset fact rows    : {fact_rows_written:,}")
    print(f"Asset components             : {len(ASSET_BLOCKS)}")
    print(f"Official AVA controls        : {len(OFFICIAL_AVA_CONTROLS)}")
    print(f"Failed AVA controls          : {failed_controls}")
    print(f"Warnings                     : {len(warnings)}")
    print(f"Errors                       : {len(errors)}")
    print(f"Household asset facts        : {ASSET_FACT_FILE}")
    print(f"Block audit                  : {BLOCK_AUDIT_FILE}")
    print(f"AVA controls                 : {AVA_CONTROL_FILE}")
    print(f"Component estimates          : {COMPONENT_ESTIMATES_FILE}")
    print(f"Summary                      : {SUMMARY_FILE}")
    print()
    print(f"STEP 03 STATUS: {status}")
    print("=" * 78)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())