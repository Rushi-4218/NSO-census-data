from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


# =============================================================================
# AIDIS 2013 - STEP 01B
# EXACT RAW HEADER <-> NADA METADATA VARIABLE MAPPING
#
# PURPOSE
# -------
# 1. Consume ONLY files locked by Step 01.
# 2. Read headers from every production raw dataset.
# 3. Match each raw dataset to the correct NADA metadata data-file group
#    using variable overlap, NOT filenames.
# 4. Match every raw variable to its exact NADA variable record.
# 5. Preserve the known Visit-1 Block-16 / Block-16_value metadata gap.
# 6. Produce a canonical variable catalog for later pipeline steps.
#
# IMPORTANT
# ---------
# This step DOES NOT decide KPI methodology.
# It only locks:
#
#     raw file
#       -> metadata data file
#       -> raw variable
#       -> NADA variable
#       -> label / source URL
#
# Methodology/formulas are locked later.
# =============================================================================


PROJECT_ROOT = Path(
    r"D:\AIDIS\AIDIS_2013_All_India_Pipeline"
)

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
# STEP 01 INPUTS
# =============================================================================

STEP01_MANIFEST = (
    CACHE_DIR
    / "step01_production_manifest.csv"
)

STEP01_RAW_INVENTORY = (
    CACHE_DIR
    / "step01_raw_inventory.csv"
)


# =============================================================================
# STEP 01B OUTPUTS
# =============================================================================

DATASET_MAP_FILE = (
    CACHE_DIR
    / "step01b_dataset_mapping.csv"
)

VARIABLE_MAP_FILE = (
    CACHE_DIR
    / "step01b_variable_mapping.csv"
)

METADATA_COVERAGE_FILE = (
    CACHE_DIR
    / "step01b_metadata_group_coverage.csv"
)

SEMANTIC_CANDIDATES_FILE = (
    CACHE_DIR
    / "step01b_semantic_candidates.csv"
)

CANONICAL_CATALOG_FILE = (
    CONFIG_DIR
    / "aidis_2013_variable_catalog.csv"
)

SUMMARY_FILE = (
    REPORT_DIR
    / "step01b_variable_mapping_summary.txt"
)


# =============================================================================
# EXPECTED LOCKED STRUCTURE
# =============================================================================

EXPECTED = {
    "visit1": {
        "raw_files": 18,
        "metadata_records": 519,
        "metadata_data_files": 16,

        # These two production datasets exist in the downloaded package
        # but do not have their own variable pages in the supplied
        # Visit-1 scraped metadata.
        "known_metadata_gap_count": 2,
    },

    "visit2": {
        "raw_files": 6,
        "metadata_records": 211,
        "metadata_data_files": 6,
        "known_metadata_gap_count": 0,
    },
}


errors: list[str] = []
warnings: list[str] = []


# =============================================================================
# NORMALISATION
# =============================================================================

def clean(value) -> str:

    if value is None:
        return ""

    if (
        isinstance(value, float)
        and value.is_integer()
    ):
        return str(
            int(value)
        )

    return str(
        value
    ).strip()


def normalize_name(value) -> str:

    return re.sub(
        r"[^a-z0-9]",
        "",
        clean(value).lower(),
    )


def normalize_file_text(value) -> str:

    text = clean(
        value
    ).lower()

    text = text.replace(
        "&",
        "and",
    )

    return re.sub(
        r"[^a-z0-9]",
        "",
        text,
    )


# =============================================================================
# CSV HELPERS
# =============================================================================

def read_csv(path: Path):

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:

        return list(
            csv.DictReader(
                fh
            )
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

        writer.writerows(
            rows
        )


# =============================================================================
# STEP 01 MANIFEST
# =============================================================================

def load_step01_manifest():

    print(
        "\n[1] Loading Step-01 production lock"
    )

    if not STEP01_MANIFEST.exists():

        raise FileNotFoundError(
            f"Step-01 manifest missing: "
            f"{STEP01_MANIFEST}"
        )

    rows = read_csv(
        STEP01_MANIFEST
    )

    if not rows:

        raise RuntimeError(
            "Step-01 manifest is empty."
        )

    bad_locks = [
        row
        for row in rows
        if clean(
            row.get(
                "lock_status"
            )
        ) != "LOCKED"
    ]

    if bad_locks:

        raise RuntimeError(
            "Step-01 manifest contains "
            "non-LOCKED records. "
            "Do not run Step 01B."
        )

    raw_rows = [
        row
        for row in rows
        if clean(
            row.get(
                "kind"
            )
        ) == "RAW"
    ]

    metadata_json_rows = [
        row
        for row in rows
        if clean(
            row.get(
                "kind"
            )
        ) == "METADATA_JSON"
    ]

    print(
        f"Locked raw files           : "
        f"{len(raw_rows)}"
    )

    print(
        f"Locked metadata JSON files : "
        f"{len(metadata_json_rows)}"
    )

    for visit in [
        "visit1",
        "visit2",
    ]:

        visit_raw = [
            row
            for row in raw_rows
            if clean(
                row.get(
                    "visit"
                )
            ) == visit
        ]

        visit_meta = [
            row
            for row in metadata_json_rows
            if clean(
                row.get(
                    "visit"
                )
            ) == visit
        ]

        expected_raw = (
            EXPECTED[
                visit
            ]["raw_files"]
        )

        if len(
            visit_raw
        ) != expected_raw:

            errors.append(
                f"{visit}: Step-01 manifest "
                f"expected {expected_raw} raw files; "
                f"found {len(visit_raw)}"
            )

        if len(
            visit_meta
        ) != 1:

            errors.append(
                f"{visit}: expected exactly "
                f"one locked metadata JSON; "
                f"found {len(visit_meta)}"
            )

    return (
        raw_rows,
        metadata_json_rows,
    )


# =============================================================================
# RAW INVENTORY SUPPORT
# =============================================================================

def load_raw_inventory():

    if not STEP01_RAW_INVENTORY.exists():

        raise FileNotFoundError(
            f"Step-01 raw inventory missing: "
            f"{STEP01_RAW_INVENTORY}"
        )

    rows = read_csv(
        STEP01_RAW_INVENTORY
    )

    result = {}

    for row in rows:

        key = (
            clean(
                row.get(
                    "visit"
                )
            ),
            clean(
                row.get(
                    "file_name"
                )
            ),
        )

        result[
            key
        ] = row

    return result


# =============================================================================
# RAW HEADER READERS
# =============================================================================

def detect_text_format(
    path: Path
):

    with path.open(
        "rb"
    ) as fh:

        raw = fh.read(
            131072
        )

    encoding = None
    sample = None

    for candidate in [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin1",
    ]:

        try:

            sample = raw.decode(
                candidate
            )

            encoding = (
                candidate
            )

            break

        except UnicodeDecodeError:

            continue

    if encoding is None:

        encoding = "latin1"

        sample = raw.decode(
            "latin1"
        )

    if (
        path.suffix.lower()
        == ".tsv"
    ):

        delimiter = "\t"

    else:

        try:

            delimiter = (
                csv.Sniffer()
                .sniff(
                    sample,
                    delimiters=",\t;|",
                )
                .delimiter
            )

        except Exception:

            delimiter = ","

    return (
        encoding,
        delimiter,
    )


def read_delimited_header(
    path: Path
):

    encoding, delimiter = (
        detect_text_format(
            path
        )
    )

    with path.open(
        "r",
        encoding=encoding,
        errors="replace",
        newline="",
    ) as fh:

        reader = csv.reader(
            fh,
            delimiter=delimiter,
        )

        try:

            header = next(
                reader
            )

        except StopIteration:

            raise RuntimeError(
                "File has no header row."
            )

    header = [
        clean(
            value
        )
        for value in header
    ]

    while (
        header
        and
        header[-1] == ""
    ):

        header.pop()

    return (
        header,
        "",
        1,
    )


def row_has_data(
    values
):

    return any(
        value is not None
        and
        clean(value) != ""
        for value in values
    )


def read_xlsx_header(
    path: Path,
    preferred_sheet="",
    preferred_header_row=0,
):

    try:

        import openpyxl

    except ImportError as exc:

        raise RuntimeError(
            "openpyxl is required. "
            "Install using: pip install openpyxl"
        ) from exc

    workbook = (
        openpyxl.load_workbook(
            path,
            read_only=True,
            data_only=True,
        )
    )

    sheet_names = list(
        workbook.sheetnames
    )

    if (
        preferred_sheet
        and
        preferred_sheet
        in sheet_names
    ):

        sheet_names.remove(
            preferred_sheet
        )

        sheet_names.insert(
            0,
            preferred_sheet,
        )

    # -----------------------------------------------------------------
    # First use the exact header row locked by Step 01, if available.
    # -----------------------------------------------------------------

    if preferred_header_row:

        for sheet_name in sheet_names:

            worksheet = (
                workbook[
                    sheet_name
                ]
            )

            try:
                worksheet.reset_dimensions()
            except Exception:
                pass

            for row_number, values in enumerate(
                worksheet.iter_rows(
                    values_only=True
                ),
                start=1,
            ):

                if (
                    row_number
                    < preferred_header_row
                ):
                    continue

                if (
                    row_number
                    > preferred_header_row
                ):
                    break

                header = [
                    clean(
                        value
                    )
                    for value in values
                ]

                while (
                    header
                    and
                    header[-1] == ""
                ):

                    header.pop()

                normalized = {
                    normalize_name(
                        value
                    )
                    for value in header
                    if clean(
                        value
                    )
                }

                if (
                    len(header) >= 2
                    and
                    "hhid"
                    in normalized
                ):

                    workbook.close()

                    return (
                        header,
                        sheet_name,
                        preferred_header_row,
                    )

    # -----------------------------------------------------------------
    # Fallback: scan first rows for HHID.
    # -----------------------------------------------------------------

    for sheet_name in sheet_names:

        worksheet = (
            workbook[
                sheet_name
            ]
        )

        try:
            worksheet.reset_dimensions()
        except Exception:
            pass

        for row_number, values in enumerate(
            worksheet.iter_rows(
                values_only=True
            ),
            start=1,
        ):

            # There should not be a huge preamble in production NSS
            # files. This prevents scanning millions of data rows
            # if something is malformed.

            if row_number > 100:
                break

            if not row_has_data(
                values
            ):
                continue

            header = [
                clean(
                    value
                )
                for value in values
            ]

            while (
                header
                and
                header[-1] == ""
            ):

                header.pop()

            normalized = {
                normalize_name(
                    value
                )
                for value in header
                if clean(
                    value
                )
            }

            if (
                len(header) >= 2
                and
                "hhid"
                in normalized
            ):

                workbook.close()

                return (
                    header,
                    sheet_name,
                    row_number,
                )

    workbook.close()

    raise RuntimeError(
        "Could not locate XLSX header row containing HHID."
    )


def read_raw_header(
    path: Path,
    inventory_record=None,
):

    suffix = (
        path.suffix.lower()
    )

    if suffix in {
        ".csv",
        ".txt",
        ".tsv",
    }:

        return read_delimited_header(
            path
        )

    if suffix == ".xlsx":

        preferred_sheet = ""
        preferred_header = 0

        if inventory_record:

            preferred_sheet = clean(
                inventory_record.get(
                    "sheet"
                )
            )

            try:

                preferred_header = int(
                    clean(
                        inventory_record.get(
                            "header_row"
                        )
                    )
                    or 0
                )

            except Exception:

                preferred_header = 0

        return read_xlsx_header(
            path,
            preferred_sheet=preferred_sheet,
            preferred_header_row=preferred_header,
        )

    if suffix == ".xls":

        import pandas as pd

        frame = pd.read_excel(
            path,
            nrows=0,
        )

        return (
            [
                clean(
                    column
                )
                for column
                in frame.columns
            ],
            "",
            1,
        )

    raise RuntimeError(
        f"Unsupported raw extension: "
        f"{suffix}"
    )


# =============================================================================
# METADATA PARSING
# =============================================================================

def extract_metadata_data_file(
    record
):

    raw_text = clean(
        record.get(
            "raw_text"
        )
    )

    match = re.search(
        r"Data file:\s*(.*?)\r?\nOverview",
        raw_text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if not match:
        return ""

    return re.sub(
        r"\s+",
        " ",
        match.group(1),
    ).strip()


def extract_variable_label(
    record
):

    raw_text = clean(
        record.get(
            "raw_text"
        )
    )

    variable = clean(
        record.get(
            "name"
        )
    )

    data_marker = re.search(
        r"\r?\nData file:",
        raw_text,
        flags=re.IGNORECASE,
    )

    if not data_marker:

        return ""

    before = (
        raw_text[
            :data_marker.start()
        ]
    )

    lines = [
        line.strip()
        for line in before.splitlines()
        if line.strip()
    ]

    if not lines:
        return ""

    candidate = (
        lines[-1]
    )

    # Typical NADA line:
    # Credit agency (b14_q6)

    pattern = re.compile(
        r"\s*\("
        + re.escape(
            variable
        )
        + r"\)\s*$",
        flags=re.IGNORECASE,
    )

    candidate = pattern.sub(
        "",
        candidate,
    ).strip()

    candidate = (
        candidate
        .replace(
            "‘",
            ""
        )
        .replace(
            "’",
            ""
        )
        .replace(
            "“",
            ""
        )
        .replace(
            "”",
            ""
        )
    )

    return candidate


def metadata_valid_count(
    record
):

    overview = (
        record.get(
            "overview"
        )
        or {}
    )

    return clean(
        overview.get(
            "valid"
        )
    )


def metadata_invalid_count(
    record
):

    overview = (
        record.get(
            "overview"
        )
        or {}
    )

    return clean(
        overview.get(
            "invalid"
        )
    )


def load_metadata_packages(
    metadata_manifest_rows
):

    print(
        "\n[2] Loading locked NADA metadata"
    )

    result = {}

    for visit in [
        "visit1",
        "visit2",
    ]:

        candidates = [
            row
            for row in metadata_manifest_rows
            if clean(
                row.get(
                    "visit"
                )
            ) == visit
        ]

        if len(
            candidates
        ) != 1:

            errors.append(
                f"{visit}: cannot select "
                f"locked metadata JSON."
            )

            continue

        path = Path(
            candidates[
                0
            ]["path"]
        )

        if not path.exists():

            errors.append(
                f"{visit}: metadata JSON "
                f"does not exist: {path}"
            )

            continue

        with path.open(
            "r",
            encoding="utf-8-sig",
        ) as fh:

            records = json.load(
                fh
            )

        if not isinstance(
            records,
            list,
        ):

            errors.append(
                f"{visit}: metadata JSON "
                f"is not a list."
            )

            continue

        expected_records = (
            EXPECTED[
                visit
            ]["metadata_records"]
        )

        if (
            len(records)
            != expected_records
        ):

            errors.append(
                f"{visit}: expected "
                f"{expected_records} metadata records; "
                f"found {len(records)}"
            )

        enriched = []

        for record_number, record in enumerate(
            records,
            start=1,
        ):

            metadata_data_file = (
                extract_metadata_data_file(
                    record
                )
            )

            variable_name = clean(
                record.get(
                    "name"
                )
            )

            enriched.append({
                "record_number":
                    record_number,

                "metadata_group":
                    clean(
                        record.get(
                            "file"
                        )
                    ),

                "metadata_data_file":
                    metadata_data_file,

                "variable_name":
                    variable_name,

                "normalized_variable":
                    normalize_name(
                        variable_name
                    ),

                "variable_label":
                    extract_variable_label(
                        record
                    ),

                "variable_url":
                    clean(
                        record.get(
                            "url"
                        )
                    ),

                "valid_count":
                    metadata_valid_count(
                        record
                    ),

                "invalid_count":
                    metadata_invalid_count(
                        record
                    ),

                "_source":
                    record,
            })

        groups = defaultdict(
            list
        )

        for record in enriched:

            data_file = clean(
                record[
                    "metadata_data_file"
                ]
            )

            if data_file:

                groups[
                    data_file
                ].append(
                    record
                )

        expected_groups = (
            EXPECTED[
                visit
            ]["metadata_data_files"]
        )

        if (
            len(groups)
            != expected_groups
        ):

            errors.append(
                f"{visit}: expected "
                f"{expected_groups} metadata "
                f"data-file groups; "
                f"found {len(groups)}"
            )

        result[
            visit
        ] = {
            "path":
                path,

            "records":
                enriched,

            "groups":
                dict(groups),
        }

        print(
            f"{visit.upper():8s} "
            f"records={len(enriched):>3} | "
            f"data-file groups={len(groups):>2} | "
            f"{path.name}"
        )

    return result


# =============================================================================
# KNOWN VISIT-1 BLOCK 16 METADATA GAP
# =============================================================================

def is_known_visit1_metadata_gap(
    visit,
    raw_file_name,
):

    if visit != "visit1":
        return False

    compact = normalize_file_text(
        raw_file_name
    )

    # The two files are:
    #
    # Visit 1_Block 16.csv
    # Visit 1_Block 16_value.csv

    return (
        "visit1block16"
        in compact
    )


# =============================================================================
# RAW FILE HEADER CATALOG
# =============================================================================

def build_raw_header_catalog(
    raw_manifest_rows,
    raw_inventory,
):

    print(
        "\n[3] Reading locked raw headers"
    )

    result = []

    for index, row in enumerate(
        sorted(
            raw_manifest_rows,
            key=lambda x: (
                clean(
                    x.get(
                        "visit"
                    )
                ),
                clean(
                    x.get(
                        "file_name"
                    )
                ),
            ),
        ),
        start=1,
    ):

        visit = clean(
            row.get(
                "visit"
            )
        )

        file_name = clean(
            row.get(
                "file_name"
            )
        )

        path = Path(
            clean(
                row.get(
                    "path"
                )
            )
        )

        if not path.exists():

            errors.append(
                f"{visit}: locked raw file missing: "
                f"{path}"
            )

            continue

        inventory_record = (
            raw_inventory.get(
                (
                    visit,
                    file_name,
                )
            )
        )

        try:

            (
                headers,
                sheet,
                header_row,
            ) = read_raw_header(
                path,
                inventory_record,
            )

        except Exception as exc:

            errors.append(
                f"{visit}: failed reading header "
                f"for {file_name}: "
                f"{type(exc).__name__}: {exc}"
            )

            continue

        if not headers:

            errors.append(
                f"{visit}: no headers found "
                f"in {file_name}"
            )

            continue

        normalized_headers = [
            normalize_name(
                header
            )
            for header in headers
        ]

        blank_headers = sum(
            1
            for header in headers
            if not clean(
                header
            )
        )

        duplicate_normalized = [
            name
            for name, count
            in Counter(
                normalized_headers
            ).items()
            if (
                name
                and
                count > 1
            )
        ]

        if blank_headers:

            errors.append(
                f"{visit}: {file_name} "
                f"has {blank_headers} blank headers."
            )

        if duplicate_normalized:

            errors.append(
                f"{visit}: {file_name} "
                f"has duplicate normalized "
                f"headers: {duplicate_normalized}"
            )

        result.append({
            "visit":
                visit,

            "file_name":
                file_name,

            "path":
                path,

            "headers":
                headers,

            "normalized_headers":
                normalized_headers,

            "sheet":
                sheet,

            "header_row":
                header_row,

            "row_count":
                clean(
                    row.get(
                        "row_count"
                    )
                ),

            "column_count":
                len(headers),

            "known_metadata_gap":
                is_known_visit1_metadata_gap(
                    visit,
                    file_name,
                ),
        })

        print(
            f"  [{index:02d}/"
            f"{len(raw_manifest_rows):02d}] "
            f"{visit.upper():6s} | "
            f"cols={len(headers):>2} | "
            f"{file_name}"
        )

    return result


# =============================================================================
# DATASET MATCHING
# =============================================================================

def score_dataset_group(
    raw_headers,
    metadata_records,
):

    raw_set = {
        normalize_name(
            header
        )
        for header in raw_headers
        if normalize_name(
            header
        )
    }

    metadata_set = {
        record[
            "normalized_variable"
        ]
        for record
        in metadata_records
        if record[
            "normalized_variable"
        ]
    }

    intersection = (
        raw_set
        & metadata_set
    )

    matched = len(
        intersection
    )

    raw_coverage = (
        matched
        / len(raw_set)
        if raw_set
        else 0.0
    )

    metadata_coverage = (
        matched
        / len(metadata_set)
        if metadata_set
        else 0.0
    )

    union = (
        raw_set
        | metadata_set
    )

    jaccard = (
        matched
        / len(union)
        if union
        else 0.0
    )

    return {
        "matched":
            matched,

        "raw_coverage":
            raw_coverage,

        "metadata_coverage":
            metadata_coverage,

        "jaccard":
            jaccard,

        "combined_score":
            (
                raw_coverage
                + metadata_coverage
                + jaccard
            ),
    }


def map_datasets(
    raw_catalog,
    metadata_packages,
):

    print(
        "\n[4] Exact dataset mapping"
    )

    dataset_rows = []

    mapped_group_usage = defaultdict(
        list
    )

    for raw in raw_catalog:

        visit = raw[
            "visit"
        ]

        file_name = raw[
            "file_name"
        ]

        # -------------------------------------------------------------
        # Known Visit-1 metadata omission.
        # -------------------------------------------------------------

        if raw[
            "known_metadata_gap"
        ]:

            dataset_rows.append({
                "visit":
                    visit,

                "raw_file":
                    file_name,

                "raw_columns":
                    raw[
                        "column_count"
                    ],

                "metadata_data_file":
                    "",

                "metadata_group":
                    "",

                "matched_variables":
                    0,

                "raw_coverage_pct":
                    "",

                "metadata_coverage_pct":
                    "",

                "jaccard_pct":
                    "",

                "dataset_status":
                    "KNOWN_METADATA_GAP",
            })

            print(
                f"  {visit.upper():6s} | "
                f"KNOWN GAP | "
                f"{file_name}"
            )

            continue

        package = (
            metadata_packages.get(
                visit
            )
        )

        if not package:

            errors.append(
                f"{visit}: metadata package unavailable."
            )

            continue

        scores = []

        for data_file, records in (
            package[
                "groups"
            ].items()
        ):

            score = (
                score_dataset_group(
                    raw[
                        "headers"
                    ],
                    records,
                )
            )

            scores.append({
                "metadata_data_file":
                    data_file,

                "metadata_group":
                    (
                        records[
                            0
                        ][
                            "metadata_group"
                        ]
                        if records
                        else ""
                    ),

                **score,
            })

        scores.sort(
            key=lambda item: (
                item[
                    "combined_score"
                ],
                item[
                    "matched"
                ],
            ),
            reverse=True,
        )

        if not scores:

            errors.append(
                f"{visit}: no metadata groups "
                f"available for {file_name}"
            )

            continue

        best = (
            scores[0]
        )

        second = (
            scores[1]
            if len(scores) > 1
            else None
        )

        # -------------------------------------------------------------
        # A valid group should explain nearly the whole raw schema
        # AND nearly the whole metadata schema.
        # -------------------------------------------------------------

        strong = (
            best[
                "raw_coverage"
            ] >= 0.80
            and
            best[
                "metadata_coverage"
            ] >= 0.80
        )

        ambiguous = False

        if (
            strong
            and
            second is not None
            and
            second[
                "raw_coverage"
            ] >= 0.80
            and
            second[
                "metadata_coverage"
            ] >= 0.80
            and
            abs(
                best[
                    "combined_score"
                ]
                -
                second[
                    "combined_score"
                ]
            ) < 0.05
        ):

            ambiguous = True

        if ambiguous:

            status = (
                "AMBIGUOUS"
            )

            errors.append(
                f"{visit}: ambiguous metadata "
                f"dataset mapping for "
                f"{file_name}"
            )

        elif not strong:

            status = (
                "UNMAPPED"
            )

            errors.append(
                f"{visit}: no sufficiently strong "
                f"metadata dataset mapping for "
                f"{file_name}. "
                f"Best raw coverage="
                f"{best['raw_coverage']:.3f}, "
                f"metadata coverage="
                f"{best['metadata_coverage']:.3f}"
            )

        elif (
            best[
                "raw_coverage"
            ] == 1.0
            and
            best[
                "metadata_coverage"
            ] == 1.0
        ):

            status = (
                "EXACT"
            )

        else:

            status = (
                "STRONG"
            )

        dataset_rows.append({
            "visit":
                visit,

            "raw_file":
                file_name,

            "raw_columns":
                raw[
                    "column_count"
                ],

            "metadata_data_file":
                (
                    best[
                        "metadata_data_file"
                    ]
                    if strong
                    else ""
                ),

            "metadata_group":
                (
                    best[
                        "metadata_group"
                    ]
                    if strong
                    else ""
                ),

            "matched_variables":
                best[
                    "matched"
                ],

            "raw_coverage_pct":
                f"{best['raw_coverage'] * 100:.6f}",

            "metadata_coverage_pct":
                f"{best['metadata_coverage'] * 100:.6f}",

            "jaccard_pct":
                f"{best['jaccard'] * 100:.6f}",

            "dataset_status":
                status,
        })

        if strong:

            mapped_group_usage[
                (
                    visit,
                    best[
                        "metadata_data_file"
                    ],
                )
            ].append(
                file_name
            )

        print(
            f"  {visit.upper():6s} | "
            f"{status:10s} | "
            f"raw={best['raw_coverage']*100:6.2f}% | "
            f"meta={best['metadata_coverage']*100:6.2f}% | "
            f"{file_name}"
        )

    # -----------------------------------------------------------------
    # A metadata data-file must map to one and only one raw dataset.
    # -----------------------------------------------------------------

    for (
        visit,
        metadata_data_file,
    ), raw_files in (
        mapped_group_usage.items()
    ):

        if len(
            raw_files
        ) > 1:

            errors.append(
                f"{visit}: metadata data file "
                f"'{metadata_data_file}' mapped "
                f"to multiple raw datasets: "
                f"{raw_files}"
            )

    # -----------------------------------------------------------------
    # Every metadata group must be represented exactly once.
    # -----------------------------------------------------------------

    for visit in [
        "visit1",
        "visit2",
    ]:

        package = (
            metadata_packages.get(
                visit
            )
        )

        if not package:
            continue

        for data_file in (
            package[
                "groups"
            ]
        ):

            usage = (
                mapped_group_usage.get(
                    (
                        visit,
                        data_file,
                    ),
                    [],
                )
            )

            if len(
                usage
            ) == 0:

                errors.append(
                    f"{visit}: metadata data file "
                    f"has no raw dataset mapping: "
                    f"{data_file}"
                )

    known_gaps = [
        row
        for row in dataset_rows
        if row[
            "dataset_status"
        ] == "KNOWN_METADATA_GAP"
    ]

    visit1_known = sum(
        1
        for row in known_gaps
        if row[
            "visit"
        ] == "visit1"
    )

    if (
        visit1_known
        != EXPECTED[
            "visit1"
        ][
            "known_metadata_gap_count"
        ]
    ):

        errors.append(
            "visit1: expected exactly "
            f"{EXPECTED['visit1']['known_metadata_gap_count']} "
            f"known metadata-gap datasets; "
            f"found {visit1_known}"
        )

    return dataset_rows


# =============================================================================
# VARIABLE MAPPING
# =============================================================================

def build_variable_mapping(
    raw_catalog,
    dataset_rows,
    metadata_packages,
):

    print(
        "\n[5] Exact variable mapping"
    )

    dataset_lookup = {
        (
            row[
                "visit"
            ],
            row[
                "raw_file"
            ],
        ):
            row

        for row in dataset_rows
    }

    variable_rows = []

    per_dataset_stats = []

    for raw in raw_catalog:

        visit = raw[
            "visit"
        ]

        raw_file = raw[
            "file_name"
        ]

        dataset = (
            dataset_lookup.get(
                (
                    visit,
                    raw_file,
                )
            )
        )

        if not dataset:

            continue

        dataset_status = (
            dataset[
                "dataset_status"
            ]
        )

        # -------------------------------------------------------------
        # Known raw-header-only Visit-1 Block 16 datasets.
        # -------------------------------------------------------------

        if (
            dataset_status
            == "KNOWN_METADATA_GAP"
        ):

            for column_number, raw_variable in enumerate(
                raw[
                    "headers"
                ],
                start=1,
            ):

                variable_rows.append({
                    "visit":
                        visit,

                    "raw_file":
                        raw_file,

                    "metadata_data_file":
                        "",

                    "metadata_group":
                        "",

                    "column_number":
                        column_number,

                    "raw_variable":
                        raw_variable,

                    "normalized_variable":
                        normalize_name(
                            raw_variable
                        ),

                    "metadata_variable":
                        "",

                    "variable_label":
                        "",

                    "variable_url":
                        "",

                    "metadata_valid":
                        "",

                    "metadata_invalid":
                        "",

                    "candidate_tag":
                        classify_candidate(
                            visit,
                            raw_file,
                            raw_variable,
                            "",
                            "",
                        ),

                    "mapping_status":
                        "KNOWN_METADATA_GAP",
                })

            per_dataset_stats.append({
                "visit":
                    visit,

                "raw_file":
                    raw_file,

                "raw_variables":
                    len(
                        raw[
                            "headers"
                        ]
                    ),

                "metadata_variables":
                    0,

                "exact_variables":
                    0,

                "raw_only":
                    len(
                        raw[
                            "headers"
                        ]
                    ),

                "metadata_only":
                    0,

                "status":
                    "KNOWN_METADATA_GAP",
            })

            continue

        if dataset_status not in {
            "EXACT",
            "STRONG",
        }:

            continue

        metadata_data_file = (
            dataset[
                "metadata_data_file"
            ]
        )

        metadata_records = (
            metadata_packages[
                visit
            ][
                "groups"
            ][
                metadata_data_file
            ]
        )

        metadata_by_name = defaultdict(
            list
        )

        for record in metadata_records:

            metadata_by_name[
                record[
                    "normalized_variable"
                ]
            ].append(
                record
            )

        raw_norms = set()

        exact_count = 0
        raw_only_count = 0

        for column_number, raw_variable in enumerate(
            raw[
                "headers"
            ],
            start=1,
        ):

            normalized = (
                normalize_name(
                    raw_variable
                )
            )

            raw_norms.add(
                normalized
            )

            candidates = (
                metadata_by_name.get(
                    normalized,
                    [],
                )
            )

            if len(
                candidates
            ) == 1:

                record = (
                    candidates[0]
                )

                mapping_status = (
                    "EXACT"
                )

                exact_count += 1

            elif len(
                candidates
            ) == 0:

                record = None

                mapping_status = (
                    "RAW_ONLY"
                )

                raw_only_count += 1

                errors.append(
                    f"{visit}: raw variable "
                    f"'{raw_variable}' in "
                    f"{raw_file} has no metadata "
                    f"record in matched data file."
                )

            else:

                record = None

                mapping_status = (
                    "AMBIGUOUS_METADATA"
                )

                errors.append(
                    f"{visit}: raw variable "
                    f"'{raw_variable}' in "
                    f"{raw_file} matches multiple "
                    f"metadata records."
                )

            variable_label = (
                record[
                    "variable_label"
                ]
                if record
                else ""
            )

            metadata_variable = (
                record[
                    "variable_name"
                ]
                if record
                else ""
            )

            variable_rows.append({
                "visit":
                    visit,

                "raw_file":
                    raw_file,

                "metadata_data_file":
                    metadata_data_file,

                "metadata_group":
                    (
                        record[
                            "metadata_group"
                        ]
                        if record
                        else dataset[
                            "metadata_group"
                        ]
                    ),

                "column_number":
                    column_number,

                "raw_variable":
                    raw_variable,

                "normalized_variable":
                    normalized,

                "metadata_variable":
                    metadata_variable,

                "variable_label":
                    variable_label,

                "variable_url":
                    (
                        record[
                            "variable_url"
                        ]
                        if record
                        else ""
                    ),

                "metadata_valid":
                    (
                        record[
                            "valid_count"
                        ]
                        if record
                        else ""
                    ),

                "metadata_invalid":
                    (
                        record[
                            "invalid_count"
                        ]
                        if record
                        else ""
                    ),

                "candidate_tag":
                    classify_candidate(
                        visit,
                        raw_file,
                        raw_variable,
                        metadata_variable,
                        variable_label,
                    ),

                "mapping_status":
                    mapping_status,
            })

        # -------------------------------------------------------------
        # Metadata-only variables.
        # -------------------------------------------------------------

        metadata_only = []

        for record in metadata_records:

            normalized = (
                record[
                    "normalized_variable"
                ]
            )

            if (
                normalized
                not in raw_norms
            ):

                metadata_only.append(
                    record
                )

                variable_rows.append({
                    "visit":
                        visit,

                    "raw_file":
                        raw_file,

                    "metadata_data_file":
                        metadata_data_file,

                    "metadata_group":
                        record[
                            "metadata_group"
                        ],

                    "column_number":
                        "",

                    "raw_variable":
                        "",

                    "normalized_variable":
                        normalized,

                    "metadata_variable":
                        record[
                            "variable_name"
                        ],

                    "variable_label":
                        record[
                            "variable_label"
                        ],

                    "variable_url":
                        record[
                            "variable_url"
                        ],

                    "metadata_valid":
                        record[
                            "valid_count"
                        ],

                    "metadata_invalid":
                        record[
                            "invalid_count"
                        ],

                    "candidate_tag":
                        classify_candidate(
                            visit,
                            raw_file,
                            "",
                            record[
                                "variable_name"
                            ],
                            record[
                                "variable_label"
                            ],
                        ),

                    "mapping_status":
                        "METADATA_ONLY",
                })

        if metadata_only:

            errors.append(
                f"{visit}: {raw_file} has "
                f"{len(metadata_only)} metadata-only "
                f"variables."
            )

        if (
            raw_only_count == 0
            and
            len(metadata_only) == 0
            and
            exact_count
            == len(
                raw[
                    "headers"
                ]
            )
        ):

            status = "EXACT"

        else:

            status = "MISMATCH"

        per_dataset_stats.append({
            "visit":
                visit,

            "raw_file":
                raw_file,

            "raw_variables":
                len(
                    raw[
                        "headers"
                    ]
                ),

            "metadata_variables":
                len(
                    metadata_records
                ),

            "exact_variables":
                exact_count,

            "raw_only":
                raw_only_count,

            "metadata_only":
                len(
                    metadata_only
                ),

            "status":
                status,
        })

        print(
            f"  {visit.upper():6s} | "
            f"{status:10s} | "
            f"raw={len(raw['headers']):>2} | "
            f"meta={len(metadata_records):>2} | "
            f"exact={exact_count:>2} | "
            f"{raw_file}"
        )

    return (
        variable_rows,
        per_dataset_stats,
    )


# =============================================================================
# NON-BINDING SEMANTIC CANDIDATES
# =============================================================================

def classify_candidate(
    visit,
    raw_file,
    raw_variable,
    metadata_variable,
    variable_label,
):

    variable = (
        metadata_variable
        or raw_variable
    )

    normalized = (
        normalize_name(
            variable
        )
    )

    text = " ".join([
        clean(
            raw_file
        ).lower(),

        clean(
            variable_label
        ).lower(),
    ])

    # -----------------------------------------------------------------
    # Core survey fields
    # -----------------------------------------------------------------

    core_names = {
        "hhid",
        "sector",
        "state",
        "stateregion",
        "districtid",
        "statedistrict",
        "visitno",
        "round",
        "schedule",
        "nss",
        "nsc",
        "mlt",
        "weightss",
        "weightsc",
    }

    if normalized in core_names:

        return "CORE_ID_WEIGHT"

    # -----------------------------------------------------------------
    # Household characteristics / classification candidates
    # -----------------------------------------------------------------

    if (
        "household characteristics"
        in text
        or
        normalized.startswith(
            "b3q"
        )
    ):

        return "HOUSEHOLD_CLASSIFICATION_CANDIDATE"

    # -----------------------------------------------------------------
    # Debt / credit
    # -----------------------------------------------------------------

    if (
        "cash loans payable"
        in text
        or
        normalized.startswith(
            "b14q"
        )
    ):

        if (
            "interest"
            in text
        ):

            return "DEBT_INTEREST_CANDIDATE"

        if (
            "credit agency"
            in text
            or
            "agency"
            in text
        ):

            return "DEBT_AGENCY_CANDIDATE"

        if (
            "purpose"
            in text
        ):

            return "DEBT_PURPOSE_CANDIDATE"

        return "DEBT_CREDIT_CANDIDATE"

    # -----------------------------------------------------------------
    # Visit-1 asset stock blocks
    # -----------------------------------------------------------------

    if (
        visit == "visit1"
        and any(
            phrase
            in text
            for phrase in [
                "land owned",
                "buildings and other constructions",
                "livestock and poultry",
                "transport equipment",
                "agricultural machinery",
                "non-farm business equipment",
                "shares",
                "deposits",
                "financial",
            ]
        )
    ):

        return "ASSET_STOCK_CANDIDATE"

    # -----------------------------------------------------------------
    # Block 16 capital expenditure
    # -----------------------------------------------------------------

    if (
        "block 16"
        in text
        or
        normalized.startswith(
            "b16q"
        )
    ):

        return "CAPITAL_EXPENDITURE_CANDIDATE"

    return ""


def build_semantic_candidates(
    variable_rows
):

    return [
        {
            "visit":
                row[
                    "visit"
                ],

            "raw_file":
                row[
                    "raw_file"
                ],

            "metadata_data_file":
                row[
                    "metadata_data_file"
                ],

            "raw_variable":
                row[
                    "raw_variable"
                ],

            "metadata_variable":
                row[
                    "metadata_variable"
                ],

            "variable_label":
                row[
                    "variable_label"
                ],

            "candidate_tag":
                row[
                    "candidate_tag"
                ],

            "mapping_status":
                row[
                    "mapping_status"
                ],

            "variable_url":
                row[
                    "variable_url"
                ],
        }

        for row in variable_rows

        if clean(
            row.get(
                "candidate_tag"
            )
        )
    ]


# =============================================================================
# METADATA GROUP COVERAGE
# =============================================================================

def build_metadata_group_coverage(
    metadata_packages,
    dataset_rows,
    variable_stats,
):

    dataset_lookup = {
        (
            row[
                "visit"
            ],
            row[
                "metadata_data_file"
            ],
        ):
            row

        for row in dataset_rows

        if clean(
            row.get(
                "metadata_data_file"
            )
        )
    }

    variable_lookup = {
        (
            row[
                "visit"
            ],
            row[
                "raw_file"
            ],
        ):
            row

        for row in variable_stats
    }

    output = []

    for visit, package in (
        metadata_packages.items()
    ):

        for data_file, records in (
            package[
                "groups"
            ].items()
        ):

            dataset = (
                dataset_lookup.get(
                    (
                        visit,
                        data_file,
                    )
                )
            )

            raw_file = (
                dataset[
                    "raw_file"
                ]
                if dataset
                else ""
            )

            variable_stat = (
                variable_lookup.get(
                    (
                        visit,
                        raw_file,
                    )
                )
                if raw_file
                else None
            )

            output.append({
                "visit":
                    visit,

                "metadata_data_file":
                    data_file,

                "metadata_group":
                    (
                        records[
                            0
                        ][
                            "metadata_group"
                        ]
                        if records
                        else ""
                    ),

                "metadata_variables":
                    len(
                        records
                    ),

                "mapped_raw_file":
                    raw_file,

                "dataset_status":
                    (
                        dataset[
                            "dataset_status"
                        ]
                        if dataset
                        else "UNMAPPED"
                    ),

                "exact_variables":
                    (
                        variable_stat[
                            "exact_variables"
                        ]
                        if variable_stat
                        else 0
                    ),

                "raw_only":
                    (
                        variable_stat[
                            "raw_only"
                        ]
                        if variable_stat
                        else ""
                    ),

                "metadata_only":
                    (
                        variable_stat[
                            "metadata_only"
                        ]
                        if variable_stat
                        else ""
                    ),
            })

    return output


# =============================================================================
# MAIN
# =============================================================================

def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS 2013 - STEP 01B "
        "EXACT VARIABLE & BLOCK MAPPING"
    )

    print(
        "NSS 70th Round | "
        "Visit 1 + Visit 2"
    )

    print(
        "=" * 78
    )

    print(
        f"Project root              : "
        f"{PROJECT_ROOT}"
    )

    try:

        (
            raw_manifest_rows,
            metadata_manifest_rows,
        ) = load_step01_manifest()

        raw_inventory = (
            load_raw_inventory()
        )

        metadata_packages = (
            load_metadata_packages(
                metadata_manifest_rows
            )
        )

        raw_catalog = (
            build_raw_header_catalog(
                raw_manifest_rows,
                raw_inventory,
            )
        )

        dataset_rows = (
            map_datasets(
                raw_catalog,
                metadata_packages,
            )
        )

        (
            variable_rows,
            variable_stats,
        ) = build_variable_mapping(
            raw_catalog,
            dataset_rows,
            metadata_packages,
        )

        metadata_coverage = (
            build_metadata_group_coverage(
                metadata_packages,
                dataset_rows,
                variable_stats,
            )
        )

        semantic_candidates = (
            build_semantic_candidates(
                variable_rows
            )
        )

    except Exception as exc:

        errors.append(
            f"Fatal Step-01B error: "
            f"{type(exc).__name__}: {exc}"
        )

        print(
            f"\nFATAL: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        dataset_rows = []
        variable_rows = []
        variable_stats = []
        metadata_coverage = []
        semantic_candidates = []

    # =========================================================================
    # OUTPUTS
    # =========================================================================

    write_csv(
        DATASET_MAP_FILE,
        dataset_rows,
        [
            "visit",
            "raw_file",
            "raw_columns",
            "metadata_data_file",
            "metadata_group",
            "matched_variables",
            "raw_coverage_pct",
            "metadata_coverage_pct",
            "jaccard_pct",
            "dataset_status",
        ],
    )

    write_csv(
        VARIABLE_MAP_FILE,
        variable_rows,
        [
            "visit",
            "raw_file",
            "metadata_data_file",
            "metadata_group",
            "column_number",
            "raw_variable",
            "normalized_variable",
            "metadata_variable",
            "variable_label",
            "variable_url",
            "metadata_valid",
            "metadata_invalid",
            "candidate_tag",
            "mapping_status",
        ],
    )

    # Canonical catalog is intentionally the same mapping in CONFIG,
    # because all later pipeline steps should consume THIS locked mapping
    # rather than re-scraping/re-inferring metadata.

    write_csv(
        CANONICAL_CATALOG_FILE,
        variable_rows,
        [
            "visit",
            "raw_file",
            "metadata_data_file",
            "metadata_group",
            "column_number",
            "raw_variable",
            "normalized_variable",
            "metadata_variable",
            "variable_label",
            "variable_url",
            "metadata_valid",
            "metadata_invalid",
            "candidate_tag",
            "mapping_status",
        ],
    )

    write_csv(
        METADATA_COVERAGE_FILE,
        metadata_coverage,
        [
            "visit",
            "metadata_data_file",
            "metadata_group",
            "metadata_variables",
            "mapped_raw_file",
            "dataset_status",
            "exact_variables",
            "raw_only",
            "metadata_only",
        ],
    )

    write_csv(
        SEMANTIC_CANDIDATES_FILE,
        semantic_candidates,
        [
            "visit",
            "raw_file",
            "metadata_data_file",
            "raw_variable",
            "metadata_variable",
            "variable_label",
            "candidate_tag",
            "mapping_status",
            "variable_url",
        ],
    )

    # =========================================================================
    # SUMMARY METRICS
    # =========================================================================

    exact_datasets = sum(
        1
        for row in dataset_rows
        if row[
            "dataset_status"
        ] == "EXACT"
    )

    strong_datasets = sum(
        1
        for row in dataset_rows
        if row[
            "dataset_status"
        ] == "STRONG"
    )

    known_gap_datasets = sum(
        1
        for row in dataset_rows
        if row[
            "dataset_status"
        ] == "KNOWN_METADATA_GAP"
    )

    bad_datasets = sum(
        1
        for row in dataset_rows
        if row[
            "dataset_status"
        ] in {
            "UNMAPPED",
            "AMBIGUOUS",
        }
    )

    exact_variables = sum(
        1
        for row in variable_rows
        if row[
            "mapping_status"
        ] == "EXACT"
    )

    raw_only_variables = sum(
        1
        for row in variable_rows
        if row[
            "mapping_status"
        ] == "RAW_ONLY"
    )

    metadata_only_variables = sum(
        1
        for row in variable_rows
        if row[
            "mapping_status"
        ] == "METADATA_ONLY"
    )

    gap_variables = sum(
        1
        for row in variable_rows
        if row[
            "mapping_status"
        ] == "KNOWN_METADATA_GAP"
    )

    ambiguous_variables = sum(
        1
        for row in variable_rows
        if row[
            "mapping_status"
        ] == "AMBIGUOUS_METADATA"
    )

    metadata_groups = sum(
        EXPECTED[
            visit
        ][
            "metadata_data_files"
        ]
        for visit in [
            "visit1",
            "visit2",
        ]
    )

    mapped_metadata_groups = sum(
        1
        for row in metadata_coverage
        if clean(
            row.get(
                "mapped_raw_file"
            )
        )
    )

    # =========================================================================
    # FINAL STATUS
    # =========================================================================

    if (
        bad_datasets
        or
        raw_only_variables
        or
        metadata_only_variables
        or
        ambiguous_variables
    ):

        if not errors:

            errors.append(
                "Mapping mismatch detected."
            )

    status = (
        "PASS_WITH_DISCLOSURES"
        if (
            not errors
            and
            known_gap_datasets > 0
        )
        else
        (
            "PASS"
            if not errors
            else "FAIL"
        )
    )

    summary_lines = [
        "=" * 78,
        "AIDIS 2013 - STEP 01B VARIABLE MAPPING SUMMARY",
        "=" * 78,
        "",
        f"Project root              : {PROJECT_ROOT}",
        "",
        "DATASET MAPPING",
        "---------------",
        f"Raw datasets audited      : {len(dataset_rows)}",
        f"Exact dataset mappings    : {exact_datasets}",
        f"Strong dataset mappings   : {strong_datasets}",
        f"Known metadata gaps       : {known_gap_datasets}",
        f"Bad dataset mappings      : {bad_datasets}",
        "",
        "VARIABLE MAPPING",
        "----------------",
        f"Exact variables           : {exact_variables}",
        f"Raw-only variables        : {raw_only_variables}",
        f"Metadata-only variables   : {metadata_only_variables}",
        f"Ambiguous variables       : {ambiguous_variables}",
        f"Known-gap raw variables   : {gap_variables}",
        "",
        "METADATA GROUPS",
        "---------------",
        f"Expected groups           : {metadata_groups}",
        f"Mapped groups             : {mapped_metadata_groups}",
        "",
        f"Semantic candidates       : {len(semantic_candidates)}",
        "",
        f"Errors                    : {len(errors)}",
        f"Warnings                  : {len(warnings)}",
        "",
        f"Dataset map               : {DATASET_MAP_FILE}",
        f"Variable map              : {VARIABLE_MAP_FILE}",
        f"Metadata coverage         : {METADATA_COVERAGE_FILE}",
        f"Semantic candidates       : {SEMANTIC_CANDIDATES_FILE}",
        f"Canonical catalog         : {CANONICAL_CATALOG_FILE}",
        "",
    ]

    # Known Visit-1 Block 16 omission is explicitly disclosed,
    # rather than silently guessed.

    if known_gap_datasets:

        summary_lines.extend([
            "DISCLOSURES:",
            (
                "  - Visit-1 Block 16 / Block 16_value are retained "
                "as raw-header-only production datasets because the "
                "supplied Visit-1 NADA variable metadata does not provide "
                "separate data-file variable records for these two raw files."
            ),
            (
                "  - Their semantic mapping must be established in the "
                "methodology stage from raw headers plus the official "
                "NSS 70th Round Schedule/Instructions. No variable meaning "
                "is fabricated here."
            ),
            "",
        ])

    if warnings:

        summary_lines.append(
            "WARNINGS:"
        )

        for warning in warnings:

            summary_lines.append(
                f"  - {warning}"
            )

        summary_lines.append(
            ""
        )

    if errors:

        summary_lines.append(
            "ERRORS:"
        )

        for error in errors:

            summary_lines.append(
                f"  - {error}"
            )

        summary_lines.append(
            ""
        )

    summary_lines.extend([
        f"STEP 01B STATUS: {status}",
        "=" * 78,
    ])

    summary = "\n".join(
        summary_lines
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