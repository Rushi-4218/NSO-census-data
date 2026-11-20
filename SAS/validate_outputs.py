from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
EXPECTED_FILES = {
    2003: "SAS_2003_All_India_State_District_Final.csv",
    2013: "SAS_2013_All_India_State_District_Final.csv",
    2019: "SAS_2019_All_India_State_District_Final.csv",
}
EXPECTED_PUBLISHED = {2003: "01-Dec-05", 2013: "19-Dec-14", 2019: "10-Sep-21"}
EXPECTED_KPIS = {
    "HH_SHARE", "HH_SIZE", "LAND_OWNED_HA", "LAND_POSS_HA", "NET_CROP_RCPT",
    "INC_WAGES", "INC_LEASE", "INC_ANIMALS", "INC_NONFARM", "INC_PENSION_REMIT",
    "MONTHLY_INCOME", "OUTPUT_PER_HH", "OUTPUT_PER_CAPITA", "OUTPUT_PER_HA",
}
EXPECTED_UNITS = {
    "HH_SHARE": "percent",
    "HH_SIZE": "members/household",
    "LAND_OWNED_HA": "hectares",
    "LAND_POSS_HA": "hectares",
    "NET_CROP_RCPT": "Rupees/month",
    "INC_WAGES": "Rupees/month",
    "INC_LEASE": "Rupees/month",
    "INC_ANIMALS": "Rupees/month",
    "INC_NONFARM": "Rupees/month",
    "INC_PENSION_REMIT": "Rupees/month",
    "MONTHLY_INCOME": "Rupees/month",
    "OUTPUT_PER_HH": "Rupees/household",
    "OUTPUT_PER_CAPITA": "Rupees/capita",
    "OUTPUT_PER_HA": "Rupees/hectare",
}
EXPECTED_SIZES = {"All sizes", "<0.01 ha", "0.01 - 0.4 ha", "0.4 - 1 ha", "1-2 ha", "2-4 ha", "4-10 ha"}


def _norm_id(x) -> str:
    s = "" if pd.isna(x) else str(x).strip()
    if not s:
        return ""
    try:
        return str(int(float(s)))
    except Exception:
        return s


def main() -> int:
    p = argparse.ArgumentParser(description="Validate SAS v5 aggregate-only production outputs.")
    p.add_argument("--outputs", default=str(ROOT / "outputs"))
    p.add_argument("--dictionary", default=str(ROOT / "config" / "client_schema_fallback.csv"), help="CSV with Position,Column_Name")
    args = p.parse_args()

    outputs = Path(args.outputs)
    schema = pd.read_csv(args.dictionary).sort_values("Position")
    expected_cols = schema["Column_Name"].astype(str).tolist()
    rows = []
    all_pass = True

    for year, name in EXPECTED_FILES.items():
        path = outputs / name
        if not path.exists() or path.stat().st_size == 0:
            rows.append({"Year": year, "File": name, "Check": "file_exists", "Status": "FAIL", "Detail": "missing or empty"})
            all_pass = False
            continue

        header = list(pd.read_csv(path, nrows=0).columns)
        schema_ok = header == expected_cols and "houseHold_ID" not in header and "HH_Type" in header
        rows.append({"Year": year, "File": name, "Check": "aggregate_schema_exact", "Status": "PASS" if schema_ok else "FAIL", "Detail": f"columns={len(header)}; HH_Type={'HH_Type' in header}; houseHold_ID={'houseHold_ID' in header}"})
        all_pass = all_pass and schema_ok

        df = pd.read_csv(path, dtype=str, low_memory=False)
        total = len(df)
        kpis = set(df["Col_ID"].dropna().astype(str))
        visits = set(df["Visit_ID"].dropna().astype(str).str.replace(r"\.0$", "", regex=True))
        sizes = set(df["Size"].dropna().astype(str))
        hh_types = set(df["HH_Type"].dropna().astype(str))
        years_seen = set(pd.to_numeric(df["Year"], errors="coerce").dropna().astype(int))

        sid = df["State_ID"].map(_norm_id)
        did = df["District_ID"].map(_norm_id)
        sname = df["State_Name"].fillna("").astype(str).str.strip()
        dname = df["District_Name"].fillna("").astype(str).str.strip()
        all_india = bool((sid.eq("0") & sname.eq("India") & did.eq("0") & dname.eq("All Districts")).any())
        state_totals = set(sid[sid.ne("0") & did.eq("0") & dname.eq("All Districts")])
        district_rows = int((did.ne("0") & dname.ne("")).sum())
        blank_named_district_rows = int((did.ne("0") & dname.eq("")).sum())

        key = ["State_ID", "District_ID", "Visit_ID", "HH_Type", "Size", "Col_ID"]
        key_unique = not df.duplicated(key).any()
        all_hh = "All HH" in hh_types
        agri_hh = "Agricultural HH" in hh_types
        # 2019 should expose Non-Agricultural HH when supported by the source.
        nonagri_ok = year != 2019 or "Non-Agricultural HH" in hh_types
        kpi_ok = kpis == EXPECTED_KPIS
        sizes_ok = EXPECTED_SIZES.issubset(sizes)
        year_ok = years_seen == {year}
        visit_ok = visits == {"1", "2"}
        unit_ok = True
        for kid, unit in EXPECTED_UNITS.items():
            units = set(df.loc[df["Col_ID"].eq(kid), "Unit"].dropna().astype(str))
            if units != {unit}:
                unit_ok = False
        published_ok = df["Published_date"].fillna("").astype(str).str.strip().eq(EXPECTED_PUBLISHED[year]).all()
        no_hh_id_values = "houseHold_ID" not in df.columns

        checks = [
            ("aggregate_rows_nonempty", total > 0, f"rows={total}"),
            ("all_14_kpis_exact", kpi_ok, f"missing={sorted(EXPECTED_KPIS-kpis)}; extra={sorted(kpis-EXPECTED_KPIS)}"),
            ("both_visits_present", visit_ok, str(sorted(visits))),
            ("all_required_sizes_present", sizes_ok, f"missing={sorted(EXPECTED_SIZES-sizes)}"),
            ("all_hh_present", all_hh, str(sorted(hh_types))),
            ("agricultural_hh_present", agri_hh, str(sorted(hh_types))),
            ("non_agricultural_hh_2019", nonagri_ok, str(sorted(hh_types))),
            ("all_india_present", all_india, f"present={all_india}"),
            ("state_all_districts_present", len(state_totals) > 0, f"states={len(state_totals)}"),
            ("district_rows_present", district_rows > 0, f"rows={district_rows}"),
            ("district_name_complete", blank_named_district_rows == 0, f"blank_named_district_rows={blank_named_district_rows}"),
            ("aggregate_key_unique", key_unique, f"duplicate_keys={int(df.duplicated(key).sum())}"),
            ("household_id_removed", no_hh_id_values, "houseHold_ID column absent"),
            ("unit_mapping_exact", unit_ok, str(EXPECTED_UNITS)),
            ("published_date_exact", published_ok, EXPECTED_PUBLISHED[year]),
            ("year_constant", year_ok, str(sorted(years_seen))),
        ]
        for check, ok, detail in checks:
            rows.append({"Year": year, "File": name, "Check": check, "Status": "PASS" if ok else "FAIL", "Detail": detail})
            all_pass = all_pass and ok

    report = pd.DataFrame(rows)
    print(report.to_string(index=False))
    outputs.mkdir(parents=True, exist_ok=True)
    out = outputs / "final_output_validation.csv"
    report.to_csv(out, index=False)
    print(f"\nValidation report: {out}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
