# Configuration guide v4

Main configuration: `config/pipeline_config.json`.

Important locks:

- `pipeline_version`: `4.0.0`
- `expected_household_visits`: full production household/visit counts
- `years.<year>.published_date`: client publication date
- `monthlyization`: round-specific conversion logic
- `geography.authority`: master dictionary `State_District` sheet
- `final_geography_contract`: All India / state-total / district output convention
- `write_weighted_summary`: enabled by default
- `reuse_cached_household_mart`: enables fast reruns

Do not modify expected household counts just to make an incomplete output pass validation.
