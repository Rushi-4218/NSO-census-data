# ASUSE 2023-2024 failure trace and correction

## Original acceptance failure

The year was held by six `OFFICIAL_BENCHMARK_RECONCILIATION` rules, not by registration or GVA reconciliation:

| Metric | Area | Published benchmark | Raw-microdata estimate before BAC fix | Difference | Status |
|---|---:|---:|---:|---:|---|
| Establishments | Total | 73,399,500 | 77,135,588.3546 | +3,736,088.3546 | FAIL |
| Establishments | Rural | 39,747,700 | 40,254,206.3736 | +506,506.3736 | FAIL |
| Establishments | Urban | 33,651,800 | 36,881,381.9810 | +3,229,581.9810 | FAIL |
| Workers | Total | 120,599,800 | 124,410,523.2737 | +3,810,723.2737 | FAIL |
| Workers | Rural | 56,138,400 | 56,650,299.6765 | +511,899.6765 | FAIL |
| Workers | Urban | 64,461,400 | 67,760,223.5972 | +3,298,823.5972 | FAIL |

These differences are material and are not caused by rounding, blanks, zero denominators, duplicated QA rows, stale status, cross-year propagation, or a 2025-specific rule.

## Root cause assessment

- The six year-level failures are a conflict between estimates produced directly from the supplied 2023-2024 multiplier-bearing microdata and the configured published All-India benchmarks.
- All 523,775 L02 enterprise keys match L01 one-to-one. The supplied multiplier is numeric, positive, and used after the documented `/100` storage scaling. The official procedure does not support dropping substitute enterprises or manually changing these weights.
- No defensible source-based adjustment was found that reconciles the published totals. The benchmark failures therefore remain visible and the year remains `FAIL`.
- A separate genuine code issue was found in the sector classifier: the legacy shared rule did not implement the 2023-2024 official manufacturing exceptions.

## Code changes

- `src/multiyear_pipeline.py`
  - Added `_classify_bac_for_round` for the official 2023-2024 BAC definition.
  - Manufacturing now includes divisions 10-33 and NIC 01632, 35103, 35105, 35106, 35107, 35109, 45200, and 45403.
  - Trade remains divisions 45-47 but excludes 45200 and 45403.
  - Enhanced `_merge` with duplicate, matched, unmatched, cardinality, and row-preservation diagnostics.
  - Added unrounded QA output and rule-derived `PASS` / `WARN` / `HOLD` / `FAIL` acceptance semantics.
  - Added the named 2023-2024 detailed, failure-only, merge, metric-summary, and year-acceptance outputs.
- `src/qa/validations.py`
  - Added ratio-domain checks that distinguish legitimate zero/no-sample denominators (`NOT_CALCULABLE`) from negative-value failures.

## Previous and corrected behavior

- Previous BAC behavior: NIC 33 and the official manufacturing special codes could be classified as Other Services or Trade.
- Corrected BAC behavior: 14,273 sample enterprises, representing 1,410,212.4268 weighted UEs, were reassigned to Manufacturing under the official 2023-2024 schedule.
- Client-facing values changed: **YES**. A total of 39,107 sector-specific client cells changed across subgroups 1 and 3-8. Ownership and every `COL_DESC=Total` value were unchanged.
- Previous year status: `HOLD` (all critical conditions were collapsed into one non-pass status).
- Corrected year status: `FAIL` because sources exist but six material benchmark rules fail. Missing-source conditions are now separately classified as `HOLD`.

## Estimation and QA tests

- Establishments: `sum(weight)`.
- Workers: `sum(total_workers × weight)`.
- Annual emoluments per hired worker: `sum(annualized_emoluments × weight) / sum(hired_workers × weight)`.
- Fixed assets per UE: `sum(fixed_assets × weight) / sum(valid UE weight)`.
- Outstanding loan per UE: `sum(outstanding_loan × weight) / sum(valid UE weight)`.
- Registration: independent weighted code-1 and code-2 numerators over the weighted valid-code denominator.
- GVA shares: weighted BAC GVA divided by weighted total GVA.
- Internal QA is calculated from unrounded estimates; client rounding occurs only during export.
- All seven enterprise-level joins preserve the 523,775-row base, have zero duplicate keys on both sides, and have zero right-side unmatched keys.
- All internal establishment, ownership, worker, rural/urban, registration, and GVA reconciliation rules pass.
- Final CSV/XLSX schema and filenames are preserved.

## Final status

`2023-2024 = FAIL` pending resolution or authoritative explanation of the supplied raw-microdata versus published-benchmark conflict. No official values were copied into the microdata output and no tolerance was relaxed.

