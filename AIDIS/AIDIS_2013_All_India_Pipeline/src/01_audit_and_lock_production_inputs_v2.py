from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


# =============================================================================
# AIDIS 2013 - STEP 01 V2
# PRODUCTION INPUT AUDIT + LOCK
#
# Fixes:
#   1. Correctly reads NSS XLSX files with broken worksheet dimensions.
#   2. Selects the REAL household identification files explicitly.
#   3. Discovers metadata by content/count, not (1)/(2) filename.
#   4. 0-row XLSX files can no longer PASS.
#   5. Rebuilds Step-01 outputs and manifest from scratch.
# =============================================================================


PROJECT_ROOT = Path(
    r"D:\AIDIS\AIDIS_2013_All_India_Pipeline"
)

RAW_ROOTS = {
    "visit1":
        PROJECT_ROOT
        / "input"
        / "raw"
        / "visit1"
        / "Debt & Investment, NSS 70th Round Visit-1 Jan - Dec 2013",

    "visit2":
        PROJECT_ROOT
        / "input"
        / "raw"
        / "visit2"
        / "Debt & Investment Visit 2 , Jan - Dec 2013",
}

METADATA_ROOT = (
    PROJECT_ROOT
    / "input"
    / "metadata"
)

EXPECTED = {
    "visit1": {
        "raw_files": 18,
        "metadata_records": 519,
        "unique_variables": 129,
        "households": 110800,
        "visit_no": "1",
    },
    "visit2": {
        "raw_files": 6,
        "metadata_records": 211,
        "unique_variables": 80,
        "households": 108425,
        "visit_no": "2",
    },
}


CACHE_DIR = PROJECT_ROOT / "cache"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"
WORK_DIR = PROJECT_ROOT / "work"
LOG_DIR = PROJECT_ROOT / "logs"

for folder in [
    CACHE_DIR,
    REPORT_DIR,
    WORK_DIR,
    LOG_DIR,
]:
    folder.mkdir(
        parents=True,
        exist_ok=True,
    )


RAW_INVENTORY_FILE = (
    CACHE_DIR
    / "step01_raw_inventory.csv"
)

METADATA_INVENTORY_FILE = (
    CACHE_DIR
    / "step01_metadata_inventory.csv"
)

HOUSEHOLD_UNIVERSE_FILE = (
    CACHE_DIR
    / "step01_household_universe.csv"
)

CROSS_VISIT_FILE = (
    CACHE_DIR
    / "step01_cross_visit_audit.csv"
)

COVERAGE_FILE = (
    CACHE_DIR
    / "step01_metadata_raw_coverage.csv"
)

MANIFEST_FILE = (
    CACHE_DIR
    / "step01_production_manifest.csv"
)

SUMMARY_FILE = (
    REPORT_DIR
    / "step01_production_lock_summary.txt"
)


TABULAR_EXTENSIONS = {
    ".csv",
    ".txt",
    ".tsv",
    ".xlsx",
    ".xls",
}


errors = []
warnings = []


# =============================================================================
# FIELD NORMALISATION
# =============================================================================


FIELD_ALIASES = {
    "HHID": {
        "hhid",
    },

    "Visit_no": {
        "visitno",
        "visitnumber",
    },

    "Sector": {
        "sector",
    },

    "State": {
        "state",
    },

    "District_id": {
        "districtid",
        "district",
        "districtcode",
    },

    "State_District": {
        "statedistrict",
    },

    "NSS": {
        "nss",
    },

    "NSC": {
        "nsc",
    },

    "MLT": {
        "mlt",
        "multiplier",
    },

    "Weight_SS": {
        "weightss",
    },

    "Weight_SC": {
        "weightsc",
    },
}


def clean(value):

    if value is None:
        return ""

    if (
        isinstance(value, float)
        and value.is_integer()
    ):
        return str(int(value))

    return str(value).strip()


def normalize_field(value):

    return re.sub(
        r"[^a-z0-9]",
        "",
        str(value).lower(),
    )


def build_canonical_map(headers):

    actual = {}

    for header in headers:

        normalized = normalize_field(
            header
        )

        if normalized:
            actual.setdefault(
                normalized,
                header,
            )

    output = {}

    for canonical, aliases in (
        FIELD_ALIASES.items()
    ):

        for alias in aliases:

            if alias in actual:

                output[canonical] = (
                    actual[alias]
                )

                break

    return output


# =============================================================================
# FILE HASH
# =============================================================================


def sha256_file(
    path,
    block_size=1024 * 1024,
):

    digest = hashlib.sha256()

    with path.open("rb") as fh:

        while True:

            block = fh.read(
                block_size
            )

            if not block:
                break

            digest.update(
                block
            )

    return digest.hexdigest()


# =============================================================================
# CSV/TEXT READER
# =============================================================================


def detect_text_format(path):

    with path.open("rb") as fh:

        raw = fh.read(
            131072
        )

    selected_encoding = None
    sample = None

    for encoding in [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin1",
    ]:

        try:

            sample = raw.decode(
                encoding
            )

            selected_encoding = (
                encoding
            )

            break

        except UnicodeDecodeError:
            continue

    if selected_encoding is None:

        selected_encoding = "latin1"

        sample = raw.decode(
            "latin1"
        )

    if path.suffix.lower() == ".tsv":

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
        selected_encoding,
        delimiter,
    )


def inspect_delimited(path):

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

            headers = [
                clean(value)
                for value in next(reader)
            ]

        except StopIteration:

            return {
                "rows": 0,
                "cols": 0,
                "headers": [],
                "sheet": "",
                "header_row": 0,
                "encoding": encoding,
                "delimiter": delimiter,
            }

        row_count = 0

        for _ in reader:
            row_count += 1

    return {
        "rows": row_count,
        "cols": len(headers),
        "headers": headers,
        "sheet": "",
        "header_row": 1,
        "encoding": encoding,
        "delimiter": delimiter,
    }


# =============================================================================
# ROBUST XLSX READER
# =============================================================================


def row_has_data(row):

    return any(
        value is not None
        and str(value).strip() != ""
        for value in row
    )


def find_header_in_sheet(ws):

    # NSS Excel files sometimes contain an incorrect
    # worksheet dimension such as A1:A1.
    #
    # reset_dimensions() forces openpyxl to stream
    # the real XML rows.

    try:
        ws.reset_dimensions()
    except Exception:
        pass

    for row_number, values in enumerate(
        ws.iter_rows(
            values_only=True
        ),
        start=1,
    ):

        if not row_has_data(
            values
        ):
            continue

        normalized = [
            normalize_field(value)
            for value in values
        ]

        # Every production NSS data block
        # should contain HHID.

        if "hhid" in normalized:

            headers = [
                clean(value)
                for value in values
            ]

            while (
                headers
                and headers[-1] == ""
            ):
                headers.pop()

            return (
                row_number,
                headers,
            )

    return (
        None,
        None,
    )


def inspect_xlsx(path):

    try:

        import openpyxl

    except ImportError as exc:

        raise RuntimeError(
            "Install openpyxl first: "
            "pip install openpyxl"
        ) from exc

    workbook = (
        openpyxl.load_workbook(
            path,
            read_only=True,
            data_only=True,
        )
    )

    candidates = []

    for sheet_name in (
        workbook.sheetnames
    ):

        worksheet = (
            workbook[
                sheet_name
            ]
        )

        (
            header_row,
            headers,
        ) = find_header_in_sheet(
            worksheet
        )

        if headers is None:
            continue

        # Restart worksheet streaming.

        try:
            worksheet.reset_dimensions()
        except Exception:
            pass

        row_count = 0

        for row_number, row in enumerate(
            worksheet.iter_rows(
                values_only=True
            ),
            start=1,
        ):

            if row_number <= header_row:
                continue

            if row_has_data(
                row
            ):
                row_count += 1

        canonical = (
            build_canonical_map(
                headers
            )
        )

        score = row_count

        if "HHID" in canonical:
            score += 10_000_000

        if "Weight_SC" in canonical:
            score += 1_000_000

        candidates.append({
            "score": score,
            "rows": row_count,
            "cols": len(headers),
            "headers": headers,
            "sheet": sheet_name,
            "header_row": header_row,
            "encoding": "",
            "delimiter": "",
        })

    workbook.close()

    if not candidates:

        return {
            "rows": 0,
            "cols": 0,
            "headers": [],
            "sheet": "",
            "header_row": 0,
            "encoding": "",
            "delimiter": "",
        }

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    selected = candidates[0]

    selected.pop(
        "score",
        None,
    )

    return selected


def inspect_tabular(path):

    extension = (
        path.suffix.lower()
    )

    if extension in {
        ".csv",
        ".txt",
        ".tsv",
    }:

        return inspect_delimited(
            path
        )

    if extension == ".xlsx":

        return inspect_xlsx(
            path
        )

    if extension == ".xls":

        import pandas as pd

        dataframe = (
            pd.read_excel(
                path
            )
        )

        return {
            "rows": len(dataframe),
            "cols": len(
                dataframe.columns
            ),
            "headers": [
                str(column)
                for column
                in dataframe.columns
            ],
            "sheet": "",
            "header_row": 1,
            "encoding": "",
            "delimiter": "",
        }

    raise ValueError(
        f"Unsupported file: {path}"
    )


# =============================================================================
# RAW INVENTORY
# =============================================================================


def build_raw_inventory():

    print(
        "\n[1] Raw production file inventory"
    )

    inventory = []

    for visit in [
        "visit1",
        "visit2",
    ]:

        root = RAW_ROOTS[
            visit
        ]

        if not root.exists():

            errors.append(
                f"{visit}: folder missing: {root}"
            )

            continue

        files = sorted(
            path
            for path
            in root.rglob("*")
            if (
                path.is_file()
                and path.suffix.lower()
                in TABULAR_EXTENSIONS
            )
        )

        print(
            f"{visit.upper():8s} "
            f"discovered tabular files : "
            f"{len(files)}"
        )

        expected_count = (
            EXPECTED[
                visit
            ]["raw_files"]
        )

        if len(files) != expected_count:

            errors.append(
                f"{visit}: expected "
                f"{expected_count} datasets, "
                f"found {len(files)}"
            )

        duplicates = [
            name
            for name, count
            in Counter(
                path.name.lower()
                for path in files
            ).items()
            if count > 1
        ]

        if duplicates:

            errors.append(
                f"{visit}: duplicate filenames: "
                f"{duplicates}"
            )

        for index, path in enumerate(
            files,
            start=1,
        ):

            try:

                info = (
                    inspect_tabular(
                        path
                    )
                )

                if (
                    info["rows"] <= 0
                    or info["cols"] <= 0
                ):

                    raise ValueError(
                        "No readable data/header "
                        f"(rows={info['rows']}, "
                        f"cols={info['cols']})"
                    )

                canonical = (
                    build_canonical_map(
                        info["headers"]
                    )
                )

                record = {
                    "_path": path,
                    "_canonical": canonical,

                    "visit": visit,
                    "relative_path":
                        str(
                            path.relative_to(
                                root
                            )
                        ),

                    "file_name": path.name,
                    "extension":
                        path.suffix.lower(),

                    "size_bytes":
                        path.stat().st_size,

                    "row_count":
                        info["rows"],

                    "column_count":
                        info["cols"],

                    "sheet":
                        info["sheet"],

                    "header_row":
                        info["header_row"],

                    "encoding":
                        info["encoding"],

                    "delimiter":
                        "\\t"
                        if info["delimiter"] == "\t"
                        else info["delimiter"],

                    "has_HHID":
                        int(
                            "HHID"
                            in canonical
                        ),

                    "has_Visit_no":
                        int(
                            "Visit_no"
                            in canonical
                        ),

                    "has_Sector":
                        int(
                            "Sector"
                            in canonical
                        ),

                    "has_State":
                        int(
                            "State"
                            in canonical
                        ),

                    "has_District":
                        int(
                            "District_id"
                            in canonical
                            or
                            "State_District"
                            in canonical
                        ),

                    "has_MLT":
                        int(
                            "MLT"
                            in canonical
                        ),

                    "has_NSS":
                        int(
                            "NSS"
                            in canonical
                        ),

                    "has_NSC":
                        int(
                            "NSC"
                            in canonical
                        ),

                    "has_Weight_SS":
                        int(
                            "Weight_SS"
                            in canonical
                        ),

                    "has_Weight_SC":
                        int(
                            "Weight_SC"
                            in canonical
                        ),

                    "status": "PASS",
                    "error": "",
                }

                inventory.append(
                    record
                )

                sheet_text = ""

                if record["sheet"]:

                    sheet_text = (
                        f" | sheet="
                        f"{record['sheet']}"
                    )

                print(
                    f"  [{index:02d}/"
                    f"{len(files):02d}] "
                    f"PASS | "
                    f"rows="
                    f"{record['row_count']:>10,} | "
                    f"cols="
                    f"{record['column_count']:>3}"
                    f"{sheet_text} | "
                    f"{path.name}"
                )

            except Exception as exc:

                errors.append(
                    f"{visit}: "
                    f"{path.name}: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                print(
                    f"  [{index:02d}/"
                    f"{len(files):02d}] "
                    f"FAIL | "
                    f"{path.name} | "
                    f"{exc}"
                )

                inventory.append({
                    "_path": path,
                    "_canonical": {},

                    "visit": visit,
                    "relative_path":
                        str(
                            path.relative_to(
                                root
                            )
                        ),

                    "file_name":
                        path.name,

                    "extension":
                        path.suffix.lower(),

                    "size_bytes":
                        path.stat().st_size,

                    "row_count": 0,
                    "column_count": 0,
                    "sheet": "",
                    "header_row": 0,
                    "encoding": "",
                    "delimiter": "",

                    "has_HHID": 0,
                    "has_Visit_no": 0,
                    "has_Sector": 0,
                    "has_State": 0,
                    "has_District": 0,
                    "has_MLT": 0,
                    "has_NSS": 0,
                    "has_NSC": 0,
                    "has_Weight_SS": 0,
                    "has_Weight_SC": 0,

                    "status": "FAIL",

                    "error":
                        f"{type(exc).__name__}: "
                        f"{exc}",
                })

    return inventory


# =============================================================================
# METADATA DISCOVERY
# =============================================================================


def count_jsonl(path):

    count = 0

    with path.open(
        "r",
        encoding="utf-8-sig",
    ) as fh:

        for line in fh:

            if line.strip():
                count += 1

    return count


def discover_metadata_file(
    visit,
    extension,
    expected_records,
):

    candidates = []

    for path in (
        METADATA_ROOT.rglob(
            f"*{extension}"
        )
    ):

        if not path.is_file():
            continue

        try:

            if extension == ".json":

                with path.open(
                    "r",
                    encoding="utf-8-sig",
                ) as fh:

                    value = json.load(
                        fh
                    )

                if (
                    isinstance(value, list)
                    and
                    len(value)
                    == expected_records
                ):

                    candidates.append(
                        path
                    )

            elif extension == ".jsonl":

                if (
                    count_jsonl(path)
                    == expected_records
                ):

                    candidates.append(
                        path
                    )

            elif extension == ".csv":

                if (
                    inspect_delimited(
                        path
                    )["rows"]
                    == expected_records
                ):

                    candidates.append(
                        path
                    )

        except Exception:
            continue

    if not candidates:

        raise FileNotFoundError(
            f"{visit}: could not find "
            f"{extension} metadata with "
            f"{expected_records} records"
        )

    if len(candidates) > 1:

        preferred = []

        visit_folder = (
            "visit1"
            if visit == "visit1"
            else "visit2"
        )

        for path in candidates:

            if (
                visit_folder
                in str(path).lower()
            ):

                preferred.append(
                    path
                )

        if len(preferred) == 1:

            return preferred[0]

        raise RuntimeError(
            f"{visit}: multiple candidate "
            f"{extension} metadata files: "
            + ", ".join(
                path.name
                for path in candidates
            )
        )

    return candidates[0]


def read_jsonl(path):

    records = []

    with path.open(
        "r",
        encoding="utf-8-sig",
    ) as fh:

        for line_number, line in enumerate(
            fh,
            start=1,
        ):

            if not line.strip():
                continue

            try:

                records.append(
                    json.loads(
                        line
                    )
                )

            except Exception as exc:

                raise ValueError(
                    f"{path.name} line "
                    f"{line_number}: {exc}"
                )

    return records


def metadata_identity(record):

    return (
        clean(
            record.get("file")
        ),
        clean(
            record.get("name")
        ),
        clean(
            record.get("url")
        ),
    )


def extract_data_file(record):

    raw_text = str(
        record.get("raw_text")
        or ""
    )

    match = re.search(
        r"Data file:\s*"
        r"(.*?)"
        r"\r?\nOverview",
        raw_text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if match:

        return re.sub(
            r"\s+",
            " ",
            match.group(1),
        ).strip()

    return ""


def audit_metadata():

    print(
        "\n[2] Metadata package consistency"
    )

    packages = {}
    inventory = []

    for visit in [
        "visit1",
        "visit2",
    ]:

        expected_records = (
            EXPECTED[
                visit
            ]["metadata_records"]
        )

        try:

            json_path = (
                discover_metadata_file(
                    visit,
                    ".json",
                    expected_records,
                )
            )

            jsonl_path = (
                discover_metadata_file(
                    visit,
                    ".jsonl",
                    expected_records,
                )
            )

            csv_path = (
                discover_metadata_file(
                    visit,
                    ".csv",
                    expected_records,
                )
            )

            with json_path.open(
                "r",
                encoding="utf-8-sig",
            ) as fh:

                json_records = (
                    json.load(
                        fh
                    )
                )

            jsonl_records = (
                read_jsonl(
                    jsonl_path
                )
            )

            summary_rows = (
                inspect_delimited(
                    csv_path
                )["rows"]
            )

            json_ids = {
                metadata_identity(
                    record
                )
                for record
                in json_records
            }

            jsonl_ids = {
                metadata_identity(
                    record
                )
                for record
                in jsonl_records
            }

            unique_variables = {
                clean(
                    record.get("name")
                )
                for record
                in json_records
                if clean(
                    record.get("name")
                )
            }

            metadata_data_files = {
                extract_data_file(
                    record
                )
                for record
                in json_records
            }

            metadata_data_files.discard(
                ""
            )

            if json_ids != jsonl_ids:

                errors.append(
                    f"{visit}: JSON and "
                    f"JSONL identities differ"
                )

            expected_unique = (
                EXPECTED[
                    visit
                ]["unique_variables"]
            )

            if (
                len(unique_variables)
                != expected_unique
            ):

                errors.append(
                    f"{visit}: expected "
                    f"{expected_unique} "
                    f"unique variables, "
                    f"found "
                    f"{len(unique_variables)}"
                )

            packages[visit] = {
                "records":
                    json_records,

                "data_files":
                    sorted(
                        metadata_data_files
                    ),

                "paths": {
                    "json":
                        json_path,

                    "jsonl":
                        jsonl_path,

                    "summary":
                        csv_path,
                },
            }

            print(
                f"{visit.upper():8s} "
                f"JSON="
                f"{len(json_records)} | "
                f"JSONL="
                f"{len(jsonl_records)} | "
                f"summary="
                f"{summary_rows} | "
                f"unique vars="
                f"{len(unique_variables)} | "
                f"data files="
                f"{len(metadata_data_files)}"
            )

            print(
                f"          JSON    : "
                f"{json_path}"
            )

            print(
                f"          JSONL   : "
                f"{jsonl_path}"
            )

            print(
                f"          SUMMARY : "
                f"{csv_path}"
            )

            for (
                metadata_type,
                path,
                records,
            ) in [
                (
                    "JSON",
                    json_path,
                    len(json_records),
                ),
                (
                    "JSONL",
                    jsonl_path,
                    len(jsonl_records),
                ),
                (
                    "SUMMARY",
                    csv_path,
                    summary_rows,
                ),
            ]:

                inventory.append({
                    "visit": visit,
                    "metadata_type":
                        metadata_type,

                    "file_name":
                        path.name,

                    "path":
                        str(path),

                    "records":
                        records,

                    "status":
                        "PASS",
                })

        except Exception as exc:

            errors.append(
                f"{visit}: metadata "
                f"audit failed: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            print(
                f"{visit.upper():8s} "
                f"FAIL | {exc}"
            )

    return (
        packages,
        inventory,
    )


# =============================================================================
# IDENTIFICATION FILE
# =============================================================================


def find_identification_file(
    visit,
    inventory,
):

    candidates = [
        record
        for record
        in inventory
        if (
            record["visit"]
            == visit
            and
            record["status"]
            == "PASS"
        )
    ]

    if visit == "visit1":

        matches = [
            record
            for record
            in candidates
            if (
                "block 12_identification "
                "of sample household"
                in
                record[
                    "file_name"
                ].lower()
            )
        ]

    else:

        matches = [
            record
            for record
            in candidates
            if (
                "block 1&2_identification "
                "of sample household"
                in
                record[
                    "file_name"
                ].lower()
            )
        ]

    if len(matches) == 1:
        return matches[0]

    matches = [
        record
        for record
        in candidates
        if (
            "identification of "
            "sample household"
            in
            record[
                "file_name"
            ].lower()
        )
    ]

    if len(matches) == 1:
        return matches[0]

    return None


def iterate_identification(
    selected,
):

    import openpyxl

    path = selected[
        "_path"
    ]

    workbook = (
        openpyxl.load_workbook(
            path,
            read_only=True,
            data_only=True,
        )
    )

    sheet_name = (
        selected["sheet"]
    )

    worksheet = (
        workbook[
            sheet_name
        ]
    )

    try:
        worksheet.reset_dimensions()
    except Exception:
        pass

    header_row = (
        int(
            selected[
                "header_row"
            ]
        )
    )

    canonical = (
        selected[
            "_canonical"
        ]
    )

    iterator = (
        worksheet.iter_rows(
            values_only=True
        )
    )

    headers = None

    for row_number, row in enumerate(
        iterator,
        start=1,
    ):

        if row_number < header_row:
            continue

        if row_number == header_row:

            headers = [
                clean(value)
                for value in row
            ]

            while (
                headers
                and headers[-1] == ""
            ):
                headers.pop()

            break

    if headers is None:

        workbook.close()

        raise RuntimeError(
            "Header row could not be read"
        )

    index_map = {
        header: index
        for index, header
        in enumerate(headers)
    }

    for row in iterator:

        if not row_has_data(
            row
        ):
            continue

        output = {}

        for canonical_name, actual_name in (
            canonical.items()
        ):

            index = (
                index_map.get(
                    actual_name
                )
            )

            if (
                index is not None
                and
                index < len(row)
            ):

                output[
                    canonical_name
                ] = row[index]

            else:

                output[
                    canonical_name
                ] = None

        yield output

    workbook.close()


def audit_households(
    visit,
    inventory,
):

    selected = (
        find_identification_file(
            visit,
            inventory,
        )
    )

    if selected is None:

        errors.append(
            f"{visit}: real "
            f"identification file "
            f"not found"
        )

        return None

    print(
        f"\n[3] "
        f"{visit.upper()} "
        f"household universe"
    )

    print(
        f"Identification file        : "
        f"{selected['file_name']}"
    )

    print(
        f"Worksheet                  : "
        f"{selected['sheet']}"
    )

    canonical = (
        selected[
            "_canonical"
        ]
    )

    required = {
        "HHID",
        "Visit_no",
        "Sector",
        "State",
        "Weight_SC",
    }

    missing = (
        required
        - set(canonical)
    )

    if (
        "District_id"
        not in canonical
        and
        "State_District"
        not in canonical
    ):

        missing.add(
            "District"
        )

    if missing:

        errors.append(
            f"{visit}: "
            f"identification "
            f"missing fields: "
            f"{sorted(missing)}"
        )

    hhids = set()

    rows = 0
    blanks = 0
    duplicates = 0
    invalid_weights = 0

    visits = Counter()
    sectors = Counter()

    states = set()
    state_districts = set()

    for row in (
        iterate_identification(
            selected
        )
    ):

        rows += 1

        hhid = clean(
            row.get("HHID")
        )

        if not hhid:

            blanks += 1

        elif hhid in hhids:

            duplicates += 1

        else:

            hhids.add(
                hhid
            )

        visit_no = clean(
            row.get(
                "Visit_no"
            )
        )

        if visit_no:

            visits[
                visit_no
            ] += 1

        sector = clean(
            row.get(
                "Sector"
            )
        )

        if sector:

            sectors[
                sector
            ] += 1

        state = clean(
            row.get(
                "State"
            )
        )

        district = clean(
            row.get(
                "District_id"
            )
        )

        state_district = clean(
            row.get(
                "State_District"
            )
        )

        if state:
            states.add(
                state
            )

        if state_district:

            state_districts.add(
                state_district
            )

        elif (
            state
            and district
        ):

            state_districts.add(
                f"{state}:{district}"
            )

        try:

            weight = float(
                row.get(
                    "Weight_SC"
                )
            )

            if weight <= 0:
                invalid_weights += 1

        except Exception:

            invalid_weights += 1

    expected = (
        EXPECTED[
            visit
        ]
    )

    if (
        rows
        != expected["households"]
    ):

        errors.append(
            f"{visit}: expected "
            f"{expected['households']:,} "
            f"households, found "
            f"{rows:,}"
        )

    if duplicates:

        errors.append(
            f"{visit}: "
            f"{duplicates:,} "
            f"duplicate HHIDs"
        )

    if blanks:

        errors.append(
            f"{visit}: "
            f"{blanks:,} blank HHIDs"
        )

    if (
        set(visits)
        != {
            expected[
                "visit_no"
            ]
        }
    ):

        errors.append(
            f"{visit}: expected "
            f"Visit_no="
            f"{expected['visit_no']}; "
            f"found {dict(visits)}"
        )

    if invalid_weights:

        errors.append(
            f"{visit}: "
            f"{invalid_weights:,} "
            f"invalid Weight_SC"
        )

    print(
        f"Household rows             : "
        f"{rows:,}"
    )

    print(
        f"Unique HHID                : "
        f"{len(hhids):,}"
    )

    print(
        f"Blank HHID                 : "
        f"{blanks:,}"
    )

    print(
        f"Duplicate HHID             : "
        f"{duplicates:,}"
    )

    print(
        f"Visit_no values            : "
        f"{dict(visits)}"
    )

    print(
        f"Sector values              : "
        f"{dict(sectors)}"
    )

    print(
        f"Observed states/UTs        : "
        f"{len(states)}"
    )

    print(
        f"Observed State-Districts   : "
        f"{len(state_districts)}"
    )

    print(
        f"Invalid Weight_SC          : "
        f"{invalid_weights:,}"
    )

    return {
        "visit":
            visit,

        "identification_file":
            selected["file_name"],

        "rows":
            rows,

        "unique_hhid":
            len(hhids),

        "blank_hhid":
            blanks,

        "duplicate_hhid":
            duplicates,

        "visit_values":
            "|".join(
                sorted(visits)
            ),

        "sector_values":
            "|".join(
                sorted(sectors)
            ),

        "states":
            len(states),

        "state_districts":
            len(state_districts),

        "invalid_weight_sc":
            invalid_weights,

        "has_NSS":
            int(
                "NSS"
                in canonical
            ),

        "has_NSC":
            int(
                "NSC"
                in canonical
            ),

        "has_MLT":
            int(
                "MLT"
                in canonical
            ),

        "has_Weight_SS":
            int(
                "Weight_SS"
                in canonical
            ),

        "has_Weight_SC":
            int(
                "Weight_SC"
                in canonical
            ),

        "_hhids":
            hhids,
    }


# =============================================================================
# METADATA COVERAGE
# =============================================================================


def fuzzy_match(
    raw_name,
    metadata_names,
):

    raw_key = (
        re.sub(
            r"[^a-z0-9]",
            "",
            Path(
                raw_name
            ).stem.lower()
            .replace(
                "&",
                "and",
            ),
        )
    )

    best_name = ""
    best_score = 0.0

    for metadata_name in (
        metadata_names
    ):

        metadata_key = (
            re.sub(
                r"[^a-z0-9]",
                "",
                metadata_name
                .lower()
                .replace(
                    "&",
                    "and",
                ),
            )
        )

        if (
            raw_key
            == metadata_key
        ):

            return (
                metadata_name,
                1.0,
            )

        score = (
            SequenceMatcher(
                None,
                raw_key,
                metadata_key,
            ).ratio()
        )

        if score > best_score:

            best_score = score
            best_name = (
                metadata_name
            )

    if best_score >= 0.75:

        return (
            best_name,
            best_score,
        )

    return (
        "",
        best_score,
    )


def build_coverage(
    raw_inventory,
    metadata,
):

    print(
        "\n[4] Raw / metadata coverage"
    )

    rows = []

    for visit in [
        "visit1",
        "visit2",
    ]:

        if visit not in metadata:
            continue

        names = (
            metadata[
                visit
            ]["data_files"]
        )

        unresolved = []

        for raw in raw_inventory:

            if (
                raw["visit"]
                != visit
                or
                raw["status"]
                != "PASS"
            ):
                continue

            name, score = (
                fuzzy_match(
                    raw["file_name"],
                    names,
                )
            )

            status = (
                "MATCHED"
                if name
                else
                "UNRESOLVED"
            )

            rows.append({
                "visit":
                    visit,

                "raw_file":
                    raw["file_name"],

                "metadata_data_file":
                    name,

                "match_score":
                    f"{score:.6f}",

                "status":
                    status,
            })

            if not name:

                unresolved.append(
                    raw["file_name"]
                )

        print(
            f"{visit.upper():8s} "
            f"metadata files : "
            f"{len(names)}"
        )

        print(
            f"{visit.upper():8s} "
            f"unresolved raw : "
            f"{len(unresolved)}"
        )

        for name in unresolved:

            compact = (
                normalize_field(
                    name
                )
            )

            if (
                visit == "visit1"
                and
                "block16"
                in compact
            ):

                warnings.append(
                    "Visit 1 Block 16 "
                    "metadata gap retained "
                    "for Step 01B resolution."
                )

            else:

                warnings.append(
                    f"{visit}: "
                    f"metadata match "
                    f"unresolved for "
                    f"{name}"
                )

    return rows


# =============================================================================
# CSV OUTPUT
# =============================================================================


def write_csv(
    path,
    rows,
    fields,
):

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as fh:

        writer = csv.DictWriter(
            fh,
            fieldnames=fields,
            extrasaction="ignore",
        )

        writer.writeheader()

        writer.writerows(
            rows
        )


# =============================================================================
# MAIN
# =============================================================================


def main():

    print(
        "=" * 78
    )

    print(
        "AIDIS 2013 - STEP 01 V2 "
        "PRODUCTION INPUT AUDIT + LOCK"
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

    # -----------------------------------------------------------------
    # RAW
    # -----------------------------------------------------------------

    raw_inventory = (
        build_raw_inventory()
    )

    # -----------------------------------------------------------------
    # METADATA
    # -----------------------------------------------------------------

    (
        metadata,
        metadata_inventory,
    ) = audit_metadata()

    # -----------------------------------------------------------------
    # HOUSEHOLDS
    # -----------------------------------------------------------------

    household_results = {}
    household_rows = []

    for visit in [
        "visit1",
        "visit2",
    ]:

        result = (
            audit_households(
                visit,
                raw_inventory,
            )
        )

        if result:

            household_results[
                visit
            ] = result

            household_rows.append({
                key: value
                for key, value
                in result.items()
                if not key.startswith(
                    "_"
                )
            })

    # -----------------------------------------------------------------
    # CROSS VISIT
    # -----------------------------------------------------------------

    print(
        "\n[4A] Cross-visit "
        "household audit"
    )

    cross_rows = []

    if (
        "visit1"
        in household_results
        and
        "visit2"
        in household_results
    ):

        visit1_hh = (
            household_results[
                "visit1"
            ]["_hhids"]
        )

        visit2_hh = (
            household_results[
                "visit2"
            ]["_hhids"]
        )

        overlap = (
            visit1_hh
            & visit2_hh
        )

        visit1_only = (
            visit1_hh
            - visit2_hh
        )

        visit2_only = (
            visit2_hh
            - visit1_hh
        )

        metrics = [
            (
                "Visit 1 HHIDs",
                len(visit1_hh),
            ),
            (
                "Visit 2 HHIDs",
                len(visit2_hh),
            ),
            (
                "Exact HHID overlap",
                len(overlap),
            ),
            (
                "Visit 1 only",
                len(visit1_only),
            ),
            (
                "Visit 2 only",
                len(visit2_only),
            ),
        ]

        for label, value in metrics:

            print(
                f"{label:26s}: "
                f"{value:,}"
            )

            cross_rows.append({
                "metric":
                    label,

                "value":
                    value,

                "status":
                    "INFO",
            })

        warnings.append(
            "Exact Visit1/Visit2 HHID "
            "overlap is informational. "
            "Formal panel methodology "
            "will be locked later."
        )

    # -----------------------------------------------------------------
    # COVERAGE
    # -----------------------------------------------------------------

    coverage_rows = (
        build_coverage(
            raw_inventory,
            metadata,
        )
    )

    # -----------------------------------------------------------------
    # WRITE AUDITS
    # -----------------------------------------------------------------

    raw_public = [
        {
            key: value
            for key, value
            in row.items()
            if not key.startswith(
                "_"
            )
        }
        for row in raw_inventory
    ]

    write_csv(
        RAW_INVENTORY_FILE,
        raw_public,
        [
            "visit",
            "relative_path",
            "file_name",
            "extension",
            "size_bytes",
            "row_count",
            "column_count",
            "sheet",
            "header_row",
            "encoding",
            "delimiter",
            "has_HHID",
            "has_Visit_no",
            "has_Sector",
            "has_State",
            "has_District",
            "has_MLT",
            "has_NSS",
            "has_NSC",
            "has_Weight_SS",
            "has_Weight_SC",
            "status",
            "error",
        ],
    )

    write_csv(
        METADATA_INVENTORY_FILE,
        metadata_inventory,
        [
            "visit",
            "metadata_type",
            "file_name",
            "path",
            "records",
            "status",
        ],
    )

    write_csv(
        HOUSEHOLD_UNIVERSE_FILE,
        household_rows,
        [
            "visit",
            "identification_file",
            "rows",
            "unique_hhid",
            "blank_hhid",
            "duplicate_hhid",
            "visit_values",
            "sector_values",
            "states",
            "state_districts",
            "invalid_weight_sc",
            "has_NSS",
            "has_NSC",
            "has_MLT",
            "has_Weight_SS",
            "has_Weight_SC",
        ],
    )

    write_csv(
        CROSS_VISIT_FILE,
        cross_rows,
        [
            "metric",
            "value",
            "status",
        ],
    )

    write_csv(
        COVERAGE_FILE,
        coverage_rows,
        [
            "visit",
            "raw_file",
            "metadata_data_file",
            "match_score",
            "status",
        ],
    )

    # -----------------------------------------------------------------
    # LOCK STATUS
    # -----------------------------------------------------------------

    status = (
        "PASS"
        if not errors
        else
        "FAIL"
    )

    lock_status = (
        "LOCKED"
        if status == "PASS"
        else
        "DRAFT_NOT_LOCKED"
    )

    # -----------------------------------------------------------------
    # MANIFEST
    # -----------------------------------------------------------------

    print(
        "\n[5] Production manifest + SHA256"
    )

    manifest_rows = []

    raw_number = 0

    for record in raw_inventory:

        if record["status"] != "PASS":
            continue

        raw_number += 1

        path = record[
            "_path"
        ]

        print(
            f"Hashing raw "
            f"{raw_number:02d}: "
            f"{path.name}"
        )

        manifest_rows.append({
            "kind":
                "RAW",

            "visit":
                record["visit"],

            "file_name":
                path.name,

            "path":
                str(path),

            "size_bytes":
                path.stat().st_size,

            "row_count":
                record["row_count"],

            "column_count":
                record["column_count"],

            "sha256":
                sha256_file(
                    path
                ),

            "lock_status":
                lock_status,
        })

    for visit in [
        "visit1",
        "visit2",
    ]:

        if visit not in metadata:
            continue

        for kind, path in (
            metadata[
                visit
            ]["paths"].items()
        ):

            print(
                f"Hashing metadata: "
                f"{path.name}"
            )

            manifest_rows.append({
                "kind":
                    "METADATA_"
                    + kind.upper(),

                "visit":
                    visit,

                "file_name":
                    path.name,

                "path":
                    str(path),

                "size_bytes":
                    path.stat().st_size,

                "row_count":
                    "",

                "column_count":
                    "",

                "sha256":
                    sha256_file(
                        path
                    ),

                "lock_status":
                    lock_status,
            })

    write_csv(
        MANIFEST_FILE,
        manifest_rows,
        [
            "kind",
            "visit",
            "file_name",
            "path",
            "size_bytes",
            "row_count",
            "column_count",
            "sha256",
            "lock_status",
        ],
    )

    # -----------------------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------------------

    visit1_files = sum(
        1
        for row in raw_inventory
        if row["visit"]
        == "visit1"
    )

    visit2_files = sum(
        1
        for row in raw_inventory
        if row["visit"]
        == "visit2"
    )

    visit1_hh = (
        household_results
        .get(
            "visit1",
            {},
        )
        .get(
            "rows",
            0,
        )
    )

    visit2_hh = (
        household_results
        .get(
            "visit2",
            {},
        )
        .get(
            "rows",
            0,
        )
    )

    lines = [
        "=" * 78,
        "AIDIS 2013 - STEP 01 V2 "
        "PRODUCTION INPUT LOCK SUMMARY",
        "=" * 78,
        "",
        f"Project root              : "
        f"{PROJECT_ROOT}",
        "",
        f"Visit 1 raw datasets      : "
        f"{visit1_files}",
        f"Visit 2 raw datasets      : "
        f"{visit2_files}",
        f"Total raw datasets        : "
        f"{visit1_files + visit2_files}",
        "",
        f"Visit 1 households        : "
        f"{visit1_hh:,}",
        f"Visit 2 households        : "
        f"{visit2_hh:,}",
        "",
        f"Errors                    : "
        f"{len(errors)}",
        f"Warnings                  : "
        f"{len(warnings)}",
        f"Production lock           : "
        f"{lock_status}",
        "",
        f"Raw inventory             : "
        f"{RAW_INVENTORY_FILE}",
        f"Metadata inventory        : "
        f"{METADATA_INVENTORY_FILE}",
        f"Household universe        : "
        f"{HOUSEHOLD_UNIVERSE_FILE}",
        f"Cross-visit audit         : "
        f"{CROSS_VISIT_FILE}",
        f"Metadata/raw coverage     : "
        f"{COVERAGE_FILE}",
        f"Production manifest       : "
        f"{MANIFEST_FILE}",
        "",
    ]

    if warnings:

        lines.append(
            "WARNINGS:"
        )

        for warning in warnings:

            lines.append(
                f"  - {warning}"
            )

        lines.append(
            ""
        )

    if errors:

        lines.append(
            "ERRORS:"
        )

        for error in errors:

            lines.append(
                f"  - {error}"
            )

        lines.append(
            ""
        )

    lines.extend([
        f"STEP 01 STATUS: "
        f"{status}",
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

    if status != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()