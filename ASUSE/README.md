# ASUSE state/district estimation pipeline

Python pipeline for processing Annual Survey of Unincorporated Sector Enterprises (ASUSE) microdata into state/district indicators with reconciliation and acceptance QA.

This repository intentionally contains **code only**. Official microdata, data dictionaries, layouts, client deliverables, generated QA files, caches, and logs are excluded from Git because they are large and may be confidential.

## Indicators

The pipeline produces eight indicators:

1. Unincorporated establishments
2. Ownership pattern
3. Workers employed
4. Annual emoluments per hired worker
5. Average fixed assets per establishment
6. Outstanding loan per establishment
7. Sector share of GVA
8. Registration status

Generated client files use a 21-column schema; the former `houseHold_ID` field has been removed.

## Local setup

Python 3.11 or newer is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create an `Input` directory locally and place the authorized year-specific raw ZIP, DDI workbook, official layouts/reports, census geography workbook, and client template there. These files must not be committed.

## Running the multiyear pipeline

By default, the command processes 2022-2023 followed by 2023-2024:

```powershell
python main.py
```

Run one round with:

```powershell
python main.py --years 2023-2024
```

The pipeline discovers year-matched inputs, validates required raw levels, builds enterprise-level estimation tables, calculates the indicators, writes step/final outputs, and produces round-specific QA and acceptance results.

## Acceptance is mandatory

Generated files are not automatically client-ready. Always inspect the year acceptance status and critical QA before delivery.

Current supplied-source limitations documented during development:

- 2022-2023 remains `HOLD` because the supplied raw package has no Level 08 / Block 7.1 and 7.2 source required for GVA.
- 2023-2024 remains `FAIL` against six official establishment/worker benchmarks even though internal arithmetic QA passes.
- 2025 remains `HOLD` against the supplied Maharashtra reference while internal QA passes.

## Repository layout

- `src/` — pipeline, parsing, mappings, calculations, and QA logic
- `scripts/` — audit and maintenance utilities
- `config/surveys.json` — year-specific public configuration
- `main.py` — multiyear command-line entry point
- `CHANGELOG*.md` — documented corrections and investigations

Folders such as `Input`, `work`, `output`, `qa`, `mapping`, and `logs` are local/generated and excluded by `.gitignore`.
