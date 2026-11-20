from __future__ import annotations

import re
import pandas as pd

from .common import norm_text, state_district_id


def state_display_label(full_label: str) -> str:
    s = "" if full_label is None else str(full_label).strip()
    if not s:
        return ""
    return re.sub(r"\s*\(2011 boundaries\)\s*$", "", s, flags=re.IGNORECASE).strip()


def district_display_label(full_label: str) -> str:
    """Remove only the final parenthetical state suffix from a district lookup label.

    Examples:
      Pune (Maharashtra) -> Pune
      Kaimur (Bhabua) (Bihar) -> Kaimur (Bhabua)
      Leh (Ladakh) (Jammu & Kashmir) -> Leh (Ladakh)
    """
    s = "" if full_label is None else str(full_label).strip()
    if not s:
        return ""
    return re.sub(r"\s*\([^()]*\)\s*$", "", s).strip()


def add_geography(
    base: pd.DataFrame,
    state_map: dict[str, str],
    district_map: dict[str, str],
    district_full_map: dict[str, str] | None = None,
    state_col: str = "State",
    district_col: str = "District",
    state_district_col: str = "State_District",
) -> pd.DataFrame:
    """Attach client geography columns from the master dictionary only.

    Raw codes are preserved as normalized text. If a district key is not present in the
    dictionary, its code remains in District_ID but the name is intentionally blank so QA
    can expose the mismatch rather than fabricate a historical district label.
    """
    out = base.copy()
    if state_col in out.columns:
        out["State_ID"] = out[state_col].map(lambda x: norm_text(x, 2))
    else:
        out["State_ID"] = ""
    out["State_Lookup_Label"] = out["State_ID"].map(state_map).fillna("")
    out["State_Name"] = out["State_Lookup_Label"].map(state_display_label).astype(str)

    if state_district_col in out.columns:
        sd = out[state_district_col].map(lambda x: norm_text(x, 4))
        # Some source files contain blank/invalid State_District despite valid component codes.
        if district_col in out.columns:
            fallback = pd.Series(
                [state_district_id(s, d) for s, d in zip(out["State_ID"], out[district_col])],
                index=out.index,
                dtype=object,
            )
            valid = sd.str.fullmatch(r"\d{4}", na=False)
            out["District_ID"] = sd.where(valid, fallback)
        else:
            out["District_ID"] = sd
    elif district_col in out.columns:
        out["District_ID"] = [state_district_id(s, d) for s, d in zip(out["State_ID"], out[district_col])]
    else:
        out["District_ID"] = ""

    out["District_ID"] = out["District_ID"].map(lambda x: norm_text(x, 4) if norm_text(x) else "")
    out["District_Name"] = out["District_ID"].map(district_map).fillna("")
    if district_full_map is not None:
        out["District_Lookup_Label"] = out["District_ID"].map(district_full_map).fillna("")
    else:
        out["District_Lookup_Label"] = ""
    out["geography_match_status"] = "MATCHED"
    out.loc[out["State_ID"].ne("") & out["State_Name"].eq(""), "geography_match_status"] = "UNMAPPED_STATE"
    out.loc[out["District_ID"].ne("") & out["District_Name"].eq(""), "geography_match_status"] = "UNMAPPED_DISTRICT"
    return out
