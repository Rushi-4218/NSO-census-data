from __future__ import annotations

from pathlib import Path
import pandas as pd

from .common import norm_text
from .geography import district_display_label


class MasterDictionary:
    """Runtime control metadata loaded from SAS_Master_Complete_Data_Dictionary.xlsx.

    Version 2 makes the State_District worksheet the sole runtime geography authority.
    No external state_map.csv or district_map.csv is used by the production pipeline.
    """

    REQUIRED_SHEETS = {
        "Survey_Summary",
        "Input_Manifest",
        "File_Catalog",
        "Variable_Dictionary",
        "Client_Output_Schema",
        "Client_KPI_Mapping",
        "Required_Dimensions",
        "Key_Weight_Rules",
        "Source_Gaps",
        "State_District",
    }

    def __init__(self, path: Path | str, client_schema_path: Path | str | None = None):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.client_schema_path = Path(client_schema_path) if client_schema_path else None
        if self.client_schema_path and not self.client_schema_path.exists():
            raise FileNotFoundError(self.client_schema_path)
        self._xls = pd.ExcelFile(self.path, engine="openpyxl")
        missing = self.REQUIRED_SHEETS.difference(self._xls.sheet_names)
        if missing:
            raise ValueError(f"Master dictionary is missing required sheets: {sorted(missing)}")
        self._cache: dict[str, pd.DataFrame] = {}
        self._validate_geography_sheet()

    def sheet(self, name: str) -> pd.DataFrame:
        if name not in self._cache:
            self._cache[name] = pd.read_excel(self._xls, sheet_name=name, dtype=object)
        return self._cache[name].copy()

    @property
    def source_client_columns(self) -> list[str]:
        d = self.sheet("Client_Output_Schema")
        d["Position"] = pd.to_numeric(d["Position"], errors="coerce")
        d = d.sort_values("Position")
        return d["Column_Name"].astype(str).tolist()

    @property
    def client_columns(self) -> list[str]:
        """Final output schema, optionally using a versioned client correction.

        The supplied master dictionary preserves the retired ``houseHold_ID``
        field.  Aggregate-only SAS delivery replaces that field with
        ``HH_Type`` without changing the 24-column position or any other
        dictionary-controlled attribute.  The checked-in CSV is therefore a
        narrow, auditable schema correction rather than a second dictionary.
        """
        if self.client_schema_path is None:
            return self.source_client_columns

        d = pd.read_csv(self.client_schema_path, dtype=str)
        required = {"Position", "Column_Name"}
        if not required.issubset(d.columns):
            raise ValueError(
                f"Client schema override must contain {sorted(required)}: {self.client_schema_path}"
            )
        d["Position"] = pd.to_numeric(d["Position"], errors="coerce")
        if d["Position"].isna().any() or d["Position"].duplicated().any():
            raise ValueError(f"Client schema override has invalid positions: {self.client_schema_path}")
        d = d.sort_values("Position")
        columns = d["Column_Name"].fillna("").astype(str).tolist()
        if any(not c.strip() for c in columns):
            raise ValueError(f"Client schema override has blank column names: {self.client_schema_path}")
        return columns

    @property
    def kpis(self) -> pd.DataFrame:
        return self.sheet("Client_KPI_Mapping")

    @property
    def survey_summary(self) -> pd.DataFrame:
        return self.sheet("Survey_Summary")

    @property
    def source_gaps(self) -> pd.DataFrame:
        return self.sheet("Source_Gaps")

    @property
    def geography(self) -> pd.DataFrame:
        d = self.sheet("State_District")
        d = d[["CODE_LIST_ID", "CODE", "LABEL"]].copy()
        d["CODE_LIST_ID"] = d["CODE_LIST_ID"].astype(str).str.strip().str.upper()
        d["CODE"] = d.apply(
            lambda r: norm_text(r["CODE"], 2 if r["CODE_LIST_ID"] == "STATE" else 4), axis=1
        )
        d["LABEL"] = d["LABEL"].fillna("").astype(str).str.strip()
        return d

    def _validate_geography_sheet(self) -> None:
        d = pd.read_excel(self._xls, sheet_name="State_District", dtype=str).fillna("")
        expected = ["CODE_LIST_ID", "CODE", "LABEL"]
        if list(d.columns[:3]) != expected or not set(expected).issubset(d.columns):
            raise ValueError(
                "State_District sheet must contain columns exactly beginning with "
                "CODE_LIST_ID, CODE, LABEL"
            )
        d = d[expected].copy()
        d["CODE_LIST_ID"] = d["CODE_LIST_ID"].str.strip().str.upper()
        bad_types = sorted(set(d["CODE_LIST_ID"]) - {"STATE", "DISTRICT"})
        if bad_types:
            raise ValueError(f"State_District contains unsupported CODE_LIST_ID values: {bad_types}")
        d["CODE"] = d.apply(
            lambda r: norm_text(r["CODE"], 2 if r["CODE_LIST_ID"] == "STATE" else 4), axis=1
        )
        if d[["CODE_LIST_ID", "CODE"]].duplicated().any():
            dup = d[d[["CODE_LIST_ID", "CODE"]].duplicated(keep=False)]
            raise ValueError("Duplicate geography codes in State_District:\n" + dup.to_string(index=False))
        states = d[d["CODE_LIST_ID"].eq("STATE")]
        districts = d[d["CODE_LIST_ID"].eq("DISTRICT")]
        if states.empty or districts.empty:
            raise ValueError("State_District must contain both STATE and DISTRICT rows")
        state_codes = set(states["CODE"])
        orphan = sorted({c[:2] for c in districts["CODE"] if len(c) == 4} - state_codes)
        if orphan:
            raise ValueError(f"District codes have state prefixes not present in STATE rows: {orphan}")

    def geography_lookups(self) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """Return State_Name, District_Name, and full district-label lookups."""
        d = self.geography
        states = d[d["CODE_LIST_ID"].eq("STATE")]
        districts = d[d["CODE_LIST_ID"].eq("DISTRICT")]
        state_map = {r.CODE: r.LABEL for r in states.itertuples(index=False)}
        district_full = {r.CODE: r.LABEL for r in districts.itertuples(index=False)}
        district_map = {code: district_display_label(label) for code, label in district_full.items()}
        return state_map, district_map, district_full

    def source_url(self, year: int) -> str:
        s = self.survey_summary
        hit = s[pd.to_numeric(s["Survey_Year"], errors="coerce").eq(year)]
        if hit.empty:
            return ""
        value = hit.iloc[0].get("Catalog_URL")
        return "" if pd.isna(value) else str(value)
