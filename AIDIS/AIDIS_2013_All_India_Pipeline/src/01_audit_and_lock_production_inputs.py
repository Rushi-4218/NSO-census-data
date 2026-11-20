from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher


# =============================================================================
# AIDIS 2013 - STEP 01
# PRODUCTION INPUT AUDIT + LOCK
# =============================================================================

PROJECT_ROOT = Path(r"D:\AIDIS\AIDIS_2013_All_India_Pipeline")

RAW_ROOTS = {
    "visit1": PROJECT_ROOT / "input" / "raw" / "visit1"
    / "Debt & Investment, NSS 70th Round Visit-1 Jan - Dec 2013",

    "visit2": PROJECT_ROOT / "input" / "raw" / "visit2"
    / "Debt & Investment Visit 2 , Jan - Dec 2013",
}

META_ROOTS = {
    "visit1": PROJECT_ROOT / "input" / "metadata" / "visit1",
    "visit2": PROJECT_ROOT / "input" / "metadata" / "visit2",
}

META_FILES = {
    "visit1": {
        "json": "all_variables(2).json",
        "jsonl": "variables(2).jsonl",
        "summary": "variables_summary(2).csv",
    },
    "visit2": {
        "json": "all_variables(1).json",
        "jsonl": "variables(1).jsonl",
        "summary": "variables_summary(1).csv",
    },
}

EXPECTED = {
    "visit1": {
        "raw_datasets": 18,
        "metadata_records": 519,
        "unique_variables": 129,
        "households": 110800,
        "visit_no": "1",
    },
    "visit2": {
        "raw_datasets": 6,
        "metadata_records": 211,
        "unique_variables": 80,
        "households": 108425,
        "visit_no": "2",
    },
}

CACHE_DIR = PROJECT_ROOT / "cache"
WORK_DIR = PROJECT_ROOT / "work"
REPORT_DIR = PROJECT_ROOT / "output" / "reports"
LOG_DIR = PROJECT_ROOT / "logs"

for folder in [CACHE_DIR, WORK_DIR, REPORT_DIR, LOG_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


RAW_INVENTORY_FILE = CACHE_DIR / "step01_raw_inventory.csv"
METADATA_INVENTORY_FILE = CACHE_DIR / "step01_metadata_inventory.csv"
HOUSEHOLD_UNIVERSE_FILE = CACHE_DIR / "step01_household_universe.csv"
CROSS_VISIT_FILE = CACHE_DIR / "step01_cross_visit_audit.csv"
COVERAGE_FILE = CACHE_DIR / "step01_metadata_raw_coverage.csv"
MANIFEST_FILE = CACHE_DIR / "step01_production_manifest.csv"

SUMMARY_FILE = REPORT_DIR / "step01_production_lock_summary.txt"


# =============================================================================
# SETTINGS
# =============================================================================

TABULAR_EXTENSIONS = {
    ".csv",
    ".txt",
    ".tsv",
    ".xlsx",
    ".xls",
}

TEXT_ENCODINGS = [
    "utf-8-sig",
    "utf-8",
    "cp1252",
    "latin1",
]

DELIMITERS = [",", "\t", ";", "|"]

errors = []
warnings = []


# =============================================================================
# HELPERS
# =============================================================================

def normalize_scalar(value):
    if value is None:
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def normalize_field(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


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
    "State_Region": {
        "stateregion",
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


def canonical_header_map(headers):
    normalized_to_actual = {}

    for header in headers:
        h = normalize_field(header)

        if h and h not in normalized_to_actual:
            normalized_to_actual[h] = header

    result = {}

    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized_to_actual:
                result[canonical] = normalized_to_actual[alias]
                break

    return result


def dataset_key(value):
    value = Path(str(value)).stem.lower()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9]", "", value)
    return value


def sha256_file(path, block_size=1024 * 1024):
    h = hashlib.sha256()

    with path.open("rb") as fh:
        while True:
            block = fh.read(block_size)

            if not block:
                break

            h.update(block)

    return h.hexdigest()


def choose_text_format(path):
    raw = path.open("rb").read(131072)

    selected_encoding = None
    sample = None

    for encoding in TEXT_ENCODINGS:
        try:
            sample = raw.decode(encoding)
            selected_encoding = encoding
            break
        except UnicodeDecodeError:
            continue

    if selected_encoding is None:
        selected_encoding = "latin1"
        sample = raw.decode("latin1")

    if path.suffix.lower() == ".tsv":
        delimiter = "\t"
    else:
        try:
            dialect = csv.Sniffer().sniff(
                sample,
                delimiters="".join(DELIMITERS)
            )
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ","

    return selected_encoding, delimiter


def inspect_delimited(path):
    encoding, delimiter = choose_text_format(path)

    with path.open(
        "r",
        encoding=encoding,
        errors="replace",
        newline=""
    ) as fh:

        reader = csv.reader(fh, delimiter=delimiter)

        try:
            headers = next(reader)
        except StopIteration:
            return {
                "rows": 0,
                "cols": 0,
                "headers": [],
                "encoding": encoding,
                "delimiter": delimiter,
            }

        headers = [
            normalize_scalar(h)
            for h in headers
        ]

        row_count = 0

        for _ in reader:
            row_count += 1

    return {
        "rows": row_count,
        "cols": len(headers),
        "headers": headers,
        "encoding": encoding,
        "delimiter": delimiter,
    }


def inspect_xlsx(path):
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required to inspect XLSX files"
        ) from exc

    wb = openpyxl.load_workbook(
        path,
        read_only=True,
        data_only=True,
    )

    selected_ws = None

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]

        if ws.max_row and ws.max_column:
            selected_ws = ws
            break

    if selected_ws is None:
        wb.close()

        return {
            "rows": 0,
            "cols": 0,
            "headers": [],
            "encoding": "",
            "delimiter": "",
        }

    iterator = selected_ws.iter_rows(values_only=True)

    try:
        first_row = next(iterator)
    except StopIteration:
        wb.close()

        return {
            "rows": 0,
            "cols": 0,
            "headers": [],
            "encoding": "",
            "delimiter": "",
        }

    headers = [
        normalize_scalar(v)
        for v in first_row
    ]

    row_count = 0

    for row in iterator:
        if any(v is not None and str(v).strip() != "" for v in row):
            row_count += 1

    wb.close()

    return {
        "rows": row_count,
        "cols": len(headers),
        "headers": headers,
        "encoding": "",
        "delimiter": "",
    }


def inspect_xls(path):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError(
            "pandas is required to inspect old XLS files"
        ) from exc

    df = pd.read_excel(path)

    return {
        "rows": len(df),
        "cols": len(df.columns),
        "headers": [str(c) for c in df.columns],
        "encoding": "",
        "delimiter": "",
    }


def inspect_tabular(path):
    suffix = path.suffix.lower()

    if suffix in {".csv", ".txt", ".tsv"}:
        return inspect_delimited(path)

    if suffix == ".xlsx":
        return inspect_xlsx(path)

    if suffix == ".xls":
        return inspect_xls(path)

    raise ValueError(
        f"Unsupported tabular extension: {suffix}"
    )


def get_metadata_path(visit, filename):
    preferred = META_ROOTS[visit] / filename

    if preferred.exists():
        return preferred

    search_root = PROJECT_ROOT / "input" / "metadata"

    matches = list(search_root.rglob(filename))

    if len(matches) == 1:
        return matches[0]

    raise FileNotFoundError(
        f"Could not uniquely locate metadata file: {filename}"
    )


def read_json(path):
    with path.open("r", encoding="utf-8-sig") as fh:
        value = json.load(fh)

    if not isinstance(value, list):
        raise ValueError(
            f"{path.name} is not a JSON list"
        )

    return value


def read_jsonl(path):
    records = []

    with path.open(
        "r",
        encoding="utf-8-sig"
    ) as fh:

        for line_no, line in enumerate(fh, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                records.append(json.loads(line))
            except Exception as exc:
                raise ValueError(
                    f"Invalid JSONL at line {line_no}: {exc}"
                )

    return records


def metadata_identity(record):
    return (
        normalize_scalar(record.get("file")),
        normalize_scalar(record.get("name")),
        normalize_scalar(record.get("url")),
    )


def extract_metadata_data_file(record):
    raw_text = str(
        record.get("raw_text") or ""
    )

    match = re.search(
        r"Data file:\s*(.*?)\r?\nOverview",
        raw_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if match:
        value = match.group(1)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    data_file = normalize_scalar(
        record.get("data_file")
    )

    if data_file.lower() not in {"", "visit"}:
        return data_file

    return ""


def metadata_summary_count(path):
    result = inspect_delimited(path)
    return result["rows"], result["headers"]


def fuzzy_dataset_match(raw_name, metadata_names):
    raw_key = dataset_key(raw_name)

    best_name = ""
    best_score = 0.0

    for metadata_name in metadata_names:
        metadata_key = dataset_key(metadata_name)

        if not raw_key or not metadata_key:
            continue

        if raw_key == metadata_key:
            return metadata_name, 1.0

        if (
            raw_key in metadata_key
            or metadata_key in raw_key
        ):
            score = (
                min(len(raw_key), len(metadata_key))
                / max(len(raw_key), len(metadata_key))
            )
        else:
            score = SequenceMatcher(
                None,
                raw_key,
                metadata_key,
            ).ratio()

        if score > best_score:
            best_name = metadata_name
            best_score = score

    if best_score >= 0.82:
        return best_name, best_score

    return "", best_score


# =============================================================================
# RAW INVENTORY
# =============================================================================

def build_raw_inventory():
    print("\n[1] Raw production file inventory")

    inventory = []

    for visit in ["visit1", "visit2"]:
        raw_root = RAW_ROOTS[visit]

        if not raw_root.exists():
            errors.append(
                f"{visit}: raw folder does not exist: {raw_root}"
            )
            continue

        all_files = [
            p for p in raw_root.rglob("*")
            if p.is_file()
        ]

        tabular_files = [
            p for p in all_files
            if p.suffix.lower() in TABULAR_EXTENSIONS
        ]

        print(
            f"{visit.upper():8s} discovered tabular files : "
            f"{len(tabular_files)}"
        )

        expected_count = EXPECTED[visit]["raw_datasets"]

        if len(tabular_files) != expected_count:
            errors.append(
                f"{visit}: expected {expected_count} raw datasets, "
                f"found {len(tabular_files)}"
            )

        basename_counts = Counter(
            p.name.lower()
            for p in tabular_files
        )

        duplicate_names = [
            name
            for name, count in basename_counts.items()
            if count > 1
        ]

        if duplicate_names:
            errors.append(
                f"{visit}: duplicate raw filenames: "
                + ", ".join(duplicate_names)
            )

        for index, path in enumerate(
            sorted(tabular_files),
            start=1,
        ):
            try:
                info = inspect_tabular(path)

                canonical = canonical_header_map(
                    info["headers"]
                )

                status = "PASS"

                record = {
                    "_path": path,
                    "_canonical": canonical,

                    "visit": visit,
                    "relative_path": str(
                        path.relative_to(raw_root)
                    ),
                    "file_name": path.name,
                    "extension": path.suffix.lower(),
                    "size_bytes": path.stat().st_size,
                    "row_count": info["rows"],
                    "column_count": info["cols"],
                    "encoding": info["encoding"],
                    "delimiter": (
                        "\\t"
                        if info["delimiter"] == "\t"
                        else info["delimiter"]
                    ),
                    "has_HHID": int(
                        "HHID" in canonical
                    ),
                    "has_Visit_no": int(
                        "Visit_no" in canonical
                    ),
                    "has_Sector": int(
                        "Sector" in canonical
                    ),
                    "has_State": int(
                        "State" in canonical
                    ),
                    "has_District": int(
                        (
                            "District_id" in canonical
                            or "State_District" in canonical
                        )
                    ),
                    "has_MLT": int(
                        "MLT" in canonical
                    ),
                    "has_NSS": int(
                        "NSS" in canonical
                    ),
                    "has_NSC": int(
                        "NSC" in canonical
                    ),
                    "has_Weight_SS": int(
                        "Weight_SS" in canonical
                    ),
                    "has_Weight_SC": int(
                        "Weight_SC" in canonical
                    ),
                    "status": status,
                    "error": "",
                }

                inventory.append(record)

                print(
                    f"  [{index:02d}/{len(tabular_files):02d}] "
                    f"PASS | "
                    f"rows={info['rows']:>10,} | "
                    f"cols={info['cols']:>3} | "
                    f"{path.name}"
                )

            except Exception as exc:
                errors.append(
                    f"{visit}: unreadable raw file "
                    f"{path.name}: {type(exc).__name__}: {exc}"
                )

                inventory.append({
                    "_path": path,
                    "_canonical": {},

                    "visit": visit,
                    "relative_path": str(
                        path.relative_to(raw_root)
                    ),
                    "file_name": path.name,
                    "extension": path.suffix.lower(),
                    "size_bytes": path.stat().st_size,
                    "row_count": 0,
                    "column_count": 0,
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
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                })

                print(
                    f"  [{index:02d}/{len(tabular_files):02d}] "
                    f"FAIL | {path.name}"
                )

    return inventory


# =============================================================================
# METADATA AUDIT
# =============================================================================

def audit_metadata():
    print("\n[2] Metadata package consistency")

    metadata_by_visit = {}
    inventory_rows = []

    for visit in ["visit1", "visit2"]:
        try:
            json_path = get_metadata_path(
                visit,
                META_FILES[visit]["json"]
            )
            jsonl_path = get_metadata_path(
                visit,
                META_FILES[visit]["jsonl"]
            )
            summary_path = get_metadata_path(
                visit,
                META_FILES[visit]["summary"]
            )

            json_records = read_json(json_path)
            jsonl_records = read_jsonl(jsonl_path)

            summary_count, summary_headers = (
                metadata_summary_count(summary_path)
            )

            json_ids = {
                metadata_identity(r)
                for r in json_records
            }

            jsonl_ids = {
                metadata_identity(r)
                for r in jsonl_records
            }

            unique_variables = {
                normalize_scalar(r.get("name"))
                for r in json_records
                if normalize_scalar(r.get("name"))
            }

            data_files = {
                extract_metadata_data_file(r)
                for r in json_records
            }

            data_files.discard("")

            expected_records = (
                EXPECTED[visit]["metadata_records"]
            )

            expected_unique = (
                EXPECTED[visit]["unique_variables"]
            )

            if len(json_records) != expected_records:
                errors.append(
                    f"{visit}: JSON metadata expected "
                    f"{expected_records} records, "
                    f"found {len(json_records)}"
                )

            if len(jsonl_records) != expected_records:
                errors.append(
                    f"{visit}: JSONL metadata expected "
                    f"{expected_records} records, "
                    f"found {len(jsonl_records)}"
                )

            if summary_count != expected_records:
                errors.append(
                    f"{visit}: summary metadata expected "
                    f"{expected_records} rows, "
                    f"found {summary_count}"
                )

            if json_ids != jsonl_ids:
                errors.append(
                    f"{visit}: JSON and JSONL record "
                    f"identities do not match"
                )

            if len(unique_variables) != expected_unique:
                warnings.append(
                    f"{visit}: expected approximately "
                    f"{expected_unique} unique variable names; "
                    f"found {len(unique_variables)}"
                )

            metadata_by_visit[visit] = {
                "records": json_records,
                "data_files": sorted(data_files),
                "paths": {
                    "json": json_path,
                    "jsonl": jsonl_path,
                    "summary": summary_path,
                },
            }

            print(
                f"{visit.upper():8s} "
                f"JSON={len(json_records):>4} | "
                f"JSONL={len(jsonl_records):>4} | "
                f"summary={summary_count:>4} | "
                f"unique vars={len(unique_variables):>3} | "
                f"metadata data files={len(data_files):>2}"
            )

            for kind, path, count in [
                ("JSON", json_path, len(json_records)),
                ("JSONL", jsonl_path, len(jsonl_records)),
                ("SUMMARY", summary_path, summary_count),
            ]:
                inventory_rows.append({
                    "visit": visit,
                    "metadata_type": kind,
                    "file_name": path.name,
                    "path": str(path),
                    "records": count,
                    "status": "PASS",
                })

        except Exception as exc:
            errors.append(
                f"{visit}: metadata audit failed: "
                f"{type(exc).__name__}: {exc}"
            )

            print(
                f"{visit.upper():8s} FAIL | {exc}"
            )

    return metadata_by_visit, inventory_rows


# =============================================================================
# IDENTIFICATION FILE
# =============================================================================

def select_identification_file(
    visit,
    raw_inventory,
):
    expected_rows = EXPECTED[visit]["households"]

    candidates = []

    for row in raw_inventory:
        if row["visit"] != visit:
            continue

        if row["status"] != "PASS":
            continue

        canonical = row["_canonical"]

        if "HHID" not in canonical:
            continue

        score = 0

        name = row["file_name"].lower()

        if "identification" in name:
            score += 100

        if row["row_count"] == expected_rows:
            score += 80

        for field in [
            "Visit_no",
            "Sector",
            "State",
            "Weight_SC",
        ]:
            if field in canonical:
                score += 10

        if (
            "District_id" in canonical
            or "State_District" in canonical
        ):
            score += 10

        candidates.append(
            (score, row)
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    return candidates[0][1]


def iter_selected_records(path, canonical_map):
    suffix = path.suffix.lower()

    wanted = {
        canonical: actual
        for canonical, actual in canonical_map.items()
    }

    if suffix in {".csv", ".txt", ".tsv"}:
        encoding, delimiter = choose_text_format(path)

        with path.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline=""
        ) as fh:

            reader = csv.DictReader(
                fh,
                delimiter=delimiter,
            )

            for source_row in reader:
                yield {
                    canonical: source_row.get(actual)
                    for canonical, actual in wanted.items()
                }

        return

    if suffix == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(
            path,
            read_only=True,
            data_only=True,
        )

        ws = wb[wb.sheetnames[0]]

        iterator = ws.iter_rows(
            values_only=True
        )

        headers = [
            normalize_scalar(v)
            for v in next(iterator)
        ]

        index_lookup = {
            header: index
            for index, header in enumerate(headers)
        }

        for values in iterator:
            row = {}

            for canonical, actual in wanted.items():
                idx = index_lookup.get(actual)

                row[canonical] = (
                    values[idx]
                    if idx is not None and idx < len(values)
                    else None
                )

            yield row

        wb.close()
        return

    if suffix == ".xls":
        import pandas as pd

        df = pd.read_excel(
            path,
            usecols=list(wanted.values())
        )

        reverse = {
            actual: canonical
            for canonical, actual in wanted.items()
        }

        df.rename(
            columns=reverse,
            inplace=True,
        )

        for row in df.to_dict("records"):
            yield row

        return

    raise ValueError(
        f"Unsupported identification file type: {suffix}"
    )


def audit_identification(
    visit,
    raw_inventory,
):
    selected = select_identification_file(
        visit,
        raw_inventory,
    )

    if selected is None:
        errors.append(
            f"{visit}: could not locate identification file"
        )
        return None

    path = selected["_path"]
    canonical = selected["_canonical"]

    print(
        f"\n[3] {visit.upper()} household universe"
    )
    print(
        f"Identification file        : {path.name}"
    )

    required = [
        "HHID",
        "Visit_no",
        "Sector",
        "State",
        "Weight_SC",
    ]

    missing_required = [
        field
        for field in required
        if field not in canonical
    ]

    if (
        "District_id" not in canonical
        and "State_District" not in canonical
    ):
        missing_required.append(
            "District_id/State_District"
        )

    if missing_required:
        errors.append(
            f"{visit}: identification file missing: "
            + ", ".join(missing_required)
        )

    hhids = set()

    rows = 0
    blank_hhid = 0
    duplicate_hhid = 0
    invalid_weight = 0

    visits = Counter()
    sectors = Counter()
    states = set()
    state_districts = set()

    for row in iter_selected_records(
        path,
        canonical,
    ):
        rows += 1

        hhid = normalize_scalar(
            row.get("HHID")
        )

        if not hhid:
            blank_hhid += 1
        elif hhid in hhids:
            duplicate_hhid += 1
        else:
            hhids.add(hhid)

        visit_no = normalize_scalar(
            row.get("Visit_no")
        )

        if visit_no:
            visits[visit_no] += 1

        sector = normalize_scalar(
            row.get("Sector")
        )

        if sector:
            sectors[sector] += 1

        state = normalize_scalar(
            row.get("State")
        )

        district = normalize_scalar(
            row.get("District_id")
        )

        state_district = normalize_scalar(
            row.get("State_District")
        )

        if state:
            states.add(state)

        if state_district:
            state_districts.add(
                state_district
            )
        elif state and district:
            state_districts.add(
                f"{state}:{district}"
            )

        weight_value = row.get(
            "Weight_SC"
        )

        try:
            weight = float(weight_value)

            if weight <= 0:
                invalid_weight += 1
        except Exception:
            invalid_weight += 1

    expected_rows = EXPECTED[visit]["households"]
    expected_visit = EXPECTED[visit]["visit_no"]

    if rows != expected_rows:
        errors.append(
            f"{visit}: household identification rows "
            f"expected {expected_rows:,}, found {rows:,}"
        )

    if blank_hhid:
        errors.append(
            f"{visit}: {blank_hhid:,} blank HHIDs"
        )

    if duplicate_hhid:
        errors.append(
            f"{visit}: {duplicate_hhid:,} duplicate HHIDs"
        )

    if set(visits.keys()) != {expected_visit}:
        errors.append(
            f"{visit}: expected Visit_no={expected_visit}; "
            f"found {dict(visits)}"
        )

    if invalid_weight:
        errors.append(
            f"{visit}: {invalid_weight:,} invalid/non-positive "
            f"Weight_SC values"
        )

    print(
        f"Household rows             : {rows:,}"
    )
    print(
        f"Unique HHID                : {len(hhids):,}"
    )
    print(
        f"Blank HHID                 : {blank_hhid:,}"
    )
    print(
        f"Duplicate HHID             : {duplicate_hhid:,}"
    )
    print(
        f"Visit_no values            : {dict(visits)}"
    )
    print(
        f"Sector values              : {dict(sectors)}"
    )
    print(
        f"Observed states/UTs        : {len(states)}"
    )
    print(
        f"Observed State-Districts   : {len(state_districts)}"
    )
    print(
        f"Invalid Weight_SC          : {invalid_weight:,}"
    )

    return {
        "visit": visit,
        "identification_file": path.name,
        "rows": rows,
        "unique_hhid": len(hhids),
        "blank_hhid": blank_hhid,
        "duplicate_hhid": duplicate_hhid,
        "visit_values": "|".join(
            sorted(visits.keys())
        ),
        "sector_values": "|".join(
            sorted(sectors.keys())
        ),
        "states": len(states),
        "state_districts": len(state_districts),
        "invalid_weight_sc": invalid_weight,
        "has_NSS": int(
            "NSS" in canonical
        ),
        "has_NSC": int(
            "NSC" in canonical
        ),
        "has_MLT": int(
            "MLT" in canonical
        ),
        "has_Weight_SS": int(
            "Weight_SS" in canonical
        ),
        "has_Weight_SC": int(
            "Weight_SC" in canonical
        ),
        "_hhids": hhids,
    }


# =============================================================================
# METADATA <> RAW COVERAGE
# =============================================================================

def build_metadata_raw_coverage(
    raw_inventory,
    metadata_by_visit,
):
    print("\n[4] Raw-header / metadata coverage")

    rows = []

    for visit in ["visit1", "visit2"]:
        metadata = metadata_by_visit.get(
            visit
        )

        if not metadata:
            continue

        metadata_names = metadata[
            "data_files"
        ]

        unmatched = []

        for raw in raw_inventory:
            if raw["visit"] != visit:
                continue

            if raw["status"] != "PASS":
                continue

            match_name, score = (
                fuzzy_dataset_match(
                    raw["file_name"],
                    metadata_names,
                )
            )

            if match_name:
                status = "MATCHED"
            else:
                status = "UNRESOLVED"
                unmatched.append(
                    raw["file_name"]
                )

            rows.append({
                "visit": visit,
                "raw_file": raw["file_name"],
                "metadata_data_file": match_name,
                "match_score": (
                    f"{score:.6f}"
                ),
                "status": status,
            })

        print(
            f"{visit.upper():8s} metadata data files : "
            f"{len(metadata_names)}"
        )
        print(
            f"{visit.upper():8s} unresolved raw files : "
            f"{len(unmatched)}"
        )

        for name in unmatched:
            normalized = dataset_key(name)

            if (
                visit == "visit1"
                and "block16" in normalized
            ):
                warnings.append(
                    f"{visit}: metadata coverage gap retained "
                    f"for raw dataset {name}; resolve in Step 01B "
                    f"from raw headers + official schedule."
                )
            else:
                warnings.append(
                    f"{visit}: raw dataset has no confident "
                    f"metadata data-file match: {name}"
                )

    return rows


# =============================================================================
# CSV WRITERS
# =============================================================================

def write_dict_csv(path, rows, fieldnames):
    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as fh:

        writer = csv.DictWriter(
            fh,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# MANIFEST
# =============================================================================

def build_manifest(
    raw_inventory,
    metadata_by_visit,
    lock_status,
):
    print("\n[5] Production manifest + SHA256")

    rows = []

    raw_number = 0

    for raw in raw_inventory:
        if raw["status"] != "PASS":
            continue

        raw_number += 1

        path = raw["_path"]

        print(
            f"Hashing raw {raw_number:02d}: {path.name}"
        )

        rows.append({
            "kind": "RAW",
            "visit": raw["visit"],
            "file_name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "row_count": raw["row_count"],
            "column_count": raw["column_count"],
            "sha256": sha256_file(path),
            "lock_status": lock_status,
        })

    for visit in ["visit1", "visit2"]:
        metadata = metadata_by_visit.get(
            visit
        )

        if not metadata:
            continue

        for kind, path in metadata[
            "paths"
        ].items():

            print(
                f"Hashing metadata: {path.name}"
            )

            rows.append({
                "kind": f"METADATA_{kind.upper()}",
                "visit": visit,
                "file_name": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "row_count": "",
                "column_count": "",
                "sha256": sha256_file(path),
                "lock_status": lock_status,
            })

    return rows


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 78)
    print("AIDIS 2013 - STEP 01 PRODUCTION INPUT AUDIT + LOCK")
    print("NSS 70th Round | Visit 1 + Visit 2")
    print("=" * 78)

    print(
        f"Project root              : {PROJECT_ROOT}"
    )

    raw_inventory = (
        build_raw_inventory()
    )

    metadata_by_visit, metadata_inventory = (
        audit_metadata()
    )

    household_rows = []
    id_results = {}

    for visit in ["visit1", "visit2"]:
        result = audit_identification(
            visit,
            raw_inventory,
        )

        if result:
            id_results[visit] = result

            household_rows.append({
                key: value
                for key, value in result.items()
                if not key.startswith("_")
            })

    # -------------------------------------------------------------------------
    # Cross-visit household audit
    # -------------------------------------------------------------------------

    print("\n[4A] Cross-visit household audit")

    cross_rows = []

    if (
        "visit1" in id_results
        and "visit2" in id_results
    ):
        visit1_hh = id_results[
            "visit1"
        ]["_hhids"]

        visit2_hh = id_results[
            "visit2"
        ]["_hhids"]

        exact_overlap = (
            visit1_hh & visit2_hh
        )

        visit1_only = (
            visit1_hh - visit2_hh
        )

        visit2_only = (
            visit2_hh - visit1_hh
        )

        print(
            f"Visit 1 HHIDs             : {len(visit1_hh):,}"
        )
        print(
            f"Visit 2 HHIDs             : {len(visit2_hh):,}"
        )
        print(
            f"Exact HHID overlap        : {len(exact_overlap):,}"
        )
        print(
            f"Visit 1 only              : {len(visit1_only):,}"
        )
        print(
            f"Visit 2 only              : {len(visit2_only):,}"
        )

        cross_rows.append({
            "metric": "Visit 1 HHIDs",
            "value": len(visit1_hh),
            "status": "INFO",
        })

        cross_rows.append({
            "metric": "Visit 2 HHIDs",
            "value": len(visit2_hh),
            "status": "INFO",
        })

        cross_rows.append({
            "metric": "Exact HHID overlap",
            "value": len(exact_overlap),
            "status": "INFO",
        })

        cross_rows.append({
            "metric": "Visit 1 only",
            "value": len(visit1_only),
            "status": "INFO",
        })

        cross_rows.append({
            "metric": "Visit 2 only",
            "value": len(visit2_only),
            "status": "INFO",
        })

        warnings.append(
            "Exact Visit1/Visit2 HHID overlap is informational only. "
            "The formal panel-key rule will be locked in Step 01C "
            "from the NSS 70th Round methodology; no 2003 panel-key "
            "rule is assumed."
        )

    coverage_rows = (
        build_metadata_raw_coverage(
            raw_inventory,
            metadata_by_visit,
        )
    )

    # -------------------------------------------------------------------------
    # Write audit outputs before final status
    # -------------------------------------------------------------------------

    raw_csv_rows = []

    for row in raw_inventory:
        raw_csv_rows.append({
            key: value
            for key, value in row.items()
            if not key.startswith("_")
        })

    raw_fields = [
        "visit",
        "relative_path",
        "file_name",
        "extension",
        "size_bytes",
        "row_count",
        "column_count",
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
    ]

    write_dict_csv(
        RAW_INVENTORY_FILE,
        raw_csv_rows,
        raw_fields,
    )

    write_dict_csv(
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

    write_dict_csv(
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

    write_dict_csv(
        CROSS_VISIT_FILE,
        cross_rows,
        [
            "metric",
            "value",
            "status",
        ],
    )

    write_dict_csv(
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

    # -------------------------------------------------------------------------
    # Final lock status
    # -------------------------------------------------------------------------

    status = (
        "PASS"
        if not errors
        else "FAIL"
    )

    lock_status = (
        "LOCKED"
        if status == "PASS"
        else "DRAFT_NOT_LOCKED"
    )

    manifest_rows = build_manifest(
        raw_inventory,
        metadata_by_visit,
        lock_status,
    )

    write_dict_csv(
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

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------

    visit1_raw = sum(
        1
        for row in raw_inventory
        if row["visit"] == "visit1"
    )

    visit2_raw = sum(
        1
        for row in raw_inventory
        if row["visit"] == "visit2"
    )

    visit1_hh = (
        id_results.get(
            "visit1",
            {}
        ).get(
            "rows",
            0
        )
    )

    visit2_hh = (
        id_results.get(
            "visit2",
            {}
        ).get(
            "rows",
            0
        )
    )

    summary_lines = [
        "=" * 78,
        "AIDIS 2013 - STEP 01 PRODUCTION INPUT LOCK SUMMARY",
        "=" * 78,
        "",
        f"Project root              : {PROJECT_ROOT}",
        "",
        f"Visit 1 raw datasets      : {visit1_raw}",
        f"Visit 2 raw datasets      : {visit2_raw}",
        f"Total raw datasets        : {visit1_raw + visit2_raw}",
        "",
        f"Visit 1 households        : {visit1_hh:,}",
        f"Visit 2 households        : {visit2_hh:,}",
        "",
        f"Errors                    : {len(errors)}",
        f"Warnings                  : {len(warnings)}",
        f"Production lock           : {lock_status}",
        "",
        f"Raw inventory             : {RAW_INVENTORY_FILE}",
        f"Metadata inventory        : {METADATA_INVENTORY_FILE}",
        f"Household universe        : {HOUSEHOLD_UNIVERSE_FILE}",
        f"Cross-visit audit         : {CROSS_VISIT_FILE}",
        f"Metadata/raw coverage     : {COVERAGE_FILE}",
        f"Production manifest       : {MANIFEST_FILE}",
        "",
    ]

    if warnings:
        summary_lines.append(
            "WARNINGS:"
        )

        for warning in warnings:
            summary_lines.append(
                f"  - {warning}"
            )

        summary_lines.append("")

    if errors:
        summary_lines.append(
            "ERRORS:"
        )

        for error in errors:
            summary_lines.append(
                f"  - {error}"
            )

        summary_lines.append("")

    summary_lines.extend([
        f"STEP 01 STATUS: {status}",
        "=" * 78,
    ])

    summary_text = "\n".join(
        summary_lines
    )

    SUMMARY_FILE.write_text(
        summary_text,
        encoding="utf-8",
    )

    print("\n" + summary_text)

    if status != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()