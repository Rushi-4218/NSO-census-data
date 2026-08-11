# ASUSE QA correction changelog

## 11-Aug-2026

### Files and functions changed

- `src/io/load_raw_levels.py` — `parse_l02`: retained the original item-227 parse, added validated suffix recovery for whitespace-collapsed Block 2 records, and recorded before/after parser status. `parse_l03` now limits the accounting-period month field to its documented two bytes instead of absorbing the following item 271 digit.
- `src/metrics/estimates.py` — `calculate`: registration percentages now use the weighted universe with valid item-227 codes in both denominator and numerators; added `registration_diagnostics`.
- `src/qa/validations.py` — `write_qa`: added worker, rural/urban, standardized detailed-rule QA, 0.05-point registration/GVA tolerance, and safe floating-point handling at the documented integer-rounding bound.
- `src/multiyear_pipeline.py` — added pre-calculation L08/field validation, GVA source diagnostics, registration diagnostics, detailed benchmark rules, and rule-derived `HOLD` status.
- `src/pipeline.py` — added parser-cache versioning, GVA/source diagnostics, registration code distributions and domain diagnostics, and detailed acceptance evidence.
- `src/io/discover_inputs.py` — made the established 2025 runner select year-specific ZIP/DDI/layout/Volume I resources in the multiyear workspace.
- `src/config.py` — documented and applied the two-unit ownership reconciliation bound caused by four independently rounded components.

### Root causes and corrections

- **2022-2023 GVA:** the supplied raw ZIP has no L08 / Block 7.1 & 7.2. No value was fabricated. Subgroup 7 remains blank, the source diagnostic says `SOURCE_MISSING / NOT_COMPUTABLE`, and acceptance remains `HOLD`.
- **2023-2024 acceptance:** all internal structural and arithmetic rules pass, but the raw-microdata estimates fail six official benchmarks. Establishments differ by 3,736,088 total (506,506 rural; 3,229,582 urban), and workers differ by 3,810,723 total (511,900 rural; 3,298,824 urban). The source/publication conflict remains explicit and acceptance is `FAIL`.
- **2025 registration:** 609 records were misread as codes 3-9 because optional Block 2 blanks were collapsed by the source spreadsheet rendering. The validated suffix parser recovered 491 as Registered and 118 as Unregistered. After correction there are 299,792 code-1 records and 412,859 code-2 records, no unresolved registration records, zero registration reconciliation failures, and a maximum displayed gap of 0.00 percentage points.
- **2025 annual emoluments:** whitespace rendering concatenated the two-byte item 267 month count with item 271 (for example, `121` = 12 months plus item 271 code 1). The parser formerly treated this as 121 months. The documented two-byte parse is now applied and subgroup 4 has been recalculated.

### Tests performed

- Compiled all modified Python modules successfully.
- Ran the full 2022-2023, 2023-2024, and 2025 pipelines from the supplied raw sources/caches.
- Confirmed zero duplicate client keys for all years.
- Confirmed every final CSV equals its final XLSX on `Year + State_ID + District_ID + Sector_code + SUB_GROUP_ID + Col_ID + DATA`.
- Confirmed every final CSV equals the concatenated eight step outputs on the same fields.
- Confirmed establishment, worker, ownership, rural/urban, registration, and available-year GVA reconciliation rules pass within documented rounding tolerances.

### Current acceptance

- 2022-2023: `HOLD` — L08 / Block 7.1 & 7.2 still required.
- 2023-2024: `FAIL` — six official establishment/worker benchmark conflicts remain unresolved.
- 2025: `HOLD` — registration and item-267 parsing are corrected; 1,445 Maharashtra reference-comparison failures remain after the full rerun (the prior count was 1,446), and none were suppressed.
