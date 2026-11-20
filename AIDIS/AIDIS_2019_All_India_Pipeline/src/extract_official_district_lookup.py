from pathlib import Path
import re

import pandas as pd
import pymupdf


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PDF_FILE = (
    PROJECT_ROOT
    / "input"
    / "reference"
    / "NSS_Region_District_Composition.pdf"
)

STATE_MASTER_FILE = (
    PROJECT_ROOT
    / "config"
    / "state_master.csv"
)

DISTRICT_MASTER_FILE = (
    PROJECT_ROOT
    / "config"
    / "district_master.csv"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

OFFICIAL_LOOKUP_FILE = (
    REPORT_DIR
    / "official_district_lookup_candidates.csv"
)

MATCH_REPORT_FILE = (
    REPORT_DIR
    / "district_mapping_report.csv"
)

UNMAPPED_FILE = (
    REPORT_DIR
    / "unmapped_districts.csv"
)

CONFLICT_FILE = (
    REPORT_DIR
    / "district_mapping_conflicts.csv"
)

RAW_TABLE_FILE = (
    REPORT_DIR
    / "nss_pdf_extracted_tables.txt"
)


# ============================================================
# HELPERS
# ============================================================

def normalize_code(value, width):
    """
    Normalize numeric codes while preserving leading zeroes.

    Examples:

        1     -> 01
        01    -> 01
        27.0  -> 27

        101   -> 0101
        2701  -> 2701
    """

    if pd.isna(value):
        return None

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    if not value:
        return None

    return value.zfill(width)


def clean_text(value):
    """
    Clean text extracted from PDF tables.
    """

    if value is None:
        return ""

    value = str(value)

    value = value.replace("\r", "\n")

    value = re.sub(
        r"[ \t]+",
        " ",
        value
    )

    return value.strip()


def clean_district_name(value):
    """
    Clean a district name extracted from PDF.
    """

    value = clean_text(value)

    value = value.replace("\n", " ")

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    # Remove district serial number if table extraction
    # accidentally places it inside the name.
    value = re.sub(
        r"^\d+\.\s*",
        "",
        value
    )

    return value.strip()


def extract_parenthesized_codes(value):
    """
    Extract codes such as:

        (01)
        (27)
        (01) (02) (03)

    Returns:
        ["01", "02", "03"]
    """

    value = clean_text(value)

    return re.findall(
        r"\((\d{1,2})\)",
        value
    )


def get_state_code(value, valid_state_ids):
    """
    Look for a State/UT code inside the State/U.T. table cell.

    Example:

        Maharashtra (27)

    -> 27
    """

    codes = extract_parenthesized_codes(value)

    for code in codes:

        code = code.zfill(2)

        if code in valid_state_ids:
            return code

    return None


def get_district_codes(value):
    """
    Extract district-local codes from the rightmost column.

    Examples:

        (01)

    or:

        (01)
        (02)
        (03)
    """

    codes = extract_parenthesized_codes(value)

    return [
        code.zfill(2)
        for code in codes
    ]


def split_nonempty_lines(value):
    """
    Split table cell text into non-empty lines.
    """

    value = clean_text(value)

    values = []

    for line in value.splitlines():

        line = clean_district_name(line)

        if line:
            values.append(line)

    return values


# ============================================================
# EXTRACT PDF TABLES
# ============================================================

def extract_pdf_candidates(
    pdf_path,
    valid_state_ids
):

    print("\nOpening official NSS PDF:")
    print(pdf_path)

    document = pymupdf.open(pdf_path)

    print(
        f"\nPDF pages detected: "
        f"{len(document)}"
    )

    current_state = None

    candidates = []

    raw_debug = []

    table_counter = 0

    # --------------------------------------------------------
    # Process page-by-page
    # --------------------------------------------------------

    for page_number, page in enumerate(
        document,
        start=1
    ):

        print(
            f"Processing page "
            f"{page_number}/{len(document)}..."
        )

        try:

            found_tables = page.find_tables()

            tables = found_tables.tables

        except Exception as error:

            print(
                f"WARNING: Table detection failed "
                f"on page {page_number}: {error}"
            )

            continue

        raw_debug.append(
            "\n"
            + "=" * 80
            + f"\nPAGE {page_number}\n"
            + "=" * 80
            + "\n"
        )

        raw_debug.append(
            f"Tables detected: {len(tables)}\n"
        )

        # ----------------------------------------------------
        # Process each detected table
        # ----------------------------------------------------

        for table_number, table in enumerate(
            tables,
            start=1
        ):

            table_counter += 1

            try:
                rows = table.extract()

            except Exception as error:

                raw_debug.append(
                    f"\nTABLE {table_number} "
                    f"EXTRACTION ERROR: {error}\n"
                )

                continue

            raw_debug.append(
                f"\n--- TABLE {table_number} ---\n"
            )

            if not rows:
                continue

            # ------------------------------------------------
            # Process each table row
            # ------------------------------------------------

            for row_number, row in enumerate(
                rows,
                start=1
            ):

                row = [
                    clean_text(cell)
                    for cell in row
                ]

                raw_debug.append(
                    f"{row_number}: {row}\n"
                )

                # --------------------------------------------
                # Official Appendix-II normally has:
                #
                # 0 = serial no
                # 1 = State/U.T.
                # 2 = NSS region code
                # 3 = NSS region description
                # 4 = district serial no
                # 5 = district name
                # 6 = district code
                #
                # We only process table rows that contain at
                # least enough columns for district name/code.
                # --------------------------------------------

                if len(row) < 6:
                    continue

                # --------------------------------------------
                # Detect state from the first half of row
                # --------------------------------------------

                state_search_cells = (
                    row[:3]
                    if len(row) >= 3
                    else row
                )

                for cell in state_search_cells:

                    detected_state = get_state_code(
                        cell,
                        valid_state_ids
                    )

                    if detected_state:

                        current_state = detected_state

                        break

                if current_state is None:
                    continue

                # --------------------------------------------
                # Assume district name and district code are
                # the final two columns.
                # --------------------------------------------

                district_name_cell = row[-2]

                district_code_cell = row[-1]

                district_codes = get_district_codes(
                    district_code_cell
                )

                if not district_codes:
                    continue

                district_name_lines = (
                    split_nonempty_lines(
                        district_name_cell
                    )
                )

                if not district_name_lines:
                    continue

                # --------------------------------------------
                # CASE 1
                #
                # One district code = whole name cell belongs
                # to that one district.
                # --------------------------------------------

                if len(district_codes) == 1:

                    district_name = clean_district_name(
                        district_name_cell
                    )

                    if district_name:

                        candidates.append(
                            {
                                "State_ID":
                                    current_state,

                                "District_Code":
                                    district_codes[0],

                                "District_Name":
                                    district_name,

                                "PDF_Page":
                                    page_number,

                                "PDF_Table":
                                    table_number,

                                "Extraction_Status":
                                    "SINGLE_CODE"
                            }
                        )

                    continue

                # --------------------------------------------
                # CASE 2
                #
                # Multiple district codes and exactly the same
                # number of district-name lines.
                # --------------------------------------------

                if (
                    len(district_codes)
                    == len(district_name_lines)
                ):

                    for district_code, district_name in zip(
                        district_codes,
                        district_name_lines
                    ):

                        candidates.append(
                            {
                                "State_ID":
                                    current_state,

                                "District_Code":
                                    district_code,

                                "District_Name":
                                    district_name,

                                "PDF_Page":
                                    page_number,

                                "PDF_Table":
                                    table_number,

                                "Extraction_Status":
                                    "MULTI_CODE_ALIGNED"
                            }
                        )

                    continue

                # --------------------------------------------
                # CASE 3
                #
                # More than one code but table line wrapping
                # prevents safe automatic pairing.
                #
                # We intentionally DO NOT GUESS.
                # --------------------------------------------

                candidates.append(
                    {
                        "State_ID":
                            current_state,

                        "District_Code":
                            "",

                        "District_Name":
                            clean_district_name(
                                district_name_cell
                            ),

                        "PDF_Page":
                            page_number,

                        "PDF_Table":
                            table_number,

                        "Extraction_Status":
                            (
                                "REVIEW_MULTI_CODE_"
                                f"NAMES_{len(district_name_lines)}"
                                f"_CODES_{len(district_codes)}"
                            )
                    }
                )

    document.close()

    # --------------------------------------------------------
    # Save raw table extraction for debugging
    # --------------------------------------------------------

    RAW_TABLE_FILE.write_text(
        "".join(raw_debug),
        encoding="utf-8"
    )

    print(
        f"\nTotal tables detected: "
        f"{table_counter}"
    )

    return pd.DataFrame(candidates)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 72)
    print("AIDIS OFFICIAL DISTRICT LOOKUP EXTRACTOR")
    print("=" * 72)

    # --------------------------------------------------------
    # 1. Validate files
    # --------------------------------------------------------

    required_files = [
        PDF_FILE,
        STATE_MASTER_FILE,
        DISTRICT_MASTER_FILE
    ]

    for file_path in required_files:

        if not file_path.exists():

            raise FileNotFoundError(
                f"\nRequired file not found:\n"
                f"{file_path}"
            )

    print("\nRequired files found.")

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # 2. Read state master
    # --------------------------------------------------------

    state_master = pd.read_csv(
        STATE_MASTER_FILE,
        dtype=str
    )

    state_master["State_ID"] = (
        state_master["State_ID"]
        .apply(
            lambda value:
            normalize_code(
                value,
                2
            )
        )
    )

    valid_state_ids = set(
        state_master["State_ID"]
        .dropna()
        .tolist()
    )

    state_name_lookup = dict(
        zip(
            state_master["State_ID"],
            state_master["State_Name"]
        )
    )

    print(
        f"\nState/UT codes loaded: "
        f"{len(valid_state_ids)}"
    )

    # --------------------------------------------------------
    # 3. Read AIDIS district master skeleton
    # --------------------------------------------------------

    district_master = pd.read_csv(
        DISTRICT_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    district_master["State_ID"] = (
        district_master["State_ID"]
        .apply(
            lambda value:
            normalize_code(
                value,
                2
            )
        )
    )

    district_master["District_Code"] = (
        district_master["District_Code"]
        .apply(
            lambda value:
            normalize_code(
                value,
                2
            )
        )
    )

    district_master["District_ID"] = (
        district_master["District_ID"]
        .apply(
            lambda value:
            normalize_code(
                value,
                4
            )
        )
    )

    print(
        f"AIDIS district codes loaded: "
        f"{len(district_master)}"
    )

    # --------------------------------------------------------
    # 4. Extract candidate mappings from PDF
    # --------------------------------------------------------

    candidates = extract_pdf_candidates(
        PDF_FILE,
        valid_state_ids
    )

    if candidates.empty:

        raise RuntimeError(
            "\nNo district mappings could be extracted "
            "from the PDF.\n"
            "Please inspect:\n"
            f"{RAW_TABLE_FILE}"
        )

    candidates["State_Name"] = (
        candidates["State_ID"]
        .map(state_name_lookup)
    )

    # --------------------------------------------------------
    # 5. Remove obvious header rows
    # --------------------------------------------------------

    candidates = candidates[
        ~candidates["District_Name"]
        .str.lower()
        .isin(
            [
                "name of district",
                "district",
                "code",
                "detailed composition of region"
            ]
        )
    ].copy()

    # --------------------------------------------------------
    # 6. Create composite District_ID
    # --------------------------------------------------------

    candidates["District_ID"] = ""

    valid_code_mask = (
        candidates["District_Code"]
        .astype(str)
        .str.match(
            r"^\d{2}$"
        )
    )

    candidates.loc[
        valid_code_mask,
        "District_ID"
    ] = (
        candidates.loc[
            valid_code_mask,
            "State_ID"
        ]
        +
        candidates.loc[
            valid_code_mask,
            "District_Code"
        ]
    )

    # --------------------------------------------------------
    # 7. Save complete extraction candidate file
    # --------------------------------------------------------

    candidates = candidates[
        [
            "State_ID",
            "State_Name",
            "District_Code",
            "District_ID",
            "District_Name",
            "PDF_Page",
            "PDF_Table",
            "Extraction_Status"
        ]
    ]

    candidates.to_csv(
        OFFICIAL_LOOKUP_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 8. Keep only safe, code-bearing candidates
    # --------------------------------------------------------

    usable = candidates[
        candidates["District_ID"] != ""
    ].copy()

    # --------------------------------------------------------
    # 9. Find conflicting names for same code
    # --------------------------------------------------------

    name_counts = (
        usable
        .groupby(
            [
                "State_ID",
                "District_Code"
            ]
        )["District_Name"]
        .nunique()
        .reset_index(
            name="Name_Count"
        )
    )

    conflict_keys = name_counts[
        name_counts["Name_Count"] > 1
    ][
        [
            "State_ID",
            "District_Code"
        ]
    ]

    if not conflict_keys.empty:

        conflicts = usable.merge(
            conflict_keys,
            on=[
                "State_ID",
                "District_Code"
            ],
            how="inner"
        )

    else:

        conflicts = pd.DataFrame(
            columns=usable.columns
        )

    conflicts.to_csv(
        CONFLICT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 10. Keep unique official mapping only
    # --------------------------------------------------------

    unique_mapping = (
        usable
        .drop_duplicates(
            subset=[
                "State_ID",
                "District_Code",
                "District_Name"
            ]
        )
        .copy()
    )

    unique_name_count = (
        unique_mapping
        .groupby(
            [
                "State_ID",
                "District_Code"
            ]
        )["District_Name"]
        .transform("nunique")
    )

    unique_mapping = unique_mapping[
        unique_name_count == 1
    ].copy()

    unique_mapping = (
        unique_mapping
        .drop_duplicates(
            subset=[
                "State_ID",
                "District_Code"
            ]
        )
    )

    # --------------------------------------------------------
    # 11. Match official extraction to AIDIS skeleton
    # --------------------------------------------------------

    report = district_master.merge(
        unique_mapping[
            [
                "State_ID",
                "District_Code",
                "District_Name",
                "PDF_Page",
                "Extraction_Status"
            ]
        ],
        on=[
            "State_ID",
            "District_Code"
        ],
        how="left",
        suffixes=(
            "_AIDIS",
            "_PDF"
        )
    )

    report.rename(
        columns={
            "District_Name_AIDIS":
                "Existing_District_Name",

            "District_Name_PDF":
                "PDF_District_Name"
        },
        inplace=True
    )

    report["Mapping_Status"] = "UNMATCHED"

    matched_mask = (
        report["PDF_District_Name"]
        .notna()
        &
        (
            report["PDF_District_Name"]
            .astype(str)
            .str.strip()
            != ""
        )
    )

    report.loc[
        matched_mask,
        "Mapping_Status"
    ] = "CODE_MATCHED"

    # --------------------------------------------------------
    # 12. Maharashtra validation
    # --------------------------------------------------------

    maharashtra = report[
        report["State_ID"] == "27"
    ].copy()

    def normalized_name(value):

        value = str(value).strip().casefold()

        value = re.sub(
            r"[^a-z0-9]+",
            "",
            value
        )

        return value

    maharashtra[
        "Name_Match"
    ] = maharashtra.apply(
        lambda row:
        (
            normalized_name(
                row["Existing_District_Name"]
            )
            ==
            normalized_name(
                row["PDF_District_Name"]
            )
        )
        if (
            str(
                row["PDF_District_Name"]
            ).strip()
            not in [
                "",
                "nan",
                "None"
            ]
        )
        else False,
        axis=1
    )

    mh_total = len(maharashtra)

    mh_code_matched = int(
        (
            maharashtra[
                "Mapping_Status"
            ]
            ==
            "CODE_MATCHED"
        ).sum()
    )

    mh_name_matched = int(
        maharashtra[
            "Name_Match"
        ].sum()
    )

    # --------------------------------------------------------
    # 13. Save mapping report
    # --------------------------------------------------------

    report.to_csv(
        MATCH_REPORT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    unmapped = report[
        report["Mapping_Status"]
        ==
        "UNMATCHED"
    ].copy()

    unmapped.to_csv(
        UNMAPPED_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 14. Summary
    # --------------------------------------------------------

    print("\n" + "=" * 72)
    print("OFFICIAL DISTRICT EXTRACTION SUMMARY")
    print("=" * 72)

    print(
        f"\nRaw candidate records        : "
        f"{len(candidates):,}"
    )

    print(
        f"Usable code/name records     : "
        f"{len(usable):,}"
    )

    print(
        f"Unique safe mappings         : "
        f"{len(unique_mapping):,}"
    )

    print(
        f"AIDIS district codes         : "
        f"{len(district_master):,}"
    )

    print(
        f"AIDIS codes matched          : "
        f"{int(matched_mask.sum()):,}"
    )

    print(
        f"AIDIS codes still unmatched  : "
        f"{len(unmapped):,}"
    )

    print(
        f"Conflicting extracted records: "
        f"{len(conflicts):,}"
    )

    print("\nMAHARASHTRA CONTROL CHECK")
    print("-" * 72)

    print(
        f"Maharashtra AIDIS districts  : "
        f"{mh_total}"
    )

    print(
        f"Maharashtra codes matched    : "
        f"{mh_code_matched}"
    )

    print(
        f"Maharashtra names matched    : "
        f"{mh_name_matched}"
    )

    # --------------------------------------------------------
    # 15. Safety decision
    # --------------------------------------------------------

    if (
        mh_code_matched == mh_total
        and
        mh_name_matched == mh_total
    ):

        print(
            "\nMAHARASHTRA PDF CONTROL: PASS"
        )

    else:

        print(
            "\nMAHARASHTRA PDF CONTROL: REVIEW REQUIRED"
        )

        print(
            "\nIMPORTANT: district_master.csv "
            "has NOT been modified."
        )

    print("\nFiles created:")

    print(
        f"\n1. Candidate lookup:\n"
        f"{OFFICIAL_LOOKUP_FILE}"
    )

    print(
        f"\n2. Match report:\n"
        f"{MATCH_REPORT_FILE}"
    )

    print(
        f"\n3. Unmapped districts:\n"
        f"{UNMAPPED_FILE}"
    )

    print(
        f"\n4. Conflicts:\n"
        f"{CONFLICT_FILE}"
    )

    print(
        f"\n5. Raw PDF table debug:\n"
        f"{RAW_TABLE_FILE}"
    )

    print("\n" + "=" * 72)
    print("EXTRACTION COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()