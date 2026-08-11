from __future__ import annotations

import csv
from pathlib import Path
import sys
import zipfile

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa" / "2022-2023"
RAW = ROOT / "work" / "2022-2023" / "raw"
ARCHIVE = ROOT / "Input" / "Annual Survey of Unincorporated Sector Enterprises (ASUSE) of 2022-2023.zip"
EXPECTED_NAME = "asuse_2223_esu_l08.csv"


def candidates() -> list[Path]:
    terms = ("level - 08", "level_08", "level08", "esu_l08", "block 7.1", "block 7_1")
    found = []
    for base in [ROOT / "Input", RAW, Path.home() / "Downloads", Path.home() / ".codex" / "attachments"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and any(term in path.name.lower() for term in terms):
                # Files from other ASUSE years are not valid candidates.
                context = str(path).lower()
                if "2023-2024" not in context and "2025" not in context:
                    found.append(path)
    return sorted(set(found))


def archive_members() -> list[str]:
    if not ARCHIVE.exists():
        return []
    with zipfile.ZipFile(ARCHIVE) as book:
        return [item.filename for item in book.infolist()]


def write_diagnostics() -> None:
    QA.mkdir(parents=True, exist_ok=True)
    found = candidates()
    members = archive_members()
    archive_l08 = [name for name in members if any(x in name.lower() for x in ("level - 08", "esu_l08", "block 7_1", "block 7.1"))]
    required = [
        "FSU_Serial_No", "Schedule", "Sector", "NSS_Region", "District", "Stratum",
        "Sub_stratum", "Sub_Round", "FOD_Sub_Region", "Segment_No",
        "Second_Stage_Stratum_No", "Sample_Establishment_No", "Level",
        "b7q2 / item_no", "b7q3 / value_rs", "MLT",
    ]
    source = pd.DataFrame([{
        "file_name": "" if not found else found[0].name,
        "file_path": "" if not found else str(found[0]),
        "survey_year": "2022-2023",
        "level": "L08",
        "block": "Block 7.1 & 7.2",
        "row_count": 0,
        "column_count": 0,
        "required_fields_present": False,
        "missing_required_fields": "; ".join(required),
        "duplicate_establishment_keys": np.nan,
        "status": "SOURCE_MISSING / NOT_COMPUTABLE",
        "notes": (
            f"Official layout requires {EXPECTED_NAME} (56-byte L08 records). The supplied ZIP has "
            f"{len(members)} members and no L08 member; extracted raw levels skip L07 to L09. "
            "Workspace, attachment and Downloads searches found no 2022-2023 L08 candidate."
        ),
    }])
    source.to_csv(QA / "qa_2022_2023_gva_source_availability.csv", index=False)

    mapping = pd.DataFrame([
        ("enterprise identifier fields", "bytes 1-29", "Identification", "FSU through sample establishment number", "Code", "Exact fixed-width concatenation", "Missing invalidates join", "Zero retained as coded", False, "One-to-one Level 02/L08 join key"),
        ("b7q2 / item_no", "765", "7.1", "Total input for market establishment", "Rupees", "Non-negative component", "Blank is missing", "Zero is valid", False, "Intermediate component of official item 769"),
        ("b7q2 / item_no", "766", "7.1", "Total output for market establishment", "Rupees", "Non-negative component", "Blank is missing", "Zero is valid", False, "Intermediate component of official item 769"),
        ("b7q2 + b7q3 / item_no + value_rs", "769", "7.1", "Gross value added = item 766 - item 765", "Rupees", "Negative values explicitly permitted", "Blank is missing GVA", "Zero is valid GVA", True, "Establishment GVA for market establishments"),
        ("b7q2 / item_no", "772", "7.2", "Total emoluments for non-market establishment", "Rupees", "Non-negative component", "Blank is missing", "Zero is valid", False, "Intermediate component of official item 779"),
        ("b7q2 / item_no", "773", "7.2", "Total input for non-market establishment", "Rupees", "Non-negative component", "Blank is missing", "Zero is valid", False, "Intermediate component of official item 779"),
        ("b7q2 / item_no", "774", "7.2", "Total output = item 772 + item 773", "Rupees", "Non-negative component", "Blank is missing", "Zero is valid", False, "Intermediate component of official item 779"),
        ("b7q2 + b7q3 / item_no + value_rs", "779", "7.2", "Net value added = item 774 - item 773", "Rupees", "Negative values explicitly permitted", "Blank is missing GVA", "Zero is valid GVA", True, "Establishment GVA for non-market establishments"),
        ("MLT", "Generated", "L08", "Final survey multiplier", "Multiplier stored ×100", "Divide by configured 100", "Blank invalidates weighted estimate", "Zero invalid", True, "weighted_GVA = selected item value × final multiplier"),
    ], columns=[
        "raw_variable", "item_number", "block", "description", "unit", "sign_convention",
        "treatment_of_blank", "treatment_of_zero", "included_in_GVA", "calculation_role",
    ])
    mapping.to_csv(QA / "qa_2022_2023_gva_field_mapping.csv", index=False)

    base = pd.read_parquet(ROOT / "work" / "2022-2023" / "ASUSE_2022-2023_Master_Estimation_Table.parquet")
    duplicate_count = base.groupby("Enterprise_Key").Enterprise_Key.transform("size")
    join = pd.DataFrame({
        "establishment_id": base.Enterprise_Key,
        "main_level_present": True,
        "level08_present": False,
        "match_status": "LEVEL08_SOURCE_MISSING",
        "duplicate_count_main": duplicate_count,
        "duplicate_count_level08": 0,
        "weight": base.Multiplier,
        "rural_urban": base.Sector,
        "state": base.State_Name,
        "sector": base.BAC,
        "notes": f"Cannot perform merge: official 2022-2023 {EXPECTED_NAME} was not supplied.",
    })
    for name in ["qa_2022_2023_level08_join_diagnostic.csv", "qa_2022_2023_gva_join_diagnostic.csv"]:
        join.to_csv(QA / name, index=False)

    component_columns = [
        "establishment_id", "item_765_total_input", "item_766_total_output", "item_769_gva",
        "item_772_emoluments", "item_773_total_input", "item_774_total_output", "item_779_nva",
        "calculated_gva", "negative_gva_flag", "missing_component_flag", "outlier_flag",
        "eligibility_flag", "weight", "weighted_gva", "status",
    ]
    pd.DataFrame(columns=component_columns).to_csv(QA / "qa_2022_2023_gva_components.csv", index=False)

    step = pd.read_csv(ROOT / "output" / "2022-2023" / "steps" / "07_gva_share.csv")
    share = step[["State_ID", "State_Name", "District_ID", "District_Name", "Sector_code", "Sector", "Col_ID", "COL_DESC", "DATA"]].copy()
    share["weighted_total_gva_denominator"] = np.nan
    share["manufacturing_trade_other_sum"] = np.nan
    share["reconciliation_gap"] = np.nan
    share["denominator_positive"] = False
    share["finite_percentage"] = False
    share["status"] = "NOT_COMPUTABLE_SOURCE_MISSING"
    share.to_csv(QA / "qa_2022_2023_gva_share.csv", index=False)

    print(f"candidate_files={len(found)} archive_l08_members={len(archive_l08)} main_establishments={len(base)}")


if __name__ == "__main__":
    write_diagnostics()
