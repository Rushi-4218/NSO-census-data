from __future__ import annotations

import numpy as np
import pandas as pd

from .common import ZipSurveyReader, aggregate_total_or_details, merge_activity, norm_text, numeric_col
from .geography import add_geography
from .kpi import finish_household_mart


def _read(z, visit: int, token: str, cols, nrows):
    return z.read(f"visit {visit}", token, wanted_columns=cols, nrows=nrows, extension=".xlsx")


def _build_visit(z, visit, state_map, district_map, district_full_map, cfg, row_limit, visit1_household=None):
    ident = _read(z, visit, "identification of sample household", [
        "HHID", "State", "State_District", "District_id", "Visit_no", "MLT", "Weight_SC", "Sector"
    ], row_limit)
    ident["household_id"] = ident["HHID"].map(norm_text)
    ident["visit"] = ident["Visit_no"].map(lambda x: norm_text(x, 1))
    ident["household_visit_id"] = ident["household_id"] + "-V" + ident["visit"]
    ident = ident.drop_duplicates("household_visit_id").copy()
    ident["District"] = ident["District_id"]
    ident["weight"] = numeric_col(ident, "Weight_SC")
    missing_weight = ident["weight"].isna() | ident["weight"].le(0)
    ident.loc[missing_weight, "weight"] = numeric_col(ident, "MLT")[missing_weight] / 100.0
    base = ident

    members = _read(z, visit, "block 4", ["HHID", "b4q13"], row_limit)
    members["household_id"] = members["HHID"].map(norm_text)
    # Blank member earnings mean the member did not report wage/salary earnings.
    members["wage_amount"] = numeric_col(members, "b4q13").fillna(0.0)
    mem = members.groupby("household_id", as_index=False).agg(
        member_count=("HHID", "size"),
        wage_amount=("wage_amount", "sum"),
    )
    base = base.merge(mem, on="household_id", how="left", validate="one_to_one")

    household_for_carry = visit1_household
    if visit == 1:
        hh = _read(z, 1, "block 3_household", ["HHID", "b3_q1", "b3_q11", "b3_q15"], row_limit)
        hh["household_id"] = hh["HHID"].map(norm_text)
        hh = hh.drop_duplicates("household_id").copy()
        hh["hh_size_v1"] = numeric_col(hh, "b3_q1")
        # IMPORTANT V2 FIX: 2013 Block 3 source values are already decimal hectares.
        # Do not divide by 1000 (that was the main land-size error in the old pipeline).
        hh["land_owned_ha_v1"] = numeric_col(hh, "b3_q11")
        hh["land_poss_ha_v1"] = numeric_col(hh, "b3_q15")
        household_for_carry = hh[["household_id", "hh_size_v1", "land_owned_ha_v1", "land_poss_ha_v1"]]

    if household_for_carry is not None:
        base = base.merge(household_for_carry, on="household_id", how="left", validate="one_to_one")
    else:
        base["hh_size_v1"] = np.nan
        base["land_owned_ha_v1"] = np.nan
        base["land_poss_ha_v1"] = np.nan

    if visit == 1:
        base["hh_size"] = base["hh_size_v1"].where(base["hh_size_v1"].notna(), base["member_count"])
        base["land_owned_ha"] = base["land_owned_ha_v1"]
        base["land_poss_ha"] = base["land_poss_ha_v1"]
        base["land_lineage"] = "Visit 1 Block 3; source already in hectares"
    else:
        base["hh_size"] = base["member_count"]
        if cfg.get("carry_2013_visit1_land_to_visit2", True):
            base["land_owned_ha"] = base["land_owned_ha_v1"]
            base["land_poss_ha"] = base["land_poss_ha_v1"]
            base["land_lineage"] = "Carried from Visit 1 Block 3 (configured; Visit 2 has no Block 3)"
        else:
            base["land_owned_ha"] = np.nan
            base["land_poss_ha"] = np.nan
            base["land_lineage"] = "Unavailable in Visit 2 source"

    # Each of these blocks contains detail rows plus one official total row.
    crop_out = _read(z, visit, "block 5a_value of output", ["HHID", "b5a_q1", "b5a_q18"], row_limit)
    crop_out["household_id"] = crop_out["HHID"].map(norm_text)
    crop_out_agg = aggregate_total_or_details(
        crop_out, "household_id", "b5a_q1", {"b5a_q18": "crop_output_half_year"}, [9]
    )
    base = merge_activity(base, crop_out_agg, "household_id", ["crop_output_half_year"], f"2013 visit {visit} crop output")

    crop_exp = _read(z, visit, "block 6_", ["HHID", "b6_q1", "b6_q8"], row_limit)
    crop_exp["household_id"] = crop_exp["HHID"].map(norm_text)
    crop_exp_agg = aggregate_total_or_details(
        crop_exp, "household_id", "b6_q1", {"b6_q8": "crop_expense_half_year"}, [19]
    )
    base = merge_activity(base, crop_exp_agg, "household_id", ["crop_expense_half_year"], f"2013 visit {visit} crop expense")

    animal_out = _read(z, visit, "block 7_", ["HHID", "b7_q1", "b7_q14"], row_limit)
    animal_out["household_id"] = animal_out["HHID"].map(norm_text)
    animal_out_agg = aggregate_total_or_details(
        animal_out, "household_id", "b7_q1", {"b7_q14": "animal_output_month"}, [9]
    )
    base = merge_activity(base, animal_out_agg, "household_id", ["animal_output_month"], f"2013 visit {visit} animal output")

    animal_exp = _read(z, visit, "block 8_", ["HHID", "b8_q1", "b8_q6"], row_limit)
    animal_exp["household_id"] = animal_exp["HHID"].map(norm_text)
    animal_exp_agg = aggregate_total_or_details(
        animal_exp, "household_id", "b8_q1", {"b8_q6": "animal_expense_month"}, [14]
    )
    base = merge_activity(base, animal_exp_agg, "household_id", ["animal_expense_month"], f"2013 visit {visit} animal expense")

    nonfarm = _read(z, visit, "block 9_", ["HHID", "b9_q1", "b9_q4", "b9_q5", "b9_q6"], row_limit)
    nonfarm["household_id"] = nonfarm["HHID"].map(norm_text)
    nonfarm["nonfarm_net_source"] = numeric_col(nonfarm, "b9_q6")
    fallback = numeric_col(nonfarm, "b9_q5") - numeric_col(nonfarm, "b9_q4")
    nonfarm["nonfarm_net_source"] = nonfarm["nonfarm_net_source"].where(
        nonfarm["nonfarm_net_source"].notna(), fallback
    )
    nonfarm_agg = aggregate_total_or_details(
        nonfarm, "household_id", "b9_q1", {"nonfarm_net_source": "nonfarm_net_month"}, [99]
    )
    base = merge_activity(base, nonfarm_agg, "household_id", ["nonfarm_net_month"], f"2013 visit {visit} nonfarm")

    mcfg = cfg["monthlyization"]["2013"]
    base["crop_output_month"] = base["crop_output_half_year"] / float(mcfg["crop_half_year_divisor"])
    base["net_crop_receipts_month"] = (
        base["crop_output_half_year"] - base["crop_expense_half_year"]
    ) / float(mcfg["crop_half_year_divisor"])
    base["income_wages_month"] = base["wage_amount"] / float(mcfg["member_income_divisor"])
    base["income_animals_month"] = base["animal_output_month"] - base["animal_expense_month"]
    base["income_nonfarm_month"] = base["nonfarm_net_month"]
    base["income_lease_month"] = np.nan
    base["income_pension_remit_month"] = np.nan
    base["hh_category"] = "Agricultural HH"
    base["Sector_code"] = base["Sector"].map(norm_text)
    base["Sector"] = base["Sector_code"].map({"1": "Rural", "2": "Urban"}).fillna("Rural")
    base = add_geography(
        base, state_map, district_map, district_full_map,
        district_col="District", state_district_col="State_District"
    )
    base = finish_household_mart(base, cfg, 2013)
    return base, household_for_carry


def build(v1_zip, v2_zip, cache_dir, state_map, district_map, district_full_map, cfg, row_limit=None):
    with ZipSurveyReader(v1_zip, cache_dir) as z1:
        v1, hh = _build_visit(z1, 1, state_map, district_map, district_full_map, cfg, row_limit, None)
    with ZipSurveyReader(v2_zip, cache_dir) as z2:
        v2, _ = _build_visit(z2, 2, state_map, district_map, district_full_map, cfg, row_limit, hh)
    return pd.concat([v1, v2], ignore_index=True)
