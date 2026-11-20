# Changelog

## 6.0.0
- Fixed SAS 2019 District_ID-present / District_Name-blank issue.
- Extended the bundled master dictionary State_District lookup with 42 district codes observed in the 2019 output that previously lacked names.
- Added `2019_District_Name_Fixes` audit sheet to the master dictionary.
- Final output QA now requires every non-zero District_ID to have a District_Name.
- 2019 household-mart QA treats unmapped district rows as a failure.
- No change to aggregate-only output grain; household IDs remain excluded from client outputs.

# Changelog

## v5.0.0

- Removed household-level rows from all final client CSVs.
- Replaced `houseHold_ID` with `HH_Type` in the corrected 24-column schema.
- Main final output is now `Geography × Visit × HH_Type × Size × KPI`.
- Added `Agricultural HH`, `Non-Agricultural HH` when supported, and `All HH` aggregation.
- Created a complete size/KPI grid so required datapoint rows do not disappear when a cell has zero sampled households.
- For empty size cells, `HH_SHARE=0`; mean/ratio KPIs stay blank.
- Removed `Unknown` as a client-facing size category while retaining unknown-size households in `All sizes`.
- Added KPI coverage status: AVAILABLE / PARTIAL_SOURCE_COVERAGE / UNAVAILABLE_IN_SOURCE.
- Kept All India, state `All Districts`, and district geography logic from v4.
- Kept `State_District` sheet as the sole runtime geography lookup authority.
- Kept publication-date and exact unit locks.
- Kept cached household-visit marts for fast reruns.
