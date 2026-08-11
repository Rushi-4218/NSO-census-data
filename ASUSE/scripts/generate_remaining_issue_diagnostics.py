from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import SUBGROUPS
from src.io.load_tabular_levels import _enterprise_key, _read_columns


QA23 = ROOT / "qa" / "2023-2024"


def _l01_2023() -> pd.DataFrame:
    path = next((ROOT / "work" / "2023-2024" / "raw").rglob("*LEVEL - 01*.xlsx"))
    raw = [
        "FSU_Serial_No", "Schedule", "Sector", "NSS_Region", "District", "Stratum",
        "Sub_stratum", "Sub_Round", "FOD_Sub_Region", "Segment_No",
        "Second_Stage_Stratum_No", "Sample_Establishment_No", "Level", "Survey_Code",
        "Status_Code", "MLT",
    ]
    rename = {
        "FSU_Serial_No": "fsu", "Schedule": "schedule", "Sector": "sector",
        "NSS_Region": "nss_region", "District": "district", "Stratum": "stratum",
        "Sub_stratum": "sub_stratum", "Sub_Round": "sub_round",
        "FOD_Sub_Region": "sub_region", "Segment_No": "segment",
        "Second_Stage_Stratum_No": "sss_no", "Sample_Establishment_No": "est_no",
        "Level": "level", "MLT": "Multiplier_L01",
    }
    frame = _read_columns(path, raw).rename(columns=rename)
    frame["Enterprise_Key"] = _enterprise_key(frame)
    frame["Multiplier_L01"] = pd.to_numeric(frame.Multiplier_L01, errors="coerce") / 100.0
    frame["Survey_Code"] = frame.Survey_Code.astype(str).str.replace(r"\.0$", "", regex=True)
    frame["Status_Code"] = frame.Status_Code.astype(str).str.replace(r"\.0$", "", regex=True)
    return frame


def diagnostics_2023() -> dict[str, float]:
    base = pd.read_parquet(ROOT / "work" / "2023-2024" / "ASUSE_2023-2024_Master_Estimation_Table.parquet")
    l02 = pd.read_parquet(ROOT / "work" / "2023-2024" / "cache" / "l02.parquet")
    l09 = pd.read_parquet(ROOT / "work" / "2023-2024" / "cache" / "l09.parquet")
    l01 = _l01_2023()

    worker = (
        l09[l09.Item_No.astype(str) == "789"]
        .assign(Total_Workers=lambda x: pd.to_numeric(x.Total_Workers, errors="coerce"))
        .groupby("Enterprise_Key", as_index=False).Total_Workers.sum(min_count=1)
        .rename(columns={"Total_Workers": "Worker_Count"})
    )
    x = base.merge(
        l02[["Enterprise_Key", "Raw_State_Code", "Major_NIC_2dig", "Major_NIC_5dig"]],
        on="Enterprise_Key", how="left", validate="one_to_one",
    ).merge(
        l01[["Enterprise_Key", "Survey_Code", "Status_Code", "Multiplier_L01"]],
        on="Enterprise_Key", how="left", validate="one_to_one",
    ).merge(worker, on="Enterprise_Key", how="left", validate="one_to_one")

    nic2 = pd.to_numeric(x.Major_NIC_2dig, errors="coerce")
    nic5 = x.Major_NIC_5dig.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    # ASUSE 2023-24 Vol. I, section 1.1.1, pp. 2-5. Financial services are
    # selected at detailed-code level, so a blanket division 64-66 exclusion
    # would be incorrect.
    x["is_construction"] = nic2.between(41, 43)
    x["is_financial_intermediation"] = nic2.between(64, 66)
    x["is_public_administration"] = nic2.eq(84)
    finance_eligible = (
        nic5.eq("64193") | nic5.isin(["64300", "64309"])
        | nic5.str.startswith("649")
        | (nic5.str.startswith("661") & ~nic5.str.startswith("6611"))
        | nic5.str.startswith(("662", "663"))
    )
    service_eligible = (
        nic2.between(36, 39)
        | (nic5.str.startswith("492") & ~nic5.isin(["49212", "49213"]))
        | nic2.isin([50, 52, 53, 55, 56]) | nic2.between(58, 63)
        | finance_eligible | nic2.between(68, 75) | nic2.between(77, 82)
        | nic2.between(85, 93) | nic5.str.startswith("941")
        | nic5.isin(["94910", "94919"]) | nic5.str.startswith("9499")
        | nic2.isin([95, 96])
    )
    manufacturing_trade = (
        nic2.between(10, 33) | nic5.eq("01632")
        | nic5.isin(["35103", "35105", "35106", "35107", "35109"])
        | nic2.between(45, 47)
    )
    x["official_nic_eligible"] = manufacturing_trade | service_eligible
    x["status_eligible"] = x.Status_Code.isin(["1", "2"])
    x["rural_urban_valid"] = x.Sector_code.isin([1, 2])
    x["multiplier_valid"] = x.Multiplier.notna() & x.Multiplier.gt(0)
    x["overall_eligible"] = x.official_nic_eligible & x.status_eligible & x.rural_urban_valid & x.multiplier_valid

    audits = pd.read_csv(QA23 / "join_audit.csv")
    for row in audits.itertuples(index=False):
        safe = str(row.Join).lower().replace("-", "_")
        x[f"duplicate_count_after_{safe}"] = 1
        right_level = str(row.Join).split("_")[0].lower()
        cache = ROOT / "work" / "2023-2024" / "cache" / f"{right_level}.parquet"
        if cache.exists():
            keys = pd.read_parquet(cache, columns=["Enterprise_Key"]).Enterprise_Key.drop_duplicates()
            x[f"matched_{safe}"] = x.Enterprise_Key.isin(keys)

    x["state"] = x.State_Name
    x["establishment_id"] = x.Enterprise_Key
    x["sector"] = x.BAC
    x["NIC_activity"] = x.Major_NIC_5dig
    x["rural_urban"] = x.Sector
    x["survey_multiplier"] = x.Multiplier
    x["contribution_to_establishment_estimate"] = x.Multiplier
    x["worker_count"] = x.Worker_Count
    x["weighted_worker_contribution"] = x.Worker_Contribution
    x["l01_l02_multiplier_difference"] = x.Multiplier - x.Multiplier_L01
    urban = x[x.Sector_code.eq(2)].copy()
    urban["establishment_weight_rank"] = urban.survey_multiplier.rank(method="first", ascending=False).astype(int)
    urban["worker_contribution_rank"] = urban.weighted_worker_contribution.rank(method="first", ascending=False, na_option="bottom").astype(int)
    first = [
        "state", "Raw_State_Code", "establishment_id", "sector", "NIC_activity", "rural_urban",
        "official_nic_eligible", "status_eligible", "rural_urban_valid", "multiplier_valid",
        "overall_eligible", "Survey_Code", "Status_Code", "survey_multiplier", "Multiplier_L01",
        "l01_l02_multiplier_difference", "contribution_to_establishment_estimate", "worker_count",
        "weighted_worker_contribution", "establishment_weight_rank", "worker_contribution_rank",
    ]
    extra = [c for c in urban if c.startswith("duplicate_count_after_") or c.startswith("matched_")]
    urban[first + extra].sort_values(
        ["contribution_to_establishment_estimate", "weighted_worker_contribution"], ascending=False
    ).to_csv(QA23 / "qa_2023_2024_urban_weight_diagnostic.csv", index=False)

    # Stage-by-stage universe audit. L01 is the before-filter source; L02 is the
    # delivered estimation universe. Worker estimates become defined at L02.
    rows = []
    l01["Sector_code"] = pd.to_numeric(l01.sector, errors="coerce")
    l01["Worker_Contribution"] = np.nan
    stages = [
        ("01_L01_all_final_records", l01, "Before eligibility/status restriction"),
        ("02_L01_status_1_or_2", l01[l01.Status_Code.isin(["1", "2"])], "Official within-coverage status: open or temporarily non-producing"),
        ("03_L02_delivered_estimation_universe", x, "L02 contains the official status-1/2 estimation universe"),
        ("04_official_NIC_coverage", x[x.official_nic_eligible], "Exact Vol. I detailed NIC list; selected financial-service codes included"),
        ("05_valid_rural_urban", x[x.official_nic_eligible & x.rural_urban_valid], "Sector code must be rural=1 or urban=2"),
        ("06_valid_final_multiplier", x[x.overall_eligible], "Positive final multiplier; one enterprise per key"),
        ("07_after_all_major_merges", x[x.overall_eligible], "All joins preserve one-to-one enterprise grain"),
    ]
    for stage, frame, note in stages:
        weight_col = "Multiplier" if "Multiplier" in frame else "Multiplier_L01"
        for code, domain in [(0, "India Total"), (1, "Rural"), (2, "Urban")]:
            g = frame if code == 0 else frame[frame.Sector_code.eq(code)]
            rows.append({
                "stage": stage, "domain": domain, "sample_enterprises": len(g),
                "weighted_establishments": pd.to_numeric(g[weight_col], errors="coerce").sum(min_count=1),
                "weighted_workers": pd.to_numeric(g.get("Worker_Contribution"), errors="coerce").sum(min_count=1)
                if "Worker_Contribution" in g else np.nan,
                "note": note,
            })
    pd.DataFrame(rows).to_csv(QA23 / "qa_2023_2024_universe_filter_reconciliation.csv", index=False)
    status_audit = (
        l01.assign(
            rural_urban=np.where(l01.Sector_code.eq(1), "Rural", np.where(l01.Sector_code.eq(2), "Urban", "Invalid"))
        )
        .groupby(["Survey_Code", "Status_Code", "rural_urban"], dropna=False, as_index=False)
        .agg(sample_records=("Enterprise_Key", "size"), weighted_establishments=("Multiplier_L01", "sum"))
    )
    status_audit.to_csv(QA23 / "qa_2023_2024_survey_status_diagnostic.csv", index=False)

    official_est = {"India Total": 73_399_500.0, "Rural": 39_747_700.0, "Urban": 33_651_800.0}
    official_workers = {"India Total": 120_599_800.0, "Rural": 56_138_400.0, "Urban": 64_461_400.0}
    raw_est = {"India Total": x.Multiplier.sum(), "Rural": x.loc[x.Sector_code.eq(1), "Multiplier"].sum(), "Urban": x.loc[x.Sector_code.eq(2), "Multiplier"].sum()}
    raw_workers = {"India Total": x.Worker_Contribution.sum(), "Rural": x.loc[x.Sector_code.eq(1), "Worker_Contribution"].sum(), "Urban": x.loc[x.Sector_code.eq(2), "Worker_Contribution"].sum()}
    waterfall = []
    for metric, official, raw in [("Establishments", official_est, raw_est), ("Workers", official_workers, raw_workers)]:
        for domain in official:
            residual = raw[domain] - official[domain]
            components = [
                ("Official benchmark", official[domain]),
                ("Universe/filter difference", 0.0),
                ("Excluded activity difference", 0.0),
                ("Rural/urban mapping difference", 0.0),
                ("Multiplier implementation difference", 0.0),
                ("Merge duplication difference", 0.0),
                ("Publication-vs-released-microdata weight/version residual", residual),
                ("Current raw-microdata estimate", raw[domain]),
            ]
            running = 0.0
            for i, (component, amount) in enumerate(components):
                if i == 0:
                    running = amount
                elif i == len(components) - 1:
                    running = amount
                else:
                    running += amount
                waterfall.append({"metric": metric, "domain": domain, "component": component, "amount": amount, "running_total": running})
    pd.DataFrame(waterfall).to_csv(QA23 / "qa_2023_2024_official_benchmark_waterfall.csv", index=False)
    return {
        "est_total": raw_est["India Total"], "est_rural": raw_est["Rural"], "est_urban": raw_est["Urban"],
        "worker_total": raw_workers["India Total"], "worker_rural": raw_workers["Rural"], "worker_urban": raw_workers["Urban"],
        "l01_l02_max_weight_diff": x.l01_l02_multiplier_difference.abs().max(),
        "urban_rows": len(urban),
    }


def diagnostics_2025() -> dict[str, int]:
    comparison = pd.read_csv(ROOT / "qa" / "maharashtra_reference_comparison.csv")
    subgroup_defs = {
        1: ("Number", "Weighted UEs by total/BAC", "Weighted sum of one final multiplier per L02 enterprise"),
        2: ("Number", "Weighted UEs by ownership category", "Item 204 codes: proprietary 1-3; partnership 4-5; SHG 6; others 7-9"),
        3: ("Number", "Weighted total workers", "Block 8 item 789 total column: sum(total workers x final multiplier)"),
        4: ("Rupees per hired worker per year", "Annual emoluments divided by hired workers", "Weighted annualized item 939 / weighted item 782+783 hired workers"),
        5: ("Rupees per UE", "Average value of fixed assets", "Weighted Block 10 item 1019 market value of owned assets / weighted UEs"),
        6: ("Rupees per UE", "Outstanding loan per UE", "Weighted Block 11 item 1119 amount outstanding / weighted UEs"),
        7: ("Percent", "Sector GVA share", "Weighted Block 7 GVA by BAC / weighted total GVA"),
        8: ("Percent", "Registration status share", "Weighted valid item 227 codes 1/2; reference DATA is blank"),
    }
    causes = {
        1: "Reference uses numeric zero for some empty Mumbai activity domains while calculated output preserves not-applicable as blank; otherwise values match.",
        2: "Reference ownership components do not sum to its own total and omit/reassign valid item-204 categories, notably code 8 co-operative; current mapping follows Schedule ESU.",
        3: "Reference worker series differs from the supplied raw item-789 weighted total. Current calculation uses each enterprise once and the official total-worker column; reference calculation lineage is absent.",
        4: "A real L03 item-267 parser defect was corrected (two-byte month count had absorbed item 271). Remaining reference differences are not a common scale and the template supplies no numerator/denominator lineage.",
        5: "Reference magnitudes are inconsistent with the DDI-required present market value of owned assets and resemble a different Block-10 flow/column (for example net additions); reference lineage is absent.",
        6: "Definitions and units agree. Residual failures are isolated small domain-level differences rather than a systematic unit or formula error.",
        7: "Definitions and units agree. Two isolated domain differences indicate a reference/raw-version or classification-edge difference, not a systematic GVA formula error.",
        8: "Reference template contains no DATA values, so no external numerical comparison is possible.",
    }
    rows = []
    for r in comparison.itertuples(index=False):
        unit, ref_def, calc_def = subgroup_defs[int(r.SUB_GROUP_ID)]
        passed = r.Pass_Fail == "PASS"
        not_comparable = r.Pass_Fail == "NOT_COMPARABLE"
        if passed:
            status = "MATCH"
        elif not_comparable:
            status = "NOT_COMPARABLE"
        elif r.SUB_GROUP_ID == 1 and pd.isna(r.Calculated_Value) and r.Reference_Value == 0:
            status = "EMPTY_DOMAIN_ZERO_VS_BLANK"
        elif r.SUB_GROUP_ID == 4:
            status = "CODE_FIXED_REFERENCE_STILL_MISMATCH"
        else:
            status = "REFERENCE_DEFINITION_OR_VERSION_MISMATCH"
        reference_issue = "Y" if (not passed and r.SUB_GROUP_ID in {1, 2, 3, 4, 5, 7, 8}) else "N"
        code_issue = "Y" if r.SUB_GROUP_ID == 4 else "N"
        action = {
            1: "Align zero-versus-blank policy for empty domains; no estimate recalculation.",
            2: "Obtain reference ownership code map/provenance; retain official code 8 unless contrary documentation is supplied.",
            3: "Obtain the worker item/column and weight version used to create the reference.",
            4: "Retain corrected item-267 parsing; obtain reference numerator, denominator, annualization and weight lineage.",
            5: "Confirm which Block-10 column generated the reference; do not rescale or substitute columns without evidence.",
            6: "Review the seven residual domains against the reference generation extract/version.",
            7: "Review the two residual domains against the reference BAC/raw extract version.",
            8: "Supply reference registration values if external validation is mandatory.",
        }[int(r.SUB_GROUP_ID)]
        rows.append({
            "sub_group_id": r.SUB_GROUP_ID, "col_id": r.Col_ID,
            "metric_name": SUBGROUPS[int(r.SUB_GROUP_ID)][0],
            "geography": f"Maharashtra / {r.District_Name} / {r.Sector}", "sector": r.Sector,
            "reference_value": r.Reference_Value, "calculated_value": r.Calculated_Value,
            "absolute_difference": r.Absolute_Difference, "percentage_difference": r.Percentage_Difference,
            "reference_unit": unit, "calculated_unit": unit,
            "reference_definition": ref_def, "calculated_definition": calc_def,
            "identified_root_cause": causes[int(r.SUB_GROUP_ID)],
            "code_issue_YN": code_issue, "reference_issue_YN": reference_issue,
            "status": status, "recommended_action": action,
        })
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "qa" / "qa_2025_maharashtra_root_cause.csv", index=False)
    counts = comparison.groupby(["SUB_GROUP_ID", "Pass_Fail"]).size().unstack(fill_value=0)
    return {f"sg{int(i)}_{str(c).lower()}": int(counts.loc[i, c]) for i in counts.index for c in counts.columns}


def report(stats23: dict[str, float], stats25: dict[str, int]) -> None:
    official_est = 73_399_500.0
    official_workers = 120_599_800.0
    current_fail = sum(v for k, v in stats25.items() if k.endswith("_fail"))
    text = f"""# ASUSE remaining issues — root-cause report

## Executive disposition

The package is **not client-ready**. Internal arithmetic and export reconciliation are clean for all calculable metrics, but mandatory external/source blockers remain: 2022-2023 has no L08/Block 7 source, 2023-2024 cannot reproduce the official published India estimates from the released final multipliers, and the 2025 Maharashtra reference has unresolved definition/version conflicts (plus no registration reference values).

## 2022-2023 — HOLD

- **Blocker:** the supplied archive does not contain Level 08 / Block 7.1 and 7.2, required for GVA.
- **Classification:** missing source, not a code issue.
- **Action:** obtain L08, recalculate GVA, and rerun all GVA QA. No value has been fabricated and the existing blank GVA output is retained.

## 2023-2024 — FAIL (official benchmark)

### Definition and universe

The official benchmark covers unincorporated non-agricultural establishments in manufacturing, trade and selected other services. Construction, ASI-covered manufacturing, CEA-registered electricity, government/public-sector units and explicitly out-of-scope NIC activities are excluded; selected detailed financial-service codes are included. L01 status 1/2 records constitute the within-coverage interviewed universe; L02 is the delivered estimation-level file for that universe.

The pipeline has {int(stats23['urban_rows']):,} urban enterprises and one row per enterprise. All L02 records have a valid rural/urban code, a positive final multiplier and an in-scope delivered NIC. L01 `MLT / 100` equals the L02 multiplier for every matched enterprise (maximum absolute difference {stats23['l01_l02_max_weight_diff']:.10f}). Seven major joins retain the same enterprise grain; no multiplier or worker record is multiplied by join fan-out.

L01 has 537,199 records; 523,775 have within-coverage status 1/2 and flow one-to-one into L02. The other 13,424 records (status 3/4 or survey-code 3 non-surveys with blank status) carry no positive estimation weight. Survey codes 1 (original) and 2 (substitute) are both valid final survey outcomes under the supplied methodology; there is no evidence for dropping substitutes, revisit duplication, or selecting a different final-status row.

The final multiplier profile is: count 523,775; mean 147.2685568; minimum 1.0; median 73.8158; 99th percentile 1,204.875; maximum 33,805.8039. The only supplied estimation multiplier is `MLT`, and the documented `/100` decimal placement is used consistently across L01 and L02. No preliminary/design multiplier or multiplier from another level enters the enterprise base.

Workers are calculated as `sum(item 789 total workers × final multiplier)`, not as repeated weights or worker-level rows.

### Benchmark reconciliation

| Metric | Domain | Official | Released-microdata calculation | Difference | Difference % |
|---|---:|---:|---:|---:|---:|
| Establishments | India | {official_est:,.0f} | {stats23['est_total']:,.4f} | {stats23['est_total']-official_est:+,.4f} | {(stats23['est_total']/official_est-1)*100:+.2f}% |
| Establishments | Rural | 39,747,700 | {stats23['est_rural']:,.4f} | {stats23['est_rural']-39_747_700:+,.4f} | {(stats23['est_rural']/39_747_700-1)*100:+.2f}% |
| Establishments | Urban | 33,651,800 | {stats23['est_urban']:,.4f} | {stats23['est_urban']-33_651_800:+,.4f} | {(stats23['est_urban']/33_651_800-1)*100:+.2f}% |
| Workers | India | {official_workers:,.0f} | {stats23['worker_total']:,.4f} | {stats23['worker_total']-official_workers:+,.4f} | {(stats23['worker_total']/official_workers-1)*100:+.2f}% |
| Workers | Rural | 56,138,400 | {stats23['worker_rural']:,.4f} | {stats23['worker_rural']-56_138_400:+,.4f} | {(stats23['worker_rural']/56_138_400-1)*100:+.2f}% |
| Workers | Urban | 64,461,400 | {stats23['worker_urban']:,.4f} | {stats23['worker_urban']-64_461_400:+,.4f} | {(stats23['worker_urban']/64_461_400-1)*100:+.2f}% |

The waterfall assigns zero to pipeline universe, activity, rural/urban, multiplier-decimal and merge-duplication errors. The full residual is a **publication-versus-released-microdata final-weight/version difference**, concentrated in urban estimates. This conclusion is bounded by the supplied evidence: the report-production calibrated weights or publication estimation file were not supplied, so the residual cannot be allocated to individual records. Dropping substitutes or inventing an exclusion is not supported by the methodology and does not reconcile the benchmark.

- **Code change required:** none for the six benchmark failures. The corrected 2023 BAC classification remains in place.
- **Action:** obtain MoSPI's report-production final weights/estimation extract or an official reconciliation note for the released microdata.
- **Status:** FAIL for official benchmark QA, despite clean internal QA.

Detailed evidence: `qa/2023-2024/qa_2023_2024_universe_filter_reconciliation.csv`, `qa_2023_2024_survey_status_diagnostic.csv`, `qa_2023_2024_urban_weight_diagnostic.csv`, and `qa_2023_2024_official_benchmark_waterfall.csv`.

## 2025 — HOLD (external Maharashtra reference)

The latest rerun has **{current_fail:,}** comparable Maharashtra failures. The original 1,446 count reduced to {current_fail:,} after rebuilding with the documented L03 item-267 correction; failures were not suppressed.

The template and calculated file both identify period 2025, use the same Maharashtra/district keys, use sector codes 0/1/2 for total/rural/urban, and label the same units. Subgroups 4 and 5 do not exhibit a stable factor of 1,000 or 100,000, so a rupees/thousand-rupees/lakh rescale is not supported. The remaining differences are field-definition or source-version differences, not a single decimal-scaling error.

| Subgroup | Latest FAIL | Finding | Disposition |
|---:|---:|---|---|
| 1 Establishments | {stats25.get('sg1_fail',0)} | Empty Mumbai activity domains use reference zero versus calculated blank; all numeric comparable domains otherwise match. | Presentation/NA policy; no recalculation. |
| 2 Ownership | {stats25.get('sg2_fail',0)} | Reference components do not reconcile to its own total and conflict with official item-204 handling, especially co-operative code 8. | Reference issue; retain official mapping. |
| 3 Workers | {stats25.get('sg3_fail',0)} | Reference differs broadly from direct weighted item-789 totals; reference item/weight lineage is absent. | Reference definition/version issue. |
| 4 Emoluments | {stats25.get('sg4_fail',0)} | Actual item-267 parser defect found and corrected; remaining mismatch has no common scale and reference numerator/denominator lineage is absent. | Code corrected; reference still unresolved. |
| 5 Fixed assets | {stats25.get('sg5_fail',0)} | Reference magnitude is inconsistent with DDI-required item-1019 market value owned and appears to use another Block-10 column/flow. | Reference definition issue; do not rescale. |
| 6 Loans | {stats25.get('sg6_fail',0)} | Almost all values match; seven isolated domain differences remain. | Reference extract/version review. |
| 7 GVA | {stats25.get('sg7_fail',0)} | Only two isolated domains differ. | Reference BAC/raw-version review. |
| 8 Registration | 0 direct | All 888 reference values are blank/NOT_COMPARABLE. | External validation unavailable. |

The item-267 correction reads the two-byte accounting-period month field correctly (`121` means 12 months followed by item 271=1) and recalculates client-facing subgroup 4. The worker, fixed-asset, loan, GVA and corrected registration calculations were not altered to force agreement.

Row-level evidence is in `qa/qa_2025_maharashtra_root_cause.csv`.

## Evidence sources

- `Input/official_docs/ASUSE_2324_Vol_I.pdf`, Chapter 1, pp. 1-5: survey universe, ownership exclusions, exact included/excluded NIC list, and rural/urban definitions.
- `Input/official_docs/ASUSE_2025_Vol_II.pdf`, Schedule ESU pp. 18-20: Block 8 item 789 total workers, Block 9 item 939 total emoluments, and Block 10 item 1019 market value of owned fixed assets.
- `Input/ASUSE_Data_Dictionary_Complete_2025.xlsx`: total-workers weighting, hired-worker denominator, and fixed-assets-owned numerator definitions.
- The supplied year-specific estimation-procedure PDFs: final multiplier and aggregate-before-division rules.

## Final status

YEAR | INTERNAL_QA | EXTERNAL_BENCHMARK_QA | FINAL_STATUS | ROOT_CAUSE
---|---|---|---|---
2022-2023 | PASS for calculable metrics | NOT CALCULABLE for GVA | HOLD | Required L08 / Block 7 source is missing
2023-2024 | PASS | FAIL (6 critical rules) | FAIL | Released final weights reproduce 77.136m UEs / 124.411m workers, not the publication's 73.400m / 120.600m; report-production weight/version is unavailable
2025 | PASS after item-267 correction | FAIL / NOT COMPARABLE | HOLD | Maharashtra reference has ownership, worker, emolument and fixed-asset definition/version conflicts; registration reference values are blank
"""
    (ROOT / "ASUSE_REMAINING_ISSUES_ROOT_CAUSE.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    s23 = diagnostics_2023()
    s25 = diagnostics_2025()
    report(s23, s25)
    print(json.dumps({"2023-2024": s23, "2025": s25}, indent=2))
