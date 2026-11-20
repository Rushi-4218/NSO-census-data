# AIDIS 77th Round - Final Validation Report

## Delivery status

- Final CSV and true XLSX generated with identical 535,537 rows and 23 columns.
- Extraction date: 07-Aug-2026; publication date: 10-Sep-2021; source: https://microdata.gov.in/NADA/index.php/catalog/156

## Raw/DDI validation

- Raw workbooks found/used: 23 / 23
- DDI variable rows checked: 656
- DDI KPI mappings checked: 40
- Missing DDI columns in corresponding raw file: 0 []
- Raw columns not represented in corresponding DDI level: 0 []
- DDI Mapping_Status: {'Mapped': 646, 'Needs Review': 10}
- Block 14 conflict: resolved against official catalog. b14q2=item serial, b14q4=purchase, b14q8=total expenditure, b14q14=net addition.

## Analytical master

- Visit 1 households: 116,461
- Visit 2 households: 113,072
- Total household-visit records: 229,533
- Visit 1 unique panel keys: 116,461
- Visit 2 unique panel keys: 113,072
- Visit 2 records linked to Visit 1 classification: 113,072 / 113,072
- States: 36
- Official composite State-District codes: 682
- Rural household-visit records: 137,746
- Urban household-visit records: 91,787

## Final-file QA

- Output rows: 535,537
- Output columns: 23
- KPI/Col_ID count: 114
- Null DATA values: 0
- Duplicate final-row keys: 0
- Percent values outside 0-100: 0
- Gini values outside 0-1: 0
- CSV/XLSX cross-format comparison is performed after generation.

## Assumptions and unresolved metadata

- The supplied DDI does not contain a State-wise district-name directory. District_ID uses the official State_District composite code; District_Name is therefore a transparent `District code NN` label, not a fabricated place name.
- Rural b4q4=1 is classified as Cultivator HH; other rural types as Non-Cultivator HH. Urban b4q4=1 is Self-employed; other urban types are Others, following the supplied sector-specific code list.
- `Others` asset component follows official Report 588: livestock, transport equipment, agricultural machinery, non-farm business equipment and shares.
- Credit distributions are amount shares (%) within the relevant institutional/non-institutional denominator.
- Visit-2 assets were not recollected. No Visit-2 AVA/component rows are emitted; Visit-2 DAR uses the correctly panel-linked Visit-1 asset stock.
- Annual FCE/EPL combine both half-year visits by panel household and use Visit-2 weights. FCE excludes land purchase (Block 14 col.4, items 1/4/5/17); EPL is that excluded purchase amount. All-India FCE reconciles to official rounded benchmarks (Rural Rs.8,966; Urban Rs.10,863).
