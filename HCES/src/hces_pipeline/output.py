from __future__ import annotations
import numpy as np
import pandas as pd
from .utils import auto_date

CLIENT_COLUMNS=["Survey_ID","Survey_NAME","Survey_GROUP_ID","GROUP_NAME","SUB_GROUP_ID","SUB_GROUP_NAME","Year","FREQ_DESC","State_ID","State_Name","District_ID","District_Name","Sector_code","Sector","Published_date","Extracted_Date","Col_ID","COL_DESC","DATA","Unit","Source"]


def sector_code(x): return {"total":"0","rural":"1","urban":"2"}.get(str(x).lower(),"")


def attach_names(agg,state_lookup=None,district_lookup=None):
    x=agg.copy()
    x["State_Name"]=x["State"]
    x["District_Name"]=x["District_ID"]
    if state_lookup is not None:
        s=state_lookup.copy(); s.columns=[str(c).strip() for c in s.columns]
        sc=next((c for c in s if c.lower() in {"state","state_id","state_code","code"}),None); sn=next((c for c in s if c.lower() in {"state_name","name","label"}),None)
        if sc and sn:
            s["_s"]=s[sc].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(2)
            x=x.drop(columns="State_Name").merge(s[["_s",sn]].drop_duplicates("_s"),left_on="State",right_on="_s",how="left").rename(columns={sn:"State_Name"}).drop(columns="_s")
    if district_lookup is not None:
        d=district_lookup.copy(); d.columns=[str(c).strip() for c in d.columns]
        dc=next((c for c in d if c.lower() in {"district_id","district_code","code"}),None); dn=next((c for c in d if c.lower() in {"district_name","name","label"}),None)
        if dc and dn:
            d["_d"]=d[dc].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(4)
            x=x.drop(columns="District_Name").merge(d[["_d",dn]].drop_duplicates("_d"),left_on="District_ID",right_on="_d",how="left").rename(columns={dn:"District_Name"}).drop(columns="_d")
    x.loc[x.geo_level.eq("State"),"District_Name"]="All Districts"
    x.loc[x.geo_level.eq("All India"),["State_Name","District_Name"]]=["All India","All Districts"]
    return x


def base(df,cfg,subkey):
    c=cfg["client"]; s=cfg["survey"]; sg=c["subgroups"][subkey]; x=df.copy()
    x["Survey_ID"]=c["survey_id"]; x["Survey_NAME"]=c["survey_name"]; x["Survey_GROUP_ID"]=c["survey_group_id"]; x["GROUP_NAME"]=c["group_name"]
    x["SUB_GROUP_ID"]=sg["id"]; x["SUB_GROUP_NAME"]=sg["name"]; x["Year"]=s["year"]; x["FREQ_DESC"]=c["frequency"]
    x["State_ID"]=x["State"].astype(str).str.lstrip("0").replace("","0"); x["District_ID"]=x["District_ID"].astype(str).str.lstrip("0").replace("","0")
    x["Sector_code"]=x["Sector_Name"].map(sector_code); x["Sector"]=x["Sector_Name"].str.title()
    x["Published_date"]=s.get("published_date",""); x["Extracted_Date"]=auto_date(); x["Source"]=s["source"]
    return x


def aggregate_outputs(agg,cfg,cpi=None):
    ids=["State","State_Name","District_ID","District_Name","Sector_Name"]
    parts=[]
    m=agg.melt(id_vars=ids,value_vars=["avg_mpce_total","avg_mpce_food","avg_mpce_nonfood"],var_name="metric",value_name="DATA")
    mp={"avg_mpce_total":("1","Total"),"avg_mpce_food":("2","Food"),"avg_mpce_nonfood":("3","Non-Food")}
    m["Col_ID"]=m.metric.map(lambda z:mp[z][0]); m["COL_DESC"]=m.metric.map(lambda z:mp[z][1]); m["Unit"]="Rupees"; parts.append(base(m,cfg,"average_nominal"))
    const=m[ids+["Col_ID","COL_DESC","DATA"]].copy()
    if cfg["survey"].get("constant_price_identity"):
        pass
    elif cpi is not None:
        cp=cpi.copy(); cp.columns=[str(c).strip() for c in cp.columns]; cp["State_ID"]=cp["State_ID"].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(2); cp["Sector"]=cp["Sector"].astype(str).str.lower(); cp["Deflator"]=pd.to_numeric(cp["Deflator"],errors="coerce")
        const=const.merge(cp[["State_ID","Sector","Deflator"]],left_on=["State","Sector_Name"],right_on=["State_ID","Sector"],how="left"); const["DATA"]=pd.to_numeric(const["DATA"],errors="coerce")/const["Deflator"]
    else: const["DATA"]=np.nan
    const["Unit"]="Rupees"; parts.append(base(const,cfg,"average_constant"))
    sh=agg.melt(id_vars=ids,value_vars=["share_total","share_food","share_nonfood"],var_name="metric",value_name="DATA")
    sm={"share_total":("1","Total"),"share_food":("2","Food"),"share_nonfood":("3","Non-Food")}; sh["Col_ID"]=sh.metric.map(lambda z:sm[z][0]); sh["COL_DESC"]=sh.metric.map(lambda z:sm[z][1]); sh["Unit"]="Percent"; parts.append(base(sh,cfg,"share_mpce"))
    ce=agg[ids+["share_cereal"]].rename(columns={"share_cereal":"DATA"}); ce["Col_ID"]="1"; ce["COL_DESC"]="Cereals"; ce["Unit"]="Percent"; parts.append(base(ce,cfg,"cereal_share"))
    gi=agg[ids+["gini"]].rename(columns={"gini":"DATA"}); gi["Col_ID"]="1"; gi["COL_DESC"]="Total"; gi["Unit"]="Coefficient"; parts.append(base(gi,cfg,"gini"))
    return pd.concat([p[CLIENT_COLUMNS] for p in parts],ignore_index=True)


