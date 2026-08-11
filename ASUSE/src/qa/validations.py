from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


KEYS = ["State_ID", "District_ID", "Sector_code"]


def _reconcile(step: pd.DataFrame, subgroup: int, total: str, components: list[str], tolerance: float) -> pd.DataFrame:
    x = step[step.SUB_GROUP_ID == subgroup].pivot_table(index=KEYS, columns="COL_DESC", values="DATA", aggfunc="first").reset_index()
    for column in [total, *components]:
        if column not in x.columns:
            x[column] = np.nan
    x["Calculated_Component_Sum"] = x.reindex(columns=components).sum(axis=1, min_count=len(components))
    x["Reference_Total"] = x.get(total)
    x["Difference"] = x.Calculated_Component_Sum - x.Reference_Total
    unavailable = x.Reference_Total.isna() | x.reindex(columns=components).isna().any(axis=1)
    x["Pass_Fail"] = np.where(unavailable, "NOT_CALCULABLE", np.where(x.Difference.abs() <= tolerance + 1e-9, "PASS", "FAIL"))
    return x


def write_qa(final: pd.DataFrame, master: pd.DataFrame, qa_dir: Path, tolerance: float) -> dict[str, int]:
    qa_dir.mkdir(parents=True, exist_ok=True)
    est = _reconcile(final, 1, "Total", ["Manufacturing", "Trade", "Other Services"], tolerance)
    own = _reconcile(final, 2, "Total", ["Proprietary", "Partnership", "SHG", "Others"], tolerance)
    workers = _reconcile(final, 3, "Total", ["Manufacturing", "Trade", "Other Services"], tolerance)
    gva = _reconcile(final, 7, "Total", ["Manufacturing", "Trade", "Other Services"], 0.05)
    est.to_csv(qa_dir / "qa_establishment_reconciliation.csv", index=False)
    own.to_csv(qa_dir / "qa_ownership_reconciliation.csv", index=False)
    workers.to_csv(qa_dir / "qa_worker_reconciliation.csv", index=False)
    gva.to_csv(qa_dir / "qa_gva_share.csv", index=False)

    reg = final[final.SUB_GROUP_ID == 8].copy()
    reg["BAC"] = reg.COL_DESC.str.replace(r" - (Unregistered|Registered)$", "", regex=True)
    reg["Status"] = reg.COL_DESC.str.extract(r" - (Unregistered|Registered)$")
    reg = reg.pivot_table(index=KEYS + ["BAC"], columns="Status", values="DATA", aggfunc="first").reset_index()
    reg["Sum"] = reg.get("Registered") + reg.get("Unregistered")
    reg["Difference_From_100"] = reg.Sum - 100
    reg["Pass_Fail"] = np.where(reg[["Registered", "Unregistered"]].isna().any(axis=1), "NOT_CALCULABLE", np.where(reg.Difference_From_100.abs() <= 0.05, "PASS", "FAIL"))
    reg.to_csv(qa_dir / "qa_registration.csv", index=False)

    for subgroup, name in [(3, "worker"), (4, "emolument"), (5, "fixed_asset"), (6, "loan")]:
        x = final[final.SUB_GROUP_ID == subgroup].copy()
        x["QA_Flag"] = np.where(x.DATA.isna(), "MISSING", np.where(x.DATA < 0, "NEGATIVE", "OK"))
        x.to_csv(qa_dir / f"qa_{name}_checks.csv", index=False)

    dup = final[final.duplicated(["State_ID", "District_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"], keep=False)]
    dup.to_csv(qa_dir / "qa_duplicate_rows.csv", index=False)
    valid = set(zip(master.SUB_GROUP_ID, master.Client_Col_ID))
    missing = final[["SUB_GROUP_ID", "Col_ID"]].drop_duplicates()
    missing = missing[~missing.apply(lambda r: (r.SUB_GROUP_ID, r.Col_ID) in valid, axis=1)]
    missing.to_csv(qa_dir / "qa_missing_mapping.csv", index=False)

    # Additive total versus rural+urban.
    additive = final[final.SUB_GROUP_ID.isin([1, 2, 3])]
    p = additive.pivot_table(index=["State_ID", "District_ID", "SUB_GROUP_ID", "Col_ID"], columns="Sector_code", values="DATA", aggfunc="first").reset_index()
    p["Rural_Urban_Sum"] = p.get(1) + p.get(2)
    p["Difference"] = p.get(0) - p.Rural_Urban_Sum
    p["Pass_Fail"] = np.where(p[[0, 1, 2]].isna().any(axis=1), "NOT_CALCULABLE", np.where(p.Difference.abs() <= tolerance, "PASS", "FAIL"))
    p = p.rename(columns={0: "Total", 1: "Rural", 2: "Urban"})
    p.to_csv(qa_dir / "qa_total_rural_urban.csv", index=False)

    state = final[(final.District_ID == 0) & (final.State_ID != 0) & final.SUB_GROUP_ID.isin([1, 2, 3])]
    dist = final[(final.District_ID != 0) & final.SUB_GROUP_ID.isin([1, 2, 3])].groupby(["State_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"], as_index=False).DATA.sum()
    sd = state.merge(dist, on=["State_ID", "Sector_code", "SUB_GROUP_ID", "Col_ID"], suffixes=("_State", "_District_Sum"))
    sd["Difference"] = sd.DATA_State - sd.DATA_District_Sum
    sd.to_csv(qa_dir / "qa_state_district.csv", index=False)

    year = str(final.Year.iloc[0]) if len(final) else ""
    detailed_rows = []

    def add_reconciliation(frame: pd.DataFrame, rule: str, metric: str, tol: float) -> None:
        for row in frame.itertuples(index=False):
            detailed_rows.append({
                "rule_name": rule, "metric": metric, "year": year,
                "geography": f"State_ID={row.State_ID};District_ID={row.District_ID}",
                "sector/activity": f"Sector_code={row.Sector_code}",
                "expected_value": row.Reference_Total,
                "actual_value": row.Calculated_Component_Sum,
                "difference": row.Difference, "tolerance": tol,
                "status": row.Pass_Fail,
            })

    add_reconciliation(est, "BAC_COMPONENTS_EQUAL_TOTAL", "Establishments", tolerance)
    add_reconciliation(workers, "BAC_COMPONENTS_EQUAL_TOTAL", "Workers", tolerance)
    add_reconciliation(own, "OWNERSHIP_COMPONENTS_EQUAL_TOTAL", "Ownership", tolerance)
    add_reconciliation(gva, "GVA_SECTOR_SHARES_EQUAL_100", "GVA share", 0.05)
    for row in reg.itertuples(index=False):
        detailed_rows.append({
            "rule_name": "REGISTRATION_SHARES_EQUAL_100", "metric": "Registration status", "year": year,
            "geography": f"State_ID={row.State_ID};District_ID={row.District_ID}",
            "sector/activity": f"Sector_code={row.Sector_code};BAC={row.BAC}",
            "expected_value": 100.0, "actual_value": row.Sum,
            "difference": row.Difference_From_100, "tolerance": 0.05,
            "status": row.Pass_Fail,
        })
    for row in p.itertuples(index=False):
        detailed_rows.append({
            "rule_name": "TOTAL_EQUALS_RURAL_PLUS_URBAN", "metric": f"SUB_GROUP_ID={row.SUB_GROUP_ID};Col_ID={row.Col_ID}", "year": year,
            "geography": f"State_ID={row.State_ID};District_ID={row.District_ID}",
            "sector/activity": "Total/Rural/Urban", "expected_value": row.Total,
            "actual_value": row.Rural_Urban_Sum, "difference": row.Difference,
            "tolerance": tolerance, "status": row.Pass_Fail,
        })
    ratio_metrics = {
        4: "Annual emoluments per hired worker",
        5: "Average fixed assets per UE",
        6: "Outstanding loan per UE",
    }
    for row in final.loc[final.SUB_GROUP_ID.isin(ratio_metrics)].itertuples(index=False):
        status = "NOT_CALCULABLE" if pd.isna(row.DATA) else "FAIL" if row.DATA < 0 else "PASS"
        detailed_rows.append({
            "rule_name": "RATIO_VALUE_NONNEGATIVE_OR_ZERO_DENOMINATOR",
            "metric": ratio_metrics[row.SUB_GROUP_ID], "year": year,
            "geography": f"State_ID={row.State_ID};District_ID={row.District_ID}",
            "sector/activity": f"Sector_code={row.Sector_code};Category={row.COL_DESC}",
            "expected_value": ">= 0 when denominator is non-zero", "actual_value": row.DATA,
            "difference": np.nan, "tolerance": "Not applicable", "status": status,
        })
    pd.DataFrame(detailed_rows, columns=[
        "rule_name", "metric", "year", "geography", "sector/activity",
        "expected_value", "actual_value", "difference", "tolerance", "status",
    ]).to_csv(qa_dir / "qa_detailed.csv", index=False)

    summary = {
        "duplicate_rows": len(dup), "missing_mapping": len(missing),
        "establishment_failures": int((est.Pass_Fail == "FAIL").sum()),
        "worker_failures": int((workers.Pass_Fail == "FAIL").sum()),
        "ownership_failures": int((own.Pass_Fail == "FAIL").sum()),
        "gva_failures": int((gva.Pass_Fail == "FAIL").sum()),
        "registration_failures": int((reg.Pass_Fail == "FAIL").sum()),
        "rural_urban_failures": int((p.Pass_Fail == "FAIL").sum()),
    }
    pd.DataFrame([summary]).to_excel(qa_dir / "qa_summary.xlsx", index=False)
    return summary
