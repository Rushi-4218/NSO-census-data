from pathlib import Path
from collections import Counter
import csv
import sys

from openpyxl import load_workbook


# ============================================================
# PATHS
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

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

DETAIL_REPORT = (
    REPORT_DIR
    / "ddi_raw_mapping_validation.csv"
)

SUMMARY_REPORT = (
    REPORT_DIR
    / "ddi_raw_mapping_validation_summary.txt"
)


# ============================================================
# DDI SHEET NAMES
# ============================================================

MASTER_SHEET = "Master_DDI_AIDIS_77th_Round"
KPI_SHEET = "DDI_Mapping"
TREE_SHEET = "Data_Transformation_Tree"


# ============================================================
# EXPECTED DDI HEADERS
# ============================================================

MASTER_REQUIRED_HEADERS = {
    "Row_ID",
    "Visit",
    "Level",
    "Source_File",
    "Source_Sheet",
    "Original_Column_Name",
    "Column_Position",
    "DDI_Variable_Name",
    "Variable_Label",
    "Primary_Key",
    "Foreign_Key",
    "Weight_Variable",
    "Validation_Status",
    "Mapping_Status",
}

KPI_REQUIRED_HEADERS = {
    "ID",
    "Name",
    "Sub_Breakdown_Dimension",
    "Required_Source_Variables",
    "Source_File_Level",
    "Formula_Logic",
    "Weight_Variable",
}

TREE_REQUIRED_HEADERS = {
    "Level1",
    "Level2",
    "Level3",
    "Level4",
    "Level5",
    "Level6",
    "Node_Type",
    "Required_Source_Variable",
    "Source_File_Level",
    "Computation_Logic",
    "Notes",
}


# ============================================================
# CRITICAL VARIABLES NEEDED FOR HOUSEHOLD BASE
# ============================================================

CRITICAL_LEVEL1_VARIABLES = {
    "HHID",
    "Sector",
    "NSS_Region",
    "State",
    "State_District",
    "District",
    "Stratum",
    "SubStratumNo",
    "SSS",
    "visitNo",
    "MLT",
}

CRITICAL_LEVEL3_VARIABLES = {
    "HHID",
    "b4q4",
    "b4q7",
    "MLT",
}


# ============================================================
# HELPERS
# ============================================================

def clean(value):
    if value is None:
        return ""

    return str(value).strip()


def normalize_position(value):
    if value is None:
        return None

    try:
        return int(float(value))
    except Exception:
        return None


def read_first_nonempty_row(ws, scan_limit=5):
    """
    Raw microdata headers are expected at the top of Sheet1.

    This function safely checks the first few rows and returns
    the first non-empty row.
    """

    for row_number, values in enumerate(
        ws.iter_rows(values_only=True),
        start=1
    ):
        if row_number > scan_limit:
            break

        cleaned = [
            clean(value)
            for value in values
        ]

        if any(cleaned):
            return row_number, cleaned

    return None, []


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(row)


# ============================================================
# FIND RAW FILES
# ============================================================

def build_raw_file_index():
    """
    Index the raw folder by exact filename.

    The DDI Source_File values should match these names.
    """

    index = {}

    for path in RAW_DIR.rglob("*.xlsx"):

        if path.name.startswith("~$"):
            continue

        if path.name in index:
            raise ValueError(
                f"Duplicate raw filename detected:\n"
                f"{path.name}\n\n"
                f"{index[path.name]}\n"
                f"{path}"
            )

        index[path.name] = path

    return index


# ============================================================
# VALIDATE DDI SHEET STRUCTURE
# ============================================================

def validate_ddi_headers(workbook):

    checks = [
        (
            MASTER_SHEET,
            MASTER_REQUIRED_HEADERS
        ),
        (
            KPI_SHEET,
            KPI_REQUIRED_HEADERS
        ),
        (
            TREE_SHEET,
            TREE_REQUIRED_HEADERS
        ),
    ]

    print("\n" + "=" * 78)
    print("VALIDATING DDI HEADERS")
    print("=" * 78)

    for sheet_name, required in checks:

        if sheet_name not in workbook.sheetnames:
            raise ValueError(
                f"Missing DDI sheet: {sheet_name}"
            )

        ws = workbook[sheet_name]

        # DDI uses row 1 as the real header.
        headers = [
            clean(value)
            for value in next(
                ws.iter_rows(
                    min_row=1,
                    max_row=1,
                    values_only=True
                )
            )
        ]

        header_set = set(headers)

        missing = sorted(
            required
            -
            header_set
        )

        print(
            f"\n{sheet_name}"
        )

        print(
            f"Header row       : 1"
        )

        print(
            f"Columns detected : {len(headers)}"
        )

        print(
            f"Missing required : "
            f"{len(missing)}"
        )

        if missing:
            for column in missing:
                print(
                    f"    - {column}"
                )

            raise ValueError(
                f"DDI sheet structure failed: "
                f"{sheet_name}"
            )

        print(
            "Status           : PASS"
        )


# ============================================================
# LOAD RAW HEADER WITH CACHE
# ============================================================

def get_raw_header(
    file_path,
    sheet_name,
    cache
):

    cache_key = (
        str(file_path),
        sheet_name
    )

    if cache_key in cache:
        return cache[cache_key]

    workbook = load_workbook(
        file_path,
        read_only=True,
        data_only=False
    )

    if sheet_name not in workbook.sheetnames:

        workbook.close()

        result = {
            "status":
                "SHEET_NOT_FOUND",

            "header_row":
                None,

            "headers":
                [],
        }

        cache[
            cache_key
        ] = result

        return result

    ws = workbook[
        sheet_name
    ]

    header_row, headers = (
        read_first_nonempty_row(
            ws
        )
    )

    workbook.close()

    result = {
        "status":
            (
                "PASS"
                if header_row is not None
                else "NO_HEADER_FOUND"
            ),

        "header_row":
            header_row,

        "headers":
            headers,
    }

    cache[
        cache_key
    ] = result

    return result


# ============================================================
# VALIDATE MASTER DDI AGAINST RAW FILES
# ============================================================

def validate_master_mapping(
    workbook,
    raw_index
):

    print("\n" + "=" * 78)
    print("VALIDATING MASTER DDI AGAINST RAW XLSX FILES")
    print("=" * 78)

    ws = workbook[
        MASTER_SHEET
    ]

    rows = ws.iter_rows(
        values_only=True
    )

    headers = [
        clean(value)
        for value in next(rows)
    ]

    index = {
        header:
            position
        for position, header
        in enumerate(headers)
    }

    cache = {}

    validation_rows = []

    total_ddi_rows = 0
    exact_matches = 0

    missing_files = 0
    missing_sheets = 0
    invalid_positions = 0
    position_mismatches = 0
    blank_required_values = 0

    validation_status_counter = Counter()
    mapping_status_counter = Counter()

    source_files_seen = set()

    for ddi_row in rows:

        total_ddi_rows += 1

        row_id = clean(
            ddi_row[
                index["Row_ID"]
            ]
        )

        visit = clean(
            ddi_row[
                index["Visit"]
            ]
        )

        level = clean(
            ddi_row[
                index["Level"]
            ]
        )

        source_file = clean(
            ddi_row[
                index["Source_File"]
            ]
        )

        source_sheet = clean(
            ddi_row[
                index["Source_Sheet"]
            ]
        )

        expected_column = clean(
            ddi_row[
                index["Original_Column_Name"]
            ]
        )

        expected_position = (
            normalize_position(
                ddi_row[
                    index[
                        "Column_Position"
                    ]
                ]
            )
        )

        validation_status = clean(
            ddi_row[
                index[
                    "Validation_Status"
                ]
            ]
        )

        mapping_status = clean(
            ddi_row[
                index[
                    "Mapping_Status"
                ]
            ]
        )

        validation_status_counter[
            validation_status
        ] += 1

        mapping_status_counter[
            mapping_status
        ] += 1

        source_files_seen.add(
            source_file
        )

        status = "PASS"
        observed_column = ""
        raw_header_row = ""

        if (
            not source_file
            or
            not source_sheet
            or
            not expected_column
            or
            expected_position is None
        ):

            status = (
                "BLANK_REQUIRED_DDI_VALUE"
            )

            blank_required_values += 1

        elif source_file not in raw_index:

            status = (
                "SOURCE_FILE_NOT_FOUND"
            )

            missing_files += 1

        else:

            file_path = raw_index[
                source_file
            ]

            raw_info = get_raw_header(
                file_path=file_path,
                sheet_name=source_sheet,
                cache=cache
            )

            if (
                raw_info[
                    "status"
                ]
                ==
                "SHEET_NOT_FOUND"
            ):

                status = (
                    "SOURCE_SHEET_NOT_FOUND"
                )

                missing_sheets += 1

            elif (
                raw_info[
                    "status"
                ]
                !=
                "PASS"
            ):

                status = (
                    "RAW_HEADER_NOT_FOUND"
                )

                missing_sheets += 1

            else:

                raw_header_row = (
                    raw_info[
                        "header_row"
                    ]
                )

                headers_raw = (
                    raw_info[
                        "headers"
                    ]
                )

                if (
                    expected_position
                    <
                    1
                    or
                    expected_position
                    >
                    len(headers_raw)
                ):

                    status = (
                        "COLUMN_POSITION_OUT_OF_RANGE"
                    )

                    invalid_positions += 1

                else:

                    observed_column = clean(
                        headers_raw[
                            expected_position
                            -
                            1
                        ]
                    )

                    if (
                        observed_column
                        !=
                        expected_column
                    ):

                        status = (
                            "COLUMN_MISMATCH"
                        )

                        position_mismatches += 1

                    else:

                        exact_matches += 1

        validation_rows.append(
            {
                "Row_ID":
                    row_id,

                "Visit":
                    visit,

                "Level":
                    level,

                "Source_File":
                    source_file,

                "Source_Sheet":
                    source_sheet,

                "Raw_Header_Row":
                    raw_header_row,

                "Expected_Position":
                    (
                        expected_position
                        if
                        expected_position
                        is not None
                        else ""
                    ),

                "Expected_Column":
                    expected_column,

                "Observed_Column":
                    observed_column,

                "DDI_Validation_Status":
                    validation_status,

                "DDI_Mapping_Status":
                    mapping_status,

                "Raw_Mapping_Result":
                    status,
            }
        )

    return {
        "rows":
            validation_rows,

        "total_ddi_rows":
            total_ddi_rows,

        "exact_matches":
            exact_matches,

        "missing_files":
            missing_files,

        "missing_sheets":
            missing_sheets,

        "invalid_positions":
            invalid_positions,

        "position_mismatches":
            position_mismatches,

        "blank_required_values":
            blank_required_values,

        "validation_status_counter":
            validation_status_counter,

        "mapping_status_counter":
            mapping_status_counter,

        "source_files_seen":
            source_files_seen,
    }


# ============================================================
# VALIDATE CRITICAL HOUSEHOLD-BASE VARIABLES
# ============================================================

def validate_critical_variables(
    workbook
):

    print("\n" + "=" * 78)
    print("HOUSEHOLD-BASE VARIABLE CHECK")
    print("=" * 78)

    ws = workbook[
        MASTER_SHEET
    ]

    rows = ws.iter_rows(
        values_only=True
    )

    headers = [
        clean(value)
        for value in next(rows)
    ]

    index = {
        header:
            position
        for position, header
        in enumerate(headers)
    }

    level1_found = set()
    level3_found = set()

    for row in rows:

        visit = clean(
            row[
                index["Visit"]
            ]
        )

        level = clean(
            row[
                index["Level"]
            ]
        )

        column_name = clean(
            row[
                index[
                    "Original_Column_Name"
                ]
            ]
        )

        if (
            visit == "Visit 1"
            and
            level == "Level 1"
        ):

            if (
                column_name
                in
                CRITICAL_LEVEL1_VARIABLES
            ):

                level1_found.add(
                    column_name
                )

        if (
            visit == "Visit 1"
            and
            level == "Level 3"
        ):

            if (
                column_name
                in
                CRITICAL_LEVEL3_VARIABLES
            ):

                level3_found.add(
                    column_name
                )

    missing_level1 = sorted(
        CRITICAL_LEVEL1_VARIABLES
        -
        level1_found
    )

    missing_level3 = sorted(
        CRITICAL_LEVEL3_VARIABLES
        -
        level3_found
    )

    print(
        "\nVisit 1 Level 01 required:"
    )

    for variable in sorted(
        CRITICAL_LEVEL1_VARIABLES
    ):

        status = (
            "PASS"
            if variable in level1_found
            else "MISSING"
        )

        print(
            f"  {variable:<20} {status}"
        )

    print(
        "\nVisit 1 Level 03 required:"
    )

    for variable in sorted(
        CRITICAL_LEVEL3_VARIABLES
    ):

        status = (
            "PASS"
            if variable in level3_found
            else "MISSING"
        )

        print(
            f"  {variable:<20} {status}"
        )

    return (
        missing_level1,
        missing_level3
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS NSS 77 - STRICT DDI TO RAW VALIDATION")
    print("=" * 78)

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Paths
    # --------------------------------------------------------

    if not RAW_DIR.exists():
        raise FileNotFoundError(
            f"Raw directory missing:\n"
            f"{RAW_DIR}"
        )

    if not DDI_FILE.exists():
        raise FileNotFoundError(
            f"DDI workbook missing:\n"
            f"{DDI_FILE}"
        )

    # --------------------------------------------------------
    # Raw file index
    # --------------------------------------------------------

    raw_index = (
        build_raw_file_index()
    )

    print(
        f"\nRaw XLSX files indexed: "
        f"{len(raw_index)}"
    )

    # --------------------------------------------------------
    # DDI workbook
    # --------------------------------------------------------

    workbook = load_workbook(
        DDI_FILE,
        read_only=True,
        data_only=False
    )

    validate_ddi_headers(
        workbook
    )

    # --------------------------------------------------------
    # DDI -> raw validation
    # --------------------------------------------------------

    result = validate_master_mapping(
        workbook=workbook,
        raw_index=raw_index
    )

    # --------------------------------------------------------
    # Critical base fields
    # --------------------------------------------------------

    (
        missing_level1,
        missing_level3
    ) = validate_critical_variables(
        workbook
    )

    workbook.close()

    # --------------------------------------------------------
    # Write detail report
    # --------------------------------------------------------

    write_csv(
        DETAIL_REPORT,
        result["rows"],
        [
            "Row_ID",
            "Visit",
            "Level",
            "Source_File",
            "Source_Sheet",
            "Raw_Header_Row",
            "Expected_Position",
            "Expected_Column",
            "Observed_Column",
            "DDI_Validation_Status",
            "DDI_Mapping_Status",
            "Raw_Mapping_Result",
        ]
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    missing_raw_from_ddi = sorted(
        result[
            "source_files_seen"
        ]
        -
        set(
            raw_index.keys()
        )
    )

    extra_raw_not_in_ddi = sorted(
        set(
            raw_index.keys()
        )
        -
        result[
            "source_files_seen"
        ]
    )

    raw_mapping_pass = all(
        [
            result[
                "missing_files"
            ] == 0,

            result[
                "missing_sheets"
            ] == 0,

            result[
                "invalid_positions"
            ] == 0,

            result[
                "position_mismatches"
            ] == 0,

            result[
                "blank_required_values"
            ] == 0,

            len(
                missing_level1
            ) == 0,

            len(
                missing_level3
            ) == 0,
        ]
    )

    print("\n" + "=" * 78)
    print("STRICT VALIDATION SUMMARY")
    print("=" * 78)

    print(
        f"\nMaster DDI rows checked   : "
        f"{result['total_ddi_rows']:,}"
    )

    print(
        f"Exact raw column matches  : "
        f"{result['exact_matches']:,}"
    )

    print(
        f"Missing raw files         : "
        f"{result['missing_files']}"
    )

    print(
        f"Missing raw sheets        : "
        f"{result['missing_sheets']}"
    )

    print(
        f"Invalid column positions  : "
        f"{result['invalid_positions']}"
    )

    print(
        f"Column mismatches         : "
        f"{result['position_mismatches']}"
    )

    print(
        f"Blank required DDI values : "
        f"{result['blank_required_values']}"
    )

    print(
        f"\nDDI source files          : "
        f"{len(result['source_files_seen'])}"
    )

    print(
        f"Raw files not in DDI      : "
        f"{len(extra_raw_not_in_ddi)}"
    )

    print(
        "\nDDI Mapping_Status counts:"
    )

    for status, count in sorted(
        result[
            "mapping_status_counter"
        ].items()
    ):

        print(
            f"  {status:<20} "
            f"{count}"
        )

    print(
        "\nDDI Validation_Status counts:"
    )

    for status, count in sorted(
        result[
            "validation_status_counter"
        ].items()
    ):

        print(
            f"  {status:<65} "
            f"{count}"
        )

    if missing_raw_from_ddi:

        print(
            "\nMissing DDI source files:"
        )

        for name in missing_raw_from_ddi:
            print(
                f"  - {name}"
            )

    if extra_raw_not_in_ddi:

        print(
            "\nRaw files not referenced by DDI:"
        )

        for name in extra_raw_not_in_ddi:
            print(
                f"  - {name}"
            )

    print(
        "\nSTRICT DDI -> RAW STATUS: "
        +
        (
            "PASS"
            if raw_mapping_pass
            else "FAIL"
        )
    )

    # --------------------------------------------------------
    # Write summary file
    # --------------------------------------------------------

    summary_lines = [
        "=" * 78,
        "AIDIS NSS 77 - STRICT DDI TO RAW VALIDATION",
        "=" * 78,
        "",
        (
            "Master DDI rows checked   : "
            f"{result['total_ddi_rows']:,}"
        ),
        (
            "Exact raw column matches  : "
            f"{result['exact_matches']:,}"
        ),
        (
            "Missing raw files         : "
            f"{result['missing_files']}"
        ),
        (
            "Missing raw sheets        : "
            f"{result['missing_sheets']}"
        ),
        (
            "Invalid column positions  : "
            f"{result['invalid_positions']}"
        ),
        (
            "Column mismatches         : "
            f"{result['position_mismatches']}"
        ),
        (
            "Blank required DDI values : "
            f"{result['blank_required_values']}"
        ),
        "",
        (
            "Missing Level-01 fields   : "
            +
            (
                ", ".join(
                    missing_level1
                )
                or "None"
            )
        ),
        (
            "Missing Level-03 fields   : "
            +
            (
                ", ".join(
                    missing_level3
                )
                or "None"
            )
        ),
        "",
        (
            "STRICT DDI -> RAW STATUS  : "
            +
            (
                "PASS"
                if raw_mapping_pass
                else "FAIL"
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

    print(
        f"\nDetail report:\n"
        f"{DETAIL_REPORT}"
    )

    print(
        f"\nSummary report:\n"
        f"{SUMMARY_REPORT}"
    )

    if not raw_mapping_pass:

        sys.exit(1)


if __name__ == "__main__":
    main()