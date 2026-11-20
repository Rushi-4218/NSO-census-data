from __future__ import annotations

import numpy as np
import pandas as pd

from .common import land_size_class, safe_divide


def _display_id(value) -> str:
    s = "" if value is None else str(value).strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        return str(int(float(s)))
    except Exception:
        return s

KPI_WIDE_MAP = {
    "HH_SHARE": "hh_share_household_row",
    "HH_SIZE": "hh_size",
    "LAND_OWNED_HA": "land_owned_ha",
    "LAND_POSS_HA": "land_poss_ha",
    "NET_CROP_RCPT": "net_crop_receipts_month",
    "INC_WAGES": "income_wages_month",
    "INC_LEASE": "income_lease_month",
    "INC_ANIMALS": "income_animals_month",
    "INC_NONFARM": "income_nonfarm_month",
    "INC_PENSION_REMIT": "income_pension_remit_month",
    "MONTHLY_INCOME": "monthly_income",
    "OUTPUT_PER_HH": "output_value_household",
    "OUTPUT_PER_CAPITA": "output_value_per_capita",
    "OUTPUT_PER_HA": "output_value_per_hectare",
}


def finish_household_mart(df: pd.DataFrame, config: dict, year: int) -> pd.DataFrame:
    out = df.copy()
    for c in [
        "hh_size", "land_owned_ha", "land_poss_ha", "net_crop_receipts_month",
        "income_wages_month", "income_lease_month", "income_animals_month",
        "income_nonfarm_month", "income_pension_remit_month", "crop_output_month",
        "animal_output_month", "weight"
    ]:
        if c not in out:
            out[c] = np.nan
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # The approved Maharashtra delivery is household-KPI long format. HH_SHARE=1 on a sampled household row.
    # True weighted percentage share is produced in the weighted summary report.
    out["hh_share_household_row"] = 1.0

    all_income_cols = [
        "net_crop_receipts_month", "income_wages_month", "income_lease_month",
        "income_animals_month", "income_nonfarm_month", "income_pension_remit_month"
    ]
    mcfg = config.get("monthlyization", {}).get(str(year), {})
    supported = mcfg.get("monthly_income_components", all_income_cols)
    supported = [c for c in supported if c in all_income_cols]
    if not supported:
        out["monthly_income"] = np.nan
        out["monthly_income_component_count"] = 0
    else:
        require_complete = bool(config.get("require_supported_income_components_complete", True))
        out["monthly_income_component_count"] = out[supported].notna().sum(axis=1)
        if require_complete:
            complete = out[supported].notna().all(axis=1)
            out["monthly_income"] = out[supported].sum(axis=1, min_count=len(supported)).where(complete)
        else:
            out["monthly_income"] = out[supported].sum(axis=1, min_count=1)

    out["output_value_household"] = out[["crop_output_month", "animal_output_month"]].sum(axis=1, min_count=1)
    out["output_value_per_capita"] = safe_divide(out["output_value_household"], out["hh_size"])
    out["output_value_per_hectare"] = safe_divide(out["output_value_household"], out["land_poss_ha"])
    out["Size"] = out["land_poss_ha"].map(land_size_class)
    return out


def to_client_long(mart: pd.DataFrame, dictionary, year_config: dict, extracted_date: str) -> pd.DataFrame:
    kpis = dictionary.kpis[["Col_ID", "COL_DESC", "Unit"]].copy()
    records = []
    for k in kpis.itertuples(index=False):
        wide_col = KPI_WIDE_MAP.get(str(k.Col_ID))
        if not wide_col:
            continue
        x = pd.DataFrame({
            "Survey_ID": year_config["survey_id"],
            "Survey_NAME": year_config["survey_name"],
            "Survey_GROUP_ID": "SAS",
            "GROUP_NAME": "Agriculture",
            "SUB_GROUP_ID": "FARM",
            "SUB_GROUP_NAME": "Farm Economy",
            "Year": int(year_config["year"]),
            "FREQ_DESC": "Annual",
            "State_ID": mart["State_ID"].map(_display_id),
            "State_Name": mart["State_Name"].fillna("").astype(str),
            "District_ID": mart["District_ID"].map(_display_id),
            "District_Name": mart["District_Name"],
            "Sector_code": mart["Sector_code"],
            "Sector": mart["Sector"],
            "Published_date": mart["Published_date"] if "Published_date" in mart else year_config.get("published_date", ""),
            "Extracted_Date": extracted_date,
            "Visit_ID": mart["visit"],
            "Size": mart["Size"],
            "houseHold_ID": mart["household_id"],
            "Col_ID": str(k.Col_ID),
            "COL_DESC": str(k.COL_DESC),
            "DATA": mart[wide_col] if wide_col in mart else np.nan,
            "Unit": str(k.Unit),
            "Source": mart["Source"] if "Source" in mart else year_config.get("source", ""),
        })
        records.append(x)
    out = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    client_cols = dictionary.client_columns
    for c in client_cols:
        if c not in out:
            out[c] = ""
    out = out[client_cols]
    # Existing approval file contains exact duplicates; new production output does not reproduce them.
    out = out.drop_duplicates(ignore_index=True)
    return out


def _client_chunk(mart: pd.DataFrame, k, year_config: dict, extracted_date: str, client_cols: list[str]) -> pd.DataFrame:
    wide_col = KPI_WIDE_MAP[str(k.Col_ID)]
    n = len(mart)
    def col_or_const(name, default):
        return mart[name] if name in mart else default
    x = pd.DataFrame({
        "Survey_ID": year_config["survey_id"],
        "Survey_NAME": year_config["survey_name"],
        "Survey_GROUP_ID": "SAS",
        "GROUP_NAME": "Agriculture",
        "SUB_GROUP_ID": "FARM",
        "SUB_GROUP_NAME": "Farm Economy",
        "Year": int(year_config["year"]),
        "FREQ_DESC": "Annual",
        "State_ID": mart["State_ID"].map(_display_id),
        "State_Name": mart["State_Name"].fillna("").astype(str),
        "District_ID": mart["District_ID"].map(_display_id),
        "District_Name": mart["District_Name"],
        "Sector_code": mart["Sector_code"],
        "Sector": mart["Sector"],
        "Published_date": col_or_const("Published_date", year_config.get("published_date", "")),
        "Extracted_Date": extracted_date,
        "Visit_ID": mart["visit"],
        "Size": mart["Size"],
        "houseHold_ID": mart["household_id"],
        "Col_ID": str(k.Col_ID),
        "COL_DESC": str(k.COL_DESC),
        "DATA": mart[wide_col] if wide_col in mart else np.nan,
        "Unit": str(k.Unit),
        "Source": col_or_const("Source", year_config.get("source", "")),
    })
    for c in client_cols:
        if c not in x:
            x[c] = ""
    return x[client_cols].drop_duplicates(ignore_index=True)


def write_client_long(mart: pd.DataFrame, dictionary, year_config: dict, extracted_date: str, output_path, append: bool = False) -> dict:
    """Stream the 14 KPI chunks to disk so all-India files do not require a huge 24-column frame in memory."""
    output_path = str(output_path)
    kpis = dictionary.kpis[["Col_ID", "COL_DESC", "Unit"]].copy()
    client_cols = dictionary.client_columns
    total_rows = 0
    first = True
    per_kpi = []
    for k in kpis.itertuples(index=False):
        if str(k.Col_ID) not in KPI_WIDE_MAP:
            continue
        chunk = _client_chunk(mart, k, year_config, extracted_date, client_cols)
        if append:
            mode = "a"
            header = False
        else:
            mode = "w" if first else "a"
            header = first
        chunk.to_csv(output_path, index=False, mode=mode, header=header)
        total_rows += len(chunk)
        per_kpi.append({"Col_ID": str(k.Col_ID), "Rows": len(chunk), "NonNull": int(pd.to_numeric(chunk["DATA"], errors="coerce").notna().sum())})
        first = False
        del chunk
    return {"rows": total_rows, "per_kpi": per_kpi, "columns": client_cols}
