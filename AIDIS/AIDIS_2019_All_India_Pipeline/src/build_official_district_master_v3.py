from pathlib import Path
import re

import pandas as pd
import pymupdf
import pymupdf4llm


# ============================================================
# PROJECT CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PDF_FILE = (
    PROJECT_ROOT
    / "input"
    / "reference"
    / "NSS_77th_Vol_I.pdf"
)

DISTRICT_MASTER_FILE = (
    PROJECT_ROOT
    / "config"
    / "district_master.csv"
)

STATE_MASTER_FILE = (
    PROJECT_ROOT
    / "config"
    / "state_master.csv"
)

REPORT_DIR = (
    PROJECT_ROOT
    / "output"
    / "reports"
)

REPORT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# IMPORTANT PAGE RANGE
# ============================================================

# Human-readable PDF pages.
APPENDIX_START_PAGE = 249
APPENDIX_END_PAGE = 277

# PyMuPDF / PyMuPDF4LLM uses 0-based page indexes.
#
# Human page 249 -> index 248
# Human page 277 -> index 276
APPENDIX_PAGE_INDEXES = list(
    range(
        APPENDIX_START_PAGE - 1,
        APPENDIX_END_PAGE
    )
)


# ============================================================
# OUTPUT FILES
# ============================================================

MARKDOWN_FILE = (
    REPORT_DIR
    / "nss77_district_appendix.md"
)

OFFICIAL_LOOKUP_FILE = (
    REPORT_DIR
    / "official_district_lookup_v3.csv"
)

VALIDATION_FILE = (
    REPORT_DIR
    / "district_mapping_validation_v3.csv"
)

UNMAPPED_FILE = (
    REPORT_DIR
    / "unmapped_districts_v3.csv"
)

EXTRA_OFFICIAL_FILE = (
    REPORT_DIR
    / "official_not_in_aidis_v3.csv"
)

PARSER_ISSUES_FILE = (
    REPORT_DIR
    / "district_parser_issues_v3.csv"
)

FINAL_CANDIDATE_FILE = (
    PROJECT_ROOT
    / "config"
    / "district_master_final_candidate.csv"
)


# ============================================================
# EXPECTED AIDIS DISTRICT COUNT
# ============================================================

EXPECTED_AIDIS_DISTRICTS = 682


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_code(value, width):
    """
    Normalize State_ID, District_Code and District_ID.

    Examples
    --------
    State:
        1  -> 01
        27 -> 27

    District:
        1  -> 01

    District ID:
        101  -> 0101
        2701 -> 2701
    """

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    if value == "":
        return ""

    return value.zfill(width)


def clean_text(value):
    """
    Clean Markdown / PDF text without changing the
    actual district spelling.
    """

    if value is None:
        return ""

    value = str(value)

    # Remove HTML tags while preserving textual content.
    value = re.sub(
        r"<[^>]+>",
        "",
        value
    )

    # Remove Markdown formatting.
    value = (
        value
        .replace("**", "")
        .replace("__", "")
    )

    # Normalize whitespace.
    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip(" .")


def normalize_name(value):
    """
    Normalize district names only for comparison.

    Original names are NEVER replaced by this normalized text.
    """

    value = clean_text(
        value
    ).casefold()

    return re.sub(
        r"[^a-z0-9]+",
        "",
        value
    )


def split_br(value):
    """
    Split Markdown cells containing <br>.

    Example:

        Hassan<br>(20)<br>Kodagu<br>(22)

    becomes:

        Hassan
        (20)
        Kodagu
        (22)
    """

    if value is None:
        return []

    parts = re.split(
        r"(?i)<br\s*/?>",
        str(value)
    )

    result = []

    for part in parts:

        part = clean_text(
            part
        )

        if part:
            result.append(
                part
            )

    return result


# ============================================================
# STEP 1
# VALIDATE THE PDF
# ============================================================

def validate_pdf():

    print("\n" + "=" * 76)
    print("VALIDATING NSS 77TH ROUND PDF")
    print("=" * 76)

    if not PDF_FILE.exists():

        raise FileNotFoundError(
            f"\nPDF not found:\n{PDF_FILE}"
        )

    document = pymupdf.open(
        PDF_FILE
    )

    page_count = document.page_count

    print(
        f"\nPDF file:\n{PDF_FILE}"
    )

    print(
        f"\nPDF pages: {page_count}"
    )

    # --------------------------------------------------------
    # Read first 15 pages using native PDF text extraction.
    #
    # This is more reliable for document identification than
    # checking the Markdown conversion.
    # --------------------------------------------------------

    sample_page_count = min(
        15,
        page_count
    )

    first_pages_text = "\n".join(
        document[index].get_text(
            "text"
        )
        for index in range(
            sample_page_count
        )
    )

    document.close()

    normalized = re.sub(
        r"\s+",
        " ",
        first_pages_text
    ).casefold()

    # --------------------------------------------------------
    # Flexible identity tests
    # --------------------------------------------------------

    nss77_match = re.search(
        r"\bnss\s*77(?:th)?\s*round\b",
        normalized,
        flags=re.IGNORECASE
    )

    debt_match = (
        "debt and investment"
        in normalized
    )

    field_staff_match = (
        "instructions to field staff"
        in normalized
    )

    print(
        "\nPDF identity checks:"
    )

    print(
        f"  NSS 77th Round           : "
        f"{bool(nss77_match)}"
    )

    print(
        f"  Debt and Investment      : "
        f"{debt_match}"
    )

    print(
        f"  Instructions Field Staff : "
        f"{field_staff_match}"
    )

    if not nss77_match:

        raise ValueError(
            "\nERROR:\n"
            "Could not verify 'NSS 77th Round' "
            "from the PDF."
        )

    if not debt_match:

        raise ValueError(
            "\nERROR:\n"
            "Could not verify 'Debt and Investment' "
            "from the PDF."
        )

    if not field_staff_match:

        raise ValueError(
            "\nERROR:\n"
            "Could not verify 'Instructions to Field Staff' "
            "from the PDF."
        )

    if page_count < APPENDIX_END_PAGE:

        raise ValueError(
            f"\nPDF contains only {page_count} pages, "
            f"but page {APPENDIX_END_PAGE} is required."
        )

    print(
        "\nPDF IDENTITY: PASS"
    )

    return page_count


# ============================================================
# STEP 2
# CONVERT ONLY APPENDIX PAGES TO MARKDOWN
# ============================================================

def generate_appendix_markdown():

    print("\n" + "=" * 76)
    print("EXTRACTING APPENDIX PAGES")
    print("=" * 76)

    print(
        f"\nOnly processing PDF pages "
        f"{APPENDIX_START_PAGE}-{APPENDIX_END_PAGE}"
    )

    print(
        f"Total pages to process: "
        f"{len(APPENDIX_PAGE_INDEXES)}"
    )

    markdown = pymupdf4llm.to_markdown(
        str(PDF_FILE),

        pages=APPENDIX_PAGE_INDEXES,

        show_progress=True,

        page_separators=True
    )

    MARKDOWN_FILE.write_text(
        markdown,
        encoding="utf-8"
    )

    print(
        "\nAppendix Markdown created:"
    )

    print(
        MARKDOWN_FILE
    )

    return markdown


# ============================================================
# STEP 3
# ISOLATE APPENDIX-II DISTRICT SECTION
# ============================================================

def isolate_district_appendix(
    markdown
):
    """
    Find:

        LIST OF NSS REGIONS AND THEIR COMPOSITION

    and ignore any content appearing before Appendix-II.
    """

    pattern = re.compile(
        r"list\s+of\s+nss\s+regions\s+"
        r"and\s+their\s+composition",
        flags=re.IGNORECASE
    )

    match = pattern.search(
        markdown
    )

    if match:

        print(
            "\nDistrict Appendix-II heading found."
        )

        return markdown[
            match.start():
        ]

    # --------------------------------------------------------
    # Fallback:
    #
    # Some Markdown conversions may insert formatting between
    # heading words.
    #
    # Do not fail immediately. The parser itself will still
    # only process rows that match the NSS district structure.
    # --------------------------------------------------------

    print(
        "\nWARNING:"
        "\nExact Appendix-II heading was not detected."
        "\nThe parser will inspect the selected appendix "
        "pages directly."
    )

    return markdown


# ============================================================
# STEP 4
# PARSE SERIAL NUMBERS
# ============================================================

def parse_serial_numbers(
    value
):
    """
    Examples:

        340.

    or:

        340.<br>341.<br>342.

    Returns integer serial numbers.
    """

    serial_numbers = []

    for token in split_br(
        value
    ):

        matches = re.findall(
            r"(?<!\d)(\d+)\.?",
            token
        )

        for match in matches:

            serial_numbers.append(
                int(match)
            )

    return serial_numbers


# ============================================================
# STEP 5
# PARSE 7-COLUMN TABLE FORMAT
# ============================================================

def parse_separate_name_code(
    name_cell,
    code_cell
):
    """
    Seven-column layout:

        District Name | District Code

    Example:

        Nandurbar | (01)

    Multiple values may exist inside one Markdown row.
    """

    names = [
        clean_text(item)
        for item in split_br(
            name_cell
        )
        if clean_text(item)
    ]

    codes = []

    for token in split_br(
        code_cell
    ):

        parenthesized = re.findall(
            r"\((\d{1,2})\)",
            token
        )

        if parenthesized:

            for code in parenthesized:

                codes.append(
                    code.zfill(2)
                )

            continue

        if re.fullmatch(
            r"\d{1,2}",
            token
        ):

            codes.append(
                token.zfill(2)
            )

    if len(names) != len(codes):

        return []

    return list(
        zip(
            names,
            codes
        )
    )


# ============================================================
# STEP 6
# PARSE 6-COLUMN TABLE FORMAT
# ============================================================

def parse_combined_name_code(
    value
):
    """
    Some Markdown tables merge district name and code
    into one cell.

    Examples:

        Adilabad<br>(01)

        Khargone (West Nimar)<br>(23)

    This function converts them to:

        ("Adilabad", "01")
    """

    pairs = []

    pending_name_parts = []

    for token in split_br(
        value
    ):

        # ----------------------------------------------------
        # Case:
        #
        # (01)
        # ----------------------------------------------------

        code_only = re.fullmatch(
            r"\((\d{1,2})\)",
            token
        )

        if code_only:

            district_name = clean_text(
                " ".join(
                    pending_name_parts
                )
            )

            if district_name:

                pairs.append(
                    (
                        district_name,
                        code_only
                        .group(1)
                        .zfill(2)
                    )
                )

            pending_name_parts = []

            continue

        # ----------------------------------------------------
        # Case:
        #
        # Adilabad (01)
        #
        # or
        #
        # Y.S.R. (Cuddapah) (10)
        #
        # The final parentheses are interpreted as code.
        # ----------------------------------------------------

        combined = re.match(
            r"^(.*?)\s*\((\d{1,2})\)\s*$",
            token
        )

        if (
            combined
            and
            combined.group(1).strip()
        ):

            pending_name_parts.append(
                combined
                .group(1)
                .strip()
            )

            district_name = clean_text(
                " ".join(
                    pending_name_parts
                )
            )

            pairs.append(
                (
                    district_name,
                    combined
                    .group(2)
                    .zfill(2)
                )
            )

            pending_name_parts = []

            continue

        pending_name_parts.append(
            token
        )

    return pairs


# ============================================================
# STEP 7
# HEADER DETECTION
# ============================================================

def is_header_line(
    line
):

    lower = line.casefold()

    if "state/u.t" in lower:
        return True

    if "state/ut" in lower:
        return True

    if "name of district" in lower:
        return True

    if "detailed composition" in lower:
        return True

    # Markdown separator.
    if re.match(
        r"^\|\s*:?-+",
        line
    ):
        return True

    # Ignore column-number header:
    #
    # (1) (2) (3) (4) (5) (6) (7)
    number_headers = sum(
        f"({number})" in line
        for number in range(
            1,
            8
        )
    )

    if number_headers >= 5:
        return True

    return False


# ============================================================
# STEP 8
# PARSE OFFICIAL DISTRICT TABLE
# ============================================================

def parse_official_districts(
    markdown
):

    print("\n" + "=" * 76)
    print("PARSING NSS 77TH DISTRICT TABLE")
    print("=" * 76)

    current_state = ""

    current_region = ""

    records = []

    issues = []

    table_lines_examined = 0

    for line_number, line in enumerate(
        markdown.splitlines(),
        start=1
    ):

        line = line.strip()

        if not line.startswith("|"):
            continue

        if is_header_line(
            line
        ):
            continue

        # ----------------------------------------------------
        # VERY IMPORTANT
        #
        # Preserve empty Markdown columns.
        #
        # Do NOT use:
        #
        #     line.strip("|").split("|")
        #
        # because that caused the V2 State_ID corruption.
        # ----------------------------------------------------

        cells = line.split("|")[1:-1]

        if len(cells) < 6:
            continue

        table_lines_examined += 1

        # ----------------------------------------------------
        # REGION CODE
        #
        # NSS Region example:
        #
        # 271
        #
        # First two digits:
        #
        # 27 = Maharashtra
        #
        # This is our reliable state anchor.
        # ----------------------------------------------------

        region_cell = clean_text(
            cells[2]
        )

        region_match = re.search(
            r"(?<!\d)(\d{3})(?!\d)",
            region_cell
        )

        if region_match:

            region_code = (
                region_match.group(1)
            )

            current_region = (
                region_code
            )

            current_state = (
                region_code[:2]
            )

        # ----------------------------------------------------
        # DISTRICT SERIAL NUMBER
        # ----------------------------------------------------

        serial_numbers = (
            parse_serial_numbers(
                cells[4]
            )
        )

        if not serial_numbers:
            continue

        if not current_state:

            issues.append(
                {
                    "Markdown_Line":
                        line_number,

                    "Reason":
                        "STATE_NOT_RESOLVED",

                    "Source_Line":
                        line
                }
            )

            continue

        # ----------------------------------------------------
        # District names/codes.
        # ----------------------------------------------------

        if len(cells) >= 7:

            pairs = (
                parse_separate_name_code(
                    cells[5],
                    cells[6]
                )
            )

        else:

            pairs = (
                parse_combined_name_code(
                    cells[5]
                )
            )

        # ----------------------------------------------------
        # Safety:
        #
        # We will NEVER guess which district belongs to which
        # serial number.
        # ----------------------------------------------------

        if (
            len(serial_numbers)
            !=
            len(pairs)
        ):

            issues.append(
                {
                    "Markdown_Line":
                        line_number,

                    "Reason":
                        (
                            "COUNT_MISMATCH "
                            f"serials={len(serial_numbers)} "
                            f"district_pairs={len(pairs)}"
                        ),

                    "Source_Line":
                        line
                }
            )

            continue

        # ----------------------------------------------------
        # Save district records
        # ----------------------------------------------------

        for (
            serial_number,
            district_pair
        ) in zip(
            serial_numbers,
            pairs
        ):

            (
                district_name,
                district_code
            ) = district_pair

            records.append(
                {
                    "Official_Serial_No":
                        serial_number,

                    "State_ID":
                        current_state,

                    "NSS_Region_Code":
                        current_region,

                    "District_Code":
                        district_code,

                    "District_ID":
                        (
                            current_state
                            +
                            district_code
                        ),

                    "District_Name":
                        district_name,

                    "Markdown_Line":
                        line_number
                }
            )

    official = pd.DataFrame(
        records
    )

    parser_issues = pd.DataFrame(
        issues
    )

    print(
        f"\nMarkdown table lines examined : "
        f"{table_lines_examined:,}"
    )

    print(
        f"District records extracted    : "
        f"{len(official):,}"
    )

    print(
        f"Parser issues found           : "
        f"{len(parser_issues):,}"
    )

    return (
        official,
        parser_issues
    )


# ============================================================
# STEP 9
# VALIDATE OFFICIAL EXTRACTION
# ============================================================

def validate_official_extraction(
    official,
    parser_issues
):

    print("\n" + "=" * 76)
    print("VALIDATING OFFICIAL DISTRICT EXTRACTION")
    print("=" * 76)

    if not parser_issues.empty:

        parser_issues.to_csv(
            PARSER_ISSUES_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        print(
            "\nParser issues saved:"
        )

        print(
            PARSER_ISSUES_FILE
        )

        raise ValueError(
            "\nDistrict parser found ambiguous rows."
            "\nNo District Master has been modified."
        )

    if official.empty:

        raise ValueError(
            "\nNo official district rows were extracted."
        )

    # --------------------------------------------------------
    # Duplicate official serial numbers
    # --------------------------------------------------------

    duplicate_serials = official[
        official.duplicated(
            subset=[
                "Official_Serial_No"
            ],
            keep=False
        )
    ]

    if not duplicate_serials.empty:

        print(
            "\nDuplicate serial numbers:"
        )

        print(
            duplicate_serials.to_string(
                index=False
            )
        )

        raise ValueError(
            "Duplicate official serial numbers detected."
        )

    # --------------------------------------------------------
    # Duplicate State_ID + District_Code
    # --------------------------------------------------------

    duplicate_codes = official[
        official.duplicated(
            subset=[
                "State_ID",
                "District_Code"
            ],
            keep=False
        )
    ]

    if not duplicate_codes.empty:

        print(
            "\nDuplicate district codes:"
        )

        print(
            duplicate_codes.to_string(
                index=False
            )
        )

        raise ValueError(
            "Duplicate State_ID + District_Code "
            "detected."
        )

    # --------------------------------------------------------
    # Check official serial sequence
    # --------------------------------------------------------

    serial_numbers = sorted(
        official[
            "Official_Serial_No"
        ]
        .astype(int)
        .unique()
        .tolist()
    )

    minimum_serial = min(
        serial_numbers
    )

    maximum_serial = max(
        serial_numbers
    )

    expected_serials = set(
        range(
            minimum_serial,
            maximum_serial + 1
        )
    )

    actual_serials = set(
        serial_numbers
    )

    missing_serials = sorted(
        expected_serials
        -
        actual_serials
    )

    print(
        f"\nMinimum official serial : "
        f"{minimum_serial}"
    )

    print(
        f"Maximum official serial : "
        f"{maximum_serial}"
    )

    print(
        f"Official district rows  : "
        f"{len(official):,}"
    )

    print(
        f"Missing serial numbers  : "
        f"{len(missing_serials)}"
    )

    if missing_serials:

        print(
            "\nMissing serials:"
        )

        print(
            missing_serials
        )

        raise ValueError(
            "\nOfficial district serial sequence "
            "is incomplete."
        )

    print(
        "\nOFFICIAL DISTRICT EXTRACTION: PASS"
    )


# ============================================================
# STEP 10
# ADD STATE NAMES
# ============================================================

def add_state_names(
    official
):

    state_master = pd.read_csv(
        STATE_MASTER_FILE,
        dtype=str
    )

    state_master[
        "State_ID"
    ] = state_master[
        "State_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    state_lookup = dict(
        zip(
            state_master[
                "State_ID"
            ],
            state_master[
                "State_Name"
            ]
        )
    )

    official[
        "State_Name"
    ] = official[
        "State_ID"
    ].map(
        state_lookup
    )

    unknown = official[
        official[
            "State_Name"
        ].isna()
    ]

    if not unknown.empty:

        raise ValueError(
            "\nOfficial extraction contains unknown "
            "State_ID values."
        )

    official = official[
        [
            "Official_Serial_No",
            "State_ID",
            "State_Name",
            "NSS_Region_Code",
            "District_Code",
            "District_ID",
            "District_Name",
            "Markdown_Line"
        ]
    ]

    return official


# ============================================================
# STEP 11
# MATCH WITH OUR 682 AIDIS DISTRICTS
# ============================================================

def match_with_aidis(
    official
):

    print("\n" + "=" * 76)
    print("MATCHING OFFICIAL DISTRICTS WITH AIDIS")
    print("=" * 76)

    district_master = pd.read_csv(
        DISTRICT_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    district_master[
        "State_ID"
    ] = district_master[
        "State_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    district_master[
        "District_Code"
    ] = district_master[
        "District_Code"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    district_master[
        "District_ID"
    ] = district_master[
        "District_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            4
        )
    )

    if (
        len(district_master)
        !=
        EXPECTED_AIDIS_DISTRICTS
    ):

        raise ValueError(
            f"\nExpected "
            f"{EXPECTED_AIDIS_DISTRICTS} "
            f"AIDIS district rows, but found "
            f"{len(district_master)}."
        )

    report = district_master.merge(
        official[
            [
                "State_ID",
                "District_Code",
                "District_Name",
                "NSS_Region_Code",
                "Official_Serial_No"
            ]
        ],
        on=[
            "State_ID",
            "District_Code"
        ],
        how="left",
        suffixes=(
            "_Current",
            "_Official"
        )
    )

    report.rename(
        columns={
            "District_Name_Current":
                "Existing_District_Name",

            "District_Name_Official":
                "Official_District_Name"
        },
        inplace=True
    )

    matched_mask = (
        report[
            "Official_District_Name"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    )

    report[
        "Mapping_Status"
    ] = "UNMATCHED"

    report.loc[
        matched_mask,
        "Mapping_Status"
    ] = "MATCHED_NSS77"

    # --------------------------------------------------------
    # Existing-name comparison.
    #
    # This is especially important for Maharashtra because
    # those 34 names already came from the working reference.
    # --------------------------------------------------------

    report[
        "Existing_Name_Matches_Official"
    ] = False

    existing_name_mask = (
        report[
            "Existing_District_Name"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
        &
        matched_mask
    )

    for index in report[
        existing_name_mask
    ].index:

        existing = report.at[
            index,
            "Existing_District_Name"
        ]

        official_name = report.at[
            index,
            "Official_District_Name"
        ]

        report.at[
            index,
            "Existing_Name_Matches_Official"
        ] = (
            normalize_name(
                existing
            )
            ==
            normalize_name(
                official_name
            )
        )

    report.to_csv(
        VALIDATION_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    unmatched = report[
        ~matched_mask
    ].copy()

    unmatched.to_csv(
        UNMAPPED_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # Official districts which do not exist in our 682-code
    # AIDIS skeleton.
    # --------------------------------------------------------

    official_extra = official.merge(
        district_master[
            [
                "State_ID",
                "District_Code"
            ]
        ],
        on=[
            "State_ID",
            "District_Code"
        ],
        how="left",
        indicator=True
    )

    official_extra = official_extra[
        official_extra[
            "_merge"
        ]
        ==
        "left_only"
    ].drop(
        columns=[
            "_merge"
        ]
    )

    official_extra.to_csv(
        EXTRA_OFFICIAL_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    matched_count = int(
        matched_mask.sum()
    )

    print(
        f"\nOfficial NSS77 districts : "
        f"{len(official):,}"
    )

    print(
        f"AIDIS districts           : "
        f"{len(district_master):,}"
    )

    print(
        f"AIDIS districts matched   : "
        f"{matched_count:,}"
    )

    print(
        f"AIDIS districts unmatched : "
        f"{len(unmatched):,}"
    )

    print(
        f"Official not in AIDIS     : "
        f"{len(official_extra):,}"
    )

    return (
        district_master,
        report,
        unmatched,
        official_extra,
        matched_count
    )


# ============================================================
# STEP 12
# MAHARASHTRA CONTROL TEST
# ============================================================

def validate_maharashtra(
    report
):

    print("\n" + "=" * 76)
    print("MAHARASHTRA CONTROL CHECK")
    print("=" * 76)

    maharashtra = report[
        report[
            "State_ID"
        ]
        ==
        "27"
    ].copy()

    total = len(
        maharashtra
    )

    code_matches = int(
        (
            maharashtra[
                "Mapping_Status"
            ]
            ==
            "MATCHED_NSS77"
        ).sum()
    )

    name_matches = int(
        maharashtra[
            "Existing_Name_Matches_Official"
        ].sum()
    )

    print(
        f"\nMaharashtra AIDIS districts : "
        f"{total}"
    )

    print(
        f"Maharashtra codes matched   : "
        f"{code_matches}"
    )

    print(
        f"Maharashtra names matched   : "
        f"{name_matches}"
    )

    if (
        code_matches
        !=
        total
    ):

        failed = maharashtra[
            maharashtra[
                "Mapping_Status"
            ]
            !=
            "MATCHED_NSS77"
        ]

        print(
            "\nUnmatched Maharashtra codes:"
        )

        print(
            failed[
                [
                    "District_ID",
                    "Existing_District_Name",
                    "Official_District_Name"
                ]
            ]
            .to_string(
                index=False
            )
        )

        raise ValueError(
            "\nMaharashtra district-code "
            "control failed."
        )

    if (
        name_matches
        !=
        total
    ):

        failed = maharashtra[
            ~maharashtra[
                "Existing_Name_Matches_Official"
            ]
        ]

        print(
            "\nMaharashtra name differences:"
        )

        print(
            failed[
                [
                    "District_ID",
                    "Existing_District_Name",
                    "Official_District_Name"
                ]
            ]
            .to_string(
                index=False
            )
        )

        raise ValueError(
            "\nMaharashtra name control failed."
        )

    print(
        "\nMAHARASHTRA CONTROL: PASS"
    )


# ============================================================
# STEP 13
# CREATE FINAL DISTRICT MASTER CANDIDATE
# ============================================================

def create_final_candidate(
    district_master,
    report
):

    official_lookup = dict(
        zip(
            report[
                "District_ID"
            ],
            report[
                "Official_District_Name"
            ]
        )
    )

    final_master = (
        district_master.copy()
    )

    final_master[
        "District_Name"
    ] = final_master[
        "District_ID"
    ].map(
        official_lookup
    )

    final_master[
        "Source"
    ] = (
        "MoSPI NSS 77th Round Vol-I Appendix II"
    )

    final_master[
        "Status"
    ] = "VERIFIED_NSS77"

    final_master[
        "Notes"
    ] = (
        "Matched using State_ID + District_Code "
        "against NSS 77th Round district composition"
    )

    # Maharashtra received an independent second validation.
    maharashtra_mask = (
        final_master[
            "State_ID"
        ]
        ==
        "27"
    )

    final_master.loc[
        maharashtra_mask,
        "Notes"
    ] = (
        "NSS77 mapping also matches the existing "
        "Maharashtra reference"
    )

    final_master.to_csv(
        FINAL_CANDIDATE_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    return final_master


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():

    print("=" * 76)
    print("AIDIS NSS 77 DISTRICT MASTER BUILDER - V3.1")
    print("=" * 76)

    # --------------------------------------------------------
    # 1. Check required files
    # --------------------------------------------------------

    for file_path in [
        PDF_FILE,
        DISTRICT_MASTER_FILE,
        STATE_MASTER_FILE
    ]:

        if not file_path.exists():

            raise FileNotFoundError(
                f"\nRequired file not found:\n"
                f"{file_path}"
            )

    # --------------------------------------------------------
    # 2. Validate actual source PDF
    # --------------------------------------------------------

    validate_pdf()

    # --------------------------------------------------------
    # 3. Process only PDF pages 249-277
    # --------------------------------------------------------

    markdown = (
        generate_appendix_markdown()
    )

    # --------------------------------------------------------
    # 4. Find Appendix-II section
    # --------------------------------------------------------

    district_appendix = (
        isolate_district_appendix(
            markdown
        )
    )

    # --------------------------------------------------------
    # 5. Parse official district directory
    # --------------------------------------------------------

    (
        official,
        parser_issues
    ) = parse_official_districts(
        district_appendix
    )

    # --------------------------------------------------------
    # 6. Validate official extraction
    # --------------------------------------------------------

    validate_official_extraction(
        official,
        parser_issues
    )

    # --------------------------------------------------------
    # 7. Add State_Name
    # --------------------------------------------------------

    official = add_state_names(
        official
    )

    official.to_csv(
        OFFICIAL_LOOKUP_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 8. Match official directory to AIDIS skeleton
    # --------------------------------------------------------

    (
        district_master,
        report,
        unmatched,
        official_extra,
        matched_count
    ) = match_with_aidis(
        official
    )

    # --------------------------------------------------------
    # 9. Maharashtra control
    # --------------------------------------------------------

    validate_maharashtra(
        report
    )

    # --------------------------------------------------------
    # 10. Final gate
    # --------------------------------------------------------

    if (
        matched_count
        !=
        EXPECTED_AIDIS_DISTRICTS
    ):

        print("\n" + "=" * 76)
        print("UNMATCHED AIDIS DISTRICTS")
        print("=" * 76)

        if not unmatched.empty:

            print(
                unmatched[
                    [
                        "State_ID",
                        "State_Name",
                        "District_Code",
                        "District_ID"
                    ]
                ]
                .to_string(
                    index=False
                )
            )

        raise ValueError(
            f"\nOnly {matched_count} of "
            f"{EXPECTED_AIDIS_DISTRICTS} "
            "AIDIS district codes matched."
            "\n\nNo final District Master was promoted."
        )

    # --------------------------------------------------------
    # 11. Create final candidate
    # --------------------------------------------------------

    final_master = create_final_candidate(
        district_master,
        report
    )

    # --------------------------------------------------------
    # 12. Final summary
    # --------------------------------------------------------

    print("\n" + "=" * 76)
    print("FINAL DISTRICT MASTER SUMMARY")
    print("=" * 76)

    print(
        f"\nFinal candidate rows : "
        f"{len(final_master):,}"
    )

    print(
        "AIDIS unmatched      : 0"
    )

    print(
        f"Official extras      : "
        f"{len(official_extra):,}"
    )

    print(
        "\nDISTRICT MASTER STATUS: PASS"
    )

    print(
        "\nFinal candidate:"
    )

    print(
        FINAL_CANDIDATE_FILE
    )

    print(
        "\nOriginal district_master.csv "
        "has NOT been overwritten."
    )

    print("\nReports created:")

    print(
        f"\n{OFFICIAL_LOOKUP_FILE}"
    )

    print(
        f"\n{VALIDATION_FILE}"
    )

    print(
        f"\n{UNMAPPED_FILE}"
    )

    print(
        f"\n{EXTRA_OFFICIAL_FILE}"
    )

    print("\n" + "=" * 76)


if __name__ == "__main__":
    main()