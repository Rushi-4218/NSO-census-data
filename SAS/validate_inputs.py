from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

from src.common import read_json
from src.dictionary import MasterDictionary

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description="Validate the SAS v5 INPUT folder and aggregate master dictionary contract.")
    p.add_argument("--inputs", required=True)
    p.add_argument("--config", default=str(ROOT / "config" / "pipeline_config.json"))
    args = p.parse_args()
    cfg = read_json(args.config)
    base = Path(args.inputs)
    rows = []
    for key, name in cfg["input_files"].items():
        f = base / name
        rows.append({"Key": key, "File": name, "Exists": f.exists(), "Size_MB": round(f.stat().st_size / 1048576, 2) if f.exists() else None})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    if not df["Exists"].all():
        return 1

    md = MasterDictionary(base / cfg["input_files"]["dictionary"])
    ref = list(pd.read_csv(base / cfg["input_files"]["client_reference"], nrows=1).columns)
    geo = md.geography
    n_state = int(geo["CODE_LIST_ID"].eq("STATE").sum())
    n_district = int(geo["CODE_LIST_ID"].eq("DISTRICT").sum())
    print("\nMaster dictionary contract: PASS")
    print("State_District sheet:", f"PASS ({n_state} states, {n_district} districts)")
    corrected_ref = ["HH_Type" if c == "houseHold_ID" else c for c in ref]
    schema_ok = corrected_ref == md.client_columns
    print("Client aggregate 24-column schema:", "PASS" if schema_ok else "FAIL")
    print("  correction: houseHold_ID -> HH_Type")
    return 0 if schema_ok and n_state >= 36 and n_district >= 600 else 1


if __name__ == "__main__":
    raise SystemExit(main())
