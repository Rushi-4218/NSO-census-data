from pathlib import Path
import re
import sys

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

CACHE_DIR = (
    PROJECT_ROOT
    / "cache"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

OUTPUT_FILE = (
    CACHE_DIR
    / "household_debt_credit_facts.csv"
)

CASH_V1_FILE = (
    CACHE_DIR
    / "cash_loan_detail_visit1.csv"
)

CASH_V2_FILE = (
    CACHE_DIR
    / "cash_loan_detail_visit2.csv"
)

KIND_V1_FILE = (
    CACHE_DIR
    / "kind_loan_detail_visit1.csv"
)

KIND_V2_FILE = (
    CACHE_DIR
    / "kind_loan_detail_visit2.csv"
)

SUMMARY_REPORT = (
    REPORT_DIR
    / "debt_credit_build_summary.txt"
)


MASTER_DDI_SHEET = "Master_DDI_AIDIS_77th_Round"


# ============================================================
# OFFICIAL CONTROL VALUES
# ============================================================

OFFICIAL_RURAL_AOD = 59748.0
OFFICIAL_URBAN_AOD = 120336.0

OFFICIAL_RURAL_IOI = 35.0
OFFICIAL_URBAN_IOI = 22.4


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


def normalize_code(value):

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


def canonicalize_hhid(
    value,
    visit
):

    hhid = normalize_integer_text(
        value
    )

    if not hhid:
        return ""

    if visit == "Visit 1":

        if not hhid.endswith(
            "1"
        ):

            raise ValueError(
                f"Unexpected Visit 1 HHID: "
                f"{hhid}"
            )

        return hhid

    if visit == "Visit 2":

        if not hhid.endswith(
            "2"
        ):

            raise ValueError(
                f"Unexpected Visit 2 HHID: "
                f"{hhid}"
            )

        return (
            hhid[:-1]
            +
            "1"
        )

    raise ValueError(
        f"Unsupported visit: {visit}"
    )


# ============================================================
# DDI SOURCE RESOLUTION
# ============================================================

def get_source(
    visit,
    level_number
):

    wb = load_workbook(
        DDI_FILE,
        read_only=True,
        data_only=True
    )

    ws = wb[
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

    files = set()
    sheets = set()

    for row in rows:

        if clean_text(
            row[
                index["Visit"]
            ]
        ) != visit:
            continue

        if clean_text(
            row[
                index["Level"]
            ]
        ) != expected_level:
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

        if source_file:
            files.add(
                source_file
            )

        if source_sheet:
            sheets.add(
                source_sheet
            )

    wb.close()

    if len(files) != 1:

        raise ValueError(
            f"{visit} Level {level_number}: "
            f"source files = {sorted(files)}"
        )

    if len(sheets) != 1:

        raise ValueError(
            f"{visit} Level {level_number}: "
            f"source sheets = {sorted(sheets)}"
        )

    return (
        next(iter(files)),
        next(iter(sheets))
    )


# ============================================================
# HOUSEHOLD BASE
# ============================================================

def load_base():

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

    base = base[
        required
    ].copy()

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

    return base


# ============================================================
# CASH LOANS - LEVEL 14
# ============================================================

def load_cash_loans(
    visit
):

    file_name, sheet_name = (
        get_source(
            visit,
            14
        )
    )

    path = (
        RAW_DIR
        /
        file_name
    )

    print(
        f"\nReading {visit} Level 14:"
    )

    print(
        f"  {file_name}"
    )

    required = [
        "HHID",

        # Loan serial number.
        # 99 = household total/control row.
        "b12q1",

        "b12q3",
        "b12q6",
        "b12q8",
        "b12q13",
        "b12q14",
        "b12q15",
    ]
    
    df = pd.read_excel(
        path,
        sheet_name=sheet_name,
        usecols=required,
        dtype=str,
        engine="openpyxl"
    )

    df = df.dropna(
        how="all"
    ).copy()

    df[
        "Raw_HHID"
    ] = df[
        "HHID"
    ].map(
        normalize_integer_text
    )

    df[
        "HHID"
    ] = df[
        "Raw_HHID"
    ].map(
        lambda value:
        canonicalize_hhid(
            value,
            visit
        )
    )

    for column in [
        "b12q1",
        "b12q3",
        "b12q6",
        "b12q8",
        "b12q14",
    ]:

        df[
            column
        ] = df[
            column
        ].map(
            normalize_code
        )

    df[
        "b12q13"
    ] = pd.to_numeric(
        df[
            "b12q13"
        ],
        errors="coerce"
    )

    df[
        "b12q15"
    ] = pd.to_numeric(
        df[
            "b12q15"
        ],
        errors="coerce"
    )

    blank_q13 = int(
        df[
            "b12q13"
        ].isna().sum()
    )

    blank_q15 = int(
        df[
            "b12q15"
        ].isna().sum()
    )

    negative_q13 = int(
        (
            df[
                "b12q13"
            ]
            <
            0
        ).sum()
    )

    negative_q15 = int(
        (
            df[
                "b12q15"
            ]
            <
            0
        ).sum()
    )

    if negative_q13 or negative_q15:

        raise ValueError(
            f"{visit} Level 14 contains "
            "negative debt amounts."
        )

    print(
        f"  Rows                    : "
        f"{len(df):,}"
    )

    print(
        f"  Canonical HHID          : "
        f"{df['HHID'].nunique():,}"
    )

    if visit == "Visit 2":

        print(
            "  Visit-2 HHID mapping    : "
            "last digit 2 -> 1"
        )

    print(
        f"  Blank survey-date q13   : "
        f"{blank_q13:,}"
    )

    print(
        f"  Blank fixed-date q15    : "
        f"{blank_q15:,}"
    )

    print(
        f"  Negative q15            : "
        f"{negative_q15:,}"
    )

    return df


# ============================================================
# KIND LOANS - LEVEL 15
#
# Retained as auxiliary information only.
# NOT included in official Report-588 AOD/IOI.
# ============================================================

def load_kind_loans(
    visit
):

    file_name, sheet_name = (
        get_source(
            visit,
            15
        )
    )

    path = (
        RAW_DIR
        /
        file_name
    )

    print(
        f"\nReading {visit} Level 15:"
    )

    print(
        f"  {file_name}"
    )

    df = pd.read_excel(
        path,
        sheet_name=sheet_name,
        usecols=[
            "HHID",
            "b13q5",
        ],
        dtype=str,
        engine="openpyxl"
    )

    df = df.dropna(
        how="all"
    ).copy()

    df[
        "Raw_HHID"
    ] = df[
        "HHID"
    ].map(
        normalize_integer_text
    )

    df[
        "HHID"
    ] = df[
        "Raw_HHID"
    ].map(
        lambda value:
        canonicalize_hhid(
            value,
            visit
        )
    )

    df[
        "b13q5"
    ] = pd.to_numeric(
        df[
            "b13q5"
        ],
        errors="coerce"
    )

    negative_amount = int(
        (
            df[
                "b13q5"
            ]
            <
            0
        ).sum()
    )

    if negative_amount:

        raise ValueError(
            f"{visit} Level 15 contains "
            "negative kind-loan values."
        )

    print(
        f"  Rows                    : "
        f"{len(df):,}"
    )

    print(
        f"  Canonical HHID          : "
        f"{df['HHID'].nunique():,}"
    )

    if visit == "Visit 2":

        print(
            "  Visit-2 HHID mapping    : "
            "last digit 2 -> 1"
        )

    print(
        f"  Negative debt amount    : "
        f"{negative_amount:,}"
    )

    return df


# ============================================================
# CASH-LOAN HOUSEHOLD SUMMARY
# ============================================================
def build_cash_summary(
    cash,
    suffix,
    base_date_name
):

    # ========================================================
    # REMOVE TOTAL / CONTROL ROW
    #
    # b12q1 = 99 is the household total.
    # Individual loan rows already sum to that total.
    # Including both doubles the debt amount.
    # ========================================================

    total_row_count = int(
        (
            cash[
                "b12q1"
            ]
            ==
            "99"
        ).sum()
    )

    print(
        f"  Excluding b12q1=99 totals: "
        f"{total_row_count:,}"
    )

    df = cash.loc[
        cash[
            "b12q1"
        ]
        !=
        "99"
    ].copy()

    # ========================================================
    # CREATE REQUIRED AMOUNT COLUMNS
    # ========================================================

    # Outstanding debt as on survey date.
    # Retained only as auxiliary information.
    df[
        "Survey_Amount"
    ] = pd.to_numeric(
        df[
            "b12q13"
        ],
        errors="coerce"
    ).fillna(
        0
    )

    # Outstanding cash debt at fixed reference date.
    #
    # Visit 1:
    #   b12q15 -> 30.06.2018
    #
    # Visit 2:
    #   b12q15 -> corresponding Visit-2 fixed date
    df[
        "Base_Amount"
    ] = pd.to_numeric(
        df[
            "b12q15"
        ],
        errors="coerce"
    ).fillna(
        0
    )

    # ========================================================
    # CREDIT AGENCY GROUPS
    # ========================================================

    institutional_codes = {
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "10",
        "11",
        "12",
        "13",
    }

    noninstitutional_codes = {
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
    }

    # ========================================================
    # INSTITUTIONAL / NON-INSTITUTIONAL
    # ========================================================

    df[
        "Institutional_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ].isin(
            institutional_codes
        ),
        0
    )

    df[
        "NonInstitutional_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ].isin(
            noninstitutional_codes
        ),
        0
    )

    # ========================================================
    # SPECIFIC AGENCIES
    # ========================================================

    df[
        "SCB_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ]
        ==
        "1",
        0
    )

    df[
        "RRB_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ]
        ==
        "2",
        0
    )

    df[
        "RCB_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ].isin(
            {
                "3",
                "4",
            }
        ),
        0
    )

    df[
        "NBFC_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ]
        ==
        "10",
        0
    )

    # ========================================================
    # NON-INSTITUTIONAL SOURCES
    # ========================================================

    df[
        "Landlord_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ]
        ==
        "14",
        0
    )

    df[
        "Moneylender_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ].isin(
            {
                "15",
                "16",
            }
        ),
        0
    )

    df[
        "InputSupplier_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ]
        ==
        "17",
        0
    )

    df[
        "RelativesFriends_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q3"
        ]
        ==
        "18",
        0
    )

    # ========================================================
    # NATURE OF INTEREST
    # ========================================================

    df[
        "InterestFree_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q6"
        ]
        ==
        "1",
        0
    )

    df[
        "SimpleInterest_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q6"
        ]
        ==
        "2",
        0
    )

    df[
        "CompoundInterest_Amount"
    ] = df[
        "Base_Amount"
    ].where(
        df[
            "b12q6"
        ]
        ==
        "3",
        0
    )

    # ========================================================
    # HOUSEHOLD AGGREGATION
    # ========================================================

    sum_columns = [
        "Survey_Amount",
        "Base_Amount",

        "Institutional_Amount",
        "NonInstitutional_Amount",

        "SCB_Amount",
        "RRB_Amount",
        "RCB_Amount",
        "NBFC_Amount",

        "Landlord_Amount",
        "Moneylender_Amount",
        "InputSupplier_Amount",
        "RelativesFriends_Amount",

        "InterestFree_Amount",
        "SimpleInterest_Amount",
        "CompoundInterest_Amount",
    ]

    result = (
        df.groupby(
            "HHID",
            as_index=False
        )[
            sum_columns
        ]
        .sum()
    )

    # ========================================================
    # OUTPUT COLUMN NAMES
    # ========================================================

    rename = {

        "Survey_Amount":
            f"Cash_Debt_SurveyDate_{suffix}",

        "Base_Amount":
            f"Cash_Debt_{base_date_name}_{suffix}",

        "Institutional_Amount":
            f"Institutional_Debt_{suffix}",

        "NonInstitutional_Amount":
            f"NonInstitutional_Debt_{suffix}",

        "SCB_Amount":
            f"SCB_Debt_{suffix}",

        "RRB_Amount":
            f"RRB_Debt_{suffix}",

        "RCB_Amount":
            f"RCB_Debt_{suffix}",

        "NBFC_Amount":
            f"NBFC_Debt_{suffix}",

        "Landlord_Amount":
            f"Landlord_Debt_{suffix}",

        "Moneylender_Amount":
            f"Moneylender_Debt_{suffix}",

        "InputSupplier_Amount":
            f"InputSupplier_Debt_{suffix}",

        "RelativesFriends_Amount":
            f"RelativesFriends_Debt_{suffix}",

        "InterestFree_Amount":
            f"InterestFree_Debt_{suffix}",

        "SimpleInterest_Amount":
            f"SimpleInterest_Debt_{suffix}",

        "CompoundInterest_Amount":
            f"CompoundInterest_Debt_{suffix}",
    }

    result = result.rename(
        columns=rename
    )

    print(
        f"  Detail loan rows used        : "
        f"{len(df):,}"
    )

    print(
        f"  HH with loan details         : "
        f"{result['HHID'].nunique():,}"
    )

    return result


# ============================================================
# KIND LOAN HOUSEHOLD SUMMARY
# ============================================================

def build_kind_summary(
    kind,
    suffix
):

    result = (
        kind.groupby(
            "HHID",
            as_index=False
        )[
            "b13q5"
        ]
        .sum(
            min_count=1
        )
        .rename(
            columns={
                "b13q5":
                    f"Kind_Debt_SurveyDate_{suffix}"
            }
        )
    )

    result[
        f"Kind_Debt_SurveyDate_{suffix}"
    ] = result[
        f"Kind_Debt_SurveyDate_{suffix}"
    ].fillna(
        0
    )

    return result


# ============================================================
# ADD VISIT
# ============================================================

def add_visit(
    base,
    visit,
    suffix,
    base_date_name,
    cash_file,
    kind_file
):

    cash = load_cash_loans(
        visit
    )

    kind = load_kind_loans(
        visit
    )

    base_ids = set(
        base[
            "HHID"
        ]
    )

    unknown_cash = (
        set(
            cash[
                "HHID"
            ]
        )
        -
        base_ids
    )

    unknown_kind = (
        set(
            kind[
                "HHID"
            ]
        )
        -
        base_ids
    )

    print(
        f"\n{visit} linkage:"
    )

    print(
        f"  Unknown cash-loan HHID: "
        f"{len(unknown_cash):,}"
    )

    print(
        f"  Unknown kind-loan HHID: "
        f"{len(unknown_kind):,}"
    )

    if unknown_cash or unknown_kind:

        raise ValueError(
            f"{visit}: debt HHID linkage failed."
        )

    # --------------------------------------------------------
    # Save normalized detail BEFORE any grouping.
    # q13 and q15 both remain available.
    # --------------------------------------------------------

    cash.to_csv(
        cash_file,
        index=False,
        encoding="utf-8"
    )

    kind.to_csv(
        kind_file,
        index=False,
        encoding="utf-8"
    )

    cash_summary = build_cash_summary(
        cash,
        suffix,
        base_date_name
    )

    kind_summary = build_kind_summary(
        kind,
        suffix
    )

    output = base.merge(
        cash_summary,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    output = output.merge(
        kind_summary,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    added_columns = [
        column
        for column in output.columns
        if column.endswith(
            f"_{suffix}"
        )
    ]

    for column in added_columns:

        output[
            column
        ] = pd.to_numeric(
            output[
                column
            ],
            errors="coerce"
        ).fillna(
            0
        )

    official_cash_column = (
        f"Cash_Debt_"
        f"{base_date_name}_"
        f"{suffix}"
    )

    output[
        f"Indebted_Flag_{suffix}"
    ] = (
        output[
            official_cash_column
        ]
        >
        0
    ).astype(int)

    return output


# ============================================================
# WEIGHTED KPI
# ============================================================

def calculate_kpis(
    df,
    debt_column,
    indebted_column
):

    weights = pd.to_numeric(
        df[
            "MLT"
        ],
        errors="coerce"
    ).fillna(
        0
    )

    debt = pd.to_numeric(
        df[
            debt_column
        ],
        errors="coerce"
    ).fillna(
        0
    )

    indebted = (
        df[
            indebted_column
        ]
        ==
        1
    )

    all_weight = weights.sum()

    indebted_weight = (
        weights[
            indebted
        ].sum()
    )

    weighted_debt = (
        debt
        *
        weights
    ).sum()

    aod = (
        weighted_debt
        /
        all_weight
        if all_weight
        else 0
    )

    aodl = (
        weighted_debt
        /
        indebted_weight
        if indebted_weight
        else 0
    )

    ioi = (
        indebted_weight
        /
        all_weight
        *
        100
        if all_weight
        else 0
    )

    return (
        aod,
        aodl,
        ioi,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS NSS 77 - STEP 04 BUILD "
        "DEBT AND CREDIT FACTS - CORRECTED"
    )

    print(
        "=" * 78
    )

    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    base = load_base()

    print(
        f"\nHousehold base rows: "
        f"{len(base):,}"
    )

    # ========================================================
    # VISIT 1
    #
    # b12q15 = debt outstanding as on 30.06.2018
    # This is the official Report-588 debt position.
    # ========================================================

    working = add_visit(
        base=base,
        visit="Visit 1",
        suffix="V1",
        base_date_name="30062018",
        cash_file=CASH_V1_FILE,
        kind_file=KIND_V1_FILE
    )

    # ========================================================
    # VISIT 2
    #
    # Preserved as 30.06.2019 auxiliary debt position.
    # It does NOT replace the official 30.06.2018 published KPI.
    # ========================================================

    working = add_visit(
        base=working,
        visit="Visit 2",
        suffix="V2",
        base_date_name="30062019",
        cash_file=CASH_V2_FILE,
        kind_file=KIND_V2_FILE
    )

    # ========================================================
    # STRUCTURAL VALIDATION
    # ========================================================

    duplicate_hhid = int(
        working[
            "HHID"
        ].duplicated().sum()
    )

    negative_v1 = int(
        (
            working[
                "Cash_Debt_30062018_V1"
            ]
            <
            0
        ).sum()
    )

    negative_v2 = int(
        (
            working[
                "Cash_Debt_30062019_V2"
            ]
            <
            0
        ).sum()
    )

    print(
        "\n" + "=" * 78
    )

    print(
        "DEBT FACT VALIDATION"
    )

    print(
        "=" * 78
    )

    print(
        f"\nRows                 : "
        f"{len(working):,}"
    )

    print(
        f"Unique HHID          : "
        f"{working['HHID'].nunique():,}"
    )

    print(
        f"Duplicate HHID       : "
        f"{duplicate_hhid:,}"
    )

    print(
        f"Negative V1 debt     : "
        f"{negative_v1:,}"
    )

    print(
        f"Negative V2 debt     : "
        f"{negative_v2:,}"
    )

    print(
        f"Indebted HH V1       : "
        f"{int(working['Indebted_Flag_V1'].sum()):,}"
    )

    print(
        f"Indebted HH V2       : "
        f"{int(working['Indebted_Flag_V2'].sum()):,}"
    )

    if (
        duplicate_hhid
        or
        negative_v1
        or
        negative_v2
    ):

        raise ValueError(
            "Debt fact validation failed."
        )

    # ========================================================
    # OFFICIAL VISIT-1 30.06.2018 KPIs
    # ========================================================

    aod_all, aodl_all, ioi_all = (
        calculate_kpis(
            working,
            "Cash_Debt_30062018_V1",
            "Indebted_Flag_V1"
        )
    )

    rural = working[
        working[
            "Sector"
        ]
        ==
        "1"
    ].copy()

    urban = working[
        working[
            "Sector"
        ]
        ==
        "2"
    ].copy()

    rural_aod, rural_aodl, rural_ioi = (
        calculate_kpis(
            rural,
            "Cash_Debt_30062018_V1",
            "Indebted_Flag_V1"
        )
    )

    urban_aod, urban_aodl, urban_ioi = (
        calculate_kpis(
            urban,
            "Cash_Debt_30062018_V1",
            "Indebted_Flag_V1"
        )
    )

    print(
        "\n" + "=" * 78
    )

    print(
        "OFFICIAL 30.06.2018 DEBT CONTROL CHECK"
    )

    print(
        "=" * 78
    )

    print(
        f"\nAll India AOD       : "
        f"{aod_all:,.2f}"
    )

    print(
        f"All India AODL      : "
        f"{aodl_all:,.2f}"
    )

    print(
        f"All India IOI       : "
        f"{ioi_all:.4f}%"
    )

    print(
        "\nRural:"
    )

    print(
        f"  Calculated AOD    : "
        f"{rural_aod:,.2f}"
    )

    print(
        f"  Official AOD      : "
        f"{OFFICIAL_RURAL_AOD:,.2f}"
    )

    print(
        f"  Calculated IOI    : "
        f"{rural_ioi:.4f}%"
    )

    print(
        f"  Official IOI      : "
        f"{OFFICIAL_RURAL_IOI:.4f}%"
    )

    print(
        "\nUrban:"
    )

    print(
        f"  Calculated AOD    : "
        f"{urban_aod:,.2f}"
    )

    print(
        f"  Official AOD      : "
        f"{OFFICIAL_URBAN_AOD:,.2f}"
    )

    print(
        f"  Calculated IOI    : "
        f"{urban_ioi:.4f}%"
    )

    print(
        f"  Official IOI      : "
        f"{OFFICIAL_URBAN_IOI:.4f}%"
    )

    # ========================================================
    # SAVE
    # ========================================================

    working.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8",
        lineterminator="\n"
    )

    summary = [
        "=" * 78,
        "AIDIS NSS 77 - CORRECTED DEBT/CREDIT FACT SUMMARY",
        "=" * 78,
        "",
        f"Household rows       : {len(working):,}",
        f"Unique HHID          : {working['HHID'].nunique():,}",
        f"Duplicate HHID       : {duplicate_hhid:,}",
        "",
        "Official debt basis : Visit 1 / cash loans / 30.06.2018",
        "",
        f"Indebted HH V1       : {int(working['Indebted_Flag_V1'].sum()):,}",
        "",
        f"All India AOD        : {aod_all:,.2f}",
        f"All India AODL       : {aodl_all:,.2f}",
        f"All India IOI        : {ioi_all:.4f}%",
        "",
        f"Rural calculated AOD : {rural_aod:,.2f}",
        f"Rural official AOD   : {OFFICIAL_RURAL_AOD:,.2f}",
        f"Rural calculated IOI : {rural_ioi:.4f}%",
        f"Rural official IOI   : {OFFICIAL_RURAL_IOI:.4f}%",
        "",
        f"Urban calculated AOD : {urban_aod:,.2f}",
        f"Urban official AOD   : {OFFICIAL_URBAN_AOD:,.2f}",
        f"Urban calculated IOI : {urban_ioi:.4f}%",
        f"Urban official IOI   : {OFFICIAL_URBAN_IOI:.4f}%",
        "",
        "Visit 2 30.06.2019 position retained separately.",
        "Kind loans retained separately and not added to published AOD.",
        "",
        "STEP 04 STATUS       : PASS",
        "=" * 78,
    ]

    SUMMARY_REPORT.write_text(
        "\n".join(
            summary
        ),
        encoding="utf-8"
    )

    print(
        "\n" + "\n".join(
            summary
        )
    )

    print(
        "\nCreated:"
    )

    print(
        OUTPUT_FILE
    )

    print(
        CASH_V1_FILE
    )

    print(
        CASH_V2_FILE
    )

    print(
        KIND_V1_FILE
    )

    print(
        KIND_V2_FILE
    )

    print(
        SUMMARY_REPORT
    )

    print(
        "\nSTEP 04 STATUS: PASS"
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            "\n" + "=" * 78
        )

        print(
            "STEP 04 DEBT/CREDIT BUILD: FAIL"
        )

        print(
            "=" * 78
        )

        print(
            f"\n{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)