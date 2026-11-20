# Changelog

## 3.0.0
- Expanded from 2023-24-only to 2011-12 + 2022-23 + 2023-24.
- Added survey registry and per-year adapters.
- Added legacy NSS 68 Schedule 1.0 Type 2 calculation path.
- Retained corrected canonical-key / missing-expenditure / third-visit logic for recent HCES.
- Commonized All India / State / District and Rural / Urban / Total aggregation.
- Commonized nominal MPCE, constant-price MPCE, Food/Non-Food shares, cereal share, weighted Gini, QA and client formatter.
- 2011-12 constant-price subgroup uses nominal values by default because 2011-12 is the requested base year.
- Later-year constant-price values require a verified CPI deflator input.
