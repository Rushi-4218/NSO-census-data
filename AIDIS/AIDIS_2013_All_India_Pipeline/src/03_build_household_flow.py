from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


# =============================================================================
# AIDIS 2013 - STEP 03
# CANONICAL COMMON-PANEL HOUSEHOLD FLOW LAYER
#
# NSS 70th Round - Schedule 18.2
#
# PURPOSE
# -------
# Consume the validated Step-02 household stock layer and the Step-01C
# methodology lock, then construct exactly one annual-flow record for each
# household in the exact Visit-1 / Visit-2 common panel.
#
# LOCKED METHODOLOGY IMPLEMENTED HERE
# -----------------------------------
#   Visit-1 flow period : 01-07-2012 to 31-12-2012
#   Visit-2 flow period : 01-01-2013 to 30-06-2013
#   Annual flow period  : 01-07-2012 to 30-06-2013
#   Panel key           : exact HHID equality
#   Expected panel      : 108,421 households
#   Flow weight         : Visit-2 Weight_SC
#   Block-16 join key   : HHID + b16_q2
#   FCE                 : b16_q4 + b16_q5 + b16_q6 + b16_q7
#   Normal repairs      : b16_q8, retained separately and EXCLUDED from FCE
#   Land purchase items : 1, 4, 5, 14
#   Subtotal items      : 97, 98, EXCLUDED from household flow aggregation
#   Disposals           : b16_q12 + b16_q13 + b16_q14, retained separately
#                         and NEVER netted from FCE
#
# DESIGN NOTES
# ------------
# 1. Raw Block-16 files are discovered from their column signatures, not from
#    fragile hard-coded filenames. This supports the released Visit-1 CSVs and
#    Visit-2 XLSX/CSV layouts already mapped by Step 01B/01C.
# 2. Block-16 part 1 and part 2 are joined at the locked HHID+b16_q2 key in a
#    temporary SQLite work database. This keeps memory bounded for large files.
# 3. Visit-1-only and Visit-2-only households are audited but excluded from the
#    annual common-panel estimator.
# 4. q10/q11/q15 are retained for audit/completeness but are not part of FCE.
# 5. Official All-India FCE controls are hard checks. Occupational subgroup
#    controls, if present in the Step-01C control file, remain diagnostic until
#    the subgroup classification discrepancy documented in Step 02 is resolved.
# =============================================================================


SCRIPT_REVISION = "R1-COMMON-PANEL-BLOCK16-2026-08-27"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "input"
RAW_V1_ROOT = INPUT_DIR / "raw" / "visit1"
RAW_V2_ROOT = INPUT_DIR / "raw" / "visit2"
CACHE_DIR = PROJECT_ROOT / "cache"
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DATA_DIR = PROJECT_ROOT / "output" / "data"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"

for folder in [CACHE_DIR, CONFIG_DIR, OUTPUT_DATA_DIR, REPORT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


# =============================================================================
# UPSTREAM INPUTS
# =============================================================================

METHODOLOGY_JSON = CONFIG_DIR / "aidis_2013_methodology_lock.json"
BLOCK16_VARIABLE_MAP = CONFIG_DIR / "aidis_2013_block16_variable_map.csv"
BLOCK16_ITEM_CODEBOOK = CONFIG_DIR / "aidis_2013_block16_item_codebook.csv"
OFFICIAL_CONTROLS_FILE = CONFIG_DIR / "aidis_2013_official_controls.csv"
STEP02_LOCK_FILE = CONFIG_DIR / "aidis_2013_step02_lock.json"
HOUSEHOLD_STOCK_FILE = OUTPUT_DATA_DIR / "aidis_2013_household_stock.csv"
STEP01C_SUMMARY = REPORT_DIR / "step01c_methodology_lock_summary.txt"
STEP02_SUMMARY = REPORT_DIR / "step02_household_stock_summary.txt"


# =============================================================================
# STEP 03 OUTPUTS
# =============================================================================

HOUSEHOLD_FLOW_FILE = OUTPUT_DATA_DIR / "aidis_2013_household_flow.csv"
CHECKS_FILE = CACHE_DIR / "step03_household_flow_checks.csv"
BLOCK16_AUDIT_FILE = CACHE_DIR / "step03_block16_visit_audit.csv"
CONTROL_VALIDATION_FILE = CACHE_DIR / "step03_official_control_validation.csv"
STEP03_LOCK_FILE = CONFIG_DIR / "aidis_2013_step03_lock.json"
SUMMARY_FILE = REPORT_DIR / "step03_household_flow_summary.txt"
WORK_DB = CACHE_DIR / "step03_block16_work.sqlite"

EXPECTED_V1_HOUSEHOLDS = 110800
EXPECTED_V2_HOUSEHOLDS = 108425
EXPECTED_COMMON_HOUSEHOLDS = 108421
EXPECTED_V1_ONLY = 2379
EXPECTED_V2_ONLY = 4

SUBTOTAL_ITEM_CODES = {"97", "98"}
LAND_PURCHASE_ITEM_CODES = {"1", "4", "5", "14"}

MAIN_REQUIRED = ["HHID", "b16_q2", "b16_q4", "b16_q5", "b16_q6", "b16_q7", "b16_q8"]
VALUE_REQUIRED = [
    "HHID", "b16_q2", "b16_q10", "b16_q11", "b16_q12", "b16_q13", "b16_q14", "b16_q15"
]


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


def display_number(value: float, digits: int = 6) -> str:
    if not math.isfinite(value):
        return ""
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
    severity = severity.upper()
    status = "PASS" if passed else ("WARN" if severity == "WARNING" else "FAIL")
    checks.append(
        {
            "check_id": check_id,
            "check_name": check_name,
            "expected": clean(expected),
            "actual": clean(actual),
            "status": status,
            "severity": severity,
            "note": note,
        }
    )
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


def normalized_filename(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", " ", path.stem.lower()).strip()


def candidate_tabular_files(root: Path) -> List[Path]:
    extensions = {".csv", ".xlsx", ".xlsm"}
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in extensions)


# =============================================================================
# GENERIC CSV/XLSX STREAMING
# =============================================================================

def _csv_dialect(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as fh:
        sample = fh.read(65536)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _csv_header(path: Path, max_rows: int = 50) -> Tuple[Optional[int], List[str], object]:
    dialect = _csv_dialect(path)
    with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as fh:
        reader = csv.reader(fh, dialect)
        for row_no, row in enumerate(reader):
            header = [clean(v) for v in row]
            if "HHID" in header:
                return row_no, header, dialect
            if row_no + 1 >= max_rows:
                break
    return None, [], dialect


def _xlsx_header(path: Path, required_columns: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required. Install it with: pip install openpyxl") from exc

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            try:
                ws.reset_dimensions()
            except Exception:
                pass
            for row_no, values in enumerate(ws.iter_rows(values_only=True)):
                header = [clean(v) for v in values]
                if "HHID" in header and all(c in header for c in required_columns):
                    return sheet_name, header
                if row_no >= 49:
                    break
    finally:
        wb.close()
    return None, []


def tabular_has_columns(path: Path, required_columns: Sequence[str]) -> bool:
    required = list(required_columns)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        _, header, _ = _csv_header(path)
        return bool(header) and all(c in header for c in required)
    if suffix in {".xlsx", ".xlsm"}:
        sheet, _ = _xlsx_header(path, required)
        return sheet is not None
    return False


def tabular_dict_rows(path: Path, required_columns: Sequence[str]) -> Iterator[Dict[str, object]]:
    required = list(required_columns)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        header_row, header, dialect = _csv_header(path)
        if header_row is None or not all(c in header for c in required):
            raise RuntimeError(
                f"Could not find required columns in {path.name}: " + ", ".join(required)
            )
        indexes = {c: header.index(c) for c in required}
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as fh:
            reader = csv.reader(fh, dialect)
            for row_no, row in enumerate(reader):
                if row_no <= header_row:
                    continue
                if not any(clean(v) for v in row):
                    continue
                yield {
                    c: (row[indexes[c]] if indexes[c] < len(row) else None)
                    for c in required
                }
        return

    if suffix in {".xlsx", ".xlsm"}:
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("openpyxl is required. Install it with: pip install openpyxl") from exc

        sheet_name, header = _xlsx_header(path, required)
        if sheet_name is None:
            raise RuntimeError(
                f"Could not find required columns in {path.name}: " + ", ".join(required)
            )
        indexes = {c: header.index(c) for c in required}
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb[sheet_name]
            try:
                ws.reset_dimensions()
            except Exception:
                pass
            header_seen = False
            for values in ws.iter_rows(values_only=True):
                row = list(values)
                cleaned = [clean(v) for v in row]
                if not header_seen:
                    if "HHID" in cleaned and all(c in cleaned for c in required):
                        header_seen = True
                    continue
                if not any(cleaned):
                    continue
                yield {
                    c: (row[indexes[c]] if indexes[c] < len(row) else None)
                    for c in required
                }
        finally:
            wb.close()
        return

    raise RuntimeError(f"Unsupported tabular file format: {path}")


# =============================================================================
# UPSTREAM LOCK VALIDATION
# =============================================================================

def validate_upstream() -> Tuple[dict, dict]:
    print("\n[1] Validating upstream locks")

    for path, label in [
        (STEP01C_SUMMARY, "STEP01C_SUMMARY"),
        (METHODOLOGY_JSON, "METHODOLOGY_JSON"),
        (BLOCK16_VARIABLE_MAP, "BLOCK16_VARIABLE_MAP"),
        (BLOCK16_ITEM_CODEBOOK, "BLOCK16_ITEM_CODEBOOK"),
        (OFFICIAL_CONTROLS_FILE, "OFFICIAL_CONTROLS"),
        (STEP02_LOCK_FILE, "STEP02_LOCK"),
        (HOUSEHOLD_STOCK_FILE, "HOUSEHOLD_STOCK"),
    ]:
        require_file(path, label)

    if errors:
        return {}, {}

    with METHODOLOGY_JSON.open("r", encoding="utf-8") as fh:
        methodology = json.load(fh)
    with STEP02_LOCK_FILE.open("r", encoding="utf-8") as fh:
        step02_lock = json.load(fh)

    step02_status = clean(step02_lock.get("status"))
    add_check(
        "LOCK_STEP02_STATUS",
        "Step-02 lock status is passing",
        "PASS or PASS_WITH_DISCLOSURES",
        step02_status,
        step02_status.startswith("PASS"),
    )
    add_check(
        "LOCK_STEP02_ROWS",
        "Step-02 household output count",
        EXPECTED_V1_HOUSEHOLDS,
        step02_lock.get("household_output_rows"),
        int(step02_lock.get("household_output_rows") or -1) == EXPECTED_V1_HOUSEHOLDS,
    )

    # The Step-01C run supplied with this project locked these exact constants.
    # Validate them when their common schema keys exist; do not guess alternate
    # JSON paths if an earlier lock format omitted them.
    survey = methodology.get("survey", {}) if isinstance(methodology, dict) else {}
    for key, expected, check_id in [
        ("visit1_sample_households", EXPECTED_V1_HOUSEHOLDS, "LOCK_V1_COUNT"),
        ("visit2_sample_households", EXPECTED_V2_HOUSEHOLDS, "LOCK_V2_COUNT"),
        ("common_households", EXPECTED_COMMON_HOUSEHOLDS, "LOCK_COMMON_COUNT"),
    ]:
        if key in survey:
            actual = survey.get(key)
            add_check(check_id, f"Step-01C {key}", expected, actual, int(actual or -1) == expected)

    return methodology, step02_lock


# =============================================================================
# STEP-02 STOCK BACKBONE + VISIT-2 WEIGHTS
# =============================================================================

def load_step02_stock() -> Tuple[Dict[str, dict], List[str]]:
    print("\n[2] Loading validated Step-02 household stock backbone")

    required = [
        "HHID", "Sector", "State", "District_id", "State_District", "Weight_SC", "household_group"
    ]
    stock: Dict[str, dict] = {}
    order: List[str] = []
    duplicates = 0
    invalid_weights = 0

    with HOUSEHOLD_STOCK_FILE.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise RuntimeError("Step-02 stock file is missing columns: " + ", ".join(missing))
        for row in reader:
            hhid = clean(row.get("HHID"))
            if not hhid:
                continue
            if hhid in stock:
                duplicates += 1
                continue
            w1 = numeric(row.get("Weight_SC"), float("nan"))
            if not math.isfinite(w1) or w1 <= 0:
                invalid_weights += 1
                w1 = 0.0
            stock[hhid] = {
                "HHID": hhid,
                "Sector": normalized_code(row.get("Sector")),
                "State": clean(row.get("State")),
                "District_id": clean(row.get("District_id")),
                "State_District": clean(row.get("State_District")),
                "household_group": clean(row.get("household_group")),
                "Weight_SC_visit1": w1,
            }
            order.append(hhid)

    add_check("STOCK_COUNT", "Step-02 stock household count", EXPECTED_V1_HOUSEHOLDS, len(stock), len(stock) == EXPECTED_V1_HOUSEHOLDS)
    add_check("STOCK_DUPLICATES", "Duplicate HHIDs in Step-02 stock", 0, duplicates, duplicates == 0)
    add_check("STOCK_INVALID_WEIGHT", "Invalid Step-02 Visit-1 weights", 0, invalid_weights, invalid_weights == 0)

    print(f"  Visit-1 households        : {len(stock):,}")
    print(f"  Duplicate HHIDs           : {duplicates:,}")
    return stock, order


def probe_weight_file(path: Path) -> dict:
    unique = {}
    duplicate_rows = 0
    conflicting_weights = 0
    invalid_weights = 0
    rows = 0
    for row in tabular_dict_rows(path, ["HHID", "Weight_SC"]):
        hhid = clean(row.get("HHID"))
        if not hhid:
            continue
        rows += 1
        weight = numeric(row.get("Weight_SC"), float("nan"))
        if not math.isfinite(weight) or weight <= 0:
            invalid_weights += 1
            continue
        if hhid in unique:
            duplicate_rows += 1
            if abs(unique[hhid] - weight) > 1e-9:
                conflicting_weights += 1
        else:
            unique[hhid] = weight
    return {
        "path": path,
        "rows": rows,
        "unique": len(unique),
        "duplicate_rows": duplicate_rows,
        "conflicting_weights": conflicting_weights,
        "invalid_weights": invalid_weights,
        "weights": unique,
    }


def discover_visit2_weight_file() -> dict:
    print("\n[3] Resolving Visit-2 household weight source")

    candidates = [p for p in candidate_tabular_files(RAW_V2_ROOT) if tabular_has_columns(p, ["HHID", "Weight_SC"])]
    if not candidates:
        raise RuntimeError(f"No Visit-2 file containing HHID + Weight_SC found under {RAW_V2_ROOT}")

    def hint_score(path: Path) -> int:
        name = normalized_filename(path)
        score = 0
        for token in ["identification", "sample household", "field operations", "block 1"]:
            if token in name:
                score += 10
        if "block 16" in name:
            score -= 5
        return score

    # Probe hinted identification files first; fall back to every candidate if
    # necessary. The correct source must expose exactly 108,425 unique HHIDs.
    hinted = sorted([p for p in candidates if hint_score(p) > 0], key=hint_score, reverse=True)
    probe_order = hinted if hinted else candidates
    results = []
    for path in probe_order:
        result = probe_weight_file(path)
        results.append(result)
        print(
            f"  PROBE | {path.name} | unique HHID={result['unique']:,} | "
            f"duplicate rows={result['duplicate_rows']:,}"
        )
        if result["unique"] == EXPECTED_V2_HOUSEHOLDS and result["conflicting_weights"] == 0:
            selected = result
            break
    else:
        if hinted:
            for path in candidates:
                if path in hinted:
                    continue
                result = probe_weight_file(path)
                results.append(result)
                print(
                    f"  PROBE | {path.name} | unique HHID={result['unique']:,} | "
                    f"duplicate rows={result['duplicate_rows']:,}"
                )
                if result["unique"] == EXPECTED_V2_HOUSEHOLDS and result["conflicting_weights"] == 0:
                    selected = result
                    break
            else:
                selected = max(results, key=lambda r: r["unique"])
        else:
            selected = max(results, key=lambda r: r["unique"])

    add_check(
        "V2_WEIGHT_UNIVERSE",
        "Unique households in selected Visit-2 weight source",
        EXPECTED_V2_HOUSEHOLDS,
        selected["unique"],
        selected["unique"] == EXPECTED_V2_HOUSEHOLDS,
    )
    add_check(
        "V2_WEIGHT_CONFLICT",
        "Conflicting Visit-2 weights for same HHID",
        0,
        selected["conflicting_weights"],
        selected["conflicting_weights"] == 0,
    )
    add_check(
        "V2_WEIGHT_INVALID",
        "Invalid/non-positive Visit-2 weights",
        0,
        selected["invalid_weights"],
        selected["invalid_weights"] == 0,
    )

    print(f"  SELECTED                  : {selected['path'].name}")
    return selected


def build_common_panel(
    stock: Dict[str, dict],
    stock_order: List[str],
    v2_weight_result: dict,
) -> Tuple[Dict[str, dict], List[str], set, set]:
    print("\n[4] Building exact Visit-1 / Visit-2 common panel")

    v1_ids = set(stock)
    v2_weights: Dict[str, float] = v2_weight_result["weights"]
    v2_ids = set(v2_weights)
    common_ids = v1_ids & v2_ids
    v1_only = v1_ids - v2_ids
    v2_only = v2_ids - v1_ids

    add_check("PANEL_COMMON", "Exact common HHID count", EXPECTED_COMMON_HOUSEHOLDS, len(common_ids), len(common_ids) == EXPECTED_COMMON_HOUSEHOLDS)
    add_check("PANEL_V1_ONLY", "Visit-1-only HHID count", EXPECTED_V1_ONLY, len(v1_only), len(v1_only) == EXPECTED_V1_ONLY)
    add_check("PANEL_V2_ONLY", "Visit-2-only HHID count", EXPECTED_V2_ONLY, len(v2_only), len(v2_only) == EXPECTED_V2_ONLY)

    panel: Dict[str, dict] = {}
    panel_order: List[str] = []
    for hhid in stock_order:
        if hhid not in common_ids:
            continue
        base = dict(stock[hhid])
        base["Weight_SC_visit2"] = v2_weights[hhid]
        base["Weight_SC_flow"] = v2_weights[hhid]
        panel[hhid] = base
        panel_order.append(hhid)

    print(f"  Visit-1 households        : {len(v1_ids):,}")
    print(f"  Visit-2 households        : {len(v2_ids):,}")
    print(f"  Common households         : {len(common_ids):,}")
    print(f"  Visit-1 only              : {len(v1_only):,}")
    print(f"  Visit-2 only              : {len(v2_only):,}")

    return panel, panel_order, v1_ids, v2_ids


# =============================================================================
# BLOCK-16 FILE DISCOVERY
# =============================================================================

def discover_block16_pair(root: Path, visit_label: str) -> Tuple[Path, Path]:
    block16_candidates = [
        p for p in candidate_tabular_files(root)
        if re.search(r"\bblock\s*16\b", normalized_filename(p))
        or "block 16" in normalized_filename(p)
        or "block16" in normalized_filename(p).replace(" ", "")
    ]
    if not block16_candidates:
        # Last-resort signature discovery in case the released filenames differ.
        block16_candidates = candidate_tabular_files(root)

    main_matches = [p for p in block16_candidates if tabular_has_columns(p, MAIN_REQUIRED)]
    value_matches = [p for p in block16_candidates if tabular_has_columns(p, VALUE_REQUIRED)]

    if len(main_matches) != 1:
        raise RuntimeError(
            f"{visit_label}: expected exactly one Block-16 part-1 file with q2/q4-q8; "
            f"found {len(main_matches)}: {[p.name for p in main_matches]}"
        )
    if len(value_matches) != 1:
        raise RuntimeError(
            f"{visit_label}: expected exactly one Block-16 part-2/value file with q2/q10-q15; "
            f"found {len(value_matches)}: {[p.name for p in value_matches]}"
        )
    if main_matches[0] == value_matches[0]:
        raise RuntimeError(f"{visit_label}: Block-16 part-1 and part-2 resolved to the same file")

    return main_matches[0], value_matches[0]


# =============================================================================
# BLOCK-16 SQLITE JOIN / AGGREGATION
# =============================================================================

def create_work_db(panel: Dict[str, dict]) -> sqlite3.Connection:
    if WORK_DB.exists():
        WORK_DB.unlink()
    conn = sqlite3.connect(WORK_DB)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-65536")  # ~64 MiB cache
    conn.execute("CREATE TABLE panel (hhid TEXT PRIMARY KEY) WITHOUT ROWID")
    conn.executemany("INSERT INTO panel(hhid) VALUES (?)", ((hhid,) for hhid in panel))
    conn.commit()
    return conn


def create_visit_tables(conn: sqlite3.Connection, prefix: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE {prefix}_main (
            hhid TEXT NOT NULL,
            item_code TEXT NOT NULL,
            q4 REAL NOT NULL,
            q5 REAL NOT NULL,
            q6 REAL NOT NULL,
            q7 REAL NOT NULL,
            q8 REAL NOT NULL,
            PRIMARY KEY (hhid, item_code)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        f"""
        CREATE TABLE {prefix}_value (
            hhid TEXT NOT NULL,
            item_code TEXT NOT NULL,
            q10 REAL NOT NULL,
            q11 REAL NOT NULL,
            q12 REAL NOT NULL,
            q13 REAL NOT NULL,
            q14 REAL NOT NULL,
            q15 REAL NOT NULL,
            PRIMARY KEY (hhid, item_code)
        ) WITHOUT ROWID
        """
    )


def load_main_table(
    conn: sqlite3.Connection,
    prefix: str,
    path: Path,
    valid_sample_ids: set,
) -> dict:
    rows = 0
    loaded = 0
    blank_key = 0
    unknown_hhid = 0
    duplicate_keys = 0
    negative_component_rows = 0
    subtotal_rows = 0
    nonpanel_rows = 0

    sql = f"""
        INSERT INTO {prefix}_main(hhid,item_code,q4,q5,q6,q7,q8)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(hhid,item_code) DO UPDATE SET
            q4=q4+excluded.q4, q5=q5+excluded.q5, q6=q6+excluded.q6,
            q7=q7+excluded.q7, q8=q8+excluded.q8
    """

    batch = []
    for row in tabular_dict_rows(path, MAIN_REQUIRED):
        rows += 1
        hhid = clean(row.get("HHID"))
        item = normalized_code(row.get("b16_q2"))
        if not hhid or not item:
            blank_key += 1
            continue
        if hhid not in valid_sample_ids:
            unknown_hhid += 1
            continue
        vals = [numeric(row.get(f"b16_q{i}"), 0.0) for i in range(4, 9)]
        if any(v < 0 for v in vals):
            negative_component_rows += 1
        if item in SUBTOTAL_ITEM_CODES:
            subtotal_rows += 1
        batch.append((hhid, item, *vals))
        loaded += 1
        if len(batch) >= 10000:
            conn.executemany(sql, batch)
            batch.clear()
    if batch:
        conn.executemany(sql, batch)
    conn.commit()
    unique_keys = conn.execute(f"SELECT COUNT(*) FROM {prefix}_main").fetchone()[0]
    duplicate_keys = loaded - unique_keys

    # Count valid sample keys that do not belong to the common panel.
    nonpanel_rows = conn.execute(
        f"SELECT COUNT(*) FROM {prefix}_main m LEFT JOIN panel p ON p.hhid=m.hhid WHERE p.hhid IS NULL"
    ).fetchone()[0]

    return {
        "part": "main",
        "source_file": path.name,
        "raw_rows": rows,
        "loaded_rows": loaded,
        "blank_key_rows": blank_key,
        "unknown_hhid_rows": unknown_hhid,
        "duplicate_hhid_item_keys": duplicate_keys,
        "negative_component_rows": negative_component_rows,
        "subtotal_rows": subtotal_rows,
        "noncommon_valid_rows": nonpanel_rows,
    }


def load_value_table(
    conn: sqlite3.Connection,
    prefix: str,
    path: Path,
    valid_sample_ids: set,
) -> dict:
    rows = 0
    loaded = 0
    blank_key = 0
    unknown_hhid = 0
    duplicate_keys = 0
    negative_component_rows = 0
    subtotal_rows = 0

    sql = f"""
        INSERT INTO {prefix}_value(hhid,item_code,q10,q11,q12,q13,q14,q15)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(hhid,item_code) DO UPDATE SET
            q10=q10+excluded.q10, q11=q11+excluded.q11,
            q12=q12+excluded.q12, q13=q13+excluded.q13,
            q14=q14+excluded.q14, q15=q15+excluded.q15
    """

    batch = []
    for row in tabular_dict_rows(path, VALUE_REQUIRED):
        rows += 1
        hhid = clean(row.get("HHID"))
        item = normalized_code(row.get("b16_q2"))
        if not hhid or not item:
            blank_key += 1
            continue
        if hhid not in valid_sample_ids:
            unknown_hhid += 1
            continue
        vals = [numeric(row.get(f"b16_q{i}"), 0.0) for i in range(10, 16)]
        if any(v < 0 for v in vals):
            negative_component_rows += 1
        if item in SUBTOTAL_ITEM_CODES:
            subtotal_rows += 1
        batch.append((hhid, item, *vals))
        loaded += 1
        if len(batch) >= 10000:
            conn.executemany(sql, batch)
            batch.clear()
    if batch:
        conn.executemany(sql, batch)
    conn.commit()
    unique_keys = conn.execute(f"SELECT COUNT(*) FROM {prefix}_value").fetchone()[0]
    duplicate_keys = loaded - unique_keys

    nonpanel_rows = conn.execute(
        f"SELECT COUNT(*) FROM {prefix}_value v LEFT JOIN panel p ON p.hhid=v.hhid WHERE p.hhid IS NULL"
    ).fetchone()[0]

    return {
        "part": "value",
        "source_file": path.name,
        "raw_rows": rows,
        "loaded_rows": loaded,
        "blank_key_rows": blank_key,
        "unknown_hhid_rows": unknown_hhid,
        "duplicate_hhid_item_keys": duplicate_keys,
        "negative_component_rows": negative_component_rows,
        "subtotal_rows": subtotal_rows,
        "noncommon_valid_rows": nonpanel_rows,
    }


def visit_join_audit(conn: sqlite3.Connection, prefix: str) -> dict:
    main_only = conn.execute(
        f"""
        SELECT COUNT(*) FROM {prefix}_main m
        LEFT JOIN {prefix}_value v ON v.hhid=m.hhid AND v.item_code=m.item_code
        WHERE v.hhid IS NULL
        """
    ).fetchone()[0]
    value_only = conn.execute(
        f"""
        SELECT COUNT(*) FROM {prefix}_value v
        LEFT JOIN {prefix}_main m ON m.hhid=v.hhid AND m.item_code=v.item_code
        WHERE m.hhid IS NULL
        """
    ).fetchone()[0]
    joined = conn.execute(
        f"""
        SELECT COUNT(*) FROM {prefix}_main m
        INNER JOIN {prefix}_value v ON v.hhid=m.hhid AND v.item_code=m.item_code
        """
    ).fetchone()[0]
    return {"joined_keys": joined, "main_only_keys": main_only, "value_only_keys": value_only}


def aggregate_visit(conn: sqlite3.Connection, prefix: str) -> Tuple[Dict[str, dict], dict]:
    # Full key union enforces the locked HHID+b16_q2 join without losing a row
    # that appears in only one Block-16 part. Subtotals 97/98 are excluded from
    # every household aggregate.
    subtotal_sql = ",".join(f"'{c}'" for c in sorted(SUBTOTAL_ITEM_CODES))
    land_sql = ",".join(f"'{c}'" for c in sorted(LAND_PURCHASE_ITEM_CODES))

    query = f"""
        WITH keys AS (
            SELECT hhid, item_code FROM {prefix}_main
            UNION
            SELECT hhid, item_code FROM {prefix}_value
        ), joined AS (
            SELECT
                k.hhid,
                k.item_code,
                COALESCE(m.q4,0) AS q4,
                COALESCE(m.q5,0) AS q5,
                COALESCE(m.q6,0) AS q6,
                COALESCE(m.q7,0) AS q7,
                COALESCE(m.q8,0) AS q8,
                COALESCE(v.q10,0) AS q10,
                COALESCE(v.q11,0) AS q11,
                COALESCE(v.q12,0) AS q12,
                COALESCE(v.q13,0) AS q13,
                COALESCE(v.q14,0) AS q14,
                COALESCE(v.q15,0) AS q15
            FROM keys k
            LEFT JOIN {prefix}_main m ON m.hhid=k.hhid AND m.item_code=k.item_code
            LEFT JOIN {prefix}_value v ON v.hhid=k.hhid AND v.item_code=k.item_code
            INNER JOIN panel p ON p.hhid=k.hhid
            WHERE k.item_code NOT IN ({subtotal_sql})
        )
        SELECT
            hhid,
            SUM(q4) AS q4,
            SUM(q5) AS q5,
            SUM(q6) AS q6,
            SUM(q7) AS q7,
            SUM(q8) AS q8,
            SUM(q10) AS q10,
            SUM(q11) AS q11,
            SUM(q12) AS q12,
            SUM(q13) AS q13,
            SUM(q14) AS q14,
            SUM(q15) AS q15,
            SUM(q4+q5+q6+q7) AS fce,
            SUM(CASE WHEN item_code IN ({land_sql}) THEN q4+q5+q6+q7 ELSE 0 END) AS land_purchase,
            SUM(q12+q13+q14) AS disposals,
            COUNT(*) AS detail_item_keys
        FROM joined
        GROUP BY hhid
    """

    result: Dict[str, dict] = {}
    for row in conn.execute(query):
        hhid = row[0]
        result[hhid] = {
            "q4": float(row[1] or 0),
            "q5": float(row[2] or 0),
            "q6": float(row[3] or 0),
            "q7": float(row[4] or 0),
            "q8": float(row[5] or 0),
            "q10": float(row[6] or 0),
            "q11": float(row[7] or 0),
            "q12": float(row[8] or 0),
            "q13": float(row[9] or 0),
            "q14": float(row[10] or 0),
            "q15": float(row[11] or 0),
            "fce": float(row[12] or 0),
            "land_purchase": float(row[13] or 0),
            "disposals": float(row[14] or 0),
            "detail_item_keys": int(row[15] or 0),
        }

    summary = {
        "common_households_with_detail_items": len(result),
        "common_households_without_detail_items": EXPECTED_COMMON_HOUSEHOLDS - len(result),
        "unweighted_fce": sum(r["fce"] for r in result.values()),
        "unweighted_land_purchase": sum(r["land_purchase"] for r in result.values()),
        "unweighted_normal_repairs": sum(r["q8"] for r in result.values()),
        "unweighted_disposals": sum(r["disposals"] for r in result.values()),
    }
    return result, summary


def build_block16_flows(
    panel: Dict[str, dict],
    v1_ids: set,
    v2_ids: set,
    paths: Dict[str, Path],
) -> Tuple[List[dict], dict, dict]:
    print("\n[6] Building Block-16 Visit-1 / Visit-2 household flows")

    conn = create_work_db(panel)
    audit_rows: List[dict] = []
    visit_summaries = {}
    visit_results = {}

    try:
        for prefix, label, valid_ids in [
            ("v1", "Visit 1", v1_ids),
            ("v2", "Visit 2", v2_ids),
        ]:
            create_visit_tables(conn, prefix)
            main_audit = load_main_table(conn, prefix, paths[f"{prefix}_main"], valid_ids)
            value_audit = load_value_table(conn, prefix, paths[f"{prefix}_value"], valid_ids)
            join_audit = visit_join_audit(conn, prefix)

            main_audit.update({"visit": label, **join_audit})
            value_audit.update({"visit": label, **join_audit})
            audit_rows.extend([main_audit, value_audit])

            # Duplicate HHID+item keys would make the official join ambiguous.
            add_check(
                f"{prefix.upper()}_MAIN_DUPKEY",
                f"{label} Block-16 part-1 duplicate HHID+b16_q2 keys",
                0,
                main_audit["duplicate_hhid_item_keys"],
                main_audit["duplicate_hhid_item_keys"] == 0,
            )
            add_check(
                f"{prefix.upper()}_VALUE_DUPKEY",
                f"{label} Block-16 part-2 duplicate HHID+b16_q2 keys",
                0,
                value_audit["duplicate_hhid_item_keys"],
                value_audit["duplicate_hhid_item_keys"] == 0,
            )
            add_check(
                f"{prefix.upper()}_MAIN_UNKNOWN_HH",
                f"{label} Block-16 part-1 HHIDs outside visit sample",
                0,
                main_audit["unknown_hhid_rows"],
                main_audit["unknown_hhid_rows"] == 0,
            )
            add_check(
                f"{prefix.upper()}_VALUE_UNKNOWN_HH",
                f"{label} Block-16 part-2 HHIDs outside visit sample",
                0,
                value_audit["unknown_hhid_rows"],
                value_audit["unknown_hhid_rows"] == 0,
            )
            add_check(
                f"{prefix.upper()}_MAIN_BLANK_KEY",
                f"{label} Block-16 part-1 blank HHID/item keys",
                0,
                main_audit["blank_key_rows"],
                main_audit["blank_key_rows"] == 0,
                severity="WARNING",
            )
            add_check(
                f"{prefix.upper()}_VALUE_BLANK_KEY",
                f"{label} Block-16 part-2 blank HHID/item keys",
                0,
                value_audit["blank_key_rows"],
                value_audit["blank_key_rows"] == 0,
                severity="WARNING",
            )
            add_check(
                f"{prefix.upper()}_MAIN_NEGATIVE",
                f"{label} q4-q8 rows containing negative values",
                0,
                main_audit["negative_component_rows"],
                main_audit["negative_component_rows"] == 0,
                severity="WARNING",
                note="Flow negatives are never silently cleaned; they remain in the audit and calculation pending source review.",
            )
            add_check(
                f"{prefix.upper()}_VALUE_NEGATIVE",
                f"{label} q10-q15 rows containing negative values",
                0,
                value_audit["negative_component_rows"],
                value_audit["negative_component_rows"] == 0,
                severity="WARNING",
                note="Flow negatives are never silently cleaned; they remain in the audit and calculation pending source review.",
            )

            # Part-1/part-2 can legitimately differ in sparse releases. Preserve
            # union keys, report the mismatch, and do not discard either side.
            if join_audit["main_only_keys"] or join_audit["value_only_keys"]:
                disclosures.append(
                    f"{label} Block-16 HHID+b16_q2 join has {join_audit['main_only_keys']} part-1-only "
                    f"key(s) and {join_audit['value_only_keys']} part-2-only key(s); Step 03 uses the union "
                    "of keys with missing counterpart values set to 0."
                )

            flow, summary = aggregate_visit(conn, prefix)
            visit_results[prefix] = flow
            visit_summaries[prefix] = {**summary, **join_audit}

            print(f"  {label}")
            print(f"    Part-1 rows              : {main_audit['raw_rows']:,}")
            print(f"    Part-2 rows              : {value_audit['raw_rows']:,}")
            print(f"    Joined HHID+item keys    : {join_audit['joined_keys']:,}")
            print(f"    Part-1-only keys         : {join_audit['main_only_keys']:,}")
            print(f"    Part-2-only keys         : {join_audit['value_only_keys']:,}")
            print(f"    Panel HH with detail     : {summary['common_households_with_detail_items']:,}")

        # Attach Visit-1, Visit-2 and annual totals to every common-panel HH.
        zero = {
            "q4": 0.0, "q5": 0.0, "q6": 0.0, "q7": 0.0, "q8": 0.0,
            "q10": 0.0, "q11": 0.0, "q12": 0.0, "q13": 0.0, "q14": 0.0,
            "q15": 0.0, "fce": 0.0, "land_purchase": 0.0, "disposals": 0.0,
            "detail_item_keys": 0,
        }

        for hhid, hh in panel.items():
            v1 = visit_results["v1"].get(hhid, zero)
            v2 = visit_results["v2"].get(hhid, zero)

            for q in ["q4", "q5", "q6", "q7", "q8", "q10", "q11", "q12", "q13", "q14", "q15"]:
                hh[f"block16_{q}_visit1"] = v1[q]
                hh[f"block16_{q}_visit2"] = v2[q]
                hh[f"block16_{q}_annual"] = v1[q] + v2[q]

            for metric in ["fce", "land_purchase", "disposals"]:
                hh[f"{metric}_visit1"] = v1[metric]
                hh[f"{metric}_visit2"] = v2[metric]
                hh[f"{metric}_annual"] = v1[metric] + v2[metric]

            hh["normal_repairs_visit1"] = v1["q8"]
            hh["normal_repairs_visit2"] = v2["q8"]
            hh["normal_repairs_annual"] = v1["q8"] + v2["q8"]
            hh["block16_detail_items_visit1"] = v1["detail_item_keys"]
            hh["block16_detail_items_visit2"] = v2["detail_item_keys"]
            hh["has_fce"] = 1 if hh["fce_annual"] > 0 else 0
            hh["has_land_purchase"] = 1 if hh["land_purchase_annual"] > 0 else 0
            hh["has_normal_repairs"] = 1 if hh["normal_repairs_annual"] > 0 else 0
            hh["has_disposals"] = 1 if hh["disposals_annual"] > 0 else 0

        # Algebraic invariants: FCE is q4+q5+q6+q7 only; disposals and repairs
        # must not change it.
        fce_recon_fail = 0
        for hh in panel.values():
            expected = sum(hh[f"block16_q{i}_annual"] for i in [4, 5, 6, 7])
            if abs(hh["fce_annual"] - expected) > 0.01:
                fce_recon_fail += 1
        add_check("FCE_RECONCILIATION", "Annual FCE = q4+q5+q6+q7", 0, fce_recon_fail, fce_recon_fail == 0)

    finally:
        conn.close()

    return audit_rows, visit_summaries, visit_results


# =============================================================================
# OFFICIAL FCE VALIDATION
# =============================================================================

def weighted_flow_metrics(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    denominator = sum(float(r["Weight_SC_flow"]) for r in rows)
    if denominator <= 0:
        return {
            "Average FCE": float("nan"),
            "FCE incidence": float("nan"),
            "Average land purchase": float("nan"),
            "Average normal repairs": float("nan"),
            "Average disposals": float("nan"),
        }
    return {
        "Average FCE": sum(r["Weight_SC_flow"] * r["fce_annual"] for r in rows) / denominator,
        "FCE incidence": 100.0 * sum(r["Weight_SC_flow"] * r["has_fce"] for r in rows) / denominator,
        "Average land purchase": sum(r["Weight_SC_flow"] * r["land_purchase_annual"] for r in rows) / denominator,
        "Average normal repairs": sum(r["Weight_SC_flow"] * r["normal_repairs_annual"] for r in rows) / denominator,
        "Average disposals": sum(r["Weight_SC_flow"] * r["disposals_annual"] for r in rows) / denominator,
    }


def panel_group_rows(panel: Dict[str, dict], sector: str, group: str) -> List[dict]:
    sector_code = {"Rural": "1", "Urban": "2"}.get(sector)
    rows = []
    for hh in panel.values():
        if sector_code and hh["Sector"] != sector_code:
            continue
        if group and group != "All" and hh["household_group"] != group:
            continue
        rows.append(hh)
    return rows


def parse_tolerance(text: str, published: float) -> float:
    value = clean(text).lower()
    if not value:
        return max(abs(published) * 0.01, 0.2 if abs(published) < 100 else 1.0)
    if value == "exact":
        return 0.0
    m = re.match(r"([0-9.]+)%$", value)
    if m:
        return abs(published) * float(m.group(1)) / 100.0
    m = re.match(r"([0-9.]+)\s*percentage point", value)
    if m:
        return float(m.group(1))
    # Conservative fallback for an unfamiliar textual tolerance.
    return max(abs(published) * 0.01, 0.2 if abs(published) < 100 else 1.0)


def infer_flow_metric(family: str, metric: str) -> Optional[str]:
    text = f"{family} {metric}".lower()
    if not any(token in text for token in ["capital", "fce", "fixed"]):
        return None
    if any(token in text for token in ["incidence", "percent", "percentage", "proportion"]):
        return "FCE incidence"
    if "land" in text and any(token in text for token in ["purchase", "expenditure"]):
        return "Average land purchase"
    if "repair" in text:
        return "Average normal repairs"
    if any(token in text for token in ["disposal", "sale"]):
        return "Average disposals"
    return "Average FCE"


def validate_flow_controls(panel: Dict[str, dict]) -> List[dict]:
    print("\n[7] Validating official annual FCE controls")

    metric_cache = {}
    for sector, group in [
        ("Rural", "All"),
        ("Rural", "Cultivator"),
        ("Rural", "Non-cultivator"),
        ("Urban", "All"),
        ("Urban", "Self-employed"),
        ("Urban", "Others"),
    ]:
        metric_cache[(sector, group)] = weighted_flow_metrics(panel_group_rows(panel, sector, group))

    validation_rows = []
    recognized_hard = 0

    for control in read_csv(OFFICIAL_CONTROLS_FILE):
        family = clean(control.get("family"))
        metric = clean(control.get("metric"))
        mapped_metric = infer_flow_metric(family, metric)
        if mapped_metric is None:
            continue

        sector = clean(control.get("sector"))
        group = clean(control.get("household_group")) or "All"
        if sector not in {"Rural", "Urban"} or (sector, group) not in metric_cache:
            continue

        published = numeric(control.get("published_value"), float("nan"))
        if not math.isfinite(published):
            continue
        actual = metric_cache[(sector, group)][mapped_metric]
        tolerance = parse_tolerance(clean(control.get("tolerance")), published)
        difference = actual - published
        passed = math.isfinite(actual) and abs(difference) <= tolerance + 1e-12
        hard = group == "All"
        if hard:
            recognized_hard += 1
            add_check(
                f"FLOW_CONTROL_{clean(control.get('control_id')) or len(validation_rows)+1}",
                f"Official {sector} {group} {metric or mapped_metric}",
                published,
                display_number(actual, 3),
                passed,
            )

        validation_rows.append(
            {
                "control_id": clean(control.get("control_id")),
                "family": family,
                "sector": sector,
                "household_group": group,
                "metric": metric,
                "mapped_metric": mapped_metric,
                "published_value": display_number(published, 6),
                "computed_value": display_number(actual, 6),
                "difference": display_number(difference, 6),
                "absolute_tolerance": display_number(tolerance, 6),
                "validation_mode": "HARD" if hard else "DIAGNOSTIC",
                "status": "PASS" if passed else ("FAIL" if hard else "DIFFERENT"),
            }
        )

    # Independent Key Indicators anchors. If the Step-01C control CSV already
    # contains them these are still useful as named reproducibility checks.
    # Published: ~31% rural / 15.2% urban incidence and Rs 10,717 / 14,493
    # average annual fixed capital expenditure per household.
    key_anchors = [
        ("FCE_RURAL_INCIDENCE", "Rural", "FCE incidence", 31.0, 1.0),
        ("FCE_URBAN_INCIDENCE", "Urban", "FCE incidence", 15.2, 0.5),
        ("FCE_RURAL_AVERAGE", "Rural", "Average FCE", 10717.0, 0.02 * 10717.0),
        ("FCE_URBAN_AVERAGE", "Urban", "Average FCE", 14493.0, 0.02 * 14493.0),
    ]
    for cid, sector, mapped_metric, published, tolerance in key_anchors:
        actual = metric_cache[(sector, "All")][mapped_metric]
        passed = math.isfinite(actual) and abs(actual - published) <= tolerance
        add_check(cid, f"Published All-India {sector} {mapped_metric}", published, display_number(actual, 3), passed)
        print(
            f"  {cid:24s} | computed={actual:12,.3f} | "
            f"published={published:12,.3f} | {'PASS' if passed else 'FAIL'}"
        )

    if recognized_hard == 0:
        disclosures.append(
            "No machine-readable All-group FCE controls were recognized in aidis_2013_official_controls.csv; "
            "Step 03 therefore relies on the four independently named All-India Key Indicators anchors."
        )

    return validation_rows


# =============================================================================
# OUTPUT
# =============================================================================

FLOW_COLUMNS = [
    "HHID",
    "Sector",
    "State",
    "District_id",
    "State_District",
    "household_group",
    "Weight_SC_visit1",
    "Weight_SC_visit2",
    "Weight_SC_flow",
    "block16_detail_items_visit1",
    "block16_detail_items_visit2",
    "block16_q4_visit1", "block16_q4_visit2", "block16_q4_annual",
    "block16_q5_visit1", "block16_q5_visit2", "block16_q5_annual",
    "block16_q6_visit1", "block16_q6_visit2", "block16_q6_annual",
    "block16_q7_visit1", "block16_q7_visit2", "block16_q7_annual",
    "block16_q8_visit1", "block16_q8_visit2", "block16_q8_annual",
    "block16_q10_visit1", "block16_q10_visit2", "block16_q10_annual",
    "block16_q11_visit1", "block16_q11_visit2", "block16_q11_annual",
    "block16_q12_visit1", "block16_q12_visit2", "block16_q12_annual",
    "block16_q13_visit1", "block16_q13_visit2", "block16_q13_annual",
    "block16_q14_visit1", "block16_q14_visit2", "block16_q14_annual",
    "block16_q15_visit1", "block16_q15_visit2", "block16_q15_annual",
    "fce_visit1", "fce_visit2", "fce_annual",
    "land_purchase_visit1", "land_purchase_visit2", "land_purchase_annual",
    "normal_repairs_visit1", "normal_repairs_visit2", "normal_repairs_annual",
    "disposals_visit1", "disposals_visit2", "disposals_annual",
    "has_fce", "has_land_purchase", "has_normal_repairs", "has_disposals",
]

NUMERIC_FLOW_COLUMNS = {
    c for c in FLOW_COLUMNS
    if c.startswith("Weight_")
    or c.startswith("block16_q")
    or c.startswith("fce_")
    or c.startswith("land_purchase_")
    or c.startswith("normal_repairs_")
    or c.startswith("disposals_")
}


def write_flow_output(panel: Dict[str, dict], panel_order: List[str]) -> None:
    with HOUSEHOLD_FLOW_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FLOW_COLUMNS)
        writer.writeheader()
        for hhid in panel_order:
            source = panel[hhid]
            row = {}
            for col in FLOW_COLUMNS:
                value = source.get(col, "")
                if col in NUMERIC_FLOW_COLUMNS:
                    value = display_number(float(value or 0.0))
                row[col] = value
            writer.writerow(row)


def build_lock(
    methodology: dict,
    step02_lock: dict,
    paths: Dict[str, Path],
    v2_weight_result: dict,
    panel: Dict[str, dict],
    visit_summaries: dict,
    control_rows: List[dict],
    final_status: str,
) -> dict:
    return {
        "step": "03",
        "name": "Canonical common-panel household flow layer",
        "status": final_status,
        "script_revision": SCRIPT_REVISION,
        "project_root": str(PROJECT_ROOT),
        "upstream": {
            "step02_status": step02_lock.get("status"),
            "methodology_lock": str(METHODOLOGY_JSON),
            "step02_lock": str(STEP02_LOCK_FILE),
        },
        "panel": {
            "visit1_households": EXPECTED_V1_HOUSEHOLDS,
            "visit2_households": EXPECTED_V2_HOUSEHOLDS,
            "common_households": len(panel),
            "panel_key": "Exact HHID equality",
            "flow_weight": "Visit-2 Weight_SC",
            "visit2_weight_source": str(v2_weight_result["path"]),
        },
        "reference_periods": {
            "visit1": "01-07-2012 to 31-12-2012",
            "visit2": "01-01-2013 to 30-06-2013",
            "annual": "01-07-2012 to 30-06-2013",
        },
        "block16_method": {
            "join_key": ["HHID", "b16_q2"],
            "fce_formula": "b16_q4 + b16_q5 + b16_q6 + b16_q7",
            "normal_repairs": "b16_q8 retained separately; excluded from FCE",
            "land_purchase_item_codes": sorted(LAND_PURCHASE_ITEM_CODES, key=int),
            "subtotal_item_codes_excluded": sorted(SUBTOTAL_ITEM_CODES, key=int),
            "disposals": "b16_q12 + b16_q13 + b16_q14 retained separately; not netted from FCE",
            "q10_q11_q15": "retained for audit; not part of FCE",
        },
        "raw_files": {key: str(path) for key, path in paths.items()},
        "visit_audit": visit_summaries,
        "official_flow_controls": control_rows,
        "errors": errors,
        "warnings": warnings,
        "disclosures": disclosures,
        "outputs": {
            "household_flow": str(HOUSEHOLD_FLOW_FILE),
            "checks": str(CHECKS_FILE),
            "block16_audit": str(BLOCK16_AUDIT_FILE),
            "official_control_validation": str(CONTROL_VALIDATION_FILE),
            "summary": str(SUMMARY_FILE),
        },
    }


def write_summary(final_status: str, panel: Dict[str, dict], paths: Dict[str, Path], control_rows: List[dict]) -> None:
    rural = weighted_flow_metrics(hh for hh in panel.values() if hh.get("Sector") == "1") if panel else {}
    urban = weighted_flow_metrics(hh for hh in panel.values() if hh.get("Sector") == "2") if panel else {}
    hard_control_rows = [r for r in control_rows if r.get("validation_mode") == "HARD"]
    hard_passed = [r for r in hard_control_rows if r.get("status") == "PASS"]

    lines = [
        "==============================================================================",
        "AIDIS 2013 - STEP 03 HOUSEHOLD FLOW BUILD SUMMARY",
        "==============================================================================",
        "",
        f"Project root              : {PROJECT_ROOT}",
        f"Script revision           : {SCRIPT_REVISION}",
        "",
        "COMMON PANEL",
        "------------",
        f"Visit-1 expected          : {EXPECTED_V1_HOUSEHOLDS:,}",
        f"Visit-2 expected          : {EXPECTED_V2_HOUSEHOLDS:,}",
        f"Common expected           : {EXPECTED_COMMON_HOUSEHOLDS:,}",
        f"Output households         : {len(panel):,}",
        "Panel key                 : Exact HHID equality",
        "Flow weight               : Visit-2 Weight_SC",
        "",
        "BLOCK-16 METHOD",
        "---------------",
        "Visit-1 period            : 01-07-2012 to 31-12-2012",
        "Visit-2 period            : 01-01-2013 to 30-06-2013",
        "Annual period             : 01-07-2012 to 30-06-2013",
        "Join key                  : HHID + b16_q2",
        "FCE                       : q4 + q5 + q6 + q7",
        "Normal repairs q8         : EXCLUDED from FCE / retained separately",
        "Land purchase items       : 1, 4, 5, 14",
        "Subtotal items            : 97, 98 EXCLUDED",
        "Disposals q12-q14         : retained separately / NOT netted",
        "",
        "ALL-INDIA FLOW CONTROLS",
        "-----------------------",
    ]

    if rural:
        lines.extend([
            f"Rural FCE incidence      : {rural['FCE incidence']:.6f}%",
            f"Rural average FCE        : {rural['Average FCE']:,.3f}",
        ])
    if urban:
        lines.extend([
            f"Urban FCE incidence      : {urban['FCE incidence']:.6f}%",
            f"Urban average FCE        : {urban['Average FCE']:,.3f}",
        ])

    lines.extend([
        "",
        "VALIDATION",
        "----------",
        f"Machine-readable hard controls : {len(hard_control_rows)}",
        f"Hard controls passed            : {len(hard_passed)}",
        f"Checks                          : {len(checks)}",
        f"Failed checks                   : {sum(1 for c in checks if c['status'] == 'FAIL')}",
        f"Warnings                        : {len(warnings)}",
        f"Disclosures                     : {len(disclosures)}",
        "",
        f"Household flow           : {HOUSEHOLD_FLOW_FILE}",
        f"Checks                   : {CHECKS_FILE}",
        f"Block16 audit            : {BLOCK16_AUDIT_FILE}",
        f"Official controls        : {CONTROL_VALIDATION_FILE}",
        f"Step-03 lock             : {STEP03_LOCK_FILE}",
    ])

    if disclosures:
        lines.extend(["", "DISCLOSURES:"])
        lines.extend(f"  - {d}" for d in disclosures)
    if warnings:
        lines.extend(["", "WARNINGS:"])
        lines.extend(f"  - {w}" for w in warnings)
    if errors:
        lines.extend(["", "ERRORS:"])
        lines.extend(f"  - {e}" for e in errors)

    lines.extend(["", f"STEP 03 STATUS: {final_status}", "=" * 78])
    text = "\n".join(lines)
    SUMMARY_FILE.write_text(text, encoding="utf-8")
    print("\n" + text)


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    print("==============================================================================")
    print("AIDIS 2013 - STEP 03 HOUSEHOLD FLOW BUILD")
    print("NSS 70th Round | Schedule 18.2")
    print("==============================================================================")
    print(f"Project root              : {PROJECT_ROOT}")
    print(f"Script revision           : {SCRIPT_REVISION}")

    methodology, step02_lock = validate_upstream()
    if errors:
        write_csv(CHECKS_FILE, checks, ["check_id", "check_name", "expected", "actual", "status", "severity", "note"])
        write_summary("FAIL", {}, {}, [])
        return 1

    stock, stock_order = load_step02_stock()
    v2_weight_result = discover_visit2_weight_file()
    panel, panel_order, v1_ids, v2_ids = build_common_panel(stock, stock_order, v2_weight_result)

    print("\n[5] Resolving locked Block-16 raw files by column signature")
    try:
        v1_main, v1_value = discover_block16_pair(RAW_V1_ROOT, "Visit 1")
        v2_main, v2_value = discover_block16_pair(RAW_V2_ROOT, "Visit 2")
        paths = {
            "v1_main": v1_main,
            "v1_value": v1_value,
            "v2_main": v2_main,
            "v2_value": v2_value,
        }
        for key, path in paths.items():
            print(f"  PASS | {key:10s} | {path.name}")
    except Exception as exc:
        errors.append(str(exc))
        paths = {}
        print(f"  FAIL | {exc}")

    if errors:
        write_csv(CHECKS_FILE, checks, ["check_id", "check_name", "expected", "actual", "status", "severity", "note"])
        write_summary("FAIL", panel, paths, [])
        return 1

    audit_rows, visit_summaries, _ = build_block16_flows(panel, v1_ids, v2_ids, paths)

    add_check(
        "FINAL_PANEL_COUNT",
        "Final Step-03 household-flow row count",
        EXPECTED_COMMON_HOUSEHOLDS,
        len(panel),
        len(panel) == EXPECTED_COMMON_HOUSEHOLDS,
    )

    control_rows = validate_flow_controls(panel)

    # Work DB is only an implementation cache. Remove it after the join is
    # complete so the final lock captures any cleanup disclosure.
    if WORK_DB.exists():
        try:
            WORK_DB.unlink()
        except OSError:
            disclosures.append(f"Temporary work database could not be removed: {WORK_DB}")

    final_status = "FAIL" if errors else ("PASS_WITH_DISCLOSURES" if warnings or disclosures else "PASS")

    print("\n[8] Writing Step-03 outputs")
    write_flow_output(panel, panel_order)
    write_csv(CHECKS_FILE, checks, ["check_id", "check_name", "expected", "actual", "status", "severity", "note"])
    write_csv(
        BLOCK16_AUDIT_FILE,
        audit_rows,
        [
            "visit", "part", "source_file", "raw_rows", "loaded_rows", "blank_key_rows",
            "unknown_hhid_rows", "duplicate_hhid_item_keys", "negative_component_rows",
            "subtotal_rows", "noncommon_valid_rows", "joined_keys", "main_only_keys", "value_only_keys",
        ],
    )
    write_csv(
        CONTROL_VALIDATION_FILE,
        control_rows,
        [
            "control_id", "family", "sector", "household_group", "metric", "mapped_metric",
            "published_value", "computed_value", "difference", "absolute_tolerance",
            "validation_mode", "status",
        ],
    )
    lock = build_lock(
        methodology, step02_lock, paths, v2_weight_result, panel, visit_summaries, control_rows, final_status
    )
    write_json(STEP03_LOCK_FILE, lock)
    write_summary(final_status, panel, paths, control_rows)

    return 1 if final_status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
