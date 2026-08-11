from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import polars as pl


TARGET_LEVELS = {"l02", "l03", "l08", "l09", "l10", "l11", "l12"}
COMMON = {
    "fsu": ("fsu", "fsu_serial_no"),
    "schedule": ("sch", "schedule"),
    "sector": ("sector",),
    "nss_region": ("nss_region",),
    "district": ("district",),
    "stratum": ("Stratum", "stratum"),
    "sub_stratum": ("sub_stratum", "substratum"),
    "sub_round": ("subround", "sub_round"),
    "sub_region": ("fodsubregion", "fod_sub_region"),
    "segment": ("b1q3", "segment_no"),
    "sss_no": ("b1q4", "second_stage_stratum", "second_stage_stratum_no"),
    "est_no": ("b1q5", "sample_est_no", "sample_estab_no"),
    "level": ("level",),
    "Multiplier": ("MLT", "mlt"),
}

ROUND_FIELDS = {
    "2022-2023": {
        "l02": {"Major_NIC_2dig": ("b2202_a",), "Major_NIC_5dig": ("b2202_b",), "Ownership_Type": ("b2204",), "Registered": ("b2227",)},
        "l03": {"Ref_Period_Type": ("b2pt2265",), "Months_In_Accounting_Period": ("b2pt2267",)},
        "l08": {"Item_No": ("b7q2",), "GVA_Value": ("b7q3",)},
        "l09": {"Item_No": ("b8q2",), "Total_Workers": ("b8q9",)},
        "l10": {"Item_No": ("b9q2",), "Emolument_Value": ("b9q3",)},
        "l11": {"Item_No": ("b10q2",), "Fixed_Asset_Value": ("b10q3",)},
        "l12": {"Item_No": ("b11q2",), "Loan_Value": ("b11q3",)},
    },
    "2023-2024": {
        "l02": {"Major_NIC_2dig": ("major_nic_2dig",), "Major_NIC_5dig": ("major_nic_5dig",), "Ownership_Type": ("ownership_type",), "Registered": ("registered",)},
        "l03": {"Ref_Period_Type": ("ref_period_type",), "Months_In_Accounting_Period": ("months_in_accounting_period",)},
        "l08": {"Item_No": ("item_no",), "GVA_Value": ("value_rs",)},
        "l09": {"Item_No": ("item_no",), "Total_Workers": ("total_workers",)},
        "l10": {"Item_No": ("item_no",), "Emolument_Value": ("value_rs",)},
        "l11": {"Item_No": ("item_no",), "Fixed_Asset_Value": ("mv_assets_owned",)},
        "l12": {"Item_No": ("item_no",), "Loan_Value": ("amount_outstanding",)},
    },
}

SELECTORS = {
    "l08": {"769", "779"},
    "l09": {"782", "783", "789"},
    "l10": {"939"},
    "l11": {"1019"},
    "l12": {"1119"},
}


def level_from_name(path: Path) -> str | None:
    match = re.search(r"LEVEL\s*-\s*(\d{2})\b", path.name, re.IGNORECASE)
    return f"l{match.group(1)}" if match else None


def discover_level_files(raw_root: Path) -> tuple[list[Path], dict[str, Path]]:
    files = sorted(p for p in raw_root.rglob("*") if p.is_file() and p.suffix.lower() in {".csv", ".xlsx"})
    by_level: dict[str, list[Path]] = {}
    for path in files:
        level = level_from_name(path)
        if level:
            by_level.setdefault(level, []).append(path)
    selected = {}
    for level, choices in by_level.items():
        # Prefer CSV when the delivery contains duplicate CSV/XLSX renderings.
        selected[level] = sorted(choices, key=lambda p: (p.suffix.lower() != ".csv", p.name))[0]
    return files, selected


def _xlsx_headers(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as book:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in book.namelist():
            for _, element in ET.iterparse(book.open("xl/sharedStrings.xml"), events=("end",)):
                if element.tag.endswith("}si"):
                    shared.append("".join(t.text or "" for t in element.iter() if t.tag.endswith("}t")))
                    element.clear()
        for _, row in ET.iterparse(book.open("xl/worksheets/sheet1.xml"), events=("end",)):
            if not row.tag.endswith("}row"):
                continue
            result = []
            for cell in row:
                if not cell.tag.endswith("}c"):
                    continue
                kind = cell.attrib.get("t")
                value = next((x.text for x in cell.iter() if x.tag.endswith("}v")), None)
                inline = "".join(x.text or "" for x in cell.iter() if x.tag.endswith("}t"))
                result.append(shared[int(value)] if kind == "s" and value is not None else (inline or value or ""))
            return result
    return []


def headers(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle))
    return _xlsx_headers(path)


def row_count(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        lines = 0
        with path.open("rb") as handle:
            while block := handle.read(8 * 1024 * 1024):
                lines += block.count(b"\n")
        return max(lines - 1, 0)
    with zipfile.ZipFile(path) as book:
        with book.open("xl/worksheets/sheet1.xml") as sheet:
            head = sheet.read(8192).decode("utf-8", "ignore")
        match = re.search(r'<dimension ref="[A-Z]+\d+:?[A-Z]*?(\d+)"', head)
        if match:
            return max(int(match.group(1)) - 1, 0)
    return -1


def _resolve(header: list[str], candidates: tuple[str, ...], canonical: str) -> str:
    lookup = {name.lower(): name for name in header}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise RuntimeError(f"Required raw field {canonical!r} not found; candidates={candidates}; header={header}")


def _read_columns(path: Path, raw_columns: list[str]) -> pd.DataFrame:
    schema = {name: pl.String for name in raw_columns}
    if path.suffix.lower() == ".csv":
        frame = pl.read_csv(
            path,
            columns=raw_columns,
            schema_overrides=schema,
            infer_schema_length=0,
            null_values=[],
            ignore_errors=False,
        )
    else:
        frame = pl.read_excel(
            path,
            engine="calamine",
            columns=raw_columns,
            schema_overrides=schema,
            infer_schema_length=0,
        )
    return frame.to_pandas().fillna("")


def _normalize_code(series: pd.Series, width: int) -> pd.Series:
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(width)


def _enterprise_key(frame: pd.DataFrame) -> pd.Series:
    widths = {
        "fsu": 5, "schedule": 3, "sector": 1, "nss_region": 3,
        "district": 2, "stratum": 3, "sub_stratum": 2, "sub_round": 1,
        "sub_region": 4, "segment": 1, "sss_no": 2, "est_no": 2,
    }
    parts = []
    for column, width in widths.items():
        parts.append(_normalize_code(frame[column], width))
    key = parts[0]
    for part in parts[1:]:
        key = key + part
    return key


def load_round_levels(
    survey_round: str,
    selected_files: dict[str, Path],
    cache_dir: Path,
    multiplier_divisor: float,
    log,
) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    parsed: dict[str, pd.DataFrame] = {}
    profiles: list[dict] = []
    for level in sorted(TARGET_LEVELS):
        path = selected_files.get(level)
        if path is None:
            profiles.append({"Raw_Level": level.upper(), "Rows": 0, "Selected_Rows": 0, "Status": "MISSING"})
            continue
        cache = cache_dir / f"{level}.parquet"
        meta_path = cache_dir / f"{level}_meta.json"
        fingerprint = {
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime_ns,
            "round": survey_round,
            "multiplier_divisor": multiplier_divisor,
            "version": 3,
        }
        if cache.exists() and meta_path.exists() and json.loads(meta_path.read_text(encoding="utf-8")) == fingerprint:
            frame = pd.read_parquet(cache)
            parsed[level] = frame
            profiles.append({"Raw_Level": level.upper(), "Rows": row_count(path), "Selected_Rows": len(frame), "Status": "CACHED"})
            log.info("Loaded %s from cache (%s selected rows)", level, len(frame))
            continue

        header = headers(path)
        mapping: dict[str, str] = {}
        for canonical, candidates in COMMON.items():
            mapping[canonical] = _resolve(header, candidates, canonical)
        for canonical, candidates in ROUND_FIELDS[survey_round][level].items():
            mapping[canonical] = _resolve(header, candidates, canonical)
        raw_names = list(dict.fromkeys(mapping.values()))
        frame = _read_columns(path, raw_names).rename(columns={raw: canonical for canonical, raw in mapping.items()})
        frame["Enterprise_Key"] = _enterprise_key(frame)
        frame["Raw_State_Code"] = _normalize_code(frame["nss_region"].str[:2], 2)
        frame["sector"] = _normalize_code(frame["sector"], 1)
        frame["nss_region"] = _normalize_code(frame["nss_region"], 3)
        frame["district"] = _normalize_code(frame["district"], 2)
        frame["Multiplier"] = pd.to_numeric(frame["Multiplier"], errors="coerce") / multiplier_divisor
        if "Item_No" in frame:
            frame["Item_No"] = frame["Item_No"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            frame = frame[frame.Item_No.isin(SELECTORS.get(level, set()))].copy()
        frame.to_parquet(cache, index=False)
        meta_path.write_text(json.dumps(fingerprint), encoding="utf-8")
        parsed[level] = frame
        profiles.append({"Raw_Level": level.upper(), "Rows": row_count(path), "Selected_Rows": len(frame), "Status": "PARSED"})
        log.info("Parsed %s: %s selected rows", level, len(frame))
    return parsed, profiles
