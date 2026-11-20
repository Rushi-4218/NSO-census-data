# Outputs — v5

Final files are aggregate-only 24-column CSVs. `houseHold_ID` is not present; `HH_Type` occupies that analytical dimension.

Final grain: Geography × Visit × HH_Type × Size × KPI.

Every supported cell contains all 14 KPI IDs. Missing source measures remain blank but the row is retained. See the per-year `kpi_coverage.csv` report for availability status.
