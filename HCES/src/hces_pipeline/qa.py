from __future__ import annotations
import pandas as pd


def qa_summary(hh,agg,threshold=30):
    rows=[]
    def add(check,result,status): rows.append({"Check":check,"Result":result,"Status":status})
    add("Unique internal household key",hh.HH_KEY.nunique(),"PASS" if hh.HH_KEY.is_unique else "FAIL")
    add("Missing final weights",int(hh.FINAL_WEIGHT.isna().sum()),"PASS" if hh.FINAL_WEIGHT.notna().all() else "FAIL")
    complete=hh.MPCE_TOTAL.notna() & hh.MPCE_FOOD.notna() & hh.MPCE_NONFOOD.notna()
    err=(hh.loc[complete,"MPCE_TOTAL"]-hh.loc[complete,"MPCE_FOOD"]-hh.loc[complete,"MPCE_NONFOOD"]).abs().max(skipna=True); add("Food + Non-Food = Total max error",float(err or 0),"PASS" if pd.isna(err) or err<1e-6 else "FAIL")
    missing_components=int((hh.MPCE_TOTAL.notna() & ~complete).sum()); add("MPCE households missing detailed food/non-food component",missing_components,"WARN" if missing_components else "PASS")
    serr=(agg.share_food+agg.share_nonfood-100).abs().max(skipna=True); add("Food + Non-Food share = 100 max error",float(serr or 0),"PASS" if pd.isna(serr) or serr<1e-6 else "FAIL")
    low=int(((agg.geo_level=="District")&(agg.sample_households<threshold)).sum()); add(f"District domains sample < {threshold}",low,"WARN" if low else "PASS")
    return pd.DataFrame(rows)


def final_output_checks(final, expected_columns, household_subgroup_id):
    """Validate the aggregate-only client contract before a final file is written."""
    key=["Survey_ID","SUB_GROUP_ID","Year","State_ID","District_ID","Sector_code","Col_ID"]
    rows=[]
    rows.append({"Check":"Exact client schema","Result":len(final.columns),"Status":"PASS" if list(final.columns)==list(expected_columns) else "FAIL"})
    rows.append({"Check":"Duplicate aggregate analytical keys","Result":int(final.duplicated(key).sum()),"Status":"PASS" if not final.duplicated(key).any() else "FAIL"})
    household_rows=int(final["SUB_GROUP_ID"].astype(str).eq(str(household_subgroup_id)).sum())
    rows.append({"Check":"Household rows excluded from aggregate client output","Result":household_rows,"Status":"PASS" if household_rows==0 else "FAIL"})
    return pd.DataFrame(rows)
