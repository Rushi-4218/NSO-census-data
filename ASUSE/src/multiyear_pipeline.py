from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import logging
from pathlib import Path
import re
import time
import zipfile

import numpy as np
import pandas as pd

from src.config import CLIENT_COLUMNS, SUBGROUPS
from src.io.load_tabular_levels import (
    ROUND_FIELDS,
    TARGET_LEVELS,
    discover_level_files,
    headers,
    level_from_name,
    load_round_levels,
    row_count,
)
from src.mapping.build_geography_mapping import build_district_master, load_state_codes
from src.mapping.build_master_mapping import build_master_mapping
from src.metrics.estimates import calculate, classify_bac, ownership_group, registration_diagnostics
from src.qa.validations import write_qa


STEP_NAMES = [
    "01_unincorporated_establishments.csv",
    "02_ownership_pattern.csv",
    "03_workers_employed.csv",
    "04_emoluments_per_hired_worker.csv",
    "05_average_fixed_assets.csv",
    "06_outstanding_loan_per_ue.csv",
    "07_gva_share.csv",
    "08_registration_status.csv",
]

LEVEL_REQUIREMENTS = {
    "l02": ("Block 2", "1, 2, 8"),
    "l03": ("Blocks 2.1-2.3", "4, 7"),
    "l08": ("Block 7", "7"),
    "l09": ("Block 8", "3, 4"),
    "l10": ("Block 9", "4"),
    "l11": ("Block 10", "5"),
    "l12": ("Block 11", "6"),
}

ASUSE_2023_2024_MANUFACTURING_SPECIAL_NIC5 = {
    "01632", "35103", "35105", "35106", "35107", "35109", "45200", "45403",
}


def _classify_bac_for_round(survey_round: str, nic2: str, nic5: str) -> str | None:
    if survey_round != "2023-2024":
        return classify_bac(nic2, nic5)
    normalized_nic5 = str(nic5).strip().replace(".0", "").zfill(5)
    try:
        division = int(str(nic2))
    except ValueError:
        return None
    if normalized_nic5 in ASUSE_2023_2024_MANUFACTURING_SPECIAL_NIC5 or 10 <= division <= 33:
        return "Manufacturing"
    if 45 <= division <= 47 and normalized_nic5 not in {"45200", "45403"}:
        return "Trade"
    return "Other Services"


@dataclass(frozen=True)
class RoundConfig:
    root: Path
    survey_round: str
    source_url: str
    output_year: str
    published_date: str
    multiplier_divisor: float
    district_page_start: int
    district_page_stop: int
    raw_stem: str
    ddi_name: str
    official_benchmarks: dict
    survey_id: int = 8
    survey_name: str = "ASUSE"
    group_id: int = 1
    group_name: str = "Annual Survey of Unincorporated Sector Enterprises"
    # Counts are rounded independently at final delivery. With four ownership
    # components, a two-unit reconciliation difference is the rounding bound.
    tolerance: float = 2.0

    @property
    def survey_year(self) -> str:
        return self.output_year

    @property
    def extracted_date(self) -> str:
        return date.today().strftime("%d-%b-%y")

    @property
    def mapping_dir(self) -> Path:
        return self.root / "mapping" / self.survey_round

    @property
    def work_dir(self) -> Path:
        return self.root / "work" / self.survey_round

    @property
    def output_dir(self) -> Path:
        return self.root / "output" / self.survey_round

    @property
    def qa_dir(self) -> Path:
        return self.root / "qa" / self.survey_round


@dataclass(frozen=True)
class RoundInputs:
    zip_file: Path
    ddi_file: Path
    layout_file: Path
    volume_i_file: Path
    volume_ii_file: Path
    estimation_file: Path
    census_file: Path
    template_file: Path


def _input_dir(root: Path) -> Path:
    for name in ("Input", "INPUT", "input"):
        path = root / name
        if path.is_dir():
            return path
    raise FileNotFoundError("Input directory not found")


def _one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise RuntimeError(f"Expected exactly one {label}; found {len(paths)}: {[p.name for p in paths]}")
    return paths[0]


def _discover(root: Path, survey_round: str, settings: dict) -> RoundInputs:
    input_dir = _input_dir(root)
    docs = input_dir / "official_docs"
    return RoundInputs(
        _one(list(input_dir.glob(settings["zip_pattern"])), f"{survey_round} raw ZIP"),
        _one(list(input_dir.glob(settings["ddi_pattern"])), f"{survey_round} DDI"),
        docs / settings["layout"],
        docs / settings["volume_i"],
        docs / settings["volume_ii"],
        docs / settings["estimation_procedure"],
        docs / "PC11_TV_DIR.xlsx",
        _one(list(input_dir.glob("*Maharashtra*Template*.csv")), "Maharashtra structural template"),
    )


def _mkdirs(cfg: RoundConfig) -> None:
    for path in [cfg.mapping_dir, cfg.work_dir / "profiling", cfg.work_dir / "cache", cfg.output_dir / "steps", cfg.qa_dir, cfg.root / "logs"]:
        path.mkdir(parents=True, exist_ok=True)


def _logger(cfg: RoundConfig) -> logging.Logger:
    log = logging.getLogger(f"asuse.{cfg.survey_round}")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(cfg.root / "logs" / f"ASUSE_{cfg.survey_round}_pipeline.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    log.addHandler(stream_handler)
    return log


def _phase(name: str, **details) -> None:
    print("\n" + "=" * 72)
    print(f"PHASE NAME: {name}")
    for label, value in details.items():
        print(f"{label.replace('_', ' ').upper()}: {value}")


def _extract(inputs: RoundInputs, cfg: RoundConfig) -> Path:
    destination = cfg.work_dir / "raw"
    destination.mkdir(parents=True, exist_ok=True)
    if not any(destination.rglob("*")):
        with zipfile.ZipFile(inputs.zip_file) as archive:
            archive.extractall(destination)
    return destination


def _profile_raw(files: list[Path], selected: dict[str, Path], parsed_profiles: list[dict], cfg: RoundConfig) -> None:
    inventory = []
    column_rows = []
    for path in files:
        level = level_from_name(path) or "unknown"
        inventory.append({
            "Raw_Level": level.upper(), "Source_File": path.name,
            "Format": path.suffix.lower().lstrip("."), "Size_Bytes": path.stat().st_size,
            "Selected_For_Processing": selected.get(level) == path,
        })
        for ordinal, column in enumerate(headers(path), 1):
            column_rows.append({
                "Raw_Level": level.upper(), "Source_File": path.name,
                "Column_Ordinal": ordinal, "Raw_Column": column,
                "Inferred_Type": "numeric" if any(x in column.lower() for x in ("value", "amount", "worker", "mlt")) else "character",
            })
    profile_lookup = {row["Raw_Level"].lower(): row for row in parsed_profiles}
    counts = []
    keys = []
    for level, path in sorted(selected.items()):
        profile = profile_lookup.get(level, {"Selected_Rows": 0, "Status": "INVENTORIED"})
        row = {"Raw_Level": level.upper(), "Rows": row_count(path), **{k: v for k, v in profile.items() if k != "Raw_Level"}}
        counts.append(row)
        keys.append({
            **row,
            "Enterprise_Key_Definition": "29-character concatenation of common identification fields",
        })
    pd.DataFrame(inventory).to_csv(cfg.work_dir / "profiling/raw_file_inventory.csv", index=False)
    pd.DataFrame(column_rows).to_csv(cfg.work_dir / "profiling/raw_level_columns.csv", index=False)
    pd.DataFrame(counts).to_csv(cfg.work_dir / "profiling/raw_row_counts.csv", index=False)
    pd.DataFrame(keys).to_csv(cfg.work_dir / "profiling/raw_key_profile.csv", index=False)


def _missing_levels(selected: dict[str, Path], cfg: RoundConfig) -> pd.DataFrame:
    rows = []
    for number in range(1, 17):
        level = f"l{number:02d}"
        block, datapoint = LEVEL_REQUIREMENTS.get(level, ("Not required by client metrics", "None"))
        present = level in selected
        rows.append({
            "Expected_Level": level.upper(), "Expected_Block": block,
            "Required_For_Datapoint": datapoint, "Present_In_ZIP": present,
            "Alternative_Source": "", "Status": "PRESENT" if present else ("MISSING_CRITICAL" if level in LEVEL_REQUIREMENTS else "MISSING_NONMETRIC"),
            "Notes": "" if present else "No validated alternative source in supplied ZIP/DDI",
        })
    result = pd.DataFrame(rows)
    result.to_csv(cfg.qa_dir / "missing_raw_levels.csv", index=False)
    return result


def _validate_gva_source(selected: dict[str, Path], cfg: RoundConfig) -> tuple[bool, pd.DataFrame]:
    path = selected.get("l08")
    required = ROUND_FIELDS[cfg.survey_round]["l08"]
    source_headers = headers(path) if path else []
    lookup = {column.lower() for column in source_headers}
    missing_fields = [
        canonical for canonical, candidates in required.items()
        if not any(candidate.lower() in lookup for candidate in candidates)
    ]
    available = path is not None and not missing_fields
    result = pd.DataFrame([{
        "Year": cfg.survey_round, "Metric": "% share of sectors in GVA",
        "Required_Level": "L08", "Required_Block": "Block 7.1 & 7.2",
        "Required_Fields": ", ".join(required),
        "Source_File": path.name if path else "",
        "Missing_Fields": ", ".join(missing_fields) if path else ", ".join(required),
        "Status": "COMPUTABLE" if available else "SOURCE_MISSING / NOT_COMPUTABLE",
    }])
    result.to_csv(cfg.qa_dir / "qa_gva_source_availability.csv", index=False)
    return available, result


def _mapping_outputs(cfg: RoundConfig, inputs: RoundInputs, available_levels: set[str]) -> pd.DataFrame:
    master = build_master_mapping(cfg, available_levels)
    stem = f"ASUSE_{cfg.survey_round}_Master_Mapping"
    master.to_csv(cfg.mapping_dir / f"{stem}.csv", index=False)
    master.to_excel(cfg.mapping_dir / f"{stem}.xlsx", index=False)
    ddi = pd.concat([pd.read_excel(inputs.ddi_file, sheet_name="Sheet1"), pd.read_excel(inputs.ddi_file, sheet_name="Sheet2")], ignore_index=True)
    coverage = master[["Mapping_ID", "Requirement_Code", "Source_Level", "Source_Item", "Source_Raw_Column", "Mapping_Status"]].copy()
    ddi_text = " ".join(ddi.astype(str).to_numpy().ravel()).lower()
    coverage["DDI_Match"] = coverage.Source_Item.astype(str).apply(lambda value: value.split("/")[0].split(" or ")[0] in ddi_text)
    coverage.to_csv(cfg.work_dir / "profiling/ddi_coverage_report.csv", index=False)
    master[master.Mapping_Status != "Resolved"].to_csv(cfg.work_dir / "profiling/unresolved_variables.csv", index=False)
    return master


def _geography(base: pd.DataFrame, cfg: RoundConfig, inputs: RoundInputs):
    states = load_state_codes(inputs.layout_file)
    lookup = states.set_index("Raw_State_Code")
    base["State_ID"] = base.Raw_State_Code.map(lookup.State_ID)
    base["State_Name"] = base.Raw_State_Code.map(lookup.State_Name)
    if base.State_ID.isna().any():
        raise RuntimeError(f"Unresolved state codes: {base.loc[base.State_ID.isna(), 'Raw_State_Code'].unique().tolist()}")
    base["State_ID"] = base.State_ID.astype(int)
    observed = base.groupby(["State_ID", "State_Name", "district"], as_index=False).agg(Raw_NSS_Region=("nss_region", "first")).rename(columns={"district": "Raw_District_Code"})
    districts = build_district_master(
        inputs.census_file, inputs.volume_i_file, observed,
        cfg.root / "work/cache/census_districts.csv",
        range(cfg.district_page_start, cfg.district_page_stop), cfg.survey_round,
    )
    unresolved = districts[districts.Mapping_Status != "Resolved"]
    if len(unresolved):
        unresolved.to_csv(cfg.work_dir / "profiling/unresolved_geography.csv", index=False)
        raise RuntimeError(f"Unresolved geography mappings: {unresolved.head(20).to_dict('records')}")
    template = pd.read_csv(inputs.template_file, usecols=["State_ID", "District_ID", "District_Name"]).drop_duplicates()
    template_names = template.set_index(["State_ID", "District_ID"]).District_Name.to_dict()
    districts["District_Name"] = [template_names.get((int(s), int(d)), n) for s, d, n in zip(districts.State_ID, districts.District_ID, districts.District_Name)]
    district_lookup = districts.set_index(["State_ID", "Raw_District_Code"])
    index = pd.MultiIndex.from_arrays([base.State_ID, base.district])
    base["District_ID"] = district_lookup.District_ID.reindex(index).to_numpy().astype(int)
    base["District_Name"] = district_lookup.District_Name.reindex(index).to_numpy()
    available = base.pivot_table(index="State_ID", columns="sector", values="Enterprise_Key", aggfunc="size", fill_value=0)
    state_master = states.copy()
    state_master["NSS_Region_Prefix"] = state_master.Raw_State_Code
    state_master["Available_Rural"] = state_master.State_ID.map(available.get("1", pd.Series(dtype=int))).fillna(0).gt(0)
    state_master["Available_Urban"] = state_master.State_ID.map(available.get("2", pd.Series(dtype=int))).fillna(0).gt(0)
    state_master["District_Count"] = state_master.State_ID.map(districts.groupby("State_ID").District_ID.nunique()).fillna(0).astype(int)
    state_master.to_csv(cfg.mapping_dir / "state_master.csv", index=False)
    districts.to_csv(cfg.mapping_dir / "district_master.csv", index=False)
    return base, state_master, districts


def _category_mappings(base: pd.DataFrame, cfg: RoundConfig) -> None:
    activity = base[["Major_NIC_2dig", "Major_NIC_5dig", "BAC"]].drop_duplicates().sort_values(["BAC", "Major_NIC_2dig", "Major_NIC_5dig"])
    activity["Mapping_Source"] = f"ASUSE {cfg.survey_round} DDI/layout, principal NIC"
    activity.to_csv(cfg.mapping_dir / "activity_master.csv", index=False)
    ownership = pd.DataFrame([
        ("1", "Proprietary male/HUF", "Proprietary", 1), ("2", "Proprietary female/HUF", "Proprietary", 1),
        ("3", "Proprietary transgender/HUF", "Proprietary", 1), ("4", "Partnership same household", "Partnership", 2),
        ("5", "Partnership different households", "Partnership", 2), ("6", "Self Help Group", "SHG", 3),
        ("7", "Trust", "Others", 4), ("8", "Co-operative society", "Others", 4), ("9", "Others", "Others", 4),
    ], columns=["Raw_Ownership_Code", "Raw_Ownership_Label", "Client_Ownership", "Client_Col_ID"])
    ownership["Mapping_Source"] = f"ASUSE {cfg.survey_round} DDI item 204"
    ownership.to_csv(cfg.mapping_dir / "ownership_master.csv", index=False)
    registration = pd.DataFrame([("1", "Registered"), ("2", "Unregistered")], columns=["Raw_Registration_Code", "Client_Registration"])
    registration["Mapping_Source"] = f"ASUSE {cfg.survey_round} DDI item 227"
    registration.to_csv(cfg.mapping_dir / "registration_master.csv", index=False)


def _merge(base: pd.DataFrame, right: pd.DataFrame, name: str, audits: list[dict]) -> pd.DataFrame:
    left_duplicates = int(base.Enterprise_Key.duplicated().sum())
    right_duplicates = int(right.Enterprise_Key.duplicated().sum())
    if right_duplicates:
        raise RuntimeError(f"{name} is not unique at enterprise grain")
    before = len(base)
    left_keys = pd.Index(base.Enterprise_Key)
    right_keys = pd.Index(right.Enterprise_Key)
    matched = int(left_keys.isin(right_keys).sum())
    right_unmatched = int((~right_keys.isin(left_keys)).sum())
    result = base.merge(right, on="Enterprise_Key", how="left", validate="one_to_one")
    audits.append({
        "Join": name, "Left_Rows": before, "Right_Rows": len(right), "Result_Rows": len(result),
        "Unique_Before": base.Enterprise_Key.nunique(), "Unique_After": result.Enterprise_Key.nunique(),
        "Left_Duplicate_Keys": left_duplicates, "Right_Duplicate_Keys": right_duplicates,
        "Matched_Rows": matched, "Left_Unmatched_Rows": before - matched,
        "Right_Unmatched_Keys": right_unmatched, "Cardinality": "one_to_one",
        "Duplicate_Factor": len(result) / before,
        "Status": "PASS" if len(result) == before and not left_duplicates and not right_duplicates and not right_unmatched else "REVIEW",
    })
    return result


def _enterprise_table(base: pd.DataFrame, parsed: dict[str, pd.DataFrame], cfg: RoundConfig) -> pd.DataFrame:
    audits = []
    ref = parsed["l03"][["Enterprise_Key", "Ref_Period_Type", "Months_In_Accounting_Period"]].drop_duplicates("Enterprise_Key")
    base = _merge(base, ref, "L03_reference_period", audits)
    months = pd.to_numeric(base.Months_In_Accounting_Period, errors="coerce")
    base["Annual_Factor"] = np.where(base.Ref_Period_Type.astype(str) == "4", 12 / months.fillna(12).replace(0, 12), 12.0)

    workers_raw = parsed["l09"].copy()
    workers_raw["Total_Workers"] = pd.to_numeric(workers_raw.Total_Workers, errors="coerce")
    workers = workers_raw[workers_raw.Item_No == "789"].groupby("Enterprise_Key", as_index=False).Total_Workers.sum(min_count=1).rename(columns={"Total_Workers": "Worker_Value"})
    hired = workers_raw[workers_raw.Item_No.isin(["782", "783"])].groupby("Enterprise_Key", as_index=False).Total_Workers.sum(min_count=1).rename(columns={"Total_Workers": "Hired_Worker_Value"})
    base = _merge(base, workers, "L09_total_workers_789", audits)
    base = _merge(base, hired, "L09_hired_workers_782_783", audits)

    specs = [
        ("l10", "Emolument_Value", "L10_total_emoluments_939"),
        ("l11", "Fixed_Asset_Value", "L11_total_fixed_assets_1019"),
        ("l12", "Loan_Value", "L12_total_loans_1119"),
        ("l08", "GVA_Value", "L08_GVA_769_779"),
    ]
    for level, value, label in specs:
        if level not in parsed:
            base[value] = np.nan
            audits.append({"Join": label, "Left_Rows": len(base), "Right_Rows": 0, "Result_Rows": len(base), "Unique_Before": base.Enterprise_Key.nunique(), "Unique_After": base.Enterprise_Key.nunique(), "Duplicate_Factor": 1.0, "Status": "MISSING_LEVEL"})
            continue
        right = parsed[level][["Enterprise_Key", value]].copy()
        right[value] = pd.to_numeric(right[value], errors="coerce")
        right = right.groupby("Enterprise_Key", as_index=False)[value].sum(min_count=1)
        base = _merge(base, right, label, audits)

    base["Establishment_Contribution"] = base.Multiplier
    base["Worker_Contribution"] = base.Worker_Value * base.Multiplier
    base["Hired_Worker_Contribution"] = base.Hired_Worker_Value * base.Multiplier
    base["Emolument_Contribution"] = base.Emolument_Value * base.Annual_Factor * base.Multiplier
    base["Fixed_Asset_Contribution"] = base.Fixed_Asset_Value * base.Multiplier
    base["Loan_Contribution"] = base.Loan_Value * base.Multiplier
    base["GVA_Contribution"] = base.GVA_Value * base.Multiplier
    keep = [
        "State_ID", "State_Name", "District_ID", "District_Name", "Sector_code", "Sector", "BAC",
        "Enterprise_Key", "Multiplier", "Ownership_Group", "Registered", "Establishment_Contribution",
        "Worker_Contribution", "Hired_Worker_Contribution", "Emolument_Contribution",
        "Fixed_Asset_Contribution", "Loan_Contribution", "GVA_Contribution", "fsu", "nss_region", "district",
    ]
    base[keep].to_parquet(cfg.work_dir / f"ASUSE_{cfg.survey_round}_Master_Estimation_Table.parquet", index=False)
    pd.DataFrame(audits).to_csv(cfg.qa_dir / "join_audit.csv", index=False)
    profile = base.Multiplier.describe(percentiles=[.01, .5, .99]).to_frame("Value").reset_index(names="Statistic")
    profile["Null_Count"] = base.Multiplier.isna().sum()
    profile["Zero_Count"] = (base.Multiplier == 0).sum()
    profile.to_csv(cfg.qa_dir / "multiplier_profile.csv", index=False)
    return base


def _skeleton(cfg: RoundConfig, states: pd.DataFrame, districts: pd.DataFrame) -> pd.DataFrame:
    geographies = [{"State_ID": 0, "State_Name": "India", "District_ID": 0, "District_Name": "All Districts"}]
    geographies.extend({"State_ID": int(s.State_ID), "State_Name": s.State_Name, "District_ID": 0, "District_Name": "All Districts"} for s in states.itertuples())
    geographies.extend(districts[["State_ID", "State_Name", "District_ID", "District_Name"]].drop_duplicates().to_dict("records"))
    rows = []
    for geo in geographies:
        for sector_code, sector in [(0, "total"), (1, "rural"), (2, "urban")]:
            for subgroup_id, (subgroup_name, columns, unit) in SUBGROUPS.items():
                for col_id, description in enumerate(columns, 1):
                    rows.append({
                        "Survey_ID": cfg.survey_id, "Survey_NAME": cfg.survey_name,
                        "Survey_GROUP_ID": cfg.group_id, "GROUP_NAME": cfg.group_name,
                        "SUB_GROUP_ID": subgroup_id, "SUB_GROUP_NAME": subgroup_name,
                        "Year": cfg.output_year, "FREQ_DESC": "Annual", **geo,
                        "Sector_code": sector_code, "Sector": sector,
                        "Col_ID": col_id, "COL_DESC": description, "Unit": unit,
                    })
    return pd.DataFrame(rows)


def _client_master(skeleton: pd.DataFrame, master: pd.DataFrame, cfg: RoundConfig) -> None:
    metadata = master.rename(columns={"Client_Col_ID": "Col_ID", "Client_COL_DESC": "COL_DESC"})
    metadata = metadata[["SUB_GROUP_ID", "Col_ID", "Requirement_Code", "Source_Level", "Source_Raw_Column", "Source_Filter", "Formula_Description", "Weighting_Rule", "Numerator_Definition", "Denominator_Definition", "QA_Check"]]
    metadata.columns = ["SUB_GROUP_ID", "Col_ID", "Requirement_Code", "Source_Level", "Source_Field", "Filter", "Formula", "Weighting_Rule", "Numerator", "Denominator", "Validation_Rule"]
    with pd.ExcelWriter(cfg.mapping_dir / f"ASUSE_{cfg.survey_round}_Client_Output_Master.xlsx", engine="openpyxl") as writer:
        skeleton.to_excel(writer, sheet_name="Client_Row_Skeleton", index=False)
        metadata.to_excel(writer, sheet_name="Mapping_Metadata", index=False)


def _client_output(skeleton: pd.DataFrame, estimates: pd.DataFrame, cfg: RoundConfig, *, round_data: bool = True) -> pd.DataFrame:
    join = ["State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "COL_DESC"]
    output = skeleton.merge(estimates[join + ["DATA"]], on=join, how="left", validate="one_to_one")
    output["Published_date"] = cfg.published_date
    output["Extracted_Date"] = cfg.extracted_date
    output["Source"] = cfg.source_url
    count_mask = output.SUB_GROUP_ID.isin([1, 2, 3])
    output.loc[count_mask, "DATA"] = output.loc[count_mask, "DATA"].fillna(0)
    if round_data:
        output.loc[count_mask, "DATA"] = output.loc[count_mask, "DATA"].round(0)
        output.loc[~count_mask, "DATA"] = output.loc[~count_mask, "DATA"].round(2)
    return output[CLIENT_COLUMNS].sort_values(["State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"], kind="stable").reset_index(drop=True)


def _official_benchmark_qa(final: pd.DataFrame, cfg: RoundConfig) -> pd.DataFrame:
    rows = []
    sectors = {"total": 0, "rural": 1, "urban": 2}
    metrics = {"establishments": 1, "workers": 3}
    for metric, subgroup in metrics.items():
        for sector, sector_code in sectors.items():
            calculated = final.loc[
                (final.State_ID == 0) & (final.District_ID == 0) &
                (final.Sector_code == sector_code) & (final.SUB_GROUP_ID == subgroup) &
                (final.Col_ID == 1), "DATA"
            ]
            expected = float(cfg.official_benchmarks[metric][sector])
            value = float(calculated.iloc[0]) if len(calculated) else np.nan
            difference = value - expected
            # Published factsheet figures are in hundreds, so ±100 is the
            # appropriate comparison tolerance after unit conversion.
            rows.append({
                "Metric": metric, "Sector": sector, "Published_Value": expected,
                "Calculated_Raw_Microdata_Value": value, "Difference": difference,
                "Tolerance": 100.0,
                "Pass_Fail": "PASS" if pd.notna(value) and abs(difference) <= 100 else "FAIL",
                "Reference": "Official ASUSE factsheet/report key aggregate table",
            })
    result = pd.DataFrame(rows)
    result.to_csv(cfg.qa_dir / "qa_official_benchmark.csv", index=False)
    return result


def _derive_year_status(qa_summary: dict[str, int]) -> tuple[str, str]:
    source_blockers = qa_summary.get("missing_required_levels", 0) + qa_summary.get("unresolved_registration_enterprises", 0)
    if source_blockers:
        return "HOLD", "Mandatory source/field or registration classification is unresolved"
    critical_keys = [
        "duplicate_rows", "missing_mapping", "establishment_failures", "worker_failures",
        "ownership_failures", "gva_failures", "registration_failures", "rural_urban_failures",
        "official_benchmark_failures", "merge_failures",
    ]
    if any(qa_summary.get(key, 0) for key in critical_keys):
        return "FAIL", "Source exists but one or more critical calculation/benchmark rules materially fail"
    if qa_summary.get("warning_rules", 0):
        return "WARN", "Only non-critical warning rules remain"
    return "PASS", "All mandatory metrics are computable and all critical rules pass"


def _write_2023_2024_audit_outputs(
    final: pd.DataFrame,
    cfg: RoundConfig,
    selected: dict[str, Path],
    qa_summary: dict[str, int],
    status: str,
    status_reason: str,
) -> None:
    if cfg.survey_round != "2023-2024":
        return
    raw = pd.read_csv(cfg.qa_dir / "qa_detailed.csv")
    level_files = {level.upper(): path.name for level, path in selected.items()}
    source_by_metric = {
        "Establishments": (level_files.get("L02", ""), "L02 / Block 2 / multiplier"),
        "Ownership": (level_files.get("L02", ""), "L02 / Block 2 / item 204"),
        "Workers": (level_files.get("L09", ""), "L09 / Block 8 / item 789"),
        "GVA share": (level_files.get("L08", ""), "L08 / Block 7.1 & 7.2 / items 769, 779"),
        "Registration status": (level_files.get("L02", ""), "L02 / Block 2 / item 227"),
        "Annual emoluments per hired worker": (level_files.get("L10", ""), "L10 + L09 + L03 / items 939, 782-783 / annualization"),
        "Average fixed assets per UE": (level_files.get("L11", ""), "L11 + L02 / item 1019 / UE denominator"),
        "Outstanding loan per UE": (level_files.get("L12", ""), "L12 + L02 / item 1119 / UE denominator"),
    }
    subgroup_metrics = {
        1: "Establishments", 2: "Ownership", 3: "Workers",
        4: "Annual emoluments per hired worker", 5: "Average fixed assets per UE",
        6: "Outstanding loan per UE", 7: "GVA share", 8: "Registration status",
    }
    rows = []
    area_labels = {0: "Total", 1: "Rural", 2: "Urban"}
    for number, row in enumerate(raw.itertuples(index=False), 1):
        sector_text = str(getattr(row, "_4"))
        sector_match = re.search(r"Sector_code=(\d+)", sector_text)
        area = area_labels.get(int(sector_match.group(1)), "") if sector_match else ("Total vs Rural+Urban" if "Total/Rural/Urban" in sector_text else "")
        if not area and sector_text.lower() in {"total", "rural", "urban"}:
            area = sector_text.title()
        category_match = re.search(r"(?:BAC|Category)=([^;]+)", sector_text)
        metric = str(row.metric)
        subgroup_match = re.search(r"SUB_GROUP_ID=(\d+)", metric)
        if subgroup_match:
            metric = subgroup_metrics[int(subgroup_match.group(1))]
        elif metric == "establishments":
            metric = "Establishments"
        elif metric == "workers":
            metric = "Workers"
        elif metric == "% share of sectors in GVA":
            metric = "GVA share"
        if row.rule_name == "OFFICIAL_BENCHMARK_RECONCILIATION":
            source_file, source_level = cfg.volume_i_file.name if hasattr(cfg, "volume_i_file") else "ASUSE_2324_Vol_I.pdf", "Published All-India key aggregate"
        else:
            source_file, source_level = source_by_metric.get(metric, ("Multiple step sources", "Derived final QA"))
        expected_num = pd.to_numeric(pd.Series([row.expected_value]), errors="coerce").iloc[0]
        actual_num = pd.to_numeric(pd.Series([row.actual_value]), errors="coerce").iloc[0]
        difference_num = pd.to_numeric(pd.Series([row.difference]), errors="coerce").iloc[0]
        absolute = abs(difference_num) if pd.notna(difference_num) else np.nan
        relative = 100 * absolute / abs(expected_num) if pd.notna(expected_num) and expected_num != 0 and pd.notna(absolute) else np.nan
        notes = ""
        if row.status == "NOT_CALCULABLE":
            notes = "Zero/no-sample denominator domain; retained as NA and excluded from year failure count."
        elif row.rule_name == "OFFICIAL_BENCHMARK_RECONCILIATION":
            notes = "Independent raw-microdata estimate differs materially from the configured official published benchmark."
        category = category_match.group(1) if category_match else ""
        if metric == "Ownership" and not category:
            category = "Proprietary|Partnership|SHG|Others"
        elif metric == "Registration status" and not category:
            category = "Registered|Unregistered"
        rows.append({
            "year": cfg.survey_round, "rule_id": f"QA2324-{number:06d}", "rule_name": row.rule_name,
            "metric": metric, "geography": row.geography, "rural_urban": area,
            "sector/activity": sector_text, "ownership/registration_category": category,
            "expected_value": row.expected_value, "actual_value": row.actual_value,
            "absolute_difference": absolute, "relative_difference": relative,
            "tolerance": row.tolerance, "severity": "INFO" if row.status == "NOT_CALCULABLE" else "CRITICAL",
            "status": row.status, "source_file": source_file, "source_block/level": source_level,
            "notes": notes,
        })
    detailed = pd.DataFrame(rows)
    detailed.to_csv(cfg.qa_dir / "qa_2023_2024_detailed.csv", index=False)
    detailed[detailed.status == "FAIL"].to_csv(cfg.qa_dir / "qa_2023_2024_failures_only.csv", index=False)

    merge = pd.read_csv(cfg.qa_dir / "join_audit.csv")
    merge.insert(0, "Year", cfg.survey_round)
    merge.to_csv(cfg.qa_dir / "qa_2023_2024_merge_diagnostics.csv", index=False)

    metric_order = [
        "Establishments", "Ownership", "Workers", "Annual emoluments per hired worker",
        "Average fixed assets per UE", "Outstanding loan per UE", "GVA share", "Registration status",
    ]
    metric_summary = detailed.groupby("metric", dropna=False).agg(
        Rules_Checked=("rule_id", "size"), Pass=("status", lambda s: int((s == "PASS").sum())),
        Fail=("status", lambda s: int((s == "FAIL").sum())),
        Not_Calculable=("status", lambda s: int((s == "NOT_CALCULABLE").sum())),
    ).reindex(metric_order, fill_value=0).reset_index()
    metric_summary.insert(0, "Year", cfg.survey_round)
    metric_summary["Mandatory_Metric"] = True
    metric_summary["Critical_Status"] = np.where(metric_summary.Fail > 0, "FAIL", "PASS")
    metric_summary.to_csv(cfg.qa_dir / "qa_2023_2024_metric_summary.csv", index=False)

    pd.DataFrame([{
        "Year": cfg.survey_round, "Acceptance_Status": status, "Reason": status_reason,
        **qa_summary,
    }]).to_csv(cfg.qa_dir / "year_acceptance_status.csv", index=False)


def run_round(root: Path, survey_round: str, settings: dict) -> dict:
    started = time.time()
    inputs = _discover(root, survey_round, settings)
    cfg = RoundConfig(
        root=root, survey_round=survey_round, source_url=settings["source_url"],
        output_year=str(settings["output_year"]), published_date=settings["published_date"],
        multiplier_divisor=float(settings["multiplier_divisor"]),
        district_page_start=int(settings["district_page_start"]), district_page_stop=int(settings["district_page_stop"]),
        raw_stem=settings["raw_stem"], ddi_name=inputs.ddi_file.name,
        official_benchmarks=settings["official_benchmarks"],
    )
    _mkdirs(cfg)
    log = _logger(cfg)
    print(f"\nSELECTED YEAR CONVENTION: {survey_round} -> Year={cfg.output_year}")
    raw_root = _extract(inputs, cfg)
    files, selected = discover_level_files(raw_root)
    missing = _missing_levels(selected, cfg)
    gva_available, gva_source = _validate_gva_source(selected, cfg)
    selected_for_load = selected.copy()
    if not gva_available:
        selected_for_load.pop("l08", None)
        log.error("GVA SOURCE_MISSING / NOT_COMPUTABLE: required L08 Block 7.1 & 7.2 fields=%s", ", ".join(ROUND_FIELDS[survey_round]["l08"]))
    parsed, profiles = load_round_levels(survey_round, selected_for_load, cfg.work_dir / "cache", cfg.multiplier_divisor, log)
    _profile_raw(files, selected, profiles, cfg)
    _phase("PHASE 1 - Input discovery and raw profiling", survey_year=survey_round, files_used=inputs.zip_file.name, levels_found=", ".join(x.upper() for x in sorted(selected)), levels_missing=", ".join(missing.loc[~missing.Present_In_ZIP, "Expected_Level"]), output_file_created=cfg.work_dir / "profiling")

    available_levels = set(parsed)
    master = _mapping_outputs(cfg, inputs, available_levels)
    _phase("PHASES 2-4 - DDI parsing and master mapping", files_used=inputs.ddi_file.name, rows_output=len(master), mapping_status=master.Mapping_Status.value_counts().to_dict(), output_file_created=cfg.mapping_dir)

    required_base = {"l02", "l03", "l09", "l10", "l11", "l12"}
    absent_base = sorted(required_base - set(parsed))
    if absent_base:
        raise RuntimeError(f"Cannot build enterprise estimation base; missing required levels: {absent_base}")
    base = parsed["l02"].copy()
    if base.Enterprise_Key.duplicated().any():
        raise RuntimeError("Ambiguous enterprise key: duplicate L02 records")
    if base.Multiplier.isna().any() or (base.Multiplier <= 0).any():
        raise RuntimeError("Missing, zero, or negative multiplier in L02 enterprise base")
    invalid_registration = base[~base.Registered.astype(str).isin(["1", "2"])][["Enterprise_Key", "Raw_State_Code", "nss_region", "district", "Registered"]].copy()
    invalid_registration["QA_Flag"] = "UNRESOLVED_OFFICIAL_ITEM_227"
    invalid_registration.to_csv(cfg.qa_dir / "qa_unresolved_registration.csv", index=False)
    base.loc[~base.Registered.astype(str).isin(["1", "2"]), "Registered"] = ""

    base, states, districts = _geography(base, cfg, inputs)
    _phase("PHASE 5 - Geography master", rows_input=len(base), states_uts=len(states), observed_districts=len(districts), output_file_created=cfg.mapping_dir)
    base["BAC"] = [_classify_bac_for_round(survey_round, a, b) for a, b in zip(base.Major_NIC_2dig, base.Major_NIC_5dig)]
    base["Ownership_Group"] = base.Ownership_Type.astype(str).map(ownership_group)
    if base.BAC.isna().any():
        raise RuntimeError("Invalid BAC mapping")
    base["Sector_code"] = pd.to_numeric(base.sector, errors="raise").astype(int)
    base["Sector"] = base.Sector_code.map({1: "rural", 2: "urban"})
    _category_mappings(base, cfg)
    base = _enterprise_table(base, parsed, cfg)
    registration_diagnostics(base).assign(Year=survey_round).to_csv(cfg.qa_dir / "qa_registration_diagnostic.csv", index=False)
    _phase("PHASES 6-7 - Enterprise base, multiplier and BAC", rows_input=len(parsed["l02"]), rows_output=len(base), validation_result="PASS", output_file_created=cfg.work_dir / f"ASUSE_{survey_round}_Master_Estimation_Table.parquet")

    estimates = calculate(base)
    skeleton = _skeleton(cfg, states, districts)
    _client_master(skeleton, master, cfg)
    unrounded = _client_output(skeleton, estimates, cfg, round_data=False)
    final = _client_output(skeleton, estimates, cfg)
    rows_by_datapoint = {}
    for subgroup, filename in enumerate(STEP_NAMES, 1):
        step = final[final.SUB_GROUP_ID == subgroup]
        step.to_csv(cfg.output_dir / "steps" / filename, index=False)
        rows_by_datapoint[subgroup] = len(step)
        unavailable = subgroup == 7 and "l08" not in parsed
        _phase(f"PHASE {7 + subgroup} - Datapoint {subgroup}", rows_output=len(step), validation_result="NOT CALCULABLE - L08 MISSING" if unavailable else "CALCULATED", output_file_created=cfg.output_dir / "steps" / filename)

    # QA uses unrounded estimates. Rounding is reserved for client output.
    qa_summary = write_qa(unrounded, master, cfg.qa_dir, 0.01)
    benchmark_qa = _official_benchmark_qa(unrounded, cfg)
    detailed_path = cfg.qa_dir / "qa_detailed.csv"
    detailed = pd.read_csv(detailed_path)
    extra_details = [{
        "rule_name": "MANDATORY_GVA_SOURCE_AVAILABLE", "metric": row.Metric,
        "year": survey_round, "geography": "All domains", "sector/activity": "All BACs",
        "expected_value": "L08 Block 7.1 & 7.2 with required fields",
        "actual_value": row.Source_File or row.Status, "difference": row.Missing_Fields,
        "tolerance": "Not applicable", "status": "PASS" if row.Status == "COMPUTABLE" else "FAIL",
    } for row in gva_source.itertuples(index=False)]
    extra_details.extend({
        "rule_name": "OFFICIAL_BENCHMARK_RECONCILIATION", "metric": row.Metric,
        "year": survey_round, "geography": "India", "sector/activity": row.Sector,
        "expected_value": row.Published_Value, "actual_value": row.Calculated_Raw_Microdata_Value,
        "difference": row.Difference, "tolerance": row.Tolerance, "status": row.Pass_Fail,
    } for row in benchmark_qa.itertuples(index=False))
    pd.concat([detailed, pd.DataFrame(extra_details)], ignore_index=True).to_csv(detailed_path, index=False)
    critical_missing = missing[(missing.Status == "MISSING_CRITICAL") & (missing.Required_For_Datapoint != "None")]
    qa_summary["missing_required_levels"] = len(critical_missing)
    qa_summary["unresolved_registration_enterprises"] = len(invalid_registration)
    qa_summary["official_benchmark_failures"] = int((benchmark_qa.Pass_Fail == "FAIL").sum())
    merge_audit = pd.read_csv(cfg.qa_dir / "join_audit.csv")
    qa_summary["merge_failures"] = int((merge_audit.Status == "REVIEW").sum()) if "Status" in merge_audit else 0
    qa_summary["warning_rules"] = int((pd.read_csv(detailed_path).status == "WARN").sum())
    pd.DataFrame([qa_summary]).to_excel(cfg.qa_dir / "qa_summary.xlsx", index=False)
    duplicate_key = ["State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"]
    duplicate_rows = int(final.duplicated(duplicate_key).sum())
    if duplicate_rows or list(final.columns) != CLIENT_COLUMNS:
        raise RuntimeError(f"Invalid final structure: duplicates={duplicate_rows}; columns={list(final.columns)}")

    acceptance_status, status_reason = _derive_year_status(qa_summary)
    accepted = acceptance_status in {"PASS", "WARN"}
    status_frame = pd.DataFrame([{
        "Survey_Year": survey_round, "Acceptance_Status": acceptance_status, **qa_summary,
        "Delivery_Note": status_reason,
    }])
    status_frame.to_csv(cfg.qa_dir / "acceptance_status.csv", index=False)
    _write_2023_2024_audit_outputs(final, cfg, selected, qa_summary, acceptance_status, status_reason)
    out_csv = cfg.output_dir / f"ASUSE_{survey_round}_All_India_State_District_Client_Final.csv"
    out_xlsx = cfg.output_dir / f"ASUSE_{survey_round}_All_India_State_District_Client_Final.xlsx"
    final.to_csv(out_csv, index=False)
    with pd.ExcelWriter(out_xlsx, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_urls": False}}) as writer:
        final.to_excel(writer, index=False)

    log.info("Round=%s rows=%s accepted=%s QA=%s runtime=%.1fs", survey_round, len(final), accepted, qa_summary, time.time() - started)
    print("\n" + "=" * 72)
    print(f"SURVEY YEAR: {survey_round}")
    print(f"RAW ZIP USED: {inputs.zip_file.name}")
    print(f"DDI USED: {inputs.ddi_file.name}")
    print(f"LEVELS FOUND: {', '.join(x.upper() for x in sorted(selected))}")
    print(f"LEVELS MISSING: {', '.join(missing.loc[~missing.Present_In_ZIP, 'Expected_Level']) or 'None'}")
    print(f"MAPPING STATUS: {master.Mapping_Status.value_counts().to_dict()}")
    print(f"ROWS GENERATED BY DATAPOINT: {rows_by_datapoint}")
    print(f"QA PASS/FAIL SUMMARY: {acceptance_status} {qa_summary}")
    print(f"FINAL OUTPUT PATH: {out_csv}")
    return {"round": survey_round, "accepted": accepted, "status": acceptance_status, "final": final, "csv": out_csv, "qa": qa_summary}


def run_multiyear(root: str | Path | None = None, survey_rounds: list[str] | None = None) -> list[dict]:
    workspace = Path(root or Path.cwd()).resolve()
    settings_path = workspace / "config/surveys.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    rounds = survey_rounds or ["2022-2023", "2023-2024"]
    results = []
    for survey_round in rounds:
        if survey_round == "2025":
            raise ValueError("Use the established 2025 runner for survey round 2025")
        results.append(run_round(workspace, survey_round, settings[survey_round]))

    status_path = workspace / "output/multiyear_acceptance_status.csv"
    if len(results) == 2 and all(result["accepted"] for result in results):
        first_columns = list(results[0]["final"].columns)
        if any(list(result["final"].columns) != first_columns for result in results):
            raise RuntimeError("Year-wise schemas differ; multi-year append refused")
        combined = pd.concat([result["final"] for result in results], ignore_index=True)
        duplicate_key = ["Year", "State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"]
        if combined.duplicated(duplicate_key).any():
            raise RuntimeError("Duplicate multi-year client keys; append refused")
        combined_path = workspace / "output/ASUSE_2022-2024_MultiYear_Client_Final.csv"
        combined.to_csv(combined_path, index=False)
        pd.DataFrame([{"Acceptance_Status": "PASS", "Combined_File_Generated": True, "Output_Path": str(combined_path)}]).to_csv(status_path, index=False)
    else:
        failed = [result["round"] for result in results if not result["accepted"]]
        statuses = {result["round"]: result["status"] for result in results}
        overall_status = "FAIL" if "FAIL" in statuses.values() else "HOLD"
        pd.DataFrame([{
            "Acceptance_Status": overall_status, "Combined_File_Generated": False,
            "Failed_Years": ", ".join(failed),
            "Year_Statuses": "; ".join(f"{year}={value}" for year, value in statuses.items()),
            "Reason": "At least one yearly pipeline has a missing-source HOLD or material critical FAIL",
        }]).to_csv(status_path, index=False)
        print(f"MULTI-YEAR FILE NOT GENERATED: critical failure in {', '.join(failed)}")
    return results
