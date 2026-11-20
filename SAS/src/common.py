from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .fast_xlsx import read_xlsx_selected


def read_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, obj: dict) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def norm_text(value, width: int | None = None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return ""
    s = str(value).strip()
    if re.fullmatch(r"[-+]?\d+(?:\.0+)?", s):
        s = str(int(float(s)))
    if width and s:
        s = s.zfill(width)
    return s


def numeric(series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def numeric_col(df: pd.DataFrame, col: str, default=np.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def safe_divide(numerator, denominator):
    n = pd.to_numeric(numerator, errors="coerce")
    d = pd.to_numeric(denominator, errors="coerce")
    return n.div(d.where(d != 0))


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    m = v.notna() & w.notna() & (w > 0)
    if not m.any():
        return np.nan
    return float(np.average(v[m], weights=w[m]))


def weighted_ratio(numerator: pd.Series, denominator: pd.Series, weights: pd.Series) -> float:
    n = pd.to_numeric(numerator, errors="coerce")
    d = pd.to_numeric(denominator, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    m = n.notna() & d.notna() & w.notna() & (w > 0)
    if not m.any():
        return np.nan
    den = float((d[m] * w[m]).sum())
    if den == 0:
        return np.nan
    return float((n[m] * w[m]).sum() / den)


def land_size_class(value) -> str:
    if pd.isna(value):
        return "Unknown"
    x = float(value)
    if x < 0.01:
        return "<0.01 ha"
    if x < 0.4:
        return "0.01 - 0.4 ha"
    if x < 1:
        return "0.4 - 1 ha"
    if x < 2:
        return "1-2 ha"
    if x < 4:
        return "2-4 ha"
    # Client-approved SAS template has six bands only and top-codes every
    # value >=4 ha into the final "4-10 ha" display band.
    return "4-10 ha"


def first_non_null(s: pd.Series):
    x = s.dropna()
    return x.iloc[0] if not x.empty else np.nan


def map_columns_case_insensitive(df: pd.DataFrame, wanted: Iterable[str]) -> dict[str, str]:
    lower = {str(c).strip().lower(): c for c in df.columns}
    out = {}
    for w in wanted:
        if w in df.columns:
            out[w] = w
        elif w.lower() in lower:
            out[w] = lower[w.lower()]
    return out


def ensure_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for c in columns:
        if c not in out.columns:
            out[c] = np.nan
    return out


def state_district_id(state, district) -> str:
    s = norm_text(state, 2)
    d = norm_text(district, 2)
    if not s or not d:
        return ""
    return s + d


def file_sha256(path: Path | str, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class ZipSurveyReader:
    """Read CSV/XLSX members from a source ZIP with a persistent extraction cache."""

    def __init__(self, archive: Path | str, cache_dir: Path | str):
        self.archive = Path(archive)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.zf = zipfile.ZipFile(self.archive)

    def close(self):
        self.zf.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def members(self) -> list[str]:
        return [n for n in self.zf.namelist() if not n.endswith("/")]

    def find(self, *tokens: str, extension: str | None = None, exclude: Iterable[str] = ()) -> str:
        tokens_l = [t.lower() for t in tokens if t]
        exclude_l = [t.lower() for t in exclude if t]
        hits = []
        for n in self.members:
            low = n.lower()
            if extension and not low.endswith(extension.lower()):
                continue
            if all(t in low for t in tokens_l) and not any(e in low for e in exclude_l):
                hits.append(n)
        if not hits:
            raise FileNotFoundError(f"{self.archive.name}: no member matching tokens={tokens}")
        # Prefer data files, then the shortest exact-looking name.
        hits.sort(key=lambda x: (0 if x.lower().endswith(('.csv', '.xlsx')) else 1, len(x), x.lower()))
        return hits[0]

    def _extract(self, member: str) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(member).name)
        key = hashlib.sha1((self.archive.name + "|" + member).encode("utf-8")).hexdigest()[:12]
        target = self.cache_dir / f"{key}_{safe_name}"
        if not target.exists() or target.stat().st_size == 0:
            with self.zf.open(member) as src, open(target, "wb") as dst:
                while True:
                    b = src.read(8 * 1024 * 1024)
                    if not b:
                        break
                    dst.write(b)
        return target

    def read_member(
        self,
        member: str,
        wanted_columns: Iterable[str] | None = None,
        nrows: int | None = None,
        dtype=None,
    ) -> pd.DataFrame:
        wanted = set(wanted_columns or [])
        low = member.lower()
        if low.endswith(".csv"):
            with self.zf.open(member) as f:
                usecols = (lambda c: c in wanted) if wanted else None
                return pd.read_csv(f, usecols=usecols, nrows=nrows, dtype=dtype, low_memory=False)
        if low.endswith(".xlsx"):
            path = self._extract(member)
            # First use the lightweight streaming XML reader. It is materially
            # faster on the large NSO workbooks and has no optional dependency.
            try:
                return read_xlsx_selected(path, wanted_columns=wanted if wanted else None, nrows=nrows)
            except Exception as fast_exc:
                # Compatibility fallback for unusual XLSX files. Calamine is
                # preferred when installed; otherwise use openpyxl.
                usecols = (lambda c: c in wanted) if wanted else None
                try:
                    import python_calamine  # noqa: F401
                    return pd.read_excel(path, engine="calamine", usecols=usecols, nrows=nrows, dtype=dtype)
                except Exception:
                    try:
                        return pd.read_excel(path, engine="openpyxl", usecols=usecols, nrows=nrows, dtype=dtype)
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            f"Failed reading {member} with fast XLSX and pandas fallback; "
                            f"fast={fast_exc!r}; fallback={fallback_exc!r}"
                        ) from fallback_exc
        raise ValueError(f"Unsupported archive member: {member}")

    def read(
        self,
        *tokens: str,
        wanted_columns: Iterable[str] | None = None,
        nrows: int | None = None,
        extension: str | None = None,
        exclude: Iterable[str] = (),
        dtype=None,
    ) -> pd.DataFrame:
        member = self.find(*tokens, extension=extension, exclude=exclude)
        print(f"  reading: {Path(member).name}", flush=True)
        return self.read_member(member, wanted_columns=wanted_columns, nrows=nrows, dtype=dtype)


def aggregate_sum(df: pd.DataFrame, key: str, cols: Iterable[str]) -> pd.DataFrame:
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return pd.DataFrame({key: df[key].drop_duplicates()}) if key in df else pd.DataFrame(columns=[key])
    work = df[[key] + cols].copy()
    for c in cols:
        work[c] = pd.to_numeric(work[c], errors="coerce")
    # min_count=1 preserves all-missing as NaN instead of silently creating zero.
    return work.groupby(key, as_index=False)[cols].sum(min_count=1)



def aggregate_total_or_details(
    df: pd.DataFrame,
    key: str,
    serial_col: str,
    value_map: dict[str, str],
    total_values: Iterable[float | int | str],
) -> pd.DataFrame:
    """Aggregate a repeated survey block without double-counting official total rows.

    For each household/visit key, official total row(s) are preferred when present.
    If a group has no total row, detail rows are summed as a controlled fallback.
    The returned frame contains one row for every key present in the child table, even
    when all selected measures are missing; this lets merge_activity distinguish a true
    structural zero (no child records) from an observed-but-missing value.
    """
    if key not in df.columns:
        return pd.DataFrame(columns=[key] + list(value_map.values()))
    work_cols = [key, serial_col] + [c for c in value_map if c in df.columns]
    work = df[work_cols].copy()
    serial = pd.to_numeric(work[serial_col], errors="coerce")
    total_numeric = {float(v) for v in total_values}
    work["__is_total"] = serial.isin(total_numeric)
    for src in value_map:
        if src not in work.columns:
            work[src] = np.nan
        work[src] = pd.to_numeric(work[src], errors="coerce")

    total_keys = set(work.loc[work["__is_total"], key].dropna().astype(str))
    key_as_str = work[key].astype(str)
    selected = work[work["__is_total"] | ~key_as_str.isin(total_keys)].copy()
    grouped = selected.groupby(key, as_index=False)[list(value_map.keys())].sum(min_count=1)
    grouped = grouped.rename(columns=value_map)

    # Preserve child-presence keys even if unusual source rows were fully blank.
    all_keys = work[[key]].drop_duplicates()
    grouped = all_keys.merge(grouped, on=key, how="left", validate="one_to_one")
    return grouped


def merge_activity(
    base: pd.DataFrame,
    child: pd.DataFrame,
    key: str,
    value_cols: Iterable[str],
    label: str,
    zero_if_absent: bool = True,
) -> pd.DataFrame:
    """Merge a one-row-per-key activity aggregate with structural-zero semantics.

    If a household has no child record at all, optional activity amounts are zero.
    If a household has child rows but the requested source amount is missing, NaN is
    retained for QA instead of being silently changed to zero.
    """
    value_cols = list(value_cols)
    out = base.copy()
    if child.empty:
        for c in value_cols:
            if c not in out.columns:
                out[c] = 0.0 if zero_if_absent else np.nan
        return out
    if child[key].duplicated().any():
        dup = int(child[key].duplicated().sum())
        raise ValueError(f"{label}: expected one row per {key}, found {dup} duplicates")
    c = child.copy()
    marker = f"__present_{re.sub(r'[^A-Za-z0-9]+', '_', label)}"
    c[marker] = 1
    out = out.merge(c, how="left", on=key, validate="one_to_one")
    if zero_if_absent:
        absent = out[marker].isna()
        for col in value_cols:
            if col not in out.columns:
                out[col] = np.nan
            out.loc[absent, col] = 0.0
    return out.drop(columns=[marker])

def merge_one_to_one(base: pd.DataFrame, child: pd.DataFrame, key: str, label: str) -> pd.DataFrame:
    if child.empty:
        return base
    if child[key].duplicated().any():
        dup = int(child[key].duplicated().sum())
        raise ValueError(f"{label}: expected one row per {key}, found {dup} duplicates")
    return base.merge(child, how="left", on=key, validate="one_to_one")
