from __future__ import annotations

import numpy as np
import pandas as pd

from .common import (
    ZipSurveyReader,
    aggregate_total_or_details,
    merge_activity,
    norm_text,
    numeric_col,
)
from .geography import add_geography
from .kpi import finish_household_mart

KEY_COLS = ["FSU", "HAMLET_NO", "SSS", "SMPHH_NO"]


def _household_key(df: pd.DataFrame) -> pd.Series:
    return (
        df["FSU"].map(lambda x: norm_text(x, 5)) + "-" +
        df["HAMLET_NO"].map(lambda x: norm_text(x, 1)) + "-" +
        df["SSS"].map(lambda x: norm_text(x, 1)) + "-" +
        df["SMPHH_NO"].map(lambda x: norm_text(x, 2))
    )


def _add_keys(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["household_id"] = _household_key(out)
    out["visit"] = out["VISIT_NO"].map(lambda x: norm_text(x, 1))
    out["household_visit_id"] = out["household_id"] + "-V" + out["visit"]
    return out


def _read(reader, token, cols, nrows):
    return reader.read(token, wanted_columns=cols, nrows=nrows, extension=".xlsx")


def _serial_total(
    df: pd.DataFrame,
    key: str,
    serial_col: str,
    value_col: str,
    output_col: str,
    total_serial: int,
    detail_min: int | None = None,
    detail_max: int | None = None,
) -> pd.DataFrame:
    x = df.copy()
    serial = pd.to_numeric(x[serial_col], errors="coerce")
    keep = serial.eq(total_serial)
    if detail_min is not None:
        keep |= serial.ge(detail_min)
    if detail_max is not None:
        keep &= serial.le(max(total_serial, detail_max))
    x = x[keep].copy()
    return aggregate_total_or_details(
        x,
        key=key,
        serial_col=serial_col,
        value_map={value_col: output_col},
        total_values=[total_serial],
    )


def build(raw_zip, cache_dir, state_map, district_map, district_full_map, cfg, row_limit=None):
    with ZipSurveyReader(raw_zip, cache_dir) as z:
        base = _read(z, "bk_1_2", [
            *KEY_COLS, "VISIT_NO", "SECTOR", "DISTT", "state_cd",
            "NSS_CNT", "NSC_CNT", "MULT", "HHWGT"
        ], row_limit)
        base = _add_keys(base).drop_duplicates("household_visit_id").copy()
        base["State"] = base["state_cd"]
        base["District"] = base["DISTT"]
        base["State_District"] = [
            norm_text(s, 2) + norm_text(d, 2) for s, d in zip(base["State"], base["District"])
        ]

        reported = numeric_col(base, "HHWGT")
        formula = np.where(
            numeric_col(base, "NSC_CNT") > numeric_col(base, "NSS_CNT"),
            numeric_col(base, "MULT") / 200.0,
            numeric_col(base, "MULT") / 100.0,
        )
        base["weight"] = reported.where(reported.notna() & (reported > 0), formula)
        base["weight_formula_recalc"] = formula
        base["weight_abs_diff"] = (base["weight"] - base["weight_formula_recalc"]).abs()

        # Block 3 values are implied 0.000 hectares in the 2003 layout.
        hh = _read(z, "bk_3", [*KEY_COLS, "VISIT_NO", "B3_C1", "B3_C8", "B3_C12"], row_limit)
        hh["household_id"] = _household_key(hh)
        hhm = hh.groupby("household_id", as_index=False).agg(
            hh_size=("B3_C1", "first"),
            land_owned_raw=("B3_C8", "first"),
            land_poss_raw=("B3_C12", "first"),
        )
        hhm["hh_size"] = pd.to_numeric(hhm["hh_size"], errors="coerce")
        hhm["land_owned_ha"] = pd.to_numeric(hhm["land_owned_raw"], errors="coerce") / 1000.0
        hhm["land_poss_ha"] = pd.to_numeric(hhm["land_poss_raw"], errors="coerce") / 1000.0
        base = base.merge(
            hhm[["household_id", "hh_size", "land_owned_ha", "land_poss_ha"]],
            on="household_id", how="left", validate="many_to_one"
        )

        # Member wage fields are blank for members with no wage income; within an observed
        # member table those blanks are structural zeroes, not missing households.
        mem = _read(z, "bk_4", [*KEY_COLS, "VISIT_NO", "B4_C17"], row_limit)
        mem = _add_keys(mem)
        mem["wages_weekly"] = numeric_col(mem, "B4_C17").fillna(0.0)
        wages = mem.groupby("household_visit_id", as_index=False)["wages_weekly"].sum(min_count=1)
        base = merge_activity(base, wages, "household_visit_id", ["wages_weekly"], "2003 wages", zero_if_absent=False)

        # Block 14 has crop detail rows plus official serial 99 total. Never sum both.
        crop = _read(z, "bk_14_c12_20", [
            *KEY_COLS, "VISIT_NO", "B14_C1", "B14_C14", "B14_C20"
        ], row_limit)
        crop = _add_keys(crop)
        crop_agg = aggregate_total_or_details(
            crop,
            key="household_visit_id",
            serial_col="B14_C1",
            value_map={"B14_C14": "crop_expense_6m", "B14_C20": "crop_receipts_6m"},
            total_values=[99],
        )
        base = merge_activity(
            base, crop_agg, "household_visit_id",
            ["crop_expense_6m", "crop_receipts_6m"], "2003 crop", zero_if_absent=True
        )

        # Block 15: total expense row=9; total output/receipts row=25.
        animal = _read(z, "bk_15", [*KEY_COLS, "VISIT_NO", "B15_C1", "B15_C11"], row_limit)
        animal = _add_keys(animal)
        serial = pd.to_numeric(animal["B15_C1"], errors="coerce")
        aexp = aggregate_total_or_details(
            animal[serial.between(1, 9, inclusive="both")], "household_visit_id", "B15_C1",
            {"B15_C11": "animal_expense_month"}, [9]
        )
        aout = aggregate_total_or_details(
            animal[serial.between(10, 25, inclusive="both")], "household_visit_id", "B15_C1",
            {"B15_C11": "animal_output_month"}, [25]
        )
        base = merge_activity(base, aexp, "household_visit_id", ["animal_expense_month"], "2003 animal expense")
        base = merge_activity(base, aout, "household_visit_id", ["animal_output_month"], "2003 animal output")

        # Blocks 16/17 have explicit total rows 21 and 14 respectively.
        nfexp = _read(z, "bk_16", [*KEY_COLS, "VISIT_NO", "B16_C1", "B16_C3"], row_limit)
        nfexp = _add_keys(nfexp)
        nfexp_agg = aggregate_total_or_details(
            nfexp, "household_visit_id", "B16_C1", {"B16_C3": "nonfarm_expense_month"}, [21]
        )
        base = merge_activity(base, nfexp_agg, "household_visit_id", ["nonfarm_expense_month"], "2003 nonfarm expense")

        nfrec = _read(z, "bk_17", [*KEY_COLS, "VISIT_NO", "B17_C1", "B17_C3"], row_limit)
        nfrec = _add_keys(nfrec)
        nfrec_agg = aggregate_total_or_details(
            nfrec, "household_visit_id", "B17_C1", {"B17_C3": "nonfarm_receipts_month"}, [14]
        )
        base = merge_activity(base, nfrec_agg, "household_visit_id", ["nonfarm_receipts_month"], "2003 nonfarm receipts")

    mcfg = cfg["monthlyization"]["2003"]
    base["crop_output_month"] = base["crop_receipts_6m"] / float(mcfg["crop_half_year_divisor"])
    base["net_crop_receipts_month"] = (
        base["crop_receipts_6m"] - base["crop_expense_6m"]
    ) / float(mcfg["crop_half_year_divisor"])
    base["income_wages_month"] = base["wages_weekly"] * float(mcfg["wages_7day_to_month_factor"])
    base["income_animals_month"] = base["animal_output_month"] - base["animal_expense_month"]
    base["income_nonfarm_month"] = base["nonfarm_receipts_month"] - base["nonfarm_expense_month"]
    # These two client KPIs are unsupported by the supplied 2003 source mapping.
    base["income_lease_month"] = np.nan
    base["income_pension_remit_month"] = np.nan
    base["hh_category"] = "Agricultural HH"
    base["Sector_code"] = base["SECTOR"].map(norm_text)
    base["Sector"] = base["Sector_code"].map({"1": "Rural", "2": "Urban"}).fillna("")
    base = add_geography(base, state_map, district_map, district_full_map)
    base = finish_household_mart(base, cfg, 2003)
    return base
