from pathlib import Path
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict


# =============================================================================
# AIDIS 2003 - STEP 02 HOUSEHOLD BASE
# NSS 59th Round, Schedule 18.2 (Debt & Investment)
#
# Builds two one-row-per-household bases:
#   1) Stock base: Visit-1 universe (assets/debt as on 30-06-2002)
#   2) Flow-panel base: households present in both visits, keyed by PANEL_HHID
#
# IMPORTANT:
# - No one-to-many asset/debt/expenditure block is joined here.
# - Weight is carried once per household and must never be repeated at fact-row
#   level for estimation.
# - Survey-era State/District codes are preserved exactly as supplied.
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
CONFIG_DIR = ROOT / "config"
WORK_DIR = ROOT / "work"
REPORT_DIR = ROOT / "output" / "reports"

PRODUCTION_MANIFEST = CACHE_DIR / "step01_production_manifest.csv"
METHODOLOGY_FILE = CONFIG_DIR / "aidis_2003_methodology_lock.json"

STOCK_BASE_FILE = WORK_DIR / "step02_household_base_stock.csv"
PANEL_BASE_FILE = WORK_DIR / "step02_household_base_panel.csv"
QA_FILE = CACHE_DIR / "step02_household_base_checks.csv"
GROUP_COUNTS_FILE = CACHE_DIR / "step02_household_group_counts.csv"
GEOGRAPHY_FILE = CACHE_DIR / "step02_geography_inventory.csv"
VISIT2_B3_UPDATES_FILE = CACHE_DIR / "step02_combined_block3_visit2_updates.csv"
SUMMARY_FILE = REPORT_DIR / "step02_household_base_summary.txt"

# Locked package controls established in Step 01B-C.
EXPECTED_STOCK_HOUSEHOLDS = 143_285
EXPECTED_STOCK_SECTOR = {"1": 91_192, "2": 52_093}
EXPECTED_PANEL_HOUSEHOLDS = 139_039
EXPECTED_PANEL_SECTOR = {"1": 89_718, "2": 49_321}
EXPECTED_COMBINED_IDENTIFICATION_ROWS = 278_078

STOCK_IDENTIFICATION = "Visit1_Blocks_1_and_2"
STOCK_BLOCK3 = "Visit1_Block_3"
COMBINED_IDENTIFICATION = "Visit1and2_CBlocks_1and2"
COMBINED_BLOCK3 = "Visit1and2_CB_3"

ID_REQUIRED_FIELDS = [
    "HHID", "Sector", "State_Region", "State", "District", "Visit_no",
    "NSS", "NSC", "MLT", "Weight",
]

BLOCK3_REQUIRED_FIELDS = [
    "HHID", "Sector", "State", "District", "Visit_no", "B3_q1",
    "B3_q4", "B3_q7", "B3_q8", "NSS", "NSC", "MLT", "Weight",
]

# Identification fields carried to the base. Missing optional fields are written
# blank rather than causing failure; required linkage/weight fields are validated.
ID_CARRY_FIELDS = [
    "CentreCodeRndShift", "Vill_Blk_Slno", "Round", "Schedule", "Sample",
    "Sector", "State_Region", "State", "District", "Stratum", "SubRound",
    "SubSample", "FOD_SubRegion", "HG_SubBlkNo", "Second_Stratum",
    "Hhold_no", "Level", "NSS", "NSC", "MLT", "Weight", "Survey_Date",
]

BLOCK3_CARRY_FIELDS = [
    "B3_q1", "B3_q2", "B3_q3", "B3_q4", "HH_Type", "B3_q5", "B3_q6",
    "B3_q7", "B3_q8", "B3_q9", "B3_q10", "B3_q11", "B3_q12",
    "B3_q13", "B3_q14",
]

SECTOR_NAMES = {"1": "Rural", "2": "Urban"}


# =============================================================================
# HELPERS
# =============================================================================

def clean(value):
    return "" if value is None else str(value).strip()


def norm_name(value):
    return re.sub(r"[^a-z0-9]+", "", clean(value).casefold())


def as_float(value):
    text = clean(value)
    if not text:
        return None
    return float(text)


def nearly_equal(a, b):
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=5e-7)


def add_check(rows, check, expected, observed, passed, note=""):
    rows.append({
        "check": check,
        "expected": str(expected),
        "observed": str(observed),
        "status": "PASS" if passed else "FAIL",
        "note": note,
    })


def read_manifest():
    if not PRODUCTION_MANIFEST.exists():
        raise FileNotFoundError(
            f"Missing production manifest: {PRODUCTION_MANIFEST}. Run Step 01D first."
        )
    with PRODUCTION_MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 42:
        raise ValueError(f"Production manifest must contain 42 datasets; found {len(rows)}")
    failed = [r for r in rows if clean(r.get("status")).upper() != "PASS"]
    if failed:
        raise ValueError(f"Production manifest has {len(failed)} non-PASS rows")
    return rows


def find_manifest_source(manifest, logical_dataset):
    target = norm_name(logical_dataset)
    matches = [r for r in manifest if norm_name(r.get("logical_dataset")) == target]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one manifest source for {logical_dataset}; found {len(matches)}"
        )
    path = Path(matches[0]["source_path"])
    if not path.exists():
        raise FileNotFoundError(f"Manifest source missing: {path}")
    if path.suffix.casefold() != ".csv":
        raise ValueError(
            f"Step 02 expects CSV for {logical_dataset}; got {path.name}"
        )
    return path


def load_methodology():
    if not METHODOLOGY_FILE.exists():
        raise FileNotFoundError(
            f"Missing methodology lock: {METHODOLOGY_FILE}. Run Step 01B-C first."
        )
    with METHODOLOGY_FILE.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    if config.get("methodology_lock_status") != "LOCKED":
        raise ValueError("Methodology configuration is not LOCKED")

    estimation = config.get("estimation", {})
    if estimation.get("locked_weight_field") != "Weight":
        raise ValueError("Methodology lock does not specify Weight as estimator field")

    return config


def open_csv_dict(path):
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
    raise RuntimeError(f"Unable to read {path.name}: {last_error}")


def require_fields(fieldnames, required, dataset_label):
    present = {norm_name(x): x for x in fieldnames or []}
    missing = [x for x in required if norm_name(x) not in present]
    if missing:
        raise ValueError(f"{dataset_label}: missing fields {missing}")


def derive_panel_hhid(hhid, visit_no):
    hhid = clean(hhid)
    visit_no = clean(visit_no)
    if len(hhid) != 10:
        return None, "HHID length is not 10"
    if visit_no not in {"1", "2"}:
        return None, f"unexpected Visit_no={visit_no!r}"
    if hhid[7] != visit_no:
        return None, f"HHID visit digit {hhid[7]!r} != Visit_no {visit_no!r}"
    return hhid[:7] + hhid[8:], ""


def compare_core(id_row, b3_row):
    """Return list of core mismatches between identification and Block 3."""
    mismatches = []
    for field in ("Sector", "State", "District", "Visit_no"):
        if clean(id_row.get(field)) != clean(b3_row.get(field)):
            mismatches.append(field)

    try:
        a = as_float(id_row.get("Weight"))
        b = as_float(b3_row.get("Weight"))
        if not nearly_equal(a, b):
            mismatches.append("Weight")
    except Exception:
        mismatches.append("Weight")

    return mismatches


def classify_household(sector, b3_q4, b3_q7, b3_q8):
    """
    Apply only the Step 01B-C locked definitions.

    Rural:
      cultivator     -> B3_q8 >= 0.002 hectare
      non-cultivator -> B3_q8 < 0.002 OR explicit B3_q7 == 2 when area blank
      otherwise      -> unclassified (do not invent area)

    Urban:
      self-employed  -> B3_q4 == 1
      others          -> B3_q4 in {2,3,9}
      otherwise       -> unclassified
    """
    sector = clean(sector)
    q4 = clean(b3_q4)
    q7 = clean(b3_q7)
    q8_text = clean(b3_q8)

    if sector == "1":
        if q8_text:
            try:
                area = float(q8_text)
                if area >= 0.002:
                    return (
                        "R_CULTIVATOR", "Rural Cultivator", "CLASSIFIED",
                        "B3_q8 >= 0.002 hectare", area,
                    )
                return (
                    "R_NON_CULTIVATOR", "Rural Non-cultivator", "CLASSIFIED",
                    "B3_q8 < 0.002 hectare", area,
                )
            except ValueError:
                return (
                    "R_UNCLASSIFIED", "Rural Unclassified", "UNCLASSIFIED",
                    "B3_q8 is non-numeric", None,
                )

        if q7 == "2":
            return (
                "R_NON_CULTIVATOR", "Rural Non-cultivator", "CLASSIFIED",
                "B3_q7 explicitly indicates no operated agricultural land", None,
            )

        return (
            "R_UNCLASSIFIED", "Rural Unclassified", "UNCLASSIFIED",
            "B3_q8 missing without an explicit no-land response", None,
        )

    if sector == "2":
        if q4 == "1":
            return (
                "U_SELF_EMPLOYED", "Urban Self-employed", "CLASSIFIED",
                "B3_q4 = 1", None,
            )
        if q4 in {"2", "3", "9"}:
            return (
                "U_OTHERS", "Urban Others", "CLASSIFIED",
                f"B3_q4 = {q4}", None,
            )
        return (
            "U_UNCLASSIFIED", "Urban Unclassified", "UNCLASSIFIED",
            "B3_q4 missing or outside locked urban codes {1,2,3,9}", None,
        )

    return (
        "SECTOR_UNCLASSIFIED", "Sector Unclassified", "UNCLASSIFIED",
        f"Unexpected Sector={sector!r}", None,
    )


def load_block3(path, mode):
    """
    mode='stock'    -> all rows must be Visit 1; keyed by raw HHID.
    mode='combined' -> Visit-1 rows are baseline panel characteristics;
                       Visit-2 rows are retained separately as update records.
    """
    baseline = {}
    update_rows = []
    duplicates = 0
    rows = 0
    visit_counts = Counter()

    handle, reader, encoding = open_csv_dict(path)
    try:
        require_fields(reader.fieldnames, BLOCK3_REQUIRED_FIELDS, path.name)
        for row in reader:
            rows += 1
            visit = clean(row.get("Visit_no"))
            visit_counts[visit] += 1
            hhid = clean(row.get("HHID"))

            if mode == "stock":
                if visit != "1":
                    raise ValueError(f"{path.name}: non-Visit1 row {hhid} Visit_no={visit}")
                if hhid in baseline:
                    duplicates += 1
                baseline[hhid] = {k: clean(row.get(k)) for k in BLOCK3_CARRY_FIELDS + [
                    "Sector", "State", "District", "Visit_no", "Weight"
                ]}

            elif mode == "combined":
                if visit == "1":
                    if hhid in baseline:
                        duplicates += 1
                    baseline[hhid] = {k: clean(row.get(k)) for k in BLOCK3_CARRY_FIELDS + [
                        "Sector", "State", "District", "Visit_no", "Weight"
                    ]}
                elif visit == "2":
                    update_rows.append({k: clean(row.get(k)) for k in ([
                        "HHID", "Sector", "State_Region", "State", "District", "Visit_no",
                        "Hhold_no", "Weight"
                    ] + BLOCK3_CARRY_FIELDS)})
                else:
                    raise ValueError(f"{path.name}: unexpected Visit_no={visit!r}")
            else:
                raise ValueError(f"Unsupported Block3 mode: {mode}")
    finally:
        handle.close()

    return {
        "baseline": baseline,
        "update_rows": update_rows,
        "rows": rows,
        "visit_counts": visit_counts,
        "duplicates": duplicates,
        "encoding": encoding,
    }


def scan_combined_identification(path):
    """Build minimal panel pairing map and validate visit stability."""
    panels = {}
    rows = 0
    visit_counts = Counter()
    format_errors = 0
    geo_mismatches = 0
    weight_mismatches = 0
    duplicate_visit_rows = 0

    handle, reader, encoding = open_csv_dict(path)
    try:
        require_fields(reader.fieldnames, ID_REQUIRED_FIELDS, path.name)
        for row in reader:
            rows += 1
            visit = clean(row.get("Visit_no"))
            visit_counts[visit] += 1
            hhid = clean(row.get("HHID"))
            panel, err = derive_panel_hhid(hhid, visit)
            if panel is None:
                format_errors += 1
                continue

            entry = panels.setdefault(panel, {
                "visit1_hhid": "",
                "visit2_hhid": "",
                "sector": "",
                "state": "",
                "district": "",
                "weight": None,
                "mask": 0,
            })

            bit = 1 if visit == "1" else 2
            if entry["mask"] & bit:
                duplicate_visit_rows += 1
            entry["mask"] |= bit

            if visit == "1":
                entry["visit1_hhid"] = hhid
            else:
                entry["visit2_hhid"] = hhid

            sector = clean(row.get("Sector"))
            state = clean(row.get("State"))
            district = clean(row.get("District"))
            try:
                weight = as_float(row.get("Weight"))
            except Exception:
                weight = None

            if not entry["sector"]:
                entry["sector"] = sector
                entry["state"] = state
                entry["district"] = district
                entry["weight"] = weight
            else:
                if (entry["sector"], entry["state"], entry["district"]) != (
                    sector, state, district
                ):
                    geo_mismatches += 1
                if not nearly_equal(entry["weight"], weight):
                    weight_mismatches += 1
    finally:
        handle.close()

    complete = sum(1 for v in panels.values() if v["mask"] == 3)
    incomplete = len(panels) - complete

    return {
        "panels": panels,
        "rows": rows,
        "visit_counts": visit_counts,
        "format_errors": format_errors,
        "geo_mismatches": geo_mismatches,
        "weight_mismatches": weight_mismatches,
        "duplicate_visit_rows": duplicate_visit_rows,
        "complete": complete,
        "incomplete": incomplete,
        "encoding": encoding,
    }


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sorted_counter_rows(universe, counter, weight_counter):
    result = []
    for group in sorted(counter):
        sector = "Rural" if group.startswith("Rural") else "Urban" if group.startswith("Urban") else ""
        result.append({
            "universe": universe,
            "sector": sector,
            "household_group": group,
            "surveyed_households": counter[group],
            "weight_sum": f"{weight_counter[group]:.10f}",
        })
    return result


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 78)
    print("AIDIS 2003 - STEP 02 HOUSEHOLD BASE")
    print("Build Visit-1 stock base + paired Visit1/Visit2 flow-panel base")
    print("=" * 78)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    checks = []
    errors = []
    warnings = []

    # -------------------------------------------------------------------------
    # 1. Prerequisites / sources
    # -------------------------------------------------------------------------
    print("\n[1] Step prerequisites and locked sources")
    try:
        manifest = read_manifest()
        methodology = load_methodology()

        stock_id_path = find_manifest_source(manifest, STOCK_IDENTIFICATION)
        stock_b3_path = find_manifest_source(manifest, STOCK_BLOCK3)
        combined_id_path = find_manifest_source(manifest, COMBINED_IDENTIFICATION)
        combined_b3_path = find_manifest_source(manifest, COMBINED_BLOCK3)

        stock_ref_date = methodology.get("survey", {}).get(
            "stock_reference_date", "2002-06-30"
        )
        flow_period = methodology.get("survey", {}).get(
            "capital_expenditure_reference_period", {}
        )
        flow_start = flow_period.get("start", "2002-07-01")
        flow_end = flow_period.get("end", "2003-06-30")

        print(f"Methodology lock         : PASS")
        print(f"Stock identification     : {stock_id_path.name}")
        print(f"Stock Block 3            : {stock_b3_path.name}")
        print(f"Combined identification  : {combined_id_path.name}")
        print(f"Combined Block 3         : {combined_b3_path.name}")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print("\nSTEP 02 STATUS: FAIL")
        return 1

    # -------------------------------------------------------------------------
    # 2. Load Block 3 household characteristics
    # -------------------------------------------------------------------------
    print("\n[2] Household-characteristics inputs")
    try:
        stock_b3 = load_block3(stock_b3_path, "stock")
        combined_b3 = load_block3(combined_b3_path, "combined")

        print(f"Visit1 Block3 rows        : {stock_b3['rows']:,}")
        print(f"Visit1 Block3 unique HHID : {len(stock_b3['baseline']):,}")
        print(f"Combined Block3 rows      : {combined_b3['rows']:,}")
        print(f"  Visit1 baseline rows    : {combined_b3['visit_counts']['1']:,}")
        print(f"  Visit2 update rows      : {combined_b3['visit_counts']['2']:,}")

        add_check(
            checks, "visit1_block3_rows", EXPECTED_STOCK_HOUSEHOLDS,
            stock_b3["rows"], stock_b3["rows"] == EXPECTED_STOCK_HOUSEHOLDS,
        )
        add_check(
            checks, "visit1_block3_unique_hhid", EXPECTED_STOCK_HOUSEHOLDS,
            len(stock_b3["baseline"]),
            len(stock_b3["baseline"]) == EXPECTED_STOCK_HOUSEHOLDS,
        )
        add_check(checks, "visit1_block3_duplicates", 0, stock_b3["duplicates"], stock_b3["duplicates"] == 0)
        add_check(
            checks, "combined_block3_visit1_baseline_rows",
            EXPECTED_PANEL_HOUSEHOLDS, combined_b3["visit_counts"]["1"],
            combined_b3["visit_counts"]["1"] == EXPECTED_PANEL_HOUSEHOLDS,
            "Visit-1 Block3 row is used as the canonical household-characteristics record for the paired panel base.",
        )
        add_check(checks, "combined_block3_visit1_duplicates", 0, combined_b3["duplicates"], combined_b3["duplicates"] == 0)

        # Visit-2 Block3 rows are retained as updates rather than creating extra
        # panel-household rows. This protects the one-row-per-PANEL_HHID grain.
        write_csv(
            VISIT2_B3_UPDATES_FILE,
            [
                "HHID", "Sector", "State_Region", "State", "District", "Visit_no",
                "Hhold_no", "Weight"
            ] + BLOCK3_CARRY_FIELDS,
            combined_b3["update_rows"],
        )
        if combined_b3["visit_counts"]["2"]:
            warnings.append(
                f"Combined Block3 contains {combined_b3['visit_counts']['2']} Visit-2 "
                "household-characteristic update row(s). They were saved separately and "
                "not allowed to duplicate PANEL_HHID rows."
            )
    except Exception as exc:
        errors.append(f"Block3 load failed: {type(exc).__name__}: {exc}")
        print(f"ERROR: {errors[-1]}")
        stock_b3 = {"baseline": {}}
        combined_b3 = {"baseline": {}, "update_rows": [], "visit_counts": Counter()}

    # -------------------------------------------------------------------------
    # 3. Build Visit-1 stock household base
    # -------------------------------------------------------------------------
    print("\n[3] Build Visit-1 stock household base")

    stock_fields = (
        ["HHID", "Sector_Name"]
        + ID_CARRY_FIELDS
        + BLOCK3_CARRY_FIELDS
        + [
            "Household_Size", "Operated_Area_Ha", "Household_Group_Code",
            "Household_Group", "Group_Classification_Status",
            "Group_Classification_Reason", "Stock_Reference_Date",
            "Base_Universe",
        ]
    )

    stock_rows_written = 0
    stock_seen_hhid = set()
    stock_sector = Counter()
    stock_weight_missing = 0
    stock_weight_nonpositive = 0
    stock_geo_missing = 0
    stock_core_mismatch = 0
    stock_group_counts = Counter()
    stock_group_weight = defaultdict(float)
    stock_geo_counts = Counter()
    stock_geo_weight = defaultdict(float)

    try:
        handle, reader, _ = open_csv_dict(stock_id_path)
        try:
            require_fields(reader.fieldnames, ID_REQUIRED_FIELDS, stock_id_path.name)
            with STOCK_BASE_FILE.open("w", encoding="utf-8", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=stock_fields)
                writer.writeheader()

                for id_row in reader:
                    hhid = clean(id_row.get("HHID"))
                    visit = clean(id_row.get("Visit_no"))
                    if visit != "1":
                        errors.append(f"Stock identification contains non-Visit1 HHID {hhid}")
                        continue

                    if hhid in stock_seen_hhid:
                        errors.append(f"Duplicate stock HHID in identification: {hhid}")
                        continue
                    stock_seen_hhid.add(hhid)

                    b3 = stock_b3["baseline"].get(hhid)
                    if b3 is None:
                        errors.append(f"Stock HHID missing from Block3: {hhid}")
                        continue

                    mismatch = compare_core(id_row, b3)
                    if mismatch:
                        stock_core_mismatch += 1

                    sector = clean(id_row.get("Sector"))
                    state = clean(id_row.get("State"))
                    district = clean(id_row.get("District"))
                    stock_sector[sector] += 1

                    try:
                        weight = as_float(id_row.get("Weight"))
                    except Exception:
                        weight = None
                    if weight is None:
                        stock_weight_missing += 1
                        weight_for_sum = 0.0
                    else:
                        weight_for_sum = weight
                        if weight <= 0:
                            stock_weight_nonpositive += 1

                    if not state or not district:
                        stock_geo_missing += 1

                    group_code, group_name, class_status, class_reason, area = classify_household(
                        sector, b3.get("B3_q4"), b3.get("B3_q7"), b3.get("B3_q8")
                    )
                    stock_group_counts[group_name] += 1
                    stock_group_weight[group_name] += weight_for_sum
                    stock_geo_counts[(state, district, sector)] += 1
                    stock_geo_weight[(state, district, sector)] += weight_for_sum

                    out_row = {
                        "HHID": hhid,
                        "Sector_Name": SECTOR_NAMES.get(sector, "Unclassified"),
                        "Household_Size": clean(b3.get("B3_q1")),
                        "Operated_Area_Ha": "" if area is None else f"{area:.6f}",
                        "Household_Group_Code": group_code,
                        "Household_Group": group_name,
                        "Group_Classification_Status": class_status,
                        "Group_Classification_Reason": class_reason,
                        "Stock_Reference_Date": stock_ref_date,
                        "Base_Universe": "Visit1 stock universe",
                    }
                    for field in ID_CARRY_FIELDS:
                        out_row[field] = clean(id_row.get(field))
                    for field in BLOCK3_CARRY_FIELDS:
                        out_row[field] = clean(b3.get(field))

                    writer.writerow(out_row)
                    stock_rows_written += 1
        finally:
            handle.close()

        missing_in_identification = set(stock_b3["baseline"]) - stock_seen_hhid

        add_check(checks, "stock_base_rows", EXPECTED_STOCK_HOUSEHOLDS, stock_rows_written, stock_rows_written == EXPECTED_STOCK_HOUSEHOLDS)
        add_check(checks, "stock_identification_unique_hhid", EXPECTED_STOCK_HOUSEHOLDS, len(stock_seen_hhid), len(stock_seen_hhid) == EXPECTED_STOCK_HOUSEHOLDS)
        add_check(checks, "stock_block3_not_in_identification", 0, len(missing_in_identification), len(missing_in_identification) == 0)
        add_check(checks, "stock_sector_rural", EXPECTED_STOCK_SECTOR["1"], stock_sector["1"], stock_sector["1"] == EXPECTED_STOCK_SECTOR["1"])
        add_check(checks, "stock_sector_urban", EXPECTED_STOCK_SECTOR["2"], stock_sector["2"], stock_sector["2"] == EXPECTED_STOCK_SECTOR["2"])
        add_check(checks, "stock_missing_weight", 0, stock_weight_missing, stock_weight_missing == 0)
        add_check(checks, "stock_nonpositive_weight", 0, stock_weight_nonpositive, stock_weight_nonpositive == 0)
        add_check(checks, "stock_missing_state_or_district", 0, stock_geo_missing, stock_geo_missing == 0)
        add_check(checks, "stock_identification_block3_core_mismatch", 0, stock_core_mismatch, stock_core_mismatch == 0)

        print(f"Stock base rows            : {stock_rows_written:,}")
        print(f"Stock rural / urban        : {stock_sector['1']:,} / {stock_sector['2']:,}")
        print(f"Stock core mismatches      : {stock_core_mismatch}")
    except Exception as exc:
        errors.append(f"Stock base build failed: {type(exc).__name__}: {exc}")
        print(f"ERROR: {errors[-1]}")

    # -------------------------------------------------------------------------
    # 4. Validate pair structure and build panel household base
    # -------------------------------------------------------------------------
    print("\n[4] Build paired Visit1/Visit2 flow-panel household base")

    panel_fields = (
        ["PANEL_HHID", "HHID_Visit1", "HHID_Visit2", "Sector_Name"]
        + ID_CARRY_FIELDS
        + ["Survey_Date_Visit2"]
        + BLOCK3_CARRY_FIELDS
        + [
            "Household_Size", "Operated_Area_Ha", "Household_Group_Code",
            "Household_Group", "Group_Classification_Status",
            "Group_Classification_Reason", "Household_Group_Basis",
            "Flow_Reference_Start", "Flow_Reference_End", "Base_Universe",
        ]
    )

    panel_rows_written = 0
    panel_seen = set()
    panel_sector = Counter()
    panel_weight_missing = 0
    panel_weight_nonpositive = 0
    panel_geo_missing = 0
    panel_core_mismatch = 0
    panel_missing_b3 = 0
    panel_group_counts = Counter()
    panel_group_weight = defaultdict(float)
    panel_geo_counts = Counter()
    panel_geo_weight = defaultdict(float)

    try:
        combined_scan = scan_combined_identification(combined_id_path)

        add_check(checks, "combined_identification_rows", EXPECTED_COMBINED_IDENTIFICATION_ROWS, combined_scan["rows"], combined_scan["rows"] == EXPECTED_COMBINED_IDENTIFICATION_ROWS)
        add_check(checks, "combined_complete_panels", EXPECTED_PANEL_HOUSEHOLDS, combined_scan["complete"], combined_scan["complete"] == EXPECTED_PANEL_HOUSEHOLDS)
        add_check(checks, "combined_incomplete_panels", 0, combined_scan["incomplete"], combined_scan["incomplete"] == 0)
        add_check(checks, "combined_panel_format_errors", 0, combined_scan["format_errors"], combined_scan["format_errors"] == 0)
        add_check(checks, "combined_panel_geo_mismatches", 0, combined_scan["geo_mismatches"], combined_scan["geo_mismatches"] == 0)
        add_check(checks, "combined_panel_weight_mismatches", 0, combined_scan["weight_mismatches"], combined_scan["weight_mismatches"] == 0)
        add_check(checks, "combined_duplicate_visit_rows", 0, combined_scan["duplicate_visit_rows"], combined_scan["duplicate_visit_rows"] == 0)

        # Map Visit-2 survey date by PANEL_HHID. We then stream Visit-1 rows to
        # construct exactly one panel-base row per complete household.
        visit2_survey_date = {}
        handle, reader, _ = open_csv_dict(combined_id_path)
        try:
            for row in reader:
                if clean(row.get("Visit_no")) != "2":
                    continue
                panel, _ = derive_panel_hhid(row.get("HHID"), "2")
                if panel:
                    visit2_survey_date[panel] = clean(row.get("Survey_Date"))
        finally:
            handle.close()

        handle, reader, _ = open_csv_dict(combined_id_path)
        try:
            require_fields(reader.fieldnames, ID_REQUIRED_FIELDS, combined_id_path.name)
            with PANEL_BASE_FILE.open("w", encoding="utf-8", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=panel_fields)
                writer.writeheader()

                for id_row in reader:
                    if clean(id_row.get("Visit_no")) != "1":
                        continue

                    hhid_v1 = clean(id_row.get("HHID"))
                    panel, err = derive_panel_hhid(hhid_v1, "1")
                    if panel is None:
                        continue
                    pair = combined_scan["panels"].get(panel)
                    if not pair or pair["mask"] != 3:
                        continue

                    if panel in panel_seen:
                        errors.append(f"Duplicate PANEL_HHID while writing base: {panel}")
                        continue
                    panel_seen.add(panel)

                    b3 = combined_b3["baseline"].get(hhid_v1)
                    if b3 is None:
                        panel_missing_b3 += 1
                        continue

                    mismatch = compare_core(id_row, b3)
                    if mismatch:
                        panel_core_mismatch += 1

                    sector = clean(id_row.get("Sector"))
                    state = clean(id_row.get("State"))
                    district = clean(id_row.get("District"))
                    panel_sector[sector] += 1

                    try:
                        weight = as_float(id_row.get("Weight"))
                    except Exception:
                        weight = None
                    if weight is None:
                        panel_weight_missing += 1
                        weight_for_sum = 0.0
                    else:
                        weight_for_sum = weight
                        if weight <= 0:
                            panel_weight_nonpositive += 1

                    if not state or not district:
                        panel_geo_missing += 1

                    group_code, group_name, class_status, class_reason, area = classify_household(
                        sector, b3.get("B3_q4"), b3.get("B3_q7"), b3.get("B3_q8")
                    )
                    panel_group_counts[group_name] += 1
                    panel_group_weight[group_name] += weight_for_sum
                    panel_geo_counts[(state, district, sector)] += 1
                    panel_geo_weight[(state, district, sector)] += weight_for_sum

                    out_row = {
                        "PANEL_HHID": panel,
                        "HHID_Visit1": hhid_v1,
                        "HHID_Visit2": pair["visit2_hhid"],
                        "Sector_Name": SECTOR_NAMES.get(sector, "Unclassified"),
                        "Survey_Date_Visit2": visit2_survey_date.get(panel, ""),
                        "Household_Size": clean(b3.get("B3_q1")),
                        "Operated_Area_Ha": "" if area is None else f"{area:.6f}",
                        "Household_Group_Code": group_code,
                        "Household_Group": group_name,
                        "Group_Classification_Status": class_status,
                        "Group_Classification_Reason": class_reason,
                        "Household_Group_Basis": "Combined Block3 Visit-1 baseline record",
                        "Flow_Reference_Start": flow_start,
                        "Flow_Reference_End": flow_end,
                        "Base_Universe": "Paired Visit1+Visit2 flow universe",
                    }
                    for field in ID_CARRY_FIELDS:
                        out_row[field] = clean(id_row.get(field))
                    for field in BLOCK3_CARRY_FIELDS:
                        out_row[field] = clean(b3.get(field))

                    writer.writerow(out_row)
                    panel_rows_written += 1
        finally:
            handle.close()

        block3_baseline_set = set(combined_b3["baseline"])
        paired_visit1_set = {
            v["visit1_hhid"] for v in combined_scan["panels"].values() if v["mask"] == 3
        }
        b3_missing_for_panel = paired_visit1_set - block3_baseline_set
        b3_extra_baseline = block3_baseline_set - paired_visit1_set

        add_check(checks, "panel_base_rows", EXPECTED_PANEL_HOUSEHOLDS, panel_rows_written, panel_rows_written == EXPECTED_PANEL_HOUSEHOLDS)
        add_check(checks, "panel_base_unique_panel_hhid", EXPECTED_PANEL_HOUSEHOLDS, len(panel_seen), len(panel_seen) == EXPECTED_PANEL_HOUSEHOLDS)
        add_check(checks, "panel_sector_rural", EXPECTED_PANEL_SECTOR["1"], panel_sector["1"], panel_sector["1"] == EXPECTED_PANEL_SECTOR["1"])
        add_check(checks, "panel_sector_urban", EXPECTED_PANEL_SECTOR["2"], panel_sector["2"], panel_sector["2"] == EXPECTED_PANEL_SECTOR["2"])
        add_check(checks, "panel_missing_block3_baseline", 0, len(b3_missing_for_panel), len(b3_missing_for_panel) == 0)
        add_check(checks, "panel_extra_block3_visit1_baseline", 0, len(b3_extra_baseline), len(b3_extra_baseline) == 0)
        add_check(checks, "panel_missing_weight", 0, panel_weight_missing, panel_weight_missing == 0)
        add_check(checks, "panel_nonpositive_weight", 0, panel_weight_nonpositive, panel_weight_nonpositive == 0)
        add_check(checks, "panel_missing_state_or_district", 0, panel_geo_missing, panel_geo_missing == 0)
        add_check(checks, "panel_identification_block3_core_mismatch", 0, panel_core_mismatch, panel_core_mismatch == 0)

        print(f"Panel base rows            : {panel_rows_written:,}")
        print(f"Panel rural / urban        : {panel_sector['1']:,} / {panel_sector['2']:,}")
        print(f"Panel core mismatches      : {panel_core_mismatch}")
    except Exception as exc:
        errors.append(f"Panel base build failed: {type(exc).__name__}: {exc}")
        print(f"ERROR: {errors[-1]}")

    # -------------------------------------------------------------------------
    # 5. Classification and geography QA outputs
    # -------------------------------------------------------------------------
    print("\n[5] Classification / geography QA")

    group_rows = []
    group_rows.extend(sorted_counter_rows("stock_visit1", stock_group_counts, stock_group_weight))
    group_rows.extend(sorted_counter_rows("flow_panel", panel_group_counts, panel_group_weight))
    write_csv(
        GROUP_COUNTS_FILE,
        ["universe", "sector", "household_group", "surveyed_households", "weight_sum"],
        group_rows,
    )

    # Unclassified rows are retained in total/sector estimates but must not be
    # silently forced into a client household-group category.
    stock_unclassified = sum(
        n for g, n in stock_group_counts.items() if "Unclassified" in g
    )
    panel_unclassified = sum(
        n for g, n in panel_group_counts.items() if "Unclassified" in g
    )
    if stock_unclassified:
        warnings.append(
            f"Stock base has {stock_unclassified} household(s) not classifiable under "
            "the locked rural/urban subgroup rules because required source values are missing."
        )
    if panel_unclassified:
        warnings.append(
            f"Panel base has {panel_unclassified} household(s) not classifiable under "
            "the locked rural/urban subgroup rules because required source values are missing."
        )

    print("Stock household groups:")
    for group, count in sorted(stock_group_counts.items()):
        print(f"  {group:24s}: {count:,}")
    print("Panel household groups:")
    for group, count in sorted(panel_group_counts.items()):
        print(f"  {group:24s}: {count:,}")

    geography_keys = sorted(set(stock_geo_counts) | set(panel_geo_counts))
    geography_rows = []
    for state, district, sector in geography_keys:
        geography_rows.append({
            "State": state,
            "District": district,
            "Sector": sector,
            "Sector_Name": SECTOR_NAMES.get(sector, "Unclassified"),
            "stock_surveyed_households": stock_geo_counts[(state, district, sector)],
            "stock_weight_sum": f"{stock_geo_weight[(state, district, sector)]:.10f}",
            "panel_surveyed_households": panel_geo_counts[(state, district, sector)],
            "panel_weight_sum": f"{panel_geo_weight[(state, district, sector)]:.10f}",
        })
    write_csv(
        GEOGRAPHY_FILE,
        [
            "State", "District", "Sector", "Sector_Name",
            "stock_surveyed_households", "stock_weight_sum",
            "panel_surveyed_households", "panel_weight_sum",
        ],
        geography_rows,
    )

    # -------------------------------------------------------------------------
    # 6. Final QA and report
    # -------------------------------------------------------------------------
    failed_checks = [r for r in checks if r["status"] == "FAIL"]
    if failed_checks:
        errors.append(f"{len(failed_checks)} Step-02 validation check(s) failed")

    write_csv(
        QA_FILE,
        ["check", "expected", "observed", "status", "note"],
        checks,
    )

    status = "PASS" if not errors else "FAIL"

    summary_lines = [
        "=" * 78,
        "AIDIS 2003 - STEP 02 HOUSEHOLD BASE SUMMARY",
        "=" * 78,
        f"Stock household rows          : {stock_rows_written}",
        f"Stock rural / urban           : {stock_sector['1']} / {stock_sector['2']}",
        f"Stock subgroup unclassified   : {stock_unclassified}",
        f"Panel household rows          : {panel_rows_written}",
        f"Panel rural / urban           : {panel_sector['1']} / {panel_sector['2']}",
        f"Panel subgroup unclassified   : {panel_unclassified}",
        f"Combined Block3 Visit2 updates: {combined_b3['visit_counts']['2']}",
        f"Validation checks             : {len(checks)}",
        f"Failed validation checks      : {len(failed_checks)}",
        f"Warnings                      : {len(warnings)}",
        f"Errors                        : {len(errors)}",
        "",
        f"Stock base                    : {STOCK_BASE_FILE}",
        f"Panel base                    : {PANEL_BASE_FILE}",
        f"Checks CSV                    : {QA_FILE}",
        f"Household-group counts        : {GROUP_COUNTS_FILE}",
        f"Geography inventory           : {GEOGRAPHY_FILE}",
        f"Visit2 Block3 updates         : {VISIT2_B3_UPDATES_FILE}",
        "",
        "BASE GRAIN:",
        "  - Stock base: exactly one row per raw Visit-1 HHID.",
        "  - Panel base: exactly one row per PANEL_HHID present in both visits.",
        "  - Weight appears once per base household; later fact tables must aggregate to",
        "    HHID/PANEL_HHID before joining to these bases.",
        "  - Original 2003 State/District codes are preserved; names are not modernised.",
        "",
        "HOUSEHOLD-GROUP POLICY:",
        "  - Rural Cultivator: B3_q8 >= 0.002 hectare.",
        "  - Rural Non-cultivator: B3_q8 < 0.002, or B3_q7 explicitly says no operated land.",
        "  - Urban Self-employed: B3_q4 = 1.",
        "  - Urban Others: B3_q4 in {2,3,9}.",
        "  - Missing source values are retained as Unclassified, never guessed.",
    ]

    if warnings:
        summary_lines.append("")
        summary_lines.append("WARNINGS:")
        summary_lines.extend(f"  - {x}" for x in warnings)

    if errors:
        summary_lines.append("")
        summary_lines.append("ERRORS:")
        summary_lines.extend(f"  - {x}" for x in errors)

    summary_lines.extend([
        "",
        f"STEP 02 STATUS: {status}",
        "=" * 78,
    ])
    SUMMARY_FILE.write_text("\n".join(summary_lines), encoding="utf-8")

    print("\n" + "=" * 78)
    print("AIDIS 2003 - STEP 02 SUMMARY")
    print("=" * 78)
    print(f"Stock household rows          : {stock_rows_written:,}")
    print(f"Stock rural / urban           : {stock_sector['1']:,} / {stock_sector['2']:,}")
    print(f"Stock subgroup unclassified   : {stock_unclassified:,}")
    print(f"Panel household rows          : {panel_rows_written:,}")
    print(f"Panel rural / urban           : {panel_sector['1']:,} / {panel_sector['2']:,}")
    print(f"Panel subgroup unclassified   : {panel_unclassified:,}")
    print(f"Combined Block3 Visit2 updates: {combined_b3['visit_counts']['2']:,}")
    print(f"Validation checks             : {len(checks)}")
    print(f"Failed validation checks      : {len(failed_checks)}")
    print(f"Warnings                      : {len(warnings)}")
    print(f"Errors                        : {len(errors)}")
    print(f"Stock base                    : {STOCK_BASE_FILE}")
    print(f"Panel base                    : {PANEL_BASE_FILE}")
    print(f"Checks CSV                    : {QA_FILE}")
    print(f"Summary                       : {SUMMARY_FILE}")
    print()
    print(f"STEP 02 STATUS: {status}")
    print("=" * 78)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())