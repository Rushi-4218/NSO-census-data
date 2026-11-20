from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

import pandas as pd


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AIDIS_ROOT = PROJECT_ROOT.parent

NATIONAL_FILE = (
    AIDIS_ROOT
    / "AIDIS_Final_Client.csv"
)

STATE_MASTER_FILE = (
    PROJECT_ROOT
    / "config"
    / "state_master.csv"
)

DISTRICT_MASTER_FILE = (
    PROJECT_ROOT
    / "config"
    / "district_master.csv"
)

FINAL_STATES_DIR = (
    PROJECT_ROOT
    / "output"
    / "final_states"
)

MANIFEST_FILE = (
    PROJECT_ROOT
    / "output"
    / "reports"
    / "final_state_export_manifest.csv"
)

VALIDATION_REPORT_FILE = (
    PROJECT_ROOT
    / "output"
    / "reports"
    / "final_delivery_validation.csv"
)

VALIDATION_SUMMARY_FILE = (
    PROJECT_ROOT
    / "output"
    / "reports"
    / "final_delivery_validation_summary.txt"
)


# ============================================================
# EXPECTED VALUES
# ============================================================

EXPECTED_STATE_COUNT = 36
EXPECTED_DISTRICT_COUNT = 682
EXPECTED_TOTAL_STATE_ROWS = 534_502
EXPECTED_NATIONAL_ROWS = 535_537
EXPECTED_ALL_INDIA_ROWS = (
    EXPECTED_NATIONAL_ROWS
    -
    EXPECTED_TOTAL_STATE_ROWS
)


FINAL_COLUMNS = [
    "Survey_ID",
    "Survey_NAME",
    "Survey_GROUP_ID",
    "GROUP_NAME",
    "SUB_GROUP_ID",
    "SUB_GROUP_NAME",
    "Year",
    "FREQ_DESC",
    "State_ID",
    "State_Name",
    "District_ID",
    "District_Name",
    "Sector_code",
    "Sector",
    "Published_date",
    "Extracted_Date",
    "Visit_ID",
    "Col_ID",
    "COL_DESC",
    "DATA",
    "Unit",
    "Source",
]


# ============================================================
# HELPERS
# ============================================================

def normalize_code(value, width):
    """
    Convert an ID into a fixed-width internal key.

    Examples:
        State_ID 1    -> 01
        State_ID 27   -> 27

        District_ID 0    -> 0000
        District_ID 101  -> 0101
        District_ID 2701 -> 2701
    """

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if not value:
        return ""

    if value.endswith(".0"):
        value = value[:-2]

    return value.zfill(width)


def integer_text(value):
    """
    Convert numeric-looking IDs to normal integer text.

    Examples:
        01   -> 1
        07   -> 7
        0000 -> 0
        2701 -> 2701
    """

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if not value:
        return ""

    if re.fullmatch(
        r"[+-]?\d+(?:\.0+)?",
        value
    ):
        return str(
            int(
                Decimal(value)
            )
        )

    return value


def format_delivery_date(value):
    """
    Convert dates to DD-Mon-YY.

    Example:
        10-Sep-2021 -> 10-Sep-21
        07-Aug-2026 -> 07-Aug-26
    """

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if not value:
        return ""

    match = re.fullmatch(
        r"(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})",
        value
    )

    if match:

        day = int(
            match.group(1)
        )

        month = (
            match.group(2)
            .title()
        )

        year = match.group(3)

        if len(year) == 4:
            year = year[-2:]

        return (
            f"{day:02d}-"
            f"{month}-"
            f"{year}"
        )

    iso_match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})",
        value
    )

    if iso_match:

        months = {
            "01": "Jan",
            "02": "Feb",
            "03": "Mar",
            "04": "Apr",
            "05": "May",
            "06": "Jun",
            "07": "Jul",
            "08": "Aug",
            "09": "Sep",
            "10": "Oct",
            "11": "Nov",
            "12": "Dec",
        }

        year = iso_match.group(1)
        month = iso_match.group(2)
        day = iso_match.group(3)

        if month not in months:
            raise ValueError(
                f"Invalid date: {value}"
            )

        return (
            f"{day}-"
            f"{months[month]}-"
            f"{year[-2:]}"
        )

    raise ValueError(
        f"Unsupported date format: {value}"
    )


def round_significant_digits(value, digits=10):
    """
    Reproduce the final DATA formatting:
    10 significant digits using ROUND_HALF_UP.
    """

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if not value:
        return ""

    try:
        number = Decimal(
            value
        )

    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid DATA value: {value}"
        ) from exc

    if not number.is_finite():
        raise ValueError(
            f"Non-finite DATA value: {value}"
        )

    if number == 0:
        return "0"

    with localcontext() as context:

        context.prec = 50

        exponent = (
            number.adjusted()
            -
            digits
            +
            1
        )

        quantum = Decimal(
            f"1e{exponent}"
        )

        rounded = number.quantize(
            quantum,
            rounding=ROUND_HALF_UP
        )

    result = format(
        rounded,
        "f"
    )

    if "." in result:

        result = (
            result
            .rstrip("0")
            .rstrip(".")
        )

    if result == "-0":
        result = "0"

    return result


# ============================================================
# LOAD STATE MASTER
# ============================================================

def load_state_master():

    if not STATE_MASTER_FILE.exists():

        raise FileNotFoundError(
            f"\nState master missing:\n"
            f"{STATE_MASTER_FILE}"
        )

    states = pd.read_csv(
        STATE_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    required = {
        "State_ID",
        "State_Name",
        "File_Name",
    }

    missing = (
        required
        -
        set(states.columns)
    )

    if missing:

        raise ValueError(
            f"State master missing columns: "
            f"{sorted(missing)}"
        )

    states[
        "State_ID"
    ] = states[
        "State_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    if len(states) != EXPECTED_STATE_COUNT:

        raise ValueError(
            f"Expected {EXPECTED_STATE_COUNT} "
            f"states but found {len(states)}."
        )

    if states[
        "State_ID"
    ].duplicated().any():

        raise ValueError(
            "Duplicate State_ID "
            "in state_master.csv."
        )

    return states


# ============================================================
# LOAD DISTRICT MASTER
# ============================================================

def load_district_master():

    if not DISTRICT_MASTER_FILE.exists():

        raise FileNotFoundError(
            f"\nDistrict master missing:\n"
            f"{DISTRICT_MASTER_FILE}"
        )

    districts = pd.read_csv(
        DISTRICT_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    required = {
        "State_ID",
        "District_Code",
        "District_ID",
        "District_Name",
        "Status",
    }

    missing = (
        required
        -
        set(districts.columns)
    )

    if missing:

        raise ValueError(
            f"District master missing columns: "
            f"{sorted(missing)}"
        )

    districts[
        "State_ID"
    ] = districts[
        "State_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    districts[
        "District_Code"
    ] = districts[
        "District_Code"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    districts[
        "District_ID"
    ] = districts[
        "District_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            4
        )
    )

    if len(districts) != EXPECTED_DISTRICT_COUNT:

        raise ValueError(
            f"Expected {EXPECTED_DISTRICT_COUNT} "
            f"districts but found "
            f"{len(districts)}."
        )

    if districts[
        "District_ID"
    ].duplicated().any():

        raise ValueError(
            "Duplicate District_ID "
            "in district master."
        )

    if (
        districts[
            "District_Name"
        ]
        .str.strip()
        .eq("")
        .any()
    ):

        raise ValueError(
            "Blank District_Name "
            "in district master."
        )

    if (
        districts[
            "Status"
        ]
        !=
        "VERIFIED_NSS77"
    ).any():

        raise ValueError(
            "District master contains "
            "non-verified districts."
        )

    composite = (
        districts[
            "State_ID"
        ]
        +
        districts[
            "District_Code"
        ]
    )

    if (
        composite
        !=
        districts[
            "District_ID"
        ]
    ).any():

        raise ValueError(
            "Invalid State_ID + District_Code "
            "composite detected."
        )

    return districts


# ============================================================
# LOAD NATIONAL SOURCE
# ============================================================

def load_national():

    if not NATIONAL_FILE.exists():

        raise FileNotFoundError(
            f"\nNational source missing:\n"
            f"{NATIONAL_FILE}"
        )

    national = pd.read_csv(
        NATIONAL_FILE,
        dtype=str,
        keep_default_na=False,
        low_memory=False
    )

    required = (
        set(FINAL_COLUMNS)
        |
        {
            "houseHold_ID"
        }
    )

    missing = (
        required
        -
        set(national.columns)
    )

    if missing:

        raise ValueError(
            "National file missing columns: "
            f"{sorted(missing)}"
        )

    national[
        "_State_Key"
    ] = national[
        "State_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    national[
        "_District_Key"
    ] = national[
        "District_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            4
        )
    )

    return national


# ============================================================
# BUILD EXPECTED STATE FROM NATIONAL SOURCE
# ============================================================

def build_expected_state(
    national,
    state_id,
    state_name,
    district_lookup
):

    state_rows = national[
        national[
            "_State_Key"
        ]
        ==
        state_id
    ].copy()

    if state_rows.empty:

        raise ValueError(
            f"No national rows for "
            f"State_ID {state_id}."
        )

    actual_district_rows = state_rows[
        state_rows[
            "_District_Key"
        ]
        !=
        "0000"
    ]

    unmapped = sorted(
        set(
            actual_district_rows[
                "_District_Key"
            ]
        )
        -
        set(
            district_lookup.keys()
        )
    )

    if unmapped:

        raise ValueError(
            f"Unmapped districts in "
            f"State_ID {state_id}: "
            f"{unmapped}"
        )

    state_rows[
        "State_Name"
    ] = state_name

    state_rows[
        "District_Name"
    ] = state_rows[
        "_District_Key"
    ].apply(
        lambda district_id:
        (
            "All Districts"
            if district_id == "0000"
            else district_lookup[
                district_id
            ]
        )
    )

    state_rows[
        "FREQ_DESC"
    ] = "Annual"

    state_rows[
        "Published_date"
    ] = state_rows[
        "Published_date"
    ].apply(
        format_delivery_date
    )

    state_rows[
        "Extracted_Date"
    ] = state_rows[
        "Extracted_Date"
    ].apply(
        format_delivery_date
    )

    state_rows[
        "DATA"
    ] = state_rows[
        "DATA"
    ].apply(
        round_significant_digits
    )

    state_rows[
        "Survey_GROUP_ID"
    ] = state_rows[
        "Survey_GROUP_ID"
    ].apply(
        integer_text
    )

    state_rows[
        "State_ID"
    ] = state_rows[
        "_State_Key"
    ].apply(
        integer_text
    )

    state_rows[
        "District_ID"
    ] = state_rows[
        "_District_Key"
    ].apply(
        integer_text
    )

    state_rows[
        "Sector_code"
    ] = state_rows[
        "Sector_code"
    ].apply(
        integer_text
    )

    state_rows[
        "Visit_ID"
    ] = state_rows[
        "Visit_ID"
    ].apply(
        integer_text
    )

    return state_rows[
        FINAL_COLUMNS
    ].reset_index(
        drop=True
    )


# ============================================================
# FIND FIRST CELL DIFFERENCE
# ============================================================

def get_first_difference(
    expected,
    actual
):

    if expected.shape != actual.shape:

        return (
            "Shape differs: "
            f"expected={expected.shape}, "
            f"actual={actual.shape}"
        )

    difference = (
        expected
        !=
        actual
    )

    if not difference.any().any():

        return ""

    stacked = difference.stack()

    first = stacked[
        stacked
    ].index[0]

    row_index = first[0]
    column_name = first[1]

    expected_value = expected.at[
        row_index,
        column_name
    ]

    actual_value = actual.at[
        row_index,
        column_name
    ]

    # +2 because:
    # CSV row 1 = header
    # dataframe index 0 = CSV row 2
    csv_row = row_index + 2

    return (
        f"Row {csv_row}, "
        f"Column {column_name}, "
        f"Expected='{expected_value}', "
        f"Actual='{actual_value}'"
    )


# ============================================================
# VALIDATE ONE STATE FILE
# ============================================================

def validate_state_file(
    state,
    national,
    district_lookup
):

    state_id_key = state[
        "State_ID"
    ]

    state_id_output = integer_text(
        state_id_key
    )

    state_name = state[
        "State_Name"
    ]

    file_name = state[
        "File_Name"
    ]

    file_path = (
        FINAL_STATES_DIR
        /
        file_name
    )

    result = {
        "State_ID":
            state_id_output,

        "State_Name":
            state_name,

        "File_Name":
            file_name,

        "Rows":
            0,

        "Expected_Rows":
            0,

        "Districts_Used":
            0,

        "Blank_DATA":
            0,

        "Blank_District_Name":
            0,

        "District_Placeholders":
            0,

        "Wrong_State_ID":
            0,

        "Wrong_State_Name":
            0,

        "Wrong_Frequency":
            0,

        "Bad_District_Mapping":
            0,

        "Bad_Published_Date":
            0,

        "Bad_Extracted_Date":
            0,

        "Exact_Duplicates":
            0,

        "Expected_Duplicates":
            0,

        "Different_Cells":
            0,

        "First_Difference":
            "",

        "Status":
            "FAIL",

        "Failure_Reason":
            "",
    }

    try:

        if not file_path.exists():

            result[
                "Failure_Reason"
            ] = "FILE_NOT_FOUND"

            return result

        actual = pd.read_csv(
            file_path,
            dtype=str,
            keep_default_na=False,
            low_memory=False
        )

        result[
            "Rows"
        ] = len(
            actual
        )

        if list(
            actual.columns
        ) != FINAL_COLUMNS:

            result[
                "Failure_Reason"
            ] = (
                "INVALID_COLUMN_STRUCTURE"
            )

            return result

        if (
            "houseHold_ID"
            in
            actual.columns
        ):

            result[
                "Failure_Reason"
            ] = (
                "houseHold_ID_PRESENT"
            )

            return result

        expected = (
            build_expected_state(
                national=national,
                state_id=state_id_key,
                state_name=state_name,
                district_lookup=district_lookup
            )
        )

        result[
            "Expected_Rows"
        ] = len(
            expected
        )

        # ----------------------------------------------------
        # Basic field checks
        # ----------------------------------------------------

        result[
            "Blank_DATA"
        ] = int(
            actual[
                "DATA"
            ]
            .str.strip()
            .eq("")
            .sum()
        )

        result[
            "Blank_District_Name"
        ] = int(
            actual[
                "District_Name"
            ]
            .str.strip()
            .eq("")
            .sum()
        )

        result[
            "District_Placeholders"
        ] = int(
            actual[
                "District_Name"
            ]
            .str.match(
                r"^District code \d+$",
                case=False,
                na=False
            )
            .sum()
        )

        result[
            "Wrong_State_ID"
        ] = int(
            (
                actual[
                    "State_ID"
                ]
                !=
                state_id_output
            ).sum()
        )

        result[
            "Wrong_State_Name"
        ] = int(
            (
                actual[
                    "State_Name"
                ]
                !=
                state_name
            ).sum()
        )

        result[
            "Wrong_Frequency"
        ] = int(
            (
                actual[
                    "FREQ_DESC"
                ]
                !=
                "Annual"
            ).sum()
        )

        # ----------------------------------------------------
        # District validation
        # ----------------------------------------------------

        actual_district_keys = (
            actual[
                "District_ID"
            ]
            .apply(
                lambda value:
                normalize_code(
                    value,
                    4
                )
            )
        )

        expected_names = (
            actual_district_keys
            .apply(
                lambda district_id:
                (
                    "All Districts"
                    if district_id == "0000"
                    else district_lookup.get(
                        district_id,
                        "__UNMAPPED__"
                    )
                )
            )
        )

        result[
            "Bad_District_Mapping"
        ] = int(
            (
                actual[
                    "District_Name"
                ]
                !=
                expected_names
            ).sum()
        )

        result[
            "Districts_Used"
        ] = int(
            actual.loc[
                actual[
                    "District_ID"
                ]
                !=
                "0",
                "District_ID"
            ]
            .nunique()
        )

        # ----------------------------------------------------
        # Date formatting
        # ----------------------------------------------------

        date_pattern = (
            r"^\d{2}-"
            r"[A-Z][a-z]{2}-"
            r"\d{2}$"
        )

        result[
            "Bad_Published_Date"
        ] = int(
            (
                ~actual[
                    "Published_date"
                ]
                .str.match(
                    date_pattern,
                    na=False
                )
            ).sum()
        )

        result[
            "Bad_Extracted_Date"
        ] = int(
            (
                ~actual[
                    "Extracted_Date"
                ]
                .str.match(
                    date_pattern,
                    na=False
                )
            ).sum()
        )

        # ----------------------------------------------------
        # Duplicate validation
        #
        # We compare against the expected data rather than
        # blindly assuming zero duplicates.
        # ----------------------------------------------------

        result[
            "Exact_Duplicates"
        ] = int(
            actual
            .duplicated()
            .sum()
        )

        result[
            "Expected_Duplicates"
        ] = int(
            expected
            .duplicated()
            .sum()
        )

        # ----------------------------------------------------
        # Exact 22-column cell-by-cell validation
        # ----------------------------------------------------

        if (
            actual.shape
            ==
            expected.shape
        ):

            difference = (
                actual
                !=
                expected
            )

            result[
                "Different_Cells"
            ] = int(
                difference
                .sum()
                .sum()
            )

        else:

            result[
                "Different_Cells"
            ] = -1

        result[
            "First_Difference"
        ] = get_first_difference(
            expected,
            actual
        )

        # ----------------------------------------------------
        # Final state-level gate
        # ----------------------------------------------------

        failures = []

        if (
            len(actual)
            !=
            len(expected)
        ):
            failures.append(
                "ROW_COUNT"
            )

        if result[
            "Blank_DATA"
        ]:
            failures.append(
                "BLANK_DATA"
            )

        if result[
            "Blank_District_Name"
        ]:
            failures.append(
                "BLANK_DISTRICT_NAME"
            )

        if result[
            "District_Placeholders"
        ]:
            failures.append(
                "DISTRICT_PLACEHOLDER"
            )

        if result[
            "Wrong_State_ID"
        ]:
            failures.append(
                "WRONG_STATE_ID"
            )

        if result[
            "Wrong_State_Name"
        ]:
            failures.append(
                "WRONG_STATE_NAME"
            )

        if result[
            "Wrong_Frequency"
        ]:
            failures.append(
                "WRONG_FREQUENCY"
            )

        if result[
            "Bad_District_Mapping"
        ]:
            failures.append(
                "BAD_DISTRICT_MAPPING"
            )

        if result[
            "Bad_Published_Date"
        ]:
            failures.append(
                "BAD_PUBLISHED_DATE"
            )

        if result[
            "Bad_Extracted_Date"
        ]:
            failures.append(
                "BAD_EXTRACTED_DATE"
            )

        if (
            result[
                "Exact_Duplicates"
            ]
            !=
            result[
                "Expected_Duplicates"
            ]
        ):
            failures.append(
                "DUPLICATE_COUNT_CHANGED"
            )

        if result[
            "Different_Cells"
        ] != 0:
            failures.append(
                "CELL_DIFFERENCE"
            )

        if failures:

            result[
                "Status"
            ] = "FAIL"

            result[
                "Failure_Reason"
            ] = ",".join(
                failures
            )

        else:

            result[
                "Status"
            ] = "PASS"

            result[
                "Failure_Reason"
            ] = ""

        return result

    except Exception as exc:

        result[
            "Status"
        ] = "FAIL"

        result[
            "Failure_Reason"
        ] = (
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return result


# ============================================================
# VALIDATE OUTPUT FILE SET
# ============================================================

def validate_file_set(states):

    expected_files = set(
        states[
            "File_Name"
        ]
    )

    actual_files = set(
        file.name
        for file in FINAL_STATES_DIR.glob(
            "AIDIS_*.csv"
        )
    )

    missing = sorted(
        expected_files
        -
        actual_files
    )

    extra = sorted(
        actual_files
        -
        expected_files
    )

    return (
        missing,
        extra
    )


# ============================================================
# VALIDATE MANIFEST
# ============================================================

def validate_manifest(
    report
):

    if not MANIFEST_FILE.exists():

        return (
            False,
            "Manifest file is missing."
        )

    manifest = pd.read_csv(
        MANIFEST_FILE,
        dtype=str,
        keep_default_na=False
    )

    if len(manifest) != EXPECTED_STATE_COUNT:

        return (
            False,
            (
                "Manifest state count is "
                f"{len(manifest)}, expected "
                f"{EXPECTED_STATE_COUNT}."
            )
        )

    expected_manifest = report[
        [
            "State_ID",
            "State_Name",
            "File_Name",
            "Rows",
        ]
    ].copy()

    expected_manifest[
        "Rows"
    ] = expected_manifest[
        "Rows"
    ].astype(str)

    manifest_check = manifest[
        [
            "State_ID",
            "State_Name",
            "File_Name",
            "Rows",
        ]
    ].copy()

    for column in [
        "State_ID",
        "Rows",
    ]:

        manifest_check[
            column
        ] = manifest_check[
            column
        ].astype(str)

    if not expected_manifest.equals(
        manifest_check
    ):

        return (
            False,
            "Manifest does not match final files."
        )

    return (
        True,
        "PASS"
    )


# ============================================================
# WRITE SUMMARY
# ============================================================

def write_summary(
    report,
    national_rows,
    all_india_rows,
    state_rows,
    missing_files,
    extra_files,
    manifest_ok,
    manifest_message
):

    passed_states = int(
        (
            report[
                "Status"
            ]
            ==
            "PASS"
        ).sum()
    )

    failed_states = int(
        (
            report[
                "Status"
            ]
            !=
            "PASS"
        ).sum()
    )

    total_rows = int(
        report[
            "Rows"
        ].sum()
    )

    total_different_cells = int(
        report.loc[
            report[
                "Different_Cells"
            ]
            >=
            0,
            "Different_Cells"
        ].sum()
    )

    lines = [
        "=" * 78,
        "AIDIS FINAL DELIVERY VALIDATION SUMMARY",
        "=" * 78,
        "",
        f"National source rows       : {national_rows:,}",
        f"All India rows              : {all_india_rows:,}",
        f"Expected All India rows     : {EXPECTED_ALL_INDIA_ROWS:,}",
        f"State / UT source rows      : {state_rows:,}",
        f"Exported state rows         : {total_rows:,}",
        f"Expected state rows         : {EXPECTED_TOTAL_STATE_ROWS:,}",
        "",
        f"Expected State/UT files     : {EXPECTED_STATE_COUNT}",
        f"Validated State/UT files    : {len(report)}",
        f"Passed states               : {passed_states}",
        f"Failed states               : {failed_states}",
        "",
        f"Missing output files        : {len(missing_files)}",
        f"Extra output files          : {len(extra_files)}",
        "",
        f"Total different cells       : {total_different_cells:,}",
        "",
        f"Manifest validation         : {'PASS' if manifest_ok else 'FAIL'}",
        f"Manifest detail             : {manifest_message}",
        "",
    ]

    if missing_files:

        lines.append(
            "Missing files:"
        )

        lines.extend(
            f"  - {name}"
            for name in missing_files
        )

        lines.append("")

    if extra_files:

        lines.append(
            "Extra files:"
        )

        lines.extend(
            f"  - {name}"
            for name in extra_files
        )

        lines.append("")

    failed = report[
        report[
            "Status"
        ]
        !=
        "PASS"
    ]

    if not failed.empty:

        lines.append(
            "FAILED STATES:"
        )

        for _, row in failed.iterrows():

            lines.append(
                f"  {row['State_ID']} "
                f"{row['State_Name']} -> "
                f"{row['Failure_Reason']}"
            )

            if row[
                "First_Difference"
            ]:

                lines.append(
                    "      "
                    +
                    row[
                        "First_Difference"
                    ]
                )

        lines.append("")

    final_pass = (
        passed_states
        ==
        EXPECTED_STATE_COUNT
        and
        failed_states
        ==
        0
        and
        total_rows
        ==
        EXPECTED_TOTAL_STATE_ROWS
        and
        state_rows
        ==
        EXPECTED_TOTAL_STATE_ROWS
        and
        all_india_rows
        ==
        EXPECTED_ALL_INDIA_ROWS
        and
        not missing_files
        and
        not extra_files
        and
        total_different_cells
        ==
        0
        and
        manifest_ok
    )

    if final_pass:

        lines.append(
            "FINAL DELIVERY VALIDATION: PASS"
        )

    else:

        lines.append(
            "FINAL DELIVERY VALIDATION: FAIL"
        )

    lines.append(
        "=" * 78
    )

    VALIDATION_SUMMARY_FILE.write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8"
    )

    return (
        final_pass,
        "\n".join(
            lines
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS FINAL 36-STATE DELIVERY VALIDATOR")
    print("=" * 78)

    # --------------------------------------------------------
    # Load configuration
    # --------------------------------------------------------

    states = load_state_master()

    districts = load_district_master()

    district_lookup = dict(
        zip(
            districts[
                "District_ID"
            ],
            districts[
                "District_Name"
            ]
        )
    )

    national = load_national()

    # --------------------------------------------------------
    # National source counts
    # --------------------------------------------------------

    national_rows = len(
        national
    )

    all_india_rows = int(
        (
            national[
                "_State_Key"
            ]
            ==
            "00"
        ).sum()
    )

    state_rows = int(
        (
            national[
                "_State_Key"
            ]
            !=
            "00"
        ).sum()
    )

    print("\n" + "=" * 78)
    print("NATIONAL SOURCE CHECK")
    print("=" * 78)

    print(
        f"\nNational rows   : "
        f"{national_rows:,}"
    )

    print(
        f"All India rows  : "
        f"{all_india_rows:,}"
    )

    print(
        f"State / UT rows : "
        f"{state_rows:,}"
    )

    # --------------------------------------------------------
    # Output directory
    # --------------------------------------------------------

    if not FINAL_STATES_DIR.exists():

        raise FileNotFoundError(
            f"\nFinal state folder missing:\n"
            f"{FINAL_STATES_DIR}"
        )

    # --------------------------------------------------------
    # Check expected filenames
    # --------------------------------------------------------

    (
        missing_files,
        extra_files
    ) = validate_file_set(
        states
    )

    print("\n" + "=" * 78)
    print("OUTPUT FILE SET CHECK")
    print("=" * 78)

    print(
        f"\nMissing files: "
        f"{len(missing_files)}"
    )

    print(
        f"Extra files  : "
        f"{len(extra_files)}"
    )

    # --------------------------------------------------------
    # Validate every state
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("VALIDATING ALL 36 STATE / UT FILES")
    print("=" * 78)

    results = []

    for _, state in states.iterrows():

        result = validate_state_file(
            state=state,
            national=national,
            district_lookup=district_lookup
        )

        results.append(
            result
        )

        print(
            f"{str(result['State_ID']).zfill(2)}  "
            f"{result['State_Name']:<32} "
            f"{result['Rows']:>8,} rows  "
            f"{result['Status']}"
        )

        if (
            result[
                "Status"
            ]
            !=
            "PASS"
        ):

            print(
                "    "
                +
                result[
                    "Failure_Reason"
                ]
            )

            if result[
                "First_Difference"
            ]:

                print(
                    "    "
                    +
                    result[
                        "First_Difference"
                    ]
                )

    report = pd.DataFrame(
        results
    )

    # --------------------------------------------------------
    # Save detailed report
    # --------------------------------------------------------

    VALIDATION_REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    report.to_csv(
        VALIDATION_REPORT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # Validate manifest
    # --------------------------------------------------------

    (
        manifest_ok,
        manifest_message
    ) = validate_manifest(
        report
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    (
        final_pass,
        summary_text
    ) = write_summary(
        report=report,
        national_rows=national_rows,
        all_india_rows=all_india_rows,
        state_rows=state_rows,
        missing_files=missing_files,
        extra_files=extra_files,
        manifest_ok=manifest_ok,
        manifest_message=manifest_message
    )

    print("\n")
    print(
        summary_text
    )

    print(
        "\nDetailed validation report:"
    )

    print(
        VALIDATION_REPORT_FILE
    )

    print(
        "\nValidation summary:"
    )

    print(
        VALIDATION_SUMMARY_FILE
    )

    if not final_pass:

        raise ValueError(
            "\nFINAL DELIVERY VALIDATION FAILED."
            "\nReview the validation reports above."
        )


if __name__ == "__main__":
    main()