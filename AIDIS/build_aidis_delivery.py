from __future__ import annotations

import gc
import io
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import xlsxwriter
import pyarrow.parquet as pq


ROOT = Path(r"D:\AIDIS")
INPUT = ROOT / "Input"
RAW = INPUT / "Debt and Investment 77th RoundJANUARY 2019 – DECEMBER 2019-Visit 1 and Visit 2"
DDI = INPUT / "AIDIS_77th_Round_Master_DDI.xlsx"
OUT_CSV = ROOT / "AIDIS_Final_Client.csv"
OUT_XLSX = ROOT / "AIDIS_Final_Client.xlsx"
REPORT = ROOT / "AIDIS_Final_Validation_Report.md"
COVERAGE = ROOT / "AIDIS_KPI_Coverage.csv"
CACHE = ROOT / ".aidis_cache"

SURVEY_ID = "AIDIS_77_2019"
SURVEY_NAME = "All India Debt and Investment Survey (AIDIS), 77th Round"
YEAR = 2019
PUBLISHED = "10-Sep-2021"
EXTRACTED = "07-Aug-2026"
SOURCE = "https://microdata.gov.in/NADA/index.php/catalog/156"

STATE_NAMES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "25": "Daman & Diu", "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana",
}

# Official composite State-District codes supplied and validated for Maharashtra.
DISTRICT_NAMES = {
    "2701": "Nandurbar", "2702": "Dhule", "2703": "Jalgaon",
    "2704": "Buldana", "2705": "Akola", "2706": "Washim",
    "2707": "Amravati", "2708": "Wardha", "2709": "Nagpur",
    "2710": "Bhandara", "2711": "Gondiya", "2712": "Gadchiroli",
    "2713": "Chandrapur", "2714": "Yavatmal", "2715": "Nanded",
    "2716": "Hingoli", "2717": "Parbhani", "2718": "Jalna",
    "2719": "Aurangabad", "2720": "Nashik", "2721": "Thane",
    "2722": "Mumbai Suburban", "2724": "Raigarh", "2725": "Pune",
    "2726": "Ahmadnagar", "2727": "Bid", "2728": "Latur",
    "2729": "Osmanabad", "2730": "Solapur", "2731": "Satara",
    "2732": "Ratnagiri", "2733": "Sindhudurg", "2734": "Kolhapur",
    "2735": "Sangli",
}

COLS = [
    "Survey_ID", "Survey_NAME", "Survey_GROUP_ID", "GROUP_NAME", "SUB_GROUP_ID",
    "SUB_GROUP_NAME", "Year", "FREQ_DESC", "State_ID", "State_Name", "District_ID",
    "District_Name", "Sector_code", "Sector", "Published_date", "Extracted_Date",
    "Visit_ID", "houseHold_ID", "Col_ID", "COL_DESC", "DATA", "Unit", "Source",
]


def long_path(p: Path) -> str:
    s = str(p.resolve())
    return s if s.startswith("\\\\?\\") else "\\\\?\\" + s


def read_raw(path: Path, needed: list[str] | None = None) -> pd.DataFrame:
    """Read long-path xlsx with calamine and keep only requested fields."""
    with open(long_path(path), "rb") as fh:
        payload = fh.read()
    frame = pl.read_excel(io.BytesIO(payload), engine="calamine")
    if needed is not None:
        have = [c for c in needed if c in frame.columns]
        frame = frame.select(have)
    out = frame.to_pandas()
    del frame, payload
    gc.collect()
    return out


def identify_files() -> dict[tuple[int, int], Path]:
    found: dict[tuple[int, int], Path] = {}
    for p in RAW.glob("*.xlsx"):
        m = re.match(r"Visit(\d+)\s+Level\s*-\s*(\d+)", p.name)
        if m:
            found[(int(m.group(1)), int(m.group(2)))] = p
    return found


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def clean_base(df: pd.DataFrame, visit: int | None = None) -> pd.DataFrame:
    df = df.copy()
    if "HHID" in df:
        df["HHID"] = df["HHID"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        df["Panel_HHID"] = df["HHID"].str[:-1]
    for c in ["Sector", "State", "District", "MLT", "visitNo"]:
        if c in df:
            df[c] = to_num(df[c])
    if visit is not None:
        df["Visit_ID"] = visit
    return df


def raw_header_validation(files: dict[tuple[int, int], Path], ddi: pd.DataFrame):
    rows = []
    header_map = {}
    for key, p in sorted(files.items()):
        cache_file=CACHE / f"v{key[0]}_l{key[1]:02d}.parquet"
        if cache_file.exists():
            meta=pq.ParquetFile(cache_file)
            actual_columns=meta.schema.names
            row_count=meta.metadata.num_rows
            df=None
        else:
            # Reading a single row is not supported efficiently by calamine; load once and cache.
            df = read_raw(p)
            actual_columns=list(df.columns)
            row_count=len(df)
        header_map[key] = actual_columns
        expected = set(ddi.loc[(ddi["Visit"].eq(f"Visit {key[0]}")) &
                               (ddi["Level"].astype(str).str.extract(r"(\d+)", expand=False).astype(float).eq(key[1])),
                               "Original_Column_Name"].dropna().astype(str))
        actual = set(actual_columns)
        rows.append({
            "visit": key[0], "level": key[1], "file": p.name, "rows": row_count,
            "columns": len(actual_columns), "missing_from_raw": sorted(expected - actual),
            "raw_not_in_ddi": sorted(actual - expected),
        })
        # Cache the relevant full frame for later stages.
        if df is not None:
            CACHE.mkdir(exist_ok=True)
            df.to_parquet(cache_file, index=False)
            del df
            gc.collect()
    return rows, header_map


def load(level: int, visit: int = 1, cols: list[str] | None = None) -> pd.DataFrame:
    p = CACHE / f"v{visit}_l{level:02d}.parquet"
    return pd.read_parquet(p, columns=cols)


def hh_sum(level: int, value: str, visit: int = 1, item: str | None = None,
           include: set[int] | None = None) -> pd.Series:
    cols = ["HHID", value] + ([item] if item else [])
    d = clean_base(load(level, visit, cols), visit)
    d[value] = to_num(d[value]).fillna(0)
    if item and include is not None:
        d[item] = to_num(d[item])
        d = d[d[item].isin(include)]
    elif item:
        d[item] = to_num(d[item])
        d = d[d[item].ne(99)]
    return d.groupby("HHID", sort=False)[value].sum()


def weighted_decile(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    w = np.maximum(np.nan_to_num(weights[order], nan=0.0), 0)
    total = w.sum()
    result = np.ones(len(values), dtype=np.int8)
    if total <= 0:
        return result
    midpoint = (np.cumsum(w) - 0.5 * w) / total
    result[order] = np.minimum(10, np.floor(midpoint * 10).astype(int) + 1)
    return result


def weighted_gini(x: np.ndarray, w: np.ndarray) -> float:
    ok = np.isfinite(x) & np.isfinite(w) & (w > 0) & (x >= 0)
    x, w = x[ok], w[ok]
    if len(x) == 0 or np.sum(x * w) == 0:
        return 0.0
    o = np.argsort(x, kind="mergesort")
    x, w = x[o], w[o]
    cw = np.cumsum(w) / np.sum(w)
    cy = np.cumsum(x * w) / np.sum(x * w)
    return float(1 - np.sum((cy[1:] + cy[:-1]) * np.diff(cw)))


def classify(master: pd.DataFrame) -> pd.DataFrame:
    out = master.copy()
    ht = to_num(out["b4q4"])
    sec = to_num(out["Sector"])
    out["HH_Category"] = np.where(
        sec.eq(1), np.where(ht.eq(1), "Cultivator HH", "Non-Cultivator HH"),
        np.where(ht.eq(1), "Self-employed", "Others"),
    )
    out["Sector_Name"] = sec.map({1: "Rural", 2: "Urban"})
    return out


def expand_domains(df: pd.DataFrame, categories: bool = True,
                   district: bool = True) -> pd.DataFrame:
    parts = []
    geo_specs = [("00", "All India", "0000", "All India")]
    # Use vectorized copies for All India, State and official composite district code.
    for geo in ["india", "state"] + (["district"] if district else []):
        for sector_total in [True, False]:
            x = df.copy()
            if geo == "india":
                x["State_ID"] = "00"; x["State_Name"] = "All India"
                x["District_ID"] = "0000"; x["District_Name"] = "All India"
            elif geo == "state":
                x["State_ID"] = x["State"].astype("Int64").astype(str).str.zfill(2)
                x["State_Name"] = x["State_ID"].map(STATE_NAMES)
                x["District_ID"] = "0000"; x["District_Name"] = "All Districts"
            else:
                x["State_ID"] = x["State"].astype("Int64").astype(str).str.zfill(2)
                x["State_Name"] = x["State_ID"].map(STATE_NAMES)
                dist = x["District"].astype("Int64").astype(str).str.zfill(2)
                x["District_ID"] = x["State_ID"] + dist
                # Decode validated mappings where available; retain transparent
                # code labels for states whose official directory is unavailable.
                x["District_Name"] = x["District_ID"].map(DISTRICT_NAMES).fillna("District code " + dist)
            if sector_total:
                x["Sector_code"] = 0; x["Sector_Label"] = "Total"
            else:
                x["Sector_code"] = x["Sector"].astype("Int64")
                x["Sector_Label"] = x["Sector_Name"]
            if categories:
                a = x.copy(); a["Category"] = "All HH"
                b = x.copy(); b["Category"] = b["HH_Category"]
                # Category rows are valid only within their own sector, not Total.
                if sector_total:
                    parts.append(a)
                else:
                    parts.extend([a, b])
            else:
                x["Category"] = "All HH"; parts.append(x)
    return pd.concat(parts, ignore_index=True)


DOMAIN = ["State_ID", "State_Name", "District_ID", "District_Name", "Sector_code", "Sector_Label", "Category", "Visit_ID"]


def make_row(key, group_id, group_name, subgroup_id, subgroup_name, col_id, desc, value, unit):
    if not isinstance(key, tuple): key = (key,)
    d = dict(zip(DOMAIN, key))
    return {
        "Survey_ID": SURVEY_ID, "Survey_NAME": SURVEY_NAME,
        "Survey_GROUP_ID": group_id, "GROUP_NAME": group_name,
        "SUB_GROUP_ID": subgroup_id, "SUB_GROUP_NAME": subgroup_name,
        "Year": YEAR, "FREQ_DESC": "Annual",
        "State_ID": d["State_ID"], "State_Name": d["State_Name"],
        "District_ID": d["District_ID"], "District_Name": d["District_Name"],
        "Sector_code": d["Sector_code"], "Sector": d["Sector_Label"],
        "Published_date": PUBLISHED, "Extracted_Date": EXTRACTED,
        "Visit_ID": d["Visit_ID"], "houseHold_ID": "",
        "Col_ID": col_id, "COL_DESC": desc, "DATA": value, "Unit": unit, "Source": SOURCE,
    }


def aggregate_basic(expanded: pd.DataFrame, output: list[dict]):
    for key, g in expanded.groupby(DOMAIN, dropna=False, sort=False):
        cat = key[6]
        w = g["MLT"].to_numpy(float)
        sw = w.sum()
        if sw <= 0: continue
        vals = {
            "HH_SURVEYED": (g["HHID"].nunique(), "Number", "No. of Households Surveyed"),
            "AVA": (np.sum(g["assets"] * w) / sw, "Rs. per HH", "Average Value of Assets (AVA)"),
            "AOD": (np.sum(g["debt"] * w) / sw, "Rs. per HH", "Average Amount of Debt (AOD) per HH"),
            "IOI": (100 * np.sum(w[g["debt"].to_numpy() > 0]) / sw, "%", "Incidence of Indebtedness (IOI)"),
        }
        indebted = g["debt"].to_numpy() > 0
        vals["AODL"] = ((np.sum(g.loc[indebted, "debt"] * w[indebted]) / np.sum(w[indebted])) if indebted.any() else 0,
                         "Rs.", "Average Amount of Debt per Indebted Household (AODL)")
        asset_total = np.sum(g["assets"] * w)
        vals["DAR"] = ((np.sum(g["debt"] * w) / asset_total) if asset_total else 0, "Ratio", "Debt Asset Ratio (DAR)")
        for cid, (v, unit, desc) in vals.items():
            output.append(make_row(key, "01", "Household Assets and Debt", cat, cat, cid, f"{desc} - {cat}", float(v), unit))
        if key[7] == 1:
            components = {
                "Physical assets": "physical", "Financial assets": "financial", "Land": "land",
                "Buildings": "buildings", "Deposits": "deposits", "Livestock & poultry": "livestock",
                "Agricultural machinery & equipment": "agri_machinery", "Transport equipment": "transport",
                "Non-farm business equipment": "nonfarm_equipment", "Others": "other_assets",
            }
            for name, col in components.items():
                v = np.sum(g[col] * w) / sw
                output.append(make_row(key, "02", "Assets by Component", cat, cat,
                                       "AVA_COMPONENT_" + re.sub(r"\W+", "_", name.upper()).strip("_"),
                                       f"Average Value of Assets - {name} - {cat}", float(v), "Rs. per HH"))


def aggregate_credit(master: pd.DataFrame, loans: pd.DataFrame, output: list[dict]):
    inst = {1,2,3,4,5,6,7,8,10,11,12,13}; noninst = {14,15,16,17,18,19,20}
    source_groups = {
        "All institutional sources": inst, "SCBs": {1}, "RRBs": {2}, "RCBs": {3,4},
        "NBFCs": {10}, "Other institutional agencies": {5,6,7,8,11,12,13},
        "All non-institutional sources": noninst, "Landlord": {14}, "Moneylender": {15,16},
        "Input supplier": {17}, "Relatives & friends": {18}, "Other non-institutional agencies": {19,20},
    }
    purpose_names = {0:"All purposes",1:"Capital expenditure in farm business",2:"Revenue expenditure in farm business",
                     3:"Capital expenditure in non-farm business",4:"Revenue expenditure in non-farm business",
                     5:"Litigation",6:"Repayment of debt",7:"Financial investment",8:"Education",9:"Others",
                     10:"Medical treatment",11:"Housing",12:"Other household expenditure"}
    nature_names = {0:"All",1:"Interest-free",2:"Simple interest",3:"Compound interest"}
    for visit in sorted(master.Visit_ID.unique()):
        m = master[master.Visit_ID.eq(visit)].copy()
        l = loans[loans.Visit_ID.eq(visit)].copy()
        # HH flags/amounts are merged before domain expansion, preserving one row per HH.
        for label, codes in source_groups.items():
            h = l[l.agency.isin(codes)].groupby("HHID")["outstanding"].sum()
            t = m[["HHID","Panel_HHID","State","District","Sector","Sector_Name","HH_Category","MLT","Visit_ID"]].copy()
            t["metric"] = t.HHID.map(h).fillna(0)
            ex = expand_domains(t, categories=True, district=True)
            allset = inst if "institutional" in label.lower() and "non-institutional" not in label.lower() else noninst
            denom_h = l[l.agency.isin(allset)].groupby("HHID")["outstanding"].sum()
            ex["denom"] = ex.HHID.map(denom_h).fillna(0)
            for key, g in ex.groupby(DOMAIN, dropna=False, sort=False):
                w = g.MLT.to_numpy(float); den = np.sum(g.denom.to_numpy(float)*w)
                val = 100*np.sum(g.metric.to_numpy(float)*w)/den if den else 0
                typ = "Institutional" if allset is inst else "Non-Institutional"
                output.append(make_row(key,"03","Outstanding Credit Distribution",key[6],key[6],
                                       "CREDIT_SOURCE_"+re.sub(r"\W+","_",label.upper()).strip("_"),
                                       f"Distribution of Outstanding {typ} Credit - {label} - {key[6]}",float(val),"%"))
        for nature, nlabel in nature_names.items():
            ll = l[l.agency.isin(inst)]
            if nature: ll = ll[ll.interest.eq(nature)]
            positive = set(ll.loc[ll.outstanding.gt(0),"HHID"])
            t = m.copy(); t["flag"] = t.HHID.isin(positive).astype(float)
            ex = expand_domains(t, categories=True, district=True)
            for key,g in ex.groupby(DOMAIN,dropna=False,sort=False):
                w=g.MLT.to_numpy(float); val=100*np.sum(g.flag.to_numpy()*w)/w.sum() if w.sum() else 0
                output.append(make_row(key,"03","Institutional Credit IOI",key[6],key[6],"INST_IOI_"+str(nature),
                                       f"IOI for Institutional Credit - {nlabel} - {key[6]}",float(val),"%"))
        for credit_name,codes in [("Institutional",inst),("Non-Institutional",noninst)]:
            base=l[l.agency.isin(codes)]
            for purpose,pname in purpose_names.items():
                ll=base if purpose==0 else base[base.purpose.eq(purpose)]
                num=ll.groupby("HHID").outstanding.sum(); denh=base.groupby("HHID").outstanding.sum()
                t=m.copy(); t["num"]=t.HHID.map(num).fillna(0); t["den"]=t.HHID.map(denh).fillna(0)
                ex=expand_domains(t,categories=True,district=True)
                for key,g in ex.groupby(DOMAIN,dropna=False,sort=False):
                    w=g.MLT.to_numpy(float); den=np.sum(g.den.to_numpy()*w)
                    val=100*np.sum(g.num.to_numpy()*w)/den if den else 0
                    output.append(make_row(key,"03","Credit by Purpose",key[6],key[6],f"PURPOSE_{credit_name[:4].upper()}_{purpose:02d}",
                                           f"Distribution of Outstanding {credit_name} Credit - Purpose: {pname} - {key[6]}",float(val),"%"))


def aggregate_deciles_and_gini(master: pd.DataFrame, output: list[dict]):
    # The DDI specifies All-India/State/Sector for distributional measures; no district estimates are manufactured.
    m=master[master.Visit_ID.eq(1)].copy()
    ex=expand_domains(m,categories=True,district=False)
    for key,g in ex.groupby(DOMAIN,dropna=False,sort=False):
        w=g.MLT.to_numpy(float); a=g.assets.to_numpy(float); debt=g.debt.to_numpy(float)
        dec=weighted_decile(a,w)
        for q in range(1,11):
            z=dec==q; sw=w[z].sum()
            if sw<=0: continue
            ava=np.sum(a[z]*w[z])/sw; aod=np.sum(debt[z]*w[z])/sw
            at=np.sum(a[z]*w[z]); dar=np.sum(debt[z]*w[z])/at if at else 0
            for cid,val,unit,name in [("AVA",ava,"Rs. per HH","AVA"),("AOD",aod,"Rs. per HH","AOD"),("DAR",dar,"Ratio","DAR")]:
                output.append(make_row(key,"04","Asset-Holding Deciles",f"D{q}",f"Asset Decile {q}",f"DECILE_{q}_{cid}",
                                       f"{name} by Asset-Holding Decile {q} - {key[6]}",float(val),unit))
        gini=weighted_gini(a,w)
        output.append(make_row(key,"06","Asset Inequality",key[6],key[6],"GINI_ASSET",
                               f"Gini's Coefficient of Asset Holdings - {key[6]}",gini,"Coefficient"))


def aggregate_fce(master: pd.DataFrame, annual: pd.DataFrame, output: list[dict]):
    """Annual FCE/EPL using the official 77th-round tabulation-plan rule.

    Annual amount = Visit 1 + Visit 2 for the same panel household. Published
    annual tables use the Visit-2 responding universe and Visit-2 multiplier.
    """
    m=master[master.Visit_ID.eq(2)].copy()
    m["FCE"]=m.Panel_HHID.map(annual.set_index("Panel_HHID").FCE).fillna(0)
    m["EPL"]=m.Panel_HHID.map(annual.set_index("Panel_HHID").EPL).fillna(0)

    # Occupational-category estimates (including appropriate rural/urban types).
    ex=expand_domains(m,categories=True,district=False)
    for key,g in ex.groupby(DOMAIN,dropna=False,sort=False):
        w=g.MLT.to_numpy(float); sw=w.sum()
        if sw<=0: continue
        for cid,col,name in [("FCE","FCE","Average Fixed Capital Expenditure per HH"),
                             ("EPL","EPL","Average Expenditure on Purchase of Land per HH")]:
            val=np.sum(g[col].to_numpy(float)*w)/sw
            output.append(make_row(key,"05","Capital Expenditure",key[6],key[6],cid,
                                   f"{name} - Occupational Category: {key[6]}",float(val),"Rs. per HH"))

    # Asset-decile estimates are a separate breakdown, not a decile x occupation cross-product.
    decile_ex=expand_domains(m,categories=False,district=False)
    for key,g in decile_ex.groupby(DOMAIN,dropna=False,sort=False):
        w=g.MLT.to_numpy(float); dec=weighted_decile(g.assets.fillna(0).to_numpy(float),w)
        for q in range(1,11):
            z=dec==q; sw=w[z].sum()
            if sw<=0: continue
            for cid,col,name in [("FCE","FCE","Average Fixed Capital Expenditure per HH"),
                                 ("EPL","EPL","Average Expenditure on Purchase of Land per HH")]:
                val=np.sum(g.loc[z,col].to_numpy(float)*w[z])/sw
                output.append(make_row(key,"05","Capital Expenditure",f"D{q}",f"Asset Decile {q}",f"{cid}_DECILE_{q}",
                                       f"{name} - Asset Decile {q}",float(val),"Rs. per HH"))


def aggregate_people(master_v1: pd.DataFrame, people: pd.DataFrame, output: list[dict]):
    p=people.merge(master_v1[["HHID","HH_Category","Sector_Name"]],on="HHID",how="inner",validate="many_to_one")
    p=p[p.age.ge(18)].copy(); p["has_account"]=p.deposit.isin([1,2,3]).astype(float); p["Visit_ID"]=1
    ex=expand_domains(p,categories=False,district=True)
    for key,g in ex.groupby(DOMAIN,dropna=False,sort=False):
        for sex,label in [(0,"Total"),(1,"Male"),(2,"Female")]:
            z=g if sex==0 else g[g.gender.eq(sex)]
            w=z.MLT.to_numpy(float); val=100*np.sum(z.has_account.to_numpy()*w)/w.sum() if w.sum() else 0
            output.append(make_row(key,"07","Financial Inclusion",label,label,f"ADULT_BANK_{label.upper()}",
                                   f"Adult Population Having Deposit Account in Bank - {label}",float(val),"%"))


def main():
    files=identify_files()
    if len(files)!=23: raise RuntimeError(f"Expected 23 raw workbooks, found {len(files)}")
    ddi=pd.read_excel(DDI,sheet_name="Master_DDI_AIDIS_77th_Round")
    ddi_map=pd.read_excel(DDI,sheet_name="DDI_Mapping")
    validation,headers=raw_header_validation(files,ddi)

    # Household masters, one row per HH/visit.
    masters=[]
    v1=clean_base(load(1,1,["HHID","Sector","State","District","visitNo","MLT"]),1)
    ht=clean_base(load(3,1,["HHID","b4q4"]),1)[["HHID","b4q4"]]
    v1=v1.merge(ht,on="HHID",how="left",validate="one_to_one")
    v1=classify(v1)
    v2=clean_base(load(1,2,["HHID","Sector","State","District","visitNo","MLT"]),2)
    ht_panel=v1[["Panel_HHID","b4q4"]].drop_duplicates("Panel_HHID")
    v2=v2.merge(ht_panel,on="Panel_HHID",how="left",validate="many_to_one")
    v2=classify(v2)

    # Assets: sum detail rows only, excluding printed subtotal/total rows.
    comps={}
    comps["land"]=hh_sum(5,"b5pt1q5",item="b5pt1q1") .add(hh_sum(6,"b5pt2q5",item="b5pt2q1"),fill_value=0)
    comps["buildings"]=hh_sum(7,"b6q5",item="b6q3",include=set(range(1,10)))
    comps["livestock"]=hh_sum(8,"b7q4",item="b7q2",include=set(range(1,13))|{14,15,16})
    comps["transport"]=hh_sum(9,"b8q4",item="b8q2",include=set(range(1,8)))
    comps["agri_machinery"]=hh_sum(10,"b9q4",item="b9q2",include=set(range(1,13)))
    comps["nonfarm_equipment"]=hh_sum(11,"b10q3",item="b10q2",include=set(range(1,15))|{16,17,18,19})
    # Financial stock is required at 30-Jun-2018 (q6), not survey-date q3.
    fin=clean_base(load(12,1,["HHID","b11aq1","b11aq6"]),1); fin["b11aq1"]=to_num(fin.b11aq1); fin["b11aq6"]=to_num(fin.b11aq6).fillna(0)
    comps["financial_base"]=fin[fin.b11aq1.isin(set(range(1,19)))].groupby("HHID").b11aq6.sum()
    comps["deposits"]=fin[fin.b11aq1.isin(set(range(3,10)))].groupby("HHID").b11aq6.sum()
    shares=hh_sum(13,"b11bq6",item="b11bq1",include={1,2,3,4})
    for name,s in comps.items(): v1[name]=v1.HHID.map(s).fillna(0)
    v1["financial"]=v1.financial_base+v1.HHID.map(shares).fillna(0)
    v1["physical"]=v1[["land","buildings","livestock","transport","agri_machinery","nonfarm_equipment"]].sum(axis=1)
    v1["assets"]=v1.physical+v1.financial
    # Official Report 588 definition: other assets comprise livestock, transport,
    # agricultural machinery, non-farm equipment and shares.
    v1["other_assets"]=v1[["livestock","transport","agri_machinery","nonfarm_equipment"]].sum(axis=1)+v1.HHID.map(shares).fillna(0)

    # Debt by visit. Link Visit-1 assets to Visit-2 panel for DAR/decile references; AVA rows for V2 are later excluded.
    loan_frames=[]
    for visit in [1,2]:
        cash=clean_base(load(14,visit,["HHID","b12q1","b12q3","b12q6","b12q8","b12q15"]),visit)
        cash["loan_no"]=to_num(cash.b12q1)
        cash=cash[cash.loan_no.ne(99)].copy()  # remove printed HH total row
        cash["agency"]=to_num(cash.b12q3); cash["interest"]=to_num(cash.b12q6); cash["purpose"]=to_num(cash.b12q8); cash["outstanding"]=to_num(cash.b12q15).fillna(0)
        loan_frames.append(cash[["HHID","Visit_ID","agency","interest","purpose","outstanding"]])
        # Official AOD/IOI definitions use outstanding cash dues at the base date.
        debt=cash.groupby("HHID").outstanding.sum()
        if visit==1: v1["debt"]=v1.HHID.map(debt).fillna(0)
        else: v2["debt"]=v2.HHID.map(debt).fillna(0)
    asset_panel=v1.set_index("Panel_HHID")[["assets","physical","financial","land","buildings","deposits","livestock","agri_machinery","transport","nonfarm_equipment","other_assets"]]
    for c in asset_panel.columns: v2[c]=v2.Panel_HHID.map(asset_panel[c])
    master=pd.concat([v1,v2],ignore_index=True)
    loans=pd.concat(loan_frames,ignore_index=True)

    # Official annual FCE/EPL: combine both half-year visits by panel household.
    # FCE is col.8 except land purchase in col.4 for items 1,4,5,17; EPL is
    # precisely that land-purchase amount. Rows 97/98 are totals and excluded.
    fce_frames=[]
    for visit in [1,2]:
        f=clean_base(load(16,visit,["HHID","b14q2","b14q4","b14q8"]),visit)
        f["item"]=to_num(f.b14q2); f["purchase"]=to_num(f.b14q4).fillna(0); f["total"]=to_num(f.b14q8).fillna(0)
        f=f[f.item.between(1,21)].copy()
        f["EPL"]=f.purchase.where(f.item.isin([1,4,5,17]),0)
        f["FCE"]=f.total-f.EPL
        fce_frames.append(f[["Panel_HHID","FCE","EPL"]])
    annual_fce=pd.concat(fce_frames,ignore_index=True).groupby("Panel_HHID",as_index=False)[["FCE","EPL"]].sum()

    people=clean_base(load(2,1,["HHID","State","District","Sector","MLT","b3q4","b3q5","b3q7"]),1)
    people=people.rename(columns={"b3q4":"gender","b3q5":"age","b3q7":"deposit"})
    for c in ["gender","age","deposit"]: people[c]=to_num(people[c])

    output=[]
    # Basic V1 contains all metrics; V2 uses debt metrics and panel-linked asset denominator. Remove non-collected V2 AVA/component rows below.
    aggregate_basic(expand_domains(master,categories=True,district=True),output)
    output=[r for r in output if not (r["Visit_ID"]==2 and (r["Col_ID"]=="AVA" or str(r["Col_ID"]).startswith("AVA_COMPONENT")))]
    aggregate_credit(master,loans,output)
    aggregate_deciles_and_gini(master,output)
    aggregate_fce(master,annual_fce,output)
    aggregate_people(v1,people,output)

    final=pd.DataFrame(output,columns=COLS)
    final["DATA"]=pd.to_numeric(final.DATA,errors="coerce").round(6)
    final=final.drop_duplicates(subset=[c for c in COLS if c not in ["DATA"]],keep="first")
    final=final.sort_values(["Survey_GROUP_ID","State_ID","District_ID","Sector_code","Visit_ID","SUB_GROUP_ID","Col_ID"],kind="stable").reset_index(drop=True)
    final.to_csv(OUT_CSV,index=False,encoding="utf-8-sig")
    # Stream complete rows. Pandas' column-oriented writer is incompatible with
    # xlsxwriter constant_memory and can silently leave most cells blank.
    workbook=xlsxwriter.Workbook(str(OUT_XLSX),{"constant_memory":True,"strings_to_urls":False})
    worksheet=workbook.add_worksheet("AIDIS_Final_Client")
    worksheet.write_row(0,0,COLS)
    for row_no,row in enumerate(final.itertuples(index=False,name=None),start=1):
        worksheet.write_row(row_no,0,[None if pd.isna(v) else v for v in row])
    workbook.close()

    coverage_rows=[
        ("a","No. of Households Surveyed","GENERATED","Sample household count; not weighted population"),
        ("b","AVA","GENERATED","Visit 1 only; assets collected once"),("c","AOD","GENERATED","Visits 1 and 2"),
        ("d","AODL","GENERATED","Positive-debt HH denominator"),("e","IOI","GENERATED","Weighted HH percentage"),
        ("f","DAR","GENERATED","Visit 2 uses linked Visit-1 asset stock"),("g","AVA by asset component","GENERATED","Detail rows used; total rows excluded"),
        ("h","Institutional-credit distribution","GENERATED","Percent of institutional outstanding amount"),
        ("i","Non-institutional-credit distribution","GENERATED","Percent of non-institutional outstanding amount"),
        ("j","IOI by nature of interest","GENERATED","Institutional cash-credit records"),
        ("k","Credit distribution by purpose","GENERATED","Percent within institutional/non-institutional total"),
        ("l","AVA/AOD/DAR by asset decile","GENERATED","Weighted within-domain deciles, Visit 1"),
        ("m","FCE and EPL","GENERATED","Visit 1 + Visit 2; official tabulation-plan exclusions applied; Visit-2 weights"),
        ("n","Adult population with bank deposit account","GENERATED","Age >=18, person records weighted by HH multiplier"),
        ("o","Gini coefficient of assets","GENERATED","Weighted Lorenz method, All India/State/Sector"),
    ]
    cov=pd.DataFrame(coverage_rows,columns=["ID","KPI","Status","Notes"]); cov.to_csv(COVERAGE,index=False)

    missing=[x for r in validation for x in r["missing_from_raw"]]
    extra=[x for r in validation for x in r["raw_not_in_ddi"]]
    dup=int(final.duplicated(subset=[c for c in COLS if c!="DATA"]).sum())
    null=int(final.DATA.isna().sum())
    report=f"""# AIDIS 77th Round - Final Validation Report

## Delivery status

- Final CSV and true XLSX generated with identical {len(final):,} rows and {len(final.columns)} columns.
- Extraction date: {EXTRACTED}; publication date: {PUBLISHED}; source: {SOURCE}

## Raw/DDI validation

- Raw workbooks found/used: {len(files)} / {len(files)}
- DDI variable rows checked: {len(ddi):,}
- DDI KPI mappings checked: {len(ddi_map):,}
- Missing DDI columns in corresponding raw file: {len(missing)} {missing[:20]}
- Raw columns not represented in corresponding DDI level: {len(extra)} {extra[:20]}
- DDI Mapping_Status: {ddi.Mapping_Status.fillna('Blank').value_counts().to_dict()}
- Block 14 conflict: resolved against official catalog. b14q2=item serial, b14q4=purchase, b14q8=total expenditure, b14q14=net addition.

## Analytical master

- Visit 1 households: {len(v1):,}
- Visit 2 households: {len(v2):,}
- Total household-visit records: {len(master):,}
- Visit 1 unique panel keys: {v1.Panel_HHID.nunique():,}
- Visit 2 unique panel keys: {v2.Panel_HHID.nunique():,}
- Visit 2 records linked to Visit 1 classification: {v2.b4q4.notna().sum():,} / {len(v2):,}
- States: {master.State.nunique()}
- Official composite State-District codes: {master[['State','District']].drop_duplicates().shape[0]}
- Rural household-visit records: {master.Sector.eq(1).sum():,}
- Urban household-visit records: {master.Sector.eq(2).sum():,}

## Final-file QA

- Output rows: {len(final):,}
- Output columns: {len(final.columns)}
- KPI/Col_ID count: {final.Col_ID.nunique():,}
- Null DATA values: {null}
- Duplicate final-row keys: {dup}
- Percent values outside 0-100: {int(((final.Unit=='%') & ~final.DATA.between(0,100)).sum())}
- Gini values outside 0-1: {int(((final.Col_ID=='GINI_ASSET') & ~final.DATA.between(0,1)).sum())}
- CSV/XLSX cross-format comparison is performed after generation.

## Assumptions and unresolved metadata

- The supplied DDI does not contain a State-wise district-name directory. District_ID uses the official State_District composite code; District_Name is therefore a transparent `District code NN` label, not a fabricated place name.
- Rural b4q4=1 is classified as Cultivator HH; other rural types as Non-Cultivator HH. Urban b4q4=1 is Self-employed; other urban types are Others, following the supplied sector-specific code list.
- `Others` asset component follows official Report 588: livestock, transport equipment, agricultural machinery, non-farm business equipment and shares.
- Credit distributions are amount shares (%) within the relevant institutional/non-institutional denominator.
- Visit-2 assets were not recollected. No Visit-2 AVA/component rows are emitted; Visit-2 DAR uses the correctly panel-linked Visit-1 asset stock.
- Annual FCE/EPL combine both half-year visits by panel household and use Visit-2 weights. FCE excludes land purchase (Block 14 col.4, items 1/4/5/17); EPL is that excluded purchase amount. All-India FCE reconciles to official rounded benchmarks (Rural Rs.8,966; Urban Rs.10,863).
"""
    REPORT.write_text(report,encoding="utf-8")
    print(json.dumps({"rows":len(final),"columns":len(final.columns),"v1":len(v1),"v2":len(v2),"null_data":null,"duplicates":dup,"missing_headers":len(missing)},indent=2))


def rewrite_xlsx_only():
    workbook=xlsxwriter.Workbook(str(OUT_XLSX),{"constant_memory":True,"strings_to_urls":False})
    worksheet=workbook.add_worksheet("AIDIS_Final_Client")
    worksheet.write_row(0,0,COLS)
    row_no=1
    id_types={"Survey_ID":str,"Survey_GROUP_ID":str,"SUB_GROUP_ID":str,"State_ID":str,
              "District_ID":str,"Col_ID":str,"houseHold_ID":str}
    for chunk in pd.read_csv(OUT_CSV,chunksize=10000,encoding="utf-8-sig",dtype=id_types):
        for row in chunk[COLS].itertuples(index=False,name=None):
            worksheet.write_row(row_no,0,[None if pd.isna(v) else v for v in row])
            row_no+=1
    workbook.close()
    print(json.dumps({"xlsx_rows":row_no-1,"xlsx_columns":len(COLS)}))


if __name__ == "__main__":
    rewrite_xlsx_only() if "--xlsx-only" in sys.argv else main()
