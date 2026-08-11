from __future__ import annotations

import numpy as np
import pandas as pd

BAC_ORDER = ["Total", "Manufacturing", "Trade", "Other Services"]


def classify_bac(nic2: str, nic5: str) -> str | None:
    try:
        div = int(str(nic2))
    except ValueError:
        return None
    # Gold-template BAC convention: divisions 10-32, 45-47, remainder.
    if 10 <= div <= 32:
        return "Manufacturing"
    if 45 <= div <= 47:
        return "Trade"
    return "Other Services"


def ownership_group(code: str) -> str | None:
    if code in {"1", "2", "3"}: return "Proprietary"
    if code in {"4", "5"}: return "Partnership"
    if code == "6": return "SHG"
    if code in {"7", "8", "9"}: return "Others"
    return None


def _expanded_domains(base: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for geo in ("district", "state", "india"):
        x = base.copy()
        if geo == "state":
            x["District_ID"] = 0; x["District_Name"] = "All Districts"
        elif geo == "india":
            x["State_ID"] = 0; x["State_Name"] = "India"
            x["District_ID"] = 0; x["District_Name"] = "All Districts"
        parts.append(x)
    geo = pd.concat(parts, ignore_index=True)
    total = geo.copy(); total["Sector_code"] = 0; total["Sector"] = "total"
    return pd.concat([total, geo], ignore_index=True)


def calculate(base: pd.DataFrame) -> pd.DataFrame:
    d = _expanded_domains(base)
    keys = ["State_ID", "State_Name", "District_ID", "District_Name", "Sector_code", "Sector"]
    out = []
    for key, g in d.groupby(keys, sort=False, dropna=False):
        prefix = dict(zip(keys, key))
        w = g["Multiplier"]
        for bac in BAC_ORDER:
            b = g if bac == "Total" else g[g.BAC == bac]
            bw = b.Multiplier
            out.append({**prefix, "SUB_GROUP_ID": 1, "COL_DESC": bac, "DATA": bw.sum()})
        for owner in ["Proprietary", "Partnership", "SHG", "Others", "Total"]:
            val = w.sum() if owner == "Total" else g.loc[g.Ownership_Group == owner, "Multiplier"].sum()
            out.append({**prefix, "SUB_GROUP_ID": 2, "COL_DESC": owner, "DATA": val})
        for bac in BAC_ORDER:
            b = g if bac == "Total" else g[g.BAC == bac]
            out.append({**prefix, "SUB_GROUP_ID": 3, "COL_DESC": bac, "DATA": b.Worker_Contribution.sum(min_count=1)})
            hired = b.Hired_Worker_Contribution.sum(min_count=1)
            emol = b.Emolument_Contribution.sum(min_count=1)
            out.append({**prefix, "SUB_GROUP_ID": 4, "COL_DESC": bac, "DATA": emol / hired if hired and not pd.isna(hired) else np.nan})
            den = b.Multiplier.sum()
            fixed = b.Fixed_Asset_Contribution.sum(min_count=1)
            loan = b.Loan_Contribution.sum(min_count=1)
            out.append({**prefix, "SUB_GROUP_ID": 5, "COL_DESC": bac, "DATA": fixed / den if den and not pd.isna(fixed) else np.nan})
            out.append({**prefix, "SUB_GROUP_ID": 6, "COL_DESC": bac, "DATA": loan / den if den and not pd.isna(loan) else np.nan})
        total_gva = g.GVA_Contribution.sum(min_count=1)
        for bac in BAC_ORDER:
            value = 100.0 if bac == "Total" and pd.notna(total_gva) else np.nan
            if bac != "Total" and total_gva not in (0, None) and pd.notna(total_gva):
                value = 100 * g.loc[g.BAC == bac, "GVA_Contribution"].sum(min_count=1) / total_gva
            out.append({**prefix, "SUB_GROUP_ID": 7, "COL_DESC": bac, "DATA": value})
        for bac in BAC_ORDER:
            b = g if bac == "Total" else g[g.BAC == bac]
            valid_registration = b[b.Registered.isin(["1", "2"])]
            den = valid_registration.Multiplier.sum()
            for status, code in (("Unregistered", "2"), ("Registered", "1")):
                value = 100 * valid_registration.loc[valid_registration.Registered == code, "Multiplier"].sum() / den if den else np.nan
                out.append({**prefix, "SUB_GROUP_ID": 8, "COL_DESC": f"{bac} - {status}", "DATA": value})
    return pd.DataFrame(out)


def registration_diagnostics(base: pd.DataFrame) -> pd.DataFrame:
    """Return auditable weighted item-227 counts for every client domain."""
    d = _expanded_domains(base)
    keys = ["State_ID", "State_Name", "District_ID", "District_Name", "Sector_code", "Sector"]
    rows = []
    for key, group in d.groupby(keys, sort=False, dropna=False):
        prefix = dict(zip(keys, key))
        for bac in BAC_ORDER:
            b = group if bac == "Total" else group[group.BAC == bac]
            registered = b.loc[b.Registered == "1", "Multiplier"].sum()
            unregistered = b.loc[b.Registered == "2", "Multiplier"].sum()
            valid = registered + unregistered
            invalid = b.loc[~b.Registered.isin(["1", "2"]), "Multiplier"].sum()
            eligible = b.Multiplier.sum()
            registered_pct = 100 * registered / valid if valid else np.nan
            unregistered_pct = 100 * unregistered / valid if valid else np.nan
            pct_sum = registered_pct + unregistered_pct
            rows.append({
                **prefix, "BAC": bac,
                "Eligible_UE_Weighted_Count": eligible,
                "Valid_Registration_Weighted_Count": valid,
                "Registered_Weighted_Count": registered,
                "Unregistered_Weighted_Count": unregistered,
                "Missing_Invalid_Registration_Weighted_Count": invalid,
                "Denominator_Used": valid,
                "Registered_Percent": registered_pct,
                "Unregistered_Percent": unregistered_pct,
                "Percent_Sum": pct_sum,
                "Reconciliation_Gap": pct_sum - 100 if pd.notna(pct_sum) else np.nan,
            })
    return pd.DataFrame(rows)
