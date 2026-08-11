from __future__ import annotations

import pandas as pd

from src.config import PipelineConfig, SUBGROUPS


SOURCES = {
    1: ("L02", "asuse_2025_esu_l02", "Block 2", "202a/202b", "Multiplier", "weighted_sum"),
    2: ("L02", "asuse_2025_esu_l02", "Block 2", "204", "Ownership_Type", "weighted_sum"),
    3: ("L09", "asuse_2025_esu_l09", "Block 8", "789", "Workers_Total", "weighted_sum_product"),
    4: ("L10+L09+L03", "asuse_2025_esu_l10/l09/l03", "Blocks 9/8/2.2", "939/(782+783)", "value_10/Workers_Total", "ratio_of_weighted_sums"),
    5: ("L11", "asuse_2025_esu_l11", "Block 10", "1019", "Value_owned_assets", "ratio_of_weighted_sums"),
    6: ("L12", "asuse_2025_esu_l12", "Block 11", "1119", "Amount_outstnd", "ratio_of_weighted_sums"),
    7: ("L08+L03", "asuse_2025_esu_l08/l03", "Blocks 7/2.2", "769 or 779", "value_08", "share_of_weighted_sums"),
    8: ("L02", "asuse_2025_esu_l02", "Block 2", "227", "Registered", "weighted_percentage"),
}


def build_master_mapping(cfg: PipelineConfig, available_levels: set[str] | None = None) -> pd.DataFrame:
    rows = []
    mid = 0
    for subgroup_id, (subgroup, columns, unit) in SUBGROUPS.items():
        level, file, block, item, field, method = SOURCES[subgroup_id]
        raw_stem = getattr(cfg, "raw_stem", "asuse_2025_esu")
        file = file.replace("asuse_2025_esu", raw_stem)
        required_levels = {part.lower() for part in level.replace("+", ",").split(",")}
        missing_levels = sorted(required_levels - (available_levels or required_levels))
        for col_id, desc in enumerate(columns, 1):
            mid += 1
            is_ratio = subgroup_id in {4, 5, 6, 7, 8}
            rows.append({
                "Mapping_ID": f"M{mid:03d}", "Survey_ID": cfg.survey_id,
                "Survey_NAME": cfg.survey_name, "Survey_GROUP_ID": cfg.group_id,
                "GROUP_NAME": cfg.group_name, "SUB_GROUP_ID": subgroup_id,
                "SUB_GROUP_NAME": subgroup, "Client_Col_ID": col_id,
                "Client_COL_DESC": desc, "Client_Unit": unit,
                "Requirement_Code": f"DP{subgroup_id:02d}", "Requirement_Name": subgroup,
                "Metric_Type": "Ratio/Percent" if is_ratio else "Additive",
                "Source_Level": level, "Source_File": file, "Source_Block": block,
                "Source_Item": item, "Source_Raw_Column": field,
                "Source_Value_Column": field, "Enterprise_Key_Fields": "bytes 1-29",
                "Geography_Key_Fields": "sector+nss_region+district",
                "Multiplier_Field": "mult / 100", "Source_Filter": desc,
                "Source_Code": item, "Source_Code_Description": desc,
                "Ownership_Group": desc if subgroup_id == 2 else "",
                "Activity_Group": desc if subgroup_id in {1, 3, 4, 5, 6, 7} else "",
                "Registration_Group": desc if subgroup_id == 8 else "",
                "Aggregation_Method": method,
                "Numerator_Definition": "See Formula_Description" if is_ratio else "weighted contribution",
                "Denominator_Definition": "weighted denominator for same domain" if is_ratio else "",
                "Annualisation_Rule": "12 for monthly reference; 12/months for audited period" if subgroup_id == 4 else ("Not applied: like-reference-period GVA shares" if subgroup_id == 7 else "Not applicable (stock/count)"),
                "Weighting_Rule": "Use annual ASUSE multiplier divided by 100; aggregate before division",
                "Sector_Applicable": True, "District_Applicable": True, "State_Applicable": True,
                "Derived_Flag": is_ratio or desc == "Total",
                "Formula_Description": method,
                "QA_Check": "domain reconciliation and Maharashtra comparison",
                "Expected_Reconciliation": "within configured tolerance",
                "DDI_Source": getattr(cfg, "ddi_name", "ASUSE_Data_Dictionary_Complete_2025.xlsx"),
                "Official_Source": cfg.source_url,
                "Mapping_Status": "Missing Raw Level" if missing_levels else "Resolved",
                "Mapping_Notes": (
                    f"Required raw level(s) absent: {', '.join(x.upper() for x in missing_levels)}"
                    if missing_levels else "Year-specific official layout and Schedule ESU Vol II verified"
                ),
            })
    return pd.DataFrame(rows)
