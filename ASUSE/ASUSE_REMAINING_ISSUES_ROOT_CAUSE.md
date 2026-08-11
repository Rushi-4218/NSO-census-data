# ASUSE remaining issues — root-cause report

## Executive disposition

The package is **not client-ready**. Internal arithmetic and export reconciliation are clean for all calculable metrics, but mandatory external/source blockers remain: 2022-2023 has no L08/Block 7 source, 2023-2024 cannot reproduce the official published India estimates from the released final multipliers, and the 2025 Maharashtra reference has unresolved definition/version conflicts (plus no registration reference values).

## 2022-2023 — HOLD

- **Blocker:** the supplied archive does not contain Level 08 / Block 7.1 and 7.2, required for GVA.
- **Classification:** missing source, not a code issue.
- **Action:** obtain L08, recalculate GVA, and rerun all GVA QA. No value has been fabricated and the existing blank GVA output is retained.

## 2023-2024 — FAIL (official benchmark)

### Definition and universe

The official benchmark covers unincorporated non-agricultural establishments in manufacturing, trade and selected other services. Construction, ASI-covered manufacturing, CEA-registered electricity, government/public-sector units and explicitly out-of-scope NIC activities are excluded; selected detailed financial-service codes are included. L01 status 1/2 records constitute the within-coverage interviewed universe; L02 is the delivered estimation-level file for that universe.

The pipeline has 246,336 urban enterprises and one row per enterprise. All L02 records have a valid rural/urban code, a positive final multiplier and an in-scope delivered NIC. L01 `MLT / 100` equals the L02 multiplier for every matched enterprise (maximum absolute difference 0.0000000000). Seven major joins retain the same enterprise grain; no multiplier or worker record is multiplied by join fan-out.

L01 has 537,199 records; 523,775 have within-coverage status 1/2 and flow one-to-one into L02. The other 13,424 records (status 3/4 or survey-code 3 non-surveys with blank status) carry no positive estimation weight. Survey codes 1 (original) and 2 (substitute) are both valid final survey outcomes under the supplied methodology; there is no evidence for dropping substitutes, revisit duplication, or selecting a different final-status row.

The final multiplier profile is: count 523,775; mean 147.2685568; minimum 1.0; median 73.8158; 99th percentile 1,204.875; maximum 33,805.8039. The only supplied estimation multiplier is `MLT`, and the documented `/100` decimal placement is used consistently across L01 and L02. No preliminary/design multiplier or multiplier from another level enters the enterprise base.

Workers are calculated as `sum(item 789 total workers × final multiplier)`, not as repeated weights or worker-level rows.

### Benchmark reconciliation

| Metric | Domain | Official | Released-microdata calculation | Difference | Difference % |
|---|---:|---:|---:|---:|---:|
| Establishments | India | 73,399,500 | 77,135,588.3546 | +3,736,088.3546 | +5.09% |
| Establishments | Rural | 39,747,700 | 40,254,206.3736 | +506,506.3736 | +1.27% |
| Establishments | Urban | 33,651,800 | 36,881,381.9810 | +3,229,581.9810 | +9.60% |
| Workers | India | 120,599,800 | 124,410,523.2737 | +3,810,723.2737 | +3.16% |
| Workers | Rural | 56,138,400 | 56,650,299.6765 | +511,899.6765 | +0.91% |
| Workers | Urban | 64,461,400 | 67,760,223.5972 | +3,298,823.5972 | +5.12% |

The waterfall assigns zero to pipeline universe, activity, rural/urban, multiplier-decimal and merge-duplication errors. The full residual is a **publication-versus-released-microdata final-weight/version difference**, concentrated in urban estimates. This conclusion is bounded by the supplied evidence: the report-production calibrated weights or publication estimation file were not supplied, so the residual cannot be allocated to individual records. Dropping substitutes or inventing an exclusion is not supported by the methodology and does not reconcile the benchmark.

- **Code change required:** none for the six benchmark failures. The corrected 2023 BAC classification remains in place.
- **Action:** obtain MoSPI's report-production final weights/estimation extract or an official reconciliation note for the released microdata.
- **Status:** FAIL for official benchmark QA, despite clean internal QA.

Detailed evidence: `qa/2023-2024/qa_2023_2024_universe_filter_reconciliation.csv`, `qa_2023_2024_survey_status_diagnostic.csv`, `qa_2023_2024_urban_weight_diagnostic.csv`, and `qa_2023_2024_official_benchmark_waterfall.csv`.

## 2025 — HOLD (external Maharashtra reference)

The latest rerun has **1,445** comparable Maharashtra failures. The original 1,446 count reduced to 1,445 after rebuilding with the documented L03 item-267 correction; failures were not suppressed.

The template and calculated file both identify period 2025, use the same Maharashtra/district keys, use sector codes 0/1/2 for total/rural/urban, and label the same units. Subgroups 4 and 5 do not exhibit a stable factor of 1,000 or 100,000, so a rupees/thousand-rupees/lakh rescale is not supported. The remaining differences are field-definition or source-version differences, not a single decimal-scaling error.

| Subgroup | Latest FAIL | Finding | Disposition |
|---:|---:|---|---|
| 1 Establishments | 12 | Empty Mumbai activity domains use reference zero versus calculated blank; all numeric comparable domains otherwise match. | Presentation/NA policy; no recalculation. |
| 2 Ownership | 164 | Reference components do not reconcile to its own total and conflict with official item-204 handling, especially co-operative code 8. | Reference issue; retain official mapping. |
| 3 Workers | 428 | Reference differs broadly from direct weighted item-789 totals; reference item/weight lineage is absent. | Reference definition/version issue. |
| 4 Emoluments | 416 | Actual item-267 parser defect found and corrected; remaining mismatch has no common scale and reference numerator/denominator lineage is absent. | Code corrected; reference still unresolved. |
| 5 Fixed assets | 416 | Reference magnitude is inconsistent with DDI-required item-1019 market value owned and appears to use another Block-10 column/flow. | Reference definition issue; do not rescale. |
| 6 Loans | 7 | Almost all values match; seven isolated domain differences remain. | Reference extract/version review. |
| 7 GVA | 2 | Only two isolated domains differ. | Reference BAC/raw-version review. |
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
