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

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

ITEM_PROFILE_REPORT = (
    REPORT_DIR
    / "asset_value_item_profile.csv"
)

BLANK_SAMPLE_REPORT = (
    REPORT_DIR
    / "asset_blank_value_samples.csv"
)

LEVEL12_BLANK_COLUMN_PROFILE = (
    REPORT_DIR
    / "level12_blank_value_column_profile.csv"
)

LEVEL12_ITEM19_PROFILE = (
    REPORT_DIR
    / "level12_item19_column_profile.csv"
)

LEVEL12_CANDIDATE_PROFILE = (
    REPORT_DIR
    / "level12_candidate_value_columns.csv"
)

DDI_LEVEL12_VARIABLES_REPORT = (
    REPORT_DIR
    / "level12_ddi_variable_inventory.csv"
)

SUMMARY_REPORT = (
    REPORT_DIR
    / "asset_value_review_summary.txt"
)


# ============================================================
# DDI SETTINGS
# ============================================================

MASTER_DDI_SHEET = "Master_DDI_AIDIS_77th_Round"

VISIT = "Visit 1"


# ============================================================
# LEVELS REQUIRING REVIEW
# ============================================================

REVIEW_LEVELS = {
    5: {
        "name": "Rural Land",
        "item_column": "b5pt1q1",
        "value_column": "b5pt1q5",
        "block_prefix": "b5pt1",
    },

    6: {
        "name": "Urban Land",
        "item_column": "b5pt2q1",
        "value_column": "b5pt2q5",
        "block_prefix": "b5pt2",
    },

    12: {
        "name": "Financial Assets excluding Shares",
        "item_column": "b11aq1",
        "value_column": "b11aq3",
        "block_prefix": "b11a",
    },

    13: {
        "name": "Shares and Investments",
        "item_column": "b11bq1",
        "value_column": "b11bq3",
        "block_prefix": "b11b",
    },
}


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

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
    Examples:
        1.0 -> 1
        19.0 -> 19
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


def normalize_item_code(value):
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
    cleaned = (
        series
        .map(clean_text)
        .replace(
            "",
            pd.NA
        )
    )

    return pd.to_numeric(
        cleaned,
        errors="coerce"
    )


def safe_number(value):
    if pd.isna(value):
        return ""

    return value


def example_values(
    series,
    limit=5
):
    values = []

    for value in series:

        value = clean_text(
            value
        )

        if not value:
            continue

        if value not in values:
            values.append(
                value
            )

        if len(values) >= limit:
            break

    return " | ".join(
        values
    )


# ============================================================
# READ MASTER DDI
# ============================================================

def load_master_ddi_rows():

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

    output = []

    for row in rows:

        record = {}

        for index, header in enumerate(
            headers
        ):

            if not header:
                continue

            record[
                header
            ] = (
                row[index]
                if index < len(row)
                else None
            )

        output.append(
            record
        )

    workbook.close()

    return output


# ============================================================
# GET DDI INFORMATION FOR A LEVEL
# ============================================================

def get_level_ddi_info(
    all_ddi_rows,
    level_number
):

    expected_level = (
        f"Level {level_number}"
    )

    level_rows = []

    for row in all_ddi_rows:

        visit = clean_text(
            row.get(
                "Visit"
            )
        )

        level = clean_text(
            row.get(
                "Level"
            )
        )

        if (
            visit == VISIT
            and
            level == expected_level
        ):

            level_rows.append(
                row
            )

    if not level_rows:

        raise ValueError(
            f"No DDI rows found for "
            f"{VISIT} / {expected_level}"
        )

    source_files = {
        clean_text(
            row.get(
                "Source_File"
            )
        )
        for row in level_rows
        if clean_text(
            row.get(
                "Source_File"
            )
        )
    }

    source_sheets = {
        clean_text(
            row.get(
                "Source_Sheet"
            )
        )
        for row in level_rows
        if clean_text(
            row.get(
                "Source_Sheet"
            )
        )
    }

    if len(source_files) != 1:

        raise ValueError(
            f"Level {level_number}: "
            f"expected one source file, "
            f"found {sorted(source_files)}"
        )

    if len(source_sheets) != 1:

        raise ValueError(
            f"Level {level_number}: "
            f"expected one source sheet, "
            f"found {sorted(source_sheets)}"
        )

    variable_metadata = {}

    for row in level_rows:

        variable = clean_text(
            row.get(
                "Original_Column_Name"
            )
        )

        if not variable:
            continue

        variable_metadata[
            variable
        ] = {
            "Variable_Label":
                clean_text(
                    row.get(
                        "Variable_Label"
                    )
                ),

            "DDI_Variable_Name":
                clean_text(
                    row.get(
                        "DDI_Variable_Name"
                    )
                ),

            "Mapping_Status":
                clean_text(
                    row.get(
                        "Mapping_Status"
                    )
                ),

            "Validation_Status":
                clean_text(
                    row.get(
                        "Validation_Status"
                    )
                ),
        }

    return {
        "source_file":
            next(
                iter(
                    source_files
                )
            ),

        "source_sheet":
            next(
                iter(
                    source_sheets
                )
            ),

        "ddi_rows":
            level_rows,

        "variable_metadata":
            variable_metadata,
    }


# ============================================================
# LOAD RAW LEVEL
# ============================================================

def load_raw_level(
    level_number,
    spec,
    ddi_info
):

    file_path = (
        RAW_DIR
        /
        ddi_info[
            "source_file"
        ]
    )

    if not file_path.exists():

        raise FileNotFoundError(
            f"Level {level_number} "
            f"source file missing:\n"
            f"{file_path}"
        )

    print(
        f"\nReading Level "
        f"{level_number:02d}: "
        f"{spec['name']}"
    )

    print(
        f"  File  : "
        f"{file_path.name}"
    )

    print(
        f"  Sheet : "
        f"{ddi_info['source_sheet']}"
    )

    df = pd.read_excel(
        file_path,
        sheet_name=ddi_info[
            "source_sheet"
        ],
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

    item_column = spec[
        "item_column"
    ]

    value_column = spec[
        "value_column"
    ]

    required = [
        "HHID",
        item_column,
        value_column,
    ]

    missing = [
        column
        for column in required
        if column not in df.columns
    ]

    if missing:

        raise ValueError(
            f"Level {level_number}: "
            f"missing required columns:\n"
            +
            "\n".join(
                f"  - {column}"
                for column in missing
            )
        )

    df[
        "HHID"
    ] = (
        df[
            "HHID"
        ]
        .map(
            normalize_integer_text
        )
    )

    df[
        item_column
    ] = (
        df[
            item_column
        ]
        .map(
            normalize_item_code
        )
    )

    df[
        "_Value_Text"
    ] = (
        df[
            value_column
        ]
        .map(
            clean_text
        )
    )

    df[
        "_Value_Numeric"
    ] = numeric_series(
        df[
            value_column
        ]
    )

    return df


# ============================================================
# ITEM-CODE VALUE PROFILE
# ============================================================

def build_item_profile(
    level_number,
    spec,
    df
):

    item_column = spec[
        "item_column"
    ]

    profile_rows = []

    item_codes = sorted(
        df[
            item_column
        ]
        .drop_duplicates()
        .tolist(),
        key=lambda value: (
            int(value)
            if str(value).isdigit()
            else 999999
        )
    )

    for item_code in item_codes:

        part = df[
            df[
                item_column
            ]
            ==
            item_code
        ]

        total_rows = len(
            part
        )

        blank_count = int(
            part[
                "_Value_Text"
            ]
            .eq("")
            .sum()
        )

        numeric_count = int(
            part[
                "_Value_Numeric"
            ]
            .notna()
            .sum()
        )

        zero_count = int(
            (
                part[
                    "_Value_Numeric"
                ]
                ==
                0
            ).sum()
        )

        positive_count = int(
            (
                part[
                    "_Value_Numeric"
                ]
                >
                0
            ).sum()
        )

        negative_count = int(
            (
                part[
                    "_Value_Numeric"
                ]
                <
                0
            ).sum()
        )

        numeric_values = (
            part[
                "_Value_Numeric"
            ]
            .dropna()
        )

        profile_rows.append(
            {
                "Level":
                    level_number,

                "Asset_Component":
                    spec[
                        "name"
                    ],

                "Item_Column":
                    item_column,

                "Item_Code":
                    item_code,

                "Value_Column":
                    spec[
                        "value_column"
                    ],

                "Rows":
                    total_rows,

                "Unique_HHID":
                    part[
                        "HHID"
                    ].nunique(),

                "Blank_Value":
                    blank_count,

                "Blank_Percent":
                    (
                        blank_count
                        /
                        total_rows
                        *
                        100
                        if total_rows
                        else 0
                    ),

                "Numeric_Value_Rows":
                    numeric_count,

                "Zero_Value":
                    zero_count,

                "Positive_Value":
                    positive_count,

                "Negative_Value":
                    negative_count,

                "Min_Value":
                    (
                        safe_number(
                            numeric_values.min()
                        )
                        if len(
                            numeric_values
                        )
                        else ""
                    ),

                "Max_Value":
                    (
                        safe_number(
                            numeric_values.max()
                        )
                        if len(
                            numeric_values
                        )
                        else ""
                    ),

                "Sum_Value":
                    (
                        safe_number(
                            numeric_values.sum()
                        )
                        if len(
                            numeric_values
                        )
                        else ""
                    ),

                "Mean_Value":
                    (
                        safe_number(
                            numeric_values.mean()
                        )
                        if len(
                            numeric_values
                        )
                        else ""
                    ),
            }
        )

    return profile_rows


# ============================================================
# BLANK ROW SAMPLES
# ============================================================

def build_blank_samples(
    level_number,
    spec,
    df,
    sample_per_item=10
):

    item_column = spec[
        "item_column"
    ]

    prefix = spec[
        "block_prefix"
    ].lower()

    block_columns = [
        column
        for column in df.columns
        if (
            column.lower().startswith(
                prefix
            )
            or
            column
            ==
            "HHID"
        )
    ]

    blank_df = df[
        df[
            "_Value_Text"
        ]
        ==
        ""
    ].copy()

    sample_rows = []

    for item_code, part in (
        blank_df.groupby(
            item_column,
            dropna=False
        )
    ):

        sample = part.head(
            sample_per_item
        )

        for _, row in sample.iterrows():

            output = {
                "Level":
                    level_number,

                "Asset_Component":
                    spec[
                        "name"
                    ],

                "Item_Code":
                    item_code,

                "Expected_Value_Column":
                    spec[
                        "value_column"
                    ],
            }

            for column in block_columns:

                output[
                    column
                ] = clean_text(
                    row.get(
                        column
                    )
                )

            sample_rows.append(
                output
            )

    return sample_rows


# ============================================================
# LEVEL 12 SPECIAL DIAGNOSTICS
# ============================================================

def build_level12_diagnostics(
    df,
    ddi_info
):

    item_column = "b11aq1"
    expected_value_column = "b11aq3"

    block_columns = [
        column
        for column in df.columns
        if column.lower().startswith(
            "b11a"
        )
    ]

    variable_metadata = ddi_info[
        "variable_metadata"
    ]

    # --------------------------------------------------------
    # 1. Profile all possible b11a columns by item code
    # --------------------------------------------------------

    candidate_rows = []

    item_codes = sorted(
        df[
            item_column
        ]
        .drop_duplicates()
        .tolist(),
        key=lambda value: (
            int(value)
            if str(value).isdigit()
            else 999999
        )
    )

    for item_code in item_codes:

        item_df = df[
            df[
                item_column
            ]
            ==
            item_code
        ]

        for column in block_columns:

            if column == item_column:
                continue

            text_values = (
                item_df[
                    column
                ]
                .map(
                    clean_text
                )
            )

            numeric_values = pd.to_numeric(
                text_values.replace(
                    "",
                    pd.NA
                ),
                errors="coerce"
            )

            nonblank_count = int(
                text_values.ne(
                    ""
                ).sum()
            )

            numeric_count = int(
                numeric_values
                .notna()
                .sum()
            )

            metadata = (
                variable_metadata.get(
                    column,
                    {}
                )
            )

            candidate_rows.append(
                {
                    "Item_Code":
                        item_code,

                    "Column":
                        column,

                    "Variable_Label":
                        metadata.get(
                            "Variable_Label",
                            ""
                        ),

                    "Rows_For_Item":
                        len(
                            item_df
                        ),

                    "NonBlank_Count":
                        nonblank_count,

                    "Numeric_Count":
                        numeric_count,

                    "NonBlank_Percent":
                        (
                            nonblank_count
                            /
                            len(
                                item_df
                            )
                            *
                            100
                            if len(
                                item_df
                            )
                            else 0
                        ),

                    "Numeric_Percent":
                        (
                            numeric_count
                            /
                            len(
                                item_df
                            )
                            *
                            100
                            if len(
                                item_df
                            )
                            else 0
                        ),

                    "Examples":
                        example_values(
                            text_values
                        ),
                }
            )

    # --------------------------------------------------------
    # 2. Blank b11aq3 rows:
    #    determine which OTHER b11a columns are populated.
    # --------------------------------------------------------

    blank_value_df = df[
        df[
            "_Value_Text"
        ]
        ==
        ""
    ].copy()

    blank_profile_rows = []

    for item_code, item_df in (
        blank_value_df.groupby(
            item_column,
            dropna=False
        )
    ):

        for column in block_columns:

            if column in {
                item_column,
                expected_value_column,
            }:
                continue

            text_values = (
                item_df[
                    column
                ]
                .map(
                    clean_text
                )
            )

            nonblank_count = int(
                text_values.ne(
                    ""
                ).sum()
            )

            if nonblank_count == 0:
                continue

            numeric_values = pd.to_numeric(
                text_values.replace(
                    "",
                    pd.NA
                ),
                errors="coerce"
            )

            metadata = (
                variable_metadata.get(
                    column,
                    {}
                )
            )

            blank_profile_rows.append(
                {
                    "Item_Code":
                        item_code,

                    "Blank_b11aq3_Rows":
                        len(
                            item_df
                        ),

                    "Other_Column":
                        column,

                    "Variable_Label":
                        metadata.get(
                            "Variable_Label",
                            ""
                        ),

                    "Other_Column_NonBlank":
                        nonblank_count,

                    "Other_Column_Numeric":
                        int(
                            numeric_values
                            .notna()
                            .sum()
                        ),

                    "Examples":
                        example_values(
                            text_values
                        ),
                }
            )

    # --------------------------------------------------------
    # 3. Item 19 investigation
    # --------------------------------------------------------

    item19 = df[
        df[
            item_column
        ]
        ==
        "19"
    ].copy()

    item19_rows = []

    for column in block_columns:

        if column == item_column:
            continue

        text_values = (
            item19[
                column
            ]
            .map(
                clean_text
            )
        )

        numeric_values = pd.to_numeric(
            text_values.replace(
                "",
                pd.NA
            ),
            errors="coerce"
        )

        nonblank_count = int(
            text_values.ne(
                ""
            ).sum()
        )

        numeric_count = int(
            numeric_values.notna(
            ).sum()
        )

        metadata = (
            variable_metadata.get(
                column,
                {}
            )
        )

        item19_rows.append(
            {
                "Column":
                    column,

                "Variable_Label":
                    metadata.get(
                        "Variable_Label",
                        ""
                    ),

                "Item19_Rows":
                    len(
                        item19
                    ),

                "NonBlank_Count":
                    nonblank_count,

                "Numeric_Count":
                    numeric_count,

                "Blank_Count":
                    (
                        len(
                            item19
                        )
                        -
                        nonblank_count
                    ),

                "Min_Numeric":
                    (
                        safe_number(
                            numeric_values.min()
                        )
                        if numeric_count
                        else ""
                    ),

                "Max_Numeric":
                    (
                        safe_number(
                            numeric_values.max()
                        )
                        if numeric_count
                        else ""
                    ),

                "Sum_Numeric":
                    (
                        safe_number(
                            numeric_values.sum()
                        )
                        if numeric_count
                        else ""
                    ),

                "Examples":
                    example_values(
                        text_values
                    ),
            }
        )

    item19_df = pd.DataFrame(
        item19_rows
    )

    if not item19_df.empty:

        item19_df = item19_df.sort_values(
            by=[
                "Numeric_Count",
                "NonBlank_Count",
            ],
            ascending=[
                False,
                False,
            ]
        )

    return (
        candidate_rows,
        blank_profile_rows,
        item19_df,
    )


# ============================================================
# LEVEL 12 DDI VARIABLE INVENTORY
# ============================================================

def build_level12_ddi_inventory(
    ddi_info
):

    rows = []

    for variable, metadata in (
        ddi_info[
            "variable_metadata"
        ].items()
    ):

        if not variable.lower().startswith(
            "b11a"
        ):
            continue

        rows.append(
            {
                "Variable":
                    variable,

                "DDI_Variable_Name":
                    metadata.get(
                        "DDI_Variable_Name",
                        ""
                    ),

                "Variable_Label":
                    metadata.get(
                        "Variable_Label",
                        ""
                    ),

                "Mapping_Status":
                    metadata.get(
                        "Mapping_Status",
                        ""
                    ),

                "Validation_Status":
                    metadata.get(
                        "Validation_Status",
                        ""
                    ),
            }
        )

    return rows


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS NSS 77 - STEP 03A2 ASSET VALUE REVIEW"
    )

    print(
        "=" * 78
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if not DDI_FILE.exists():

        raise FileNotFoundError(
            f"Master DDI not found:\n"
            f"{DDI_FILE}"
        )

    if not RAW_DIR.exists():

        raise FileNotFoundError(
            f"Raw input directory not found:\n"
            f"{RAW_DIR}"
        )

    ddi_rows = (
        load_master_ddi_rows()
    )

    all_item_profiles = []

    all_blank_samples = []

    level12_candidate_rows = []

    level12_blank_rows = []

    level12_item19_df = (
        pd.DataFrame()
    )

    level12_ddi_inventory = []

    level_summaries = []

    # --------------------------------------------------------
    # Review Levels 05, 06, 12 and 13
    # --------------------------------------------------------

    for level_number, spec in (
        REVIEW_LEVELS.items()
    ):

        ddi_info = (
            get_level_ddi_info(
                ddi_rows,
                level_number
            )
        )

        df = load_raw_level(
            level_number,
            spec,
            ddi_info
        )

        item_profiles = (
            build_item_profile(
                level_number,
                spec,
                df
            )
        )

        all_item_profiles.extend(
            item_profiles
        )

        blank_samples = (
            build_blank_samples(
                level_number,
                spec,
                df,
                sample_per_item=10
            )
        )

        all_blank_samples.extend(
            blank_samples
        )

        total_blank = int(
            df[
                "_Value_Text"
            ]
            .eq("")
            .sum()
        )

        total_numeric = int(
            df[
                "_Value_Numeric"
            ]
            .notna()
            .sum()
        )

        blank_item_codes = sorted(
            df.loc[
                df[
                    "_Value_Text"
                ]
                ==
                "",
                spec[
                    "item_column"
                ],
            ]
            .drop_duplicates()
            .tolist(),
            key=lambda value: (
                int(value)
                if str(value).isdigit()
                else 999999
            )
        )

        level_summaries.append(
            {
                "Level":
                    level_number,

                "Name":
                    spec[
                        "name"
                    ],

                "Rows":
                    len(
                        df
                    ),

                "Blank_Value":
                    total_blank,

                "Numeric_Value":
                    total_numeric,

                "Blank_Item_Codes":
                    ", ".join(
                        blank_item_codes
                    ),
            }
        )

        print(
            f"\nLevel {level_number:02d} "
            f"- {spec['name']}"
        )

        print(
            f"  Rows                  : "
            f"{len(df):,}"
        )

        print(
            f"  Blank "
            f"{spec['value_column']:<12}: "
            f"{total_blank:,}"
        )

        print(
            f"  Numeric values        : "
            f"{total_numeric:,}"
        )

        print(
            "  Item codes with blanks: "
            +
            (
                ", ".join(
                    blank_item_codes
                )
                if blank_item_codes
                else "None"
            )
        )

        # ----------------------------------------------------
        # Level 12 special analysis
        # ----------------------------------------------------

        if level_number == 12:

            (
                level12_candidate_rows,
                level12_blank_rows,
                level12_item19_df,
            ) = build_level12_diagnostics(
                df,
                ddi_info
            )

            level12_ddi_inventory = (
                build_level12_ddi_inventory(
                    ddi_info
                )
            )

    # ========================================================
    # WRITE GENERAL ITEM PROFILE
    # ========================================================

    item_profile_df = pd.DataFrame(
        all_item_profiles
    )

    item_profile_df.to_csv(
        ITEM_PROFILE_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # WRITE BLANK SAMPLES
    # ========================================================

    blank_sample_df = pd.DataFrame(
        all_blank_samples
    )

    blank_sample_df.to_csv(
        BLANK_SAMPLE_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # LEVEL 12 SPECIAL REPORTS
    # ========================================================

    pd.DataFrame(
        level12_blank_rows
    ).to_csv(
        LEVEL12_BLANK_COLUMN_PROFILE,
        index=False,
        encoding="utf-8-sig"
    )

    level12_item19_df.to_csv(
        LEVEL12_ITEM19_PROFILE,
        index=False,
        encoding="utf-8-sig"
    )

    pd.DataFrame(
        level12_candidate_rows
    ).to_csv(
        LEVEL12_CANDIDATE_PROFILE,
        index=False,
        encoding="utf-8-sig"
    )

    pd.DataFrame(
        level12_ddi_inventory
    ).to_csv(
        DDI_LEVEL12_VARIABLES_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # TERMINAL LEVEL 12 ITEM-19 DIAGNOSTIC
    # ========================================================

    print(
        "\n" + "=" * 78
    )

    print(
        "LEVEL 12 - ITEM 19 COLUMN INVESTIGATION"
    )

    print(
        "=" * 78
    )

    if level12_item19_df.empty:

        print(
            "\nNo item 19 rows found."
        )

    else:

        print(
            "\nMost populated numeric columns "
            "on b11aq1 = 19 rows:"
        )

        useful = (
            level12_item19_df[
                level12_item19_df[
                    "Numeric_Count"
                ]
                >
                0
            ]
            .head(
                15
            )
        )

        if useful.empty:

            print(
                "  No numeric b11a columns "
                "found on item 19 rows."
            )

        else:

            for _, row in (
                useful.iterrows()
            ):

                print(
                    f"  "
                    f"{row['Column']:<15} "
                    f"numeric={int(row['Numeric_Count']):>7,}  "
                    f"nonblank={int(row['NonBlank_Count']):>7,}"
                )

                label = clean_text(
                    row[
                        "Variable_Label"
                    ]
                )

                if label:

                    print(
                        f"      {label}"
                    )

    # ========================================================
    # SHOW ITEM-CODE BLANK SUMMARY
    # ========================================================

    print(
        "\n" + "=" * 78
    )

    print(
        "BLANK VALUE SUMMARY BY ITEM CODE"
    )

    print(
        "=" * 78
    )

    blanks = item_profile_df[
        item_profile_df[
            "Blank_Value"
        ]
        >
        0
    ].copy()

    if blanks.empty:

        print(
            "\nNo blank expected asset "
            "values found."
        )

    else:

        for _, row in (
            blanks.iterrows()
        ):

            print(
                f"\nLevel {int(row['Level']):02d} "
                f"{row['Asset_Component']}"
            )

            print(
                f"  Item code       : "
                f"{row['Item_Code']}"
            )

            print(
                f"  Rows            : "
                f"{int(row['Rows']):,}"
            )

            print(
                f"  Blank values    : "
                f"{int(row['Blank_Value']):,}"
            )

            print(
                f"  Blank percentage: "
                f"{row['Blank_Percent']:.2f}%"
            )

    # ========================================================
    # WRITE TEXT SUMMARY
    # ========================================================

    summary_lines = [
        "=" * 78,
        "AIDIS NSS 77 - STEP 03A2 ASSET VALUE REVIEW",
        "=" * 78,
        "",
    ]

    for level in level_summaries:

        summary_lines.extend(
            [
                (
                    f"Level {level['Level']:02d} - "
                    f"{level['Name']}"
                ),
                (
                    f"  Rows             : "
                    f"{level['Rows']:,}"
                ),
                (
                    f"  Blank values     : "
                    f"{level['Blank_Value']:,}"
                ),
                (
                    f"  Numeric values   : "
                    f"{level['Numeric_Value']:,}"
                ),
                (
                    "  Blank item codes : "
                    +
                    (
                        level[
                            "Blank_Item_Codes"
                        ]
                        or "None"
                    )
                ),
                "",
            ]
        )

    summary_lines.extend(
        [
            "Purpose of this review:",
            (
                "  Determine whether blank expected asset "
                "values represent true zero/no-value records,"
            ),
            (
                "  or whether the monetary value is stored "
                "in a different source column."
            ),
            "",
            (
                "No raw value was modified by this script."
            ),
            (
                "No household asset total was calculated."
            ),
            (
                "No AVA was calculated."
            ),
            "=" * 78,
        ]
    )

    SUMMARY_REPORT.write_text(
        "\n".join(
            summary_lines
        ),
        encoding="utf-8"
    )

    # ========================================================
    # REPORT PATHS
    # ========================================================

    print(
        "\n" + "=" * 78
    )

    print(
        "STEP 03A2 REPORTS CREATED"
    )

    print(
        "=" * 78
    )

    print(
        f"\n{ITEM_PROFILE_REPORT}"
    )

    print(
        f"{BLANK_SAMPLE_REPORT}"
    )

    print(
        f"{LEVEL12_BLANK_COLUMN_PROFILE}"
    )

    print(
        f"{LEVEL12_ITEM19_PROFILE}"
    )

    print(
        f"{LEVEL12_CANDIDATE_PROFILE}"
    )

    print(
        f"{DDI_LEVEL12_VARIABLES_REPORT}"
    )

    print(
        f"{SUMMARY_REPORT}"
    )

    print(
        "\nSTEP 03A2 STATUS: COMPLETE"
    )

    print(
        "\nNo data was changed and "
        "no AVA was calculated."
    )


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
            "STEP 03A2 ASSET VALUE REVIEW: FAIL"
        )

        print(
            "=" * 78
        )

        print(
            f"\n{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)