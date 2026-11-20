from pathlib import Path
import pandas as pd


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
    / "AIDIS_All_States_Final.csv"
)


# ============================================================
# EXPECTED VALUES
# ============================================================

EXPECTED_STATE_COUNT = 36
EXPECTED_TOTAL_ROWS = 534_502


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
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS - COMBINE ALL 36 STATE / UT FILES")
    print("=" * 78)

    # --------------------------------------------------------
    # Validate paths
    # --------------------------------------------------------

    if not STATE_MASTER_FILE.exists():
        raise FileNotFoundError(
            f"State master not found:\n{STATE_MASTER_FILE}"
        )

    if not FINAL_STATES_DIR.exists():
        raise FileNotFoundError(
            f"Final states folder not found:\n{FINAL_STATES_DIR}"
        )

    # --------------------------------------------------------
    # Read state master
    # --------------------------------------------------------

    states = pd.read_csv(
        STATE_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    required_columns = {
        "State_ID",
        "State_Name",
        "File_Name",
    }

    missing_columns = (
        required_columns
        -
        set(states.columns)
    )

    if missing_columns:
        raise ValueError(
            "state_master.csv is missing columns: "
            f"{sorted(missing_columns)}"
        )

    if len(states) != EXPECTED_STATE_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_STATE_COUNT} states/UTs, "
            f"found {len(states)}."
        )

    print(f"\nStates/UTs in state master: {len(states)}")

    # --------------------------------------------------------
    # Read all state files
    # --------------------------------------------------------

    all_state_data = []

    total_rows = 0

    print("\n" + "=" * 78)
    print("READING STATE / UT FILES")
    print("=" * 78)

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
                f"\nMissing state file:\n{file_path}"
            )

        df = pd.read_csv(
            file_path,
            dtype=str,
            keep_default_na=False,
            low_memory=False
        )

        # ----------------------------------------------------
        # Exact 22-column validation
        # ----------------------------------------------------

        if list(df.columns) != FINAL_COLUMNS:

            raise ValueError(
                f"\nColumn structure mismatch:\n"
                f"{file_name}"
            )

        # ----------------------------------------------------
        # State ID validation
        # ----------------------------------------------------

        observed_state_ids = set(
            df["State_ID"].unique()
        )

        if observed_state_ids != {state_id}:

            raise ValueError(
                f"\nWrong State_ID found in "
                f"{file_name}.\n"
                f"Expected: {state_id}\n"
                f"Found: {observed_state_ids}"
            )

        # ----------------------------------------------------
        # State name validation
        # ----------------------------------------------------

        observed_state_names = set(
            df["State_Name"].unique()
        )

        if observed_state_names != {state_name}:

            raise ValueError(
                f"\nWrong State_Name found in "
                f"{file_name}.\n"
                f"Expected: {state_name}\n"
                f"Found: {observed_state_names}"
            )

        row_count = len(df)

        total_rows += row_count

        all_state_data.append(df)

        print(
            f"{state_id.zfill(2)}  "
            f"{state_name:<32} "
            f"{row_count:>8,} rows"
        )

    # --------------------------------------------------------
    # Combine
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("COMBINING FILES")
    print("=" * 78)

    combined = pd.concat(
        all_state_data,
        ignore_index=True
    )

    # Keep exact required column order.
    combined = combined[
        FINAL_COLUMNS
    ]

    # --------------------------------------------------------
    # Final validation
    # --------------------------------------------------------

    unique_states = (
        combined["State_ID"]
        .nunique()
    )

    blank_data = int(
        combined["DATA"]
        .str.strip()
        .eq("")
        .sum()
    )

    blank_district_names = int(
        combined["District_Name"]
        .str.strip()
        .eq("")
        .sum()
    )

    district_placeholders = int(
        combined["District_Name"]
        .str.match(
            r"^District code \d+$",
            case=False,
            na=False
        )
        .sum()
    )

    non_annual_rows = int(
        (
            combined["FREQ_DESC"]
            !=
            "Annual"
        ).sum()
    )

    print(f"\nCombined rows              : {len(combined):,}")
    print(f"Combined columns           : {len(combined.columns)}")
    print(f"Unique States/UTs          : {unique_states}")
    print(f"Blank DATA                 : {blank_data}")
    print(f"Blank District_Name        : {blank_district_names}")
    print(f"District code placeholders : {district_placeholders}")
    print(f"Non-Annual rows            : {non_annual_rows}")

    # --------------------------------------------------------
    # Validation gates
    # --------------------------------------------------------

    if len(combined) != EXPECTED_TOTAL_ROWS:

        raise ValueError(
            f"\nExpected {EXPECTED_TOTAL_ROWS:,} rows, "
            f"found {len(combined):,}."
        )

    if len(combined.columns) != len(FINAL_COLUMNS):

        raise ValueError(
            "\nExpected 22 columns."
        )

    if unique_states != EXPECTED_STATE_COUNT:

        raise ValueError(
            f"\nExpected {EXPECTED_STATE_COUNT} "
            f"State/UT IDs, found {unique_states}."
        )

    if blank_data != 0:

        raise ValueError(
            f"\nFound {blank_data} blank DATA values."
        )

    if blank_district_names != 0:

        raise ValueError(
            f"\nFound {blank_district_names} "
            f"blank District_Name values."
        )

    if district_placeholders != 0:

        raise ValueError(
            f"\nFound {district_placeholders} "
            f"district placeholders."
        )

    if non_annual_rows != 0:

        raise ValueError(
            f"\nFound {non_annual_rows} "
            f"non-Annual rows."
        )

    # --------------------------------------------------------
    # Save combined CSV
    # --------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    combined.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8",
        lineterminator="\n"
    )

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("FINAL COMBINED CSV SUMMARY")
    print("=" * 78)

    print(f"\nFiles combined : {len(all_state_data)}")
    print(f"States/UTs     : {unique_states}")
    print(f"Rows           : {len(combined):,}")
    print(f"Columns        : {len(combined.columns)}")

    print(
        f"\nOutput file:\n{OUTPUT_FILE}"
    )

    print("\nCOMBINED CSV STATUS: PASS")
    print("=" * 78)


if __name__ == "__main__":
    main()