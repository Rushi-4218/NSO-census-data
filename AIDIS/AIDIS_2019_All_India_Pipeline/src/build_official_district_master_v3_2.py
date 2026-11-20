from pathlib import Path
import re

import pandas as pd
import pymupdf
import pymupdf4llm


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PDF_FILE = (
    PROJECT_ROOT
    / "input"
    / "reference"
    / "NSS_77th_Vol_I.pdf"
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

REPORT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# PDF PAGE RANGE
# ============================================================

APPENDIX_START_PAGE = 249
APPENDIX_END_PAGE = 277

# PyMuPDF uses zero-based page indexes.
APPENDIX_PAGE_INDEXES = list(
    range(
        APPENDIX_START_PAGE - 1,
        APPENDIX_END_PAGE
    )
)


# ============================================================
# EXPECTED AIDIS STRUCTURE
# ============================================================

EXPECTED_AIDIS_DISTRICTS = 682


# ============================================================
# OUTPUT FILES
# ============================================================

MARKDOWN_FILE = (
    REPORT_DIR
    / "nss77_district_appendix_v3_2.md"
)

OFFICIAL_LOOKUP_FILE = (
    REPORT_DIR
    / "official_district_lookup_v3_2.csv"
)

PARSER_ISSUES_FILE = (
    REPORT_DIR
    / "district_parser_issues_v3_2.csv"
)

FALLBACK_REPORT_FILE = (
    REPORT_DIR
    / "native_pdf_fallback_v3_2.csv"
)

VALIDATION_FILE = (
    REPORT_DIR
    / "district_mapping_validation_v3_2.csv"
)

UNMAPPED_FILE = (
    REPORT_DIR
    / "unmapped_districts_v3_2.csv"
)

EXTRA_OFFICIAL_FILE = (
    REPORT_DIR
    / "official_not_in_aidis_v3_2.csv"
)

FINAL_CANDIDATE_FILE = (
    PROJECT_ROOT
    / "config"
    / "district_master_final_candidate.csv"
)


# ============================================================
# BASIC HELPERS
# ============================================================

def normalize_code(value, width):
    """
    Convert a numeric ID into a zero-padded string.

    Examples:
        7    -> 07
        1    -> 01
        701  -> 0701
    """

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    if not value:
        return ""

    return value.zfill(width)


def clean_text(value):
    """
    Clean Markdown / HTML formatting while preserving
    district-name spelling.
    """

    if value is None:
        return ""

    value = str(value)

    value = re.sub(
        r"<[^>]+>",
        "",
        value
    )

    value = (
        value
        .replace("**", "")
        .replace("__", "")
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip(" .")


def normalize_name(value):
    """
    Normalize district names only for comparison.

    Original spelling is retained in final output.
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
    Split Markdown <br> elements.

    Example:

        South West<br>(08)

    becomes:

        ["South West", "(08)"]
    """

    if value is None:
        return []

    parts = re.split(
        r"(?i)<br\s*/?>",
        str(value)
    )

    result = []

    for part in parts:

        cleaned = clean_text(
            part
        )

        if cleaned:
            result.append(
                cleaned
            )

    return result


# ============================================================
# PDF VALIDATION
# ============================================================

def validate_pdf():

    print("\n" + "=" * 78)
    print("VALIDATING NSS 77TH ROUND PDF")
    print("=" * 78)

    if not PDF_FILE.exists():

        raise FileNotFoundError(
            f"\nPDF not found:\n{PDF_FILE}"
        )

    document = pymupdf.open(
        PDF_FILE
    )

    page_count = document.page_count

    print(
        f"\nPDF pages: {page_count}"
    )

    first_pages = "\n".join(
        document[index].get_text(
            "text"
        )
        for index in range(
            min(
                15,
                page_count
            )
        )
    )

    document.close()

    normalized = re.sub(
        r"\s+",
        " ",
        first_pages
    ).casefold()

    nss77 = bool(
        re.search(
            r"\bnss\s*77(?:th)?\s*round\b",
            normalized,
            flags=re.IGNORECASE
        )
    )

    debt = (
        "debt and investment"
        in normalized
    )

    field_staff = (
        "instructions to field staff"
        in normalized
    )

    print(
        f"NSS 77th Round           : "
        f"{nss77}"
    )

    print(
        f"Debt and Investment      : "
        f"{debt}"
    )

    print(
        f"Instructions Field Staff : "
        f"{field_staff}"
    )

    if not all(
        [
            nss77,
            debt,
            field_staff
        ]
    ):

        raise ValueError(
            "\nPDF identity validation failed."
        )

    if page_count < APPENDIX_END_PAGE:

        raise ValueError(
            "\nPDF does not contain the required "
            "appendix pages."
        )

    print(
        "\nPDF IDENTITY: PASS"
    )


# ============================================================
# MARKDOWN GENERATION
# ============================================================

def generate_markdown():

    print("\n" + "=" * 78)
    print("EXTRACTING NSS 77 APPENDIX")
    print("=" * 78)

    print(
        f"\nProcessing PDF pages "
        f"{APPENDIX_START_PAGE}-"
        f"{APPENDIX_END_PAGE}"
    )

    markdown = (
        pymupdf4llm.to_markdown(
            str(PDF_FILE),
            pages=APPENDIX_PAGE_INDEXES,
            show_progress=True,
            page_separators=True
        )
    )

    MARKDOWN_FILE.write_text(
        markdown,
        encoding="utf-8"
    )

    print(
        "\nMarkdown saved:"
    )

    print(
        MARKDOWN_FILE
    )

    return markdown


# ============================================================
# APPENDIX-II ISOLATION
# ============================================================

def isolate_appendix_ii(markdown):

    pattern = re.compile(
        r"list\s+of\s+nss\s+regions\s+"
        r"and\s+their\s+composition",
        flags=re.IGNORECASE
    )

    match = pattern.search(
        markdown
    )

    if not match:

        raise ValueError(
            "\nCould not locate Appendix-II "
            "'LIST OF NSS REGIONS AND THEIR COMPOSITION'."
        )

    print(
        "\nAppendix-II heading found."
    )

    return markdown[
        match.start():
    ]


# ============================================================
# SERIAL NUMBER PARSER
# ============================================================

def parse_serial_numbers(value):

    serials = []

    for token in split_br(
        value
    ):

        matches = re.findall(
            r"(?<!\d)(\d+)\.?",
            token
        )

        for match in matches:

            serials.append(
                int(match)
            )

    return serials


# ============================================================
# 7-COLUMN PARSER
# ============================================================

def parse_separate_name_code(
    name_cell,
    code_cell
):

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

        matches = re.findall(
            r"\((\d{1,2})\)",
            token
        )

        if matches:

            for match in matches:

                codes.append(
                    match.zfill(2)
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
# 6-COLUMN PARSER
# ============================================================

def parse_combined_name_code(value):

    pairs = []

    pending_name = []

    for token in split_br(
        value
    ):

        # Code-only token such as:
        #
        # (08)
        code_only = re.fullmatch(
            r"\((\d{1,2})\)",
            token
        )

        if code_only:

            name = clean_text(
                " ".join(
                    pending_name
                )
            )

            if name:

                pairs.append(
                    (
                        name,
                        code_only
                        .group(1)
                        .zfill(2)
                    )
                )

            pending_name = []

            continue

        # Combined form:
        #
        # South West (08)
        combined = re.match(
            r"^(.*?)\s*\((\d{1,2})\)\s*$",
            token
        )

        if (
            combined
            and
            combined.group(1).strip()
        ):

            pending_name.append(
                combined
                .group(1)
                .strip()
            )

            name = clean_text(
                " ".join(
                    pending_name
                )
            )

            pairs.append(
                (
                    name,
                    combined
                    .group(2)
                    .zfill(2)
                )
            )

            pending_name = []

            continue

        pending_name.append(
            token
        )

    return pairs


# ============================================================
# HEADER DETECTION
# ============================================================

def is_header_line(line):

    lower = line.casefold()

    if "state/u.t" in lower:
        return True

    if "state/ut" in lower:
        return True

    if "name of district" in lower:
        return True

    if "detailed composition" in lower:
        return True

    if re.match(
        r"^\|\s*:?-+",
        line
    ):
        return True

    header_count = sum(
        f"({number})" in line
        for number in range(
            1,
            8
        )
    )

    if header_count >= 5:
        return True

    return False


# ============================================================
# NORMAL MARKDOWN PARSER
# ============================================================

def parse_markdown_districts(markdown):

    print("\n" + "=" * 78)
    print("PARSING NSS 77 DISTRICT TABLE")
    print("=" * 78)

    current_state = ""

    current_region = ""

    records = []

    issues = []

    table_lines = 0

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

        # Preserve blank columns.
        cells = line.split("|")[1:-1]

        if len(cells) < 6:
            continue

        table_lines += 1

        # ----------------------------------------------------
        # NSS region code is the state anchor.
        #
        # 071 -> Delhi       -> State_ID 07
        # 271 -> Maharashtra -> State_ID 27
        # ----------------------------------------------------

        region_cell = clean_text(
            cells[2]
        )

        region_match = re.search(
            r"(?<!\d)(\d{3})(?!\d)",
            region_cell
        )

        if region_match:

            current_region = (
                region_match.group(1)
            )

            current_state = (
                current_region[:2]
            )

        serials = parse_serial_numbers(
            cells[4]
        )

        if not serials:
            continue

        if not current_state:

            issues.append(
                {
                    "Markdown_Line":
                        line_number,

                    "State_ID":
                        "",

                    "NSS_Region_Code":
                        "",

                    "Serial_Numbers":
                        ",".join(
                            map(
                                str,
                                serials
                            )
                        ),

                    "Reason":
                        "STATE_NOT_RESOLVED",

                    "Source_Line":
                        line
                }
            )

            continue

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

        if len(serials) != len(pairs):

            issues.append(
                {
                    "Markdown_Line":
                        line_number,

                    "State_ID":
                        current_state,

                    "NSS_Region_Code":
                        current_region,

                    "Serial_Numbers":
                        ",".join(
                            map(
                                str,
                                serials
                            )
                        ),

                    "Reason":
                        (
                            "COUNT_MISMATCH "
                            f"serials={len(serials)} "
                            f"district_pairs={len(pairs)}"
                        ),

                    "Source_Line":
                        line
                }
            )

            continue

        for serial, pair in zip(
            serials,
            pairs
        ):

            (
                district_name,
                district_code
            ) = pair

            records.append(
                {
                    "Official_Serial_No":
                        serial,

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

                    "Extraction_Method":
                        "MARKDOWN",

                    "Source_Page":
                        ""
                }
            )

    records_df = pd.DataFrame(
        records
    )

    issues_df = pd.DataFrame(
        issues
    )

    print(
        f"\nMarkdown table lines examined : "
        f"{table_lines:,}"
    )

    print(
        f"District records extracted    : "
        f"{len(records_df):,}"
    )

    print(
        f"Markdown parser issues        : "
        f"{len(issues_df):,}"
    )

    return (
        records_df,
        issues_df
    )


# ============================================================
# LOCATE APPENDIX-II IN ORIGINAL PDF
# ============================================================

def find_appendix_ii_pdf_page():

    document = pymupdf.open(
        PDF_FILE
    )

    start_index = None

    for page_index in APPENDIX_PAGE_INDEXES:

        text = (
            document[
                page_index
            ]
            .get_text(
                "text"
            )
        )

        normalized = re.sub(
            r"\s+",
            " ",
            text
        ).casefold()

        if (
            "appendix ii"
            in normalized
            and
            "list of nss regions"
            in normalized
        ):

            start_index = page_index
            break

    document.close()

    if start_index is None:

        raise ValueError(
            "\nCould not locate Appendix-II "
            "in native PDF text."
        )

    print(
        f"\nNative PDF Appendix-II starts "
        f"around PDF page {start_index + 1}."
    )

    return start_index


# ============================================================
# NATIVE PDF FALLBACK
# ============================================================

def extract_serial_from_native_pdf(
    serial_number,
    state_id,
    nss_region,
    appendix_start_index
):
    """
    Recover a district from original PDF text when the
    Markdown table row is damaged.

    Example:

        137.
        South
        (09)

    becomes:

        State_ID       = 07
        District_Code  = 09
        District_Name  = South
    """

    document = pymupdf.open(
        PDF_FILE
    )

    serial_pattern = re.compile(
        rf"^{serial_number}\.\s*(.*)$"
    )

    result = None

    for page_index in range(
        appendix_start_index,
        min(
            APPENDIX_END_PAGE,
            document.page_count
        )
    ):

        page_text = (
            document[
                page_index
            ]
            .get_text(
                "text"
            )
        )

        lines = [
            re.sub(
                r"\s+",
                " ",
                line
            ).strip()
            for line in page_text.splitlines()
            if line.strip()
        ]

        for position, line in enumerate(
            lines
        ):

            serial_match = (
                serial_pattern.match(
                    line
                )
            )

            if not serial_match:
                continue

            # ------------------------------------------------
            # Serial might be on the same line as the
            # district name.
            # ------------------------------------------------

            remainder = (
                serial_match
                .group(1)
                .strip()
            )

            name_parts = []

            if remainder:

                combined = re.match(
                    r"^(.*?)\s*\((\d{1,2})\)\s*$",
                    remainder
                )

                if (
                    combined
                    and
                    combined.group(1).strip()
                ):

                    result = {
                        "Official_Serial_No":
                            serial_number,

                        "State_ID":
                            state_id,

                        "NSS_Region_Code":
                            nss_region,

                        "District_Code":
                            combined
                            .group(2)
                            .zfill(2),

                        "District_ID":
                            (
                                state_id
                                +
                                combined
                                .group(2)
                                .zfill(2)
                            ),

                        "District_Name":
                            clean_text(
                                combined.group(1)
                            ),

                        "Extraction_Method":
                            "NATIVE_PDF_FALLBACK",

                        "Source_Page":
                            page_index + 1
                    }

                    break

                name_parts.append(
                    remainder
                )

            # ------------------------------------------------
            # Search immediately after the serial.
            # ------------------------------------------------

            for next_line in lines[
                position + 1:
                position + 12
            ]:

                # Next district reached.
                if re.fullmatch(
                    r"\d+\.",
                    next_line
                ):

                    break

                # Code-only line:
                #
                # (09)
                code_match = re.fullmatch(
                    r"\((\d{1,2})\)",
                    next_line
                )

                if code_match:

                    district_name = clean_text(
                        " ".join(
                            name_parts
                        )
                    )

                    if district_name:

                        district_code = (
                            code_match
                            .group(1)
                            .zfill(2)
                        )

                        result = {
                            "Official_Serial_No":
                                serial_number,

                            "State_ID":
                                state_id,

                            "NSS_Region_Code":
                                nss_region,

                            "District_Code":
                                district_code,

                            "District_ID":
                                (
                                    state_id
                                    +
                                    district_code
                                ),

                            "District_Name":
                                district_name,

                            "Extraction_Method":
                                "NATIVE_PDF_FALLBACK",

                            "Source_Page":
                                page_index + 1
                        }

                    break

                # Name + code on same line.
                combined = re.match(
                    r"^(.*?)\s*\((\d{1,2})\)\s*$",
                    next_line
                )

                if (
                    combined
                    and
                    combined.group(1).strip()
                ):

                    name_parts.append(
                        combined
                        .group(1)
                        .strip()
                    )

                    district_name = clean_text(
                        " ".join(
                            name_parts
                        )
                    )

                    district_code = (
                        combined
                        .group(2)
                        .zfill(2)
                    )

                    result = {
                        "Official_Serial_No":
                            serial_number,

                        "State_ID":
                            state_id,

                        "NSS_Region_Code":
                            nss_region,

                        "District_Code":
                            district_code,

                        "District_ID":
                            (
                                state_id
                                +
                                district_code
                            ),

                        "District_Name":
                            district_name,

                        "Extraction_Method":
                            "NATIVE_PDF_FALLBACK",

                        "Source_Page":
                            page_index + 1
                    }

                    break

                # Ignore obvious document metadata.
                lower = next_line.casefold()

                ignore_terms = [
                    "instructions to field staff",
                    "appendix ii",
                    "list of nss regions",
                    "state/u.t",
                    "detailed composition",
                    "name of district",
                ]

                if any(
                    term in lower
                    for term in ignore_terms
                ):
                    continue

                if re.fullmatch(
                    r"[A-Z]-\d+",
                    next_line
                ):
                    continue

                if re.fullmatch(
                    r"\d{3}",
                    next_line
                ):
                    continue

                name_parts.append(
                    next_line
                )

            if result is not None:
                break

        if result is not None:
            break

    document.close()

    return result


# ============================================================
# RESOLVE MARKDOWN ISSUES WITH NATIVE PDF
# ============================================================

def resolve_parser_issues(
    records,
    issues
):

    print("\n" + "=" * 78)
    print("RESOLVING MARKDOWN ISSUES FROM ORIGINAL PDF")
    print("=" * 78)

    if issues.empty:

        print(
            "\nNo fallback required."
        )

        empty = pd.DataFrame()

        return (
            records,
            empty,
            empty
        )

    appendix_start_index = (
        find_appendix_ii_pdf_page()
    )

    resolved = []

    unresolved = []

    for _, issue in issues.iterrows():

        serial_text = str(
            issue[
                "Serial_Numbers"
            ]
        )

        serial_numbers = []

        for value in serial_text.split(
            ","
        ):

            value = value.strip()

            if value.isdigit():

                serial_numbers.append(
                    int(value)
                )

        if not serial_numbers:

            unresolved.append(
                issue.to_dict()
            )

            continue

        all_resolved = True

        recovered_for_issue = []

        for serial_number in serial_numbers:

            recovered = (
                extract_serial_from_native_pdf(
                    serial_number=
                        serial_number,

                    state_id=
                        str(
                            issue[
                                "State_ID"
                            ]
                        ).zfill(2),

                    nss_region=
                        str(
                            issue[
                                "NSS_Region_Code"
                            ]
                        ),

                    appendix_start_index=
                        appendix_start_index
                )
            )

            if recovered is None:

                all_resolved = False

                break

            recovered_for_issue.append(
                recovered
            )

        if all_resolved:

            resolved.extend(
                recovered_for_issue
            )

        else:

            unresolved.append(
                issue.to_dict()
            )

    resolved_df = pd.DataFrame(
        resolved
    )

    unresolved_df = pd.DataFrame(
        unresolved
    )

    if not resolved_df.empty:

        print(
            "\nRecovered from native PDF:"
        )

        print(
            resolved_df[
                [
                    "Official_Serial_No",
                    "State_ID",
                    "District_Code",
                    "District_Name",
                    "Source_Page"
                ]
            ]
            .to_string(
                index=False
            )
        )

        records = pd.concat(
            [
                records,
                resolved_df
            ],
            ignore_index=True
        )

    print(
        f"\nFallback records recovered : "
        f"{len(resolved_df)}"
    )

    print(
        f"Unresolved parser issues   : "
        f"{len(unresolved_df)}"
    )

    return (
        records,
        resolved_df,
        unresolved_df
    )


# ============================================================
# VALIDATE OFFICIAL EXTRACTION
# ============================================================

def validate_official_records(
    records,
    unresolved
):

    print("\n" + "=" * 78)
    print("VALIDATING OFFICIAL NSS 77 DISTRICT RECORDS")
    print("=" * 78)

    if not unresolved.empty:

        unresolved.to_csv(
            PARSER_ISSUES_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        raise ValueError(
            "\nUnresolved parser issues remain."
            "\nNo District Master has been modified."
        )

    if records.empty:

        raise ValueError(
            "\nNo official districts were extracted."
        )

    records = records.copy()

    records[
        "Official_Serial_No"
    ] = records[
        "Official_Serial_No"
    ].astype(int)

    # Exact duplicate lines can safely be removed.
    records = records.drop_duplicates(
        subset=[
            "Official_Serial_No",
            "State_ID",
            "District_Code",
            "District_Name"
        ]
    ).copy()

    duplicate_serials = records[
        records.duplicated(
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
            "\nDuplicate official serial numbers detected."
        )

    duplicate_district_codes = records[
        records.duplicated(
            subset=[
                "State_ID",
                "District_Code"
            ],
            keep=False
        )
    ]

    if not duplicate_district_codes.empty:

        print(
            "\nDuplicate State_ID + District_Code:"
        )

        print(
            duplicate_district_codes.to_string(
                index=False
            )
        )

        raise ValueError(
            "\nDuplicate official district codes detected."
        )

    serials = sorted(
        records[
            "Official_Serial_No"
        ]
        .unique()
        .tolist()
    )

    minimum_serial = min(
        serials
    )

    maximum_serial = max(
        serials
    )

    expected_serials = set(
        range(
            minimum_serial,
            maximum_serial + 1
        )
    )

    actual_serials = set(
        serials
    )

    missing_serials = sorted(
        expected_serials
        -
        actual_serials
    )

    print(
        f"\nOfficial records       : "
        f"{len(records):,}"
    )

    print(
        f"Minimum serial         : "
        f"{minimum_serial}"
    )

    print(
        f"Maximum serial         : "
        f"{maximum_serial}"
    )

    print(
        f"Missing serial numbers : "
        f"{len(missing_serials)}"
    )

    if minimum_serial != 1:

        raise ValueError(
            "\nOfficial serial sequence "
            "does not begin at 1."
        )

    if missing_serials:

        print(
            "\nMissing serials:"
        )

        print(
            missing_serials
        )

        raise ValueError(
            "\nOfficial serial sequence "
            "contains gaps."
        )

    if len(records) < EXPECTED_AIDIS_DISTRICTS:

        raise ValueError(
            "\nOfficial extraction contains fewer "
            "districts than the AIDIS skeleton."
        )

    print(
        "\nOFFICIAL NSS77 EXTRACTION: PASS"
    )

    return records


# ============================================================
# ADD STATE NAMES
# ============================================================

def add_state_names(records):

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

    records[
        "State_Name"
    ] = records[
        "State_ID"
    ].map(
        state_lookup
    )

    unknown = records[
        records[
            "State_Name"
        ].isna()
    ]

    if not unknown.empty:

        print(
            unknown.to_string(
                index=False
            )
        )

        raise ValueError(
            "\nUnknown State_ID found in "
            "official extraction."
        )

    return records


# ============================================================
# MATCH WITH AIDIS DISTRICT MASTER
# ============================================================

def match_with_aidis(records):

    print("\n" + "=" * 78)
    print("MATCHING NSS77 DISTRICTS WITH AIDIS")
    print("=" * 78)

    master = pd.read_csv(
        DISTRICT_MASTER_FILE,
        dtype=str,
        keep_default_na=False
    )

    master[
        "State_ID"
    ] = master[
        "State_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    master[
        "District_Code"
    ] = master[
        "District_Code"
    ].apply(
        lambda value:
        normalize_code(
            value,
            2
        )
    )

    master[
        "District_ID"
    ] = master[
        "District_ID"
    ].apply(
        lambda value:
        normalize_code(
            value,
            4
        )
    )

    if (
        len(master)
        !=
        EXPECTED_AIDIS_DISTRICTS
    ):

        raise ValueError(
            f"\nExpected "
            f"{EXPECTED_AIDIS_DISTRICTS} "
            f"AIDIS districts but found "
            f"{len(master)}."
        )

    official_lookup = records[
        [
            "State_ID",
            "District_Code",
            "District_Name",
            "Official_Serial_No",
            "NSS_Region_Code",
            "Extraction_Method",
            "Source_Page"
        ]
    ].copy()

    report = master.merge(
        official_lookup,
        on=[
            "State_ID",
            "District_Code"
        ],
        how="left",
        suffixes=(
            "_Existing",
            "_Official"
        )
    )

    report.rename(
        columns={
            "District_Name_Existing":
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

    report[
        "Existing_Name_Matches_Official"
    ] = False

    existing_mask = (
        matched_mask
        &
        report[
            "Existing_District_Name"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    )

    for index in report[
        existing_mask
    ].index:

        existing_name = report.at[
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
                existing_name
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

    # Official districts that do not occur in our AIDIS
    # national output.
    official_extra = records.merge(
        master[
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
        f"{len(records):,}"
    )

    print(
        f"AIDIS district codes      : "
        f"{len(master):,}"
    )

    print(
        f"AIDIS codes matched       : "
        f"{matched_count:,}"
    )

    print(
        f"AIDIS codes unmatched     : "
        f"{len(unmatched):,}"
    )

    print(
        f"Official not used by AIDIS: "
        f"{len(official_extra):,}"
    )

    return (
        master,
        report,
        unmatched,
        official_extra,
        matched_count
    )


# ============================================================
# MAHARASHTRA CONTROL
# ============================================================

def validate_maharashtra(report):

    print("\n" + "=" * 78)
    print("MAHARASHTRA CONTROL CHECK")
    print("=" * 78)

    mh = report[
        report[
            "State_ID"
        ]
        ==
        "27"
    ].copy()

    total = len(
        mh
    )

    code_matches = int(
        (
            mh[
                "Mapping_Status"
            ]
            ==
            "MATCHED_NSS77"
        ).sum()
    )

    name_matches = int(
        mh[
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

    if code_matches != total:

        failed = mh[
            mh[
                "Mapping_Status"
            ]
            !=
            "MATCHED_NSS77"
        ]

        print(
            "\nUnmatched Maharashtra districts:"
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
            "\nMaharashtra code validation failed."
        )

    if name_matches != total:

        failed = mh[
            ~mh[
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
            "\nMaharashtra name validation failed."
        )

    print(
        "\nMAHARASHTRA CONTROL: PASS"
    )


# ============================================================
# CREATE FINAL CANDIDATE
# ============================================================

def create_final_candidate(
    master,
    report
):

    name_lookup = dict(
        zip(
            report[
                "District_ID"
            ],
            report[
                "Official_District_Name"
            ]
        )
    )

    final_master = master.copy()

    final_master[
        "District_Name"
    ] = final_master[
        "District_ID"
    ].map(
        name_lookup
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
        "Matched by State_ID + District_Code "
        "against NSS 77th Round Appendix II"
    )

    # Maharashtra has independent validation from the
    # existing reference.
    mh_mask = (
        final_master[
            "State_ID"
        ]
        ==
        "27"
    )

    final_master.loc[
        mh_mask,
        "Notes"
    ] = (
        "NSS77 mapping matches existing "
        "Maharashtra reference"
    )

    final_master.to_csv(
        FINAL_CANDIDATE_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    return final_master


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS NSS 77 DISTRICT MASTER BUILDER - V3.2")
    print("=" * 78)

    # --------------------------------------------------------
    # Required files
    # --------------------------------------------------------

    for file_path in [
        PDF_FILE,
        STATE_MASTER_FILE,
        DISTRICT_MASTER_FILE
    ]:

        if not file_path.exists():

            raise FileNotFoundError(
                f"\nRequired file not found:\n"
                f"{file_path}"
            )

    # --------------------------------------------------------
    # 1. Validate official source
    # --------------------------------------------------------

    validate_pdf()

    # --------------------------------------------------------
    # 2. Extract appendix pages
    # --------------------------------------------------------

    markdown = generate_markdown()

    # --------------------------------------------------------
    # 3. Isolate Appendix-II
    # --------------------------------------------------------

    appendix = isolate_appendix_ii(
        markdown
    )

    # --------------------------------------------------------
    # 4. Parse Markdown
    # --------------------------------------------------------

    (
        records,
        issues
    ) = parse_markdown_districts(
        appendix
    )

    # Save original parser issues for audit.
    if not issues.empty:

        issues.to_csv(
            PARSER_ISSUES_FILE,
            index=False,
            encoding="utf-8-sig"
        )

    # --------------------------------------------------------
    # 5. Recover damaged rows from native PDF
    # --------------------------------------------------------

    (
        records,
        fallback_records,
        unresolved
    ) = resolve_parser_issues(
        records,
        issues
    )

    if not fallback_records.empty:

        fallback_records.to_csv(
            FALLBACK_REPORT_FILE,
            index=False,
            encoding="utf-8-sig"
        )

    # --------------------------------------------------------
    # 6. Validate official data
    # --------------------------------------------------------

    records = validate_official_records(
        records,
        unresolved
    )

    # --------------------------------------------------------
    # 7. Add State_Name
    # --------------------------------------------------------

    records = add_state_names(
        records
    )

    records = records.sort_values(
        by=[
            "Official_Serial_No"
        ]
    ).reset_index(
        drop=True
    )

    records.to_csv(
        OFFICIAL_LOOKUP_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 8. Match against AIDIS 682-code skeleton
    # --------------------------------------------------------

    (
        master,
        report,
        unmatched,
        official_extra,
        matched_count
    ) = match_with_aidis(
        records
    )

    # --------------------------------------------------------
    # 9. Maharashtra independent validation
    # --------------------------------------------------------

    validate_maharashtra(
        report
    )

    # --------------------------------------------------------
    # 10. Final AIDIS gate
    # --------------------------------------------------------

    if (
        matched_count
        !=
        EXPECTED_AIDIS_DISTRICTS
    ):

        print("\n" + "=" * 78)
        print("UNMATCHED AIDIS DISTRICTS")
        print("=" * 78)

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
            "\n\nNo final District Master "
            "has been promoted."
        )

    # --------------------------------------------------------
    # 11. Create final candidate
    # --------------------------------------------------------

    final_master = create_final_candidate(
        master,
        report
    )

    # --------------------------------------------------------
    # 12. Final summary
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("FINAL DISTRICT MASTER SUMMARY")
    print("=" * 78)

    print(
        f"\nOfficial NSS77 districts : "
        f"{len(records):,}"
    )

    print(
        f"AIDIS districts           : "
        f"{len(master):,}"
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
        f"Official extras           : "
        f"{len(official_extra):,}"
    )

    print(
        f"Fallback records used     : "
        f"{len(fallback_records):,}"
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
        "\nIMPORTANT:"
        "\nconfig\\district_master.csv "
        "has NOT been overwritten."
    )

    print("\nReports:")

    print(
        OFFICIAL_LOOKUP_FILE
    )

    print(
        VALIDATION_FILE
    )

    print(
        UNMAPPED_FILE
    )

    print(
        EXTRA_OFFICIAL_FILE
    )

    print(
        FALLBACK_REPORT_FILE
    )

    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()