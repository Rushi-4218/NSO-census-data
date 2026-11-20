from pathlib import Path
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "input" / "raw"


targets = [
    p
    for p in RAW_DIR.rglob("*.xlsx")
    if (
        "Visit 1 & 2 Combined" in p.name
        and
        "Block 15pt2" in p.name
    )
]


print("=" * 78)
print("AIDIS 2003 - INSPECT COMBINED BLOCK 15pt2 WORKBOOKS")
print("=" * 78)


for path in sorted(targets):

    print()
    print("=" * 78)
    print(path.name)
    print("=" * 78)

    wb = load_workbook(
        path,
        read_only=True,
        data_only=True
    )

    try:

        print(
            "Sheet names:",
            wb.sheetnames
        )

        for ws in wb.worksheets:

            print()
            print(
                f"--- SHEET: {ws.title} ---"
            )

            print(
                f"max_row={ws.max_row}, "
                f"max_column={ws.max_column}"
            )

            nonempty_seen = 0

            for row_no, row in enumerate(
                ws.iter_rows(
                    values_only=True
                ),
                start=1
            ):

                values = [
                    "" if x is None
                    else str(x).strip()
                    for x in row
                ]

                if not any(values):
                    continue

                print(
                    f"ROW {row_no}: "
                    +
                    " | ".join(values[:50])
                )

                nonempty_seen += 1

                if nonempty_seen >= 5:
                    break

    finally:

        wb.close()


print()
print("=" * 78)
print("INSPECTION COMPLETE")
print("=" * 78)