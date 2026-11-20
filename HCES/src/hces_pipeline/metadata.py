from __future__ import annotations
from pathlib import Path
import pandas as pd


def load_lookup_from_dictionary(path, code_list_id=None):
    if not path or not Path(path).exists(): return pd.DataFrame()
    try: df=pd.read_excel(path,sheet_name="Lookup",dtype=str)
    except Exception: return pd.DataFrame()
    if code_list_id and "CODE_LIST_ID" in df.columns:
        df=df[df["CODE_LIST_ID"].eq(code_list_id)].copy()
    return df


def _read_lookup(filename, optional_dir, packaged_dir):
    """Prefer a survey-specific override, then use the versioned lookup shipped with code."""
    for directory in (Path(optional_dir), Path(packaged_dir) if packaged_dir else None):
        if directory is None:
            continue
        path = directory / filename
        if path.exists():
            return pd.read_csv(path, dtype=str)
    return None


def load_state_district_lookups(optional_dir, packaged_dir=None):
    optional_dir=Path(optional_dir)
    return (
        _read_lookup("state_lookup.csv", optional_dir, packaged_dir),
        _read_lookup("district_lookup.csv", optional_dir, packaged_dir),
    )
