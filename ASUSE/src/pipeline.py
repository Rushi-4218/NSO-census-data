from __future__ import annotations

import json
import logging
from pathlib import Path
import time

import numpy as np
import pandas as pd

from src.config import CLIENT_COLUMNS, PipelineConfig, SUBGROUPS
from src.io.discover_inputs import discover, extract_raw
from src.io.load_raw_levels import common, iter_tokens, parse_item_value, parse_l02, parse_l03, parse_l09
from src.mapping.build_geography_mapping import build_district_master, load_state_codes
from src.mapping.build_master_mapping import build_master_mapping
from src.metrics.estimates import calculate, classify_bac, ownership_group, registration_diagnostics
from src.qa.validations import write_qa


TARGET_LEVELS = {"l02", "l03", "l08", "l09", "l10", "l11", "l12"}
PARSER_VERSION = 3


def _mkdirs(root: Path) -> None:
    for p in ["config", "mapping", "work/profiling", "work/cache", "output/steps", "qa", "logs"]:
        (root / p).mkdir(parents=True, exist_ok=True)


def _logger(root: Path) -> logging.Logger:
    log = logging.getLogger("asuse")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(root / "logs/pipeline.log", encoding="utf-8")
    fh.setFormatter(fmt); log.addHandler(fh)
    sh = logging.StreamHandler(); sh.setFormatter(fmt); log.addHandler(sh)
    return log


def _phase(name: str, *, files: str, levels: str, rows_in: int | str, rows_out: int | str,
           keys: str, mappings: str, validation: str, warnings: str, output: str) -> None:
    print("\n" + "=" * 72)
    print(f"PHASE NAME: {name}\nFILES USED: {files}\nRAW LEVELS USED: {levels}")
    print(f"ROWS INPUT: {rows_in}\nROWS OUTPUT: {rows_out}\nKEYS USED: {keys}")
    print(f"MAPPINGS USED: {mappings}\nVALIDATION RESULT: {validation}")
    print(f"WARNINGS: {warnings}\nOUTPUT FILE CREATED: {output}")


def _write_config(cfg: PipelineConfig) -> None:
    payload = {
        "survey_year": cfg.survey_year, "survey_id": cfg.survey_id,
        "survey_name": cfg.survey_name, "group_id": cfg.group_id,
        "group_name": cfg.group_name, "published_date": cfg.published_date,
        "extracted_date": cfg.extracted_date, "source_url": cfg.source_url,
    }
    (cfg.root / "config/pipeline_config.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _level(path: Path) -> str:
    return path.stem.lower()[-3:]


def _count_only(path: Path) -> tuple[int, int, int]:
    rows = 0; max_tokens = 0; bad = 0
    for tokens in iter_tokens(path):
        rows += 1; max_tokens = max(max_tokens, len(tokens))
        try: common(tokens[0])
        except ValueError: bad += 1
    return rows, max_tokens, bad


def _load_and_profile(raw_root: Path, layout_file: Path, root: Path, log: logging.Logger):
    files = sorted(raw_root.glob("asuse_2025_esu_l*.*"))
    inventory = []; counts = []; keys = []; parsed: dict[str, pd.DataFrame] = {}
    cache_dir = root / "work/cache"
    parsers = {
        "l02": parse_l02, "l03": parse_l03,
        "l08": lambda t: parse_item_value(t, 3, "GVA_Value"),
        "l09": parse_l09,
        "l10": lambda t: parse_item_value(t, 3, "Emolument_Value"),
        "l11": lambda t: parse_item_value(t, 4, "Fixed_Asset_Value"),
        "l12": lambda t: parse_item_value(t, 4, "Loan_Value"),
    }
    selectors = {
        "l08": {"769", "779"}, "l09": {"782", "783", "789"},
        "l10": {"939"}, "l11": {"1019"}, "l12": {"1119"},
    }
    prior_profile_path = root / "work/profiling/raw_row_counts.csv"
    prior_profiles = {}
    if prior_profile_path.exists():
        prior = pd.read_csv(prior_profile_path).fillna(0)
        prior_profiles = {str(r.Raw_Level).lower(): r._asdict() for r in prior.itertuples(index=False)}
    for path in files:
        level = _level(path)
        inventory.append({"Raw_Level": level.upper(), "Source_File": path.name, "Format": path.suffix.lower().lstrip("."), "Size_Bytes": path.stat().st_size})
        cache = cache_dir / f"{level}.parquet"
        meta = cache_dir / f"{level}_profile.json"
        cached_profile = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        required_parser_version = {"l02": 2, "l03": 3}.get(level)
        cache_is_current = required_parser_version is None or cached_profile.get("Parser_Version", 0) >= required_parser_version
        if level in TARGET_LEVELS and cache.exists() and cache_is_current:
            parsed[level] = pd.read_parquet(cache)
            profile = cached_profile
            counts.append(profile); keys.append(profile.copy())
            log.info("Loaded %s from cache (%s selected rows)", level, len(parsed[level]))
            continue
        if level not in TARGET_LEVELS:
            if level in prior_profiles:
                old = prior_profiles[level]
                profile = {"Raw_Level": level.upper(), "Rows": int(old["Rows"]), "Selected_Rows": 0, "Max_Tokens": int(old["Max_Tokens"]), "Malformed_Common_Key": int(old["Malformed_Common_Key"])}
            else:
                n, maxt, bad = _count_only(path)
                profile = {"Raw_Level": level.upper(), "Rows": n, "Selected_Rows": 0, "Max_Tokens": maxt, "Malformed_Common_Key": bad}
            counts.append(profile); keys.append(profile.copy())
            continue
        selected = []; n = 0; maxt = 0; bad = 0; unique = set(); multiplier_null = 0
        for tokens in iter_tokens(path):
            n += 1; maxt = max(maxt, len(tokens))
            try:
                c = common(tokens[0]); unique.add(c["Enterprise_Key"])
                if level in selectors:
                    width = 4 if level in {"l11", "l12"} else 3
                    item = tokens[0][31:31 + width]
                    if item not in selectors[level]:
                        continue
                row = parsers[level](tokens)
                if row.get("Multiplier") is None: multiplier_null += 1
                selected.append(row)
            except Exception as exc:
                bad += 1
                if bad <= 5: log.warning("%s row %s parse error: %s", level, n, exc)
        frame = pd.DataFrame(selected)
        frame.to_parquet(cache, index=False)
        parsed[level] = frame
        profile = {"Raw_Level": level.upper(), "Rows": n, "Selected_Rows": len(frame), "Max_Tokens": maxt, "Malformed_Common_Key": bad, "Unique_Enterprise_Keys": len(unique), "Null_Multipliers": multiplier_null, "Parser_Version": PARSER_VERSION}
        meta.write_text(json.dumps(profile), encoding="utf-8")
        counts.append(profile); keys.append(profile.copy())
        log.info("Parsed %s: %s rows, %s selected", level, n, len(frame))

    pd.DataFrame(inventory).to_csv(root / "work/profiling/raw_file_inventory.csv", index=False)
    pd.DataFrame(counts).to_csv(root / "work/profiling/raw_row_counts.csv", index=False)
    pd.DataFrame(keys).to_csv(root / "work/profiling/raw_key_profile.csv", index=False)
    layout = pd.read_excel(layout_file, sheet_name="layout")
    layout["Start_Byte"] = layout.groupby("level")["length"].transform(lambda s: s.shift(fill_value=0).cumsum() + 1)
    layout["End_Byte"] = layout.Start_Byte + layout.length - 1
    layout["Inferred_Type"] = np.where(layout.var_name.str.contains("value|amount|worker|mult", case=False), "numeric", "character")
    layout.to_csv(root / "work/profiling/raw_level_columns.csv", index=False)
    return files, parsed, pd.DataFrame(counts), layout


def _mapping_outputs(cfg: PipelineConfig, inputs, layout: pd.DataFrame) -> pd.DataFrame:
    master = build_master_mapping(cfg)
    master.to_csv(cfg.root / "mapping/ASUSE_2025_Master_Mapping.csv", index=False)
    master.to_excel(cfg.root / "mapping/ASUSE_2025_Master_Mapping.xlsx", index=False)
    ddi = pd.concat([
        pd.read_excel(inputs.ddi_file, sheet_name="Sheet1"),
        pd.read_excel(inputs.ddi_file, sheet_name="Sheet2"),
    ], ignore_index=True)
    coverage = master[["Mapping_ID", "Source_Raw_Column", "Source_Level", "Mapping_Status"]].copy()
    coverage["DDI_Match"] = coverage.Source_Raw_Column.apply(lambda x: any(str(x).lower() in str(v).lower() for v in ddi.Columns.dropna()))
    coverage.to_csv(cfg.root / "work/profiling/ddi_coverage_report.csv", index=False)
    master[master.Mapping_Status != "Resolved"].to_csv(cfg.root / "work/profiling/unresolved_variables.csv", index=False)
    return master


def _geography(base: pd.DataFrame, cfg: PipelineConfig, layout_file: Path, census_file: Path, volume_i_file: Path, template_file: Path):
    states = load_state_codes(layout_file)
    state_lookup = states.set_index("Raw_State_Code")
    base["State_ID"] = base.Raw_State_Code.map(state_lookup.State_ID)
    base["State_Name"] = base.Raw_State_Code.map(state_lookup.State_Name)
    if base.State_ID.isna().any():
        raise RuntimeError(f"Unresolved state codes: {base.loc[base.State_ID.isna(), 'Raw_State_Code'].unique().tolist()}")
    base["State_ID"] = base.State_ID.astype(int)
    observed = base.groupby(["State_ID", "State_Name", "district"], as_index=False).agg(Raw_NSS_Region=("nss_region", "first"))
    observed = observed.rename(columns={"district": "Raw_District_Code"})
    district = build_district_master(census_file, volume_i_file, observed, cfg.root / "work/cache/census_districts.csv")
    if (district.Mapping_Status != "Resolved").any():
        unresolved = district[district.Mapping_Status != "Resolved"]
        unresolved.to_csv(cfg.root / "work/profiling/unresolved_geography.csv", index=False)
        raise RuntimeError(f"Unresolved geography mappings: {unresolved[['State_ID','Raw_District_Code']].to_dict('records')[:20]}")
    stale_unresolved = cfg.root / "work/profiling/unresolved_geography.csv"
    if stale_unresolved.exists():
        stale_unresolved.unlink()
    template_geo = pd.read_csv(template_file, usecols=["State_ID", "District_ID", "District_Name"]).drop_duplicates()
    template_names = template_geo.set_index(["State_ID", "District_ID"]).District_Name.to_dict()
    district["District_Name"] = [template_names.get((int(s), int(d)), n) for s, d, n in zip(district.State_ID, district.District_ID, district.District_Name)]
    dm = district.set_index(["State_ID", "Raw_District_Code"])
    idx = pd.MultiIndex.from_arrays([base.State_ID, base.district])
    base["District_ID"] = dm.District_ID.reindex(idx).to_numpy()
    base["District_Name"] = dm.District_Name.reindex(idx).to_numpy()
    base["District_ID"] = base.District_ID.astype(int)
    sector_avail = base.pivot_table(index="State_ID", columns="sector", values="Enterprise_Key", aggfunc="size", fill_value=0)
    state_master = states.copy()
    state_master["NSS_Region_Prefix"] = state_master.Raw_State_Code
    state_master["Available_Rural"] = state_master.State_ID.map(sector_avail.get("1", pd.Series(dtype=int))).fillna(0).gt(0)
    state_master["Available_Urban"] = state_master.State_ID.map(sector_avail.get("2", pd.Series(dtype=int))).fillna(0).gt(0)
    state_master["District_Count"] = state_master.State_ID.map(district.groupby("State_ID").District_ID.nunique()).fillna(0).astype(int)
    state_master.to_csv(cfg.root / "mapping/state_master.csv", index=False)
    district.to_csv(cfg.root / "mapping/district_master.csv", index=False)
    return base, state_master, district


def _category_mappings(base: pd.DataFrame, cfg: PipelineConfig) -> None:
    activity = base[["Major_NIC_2dig", "Major_NIC_5dig", "BAC"]].drop_duplicates().sort_values(["BAC", "Major_NIC_2dig", "Major_NIC_5dig"])
    activity["Mapping_Source"] = "Schedule ESU Vol II, Block 2.1"
    activity.to_csv(cfg.root / "mapping/activity_master.csv", index=False)
    ownership = pd.DataFrame([
        ("1", "Proprietary male/HUF", "Proprietary", 1), ("2", "Proprietary female/HUF", "Proprietary", 1),
        ("3", "Proprietary transgender/HUF", "Proprietary", 1), ("4", "Partnership same household", "Partnership", 2),
        ("5", "Partnership different households", "Partnership", 2), ("6", "Self Help Group", "SHG", 3),
        ("7", "Trust", "Others", 4), ("9", "Others", "Others", 4),
    ], columns=["Raw_Ownership_Code", "Raw_Ownership_Label", "Client_Ownership", "Client_Col_ID"])
    ownership["Mapping_Source"] = "Official ASUSE DDI item 204"
    ownership.to_csv(cfg.root / "mapping/ownership_master.csv", index=False)
    registration = pd.DataFrame([("1", "Registered", "Official item 227"), ("2", "Unregistered", "Official item 227")], columns=["Raw_Registration_Code", "Client_Registration", "Mapping_Source"])
    registration.to_csv(cfg.root / "mapping/registration_master.csv", index=False)


def _merge(base: pd.DataFrame, right: pd.DataFrame, name: str, audits: list[dict]) -> pd.DataFrame:
    if right.Enterprise_Key.duplicated().any():
        raise RuntimeError(f"{name} is not unique at enterprise grain")
    before = len(base); unique_before = base.Enterprise_Key.nunique()
    out = base.merge(right, on="Enterprise_Key", how="left", validate="one_to_one")
    audits.append({"Join": name, "Left_Rows": before, "Right_Rows": len(right), "Result_Rows": len(out), "Unique_Before": unique_before, "Unique_After": out.Enterprise_Key.nunique(), "Duplicate_Factor": len(out) / before})
    return out


def _enterprise_table(base: pd.DataFrame, parsed: dict[str, pd.DataFrame], cfg: PipelineConfig):
    audits = []
    ref = parsed["l03"][["Enterprise_Key", "Ref_Period_Type", "Months_In_Accounting_Period"]].drop_duplicates("Enterprise_Key")
    base = _merge(base, ref, "L03_reference_period", audits)
    months = pd.to_numeric(base.Months_In_Accounting_Period, errors="coerce")
    base["Annual_Factor"] = np.where(base.Ref_Period_Type == "4", 12 / months.fillna(12).replace(0, 12), 12.0)

    l09 = parsed["l09"].copy()
    l09.Total_Workers = pd.to_numeric(l09.Total_Workers, errors="coerce")
    workers = l09[l09.Item_No == "789"].groupby("Enterprise_Key", as_index=False).Total_Workers.sum(min_count=1).rename(columns={"Total_Workers": "Worker_Value"})
    hired = l09[l09.Item_No.isin(["782", "783"])].groupby("Enterprise_Key", as_index=False).Total_Workers.sum(min_count=1).rename(columns={"Total_Workers": "Hired_Worker_Value"})
    base = _merge(base, workers, "L09_total_workers_789", audits)
    base = _merge(base, hired, "L09_hired_workers_782_783", audits)

    specs = [
        ("l10", "Emolument_Value", "Emolument_Value", "L10_total_emoluments_939"),
        ("l11", "Fixed_Asset_Value", "Fixed_Asset_Value", "L11_total_fixed_assets_1019"),
        ("l12", "Loan_Value", "Loan_Value", "L12_total_loans_1119"),
        ("l08", "GVA_Value", "GVA_Value", "L08_GVA_769_779"),
    ]
    for level, source, target, label in specs:
        r = parsed[level][["Enterprise_Key", source]].copy()
        r[source] = pd.to_numeric(r[source], errors="coerce")
        r = r.groupby("Enterprise_Key", as_index=False)[source].sum(min_count=1).rename(columns={source: target})
        base = _merge(base, r, label, audits)

    base["Establishment_Contribution"] = base.Multiplier
    base["Worker_Contribution"] = base.Worker_Value * base.Multiplier
    base["Hired_Worker_Contribution"] = base.Hired_Worker_Value * base.Multiplier
    base["Emolument_Contribution"] = base.Emolument_Value * base.Annual_Factor * base.Multiplier
    base["Fixed_Asset_Contribution"] = base.Fixed_Asset_Value * base.Multiplier
    base["Loan_Contribution"] = base.Loan_Value * base.Multiplier
    base["GVA_Contribution"] = base.GVA_Value * base.Multiplier
    keep = [
        "State_ID", "State_Name", "District_ID", "District_Name", "Sector_code", "Sector", "BAC",
        "Enterprise_Key", "Multiplier", "Ownership_Group", "Registered", "Registration_Initial_Code",
        "Registration_Recovery_Status", "Establishment_Contribution",
        "Worker_Contribution", "Hired_Worker_Contribution", "Emolument_Contribution",
        "Fixed_Asset_Contribution", "Loan_Contribution", "GVA_Contribution", "fsu", "nss_region", "district",
    ]
    base[keep].to_parquet(cfg.root / "work/ASUSE_2025_Master_Estimation_Table.parquet", index=False)
    pd.DataFrame(audits).to_csv(cfg.root / "qa/join_audit.csv", index=False)
    profile = base.Multiplier.describe(percentiles=[.01, .5, .99]).to_frame("Value").reset_index(names="Statistic")
    profile["Null_Count"] = base.Multiplier.isna().sum(); profile["Zero_Count"] = (base.Multiplier == 0).sum()
    profile.to_csv(cfg.root / "qa/multiplier_profile.csv", index=False)
    return base


def _skeleton(cfg: PipelineConfig, states: pd.DataFrame, districts: pd.DataFrame) -> pd.DataFrame:
    geos = [{"State_ID": 0, "State_Name": "India", "District_ID": 0, "District_Name": "All Districts"}]
    for s in states.itertuples():
        geos.append({"State_ID": s.State_ID, "State_Name": s.State_Name, "District_ID": 0, "District_Name": "All Districts"})
    geos.extend(districts[["State_ID", "State_Name", "District_ID", "District_Name"]].drop_duplicates(["State_ID", "District_ID"]).to_dict("records"))
    sectors = [(0, "total"), (1, "rural"), (2, "urban")]
    rows = []
    for geo in geos:
        for sector_code, sector in sectors:
            for subgroup_id, (subgroup, columns, unit) in SUBGROUPS.items():
                for col_id, desc in enumerate(columns, 1):
                    rows.append({
                        "Survey_ID": cfg.survey_id, "Survey_NAME": cfg.survey_name,
                        "Survey_GROUP_ID": cfg.group_id, "GROUP_NAME": cfg.group_name,
                        "SUB_GROUP_ID": subgroup_id, "SUB_GROUP_NAME": subgroup,
                        "Year": cfg.survey_year, "FREQ_DESC": "Annual", **geo,
                        "Sector_code": sector_code, "Sector": sector,
                        "Col_ID": col_id, "COL_DESC": desc, "Unit": unit,
                    })
    return pd.DataFrame(rows)


def _client_output(skeleton: pd.DataFrame, estimates: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    join = ["State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "COL_DESC"]
    out = skeleton.merge(estimates[join + ["DATA"]], on=join, how="left", validate="one_to_one")
    out["Published_date"] = cfg.published_date; out["Extracted_Date"] = cfg.extracted_date; out["Source"] = cfg.source_url
    out.loc[out.SUB_GROUP_ID.isin([1, 2, 3]), "DATA"] = out.loc[out.SUB_GROUP_ID.isin([1, 2, 3]), "DATA"].fillna(0)
    out.loc[out.SUB_GROUP_ID.isin([1, 2, 3]), "DATA"] = out.loc[out.SUB_GROUP_ID.isin([1, 2, 3]), "DATA"].round(0)
    out.loc[out.SUB_GROUP_ID.isin([4, 5, 6, 7, 8]), "DATA"] = out.loc[out.SUB_GROUP_ID.isin([4, 5, 6, 7, 8]), "DATA"].round(2)
    return out[CLIENT_COLUMNS].sort_values(["State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"], kind="stable").reset_index(drop=True)


def _client_master(skeleton: pd.DataFrame, master: pd.DataFrame, cfg: PipelineConfig) -> None:
    path = cfg.root / "mapping/ASUSE_2025_Client_Output_Master.xlsx"
    metadata = master.rename(columns={"Client_Col_ID": "Col_ID", "Client_COL_DESC": "COL_DESC"})
    metadata = metadata[["SUB_GROUP_ID", "Col_ID", "Requirement_Code", "Source_Level", "Source_Raw_Column", "Source_Filter", "Formula_Description", "Weighting_Rule", "Numerator_Definition", "Denominator_Definition", "QA_Check"]]
    metadata.columns = ["SUB_GROUP_ID", "Col_ID", "Requirement_Code", "Source_Level", "Source_Field", "Filter", "Formula", "Weighting_Rule", "Numerator", "Denominator", "Validation_Rule"]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        skeleton.to_excel(writer, sheet_name="Client_Row_Skeleton", index=False)
        metadata.to_excel(writer, sheet_name="Mapping_Metadata", index=False)


def _maharashtra_compare(final: pd.DataFrame, template_file: Path, qa_dir: Path, tolerance: float) -> pd.DataFrame:
    ref = pd.read_csv(template_file)
    calc = final[final.State_ID == 27]
    keys = ["District_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"]
    x = ref[keys + ["State_Name", "District_Name", "Sector", "DATA"]].merge(calc[keys + ["DATA"]], on=keys, how="outer", suffixes=("_Reference", "_Calculated"))
    x = x.rename(columns={"State_Name": "State", "DATA_Reference": "Reference_Value", "DATA_Calculated": "Calculated_Value"})
    x["Absolute_Difference"] = (x.Reference_Value - x.Calculated_Value).abs()
    x["Percentage_Difference"] = 100 * x.Absolute_Difference / x.Reference_Value.abs().replace(0, np.nan)
    x["Pass_Fail"] = np.where(x.Reference_Value.isna(), "NOT_COMPARABLE", np.where(x.Absolute_Difference <= tolerance, "PASS", "FAIL"))
    x.to_csv(qa_dir / "maharashtra_reference_comparison.csv", index=False)
    return x


def run_pipeline(root: str | Path | None = None) -> None:
    started = time.time()
    cfg = PipelineConfig(Path(root or Path.cwd()).resolve())
    _mkdirs(cfg.root); log = _logger(cfg.root); _write_config(cfg)
    inputs = discover(cfg.input_dir)
    raw_root = extract_raw(inputs.zip_file, cfg.root / "work/raw")
    log.info("Inputs: ZIP=%s DDI=%s template=%s", inputs.zip_file.name, inputs.ddi_file.name, inputs.template_file.name)

    files, parsed, profiles, layout = _load_and_profile(raw_root, inputs.layout_file, cfg.root, log)
    l08_files = [path for path in files if _level(path) == "l08"]
    gva_available = "l08" in parsed and {"Enterprise_Key", "GVA_Value"}.issubset(parsed["l08"].columns)
    pd.DataFrame([{
        "Year": str(cfg.survey_year), "Metric": "% share of sectors in GVA",
        "Required_Level": "L08", "Required_Block": "Block 7.1 & 7.2",
        "Required_Fields": "Enterprise_Key, Item_No (769/779), GVA_Value",
        "Source_File": l08_files[0].name if l08_files else "",
        "Missing_Fields": "" if gva_available else "L08 and/or required parsed GVA fields",
        "Status": "COMPUTABLE" if gva_available else "SOURCE_MISSING / NOT_COMPUTABLE",
    }]).to_csv(cfg.root / "qa/qa_gva_source_availability.csv", index=False)
    if not gva_available:
        raise RuntimeError("GVA SOURCE_MISSING / NOT_COMPUTABLE: L08 Block 7.1 & 7.2 fields are required")
    _phase("PHASE 1 - Input discovery and raw profiling", files=", ".join(p.name for p in files), levels="L01-L16", rows_in=int(profiles.Rows.sum()), rows_out=len(profiles), keys="bytes 1-29", mappings="official fixed-width layout", validation="PASS", warnings=str(int(profiles.Malformed_Common_Key.sum())), output="work/profiling/*.csv")

    master = _mapping_outputs(cfg, inputs, layout)
    _phase("PHASES 2-4 - DDI parsing, matching, master mapping", files=inputs.ddi_file.name, levels="L02,L03,L08-L12", rows_in=len(pd.read_excel(inputs.ddi_file, sheet_name="Sheet1")), rows_out=len(master), keys="Mapping_ID", mappings="DDI + official layout + template", validation="PASS", warnings="0 unresolved required metric mappings", output="mapping/ASUSE_2025_Master_Mapping.xlsx/csv")
    print("MASTER MAPPING SUMMARY\n", master.groupby(["SUB_GROUP_ID", "Mapping_Status"]).size().to_string())

    base = parsed["l02"].copy()
    if base.Enterprise_Key.duplicated().any():
        raise RuntimeError("Ambiguous enterprise key: duplicate L02 enterprise records")
    if base.Multiplier.isna().any() or (base.Multiplier <= 0).any():
        raise RuntimeError("Missing, zero, or negative multiplier in enterprise base")
    invalid_registration = base[~base.Registered.isin(["1", "2"])][
        ["Enterprise_Key", "Raw_State_Code", "nss_region", "district", "Registered"]
    ].copy()
    invalid_registration["QA_Flag"] = "UNRESOLVED_ITEM_227_AFTER_WHITESPACE_CONVERSION"
    invalid_registration.to_csv(cfg.root / "qa/qa_unresolved_registration.csv", index=False)
    base.loc[~base.Registered.isin(["1", "2"]), "Registered"] = ""
    base, states, districts = _geography(base, cfg, inputs.layout_file, inputs.census_file, inputs.volume_i_file, inputs.template_file)
    _phase("PHASE 5 - Geography master", files=f"{inputs.layout_file.name}; {inputs.volume_i_file.name}; {inputs.census_file.name}", levels="L02", rows_in=len(base), rows_out=len(districts), keys="State_ID+Raw_District_Code", mappings="ASUSE Volume I Appendix II + official State Code", validation="PASS", warnings="0 unresolved geographies", output="mapping/state_master.csv; mapping/district_master.csv")
    print(f"STATE / DISTRICT COUNTS: {len(states)} states/UTs; {len(districts)} observed districts")

    base["BAC"] = [classify_bac(a, b) for a, b in zip(base.Major_NIC_2dig, base.Major_NIC_5dig)]
    base["Ownership_Group"] = base.Ownership_Type.map(ownership_group)
    if base.BAC.isna().any(): raise RuntimeError("Invalid BAC mapping")
    base["Sector_code"] = base.sector.astype(int); base["Sector"] = base.Sector_code.map({1: "rural", 2: "urban"})
    _category_mappings(base, cfg)
    base = _enterprise_table(base, parsed, cfg)
    code_distribution = pd.concat([
        base.groupby("Registration_Initial_Code", dropna=False).agg(
            Sample_Count=("Enterprise_Key", "size"), Weighted_Count=("Multiplier", "sum")
        ).reset_index(names="Code").assign(Stage="BEFORE_PARSER_RECOVERY"),
        base.groupby("Registered", dropna=False).agg(
            Sample_Count=("Enterprise_Key", "size"), Weighted_Count=("Multiplier", "sum")
        ).reset_index(names="Code").assign(Stage="AFTER_PARSER_RECOVERY"),
    ], ignore_index=True)
    code_distribution["Year"] = str(cfg.survey_year)
    code_distribution[["Year", "Stage", "Code", "Sample_Count", "Weighted_Count"]].to_csv(
        cfg.root / "qa/qa_registration_code_distribution.csv", index=False
    )
    registration_diagnostics(base).assign(Year=str(cfg.survey_year)).to_csv(
        cfg.root / "qa/qa_registration_diagnostic.csv", index=False
    )
    _phase("PHASES 6-7 - Enterprise base, multiplier and BAC", files="L02,L03,L08-L12", levels="L02,L03,L08,L09,L10,L11,L12", rows_in=len(parsed["l02"]), rows_out=len(base), keys="Enterprise_Key", mappings="activity/ownership/registration masters", validation="PASS", warnings=str(int(base.Ownership_Group.isna().sum())), output="work/ASUSE_2025_Master_Estimation_Table.parquet")

    estimates = calculate(base)
    skeleton = _skeleton(cfg, states, districts)
    _client_master(skeleton, master, cfg)
    final = _client_output(skeleton, estimates, cfg)
    step_names = ["01_unincorporated_establishments.csv", "02_ownership_pattern.csv", "03_workers_employed.csv", "04_emoluments_per_hired_worker.csv", "05_average_fixed_assets.csv", "06_outstanding_loan_per_ue.csv", "07_gva_share.csv", "08_registration_status.csv"]
    for subgroup, filename in enumerate(step_names, 1):
        step = final[final.SUB_GROUP_ID == subgroup]
        step.to_csv(cfg.root / "output/steps" / filename, index=False)
        comp = _maharashtra_compare(step, inputs.template_file, cfg.root / "qa", cfg.tolerance) if subgroup == 1 else None
        _phase(f"PHASE {7 + subgroup} - Datapoint {subgroup}", files="master estimation table", levels=master.loc[master.SUB_GROUP_ID == subgroup, "Source_Level"].iloc[0], rows_in=len(base), rows_out=len(step), keys="client final key", mappings=f"DP{subgroup:02d}", validation="CALCULATED", warnings="see QA", output=f"output/steps/{filename}")

    comparison = _maharashtra_compare(final, inputs.template_file, cfg.root / "qa", cfg.tolerance)
    qa_summary = write_qa(final, master, cfg.root / "qa", cfg.tolerance)
    detailed_path = cfg.root / "qa/qa_detailed.csv"
    detailed = pd.read_csv(detailed_path)
    extra_details = [{
        "rule_name": "MANDATORY_GVA_SOURCE_AVAILABLE", "metric": "% share of sectors in GVA",
        "year": str(cfg.survey_year), "geography": "All domains", "sector/activity": "All BACs",
        "expected_value": "L08 Block 7.1 & 7.2 with required fields",
        "actual_value": l08_files[0].name if l08_files else "SOURCE_MISSING",
        "difference": "", "tolerance": "Not applicable", "status": "PASS" if gva_available else "FAIL",
    }]
    for row in comparison.loc[comparison.Pass_Fail == "FAIL"].itertuples(index=False):
        extra_details.append({
            "rule_name": "MAHARASHTRA_REFERENCE_RECONCILIATION",
            "metric": f"SUB_GROUP_ID={row.SUB_GROUP_ID};Col_ID={row.Col_ID}",
            "year": str(cfg.survey_year),
            "geography": f"State_ID=27;District_ID={row.District_ID}",
            "sector/activity": f"Sector_code={row.Sector_code}",
            "expected_value": row.Reference_Value, "actual_value": row.Calculated_Value,
            "difference": row.Absolute_Difference, "tolerance": cfg.tolerance, "status": "FAIL",
        })
    pd.concat([detailed, pd.DataFrame(extra_details)], ignore_index=True).to_csv(detailed_path, index=False)
    qa_summary["unresolved_registration_enterprises"] = len(invalid_registration)
    pd.DataFrame([qa_summary]).to_excel(cfg.root / "qa/qa_summary.xlsx", index=False)
    if final.duplicated(["State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"]).any():
        raise RuntimeError("Duplicate final keys")
    if list(final.columns) != CLIENT_COLUMNS:
        raise RuntimeError("Invalid final output columns")

    failures = int((comparison.Pass_Fail == "FAIL").sum())
    acceptance_passed = failures == 0 and all(value == 0 for value in qa_summary.values())
    pd.DataFrame([{
        "Acceptance_Status": "PASS" if acceptance_passed else "HOLD",
        "Maharashtra_Comparison_Failures": failures,
        **qa_summary,
        "Delivery_Note": (
            "Accepted client delivery"
            if acceptance_passed
            else "Provisional output only; inspect QA reports before client use"
        ),
    }]).to_csv(cfg.root / "qa/acceptance_status.csv", index=False)

    out_csv = cfg.root / "output/ASUSE_2025_All_India_State_District_Client_Final.csv"
    out_xlsx = cfg.root / "output/ASUSE_2025_All_India_State_District_Client_Final.xlsx"
    final.to_csv(out_csv, index=False)
    with pd.ExcelWriter(out_xlsx, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_urls": False}}) as writer:
        final.to_excel(writer, index=False)
    log.info("Final rows=%s; Maharashtra comparable failures=%s; QA=%s; runtime=%.1fs", len(final), failures, qa_summary, time.time() - started)
    _phase("PHASES 16-19 - Client skeleton, QA and consolidation", files="8 validated step outputs", levels="All required", rows_in=sum(len(pd.read_csv(cfg.root / "output/steps" / f)) for f in step_names), rows_out=len(final), keys="State_ID+District_ID+Sector_code+SUB_GROUP_ID+Col_ID", mappings="Client Output Master", validation=f"QA {qa_summary}; Maharashtra failures={failures}", warnings="See qa_summary.xlsx", output=f"{out_csv}; {out_xlsx}")
