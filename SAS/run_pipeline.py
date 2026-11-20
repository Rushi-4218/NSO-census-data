from __future__ import annotations

import argparse
import sys
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common import read_json
from src.dictionary import MasterDictionary
from src.round2003 import build as build_2003
from src.round2013 import build as build_2013
from src.round2019 import build as build_2019
from src.summary import build_weighted_summary, build_client_geography_aggregates
from src.validator import household_mart_checks, unmapped_districts, write_methodology_assumptions


FINAL_NAMES = {
    2003: "SAS_2003_All_India_State_District_Final.csv",
    2013: "SAS_2013_All_India_State_District_Final.csv",
    2019: "SAS_2019_All_India_State_District_Final.csv",
}

EXPECTED_KPI_IDS = {
    "HH_SHARE", "HH_SIZE", "LAND_OWNED_HA", "LAND_POSS_HA", "NET_CROP_RCPT",
    "INC_WAGES", "INC_LEASE", "INC_ANIMALS", "INC_NONFARM", "INC_PENSION_REMIT",
    "MONTHLY_INCOME", "OUTPUT_PER_HH", "OUTPUT_PER_CAPITA", "OUTPUT_PER_HA",
}


def parse_args():
    p = argparse.ArgumentParser(description="Build corrected SAS 2003/2013/2019 client outputs.")
    p.add_argument("--inputs", required=True, help="Folder containing source ZIPs, SAS_Maharashtra.csv, and the v2 master dictionary.")
    p.add_argument("--output", default=str(ROOT / "outputs"), help="Final output directory.")
    p.add_argument("--work", default=str(ROOT / "work"), help="Working/cache directory.")
    p.add_argument("--reports", default=str(ROOT / "reports"), help="QA report directory.")
    p.add_argument("--config", default=str(ROOT / "config" / "pipeline_config.json"), help="Pipeline configuration JSON.")
    p.add_argument("--client-schema", default=str(ROOT / "config" / "client_schema_fallback.csv"), help="Final client schema CSV. It records the approved aggregate-only HH_Type correction.")
    p.add_argument("--round", choices=["all", "2003", "2013", "2019"], default="all")
    p.add_argument("--smoke-test", action="store_true", help="Small structural run. Smoke outputs are isolated from production outputs by default.")
    p.add_argument("--no-wide", action="store_true", help="Do not save the internal household-visit mart CSV.gz.")
    p.add_argument("--no-summary", action="store_true", help="Skip the auxiliary weighted hierarchy summary; final aggregate 24-column CSVs are still produced and validated.")
    p.add_argument("--rebuild-cache", action="store_true", help="Ignore any cached household-visit mart and rebuild from raw ZIP files.")
    p.add_argument("--reuse-cache-only", action="store_true", help="Use an existing valid household-visit cache only; fail instead of reopening raw ZIPs.")
    return p.parse_args()


def _validate_inputs(input_dir: Path, cfg: dict, report_dir: Path) -> dict[str, Path]:
    rows = []
    paths: dict[str, Path] = {}
    for key, fname in cfg["input_files"].items():
        p = input_dir / fname
        paths[key] = p
        ok = p.exists() and p.is_file() and p.stat().st_size > 0
        rows.append({
            "Input_Key": key,
            "File_Name": fname,
            "Exists": ok,
            "Size_MB": round(p.stat().st_size / (1024 * 1024), 3) if p.exists() else None,
            "Status": "PASS" if ok else "FAIL",
        })
    pd.DataFrame(rows).to_csv(report_dir / "input_validation.csv", index=False)
    missing = [r["File_Name"] for r in rows if r["Status"] == "FAIL"]
    if missing:
        raise FileNotFoundError("Missing required INPUT files:\n  - " + "\n  - ".join(missing))

    required_tokens = {
        "sas_2003": ["bk_1_2", "bk_3", "bk_4", "bk_14_c12_20", "bk_15", "bk_16", "bk_17"],
        "sas_2013_visit1": ["identification of sample household", "block 3_household", "block 4_demographic", "block 5a_value of output", "block 6_", "block 7_", "block 8_", "block 9_"],
        "sas_2013_visit2": ["identification of sample household", "block 4_demographic", "block 5a_value of output", "block 6_", "block 7_", "block 8_", "block 9_"],
        "sas_2019": ["visit1  level - 01", "visit2  level - 01", "visit1  level - 02", "visit2  level - 02", "visit1  level - 04", "visit2  level - 04", "visit 1 level 07", "visit 2 level 07", "visit 1 level 13", "visit 2 level 13"],
    }
    archive_checks = []
    for key, tokens in required_tokens.items():
        p = paths[key]
        if not zipfile.is_zipfile(p):
            raise ValueError(f"Not a valid ZIP: {p}")
        with zipfile.ZipFile(p) as z:
            members = [n.lower() for n in z.namelist()]
        for token in tokens:
            found = any(token.lower() in n for n in members)
            archive_checks.append({
                "Archive": p.name,
                "Required_Token": token,
                "Found": found,
                "Status": "PASS" if found else "FAIL",
            })
    adf = pd.DataFrame(archive_checks)
    adf.to_csv(report_dir / "archive_structure_validation.csv", index=False)
    if (adf["Status"] == "FAIL").any():
        bad = adf[adf["Status"] == "FAIL"]
        raise ValueError("Required source blocks are missing. See archive_structure_validation.csv\n" + bad.to_string(index=False))
    return paths


def _dictionary_contract_check(dictionary: MasterDictionary, report_dir: Path):
    rows = []
    cols = dictionary.client_columns
    kpi_ids = set(dictionary.kpis["Col_ID"].dropna().astype(str))
    years = set(pd.to_numeric(dictionary.survey_summary["Survey_Year"], errors="coerce").dropna().astype(int))

    rows.append({"Check": "client_schema_24_columns", "Status": "PASS" if len(cols) == 24 else "FAIL", "Detail": f"columns={len(cols)}"})
    rows.append({
        "Check": "aggregate_schema_has_hh_type_not_household_id",
        "Status": "PASS" if "HH_Type" in cols and "houseHold_ID" not in cols else "FAIL",
        "Detail": f"override={dictionary.client_schema_path}; columns={cols}",
    })
    missing_kpis = EXPECTED_KPI_IDS - kpi_ids
    extra_kpis = kpi_ids - EXPECTED_KPI_IDS
    rows.append({
        "Check": "client_14_kpi_contract",
        "Status": "PASS" if not missing_kpis and not extra_kpis and len(kpi_ids) == 14 else "FAIL",
        "Detail": f"count={len(kpi_ids)}; missing={sorted(missing_kpis)}; extra={sorted(extra_kpis)}",
    })
    rows.append({
        "Check": "survey_rounds_present",
        "Status": "PASS" if {2003, 2013, 2019}.issubset(years) else "FAIL",
        "Detail": f"years={sorted(years)}",
    })

    req = dictionary.sheet("Required_Dimensions")
    sizes = set(req.loc[req["Dimension"].astype(str).eq("Land Size"), "Value"].dropna().astype(str))
    expected_sizes = {"All sizes", "<0.01 ha", "0.01 - 0.4 ha", "0.4 - 1 ha", "1-2 ha", "2-4 ha", "4-10 ha"}
    rows.append({
        "Check": "required_land_size_contract",
        "Status": "PASS" if expected_sizes.issubset(sizes) else "FAIL",
        "Detail": f"missing={sorted(expected_sizes - sizes)}",
    })

    geo = dictionary.geography
    n_state = int(geo["CODE_LIST_ID"].eq("STATE").sum())
    n_district = int(geo["CODE_LIST_ID"].eq("DISTRICT").sum())
    rows.append({
        "Check": "master_geography_state_district_sheet",
        "Status": "PASS" if n_state >= 36 and n_district >= 600 else "FAIL",
        "Detail": f"states={n_state}; districts={n_district}; authority=State_District sheet",
    })

    out = pd.DataFrame(rows)
    out.to_csv(report_dir / "master_dictionary_contract_validation.csv", index=False)
    if (out["Status"] == "FAIL").any():
        raise ValueError("Master data dictionary contract validation failed. See master_dictionary_contract_validation.csv")


def _reference_schema_check(reference_csv: Path, dictionary: MasterDictionary, report_dir: Path):
    # SAS_Maharashtra.csv remains the formatting reference, but the client has now
    # explicitly removed household-level output.  The corrected production schema
    # replaces its houseHold_ID column with HH_Type and stays at 24 columns.
    ref_cols = list(pd.read_csv(reference_csv, nrows=1).columns)
    source_dict_cols = dictionary.source_client_columns
    dict_cols = dictionary.client_columns
    corrected_ref = ["HH_Type" if c == "houseHold_ID" else c for c in ref_cols]
    source_status = "PASS" if ref_cols == source_dict_cols else "FAIL"
    corrected_status = "PASS" if corrected_ref == dict_cols else "FAIL"
    pd.DataFrame([{
        "Check": "source_reference_matches_master_dictionary",
        "Status": source_status,
        "Reference_Column_Count": len(ref_cols),
        "Dictionary_Column_Count": len(source_dict_cols),
        "Use_Of_Reference": "FORMAT_ONLY; source contract retains houseHold_ID",
        "Reference_Columns": " | ".join(ref_cols),
        "Corrected_Reference_Columns": " | ".join(corrected_ref),
        "Dictionary_Columns": " | ".join(source_dict_cols),
    }, {
        "Check": "approved_reference_with_client_aggregate_correction",
        "Status": corrected_status,
        "Reference_Column_Count": len(ref_cols),
        "Dictionary_Column_Count": len(dict_cols),
        "Use_Of_Reference": "FORMAT_ONLY; houseHold_ID replaced by HH_Type per client instruction",
        "Reference_Columns": " | ".join(ref_cols),
        "Corrected_Reference_Columns": " | ".join(corrected_ref),
        "Dictionary_Columns": " | ".join(dict_cols),
    }]).to_csv(report_dir / "client_schema_lock_validation.csv", index=False)
    if source_status == "FAIL" or corrected_status == "FAIL":
        raise ValueError("SAS source or corrected aggregate client schema contract does not match its controlling metadata.")


def _decorate_mart(mart: pd.DataFrame, year: int, cfg: dict) -> pd.DataFrame:
    ycfg = cfg["years"][str(year)]
    mart = mart.copy()
    mart["Published_date"] = ycfg.get("published_date", "")
    if year == 2013:
        mart["Source"] = mart["visit"].astype(str).map({
            "1": ycfg.get("source_visit1", ycfg.get("source", "")),
            "2": ycfg.get("source_visit2", ycfg.get("source", "")),
        }).fillna(ycfg.get("source", ""))
    else:
        mart["Source"] = ycfg.get("source", "")
    return mart


def _income_component_report(mart: pd.DataFrame, year: int, cfg: dict, report_dir: Path):
    cols = [
        "net_crop_receipts_month", "income_wages_month", "income_lease_month",
        "income_animals_month", "income_nonfarm_month", "income_pension_remit_month",
    ]
    supported = set(cfg["monthlyization"][str(year)].get("monthly_income_components", []))
    rows = []
    for c in cols:
        rows.append({
            "Year": year,
            "Component": c,
            "Used_In_Total_Monthly_Income": c in supported,
            "Rows": len(mart),
            "NonNull": int(pd.to_numeric(mart[c], errors="coerce").notna().sum()) if c in mart else 0,
            "Blank": int(pd.to_numeric(mart[c], errors="coerce").isna().sum()) if c in mart else len(mart),
        })
    pd.DataFrame(rows).to_csv(report_dir / f"SAS_{year}_income_component_availability.csv", index=False)


def _write_output_stats(year: int, stats: dict, out_path: Path, report_dir: Path, expected_rows: int | None):
    pd.DataFrame(stats["per_kpi"]).assign(Year=year).to_csv(report_dir / f"SAS_{year}_kpi_coverage.csv", index=False)
    status = "PASS" if expected_rows is None or stats["rows"] == expected_rows else "FAIL"
    pd.DataFrame([{
        "Year": year,
        "Output": out_path.name,
        "Rows": stats["rows"],
        "Expected_Rows": expected_rows,
        "Columns": len(stats["columns"]),
        "Status": status,
    }]).to_csv(report_dir / f"SAS_{year}_output_summary.csv", index=False)


def _path_signature(path: Path) -> dict:
    st = path.stat()
    return {"name": path.name, "size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns)}


def _mart_cache_signature(year: int, paths: dict[str, Path], cfg: dict) -> dict:
    keys = {2003: ["dictionary", "sas_2003"], 2013: ["dictionary", "sas_2013_visit1", "sas_2013_visit2"], 2019: ["dictionary", "sas_2019"]}[year]
    return {
        "pipeline_version": cfg.get("pipeline_version"),
        "year": year,
        "sources": {k: _path_signature(paths[k]) for k in keys},
        "monthlyization": cfg.get("monthlyization", {}).get(str(year), {}),
        "land_2019": cfg.get("land_2019", {}) if year == 2019 else None,
        "carry_2013_visit1_land_to_visit2": cfg.get("carry_2013_visit1_land_to_visit2") if year == 2013 else None,
    }


def _load_cached_mart(year: int, paths: dict[str, Path], cfg: dict, work_dir: Path):
    import json
    mart_path = work_dir / "marts" / f"SAS_{year}_Household_Visit_KPI_Mart.pkl"
    meta_path = work_dir / "marts" / f"SAS_{year}_Household_Visit_KPI_Mart.meta.json"
    if not mart_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if meta.get("signature") != _mart_cache_signature(year, paths, cfg):
        return None
    print(f"Reusing cached household mart: {mart_path}", flush=True)
    return pd.read_pickle(mart_path)


def _save_cached_mart(year: int, mart: pd.DataFrame, paths: dict[str, Path], cfg: dict, work_dir: Path):
    import json
    d = work_dir / "marts"
    d.mkdir(parents=True, exist_ok=True)
    mart_path = d / f"SAS_{year}_Household_Visit_KPI_Mart.pkl"
    meta_path = d / f"SAS_{year}_Household_Visit_KPI_Mart.meta.json"
    print(f"Caching household mart for fast reruns: {mart_path}", flush=True)
    mart.to_pickle(mart_path)
    meta_path.write_text(json.dumps({"signature": _mart_cache_signature(year, paths, cfg), "rows": len(mart)}, indent=2), encoding="utf-8")


def _run_year(
    year: int,
    paths: dict[str, Path],
    cfg: dict,
    dictionary: MasterDictionary,
    state_map,
    district_map,
    district_full_map,
    output_dir: Path,
    work_dir: Path,
    report_dir: Path,
    smoke: bool,
    no_wide: bool,
    no_summary: bool,
    rebuild_cache: bool,
    reuse_cache_only: bool,
):
    print("=" * 78)
    print(f"SAS {year}: BUILD START | pipeline v{cfg.get('pipeline_version', '2')}" )
    print("=" * 78)
    row_limit = int(cfg.get("smoke_test_row_limit", 3000)) if smoke else None
    cache_dir = work_dir / "cache" / str(year)
    cache_dir.mkdir(parents=True, exist_ok=True)

    mart = None
    cache_allowed = bool(cfg.get("reuse_cached_household_mart", True)) and not smoke and not rebuild_cache
    if cache_allowed:
        mart = _load_cached_mart(year, paths, cfg, work_dir)

    if mart is None:
        if reuse_cache_only and not smoke:
            raise FileNotFoundError(f"SAS {year}: no valid cached household mart exists. Run run_all.bat once first.")
        if year == 2003:
            mart = build_2003(paths["sas_2003"], cache_dir, state_map, district_map, district_full_map, cfg, row_limit)
        elif year == 2013:
            mart = build_2013(paths["sas_2013_visit1"], paths["sas_2013_visit2"], cache_dir, state_map, district_map, district_full_map, cfg, row_limit)
        elif year == 2019:
            mart = build_2019(paths["sas_2019"], cache_dir, state_map, district_map, district_full_map, cfg, row_limit)
        else:
            raise ValueError(year)
        mart = _decorate_mart(mart, year, cfg)
        if not smoke:
            _save_cached_mart(year, mart, paths, cfg, work_dir)
    else:
        # Publication/source metadata are cheap to refresh even when analytical data are reused.
        mart = _decorate_mart(mart, year, cfg)
    if mart["household_visit_id"].duplicated().any():
        raise ValueError(f"SAS {year}: household_visit_id is not unique after source aggregation")

    expected_hh = None if smoke else int(cfg["expected_household_visits"][str(year)])
    if expected_hh is not None and len(mart) != expected_hh:
        raise ValueError(f"SAS {year}: household-visit count mismatch. expected={expected_hh:,}, actual={len(mart):,}")

    checks = household_mart_checks(mart, year)
    if expected_hh is not None:
        checks = pd.concat([checks, pd.DataFrame([{
            "Year": year,
            "Check": "official_household_visit_count",
            "Status": "PASS" if len(mart) == expected_hh else "FAIL",
            "Detail": f"expected={expected_hh}; actual={len(mart)}",
        }])], ignore_index=True)
    checks.to_csv(report_dir / f"SAS_{year}_household_mart_validation.csv", index=False)
    unmapped_districts(mart, year).to_csv(report_dir / f"SAS_{year}_unmapped_districts.csv", index=False)
    _income_component_report(mart, year, cfg, report_dir)
    # Unknown land size is retained internally for All-sizes estimates but never
    # emitted as a client size class. Keep it visible in QA.
    pd.DataFrame([{
        "Year": year,
        "Household_Visits": len(mart),
        "Unknown_Size_Household_Visits": int(mart["Size"].fillna("").astype(str).eq("Unknown").sum()),
        "Unknown_Size_Pct": round(100.0 * mart["Size"].fillna("").astype(str).eq("Unknown").mean(), 3),
        "Client_Action": "Included in All sizes; excluded from explicit size bands",
    }]).to_csv(report_dir / f"SAS_{year}_size_classification_qa.csv", index=False)

    if year == 2019 and "sss_land_consistency" in mart:
        mart["sss_land_consistency"].value_counts(dropna=False).rename_axis("Status").reset_index(name="Rows").to_csv(
            report_dir / "SAS_2019_sss_land_consistency.csv", index=False
        )

    write_wide = cfg.get("write_internal_household_mart", True) and not no_wide
    if write_wide:
        wide_path = work_dir / f"SAS_{year}_Household_Visit_KPI_Mart.csv.gz"
        print(f"Writing internal mart: {wide_path}")
        mart.to_csv(wide_path, index=False, compression="gzip")

    out_path = output_dir / FINAL_NAMES[year]
    extracted_date = datetime.now().strftime("%d-%b-%y")
    print(f"Writing aggregate-only 24-column client output: {out_path}")

    # Production output is aggregate only: no household IDs or household-detail rows.
    # HH_Type replaces houseHold_ID in the corrected client contract.
    final_df = build_client_geography_aggregates(
        mart, dictionary, cfg["years"][str(year)], extracted_date
    )
    final_df.to_csv(out_path, index=False)

    # KPI coverage: rows are always present for every supported analytical cell;
    # this report distinguishes actual values from source-unavailable blanks.
    per_kpi = []
    for kid, g in final_df.groupby("Col_ID", dropna=False, sort=False):
        data_num = pd.to_numeric(g["DATA"], errors="coerce")
        per_kpi.append({
            "Col_ID": str(kid),
            "Rows": len(g),
            "NonNull": int(data_num.notna().sum()),
            "Blank": int(data_num.isna().sum()),
            "Coverage_Pct": round(100.0 * data_num.notna().mean(), 2) if len(g) else 0.0,
            "Status": "AVAILABLE" if data_num.notna().all() else ("UNAVAILABLE_IN_SOURCE" if data_num.notna().sum() == 0 else "PARTIAL_SOURCE_COVERAGE"),
        })
    stats = {"rows": len(final_df), "per_kpi": per_kpi, "columns": list(final_df.columns)}
    _write_output_stats(year, stats, out_path, report_dir, None)

    # QA the exact aggregate geography + analytical hierarchy in the main output.
    geo_checks = []
    geo_checks.append({"Check":"no_household_id_column","Status":"PASS" if "houseHold_ID" not in final_df.columns else "FAIL"})
    geo_checks.append({"Check":"hh_type_column_present","Status":"PASS" if "HH_Type" in final_df.columns else "FAIL"})
    geo_checks.append({"Check":"all_india_present","Status":"PASS" if ((final_df["State_ID"].astype(str)=="0") & (final_df["State_Name"].astype(str)=="India") & (final_df["District_ID"].astype(str)=="0") & (final_df["District_Name"].astype(str)=="All Districts")).any() else "FAIL"})
    state_totals = final_df[(final_df["State_ID"].astype(str)!="0") & (final_df["District_ID"].astype(str)=="0") & (final_df["District_Name"].astype(str)=="All Districts")]
    expected_states = set(mart.loc[mart["State_ID"].astype(str).ne(""), "State_ID"].astype(str))
    got_states = set(state_totals["State_ID"].astype(str))
    norm = lambda z: str(int(z)) if str(z).isdigit() else str(z)
    geo_checks.append({"Check":"state_all_districts_present","Status":"PASS" if {norm(x) for x in expected_states}.issubset({norm(x) for x in got_states}) else "FAIL"})
    district_rows = final_df[(final_df["District_ID"].astype(str)!="0") & final_df["District_Name"].astype(str).ne("")]
    geo_checks.append({"Check":"district_rows_present","Status":"PASS" if len(district_rows)>0 else "FAIL"})
    geo_checks.append({"Check":"all_sizes_present","Status":"PASS" if final_df["Size"].astype(str).eq("All sizes").any() else "FAIL"})
    geo_checks.append({"Check":"all_hh_present","Status":"PASS" if final_df["HH_Type"].astype(str).eq("All HH").any() else "FAIL"})
    geo_checks.append({"Check":"agricultural_hh_present","Status":"PASS" if final_df["HH_Type"].astype(str).eq("Agricultural HH").any() else "FAIL"})
    # Non-Agricultural HH is required only when the underlying round supports it (2019).
    nonagri_required = bool(mart["hh_category"].fillna("").astype(str).eq("Non-Agricultural HH").any())
    nonagri_present = bool(final_df["HH_Type"].astype(str).eq("Non-Agricultural HH").any())
    geo_checks.append({"Check":"non_agricultural_hh_when_supported","Status":"PASS" if (not nonagri_required or nonagri_present) else "FAIL"})
    units_expected = {str(r.Col_ID): str(r.Unit) for r in dictionary.kpis[["Col_ID","Unit"]].itertuples(index=False)}
    units_actual = final_df.groupby("Col_ID", dropna=False)["Unit"].agg(lambda x: set(map(str, x))).to_dict()
    unit_ok = all(units_actual.get(k, set()) == {u} for k, u in units_expected.items())
    geo_checks.append({"Check":"unit_mapping_exact","Status":"PASS" if unit_ok else "FAIL"})
    geo_checks.append({"Check":"published_date_populated","Status":"PASS" if final_df["Published_date"].fillna("").astype(str).str.strip().ne("").all() else "FAIL"})
    key_cols = ["State_ID","District_ID","Visit_ID","HH_Type","Size","Col_ID"]
    geo_checks.append({"Check":"aggregate_key_unique","Status":"PASS" if not final_df.duplicated(key_cols).any() else "FAIL"})
    pd.DataFrame(geo_checks).to_csv(report_dir / f"SAS_{year}_geography_hierarchy_validation.csv", index=False)
    if any(r["Status"] == "FAIL" for r in geo_checks):
        raise ValueError(f"SAS {year}: aggregate geography/template hierarchy validation failed")

    if cfg.get("write_weighted_summary", True) and not no_summary:
        print("Building weighted All India / State / District hierarchy...")
        summary = build_weighted_summary(mart, dictionary, cfg["years"][str(year)])
        summary_path = report_dir / f"SAS_{year}_All_India_State_District_Weighted_Summary.csv"
        summary.to_csv(summary_path, index=False)
        print(f"Weighted summary: {summary_path}")

    print(f"SAS {year}: PASS | household-visits={len(mart):,} | aggregate client rows={stats['rows']:,}")
    return {
        "year": year,
        "mode": "SMOKE" if smoke else "PRODUCTION",
        "household_visits": len(mart),
        "expected_household_visits": expected_hh,
        "client_rows": stats["rows"],
        "household_detail_rows": 0,
        "aggregate_rows": stats["rows"],
        "expected_household_detail_rows": 0,
        "output": str(out_path),
    }


def main():
    args = parse_args()
    cfg = read_json(args.config)
    input_dir = Path(args.inputs).resolve()

    # Smoke artifacts can never silently overwrite the production output folder.
    if args.smoke_test and Path(args.output).resolve() == (ROOT / "outputs").resolve():
        output_dir = (ROOT / "work" / "smoke_outputs").resolve()
    else:
        output_dir = Path(args.output).resolve()
    if args.smoke_test and Path(args.reports).resolve() == (ROOT / "reports").resolve():
        report_dir = (ROOT / "work" / "smoke_reports").resolve()
    else:
        report_dir = Path(args.reports).resolve()
    work_dir = Path(args.work).resolve()

    for p in [output_dir, work_dir, report_dir]:
        p.mkdir(parents=True, exist_ok=True)

    try:
        paths = _validate_inputs(input_dir, cfg, report_dir)
        dictionary = MasterDictionary(paths["dictionary"], args.client_schema)
        _dictionary_contract_check(dictionary, report_dir)
        _reference_schema_check(paths["client_reference"], dictionary, report_dir)

        dictionary.source_gaps.to_csv(report_dir / "source_gaps_from_master_dictionary.csv", index=False)
        dictionary.geography.to_csv(report_dir / "master_geography_lookup_snapshot.csv", index=False)
        write_methodology_assumptions(cfg, report_dir / "methodology_assumptions.csv")
        state_map, district_map, district_full_map = dictionary.geography_lookups()

        years = [2003, 2013, 2019] if args.round == "all" else [int(args.round)]
        results = []
        for year in years:
            results.append(_run_year(
                year, paths, cfg, dictionary, state_map, district_map, district_full_map,
                output_dir, work_dir, report_dir, args.smoke_test, args.no_wide, args.no_summary,
                args.rebuild_cache, args.reuse_cache_only,
            ))
    except Exception as exc:
        err = report_dir / "pipeline_error.txt"
        err.parent.mkdir(parents=True, exist_ok=True)
        err.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"\nPIPELINE FAILED: {exc}", file=sys.stderr)
        print(f"Full traceback: {err}", file=sys.stderr)
        return 1

    pd.DataFrame(results).to_csv(report_dir / "pipeline_run_summary.csv", index=False)
    print("\n" + "=" * 78)
    print("SAS PIPELINE COMPLETE")
    print("=" * 78)
    for r in results:
        print(f"{r['year']}: {r['output']}")
    print(f"QA reports: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
