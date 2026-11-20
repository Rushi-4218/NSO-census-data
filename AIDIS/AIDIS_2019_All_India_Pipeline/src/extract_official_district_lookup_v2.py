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

RAW_MARKDOWN_FILE = (
    REPORT_DIR
    / "nss_layout_extraction_v2.md"
)

OFFICIAL_LOOKUP_FILE = (
    REPORT_DIR
    / "official_district_lookup_v2.csv"
)

MATCH_REPORT_FILE = (
    REPORT_DIR
    / "district_mapping_report_v2.csv"
)

UNMAPPED_FILE = (
    REPORT_DIR
    / "unmapped_districts_v2.csv"
)

CONFLICT_FILE = (
    REPORT_DIR
    / "district_mapping_conflicts_v2.csv"
)

MAHARASHTRA_CHECK_FILE = (
    REPORT_DIR
    / "maharashtra_pdf_control_v2.csv"
)


# ============================================================
# BASIC HELPERS
# ============================================================

def normalize_code(value, width):
    """
    Convert codes into zero-padded strings.

    Examples
    --------
    1       -> 01
    27      -> 27

    101     -> 0101
    2701    -> 2701
    """

    if pd.isna(value):
        return None

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    if value == "":
        return None

    return value.zfill(width)


def clean_text(value):
    """
    Clean text obtained from Markdown/PDF extraction.
    """

    if value is None:
        return ""

    value = str(value)

    # Markdown / HTML line breaks
    value = value.replace("<br>", " ")
    value = value.replace("<br/>", " ")
    value = value.replace("<br />", " ")

    # Markdown formatting characters
    value = value.replace("**", "")
    value = value.replace("__", "")

    value = value.replace("\\", "")

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def normalize_name(value):
    """
    Normalize district names for comparison.

    Example:
        'Mumbai Suburban'
        'Mumbai  Suburban'

    become equivalent.
    """

    value = clean_text(value).casefold()

    value = re.sub(
        r"[^a-z0-9]+",
        "",
        value
    )

    return value


# ============================================================
# MARKDOWN TABLE HELPERS
# ============================================================

def split_markdown_row(line):
    """
    Convert Markdown table row into cells.

    Example:

    | 1 | Maharashtra (27) | 271 | ... | Nandurbar | 01 |

    becomes a Python list of cell values.
    """

    line = line.strip()

    if "|" not in line:
        return []

    # Remove beginning/end pipe.
    line = line.strip("|")

    cells = [
        clean_text(cell)
        for cell in line.split("|")
    ]

    return cells


def is_markdown_separator(cells):
    """
    Detect rows such as:

        | --- | --- | --- |
    """

    if not cells:
        return False

    checked = 0

    for cell in cells:

        value = cell.replace(":", "").strip()

        if value == "":
            continue

        checked += 1

        if not re.fullmatch(
            r"-+",
            value
        ):
            return False

    return checked > 0


def extract_parenthesized_codes(value):
    """
    Extract numbers contained in parentheses.

    Examples:

        Maharashtra (27)
            -> ['27']

        (01)
            -> ['01']
    """

    value = clean_text(value)

    return re.findall(
        r"\((\d{1,2})\)",
        value
    )


def extract_state_code(cells, valid_state_ids):
    """
    Search the State/U.T. portion of a table row for
    a valid NSS State_ID.

    We intentionally look for a parenthesized code so
    that district serial numbers are not accidentally
    interpreted as State_IDs.
    """

    # State information should occur near the left side.
    # Scan at most first four cells.
    for cell in cells[:4]:

        codes = extract_parenthesized_codes(
            cell
        )

        for code in codes:

            code = code.zfill(2)

            if code in valid_state_ids:
                return code

    return None


def extract_district_code(value):
    """
    Extract local district code.

    Supported examples:

        (01)
        01
        1
    """

    value = clean_text(value)

    if value == "":
        return None

    # Preferred format: (01)
    codes = extract_parenthesized_codes(
        value
    )

    if len(codes) == 1:

        return codes[0].zfill(2)

    # Plain numeric fallback.
    match = re.fullmatch(
        r"0*(\d{1,2})",
        value
    )

    if match:

        number = int(
            match.group(1)
        )

        if 1 <= number <= 99:
            return str(number).zfill(2)

    return None


def is_header_row(cells):
    """
    Detect obvious table header rows.
    """

    combined = " ".join(
        clean_text(cell).casefold()
        for cell in cells
    )

    header_phrases = [
        "state/u.t",
        "state/u.t. (code)",
        "name of district",
        "detailed composition",
        "nss region",
        "sl. no",
    ]

    matches = sum(
        phrase in combined
        for phrase in header_phrases
    )

    return matches >= 2


# ============================================================
# DISTRICT NAME EXTRACTION
# ============================================================

def determine_district_name_and_code(cells):
    """
    Identify district name and district code from a Markdown
    table row.

    The official Appendix normally ends with:

        district serial number
        district name
        district code

    Therefore the last meaningful cell should contain the
    district code and the previous cell the district name.

    We still search backwards instead of assuming exactly
    seven columns because Markdown/layout extraction may
    introduce extra cells.
    """

    if len(cells) < 2:
        return None, None

    # Search backwards for a cell that looks like district code.
    for index in range(
        len(cells) - 1,
        0,
        -1
    ):

        district_code = extract_district_code(
            cells[index]
        )

        if district_code is None:
            continue

        # Search immediately to the left for the first
        # meaningful text cell.
        for name_index in range(
            index - 1,
            -1,
            -1
        ):

            candidate_name = clean_text(
                cells[name_index]
            )

            if candidate_name == "":
                continue

            # A district name should not just be a number.
            if re.fullmatch(
                r"\d+\.?",
                candidate_name
            ):
                continue

            # Reject obvious header values.
            lower_name = candidate_name.casefold()

            if lower_name in {
                "code",
                "name of district",
                "district",
                "sl. no.",
                "sl. no",
            }:
                continue

            return (
                candidate_name,
                district_code
            )

    return None, None


# ============================================================
# EXTRACT MARKDOWN USING LAYOUT ANALYSIS
# ============================================================

def extract_layout_markdown(pdf_file):
    """
    Use PyMuPDF4LLM layout analysis.

    Returns:
        page chunks produced by to_markdown()
    """

    print("\nRunning layout-aware PDF extraction...")

    document = pymupdf.open(
        pdf_file
    )

    print(
        f"PDF pages: "
        f"{document.page_count}"
    )

    chunks = pymupdf4llm.to_markdown(
        document,
        page_chunks=True,
        show_progress=True
    )

    document.close()

    return chunks


# ============================================================
# PARSE MARKDOWN
# ============================================================

def parse_markdown_candidates(
    chunks,
    valid_state_ids,
    state_name_lookup
):

    candidates = []

    markdown_debug = []

    current_state = None

    markdown_table_rows = 0

    for chunk_index, chunk in enumerate(
        chunks,
        start=1
    ):

        metadata = chunk.get(
            "metadata",
            {}
        )

        page_number = metadata.get(
            "page_number",
            chunk_index
        )

        page_text = chunk.get(
            "text",
            ""
        )

        markdown_debug.append(
            "\n\n"
            + "=" * 100
            + f"\nPAGE {page_number}\n"
            + "=" * 100
            + "\n\n"
        )

        markdown_debug.append(
            page_text
        )

        markdown_debug.append(
            "\n"
        )

        # ----------------------------------------------------
        # Prefer areas classified as tables.
        # ----------------------------------------------------

        page_boxes = chunk.get(
            "page_boxes",
            []
        )

        table_segments = []

        for box in page_boxes:

            if box.get("class") != "table":
                continue

            position = box.get(
                "pos"
            )

            if (
                not position
                or len(position) != 2
            ):
                continue

            start, stop = position

            table_segments.append(
                page_text[
                    start:stop
                ]
            )

        # ----------------------------------------------------
        # If layout model did not expose explicit table boxes,
        # process the complete page text as fallback.
        # ----------------------------------------------------

        if not table_segments:

            table_segments = [
                page_text
            ]

        # ----------------------------------------------------
        # Process Markdown table lines.
        # ----------------------------------------------------

        for table_number, table_text in enumerate(
            table_segments,
            start=1
        ):

            lines = table_text.splitlines()

            for line_number, line in enumerate(
                lines,
                start=1
            ):

                if "|" not in line:
                    continue

                cells = split_markdown_row(
                    line
                )

                if len(cells) < 3:
                    continue

                if is_markdown_separator(
                    cells
                ):
                    continue

                if is_header_row(
                    cells
                ):
                    continue

                markdown_table_rows += 1

                # --------------------------------------------
                # Update current State_ID when state cell
                # appears.
                # --------------------------------------------

                detected_state = (
                    extract_state_code(
                        cells,
                        valid_state_ids
                    )
                )

                if detected_state:

                    current_state = (
                        detected_state
                    )

                if current_state is None:
                    continue

                # --------------------------------------------
                # Extract district name and code.
                # --------------------------------------------

                (
                    district_name,
                    district_code
                ) = determine_district_name_and_code(
                    cells
                )

                if (
                    district_name is None
                    or district_code is None
                ):
                    continue

                # --------------------------------------------
                # Avoid common document header/footer values.
                # --------------------------------------------

                lower_name = (
                    district_name
                    .casefold()
                )

                if any(
                    term in lower_name
                    for term in [
                        "instructions to field staff",
                        "appendix",
                        "list of nss regions",
                        "detailed composition",
                        "name of district",
                    ]
                ):
                    continue

                district_id = (
                    current_state
                    +
                    district_code
                )

                candidates.append(
                    {
                        "State_ID":
                            current_state,

                        "State_Name":
                            state_name_lookup.get(
                                current_state,
                                ""
                            ),

                        "District_Code":
                            district_code,

                        "District_ID":
                            district_id,

                        "District_Name":
                            district_name,

                        "PDF_Page":
                            page_number,

                        "Table_Number":
                            table_number,

                        "Line_Number":
                            line_number,

                        "Source_Line":
                            clean_text(
                                line
                            )
                    }
                )

    RAW_MARKDOWN_FILE.write_text(
        "".join(markdown_debug),
        encoding="utf-8"
    )

    print(
        f"\nMarkdown table rows examined: "
        f"{markdown_table_rows:,}"
    )

    return pd.DataFrame(
        candidates
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print("AIDIS OFFICIAL DISTRICT LOOKUP EXTRACTOR - V2")
    print("=" * 78)

    # --------------------------------------------------------
    # 1. Validate required files
    # --------------------------------------------------------

    required_files = [
        PDF_FILE,
        STATE_MASTER_FILE,
        DISTRICT_MASTER_FILE,
    ]

    for file_path in required_files:

        if not file_path.exists():

            raise FileNotFoundError(
                "\nRequired file not found:\n"
                f"{file_path}"
            )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("\nRequired files found.")

    # --------------------------------------------------------
    # 2. State master
    # --------------------------------------------------------

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

    valid_state_ids = set(
        state_master[
            "State_ID"
        ]
        .dropna()
        .tolist()
    )

    state_name_lookup = dict(
        zip(
            state_master[
                "State_ID"
            ],
            state_master[
                "State_Name"
            ]
        )
    )

    print(
        f"State/UT codes loaded: "
        f"{len(valid_state_ids)}"
    )

    # --------------------------------------------------------
    # 3. AIDIS district master
    # --------------------------------------------------------

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

    print(
        f"AIDIS districts loaded: "
        f"{len(district_master):,}"
    )

    # --------------------------------------------------------
    # 4. Layout extraction
    # --------------------------------------------------------

    chunks = extract_layout_markdown(
        PDF_FILE
    )

    print(
        f"\nPage chunks returned: "
        f"{len(chunks)}"
    )

    # --------------------------------------------------------
    # 5. Parse candidate districts
    # --------------------------------------------------------

    candidates = (
        parse_markdown_candidates(
            chunks,
            valid_state_ids,
            state_name_lookup
        )
    )

    if candidates.empty:

        raise RuntimeError(
            "\nV2 extraction returned no district candidates.\n"
            f"Inspect:\n{RAW_MARKDOWN_FILE}"
        )

    print(
        f"Raw district candidates: "
        f"{len(candidates):,}"
    )

    # --------------------------------------------------------
    # 6. Clean candidate names
    # --------------------------------------------------------

    candidates[
        "District_Name"
    ] = candidates[
        "District_Name"
    ].apply(
        clean_text
    )

    candidates = candidates[
        candidates[
            "District_Name"
        ]
        != ""
    ].copy()

    # --------------------------------------------------------
    # 7. Remove exact duplicate extractions
    # --------------------------------------------------------

    exact_unique = (
        candidates
        .drop_duplicates(
            subset=[
                "State_ID",
                "District_Code",
                "District_Name"
            ]
        )
        .copy()
    )

    # --------------------------------------------------------
    # 8. Detect conflicts
    #
    # Same state + local district code must not have
    # multiple different names.
    # --------------------------------------------------------

    name_counts = (
        exact_unique
        .groupby(
            [
                "State_ID",
                "District_Code"
            ]
        )[
            "District_Name"
        ]
        .nunique()
        .reset_index(
            name="Distinct_Name_Count"
        )
    )

    conflict_keys = (
        name_counts[
            name_counts[
                "Distinct_Name_Count"
            ]
            > 1
        ][
            [
                "State_ID",
                "District_Code"
            ]
        ]
    )

    if conflict_keys.empty:

        conflicts = pd.DataFrame(
            columns=exact_unique.columns
        )

    else:

        conflicts = (
            exact_unique
            .merge(
                conflict_keys,
                on=[
                    "State_ID",
                    "District_Code"
                ],
                how="inner"
            )
        )

    conflicts.to_csv(
        CONFLICT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 9. Keep only safe one-name mappings
    # --------------------------------------------------------

    safe_keys = (
        name_counts[
            name_counts[
                "Distinct_Name_Count"
            ]
            == 1
        ][
            [
                "State_ID",
                "District_Code"
            ]
        ]
    )

    safe_mapping = (
        exact_unique
        .merge(
            safe_keys,
            on=[
                "State_ID",
                "District_Code"
            ],
            how="inner"
        )
        .drop_duplicates(
            subset=[
                "State_ID",
                "District_Code"
            ]
        )
        .copy()
    )

    safe_mapping = safe_mapping[
        [
            "State_ID",
            "State_Name",
            "District_Code",
            "District_ID",
            "District_Name",
            "PDF_Page",
            "Table_Number",
            "Line_Number"
        ]
    ]

    safe_mapping.to_csv(
        OFFICIAL_LOOKUP_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 10. Compare against AIDIS district master
    # --------------------------------------------------------

    report = district_master.merge(
        safe_mapping[
            [
                "State_ID",
                "District_Code",
                "District_Name",
                "PDF_Page"
            ]
        ],
        on=[
            "State_ID",
            "District_Code"
        ],
        how="left",
        suffixes=(
            "_Current",
            "_PDF"
        )
    )

    report.rename(
        columns={
            "District_Name_Current":
                "Existing_District_Name",

            "District_Name_PDF":
                "PDF_District_Name"
        },
        inplace=True
    )

    report[
        "Mapping_Status"
    ] = "UNMATCHED"

    matched_mask = (
        report[
            "PDF_District_Name"
        ]
        .notna()
        &
        (
            report[
                "PDF_District_Name"
            ]
            .astype(str)
            .str.strip()
            != ""
        )
    )

    report.loc[
        matched_mask,
        "Mapping_Status"
    ] = "CODE_MATCHED"

    report.to_csv(
        MATCH_REPORT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 11. Unmatched list
    # --------------------------------------------------------

    unmatched = report[
        report[
            "Mapping_Status"
        ]
        ==
        "UNMATCHED"
    ].copy()

    unmatched.to_csv(
        UNMAPPED_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 12. Maharashtra control validation
    # --------------------------------------------------------

    maharashtra = report[
        report[
            "State_ID"
        ]
        ==
        "27"
    ].copy()

    maharashtra[
        "Existing_Normalized"
    ] = maharashtra[
        "Existing_District_Name"
    ].apply(
        normalize_name
    )

    maharashtra[
        "PDF_Normalized"
    ] = maharashtra[
        "PDF_District_Name"
    ].apply(
        normalize_name
    )

    maharashtra[
        "Name_Match"
    ] = (
        (
            maharashtra[
                "Existing_Normalized"
            ]
            != ""
        )
        &
        (
            maharashtra[
                "PDF_Normalized"
            ]
            != ""
        )
        &
        (
            maharashtra[
                "Existing_Normalized"
            ]
            ==
            maharashtra[
                "PDF_Normalized"
            ]
        )
    )

    maharashtra.to_csv(
        MAHARASHTRA_CHECK_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    mh_total = len(
        maharashtra
    )

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
    # 13. Print mismatches if Maharashtra does not match
    # --------------------------------------------------------

    mh_mismatch = maharashtra[
        ~maharashtra[
            "Name_Match"
        ]
    ]

    # --------------------------------------------------------
    # 14. Summary
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("V2 OFFICIAL DISTRICT EXTRACTION SUMMARY")
    print("=" * 78)

    print(
        f"\nRaw extracted candidates      : "
        f"{len(candidates):,}"
    )

    print(
        f"Unique code/name combinations : "
        f"{len(exact_unique):,}"
    )

    print(
        f"Safe one-name mappings        : "
        f"{len(safe_mapping):,}"
    )

    print(
        f"Conflicting candidate records : "
        f"{len(conflicts):,}"
    )

    print(
        f"AIDIS district codes          : "
        f"{len(district_master):,}"
    )

    print(
        f"AIDIS district codes matched  : "
        f"{int(matched_mask.sum()):,}"
    )

    print(
        f"AIDIS districts unmatched     : "
        f"{len(unmatched):,}"
    )

    print("\n" + "-" * 78)
    print("MAHARASHTRA CONTROL CHECK")
    print("-" * 78)

    print(
        f"Maharashtra districts         : "
        f"{mh_total}"
    )

    print(
        f"Maharashtra codes matched     : "
        f"{mh_code_matched}"
    )

    print(
        f"Maharashtra names matched     : "
        f"{mh_name_matched}"
    )

    if (
        mh_code_matched == mh_total
        and
        mh_name_matched == mh_total
    ):

        print(
            "\nMAHARASHTRA V2 CONTROL: PASS"
        )

    else:

        print(
            "\nMAHARASHTRA V2 CONTROL: REVIEW REQUIRED"
        )

        print(
            "\nMaharashtra differences:\n"
        )

        print(
            mh_mismatch[
                [
                    "District_ID",
                    "Existing_District_Name",
                    "PDF_District_Name",
                    "Mapping_Status"
                ]
            ]
            .to_string(
                index=False
            )
        )

    print("\n" + "-" * 78)
    print("OUTPUT FILES")
    print("-" * 78)

    print(
        f"\nRaw layout Markdown:\n"
        f"{RAW_MARKDOWN_FILE}"
    )

    print(
        f"\nSafe official lookup:\n"
        f"{OFFICIAL_LOOKUP_FILE}"
    )

    print(
        f"\nFull mapping report:\n"
        f"{MATCH_REPORT_FILE}"
    )

    print(
        f"\nUnmatched districts:\n"
        f"{UNMAPPED_FILE}"
    )

    print(
        f"\nConflict report:\n"
        f"{CONFLICT_FILE}"
    )

    print(
        f"\nMaharashtra control:\n"
        f"{MAHARASHTRA_CHECK_FILE}"
    )

    print(
        "\nIMPORTANT:"
        "\ndistrict_master.csv has NOT been modified."
    )

    print("\n" + "=" * 78)
    print("V2 EXTRACTION COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()