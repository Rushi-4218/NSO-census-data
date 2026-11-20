from pathlib import Path
from collections import Counter, defaultdict
import csv
import re
import sys

from openpyxl import load_workbook
import pymupdf


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = (
    PROJECT_ROOT
    / "input"
    / "raw"
    / "Debt and Investment 77th RoundJANUARY 2019 – DECEMBER 2019-Visit 1 and Visit 2"
)

DDI_FILE = (
    PROJECT_ROOT
    / "input"
    / "ddi"
    / "AIDIS_77th_Round_Master_DDI.xlsx"
)

PDF_FILE = (
    PROJECT_ROOT
    / "input"
    / "reference"
    / "NSS_77th_Vol_I.pdf"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)


# ============================================================
# REPORT FILES
# ============================================================

RAW_FILE_REPORT = (
    REPORT_DIR
    / "raw_file_inventory.csv"
)

RAW_COLUMN_REPORT = (
    REPORT_DIR
    / "raw_column_inventory.csv"
)

DDI_SHEET_REPORT = (
    REPORT_DIR
    / "ddi_sheet_inventory.csv"
)

DDI_COLUMN_REPORT = (
    REPORT_DIR
    / "ddi_column_inventory.csv"
)

CORE_FIELD_REPORT = (
    REPORT_DIR
    / "core_field_candidates.csv"
)

SUMMARY_REPORT = (
    REPORT_DIR
    / "input_audit_summary.txt"
)


# ============================================================
# EXPECTED RAW STRUCTURE
# ============================================================

EXPECTED_TOTAL_WORKBOOKS = 23

EXPECTED_LEVELS = {
    1: set(range(1, 18)),
    2: {1, 14, 15, 16, 17, 18},
}


# These are the DDI sheets we currently expect.
EXPECTED_DDI_SHEETS = {
    "Master_DDI_AIDIS_77th_Round",
    "DDI_Mapping",
    "Data_Transformation_Tree",
}


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(value):
    """
    Convert text to a simple lowercase alphanumeric key.

    Example:
        'Household ID' -> 'householdid'
        'District_Code' -> 'districtcode'
    """

    if value is None:
        return ""

    value = str(value).strip().lower()

    return re.sub(
        r"[^a-z0-9]+",
        "",
        value
    )


def clean_cell(value):
    if value is None:
        return ""

    return str(value).strip()


# ============================================================
# VISIT / LEVEL IDENTIFICATION
# ============================================================

def identify_visit_level(path):
    """
    Try to identify Visit and Level from the complete file path.
    """

    text = str(path).replace("\\", "/")

    visit = None
    level = None

    visit_patterns = [
        r"visit[\s_\-]*0*([12])",
        r"\bv[\s_\-]*0*([12])\b",
    ]

    level_patterns = [
        r"level[\s_\-]*0*(\d{1,2})",
        r"\blvl[\s_\-]*0*(\d{1,2})\b",
        r"\bl[\s_\-]*0*(\d{1,2})\b",
    ]

    for pattern in visit_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if match:
            visit = int(
                match.group(1)
            )
            break

    for pattern in level_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if match:
            level = int(
                match.group(1)
            )
            break

    return visit, level


# ============================================================
# HEADER DETECTION
# ============================================================

HEADER_KEYWORDS = {
    "hhid",
    "householdid",
    "household",
    "state",
    "statecode",
    "district",
    "districtcode",
    "sector",
    "sectorcode",
    "mlt",
    "multiplier",
    "weight",
    "visit",
    "level",
    "block",
    "fsu",
    "sample",
    "serial",
    "stratum",
}


def detect_header_row(ws, max_scan_rows=20):
    """
    Detect the most likely header row.

    This version does NOT depend on ws.max_row because some
    NSS Excel files opened in OpenPyXL read-only mode return
    max_row=None.

    We simply stream the first max_scan_rows rows and stop.
    """

    best_row = None
    best_score = -1
    best_values = []

    try:
        row_iterator = ws.iter_rows(
            values_only=True
        )

        for row_number, row_values in enumerate(
            row_iterator,
            start=1
        ):
            # We only need to inspect the first few rows.
            if row_number > max_scan_rows:
                break

            values = [
                clean_cell(value)
                for value in row_values
            ]

            nonempty = [
                value
                for value in values
                if value
            ]

            if not nonempty:
                continue

            normalized = [
                normalize_text(value)
                for value in nonempty
            ]

            string_count = sum(
                1
                for value in nonempty
                if not re.fullmatch(
                    r"[-+]?\d+(?:\.\d+)?",
                    value
                )
            )

            keyword_hits = 0

            for value in normalized:
                for keyword in HEADER_KEYWORDS:
                    if keyword in value:
                        keyword_hits += 1
                        break

            unique_count = len(
                set(normalized)
            )

            score = (
                keyword_hits * 1000
                +
                string_count * 10
                +
                unique_count
                +
                len(nonempty)
            )

            if score > best_score:
                best_score = score
                best_row = row_number
                best_values = values

    except Exception:
        # Some read-only Excel files can have incorrect or
        # undefined worksheet dimensions. OpenPyXL provides
        # reset_dimensions() specifically for this situation.
        if hasattr(ws, "reset_dimensions"):
            ws.reset_dimensions()

            row_iterator = ws.iter_rows(
                values_only=True
            )

            for row_number, row_values in enumerate(
                row_iterator,
                start=1
            ):
                if row_number > max_scan_rows:
                    break

                values = [
                    clean_cell(value)
                    for value in row_values
                ]

                nonempty = [
                    value
                    for value in values
                    if value
                ]

                if not nonempty:
                    continue

                normalized = [
                    normalize_text(value)
                    for value in nonempty
                ]

                string_count = sum(
                    1
                    for value in nonempty
                    if not re.fullmatch(
                        r"[-+]?\d+(?:\.\d+)?",
                        value
                    )
                )

                keyword_hits = 0

                for value in normalized:
                    for keyword in HEADER_KEYWORDS:
                        if keyword in value:
                            keyword_hits += 1
                            break

                unique_count = len(
                    set(normalized)
                )

                score = (
                    keyword_hits * 1000
                    +
                    string_count * 10
                    +
                    unique_count
                    +
                    len(nonempty)
                )

                if score > best_score:
                    best_score = score
                    best_row = row_number
                    best_values = values

        else:
            raise

    return (
        best_row,
        best_values
    )

# ============================================================
# RAW XLSX INVENTORY
# ============================================================

def find_raw_workbooks():
    """
    Find every Excel workbook under the raw input folder.
    Temporary Excel lock files are ignored.
    """

    extensions = {
        ".xlsx",
        ".xlsm",
        ".xls",
    }

    files = []

    for path in RAW_DIR.rglob("*"):
        if not path.is_file():
            continue

        if path.name.startswith("~$"):
            continue

        if path.suffix.lower() in extensions:
            files.append(path)

    return sorted(
        files,
        key=lambda p: str(p).lower()
    )


def audit_raw_workbooks(raw_files):
    """
    Inspect workbook sheets and raw column headers.
    """

    file_rows = []
    column_rows = []

    visit_level_map = defaultdict(
        list
    )

    unsupported_xls = []

    for index, file_path in enumerate(
        raw_files,
        start=1
    ):
        relative_path = file_path.relative_to(
            RAW_DIR
        )

        visit, level = identify_visit_level(
            relative_path
        )

        if visit is not None and level is not None:
            visit_level_map[
                (visit, level)
            ].append(
                str(relative_path)
            )

        print(
            f"[{index:02d}/{len(raw_files):02d}] "
            f"{relative_path}"
        )

        if file_path.suffix.lower() == ".xls":
            unsupported_xls.append(
                str(relative_path)
            )

            file_rows.append(
                {
                    "Relative_Path":
                        str(relative_path),

                    "File_Name":
                        file_path.name,

                    "Visit":
                        visit or "",

                    "Level":
                        level or "",

                    "Sheet_Count":
                        "",

                    "Sheets":
                        "",

                    "Status":
                        "UNSUPPORTED_XLS",
                }
            )

            continue

        try:
            workbook = load_workbook(
                file_path,
                read_only=True,
                data_only=False
            )

        except Exception as exc:
            file_rows.append(
                {
                    "Relative_Path":
                        str(relative_path),

                    "File_Name":
                        file_path.name,

                    "Visit":
                        visit or "",

                    "Level":
                        level or "",

                    "Sheet_Count":
                        "",

                    "Sheets":
                        "",

                    "Status":
                        (
                            "OPEN_ERROR: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                }
            )

            continue

        sheet_names = workbook.sheetnames

        file_rows.append(
            {
                "Relative_Path":
                    str(relative_path),

                "File_Name":
                    file_path.name,

                "Visit":
                    visit or "",

                "Level":
                    level or "",

                "Sheet_Count":
                    len(sheet_names),

                "Sheets":
                    " | ".join(sheet_names),

                "Status":
                    "PASS",
            }
        )

        for sheet_name in sheet_names:
            ws = workbook[sheet_name]

            header_row, headers = detect_header_row(
                ws
            )

            if header_row is None:
                continue

            for position, header in enumerate(
                headers,
                start=1
            ):
                header = clean_cell(
                    header
                )

                if not header:
                    continue

                column_rows.append(
                    {
                        "Relative_Path":
                            str(relative_path),

                        "File_Name":
                            file_path.name,

                        "Visit":
                            visit or "",

                        "Level":
                            level or "",

                        "Sheet_Name":
                            sheet_name,

                        "Header_Row":
                            header_row,

                        "Column_Position":
                            position,

                        "Column_Name":
                            header,

                        "Normalized_Column_Name":
                            normalize_text(
                                header
                            ),
                    }
                )

        workbook.close()

    return (
        file_rows,
        column_rows,
        visit_level_map,
        unsupported_xls,
    )


# ============================================================
# DDI INVENTORY
# ============================================================

def audit_ddi():
    """
    Inspect all DDI sheets and their detected column headers.
    """

    workbook = load_workbook(
        DDI_FILE,
        read_only=True,
        data_only=False
    )

    sheet_rows = []
    column_rows = []

    print("\nDDI sheets found:")

    for sheet_name in workbook.sheetnames:
        ws = workbook[sheet_name]

        header_row, headers = detect_header_row(
            ws,
            max_scan_rows=25
        )

        print(
            f"  - {sheet_name}"
        )

        sheet_rows.append(
            {
                "Sheet_Name":
                    sheet_name,

                "Max_Rows":
                    ws.iter_rows(values_only=True),

                "Max_Columns":
                    ws.max_column,

                "Detected_Header_Row":
                    header_row or "",

                "Status":
                    (
                        "PASS"
                        if header_row
                        else "NO_HEADER_DETECTED"
                    ),
            }
        )

        if header_row:
            print(
                f"      Header row: "
                f"{header_row}"
            )

            header_preview = []

            for position, header in enumerate(
                headers,
                start=1
            ):
                header = clean_cell(
                    header
                )

                if not header:
                    continue

                header_preview.append(
                    header
                )

                column_rows.append(
                    {
                        "Sheet_Name":
                            sheet_name,

                        "Header_Row":
                            header_row,

                        "Column_Position":
                            position,

                        "Column_Name":
                            header,

                        "Normalized_Column_Name":
                            normalize_text(
                                header
                            ),
                    }
                )

            print(
                "      Columns: "
                +
                " | ".join(
                    header_preview[:20]
                )
            )

            if len(header_preview) > 20:
                print(
                    f"      ... plus "
                    f"{len(header_preview) - 20} "
                    f"more columns"
                )

    ddi_sheet_names = set(
    workbook.sheetnames
    )

    workbook.close()

    return (
        sheet_rows,
        column_rows,
        ddi_sheet_names
    )


# ============================================================
# CORE FIELD DISCOVERY
# ============================================================

CORE_FIELD_PATTERNS = {
    "HHID": [
        r"^hhid$",
        r"householdid",
        r"householdidentifier",
        r"hhidentifier",
    ],

    "MLT": [
        r"^mlt$",
        r"multiplier",
        r"surveyweight",
        r"samplingweight",
        r"weight",
    ],

    "STATE": [
        r"^state$",
        r"statecode",
        r"stateid",
    ],

    "DISTRICT": [
        r"^district$",
        r"districtcode",
        r"districtid",
    ],

    "SECTOR": [
        r"^sector$",
        r"sectorcode",
        r"ruralurban",
    ],

    "NSS_REGION": [
        r"nssregion",
        r"regioncode",
    ],

    "VISIT": [
        r"^visit$",
        r"visitno",
        r"visitnumber",
    ],
}


def discover_core_fields(raw_column_rows):
    """
    Search all raw headers for likely join/geography/weight fields.
    """

    candidates = []

    for row in raw_column_rows:
        normalized = row[
            "Normalized_Column_Name"
        ]

        for field_name, patterns in (
            CORE_FIELD_PATTERNS.items()
        ):
            matched = False

            for pattern in patterns:
                if re.search(
                    pattern,
                    normalized,
                    flags=re.IGNORECASE
                ):
                    matched = True
                    break

            if not matched:
                continue

            candidates.append(
                {
                    "Core_Field":
                        field_name,

                    "Visit":
                        row["Visit"],

                    "Level":
                        row["Level"],

                    "File_Name":
                        row["File_Name"],

                    "Sheet_Name":
                        row["Sheet_Name"],

                    "Column_Position":
                        row["Column_Position"],

                    "Column_Name":
                        row["Column_Name"],

                    "Normalized_Column_Name":
                        normalized,
                }
            )

    return candidates


# ============================================================
# PDF VALIDATION
# ============================================================

def validate_pdf():
    """
    Verify that the PDF is the expected NSS 77 AIDIS reference.
    """

    document = pymupdf.open(
        PDF_FILE
    )

    page_count = len(
        document
    )

    pages_to_read = min(
        page_count,
        15
    )

    first_text = "\n".join(
        document[
            page_number
        ].get_text()
        for page_number in range(
            pages_to_read
        )
    )

    normalized = (
        first_text
        .lower()
        .replace("\n", " ")
    )

    checks = {
        "NSS 77":
            bool(
                re.search(
                    r"nss\s*77",
                    normalized
                )
            ),

        "Debt and Investment":
            (
                "debt and investment"
                in normalized
            ),

        "Instructions to Field Staff":
            (
                "instructions to field staff"
                in normalized
            ),
    }

    document.close()

    return (
        page_count,
        checks
    )


# ============================================================
# CSV WRITER
# ============================================================

def write_csv(
    path,
    rows,
    fieldnames
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                row
            )


# ============================================================
# EXPECTED VISIT / LEVEL CHECK
# ============================================================

def validate_visit_levels(
    visit_level_map
):
    results = []

    for visit, expected_levels in (
        EXPECTED_LEVELS.items()
    ):
        observed_levels = {
            level
            for (
                found_visit,
                level
            ) in visit_level_map
            if found_visit == visit
        }

        missing = sorted(
            expected_levels
            -
            observed_levels
        )

        extra = sorted(
            observed_levels
            -
            expected_levels
        )

        duplicates = []

        for level in sorted(
            observed_levels
        ):
            files = visit_level_map.get(
                (visit, level),
                []
            )

            if len(files) > 1:
                duplicates.append(
                    (
                        level,
                        len(files)
                    )
                )

        results.append(
            {
                "visit":
                    visit,

                "expected":
                    sorted(
                        expected_levels
                    ),

                "observed":
                    sorted(
                        observed_levels
                    ),

                "missing":
                    missing,

                "extra":
                    extra,

                "duplicates":
                    duplicates,
            }
        )

    return results


# ============================================================
# MAIN
# ============================================================

def main():
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 78)
    print("AIDIS NSS 77 - RAW INPUT + DDI AUDIT")
    print("=" * 78)

    # --------------------------------------------------------
    # Input existence
    # --------------------------------------------------------

    print("\nINPUT PATH CHECK")
    print("-" * 78)

    inputs = {
        "RAW_DIR":
            RAW_DIR,

        "DDI_FILE":
            DDI_FILE,

        "PDF_FILE":
            PDF_FILE,
    }

    missing_inputs = []

    for name, path in inputs.items():
        exists = path.exists()

        print(
            f"{name:<10}: "
            f"{'FOUND' if exists else 'MISSING'}"
        )

        print(
            f"            {path}"
        )

        if not exists:
            missing_inputs.append(
                str(path)
            )

    if missing_inputs:
        print(
            "\nINPUT AUDIT STATUS: FAIL"
        )

        print(
            "\nMissing input paths:"
        )

        for path in missing_inputs:
            print(
                f"  - {path}"
            )

        sys.exit(1)

    # --------------------------------------------------------
    # Raw file inventory
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("RAW MICRODATA INVENTORY")
    print("=" * 78)

    raw_files = find_raw_workbooks()

    print(
        f"\nExcel workbooks found: "
        f"{len(raw_files)}"
    )

    (
        raw_file_rows,
        raw_column_rows,
        visit_level_map,
        unsupported_xls,
    ) = audit_raw_workbooks(
        raw_files
    )

    write_csv(
        RAW_FILE_REPORT,
        raw_file_rows,
        [
            "Relative_Path",
            "File_Name",
            "Visit",
            "Level",
            "Sheet_Count",
            "Sheets",
            "Status",
        ]
    )

    write_csv(
        RAW_COLUMN_REPORT,
        raw_column_rows,
        [
            "Relative_Path",
            "File_Name",
            "Visit",
            "Level",
            "Sheet_Name",
            "Header_Row",
            "Column_Position",
            "Column_Name",
            "Normalized_Column_Name",
        ]
    )

    # --------------------------------------------------------
    # Visit/Level validation
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("VISIT / LEVEL COVERAGE")
    print("=" * 78)

    coverage_results = (
        validate_visit_levels(
            visit_level_map
        )
    )

    visit_level_pass = True

    for result in coverage_results:
        visit = result[
            "visit"
        ]

        print(
            f"\nVisit {visit}"
        )

        print(
            "Expected levels : "
            +
            ", ".join(
                f"{level:02d}"
                for level in result[
                    "expected"
                ]
            )
        )

        print(
            "Observed levels : "
            +
            ", ".join(
                f"{level:02d}"
                for level in result[
                    "observed"
                ]
            )
        )

        print(
            "Missing levels  : "
            +
            (
                ", ".join(
                    f"{level:02d}"
                    for level in result[
                        "missing"
                    ]
                )
                or "None"
            )
        )

        print(
            "Extra levels    : "
            +
            (
                ", ".join(
                    f"{level:02d}"
                    for level in result[
                        "extra"
                    ]
                )
                or "None"
            )
        )

        print(
            "Duplicate levels: "
            +
            (
                ", ".join(
                    f"{level:02d} ({count} files)"
                    for level, count
                    in result[
                        "duplicates"
                    ]
                )
                or "None"
            )
        )

        if (
            result["missing"]
            or
            result["extra"]
            or
            result["duplicates"]
        ):
            visit_level_pass = False

    # --------------------------------------------------------
    # Core columns
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("CORE FIELD DISCOVERY")
    print("=" * 78)

    core_candidates = (
        discover_core_fields(
            raw_column_rows
        )
    )

    write_csv(
        CORE_FIELD_REPORT,
        core_candidates,
        [
            "Core_Field",
            "Visit",
            "Level",
            "File_Name",
            "Sheet_Name",
            "Column_Position",
            "Column_Name",
            "Normalized_Column_Name",
        ]
    )

    candidate_counts = Counter(
        row["Core_Field"]
        for row in core_candidates
    )

    for field in (
        CORE_FIELD_PATTERNS.keys()
    ):
        print(
            f"{field:<12}: "
            f"{candidate_counts.get(field, 0)} "
            f"candidate(s)"
        )

    # --------------------------------------------------------
    # DDI audit
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("MASTER DDI INVENTORY")
    print("=" * 78)

    (
        ddi_sheet_rows,
        ddi_column_rows,
        ddi_sheet_names,
    ) = audit_ddi()

    write_csv(
        DDI_SHEET_REPORT,
        ddi_sheet_rows,
        [
            "Sheet_Name",
            "Max_Rows",
            "Max_Columns",
            "Detected_Header_Row",
            "Status",
        ]
    )

    write_csv(
        DDI_COLUMN_REPORT,
        ddi_column_rows,
        [
            "Sheet_Name",
            "Header_Row",
            "Column_Position",
            "Column_Name",
            "Normalized_Column_Name",
        ]
    )

    missing_ddi_sheets = sorted(
        EXPECTED_DDI_SHEETS
        -
        ddi_sheet_names
    )

    extra_ddi_sheets = sorted(
        ddi_sheet_names
        -
        EXPECTED_DDI_SHEETS
    )

    print(
        "\nExpected DDI sheets missing: "
        +
        (
            ", ".join(
                missing_ddi_sheets
            )
            or "None"
        )
    )

    print(
        "Additional DDI sheets      : "
        +
        (
            ", ".join(
                extra_ddi_sheets
            )
            or "None"
        )
    )

    ddi_pass = (
        len(
            missing_ddi_sheets
        )
        ==
        0
    )

    # --------------------------------------------------------
    # PDF validation
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("NSS 77 REFERENCE PDF CHECK")
    print("=" * 78)

    pdf_pages, pdf_checks = (
        validate_pdf()
    )

    print(
        f"\nPDF pages: "
        f"{pdf_pages}"
    )

    for name, status in (
        pdf_checks.items()
    ):
        print(
            f"{name:<30}: "
            f"{status}"
        )

    pdf_pass = all(
        pdf_checks.values()
    )

    # --------------------------------------------------------
    # Final audit result
    # --------------------------------------------------------

    raw_count_pass = (
        len(raw_files)
        ==
        EXPECTED_TOTAL_WORKBOOKS
    )

    unsupported_pass = (
        len(unsupported_xls)
        ==
        0
    )

    core_pass = (
        candidate_counts.get(
            "HHID",
            0
        )
        >
        0
        and
        candidate_counts.get(
            "MLT",
            0
        )
        >
        0
    )

    final_pass = all(
        [
            raw_count_pass,
            visit_level_pass,
            unsupported_pass,
            ddi_pass,
            pdf_pass,
            core_pass,
        ]
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    summary_lines = [
        "=" * 78,
        "AIDIS NSS 77 INPUT AUDIT SUMMARY",
        "=" * 78,
        "",
        f"Raw workbook count            : {len(raw_files)}",
        f"Expected workbook count       : {EXPECTED_TOTAL_WORKBOOKS}",
        (
            "Raw workbook count status     : "
            +
            (
                "PASS"
                if raw_count_pass
                else "FAIL"
            )
        ),
        "",
        (
            "Visit / Level coverage         : "
            +
            (
                "PASS"
                if visit_level_pass
                else "FAIL"
            )
        ),
        (
            "Unsupported .xls files         : "
            f"{len(unsupported_xls)}"
        ),
        "",
        (
            "HHID candidates                : "
            f"{candidate_counts.get('HHID', 0)}"
        ),
        (
            "MLT candidates                 : "
            f"{candidate_counts.get('MLT', 0)}"
        ),
        (
            "State candidates               : "
            f"{candidate_counts.get('STATE', 0)}"
        ),
        (
            "District candidates            : "
            f"{candidate_counts.get('DISTRICT', 0)}"
        ),
        (
            "Sector candidates              : "
            f"{candidate_counts.get('SECTOR', 0)}"
        ),
        "",
        (
            "DDI expected sheets            : "
            f"{len(EXPECTED_DDI_SHEETS)}"
        ),
        (
            "DDI sheets found               : "
            f"{len(ddi_sheet_names)}"
        ),
        (
            "DDI structure status           : "
            +
            (
                "PASS"
                if ddi_pass
                else "FAIL"
            )
        ),
        "",
        (
            "PDF pages                      : "
            f"{pdf_pages}"
        ),
        (
            "PDF identity status            : "
            +
            (
                "PASS"
                if pdf_pass
                else "FAIL"
            )
        ),
        "",
        (
            "INPUT AUDIT STATUS             : "
            +
            (
                "PASS"
                if final_pass
                else "REVIEW"
            )
        ),
        "=" * 78,
    ]

    SUMMARY_REPORT.write_text(
        "\n".join(
            summary_lines
        ),
        encoding="utf-8"
    )

    print("\n")
    print(
        "\n".join(
            summary_lines
        )
    )

    print(
        "\nReports created:"
    )

    print(
        RAW_FILE_REPORT
    )

    print(
        RAW_COLUMN_REPORT
    )

    print(
        DDI_SHEET_REPORT
    )

    print(
        DDI_COLUMN_REPORT
    )

    print(
        CORE_FIELD_REPORT
    )

    print(
        SUMMARY_REPORT
    )

    if not final_pass:
        print(
            "\nNOTE:"
            "\nREVIEW does not mean the data is wrong."
            "\nIt means one of the expected structures "
            "needs inspection before calculation."
        )


if __name__ == "__main__":
    main()