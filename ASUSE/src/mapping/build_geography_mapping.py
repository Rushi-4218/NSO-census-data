from __future__ import annotations

from pathlib import Path
import pandas as pd
from openpyxl import load_workbook
import re


def load_state_codes(layout_file: Path) -> pd.DataFrame:
    raw = pd.read_excel(layout_file, sheet_name="State Code", header=None, dtype=str)
    raw = raw.iloc[2:, :2].copy()
    raw.columns = ["State_Name", "Raw_State_Code"]
    raw = raw.dropna().reset_index(drop=True)
    raw["Raw_State_Code"] = raw["Raw_State_Code"].str.zfill(2)
    raw["State_ID"] = raw["Raw_State_Code"].astype(int)
    return raw[["State_ID", "State_Name", "Raw_State_Code"]]


def _census_district_rows(census_file: Path) -> pd.DataFrame:
    wb = load_workbook(census_file, read_only=True, data_only=True)
    rows = []
    try:
        it = wb.active.iter_rows(values_only=True)
        next(it)
        def is_zero(value) -> bool:
            if value is None:
                return True
            text = str(value).strip()
            return text == "" or set(text) <= {"0", "."}

        for state, district, subdistrict, town, name, *_ in it:
            if state and district and int(district) > 0 and is_zero(subdistrict) and is_zero(town) and name:
                rows.append((int(state), int(district), str(name).strip().title()))
    finally:
        wb.close()
    return pd.DataFrame(rows, columns=["Census_State", "Census_District", "District_Name"]).drop_duplicates()


def _asuse_district_rows(volume_i_file: Path, page_range: range | None = None) -> pd.DataFrame:
    import pdfplumber

    rows = []
    state = None
    with pdfplumber.open(volume_i_file) as pdf:
        # Appendix II page locations are validated separately for each round.
        pages = pdf.pages[page_range.start:page_range.stop] if page_range else pdf.pages[158:175]
        for page in pages:
            tables = page.extract_tables()
            if not tables:
                continue
            for row in tables[0]:
                if len(row) < 7:
                    continue
                region = (row[2] or "").strip()
                if re.fullmatch(r"\d{3}", region):
                    state = int(region[:2])
                state_cell = (row[1] or "").strip()
                state_match = re.fullmatch(r"\((\d{2})\)", state_cell)
                if state_match:
                    state = int(state_match.group(1))
                name = (row[5] or "").replace("\n", " ").strip()
                code_match = re.fullmatch(r"\((\d{2})\)", (row[6] or "").strip())
                if state is not None and name and code_match:
                    rows.append((state, int(code_match.group(1)), name))
        # The 2022-23 and 2023-24 appendices have no machine-detectable table
        # grid. Their layout-preserving text still exposes the state/NSS-region
        # header and district code at stable horizontal positions.
        if not rows:
            state = None
            awaiting_state_code = False
            pending: list[tuple[int, str]] = []
            parsed_rows: list[tuple[int, int, str]] = []
            district_pattern = re.compile(r"\b\d+\.\s+([^0-9]+?)\s+\((\d{2})\s*\)")
            for page in pages:
                text = page.extract_text(x_tolerance=1, y_tolerance=3, layout=True) or ""
                for line in text.splitlines():
                    # State codes occupy the far-left state column. Capture
                    # them even when a long state name wrapped onto a separate
                    # line and the header detector below cannot see that name.
                    left_state_code = re.match(r"^\s{0,30}\((\d{2})\)", line)
                    if left_state_code:
                        state = int(left_state_code.group(1))
                        awaiting_state_code = False
                        parsed_rows.extend((state, code, name) for code, name in pending)
                        pending = []
                    # A state header has a serial number, a non-empty name, and
                    # then the three-digit NSS-region code. Continuation region
                    # headers have no name between the serial and region code.
                    header = re.match(r"^\s*\d+\.\s+(.*?)\s+(\d{3})\s+", line)
                    if header and header.group(1).strip():
                        prefix = header.group(1).strip()
                        inline_code = re.search(r"\((\d{2})\)", prefix)
                        awaiting_state_code = inline_code is None
                        pending = []
                        if inline_code:
                            state = int(inline_code.group(1))
                    if awaiting_state_code:
                        state_code = re.match(r"^\s*\((\d{2})\)", line)
                        if state_code:
                            state = int(state_code.group(1))
                            awaiting_state_code = False
                            parsed_rows.extend((state, code, name) for code, name in pending)
                            pending = []
                    districts = [(int(code), name.strip()) for name, code in district_pattern.findall(line)]
                    if awaiting_state_code:
                        pending.extend(districts)
                    elif state is not None:
                        parsed_rows.extend((state, code, name) for code, name in districts)
            rows.extend(parsed_rows)
    frame = pd.DataFrame(rows, columns=["State_ID", "Raw_District", "District_Name"])
    conflicts = frame.groupby(["State_ID", "Raw_District"]).District_Name.nunique()
    if (conflicts > 1).any():
        raise RuntimeError(f"Conflicting official ASUSE district labels: {conflicts[conflicts > 1].index.tolist()}")
    return frame.drop_duplicates(["State_ID", "Raw_District"])


def build_district_master(
    census_file: Path,
    volume_i_file: Path,
    observed: pd.DataFrame,
    cache: Path,
    page_range: range | None = None,
    survey_label: str = "2025",
) -> pd.DataFrame:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and cache.stat().st_size > 100:
        census = pd.read_csv(cache)
    else:
        census = _census_district_rows(census_file)
        census.to_csv(cache, index=False)

    # Census District Code is nationally sequential. ASUSE uses the two-digit
    # ordinal within each State/UT (the same convention visible in the approved
    # Maharashtra template: national 497 becomes raw 01 / client 2701).
    census["Census_State"] = pd.to_numeric(census["Census_State"], errors="coerce")
    census["Census_District"] = pd.to_numeric(census["Census_District"], errors="coerce")
    census = census.dropna(subset=["Census_State", "Census_District"])
    census = census[census.Census_District > 0].sort_values(["Census_State", "Census_District"])
    census["Census_District"] = census.groupby("Census_State").cumcount() + 1

    official = _asuse_district_rows(volume_i_file, page_range)

    # Reorganisation fallbacks retain official Census legacy names where needed.
    ap_names = ["Srikakulam", "Vizianagaram", "Visakhapatnam", "East Godavari", "West Godavari", "Krishna", "Guntur", "Prakasam", "Sri Potti Sriramulu Nellore", "Ysr", "Kurnool", "Anantapur", "Chittoor"]
    tg_names = ["Adilabad", "Nizamabad", "Karimnagar", "Medak", "Hyderabad", "Rangareddy", "Mahbubnagar", "Nalgonda", "Warangal", "Khammam"]
    overrides = {(28, i + 1): n for i, n in enumerate(ap_names)}
    overrides.update({(36, i + 1): n for i, n in enumerate(tg_names)})
    overrides.update({(37, 1): "Kargil", (37, 2): "Leh (Ladakh)"})
    overrides.update({(25, 1): "Daman", (25, 2): "Diu", (25, 3): "Dadra & Nagar Haveli"})
    overrides.update({(31, 20): "Lakshadweep"})

    name_map = {(int(r.Census_State), int(r.Census_District)): r.District_Name for r in census.itertuples()}
    name_map.update(overrides)
    name_map.update({(int(r.State_ID), int(r.Raw_District)): r.District_Name for r in official.itertuples()})
    states = observed[["State_ID", "State_Name"]].drop_duplicates().set_index("State_ID")["State_Name"].to_dict()
    rows = []
    for r in observed.sort_values(["State_ID", "Raw_District_Code"]).itertuples():
        code = int(r.Raw_District_Code)
        name = name_map.get((int(r.State_ID), code))
        district_id = int(r.State_ID) * 100 + code
        if int(r.State_ID) == 31 and code == 20:
            district_id = 3101
        rows.append({
            "State_ID": int(r.State_ID), "State_Name": states[int(r.State_ID)],
            "District_ID": district_id,
            "District_Name": name or f"UNRESOLVED-{int(r.State_ID):02d}-{code:02d}",
            "Raw_District_Code": f"{code:02d}", "Raw_NSS_Region": r.Raw_NSS_Region,
            "Mapping_Source": f"ASUSE {survey_label} Volume I Appendix II / Census 2011 fallback" + ("; single-district raw-code normalization" if int(r.State_ID) == 31 and code == 20 else ""),
            "Mapping_Status": "Resolved" if name else "Unresolved",
        })
    return pd.DataFrame(rows).drop_duplicates(["State_ID", "Raw_District_Code"])
