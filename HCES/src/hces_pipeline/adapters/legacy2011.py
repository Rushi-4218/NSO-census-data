from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from ..io import discover_files,map_legacy_2011,read_table
from ..utils import clean_code
from ..metadata import load_lookup_from_dictionary


def _prep(df):
    d=df.copy(); d.columns=[str(c).strip() for c in d.columns]
    for c,w in {"FSU_Serial_No":5,"Second_Stage_Stratum_No":1,"Sample_hhld_no":2,"State_code":2,"District_Code":4,"Sector":1}.items():
        if c in d: d[c]=clean_code(d[c],w)
    if "HHID" in d: d["HH_KEY"]=d.HHID.astype(str).str.strip()
    else: d["HH_KEY"]=d[["FSU_Serial_No","Second_Stage_Stratum_No","Sample_hhld_no"]].astype(str).agg("_".join,axis=1)
    return d


def run(raw_dir,cfg,metadata_dir):
    files=discover_files(raw_dir); m=map_legacy_2011(files)
    missing=[k for k,v in m.items() if v is None]
    if missing: raise FileNotFoundError(f"Missing 2011-12 files: {missing}")
    l1=_prep(read_table(m["id"])); l2=_prep(read_table(m["hh2"])); l3=_prep(read_table(m["hh3"]));
    h=l1[[c for c in ["HH_KEY","Sector","State_code","District_Code","Combined_Multiplier"] if c in l1]].drop_duplicates("HH_KEY")
    z=l2[["HH_KEY","hh_size"]].drop_duplicates("HH_KEY"); z["hh_size"]=pd.to_numeric(z.hh_size,errors="coerce"); h=h.merge(z,on="HH_KEY",how="left")
    p=l3[["HH_KEY","MPCE"]].drop_duplicates("HH_KEY"); p["MPCE"]=pd.to_numeric(p.MPCE,errors="coerce"); h=h.merge(p,on="HH_KEY",how="left")
    h["FINAL_WEIGHT"]=pd.to_numeric(h.Combined_Multiplier,errors="coerce")/float(cfg["survey"].get("weight_divisor",1))
    # Food/cereal from detailed Block 5. Exclude subtotal rows by dictionary labels.
    b5path=m["block5"]
    dictionary=Path(metadata_dir)/cfg["survey"]["dictionary"]
    lookup=load_lookup_from_dictionary(dictionary,"L05_ITEM_CODE")
    subtotal=set()
    if len(lookup):
        for r in lookup.itertuples(index=False):
            lab=str(getattr(r,"LABEL","")).lower(); code=str(getattr(r,"CODE","")).zfill(3)
            if "s.t" in lab or "sub-total" in lab or "subtotal" in lab: subtotal.add(code)
    sums=[]; cereals=[]
    chunks=pd.read_csv(b5path,dtype=str,chunksize=500000,low_memory=False) if b5path.suffix.lower()==".csv" else [read_table(b5path)]
    cereal_codes=set([str(x) for x in range(101,123)])|{"139"}
    for raw in chunks:
        x=_prep(raw); x["Item_Code"]=clean_code(x.Item_Code,3); x["Total_Consumption_Value"]=pd.to_numeric(x.Total_Consumption_Value,errors="coerce")
        detail=x[~x.Item_Code.isin(subtotal)].copy()
        # Official Schedule 1.0 item map: codes 101-299 are food/processed food; 300+ pan/tobacco/intoxicants/fuel and therefore non-food for this client classification.
        food=detail[pd.to_numeric(detail.Item_Code,errors="coerce").between(101,299)]
        sums.append(food.groupby("HH_KEY",as_index=False).Total_Consumption_Value.sum(min_count=1))
        ce=detail[detail.Item_Code.isin(cereal_codes)];
        if len(ce): cereals.append(ce.groupby("HH_KEY",as_index=False).Total_Consumption_Value.sum(min_count=1))
    food=pd.concat(sums).groupby("HH_KEY",as_index=False).Total_Consumption_Value.sum(min_count=1).rename(columns={"Total_Consumption_Value":"FOOD_EXP"})
    cer=pd.concat(cereals).groupby("HH_KEY",as_index=False).Total_Consumption_Value.sum(min_count=1).rename(columns={"Total_Consumption_Value":"CEREAL_EXP"}) if cereals else pd.DataFrame(columns=["HH_KEY","CEREAL_EXP"])
    d=h.merge(food,on="HH_KEY",how="left").merge(cer,on="HH_KEY",how="left")
    d=d[d.hh_size.gt(0)&d.FINAL_WEIGHT.gt(0)&d.MPCE.notna()].copy()
    d["MPCE_TOTAL"]=d.MPCE; d["MPCE_FOOD"]=d.FOOD_EXP/d.hh_size; d["MPCE_NONFOOD"]=d.MPCE_TOTAL-d.MPCE_FOOD; d["MPCE_CEREAL"]=d.CEREAL_EXP.fillna(0)/d.hh_size
    d["State"]=clean_code(d.State_code,2); d["District_ID"]=clean_code(d.District_Code,4); d["Sector_Name"]=d.Sector.map({"1":"rural","2":"urban"}); d["P1"]=d.hh_size; d["PERSON_WEIGHT"]=d.FINAL_WEIGHT*d.hh_size
    return d, {k:str(v) for k,v in m.items()}
