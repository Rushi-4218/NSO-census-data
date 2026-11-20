from pathlib import Path
import csv
import json
import re
import sys
import unicodedata

from openpyxl import load_workbook


# =============================================================================
# PATHS
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "input" / "raw"
METADATA_DIR = ROOT / "input" / "metadata"
REFERENCE_DIR = ROOT / "input" / "reference"
CLIENT_DIR = ROOT / "input" / "client"
CACHE_DIR = ROOT / "cache"
REPORT_DIR = ROOT / "output" / "reports"

MAPPING_FILE = METADATA_DIR / "Key_NSO_Survey_File_Mapping 1.xlsx"
VARIABLES_JSON = METADATA_DIR / "all_variables.json"
VARIABLES_JSONL = METADATA_DIR / "variables.jsonl"
VARIABLES_SUMMARY = METADATA_DIR / "variables_summary.csv"
CLIENT_REQUIREMENT_FILE = CLIENT_DIR / "Additional_datapoints_for_agri_rural_bundles_Seamless 2.docx"

INVENTORY_FILE = CACHE_DIR / "step01_raw_inventory.csv"
SUMMARY_FILE = REPORT_DIR / "step01_input_audit_summary.txt"

SURVEY_TITLE = "Debt & Investment, Jan - Dec 2003"

CORE_COLUMNS = [
    "HHID",
    "Sector",
    "State",
    "District",
    "Visit_no",
    "MLT",
    "Weight",
]

CRITICAL_REFERENCE_PATTERNS = {
    "Schedule_V1_18.pdf": re.compile(r"^schedule[_ -]?v1[_ -]?18.*\.pdf$", re.I),
    "Schedule_V2_18.pdf": re.compile(r"^schedule[_ -]?v2[_ -]?18.*\.pdf$", re.I),
    "Report 500": re.compile(r"(^|\D)500(\D|$).*\.pdf$", re.I),
    "Report 501": re.compile(r"(^|\D)501(\D|$).*\.pdf$", re.I),
    "Report 504": re.compile(r"(^|\D)504(\D|$).*\.pdf$", re.I),
}

OPTIONAL_REFERENCE_PATTERNS = {
    "Report 502": re.compile(r"(^|\D)502(\D|$).*\.pdf$", re.I),
    "Report 503": re.compile(r"(^|\D)503(\D|$).*\.pdf$", re.I),
}


# =============================================================================
# HELPERS
# =============================================================================

def normalize_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_filename(value):
    return normalize_text(value).casefold()


def normalize_column(value):
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value).casefold())


def is_pdf_readable(path):
    try:
        if path.stat().st_size < 100:
            return False
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except Exception:
        return False


def find_reference(pattern):
    if not REFERENCE_DIR.exists():
        return None
    for path in REFERENCE_DIR.rglob("*.pdf"):
        if pattern.search(path.name):
            return path
    return None


def load_expected_raw_files():
    if not MAPPING_FILE.exists():
        raise FileNotFoundError(f"Missing mapping workbook: {MAPPING_FILE}")

    wb = load_workbook(MAPPING_FILE, read_only=True, data_only=True)
    if "AIDIS" not in wb.sheetnames:
        raise ValueError("Mapping workbook does not contain sheet 'AIDIS'.")

    ws = wb["AIDIS"]
    rows = list(ws.iter_rows(values_only=True))

    start_index = None
    for idx, row in enumerate(rows):
        first = normalize_text(row[0] if row else "")
        if first == SURVEY_TITLE:
            start_index = idx
            break

    if start_index is None:
        raise ValueError(
            f"Could not locate survey section '{SURVEY_TITLE}' in AIDIS mapping sheet."
        )

    expected = []
    notes = {}

    # Next row is header. Read until first blank row / next survey section.
    for row in rows[start_index + 2:]:
        first = normalize_text(row[0] if row else "")
        second = normalize_text(row[1] if len(row) > 1 else "")

        if not first:
            break

        expected.append(first)
        notes[first] = second

    wb.close()
    return expected, notes


def read_csv_header_and_rows(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
                row_count = sum(1 for _ in reader)
            return [normalize_text(x) for x in header], row_count, 1, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break
    raise RuntimeError(f"Unable to read CSV {path.name}: {last_error}")


def read_xlsx_header_and_rows(path):

    wb = load_workbook(
        path,
        read_only=True,
        data_only=True
    )

    try:

        ws = wb.active

        header = None
        header_row = None

        total_rows = 0

        hhid_normalized = normalize_column(
            "HHID"
        )

        # -----------------------------------------------------
        # Important:
        # Do NOT depend on ws.max_row.
        #
        # Some NSS 59th Round XLSX files do not expose a valid
        # worksheet dimension to openpyxl in read-only mode,
        # therefore ws.max_row can be None.
        #
        # Stream the worksheet once instead.
        # -----------------------------------------------------

        for row_number, row in enumerate(
            ws.iter_rows(
                values_only=True
            ),
            start=1
        ):

            total_rows = row_number

            # We only need first few rows to locate header.
            if row_number <= 10:

                values = [
                    normalize_text(x)
                    for x in row
                ]

                normalized = {
                    normalize_column(x)
                    for x in values
                    if x
                }

                # Prefer row containing HHID as true header.
                if hhid_normalized in normalized:

                    header = values
                    header_row = row_number

                # Fallback to first non-empty row.
                elif (
                    header is None
                    and
                    any(values)
                ):

                    header = values
                    header_row = row_number

        if header is None:

            header = []
            header_row = 1

        row_count = max(
            0,
            total_rows - header_row
        )

        return (
            header,
            row_count,
            header_row,
            ws.title
        )

    finally:

        wb.close()


def read_raw_file(path):
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        header, row_count, header_row, extra = read_csv_header_and_rows(path)
        return header, row_count, header_row, f"encoding={extra}"
    if suffix == ".xlsx":
        header, row_count, header_row, extra = read_xlsx_header_and_rows(path)
        return header, row_count, header_row, f"sheet={extra}"
    raise ValueError(f"Unsupported raw file type: {path}")


def load_metadata_inventory():
    result = {
        "csv_rows": 0,
        "json_rows": 0,
        "jsonl_rows": 0,
        "variable_names": set(),
        "data_files": set(),
        "labels": set(),
    }

    # variables_summary.csv
    with VARIABLES_SUMMARY.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            result["csv_rows"] += 1
            result["variable_names"].add(normalize_text(row.get("name")))
            result["data_files"].add(normalize_text(row.get("data_file")))
            result["labels"].add(normalize_text(row.get("label")))

    # all_variables.json
    with VARIABLES_JSON.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("all_variables.json must contain a JSON array.")
    result["json_rows"] = len(data)

    # variables.jsonl
    count = 0
    with VARIABLES_JSONL.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except Exception as exc:
                raise ValueError(
                    f"Invalid JSONL at line {line_no} in {VARIABLES_JSONL.name}: {exc}"
                )
            count += 1
    result["jsonl_rows"] = count

    result["variable_names"].discard("")
    result["data_files"].discard("")
    result["labels"].discard("")
    return result


def group_name(file_name):
    name = normalize_filename(file_name)
    if name.startswith("visit 1 & 2 combined_"):
        return "Visit 1 & 2 Combined"
    if name.startswith("visit 1_"):
        return "Visit 1"
    return "Unknown"


def format_int(value):
    return f"{value:,}"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 78)
    print("AIDIS 2003 - STEP 01 INPUT AUDIT")
    print("NSS 59th Round - Debt & Investment, Jan-Dec 2003")
    print("=" * 78)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    errors = []
    warnings = []

    # -------------------------------------------------------------------------
    # 1. Required folders and support files
    # -------------------------------------------------------------------------
    print("\n[1] Folder / support-file audit")

    for folder in (RAW_DIR, METADATA_DIR, REFERENCE_DIR, CLIENT_DIR):
        exists = folder.exists()
        print(f"{str(folder.relative_to(ROOT)):30s}: {'OK' if exists else 'MISSING'}")
        if not exists:
            errors.append(f"Missing folder: {folder}")

    support_files = [
        MAPPING_FILE,
        VARIABLES_JSON,
        VARIABLES_JSONL,
        VARIABLES_SUMMARY,
    ]

    for path in support_files:
        exists = path.exists()
        print(f"{path.name:45s}: {'OK' if exists else 'MISSING'}")
        if not exists:
            errors.append(f"Missing metadata file: {path}")

    if CLIENT_REQUIREMENT_FILE.exists():
        print(f"{CLIENT_REQUIREMENT_FILE.name:45s}: OK")
    else:
        warnings.append(
            f"Client requirement document not found at {CLIENT_REQUIREMENT_FILE}. "
            "It is not required for raw-file integrity, but is required before final export."
        )
        print(f"{CLIENT_REQUIREMENT_FILE.name:45s}: WARNING - NOT FOUND")

    if errors:
        raise RuntimeError("Critical folder/metadata inputs are missing; see messages above.")

    # -------------------------------------------------------------------------
    # 2. Mapping workbook -> expected 2003 raw inventory
    # -------------------------------------------------------------------------
    print("\n[2] Mapping workbook audit")

    expected_names, expected_notes = load_expected_raw_files()
    expected_by_norm = {normalize_filename(x): x for x in expected_names}

    expected_v1 = sum(1 for x in expected_names if group_name(x) == "Visit 1")
    expected_combined = sum(
        1 for x in expected_names if group_name(x) == "Visit 1 & 2 Combined"
    )

    print(f"Expected raw files             : {format_int(len(expected_names))}")
    print(f"  Visit 1                     : {format_int(expected_v1)}")
    print(f"  Visit 1 & 2 Combined        : {format_int(expected_combined)}")

    if len(expected_names) != 42:
        errors.append(
            f"Mapping workbook returned {len(expected_names)} 2003 files; expected 42."
        )
    if expected_v1 != 21 or expected_combined != 21:
        errors.append(
            f"Expected mapping split should be 21 Visit-1 + 21 Combined; got "
            f"{expected_v1} + {expected_combined}."
        )

    # -------------------------------------------------------------------------
    # 3. Actual raw inventory
    # -------------------------------------------------------------------------
    print("\n[3] Raw-data inventory")

    raw_files = sorted(
        [p for p in RAW_DIR.rglob("*") if p.is_file() and p.suffix.casefold() in {".xlsx", ".csv"}],
        key=lambda p: normalize_filename(p.name),
    )

    actual_by_norm = {}
    duplicate_names = []
    for path in raw_files:
        key = normalize_filename(path.name)
        if key in actual_by_norm:
            duplicate_names.append(path.name)
        else:
            actual_by_norm[key] = path

    missing_norms = sorted(set(expected_by_norm) - set(actual_by_norm))
    extra_norms = sorted(set(actual_by_norm) - set(expected_by_norm))

    print(f"Raw .xlsx/.csv files found     : {format_int(len(raw_files))}")
    print(f"Missing expected files         : {format_int(len(missing_norms))}")
    print(f"Unexpected raw files           : {format_int(len(extra_norms))}")
    print(f"Duplicate normalized filenames : {format_int(len(duplicate_names))}")

    if missing_norms:
        for key in missing_norms:
            errors.append(f"Missing raw file: {expected_by_norm[key]}")

    if extra_norms:
        for key in extra_norms:
            errors.append(f"Unexpected raw file: {actual_by_norm[key].name}")

    if duplicate_names:
        for name in duplicate_names:
            errors.append(f"Duplicate raw filename: {name}")

    actual_v1 = sum(1 for p in raw_files if group_name(p.name) == "Visit 1")
    actual_combined = sum(
        1 for p in raw_files if group_name(p.name) == "Visit 1 & 2 Combined"
    )

    print(f"Actual Visit 1 files           : {format_int(actual_v1)}")
    print(f"Actual Combined files          : {format_int(actual_combined)}")

    if actual_v1 != 21 or actual_combined != 21:
        errors.append(
            f"Actual raw split should be 21 Visit-1 + 21 Combined; got "
            f"{actual_v1} + {actual_combined}."
        )

    # -------------------------------------------------------------------------
    # 4. Readability + core header audit
    # -------------------------------------------------------------------------
    print("\n[4] Raw-file readability and header audit")

    inventory_rows = []
    total_rows = 0
    unreadable = 0
    missing_core_file_count = 0

    global_metadata_names = None

    # Metadata inventory will also be used for loose header coverage.
    metadata = load_metadata_inventory()
    global_metadata_names = {normalize_column(x) for x in metadata["variable_names"]}

    for index, expected_name in enumerate(expected_names, start=1):
        key = normalize_filename(expected_name)
        path = actual_by_norm.get(key)
        if path is None:
            continue

        status = "PASS"
        error_text = ""
        header = []
        row_count = 0
        header_row = 0
        extra_info = ""
        missing_core = []
        metadata_coverage = 0.0

        try:
            header, row_count, header_row, extra_info = read_raw_file(path)
            normalized_headers = {normalize_column(x) for x in header if normalize_text(x)}

            missing_core = [
                col for col in CORE_COLUMNS if normalize_column(col) not in normalized_headers
            ]

            if missing_core:
                status = "FAIL"
                missing_core_file_count += 1
                errors.append(
                    f"{path.name}: missing core columns {', '.join(missing_core)}"
                )

            nonblank_headers = [x for x in normalized_headers if x]
            if nonblank_headers:
                matched = sum(1 for x in nonblank_headers if x in global_metadata_names)
                metadata_coverage = matched / len(nonblank_headers) * 100.0

            total_rows += row_count

        except Exception as exc:
            status = "FAIL"
            unreadable += 1
            error_text = f"{type(exc).__name__}: {exc}"
            errors.append(f"Unreadable raw file {path.name}: {error_text}")

        inventory_rows.append(
            {
                "sequence": index,
                "group": group_name(path.name),
                "file_name": path.name,
                "relative_path": str(path.relative_to(ROOT)),
                "extension": path.suffix.casefold(),
                "size_bytes": path.stat().st_size,
                "row_count_excluding_header": row_count,
                "column_count": len([x for x in header if normalize_text(x)]),
                "header_row": header_row,
                "core_columns_missing": ";".join(missing_core),
                "metadata_name_coverage_pct": f"{metadata_coverage:.2f}",
                "read_info": extra_info,
                "status": status,
                "error": error_text,
                "mapping_note": expected_notes.get(expected_name, ""),
            }
        )

        print(
            f"[{index:02d}/42] {status:4s} | rows={row_count:>9,} | "
            f"cols={len([x for x in header if normalize_text(x)]):>3} | {path.name}"
        )

    print(f"\nUnreadable raw files           : {format_int(unreadable)}")
    print(f"Files missing core columns     : {format_int(missing_core_file_count)}")

    # Save inventory regardless of PASS/FAIL.
    fieldnames = [
        "sequence",
        "group",
        "file_name",
        "relative_path",
        "extension",
        "size_bytes",
        "row_count_excluding_header",
        "column_count",
        "header_row",
        "core_columns_missing",
        "metadata_name_coverage_pct",
        "read_info",
        "status",
        "error",
        "mapping_note",
    ]

    with INVENTORY_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(inventory_rows)

    # -------------------------------------------------------------------------
    # 5. Metadata consistency
    # -------------------------------------------------------------------------
    print("\n[5] Metadata-package consistency")

    print(f"variables_summary.csv rows     : {format_int(metadata['csv_rows'])}")
    print(f"all_variables.json records     : {format_int(metadata['json_rows'])}")
    print(f"variables.jsonl records        : {format_int(metadata['jsonl_rows'])}")
    print(f"Distinct metadata data_files   : {format_int(len(metadata['data_files']))}")
    print(f"Distinct variable names        : {format_int(len(metadata['variable_names']))}")

    if not (
        metadata["csv_rows"] == metadata["json_rows"] == metadata["jsonl_rows"]
    ):
        errors.append(
            "Metadata record-count mismatch: "
            f"CSV={metadata['csv_rows']}, JSON={metadata['json_rows']}, "
            f"JSONL={metadata['jsonl_rows']}."
        )

    metadata_core_norm = {normalize_column(x) for x in metadata["variable_names"]}
    missing_metadata_core = [
        col for col in CORE_COLUMNS if normalize_column(col) not in metadata_core_norm
    ]

    print(
        "Core variables in metadata      : "
        + ("PASS" if not missing_metadata_core else "FAIL")
    )

    if missing_metadata_core:
        errors.append(
            "Metadata package is missing core variables: " + ", ".join(missing_metadata_core)
        )

    survey_label_found = any(
        "debt & investment, jan - dec 2003" in normalize_text(label).casefold()
        for label in metadata["labels"]
    )
    print(f"2003 survey label in metadata  : {'PASS' if survey_label_found else 'FAIL'}")
    if not survey_label_found:
        errors.append("2003 Debt & Investment survey label not found in metadata package.")

    # -------------------------------------------------------------------------
    # 6. Reference PDF audit
    # -------------------------------------------------------------------------
    print("\n[6] Official reference PDF audit")

    for label, pattern in CRITICAL_REFERENCE_PATTERNS.items():
        path = find_reference(pattern)
        if path is None:
            print(f"{label:25s}: MISSING")
            errors.append(f"Missing critical reference PDF: {label}")
        elif not is_pdf_readable(path):
            print(f"{label:25s}: UNREADABLE ({path.name})")
            errors.append(f"Unreadable critical reference PDF: {path}")
        else:
            print(f"{label:25s}: PASS ({path.name})")

    for label, pattern in OPTIONAL_REFERENCE_PATTERNS.items():
        path = find_reference(pattern)
        if path is None:
            print(f"{label:25s}: WARNING - NOT FOUND")
            warnings.append(f"Optional official reference PDF not found: {label}")
        elif not is_pdf_readable(path):
            print(f"{label:25s}: WARNING - UNREADABLE ({path.name})")
            warnings.append(f"Optional reference PDF unreadable: {path}")
        else:
            print(f"{label:25s}: PASS ({path.name})")

    # -------------------------------------------------------------------------
    # FINAL RESULT
    # -------------------------------------------------------------------------
    status = "PASS" if not errors else "FAIL"

    summary_lines = [
        "=" * 78,
        "AIDIS 2003 - STEP 01 INPUT AUDIT SUMMARY",
        "=" * 78,
        "",
        f"Project root              : {ROOT}",
        f"Expected raw files        : {len(expected_names):,}",
        f"Actual raw files          : {len(raw_files):,}",
        f"Visit 1 files             : {actual_v1:,}",
        f"Visit 1 & 2 Combined      : {actual_combined:,}",
        f"Missing raw files         : {len(missing_norms):,}",
        f"Unexpected raw files      : {len(extra_norms):,}",
        f"Duplicate raw filenames   : {len(duplicate_names):,}",
        f"Unreadable raw files      : {unreadable:,}",
        f"Missing-core files        : {missing_core_file_count:,}",
        f"Metadata CSV records      : {metadata['csv_rows']:,}",
        f"Metadata JSON records     : {metadata['json_rows']:,}",
        f"Metadata JSONL records    : {metadata['jsonl_rows']:,}",
        f"Inventory report          : {INVENTORY_FILE}",
        "",
        f"Errors                    : {len(errors):,}",
        f"Warnings                  : {len(warnings):,}",
        "",
    ]

    if errors:
        summary_lines.append("ERRORS:")
        summary_lines.extend(f"  - {x}" for x in errors)
        summary_lines.append("")

    if warnings:
        summary_lines.append("WARNINGS:")
        summary_lines.extend(f"  - {x}" for x in warnings)
        summary_lines.append("")

    summary_lines.extend(
        [
            f"STEP 01 STATUS: {status}",
            "=" * 78,
        ]
    )

    SUMMARY_FILE.write_text("\n".join(summary_lines), encoding="utf-8")

    print("\n" + "\n".join(summary_lines))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\n" + "=" * 78)
        print("STEP 01 INPUT AUDIT: FAIL")
        print("=" * 78)
        print(f"\n{type(exc).__name__}: {exc}")
        sys.exit(1)