from __future__ import annotations
from pathlib import Path
from datetime import date
import re
import numpy as np
import pandas as pd


def clean_code(s, width=None):
    x = pd.Series(s, copy=False).astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    if width:
        x = x.str.zfill(int(width))
    return x


def weighted_mean(x, w):
    x = pd.to_numeric(x, errors="coerce"); w = pd.to_numeric(w, errors="coerce")
    ok = x.notna() & w.notna() & w.gt(0)
    if not ok.any(): return np.nan
    return float(np.average(x[ok], weights=w[ok]))


def weighted_gini(x, w):
    x=np.asarray(pd.to_numeric(x,errors="coerce"),float)
    w=np.asarray(pd.to_numeric(w,errors="coerce"),float)
    ok=np.isfinite(x)&np.isfinite(w)&(w>0)
    x=x[ok]; w=w[ok]
    if len(x)==0 or np.sum(x*w)<=0: return np.nan
    o=np.argsort(x); x=x[o]; w=w[o]
    cw=np.cumsum(w); cxw=np.cumsum(x*w)
    X=np.r_[0,cw/cw[-1]]; Y=np.r_[0,cxw/cxw[-1]]
    return float(1-2*np.trapz(Y,X))


def normalize_name(x):
    return re.sub(r"[^a-z0-9]+","",str(x).lower())


def auto_date(): return date.today().isoformat()


def ensure_dirs(*paths):
    for p in paths: Path(p).mkdir(parents=True,exist_ok=True)
