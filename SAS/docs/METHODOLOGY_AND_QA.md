# Methodology and QA — v5

The authoritative computational grain remains household-visit internally. Repeated child records are aggregated before joining so household measures are never multiplied by many-to-many joins.

Final delivery is aggregate only. State estimates are calculated from underlying weighted households, not from averages of district estimates. All India is calculated from underlying weighted households, not from averages of states.

The output grid is complete across supported HH types, two visits, seven required size categories and fourteen KPI IDs. Unsupported variables are retained as blank values and explicitly reported; the pipeline does not invent values.

`Unknown` land size is a QA condition, not a client category. Such records contribute to `All sizes` but are excluded from the six explicit size bands.
