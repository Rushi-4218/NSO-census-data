from pathlib import Path

import pandas as pd


# ============================================================
# PATH CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

AIDIS_ROOT = PROJECT_ROOT.parent

NATIONAL_FILE = AIDIS_ROOT / "AIDIS_Final_Client.csv"

DISTRICT_MASTER_FILE = (
    PROJECT_ROOT
    / "config"
    / "district_master.csv"
)


# ============================================================
# HELPER FUNCTION
# ============================================================

def normalize_code(value, width):
    """
    Convert numeric/string IDs into zero-padded strings.

    Examples:

        State:
            27      -> "27"

        District:
            2701    -> "2701"
            101     -> "0101"
    """

    if pd.isna(value):
        return None

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    if value == "":
        return None

    return value.zfill(width)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("AIDIS MAHARASHTRA DISTRICT MAPPING")
    print("=" * 70)

    # --------------------------------------------------------
    # 1. Validate required files
    # --------------------------------------------------------

    if not NATIONAL_FILE.exists():
        raise FileNotFoundError(
            f"National file not found:\n{NATIONAL_FILE}"
        )

    if not DISTRICT_MASTER_FILE.exists():
        raise FileNotFoundError(
            f"District master not found:\n{DISTRICT_MASTER_FILE}"
        )

    print("\nRequired files found.")

    # --------------------------------------------------------
    # 2. Read national AIDIS output
    # --------------------------------------------------------

    print("\nReading Maharashtra district information...")

    national = pd.read_csv(
        NATIONAL_FILE,
        usecols=[
            "State_ID",
            "District_ID",
            "District_Name"
        ],
        dtype=str,
        low_memory=False
    )

    # --------------------------------------------------------
    # 3. Normalize IDs
    # --------------------------------------------------------

    national["State_ID"] = (
        national["State_ID"]
        .apply(
            lambda x: normalize_code(
                x,
                2
            )
        )
    )

    national["District_ID"] = (
        national["District_ID"]
        .apply(
            lambda x: normalize_code(
                x,
                4
            )
        )
    )

    # --------------------------------------------------------
    # 4. Keep Maharashtra only
    #
    # Maharashtra State_ID = 27
    # --------------------------------------------------------

    maharashtra = national[
        national["State_ID"] == "27"
    ].copy()

    print(
        f"Maharashtra rows found: "
        f"{len(maharashtra):,}"
    )

    # --------------------------------------------------------
    # 5. Remove state-level rows
    #
    # District_ID = 0000 represents state total,
    # not an individual district.
    # --------------------------------------------------------

    maharashtra = maharashtra[
        maharashtra["District_ID"] != "0000"
    ].copy()

    # --------------------------------------------------------
    # 6. Clean District_Name
    # --------------------------------------------------------

    maharashtra["District_Name"] = (
        maharashtra["District_Name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # Remove empty names
    maharashtra = maharashtra[
        maharashtra["District_Name"] != ""
    ].copy()

    # Remove generic fallback names if any
    maharashtra = maharashtra[
        ~maharashtra["District_Name"]
        .str.lower()
        .str.startswith(
            "district code"
        )
    ].copy()

    # Remove All Districts
    maharashtra = maharashtra[
        maharashtra["District_Name"]
        .str.lower()
        != "all districts"
    ].copy()

    # --------------------------------------------------------
    # 7. Check that each District_ID has only one name
    # --------------------------------------------------------

    name_count = (
        maharashtra
        .groupby("District_ID")[
            "District_Name"
        ]
        .nunique()
    )

    conflicts = name_count[
        name_count > 1
    ]

    if not conflicts.empty:

        print(
            "\nERROR: Some Maharashtra District_ID "
            "values have multiple names:"
        )

        conflict_ids = conflicts.index.tolist()

        print(
            maharashtra[
                maharashtra["District_ID"]
                .isin(conflict_ids)
            ][
                [
                    "District_ID",
                    "District_Name"
                ]
            ]
            .drop_duplicates()
            .sort_values("District_ID")
            .to_string(index=False)
        )

        raise ValueError(
            "Conflicting Maharashtra district names found."
        )

    # --------------------------------------------------------
    # 8. Create unique Maharashtra lookup
    # --------------------------------------------------------

    lookup = (
        maharashtra[
            [
                "District_ID",
                "District_Name"
            ]
        ]
        .drop_duplicates()
        .sort_values("District_ID")
        .reset_index(drop=True)
    )

    print(
        f"\nUnique Maharashtra districts found: "
        f"{len(lookup)}"
    )

    print("\nMaharashtra lookup:\n")

    print(
        lookup.to_string(
            index=False
        )
    )

    # --------------------------------------------------------
    # 9. Read our working district master
    # --------------------------------------------------------

    district_master = pd.read_csv(
        DISTRICT_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    required_columns = {
        "State_ID",
        "State_Name",
        "District_Code",
        "District_ID",
        "District_Name",
        "Source",
        "Status",
        "Notes"
    }

    missing_columns = (
        required_columns
        - set(district_master.columns)
    )

    if missing_columns:

        raise ValueError(
            "district_master.csv is missing columns: "
            f"{sorted(missing_columns)}"
        )

    # --------------------------------------------------------
    # 10. Normalize our master IDs
    # --------------------------------------------------------

    district_master["State_ID"] = (
        district_master["State_ID"]
        .apply(
            lambda x: normalize_code(
                x,
                2
            )
        )
    )

    district_master["District_ID"] = (
        district_master["District_ID"]
        .apply(
            lambda x: normalize_code(
                x,
                4
            )
        )
    )

    district_master["District_Code"] = (
        district_master["District_Code"]
        .apply(
            lambda x: normalize_code(
                x,
                2
            )
        )
    )

    # --------------------------------------------------------
    # 11. Convert lookup to dictionary
    # --------------------------------------------------------

    district_name_lookup = dict(
        zip(
            lookup["District_ID"],
            lookup["District_Name"]
        )
    )

    # --------------------------------------------------------
    # 12. Update Maharashtra rows
    # --------------------------------------------------------

    maharashtra_mask = (
        district_master["State_ID"]
        == "27"
    )

    mapped_count = 0

    for index in district_master[
        maharashtra_mask
    ].index:

        district_id = (
            district_master.at[
                index,
                "District_ID"
            ]
        )

        if district_id in district_name_lookup:

            district_name = (
                district_name_lookup[
                    district_id
                ]
            )

            district_master.at[
                index,
                "District_Name"
            ] = district_name

            district_master.at[
                index,
                "Source"
            ] = "AIDIS_Final_Client.csv"

            district_master.at[
                index,
                "Status"
            ] = "VERIFIED"

            district_master.at[
                index,
                "Notes"
            ] = (
                "Mapped from friend national "
                "AIDIS delivery"
            )

            mapped_count += 1

    # --------------------------------------------------------
    # 13. Check Maharashtra rows that are still unmapped
    # --------------------------------------------------------

    mh_master = district_master[
        maharashtra_mask
    ].copy()

    unmapped = mh_master[
        mh_master["Status"]
        != "VERIFIED"
    ]

    # --------------------------------------------------------
    # 14. Save updated district master
    # --------------------------------------------------------

    district_master.to_csv(
        DISTRICT_MASTER_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 15. Summary
    # --------------------------------------------------------

    print("\n" + "=" * 70)
    print("MAHARASHTRA MAPPING SUMMARY")
    print("=" * 70)

    print(
        f"\nDistricts in Maharashtra master : "
        f"{len(mh_master)}"
    )

    print(
        f"Districts mapped successfully   : "
        f"{mapped_count}"
    )

    print(
        f"Districts still unmapped        : "
        f"{len(unmapped)}"
    )

    if not unmapped.empty:

        print("\nUnmapped Maharashtra districts:\n")

        print(
            unmapped[
                [
                    "District_ID",
                    "District_Code",
                    "District_Name"
                ]
            ]
            .to_string(
                index=False
            )
        )

    print(
        f"\nUpdated file:\n"
        f"{DISTRICT_MASTER_FILE}"
    )

    if len(unmapped) == 0:

        print("\nMAHARASHTRA DISTRICT MAPPING: PASS")

    else:

        print("\nMAHARASHTRA DISTRICT MAPPING: REVIEW REQUIRED")

    print("=" * 70)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()