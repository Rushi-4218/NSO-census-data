from __future__ import annotations

import numpy as np
import pandas as pd

from .common import weighted_mean, weighted_ratio


def _measure(group: pd.DataFrame, kpi_id: str) -> float:
    w = pd.to_numeric(group["weight"], errors="coerce")
    if kpi_id == "HH_SIZE":
        return weighted_mean(group["hh_size"], w)
    if kpi_id == "LAND_OWNED_HA":
        return weighted_mean(group["land_owned_ha"], w)
    if kpi_id == "LAND_POSS_HA":
        return weighted_mean(group["land_poss_ha"], w)
    if kpi_id == "NET_CROP_RCPT":
        return weighted_mean(group["net_crop_receipts_month"], w)
    if kpi_id == "INC_WAGES":
        return weighted_mean(group["income_wages_month"], w)
    if kpi_id == "INC_LEASE":
        return weighted_mean(group["income_lease_month"], w)
    if kpi_id == "INC_ANIMALS":
        return weighted_mean(group["income_animals_month"], w)
    if kpi_id == "INC_NONFARM":
        return weighted_mean(group["income_nonfarm_month"], w)
    if kpi_id == "INC_PENSION_REMIT":
        return weighted_mean(group["income_pension_remit_month"], w)
    if kpi_id == "MONTHLY_INCOME":
        return weighted_mean(group["monthly_income"], w)
    if kpi_id == "OUTPUT_PER_HH":
        return weighted_mean(group["output_value_household"], w)
    if kpi_id == "OUTPUT_PER_CAPITA":
        return weighted_ratio(group["output_value_household"], group["hh_size"], w)
    if kpi_id == "OUTPUT_PER_HA":
        return weighted_ratio(group["output_value_household"], group["land_poss_ha"], w)
    return np.nan


def _display_id(value) -> str:
    """ASUSE-style display ID: 01 -> 1, 0101 -> 101, aggregate -> 0."""
    s = "" if value is None else str(value).strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        return str(int(float(s)))
    except Exception:
        return s


def _geo_view(mart: pd.DataFrame, level: str) -> pd.DataFrame:
    x = mart.copy()
    if level == "All India":
        x["Geo_Key"] = "ALL_INDIA"
        x["Summary_State_ID"] = "0"
        x["Summary_State_Name"] = "India"
        x["Summary_District_ID"] = "0"
        x["Summary_District_Name"] = "All Districts"
    elif level == "State":
        x["Geo_Key"] = x["State_ID"].astype(str)
        x["Summary_State_ID"] = x["State_ID"].map(_display_id)
        x["Summary_State_Name"] = x["State_Name"]
        x["Summary_District_ID"] = "0"
        x["Summary_District_Name"] = "All Districts"
    elif level == "District":
        x["Geo_Key"] = x["District_ID"].astype(str)
        x["Summary_State_ID"] = x["State_ID"].map(_display_id)
        x["Summary_State_Name"] = x["State_Name"]
        x["Summary_District_ID"] = x["District_ID"].map(_display_id)
        x["Summary_District_Name"] = x["District_Name"]
    else:
        raise ValueError(level)
    x["Geography_Level"] = level
    return x


def build_weighted_summary(mart: pd.DataFrame, dictionary, year_cfg: dict) -> pd.DataFrame:
    """Full analytical hierarchy: geography x visit x HH type x size x KPI."""
    kpis = dictionary.kpis[["Col_ID", "COL_DESC", "Unit"]].copy()
    rows = []

    for geo_level in ["All India", "State", "District"]:
        geo = _geo_view(mart, geo_level)
        denom = geo.groupby(["Geo_Key", "visit"], dropna=False)["weight"].sum(min_count=1).to_dict()

        for hh_mode in ["actual", "all"]:
            h = geo.copy()
            h["HH_Type"] = "All HH" if hh_mode == "all" else h["hh_category"]

            for size_mode in ["actual", "all"]:
                s = h.copy()
                s["Summary_Size"] = "All sizes" if size_mode == "all" else s["Size"]
                keys = [
                    "Geography_Level", "Geo_Key", "Summary_State_ID", "Summary_State_Name",
                    "Summary_District_ID", "Summary_District_Name", "visit", "HH_Type", "Summary_Size"
                ]
                for keyvals, g in s.groupby(keys, dropna=False, sort=False):
                    gl, gk, sid, sname, did, dname, visit, hh_type, size = keyvals
                    cell_weight = pd.to_numeric(g["weight"], errors="coerce").sum(min_count=1)
                    parent_weight = denom.get((gk, visit), np.nan)
                    hh_share = np.nan if pd.isna(parent_weight) or parent_weight == 0 else float(100.0 * cell_weight / parent_weight)
                    for k in kpis.itertuples(index=False):
                        kid = str(k.Col_ID)
                        value = hh_share if kid == "HH_SHARE" else _measure(g, kid)
                        rows.append({
                            "Survey_ID": year_cfg["survey_id"], "Survey_NAME": year_cfg["survey_name"],
                            "Year": int(year_cfg["year"]), "Geography_Level": gl,
                            "State_ID": sid, "State_Name": sname, "District_ID": did, "District_Name": dname,
                            "Visit_ID": visit, "HH_Type": hh_type, "Size": size,
                            "Col_ID": kid, "COL_DESC": str(k.COL_DESC), "DATA": value, "Unit": str(k.Unit),
                            "Weighted_HH_Count": cell_weight,
                            "Source": (str(g["Source"].dropna().iloc[0]) if "Source" in g and not g["Source"].dropna().empty else year_cfg.get("source", "")),
                        })
    return pd.DataFrame(rows).drop_duplicates(ignore_index=True)


def build_client_geography_aggregates(mart: pd.DataFrame, dictionary, year_cfg: dict, extracted_date: str) -> pd.DataFrame:
    """Build a complete aggregate client grid with no household-level rows.

    Final grain:
      Geography x Visit x HH_Type x Size x KPI

    The output is intentionally COMPLETE for the client dimensions. For an
    observed geography/visit/HH type, every required land-size band and every
    KPI is emitted. If no households fall in a particular size cell,
    HH_SHARE=0 and mean/ratio KPIs are blank rather than dropping the row.

    `Unknown` is never emitted as a client size class. Households with unknown
    size still contribute to the `All sizes` aggregate and are counted in QA.
    """
    kpis = dictionary.kpis[["Col_ID", "COL_DESC", "Unit"]].copy()
    client_cols = dictionary.client_columns
    required_sizes = [
        "All sizes", "<0.01 ha", "0.01 - 0.4 ha", "0.4 - 1 ha",
        "1-2 ha", "2-4 ha", "4-10 ha"
    ]
    actual_hh_types = [x for x in mart["hh_category"].dropna().astype(str).unique().tolist() if x.strip()]
    # Stable client ordering.
    hh_types = [x for x in ["Agricultural HH", "Non-Agricultural HH"] if x in actual_hh_types] + ["All HH"]
    visits = sorted(mart["visit"].dropna().astype(str).unique().tolist())
    rows = []

    for geo_level in ["All India", "State", "District"]:
        geo = _geo_view(mart, geo_level)
        geo_meta_cols = ["Geo_Key", "Summary_State_ID", "Summary_State_Name", "Summary_District_ID", "Summary_District_Name"]
        geos = geo[geo_meta_cols].drop_duplicates()

        for gm in geos.itertuples(index=False):
            gbase = geo[geo["Geo_Key"].astype(str).eq(str(gm.Geo_Key))]
            for visit in visits:
                gv = gbase[gbase["visit"].astype(str).eq(str(visit))]
                parent_weight = pd.to_numeric(gv["weight"], errors="coerce").sum(min_count=1)
                has_parent = not pd.isna(parent_weight) and parent_weight > 0

                for hh_type in hh_types:
                    h = gv if hh_type == "All HH" else gv[gv["hh_category"].fillna("").astype(str).eq(hh_type)]
                    for size in required_sizes:
                        cell = h if size == "All sizes" else h[h["Size"].astype(str).eq(size)]
                        cell_weight = pd.to_numeric(cell["weight"], errors="coerce").sum(min_count=1) if not cell.empty else 0.0
                        if not has_parent:
                            hh_share = np.nan
                        else:
                            hh_share = float(100.0 * (0.0 if pd.isna(cell_weight) else cell_weight) / parent_weight)

                        source = year_cfg.get("source", "")
                        pub = year_cfg.get("published_date", "")
                        sector_code = "1"
                        sector = "Rural"
                        meta_source = cell if not cell.empty else (h if not h.empty else gv)
                        if not meta_source.empty:
                            if "Source" in meta_source and not meta_source["Source"].dropna().empty:
                                source = str(meta_source["Source"].dropna().iloc[0])
                            if "Published_date" in meta_source and not meta_source["Published_date"].dropna().empty:
                                pub = str(meta_source["Published_date"].dropna().iloc[0])
                            if "Sector_code" in meta_source and not meta_source["Sector_code"].dropna().empty:
                                sector_code = str(meta_source["Sector_code"].dropna().iloc[0])
                            if "Sector" in meta_source and not meta_source["Sector"].dropna().empty:
                                sector = str(meta_source["Sector"].dropna().iloc[0])

                        for k in kpis.itertuples(index=False):
                            kid = str(k.Col_ID)
                            if kid == "HH_SHARE":
                                value = hh_share
                            else:
                                value = np.nan if cell.empty else _measure(cell, kid)
                            rows.append({
                                "Survey_ID": year_cfg["survey_id"],
                                "Survey_NAME": year_cfg["survey_name"],
                                "Survey_GROUP_ID": "SAS", "GROUP_NAME": "Agriculture",
                                "SUB_GROUP_ID": "FARM", "SUB_GROUP_NAME": "Farm Economy",
                                "Year": int(year_cfg["year"]), "FREQ_DESC": "Annual",
                                "State_ID": gm.Summary_State_ID, "State_Name": gm.Summary_State_Name,
                                "District_ID": gm.Summary_District_ID, "District_Name": gm.Summary_District_Name,
                                "Sector_code": sector_code, "Sector": sector,
                                "Published_date": pub, "Extracted_Date": extracted_date,
                                "Visit_ID": visit, "Size": size, "HH_Type": hh_type,
                                "Col_ID": kid, "COL_DESC": str(k.COL_DESC), "DATA": value,
                                "Unit": str(k.Unit), "Source": source,
                            })

    out = pd.DataFrame(rows)
    for c in client_cols:
        if c not in out:
            out[c] = ""
    out = out[client_cols]
    key = ["State_ID", "District_ID", "Visit_ID", "HH_Type", "Size", "Col_ID"]
    if out.duplicated(key).any():
        dup = out.loc[out.duplicated(key, keep=False), key].head(20)
        raise ValueError("Duplicate aggregate SAS output keys detected:\n" + dup.to_string(index=False))
    return out
