SAS PRODUCTION PIPELINE v5 - AGGREGATE CLIENT OUTPUT

1) Put the six required source files in INPUT (the updated master dictionary is already bundled).
2) Do not extract the survey ZIP files.
3) Open this folder in VS Code.
4) Run, in order:
   .\setup.bat
   .\validate_inputs.bat
   .\smoke_test.bat
   .\run_all.bat
   .\validate_outputs.bat

IMPORTANT:
- Final CSVs contain NO household ID.
- houseHold_ID has been replaced by HH_Type.
- Final grain = Geography x Visit x HH_Type x Size x KPI.
- All India, State/All Districts and district rows are produced.
- All 14 KPI rows are retained for every supported analytical cell.
- Unsupported source measures stay blank and are reported in KPI coverage QA.
