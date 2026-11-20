from __future__ import annotations

from pathlib import Path
import json
import numpy as np
import pandas as pd


def validate_client_output(df: pd.DataFrame, dictionary, year: int) -> pd.DataFrame:
    expected = dictionary.client_columns
    rows = []
    rows.append({"Year": year, "Check": "schema_exact", "Status": "PASS" if list(df.columns) == expected else "FAIL", "Detail": f"expected={len(expected)} columns; actual={len(df.columns)}"})
    dups = int(df.duplicated().sum())
    rows.append({"Year": year, "Check": "exact_duplicate_rows", "Status": "PASS" if dups == 0 else "FAIL", "Detail": str(dups)})
    rows.append({"Year": year, "Check": "row_count", "Status": "INFO", "Detail": str(len(df))})
    rows.append({"Year": year, "Check": "unique_households", "Status": "INFO", "Detail": str(df["houseHold_ID"].nunique(dropna=True)) if "houseHold_ID" in df else ""})
    rows.append({"Year": year, "Check": "unique_visits", "Status": "INFO", "Detail": " | ".join(sorted(df["Visit_ID"].dropna().astype(str).unique())) if "Visit_ID" in df else ""})
    missing_kpis = sorted(set(dictionary.kpis["Col_ID"].astype(str)) - set(df["Col_ID"].dropna().astype(str).unique()))
    rows.append({"Year": year, "Check": "all_14_kpi_ids_present", "Status": "PASS" if not missing_kpis else "FAIL", "Detail": ", ".join(missing_kpis)})
    return pd.DataFrame(rows)


def kpi_coverage(df: pd.DataFrame, year: int) -> pd.DataFrame:
    x = df.groupby(["Col_ID", "COL_DESC", "Unit"], dropna=False).agg(
        rows=("DATA", "size"),
        non_null_data=("DATA", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
    ).reset_index()
    x["blank_data"] = x["rows"] - x["non_null_data"]
    x["coverage_pct"] = np.where(x["rows"] > 0, 100.0 * x["non_null_data"] / x["rows"], np.nan)
    x.insert(0, "Year", year)
    return x


def unmapped_districts(mart: pd.DataFrame, year: int) -> pd.DataFrame:
    x = mart[(mart["District_ID"].astype(str).str.len() > 0) & (mart["District_Name"].fillna("").eq(""))]
    if x.empty:
        return pd.DataFrame(columns=["Year", "State_ID", "State_Name", "District_ID", "Rows", "Policy"])
    y = x.groupby(["State_ID", "State_Name", "District_ID"], dropna=False).size().reset_index(name="Rows")
    y.insert(0, "Year", year)
    y["Policy"] = "PRESERVE_CODE_BLANK_NAME_DO_NOT_INVENT"
    return y


def household_mart_checks(mart: pd.DataFrame, year: int) -> pd.DataFrame:
    rows = []
    rows.append({"Year": year, "Check": "household_visit_rows", "Status": "INFO", "Detail": str(len(mart))})
    dup = int(mart["household_visit_id"].duplicated().sum()) if "household_visit_id" in mart else -1
    rows.append({"Year": year, "Check": "household_visit_unique", "Status": "PASS" if dup == 0 else "FAIL", "Detail": str(dup)})
    if "weight" in mart:
        weight = pd.to_numeric(mart["weight"], errors="coerce")
        bad = int((weight.isna() | weight.le(0)).sum())
        rows.append({"Year": year, "Check": "valid_positive_weight", "Status": "PASS" if bad == 0 else "WARN", "Detail": f"invalid={bad}"})
    if "Size" in mart:
        unknown = int(mart["Size"].isin(["Unknown"]).sum())
        rows.append({"Year": year, "Check": "client_size_band_unknown", "Status": "WARN" if unknown else "PASS", "Detail": str(unknown)})
    if "geography_match_status" in mart:
        unmapped_state = int(mart["geography_match_status"].eq("UNMAPPED_STATE").sum())
        unmapped_district = int(mart["geography_match_status"].eq("UNMAPPED_DISTRICT").sum())
        rows.append({"Year": year, "Check": "unmapped_state_rows", "Status": "FAIL" if unmapped_state else "PASS", "Detail": str(unmapped_state)})
        rows.append({"Year": year, "Check": "unmapped_district_rows", "Status": ("FAIL" if year == 2019 and unmapped_district else ("WARN" if unmapped_district else "PASS")), "Detail": str(unmapped_district)})
    if year == 2019 and "sss_land_consistency" in mart:
        review = int(mart["sss_land_consistency"].eq("REVIEW").sum())
        missing = int(mart["sss_land_consistency"].eq("LAND_MISSING").sum())
        rows.append({"Year": year, "Check": "sss_vs_land_broad_class", "Status": "WARN" if review or missing else "PASS", "Detail": f"review={review}; land_missing={missing}"})
    return pd.DataFrame(rows)


def reference_schema_check(reference_csv: Path | str, output_df: pd.DataFrame) -> pd.DataFrame:
    ref = pd.read_csv(reference_csv, nrows=10)
    expected = list(ref.columns)
    actual = list(output_df.columns)
    return pd.DataFrame([
        {"Check": "reference_column_order", "Status": "PASS" if expected == actual else "FAIL", "Reference": " | ".join(expected), "Output": " | ".join(actual)},
        {"Check": "reference_column_count", "Status": "PASS" if len(expected) == len(actual) else "FAIL", "Reference": len(expected), "Output": len(actual)},
    ])


def write_methodology_assumptions(config: dict, path: Path | str) -> None:
    rows = []
    for year, item in config.get("monthlyization", {}).items():
        for key, value in item.items():
            status = "CONFIGURED HARMONIZATION CONTROL"
            if key == "monthly_income_components":
                status = "Only these source-supported/harmonized components are included in Total Monthly Income"
            elif key == "method_note":
                status = "DOCUMENTATION"
            rows.append({
                "Area": f"Monthlyization {year}",
                "Setting": key,
                "Value": json.dumps(value) if isinstance(value, (list, dict)) else value,
                "Status": status,
            })
    land = config.get("land_2019", {})
    for key, value in land.items():
        rows.append({
            "Area": "2019 land",
            "Setting": key,
            "Value": json.dumps(value) if isinstance(value, (list, dict)) else value,
            "Status": "CONTROLLED SOURCE MAPPING; areas are acres before conversion",
        })
    geo = config.get("geography", {})
    for key, value in geo.items():
        rows.append({
            "Area": "Geography",
            "Setting": key,
            "Value": value,
            "Status": "MASTER DICTIONARY AUTHORITY",
        })
    rows.extend([
        {"Area": "2013 land", "Setting": "source_unit", "Value": "hectares", "Status": "V2 FIX: source values are already decimal hectares; no /1000 conversion"},
        {"Area": "2013 Visit 2", "Setting": "carry_2013_visit1_land_to_visit2", "Value": config.get("carry_2013_visit1_land_to_visit2"), "Status": "Explicitly configured because Visit 2 has no Block 3"},
        {"Area": "Repeated child blocks", "Setting": "total_row_policy", "Value": "official total row if present; detail sum only as fallback", "Status": "V2 FIX: prevents total+detail double counting"},
        {"Area": "Optional activities", "Setting": "structural_zero_policy", "Value": "no child records => 0; child records with missing measure => NaN", "Status": "V2 FIX: distinguishes zero activity from missing data"},
        {"Area": "Client reference", "Setting": "SAS_Maharashtra.csv", "Value": "schema/template only", "Status": "Never used as calculation or geography truth"},
        {"Area": "Income", "Setting": "require_supported_income_components_complete", "Value": config.get("require_supported_income_components_complete"), "Status": "Total income requires all components declared supported for the round"},
    ])
    pd.DataFrame(rows).to_csv(path, index=False)
