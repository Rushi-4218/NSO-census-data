from __future__ import annotations

"""Small streaming XLSX reader optimized for NSO survey workbooks.

It reads only selected columns from the first worksheet and avoids loading the
entire workbook through openpyxl.  The implementation intentionally supports
only ordinary scalar cells, which is sufficient for the raw survey tables.
If a workbook uses an unsupported construct the caller can fall back to
pandas/openpyxl.
"""

from pathlib import Path, PurePosixPath
import re
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd

_CELL_RE = re.compile(r"([A-Z]+)(\d+)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _col_index(cell_ref: str) -> int:
    m = _CELL_RE.match(cell_ref or "")
    if not m:
        return -1
    letters = m.group(1)
    out = 0
    for ch in letters:
        out = out * 26 + (ord(ch) - 64)
    return out - 1


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    name = "xl/sharedStrings.xml"
    if name not in zf.namelist():
        return []
    values: list[str] = []
    with zf.open(name) as f:
        for event, elem in ET.iterparse(f, events=("end",)):
            if _local(elem.tag) == "si":
                texts = []
                for child in elem.iter():
                    if _local(child.tag) == "t" and child.text is not None:
                        texts.append(child.text)
                values.append("".join(texts))
                elem.clear()
    return values


def _first_sheet_path(zf: zipfile.ZipFile) -> str:
    # Find the relationship id of the first worksheet.
    with zf.open("xl/workbook.xml") as f:
        root = ET.parse(f).getroot()
    rid = None
    for elem in root.iter():
        if _local(elem.tag) == "sheet":
            rid = elem.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if rid:
                break
    if not rid:
        raise ValueError("XLSX has no worksheet relationship")

    with zf.open("xl/_rels/workbook.xml.rels") as f:
        rel_root = ET.parse(f).getroot()
    target = None
    for elem in rel_root.iter():
        if _local(elem.tag) == "Relationship" and elem.attrib.get("Id") == rid:
            target = elem.attrib.get("Target")
            break
    if not target:
        raise ValueError("Unable to resolve first worksheet")
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    # workbook rel targets are relative to xl/
    return str(PurePosixPath("xl") / target)


def _cell_value(cell: ET.Element, shared: list[str]):
    t = cell.attrib.get("t", "")
    if t == "inlineStr":
        texts = [e.text or "" for e in cell.iter() if _local(e.tag) == "t"]
        return "".join(texts)
    v = None
    for child in cell:
        if _local(child.tag) == "v":
            v = child.text
            break
    if v is None:
        return None
    if t == "s":
        try:
            return shared[int(v)]
        except Exception:
            return v
    if t == "b":
        return 1 if v == "1" else 0
    if t in {"str", "e"}:
        return v
    # Return raw numeric text. Downstream code explicitly converts measures and
    # normalizes identifiers, so this avoids unnecessary float conversion here.
    return v


def read_xlsx_selected(path: Path | str, wanted_columns=None, nrows: int | None = None) -> pd.DataFrame:
    path = Path(path)
    wanted = None if wanted_columns is None else {str(x) for x in wanted_columns}
    with zipfile.ZipFile(path) as zf:
        shared = _shared_strings(zf)
        sheet_path = _first_sheet_path(zf)
        if sheet_path not in zf.namelist():
            # Some generators include ../ paths. Normalize conservatively.
            sheet_path = str(PurePosixPath(sheet_path))
        rows_out: list[dict[str, object]] = []
        header_by_idx: dict[int, str] | None = None
        selected_by_idx: dict[int, str] = {}

        with zf.open(sheet_path) as sheet:
            for event, elem in ET.iterparse(sheet, events=("end",)):
                if _local(elem.tag) != "row":
                    continue
                row_vals: dict[int, object] = {}
                for cell in elem:
                    if _local(cell.tag) != "c":
                        continue
                    idx = _col_index(cell.attrib.get("r", ""))
                    if idx >= 0:
                        row_vals[idx] = _cell_value(cell, shared)

                if header_by_idx is None:
                    candidate = {i: str(v).strip() for i, v in row_vals.items() if v is not None and str(v).strip()}
                    if not candidate:
                        elem.clear()
                        continue
                    # Raw NSO files use a normal header row. When wanted columns
                    # are supplied, skip any title row that does not contain one.
                    if wanted is not None and not (set(candidate.values()) & wanted):
                        elem.clear()
                        continue
                    header_by_idx = candidate
                    selected_by_idx = {
                        i: name for i, name in candidate.items()
                        if wanted is None or name in wanted
                    }
                    elem.clear()
                    continue

                rec = {name: row_vals.get(i) for i, name in selected_by_idx.items()}
                rows_out.append(rec)
                elem.clear()
                if nrows is not None and len(rows_out) >= nrows:
                    break

    columns = list(selected_by_idx.values())
    return pd.DataFrame(rows_out, columns=columns)
