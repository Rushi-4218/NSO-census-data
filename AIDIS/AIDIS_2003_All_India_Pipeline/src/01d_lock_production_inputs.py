from pathlib import Path
import csv
import re
import sys
import unicodedata

from openpyxl import load_workbook


# =============================================================================
# PATHS
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_DIR = ROOT / "input" / "official_csv" / "Data_CSV"
RAW_DIR = ROOT / "input" / "raw"
CACHE_DIR = ROOT / "cache"
REPORT_DIR = ROOT / "output" / "reports"

MANIFEST_FILE = CACHE_DIR / "step01_production_manifest.csv"
SUMMARY_FILE = REPORT_DIR / "step01_production_lock_summary.txt"

CORE_COLUMNS = [
    "HHID",
    "Sector",
    "State",
    "District",
    "Visit_no",
    "MLT",
    "Weight",
]

# These are the 41 original CSV datasets in the official Data_CSV package.
# Visit1 Block 8 is the only missing CSV and will be supplied from the already
# validated XLSX file under input/raw.
EXPECTED_OFFICIAL_CSV = [
    "Visit 1_Block_11.csv",
    "Visit1and2_CB6_part_2.csv",
    "Visit1and2_CB8.csv",
    "Visit1and2_CBlocks_1and2.csv",
    "Visit1and2_CBlock_13.csv",
    "Visit1and2_CB_ 5.csv",
    "Visit1and2_CB_10.csv",
    "Visit1and2_CB_11.csv",
    "Visit1and2_CB_12.csv",
    "Visit1and2_CB_14.csv",
    "Visit1and2_CB_15pt1.csv",
    "Visit1and2_CB_15pt2_part1.csv",
    "Visit1and2_CB_15pt2_part2.csv",
    "Visit1and2_CB_16.csv",
    "Visit1and2_CB_17pt1.csv",
    "Visit1and2_CB_17pt2.csv",
    "Visit1and2_CB_18.csv",
    "Visit1and2_CB_3.csv",
    "Visit1and2_CB_4.csv",
    "Visit1and2_CB_6_part1.csv",
    "Visit1and2_CB_7.csv",
    "Visit1and2_CB_9.csv",
    "Visit1_Block15pt1.csv",
    "Visit1_Block15pt2 part1.csv",
    "Visit1_Block15pt2 part2.csv",
    "Visit1_Block16.csv",
    "Visit1_Block17pt1.csv",
    "Visit1_Block17pt2.csv",
    "Visit1_Blocks_1_and_2.csv",
    "Visit1_Block_10.csv",
    "Visit1_Block_12.csv",
    "Visit1_Block_13.csv",
    "Visit1_Block_14.csv",
    "Visit1_Block_18.csv",
    "Visit1_Block_3.csv",
    "Visit1_Block_4.csv",
    "Visit1_Block_5.csv",
    "Visit1_Block_6.csv",
    "Visit1_Block_6_part2.csv",
    "Visit1_Block_7.csv",
    "Visit1_Block_9.csv",
]


# =============================================================================
# HELPERS
# =============================================================================

def normalize_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return re.sub(r"\s+", " ", text)


def normalize_name(value):
    return normalize_text(value).casefold()


def normalize_column(value):
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value).casefold())


def group_name(file_name):
    n = normalize_name(file_name)
    if n.startswith("visit1and2_") or n.startswith("visit 1 & 2 combined"):
        return "Visit 1 & 2 Combined"
    return "Visit 1"


def read_csv_header(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
                # Read one data row as a lightweight readability check.
                first_data_row = next(reader, None)
            if not header:
                raise ValueError("empty CSV header")
            return [normalize_text(x) for x in header], encoding, first_data_row is not None
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break
    raise RuntimeError(f"Unable to read CSV {path.name}: {last_error}")


def read_xlsx_header(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        hhid = normalize_column("HHID")
        fallback = None
        fallback_row = None

        for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
            values = [normalize_text(x) for x in row]
            if any(values) and fallback is None:
                fallback = values
                fallback_row = row_number

            normalized = {normalize_column(x) for x in values if normalize_text(x)}
            if hhid in normalized:
                return values, ws.title, row_number

            if row_number >= 20:
                break

        if fallback is not None:
            return fallback, ws.title, fallback_row
        raise ValueError("Could not identify a non-empty XLSX header row")
    finally:
        wb.close()


def find_visit1_block8_xlsx():
    matches = []
    for path in RAW_DIR.rglob("*.xlsx"):
        n = normalize_name(path.name)
        if (
            n.startswith("visit 1_block 8_")
            and "agricultural machinery" in n
        ):
            matches.append(path)

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one Visit-1 Block 8 XLSX under input/raw; "
            f"found {len(matches)}: {[p.name for p in matches]}"
        )
    return matches[0]


def missing_core(header):
    normalized = {normalize_column(x) for x in header if normalize_text(x)}
    return [c for c in CORE_COLUMNS if normalize_column(c) not in normalized]


def has_columns(header, required):
    normalized = {normalize_column(x) for x in header if normalize_text(x)}
    return [c for c in required if normalize_column(c) not in normalized]


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 78)
    print("AIDIS 2003 - STEP 01D PRODUCTION INPUT LOCK")
    print("41 official CSV datasets + 1 validated Visit-1 Block 8 XLSX")
    print("=" * 78)

    errors = []
    rows = []

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1. Folder check
    # -------------------------------------------------------------------------
    print("\n[1] Production source folders")
    print(f"Official CSV folder : {OFFICIAL_DIR}")
    print(f"Existing raw folder : {RAW_DIR}")

    if not OFFICIAL_DIR.exists():
        errors.append(f"Official CSV folder not found: {OFFICIAL_DIR}")
    if not RAW_DIR.exists():
        errors.append(f"Raw folder not found: {RAW_DIR}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print("\nSTEP 01D STATUS: FAIL")
        return 1

    # -------------------------------------------------------------------------
    # 2. Official CSV inventory
    # -------------------------------------------------------------------------
    print("\n[2] Official CSV inventory")

    actual_csv = [p for p in OFFICIAL_DIR.rglob("*.csv") if p.is_file()]
    actual_by_norm = {normalize_name(p.name): p for p in actual_csv}
    expected_by_norm = {normalize_name(x): x for x in EXPECTED_OFFICIAL_CSV}

    missing = sorted(set(expected_by_norm) - set(actual_by_norm))
    unexpected = sorted(set(actual_by_norm) - set(expected_by_norm))

    print(f"Expected official CSV files : {len(EXPECTED_OFFICIAL_CSV)}")
    print(f"Actual official CSV files   : {len(actual_csv)}")
    print(f"Missing official CSV files  : {len(missing)}")
    print(f"Unexpected CSV files        : {len(unexpected)}")

    for key in missing:
        errors.append(f"Missing official CSV: {expected_by_norm[key]}")
    for key in unexpected:
        errors.append(f"Unexpected official CSV: {actual_by_norm[key].name}")

    # -------------------------------------------------------------------------
    # 3. Header/readability check for all 41 official CSVs
    # -------------------------------------------------------------------------
    print("\n[3] Official CSV header/readability audit")

    sequence = 0
    for expected_name in EXPECTED_OFFICIAL_CSV:
        path = actual_by_norm.get(normalize_name(expected_name))
        if path is None:
            continue

        sequence += 1
        status = "PASS"
        error_text = ""
        header = []
        encoding = ""

        try:
            header, encoding, has_data = read_csv_header(path)
            core_missing = missing_core(header)
            if core_missing:
                status = "FAIL"
                error_text = "missing core columns: " + ", ".join(core_missing)
                errors.append(f"{path.name}: {error_text}")

            if not has_data:
                status = "FAIL"
                error_text = (error_text + "; " if error_text else "") + "no data rows"
                errors.append(f"{path.name}: no data rows")

            # Critical repair checks for the two files that failed in the XLSX export.
            n = normalize_name(path.name)
            if n == normalize_name("Visit1and2_CB_15pt2_part1.csv"):
                required = ["B15_2_q1", "B15_2_q5", "B15_2_q10", "B15_2_q16"]
                miss = has_columns(header, required)
                if len(header) != 39 or miss:
                    status = "FAIL"
                    msg = f"expected 39 columns and key B15.2 fields; got {len(header)}; missing={miss}"
                    error_text = (error_text + "; " if error_text else "") + msg
                    errors.append(f"{path.name}: {msg}")

            if n == normalize_name("Visit1and2_CB_15pt2_part2.csv"):
                required = ["B15_2_q1", "B15_2_q17", "B15_2_q24"]
                miss = has_columns(header, required)
                if len(header) != 32 or miss:
                    status = "FAIL"
                    msg = f"expected 32 columns and key B15.2 fields; got {len(header)}; missing={miss}"
                    error_text = (error_text + "; " if error_text else "") + msg
                    errors.append(f"{path.name}: {msg}")

        except Exception as exc:
            status = "FAIL"
            core_missing = CORE_COLUMNS[:]
            error_text = f"{type(exc).__name__}: {exc}"
            errors.append(f"Unreadable official CSV {path.name}: {error_text}")

        rows.append({
            "sequence": sequence,
            "group": group_name(path.name),
            "logical_dataset": path.stem,
            "source_type": "official_csv",
            "source_path": str(path),
            "file_name": path.name,
            "size_bytes": path.stat().st_size,
            "column_count": len(header),
            "core_columns_missing": ";".join(core_missing),
            "read_info": f"encoding={encoding}" if encoding else "",
            "status": status,
            "error": error_text,
        })

        print(
            f"[{sequence:02d}/41] {status:4s} | cols={len(header):>2} | {path.name}"
        )

    # -------------------------------------------------------------------------
    # 4. Visit-1 Block 8 XLSX fallback
    # -------------------------------------------------------------------------
    print("\n[4] Visit-1 Block 8 fallback")

    try:
        block8 = find_visit1_block8_xlsx()
        header, sheet, header_row = read_xlsx_header(block8)
        core_missing = missing_core(header)
        status = "PASS"
        error_text = ""

        if core_missing:
            status = "FAIL"
            error_text = "missing core columns: " + ", ".join(core_missing)
            errors.append(f"{block8.name}: {error_text}")

        if len(header) != 32:
            status = "FAIL"
            msg = f"expected 32 columns for Visit-1 Block 8; got {len(header)}"
            error_text = (error_text + "; " if error_text else "") + msg
            errors.append(f"{block8.name}: {msg}")

        sequence += 1
        rows.append({
            "sequence": sequence,
            "group": "Visit 1",
            "logical_dataset": "Visit1_Block_8",
            "source_type": "validated_xlsx_fallback",
            "source_path": str(block8),
            "file_name": block8.name,
            "size_bytes": block8.stat().st_size,
            "column_count": len(header),
            "core_columns_missing": ";".join(core_missing),
            "read_info": f"sheet={sheet};header_row={header_row}",
            "status": status,
            "error": error_text,
        })

        print(f"{status:4s} | cols={len(header):>2} | {block8.name}")

    except Exception as exc:
        errors.append(f"Visit-1 Block 8 fallback failed: {type(exc).__name__}: {exc}")
        print(f"FAIL | {type(exc).__name__}: {exc}")

    # -------------------------------------------------------------------------
    # 5. Production package counts
    # -------------------------------------------------------------------------
    visit1 = sum(1 for r in rows if r["group"] == "Visit 1")
    combined = sum(1 for r in rows if r["group"] == "Visit 1 & 2 Combined")
    passed = sum(1 for r in rows if r["status"] == "PASS")

    if len(rows) != 42:
        errors.append(f"Production manifest should contain 42 datasets; got {len(rows)}")
    if visit1 != 21:
        errors.append(f"Production Visit-1 count should be 21; got {visit1}")
    if combined != 21:
        errors.append(f"Production Combined count should be 21; got {combined}")
    if passed != 42:
        errors.append(f"All 42 production sources should pass; only {passed} passed")

    # -------------------------------------------------------------------------
    # 6. Save manifest + summary
    # -------------------------------------------------------------------------
    fieldnames = [
        "sequence",
        "group",
        "logical_dataset",
        "source_type",
        "source_path",
        "file_name",
        "size_bytes",
        "column_count",
        "core_columns_missing",
        "read_info",
        "status",
        "error",
    ]

    with MANIFEST_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary_lines = [
        "=" * 78,
        "AIDIS 2003 - STEP 01D PRODUCTION INPUT LOCK SUMMARY",
        "=" * 78,
        f"Official CSV folder        : {OFFICIAL_DIR}",
        f"Official CSV expected      : 41",
        f"Official CSV found         : {len(actual_csv)}",
        f"Visit-1 XLSX fallback      : 1",
        f"Production datasets        : {len(rows)}",
        f"Visit 1 datasets           : {visit1}",
        f"Visit 1 & 2 Combined       : {combined}",
        f"Passing production sources : {passed}",
        f"Errors                     : {len(errors)}",
        f"Manifest                   : {MANIFEST_FILE}",
        "",
    ]

    if errors:
        summary_lines.append("ERRORS:")
        summary_lines.extend(f"  - {e}" for e in errors)
        summary_lines.append("")

    status = "PASS" if not errors else "FAIL"
    summary_lines.append(f"STEP 01D STATUS: {status}")
    summary_lines.append("=" * 78)

    SUMMARY_FILE.write_text("\n".join(summary_lines), encoding="utf-8")

    print("\n" + "=" * 78)
    print("AIDIS 2003 - PRODUCTION INPUT LOCK SUMMARY")
    print("=" * 78)
    print(f"Official CSV datasets      : {len(actual_csv)}")
    print(f"Visit-1 XLSX fallback      : 1")
    print(f"Production datasets        : {len(rows)}")
    print(f"Visit 1                    : {visit1}")
    print(f"Visit 1 & 2 Combined       : {combined}")
    print(f"Passing sources            : {passed}")
    print(f"Errors                     : {len(errors)}")
    print(f"Manifest                   : {MANIFEST_FILE}")
    print(f"Summary                    : {SUMMARY_FILE}")
    print()

    if errors:
        print("ERRORS:")
        for error in errors:
            print(f"  - {error}")
        print()

    print(f"STEP 01D STATUS: {status}")
    print("=" * 78)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())