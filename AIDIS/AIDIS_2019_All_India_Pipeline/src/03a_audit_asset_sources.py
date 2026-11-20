from pathlib import Path
import re
import sys

import pandas as pd
from openpyxl import load_workbook


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

HOUSEHOLD_BASE_FILE = (
    PROJECT_ROOT
    / "cache"
    / "household_base_visit1.csv"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

SUMMARY_CSV = (
    REPORT_DIR
    / "asset_source_audit_summary.csv"
)

TOTAL_CHECK_REPORT = (
    REPORT_DIR
    / "asset_total_detail_check.csv"
)

NEGATIVE_VALUE_REPORT = (
    REPORT_DIR
    / "asset_negative_values.csv"
)

UNMATCHED_HHID_REPORT = (
    REPORT_DIR
    / "asset_unmatched_hhids.csv"
)

SUMMARY_TXT = (
    REPORT_DIR
    / "asset_source_audit_summary.txt"
)


# ============================================================
# DDI SETTINGS
# ============================================================

MASTER_DDI_SHEET = "Master_DDI_AIDIS_77th_Round"

VISIT = "Visit 1"


# ============================================================
# ASSET LEVEL CONFIGURATION
# ============================================================
#
# control_codes:
#   rows that are subtotal / total rows and must NOT be summed
#   again when we eventually calculate household asset totals.
#
# final_total_code:
#   the final total row that can be compared against detail rows.
#
# total_detail_codes:
#   exact item rows expected to form the final total.
#
# Level 12 is special:
#   item 19 is total of items 1-18.
#   items 20-21 are outside that total.
# ============================================================

ASSET_SPECS = {
    5: {
        "asset_name": "Rural Land",
        "item_column": "b5pt1q1",
        "value_column": "b5pt1q5",
        "control_codes": set(),
        "final_total_code": None,
        "total_detail_codes": None,
    },

    6: {
        "asset_name": "Urban Land",
        "item_column": "b5pt2q1",
        "value_column": "b5pt2q5",
        "control_codes": set(),
        "final_total_code": None,
        "total_detail_codes": None,
    },

    7: {
        "asset_name": "Buildings",
        "item_column": "b6q3",
        "value_column": "b6q5",
        "control_codes": {"10"},
        "final_total_code": "10",
        "total_detail_codes": {
            str(i)
            for i in range(1, 10)
        },
    },

    8: {
        "asset_name": "Livestock and Poultry",
        "item_column": "b7q2",
        "value_column": "b7q4",
        "control_codes": {"13", "17"},
        "final_total_code": "17",
        "total_detail_codes": {
            *[
                str(i)
                for i in range(1, 13)
            ],
            "14",
            "15",
            "16",
        },
    },

    9: {
        "asset_name": "Transport Equipment",
        "item_column": "b8q2",
        "value_column": "b8q4",
        "control_codes": {"8"},
        "final_total_code": "8",
        "total_detail_codes": {
            str(i)
            for i in range(1, 8)
        },
    },

    10: {
        "asset_name": "Agricultural Machinery",
        "item_column": "b9q2",
        "value_column": "b9q4",
        "control_codes": {"13"},
        "final_total_code": "13",
        "total_detail_codes": {
            str(i)
            for i in range(1, 13)
        },
    },

    11: {
        "asset_name": "Non-farm Business Equipment",
        "item_column": "b10q2",
        "value_column": "b10q3",
        "control_codes": {"15", "20"},
        "final_total_code": "20",
        "total_detail_codes": {
            *[
                str(i)
                for i in range(1, 15)
            ],
            "16",
            "17",
            "18",
            "19",
        },
    },

    12: {
        "asset_name": "Financial Assets excluding Shares",
        "item_column": "b11aq1",
        "value_column": "b11aq3",
        "control_codes": {"19"},
        "final_total_code": "19",
        "total_detail_codes": {
            str(i)
            for i in range(1, 19)
        },
    },

    13: {
        "asset_name": "Shares and Investments",
        "item_column": "b11bq1",
        "value_column": "b11bq3",
        "control_codes": {"5"},
        "final_total_code": "5",
        "total_detail_codes": {
            str(i)
            for i in range(1, 5)
        },
    },
}


# ============================================================
# COMMON RAW COLUMNS
# ============================================================

COMMON_COLUMNS = [
    "HHID",
    "Sector",
    "NSS_Region",
    "State",
    "State_District",
    "District",
    "MLT",
]


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    if pd.isna(value):
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
    """
    Convert:
        1.0   -> 1
        27.0  -> 27

    while preserving normal text.
    """

    value = clean_text(value)

    if not value:
        return ""

    if re.fullmatch(
        r"[+-]?\d+\.0+",
        value
    ):
        return value.split(".")[0]

    return value


def normalize_code(
    value,
    width
):
    value = normalize_integer_text(
        value
    )

    if not value:
        return ""

    return value.zfill(
        width
    )


def normalize_item_code(value):
    """
    Normalizes item codes such as:
        10.0 -> 10
        05   -> 5
    """

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


def numeric_series(series):
    return pd.to_numeric(
        series.apply(
            clean_text
        ),
        errors="coerce"
    )


def almost_equal(
    left,
    right,
    tolerance=0.01
):
    return abs(
        float(left)
        -
        float(right)
    ) <= tolerance


# ============================================================
# DDI SOURCE RESOLUTION
# ============================================================

def get_source_from_ddi(level_number):
    """
    Finds the authoritative Source_File and Source_Sheet
    for Visit 1 + requested Level directly from Master DDI.
    """

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

    expected_level = (
        f"Level {level_number}"
    )

    source_files = set()
    source_sheets = set()
    ddi_columns = set()

    for row in rows:

        visit = clean_text(
            row[
                index["Visit"]
            ]
        )

        level = clean_text(
            row[
                index["Level"]
            ]
        )

        if (
            visit != VISIT
            or
            level != expected_level
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

        column = clean_text(
            row[
                index[
                    "Original_Column_Name"
                ]
            ]
        )

        if source_file:
            source_files.add(
                source_file
            )

        if source_sheet:
            source_sheets.add(
                source_sheet
            )

        if column:
            ddi_columns.add(
                column
            )

    workbook.close()

    if len(source_files) != 1:
        raise ValueError(
            f"Visit 1 Level {level_number}: "
            f"expected exactly one source file. "
            f"Found: {sorted(source_files)}"
        )

    if len(source_sheets) != 1:
        raise ValueError(
            f"Visit 1 Level {level_number}: "
            f"expected exactly one source sheet. "
            f"Found: {sorted(source_sheets)}"
        )

    return (
        next(iter(source_files)),
        next(iter(source_sheets)),
        ddi_columns,
    )


# ============================================================
# LOAD HOUSEHOLD BASE
# ============================================================

def load_household_base():

    if not HOUSEHOLD_BASE_FILE.exists():

        raise FileNotFoundError(
            "\nHousehold base not found:\n"
            f"{HOUSEHOLD_BASE_FILE}\n\n"
            "Run 02_build_household_base.py first."
        )

    print(
        "\nReading household base:"
    )

    print(
        HOUSEHOLD_BASE_FILE
    )

    base = pd.read_csv(
        HOUSEHOLD_BASE_FILE,
        dtype=str,
        low_memory=False
    )

    required = [
        "HHID",
        "Sector",
        "NSS_Region",
        "State",
        "State_District",
        "District",
        "MLT",
    ]

    missing = [
        column
        for column in required
        if column not in base.columns
    ]

    if missing:

        raise ValueError(
            "Household base missing columns:\n"
            +
            "\n".join(
                f"  - {column}"
                for column in missing
            )
        )

    base = base[
        required
    ].copy()

    base[
        "HHID"
    ] = base[
        "HHID"
    ].apply(
        normalize_integer_text
    )

    base[
        "State"
    ] = base[
        "State"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    base[
        "District"
    ] = base[
        "District"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    base[
        "State_District"
    ] = base[
        "State_District"
    ].apply(
        lambda value:
        normalize_code(
            value,
            4
        )
    )

    for column in [
        "Sector",
        "NSS_Region",
    ]:

        base[
            column
        ] = base[
            column
        ].apply(
            normalize_integer_text
        )

    base[
        "MLT"
    ] = numeric_series(
        base[
            "MLT"
        ]
    )

    duplicates = int(
        base[
            "HHID"
        ]
        .duplicated()
        .sum()
    )

    blank_hhid = int(
        base[
            "HHID"
        ]
        .eq("")
        .sum()
    )

    print(
        f"\nHousehold rows     : "
        f"{len(base):,}"
    )

    print(
        f"Unique HHID        : "
        f"{base['HHID'].nunique():,}"
    )

    print(
        f"Duplicate HHID     : "
        f"{duplicates:,}"
    )

    print(
        f"Blank HHID         : "
        f"{blank_hhid:,}"
    )

    if duplicates != 0:

        raise ValueError(
            "Household base contains duplicate HHID."
        )

    if blank_hhid != 0:

        raise ValueError(
            "Household base contains blank HHID."
        )

    return base


# ============================================================
# LOAD ASSET LEVEL
# ============================================================

def load_asset_level(
    level_number,
    spec
):

    (
        source_file,
        source_sheet,
        ddi_columns,
    ) = get_source_from_ddi(
        level_number
    )

    path = (
        RAW_DIR
        /
        source_file
    )

    if not path.exists():

        raise FileNotFoundError(
            f"Raw source file missing:\n"
            f"{path}"
        )

    required_columns = (
        COMMON_COLUMNS
        +
        [
            spec[
                "item_column"
            ],
            spec[
                "value_column"
            ],
        ]
    )

    # --------------------------------------------------------
    # Confirm required variables exist in DDI
    # --------------------------------------------------------

    missing_from_ddi = [
        column
        for column in required_columns
        if column not in ddi_columns
    ]

    if missing_from_ddi:

        raise ValueError(
            f"Level {level_number}: "
            "required variables missing from DDI:\n"
            +
            "\n".join(
                f"  - {column}"
                for column in missing_from_ddi
            )
        )

    print(
        f"\nReading Level {level_number:02d}:"
    )

    print(
        f"  Asset : "
        f"{spec['asset_name']}"
    )

    print(
        f"  File  : "
        f"{source_file}"
    )

    print(
        f"  Sheet : "
        f"{source_sheet}"
    )

    df = pd.read_excel(
        path,
        sheet_name=source_sheet,
        dtype=str,
        engine="openpyxl"
    )

    df = df.dropna(
        how="all"
    ).copy()

    df.columns = [
        clean_text(column)
        for column in df.columns
    ]

    missing_raw_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_raw_columns:

        raise ValueError(
            f"Level {level_number}: "
            "required raw columns missing:\n"
            +
            "\n".join(
                f"  - {column}"
                for column in missing_raw_columns
            )
        )

    df = df[
        required_columns
    ].copy()

    return (
        df,
        source_file,
        source_sheet,
    )


# ============================================================
# NORMALIZE ASSET LEVEL
# ============================================================

def normalize_asset_level(
    df,
    spec
):

    for column in df.columns:

        df[
            column
        ] = df[
            column
        ].apply(
            clean_text
        )

    df[
        "HHID"
    ] = df[
        "HHID"
    ].apply(
        normalize_integer_text
    )

    df[
        "State"
    ] = df[
        "State"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    df[
        "District"
    ] = df[
        "District"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    df[
        "State_District"
    ] = df[
        "State_District"
    ].apply(
        lambda value:
        normalize_code(
            value,
            4
        )
    )

    for column in [
        "Sector",
        "NSS_Region",
    ]:

        df[
            column
        ] = df[
            column
        ].apply(
            normalize_integer_text
        )

    item_column = spec[
        "item_column"
    ]

    value_column = spec[
        "value_column"
    ]

    df[
        item_column
    ] = df[
        item_column
    ].apply(
        normalize_item_code
    )

    # Keep original text so we can differentiate
    # blank versus invalid non-numeric values.

    df[
        "_Value_Text"
    ] = df[
        value_column
    ].apply(
        clean_text
    )

    df[
        "_Asset_Value"
    ] = pd.to_numeric(
        df[
            "_Value_Text"
        ],
        errors="coerce"
    )

    df[
        "MLT"
    ] = pd.to_numeric(
        df[
            "MLT"
        ],
        errors="coerce"
    )

    return df


# ============================================================
# CHECK AGAINST HOUSEHOLD BASE
# ============================================================

def validate_against_base(
    level_number,
    df,
    base
):

    raw_ids = set(
        df[
            "HHID"
        ]
    )

    base_ids = set(
        base[
            "HHID"
        ]
    )

    unmatched = sorted(
        raw_ids
        -
        base_ids
    )

    base_without_records = (
        base_ids
        -
        raw_ids
    )

    base_for_merge = (
        base[
            [
                "HHID",
                "Sector",
                "NSS_Region",
                "State",
                "State_District",
                "District",
                "MLT",
            ]
        ]
        .copy()
    )

    merged = df.merge(
        base_for_merge,
        on="HHID",
        how="left",
        suffixes=(
            "_RAW",
            "_BASE"
        ),
        validate="many_to_one"
    )

    mismatch_counts = {}

    for column in [
        "Sector",
        "NSS_Region",
        "State",
        "State_District",
        "District",
    ]:

        raw_col = (
            f"{column}_RAW"
        )

        base_col = (
            f"{column}_BASE"
        )

        mismatch = (
            merged[
                base_col
            ].notna()
            &
            (
                merged[
                    raw_col
                ]
                !=
                merged[
                    base_col
                ]
            )
        )

        mismatch_counts[
            column
        ] = int(
            mismatch.sum()
        )

    # --------------------------------------------------------
    # MLT numeric comparison
    # --------------------------------------------------------

    both_mlt = (
        merged[
            "MLT_RAW"
        ].notna()
        &
        merged[
            "MLT_BASE"
        ].notna()
    )

    mlt_difference = (
        merged.loc[
            both_mlt,
            "MLT_RAW"
        ]
        -
        merged.loc[
            both_mlt,
            "MLT_BASE"
        ]
    ).abs()

    mlt_mismatch = int(
        (
            mlt_difference
            >
            0.0000001
        ).sum()
    )

    return (
        unmatched,
        base_without_records,
        mismatch_counts,
        mlt_mismatch,
    )


# ============================================================
# TOTAL / DETAIL CHECK
# ============================================================

def check_total_rows(
    level_number,
    df,
    spec
):

    final_total_code = spec[
        "final_total_code"
    ]

    detail_codes = spec[
        "total_detail_codes"
    ]

    item_column = spec[
        "item_column"
    ]

    if (
        final_total_code is None
        or
        detail_codes is None
    ):

        return {
            "total_rows": 0,
            "households_checked": 0,
            "households_matched": 0,
            "households_mismatched": 0,
            "detail_rows": [],
        }

    # --------------------------------------------------------
    # Final total rows
    # --------------------------------------------------------

    total_rows = df[
        df[
            item_column
        ]
        ==
        final_total_code
    ].copy()

    # --------------------------------------------------------
    # Detail rows that should form that total
    # --------------------------------------------------------

    detail_rows = df[
        df[
            item_column
        ]
        .isin(
            detail_codes
        )
    ].copy()

    # --------------------------------------------------------
    # Sum detail by household
    # --------------------------------------------------------

    detail_by_hh = (
        detail_rows
        .groupby(
            "HHID",
            as_index=False
        )[
            "_Asset_Value"
        ]
        .sum(
            min_count=1
        )
        .rename(
            columns={
                "_Asset_Value":
                    "Detail_Sum"
            }
        )
    )

    # --------------------------------------------------------
    # Sum total rows by household
    #
    # Normally one total row should occur. Summing here
    # still allows us to audit duplicates cleanly.
    # --------------------------------------------------------

    total_by_hh = (
        total_rows
        .groupby(
            "HHID",
            as_index=False
        )[
            "_Asset_Value"
        ]
        .sum(
            min_count=1
        )
        .rename(
            columns={
                "_Asset_Value":
                    "Provided_Total"
            }
        )
    )

    comparison = total_by_hh.merge(
        detail_by_hh,
        on="HHID",
        how="left"
    )

    comparison[
        "Detail_Sum"
    ] = comparison[
        "Detail_Sum"
    ].fillna(
        0
    )

    comparison[
        "Provided_Total"
    ] = comparison[
        "Provided_Total"
    ].fillna(
        0
    )

    comparison[
        "Difference"
    ] = (
        comparison[
            "Provided_Total"
        ]
        -
        comparison[
            "Detail_Sum"
        ]
    )

    comparison[
        "Match"
    ] = (
        comparison[
            "Difference"
        ]
        .abs()
        <=
        0.01
    )

    mismatches = comparison[
        ~comparison[
            "Match"
        ]
    ].copy()

    mismatch_rows = []

    for _, row in mismatches.iterrows():

        mismatch_rows.append(
            {
                "Level":
                    level_number,

                "Asset_Component":
                    spec[
                        "asset_name"
                    ],

                "HHID":
                    row[
                        "HHID"
                    ],

                "Final_Total_Code":
                    final_total_code,

                "Provided_Total":
                    row[
                        "Provided_Total"
                    ],

                "Calculated_Detail_Sum":
                    row[
                        "Detail_Sum"
                    ],

                "Difference":
                    row[
                        "Difference"
                    ],

                "Status":
                    "MISMATCH",
            }
        )

    return {
        "total_rows":
            len(
                total_rows
            ),

        "households_checked":
            len(
                comparison
            ),

        "households_matched":
            int(
                comparison[
                    "Match"
                ].sum()
            ),

        "households_mismatched":
            len(
                mismatches
            ),

        "detail_rows":
            mismatch_rows,
    }


# ============================================================
# AUDIT ONE ASSET LEVEL
# ============================================================

def audit_asset_level(
    level_number,
    spec,
    base
):

    (
        df,
        source_file,
        source_sheet,
    ) = load_asset_level(
        level_number,
        spec
    )

    df = normalize_asset_level(
        df,
        spec
    )

    item_column = spec[
        "item_column"
    ]

    value_column = spec[
        "value_column"
    ]

    # --------------------------------------------------------
    # Basic raw checks
    # --------------------------------------------------------

    raw_rows = len(
        df
    )

    unique_hhids = int(
        df[
            "HHID"
        ]
        .nunique()
    )

    blank_hhid = int(
        df[
            "HHID"
        ]
        .eq("")
        .sum()
    )

    blank_item = int(
        df[
            item_column
        ]
        .eq("")
        .sum()
    )

    blank_value = int(
        df[
            "_Value_Text"
        ]
        .eq("")
        .sum()
    )

    # Non-empty text that could not be parsed numerically.
    nonnumeric_value = int(
        (
            df[
                "_Value_Text"
            ]
            .ne("")
            &
            df[
                "_Asset_Value"
            ]
            .isna()
        ).sum()
    )

    negative_value = int(
        (
            df[
                "_Asset_Value"
            ]
            <
            0
        ).sum()
    )

    zero_value = int(
        (
            df[
                "_Asset_Value"
            ]
            ==
            0
        ).sum()
    )

    blank_mlt = int(
        df[
            "MLT"
        ]
        .isna()
        .sum()
    )

    negative_mlt = int(
        (
            df[
                "MLT"
            ]
            <
            0
        ).sum()
    )

    zero_mlt = int(
        (
            df[
                "MLT"
            ]
            ==
            0
        ).sum()
    )

    # --------------------------------------------------------
    # Household base linkage
    # --------------------------------------------------------

    (
        unmatched_hhids,
        base_without_records,
        geography_mismatches,
        mlt_mismatch,
    ) = validate_against_base(
        level_number,
        df,
        base
    )

    # --------------------------------------------------------
    # Total/subtotal controls
    # --------------------------------------------------------

    control_rows = int(
        df[
            item_column
        ]
        .isin(
            spec[
                "control_codes"
            ]
        )
        .sum()
    )

    total_check = check_total_rows(
        level_number,
        df,
        spec
    )

    # --------------------------------------------------------
    # Determine structural failure
    # --------------------------------------------------------

    structural_failures = (
        blank_hhid
        +
        nonnumeric_value
        +
        blank_mlt
        +
        negative_mlt
        +
        len(
            unmatched_hhids
        )
        +
        geography_mismatches[
            "Sector"
        ]
        +
        geography_mismatches[
            "NSS_Region"
        ]
        +
        geography_mismatches[
            "State"
        ]
        +
        geography_mismatches[
            "State_District"
        ]
        +
        geography_mismatches[
            "District"
        ]
        +
        mlt_mismatch
    )

    review_count = (
        blank_item
        +
        blank_value
        +
        negative_value
        +
        total_check[
            "households_mismatched"
        ]
    )

    if structural_failures > 0:

        status = "FAIL"

    elif review_count > 0:

        status = "REVIEW"

    else:

        status = "PASS"

    # --------------------------------------------------------
    # Console report
    # --------------------------------------------------------

    print(
        f"\nLevel {level_number:02d} - "
        f"{spec['asset_name']}"
    )

    print(
        "-" * 78
    )

    print(
        f"Raw rows                       : "
        f"{raw_rows:,}"
    )

    print(
        f"Unique HHID                    : "
        f"{unique_hhids:,}"
    )

    print(
        f"Base HH without level records  : "
        f"{len(base_without_records):,}"
    )

    print(
        f"Blank HHID                     : "
        f"{blank_hhid:,}"
    )

    print(
        f"Unmatched HHID                 : "
        f"{len(unmatched_hhids):,}"
    )

    print(
        f"Blank item code                : "
        f"{blank_item:,}"
    )

    print(
        f"Blank asset value              : "
        f"{blank_value:,}"
    )

    print(
        f"Non-numeric asset value        : "
        f"{nonnumeric_value:,}"
    )

    print(
        f"Negative asset value           : "
        f"{negative_value:,}"
    )

    print(
        f"Zero asset value               : "
        f"{zero_value:,}"
    )

    print(
        f"Zero MLT rows                  : "
        f"{zero_mlt:,}"
    )

    print(
        f"Negative MLT rows              : "
        f"{negative_mlt:,}"
    )

    print(
        f"Geography mismatches           : "
        f"{sum(geography_mismatches.values()):,}"
    )

    print(
        f"MLT mismatches                 : "
        f"{mlt_mismatch:,}"
    )

    print(
        f"Subtotal/total control rows    : "
        f"{control_rows:,}"
    )

    if (
        spec[
            "final_total_code"
        ]
        is not None
    ):

        print(
            f"Total HH checked               : "
            f"{total_check['households_checked']:,}"
        )

        print(
            f"Total/detail mismatches        : "
            f"{total_check['households_mismatched']:,}"
        )

    else:

        print(
            "Total/detail check             : "
            "Not applicable"
        )

    print(
        f"LEVEL STATUS                   : "
        f"{status}"
    )

    # --------------------------------------------------------
    # Negative-value detail rows
    # --------------------------------------------------------

    negative_rows = []

    negative_df = df[
        df[
            "_Asset_Value"
        ]
        <
        0
    ]

    for _, row in negative_df.iterrows():

        negative_rows.append(
            {
                "Level":
                    level_number,

                "Asset_Component":
                    spec[
                        "asset_name"
                    ],

                "HHID":
                    row[
                        "HHID"
                    ],

                "Item_Column":
                    item_column,

                "Item_Code":
                    row[
                        item_column
                    ],

                "Value_Column":
                    value_column,

                "Asset_Value":
                    row[
                        "_Asset_Value"
                    ],
            }
        )

    # --------------------------------------------------------
    # Unmatched HHID detail rows
    # --------------------------------------------------------

    unmatched_rows = [
        {
            "Level":
                level_number,

            "Asset_Component":
                spec[
                    "asset_name"
                ],

            "HHID":
                hhid,
        }
        for hhid
        in unmatched_hhids
    ]

    summary = {
        "Level":
            level_number,

        "Asset_Component":
            spec[
                "asset_name"
            ],

        "Source_File":
            source_file,

        "Source_Sheet":
            source_sheet,

        "Item_Column":
            item_column,

        "Value_Column":
            value_column,

        "Raw_Rows":
            raw_rows,

        "Unique_HHID":
            unique_hhids,

        "Base_HH_Without_Level_Record":
            len(
                base_without_records
            ),

        "Blank_HHID":
            blank_hhid,

        "Unmatched_HHID":
            len(
                unmatched_hhids
            ),

        "Blank_Item_Code":
            blank_item,

        "Blank_Asset_Value":
            blank_value,

        "NonNumeric_Asset_Value":
            nonnumeric_value,

        "Negative_Asset_Value":
            negative_value,

        "Zero_Asset_Value":
            zero_value,

        "Zero_MLT_Rows":
            zero_mlt,

        "Negative_MLT_Rows":
            negative_mlt,

        "Sector_Mismatch":
            geography_mismatches[
                "Sector"
            ],

        "NSS_Region_Mismatch":
            geography_mismatches[
                "NSS_Region"
            ],

        "State_Mismatch":
            geography_mismatches[
                "State"
            ],

        "State_District_Mismatch":
            geography_mismatches[
                "State_District"
            ],

        "District_Mismatch":
            geography_mismatches[
                "District"
            ],

        "MLT_Mismatch":
            mlt_mismatch,

        "Control_Rows":
            control_rows,

        "Total_HH_Checked":
            total_check[
                "households_checked"
            ],

        "Total_HH_Mismatched":
            total_check[
                "households_mismatched"
            ],

        "Status":
            status,
    }

    return (
        summary,
        total_check[
            "detail_rows"
        ],
        negative_rows,
        unmatched_rows,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS NSS 77 - STEP 03A ASSET SOURCE AUDIT"
    )

    print(
        "=" * 78
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Required input validation
    # --------------------------------------------------------

    if not RAW_DIR.exists():

        raise FileNotFoundError(
            f"Raw directory missing:\n"
            f"{RAW_DIR}"
        )

    if not DDI_FILE.exists():

        raise FileNotFoundError(
            f"Master DDI missing:\n"
            f"{DDI_FILE}"
        )

    # --------------------------------------------------------
    # Household base
    # --------------------------------------------------------

    base = load_household_base()

    # --------------------------------------------------------
    # Audit all asset levels
    # --------------------------------------------------------

    summaries = []

    total_mismatch_rows = []

    negative_rows = []

    unmatched_rows = []

    print(
        "\n" + "=" * 78
    )

    print(
        "AUDITING VISIT 1 ASSET LEVELS 05-13"
    )

    print(
        "=" * 78
    )

    for level_number in range(
        5,
        14
    ):

        spec = ASSET_SPECS[
            level_number
        ]

        (
            summary,
            level_total_mismatches,
            level_negative_rows,
            level_unmatched_rows,
        ) = audit_asset_level(
            level_number,
            spec,
            base
        )

        summaries.append(
            summary
        )

        total_mismatch_rows.extend(
            level_total_mismatches
        )

        negative_rows.extend(
            level_negative_rows
        )

        unmatched_rows.extend(
            level_unmatched_rows
        )

    # --------------------------------------------------------
    # Write reports
    # --------------------------------------------------------

    summary_df = pd.DataFrame(
        summaries
    )

    summary_df.to_csv(
        SUMMARY_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    total_columns = [
        "Level",
        "Asset_Component",
        "HHID",
        "Final_Total_Code",
        "Provided_Total",
        "Calculated_Detail_Sum",
        "Difference",
        "Status",
    ]

    pd.DataFrame(
        total_mismatch_rows,
        columns=total_columns
    ).to_csv(
        TOTAL_CHECK_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    negative_columns = [
        "Level",
        "Asset_Component",
        "HHID",
        "Item_Column",
        "Item_Code",
        "Value_Column",
        "Asset_Value",
    ]

    pd.DataFrame(
        negative_rows,
        columns=negative_columns
    ).to_csv(
        NEGATIVE_VALUE_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    unmatched_columns = [
        "Level",
        "Asset_Component",
        "HHID",
    ]

    pd.DataFrame(
        unmatched_rows,
        columns=unmatched_columns
    ).to_csv(
        UNMATCHED_HHID_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # Final status
    # --------------------------------------------------------

    pass_count = int(
        (
            summary_df[
                "Status"
            ]
            ==
            "PASS"
        ).sum()
    )

    review_count = int(
        (
            summary_df[
                "Status"
            ]
            ==
            "REVIEW"
        ).sum()
    )

    fail_count = int(
        (
            summary_df[
                "Status"
            ]
            ==
            "FAIL"
        ).sum()
    )

    total_raw_rows = int(
        summary_df[
            "Raw_Rows"
        ].sum()
    )

    total_unmatched = int(
        summary_df[
            "Unmatched_HHID"
        ].sum()
    )

    total_geo_mismatch = int(
        summary_df[
            [
                "Sector_Mismatch",
                "NSS_Region_Mismatch",
                "State_Mismatch",
                "State_District_Mismatch",
                "District_Mismatch",
            ]
        ]
        .sum()
        .sum()
    )

    total_mlt_mismatch = int(
        summary_df[
            "MLT_Mismatch"
        ].sum()
    )

    total_nonnumeric = int(
        summary_df[
            "NonNumeric_Asset_Value"
        ].sum()
    )

    total_negative = int(
        summary_df[
            "Negative_Asset_Value"
        ].sum()
    )

    total_detail_mismatch = int(
        summary_df[
            "Total_HH_Mismatched"
        ].sum()
    )

    if fail_count > 0:

        overall_status = "FAIL"

    elif review_count > 0:

        overall_status = "REVIEW"

    else:

        overall_status = "PASS"

    # --------------------------------------------------------
    # Terminal summary
    # --------------------------------------------------------

    print(
        "\n" + "=" * 78
    )

    print(
        "STEP 03A ASSET AUDIT SUMMARY"
    )

    print(
        "=" * 78
    )

    print(
        f"\nAsset levels audited          : "
        f"{len(summary_df)}"
    )

    print(
        f"PASS levels                   : "
        f"{pass_count}"
    )

    print(
        f"REVIEW levels                 : "
        f"{review_count}"
    )

    print(
        f"FAIL levels                   : "
        f"{fail_count}"
    )

    print(
        f"\nTotal raw asset rows          : "
        f"{total_raw_rows:,}"
    )

    print(
        f"Unmatched asset HHID          : "
        f"{total_unmatched:,}"
    )

    print(
        f"Geography mismatches          : "
        f"{total_geo_mismatch:,}"
    )

    print(
        f"MLT mismatches                : "
        f"{total_mlt_mismatch:,}"
    )

    print(
        f"Non-numeric asset values      : "
        f"{total_nonnumeric:,}"
    )

    print(
        f"Negative asset values         : "
        f"{total_negative:,}"
    )

    print(
        f"Total/detail HH mismatches    : "
        f"{total_detail_mismatch:,}"
    )

    print(
        f"\nSTEP 03A STATUS               : "
        f"{overall_status}"
    )

    # --------------------------------------------------------
    # Text summary
    # --------------------------------------------------------

    lines = [
        "=" * 78,
        "AIDIS NSS 77 - STEP 03A ASSET SOURCE AUDIT SUMMARY",
        "=" * 78,
        "",
        f"Household base rows           : {len(base):,}",
        f"Household base unique HHID    : {base['HHID'].nunique():,}",
        "",
        f"Asset levels audited          : {len(summary_df)}",
        f"PASS levels                   : {pass_count}",
        f"REVIEW levels                 : {review_count}",
        f"FAIL levels                   : {fail_count}",
        "",
        f"Total raw asset rows          : {total_raw_rows:,}",
        f"Unmatched asset HHID          : {total_unmatched:,}",
        f"Geography mismatches          : {total_geo_mismatch:,}",
        f"MLT mismatches                : {total_mlt_mismatch:,}",
        f"Non-numeric asset values      : {total_nonnumeric:,}",
        f"Negative asset values         : {total_negative:,}",
        f"Total/detail HH mismatches    : {total_detail_mismatch:,}",
        "",
        "Interpretation:",
        "PASS   = structural checks and value controls passed.",
        "REVIEW = structure is usable, but one or more asset-value",
        "         or total/detail conditions require inspection.",
        "FAIL   = structural linkage/mapping problem; do not continue.",
        "",
        f"STEP 03A STATUS               : {overall_status}",
        "=" * 78,
    ]

    SUMMARY_TXT.write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Report locations
    # --------------------------------------------------------

    print(
        "\nReports created:"
    )

    print(
        SUMMARY_CSV
    )

    print(
        TOTAL_CHECK_REPORT
    )

    print(
        NEGATIVE_VALUE_REPORT
    )

    print(
        UNMATCHED_HHID_REPORT
    )

    print(
        SUMMARY_TXT
    )

    print(
        "\nIMPORTANT:"
    )

    print(
        "No AVA or household asset total has been calculated yet."
    )

    print(
        "This step only validates whether Levels 05-13 "
        "are safe to aggregate."
    )

    # --------------------------------------------------------
    # Only structural FAIL should terminate as an error.
    #
    # REVIEW intentionally returns normally so we can inspect
    # the generated reports before Step 03B.
    # --------------------------------------------------------

    if overall_status == "FAIL":

        sys.exit(1)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            "\n" + "=" * 78
        )

        print(
            "STEP 03A ASSET SOURCE AUDIT: FAIL"
        )

        print(
            "=" * 78
        )

        print(
            f"\n{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)