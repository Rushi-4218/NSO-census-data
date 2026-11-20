from pathlib import Path
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import csv
import math
import sys

import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = (
    ROOT
    / "input"
    / "raw"
    / "Debt and Investment 77th RoundJANUARY 2019 – DECEMBER 2019-Visit 1 and Visit 2"
)

CACHE_DIR = ROOT / "cache"
CONFIG_DIR = ROOT / "config"
FINAL_DIR = ROOT / "output" / "final"
REPORT_DIR = ROOT / "output" / "reports"

BASE_FILE = (
    CACHE_DIR
    / "household_base_visit1.csv"
)

ASSET_FILE = (
    CACHE_DIR
    / "household_asset_facts_visit1.csv"
)

DEBT_FILE = (
    CACHE_DIR
    / "household_debt_credit_facts.csv"
)

LOAN_DETAIL_FILE = (
    CACHE_DIR
    / "cash_loan_detail_visit1.csv"
)

DISTRICT_MASTER_FILE = (
    CONFIG_DIR
    / "district_master.csv"
)

FINAL_FILE = (
    FINAL_DIR
    / "AIDIS_All_India_States_Districts_Final.csv"
)

SUMMARY_FILE = (
    REPORT_DIR
    / "step05_final_export_summary.txt"
)


# ============================================================
# CLIENT METADATA
# ============================================================

SURVEY_ID = "AIDIS_77_2019"

SURVEY_NAME = (
    "All India Debt and Investment Survey "
    "(AIDIS), 77th Round"
)

YEAR = 2019

FREQ_DESC = "Annual"

PUBLISHED_DATE = "10-Sep-2021"

EXTRACTED_DATE = (
    datetime.now().strftime(
        "%d-%b-%Y"
    )
)

SOURCE = (
    "https://microdata.gov.in/"
    "NADA/index.php/catalog/156"
)


REFERENCE_COLUMNS = [
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
# STATE MASTER
# ============================================================

STATE_NAMES = {

    1: "JAMMU & KASHMIR",
    2: "HIMACHAL PRADESH",
    3: "PUNJAB",
    4: "CHANDIGARH",
    5: "UTTARAKHAND",
    6: "HARYANA",
    7: "DELHI",
    8: "RAJASTHAN",
    9: "UTTAR PRADESH",
    10: "BIHAR",
    11: "SIKKIM",
    12: "ARUNACHAL PRADESH",
    13: "NAGALAND",
    14: "MANIPUR",
    15: "MIZORAM",
    16: "TRIPURA",
    17: "MEGHALAYA",
    18: "ASSAM",
    19: "WEST BENGAL",
    20: "JHARKHAND",
    21: "ODISHA",
    22: "CHHATTISGARH",
    23: "MADHYA PRADESH",
    24: "GUJARAT",
    25: "DAMAN & DIU",
    26: "DADRA & NAGAR HAVELI",
    27: "MAHARASHTRA",
    28: "ANDHRA PRADESH",
    29: "KARNATAKA",
    30: "GOA",
    31: "LAKSHADWEEP",
    32: "KERALA",
    33: "TAMIL NADU",
    34: "PUDUCHERRY",
    35: "ANDAMAN & NICOBAR ISLANDS",
    36: "TELANGANA",
}


# ============================================================
# CREDIT AGENCY GROUPS
# ============================================================

INST_CODES = (
    {
        str(i)
        for i in range(
            1,
            9
        )
    }
    |
    {
        "10",
        "11",
        "12",
        "13",
    }
)

NONINST_CODES = {
    str(i)
    for i in range(
        14,
        21
    )
}


# ============================================================
# LOAN PURPOSES
# ============================================================

PURPOSE_LABELS = {

    "00":
        "All purposes",

    "01":
        "Capital expenditure in farm business",

    "02":
        "Revenue expenditure in farm business",

    "03":
        "Capital expenditure in non-farm business",

    "04":
        "Revenue expenditure in non-farm business",

    "05":
        "Litigation",

    "06":
        "Repayment of debt",

    "07":
        "Financial investment",

    "08":
        "Education",

    "09":
        "Others",

    "10":
        "Medical treatment",

    "11":
        "Housing",

    "12":
        "Other household expenditure",
}


# ============================================================
# ASSET COMPONENTS
# ============================================================

ASSET_COMPONENTS = [

    (
        "AVA_COMPONENT_PHYSICAL_ASSETS",
        "Physical assets",
        "Physical_Asset_Value",
    ),

    (
        "AVA_COMPONENT_FINANCIAL_ASSETS",
        "Financial assets",
        "Financial_Asset_Value",
    ),

    (
        "AVA_COMPONENT_LAND",
        "Land",
        "Land_Value",
    ),

    (
        "AVA_COMPONENT_BUILDINGS",
        "Buildings",
        "Building_Value",
    ),

    (
        "AVA_COMPONENT_DEPOSITS",
        "Deposits",
        "Deposits_Value",
    ),

    (
        "AVA_COMPONENT_LIVESTOCK_POULTRY",
        "Livestock & poultry",
        "Livestock_Value",
    ),

    (
        "AVA_COMPONENT_AGRICULTURAL_MACHINERY_EQUIPMENT",
        "Agricultural machinery & equipment",
        "Agri_Machinery_Value",
    ),

    (
        "AVA_COMPONENT_TRANSPORT_EQUIPMENT",
        "Transport equipment",
        "Transport_Value",
    ),

    (
        "AVA_COMPONENT_NON_FARM_BUSINESS_EQUIPMENT",
        "Non-farm business equipment",
        "NonFarm_Business_Value",
    ),

    (
        "AVA_COMPONENT_OTHERS",
        "Others",
        "Other_Financial_Excl_Shares_Value",
    ),
]


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):

    if value is None:
        return ""

    if pd.isna(value):
        return ""

    value = str(
        value
    ).strip()

    if value.lower() in {
        "nan",
        "none",
        "<na>",
    }:
        return ""

    return value


def norm_int(value):

    value = clean_text(
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


def norm_comp(value):

    value = norm_int(
        value
    )

    if not value:
        return ""

    return value.zfill(
        4
    )


def canonical_hhid(
    value,
    visit
):

    value = norm_int(
        value
    )

    if not value:
        return ""

    if visit == 1:
        return value

    if visit == 2:

        if value.endswith(
            "2"
        ):

            return (
                value[:-1]
                +
                "1"
            )

        return value

    return value


# ============================================================
# ROUND DATA TO 10 SIGNIFICANT DIGITS
# ============================================================

def round_sig(
    value,
    sig=10
):

    if value is None:
        return ""

    try:

        x = float(
            value
        )

    except Exception:

        return ""

    if not math.isfinite(
        x
    ):
        return ""

    if x == 0:
        return "0"

    d = Decimal(
        str(x)
    )

    exp = (
        d.adjusted()
        -
        sig
        +
        1
    )

    q = Decimal(
        "1e{}".format(
            exp
        )
    )

    d = d.quantize(
        q,
        rounding=ROUND_HALF_UP
    )

    text = format(
        d,
        "f"
    )

    if "." in text:

        text = (
            text
            .rstrip("0")
            .rstrip(".")
        )

    if text in {
        "-0",
        "",
    }:
        return "0"

    return text


# ============================================================
# FIND RAW FILE
# ============================================================

def find_raw(
    visit,
    level
):

    matches = list(
        RAW_DIR.glob(
            f"Visit{visit}  "
            f"Level - {level:02d}*.xlsx"
        )
    )

    if len(matches) != 1:

        raise FileNotFoundError(
            f"Expected exactly one "
            f"Visit{visit} Level-{level:02d} "
            f"file; found {len(matches)}:\n"
            f"{matches}"
        )

    return matches[0]


# ============================================================
# WEIGHTED FUNCTIONS
# ============================================================

def weighted_sum(
    df,
    value_col
):

    if df.empty:
        return 0.0

    values = pd.to_numeric(
        df[
            value_col
        ],
        errors="coerce"
    ).fillna(
        0.0
    )

    weights = pd.to_numeric(
        df[
            "MLT"
        ],
        errors="coerce"
    ).fillna(
        0.0
    )

    return float(
        (
            values
            *
            weights
        ).sum()
    )


def weighted_mean(
    df,
    value_col
):

    if df.empty:
        return 0.0

    weights = pd.to_numeric(
        df[
            "MLT"
        ],
        errors="coerce"
    ).fillna(
        0.0
    )

    denominator = float(
        weights.sum()
    )

    if denominator == 0:
        return 0.0

    return (
        weighted_sum(
            df,
            value_col
        )
        /
        denominator
    )


# ============================================================
# WEIGHTED GINI
# ============================================================

def weighted_gini(
    df,
    value_col="Total_Asset_Value"
):

    if df.empty:
        return 0.0

    x = pd.to_numeric(
        df[
            value_col
        ],
        errors="coerce"
    ).fillna(
        0.0
    ).to_numpy(
        dtype=float
    )

    weights = pd.to_numeric(
        df[
            "MLT"
        ],
        errors="coerce"
    ).fillna(
        0.0
    ).to_numpy(
        dtype=float
    )

    keep = (
        (weights > 0)
        &
        np.isfinite(x)
        &
        np.isfinite(weights)
    )

    x = x[
        keep
    ]

    weights = weights[
        keep
    ]

    if len(x) == 0:
        return 0.0

    order = np.argsort(
        x,
        kind="mergesort"
    )

    x = x[
        order
    ]

    weights = weights[
        order
    ]

    total_weight = (
        weights.sum()
    )

    total_asset = (
        x
        *
        weights
    ).sum()

    if (
        total_weight <= 0
        or
        total_asset <= 0
    ):
        return 0.0

    population_share = np.concatenate(
        (
            [0.0],
            np.cumsum(
                weights
            )
            /
            total_weight
        )
    )

    asset_share = np.concatenate(
        (
            [0.0],
            np.cumsum(
                x
                *
                weights
            )
            /
            total_asset
        )
    )

    area = np.trapz(
        asset_share,
        population_share
    )

    gini = (
        1.0
        -
        2.0
        *
        area
    )

    return float(
        max(
            0.0,
            min(
                1.0,
                gini
            )
        )
    )


# ============================================================
# WEIGHTED ASSET DECILES
# ============================================================

def with_weighted_deciles(
    df
):

    result = df.copy()

    if result.empty:

        result[
            "Asset_Decile"
        ] = pd.Series(
            dtype="int64"
        )

        return result

    result = result.sort_values(
        [
            "Total_Asset_Value",
            "HHID",
        ],
        kind="mergesort"
    ).copy()

    weights = pd.to_numeric(
        result[
            "MLT"
        ],
        errors="coerce"
    ).fillna(
        0.0
    ).clip(
        lower=0.0
    )

    total_weight = float(
        weights.sum()
    )

    if total_weight <= 0:

        result[
            "Asset_Decile"
        ] = 1

        return result

    midpoint = (
        weights.cumsum()
        -
        (
            weights
            /
            2.0
        )
    ) / total_weight

    decile = (
        np.floor(
            midpoint
            *
            10.0
        ).astype(int)
        +
        1
    )

    result[
        "Asset_Decile"
    ] = np.clip(
        decile,
        1,
        10
    )

    return result


# ============================================================
# HOUSEHOLD CLASSIFICATION
# ============================================================

def classify_household(
    sector,
    b4q4
):

    sector = norm_int(
        sector
    )

    code = norm_int(
        b4q4
    )

    if sector == "1":

        if code == "1":
            return "Cultivator HH"

        return "Non-Cultivator HH"

    if sector == "2":

        if code == "1":
            return "Self-employed"

        return "Others"

    return "All HH"


# ============================================================
# DISTRICT LOOKUP
# ============================================================

def load_district_lookup():

    if not DISTRICT_MASTER_FILE.exists():

        raise FileNotFoundError(
            f"Missing district master:\n"
            f"{DISTRICT_MASTER_FILE}"
        )

    dm = pd.read_csv(
        DISTRICT_MASTER_FILE,
        dtype=str,
        low_memory=False
    )

    cols = {
        column.lower():
            column
        for column in dm.columns
    }

    name_col = cols.get(
        "district_name"
    )

    if not name_col:

        raise ValueError(
            "district_master.csv must "
            "contain District_Name"
        )

    comp_col = (
        cols.get(
            "state_district"
        )
        or
        cols.get(
            "district_id"
        )
    )

    state_col = (
        cols.get(
            "state_id"
        )
        or
        cols.get(
            "state"
        )
    )

    district_code_col = (
        cols.get(
            "district_code"
        )
        or
        cols.get(
            "district"
        )
    )

    lookup = {}

    for _, row in dm.iterrows():

        if (
            comp_col
            and
            clean_text(
                row.get(
                    comp_col
                )
            )
        ):

            key = norm_comp(
                row.get(
                    comp_col
                )
            )

        elif (
            state_col
            and
            district_code_col
        ):

            key = (
                f"{int(float(row[state_col])):02d}"
                f"{int(float(row[district_code_col])):02d}"
            )

        else:

            raise ValueError(
                "district_master.csv requires "
                "State_District/District_ID "
                "or State_ID + District_Code"
            )

        lookup[
            key
        ] = clean_text(
            row[
                name_col
            ]
        )

    return lookup


# ============================================================
# FCE + EPL
#
# Block 14:
#
# Farm business = items 4-16
# Non-farm business = items 17-21
#
# FCE = total expenditure b14q7
#       for items 4-21
#
# EPL land rows:
#       1  = residential land
#       4  = farm-business land
#       17 = non-farm-business land
#
# Visit 1 + Visit 2 are combined.
# ============================================================

def build_fce_epl():

    pieces = []

    for visit in (
        1,
        2
    ):

        path = find_raw(
            visit,
            16
        )

        print(
            "Reading FCE/EPL source:"
        )

        print(
            f"  {path.name}"
        )

        df = pd.read_excel(
            path,
            sheet_name="Sheet1",
            usecols=[
                "HHID",
                "b14q2",
                "b14q3",
                "b14q7",
            ],
            dtype=str,
            engine="openpyxl"
        )

        df[
            "HHID"
        ] = df[
            "HHID"
        ].map(
            lambda value:
            canonical_hhid(
                value,
                visit
            )
        )

        df[
            "b14q2"
        ] = df[
            "b14q2"
        ].map(
            norm_int
        )

        df[
            "b14q3"
        ] = pd.to_numeric(
            df[
                "b14q3"
            ],
            errors="coerce"
        ).fillna(
            0.0
        )

        df[
            "b14q7"
        ] = pd.to_numeric(
            df[
                "b14q7"
            ],
            errors="coerce"
        ).fillna(
            0.0
        )

        business_codes = {
            str(i)
            for i in range(
                4,
                22
            )
        }

        df[
            "FCE"
        ] = df[
            "b14q7"
        ].where(
            df[
                "b14q2"
            ].isin(
                business_codes
            ),
            0.0
        )

        df[
            "EPL"
        ] = df[
            "b14q3"
        ].where(
            df[
                "b14q2"
            ].isin(
                {
                    "1",
                    "4",
                    "17",
                }
            ),
            0.0
        )

        household = (
            df.groupby(
                "HHID",
                as_index=False
            )[
                [
                    "FCE",
                    "EPL",
                ]
            ]
            .sum()
        )

        pieces.append(
            household
        )

    annual = (
        pd.concat(
            pieces,
            ignore_index=True
        )
        .groupby(
            "HHID",
            as_index=False
        )[
            [
                "FCE",
                "EPL",
            ]
        ]
        .sum()
    )

    return annual


# ============================================================
# BUILD HOUSEHOLD ANALYTICAL MASTER
# ============================================================

def load_master():

    print(
        "\nLoading household "
        "base/assets/debt..."
    )

    base = pd.read_csv(
        BASE_FILE,
        dtype=str,
        low_memory=False
    )

    assets = pd.read_csv(
        ASSET_FILE,
        dtype=str,
        low_memory=False
    )

    debt = pd.read_csv(
        DEBT_FILE,
        dtype=str,
        low_memory=False
    )

    if "b4q4" not in base.columns:

        raise ValueError(
            "household_base_visit1.csv "
            "does not contain b4q4. "
            "It is required for the "
            "Rural/Urban HH classification."
        )

    required_asset = [

        "HHID",
        "State",
        "State_District",
        "Sector",
        "MLT",

        "Total_Asset_Value",

        "Physical_Asset_Value",
        "Financial_Asset_Value",

        "Land_Value",
        "Building_Value",
        "Deposits_Value",

        "Livestock_Value",

        "Agri_Machinery_Value",

        "Transport_Value",

        "NonFarm_Business_Value",

        "Other_Financial_Excl_Shares_Value",
    ]

    missing = [
        column
        for column in required_asset
        if column not in assets.columns
    ]

    if missing:

        raise ValueError(
            f"Asset cache missing "
            f"columns:\n{missing}"
        )

    if (
        "Cash_Debt_30062018_V1"
        not in debt.columns
    ):

        raise ValueError(
            "Debt cache does not contain "
            "Cash_Debt_30062018_V1.\n"
            "Rerun corrected Step 04."
        )

    for frame in (
        base,
        assets,
        debt
    ):

        frame[
            "HHID"
        ] = frame[
            "HHID"
        ].map(
            norm_int
        )

    base_small = (
        base[
            [
                "HHID",
                "b4q4",
            ]
        ]
        .drop_duplicates(
            "HHID"
        )
    )

    debt_small = (
        debt[
            [
                "HHID",
                "Cash_Debt_30062018_V1",
            ]
        ]
        .drop_duplicates(
            "HHID"
        )
    )

    master = assets[
        required_asset
    ].copy()

    master = master.merge(
        base_small,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    master = master.merge(
        debt_small,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    master[
        "State"
    ] = master[
        "State"
    ].map(
        norm_int
    )

    master[
        "State_District"
    ] = master[
        "State_District"
    ].map(
        norm_comp
    )

    master[
        "Sector"
    ] = master[
        "Sector"
    ].map(
        norm_int
    )

    numeric_cols = [

        "MLT",

        "Total_Asset_Value",

        "Physical_Asset_Value",

        "Financial_Asset_Value",

        "Land_Value",

        "Building_Value",

        "Deposits_Value",

        "Livestock_Value",

        "Agri_Machinery_Value",

        "Transport_Value",

        "NonFarm_Business_Value",

        "Other_Financial_Excl_Shares_Value",

        "Cash_Debt_30062018_V1",
    ]

    for column in numeric_cols:

        master[
            column
        ] = pd.to_numeric(
            master[
                column
            ],
            errors="coerce"
        ).fillna(
            0.0
        )

    master[
        "HH_Category"
    ] = [

        classify_household(
            sector,
            hh_type
        )

        for sector, hh_type
        in zip(
            master[
                "Sector"
            ],
            master[
                "b4q4"
            ]
        )
    ]

    # --------------------------------------------------------
    # Add annual FCE/EPL
    # --------------------------------------------------------

    fce = build_fce_epl()

    unknown_fce = (
        set(
            fce[
                "HHID"
            ]
        )
        -
        set(
            master[
                "HHID"
            ]
        )
    )

    if unknown_fce:

        raise ValueError(
            f"FCE/EPL contains "
            f"{len(unknown_fce)} "
            "HHIDs outside Visit-1 base."
        )

    master = master.merge(
        fce,
        on="HHID",
        how="left",
        validate="one_to_one"
    )

    master[
        [
            "FCE",
            "EPL",
        ]
    ] = master[
        [
            "FCE",
            "EPL",
        ]
    ].fillna(
        0.0
    )

    if master[
        "HHID"
    ].duplicated().any():

        raise ValueError(
            "Duplicate HHID after "
            "building analytical master."
        )

    if len(master) != 116461:

        print(
            "WARNING:"
        )

        print(
            f"Household master rows "
            f"= {len(master):,}; "
            "expected 116,461"
        )

    return master


# ============================================================
# LOAD LOAN DETAILS
# ============================================================

def load_loans(
    master
):

    print(
        "\nLoading Visit-1 "
        "loan-detail cache..."
    )

    loan = pd.read_csv(
        LOAN_DETAIL_FILE,
        dtype=str,
        low_memory=False
    )

    needed = [

        "HHID",

        "b12q1",
        "b12q3",
        "b12q6",
        "b12q8",

        "b12q15",
    ]

    missing = [
        column
        for column in needed
        if column not in loan.columns
    ]

    if missing:

        raise ValueError(
            f"Loan detail cache "
            f"is missing:\n{missing}"
        )

    loan[
        "HHID"
    ] = loan[
        "HHID"
    ].map(
        norm_int
    )

    for column in [
        "b12q1",
        "b12q3",
        "b12q6",
        "b12q8",
    ]:

        loan[
            column
        ] = loan[
            column
        ].map(
            norm_int
        )

    # --------------------------------------------------------
    # Exclude household total row.
    # --------------------------------------------------------

    loan = loan[
        loan[
            "b12q1"
        ]
        !=
        "99"
    ].copy()

    loan[
        "Base_Amount"
    ] = pd.to_numeric(
        loan[
            "b12q15"
        ],
        errors="coerce"
    ).fillna(
        0.0
    )

    meta = master[
        [
            "HHID",
            "State",
            "State_District",
            "Sector",
            "HH_Category",
            "MLT",
        ]
    ]

    loan = loan.merge(
        meta,
        on="HHID",
        how="left",
        validate="many_to_one"
    )

    if loan[
        "State"
    ].isna().any():

        raise ValueError(
            "Loan detail contains "
            "HHIDs not found in "
            "household analytical master."
        )

    return loan


# ============================================================
# ADULT BANK-DEPOSIT POPULATION
# ============================================================

def load_adults(
    master
):

    path = find_raw(
        1,
        2
    )

    print(
        "\nReading adult "
        "bank-account source:"
    )

    print(
        f"  {path.name}"
    )

    members = pd.read_excel(
        path,
        sheet_name="Sheet1",
        usecols=[
            "HHID",
            "b3q4",
            "b3q5",
            "b3q7",
        ],
        dtype=str,
        engine="openpyxl"
    )

    members[
        "HHID"
    ] = members[
        "HHID"
    ].map(
        norm_int
    )

    members[
        "Gender"
    ] = members[
        "b3q4"
    ].map(
        norm_int
    )

    members[
        "Age"
    ] = pd.to_numeric(
        members[
            "b3q5"
        ],
        errors="coerce"
    )

    members[
        "Bank_Code"
    ] = members[
        "b3q7"
    ].map(
        norm_int
    )

    # Adults only.
    members = members[
        members[
            "Age"
        ]
        >=
        18
    ].copy()

    # Bank deposit account = codes 1, 2 or 3.
    members[
        "Has_Bank_Deposit"
    ] = members[
        "Bank_Code"
    ].isin(
        {
            "1",
            "2",
            "3",
        }
    ).astype(
        int
    )

    meta = master[
        [
            "HHID",
            "State",
            "State_District",
            "Sector",
            "HH_Category",
            "MLT",
        ]
    ]

    members = members.merge(
        meta,
        on="HHID",
        how="left",
        validate="many_to_one"
    )

    if members[
        "State"
    ].isna().any():

        raise ValueError(
            "Adult member file contains "
            "HHIDs not found in "
            "household analytical master."
        )

    return members


# ============================================================
# DOMAIN FILTER
# ============================================================

def subset_classification(
    df,
    sector_code,
    category
):

    if df is None:

        return pd.DataFrame()

    if df.empty:

        return df.copy()

    result = df

    if sector_code in (
        1,
        2
    ):

        result = result[
            result[
                "Sector"
            ]
            ==
            str(
                sector_code
            )
        ]

    if category != "All HH":

        result = result[
            result[
                "HH_Category"
            ]
            ==
            category
        ]

    return result


# ============================================================
# ADULT BANK PERCENTAGE
# ============================================================

def adult_bank_pct(
    adults,
    gender=None
):

    if adults is None:
        return 0.0

    if adults.empty:
        return 0.0

    if gender is None:

        selected = adults

    else:

        selected = adults[
            adults[
                "Gender"
            ]
            ==
            str(
                gender
            )
        ]

    if selected.empty:
        return 0.0

    weights = pd.to_numeric(
        selected[
            "MLT"
        ],
        errors="coerce"
    ).fillna(
        0.0
    )

    denominator = float(
        weights.sum()
    )

    if denominator == 0:
        return 0.0

    numerator = float(
        (
            weights
            *
            selected[
                "Has_Bank_Deposit"
            ].astype(float)
        ).sum()
    )

    return (
        numerator
        /
        denominator
        *
        100.0
    )


# ============================================================
# CALCULATE ALL 114 INDICATORS FOR ONE DOMAIN
# ============================================================

def domain_rows(
    households,
    loans,
    adults,
    category
):

    values = []

    weights = pd.to_numeric(
        households[
            "MLT"
        ],
        errors="coerce"
    ).fillna(
        0.0
    )

    denominator_weight = float(
        weights.sum()
    )

    debt_sum = weighted_sum(
        households,
        "Cash_Debt_30062018_V1"
    )

    asset_sum = weighted_sum(
        households,
        "Total_Asset_Value"
    )

    indebted = (
        households[
            "Cash_Debt_30062018_V1"
        ]
        >
        0
    )

    indebted_weight = float(
        weights[
            indebted
        ].sum()
    )

    # ========================================================
    # CORE INDICATORS
    # ========================================================

    core = {

        "AOD":
            (
                debt_sum
                /
                denominator_weight
                if denominator_weight
                else 0.0
            ),

        "AODL":
            (
                debt_sum
                /
                indebted_weight
                if indebted_weight
                else 0.0
            ),

        "AVA":
            (
                asset_sum
                /
                denominator_weight
                if denominator_weight
                else 0.0
            ),

        "DAR":
            (
                debt_sum
                /
                asset_sum
                if asset_sum
                else 0.0
            ),

        "HH_SURVEYED":
            float(
                households[
                    "HHID"
                ].nunique()
            ),

        "IOI":
            (
                indebted_weight
                /
                denominator_weight
                *
                100.0
                if denominator_weight
                else 0.0
            ),
    }

    core_desc = {

        "AOD":
            "Average Amount of Debt (AOD) per HH",

        "AODL":
            "Average Amount of Debt per Indebted Household (AODL)",

        "AVA":
            "Average Value of Assets (AVA)",

        "DAR":
            "Debt Asset Ratio (DAR)",

        "HH_SURVEYED":
            "No. of Households Surveyed",

        "IOI":
            "Incidence of Indebtedness (IOI)",
    }

    core_unit = {

        "AOD":
            "Rs. per HH",

        "AODL":
            "Rs.",

        "AVA":
            "Rs. per HH",

        "DAR":
            "Ratio",

        "HH_SURVEYED":
            "Number",

        "IOI":
            "%",
    }

    for col_id in [
        "AOD",
        "AODL",
        "AVA",
        "DAR",
        "HH_SURVEYED",
        "IOI",
    ]:

        values.append(
            (
                1,
                "Household Assets and Debt",
                col_id,

                f"{core_desc[col_id]} "
                f"- {category}",

                core[
                    col_id
                ],

                core_unit[
                    col_id
                ],
            )
        )

    # ========================================================
    # ASSET COMPONENTS
    # ========================================================

    for (
        col_id,
        label,
        value_column
    ) in ASSET_COMPONENTS:

        values.append(
            (
                2,

                "Assets by Component",

                col_id,

                f"Average Value of Assets "
                f"- {label} "
                f"- {category}",

                weighted_mean(
                    households,
                    value_column
                ),

                "Rs. per HH",
            )
        )

    # ========================================================
    # LOAN DETAIL
    # ========================================================

    if loans is None:

        loan = pd.DataFrame(
            columns=[
                "HHID",
                "b12q3",
                "b12q6",
                "b12q8",
                "Base_Amount",
                "MLT",
            ]
        )

    else:

        loan = loans.copy()

    if not loan.empty:

        loan[
            "Weighted_Amount"
        ] = (
            pd.to_numeric(
                loan[
                    "Base_Amount"
                ],
                errors="coerce"
            ).fillna(
                0.0
            )
            *
            pd.to_numeric(
                loan[
                    "MLT"
                ],
                errors="coerce"
            ).fillna(
                0.0
            )
        )

    else:

        loan[
            "Weighted_Amount"
        ] = pd.Series(
            dtype=float
        )

    def loan_amount(mask):

        if loan.empty:
            return 0.0

        return float(
            loan.loc[
                mask,
                "Weighted_Amount"
            ].sum()
        )

    if loan.empty:

        inst_mask = pd.Series(
            False,
            index=loan.index
        )

        non_mask = pd.Series(
            False,
            index=loan.index
        )

    else:

        inst_mask = loan[
            "b12q3"
        ].isin(
            INST_CODES
        )

        non_mask = loan[
            "b12q3"
        ].isin(
            NONINST_CODES
        )

    inst_total = loan_amount(
        inst_mask
    )

    non_total = loan_amount(
        non_mask
    )

    # ========================================================
    # INSTITUTIONAL SOURCES
    # ========================================================

    if loan.empty:

        scb = 0.0
        rrb = 0.0
        rcb = 0.0
        nbfc = 0.0

    else:

        scb = loan_amount(
            inst_mask
            &
            (
                loan[
                    "b12q3"
                ]
                ==
                "1"
            )
        )

        rrb = loan_amount(
            inst_mask
            &
            (
                loan[
                    "b12q3"
                ]
                ==
                "2"
            )
        )

        rcb = loan_amount(
            inst_mask
            &
            loan[
                "b12q3"
            ].isin(
                {
                    "3",
                    "4",
                }
            )
        )

        nbfc = loan_amount(
            inst_mask
            &
            (
                loan[
                    "b12q3"
                ]
                ==
                "10"
            )
        )

    other_inst = max(
        0.0,

        inst_total
        -
        scb
        -
        rrb
        -
        rcb
        -
        nbfc
    )

    # ========================================================
    # NON-INSTITUTIONAL SOURCES
    # ========================================================

    if loan.empty:

        landlord = 0.0
        moneylender = 0.0
        input_supplier = 0.0
        relatives = 0.0

    else:

        landlord = loan_amount(
            non_mask
            &
            (
                loan[
                    "b12q3"
                ]
                ==
                "14"
            )
        )

        moneylender = loan_amount(
            non_mask
            &
            loan[
                "b12q3"
            ].isin(
                {
                    "15",
                    "16",
                }
            )
        )

        input_supplier = loan_amount(
            non_mask
            &
            (
                loan[
                    "b12q3"
                ]
                ==
                "17"
            )
        )

        relatives = loan_amount(
            non_mask
            &
            (
                loan[
                    "b12q3"
                ]
                ==
                "18"
            )
        )

    other_non = max(
        0.0,

        non_total
        -
        landlord
        -
        moneylender
        -
        input_supplier
        -
        relatives
    )

    def share(
        amount,
        total
    ):

        if not total:
            return 0.0

        return (
            amount
            /
            total
            *
            100.0
        )

    credit_specs = [

        (
            "CREDIT_SOURCE_ALL_INSTITUTIONAL_SOURCES",

            "Distribution of Outstanding "
            "Institutional Credit - "
            "All institutional sources",

            (
                100.0
                if inst_total
                else 0.0
            ),
        ),

        (
            "CREDIT_SOURCE_SCBS",

            "Distribution of Outstanding "
            "Institutional Credit - SCBs",

            share(
                scb,
                inst_total
            ),
        ),

        (
            "CREDIT_SOURCE_RRBS",

            "Distribution of Outstanding "
            "Institutional Credit - RRBs",

            share(
                rrb,
                inst_total
            ),
        ),

        (
            "CREDIT_SOURCE_RCBS",

            "Distribution of Outstanding "
            "Institutional Credit - RCBs",

            share(
                rcb,
                inst_total
            ),
        ),

        (
            "CREDIT_SOURCE_NBFCS",

            "Distribution of Outstanding "
            "Institutional Credit - NBFCs",

            share(
                nbfc,
                inst_total
            ),
        ),

        (
            "CREDIT_SOURCE_OTHER_INSTITUTIONAL_AGENCIES",

            "Distribution of Outstanding "
            "Institutional Credit - "
            "Other institutional agencies",

            share(
                other_inst,
                inst_total
            ),
        ),

        (
            "CREDIT_SOURCE_ALL_NON_INSTITUTIONAL_SOURCES",

            "Distribution of Outstanding "
            "Non-Institutional Credit - "
            "All non-institutional sources",

            (
                100.0
                if non_total
                else 0.0
            ),
        ),

        (
            "CREDIT_SOURCE_LANDLORD",

            "Distribution of Outstanding "
            "Non-Institutional Credit - Landlord",

            share(
                landlord,
                non_total
            ),
        ),

        (
            "CREDIT_SOURCE_MONEYLENDER",

            "Distribution of Outstanding "
            "Non-Institutional Credit - Moneylender",

            share(
                moneylender,
                non_total
            ),
        ),

        (
            "CREDIT_SOURCE_INPUT_SUPPLIER",

            "Distribution of Outstanding "
            "Non-Institutional Credit - "
            "Input supplier",

            share(
                input_supplier,
                non_total
            ),
        ),

        (
            "CREDIT_SOURCE_RELATIVES_FRIENDS",

            "Distribution of Outstanding "
            "Non-Institutional Credit - "
            "Relatives & friends",

            share(
                relatives,
                non_total
            ),
        ),

        (
            "CREDIT_SOURCE_OTHER_NON_INSTITUTIONAL_AGENCIES",

            "Distribution of Outstanding "
            "Non-Institutional Credit - "
            "Other non-institutional agencies",

            share(
                other_non,
                non_total
            ),
        ),
    ]

    for (
        col_id,
        description,
        value
    ) in credit_specs:

        values.append(
            (
                3,

                "Outstanding Credit Distribution",

                col_id,

                f"{description} "
                f"- {category}",

                value,

                "%",
            )
        )

    # ========================================================
    # INSTITUTIONAL IOI BY INTEREST TYPE
    # ========================================================

    def household_ioi(mask):

        if loan.empty:
            return 0.0

        if denominator_weight == 0:
            return 0.0

        ids = set(
            loan.loc[
                mask
                &
                (
                    loan[
                        "Base_Amount"
                    ]
                    >
                    0
                ),
                "HHID"
            ]
            .dropna()
            .astype(str)
        )

        if not ids:
            return 0.0

        numerator = float(
            pd.to_numeric(
                households.loc[
                    households[
                        "HHID"
                    ].isin(
                        ids
                    ),
                    "MLT"
                ],
                errors="coerce"
            ).fillna(
                0.0
            ).sum()
        )

        return (
            numerator
            /
            denominator_weight
            *
            100.0
        )

    if loan.empty:

        mask_interest_1 = inst_mask
        mask_interest_2 = inst_mask
        mask_interest_3 = inst_mask

    else:

        mask_interest_1 = (
            inst_mask
            &
            (
                loan[
                    "b12q6"
                ]
                ==
                "1"
            )
        )

        mask_interest_2 = (
            inst_mask
            &
            (
                loan[
                    "b12q6"
                ]
                ==
                "2"
            )
        )

        mask_interest_3 = (
            inst_mask
            &
            (
                loan[
                    "b12q6"
                ]
                ==
                "3"
            )
        )

    institutional_ioi = [

        (
            "INST_IOI_0",
            "All",
            inst_mask
        ),

        (
            "INST_IOI_1",
            "Interest-free",
            mask_interest_1
        ),

        (
            "INST_IOI_2",
            "Simple interest",
            mask_interest_2
        ),

        (
            "INST_IOI_3",
            "Compound interest",
            mask_interest_3
        ),
    ]

    for (
        col_id,
        label,
        mask
    ) in institutional_ioi:

        values.append(
            (
                3,

                "Institutional Credit IOI",

                col_id,

                f"IOI for Institutional "
                f"Credit - {label} "
                f"- {category}",

                household_ioi(
                    mask
                ),

                "%",
            )
        )

    # ========================================================
    # CREDIT BY PURPOSE
    # ========================================================

    for (
        purpose_code,
        purpose_label
    ) in PURPOSE_LABELS.items():

        if purpose_code == "00":

            institutional_pct = (
                100.0
                if inst_total
                else 0.0
            )

            noninstitutional_pct = (
                100.0
                if non_total
                else 0.0
            )

        else:

            raw_code = str(
                int(
                    purpose_code
                )
            )

            if loan.empty:

                institutional_pct = 0.0
                noninstitutional_pct = 0.0

            else:

                institutional_pct = share(

                    loan_amount(
                        inst_mask
                        &
                        (
                            loan[
                                "b12q8"
                            ]
                            ==
                            raw_code
                        )
                    ),

                    inst_total
                )

                noninstitutional_pct = share(

                    loan_amount(
                        non_mask
                        &
                        (
                            loan[
                                "b12q8"
                            ]
                            ==
                            raw_code
                        )
                    ),

                    non_total
                )

        values.append(
            (
                3,

                "Credit by Purpose",

                f"PURPOSE_INST_{purpose_code}",

                "Distribution of Outstanding "
                "Institutional Credit "
                f"- Purpose: {purpose_label} "
                f"- {category}",

                institutional_pct,

                "%",
            )
        )

        values.append(
            (
                3,

                "Credit by Purpose",

                f"PURPOSE_NON_{purpose_code}",

                "Distribution of Outstanding "
                "Non-Institutional Credit "
                f"- Purpose: {purpose_label} "
                f"- {category}",

                noninstitutional_pct,

                "%",
            )
        )

    # ========================================================
    # ASSET DECILES
    # ========================================================

    deciles = with_weighted_deciles(
        households
    )

    for decile_number in range(
        1,
        11
    ):

        selected = deciles[
            deciles[
                "Asset_Decile"
            ]
            ==
            decile_number
        ]

        ava = weighted_mean(
            selected,
            "Total_Asset_Value"
        )

        aod = weighted_mean(
            selected,
            "Cash_Debt_30062018_V1"
        )

        decile_asset_sum = weighted_sum(
            selected,
            "Total_Asset_Value"
        )

        decile_debt_sum = weighted_sum(
            selected,
            "Cash_Debt_30062018_V1"
        )

        dar = (
            decile_debt_sum
            /
            decile_asset_sum
            if decile_asset_sum
            else 0.0
        )

        values.append(
            (
                4,

                "Asset Holding Deciles",

                f"DECILE_{decile_number}_AVA",

                f"Average Value of Assets "
                f"- Asset Decile {decile_number} "
                f"- {category}",

                ava,

                "Rs. per HH",
            )
        )

        values.append(
            (
                4,

                "Asset Holding Deciles",

                f"DECILE_{decile_number}_AOD",

                f"Average Amount of Debt "
                f"- Asset Decile {decile_number} "
                f"- {category}",

                aod,

                "Rs. per HH",
            )
        )

        values.append(
            (
                4,

                "Asset Holding Deciles",

                f"DECILE_{decile_number}_DAR",

                f"Debt Asset Ratio "
                f"- Asset Decile {decile_number} "
                f"- {category}",

                dar,

                "Ratio",
            )
        )

    # ========================================================
    # FCE + EPL
    # ========================================================

    values.append(
        (
            5,

            "Capital Expenditure",

            "FCE",

            "Average Fixed Capital "
            "Expenditure per HH "
            f"- {category}",

            weighted_mean(
                households,
                "FCE"
            ),

            "Rs. per HH",
        )
    )

    values.append(
        (
            5,

            "Capital Expenditure",

            "EPL",

            "Average Expenditure on "
            "Purchase of Land per HH "
            f"- {category}",

            weighted_mean(
                households,
                "EPL"
            ),

            "Rs. per HH",
        )
    )

    # FCE / EPL by asset decile
    for decile_number in range(
        1,
        11
    ):

        selected = deciles[
            deciles[
                "Asset_Decile"
            ]
            ==
            decile_number
        ]

        values.append(
            (
                5,

                "Capital Expenditure",

                f"FCE_DECILE_{decile_number}",

                "Average Fixed Capital "
                "Expenditure per HH "
                f"- Asset Decile {decile_number} "
                f"- {category}",

                weighted_mean(
                    selected,
                    "FCE"
                ),

                "Rs. per HH",
            )
        )

        values.append(
            (
                5,

                "Capital Expenditure",

                f"EPL_DECILE_{decile_number}",

                "Average Expenditure on "
                "Purchase of Land per HH "
                f"- Asset Decile {decile_number} "
                f"- {category}",

                weighted_mean(
                    selected,
                    "EPL"
                ),

                "Rs. per HH",
            )
        )

    # ========================================================
    # ADULT POPULATION HAVING BANK DEPOSIT ACCOUNT
    # ========================================================

    values.append(
        (
            6,

            "Financial Inclusion",

            "ADULT_BANK_TOTAL",

            "Adult Population (%) having "
            "deposit account in bank "
            f"- Total - {category}",

            adult_bank_pct(
                adults
            ),

            "%",
        )
    )

    values.append(
        (
            6,

            "Financial Inclusion",

            "ADULT_BANK_MALE",

            "Adult Population (%) having "
            "deposit account in bank "
            f"- Male - {category}",

            adult_bank_pct(
                adults,
                1
            ),

            "%",
        )
    )

    values.append(
        (
            6,

            "Financial Inclusion",

            "ADULT_BANK_FEMALE",

            "Adult Population (%) having "
            "deposit account in bank "
            f"- Female - {category}",

            adult_bank_pct(
                adults,
                2
            ),

            "%",
        )
    )

    # ========================================================
    # GINI
    # ========================================================

    values.append(
        (
            7,

            "Asset Inequality",

            "GINI_ASSET",

            "Gini Coefficient of "
            "Asset Holdings "
            f"- {category}",

            weighted_gini(
                households
            ),

            "Coefficient",
        )
    )

    # Exact client KPI coverage.
    if len(values) != 114:

        raise RuntimeError(
            "Internal indicator coverage "
            f"error: expected 114, "
            f"created {len(values)}."
        )

    return values


# ============================================================
# MAIN EXPORT
# ============================================================

def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS NSS 77 - STEP 05 "
        "FINAL KPI CALCULATION + CLIENT EXPORT"
    )

    print(
        "=" * 78
    )

    FINAL_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    district_lookup = (
        load_district_lookup()
    )

    master = load_master()

    loans = load_loans(
        master
    )

    adults = load_adults(
        master
    )

    print(
        "\n" + "=" * 78
    )

    print(
        "FINAL ANALYTICAL INPUT"
    )

    print(
        "=" * 78
    )

    print(
        f"\nHousehold master rows : "
        f"{len(master):,}"
    )

    print(
        f"Loan detail rows      : "
        f"{len(loans):,}"
    )

    print(
        f"Adult member rows     : "
        f"{len(adults):,}"
    )

    print(
        f"States/UTs            : "
        f"{master['State'].nunique():,}"
    )

    print(
        f"Districts             : "
        f"{master['State_District'].nunique():,}"
    )

    # ========================================================
    # PRE-GROUP LOANS / MEMBERS
    # ========================================================

    loan_state = {
        key: group
        for key, group
        in loans.groupby(
            "State",
            sort=False
        )
    }

    loan_district = {
        key: group
        for key, group
        in loans.groupby(
            "State_District",
            sort=False
        )
    }

    adult_state = {
        key: group
        for key, group
        in adults.groupby(
            "State",
            sort=False
        )
    }

    adult_district = {
        key: group
        for key, group
        in adults.groupby(
            "State_District",
            sort=False
        )
    }

    row_count = 0
    domain_count = 0
    col_ids = set()

    # ========================================================
    # WRITE ONE DOMAIN
    # ========================================================

    def emit_domain(
        writer,
        master_geo,
        loan_geo,
        adult_geo,
        state_id,
        state_name,
        district_id,
        district_name,
        sector_code,
        sector_name,
        category
    ):

        nonlocal row_count
        nonlocal domain_count

        household_domain = (
            subset_classification(
                master_geo,
                sector_code,
                category
            )
        )

        if household_domain.empty:
            return

        loan_domain = (
            subset_classification(
                loan_geo,
                sector_code,
                category
            )
            if loan_geo is not None
            else pd.DataFrame()
        )

        adult_domain = (
            subset_classification(
                adult_geo,
                sector_code,
                category
            )
            if adult_geo is not None
            else pd.DataFrame()
        )

        calculated = domain_rows(
            household_domain,
            loan_domain,
            adult_domain,
            category
        )

        for (
            group_id,
            group_name,
            col_id,
            description,
            value,
            unit
        ) in calculated:

            writer.writerow(
                [

                    SURVEY_ID,

                    SURVEY_NAME,

                    group_id,

                    group_name,

                    category,

                    category,

                    YEAR,

                    FREQ_DESC,

                    state_id,

                    state_name,

                    district_id,

                    district_name,

                    sector_code,

                    sector_name,

                    PUBLISHED_DATE,

                    EXTRACTED_DATE,

                    1,

                    col_id,

                    description,

                    round_sig(
                        value
                    ),

                    unit,

                    SOURCE,
                ]
            )

            row_count += 1

            col_ids.add(
                col_id
            )

        domain_count += 1

    # ========================================================
    # PROCESS ONE GEOGRAPHY
    # ========================================================

    def process_geo(
        writer,
        master_geo,
        loan_geo,
        adult_geo,
        state_id,
        state_name,
        district_id,
        district_name
    ):

        # Total
        emit_domain(
            writer,
            master_geo,
            loan_geo,
            adult_geo,
            state_id,
            state_name,
            district_id,
            district_name,
            0,
            "Total",
            "All HH"
        )

        # Rural - All HH
        emit_domain(
            writer,
            master_geo,
            loan_geo,
            adult_geo,
            state_id,
            state_name,
            district_id,
            district_name,
            1,
            "Rural",
            "All HH"
        )

        # Rural - Cultivator
        emit_domain(
            writer,
            master_geo,
            loan_geo,
            adult_geo,
            state_id,
            state_name,
            district_id,
            district_name,
            1,
            "Rural",
            "Cultivator HH"
        )

        # Rural - Non-Cultivator
        emit_domain(
            writer,
            master_geo,
            loan_geo,
            adult_geo,
            state_id,
            state_name,
            district_id,
            district_name,
            1,
            "Rural",
            "Non-Cultivator HH"
        )

        # Urban - All HH
        emit_domain(
            writer,
            master_geo,
            loan_geo,
            adult_geo,
            state_id,
            state_name,
            district_id,
            district_name,
            2,
            "Urban",
            "All HH"
        )

        # Urban - Self-employed
        emit_domain(
            writer,
            master_geo,
            loan_geo,
            adult_geo,
            state_id,
            state_name,
            district_id,
            district_name,
            2,
            "Urban",
            "Self-employed"
        )

        # Urban - Others
        emit_domain(
            writer,
            master_geo,
            loan_geo,
            adult_geo,
            state_id,
            state_name,
            district_id,
            district_name,
            2,
            "Urban",
            "Others"
        )

    # ========================================================
    # FINAL CSV
    # ========================================================

    with FINAL_FILE.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file_handle:

        writer = csv.writer(
            file_handle
        )

        writer.writerow(
            REFERENCE_COLUMNS
        )

        # ====================================================
        # ALL INDIA
        # ====================================================

        print(
            "\nCalculating All India..."
        )

        process_geo(
            writer,
            master,
            loans,
            adults,
            0,
            "All India",
            0,
            "All Districts"
        )

        # ====================================================
        # STATE / UT
        # ====================================================

        print(
            "\nCalculating State/UT "
            "aggregates..."
        )

        for (
            state_code,
            state_master
        ) in master.groupby(
            "State",
            sort=True
        ):

            state_id = int(
                state_code
            )

            process_geo(
                writer,

                state_master,

                loan_state.get(
                    state_code
                ),

                adult_state.get(
                    state_code
                ),

                state_id,

                STATE_NAMES.get(
                    state_id,
                    f"STATE {state_id}"
                ),

                0,

                "All Districts"
            )

            print(
                f"  State "
                f"{state_id:02d} done"
            )

        # ====================================================
        # DISTRICTS
        # ====================================================

        print(
            "\nCalculating District "
            "aggregates..."
        )

        for (
            counter,
            (
                composite_code,
                district_households
            )
        ) in enumerate(

            master.groupby(
                "State_District",
                sort=True
            ),

            start=1
        ):

            state_id = int(
                district_households[
                    "State"
                ].iloc[
                    0
                ]
            )

            district_name = (
                district_lookup.get(
                    composite_code
                )
            )

            if not district_name:

                raise ValueError(
                    "No verified NSS77 "
                    "district name for "
                    f"State_District="
                    f"{composite_code}"
                )

            process_geo(
                writer,

                district_households,

                loan_district.get(
                    composite_code
                ),

                adult_district.get(
                    composite_code
                ),

                state_id,

                STATE_NAMES.get(
                    state_id,
                    f"STATE {state_id}"
                ),

                int(
                    composite_code
                ),

                district_name
            )

            if (
                counter
                %
                50
                ==
                0
            ):

                print(
                    "  Districts completed: "
                    f"{counter:,}"
                )

    # ========================================================
    # COVERAGE VALIDATION
    # ========================================================

    if len(
        col_ids
    ) != 114:

        raise ValueError(
            f"Final coverage contains "
            f"{len(col_ids)} "
            "unique Col_ID values; "
            "expected 114."
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    summary = [

        "=" * 78,

        "AIDIS NSS 77 - "
        "STEP 05 FINAL EXPORT SUMMARY",

        "=" * 78,

        "",

        f"Final file              : "
        f"{FINAL_FILE}",

        f"Final rows              : "
        f"{row_count:,}",

        f"Final columns           : "
        f"{len(REFERENCE_COLUMNS)}",

        f"Unique Col_ID           : "
        f"{len(col_ids)}",

        f"Calculated domains      : "
        f"{domain_count:,}",

        f"States/UTs              : "
        f"{master['State'].nunique():,}",

        f"Observed districts      : "
        f"{master['State_District'].nunique():,}",

        f"Household rows          : "
        f"{len(master):,}",

        "",

        "Coverage:",

        "  Core HH/debt/assets      : YES",

        "  AVA components           : YES",

        "  Credit source            : YES",

        "  Institutional IOI        : YES",

        "  Credit purpose           : YES",

        "  Asset deciles            : YES",

        "  FCE/EPL                  : YES",

        "  FCE/EPL by decile        : YES",

        "  Adult bank account       : YES",

        "  Gini                     : YES",

        "",

        "Important production policies:",

        "  - AVA/debt reference position uses "
        "corrected Visit-1 household facts.",

        "  - Debt uses cash outstanding on "
        "30.06.2018 with b12q1=99 totals excluded.",

        "  - FCE/EPL combine Visit-1 and Visit-2 "
        "Block-14 transaction periods to form "
        "annual values.",

        "  - Rural classification uses b4q4=1 "
        "as Cultivator HH; other rural codes "
        "= Non-Cultivator HH.",

        "  - Urban b4q4=1 = Self-employed; "
        "other urban codes = Others.",

        "  - District names use verified "
        "NSS77 district_master.csv.",

        "  - AIDIS_Final_Client.csv is NOT used "
        "as a production input.",

        "",

        "STEP 05 STATUS: PASS",

        "=" * 78,
    ]

    SUMMARY_FILE.write_text(
        "\n".join(
            summary
        ),
        encoding="utf-8"
    )

    print(
        "\n"
        +
        "\n".join(
            summary
        )
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            "\n"
            +
            "=" * 78
        )

        print(
            "STEP 05 FINAL KPI/EXPORT: FAIL"
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