from __future__ import annotations
from pathlib import Path
import yaml
import pandas as pd
from .utils import ensure_dirs
from .metadata import load_state_district_lookups
from .estimation import aggregate_all
from .output import CLIENT_COLUMNS,attach_names,aggregate_outputs
from .qa import final_output_checks,qa_summary
from .adapters import recent,legacy2011


def load_config(root,year):
    with open(Path(root)/"config/surveys.yaml","r",encoding="utf-8") as f: allcfg=yaml.safe_load(f)
    return {"client":allcfg["client"],"survey":allcfg["surveys"][year]}


def run_year(root,year,validate_only=False):
    root=Path(root); cfg=load_config(root,year); inp=root/"input"/year; raw=inp/"raw_microdata"; meta=inp/"metadata"; opt=inp/"optional"; out=root/"output"/year; work=root/"work"/year; ensure_dirs(out,work)
    if cfg["survey"]["model"]=="legacy_2011": hh,manifest=legacy2011.run(raw,cfg,meta)
    else: hh,manifest=recent.run(raw,cfg)
    agg=aggregate_all(hh)
    state,district=load_state_district_lookups(opt,root/"config"); agg=attach_names(agg,state,district)
    # Attach household names from aggregate geography mappings.
    sm=agg[agg.geo_level.eq("State")][["State","State_Name"]].drop_duplicates("State"); dm=agg[agg.geo_level.eq("District")][["District_ID","District_Name"]].drop_duplicates("District_ID")
    hh=hh.merge(sm,on="State",how="left").merge(dm,on="District_ID",how="left")
    qa=qa_summary(hh,agg); qa.to_csv(out/f"HCES_{year}_Pipeline_QA.csv",index=False)
    pd.DataFrame([{"Component":k,"Path":v} for k,v in manifest.items()]).to_csv(out/f"HCES_{year}_Run_Manifest.csv",index=False)
    if validate_only: return
    cpi_path=opt/"cpi_deflator.csv"; cpi=pd.read_csv(cpi_path,dtype=str) if cpi_path.exists() else None
    # The 21-column client contract has no household identifier.  Household
    # MPCE observations remain in the local analytical file, while the client
    # final file is strictly aggregate-grain to prevent hidden duplicate keys.
    final=aggregate_outputs(agg,cfg,cpi)
    final_qa=final_output_checks(final,CLIENT_COLUMNS,cfg["client"]["subgroups"]["household_nominal"]["id"])
    final_qa.to_csv(out/f"HCES_{year}_Final_Output_QA.csv",index=False)
    if final_qa.Status.eq("FAIL").any():
        raise ValueError(f"HCES {year} final client-output contract failed; see {out / f'HCES_{year}_Final_Output_QA.csv'}")
    final.to_csv(out/f"HCES_{year}_All_India_State_District_Final.csv",index=False,encoding="utf-8-sig")
    hh.to_csv(out/f"HCES_{year}_Household_Analytical.csv",index=False); agg.to_csv(out/f"HCES_{year}_Aggregates.csv",index=False)
    dq=agg[agg.geo_level.eq("District")][["State","District_ID","Sector_Name","sample_households","valid_mpce_households"]].copy(); dq["LOW_SAMPLE_FLAG_30"]=dq.sample_households.lt(30); dq.to_csv(out/f"HCES_{year}_District_QC.csv",index=False)
