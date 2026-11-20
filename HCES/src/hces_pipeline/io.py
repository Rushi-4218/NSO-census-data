from __future__ import annotations
from pathlib import Path
import pandas as pd
from .utils import normalize_name


def discover_files(root):
    root=Path(root)
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".csv",".xlsx",".xls",".txt"}]


def read_table(path, nrows=None, usecols=None, chunksize=None):
    path=Path(path); suf=path.suffix.lower()
    if suf==".csv":
        return pd.read_csv(path,dtype=str,nrows=nrows,usecols=usecols,chunksize=chunksize,low_memory=False)
    if suf in {".xlsx",".xls"}:
        if chunksize: raise ValueError("Chunked XLSX read is not supported")
        return pd.read_excel(path,dtype=str,nrows=nrows,usecols=usecols)
    if suf==".txt":
        return pd.read_csv(path,dtype=str,nrows=nrows,usecols=usecols,sep=None,engine="python",chunksize=chunksize)
    raise ValueError(path)


def find_file(files, must_contain):
    toks=[normalize_name(x) for x in must_contain]
    scored=[]
    for p in files:
        n=normalize_name(p.name)
        score=sum(t in n for t in toks)
        if score: scored.append((score,len(n),p))
    if not scored: return None
    return sorted(scored,key=lambda z:(-z[0],z[1]))[0][2]


def map_recent_levels(files):
    out={}
    for lv in range(1,16):
        candidates=[]
        for p in files:
            n=normalize_name(p.name)
            if f"level{lv:02d}" in n or f"lvl{lv:02d}" in n or f"level{lv}" in n or f"lvl{lv}" in n:
                candidates.append(p)
        if candidates: out[lv]=sorted(candidates,key=lambda p:len(p.name))[0]
    return out


def map_legacy_2011(files):
    specs={
      "id": ["identification","level1"],
      "hh2": ["householdcharacteristics","level2"],
      "hh3": ["householdcharacteristics","level3"],
      "members": ["demographic","level4"],
      "block5": ["block5","level5"],
      "block6": ["block7and8","level6"],
      "block7": ["block9","level7"],
      "block8": ["block10","level8"],
      "block9": ["block11","level9"],
      "block10": ["block13","level10"],
      "block11": ["block12","level11"],
    }
    return {k:find_file(files,v) for k,v in specs.items()}
