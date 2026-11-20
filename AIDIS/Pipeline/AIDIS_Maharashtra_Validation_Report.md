# AIDIS Maharashtra Delivery Validation

- State filter: State_ID = 27 (Maharashtra)
- Output rows: 26,013
- Output columns: 23
- District codes represented: 34
- District codes missing from supplied mapping: []
- Supplied district codes absent from data: []
- Visit IDs: [1, 2]
- KPI/Col_ID count: 114
- Null DATA values: 0
- Duplicate output keys: 0
- Non-Maharashtra rows: 0
- CSV and Excel were generated from the same filtered row stream.

Known limitations carried from the national delivery:

- No material KPI omission remains; FCE/EPL use the official annual Visit-1 + Visit-2 tabulation rule.
- Maharashtra district names were decoded using the user-supplied 34-code mapping; `0000` remains `All Districts` for aggregate rows.
