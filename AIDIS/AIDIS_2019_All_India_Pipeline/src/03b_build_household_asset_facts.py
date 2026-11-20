from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd
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

HOUSEHOLD_BASE_FILE = (
    PROJECT_ROOT
    / "cache"
    / "household_base_visit1.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "cache"
    / "household_asset_facts_visit1.csv"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

BUILD_REPORT = (
    REPORT_DIR
    / "household_asset_build_report.csv"
)

SUMMARY_REPORT = (
    REPORT_DIR
    / "household_asset_build_summary.txt"
)

POLICY_REPORT = (
    REPORT_DIR
    / "household_asset_calculation_policy.txt"
)


MASTER_DDI_SHEET = "Master_DDI_AIDIS_77th_Round"


# ============================================================
# OFFICIAL CONTROL VALUES
# NSS REPORT 588
# ============================================================

OFFICIAL_RURAL_AVA = 1592379.0
OFFICIAL_URBAN_AVA = 2717081.0


# ============================================================
# ASSET SPECIFICATIONS
#
# Levels 05-11 already represent the asset valuation needed
# for the fixed asset-reference position.
#
# Levels 12 and 13 require the 30.06.2018 fields:
#
#   Level 12 -> b11aq6
#   Level 13 -> b11bq6
# ============================================================

ASSET_SPECS = {

    5: {
        "name": "Rural_Land_Value",
        "item_column": "b5pt1q1",
        "value_column": "b5pt1q5",
        "total_code": "99",
        "control_codes": {"97", "98", "99"},
    },

    6: {
        "name": "Urban_Land_Value",
        "item_column": "b5pt2q1",
        "value_column": "b5pt2q5",
        "total_code": "99",
        "control_codes": {"97", "98", "99"},
    },

    7: {
        "name": "Building_Value",
        "item_column": "b6q3",
        "value_column": "b6q5",
        "total_code": "10",
        "control_codes": {"10"},
    },

    8: {
        "name": "Livestock_Value",
        "item_column": "b7q2",
        "value_column": "b7q4",
        "total_code": "17",
        "control_codes": {"13", "17"},
    },

    9: {
        "name": "Transport_Value",
        "item_column": "b8q2",
        "value_column": "b8q4",
        "total_code": "8",
        "control_codes": {"8"},
    },

    10: {
        "name": "Agri_Machinery_Value",
        "item_column": "b9q2",
        "value_column": "b9q4",
        "total_code": "13",
        "control_codes": {"13"},
    },

    11: {
        "name": "NonFarm_Business_Value",
        "item_column": "b10q2",
        "value_column": "b10q3",
        "total_code": "20",
        "control_codes": {"15", "20"},
    },

    13: {
        "name": "Shares_Investments_Value",
        "item_column": "b11bq1",

        # CORRECT FIXED REFERENCE DATE FIELD
        "value_column": "b11bq6",

        "total_code": "5",
        "control_codes": {"5"},
    },
}


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):

    if value is None or pd.isna(value):
        return ""

    value = str(value).strip()

    if value.lower() in {
        "nan",
        "none",
        "<na>",
    }:
        return ""

    return value


def normalize_integer_text(value):

    value = clean_text(value)

    if not value:
        return ""

    if re.fullmatch(
        r"[+-]?\d+\.0+",
        value
    ):
        return value.split(".")[0]

    return value


def normalize_item(value):

    value = normalize_integer_text(
        value
    )

    if not value:
        return ""

    try:
        return str(
            int(
                float(value)
            )
        )

    except Exception:
        return value


# ============================================================
# DDI SOURCE MAP
# ============================================================

def load_source_map():

    workbook = load_workbook(
        DDI_FILE,
        read_only=True,
        data_only=True
    )

    ws = workbook[
        MASTER_DDI_SHEET
    ]

    rows = ws.iter_rows(
        values_only=True
    )

    headers = [
        clean_text(value)
        for value in next(rows)
    ]

    index = {
        header: position
        for position, header
        in enumerate(headers)
    }

    working = {}

    for row in rows:

        visit = clean_text(
            row[
                index["Visit"]
            ]
        )

        if visit != "Visit 1":
            continue

        level_text = clean_text(
            row[
                index["Level"]
            ]
        )

        match = re.fullmatch(
            r"Level\s+(\d+)",
            level_text
        )

        if not match:
            continue

        level_number = int(
            match.group(1)
        )

        if level_number not in range(
            5,
            14
        ):
            continue

        source_file = clean_text(
            row[
                index["Source_File"]
            ]
        )

        source_sheet = clean_text(
            row[
                index["Source_Sheet"]
            ]
        )

        if level_number not in working:

            working[
                level_number
            ] = {
                "files": set(),
                "sheets": set(),
            }

        if source_file:

            working[
                level_number
            ][
                "files"
            ].add(
                source_file
            )

        if source_sheet:

            working[
                level_number
            ][
                "sheets"
            ].add(
                source_sheet
            )

    workbook.close()

    output = {}

    for level_number in range(
        5,
        14
    ):

        if level_number not in working:

            raise ValueError(
                f"DDI missing Visit 1 Level "
                f"{level_number}"
            )

        files = working[
            level_number
        ][
            "files"
        ]

        sheets = working[
            level_number
        ][
            "sheets"
        ]

        if len(files) != 1:

            raise ValueError(
                f"Level {level_number}: "
                f"source files = {sorted(files)}"
            )

        if len(sheets) != 1:

            raise ValueError(
                f"Level {level_number}: "
                f"source sheets = {sorted(sheets)}"
            )

        output[
            level_number
        ] = {
            "file":
                next(
                    iter(files)
                ),

            "sheet":
                next(
                    iter(sheets)
                ),
        }

    return output


# ============================================================
# HOUSEHOLD BASE
# ============================================================

def load_household_base():

    print(
        "\nLoading household base..."
    )

    if not HOUSEHOLD_BASE_FILE.exists():

        raise FileNotFoundError(
            f"Household base missing:\n"
            f"{HOUSEHOLD_BASE_FILE}"
        )

    base = pd.read_csv(
        HOUSEHOLD_BASE_FILE,
        dtype=str,
        low_memory=False
    )

    required = [
        "HHID",
        "State",
        "State_District",
        "District",
        "Sector",
        "Sector_Label",
        "MLT",
    ]

    missing = [
        column
        for column in required
        if column not in base.columns
    ]

    if missing:

        raise ValueError(
            "Household base missing columns: "
            +
            ", ".join(missing)
        )

    base[
        "HHID"
    ] = base[
        "HHID"
    ].map(
        normalize_integer_text
    )

    base[
        "Sector"
    ] = base[
        "Sector"
    ].map(
        normalize_integer_text
    )

    base[
        "MLT"
    ] = pd.to_numeric(
        base[
            "MLT"
        ],
        errors="coerce"
    )

    if base[
        "HHID"
    ].duplicated().any():

        raise ValueError(
            "Duplicate HHID in household base."
        )

    print(
        f"Households: {len(base):,}"
    )

    return base


# ============================================================
# RAW ASSET READER
# ============================================================

def load_component_raw(
    level_number,
    item_column,
    value_column,
    source_map
):

    source = source_map[
        level_number
    ]

    path = (
        RAW_DIR
        /
        source[
            "file"
        ]
    )

    print(
        f"\nReading Level "
        f"{level_number:02d}"
    )

    print(
        f"  {path.name}"
    )

    df = pd.read_excel(
        path,
        sheet_name=source[
            "sheet"
        ],
        usecols=[
            "HHID",
            item_column,
            value_column,
        ],
        dtype=str,
        engine="openpyxl"
    )

    df = df.dropna(
        how="all"
    ).copy()

    df[
        "HHID"
    ] = df[
        "HHID"
    ].map(
        normalize_integer_text
    )

    df[
        item_column
    ] = df[
        item_column
    ].map(
        normalize_item
    )

    df[
        value_column
    ] = pd.to_numeric(
        df[
            value_column
        ],
        errors="coerce"
    )

    return df


# ============================================================
# NORMAL TOTAL-ROW COMPONENTS
# ============================================================

def build_total_component(
    level_number,
    spec,
    source_map
):

    item_column = spec[
        "item_column"
    ]

    value_column = spec[
        "value_column"
    ]

    total_code = spec[
        "total_code"
    ]

    control_codes = spec[
        "control_codes"
    ]

    component_name = spec[
        "name"
    ]

    df = load_component_raw(
        level_number,
        item_column,
        value_column,
        source_map
    )

    raw_hhids = int(
        df[
            "HHID"
        ].nunique()
    )

    # --------------------------------------------------------
    # Provided household total
    # --------------------------------------------------------

    total_rows = df[
        df[
            item_column
        ]
        ==
        total_code
    ].copy()

    duplicate_total_hh = int(
        total_rows[
            "HHID"
        ]
        .duplicated()
        .sum()
    )

    if duplicate_total_hh != 0:

        raise ValueError(
            f"Level {level_number}: "
            f"duplicate total rows for "
            f"{duplicate_total_hh} HHID(s)."
        )

    provided = (
        total_rows[
            [
                "HHID",
                value_column,
            ]
        ]
        .rename(
            columns={
                value_column:
                    "Provided_Total"
            }
        )
    )

    # --------------------------------------------------------
    # Detail reconstruction fallback
    # --------------------------------------------------------

    detail = df[
        ~df[
            item_column
        ]
        .isin(
            control_codes
        )
    ].copy()

    detail_sum = (
        detail.groupby(
            "HHID",
            as_index=False
        )[
            value_column
        ]
        .sum(
            min_count=1
        )
        .rename(
            columns={
                value_column:
                    "Detail_Total"
            }
        )
    )

    result = provided.merge(
        detail_sum,
        on="HHID",
        how="outer"
    )

    result[
        component_name
    ] = result[
        "Provided_Total"
    ].where(
        result[
            "Provided_Total"
        ].notna(),
        result[
            "Detail_Total"
        ]
    )

    fallback_count = int(
        (
            result[
                "Provided_Total"
            ].isna()
            &
            result[
                "Detail_Total"
            ].notna()
        ).sum()
    )

    no_value_count = int(
        (
            result[
                "Provided_Total"
            ].isna()
            &
            result[
                "Detail_Total"
            ].isna()
        ).sum()
    )

    result[
        component_name
    ] = result[
        component_name
    ].fillna(
        0
    )

    negative_count = int(
        (
            result[
                component_name
            ]
            <
            0
        ).sum()
    )

    if negative_count:

        if level_number == 13:

            print(
                f"  WARNING negative values  : "
                f"{negative_count:,} "
                "(retained from source b11bq6)"
            )

        else:

            raise ValueError(
                f"{component_name}: "
                f"{negative_count} negative values."
            )

    print(
        f"  Component              : "
        f"{component_name}"
    )

    print(
        f"  Raw HHID               : "
        f"{raw_hhids:,}"
    )

    print(
        f"  Final-total HHID       : "
        f"{len(provided):,}"
    )

    print(
        f"  Detail fallback used   : "
        f"{fallback_count:,}"
    )

    print(
        f"  No usable value        : "
        f"{no_value_count:,}"
    )

    return (
        result[
            [
                "HHID",
                component_name,
            ]
        ],
        {
            "Level":
                level_number,

            "Component":
                component_name,

            "Raw_HHID":
                raw_hhids,

            "Final_Total_HHID":
                len(provided),

            "Detail_Fallback_Used":
                fallback_count,

            "No_Usable_Value":
                no_value_count,

            "Negative_HH_Value":
                negative_count,
        }
    )


# ============================================================
# LEVEL 12 - FINANCIAL ASSETS AS ON 30.06.2018
# ============================================================

def build_level12(
    source_map
):

    source = source_map[
        12
    ]

    path = (
        RAW_DIR
        /
        source[
            "file"
        ]
    )

    print(
        "\nReading Level 12"
    )

    print(
        f"  {path.name}"
    )

    df = pd.read_excel(
        path,
        sheet_name=source[
            "sheet"
        ],
        usecols=[
            "HHID",
            "b11aq1",

            # FIXED REFERENCE DATE
            "b11aq6",
        ],
        dtype=str,
        engine="openpyxl"
    )

    df = df.dropna(
        how="all"
    ).copy()

    df[
        "HHID"
    ] = df[
        "HHID"
    ].map(
        normalize_integer_text
    )

    df[
        "b11aq1"
    ] = df[
        "b11aq1"
    ].map(
        normalize_item
    )

    df[
        "b11aq6"
    ] = pd.to_numeric(
        df[
            "b11aq6"
        ],
        errors="coerce"
    )

    raw_hhids = int(
        df[
            "HHID"
        ].nunique()
    )

    # --------------------------------------------------------
    # Item 19 = total of items 1-18
    # --------------------------------------------------------

    provided_1_18 = (
        df[
            df[
                "b11aq1"
            ]
            ==
            "19"
        ][
            [
                "HHID",
                "b11aq6",
            ]
        ]
        .rename(
            columns={
                "b11aq6":
                    "Provided_1_18"
            }
        )
    )

    # --------------------------------------------------------
    # Detail fallback: items 1-18
    # --------------------------------------------------------

    codes_1_18 = {
        str(i)
        for i in range(
            1,
            19
        )
    }

    detail_1_18 = (
        df[
            df[
                "b11aq1"
            ].isin(
                codes_1_18
            )
        ]
        .groupby(
            "HHID",
            as_index=False
        )[
            "b11aq6"
        ]
        .sum(
            min_count=1
        )
        .rename(
            columns={
                "b11aq6":
                    "Detail_1_18"
            }
        )
    )

    # --------------------------------------------------------
    # Items 20 and 21 are explicitly OUTSIDE item 19 total.
    # They must therefore be added separately.
    # --------------------------------------------------------

    extra_20_21 = (
        df[
            df[
                "b11aq1"
            ].isin(
                {
                    "20",
                    "21",
                }
            )
        ]
        .groupby(
            "HHID",
            as_index=False
        )[
            "b11aq6"
        ]
        .sum(
            min_count=1
        )
        .rename(
            columns={
                "b11aq6":
                    "Extra_20_21"
            }
        )
    )

    # --------------------------------------------------------
    # Deposits = items 3-9
    # --------------------------------------------------------

    deposit_codes = {
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
    }

    deposits = (
        df[
            df[
                "b11aq1"
            ].isin(
                deposit_codes
            )
        ]
        .groupby(
            "HHID",
            as_index=False
        )[
            "b11aq6"
        ]
        .sum(
            min_count=1
        )
        .rename(
            columns={
                "b11aq6":
                    "Deposits_Value"
            }
        )
    )

    # --------------------------------------------------------
    # Create full Level-12 household list
    # --------------------------------------------------------

    result = (
        pd.DataFrame(
            {
                "HHID":
                    df[
                        "HHID"
                    ].drop_duplicates()
            }
        )
    )

    result = result.merge(
        provided_1_18,
        on="HHID",
        how="left"
    )

    result = result.merge(
        detail_1_18,
        on="HHID",
        how="left"
    )

    result = result.merge(
        extra_20_21,
        on="HHID",
        how="left"
    )

    result = result.merge(
        deposits,
        on="HHID",
        how="left"
    )

    # --------------------------------------------------------
    # Prefer supplied item-19 total.
    # If absent, reconstruct from items 1-18.
    # --------------------------------------------------------

    result[
        "Financial_1_18_Value"
    ] = result[
        "Provided_1_18"
    ].where(
        result[
            "Provided_1_18"
        ].notna(),
        result[
            "Detail_1_18"
        ]
    )

    fallback_count = int(
        (
            result[
                "Provided_1_18"
            ].isna()
            &
            result[
                "Detail_1_18"
            ].notna()
        ).sum()
    )

    # --------------------------------------------------------
    # Compare supplied total to reconstructed total where both
    # exist. This is an audit only; it does not change values.
    # --------------------------------------------------------

    comparable = (
        result[
            "Provided_1_18"
        ].notna()
        &
        result[
            "Detail_1_18"
        ].notna()
    )

    mismatch = int(
        (
            (
                result.loc[
                    comparable,
                    "Provided_1_18"
                ]
                -
                result.loc[
                    comparable,
                    "Detail_1_18"
                ]
            ).abs()
            >
            0.01
        ).sum()
    )

    for column in [
        "Financial_1_18_Value",
        "Extra_20_21",
        "Deposits_Value",
    ]:

        result[
            column
        ] = result[
            column
        ].fillna(
            0
        )

    result[
        "Financial_Excl_Shares_Value"
    ] = (
        result[
            "Financial_1_18_Value"
        ]
        +
        result[
            "Extra_20_21"
        ]
    )

    result[
        "Other_Financial_Excl_Shares_Value"
    ] = (
        result[
            "Financial_Excl_Shares_Value"
        ]
        -
        result[
            "Deposits_Value"
        ]
    )

    negative_count = int(
        (
            result[
                "Financial_Excl_Shares_Value"
            ]
            <
            0
        ).sum()
    )

    if negative_count:

        raise ValueError(
            "Negative household financial "
            "asset values detected."
        )

    print(
        "  Reference date          : "
        "30.06.2018"
    )

    print(
        "  Value field             : "
        "b11aq6"
    )

    print(
        f"  Raw HHID               : "
        f"{raw_hhids:,}"
    )

    print(
        f"  Item-19 total HHID     : "
        f"{len(provided_1_18):,}"
    )

    print(
        f"  Detail fallback used   : "
        f"{fallback_count:,}"
    )

    print(
        f"  Item19/detail mismatch : "
        f"{mismatch:,}"
    )

    return (
        result[
            [
                "HHID",
                "Deposits_Value",
                "Financial_Excl_Shares_Value",
                "Other_Financial_Excl_Shares_Value",
            ]
        ],
        {
            "Level": 12,
            "Component":
                "Financial_Excl_Shares_Value",
            "Raw_HHID":
                raw_hhids,
            "Final_Total_HHID":
                len(provided_1_18),
            "Detail_Fallback_Used":
                fallback_count,
            "No_Usable_Value":
                int(
                    (
                        result[
                            "Financial_Excl_Shares_Value"
                        ]
                        ==
                        0
                    ).sum()
                ),
            "Negative_HH_Value":
                negative_count,
            "Total_Detail_Mismatch":
                mismatch,
        }
    )


# ============================================================
# WEIGHTED AVERAGE
# ============================================================

def weighted_average(
    df,
    value_column
):

    valid = (
        df[
            "MLT"
        ].notna()
        &
        (
            df[
                "MLT"
            ]
            >=
            0
        )
    )

    denominator = (
        df.loc[
            valid,
            "MLT"
        ].sum()
    )

    numerator = (
        (
            df.loc[
                valid,
                value_column
            ]
            *
            df.loc[
                valid,
                "MLT"
            ]
        ).sum()
    )

    if denominator == 0:
        return np.nan

    return (
        numerator
        /
        denominator
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS NSS 77 - STEP 03B BUILD "
        "HOUSEHOLD ASSET FACTS - CORRECTED"
    )

    print(
        "=" * 78
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    base = load_household_base()

    base_ids = set(
        base[
            "HHID"
        ]
    )

    source_map = load_source_map()

    asset = base[
        [
            "HHID",
            "State",
            "State_District",
            "District",
            "Sector",
            "Sector_Label",
            "MLT",
        ]
    ].copy()

    reports = []

    # ========================================================
    # LEVELS 05-11
    # ========================================================

    for level_number in range(
        5,
        12
    ):

        component_df, report = (
            build_total_component(
                level_number,
                ASSET_SPECS[
                    level_number
                ],
                source_map
            )
        )

        unknown = (
            set(
                component_df[
                    "HHID"
                ]
            )
            -
            base_ids
        )

        if unknown:

            raise ValueError(
                f"Level {level_number}: "
                f"{len(unknown)} unknown HHIDs."
            )

        asset = asset.merge(
            component_df,
            on="HHID",
            how="left",
            validate="one_to_one"
        )

        component_name = (
            ASSET_SPECS[
                level_number
            ][
                "name"
            ]
        )

        asset[
            component_name
        ] = asset[
            component_name
        ].fillna(
            0
        )

        reports.append(
            report
        )

    # ========================================================
    # LEVEL 12
    # ========================================================

    level12_df, level12_report = (
        build_level12(
            source_map
        )
    )

    asset = asset.merge(
        level12_df,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    for column in [
        "Deposits_Value",
        "Financial_Excl_Shares_Value",
        "Other_Financial_Excl_Shares_Value",
    ]:

        asset[
            column
        ] = asset[
            column
        ].fillna(
            0
        )

    reports.append(
        level12_report
    )

    # ========================================================
    # LEVEL 13
    # b11bq6 = 30.06.2018
    # ========================================================

    level13_df, level13_report = (
        build_total_component(
            13,
            ASSET_SPECS[
                13
            ],
            source_map
        )
    )

    asset = asset.merge(
        level13_df,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    asset[
        "Shares_Investments_Value"
    ] = asset[
        "Shares_Investments_Value"
    ].fillna(
        0
    )

    reports.append(
        level13_report
    )

    # ========================================================
    # DERIVED COMPONENTS
    # ========================================================

    asset[
        "Land_Value"
    ] = (
        asset[
            "Rural_Land_Value"
        ]
        +
        asset[
            "Urban_Land_Value"
        ]
    )

    asset[
        "Physical_Asset_Value"
    ] = (
        asset[
            "Land_Value"
        ]
        +
        asset[
            "Building_Value"
        ]
        +
        asset[
            "Livestock_Value"
        ]
        +
        asset[
            "Transport_Value"
        ]
        +
        asset[
            "Agri_Machinery_Value"
        ]
        +
        asset[
            "NonFarm_Business_Value"
        ]
    )

    asset[
        "Financial_Asset_Value"
    ] = (
        asset[
            "Financial_Excl_Shares_Value"
        ]
        +
        asset[
            "Shares_Investments_Value"
        ]
    )

    asset[
        "Total_Asset_Value"
    ] = (
        asset[
            "Physical_Asset_Value"
        ]
        +
        asset[
            "Financial_Asset_Value"
        ]
    )

    # ========================================================
    # VALIDATION
    # ========================================================

    print(
        "\n" + "=" * 78
    )

    print(
        "HOUSEHOLD ASSET FACT VALIDATION"
    )

    print(
        "=" * 78
    )

    duplicate_hhid = int(
        asset[
            "HHID"
        ].duplicated().sum()
    )

    blank_hhid = int(
        asset[
            "HHID"
        ].eq("").sum()
    )

    negative_total = int(
        (
            asset[
                "Total_Asset_Value"
            ]
            <
            0
        ).sum()
    )

    zero_total_asset = int(
        (
            asset[
                "Total_Asset_Value"
            ]
            ==
            0
        ).sum()
    )

    arithmetic_error = int(
        (
            (
                asset[
                    "Total_Asset_Value"
                ]
                -
                (
                    asset[
                        "Physical_Asset_Value"
                    ]
                    +
                    asset[
                        "Financial_Asset_Value"
                    ]
                )
            ).abs()
            >
            0.01
        ).sum()
    )

    print(
        f"\nRows                     : "
        f"{len(asset):,}"
    )

    print(
        f"Unique HHID              : "
        f"{asset['HHID'].nunique():,}"
    )

    print(
        f"Duplicate HHID           : "
        f"{duplicate_hhid:,}"
    )

    print(
        f"Blank HHID               : "
        f"{blank_hhid:,}"
    )

    print(
        f"Negative total assets    : "
        f"{negative_total:,}"
    )

    print(
        f"Zero total assets        : "
        f"{zero_total_asset:,}"
    )

    print(
        f"Arithmetic errors        : "
        f"{arithmetic_error:,}"
    )

    if (
        duplicate_hhid
        or
        blank_hhid
        or
        negative_total
        or
        arithmetic_error
    ):

        raise ValueError(
            "Household asset validation failed."
        )

    # ========================================================
    # OFFICIAL CONTROL CHECKS
    # ========================================================

    all_india_ava = weighted_average(
        asset,
        "Total_Asset_Value"
    )

    rural = asset[
        asset[
            "Sector"
        ]
        ==
        "1"
    ].copy()

    urban = asset[
        asset[
            "Sector"
        ]
        ==
        "2"
    ].copy()

    rural_ava = weighted_average(
        rural,
        "Total_Asset_Value"
    )

    urban_ava = weighted_average(
        urban,
        "Total_Asset_Value"
    )

    rural_diff_pct = (
        (
            rural_ava
            -
            OFFICIAL_RURAL_AVA
        )
        /
        OFFICIAL_RURAL_AVA
        *
        100
    )

    urban_diff_pct = (
        (
            urban_ava
            -
            OFFICIAL_URBAN_AVA
        )
        /
        OFFICIAL_URBAN_AVA
        *
        100
    )

    print(
        "\n" + "=" * 78
    )

    print(
        "OFFICIAL AVA CONTROL CHECK"
    )

    print(
        "=" * 78
    )

    print(
        f"\nAll India calculated : "
        f"{all_india_ava:,.2f}"
    )

    print(
        f"\nRural calculated     : "
        f"{rural_ava:,.2f}"
    )

    print(
        f"Rural official       : "
        f"{OFFICIAL_RURAL_AVA:,.2f}"
    )

    print(
        f"Rural difference     : "
        f"{rural_diff_pct:.2f}%"
    )

    print(
        f"\nUrban calculated     : "
        f"{urban_ava:,.2f}"
    )

    print(
        f"Urban official       : "
        f"{OFFICIAL_URBAN_AVA:,.2f}"
    )

    print(
        f"Urban difference     : "
        f"{urban_diff_pct:.2f}%"
    )

    # ========================================================
    # SAVE
    # ========================================================

    output_columns = [
        "HHID",
        "State",
        "State_District",
        "District",
        "Sector",
        "Sector_Label",
        "MLT",

        "Rural_Land_Value",
        "Urban_Land_Value",
        "Land_Value",

        "Building_Value",
        "Livestock_Value",
        "Transport_Value",
        "Agri_Machinery_Value",
        "NonFarm_Business_Value",

        "Deposits_Value",
        "Financial_Excl_Shares_Value",
        "Other_Financial_Excl_Shares_Value",
        "Shares_Investments_Value",

        "Physical_Asset_Value",
        "Financial_Asset_Value",
        "Total_Asset_Value",
    ]

    asset[
        output_columns
    ].to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8",
        lineterminator="\n"
    )

    pd.DataFrame(
        reports
    ).to_csv(
        BUILD_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # POLICY REPORT
    # ========================================================

    policy_lines = [
        "=" * 78,
        "AIDIS NSS 77 - HOUSEHOLD ASSET CALCULATION POLICY",
        "=" * 78,
        "",
        "Official reference date: 30.06.2018",
        "Official published asset estimates use Visit 1.",
        "",
        "Levels 05-11:",
        "  Household asset values obtained from their respective",
        "  asset blocks using the supplied final-total rows,",
        "  with detail reconstruction only as fallback.",
        "",
        "Level 12:",
        "  b11aq6 used because it is value as on 30.06.2018.",
        "  Item 19 = total of items 1-18.",
        "  Items 20 and 21 are outside item 19 and are added separately.",
        "  Deposits = items 3-9 using b11aq6.",
        "",
        "Level 13:",
        "  b11bq6 used because it is value as on 30.06.2018.",
        "  Item 5 is the supplied total of items 1-4.",
        "",
        "Weights:",
        "  Asset records first collapsed to one row per household.",
        "  MLT applied only at the estimator/domain stage.",
        "",
        "AIDIS_Final_Client.csv is NOT used as a production input.",
        "=" * 78,
    ]

    POLICY_REPORT.write_text(
        "\n".join(
            policy_lines
        ),
        encoding="utf-8"
    )

    summary_lines = [
        "=" * 78,
        "AIDIS NSS 77 - CORRECTED HOUSEHOLD ASSET FACT BUILD",
        "=" * 78,
        "",
        f"Household rows             : {len(asset):,}",
        f"Unique HHID                : {asset['HHID'].nunique():,}",
        f"Duplicate HHID             : {duplicate_hhid:,}",
        f"Negative total assets      : {negative_total:,}",
        f"Zero total assets          : {zero_total_asset:,}",
        f"Arithmetic errors          : {arithmetic_error:,}",
        "",
        f"All India AVA              : {all_india_ava:,.2f}",
        f"Rural AVA calculated       : {rural_ava:,.2f}",
        f"Rural AVA official         : {OFFICIAL_RURAL_AVA:,.2f}",
        f"Urban AVA calculated       : {urban_ava:,.2f}",
        f"Urban AVA official         : {OFFICIAL_URBAN_AVA:,.2f}",
        "",
        "Reference date             : 30.06.2018",
        "HOUSEHOLD ASSET FACT STATUS: PASS",
        "=" * 78,
    ]

    SUMMARY_REPORT.write_text(
        "\n".join(
            summary_lines
        ),
        encoding="utf-8"
    )

    print(
        "\n" + "\n".join(
            summary_lines
        )
    )

    print(
        "\nCreated:"
    )

    print(
        OUTPUT_FILE
    )

    print(
        BUILD_REPORT
    )

    print(
        POLICY_REPORT
    )

    print(
        SUMMARY_REPORT
    )

    print(
        "\nSTEP 03B STATUS: PASS"
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            "\n" + "=" * 78
        )

        print(
            "STEP 03B HOUSEHOLD ASSET BUILD: FAIL"
        )

        print(
            "=" * 78
        )

        print(
            f"\n{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)