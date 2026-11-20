from __future__ import annotations
import numpy as np
import pandas as pd
from ..utils import clean_code
from ..io import read_table, discover_files, map_recent_levels

KEY=["FSU_Serial_No","Second_Stage_Stratum_No","Sample_Household_No"]

# Canonical aliases across HCES 2022-23 and HCES 2023-24.
# 2022-23 raw files use lower-case/DDI variable names in several levels,
# whereas 2023-24 uses descriptive names.
ALIASES={
 "FSU_Serial_No":["FSU_Serial_No","fsu_serial_no","fsu"],
 "Second_Stage_Stratum_No":["Second_Stage_Stratum_No","second_stage_stratum_no","second_stage_stratum","sss","b1q1pt11"],
 "Sample_Household_No":["Sample_Household_No","sample_household_no","sample_hhld_no","b1q1pt12"],
 "State":["State","state"],
 "District":["District","district"],
 "Sector":["Sector","sector"],
 "Questionnaire_No":["Questionnaire_No","questionnaire_no","questionaire_no"],
 "VISIT":["VISIT","visit"],
 "HOUSEHOLD_SIZE":["HOUSEHOLD_SIZE","household_size","ba2b2c2q9"],
 "MULTIPLIER":["MULTIPLIER","Multiplier","mult","mlt"],
 "HH_Size_FDQ":["HH_Size_FDQ","hh_size_fdq","b2q2pt1"],
 "SECTION":["SECTION","section","ba1b1c1_1"],
 "ITEM_CODE":["ITEM_CODE","item_code","ba1b1c1_2"],
 "VALUE_RS":["VALUE_RS","value_rs","value","ba1b1c1_3"],
}

def canon(df):
    d=df.copy()
    d.columns=[str(c).strip() for c in d.columns]
    lower={str(c).lower():c for c in d.columns}
    ren={}
    for target,opts in ALIASES.items():
        for o in opts:
            if o in d.columns:
                ren[o]=target
                break
            if o.lower() in lower:
                ren[lower[o.lower()]]=target
                break
    d=d.rename(columns=ren)

    for c,w in {
        "FSU_Serial_No":5,
        "Second_Stage_Stratum_No":1,
        "Sample_Household_No":2,
        "State":2,
        "District":2,
    }.items():
        if c in d:
            d[c]=clean_code(d[c],w)

    if all(c in d for c in KEY):
        d["HH_KEY"]=d[KEY].astype(str).agg("_".join,axis=1)
    return d

def load_level(path):
    return canon(read_table(path))

def _normalize_q(s):
    return s.astype("string").str.strip().str.upper().str[:1]

def _build_level15_controls(l15,cfg):
    """
    Build P1/P2/P3 and final multiplier from Level 15.

    2023-24 contains an explicit VISIT field.
    2022-23 does NOT contain VISIT: each household instead has H/F/C/D rows
    (sections 11/A2/B2/C2), and the final third-visit multiplier is replicated
    on those Level-15 rows. Therefore VISIT must never be mandatory for 2022-23.
    """
    required=["HH_KEY","Questionnaire_No","HOUSEHOLD_SIZE","MULTIPLIER"]
    missing=[c for c in required if c not in l15.columns]
    if missing:
        raise KeyError(
            "Level15 is missing required canonical field(s): "
            f"{missing}. Available columns: {list(l15.columns)}"
        )

    x=l15.copy()
    x["Questionnaire_No"]=_normalize_q(x["Questionnaire_No"])
    x["HOUSEHOLD_SIZE"]=pd.to_numeric(x["HOUSEHOLD_SIZE"],errors="coerce")
    x["MULTIPLIER"]=pd.to_numeric(x["MULTIPLIER"],errors="coerce")

    # P1/P2/P3 are questionnaire-specific sizes, not visit-number-specific sizes.
    q=x[x["Questionnaire_No"].isin(["F","C","D"])].copy()
    if "VISIT" in q.columns:
        q["VISIT_N"]=pd.to_numeric(q["VISIT"],errors="coerce")
        q=q.sort_values(["HH_KEY","Questionnaire_No","VISIT_N"])
    q=q.drop_duplicates(["HH_KEY","Questionnaire_No"],keep="last")

    sizes=(
        q.pivot(index="HH_KEY",columns="Questionnaire_No",values="HOUSEHOLD_SIZE")
         .rename(columns={"F":"P1","C":"P2","D":"P3"})
         .reset_index()
    )

    if "VISIT" in x.columns:
        # 2023-24: use explicit third-visit multiplier when present.
        x["VISIT_N"]=pd.to_numeric(x["VISIT"],errors="coerce")
        tv=(
            x[x["VISIT_N"].eq(3)][["HH_KEY","MULTIPLIER"]]
            .dropna(subset=["MULTIPLIER"])
            .sort_values("HH_KEY")
            .drop_duplicates("HH_KEY",keep="last")
            .rename(columns={"MULTIPLIER":"THIRD_VISIT_MULTIPLIER"})
        )
        weight_mode="explicit_visit_3"
    else:
        # 2022-23: no VISIT variable exists in Level 15. The final multiplier
        # is replicated on H/F/C/D rows. Enforce within-household consistency
        # before using the replicated value.
        pos=x[x["MULTIPLIER"].gt(0)][["HH_KEY","MULTIPLIER"]].dropna()
        nunique=pos.groupby("HH_KEY")["MULTIPLIER"].nunique()
        bad=nunique[nunique.gt(1)]
        if len(bad):
            examples=bad.head(10).index.tolist()
            raise ValueError(
                "2022-23 Level15 has no VISIT field and contains multiple "
                "positive multiplier values within some households; cannot "
                "identify the final third-visit multiplier safely. "
                f"Example HH_KEY values: {examples}"
            )
        tv=(
            pos.drop_duplicates("HH_KEY")
               .rename(columns={"MULTIPLIER":"THIRD_VISIT_MULTIPLIER"})
        )
        weight_mode="replicated_final_multiplier_no_visit"

    tv["FINAL_WEIGHT"]=(
        tv["THIRD_VISIT_MULTIPLIER"] /
        float(cfg["survey"].get("weight_divisor",100))
    )
    return sizes,tv,weight_mode

def run(raw_dir,cfg):
    files=discover_files(raw_dir)
    levels=map_recent_levels(files)
    need=[1,3,14,15]
    miss=[x for x in need if x not in levels]
    if miss:
        raise FileNotFoundError(
            f"Missing recent-HCES levels: {miss}. Found: {levels}"
        )

    l1=load_level(levels[1])
    l3=load_level(levels[3])
    l15=load_level(levels[15])

    if "HH_KEY" not in l1:
        raise KeyError(f"Level01 household key could not be built. Columns: {list(l1.columns)}")

    h=l1.drop_duplicates("HH_KEY").copy()
    keep=[c for c in ["HH_KEY","State","District","Sector"] if c in h]
    h=h[keep]

    if "HH_Size_FDQ" in l3:
        z=l3[["HH_KEY","HH_Size_FDQ"]].drop_duplicates("HH_KEY")
        z["HH_Size_FDQ"]=pd.to_numeric(z["HH_Size_FDQ"],errors="coerce")
        h=h.merge(z,on="HH_KEY",how="left")

    sizes,tv,weight_mode=_build_level15_controls(l15,cfg)
    h=h.merge(sizes,on="HH_KEY",how="left").merge(tv,on="HH_KEY",how="left")

    # Keep only households valid for the official three-questionnaire MPCE.
    h=h[
        h[["P1","P2","P3"]].notna().all(axis=1) &
        h[["P1","P2","P3"]].gt(0).all(axis=1) &
        h["FINAL_WEIGHT"].gt(0)
    ].copy()

    # Level 14 may be very large; stream CSV where possible.
    p=levels[14]
    if p.suffix.lower()==".csv":
        chunks=pd.read_csv(p,dtype=str,chunksize=500000,low_memory=False)
    else:
        chunks=[read_table(p)]

    sums=[]
    cereals=[]
    for raw in chunks:
        x=canon(raw)
        req=["HH_KEY","Questionnaire_No","SECTION","ITEM_CODE","VALUE_RS"]
        missing=[c for c in req if c not in x.columns]
        if missing:
            raise KeyError(
                f"Level14 missing canonical field(s) {missing}. "
                f"Available columns: {list(x.columns)}"
            )

        x["Questionnaire_No"]=_normalize_q(x["Questionnaire_No"])
        x["VALUE_RS"]=pd.to_numeric(x["VALUE_RS"],errors="coerce")
        x=x[x["Questionnaire_No"].isin(["F","C","D"])]

        sums.append(
            x.groupby(["HH_KEY","Questionnaire_No"],as_index=False)["VALUE_RS"]
             .sum(min_count=1)
        )

        item=clean_code(x["ITEM_CODE"],3)
        sec=x["SECTION"].astype("string").str.strip()
        c=x[
            x["Questionnaire_No"].eq("F") &
            sec.eq("5.1") &
            item.isin(["129","139"])
        ]
        if len(c):
            cereals.append(
                c.groupby("HH_KEY",as_index=False)["VALUE_RS"].sum(min_count=1)
            )

    by=(
        pd.concat(sums,ignore_index=True)
        .groupby(["HH_KEY","Questionnaire_No"],as_index=False)["VALUE_RS"]
        .sum(min_count=1)
    )
    e=(
        by.pivot(index="HH_KEY",columns="Questionnaire_No",values="VALUE_RS")
          .rename(columns={"F":"E1","C":"E2","D":"E3"})
          .reset_index()
    )

    if cereals:
        ce=(
            pd.concat(cereals,ignore_index=True)
            .groupby("HH_KEY",as_index=False)["VALUE_RS"]
            .sum(min_count=1)
            .rename(columns={"VALUE_RS":"CEREAL"})
        )
    else:
        ce=pd.DataFrame(columns=["HH_KEY","CEREAL"])

    d=h.merge(e,on="HH_KEY",how="left").merge(ce,on="HH_KEY",how="left")

    ok=d[["E1","E2","E3"]].notna().all(axis=1)
    d["MPCE_TOTAL"]=np.nan
    d.loc[ok,"MPCE_TOTAL"]=(
        d.loc[ok,"E1"] +
        (d.loc[ok,"E2"]/d.loc[ok,"P2"])*d.loc[ok,"P1"] +
        (d.loc[ok,"E3"]/d.loc[ok,"P3"])*d.loc[ok,"P1"]
    )/d.loc[ok,"P1"]

    d["MPCE_FOOD"]=np.where(ok,d["E1"]/d["P1"],np.nan)
    d["MPCE_NONFOOD"]=np.where(ok,d["MPCE_TOTAL"]-d["MPCE_FOOD"],np.nan)
    d["MPCE_CEREAL"]=np.where(ok,d["CEREAL"].fillna(0)/d["P1"],np.nan)

    d["District_ID"]=d["State"].str.zfill(2)+d["District"].str.zfill(2)
    d["Sector_Name"]=d["Sector"].map({"1":"rural","2":"urban"})
    d["PERSON_WEIGHT"]=d["FINAL_WEIGHT"]*d["P1"]

    manifest={f"level_{k:02d}":str(v) for k,v in levels.items()}
    manifest["level15_weight_mode"]=weight_mode
    manifest["eligible_three_questionnaire_households"]=str(len(d))
    return d,manifest