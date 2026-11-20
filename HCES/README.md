# HCES Multi-Year Production Pipeline

Unified VS Code pipeline for:

- NSS 68th Round Household Consumer Expenditure, Schedule 1.0 Type 2 (2011-12)
- HCES 2022-23
- HCES 2023-24

## Design

The project uses an ASUSE-style modular ETL architecture: input discovery -> year adapter -> canonical analytical household file -> common estimator -> QA -> client formatter -> export. Statistical logic is **not** forced to be identical across years.

### Survey-specific models

**2011-12** is the NSS 68th Round Schedule 1.0 Type 2 design. It does not use the FDQ/CSQ/DGQ three-visit formula. Household MPCE is taken from the survey's Block 3 MPCE field and reconciled against expenditure components. Food and cereal expenditure are reconstructed from Block 5 item values. Non-Food is the residual Total - Food at household level. `Combined_Multiplier` is the default survey weight.

**2022-23 and 2023-24** use the three-questionnaire FDQ/CSQ/DGQ framework. The adapter builds P1/P2/P3, uses the third-visit multiplier, and applies:

`TE = E1 + (E2/P2)*P1 + (E3/P3)*P1`

`MPCE = TE/P1`

Level 14 A1/B1/C1 section subtotals are used for E1/E2/E3. Missing questionnaire expenditure is never silently converted to zero.

## Input folders

Put already-unzipped raw files in:

- `input/2011-12/raw_microdata/`
- `input/2022-23/raw_microdata/`
- `input/2023-24/raw_microdata/`

Put each survey's final validated dictionary, profile and DDI in its `metadata/` folder.

Optional files:

- `input/<year>/optional/state_lookup.csv`
- `input/<year>/optional/district_lookup.csv`
- `input/<year>/optional/cpi_deflator.csv`
- `input/<year>/optional/client_template.csv`

### CPI file schema

`State_ID,Sector,Deflator`

Sector must be `rural`, `urban`, or `total`. For 2011-12, constant 2011-12 MPCE defaults to nominal MPCE because the survey period is the requested base year. For later surveys the pipeline leaves constant-price values blank unless a verified deflator file is supplied.

## Setup

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# Linux/macOS
# source .venv/bin/activate
pip install -r requirements.txt
```

## Run

One year:

```bash
python run_pipeline.py --survey 2011-12
python run_pipeline.py --survey 2022-23
python run_pipeline.py --survey 2023-24
```

All years:

```bash
python run_pipeline.py --survey all
```

Validation only:

```bash
python run_pipeline.py --survey 2022-23 --validate-only
```

## Outputs per year

- `HCES_<year>_All_India_State_District_Final.csv`
- `HCES_<year>_Household_Analytical.csv`
- `HCES_<year>_Aggregates.csv`
- `HCES_<year>_District_QC.csv`
- `HCES_<year>_Pipeline_QA.csv`
- `HCES_<year>_Run_Manifest.csv`

The client output is aggregate-only because the approved 21-column schema has no household identifier. Household-level MPCE observations are retained only in the ignored local `HCES_<year>_Household_Analytical.csv` file; they are never inserted into the client file without a lineage dimension.

## Reliability

District estimates are generated because they are required by the client. They are separately flagged by sample size. Do not imply that every district estimate is an officially published MoSPI estimate.

## Authority hierarchy

1. Raw microdata for the specific survey year
2. Official DDI / NADA Data Dictionary / survey documentation
3. Final raw-validated data dictionary and profile
4. Client template for output structure only

No year is allowed to inherit a calculation rule from another year unless the source documentation supports it.
