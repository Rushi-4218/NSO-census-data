# Pipeline flow — v5

Raw survey blocks
→ household / household-visit spine
→ aggregate repeated member/crop/animal/non-farm blocks to household-visit
→ derive KPI components
→ apply survey weights
→ aggregate directly from households to All India / State / District
→ expand Visit × HH_Type × required Size grid
→ calculate 14 KPIs
→ remove household identifiers from delivery
→ write corrected 24-column client CSV
→ run geography, unit, publication, key-uniqueness and KPI-coverage QA.
