from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path


# =============================================================================
# AIDIS 2013 - STEP 01C
# METHODOLOGY LOCK
#
# NSS 70th Round - Schedule 18.2
#
# PURPOSE
# -------
# Freeze the production methodology before any analytical transformation:
#
#   - household universes
#   - common household / Visit linkage
#   - weights
#   - stock / flow reference periods
#   - household classifications
#   - asset components
#   - debt definitions and codebooks
#   - Block 16 semantics
#   - FCE / land-purchase methodology
#   - official validation controls
#
# THIS STEP DOES NOT CALCULATE FINAL KPIs.
#
# =============================================================================


PROJECT_ROOT = Path(
    r"D:\AIDIS\AIDIS_2013_All_India_Pipeline"
)

INPUT_DIR = PROJECT_ROOT / "input"
REFERENCE_DIR = INPUT_DIR / "reference"

CACHE_DIR = PROJECT_ROOT / "cache"
CONFIG_DIR = PROJECT_ROOT / "config"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"

for folder in [
    CACHE_DIR,
    CONFIG_DIR,
    REPORT_DIR,
]:
    folder.mkdir(
        parents=True,
        exist_ok=True,
    )


# =============================================================================
# UPSTREAM LOCKS
# =============================================================================

STEP01_SUMMARY = (
    REPORT_DIR
    / "step01_production_lock_summary.txt"
)

STEP01B_SUMMARY = (
    REPORT_DIR
    / "step01b_variable_mapping_summary.txt"
)

STEP01_HOUSEHOLDS = (
    CACHE_DIR
    / "step01_household_universe.csv"
)

STEP01_CROSS_VISIT = (
    CACHE_DIR
    / "step01_cross_visit_audit.csv"
)

VARIABLE_CATALOG = (
    CONFIG_DIR
    / "aidis_2013_variable_catalog.csv"
)


# =============================================================================
# STEP 01C OUTPUTS
# =============================================================================

METHODOLOGY_JSON = (
    CONFIG_DIR
    / "aidis_2013_methodology_lock.json"
)

ASSET_MAP_FILE = (
    CONFIG_DIR
    / "aidis_2013_asset_methodology.csv"
)

AGENCY_CODEBOOK_FILE = (
    CONFIG_DIR
    / "aidis_2013_credit_agency_codebook.csv"
)

INTEREST_CODEBOOK_FILE = (
    CONFIG_DIR
    / "aidis_2013_interest_codebook.csv"
)

PURPOSE_CODEBOOK_FILE = (
    CONFIG_DIR
    / "aidis_2013_credit_purpose_codebook.csv"
)

BLOCK16_VARIABLE_MAP_FILE = (
    CONFIG_DIR
    / "aidis_2013_block16_variable_map.csv"
)

BLOCK16_ITEM_CODEBOOK_FILE = (
    CONFIG_DIR
    / "aidis_2013_block16_item_codebook.csv"
)

OFFICIAL_CONTROLS_FILE = (
    CONFIG_DIR
    / "aidis_2013_official_controls.csv"
)

REFERENCE_MANIFEST_FILE = (
    CACHE_DIR
    / "step01c_reference_manifest.csv"
)

VARIABLE_CHECK_FILE = (
    CACHE_DIR
    / "step01c_required_variable_check.csv"
)

METHODOLOGY_CHECK_FILE = (
    CACHE_DIR
    / "step01c_methodology_checks.csv"
)

SUMMARY_FILE = (
    REPORT_DIR
    / "step01c_methodology_lock_summary.txt"
)


errors: list[str] = []
warnings: list[str] = []
disclosures: list[str] = []


# =============================================================================
# OFFICIAL SOURCE URLS
# =============================================================================

SOURCE_URLS = {
    "instructions_chapter4":
        "https://mospi.gov.in/sites/default/files/publication_reports/Ins70chap4.pdf",

    "key_indicators":
        "https://mospi.gov.in/sites/default/files/publication_reports/KI_70_18.2_19dec14.pdf",

    "report_570":
        "https://mospi.gov.in/sites/default/files/publication_reports/nss_Report_570.pdf",

    # Current legacy MoSPI endpoint for Report 577 is unavailable / 404.
    "report_577":
        "",

    "report_578":
        "https://mospi.gov.in/sites/default/files/publication_reports/nss_578.pdf",

    "report_579":
        "https://mospi.gov.in/sites/default/files/publication_reports/NSS_579_7mar17.pdf",
}


# =============================================================================
# HELPERS
# =============================================================================

def clean(value) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def norm(value) -> str:
    return re.sub(
        r"[^a-z0-9]",
        "",
        clean(value).lower(),
    )


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(
            csv.DictReader(fh)
        )


def write_csv(
    path: Path,
    rows,
    fieldnames,
):
    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as fh:

        writer = csv.DictWriter(
            fh,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)


def write_json(
    path: Path,
    value,
):
    with path.open(
        "w",
        encoding="utf-8",
    ) as fh:
        json.dump(
            value,
            fh,
            indent=2,
            ensure_ascii=False,
        )


def sha256_file(
    path: Path,
    block_size=1024 * 1024,
):
    digest = hashlib.sha256()

    with path.open("rb") as fh:
        while True:
            block = fh.read(block_size)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def add_check(
    checks,
    check_id,
    description,
    expected,
    actual,
    passed,
    severity="ERROR",
):
    checks.append({
        "check_id": check_id,
        "description": description,
        "expected": expected,
        "actual": actual,
        "status": (
            "PASS"
            if passed
            else "FAIL"
        ),
        "severity": severity,
    })

    if not passed:
        message = (
            f"{check_id}: {description}; "
            f"expected={expected}, actual={actual}"
        )

        if severity == "ERROR":
            errors.append(message)
        else:
            warnings.append(message)


# =============================================================================
# UPSTREAM STATUS
# =============================================================================

def validate_upstream(checks):

    print("\n[1] Validating upstream locks")

    # -------------------------------------------------------------------------
    # STEP 01
    # -------------------------------------------------------------------------

    if not STEP01_SUMMARY.exists():
        add_check(
            checks,
            "UPSTREAM_01",
            "Step 01 summary exists",
            "present",
            "missing",
            False,
        )

    else:
        text = STEP01_SUMMARY.read_text(
            encoding="utf-8",
            errors="replace",
        )

        ok = (
            "STEP 01 STATUS: PASS"
            in text
            and
            "Production lock           : LOCKED"
            in text
        )

        add_check(
            checks,
            "UPSTREAM_01",
            "Step 01 production lock",
            "PASS / LOCKED",
            (
                "PASS / LOCKED"
                if ok
                else "NOT LOCKED"
            ),
            ok,
        )

    # -------------------------------------------------------------------------
    # STEP 01B
    # -------------------------------------------------------------------------

    if not STEP01B_SUMMARY.exists():
        add_check(
            checks,
            "UPSTREAM_01B",
            "Step 01B summary exists",
            "present",
            "missing",
            False,
        )

    else:
        text = STEP01B_SUMMARY.read_text(
            encoding="utf-8",
            errors="replace",
        )

        ok = (
            "STEP 01B STATUS: PASS_WITH_DISCLOSURES"
            in text
            or
            "STEP 01B STATUS: PASS"
            in text
        )

        add_check(
            checks,
            "UPSTREAM_01B",
            "Step 01B variable mapping",
            "PASS or PASS_WITH_DISCLOSURES",
            (
                "PASS"
                if ok
                else "FAIL"
            ),
            ok,
        )

    if not VARIABLE_CATALOG.exists():
        add_check(
            checks,
            "CATALOG",
            "Canonical variable catalog exists",
            "present",
            "missing",
            False,
        )

    else:
        add_check(
            checks,
            "CATALOG",
            "Canonical variable catalog exists",
            "present",
            "present",
            True,
        )


# =============================================================================
# REFERENCE DOCUMENT DISCOVERY
# =============================================================================

REFERENCE_ROLES = {
    "instructions_chapter1": {
        "required": False,
        "patterns": [
            "ins70chap1",
            "chapter1",
            "instructionschapter1",
        ],
    },

    "instructions_chapter4": {
        "required": True,
        "patterns": [
            "ins70chap4",
            "chapter4",
            "schedule182instructions",
            "schedule18_2instructions",
        ],
    },

    "key_indicators": {
        "required": True,
        "patterns": [
            "ki70182",
            "ki70_182",
            "keyindicators",
        ],
    },

    "report_570": {
        "required": False,
        "patterns": [
            "report570",
            "nssreport570",
            "nss570",
        ],
    },

    "report_577": {
        "required": False,
        "patterns": [
            "report577",
            "nss577",
        ],
    },

    "report_578": {
        "required": False,
        "patterns": [
            "report578",
            "nss578",
        ],
    },

    "report_579": {
        "required": True,
        "patterns": [
            "report579",
            "nss579",
        ],
    },
}


def discover_references(checks):

    print("\n[2] Discovering official reference documents")

    if not REFERENCE_DIR.exists():
        errors.append(
            f"Reference directory missing: {REFERENCE_DIR}"
        )
        return {}, []

    pdfs = sorted(
        path
        for path in REFERENCE_DIR.rglob("*.pdf")
        if path.is_file()
    )

    found = {}
    manifest_rows = []

    for role, cfg in REFERENCE_ROLES.items():

        candidates = []

        for path in pdfs:
            key = norm(path.name)

            if any(
                norm(pattern) in key
                for pattern in cfg["patterns"]
            ):
                candidates.append(path)

        selected = (
            candidates[0]
            if candidates
            else None
        )

        if selected:
            found[role] = selected

            manifest_rows.append({
                "role": role,
                "required": int(
                    cfg["required"]
                ),
                "present": 1,
                "file_name": selected.name,
                "path": str(selected),
                "size_bytes": selected.stat().st_size,
                "sha256": sha256_file(selected),
                "official_url": SOURCE_URLS.get(
                    role,
                    "",
                ),
            })

            print(
                f"  PASS | {role:24s} | "
                f"{selected.name}"
            )

        else:
            manifest_rows.append({
                "role": role,
                "required": int(
                    cfg["required"]
                ),
                "present": 0,
                "file_name": "",
                "path": "",
                "size_bytes": "",
                "sha256": "",
                "official_url": SOURCE_URLS.get(
                    role,
                    "",
                ),
            })

            if cfg["required"]:
                errors.append(
                    f"Required methodology reference "
                    f"missing: {role}"
                )
                print(
                    f"  FAIL | {role:24s} | MISSING"
                )

            else:
                print(
                    f"  INFO | {role:24s} | not present"
                )

    # Report 577 is explicitly optional because current direct endpoint is
    # unavailable. Its absence does not block methodology locking.

    if "report_577" not in found:
        disclosures.append(
            "NSS Report 577 is not present locally because the legacy "
            "MoSPI direct download endpoint is unavailable. Debt methodology "
            "is locked from the official Schedule 18.2 Instructions and "
            "Key Indicators; Report 577 is not required for this lock."
        )

    for role in [
        "instructions_chapter1",
        "report_570",
        "report_578",
    ]:
        if role not in found:
            warnings.append(
                f"Optional reference not present: {role}"
            )

    for role, cfg in REFERENCE_ROLES.items():
        if cfg["required"]:
            add_check(
                checks,
                f"REF_{role.upper()}",
                f"Required reference {role}",
                "present",
                (
                    "present"
                    if role in found
                    else "missing"
                ),
                role in found,
            )

    return found, manifest_rows


# =============================================================================
# STRUCTURAL CONTROLS
# =============================================================================

def validate_household_structure(checks):

    print("\n[3] Validating survey structure")

    if not STEP01_HOUSEHOLDS.exists():
        errors.append(
            f"Missing household universe audit: "
            f"{STEP01_HOUSEHOLDS}"
        )
        return

    rows = read_csv(
        STEP01_HOUSEHOLDS
    )

    lookup = {
        clean(row["visit"]): row
        for row in rows
    }

    expected = {
        "visit1": {
            "rows": 110800,
            "states": 36,
            "state_districts": 634,
        },
        "visit2": {
            "rows": 108425,
            "states": 36,
            "state_districts": 634,
        },
    }

    for visit, exp in expected.items():
        row = lookup.get(
            visit
        )

        if not row:
            errors.append(
                f"{visit}: household audit missing."
            )
            continue

        for field, expected_value in exp.items():
            try:
                actual = int(
                    float(
                        clean(
                            row[field]
                        )
                    )
                )
            except Exception:
                actual = -1

            add_check(
                checks,
                f"{visit.upper()}_{field.upper()}",
                f"{visit} {field}",
                expected_value,
                actual,
                actual == expected_value,
            )

    # -------------------------------------------------------------------------
    # Exact Visit-1 / Visit-2 common households
    # -------------------------------------------------------------------------

    if not STEP01_CROSS_VISIT.exists():
        errors.append(
            f"Missing cross-visit audit: "
            f"{STEP01_CROSS_VISIT}"
        )
        return

    cross = read_csv(
        STEP01_CROSS_VISIT
    )

    cross_lookup = {
        clean(
            row["metric"]
        ):
        clean(
            row["value"]
        )
        for row in cross
    }

    try:
        common = int(
            float(
                cross_lookup[
                    "Exact HHID overlap"
                ]
            )
        )
    except Exception:
        common = -1

    add_check(
        checks,
        "COMMON_HH",
        "Exact common Visit-1 / Visit-2 HHIDs",
        108421,
        common,
        common == 108421,
    )


# =============================================================================
# VARIABLE REQUIREMENTS
# =============================================================================

def catalog_match(
    catalog,
    visit,
    variable,
    file_contains=None,
    file_exact=None,
    metadata_data_file=None,
):

    target_var = norm(
        variable
    )

    candidates = []

    for row in catalog:

        if clean(
            row.get(
                "visit"
            )
        ) != visit:
            continue

        raw_variable = clean(
            row.get(
                "raw_variable"
            )
        )

        if norm(
            raw_variable
        ) != target_var:
            continue

        raw_file = clean(
            row.get(
                "raw_file"
            )
        )

        if (
            file_exact
            and
            raw_file != file_exact
        ):
            continue

        if (
            file_contains
            and
            norm(file_contains)
            not in norm(raw_file)
        ):
            continue

        if (
            metadata_data_file
            and
            clean(
                row.get(
                    "metadata_data_file"
                )
            )
            != metadata_data_file
        ):
            continue

        candidates.append(
            row
        )

    return candidates


REQUIRED_VARIABLES = [

    # -------------------------------------------------------------------------
    # VISIT 1 - household / geography / weight
    # -------------------------------------------------------------------------

    (
        "V1_HHID",
        "visit1",
        "HHID",
        "Identification of sample household",
        None,
        None,
    ),
    (
        "V1_SECTOR",
        "visit1",
        "Sector",
        "Identification of sample household",
        None,
        None,
    ),
    (
        "V1_STATE",
        "visit1",
        "State",
        "Identification of sample household",
        None,
        None,
    ),
    (
        "V1_DISTRICT",
        "visit1",
        "District_id",
        "Identification of sample household",
        None,
        None,
    ),
    (
        "V1_VISIT",
        "visit1",
        "Visit_no",
        "Identification of sample household",
        None,
        None,
    ),
    (
        "V1_WEIGHT",
        "visit1",
        "Weight_SC",
        "Identification of sample household",
        None,
        None,
    ),

    # -------------------------------------------------------------------------
    # VISIT 2 - household / geography / weight
    # -------------------------------------------------------------------------

    (
        "V2_HHID",
        "visit2",
        "HHID",
        "Identification of sample household",
        None,
        None,
    ),
    (
        "V2_WEIGHT",
        "visit2",
        "Weight_SC",
        "Identification of sample household",
        None,
        None,
    ),

    # -------------------------------------------------------------------------
    # Household classification
    # -------------------------------------------------------------------------

    (
        "HH_TYPE",
        "visit1",
        "HH_type",
        "Block 3_Household Characteristics",
        None,
        None,
    ),
    (
        "LAND_OPERATED_YN",
        "visit1",
        "b3q4",
        "Block 3_Household Characteristics",
        None,
        None,
    ),
    (
        "LAND_OPERATED_AREA",
        "visit1",
        "b3q5",
        "Block 3_Household Characteristics",
        None,
        None,
    ),

    # -------------------------------------------------------------------------
    # Financial-inclusion fields available to the project
    # -------------------------------------------------------------------------

    (
        "BANK_ACCOUNT",
        "visit1",
        "b3q8",
        "Block 3_Household Characteristics",
        None,
        None,
    ),
    (
        "POST_OFFICE_ACCOUNT",
        "visit1",
        "b3q10",
        "Block 3_Household Characteristics",
        None,
        None,
    ),

    # -------------------------------------------------------------------------
    # Assets
    # -------------------------------------------------------------------------

    (
        "LAND_RURAL_VALUE",
        "visit1",
        "b5_1_6",
        "Block 5pt1_",
        None,
        None,
    ),
    (
        "LAND_URBAN_VALUE",
        "visit1",
        "b5_2_6",
        "Block 5pt2_",
        None,
        None,
    ),
    (
        "BUILDING_VALUE",
        "visit1",
        "b6_q6",
        "Block 6_Buildings",
        None,
        None,
    ),
    (
        "LIVESTOCK_VALUE",
        "visit1",
        "b7_q5",
        "Block 7_Livestock",
        None,
        None,
    ),
    (
        "TRANSPORT_VALUE",
        "visit1",
        "b8_q5",
        "Block 8_Transport",
        None,
        None,
    ),
    (
        "AGRICULTURAL_MACHINERY_VALUE",
        "visit1",
        "b9_q4",
        "Block 9_Agricultural",
        None,
        None,
    ),
    (
        "NONFARM_EQUIPMENT_VALUE",
        "visit1",
        "b10_q3",
        "Block 10_Non-farm",
        None,
        None,
    ),
    (
        "SHARES_ITEM",
        "visit1",
        "b11_q1",
        None,
        "Visit 1_Block 11_.xlsx",
        None,
    ),
    (
        "SHARES_VALUE",
        "visit1",
        "b11_q6",
        None,
        "Visit 1_Block 11_.xlsx",
        None,
    ),
    (
        "FINANCIAL_ITEM",
        "visit1",
        "b12_q1",
        None,
        "Visit 1_Block 12.xlsx",
        None,
    ),
    (
        "FINANCIAL_VALUE",
        "visit1",
        "b12_q3",
        None,
        "Visit 1_Block 12.xlsx",
        None,
    ),
    (
        "RECEIVABLE_VALUE",
        "visit1",
        "b13_q4",
        None,
        "Visit 1_Block 13.xlsx",
        None,
    ),

    # -------------------------------------------------------------------------
    # Debt / credit
    # -------------------------------------------------------------------------

    (
        "DEBT_SERIAL",
        "visit1",
        "b14_q1",
        None,
        "Visit 1_Block 14.xlsx",
        None,
    ),
    (
        "DEBT_AGENCY",
        "visit1",
        "b14_q6",
        None,
        "Visit 1_Block 14.xlsx",
        None,
    ),
    (
        "DEBT_INTEREST_NATURE",
        "visit1",
        "b14_q9",
        None,
        "Visit 1_Block 14.xlsx",
        None,
    ),
    (
        "DEBT_RATE",
        "visit1",
        "b14_q10",
        None,
        "Visit 1_Block 14.xlsx",
        None,
    ),
    (
        "DEBT_PURPOSE",
        "visit1",
        "b14_q11",
        None,
        "Visit 1_Block 14.xlsx",
        None,
    ),
    (
        "DEBT_OUTSTANDING_STOCK",
        "visit1",
        "b14_q17",
        None,
        "Visit 1_Block 14.xlsx",
        None,
    ),
]


# Add Visit-1 Block 16 first half q2-q9.

for q in range(
    2,
    10,
):
    REQUIRED_VARIABLES.append(
        (
            f"V1_BLOCK16_Q{q}",
            "visit1",
            f"b16_q{q}",
            None,
            "Visit 1_Block 16.csv",
            None,
        )
    )


# Add Visit-1 Block 16 second half q2 and q10-q15.

for q in [
    2,
    10,
    11,
    12,
    13,
    14,
    15,
]:
    REQUIRED_VARIABLES.append(
        (
            f"V1_BLOCK16_VALUE_Q{q}",
            "visit1",
            f"b16_q{q}",
            None,
            "Visit 1_Block 16_value.csv",
            None,
        )
    )


# Visit-2 Block 16 (1): q2-q9.

for q in range(
    2,
    10,
):
    REQUIRED_VARIABLES.append(
        (
            f"V2_BLOCK16_1_Q{q}",
            "visit2",
            f"b16_q{q}",
            None,
            None,
            "Visit 2_Block 16 (1)",
        )
    )


# Visit-2 Block 16 (2): q2 and q10-q15.

for q in [
    2,
    10,
    11,
    12,
    13,
    14,
    15,
]:
    REQUIRED_VARIABLES.append(
        (
            f"V2_BLOCK16_2_Q{q}",
            "visit2",
            f"b16_q{q}",
            None,
            None,
            "Visit 2_Block 16 (2)",
        )
    )


def validate_required_variables(checks):

    print("\n[4] Validating methodology variables")

    if not VARIABLE_CATALOG.exists():
        return [], []

    catalog = read_csv(
        VARIABLE_CATALOG
    )

    output = []

    for (
        concept,
        visit,
        variable,
        file_contains,
        file_exact,
        metadata_data_file,
    ) in REQUIRED_VARIABLES:

        matches = catalog_match(
            catalog=catalog,
            visit=visit,
            variable=variable,
            file_contains=file_contains,
            file_exact=file_exact,
            metadata_data_file=metadata_data_file,
        )

        found = (
            len(matches) == 1
        )

        status = (
            "PASS"
            if found
            else "FAIL"
        )

        raw_file = (
            clean(
                matches[0].get(
                    "raw_file"
                )
            )
            if found
            else ""
        )

        mapping_status = (
            clean(
                matches[0].get(
                    "mapping_status"
                )
            )
            if found
            else ""
        )

        label = (
            clean(
                matches[0].get(
                    "variable_label"
                )
            )
            if found
            else ""
        )

        output.append({
            "concept": concept,
            "visit": visit,
            "variable": variable,
            "raw_file": raw_file,
            "metadata_data_file": (
                clean(
                    matches[0].get(
                        "metadata_data_file"
                    )
                )
                if found
                else ""
            ),
            "variable_label": label,
            "mapping_status": mapping_status,
            "status": status,
        })

        add_check(
            checks,
            f"VAR_{concept}",
            f"Required variable {concept}",
            "exactly one match",
            len(matches),
            found,
        )

        print(
            f"  {status:4s} | "
            f"{concept:28s} | "
            f"{variable}"
        )

    return catalog, output


# =============================================================================
# ASSET METHODOLOGY
# =============================================================================

ASSET_METHOD = [

    {
        "component_order": 1,
        "component": "Land",
        "asset_class": "Physical",
        "visit": "visit1",
        "raw_file_contains": "Block 5pt1_",
        "value_variable": "b5_1_6",
        "row_selector": "Sector=1 / rural land block",
        "household_aggregation": "SUM detail rows by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "Rural land source",
    },

    {
        "component_order": 1,
        "component": "Land",
        "asset_class": "Physical",
        "visit": "visit1",
        "raw_file_contains": "Block 5pt2_",
        "value_variable": "b5_2_6",
        "row_selector": "Sector=2 / urban land block",
        "household_aggregation": "SUM detail rows by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "Urban land source",
    },

    {
        "component_order": 2,
        "component": "Buildings and other constructions",
        "asset_class": "Physical",
        "visit": "visit1",
        "raw_file_contains": "Block 6_Buildings",
        "value_variable": "b6_q6",
        "row_selector": "Detail asset rows",
        "household_aggregation": "SUM detail rows by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "",
    },

    {
        "component_order": 3,
        "component": "Livestock and poultry",
        "asset_class": "Physical",
        "visit": "visit1",
        "raw_file_contains": "Block 7_Livestock",
        "value_variable": "b7_q5",
        "row_selector": "Detail asset rows",
        "household_aggregation": "SUM detail rows by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "",
    },

    {
        "component_order": 4,
        "component": "Agricultural machinery and implements",
        "asset_class": "Physical",
        "visit": "visit1",
        "raw_file_contains": "Block 9_Agricultural",
        "value_variable": "b9_q4",
        "row_selector": "Detail asset rows",
        "household_aggregation": "SUM detail rows by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "",
    },

    {
        "component_order": 5,
        "component": "Non-farm business equipment",
        "asset_class": "Physical",
        "visit": "visit1",
        "raw_file_contains": "Block 10_Non-farm",
        "value_variable": "b10_q3",
        "row_selector": "Detail asset rows",
        "household_aggregation": "SUM detail rows by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "",
    },

    {
        "component_order": 6,
        "component": "Transport equipment",
        "asset_class": "Physical",
        "visit": "visit1",
        "raw_file_contains": "Block 8_Transport",
        "value_variable": "b8_q5",
        "row_selector": "Detail asset rows",
        "household_aggregation": "SUM detail rows by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "",
    },

    {
        "component_order": 7,
        "component": "Shares and debentures",
        "asset_class": "Financial",
        "visit": "visit1",
        "raw_file_contains": "Visit 1_Block 11_.xlsx",
        "value_variable": "b11_q6",
        "row_selector": "b11_q1=5 total row",
        "household_aggregation": "Use total row per HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": (
            "Do not add detail rows to the total row."
        ),
    },

    {
        "component_order": 8,
        "component": "Deposits and other financial assets",
        "asset_class": "Financial",
        "visit": "visit1",
        "raw_file_contains": "Visit 1_Block 12.xlsx",
        "value_variable": "b12_q3",
        "row_selector": "b12_q1=11 total items 1-7 and 10",
        "household_aggregation": "Use item 11 total row per HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": (
            "Do not include insurance-policy count, sum assured, "
            "or bullion/ornaments as asset value."
        ),
    },

    {
        "component_order": 9,
        "component": "Amount receivable",
        "asset_class": "Financial",
        "visit": "visit1",
        "raw_file_contains": "Visit 1_Block 13.xlsx",
        "value_variable": "b13_q4",
        "row_selector": "Applicable receivable rows",
        "household_aggregation": "Aggregate receivable amount by HHID",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 1,
        "notes": "",
    },

    # Explicit exclusions.

    {
        "component_order": 90,
        "component": "Household consumer durables",
        "asset_class": "Excluded",
        "visit": "visit1",
        "raw_file_contains": "",
        "value_variable": "",
        "row_selector": "",
        "household_aggregation": "",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 0,
        "notes": (
            "Explicitly excluded from 70th Round asset valuation."
        ),
    },

    {
        "component_order": 91,
        "component": "Bullion and ornaments",
        "asset_class": "Excluded",
        "visit": "visit1",
        "raw_file_contains": "Visit 1_Block 12.xlsx",
        "value_variable": "b12_q3",
        "row_selector": "b12_q1=12",
        "household_aggregation": "EXCLUDE",
        "reference_date": "30-06-2012",
        "include_in_total_assets": 0,
        "notes": (
            "Explicitly excluded from 70th Round asset valuation."
        ),
    },
]


# =============================================================================
# DEBT CODEBOOKS
# =============================================================================

CREDIT_AGENCIES = [

    ("01", "Government", "Institutional"),
    ("02", "Co-operative society / co-operative bank", "Institutional"),
    ("03", "Commercial bank including RRB", "Institutional"),
    ("04", "Insurance", "Institutional"),
    ("05", "Provident fund", "Institutional"),
    ("06", "Financial corporation / institution", "Institutional"),
    ("07", "Financial company", "Institutional"),
    ("08", "Self-help group - bank linked", "Institutional"),
    ("10", "Self-help group - NBFC linked", "Institutional"),
    ("11", "Other institutional agency", "Institutional"),

    ("12", "Landlord", "Non-institutional"),
    ("13", "Agricultural moneylender", "Non-institutional"),
    ("14", "Professional moneylender", "Non-institutional"),
    ("15", "Input supplier", "Non-institutional"),
    ("16", "Relatives and friends", "Non-institutional"),
    ("17", "Doctors / lawyers / other professionals", "Non-institutional"),
    ("09", "Others", "Non-institutional"),
]


INTEREST_CODES = [
    ("1", "Interest-free"),
    ("2", "Simple interest"),
    ("3", "Compound interest"),
    ("4", "Concessional rate"),
]


PURPOSE_CODES = [
    ("01", "Capital expenditure in farm business"),
    ("02", "Current expenditure in farm business"),
    ("03", "Capital expenditure in non-farm business"),
    ("04", "Current expenditure in non-farm business"),
    ("05", "Litigation"),
    ("06", "Repayment of debt"),
    ("07", "Financial investment expenditure"),
    ("08", "Education"),
    ("09", "Others"),
    ("10", "Medical treatment"),
    ("11", "Housing"),
    ("12", "Other household expenditure"),
]


# =============================================================================
# BLOCK 16 VARIABLE SEMANTICS
# =============================================================================

BLOCK16_VARIABLES = [

    (
        "b16_q2",
        "Item serial number",
        "Key",
        "Used with HHID to align the two Block-16 halves",
    ),

    (
        "b16_q3",
        "Floor area in square metres - urban only",
        "Attribute",
        "",
    ),

    (
        "b16_q4",
        "Purchase",
        "Expenditure",
        "Included in FCE except land-purchase item codes",
    ),

    (
        "b16_q5",
        "Addition",
        "Expenditure",
        "Included in FCE",
    ),

    (
        "b16_q6",
        "Major repairs and alterations",
        "Expenditure",
        "Included in FCE",
    ),

    (
        "b16_q7",
        "Improvement",
        "Expenditure",
        "Included in FCE",
    ),

    (
        "b16_q8",
        "Normal repairs and maintenance",
        "Expenditure",
        "NOT included in fixed capital expenditure",
    ),

    (
        "b16_q9",
        "Total expenditure columns 4 to 8",
        "Derived total",
        (
            "Audit identity only. Do not use directly for FCE because "
            "it includes normal repairs."
        ),
    ),

    (
        "b16_q10",
        "Institutional borrowing used for financing",
        "Financing",
        "Not added to FCE amount",
    ),

    (
        "b16_q11",
        "Non-institutional borrowing used for financing",
        "Financing",
        "Not added to FCE amount",
    ),

    (
        "b16_q12",
        "Sale",
        "Disposal",
        "Separate transaction; do not subtract from FCE",
    ),

    (
        "b16_q13",
        "Discardment",
        "Disposal",
        "Separate transaction; do not subtract from FCE",
    ),

    (
        "b16_q14",
        "Loss",
        "Disposal",
        "Separate transaction; do not subtract from FCE",
    ),

    (
        "b16_q15",
        "Total disposal columns 12 to 14",
        "Derived total",
        "Audit identity",
    ),
]


# =============================================================================
# BLOCK 16 ITEM CODEBOOK
# =============================================================================

# Important:
#
# Fixed Capital Expenditure excludes purchase of land.
# Land-purchase expenditure is separately derived for item codes:
#
#   1  residential land
#   4  farm land
#   5  land rights
#   14 non-farm business land
#
# Subtotal codes 97 and 98 are never summed with detail rows.


BLOCK16_ITEMS = [

    ("1",  "Residential land", "Household", 1, 0, 1),
    ("2",  "Purchase of house / building", "Household", 0, 1, 1),
    ("3",  "Addition to house / building", "Household", 0, 1, 1),

    ("4",  "Farm land", "Farm business", 1, 0, 1),
    ("5",  "Land rights", "Farm business", 1, 0, 1),
    ("6",  "Barns and animal sheds", "Farm business", 0, 1, 1),
    ("7",  "Orchards and plantations", "Farm business", 0, 1, 1),
    ("8",  "Wells / irrigation / construction", "Farm business", 0, 1, 1),
    ("9",  "Working / breeding cattle and buffaloes", "Farm business", 0, 1, 1),
    ("10", "Egg-laying ducks and hens", "Farm business", 0, 1, 1),
    ("11", "Agricultural machinery and implements", "Farm business", 0, 1, 1),
    ("12", "Transport equipment - farm business", "Farm business", 0, 1, 1),
    ("13", "Other farm-business fixed assets", "Farm business", 0, 1, 1),

    ("14", "Non-farm business land", "Non-farm business", 1, 0, 1),
    ("15", "Workplace / shop / construction", "Non-farm business", 0, 1, 1),
    ("16", "Non-farm business equipment and accessories", "Non-farm business", 0, 1, 1),
    ("17", "Transport equipment - non-farm business", "Non-farm business", 0, 1, 1),
    ("18", "Other non-farm business fixed assets", "Non-farm business", 0, 1, 1),

    ("97", "Subtotal - items 1 to 10", "Subtotal", 0, 0, 0),
    ("98", "Subtotal - items 11 to 18", "Subtotal", 0, 0, 0),
]


# =============================================================================
# OFFICIAL CONTROLS
# =============================================================================

OFFICIAL_CONTROLS = [

    # -------------------------------------------------------------------------
    # STRUCTURE
    # -------------------------------------------------------------------------

    (
        "STRUCT_V1_HH",
        "Structure",
        "All India",
        "All",
        "Visit-1 households",
        110800,
        "Households",
        "Exact",
        "Step01",
    ),

    (
        "STRUCT_V2_HH",
        "Structure",
        "All India",
        "All",
        "Visit-2 households",
        108425,
        "Households",
        "Exact",
        "Step01",
    ),

    (
        "STRUCT_COMMON_HH",
        "Structure",
        "All India",
        "All",
        "Common households",
        108421,
        "Households",
        "Exact",
        "Report 579 / Step01",
    ),

    # -------------------------------------------------------------------------
    # AVA
    # Average Value of Assets per household
    # -------------------------------------------------------------------------

    (
        "AVA_RURAL_CULT",
        "Assets",
        "Rural",
        "Cultivator",
        "AVA",
        2872956,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "AVA_RURAL_NONCULT",
        "Assets",
        "Rural",
        "Non-cultivator",
        "AVA",
        674527,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "AVA_RURAL_ALL",
        "Assets",
        "Rural",
        "All",
        "AVA",
        1006985,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "AVA_URBAN_SELFEMP",
        "Assets",
        "Urban",
        "Self-employed",
        "AVA",
        5079429,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "AVA_URBAN_OTHERS",
        "Assets",
        "Urban",
        "Others",
        "AVA",
        1991505,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "AVA_URBAN_ALL",
        "Assets",
        "Urban",
        "All",
        "AVA",
        2285135,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    # -------------------------------------------------------------------------
    # DEBT
    # IOI = Incidence of Indebtedness
    # AOD = Average Amount of Debt per household
    # AODL = Average Outstanding Debt per indebted household
    # -------------------------------------------------------------------------

    (
        "DEBT_RURAL_CULT_IOI",
        "Debt",
        "Rural",
        "Cultivator",
        "IOI",
        45.94,
        "%",
        "0.50 percentage point",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_CULT_AOD",
        "Debt",
        "Rural",
        "Cultivator",
        "AOD",
        70580,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_CULT_AODL",
        "Debt",
        "Rural",
        "Cultivator",
        "AODL",
        153640,
        "Rs/indebted HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_NONCULT_IOI",
        "Debt",
        "Rural",
        "Non-cultivator",
        "IOI",
        28.85,
        "%",
        "0.50 percentage point",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_NONCULT_AOD",
        "Debt",
        "Rural",
        "Non-cultivator",
        "AOD",
        25741,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_NONCULT_AODL",
        "Debt",
        "Rural",
        "Non-cultivator",
        "AODL",
        89221,
        "Rs/indebted HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_ALL_IOI",
        "Debt",
        "Rural",
        "All",
        "IOI",
        31.44,
        "%",
        "0.50 percentage point",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_ALL_AOD",
        "Debt",
        "Rural",
        "All",
        "AOD",
        32522,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_RURAL_ALL_AODL",
        "Debt",
        "Rural",
        "All",
        "AODL",
        103457,
        "Rs/indebted HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_SELFEMP_IOI",
        "Debt",
        "Urban",
        "Self-employed",
        "IOI",
        35.85,
        "%",
        "0.50 percentage point",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_SELFEMP_AOD",
        "Debt",
        "Urban",
        "Self-employed",
        "AOD",
        108714,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_SELFEMP_AODL",
        "Debt",
        "Urban",
        "Self-employed",
        "AODL",
        303221,
        "Rs/indebted HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_OTHERS_IOI",
        "Debt",
        "Urban",
        "Others",
        "IOI",
        20.96,
        "%",
        "0.50 percentage point",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_OTHERS_AOD",
        "Debt",
        "Urban",
        "Others",
        "AOD",
        82094,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_OTHERS_AODL",
        "Debt",
        "Urban",
        "Others",
        "AODL",
        391724,
        "Rs/indebted HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_ALL_IOI",
        "Debt",
        "Urban",
        "All",
        "IOI",
        22.37,
        "%",
        "0.50 percentage point",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_ALL_AOD",
        "Debt",
        "Urban",
        "All",
        "AOD",
        84625,
        "Rs/HH",
        "1%",
        "Key Indicators",
    ),

    (
        "DEBT_URBAN_ALL_AODL",
        "Debt",
        "Urban",
        "All",
        "AODL",
        378238,
        "Rs/indebted HH",
        "1%",
        "Key Indicators",
    ),

    # -------------------------------------------------------------------------
    # INSTITUTIONAL / NON-INSTITUTIONAL IOI
    # -------------------------------------------------------------------------

    (
        "INST_IOI_RURAL",
        "Debt Source",
        "Rural",
        "All",
        "Institutional IOI",
        17.2,
        "%",
        "0.75 percentage point",
        "Key Indicators",
    ),

    (
        "NONINST_IOI_RURAL",
        "Debt Source",
        "Rural",
        "All",
        "Non-institutional IOI",
        19.0,
        "%",
        "0.75 percentage point",
        "Key Indicators",
    ),

    (
        "INST_IOI_URBAN",
        "Debt Source",
        "Urban",
        "All",
        "Institutional IOI",
        14.8,
        "%",
        "0.75 percentage point",
        "Key Indicators",
    ),

    (
        "NONINST_IOI_URBAN",
        "Debt Source",
        "Urban",
        "All",
        "Non-institutional IOI",
        10.3,
        "%",
        "0.75 percentage point",
        "Key Indicators",
    ),

    # -------------------------------------------------------------------------
    # CAPITAL EXPENDITURE
    # Published values are rounded, so tolerance is slightly wider.
    # -------------------------------------------------------------------------

    (
        "FCE_RURAL_ALL",
        "Capital Expenditure",
        "Rural",
        "All",
        "Average fixed capital expenditure",
        10717,
        "Rs/HH",
        "2%",
        "Report 579",
    ),

    (
        "FCE_RURAL_CULT",
        "Capital Expenditure",
        "Rural",
        "Cultivator",
        "Average fixed capital expenditure",
        22741,
        "Rs/HH",
        "2%",
        "Report 579",
    ),

    (
        "FCE_URBAN_ALL",
        "Capital Expenditure",
        "Urban",
        "All",
        "Average fixed capital expenditure",
        14493,
        "Rs/HH",
        "2%",
        "Report 579",
    ),

    (
        "FCE_URBAN_SELFEMP",
        "Capital Expenditure",
        "Urban",
        "Self-employed",
        "Average fixed capital expenditure",
        26197,
        "Rs/HH",
        "2%",
        "Report 579",
    ),
]


# =============================================================================
# WRITE STATIC METHODOLOGY TABLES
# =============================================================================

def write_methodology_tables():

    print("\n[5] Writing locked methodology tables")

    # -------------------------------------------------------------------------
    # Asset map
    # -------------------------------------------------------------------------

    write_csv(
        ASSET_MAP_FILE,
        ASSET_METHOD,
        [
            "component_order",
            "component",
            "asset_class",
            "visit",
            "raw_file_contains",
            "value_variable",
            "row_selector",
            "household_aggregation",
            "reference_date",
            "include_in_total_assets",
            "notes",
        ],
    )

    # -------------------------------------------------------------------------
    # Agency
    # -------------------------------------------------------------------------

    agency_rows = [
        {
            "code": code,
            "agency": agency,
            "agency_class": agency_class,
        }
        for (
            code,
            agency,
            agency_class,
        ) in CREDIT_AGENCIES
    ]

    write_csv(
        AGENCY_CODEBOOK_FILE,
        agency_rows,
        [
            "code",
            "agency",
            "agency_class",
        ],
    )

    # -------------------------------------------------------------------------
    # Interest
    # -------------------------------------------------------------------------

    interest_rows = [
        {
            "code": code,
            "interest_nature": label,
        }
        for (
            code,
            label,
        ) in INTEREST_CODES
    ]

    write_csv(
        INTEREST_CODEBOOK_FILE,
        interest_rows,
        [
            "code",
            "interest_nature",
        ],
    )

    # -------------------------------------------------------------------------
    # Purpose
    # -------------------------------------------------------------------------

    purpose_rows = [
        {
            "code": code,
            "purpose": label,
        }
        for (
            code,
            label,
        ) in PURPOSE_CODES
    ]

    write_csv(
        PURPOSE_CODEBOOK_FILE,
        purpose_rows,
        [
            "code",
            "purpose",
        ],
    )

    # -------------------------------------------------------------------------
    # Block 16 variables
    # -------------------------------------------------------------------------

    block16_variable_rows = [
        {
            "variable": variable,
            "meaning": meaning,
            "role": role,
            "production_rule": rule,
        }
        for (
            variable,
            meaning,
            role,
            rule,
        ) in BLOCK16_VARIABLES
    ]

    write_csv(
        BLOCK16_VARIABLE_MAP_FILE,
        block16_variable_rows,
        [
            "variable",
            "meaning",
            "role",
            "production_rule",
        ],
    )

    # -------------------------------------------------------------------------
    # Block 16 items
    # -------------------------------------------------------------------------

    block16_items = [
        {
            "item_code": code,
            "description": description,
            "asset_group": group,
            "land_purchase_item": land,
            "eligible_for_fce": fce,
            "detail_item": detail,
        }
        for (
            code,
            description,
            group,
            land,
            fce,
            detail,
        ) in BLOCK16_ITEMS
    ]

    write_csv(
        BLOCK16_ITEM_CODEBOOK_FILE,
        block16_items,
        [
            "item_code",
            "description",
            "asset_group",
            "land_purchase_item",
            "eligible_for_fce",
            "detail_item",
        ],
    )

    # -------------------------------------------------------------------------
    # Official controls
    # -------------------------------------------------------------------------

    control_rows = [
        {
            "control_id": control_id,
            "family": family,
            "sector": sector,
            "household_group": group,
            "metric": metric,
            "published_value": value,
            "unit": unit,
            "tolerance": tolerance,
            "source": source,
        }
        for (
            control_id,
            family,
            sector,
            group,
            metric,
            value,
            unit,
            tolerance,
            source,
        ) in OFFICIAL_CONTROLS
    ]

    write_csv(
        OFFICIAL_CONTROLS_FILE,
        control_rows,
        [
            "control_id",
            "family",
            "sector",
            "household_group",
            "metric",
            "published_value",
            "unit",
            "tolerance",
            "source",
        ],
    )


# =============================================================================
# METHODOLOGY JSON
# =============================================================================

def build_methodology_json(
    reference_manifest,
):

    methodology = {

        "survey": {
            "survey": "All India Debt and Investment Survey",
            "round": "NSS 70th Round",
            "schedule": "18.2",
            "survey_year": 2013,

            "visit1_sample_households": 110800,
            "visit2_sample_households": 108425,
            "common_households": 108421,

            "observed_states_uts": 36,
            "observed_state_district_combinations": 634,
        },

        "production_principles": {
            "raw_inputs_immutable": True,
            "step01_manifest_is_source_lock": True,
            "step01b_catalog_is_variable_lock": True,

            "aggregate_one_to_many_before_weighting": True,

            "do_not_reuse_2003_variable_formulas": True,
            "do_not_reuse_2003_panel_key_rule": True,

            "preserve_survey_era_geography": True,

            "modern_state_or_district_crosswalk_not_used_for_core_estimation": True,
        },

        "reference_periods": {

            "asset_stock": {
                "visit": 1,
                "reference_date": "30-06-2012",
            },

            "debt_stock": {
                "visit": 1,
                "reference_date": "30-06-2012",
                "cash_loans_only_for_official_IOI_AOD": True,
            },

            "visit2_liability_reference": {
                "visit": 2,
                "reference_date": "30-06-2013",
                "use_for_primary_30_06_2012_debt_KPIs": False,
            },

            "capital_expenditure_visit1": {
                "from": "01-07-2012",
                "to": "31-12-2012",
            },

            "capital_expenditure_visit2": {
                "from": "01-01-2013",
                "to": "30-06-2013",
            },

            "capital_expenditure_combined": {
                "from": "01-07-2012",
                "to": "30-06-2013",
            },
        },

        "household_linkage": {
            "key": ["HHID"],

            "rule":
                "Exact HHID equality between Visit 1 and Visit 2",

            "expected_common_households": 108421,

            "2003_string_deletion_rule_used": False,
        },

        "weighting": {

            "stock_visit1": {
                "weight_variable": "Weight_SC",
                "source_visit": 1,

                "rule":
                    "Aggregate source records to required household fact "
                    "first; apply household Weight_SC only after aggregation.",
            },

            "visit2_only": {
                "weight_variable": "Weight_SC",
                "source_visit": 2,
            },

            "combined_visit1_visit2": {
                "universe":
                    "Exact common households only",

                "weight_variable":
                    "Weight_SC",

                "weight_source":
                    "Visit 2",

                "reason":
                    "Combined common-household estimates use the Visit-2 "
                    "combined-estimate multiplier / final combined weight.",
            },

            "reconstruct_weight_from_MLT_NSS_NSC": False,
        },

        "household_classification": {

            "rural": {
                "sector_code": "1",

                "cultivator": {
                    "operated_area_variable": "b3q5",
                    "rule": "b3q5 >= 0.002 hectares",
                },

                "non_cultivator": {
                    "operated_area_variable": "b3q5",
                    "rule":
                        "b3q5 < 0.002 hectares or no operated land "
                        "as defined by the survey",
                },
            },

            "urban": {
                "sector_code": "2",
                "household_type_variable": "HH_type",

                "self_employed_codes": ["1"],

                "others_codes": [
                    "2",
                    "3",
                    "9",
                ],
            },
        },

        "assets": {

            "reference_date":
                "30-06-2012",

            "source_visit":
                1,

            "physical_components": [
                "Land",
                "Buildings and other constructions",
                "Livestock and poultry",
                "Agricultural machinery and implements",
                "Non-farm business equipment",
                "Transport equipment",
            ],

            "financial_components": [
                "Shares and debentures",
                "Deposits and other financial assets",
                "Amount receivable",
            ],

            "excluded": [
                "Household consumer durables",
                "Bullion and ornaments",
            ],

            "total_assets":
                "Sum locked included asset components at household level",

            "weight_after_household_aggregation":
                True,
        },

        "debt": {

            "primary_stock_visit":
                1,

            "reference_date":
                "30-06-2012",

            "source_block":
                14,

            "loan_type":
                "Cash loans payable",

            "outstanding_variable":
                "b14_q17",

            "indebted_household":
                "Household sum of positive b14_q17 > 0",

            "kind_loans_block15_in_official_IOI_AOD":
                False,

            "credit_agency_variable":
                "b14_q6",

            "interest_nature_variable":
                "b14_q9",

            "interest_rate_variable":
                "b14_q10",

            "purpose_variable":
                "b14_q11",

            "institutional_codes": [
                "01",
                "02",
                "03",
                "04",
                "05",
                "06",
                "07",
                "08",
                "10",
                "11",
            ],

            "non_institutional_codes": [
                "09",
                "12",
                "13",
                "14",
                "15",
                "16",
                "17",
            ],

            "blank_stock_outstanding":
                "Treat as zero for 30-06-2012 stock; audit separately",

            "do_not_double_count_explicit_total_rows":
                True,
        },

        "block16": {

            "visit1_file_half_1":
                "Visit 1_Block 16.csv",

            "visit1_file_half_2":
                "Visit 1_Block 16_value.csv",

            "visit2_metadata_half_1":
                "Visit 2_Block 16 (1)",

            "visit2_metadata_half_2":
                "Visit 2_Block 16 (2)",

            "within_visit_join_key": [
                "HHID",
                "b16_q2",
            ],

            "visit1_reference_period": [
                "01-07-2012",
                "31-12-2012",
            ],

            "visit2_reference_period": [
                "01-01-2013",
                "30-06-2013",
            ],

            "identity_checks": {
                "b16_q9":
                    "b16_q4 + b16_q5 + b16_q6 + b16_q7 + b16_q8",

                "b16_q15":
                    "b16_q12 + b16_q13 + b16_q14",
            },
        },

        "capital_expenditure": {

            "universe":
                "108421 exact common households",

            "weight":
                "Visit-2 Weight_SC",

            "detail_item_codes": [
                str(code)
                for code in range(
                    1,
                    19,
                )
            ],

            "subtotal_codes_excluded": [
                "97",
                "98",
            ],

            "fixed_capital_expenditure": {

                "eligible_item_codes": [
                    "2",
                    "3",
                    "6",
                    "7",
                    "8",
                    "9",
                    "10",
                    "11",
                    "12",
                    "13",
                    "15",
                    "16",
                    "17",
                    "18",
                ],

                "columns": [
                    "b16_q4",
                    "b16_q5",
                    "b16_q6",
                    "b16_q7",
                ],

                "formula":
                    "SUM(q4 + q5 + q6 + q7) for eligible detail items",

                "normal_repairs_q8_included":
                    False,

                "disposals_q12_q14_netted":
                    False,
            },

            "purchase_of_land": {

                "item_codes": [
                    "1",
                    "4",
                    "5",
                    "14",
                ],

                "amount_variable":
                    "b16_q4",

                "included_in_fixed_capital_expenditure":
                    False,
            },

            "normal_repairs": {
                "amount_variable": "b16_q8",
                "separate_metric": True,
            },

            "financing": {
                "institutional": "b16_q10",
                "non_institutional": "b16_q11",

                "add_to_fce_amount":
                    False,
            },

            "disposals": {
                "sale": "b16_q12",
                "discardment": "b16_q13",
                "loss": "b16_q14",
                "total": "b16_q15",

                "subtract_from_fce":
                    False,
            },
        },

        "financial_inclusion": {
            "household_bank_account_supported": True,
            "bank_account_variable": "b3q8",

            "adult_male_female_bank_account_counts_supported":
                False,

            "rule":
                "Do not fabricate adult/gender bank-account counts "
                "if not represented by survey variables.",
        },

        "geography": {
            "use_raw_state_codes": True,
            "use_raw_district_codes": True,

            "expected_states_uts":
                36,

            "expected_state_district_combinations":
                634,

            "modern_geography_crosswalk_for_core_results":
                False,
        },

        "reference_documents": reference_manifest,

        "official_control_file":
            str(
                OFFICIAL_CONTROLS_FILE
            ),

        "asset_method_file":
            str(
                ASSET_MAP_FILE
            ),

        "credit_agency_codebook":
            str(
                AGENCY_CODEBOOK_FILE
            ),

        "interest_codebook":
            str(
                INTEREST_CODEBOOK_FILE
            ),

        "purpose_codebook":
            str(
                PURPOSE_CODEBOOK_FILE
            ),

        "block16_variable_map":
            str(
                BLOCK16_VARIABLE_MAP_FILE
            ),

        "block16_item_codebook":
            str(
                BLOCK16_ITEM_CODEBOOK_FILE
            ),
    }

    write_json(
        METHODOLOGY_JSON,
        methodology,
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("=" * 78)
    print(
        "AIDIS 2013 - STEP 01C "
        "METHODOLOGY LOCK"
    )
    print(
        "NSS 70th Round | "
        "Schedule 18.2"
    )
    print("=" * 78)

    print(
        f"Project root              : "
        f"{PROJECT_ROOT}"
    )

    checks = []

    # -------------------------------------------------------------------------
    # Upstream
    # -------------------------------------------------------------------------

    validate_upstream(
        checks
    )

    # -------------------------------------------------------------------------
    # References
    # -------------------------------------------------------------------------

    (
        references,
        reference_manifest,
    ) = discover_references(
        checks
    )

    # -------------------------------------------------------------------------
    # Survey structural controls
    # -------------------------------------------------------------------------

    validate_household_structure(
        checks
    )

    # -------------------------------------------------------------------------
    # Required raw variables
    # -------------------------------------------------------------------------

    (
        catalog,
        variable_check_rows,
    ) = validate_required_variables(
        checks
    )

    # -------------------------------------------------------------------------
    # Static methodology files
    # -------------------------------------------------------------------------

    write_methodology_tables()

    # -------------------------------------------------------------------------
    # Build permanent JSON lock
    # -------------------------------------------------------------------------

    build_methodology_json(
        reference_manifest
    )

    # -------------------------------------------------------------------------
    # Additional logical methodology checks
    # -------------------------------------------------------------------------

    institutional = {
        code
        for (
            code,
            _,
            agency_class,
        )
        in CREDIT_AGENCIES
        if agency_class == "Institutional"
    }

    noninstitutional = {
        code
        for (
            code,
            _,
            agency_class,
        )
        in CREDIT_AGENCIES
        if agency_class == "Non-institutional"
    }

    add_check(
        checks,
        "AGENCY_OVERLAP",
        "Institutional and non-institutional codes do not overlap",
        0,
        len(
            institutional
            & noninstitutional
        ),
        len(
            institutional
            & noninstitutional
        ) == 0,
    )

    expected_agency_codes = {
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
    }

    all_agency_codes = (
        institutional
        | noninstitutional
    )

    add_check(
        checks,
        "AGENCY_COMPLETE",
        "Official credit-agency code universe",
        len(expected_agency_codes),
        len(all_agency_codes),
        (
            all_agency_codes
            == expected_agency_codes
        ),
    )

    land_codes = {
        code
        for (
            code,
            _,
            _,
            land,
            _,
            detail,
        )
        in BLOCK16_ITEMS
        if land
        and detail
    }

    expected_land_codes = {
        "1",
        "4",
        "5",
        "14",
    }

    add_check(
        checks,
        "LAND_CODES",
        "Land-purchase item codes",
        sorted(
            expected_land_codes
        ),
        sorted(
            land_codes
        ),
        (
            land_codes
            == expected_land_codes
        ),
    )

    fce_codes = {
        code
        for (
            code,
            _,
            _,
            _,
            fce,
            detail,
        )
        in BLOCK16_ITEMS
        if fce
        and detail
    }

    add_check(
        checks,
        "FCE_LAND_EXCLUSION",
        "FCE item set excludes land-purchase items",
        0,
        len(
            fce_codes
            & land_codes
        ),
        len(
            fce_codes
            & land_codes
        ) == 0,
    )

    # -------------------------------------------------------------------------
    # Write audit files
    # -------------------------------------------------------------------------

    write_csv(
        REFERENCE_MANIFEST_FILE,
        reference_manifest,
        [
            "role",
            "required",
            "present",
            "file_name",
            "path",
            "size_bytes",
            "sha256",
            "official_url",
        ],
    )

    write_csv(
        VARIABLE_CHECK_FILE,
        variable_check_rows,
        [
            "concept",
            "visit",
            "variable",
            "raw_file",
            "metadata_data_file",
            "variable_label",
            "mapping_status",
            "status",
        ],
    )

    write_csv(
        METHODOLOGY_CHECK_FILE,
        checks,
        [
            "check_id",
            "description",
            "expected",
            "actual",
            "status",
            "severity",
        ],
    )

    # -------------------------------------------------------------------------
    # Final status
    # -------------------------------------------------------------------------

    if errors:
        status = "FAIL"

    elif disclosures:
        status = "PASS_WITH_DISCLOSURES"

    else:
        status = "PASS"

    passed_checks = sum(
        1
        for row in checks
        if row["status"]
        == "PASS"
    )

    failed_checks = sum(
        1
        for row in checks
        if row["status"]
        == "FAIL"
    )

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------

    lines = [
        "=" * 78,
        "AIDIS 2013 - STEP 01C METHODOLOGY LOCK SUMMARY",
        "=" * 78,
        "",
        f"Project root              : {PROJECT_ROOT}",
        "",
        "LOCKED SURVEY STRUCTURE",
        "-----------------------",
        "Visit 1 households       : 110,800",
        "Visit 2 households       : 108,425",
        "Common households        : 108,421",
        "Observed states/UTs      : 36",
        "State-district combos    : 634",
        "",
        "LOCKED REFERENCE PERIODS",
        "------------------------",
        "Asset stock              : 30-06-2012 / Visit 1",
        "Debt stock               : 30-06-2012 / Visit 1",
        "Flow Visit 1             : 01-07-2012 to 31-12-2012",
        "Flow Visit 2             : 01-01-2013 to 30-06-2013",
        "Combined flow            : 01-07-2012 to 30-06-2013",
        "",
        "LOCKED ESTIMATION",
        "-----------------",
        "Stock weight             : Visit-1 Weight_SC",
        "Combined-flow weight     : Visit-2 Weight_SC",
        "Panel key                : Exact HHID equality",
        "Common panel             : 108,421 households",
        "",
        "LOCKED ASSET METHOD",
        "-------------------",
        "Included components      : 9",
        "Consumer durables        : EXCLUDED",
        "Bullion / ornaments      : EXCLUDED",
        "",
        "LOCKED DEBT METHOD",
        "------------------",
        "Debt block               : Visit-1 Block 14",
        "Outstanding field        : b14_q17",
        "Reference date           : 30-06-2012",
        "Kind loans Block 15      : EXCLUDED from official IOI/AOD",
        "",
        "LOCKED BLOCK-16 METHOD",
        "----------------------",
        "FCE columns              : q4 + q5 + q6 + q7",
        "Normal repairs q8        : separate / excluded from FCE",
        "Land purchase items      : 1, 4, 5, 14",
        "Subtotal items           : 97, 98 excluded",
        "Disposals q12-q14        : not netted from FCE",
        "",
        f"Methodology checks       : {len(checks)}",
        f"Passed checks            : {passed_checks}",
        f"Failed checks            : {failed_checks}",
        f"Errors                   : {len(errors)}",
        f"Warnings                 : {len(warnings)}",
        f"Disclosures              : {len(disclosures)}",
        "",
        f"Methodology JSON         : {METHODOLOGY_JSON}",
        f"Asset methodology        : {ASSET_MAP_FILE}",
        f"Agency codebook          : {AGENCY_CODEBOOK_FILE}",
        f"Interest codebook        : {INTEREST_CODEBOOK_FILE}",
        f"Purpose codebook         : {PURPOSE_CODEBOOK_FILE}",
        f"Block16 variable map     : {BLOCK16_VARIABLE_MAP_FILE}",
        f"Block16 item codebook    : {BLOCK16_ITEM_CODEBOOK_FILE}",
        f"Official controls        : {OFFICIAL_CONTROLS_FILE}",
        f"Reference manifest       : {REFERENCE_MANIFEST_FILE}",
        f"Required-variable audit  : {VARIABLE_CHECK_FILE}",
        f"Methodology checks       : {METHODOLOGY_CHECK_FILE}",
        "",
    ]

    if disclosures:
        lines.append(
            "DISCLOSURES:"
        )

        for disclosure in disclosures:
            lines.append(
                f"  - {disclosure}"
            )

        lines.append("")

    if warnings:
        lines.append(
            "WARNINGS:"
        )

        for warning in warnings:
            lines.append(
                f"  - {warning}"
            )

        lines.append("")

    if errors:
        lines.append(
            "ERRORS:"
        )

        for error in errors:
            lines.append(
                f"  - {error}"
            )

        lines.append("")

    lines.extend([
        f"STEP 01C STATUS: {status}",
        "=" * 78,
    ])

    summary = "\n".join(
        lines
    )

    SUMMARY_FILE.write_text(
        summary,
        encoding="utf-8",
    )

    print(
        "\n" + summary
    )

    if status == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()