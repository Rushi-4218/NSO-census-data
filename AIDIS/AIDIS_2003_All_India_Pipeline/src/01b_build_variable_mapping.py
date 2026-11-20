from pathlib import Path
import csv
import json
import re
import sys
import unicodedata

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
CONFIG_DIR = ROOT / "config"
REPORT_DIR = ROOT / "output" / "reports"
METADATA_DIR = ROOT / "input" / "metadata"
REFERENCE_DIR = ROOT / "input" / "reference"

PRODUCTION_MANIFEST = CACHE_DIR / "step01_production_manifest.csv"
VARIABLES_JSON = METADATA_DIR / "all_variables.json"
VARIABLES_SUMMARY = METADATA_DIR / "variables_summary.csv"

HEADER_CATALOG = CACHE_DIR / "step01b_raw_header_catalog.csv"
VARIABLE_MAPPING = CACHE_DIR / "step01b_variable_mapping.csv"
UNRESOLVED_FILE = CACHE_DIR / "step01b_unresolved_variables.csv"
FILE_ROLES = CACHE_DIR / "step01b_file_roles.csv"
CONFIG_FILE = CONFIG_DIR / "aidis_2003_variable_map.json"
SUMMARY_FILE = REPORT_DIR / "step01b_mapping_summary.txt"

COMMON_LABELS = {
    "HHID": "Primary household identifier",
    "CentreCodeRndShift": "Centre code, round and shift",
    "Vill_Blk_Slno": "FSU / village-block serial number",
    "Round": "Survey round",
    "Schedule": "Schedule",
    "Sample": "Sample",
    "Sector": "Sector code",
    "State_Region": "State-region code",
    "State": "State code",
    "District": "District code",
    "Stratum": "Stratum",
    "SubRound": "Sub-round",
    "SubSample": "Sub-sample",
    "FOD_SubRegion": "FOD sub-region",
    "HG_SubBlkNo": "Hamlet-group / sub-block number",
    "Second_Stratum": "Second-stage stratum",
    "Visit_no": "Visit number",
    "Hhold_no": "Household number",
    "Level": "Data level",
    "NSS": "NSS sample design value",
    "NSC": "NSC sample design value",
    "MLT": "Multiplier",
    "Weight": "Weight",
}

METHOD_GATES = {
    "estimation_weight_choice": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Use MLT, Weight, or a survey-specific transformation for estimators?",
    },
    "visit_strategy": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Which KPIs use Visit 1 only versus Visit 1 & 2 Combined?",
    },
    "stock_reference_date": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Lock the official stock reference date for asset/liability estimates.",
    },
    "flow_reference_periods": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Lock reference periods for borrowing, repayment, expenditure and asset transactions.",
    },
    "geography_codebook_2003": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Lock NSS 59th Round state/district codes and names without modernising geography.",
    },
    "household_group_classification": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Lock cultivator/non-cultivator and urban self-employed/others definitions.",
    },
    "asset_formula": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Lock AVA component formulas against official Report 500/questionnaire.",
    },
    "debt_formula": {
        "status": "PENDING_OFFICIAL_CONFIRMATION",
        "question": "Lock AOD/AODL/IOI/DAR and agency/purpose/interest formulas.",
    },
}


def norm_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return re.sub(r"\s+", " ", text)


def norm_col(value):
    return re.sub(r"[^a-z0-9]+", "", norm_text(value).casefold())


def compact_name(value):
    return re.sub(r"[^a-z0-9]+", "", norm_text(value).casefold())


def read_csv_header(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
            if not header:
                raise ValueError("empty CSV header")
            return [norm_text(x) for x in header], f"encoding={encoding}"
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break
    raise RuntimeError(f"Unable to read CSV {path.name}: {last_error}")


def read_xlsx_header(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        hhid_norm = norm_col("HHID")
        fallback = None
        fallback_row = None
        for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
            values = [norm_text(x) for x in row]
            if any(values) and fallback is None:
                fallback = values
                fallback_row = row_number
            normalized = {norm_col(x) for x in values if norm_text(x)}
            if hhid_norm in normalized:
                return values, f"sheet={ws.title};header_row={row_number}"
            if row_number >= 20:
                break
        if fallback is not None:
            return fallback, f"sheet={ws.title};header_row={fallback_row}"
        raise ValueError("Could not identify XLSX header")
    finally:
        wb.close()


def read_header(path):
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return read_csv_header(path)
    if suffix == ".xlsx":
        return read_xlsx_header(path)
    raise ValueError(f"Unsupported production source: {path}")


def load_manifest():
    if not PRODUCTION_MANIFEST.exists():
        raise FileNotFoundError(f"Production manifest missing: {PRODUCTION_MANIFEST}. Run Step 01D first.")
    with PRODUCTION_MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 42:
        raise ValueError(f"Production manifest must contain 42 datasets; found {len(rows)}")
    failed = [r for r in rows if norm_text(r.get("status")).upper() != "PASS"]
    if failed:
        raise ValueError("Production manifest contains non-PASS rows: " + ", ".join(norm_text(r.get("logical_dataset")) for r in failed))
    return rows


def extract_description(meta_row):
    name = norm_text(meta_row.get("name"))
    raw = meta_row.get("raw_text") or ""
    if not name or not raw:
        return ""
    pattern = re.compile(rf"(?:^|\n)([^\n]*\({re.escape(name)}\))\s*\nData file:", re.IGNORECASE)
    matches = pattern.findall(raw)
    if matches:
        return norm_text(matches[-1])
    lines = [norm_text(x) for x in raw.splitlines()]
    for idx, line in enumerate(lines):
        if line.casefold().startswith("data file:") and idx > 0:
            candidate = lines[idx - 1]
            if norm_col(name) in norm_col(candidate):
                return candidate
    return ""


def load_metadata():
    if not VARIABLES_JSON.exists():
        raise FileNotFoundError(f"Missing metadata JSON: {VARIABLES_JSON}")
    if not VARIABLES_SUMMARY.exists():
        raise FileNotFoundError(f"Missing metadata summary: {VARIABLES_SUMMARY}")
    with VARIABLES_JSON.open("r", encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError("all_variables.json must contain a JSON list")
    with VARIABLES_SUMMARY.open("r", encoding="utf-8-sig", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    index = {}
    for row in records:
        raw_name = norm_text(row.get("name"))
        if not raw_name:
            continue
        enriched = dict(row)
        enriched["_description"] = extract_description(row)
        index.setdefault(norm_col(raw_name), []).append(enriched)
    return records, summary_rows, index


def choose_metadata(variable_name, metadata_index):
    candidates = metadata_index.get(norm_col(variable_name), [])
    if not candidates:
        return None
    with_desc = [x for x in candidates if norm_text(x.get("_description"))]
    return with_desc[0] if with_desc else candidates[0]


def detect_block(logical_dataset):
    c = compact_name(logical_dataset)
    checks = [
        ("15.2 part 2", ("block15pt2part2", "cb15pt2part2")),
        ("15.2 part 1", ("block15pt2part1", "cb15pt2part1")),
        ("17 part 2", ("block17pt2", "cb17pt2")),
        ("17 part 1", ("block17pt1", "cb17pt1")),
        ("15.1", ("block15pt1", "cb15pt1")),
        ("6 part 2", ("block6part2", "cb6part2")),
        ("6 part 1", ("block6part1", "cb6part1")),
        ("18", ("block18", "cb18")),
        ("16", ("block16", "cb16")),
        ("14", ("block14", "cb14")),
        ("13", ("block13", "cblock13", "cb13")),
        ("12", ("block12", "cb12")),
        ("11", ("block11", "cb11")),
        ("10", ("block10", "cb10")),
        ("9", ("block9", "cb9")),
        ("8", ("block8", "cb8")),
        ("7", ("block7", "cb7")),
        ("5", ("block5", "cb5")),
        ("4", ("block4", "cb4")),
        ("3", ("block3", "cb3")),
        ("1 & 2", ("blocks1and2", "cblocks1and2")),
    ]
    for block, needles in checks:
        if any(n in c for n in needles):
            return block
    if "block6" in c or "cb6" in c:
        return "6 part 1"
    return "UNKNOWN"


BLOCK_ROLES = {
    "1 & 2": ("household_identification", "HHID, geography, visit and survey-design linkage"),
    "3": ("household_characteristics", "Household characteristics and household-group classification inputs"),
    "4": ("household_members", "Member demographics and person-level indicators"),
    "5": ("asset_land", "Land asset facts and related transactions"),
    "6 part 1": ("asset_buildings_part1", "Buildings/constructions asset facts"),
    "6 part 2": ("asset_buildings_part2", "Buildings/constructions asset facts"),
    "7": ("asset_livestock_poultry", "Livestock and poultry asset facts"),
    "8": ("asset_agricultural_machinery", "Agricultural machinery/implements asset facts"),
    "9": ("asset_nonfarm_business_equipment", "Non-farm business equipment asset facts"),
    "10": ("asset_transport_equipment", "Transport equipment asset facts"),
    "11": ("asset_durable_assets", "Durable asset facts"),
    "12": ("financial_assets_shares_debentures", "Shares/debentures financial asset facts"),
    "13": ("financial_assets_other", "Other financial asset facts"),
    "14": ("asset_loans_receivable", "Loans receivable by household - asset side, not payable debt"),
    "15.1": ("loan_count_status_control", "Loan counts/status and debt control information"),
    "15.2 part 1": ("cash_loans_payable_part1", "Cash loans payable: agency/interest/purpose/security and related fields"),
    "15.2 part 2": ("cash_loans_payable_part2", "Cash loans payable: transactions/outstanding continuation fields"),
    "16": ("kind_loans_other_liabilities", "Kind loans and other liabilities"),
    "17 part 1": ("household_expenditure_part1", "Specified household expenditure inputs"),
    "17 part 2": ("household_expenditure_part2", "Specified household expenditure inputs"),
    "18": ("asset_sale_loss", "Sale/loss of assets and capital-transaction inputs"),
    "UNKNOWN": ("unclassified", "Requires manual classification"),
}


def variable_role(name):
    n = norm_col(name)
    roles = {
        norm_col("HHID"): "join_key_household",
        norm_col("Sector"): "grouping_sector",
        norm_col("State"): "geography_state_code",
        norm_col("District"): "geography_district_code",
        norm_col("State_Region"): "geography_state_region_code",
        norm_col("Visit_no"): "visit_dimension",
        norm_col("MLT"): "candidate_estimation_multiplier",
        norm_col("Weight"): "candidate_estimation_weight",
        norm_col("NSS"): "survey_design_control",
        norm_col("NSC"): "survey_design_control",
        norm_col("Level"): "record_level",
    }
    if n in roles:
        return roles[n]
    if re.fullmatch(r"b\d+(?:\d+)?q\d+", n):
        return "survey_question_variable"
    return "supporting_identifier_or_measure"


def metadata_fields(meta):
    if not meta:
        return {"description": "", "metadata_data_file": "", "metadata_valid": "", "metadata_invalid": "", "metadata_categories": "", "metadata_url": ""}
    overview = meta.get("overview") or {}
    categories = meta.get("categories") or []
    return {
        "description": norm_text(meta.get("_description")),
        "metadata_data_file": norm_text(meta.get("data_file")),
        "metadata_valid": norm_text(overview.get("valid")),
        "metadata_invalid": norm_text(overview.get("invalid")),
        "metadata_categories": json.dumps(categories, ensure_ascii=False),
        "metadata_url": norm_text(meta.get("url")),
    }


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    print("=" * 78)
    print("AIDIS 2003 - STEP 01B VARIABLE / METHODOLOGY MAPPING")
    print("Header-only mapping: no full microdata scan")
    print("=" * 78)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    errors = []
    warnings = []

    try:
        manifest = load_manifest()
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        print("\nSTEP 01B BUILD STATUS: FAIL")
        return 1

    try:
        metadata_records, summary_rows, metadata_index = load_metadata()
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        print("\nSTEP 01B BUILD STATUS: FAIL")
        return 1

    print("\n[1] Locked production manifest")
    print(f"Production datasets          : {len(manifest)}")
    print(f"Manifest PASS rows           : {sum(1 for x in manifest if x['status'].upper() == 'PASS')}")

    print("\n[2] Metadata package")
    print(f"all_variables.json records   : {len(metadata_records)}")
    print(f"variables_summary.csv rows   : {len(summary_rows)}")
    print(f"Metadata variable names      : {len(metadata_index)}")

    if len(metadata_records) != len(summary_rows):
        warnings.append(f"Metadata record-count mismatch: JSON={len(metadata_records)}, summary={len(summary_rows)}")

    header_catalog_rows = []
    mapping_rows = []
    file_role_rows = []
    total_field_occurrences = 0
    mapped_metadata_occurrences = 0
    common_fallback_occurrences = 0
    unresolved_occurrences = 0
    unique_raw_names = set()
    unique_unresolved_names = set()

    print("\n[3] Production header -> metadata mapping")

    for idx, manifest_row in enumerate(manifest, start=1):
        logical_dataset = norm_text(manifest_row["logical_dataset"])
        source_path = Path(manifest_row["source_path"])
        group = norm_text(manifest_row["group"])
        source_type = norm_text(manifest_row["source_type"])

        if not source_path.exists():
            errors.append(f"Source missing from manifest: {source_path}")
            print(f"[{idx:02d}/42] FAIL | missing source | {logical_dataset}")
            continue

        try:
            header, read_info = read_header(source_path)
        except Exception as exc:
            errors.append(f"{logical_dataset}: {type(exc).__name__}: {exc}")
            print(f"[{idx:02d}/42] FAIL | unreadable header | {logical_dataset}")
            continue

        nonblank_header = [x for x in header if norm_text(x)]
        normalized = [norm_col(x) for x in nonblank_header]
        duplicates = sorted({x for x in normalized if normalized.count(x) > 1 and x})
        if duplicates:
            errors.append(f"{logical_dataset}: duplicate normalized header columns {duplicates}")

        block = detect_block(logical_dataset)
        conceptual_role, main_use = BLOCK_ROLES.get(block, BLOCK_ROLES["UNKNOWN"])
        dataset_metadata_count = 0
        dataset_common_count = 0
        dataset_unresolved_count = 0

        for ordinal, raw_name in enumerate(nonblank_header, start=1):
            unique_raw_names.add(norm_text(raw_name))
            total_field_occurrences += 1
            meta = choose_metadata(raw_name, metadata_index)
            mf = metadata_fields(meta)
            description = mf["description"]
            mapping_status = ""
            unresolved_reason = ""

            if meta and description:
                mapping_status = "MAPPED_METADATA"
                mapped_metadata_occurrences += 1
                dataset_metadata_count += 1
            elif raw_name in COMMON_LABELS:
                description = COMMON_LABELS[raw_name]
                mapping_status = "MAPPED_COMMON_FALLBACK"
                common_fallback_occurrences += 1
                dataset_common_count += 1
            elif meta:
                mapping_status = "UNRESOLVED_DESCRIPTION"
                unresolved_reason = "Metadata record exists but human-readable variable description was not parsed"
                unresolved_occurrences += 1
                dataset_unresolved_count += 1
                unique_unresolved_names.add(raw_name)
            else:
                mapping_status = "UNRESOLVED_METADATA_GAP"
                unresolved_reason = "Variable is present in raw production header but absent from supplied metadata package"
                unresolved_occurrences += 1
                dataset_unresolved_count += 1
                unique_unresolved_names.add(raw_name)

            mapping_rows.append({
                "dataset_sequence": idx,
                "group": group,
                "logical_dataset": logical_dataset,
                "block": block,
                "conceptual_role": conceptual_role,
                "column_ordinal": ordinal,
                "raw_variable": raw_name,
                "normalized_variable": norm_col(raw_name),
                "variable_role": variable_role(raw_name),
                "description": description,
                "metadata_data_file": mf["metadata_data_file"],
                "metadata_valid": mf["metadata_valid"],
                "metadata_invalid": mf["metadata_invalid"],
                "metadata_categories_json": mf["metadata_categories"],
                "metadata_url": mf["metadata_url"],
                "mapping_status": mapping_status,
                "unresolved_reason": unresolved_reason,
                "methodology_status": "PENDING_OFFICIAL_CONFIRMATION",
                "source_type": source_type,
                "source_path": str(source_path),
            })

        header_catalog_rows.append({
            "dataset_sequence": idx,
            "group": group,
            "logical_dataset": logical_dataset,
            "block": block,
            "conceptual_role": conceptual_role,
            "source_type": source_type,
            "source_path": str(source_path),
            "column_count": len(nonblank_header),
            "duplicate_normalized_columns": ";".join(duplicates),
            "header_columns": "|".join(nonblank_header),
            "read_info": read_info,
            "status": "PASS" if not duplicates else "FAIL",
        })

        file_role_rows.append({
            "dataset_sequence": idx,
            "group": group,
            "logical_dataset": logical_dataset,
            "block": block,
            "conceptual_role": conceptual_role,
            "main_kpi_use": main_use,
            "source_type": source_type,
            "source_path": str(source_path),
            "column_count": len(nonblank_header),
            "metadata_mapped_columns": dataset_metadata_count,
            "common_fallback_columns": dataset_common_count,
            "unresolved_columns": dataset_unresolved_count,
            "reference_period_status": "PENDING_OFFICIAL_CONFIRMATION",
            "visit_usage_status": "PENDING_OFFICIAL_CONFIRMATION",
            "status": "PASS" if block != "UNKNOWN" and not duplicates else "REVIEW",
        })

        print(f"[{idx:02d}/42] PASS | block={block:11s} | cols={len(nonblank_header):>2} | unresolved={dataset_unresolved_count:>2} | {logical_dataset}")

    unresolved_rows = [r for r in mapping_rows if r["mapping_status"].startswith("UNRESOLVED")]

    write_csv(HEADER_CATALOG, header_catalog_rows, [
        "dataset_sequence", "group", "logical_dataset", "block", "conceptual_role",
        "source_type", "source_path", "column_count", "duplicate_normalized_columns",
        "header_columns", "read_info", "status",
    ])
    write_csv(VARIABLE_MAPPING, mapping_rows, [
        "dataset_sequence", "group", "logical_dataset", "block", "conceptual_role",
        "column_ordinal", "raw_variable", "normalized_variable", "variable_role",
        "description", "metadata_data_file", "metadata_valid", "metadata_invalid",
        "metadata_categories_json", "metadata_url", "mapping_status", "unresolved_reason",
        "methodology_status", "source_type", "source_path",
    ])
    write_csv(UNRESOLVED_FILE, unresolved_rows, [
        "dataset_sequence", "group", "logical_dataset", "block", "conceptual_role",
        "column_ordinal", "raw_variable", "normalized_variable", "variable_role",
        "description", "metadata_data_file", "metadata_valid", "metadata_invalid",
        "metadata_categories_json", "metadata_url", "mapping_status", "unresolved_reason",
        "methodology_status", "source_type", "source_path",
    ])
    write_csv(FILE_ROLES, file_role_rows, [
        "dataset_sequence", "group", "logical_dataset", "block", "conceptual_role",
        "main_kpi_use", "source_type", "source_path", "column_count",
        "metadata_mapped_columns", "common_fallback_columns", "unresolved_columns",
        "reference_period_status", "visit_usage_status", "status",
    ])

    dataset_config = {}
    for role_row in file_role_rows:
        logical = role_row["logical_dataset"]
        vars_for_dataset = [
            {
                "raw_variable": r["raw_variable"],
                "variable_role": r["variable_role"],
                "description": r["description"],
                "mapping_status": r["mapping_status"],
            }
            for r in mapping_rows if r["logical_dataset"] == logical
        ]
        dataset_config[logical] = {
            "group": role_row["group"],
            "block": role_row["block"],
            "conceptual_role": role_row["conceptual_role"],
            "main_kpi_use": role_row["main_kpi_use"],
            "source_type": role_row["source_type"],
            "source_path": role_row["source_path"],
            "reference_period_status": role_row["reference_period_status"],
            "visit_usage_status": role_row["visit_usage_status"],
            "variables": vars_for_dataset,
        }

    config = {
        "survey": {
            "title": "Debt & Investment, Jan - Dec 2003",
            "round": "NSS 59th Round",
            "production_dataset_count": len(header_catalog_rows),
        },
        "production_manifest": str(PRODUCTION_MANIFEST),
        "methodology_gates": METHOD_GATES,
        "datasets": dataset_config,
        "unresolved_variable_occurrences": len(unresolved_rows),
        "unresolved_unique_variable_names": sorted(unique_unresolved_names),
        "notes": [
            "This is a Step 01B mapping build, not a final calculation specification.",
            "Do not use pending methodology fields for KPI calculation until official reports/questionnaires are reviewed.",
            "Block 14 is treated as loans receivable / asset-side based on the source dataset title.",
        ],
    }
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    unknown_roles = [r for r in file_role_rows if r["block"] == "UNKNOWN"]
    review_roles = [r for r in file_role_rows if r["status"] != "PASS"]
    if unknown_roles:
        errors.append("Unclassified production datasets: " + ", ".join(r["logical_dataset"] for r in unknown_roles))
    if review_roles and not unknown_roles:
        warnings.append(f"{len(review_roles)} dataset role rows require review.")

    references_found = sorted(p.name for p in REFERENCE_DIR.glob("*.pdf")) if REFERENCE_DIR.exists() else []
    build_status = "PASS" if not errors else "FAIL"

    summary_lines = [
        "=" * 78,
        "AIDIS 2003 - STEP 01B VARIABLE / METHODOLOGY MAPPING SUMMARY",
        "=" * 78,
        f"Production datasets             : {len(header_catalog_rows)}",
        f"Raw field occurrences           : {total_field_occurrences}",
        f"Unique raw variable names       : {len(unique_raw_names)}",
        f"Metadata-mapped occurrences     : {mapped_metadata_occurrences}",
        f"Common fallback occurrences     : {common_fallback_occurrences}",
        f"Unresolved occurrences          : {unresolved_occurrences}",
        f"Unique unresolved variables     : {len(unique_unresolved_names)}",
        f"Reference PDFs detected         : {len(references_found)}",
        f"Errors                          : {len(errors)}",
        f"Warnings                        : {len(warnings)}",
        "",
        f"Header catalog                  : {HEADER_CATALOG}",
        f"Variable mapping                : {VARIABLE_MAPPING}",
        f"Unresolved variables            : {UNRESOLVED_FILE}",
        f"File roles                      : {FILE_ROLES}",
        f"JSON config                     : {CONFIG_FILE}",
        "",
        "METHODOLOGY GATES:",
    ]
    for key, value in METHOD_GATES.items():
        summary_lines.append(f"  - {key}: {value['status']}")
    if references_found:
        summary_lines.append("")
        summary_lines.append("REFERENCE PDFS DETECTED:")
        summary_lines.extend(f"  - {x}" for x in references_found)
    if warnings:
        summary_lines.append("")
        summary_lines.append("WARNINGS:")
        summary_lines.extend(f"  - {x}" for x in warnings)
    if errors:
        summary_lines.append("")
        summary_lines.append("ERRORS:")
        summary_lines.extend(f"  - {x}" for x in errors)
    summary_lines.extend([
        "",
        f"STEP 01B BUILD STATUS: {build_status}",
        "NOTE: unresolved variables are expected here and will be resolved from the",
        "official Schedule V1/V2 and Reports 500-504 before Step 02 calculations.",
        "=" * 78,
    ])
    SUMMARY_FILE.write_text("\n".join(summary_lines), encoding="utf-8")

    print("\n" + "=" * 78)
    print("AIDIS 2003 - STEP 01B BUILD SUMMARY")
    print("=" * 78)
    print(f"Production datasets         : {len(header_catalog_rows)}")
    print(f"Raw field occurrences       : {total_field_occurrences}")
    print(f"Unique raw variable names   : {len(unique_raw_names)}")
    print(f"Metadata mapped             : {mapped_metadata_occurrences}")
    print(f"Common fallbacks            : {common_fallback_occurrences}")
    print(f"Unresolved occurrences      : {unresolved_occurrences}")
    print(f"Unique unresolved variables : {len(unique_unresolved_names)}")
    print(f"Errors                      : {len(errors)}")
    print(f"Warnings                    : {len(warnings)}")
    print()
    print(f"Header catalog              : {HEADER_CATALOG}")
    print(f"Variable mapping            : {VARIABLE_MAPPING}")
    print(f"Unresolved variables        : {UNRESOLVED_FILE}")
    print(f"File roles                  : {FILE_ROLES}")
    print(f"JSON config                 : {CONFIG_FILE}")
    print(f"Summary                     : {SUMMARY_FILE}")
    print()
    print(f"STEP 01B BUILD STATUS: {build_status}")
    print("=" * 78)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())