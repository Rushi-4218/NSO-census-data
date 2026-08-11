# ASUSE 2022-2023 GVA source audit

## Result

The required official Level 08 / Block 7.1 and 7.2 microdata is still absent. No GVA was calculated, copied, imputed, or substituted from a published report. Acceptance remains `HOLD`.

## Source search

- Expected official source: `asuse_2223_esu_l08.csv` or the equivalent official Level 08 rendering for ASUSE 2022-2023.
- Supplied raw ZIP inspected: `Input/Annual Survey of Unincorporated Sector Enterprises (ASUSE) of 2022-2023.zip`.
- Extracted raw folder inspected: `work/2022-2023/raw/`.
- The archive and extracted folder skip from Level 07 to Level 09.
- The workspace, supplied attachments, and Downloads were also searched; no 2022-2023 Level 08 candidate was found.
- Files belonging to ASUSE 2023-2024 and 2025 were explicitly rejected as wrong-year sources.

## Official schema required

The ASUSE 2022-2023 layout defines Level 08 as Block 7.1 and 7.2, fixed record length 56 bytes:

- bytes 1-29: enterprise identifier (FSU through sample establishment number)
- bytes 30-31: generated level code `08`
- bytes 32-34: Block 7 item number
- bytes 35-46: value in whole rupees
- bytes 47-56: final multiplier (`MLT`)

The 2022-2023 DDI identifies the canonical fields as `L08_Item_No / item_no`, `L08_Value_Rs / value_rs`, and `Multiplier`, together with the common enterprise identifiers.

## Documented GVA mapping and formula

- Block 7.1, market establishments: item 769 is gross value added, auto-calculated as item 766 total output minus item 765 total input. Negative values are explicitly permitted.
- Block 7.2, non-market establishments: item 779 is net value added, auto-calculated as item 774 total output minus item 773 total input. Negative values are explicitly permitted.
- Establishment GVA would be selected from mutually applicable item 769 or 779 and weighted using the same year's final `MLT` divided by 100.
- Aggregate sector share would be `100 × sum(establishment GVA × final weight for BAC) / sum(establishment GVA × final weight for total domain)`; it must not be an average of establishment percentages.

The detailed field mapping is in `qa/2022-2023/qa_2022_2023_gva_field_mapping.csv`.

## Join and QA status

- Main enterprise table: one row per existing 2022-2023 enterprise.
- Level 08 rows: unavailable.
- Merge: not performed because no reliable right-hand source exists.
- Every main enterprise is recorded as `LEVEL08_SOURCE_MISSING` in the two requested join diagnostics.
- Unmatched establishments: all main-table establishments, solely because Level 08 is absent.
- GVA component and share QA are `NOT_COMPUTABLE_SOURCE_MISSING`.

## Files created

- `qa/2022-2023/qa_2022_2023_gva_source_availability.csv`
- `qa/2022-2023/qa_2022_2023_level08_join_diagnostic.csv`
- `qa/2022-2023/qa_2022_2023_gva_join_diagnostic.csv`
- `qa/2022-2023/qa_2022_2023_gva_field_mapping.csv`
- `qa/2022-2023/qa_2022_2023_gva_components.csv`
- `qa/2022-2023/qa_2022_2023_gva_share.csv`

## Pipeline and client output impact

- Pipeline calculation code modified: no.
- Existing 2022-2023 GVA values modified: no; they remain blank/not computable.
- Existing non-GVA client values modified: no.
- 2023-2024 or 2025 logic/output modified: no.
- Previous acceptance: `HOLD`.
- New acceptance: `HOLD`.

## Action required

Obtain the official ASUSE 2022-2023 Level 08 / Block 7.1 and 7.2 microdata file containing the common enterprise identifiers, item number, rupee value, and final multiplier. Only then can schema validation, one-to-one join validation, establishment-level GVA calculation, weighted sector shares, and complete-year rerun proceed.
