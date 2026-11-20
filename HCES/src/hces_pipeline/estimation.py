from __future__ import annotations
import numpy as np
import pandas as pd
from .utils import weighted_mean, weighted_gini


def summarize_domain(g):
    pw=pd.to_numeric(g["PERSON_WEIGHT"],errors="coerce")
    valid_total=g["MPCE_TOTAL"].notna() & pw.notna() & pw.gt(0)
    valid_components=valid_total & g["MPCE_FOOD"].notna() & g["MPCE_NONFOOD"].notna()
    valid_cereal=valid_total & g["MPCE_CEREAL"].notna()
    v=g.loc[valid_total]; w=v["PERSON_WEIGHT"]
    c=g.loc[valid_components]; cw=c["PERSON_WEIGHT"]
    cereal=g.loc[valid_cereal]; cereal_w=cereal["PERSON_WEIGHT"]
    return pd.Series({
      "sample_households": int(g["HH_KEY"].nunique()),
      "valid_mpce_households": int(v["HH_KEY"].nunique()),
      "component_complete_households": int(c["HH_KEY"].nunique()),
      "household_weight_sum": pd.to_numeric(g["FINAL_WEIGHT"],errors="coerce").sum(),
      "person_weight_sum": pd.to_numeric(w,errors="coerce").sum(),
      "avg_mpce_total": weighted_mean(v["MPCE_TOTAL"],w),
      # Shares use a common complete-component universe. Do not silently
      # treat a missing detailed-food record as zero or mix denominators.
      "avg_mpce_total_components": weighted_mean(c["MPCE_TOTAL"],cw),
      "avg_mpce_food": weighted_mean(c["MPCE_FOOD"],cw),
      "avg_mpce_nonfood": weighted_mean(c["MPCE_NONFOOD"],cw),
      "avg_mpce_cereal": weighted_mean(cereal["MPCE_CEREAL"],cereal_w),
      "gini": weighted_gini(v["MPCE_TOTAL"],w),
    })


def _apply_group(df, keys):
    return df.groupby(keys,dropna=False).apply(summarize_domain,include_groups=False).reset_index()


def aggregate_all(hh):
    pieces=[]
    d=_apply_group(hh,["State","District_ID","Sector_Name"]); d["geo_level"]="District"; pieces.append(d)
    dt=_apply_group(hh,["State","District_ID"]); dt["Sector_Name"]="total"; dt["geo_level"]="District"; pieces.append(dt)
    s=_apply_group(hh,["State","Sector_Name"]); s["District_ID"]="0000"; s["geo_level"]="State"; pieces.append(s)
    st=_apply_group(hh,["State"]); st["Sector_Name"]="total"; st["District_ID"]="0000"; st["geo_level"]="State"; pieces.append(st)
    i=_apply_group(hh,["Sector_Name"]); i["State"]="00"; i["District_ID"]="0000"; i["geo_level"]="All India"; pieces.append(i)
    it=summarize_domain(hh).to_frame().T; it["State"]="00"; it["District_ID"]="0000"; it["Sector_Name"]="total"; it["geo_level"]="All India"; pieces.append(it)
    out=pd.concat(pieces,ignore_index=True)
    denominator=out["avg_mpce_total_components"]
    out["share_total"]=np.where(denominator.notna() & denominator.ne(0),100.0,np.nan)
    out["share_food"]=out["avg_mpce_food"]/denominator*100
    out["share_nonfood"]=out["avg_mpce_nonfood"]/denominator*100
    out["share_cereal"]=out["avg_mpce_cereal"]/denominator*100
    return out
