from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

import pandas as pd


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# D:\AIDIS
AIDIS_ROOT = PROJECT_ROOT.parent

# Friend / national calculated delivery.
# IMPORTANT:
# We are NOT recalculating any AIDIS KPIs here.
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

OUTPUT_DIR = (
    PROJECT_ROOT
    / "output"
    / "final_states"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

MANIFEST_FILE = (
    REPORT_DIR
    / "final_state_export_manifest.csv"
)


# ============================================================
# OPTIONAL MAHARASHTRA REFERENCE
# ============================================================

# If one of these files exists, the script will compare
# our newly generated Maharashtra output against it.
MAHARASHTRA_REFERENCE_CANDIDATES = [
    AIDIS_ROOT / "AIDIS_Maharashtra.csv",
    PROJECT_ROOT / "input" / "reference" / "AIDIS_Maharashtra.csv",
]


# ============================================================
# EXPECTED DELIVERY STRUCTURE
# ============================================================

EXPECTED_STATE_COUNT = 36
EXPECTED_DISTRICT_COUNT = 682
EXPECTED_TOTAL_STATE_ROWS = 534_502


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
    Convert an ID to a fixed-width internal string.

    Examples:
        State 1     -> 01
        State 27    -> 27

        District 0  -> 0000
        101         -> 0101
        2701        -> 2701
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
    Convert numeric-looking values to delivery-style integers.

    Examples:
        01   -> 1
        07   -> 7
        101  -> 101
        1.0  -> 1

    Non-numeric text is preserved.
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
    Convert dates to the Maharashtra delivery format.

    Examples:
        10-Sep-2021 -> 10-Sep-21
        07-Aug-2026 -> 07-Aug-26

    Already-short dates remain short.
    """

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if not value:
        return ""

    # DD-Mon-YYYY or DD-Mon-YY
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

    # ISO date fallback:
    # YYYY-MM-DD
    iso_match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})",
        value
    )

    if iso_match:

        month_names = {
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

        if month not in month_names:
            raise ValueError(
                f"Invalid month in date: {value}"
            )

        return (
            f"{day}-"
            f"{month_names[month]}-"
            f"{year[-2:]}"
        )

    raise ValueError(
        f"Unsupported date format: {value}"
    )


def round_significant_digits(value, digits=10):
    """
    Round DATA to 10 significant digits using ROUND_HALF_UP.

    This reproduces the Maharashtra delivery style.

    Examples:
        146712.930658
            -> 146712.9307

        3021967.637544
            -> 3021967.638

        10181.0
            -> 10181
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

        # Plenty of precision for the values in AIDIS.
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

    # Delivery output does not retain unnecessary zeros.
    if "." in result:
        result = (
            result
            .rstrip("0")
            .rstrip(".")
        )

    if result in {
        "-0",
        "-0.0"
    }:
        result = "0"

    return result


# ============================================================
# LOAD + VALIDATE CONFIGURATION
# ============================================================

def load_state_master():

    print("\n" + "=" * 78)
    print("VALIDATING STATE MASTER")
    print("=" * 78)

    if not STATE_MASTER_FILE.exists():
        raise FileNotFoundError(
            f"\nState master not found:\n"
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
            f"\nState master missing columns: "
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
            f"\nExpected {EXPECTED_STATE_COUNT} "
            f"states/UTs, found {len(states)}."
        )

    if states[
        "State_ID"
    ].duplicated().any():
        raise ValueError(
            "\nDuplicate State_ID found "
            "in state_master.csv."
        )

    if states[
        "File_Name"
    ].duplicated().any():
        raise ValueError(
            "\nDuplicate File_Name found "
            "in state_master.csv."
        )

    print(
        f"\nStates/UTs: {len(states)}"
    )

    print(
        "STATE MASTER: PASS"
    )

    return states


def load_district_master():

    print("\n" + "=" * 78)
    print("VALIDATING VERIFIED DISTRICT MASTER")
    print("=" * 78)

    if not DISTRICT_MASTER_FILE.exists():
        raise FileNotFoundError(
            f"\nDistrict master not found:\n"
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
            f"\nDistrict master missing columns: "
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
            f"\nExpected {EXPECTED_DISTRICT_COUNT} "
            f"districts, found {len(districts)}."
        )

    duplicate_count = int(
        districts[
            "District_ID"
        ].duplicated().sum()
    )

    blank_names = int(
        districts[
            "District_Name"
        ]
        .str.strip()
        .eq("")
        .sum()
    )

    non_verified = int(
        (
            districts[
                "Status"
            ]
            !=
            "VERIFIED_NSS77"
        ).sum()
    )

    bad_composite = int(
        (
            districts[
                "District_ID"
            ]
            !=
            (
                districts[
                    "State_ID"
                ]
                +
                districts[
                    "District_Code"
                ]
            )
        ).sum()
    )

    print(
        f"\nRows                 : "
        f"{len(districts)}"
    )

    print(
        f"Duplicate District_ID: "
        f"{duplicate_count}"
    )

    print(
        f"Blank District_Name  : "
        f"{blank_names}"
    )

    print(
        f"Non-verified rows    : "
        f"{non_verified}"
    )

    print(
        f"Bad composite IDs    : "
        f"{bad_composite}"
    )

    if any(
        [
            duplicate_count,
            blank_names,
            non_verified,
            bad_composite,
        ]
    ):
        raise ValueError(
            "\nDistrict master validation failed."
        )

    print(
        "\nDISTRICT MASTER: PASS"
    )

    return districts


# ============================================================
# LOAD NATIONAL AIDIS DELIVERY
# ============================================================

def load_national_file():

    print("\n" + "=" * 78)
    print("LOADING NATIONAL AIDIS DELIVERY")
    print("=" * 78)

    if not NATIONAL_FILE.exists():
        raise FileNotFoundError(
            f"\nNational AIDIS file not found:\n"
            f"{NATIONAL_FILE}"
        )

    data = pd.read_csv(
        NATIONAL_FILE,
        dtype=str,
        keep_default_na=False,
        low_memory=False
    )

    required_columns = (
        set(FINAL_COLUMNS)
        |
        {
            "houseHold_ID"
        }
    )

    missing = (
        required_columns
        -
        set(data.columns)
    )

    if missing:
        raise ValueError(
            "\nNational file is missing "
            f"required columns:\n{sorted(missing)}"
        )

    print(
        f"\nNational rows   : "
        f"{len(data):,}"
    )

    print(
        f"National columns: "
        f"{len(data.columns)}"
    )

    # Internal keys only.
    data[
        "_State_ID_Key"
    ] = data[
        "State_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    data[
        "_District_ID_Key"
    ] = data[
        "District_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            4
        )
    )

    return data


# ============================================================
# PREPARE FINAL 22-COLUMN DELIVERY
# ============================================================

def prepare_delivery(
    national,
    states,
    districts
):

    print("\n" + "=" * 78)
    print("PREPARING 36-STATE DELIVERY DATA")
    print("=" * 78)

    valid_state_ids = set(
        states[
            "State_ID"
        ]
    )

    # Remove national / All India rows.
    state_data = national[
        national[
            "_State_ID_Key"
        ]
        !=
        "00"
    ].copy()

    print(
        f"\nState/UT rows: "
        f"{len(state_data):,}"
    )

    if (
        len(state_data)
        !=
        EXPECTED_TOTAL_STATE_ROWS
    ):
        raise ValueError(
            f"\nExpected "
            f"{EXPECTED_TOTAL_STATE_ROWS:,} "
            f"State/UT rows but found "
            f"{len(state_data):,}."
        )

    # --------------------------------------------------------
    # Validate State_ID values
    # --------------------------------------------------------

    observed_state_ids = set(
        state_data[
            "_State_ID_Key"
        ].unique()
    )

    unknown_states = sorted(
        observed_state_ids
        -
        valid_state_ids
    )

    missing_states = sorted(
        valid_state_ids
        -
        observed_state_ids
    )

    if unknown_states:
        raise ValueError(
            f"\nUnknown State_ID values "
            f"in national data:\n"
            f"{unknown_states}"
        )

    if missing_states:
        raise ValueError(
            f"\nStates missing from national data:\n"
            f"{missing_states}"
        )

    # --------------------------------------------------------
    # Validate district-state relationship
    # --------------------------------------------------------

    actual_district_rows = state_data[
        state_data[
            "_District_ID_Key"
        ]
        !=
        "0000"
    ].copy()

    bad_prefix = actual_district_rows[
        actual_district_rows[
            "_District_ID_Key"
        ].str[:2]
        !=
        actual_district_rows[
            "_State_ID_Key"
        ]
    ]

    if not bad_prefix.empty:
        raise ValueError(
            "\nSome District_ID values do not "
            "belong to their State_ID."
        )

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

    observed_district_ids = set(
        actual_district_rows[
            "_District_ID_Key"
        ]
        .unique()
    )

    master_district_ids = set(
        districts[
            "District_ID"
        ]
    )

    unmapped = sorted(
        observed_district_ids
        -
        master_district_ids
    )

    if unmapped:
        raise ValueError(
            "\nNational AIDIS contains "
            "unmapped district IDs:\n"
            f"{unmapped}"
        )

    print(
        f"Observed district IDs: "
        f"{len(observed_district_ids)}"
    )

    print(
        f"Matched district IDs : "
        f"{len(observed_district_ids)}"
    )

    # --------------------------------------------------------
    # Apply official state names
    # --------------------------------------------------------

    state_name_lookup = dict(
        zip(
            states[
                "State_ID"
            ],
            states[
                "State_Name"
            ]
        )
    )

    state_data[
        "State_Name"
    ] = state_data[
        "_State_ID_Key"
    ].map(
        state_name_lookup
    )

    # --------------------------------------------------------
    # Apply verified NSS77 district names
    # --------------------------------------------------------

    def resolve_district_name(
        district_id
    ):

        if district_id == "0000":
            return "All Districts"

        return district_lookup[
            district_id
        ]

    state_data[
        "District_Name"
    ] = state_data[
        "_District_ID_Key"
    ].apply(
        resolve_district_name
    )

    # --------------------------------------------------------
    # Match Maharashtra reference delivery formatting
    # --------------------------------------------------------

    state_data[
        "FREQ_DESC"
    ] = "Annual"

    state_data[
        "Published_date"
    ] = state_data[
        "Published_date"
    ].apply(
        format_delivery_date
    )

    state_data[
        "Extracted_Date"
    ] = state_data[
        "Extracted_Date"
    ].apply(
        format_delivery_date
    )

    state_data[
        "DATA"
    ] = state_data[
        "DATA"
    ].apply(
        round_significant_digits
    )

    # Numeric-looking IDs in final delivery.
    state_data[
        "Survey_GROUP_ID"
    ] = state_data[
        "Survey_GROUP_ID"
    ].apply(
        integer_text
    )

    state_data[
        "State_ID"
    ] = state_data[
        "_State_ID_Key"
    ].apply(
        integer_text
    )

    state_data[
        "District_ID"
    ] = state_data[
        "_District_ID_Key"
    ].apply(
        integer_text
    )

    state_data[
        "Sector_code"
    ] = state_data[
        "Sector_code"
    ].apply(
        integer_text
    )

    state_data[
        "Visit_ID"
    ] = state_data[
        "Visit_ID"
    ].apply(
        integer_text
    )

    # --------------------------------------------------------
    # Final exact 22-column structure.
    #
    # houseHold_ID is deliberately excluded.
    # --------------------------------------------------------

    final_data = state_data[
        FINAL_COLUMNS
    ].copy()

    # --------------------------------------------------------
    # Safety validations
    # --------------------------------------------------------

    blank_data = int(
        final_data[
            "DATA"
        ]
        .str.strip()
        .eq("")
        .sum()
    )

    blank_district_names = int(
        final_data[
            "District_Name"
        ]
        .str.strip()
        .eq("")
        .sum()
    )

    placeholder_district_names = int(
        final_data[
            "District_Name"
        ]
        .str.match(
            r"^District code \d+$",
            case=False,
            na=False
        )
        .sum()
    )

    wrong_frequency = int(
        (
            final_data[
                "FREQ_DESC"
            ]
            !=
            "Annual"
        ).sum()
    )

    print(
        f"\nBlank DATA values          : "
        f"{blank_data}"
    )

    print(
        f"Blank District_Name values : "
        f"{blank_district_names}"
    )

    print(
        f"District-code placeholders : "
        f"{placeholder_district_names}"
    )

    print(
        f"Non-Annual rows            : "
        f"{wrong_frequency}"
    )

    if any(
        [
            blank_data,
            blank_district_names,
            placeholder_district_names,
            wrong_frequency,
        ]
    ):
        raise ValueError(
            "\nFinal delivery validation failed."
        )

    print(
        "\nDELIVERY PREPARATION: PASS"
    )

    return final_data


# ============================================================
# EXPORT 36 FILES
# ============================================================

def export_states(
    final_data,
    states
):

    print("\n" + "=" * 78)
    print("EXPORTING 36 STATE / UT FILES")
    print("=" * 78)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # Remove only previous AIDIS CSV outputs from this
    # dedicated final_states directory.
    for old_file in OUTPUT_DIR.glob(
        "AIDIS_*.csv"
    ):
        old_file.unlink()

    manifest = []

    total_exported_rows = 0

    for _, state in states.iterrows():

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

        state_df = final_data[
            final_data[
                "State_ID"
            ]
            ==
            state_id_output
        ].copy()

        if state_df.empty:
            raise ValueError(
                f"\nNo rows found for "
                f"{state_name} "
                f"(State_ID {state_id_key})."
            )

        if list(
            state_df.columns
        ) != FINAL_COLUMNS:
            raise ValueError(
                f"\nColumn structure failed "
                f"for {state_name}."
            )

        unique_state_ids = set(
            state_df[
                "State_ID"
            ].unique()
        )

        if unique_state_ids != {
            state_id_output
        }:
            raise ValueError(
                f"\nWrong State_ID detected "
                f"in {state_name} output."
            )

        output_file = (
            OUTPUT_DIR
            /
            file_name
        )

        state_df.to_csv(
            output_file,
            index=False,
            encoding="utf-8",
            lineterminator="\n"
        )

        row_count = len(
            state_df
        )

        total_exported_rows += (
            row_count
        )

        district_count = (
            state_df.loc[
                state_df[
                    "District_ID"
                ]
                !=
                "0",
                "District_ID"
            ]
            .nunique()
        )

        manifest.append(
            {
                "State_ID":
                    state_id_output,

                "State_Name":
                    state_name,

                "File_Name":
                    file_name,

                "Rows":
                    row_count,

                "Districts_Used":
                    district_count,

                "Status":
                    "PASS",
            }
        )

        print(
            f"{state_id_key}  "
            f"{state_name:<32} "
            f"{row_count:>8,} rows"
        )

    manifest_df = pd.DataFrame(
        manifest
    )

    manifest_df.to_csv(
        MANIFEST_FILE,
        index=False,
        encoding="utf-8"
    )

    created_files = list(
        OUTPUT_DIR.glob(
            "AIDIS_*.csv"
        )
    )

    print(
        f"\nFiles created       : "
        f"{len(created_files)}"
    )

    print(
        f"Total exported rows : "
        f"{total_exported_rows:,}"
    )

    if (
        len(created_files)
        !=
        EXPECTED_STATE_COUNT
    ):
        raise ValueError(
            f"\nExpected "
            f"{EXPECTED_STATE_COUNT} files "
            f"but found {len(created_files)}."
        )

    if (
        total_exported_rows
        !=
        EXPECTED_TOTAL_STATE_ROWS
    ):
        raise ValueError(
            f"\nExpected "
            f"{EXPECTED_TOTAL_STATE_ROWS:,} "
            f"exported rows but got "
            f"{total_exported_rows:,}."
        )

    print(
        "\n36-STATE EXPORT: PASS"
    )

    return manifest_df


# ============================================================
# OPTIONAL MAHARASHTRA EXACT COMPARISON
# ============================================================

def validate_maharashtra_reference():

    print("\n" + "=" * 78)
    print("MAHARASHTRA REFERENCE CHECK")
    print("=" * 78)

    reference_file = None

    for candidate in (
        MAHARASHTRA_REFERENCE_CANDIDATES
    ):
        if candidate.exists():
            reference_file = candidate
            break

    generated_file = (
        OUTPUT_DIR
        / "AIDIS_Maharashtra.csv"
    )

    if reference_file is None:

        print(
            "\nNo local Maharashtra "
            "reference file found."
        )

        print(
            "Reference comparison skipped."
        )

        return

    reference = pd.read_csv(
        reference_file,
        dtype=str,
        keep_default_na=False
    )

    generated = pd.read_csv(
        generated_file,
        dtype=str,
        keep_default_na=False
    )

    print(
        f"\nReference:"
        f"\n{reference_file}"
    )

    print(
        f"\nGenerated:"
        f"\n{generated_file}"
    )

    print(
        f"\nReference rows : "
        f"{len(reference):,}"
    )

    print(
        f"Generated rows : "
        f"{len(generated):,}"
    )

    if (
        list(reference.columns)
        !=
        list(generated.columns)
    ):
        raise ValueError(
            "\nMaharashtra column order "
            "does not match reference."
        )

    if reference.shape != generated.shape:
        raise ValueError(
            "\nMaharashtra shape does "
            "not match reference."
        )

    differences = (
        reference
        !=
        generated
    )

    difference_count = int(
        differences.sum().sum()
    )

    print(
        f"Different cells : "
        f"{difference_count:,}"
    )

    if difference_count:

        rows, columns = (
            differences.to_numpy()
            .nonzero()
        )

        first_row = int(
            rows[0]
        )

        first_column = int(
            columns[0]
        )

        column_name = (
            reference.columns[
                first_column
            ]
        )

        print(
            "\nFirst difference:"
        )

        print(
            f"Row    : {first_row + 2}"
        )

        print(
            f"Column : {column_name}"
        )

        print(
            "Reference:"
        )

        print(
            reference.iloc[
                first_row,
                first_column
            ]
        )

        print(
            "Generated:"
        )

        print(
            generated.iloc[
                first_row,
                first_column
            ]
        )

        raise ValueError(
            "\nMaharashtra reference "
            "comparison failed."
        )

    print(
        "\nMAHARASHTRA REFERENCE: PASS"
    )


# ============================================================
# FINAL SUMMARY
# ============================================================

def print_final_summary():

    print("\n" + "=" * 78)
    print("FINAL AIDIS ALL-STATE EXPORT SUMMARY")
    print("=" * 78)

    print(
        f"\nOutput folder:"
        f"\n{OUTPUT_DIR}"
    )

    print(
        f"\nManifest:"
        f"\n{MANIFEST_FILE}"
    )

    print(
        "\nExpected files     : 36"
    )

    print(
        "Expected columns   : 22"
    )

    print(
        "Expected total rows: 534,502"
    )

    print(
        "District mapping   : NSS77 VERIFIED"
    )

    print(
        "\nFINAL EXPORT STATUS: PASS"
    )

    print(
        "\nNo AIDIS KPI calculations "
        "were recomputed."
    )

    print(
        "The national delivery was "
        "formatted, enriched and split only."
    )

    print("\n" + "=" * 78)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS FINAL 36-STATE / UT EXPORTER")
    print("=" * 78)

    states = (
        load_state_master()
    )

    districts = (
        load_district_master()
    )

    national = (
        load_national_file()
    )

    final_data = (
        prepare_delivery(
            national=national,
            states=states,
            districts=districts
        )
    )

    export_states(
        final_data=final_data,
        states=states
    )

    validate_maharashtra_reference()

    print_final_summary()


if __name__ == "__main__":
    main()