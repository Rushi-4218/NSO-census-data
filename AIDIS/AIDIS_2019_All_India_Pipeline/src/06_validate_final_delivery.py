from pathlib import Path
import re
import sys

import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

FINAL_FILE = (
    ROOT
    / "output"
    / "final"
    / "AIDIS_All_India_States_Districts_Final.csv"
)

REPORT_FILE = (
    ROOT
    / "output"
    / "reports"
    / "final_delivery_validation.txt"
)


# ============================================================
# EXPECTED STRUCTURE
# ============================================================

EXPECTED_COLUMNS = [
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

EXPECTED_ROWS = 566922
EXPECTED_COL_IDS = 114
EXPECTED_STATES = 36
EXPECTED_DISTRICTS = 682
EXPECTED_DOMAINS = 4973


# ============================================================
# CONTROL VALUES FROM VALIDATED STEPS
# ============================================================

CONTROL_VALUES = {

    # Debt - validated against official AIDIS controls

    ("AOD", 0, 0):
        80163.54,

    ("AOD", 1, 0):
        59748.37,

    ("AOD", 2, 0):
        120336.31,

    ("IOI", 0, 0):
        30.7834,

    ("IOI", 1, 0):
        35.0362,

    ("IOI", 2, 0):
        22.4148,

    # Asset engine controls from corrected Step 03B

    ("AVA", 0, 0):
        2032991.81,

    ("AVA", 1, 0):
        1643788.89,

    ("AVA", 2, 0):
        2798861.50,
}


# ============================================================
# HELPERS
# ============================================================

def numeric(value):

    try:
        return float(value)

    except Exception:
        return None


def close_enough(
    actual,
    expected,
    tolerance=0.05
):

    if actual is None:
        return False

    return (
        abs(
            actual
            -
            expected
        )
        <=
        tolerance
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS NSS 77 - STEP 06 FINAL DELIVERY VALIDATION"
    )

    print(
        "=" * 78
    )

    if not FINAL_FILE.exists():

        raise FileNotFoundError(
            f"Final file not found:\n"
            f"{FINAL_FILE}"
        )

    print(
        "\nLoading final delivery..."
    )

    df = pd.read_csv(
        FINAL_FILE,
        dtype=str,
        low_memory=False
    )

    issues = []
    warnings = []

    # ========================================================
    # 1. BASIC FILE STRUCTURE
    # ========================================================

    print(
        "\n[1] File structure"
    )

    row_count = len(
        df
    )

    column_count = len(
        df.columns
    )

    print(
        f"Rows                : "
        f"{row_count:,}"
    )

    print(
        f"Columns             : "
        f"{column_count:,}"
    )

    if list(
        df.columns
    ) != EXPECTED_COLUMNS:

        issues.append(
            "Final column structure/order "
            "does not match required 22-column schema."
        )

    if row_count != EXPECTED_ROWS:

        warnings.append(
            f"Expected {EXPECTED_ROWS:,} rows, "
            f"found {row_count:,}."
        )

    # ========================================================
    # 2. REQUIRED FIELDS
    # ========================================================

    print(
        "\n[2] Required-field checks"
    )

    required_nonblank = [
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

    for column in required_nonblank:

        blanks = int(
            df[
                column
            ]
            .fillna("")
            .str.strip()
            .eq("")
            .sum()
        )

        print(
            f"{column:20s}: "
            f"{blanks:,} blank"
        )

        if blanks:

            issues.append(
                f"{column} contains "
                f"{blanks:,} blank values."
            )

    # ========================================================
    # 3. DUPLICATE FINAL OBSERVATIONS
    # ========================================================

    print(
        "\n[3] Duplicate final observations"
    )

    duplicate_key = [
        "Survey_ID",
        "Year",
        "State_ID",
        "District_ID",
        "Sector_code",
        "SUB_GROUP_ID",
        "Visit_ID",
        "Col_ID",
    ]

    duplicate_count = int(
        df.duplicated(
            subset=duplicate_key,
            keep=False
        ).sum()
    )

    print(
        f"Duplicate rows       : "
        f"{duplicate_count:,}"
    )

    if duplicate_count:

        issues.append(
            f"{duplicate_count:,} final rows "
            "have duplicate statistical keys."
        )

    # ========================================================
    # 4. KPI COVERAGE
    # ========================================================

    print(
        "\n[4] KPI coverage"
    )

    col_id_count = int(
        df[
            "Col_ID"
        ].nunique()
    )

    print(
        f"Unique Col_ID        : "
        f"{col_id_count:,}"
    )

    if col_id_count != EXPECTED_COL_IDS:

        issues.append(
            f"Expected {EXPECTED_COL_IDS} "
            f"Col_ID values; found "
            f"{col_id_count}."
        )

    required_col_ids = {

        "AOD",
        "AODL",
        "AVA",
        "DAR",
        "HH_SURVEYED",
        "IOI",

        "GINI_ASSET",

        "FCE",
        "EPL",

        "ADULT_BANK_TOTAL",
        "ADULT_BANK_MALE",
        "ADULT_BANK_FEMALE",

        "AVA_COMPONENT_PHYSICAL_ASSETS",
        "AVA_COMPONENT_FINANCIAL_ASSETS",
        "AVA_COMPONENT_LAND",
        "AVA_COMPONENT_BUILDINGS",
        "AVA_COMPONENT_DEPOSITS",
        "AVA_COMPONENT_LIVESTOCK_POULTRY",
        "AVA_COMPONENT_AGRICULTURAL_MACHINERY_EQUIPMENT",
        "AVA_COMPONENT_TRANSPORT_EQUIPMENT",
        "AVA_COMPONENT_NON_FARM_BUSINESS_EQUIPMENT",
        "AVA_COMPONENT_OTHERS",

        "CREDIT_SOURCE_ALL_INSTITUTIONAL_SOURCES",
        "CREDIT_SOURCE_ALL_NON_INSTITUTIONAL_SOURCES",
    }

    existing_ids = set(
        df[
            "Col_ID"
        ]
    )

    missing_ids = sorted(
        required_col_ids
        -
        existing_ids
    )

    print(
        f"Missing required IDs : "
        f"{len(missing_ids):,}"
    )

    if missing_ids:

        issues.append(
            "Missing required Col_ID values: "
            +
            ", ".join(
                missing_ids
            )
        )

    # ========================================================
    # 5. GEOGRAPHY COVERAGE
    # ========================================================

    print(
        "\n[5] Geography coverage"
    )

    state_ids = pd.to_numeric(
        df[
            "State_ID"
        ],
        errors="coerce"
    )

    district_ids = pd.to_numeric(
        df[
            "District_ID"
        ],
        errors="coerce"
    )

    states = set(
        state_ids[
            state_ids
            >
            0
        ]
        .dropna()
        .astype(int)
    )

    districts = set(
        district_ids[
            district_ids
            >
            0
        ]
        .dropna()
        .astype(int)
    )

    print(
        f"States/UTs           : "
        f"{len(states):,}"
    )

    print(
        f"Observed districts   : "
        f"{len(districts):,}"
    )

    if len(
        states
    ) != EXPECTED_STATES:

        issues.append(
            f"Expected {EXPECTED_STATES} "
            f"States/UTs; found "
            f"{len(states)}."
        )

    if len(
        districts
    ) != EXPECTED_DISTRICTS:

        issues.append(
            f"Expected {EXPECTED_DISTRICTS} "
            f"observed districts; "
            f"found {len(districts)}."
        )

    # All India must exist.

    all_india_rows = df[
        (
            state_ids
            ==
            0
        )
        &
        (
            district_ids
            ==
            0
        )
    ]

    print(
        f"All India rows       : "
        f"{len(all_india_rows):,}"
    )

    if all_india_rows.empty:

        issues.append(
            "All India observations are missing."
        )

    # ========================================================
    # 6. DOMAIN COVERAGE
    # ========================================================

    print(
        "\n[6] Domain coverage"
    )

    domain_columns = [
        "State_ID",
        "District_ID",
        "Sector_code",
        "SUB_GROUP_ID",
        "Visit_ID",
    ]

    domain_count = int(
        df[
            domain_columns
        ]
        .drop_duplicates()
        .shape[
            0
        ]
    )

    print(
        f"Domains              : "
        f"{domain_count:,}"
    )

    if domain_count != EXPECTED_DOMAINS:

        warnings.append(
            f"Expected {EXPECTED_DOMAINS:,} "
            f"domains; found "
            f"{domain_count:,}."
        )

    # Every emitted domain should have 114 indicators.

    per_domain = (
        df.groupby(
            domain_columns,
            dropna=False
        )[
            "Col_ID"
        ]
        .nunique()
    )

    bad_domains = int(
        (
            per_domain
            !=
            EXPECTED_COL_IDS
        ).sum()
    )

    print(
        f"Incomplete domains   : "
        f"{bad_domains:,}"
    )

    if bad_domains:

        issues.append(
            f"{bad_domains:,} domains "
            "do not contain all 114 KPIs."
        )

    # ========================================================
    # 7. SECTOR VALUES
    # ========================================================

    print(
        "\n[7] Sector validation"
    )

    allowed_sector_codes = {
        "0",
        "1",
        "2",
    }

    bad_sector_codes = sorted(
        set(
            df[
                "Sector_code"
            ].astype(str)
        )
        -
        allowed_sector_codes
    )

    print(
        f"Invalid sector codes : "
        f"{len(bad_sector_codes):,}"
    )

    if bad_sector_codes:

        issues.append(
            "Unexpected Sector_code values: "
            +
            ", ".join(
                bad_sector_codes
            )
        )

    # ========================================================
    # 8. DATE FORMATS
    # ========================================================

    print(
        "\n[8] Date format"
    )

    date_pattern = re.compile(
        r"^\d{2}-[A-Za-z]{3}-\d{4}$"
    )

    for column in [
        "Published_date",
        "Extracted_Date",
    ]:

        invalid = int(
            (
                ~df[
                    column
                ]
                .fillna("")
                .str.match(
                    date_pattern
                )
            ).sum()
        )

        print(
            f"{column:20s}: "
            f"{invalid:,} invalid"
        )

        if invalid:

            issues.append(
                f"{column} contains "
                f"{invalid:,} invalid dates."
            )

    # ========================================================
    # 9. NUMERIC DATA
    # ========================================================

    print(
        "\n[9] DATA numeric validation"
    )

    numeric_data = pd.to_numeric(
        df[
            "DATA"
        ],
        errors="coerce"
    )

    bad_numeric = int(
        numeric_data.isna().sum()
    )

    print(
        f"Non-numeric DATA     : "
        f"{bad_numeric:,}"
    )

    if bad_numeric:

        issues.append(
            f"{bad_numeric:,} DATA values "
            "are non-numeric."
        )

    # ========================================================
    # 10. CORE ALL-INDIA/RURAL/URBAN CONTROLS
    # ========================================================

    print(
        "\n[10] Core control checks"
    )

    control_failures = 0

    for (
        col_id,
        sector_code,
        district_id
    ), expected in CONTROL_VALUES.items():

        selected = df[
            (
                df[
                    "State_ID"
                ].astype(str)
                ==
                "0"
            )
            &
            (
                df[
                    "District_ID"
                ].astype(str)
                ==
                str(
                    district_id
                )
            )
            &
            (
                df[
                    "Sector_code"
                ].astype(str)
                ==
                str(
                    sector_code
                )
            )
            &
            (
                df[
                    "SUB_GROUP_ID"
                ]
                ==
                "All HH"
            )
            &
            (
                df[
                    "Col_ID"
                ]
                ==
                col_id
            )
        ]

        if len(
            selected
        ) != 1:

            print(
                f"{col_id} sector "
                f"{sector_code}: "
                "MISSING/AMBIGUOUS"
            )

            control_failures += 1

            continue

        actual = numeric(
            selected[
                "DATA"
            ].iloc[
                0
            ]
        )

        passed = close_enough(
            actual,
            expected
        )

        print(
            f"{col_id:5s} "
            f"sector={sector_code} "
            f"actual={actual:,.4f} "
            f"expected={expected:,.4f} "
            f"{'PASS' if passed else 'FAIL'}"
        )

        if not passed:
            control_failures += 1

    if control_failures:

        issues.append(
            f"{control_failures} "
            "All-India control checks failed."
        )

    # ========================================================
    # 11. RANGE CHECKS
    # ========================================================

    print(
        "\n[11] Percentage / ratio range checks"
    )

    percent_rows = df[
        df[
            "Unit"
        ]
        ==
        "%"
    ].copy()

    percent_values = pd.to_numeric(
        percent_rows[
            "DATA"
        ],
        errors="coerce"
    )

    bad_percent = int(
        (
            (
                percent_values
                <
                0
            )
            |
            (
                percent_values
                >
                100
            )
        ).sum()
    )

    print(
        f"Percent outside 0-100: "
        f"{bad_percent:,}"
    )

    if bad_percent:

        issues.append(
            f"{bad_percent:,} percentage "
            "observations fall outside 0-100."
        )

    gini = df[
        df[
            "Col_ID"
        ]
        ==
        "GINI_ASSET"
    ].copy()

    gini_values = pd.to_numeric(
        gini[
            "DATA"
        ],
        errors="coerce"
    )

    bad_gini = int(
        (
            (
                gini_values
                <
                0
            )
            |
            (
                gini_values
                >
                1
            )
        ).sum()
    )

    print(
        f"Gini outside 0-1     : "
        f"{bad_gini:,}"
    )

    if bad_gini:

        issues.append(
            f"{bad_gini:,} Gini values "
            "fall outside 0-1."
        )

    # ========================================================
    # FINAL RESULT
    # ========================================================

    print(
        "\n" + "=" * 78
    )

    print(
        "FINAL DELIVERY RESULT"
    )

    print(
        "=" * 78
    )

    status = (
        "PASS"
        if not issues
        else
        "FAIL"
    )

    summary = [

        "=" * 78,

        "AIDIS NSS 77 - FINAL DELIVERY VALIDATION",

        "=" * 78,

        "",

        f"Final file          : {FINAL_FILE}",

        f"Rows                : {row_count:,}",

        f"Columns             : {column_count:,}",

        f"Unique Col_ID       : {col_id_count:,}",

        f"Domains             : {domain_count:,}",

        f"States/UTs          : {len(states):,}",

        f"Observed districts  : {len(districts):,}",

        f"Duplicate rows      : {duplicate_count:,}",

        f"Incomplete domains  : {bad_domains:,}",

        f"Non-numeric DATA    : {bad_numeric:,}",

        f"Bad percentages     : {bad_percent:,}",

        f"Bad Gini values     : {bad_gini:,}",

        f"Control failures    : {control_failures:,}",

        "",

        f"Issues              : {len(issues):,}",

        f"Warnings            : {len(warnings):,}",

        "",
    ]

    if issues:

        summary.append(
            "ISSUES:"
        )

        for issue in issues:

            summary.append(
                f"  - {issue}"
            )

        summary.append(
            ""
        )

    if warnings:

        summary.append(
            "WARNINGS:"
        )

        for warning in warnings:

            summary.append(
                f"  - {warning}"
            )

        summary.append(
            ""
        )

    summary.extend(
        [

            f"FINAL DELIVERY STATUS: "
            f"{status}",

            "=" * 78,
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(
            summary
        ),
        encoding="utf-8"
    )

    print(
        "\n".join(
            summary
        )
    )

    if issues:

        sys.exit(
            1
        )


if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            "\n" + "=" * 78
        )

        print(
            "STEP 06 FINAL VALIDATION: FAIL"
        )

        print(
            "=" * 78
        )

        print(
            f"\n{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(
            1
        )