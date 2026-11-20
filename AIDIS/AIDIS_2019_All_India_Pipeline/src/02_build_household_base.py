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

CACHE_DIR = (
    PROJECT_ROOT
    / "cache"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

HOUSEHOLD_BASE_FILE = (
    CACHE_DIR
    / "household_base_visit1.csv"
)

VALIDATION_REPORT = (
    REPORT_DIR
    / "household_base_validation.csv"
)

ZERO_MLT_REPORT = (
    REPORT_DIR
    / "zero_mlt_households.csv"
)

SUMMARY_REPORT = (
    REPORT_DIR
    / "household_base_summary.txt"
)


# ============================================================
# DDI CONFIGURATION
# ============================================================

MASTER_SHEET = "Master_DDI_AIDIS_77th_Round"

VISIT = "Visit 1"

LEVEL_01 = "Level 1"
LEVEL_03 = "Level 3"


# ============================================================
# REQUIRED LEVEL 01 COLUMNS
# ============================================================

LEVEL01_REQUIRED = [
    "HHID",
    "SchID",
    "FSU_Slno",
    "Round",
    "Schedule",
    "Sample",
    "Sector",
    "NSS_Region",
    "State",
    "State_District",
    "District",
    "Stratum",
    "SubStratumNo",
    "SubRound",
    "FODSubRegion",
    "SSS",
    "hh_no",
    "visitNo",
    "Level",
    "MLT",
]


# ============================================================
# REQUIRED LEVEL 03 COLUMNS
# ============================================================

LEVEL03_REQUIRED = [
    "HHID",
    "Sector",
    "NSS_Region",
    "State",
    "State_District",
    "District",
    "Stratum",
    "SubStratumNo",
    "SSS",
    "hh_no",
    "visitNo",
    "Level",
    "b4q1",
    "b4q2",
    "b4q3",
    "b4q4",
    "b4q5",
    "b4q6dot1",
    "b4q6dot2",
    "b4q6dot3",
    "b4q6dot4",
    "b4q7",
    "b4q8dot1",
    "b4q8dot2",
    "b4q9dot1",
    "b4q9dot2",
    "b4q9dot3",
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


def numeric_series(series):

    return pd.to_numeric(
        series.apply(
            normalize_integer_text
        ),
        errors="coerce"
    )


# ============================================================
# RESOLVE SOURCE FILE DIRECTLY FROM MASTER DDI
# ============================================================

def get_source_file_from_ddi(
    visit,
    level
):

    workbook = load_workbook(
        DDI_FILE,
        read_only=True,
        data_only=True
    )

    ws = workbook[
        MASTER_SHEET
    ]

    rows = ws.iter_rows(
        values_only=True
    )

    headers = [
        clean_text(value)
        for value in next(rows)
    ]

    header_index = {
        header: index
        for index, header
        in enumerate(headers)
    }

    source_files = set()
    source_sheets = set()

    for row in rows:

        row_visit = clean_text(
            row[
                header_index[
                    "Visit"
                ]
            ]
        )

        row_level = clean_text(
            row[
                header_index[
                    "Level"
                ]
            ]
        )

        if (
            row_visit == visit
            and
            row_level == level
        ):

            source_file = clean_text(
                row[
                    header_index[
                        "Source_File"
                    ]
                ]
            )

            source_sheet = clean_text(
                row[
                    header_index[
                        "Source_Sheet"
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

    workbook.close()

    if len(source_files) != 1:

        raise ValueError(
            f"{visit} / {level}: "
            f"expected exactly one source file, "
            f"found {sorted(source_files)}"
        )

    if len(source_sheets) != 1:

        raise ValueError(
            f"{visit} / {level}: "
            f"expected exactly one source sheet, "
            f"found {sorted(source_sheets)}"
        )

    return (
        next(iter(source_files)),
        next(iter(source_sheets)),
    )


# ============================================================
# LOAD RAW LEVEL
# ============================================================

def load_raw_level(
    source_file,
    source_sheet,
    required_columns
):

    path = (
        RAW_DIR
        /
        source_file
    )

    if not path.exists():

        raise FileNotFoundError(
            f"Raw source file not found:\n"
            f"{path}"
        )

    print(
        f"\nReading:\n{path.name}"
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

    missing = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing:

        raise ValueError(
            f"Missing required columns in "
            f"{source_file}:\n"
            +
            "\n".join(
                f"  - {column}"
                for column in missing
            )
        )

    return df[
        required_columns
    ].copy()


# ============================================================
# NORMALIZE COMMON FIELDS
# ============================================================

def normalize_common_fields(df):

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
        "visitNo",
        "Level",
    ]:

        df[
            column
        ] = df[
            column
        ].apply(
            normalize_integer_text
        )

    df[
        "MLT"
    ] = numeric_series(
        df[
            "MLT"
        ]
    )

    return df


# ============================================================
# PREPARE LEVEL 01
# ============================================================

def prepare_level01(df):

    df = normalize_common_fields(
        df
    )

    return df


# ============================================================
# PREPARE LEVEL 03
# ============================================================

def prepare_level03(df):

    df = normalize_common_fields(
        df
    )

    for column in [
        "b4q1",
        "b4q2",
        "b4q3",
        "b4q4",
        "b4q7",
    ]:

        df[
            column
        ] = df[
            column
        ].apply(
            normalize_integer_text
        )

    numeric_columns = [
        "b4q5",
        "b4q6dot1",
        "b4q6dot2",
        "b4q6dot3",
        "b4q6dot4",
        "b4q8dot1",
        "b4q8dot2",
        "b4q9dot1",
        "b4q9dot2",
        "b4q9dot3",
    ]

    for column in numeric_columns:

        df[
            column
        ] = numeric_series(
            df[
                column
            ]
        )

    return df


# ============================================================
# VALIDATE ONE HOUSEHOLD LEVEL
# ============================================================

def validate_level(
    df,
    level_name
):

    duplicate_hhid = int(
        df[
            "HHID"
        ]
        .duplicated()
        .sum()
    )

    blank_hhid = int(
        df[
            "HHID"
        ]
        .eq("")
        .sum()
    )

    blank_mlt = int(
        df[
            "MLT"
        ]
        .isna()
        .sum()
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

    negative_mlt = int(
        (
            df[
                "MLT"
            ]
            <
            0
        ).sum()
    )

    print(
        f"\n{level_name}"
    )

    print(
        f"Rows              : "
        f"{len(df):,}"
    )

    print(
        f"Unique HHID       : "
        f"{df['HHID'].nunique():,}"
    )

    print(
        f"Duplicate HHID    : "
        f"{duplicate_hhid:,}"
    )

    print(
        f"Blank HHID        : "
        f"{blank_hhid:,}"
    )

    print(
        f"Blank MLT         : "
        f"{blank_mlt:,}"
    )

    print(
        f"Zero MLT          : "
        f"{zero_mlt:,}  "
        f"{'WARNING' if zero_mlt else 'PASS'}"
    )

    print(
        f"Negative MLT      : "
        f"{negative_mlt:,}  "
        f"{'FAIL' if negative_mlt else 'PASS'}"
    )

    return {
        "rows":
            len(df),

        "unique_hhid":
            df[
                "HHID"
            ].nunique(),

        "duplicate_hhid":
            duplicate_hhid,

        "blank_hhid":
            blank_hhid,

        "blank_mlt":
            blank_mlt,

        "zero_mlt":
            zero_mlt,

        "negative_mlt":
            negative_mlt,
    }


# ============================================================
# CROSS-LEVEL VALIDATION
# ============================================================

def compare_level01_level03(
    level01,
    level03
):

    print("\n" + "=" * 78)
    print("LEVEL 01 <-> LEVEL 03 CONSISTENCY")
    print("=" * 78)

    l01_ids = set(
        level01[
            "HHID"
        ]
    )

    l03_ids = set(
        level03[
            "HHID"
        ]
    )

    missing_l03 = sorted(
        l01_ids
        -
        l03_ids
    )

    extra_l03 = sorted(
        l03_ids
        -
        l01_ids
    )

    print(
        f"\nHHIDs missing in Level 03 : "
        f"{len(missing_l03):,}"
    )

    print(
        f"Extra HHIDs in Level 03   : "
        f"{len(extra_l03):,}"
    )

    comparison_columns = [
        "Sector",
        "NSS_Region",
        "State",
        "State_District",
        "District",
        "Stratum",
        "SubStratumNo",
        "SSS",
        "hh_no",
    ]

    left = level01[
        [
            "HHID",
            *comparison_columns,
            "MLT",
        ]
    ].copy()

    right = level03[
        [
            "HHID",
            *comparison_columns,
            "MLT",
        ]
    ].copy()

    merged = left.merge(
        right,
        on="HHID",
        how="inner",
        suffixes=(
            "_L01",
            "_L03",
        ),
        validate="one_to_one"
    )

    validation_rows = []

    total_mismatches = 0

    for column in comparison_columns:

        mismatch = int(
            (
                merged[
                    f"{column}_L01"
                ]
                !=
                merged[
                    f"{column}_L03"
                ]
            ).sum()
        )

        total_mismatches += (
            mismatch
        )

        print(
            f"{column:<20}: "
            f"{mismatch:,} mismatch(es)"
        )

        validation_rows.append(
            {
                "Check":
                    f"{column}_L01_vs_L03",

                "Failure_Count":
                    mismatch,

                "Status":
                    (
                        "PASS"
                        if mismatch == 0
                        else "FAIL"
                    ),
            }
        )

    mlt_difference = (
        merged[
            "MLT_L01"
        ]
        -
        merged[
            "MLT_L03"
        ]
    ).abs()

    mlt_mismatch = int(
        (
            mlt_difference
            >
            0.0000001
        ).sum()
    )

    total_mismatches += (
        mlt_mismatch
    )

    print(
        f"{'MLT':<20}: "
        f"{mlt_mismatch:,} mismatch(es)"
    )

    validation_rows.append(
        {
            "Check":
                "MLT_L01_vs_L03",

            "Failure_Count":
                mlt_mismatch,

            "Status":
                (
                    "PASS"
                    if mlt_mismatch == 0
                    else "FAIL"
                ),
        }
    )

    return (
        missing_l03,
        extra_l03,
        validation_rows,
        total_mismatches,
    )


# ============================================================
# HOUSEHOLD CLASSIFICATIONS
# ============================================================

def add_household_classifications(
    base
):

    sector_labels = {
        "1": "Rural",
        "2": "Urban",
    }

    base[
        "Sector_Label"
    ] = (
        base[
            "Sector"
        ]
        .map(
            sector_labels
        )
        .fillna(
            "Unknown"
        )
    )

    # --------------------------------------------------------
    # Rural primary DDI definition
    # --------------------------------------------------------

    base[
        "Cultivator_Flag_Primary"
    ] = (
        (
            base[
                "Sector"
            ]
            ==
            "1"
        )
        &
        (
            base[
                "b4q4"
            ]
            ==
            "1"
        )
    ).astype(int)

    base[
        "Non_Cultivator_Flag_Primary"
    ] = (
        (
            base[
                "Sector"
            ]
            ==
            "1"
        )
        &
        (
            base[
                "Cultivator_Flag_Primary"
            ]
            ==
            0
        )
    ).astype(int)

    # --------------------------------------------------------
    # Alternate rural proxy retained for review
    # --------------------------------------------------------

    base[
        "Cultivator_Flag_Alternate"
    ] = (
        (
            base[
                "Sector"
            ]
            ==
            "1"
        )
        &
        (
            base[
                "b4q7"
            ]
            ==
            "1"
        )
    ).astype(int)

    base[
        "Non_Cultivator_Flag_Alternate"
    ] = (
        (
            base[
                "Sector"
            ]
            ==
            "1"
        )
        &
        (
            base[
                "Cultivator_Flag_Alternate"
            ]
            ==
            0
        )
    ).astype(int)

    # --------------------------------------------------------
    # Urban classification
    # --------------------------------------------------------

    base[
        "Urban_Self_Employed_Flag"
    ] = (
        (
            base[
                "Sector"
            ]
            ==
            "2"
        )
        &
        (
            base[
                "b4q4"
            ]
            ==
            "1"
        )
    ).astype(int)

    base[
        "Urban_Others_Flag"
    ] = (
        (
            base[
                "Sector"
            ]
            ==
            "2"
        )
        &
        (
            base[
                "b4q4"
            ]
            .isin(
                [
                    "2",
                    "3",
                    "9",
                ]
            )
        )
    ).astype(int)

    def classify(row):

        if row["Sector"] == "1":

            if (
                row[
                    "Cultivator_Flag_Primary"
                ]
                ==
                1
            ):
                return "Cultivator HH"

            return "Non-Cultivator HH"

        if row["Sector"] == "2":

            if (
                row[
                    "Urban_Self_Employed_Flag"
                ]
                ==
                1
            ):
                return "Self-employed"

            if (
                row[
                    "Urban_Others_Flag"
                ]
                ==
                1
            ):
                return "Others"

        return "Unclassified"

    base[
        "HH_Class_DDI_Primary"
    ] = base.apply(
        classify,
        axis=1
    )

    return base


# ============================================================
# BUILD HOUSEHOLD BASE
# ============================================================

def build_household_base(
    level01,
    level03
):

    characteristics = level03[
        [
            "HHID",
            "b4q1",
            "b4q2",
            "b4q3",
            "b4q4",
            "b4q5",
            "b4q6dot1",
            "b4q6dot2",
            "b4q6dot3",
            "b4q6dot4",
            "b4q7",
            "b4q8dot1",
            "b4q8dot2",
            "b4q9dot1",
            "b4q9dot2",
            "b4q9dot3",
        ]
    ].copy()

    base = level01.merge(
        characteristics,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    return add_household_classifications(
        base
    )


# ============================================================
# FINAL BASE VALIDATION
# ============================================================

def validate_household_base(
    base
):

    duplicate_hhid = int(
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

    blank_mlt = int(
        base[
            "MLT"
        ]
        .isna()
        .sum()
    )

    negative_mlt = int(
        (
            base[
                "MLT"
            ]
            <
            0
        ).sum()
    )

    zero_mlt = int(
        (
            base[
                "MLT"
            ]
            ==
            0
        ).sum()
    )

    bad_composite = int(
        (
            base[
                "State_District"
            ]
            !=
            (
                base[
                    "State"
                ]
                +
                base[
                    "District"
                ]
            )
        ).sum()
    )

    invalid_sector = int(
        (
            ~base[
                "Sector"
            ]
            .isin(
                [
                    "1",
                    "2",
                ]
            )
        ).sum()
    )

    checks = [
        (
            "Duplicate HHID",
            duplicate_hhid,
            True
        ),
        (
            "Blank HHID",
            blank_hhid,
            True
        ),
        (
            "Blank MLT",
            blank_mlt,
            True
        ),
        (
            "Negative MLT",
            negative_mlt,
            True
        ),
        (
            "Zero MLT",
            zero_mlt,
            False
        ),
        (
            "Bad State_District composite",
            bad_composite,
            True
        ),
        (
            "Invalid Sector",
            invalid_sector,
            True
        ),
    ]

    report = []

    final_pass = True

    print("\n" + "=" * 78)
    print("FINAL HOUSEHOLD BASE VALIDATION")
    print("=" * 78)

    print(
        f"\nHousehold rows : "
        f"{len(base):,}"
    )

    print(
        f"Unique HHID    : "
        f"{base['HHID'].nunique():,}"
    )

    print(
        f"States/UTs     : "
        f"{base['State'].nunique()}"
    )

    print()

    for (
        name,
        count,
        fatal
    ) in checks:

        if count == 0:

            status = "PASS"

        elif fatal:

            status = "FAIL"
            final_pass = False

        else:

            status = "WARNING"

        print(
            f"{name:<32}: "
            f"{count:>8,}  "
            f"{status}"
        )

        report.append(
            {
                "Check":
                    name,

                "Failure_Count":
                    count,

                "Status":
                    status,
            }
        )

    return (
        final_pass,
        report
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS NSS 77 - BUILD HOUSEHOLD BASE V2")
    print("=" * 78)

    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Resolve source files from DDI
    # --------------------------------------------------------

    (
        level01_file,
        level01_sheet
    ) = get_source_file_from_ddi(
        VISIT,
        LEVEL_01
    )

    (
        level03_file,
        level03_sheet
    ) = get_source_file_from_ddi(
        VISIT,
        LEVEL_03
    )

    print(
        "\nDDI source resolution:"
    )

    print(
        f"Level 01: "
        f"{level01_file}"
    )

    print(
        f"          Sheet = "
        f"{level01_sheet}"
    )

    print(
        f"Level 03: "
        f"{level03_file}"
    )

    print(
        f"          Sheet = "
        f"{level03_sheet}"
    )

    # --------------------------------------------------------
    # Read actual raw microdata
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("LOADING VISIT 1 HOUSEHOLD FILES")
    print("=" * 78)

    level01 = load_raw_level(
        level01_file,
        level01_sheet,
        LEVEL01_REQUIRED
    )

    level03 = load_raw_level(
        level03_file,
        level03_sheet,
        LEVEL03_REQUIRED
    )

    level01 = prepare_level01(
        level01
    )

    level03 = prepare_level03(
        level03
    )

    # --------------------------------------------------------
    # Source-level audit
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("SOURCE LEVEL VALIDATION")
    print("=" * 78)

    l01_audit = validate_level(
        level01,
        "Visit 1 Level 01"
    )

    l03_audit = validate_level(
        level03,
        "Visit 1 Level 03"
    )

    # Zero MLT is intentionally NOT fatal.
    source_pass = all(
        [
            l01_audit[
                "duplicate_hhid"
            ] == 0,

            l01_audit[
                "blank_hhid"
            ] == 0,

            l01_audit[
                "blank_mlt"
            ] == 0,

            l01_audit[
                "negative_mlt"
            ] == 0,

            l03_audit[
                "duplicate_hhid"
            ] == 0,

            l03_audit[
                "blank_hhid"
            ] == 0,

            l03_audit[
                "blank_mlt"
            ] == 0,

            l03_audit[
                "negative_mlt"
            ] == 0,
        ]
    )

    if not source_pass:

        raise ValueError(
            "Level 01 / Level 03 source validation failed."
        )

    # --------------------------------------------------------
    # Cross-level consistency
    # --------------------------------------------------------

    (
        missing_l03,
        extra_l03,
        cross_report,
        cross_mismatches,
    ) = compare_level01_level03(
        level01,
        level03
    )

    if (
        missing_l03
        or
        extra_l03
        or
        cross_mismatches != 0
    ):

        pd.DataFrame(
            cross_report
        ).to_csv(
            VALIDATION_REPORT,
            index=False,
            encoding="utf-8-sig"
        )

        raise ValueError(
            "Level 01 / Level 03 household consistency failed."
        )

    # --------------------------------------------------------
    # Build base
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("BUILDING HOUSEHOLD BASE")
    print("=" * 78)

    base = build_household_base(
        level01,
        level03
    )

    # --------------------------------------------------------
    # Final validation
    # --------------------------------------------------------

    (
        final_pass,
        final_report
    ) = validate_household_base(
        base
    )

    # --------------------------------------------------------
    # Zero-weight audit report
    # --------------------------------------------------------

    zero_mlt = base[
        base[
            "MLT"
        ]
        ==
        0
    ].copy()

    zero_columns = [
        "HHID",
        "State",
        "State_District",
        "District",
        "Sector",
        "Sector_Label",
        "MLT",
    ]

    zero_mlt[
        zero_columns
    ].to_csv(
        ZERO_MLT_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # Classification summary
    # --------------------------------------------------------

    rural = base[
        base[
            "Sector"
        ]
        ==
        "1"
    ]

    urban = base[
        base[
            "Sector"
        ]
        ==
        "2"
    ]

    cultivator_disagreement = int(
        (
            rural[
                "Cultivator_Flag_Primary"
            ]
            !=
            rural[
                "Cultivator_Flag_Alternate"
            ]
        ).sum()
    )

    urban_unclassified = int(
        (
            urban[
                "HH_Class_DDI_Primary"
            ]
            ==
            "Unclassified"
        ).sum()
    )

    print("\n" + "=" * 78)
    print("HOUSEHOLD CLASSIFICATION SUMMARY")
    print("=" * 78)

    print(
        f"\nRural households     : "
        f"{len(rural):,}"
    )

    print(
        f"Urban households     : "
        f"{len(urban):,}"
    )

    print(
        "\nRural cultivator:"
    )

    print(
        "  Primary b4q4=1     : "
        f"{int(rural['Cultivator_Flag_Primary'].sum()):,}"
    )

    print(
        "  Alternate b4q7=1   : "
        f"{int(rural['Cultivator_Flag_Alternate'].sum()):,}"
    )

    print(
        "  Disagreement       : "
        f"{cultivator_disagreement:,}"
    )

    print(
        "\nUrban:"
    )

    print(
        "  Self-employed      : "
        f"{int(urban['Urban_Self_Employed_Flag'].sum()):,}"
    )

    print(
        "  Others             : "
        f"{int(urban['Urban_Others_Flag'].sum()):,}"
    )

    print(
        "  Unclassified       : "
        f"{urban_unclassified:,}"
    )

    # --------------------------------------------------------
    # Save validation report
    # --------------------------------------------------------

    pd.DataFrame(
        cross_report
        +
        final_report
    ).to_csv(
        VALIDATION_REPORT,
        index=False,
        encoding="utf-8-sig"
    )

    if not final_pass:

        raise ValueError(
            "Final household base validation failed."
        )

    # --------------------------------------------------------
    # Save household base
    # --------------------------------------------------------

    output_columns = [
        "HHID",
        "SchID",
        "FSU_Slno",
        "Round",
        "Schedule",
        "Sample",
        "Sector",
        "Sector_Label",
        "NSS_Region",
        "State",
        "State_District",
        "District",
        "Stratum",
        "SubStratumNo",
        "SubRound",
        "FODSubRegion",
        "SSS",
        "hh_no",
        "visitNo",
        "MLT",

        "b4q1",
        "b4q2",
        "b4q3",
        "b4q4",
        "b4q5",
        "b4q6dot1",
        "b4q6dot2",
        "b4q6dot3",
        "b4q6dot4",
        "b4q7",
        "b4q8dot1",
        "b4q8dot2",
        "b4q9dot1",
        "b4q9dot2",
        "b4q9dot3",

        "Cultivator_Flag_Primary",
        "Non_Cultivator_Flag_Primary",
        "Cultivator_Flag_Alternate",
        "Non_Cultivator_Flag_Alternate",

        "Urban_Self_Employed_Flag",
        "Urban_Others_Flag",

        "HH_Class_DDI_Primary",
    ]

    base[
        output_columns
    ].to_csv(
        HOUSEHOLD_BASE_FILE,
        index=False,
        encoding="utf-8",
        lineterminator="\n"
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    summary = [
        "=" * 78,
        "AIDIS NSS 77 - HOUSEHOLD BASE SUMMARY",
        "=" * 78,
        "",
        f"Visit 1 Level 01 rows          : {len(level01):,}",
        f"Visit 1 Level 03 rows          : {len(level03):,}",
        f"Final household rows           : {len(base):,}",
        f"Unique HHID                    : {base['HHID'].nunique():,}",
        f"States/UTs                     : {base['State'].nunique()}",
        f"Observed State-District codes  : {base['State_District'].nunique()}",
        "",
        f"Zero MLT households            : {len(zero_mlt):,}",
        f"Negative MLT households        : {int((base['MLT'] < 0).sum()):,}",
        "",
        "Zero MLT policy:",
        "  - raw value preserved",
        "  - household NOT deleted",
        "  - MLT NOT imputed or changed",
        "  - contributes zero to weighted SUM(MLT) estimates",
        "  - remains available for unweighted HHID counts",
        "",
        f"Level01 HHIDs missing Level03  : {len(missing_l03):,}",
        f"Extra Level03 HHIDs            : {len(extra_l03):,}",
        f"Cross-level mismatches         : {cross_mismatches:,}",
        "",
        (
            "Rural primary/alternate "
            f"cultivator disagreements : "
            f"{cultivator_disagreement:,}"
        ),
        (
            "Urban unclassified HH          : "
            f"{urban_unclassified:,}"
        ),
        "",
        "HOUSEHOLD BASE STATUS           : PASS",
        "=" * 78,
    ]

    SUMMARY_REPORT.write_text(
        "\n".join(
            summary
        ),
        encoding="utf-8"
    )

    print("\n")
    print(
        "\n".join(
            summary
        )
    )

    print(
        f"\nHousehold base:\n"
        f"{HOUSEHOLD_BASE_FILE}"
    )

    print(
        f"\nZero MLT audit:\n"
        f"{ZERO_MLT_REPORT}"
    )

    print(
        f"\nValidation report:\n"
        f"{VALIDATION_REPORT}"
    )

    print(
        f"\nSummary report:\n"
        f"{SUMMARY_REPORT}"
    )

    print(
        "\nNo KPI values have been calculated yet."
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            "\n" + "=" * 78
        )

        print(
            "HOUSEHOLD BASE BUILD: FAIL"
        )

        print(
            "=" * 78
        )

        print(
            f"\n{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)