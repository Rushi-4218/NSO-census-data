# SAS Production Pipeline v6 — Aggregate Client Output

This version implements the client-requested final grain. **No household ID is emitted in final CSVs.** Household identifiers are used only internally to aggregate source blocks safely.

## Final analytical grain

`Geography × Visit × HH_Type × Land Size × KPI`

Geography is produced at three levels:

- All India: `State_ID=0`, `State_Name=India`, `District_ID=0`, `District_Name=All Districts`
- State total: actual state + `District_ID=0`, `District_Name=All Districts`
- District: actual state/district codes and names from `SAS_Master_Complete_Data_Dictionary.xlsx -> State_District`

The corrected 24-column client schema replaces the old `houseHold_ID` column with `HH_Type`.

## Required output dimensions

Visits: `1`, `2`

Household categories:

- `Agricultural HH`
- `Non-Agricultural HH` where the source round supports it (2019)
- `All HH`

Land-size classes:

- `All sizes`
- `<0.01 ha`
- `0.01 - 0.4 ha`
- `0.4 - 1 ha`
- `1-2 ha`
- `2-4 ha`
- `4-10 ha`

The pipeline emits every required KPI row for every supported geography/visit/HH-type/size cell. If no sampled households exist in a size cell, `HH_SHARE=0` and average/ratio measures remain blank. `Unknown` is not emitted as a client size category; unknown-size households still contribute to `All sizes` and are visible in QA.

## 14 client KPIs

`HH_SHARE`, `HH_SIZE`, `LAND_OWNED_HA`, `LAND_POSS_HA`, `NET_CROP_RCPT`, `INC_WAGES`, `INC_LEASE`, `INC_ANIMALS`, `INC_NONFARM`, `INC_PENSION_REMIT`, `MONTHLY_INCOME`, `OUTPUT_PER_HH`, `OUTPUT_PER_CAPITA`, `OUTPUT_PER_HA`.

Unsupported source measures are not invented. Their rows remain present with blank `DATA`, and `reports/SAS_<year>_kpi_coverage.csv` marks coverage as `AVAILABLE`, `PARTIAL_SOURCE_COVERAGE`, or `UNAVAILABLE_IN_SOURCE`.

## INPUT folder

Put these six files in `INPUT`:

1. `SAS_Master_Complete_Data_Dictionary.xlsx`
2. `Situation Assessment Survey of Farmers, 2003.zip`
3. `Situation Assessment Survey of Agricultural Households, January - December 2013.zip`
4. `Situation Assessment survey of Agricultural households, NSS 70th Round  Jan - Dec 2013  Visit 2.zip`
5. `Land and Livestock Holding of Households and Situation Assessment of Agricultural Households)-JANUARY 2019 – DECEMBER 2019-Visit 1.zip`
6. `SAS_Maharashtra.csv`

Do not extract the ZIP files manually.

## Run in VS Code / PowerShell

```powershell
.\setup.bat
.\validate_inputs.bat
.\smoke_test.bat
.\run_all.bat
.\validate_outputs.bat
```

`smoke_test.bat` writes only to isolated smoke folders. `run_all.bat` creates the real production outputs.

## Final outputs

- `outputs/SAS_2003_All_India_State_District_Final.csv`
- `outputs/SAS_2013_All_India_State_District_Final.csv`
- `outputs/SAS_2019_All_India_State_District_Final.csv`

These files contain **aggregate rows only**.

## Fast reruns

After one successful production build, household-visit KPI marts are cached in `work/marts`.

- Use `run_final_only.bat` after formatting/output-grid changes.
- Use `rebuild_all.bat` after raw source, dictionary, geography, or methodology changes.

## Publication dates

- 2003: `01-Dec-05`
- 2013: `19-Dec-14`
- 2019: `10-Sep-21`


## v6 district-name completeness fix

The v6 build fixes the SAS 2019 case where District_ID was populated but District_Name was blank.
The bundled master dictionary `State_District` sheet now includes the previously missing 2019 district codes.
Production QA now fails if any final non-zero District_ID has a blank District_Name.
The aggregation grain remains Geography x Visit x HH_Type x Size x KPI; household-level rows are not emitted.
