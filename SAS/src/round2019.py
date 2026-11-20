from __future__ import annotations

import numpy as np
import pandas as pd

from .common import ZipSurveyReader, aggregate_total_or_details, merge_activity, merge_one_to_one, norm_text, numeric_col
from .geography import add_geography
from .kpi import finish_household_mart


def _read(z, visit: int, tokens, cols, nrows, exclude=()):
    if isinstance(tokens, str):
        tokens = [tokens]
    return z.read(*tokens, wanted_columns=cols, nrows=nrows, extension=".csv", exclude=exclude)


def _id_token(visit):
    return [f"visit{visit}", "level - 01"]


def _member_token(visit):
    return [f"visit{visit}", "level - 02"]


def _land_token(visit):
    return [f"visit{visit}", "level - 04"]


def _sss_consistency(sss: pd.Series, land_ha: pd.Series) -> pd.Series:
    s = sss.map(norm_text)
    x = pd.to_numeric(land_ha, errors="coerce")
    out = pd.Series("NOT_APPLICABLE", index=sss.index, dtype=object)
    known = x.notna() & s.isin(["2", "3", "4", "5"])
    ok = (
        (s.eq("2") & x.lt(0.25)) |
        (s.eq("3") & x.ge(0.25) & x.lt(1.0)) |
        (s.eq("4") & x.ge(1.0) & x.lt(2.0)) |
        (s.eq("5") & x.ge(2.0))
    )
    out.loc[known & ok] = "PASS"
    out.loc[known & ~ok] = "REVIEW"
    out.loc[s.isin(["2", "3", "4", "5"]) & x.isna()] = "LAND_MISSING"
    return out


def build(raw_zip, cache_dir, state_map, district_map, district_full_map, cfg, row_limit=None):
    frames = []
    with ZipSurveyReader(raw_zip, cache_dir) as z:
        for visit in (1, 2):
            ident = _read(
                z, visit, _id_token(visit),
                ["HHID", "State", "State_District", "District", "SSS", "visitNo", "MLT", "Sector"],
                row_limit,
            )
            ident["household_id"] = ident["HHID"].map(norm_text)
            ident["visit"] = ident["visitNo"].map(lambda x: norm_text(x, 1))
            ident["household_visit_id"] = ident["household_id"] + "-V" + ident["visit"]
            ident = ident.drop_duplicates("household_visit_id").copy()
            ident["weight"] = numeric_col(ident, "MLT") / 100.0
            base = ident

            # 2019 Block 3 member-level income amounts. Blank amount cells mean no amount
            # for that member and are therefore treated as structural zero before HH aggregation.
            members = _read(z, visit, _member_token(visit), ["HHID", "b3q12", "b3q13", "b3q14"], row_limit)
            members["household_id"] = members["HHID"].map(norm_text)
            for c in ["b3q12", "b3q13", "b3q14"]:
                members[c] = numeric_col(members, c).fillna(0.0)
            mi = members.groupby("household_id", as_index=False).agg(
                member_count=("HHID", "size"),
                wages_amount=("b3q12", "sum"),
                pension_remit_amount=("b3q13", "sum"),
                lease_amount=("b3q14", "sum"),
            )
            base = base.merge(mi, on="household_id", how="left", validate="one_to_one")

            if visit == 1:
                hh = _read(z, visit, ["visit1", "level - 03"], ["HHID", "b4q1"], row_limit)
                hh["household_id"] = hh["HHID"].map(norm_text)
                hh["hh_size"] = numeric_col(hh, "b4q1")
                hh = hh[["household_id", "hh_size"]].drop_duplicates("household_id")
                base = merge_one_to_one(base, hh, "household_id", "2019 visit 1 household size")
                base["hh_size"] = base["hh_size"].where(base["hh_size"].notna(), base["member_count"])
            else:
                base["hh_size"] = base["member_count"]

            # Schedule 33.1 Block 5 areas are recorded in acres. The serial-row composition
            # is controlled in pipeline_config.json and converted with the exact acre->ha factor.
            land = _read(z, visit, _land_token(visit), ["HHID", "b5q1", "b5q3"], row_limit)
            land["household_id"] = land["HHID"].map(norm_text)
            land["serial"] = pd.to_numeric(land["b5q1"], errors="coerce")
            land["area_acre"] = numeric_col(land, "b5q3")
            lcfg = cfg.get("land_2019", {})
            poss_rows = [float(x) for x in lcfg.get("possessed_positive_serial_rows", lcfg.get("possessed_serial_rows", []))]
            leased_out_rows = [float(x) for x in lcfg.get("leased_out_serial_rows", [5])]
            owned_rows = [float(x) for x in lcfg.get("owned_serial_rows", [])]
            acre_to_ha = float(lcfg.get("acre_to_hectare", 0.40468564224))

            if poss_rows:
                pos = land[land["serial"].isin(poss_rows)].groupby("household_id", as_index=False)["area_acre"].sum(min_count=1).rename(columns={"area_acre": "positive_acre"})
                if leased_out_rows:
                    neg = land[land["serial"].isin(leased_out_rows)].groupby("household_id", as_index=False)["area_acre"].sum(min_count=1).rename(columns={"area_acre": "leased_out_acre"})
                    lp = pos.merge(neg, on="household_id", how="outer")
                    lp["positive_acre"] = lp["positive_acre"].fillna(0.0)
                    lp["leased_out_acre"] = lp["leased_out_acre"].fillna(0.0)
                    lp["land_poss_ha"] = (lp["positive_acre"] - lp["leased_out_acre"]) * acre_to_ha
                else:
                    lp = pos
                    lp["land_poss_ha"] = lp["positive_acre"] * acre_to_ha
                lp = lp[["household_id", "land_poss_ha"]]
                base = merge_one_to_one(base, lp, "household_id", f"2019 visit {visit} land possessed")
            else:
                base["land_poss_ha"] = np.nan

            if owned_rows:
                lo = land[land["serial"].isin(owned_rows)].groupby("household_id", as_index=False)["area_acre"].sum(min_count=1)
                lo["land_owned_ha"] = lo["area_acre"] * acre_to_ha
                lo = lo[["household_id", "land_owned_ha"]]
                base = merge_one_to_one(base, lo, "household_id", f"2019 visit {visit} land owned")
            else:
                base["land_owned_ha"] = np.nan

            # Block 6 output: Level 07 has b6q22 and serial 9 is official total.
            crop_out = _read(
                z, visit, [f"visit {visit}", "level 07", "block 6"],
                ["HHID", "b6q1", "b6q22"], row_limit,
            )
            crop_out["household_id"] = crop_out["HHID"].map(norm_text)
            crop_out_agg = aggregate_total_or_details(
                crop_out, "household_id", "b6q1", {"b6q22": "crop_output_half_year"}, [9]
            )
            base = merge_activity(base, crop_out_agg, "household_id", ["crop_output_half_year"], f"2019 visit {visit} crop output")

            # Block 7 crop expenses: serial 22 is total. Paid-out + approved imputed expense
            # are combined only after selecting the total row, preventing detail+total duplication.
            crop_exp = _read(
                z, visit, [f"visit {visit}", "level 8", "block 7"],
                ["HHID", "b7q1", "b7q7", "b7q8"], row_limit,
            )
            crop_exp["household_id"] = crop_exp["HHID"].map(norm_text)
            crop_exp["crop_expense_source"] = numeric_col(crop_exp, "b7q7")
            if cfg.get("include_imputed_crop_expense_2019", True):
                crop_exp["crop_expense_source"] = crop_exp["crop_expense_source"].fillna(0.0) + numeric_col(crop_exp, "b7q8").fillna(0.0)
            crop_exp_agg = aggregate_total_or_details(
                crop_exp, "household_id", "b7q1", {"crop_expense_source": "crop_expense_half_year"}, [22]
            )
            base = merge_activity(base, crop_exp_agg, "household_id", ["crop_expense_half_year"], f"2019 visit {visit} crop expense")

            animal_out = _read(
                z, visit, [f"visit {visit}", "level 11", "block 9"],
                ["HHID", "b9q1", "b9q14"], row_limit,
            )
            animal_out["household_id"] = animal_out["HHID"].map(norm_text)
            animal_out_agg = aggregate_total_or_details(
                animal_out, "household_id", "b9q1", {"b9q14": "animal_output_month"}, [16]
            )
            base = merge_activity(base, animal_out_agg, "household_id", ["animal_output_month"], f"2019 visit {visit} animal output")

            animal_exp = _read(
                z, visit, [f"visit {visit}", "level 12", "block 10"],
                ["HHID", "b10q1", "b10q5", "b10q6"], row_limit,
            )
            animal_exp["household_id"] = animal_exp["HHID"].map(norm_text)
            animal_exp["animal_expense_source"] = numeric_col(animal_exp, "b10q5")
            if cfg.get("include_imputed_animal_expense_2019", True):
                animal_exp["animal_expense_source"] = animal_exp["animal_expense_source"].fillna(0.0) + numeric_col(animal_exp, "b10q6").fillna(0.0)
            animal_exp_agg = aggregate_total_or_details(
                animal_exp, "household_id", "b10q1", {"animal_expense_source": "animal_expense_month"}, [18]
            )
            base = merge_activity(base, animal_exp_agg, "household_id", ["animal_expense_month"], f"2019 visit {visit} animal expense")

            nf = _read(
                z, visit, [f"visit {visit}", "level 13", "block 11"],
                ["HHID", "b11q1", "b11q4", "b11q5", "b11q6"], row_limit,
            )
            nf["household_id"] = nf["HHID"].map(norm_text)
            nf["nonfarm_net_source"] = numeric_col(nf, "b11q6")
            fallback = numeric_col(nf, "b11q5") - numeric_col(nf, "b11q4")
            nf["nonfarm_net_source"] = nf["nonfarm_net_source"].where(nf["nonfarm_net_source"].notna(), fallback)
            nf_agg = aggregate_total_or_details(
                nf, "household_id", "b11q1", {"nonfarm_net_source": "nonfarm_net_month"}, [99]
            )
            base = merge_activity(base, nf_agg, "household_id", ["nonfarm_net_month"], f"2019 visit {visit} nonfarm")

            mcfg = cfg["monthlyization"]["2019"]
            base["crop_output_month"] = base["crop_output_half_year"] / float(mcfg["crop_half_year_divisor"])
            base["net_crop_receipts_month"] = (
                base["crop_output_half_year"] - base["crop_expense_half_year"]
            ) / float(mcfg["crop_half_year_divisor"])
            base["income_wages_month"] = base["wages_amount"] / float(mcfg["member_income_divisor"])
            base["income_pension_remit_month"] = base["pension_remit_amount"] / float(mcfg["member_income_divisor"])
            base["income_lease_month"] = base["lease_amount"] / float(mcfg["member_income_divisor"])
            base["income_animals_month"] = base["animal_output_month"] - base["animal_expense_month"]
            base["income_nonfarm_month"] = base["nonfarm_net_month"]

            sss = base["SSS"].map(norm_text)
            base["hh_category"] = np.select(
                [sss.eq("1"), sss.isin(["2", "3", "4", "5"])],
                ["Non-Agricultural HH", "Agricultural HH"],
                default="Unknown HH Type",
            )
            base["Sector_code"] = base["Sector"].map(norm_text)
            base["Sector"] = base["Sector_code"].map({"1": "Rural", "2": "Urban"}).fillna("Rural")
            base = add_geography(base, state_map, district_map, district_full_map)
            base = finish_household_mart(base, cfg, 2019)
            base["land_lineage"] = (
                "2019 Block 5: owned&possessed(1,6) + leased-in(2,3,7,8) + otherwise(4,9) - leased-out(5); acres to hectares"
                if poss_rows else "2019 land mapping unavailable"
            )
            base["sss_land_consistency"] = _sss_consistency(base["SSS"], base["land_poss_ha"])
            frames.append(base)

    return pd.concat(frames, ignore_index=True)
