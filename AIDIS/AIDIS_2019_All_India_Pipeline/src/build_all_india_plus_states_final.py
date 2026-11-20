from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

import pandas as pd


# ============================================================
# PATHS
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

FINAL_STATES_DIR = (
    PROJECT_ROOT
    / "output"
    / "final_states"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "output"
    / "AIDIS_All_India_And_States_Final.csv"
)


# ============================================================
# EXPECTED COUNTS
# ============================================================

EXPECTED_ALL_INDIA_ROWS = 1_035
EXPECTED_STATE_ROWS = 534_502
EXPECTED_FINAL_ROWS = 535_537
EXPECTED_STATE_COUNT = 36


# ============================================================
# FINAL 22-COLUMN CLIENT FORMAT
# ============================================================

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
    if pd.isna(value):
        return ""

    value = str(value).strip()

    if not value:
        return ""

    if value.endswith(".0"):
        value = value[:-2]

    return value.zfill(width)


def integer_text(value):
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
        day = int(match.group(1))
        month = match.group(2).title()
        year = match.group(3)

        if len(year) == 4:
            year = year[-2:]

        return f"{day:02d}-{month}-{year}"

    raise ValueError(
        f"Unsupported date format: {value}"
    )


def round_significant_digits(value, digits=10):
    if pd.isna(value):
        return ""

    value = str(value).strip()

    if not value:
        return ""

    try:
        number = Decimal(value)

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
            - digits
            + 1
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
# BUILD ALL-INDIA SECTION
# ============================================================

def build_all_india_rows():

    print("\n" + "=" * 78)
    print("BUILDING ALL INDIA / ALL STATES SECTION")
    print("=" * 78)

    if not NATIONAL_FILE.exists():
        raise FileNotFoundError(
            f"National source not found:\n{NATIONAL_FILE}"
        )

    national = pd.read_csv(
        NATIONAL_FILE,
        dtype=str,
        keep_default_na=False,
        low_memory=False
    )

    national["_State_Key"] = (
        national["State_ID"]
        .apply(
            lambda value:
            normalize_code(
                value,
                2
            )
        )
    )

    all_india = national[
        national["_State_Key"] == "00"
    ].copy()

    print(
        f"\nAll India source rows: "
        f"{len(all_india):,}"
    )

    if len(all_india) != EXPECTED_ALL_INDIA_ROWS:
        raise ValueError(
            f"Expected {EXPECTED_ALL_INDIA_ROWS:,} "
            f"All India rows, found "
            f"{len(all_india):,}."
        )

    # --------------------------------------------------------
    # Match the final state-file formatting
    # --------------------------------------------------------

    all_india["FREQ_DESC"] = "Annual"

    all_india["State_ID"] = "0"

    # Official national aggregate
    all_india["State_Name"] = "All India"

    all_india["District_ID"] = "0"

    # This is intentionally "All Districts" so that the
    # District_Name column behaves exactly like the
    # state-level files shown in the Maharashtra reference.
    all_india["District_Name"] = "All Districts"

    all_india["Published_date"] = (
        all_india["Published_date"]
        .apply(format_delivery_date)
    )

    all_india["Extracted_Date"] = (
        all_india["Extracted_Date"]
        .apply(format_delivery_date)
    )

    all_india["DATA"] = (
        all_india["DATA"]
        .apply(round_significant_digits)
    )

    all_india["Survey_GROUP_ID"] = (
        all_india["Survey_GROUP_ID"]
        .apply(integer_text)
    )

    all_india["Sector_code"] = (
        all_india["Sector_code"]
        .apply(integer_text)
    )

    all_india["Visit_ID"] = (
        all_india["Visit_ID"]
        .apply(integer_text)
    )

    all_india = all_india[
        FINAL_COLUMNS
    ].copy()

    print(
        f"Final All India rows : "
        f"{len(all_india):,}"
    )

    print(
        "ALL INDIA SECTION: PASS"
    )

    return all_india


# ============================================================
# LOAD THE 36 ALREADY-VALIDATED STATE FILES
# ============================================================

def load_all_state_rows():

    print("\n" + "=" * 78)
    print("LOADING 36 VALIDATED STATE / UT FILES")
    print("=" * 78)

    if not STATE_MASTER_FILE.exists():
        raise FileNotFoundError(
            f"State master not found:\n"
            f"{STATE_MASTER_FILE}"
        )

    states = pd.read_csv(
        STATE_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    if len(states) != EXPECTED_STATE_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_STATE_COUNT} "
            f"states/UTs, found {len(states)}."
        )

    frames = []
    total_rows = 0

    for _, state in states.iterrows():

        state_id = str(
            int(state["State_ID"])
        )

        state_name = state["State_Name"]
        file_name = state["File_Name"]

        file_path = (
            FINAL_STATES_DIR
            /
            file_name
        )

        if not file_path.exists():
            raise FileNotFoundError(
                f"Missing validated state file:\n"
                f"{file_path}"
            )

        df = pd.read_csv(
            file_path,
            dtype=str,
            keep_default_na=False,
            low_memory=False
        )

        if list(df.columns) != FINAL_COLUMNS:
            raise ValueError(
                f"22-column structure mismatch:\n"
                f"{file_name}"
            )

        observed_ids = set(
            df["State_ID"].unique()
        )

        if observed_ids != {state_id}:
            raise ValueError(
                f"Wrong State_ID in {file_name}: "
                f"{observed_ids}"
            )

        observed_names = set(
            df["State_Name"].unique()
        )

        if observed_names != {state_name}:
            raise ValueError(
                f"Wrong State_Name in "
                f"{file_name}"
            )

        frames.append(df)

        row_count = len(df)
        total_rows += row_count

        print(
            f"{state_id.zfill(2)}  "
            f"{state_name:<32} "
            f"{row_count:>8,} rows"
        )

    states_combined = pd.concat(
        frames,
        ignore_index=True
    )

    if total_rows != EXPECTED_STATE_ROWS:
        raise ValueError(
            f"Expected {EXPECTED_STATE_ROWS:,} "
            f"state rows, found "
            f"{total_rows:,}."
        )

    print(
        f"\nCombined State/UT rows: "
        f"{len(states_combined):,}"
    )

    print(
        "STATE / UT SECTION: PASS"
    )

    return states_combined


# ============================================================
# FINAL COMBINATION
# ============================================================

def build_final_file(
    all_india,
    all_states
):

    print("\n" + "=" * 78)
    print("CREATING FINAL ALL INDIA + 36 STATE CSV")
    print("=" * 78)

    # All India first, followed by State_ID 1 through 36.
    final = pd.concat(
        [
            all_india,
            all_states,
        ],
        ignore_index=True
    )

    final = final[
        FINAL_COLUMNS
    ]

    # --------------------------------------------------------
    # Final validations
    # --------------------------------------------------------

    all_india_count = int(
        (
            final["State_ID"] == "0"
        ).sum()
    )

    state_count = int(
        (
            final["State_ID"] != "0"
        ).sum()
    )

    unique_state_values = (
        final["State_ID"]
        .nunique()
    )

    blank_data = int(
        final["DATA"]
        .str.strip()
        .eq("")
        .sum()
    )

    blank_district_name = int(
        final["District_Name"]
        .str.strip()
        .eq("")
        .sum()
    )

    district_placeholders = int(
        final["District_Name"]
        .str.match(
            r"^District code \d+$",
            case=False,
            na=False
        )
        .sum()
    )

    non_annual = int(
        (
            final["FREQ_DESC"]
            !=
            "Annual"
        ).sum()
    )

    print(
        f"\nAll India rows             : "
        f"{all_india_count:,}"
    )

    print(
        f"36 State/UT rows           : "
        f"{state_count:,}"
    )

    print(
        f"Total rows                 : "
        f"{len(final):,}"
    )

    print(
        f"Columns                    : "
        f"{len(final.columns)}"
    )

    print(
        f"Unique State_ID values     : "
        f"{unique_state_values}"
    )

    print(
        f"Blank DATA                 : "
        f"{blank_data}"
    )

    print(
        f"Blank District_Name        : "
        f"{blank_district_name}"
    )

    print(
        f"District code placeholders : "
        f"{district_placeholders}"
    )

    print(
        f"Non-Annual rows            : "
        f"{non_annual}"
    )

    if len(final) != EXPECTED_FINAL_ROWS:
        raise ValueError(
            f"Expected {EXPECTED_FINAL_ROWS:,} "
            f"final rows, found "
            f"{len(final):,}."
        )

    if len(final.columns) != 22:
        raise ValueError(
            "Final output must contain "
            "exactly 22 columns."
        )

    # State_ID 0 + 36 State/UT IDs = 37
    if unique_state_values != 37:
        raise ValueError(
            f"Expected 37 State_ID values "
            f"(All India + 36 states), "
            f"found {unique_state_values}."
        )

    if all_india_count != EXPECTED_ALL_INDIA_ROWS:
        raise ValueError(
            "All India row count failed."
        )

    if state_count != EXPECTED_STATE_ROWS:
        raise ValueError(
            "State/UT row count failed."
        )

    if blank_data != 0:
        raise ValueError(
            f"Blank DATA values: "
            f"{blank_data}"
        )

    if blank_district_name != 0:
        raise ValueError(
            f"Blank District_Name values: "
            f"{blank_district_name}"
        )

    if district_placeholders != 0:
        raise ValueError(
            f"District placeholders found: "
            f"{district_placeholders}"
        )

    if non_annual != 0:
        raise ValueError(
            f"Non-Annual rows found: "
            f"{non_annual}"
        )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    final.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8",
        lineterminator="\n"
    )

    print("\n" + "=" * 78)
    print("FINAL MASTER CSV SUMMARY")
    print("=" * 78)

    print(
        "\nAll India aggregate rows : "
        f"{EXPECTED_ALL_INDIA_ROWS:,}"
    )

    print(
        "36 State/UT rows         : "
        f"{EXPECTED_STATE_ROWS:,}"
    )

    print(
        "Final rows               : "
        f"{len(final):,}"
    )

    print(
        "Final columns            : "
        f"{len(final.columns)}"
    )

    print(
        f"\nOutput:\n{OUTPUT_FILE}"
    )

    print(
        "\nFINAL MASTER CSV STATUS: PASS"
    )

    print("=" * 78)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS ALL INDIA + 36 STATE FINAL MASTER BUILDER")
    print("=" * 78)

    all_india = build_all_india_rows()

    all_states = load_all_state_rows()

    build_final_file(
        all_india=all_india,
        all_states=all_states
    )


if __name__ == "__main__":
    main()