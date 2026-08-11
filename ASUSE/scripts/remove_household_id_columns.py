from __future__ import annotations

import csv
from pathlib import Path
import os

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOTS = [ROOT / "output", ROOT / "qa", ROOT / "mapping"]


def is_household_id(value: object) -> bool:
    normalized = str(value or "").strip().lower().replace("_", "").replace(" ", "")
    return normalized == "householdid"


def rewrite_csv(path: Path) -> int:
    temporary = path.with_name(path.name + ".remove_household_id.tmp")
    removed = 0
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header is None:
            return 0
        indexes = [i for i, value in enumerate(header) if is_household_id(value)]
        if not indexes:
            return 0
        keep = [i for i in range(len(header)) if i not in indexes]
        with temporary.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.writer(target, lineterminator="\n")
            writer.writerow([header[i] for i in keep])
            for row in reader:
                writer.writerow([row[i] if i < len(row) else "" for i in keep])
        removed = len(indexes)
    os.replace(temporary, path)
    return removed


def rewrite_xlsx(path: Path) -> int:
    workbook = load_workbook(path)
    removed = 0
    changed = False
    for sheet in workbook.worksheets:
        indexes = [cell.column for cell in sheet[1] if is_household_id(cell.value)]
        for index in sorted(indexes, reverse=True):
            sheet.delete_cols(index, 1)
            removed += 1
            changed = True
    if changed:
        workbook.save(path)
    workbook.close()
    return removed


def main() -> None:
    changed = []
    for base in GENERATED_ROOTS:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".csv":
                count = rewrite_csv(path)
            elif path.suffix.lower() == ".xlsx":
                count = rewrite_xlsx(path)
            else:
                continue
            if count:
                changed.append((path.relative_to(ROOT), count))
    print(f"files_changed={len(changed)} columns_removed={sum(count for _, count in changed)}")
    for path, count in changed:
        print(f"{path}\t{count}")


if __name__ == "__main__":
    main()
