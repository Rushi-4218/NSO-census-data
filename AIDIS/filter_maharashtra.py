from pathlib import Path
import csv
from datetime import datetime
import pandas as pd
import polars as pl
import xlsxwriter

ROOT = Path(r"D:\AIDIS")
OUT = ROOT / "Pipeline"
OUT.mkdir(exist_ok=True)

source = ROOT / "AIDIS_Final_Client.xlsx"
csv_out = OUT / "AIDIS_Maharashtra_Final_Client.csv"
xlsx_out = OUT / "AIDIS_Maharashtra_Final_Client.xlsx"

DISTRICT_NAMES = {
    "2701": "Nandurbar", "2702": "Dhule", "2703": "Jalgaon",
    "2704": "Buldana", "2705": "Akola", "2706": "Washim",
    "2707": "Amravati", "2708": "Wardha", "2709": "Nagpur",
    "2710": "Bhandara", "2711": "Gondiya", "2712": "Gadchiroli",
    "2713": "Chandrapur", "2714": "Yavatmal", "2715": "Nanded",
    "2716": "Hingoli", "2717": "Parbhani", "2718": "Jalna",
    "2719": "Aurangabad", "2720": "Nashik", "2721": "Thane",
    "2722": "Mumbai Suburban", "2724": "Raigarh", "2725": "Pune",
    "2726": "Ahmadnagar", "2727": "Bid", "2728": "Latur",
    "2729": "Osmanabad", "2730": "Solapur", "2731": "Satara",
    "2732": "Ratnagiri", "2733": "Sindhudurg", "2734": "Kolhapur",
    "2735": "Sangli",
}

# Keep this lookup synchronized with DISTRICT_NAMES in build_aidis_delivery.py.
# The filter validates coverage and fails instead of silently emitting an
# undecoded Maharashtra district.

id_types = {
    "Survey_ID": str, "Survey_GROUP_ID": str, "SUB_GROUP_ID": str,
    "State_ID": str, "District_ID": str, "Col_ID": str, "houseHold_ID": str,
}

frame = pl.read_excel(source, engine="calamine")
mh = frame.filter(pl.col("State_ID").cast(pl.String).str.zfill(2).eq("27")).to_pandas()
for col in id_types:
    if col in mh:
        mh[col] = mh[col].astype("string")
for col in ["Survey_GROUP_ID", "State_ID"]:
    mh[col] = mh[col].str.zfill(2)
mh["District_ID"] = mh["District_ID"].str.zfill(4)
mh["FREQ_DESC"] = "Annual"
for date_col in ["Published_date", "Extracted_Date"]:
    mh[date_col] = pd.to_datetime(mh[date_col], errors="raise").dt.strftime("%d-%b-%Y")
observed = set(mh.loc[mh["District_ID"].ne("0000"), "District_ID"])
missing_mapping = sorted(observed - set(DISTRICT_NAMES))
supplied_not_observed = sorted(set(DISTRICT_NAMES) - observed)
if missing_mapping:
    raise RuntimeError(f"District codes missing from mapping: {missing_mapping}")
mh["District_Name"] = mh["District_ID"].map(DISTRICT_NAMES).fillna("All Districts")
rows = len(mh)
if rows == 0:
    raise RuntimeError("No Maharashtra rows found in final client dataset")

def pair_is_writable(csv_path, xlsx_path):
    try:
        for path in (csv_path, xlsx_path):
            with open(path, "a+b"):
                pass
        return True
    except PermissionError:
        return False

for suffix in ("", "_Updated", "_Updated_v2", "_Updated_v3"):
    candidate_csv = OUT / f"AIDIS_Maharashtra_Final_Client{suffix}.csv"
    candidate_xlsx = OUT / f"AIDIS_Maharashtra_Final_Client{suffix}.xlsx"
    if pair_is_writable(candidate_csv, candidate_xlsx):
        csv_out, xlsx_out = candidate_csv, candidate_xlsx
        break
else:
    raise PermissionError("All Maharashtra output pairs are currently open/locked")

mh.to_csv(csv_out, index=False, encoding="utf-8-sig")

workbook = xlsxwriter.Workbook(str(xlsx_out), {
    "constant_memory": True, "strings_to_urls": False,
})
sheet = workbook.add_worksheet("AIDIS_Maharashtra")
header_format = workbook.add_format({
    "bold": True, "font_color": "white", "bg_color": "#1F4E78",
    "border": 1, "align": "center", "valign": "vcenter",
})
number_format = workbook.add_format({"num_format": "0.######"})
date_format = workbook.add_format({"num_format": "dd-mmm-yyyy"})
sheet.freeze_panes(1, 0)
sheet.hide_gridlines(2)
sheet.set_tab_color("#1F4E78")
sheet.set_row(0, 30)
sheet.set_column("A:A", 18)
sheet.set_column("B:B", 52)
sheet.set_column("C:C", 16)
sheet.set_column("D:D", 30)
sheet.set_column("E:E", 18)
sheet.set_column("F:F", 25)
sheet.set_column("G:H", 14)
sheet.set_column("I:N", 19)
sheet.set_column("O:P", 18, date_format)
sheet.set_column("Q:Q", 18)
sheet.set_column("R:R", 16)
sheet.set_column("S:S", 27)
sheet.set_column("T:T", 75)
sheet.set_column("U:U", 18, number_format)
sheet.set_column("V:V", 15)
sheet.set_column("W:W", 55)
with open(csv_out, "r", encoding="utf-8-sig", newline="") as fh:
    reader = csv.reader(fh)
    for row_no, row in enumerate(reader):
        if row_no == 0:
            sheet.write_row(row_no, 0, row, header_format)
            continue
        if row_no:
            for idx in (6, 12, 16, 20):
                if row[idx] != "":
                    row[idx] = float(row[idx])
            for idx in (14, 15):
                if row[idx] != "":
                    row[idx] = datetime.strptime(row[idx], "%d-%b-%Y")
        sheet.write_row(row_no, 0, row)
sheet.autofilter(0, 0, rows, 22)
workbook.close()

coverage = pd.read_csv(ROOT / "AIDIS_KPI_Coverage.csv")
coverage.to_csv(OUT / "AIDIS_Maharashtra_KPI_Coverage.csv", index=False)

check = pd.read_csv(csv_out, dtype=id_types, encoding="utf-8-sig")
duplicates = check.duplicated(subset=[c for c in check.columns if c != "DATA"]).sum()
report = f"""# AIDIS Maharashtra Delivery Validation

- State filter: State_ID = 27 (Maharashtra)
- Output rows: {len(check):,}
- Output columns: {len(check.columns)}
- District codes represented: {check.loc[check.District_ID.ne('0000'), 'District_ID'].nunique()}
- District codes missing from supplied mapping: {missing_mapping}
- Supplied district codes absent from data: {supplied_not_observed}
- Visit IDs: {sorted(check.Visit_ID.unique().tolist())}
- KPI/Col_ID count: {check.Col_ID.nunique()}
- Null DATA values: {check.DATA.isna().sum()}
- Duplicate output keys: {duplicates}
- Non-Maharashtra rows: {(check.State_ID != '27').sum()}
- CSV and Excel were generated from the same filtered row stream.

Known limitations carried from the national delivery:

- No material KPI omission remains; FCE/EPL use the official annual Visit-1 + Visit-2 tabulation rule.
- Maharashtra district names were decoded using the user-supplied 34-code mapping; `0000` remains `All Districts` for aggregate rows.
"""
(OUT / "AIDIS_Maharashtra_Validation_Report.md").write_text(report, encoding="utf-8")
print({"rows": rows, "columns": len(check.columns), "districts": check.loc[check.District_ID.ne('0000'), 'District_ID'].nunique()})
