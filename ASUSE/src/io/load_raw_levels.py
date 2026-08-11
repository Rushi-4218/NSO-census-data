from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from openpyxl import load_workbook


def iter_tokens(path: Path) -> Iterator[list[str]]:
    """Yield nonblank whitespace runs/cells from the supplied masked delivery."""
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                tokens = [str(x).strip() for x in row if str(x).strip()]
                if tokens:
                    yield tokens
        return
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for row in wb.active.iter_rows(values_only=True):
            tokens = [str(x).strip() for x in row if x is not None and str(x).strip()]
            if tokens:
                yield tokens
    finally:
        wb.close()


COMMON_SLICES = {
    "fsu": (0, 5), "schedule": (5, 8), "sector": (8, 9),
    "nss_region": (9, 12), "district": (12, 14), "stratum": (14, 16),
    "sub_stratum": (16, 18), "sub_round": (18, 19), "sub_region": (19, 23),
    "segment": (23, 24), "SSS_no": (24, 26), "est_no": (26, 29), "level": (29, 31),
}


def common(first: str) -> dict[str, str]:
    if len(first) < 31:
        raise ValueError(f"Record shorter than common 31-byte prefix: {first!r}")
    out = {k: first[a:b] for k, (a, b) in COMMON_SLICES.items()}
    out["Enterprise_Key"] = first[:29]
    out["Raw_State_Code"] = out["nss_region"][:2]
    return out


def number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def multiplier(tokens: list[str]) -> float:
    value = number(tokens[-1])
    if value is None:
        raise ValueError(f"Invalid multiplier token: {tokens[-1]!r}")
    return value / 100.0


class TokenStream:
    def __init__(self, tokens: list[str]):
        self.tokens = [t for t in tokens if t]
        self.i = 0
        self.pos = 0

    def read(self, width: int) -> str:
        while self.i < len(self.tokens) and self.pos >= len(self.tokens[self.i]):
            self.i += 1
            self.pos = 0
        if self.i >= len(self.tokens):
            return ""
        token = self.tokens[self.i]
        if self.pos + width > len(token):
            return ""
        value = token[self.pos:self.pos + width]
        self.pos += width
        return value

    def remainder(self) -> str:
        if self.i >= len(self.tokens):
            return ""
        return self.tokens[self.i][self.pos:]

    def next_token(self) -> None:
        self.i += 1
        self.pos = 0


def parse_l02(tokens: list[str]) -> dict:
    c = common(tokens[0])
    stream = TokenStream([tokens[0][31:]] + tokens[1:-1])
    mixed = stream.read(1)
    nic2 = stream.read(2)
    nic5 = stream.read(5)
    if mixed == "1":
        stream.read(2); stream.read(5)
    ownership = stream.read(1)
    if ownership in {"1", "2", "3", "4", "5"}:
        stream.read(1); stream.read(1); stream.read(1); stream.read(2)
    nonprofit = stream.read(1)
    if nonprofit == "1":
        stream.read(1)
    stream.read(1)  # 211
    stream.read(1)  # 212
    stream.read(1)  # 213
    stream.read(1)  # 214
    stream.read(4)  # 215
    stream.read(1)  # 216
    stream.read(2)  # 217
    stream.read(2)  # 218
    stream.read(1)  # 219
    exporting = stream.read(1)  # 220
    if exporting == "1":
        stream.read(1)
    stream.read(1)  # 222
    stream.read(1)  # 223
    problems = stream.read(1)  # 224
    if problems == "1":
        stream.read(1)  # item 225 is mandatory when problems were reported
        # Item 226 is optional. It is present only in the same contiguous run;
        # otherwise the next run begins with mandatory registration item 227.
        if stream.remainder():
            stream.read(1)
    registered = stream.read(1)
    if registered == "1":
        for _ in range(6):
            stream.read(1)
        # Consume the variable-length run of 2-digit additional registrations.
        rem = stream.remainder()
        stream.pos += (len(rem) // 2) * 2
    stream.next_token()
    contract_manuf = stream.read(1)
    if contract_manuf in {"1", "2"}:
        stream.read(1); stream.read(1)
    contract_other = stream.read(1)
    if contract_other in {"1", "2"}:
        stream.read(1)
    stream.read(1)  # 244

    # The whitespace converter collapses optional items 225/226, while the
    # three contract groups (239-241, 242-243, 244) remain the final three
    # runs. Recover item 227 from the preceding run by validating its suffix.
    def registration_from_group(group: str) -> str:
        candidates = []
        for pos in (0, 3, 4, 5):
            if pos >= len(group) or group[pos] not in {"1", "2"}:
                continue
            code = group[pos]
            suffix = group[pos + 1:]
            if code == "2" and suffix == "":
                candidates.append(code)
            elif code == "1" and len(suffix) >= 6:
                acts, additions = suffix[:6], suffix[6:]
                if set(acts) <= {"1", "2"} and len(additions) % 2 == 0 and len(additions) <= 10:
                    candidates.append(code)
        return candidates[0] if len(candidates) == 1 else ""

    if len(tokens) >= 5:
        recovered = registration_from_group(tokens[-5])
        if recovered:
            registered = recovered

    initial_registered = registered

    # A small number of 2025 rows have blanks inside items 225-238.  The
    # spreadsheet-to-whitespace rendering removes those blank cells, so the
    # forward cursor can land on a problem/registration-detail code instead
    # of mandatory item 227.  Recover only when the normal parse is invalid,
    # and validate the complete 227-244 suffix against the questionnaire skip
    # pattern.  This deliberately does not reinterpret already-valid 1/2
    # values.
    if registered not in {"1", "2"}:
        allowed_additional = {
            "01", "02", "03", "04", "05", "06", "07", "08", "09",
            "11", "12", "13", "98", "99",
        }
        payload = "".join([tokens[0][31:]] + tokens[1:-1])

        def valid_contract_suffix(value: str) -> bool:
            if not value or value[0] not in {"1", "2", "3", "4"}:
                return False
            pos = 1
            if value[0] in {"1", "2"}:
                if len(value) < pos + 2 or value[pos] not in {"1", "2", "3"} or value[pos + 1] not in {"1", "2"}:
                    return False
                pos += 2
            if len(value) <= pos or value[pos] not in {"1", "2", "3", "4"}:
                return False
            contract_other = value[pos]
            pos += 1
            if contract_other in {"1", "2"}:
                if len(value) <= pos or value[pos] not in {"1", "2", "3"}:
                    return False
                pos += 1
            return len(value) == pos + 1 and value[pos] in {"1", "2"}

        candidates: list[tuple[int, str]] = []
        # The longest possible registration portion is 17 characters:
        # item 227, six act flags, and five two-digit additional codes.
        for start in range(max(0, len(payload) - 35), len(payload)):
            code = payload[start:start + 1]
            if code == "2" and valid_contract_suffix(payload[start + 1:]):
                candidates.append((start, code))
                continue
            if code != "1":
                continue
            for act_count in range(7):
                acts = payload[start + 1:start + 1 + act_count]
                if len(acts) != act_count or any(x not in {"1", "2"} for x in acts):
                    continue
                for additional_count in range(6):
                    details_start = start + 1 + act_count
                    details_end = details_start + 2 * additional_count
                    details = [payload[i:i + 2] for i in range(details_start, details_end, 2)]
                    if not all(x in allowed_additional for x in details):
                        continue
                    if valid_contract_suffix(payload[details_end:]):
                        candidates.append((start, code))
        if candidates:
            # The earliest valid suffix is item 227; later alternatives can be
            # incidental 1/2 values inside registration or contract details.
            registered = min(candidates)[1]
    c.update({
        "Multiplier": multiplier(tokens), "Major_NIC_2dig": nic2,
        "Major_NIC_5dig": nic5, "Ownership_Type": ownership,
        "Registered": registered,
        "Registration_Initial_Code": initial_registered,
        "Registration_Recovery_Status": (
            "ORIGINAL_VALID" if initial_registered in {"1", "2"}
            else "RECOVERED_SUFFIX" if registered in {"1", "2"}
            else "UNRESOLVED"
        ),
    })
    return c


def parse_l03(tokens: list[str]) -> dict:
    c = common(tokens[0])
    payload = tokens[0][31:]
    c["Ref_Period_Type"] = payload[14:15] if len(payload) >= 15 else ""
    c["Months_In_Accounting_Period"] = None
    if c["Ref_Period_Type"] == "4":
        # Item 266 is blank and item 267 begins the next whitespace run.  The
        # whitespace rendering can concatenate the two-byte item 267 with the
        # following one-byte item 271 (for example, "121" means 12 months and
        # item 271=1), so only the first two characters belong to item 267.
        candidates = tokens[1:-1]
        c["Months_In_Accounting_Period"] = number(candidates[0][:2]) if candidates else None
    c["Multiplier"] = multiplier(tokens)
    return c


def parse_item_value(tokens: list[str], item_width: int, value_name: str) -> dict:
    c = common(tokens[0])
    payload = tokens[0][31:]
    item = payload[:item_width]
    remainder = payload[item_width:]
    values = ([remainder] if remainder else []) + tokens[1:-1]
    c["Item_No"] = item
    c[value_name] = number(values[0]) if values else None
    c["Multiplier"] = multiplier(tokens)
    return c


def _worker_solutions(run_tokens: list[str]) -> list[list[int]]:
    """Recover seven worker cells from whitespace runs using total=sum(components)."""
    solutions: list[list[int]] = []

    def splits(s: str, n: int, prefix=()):
        if n == 0:
            if not s:
                yield list(prefix)
            return
        for width in range(1, min(5, len(s) - n + 1) + 1):
            part = s[:width]
            if len(part) > 1 and part[0] == "0":
                continue
            yield from splits(s[width:], n - 1, prefix + (int(part),))

    def place(ti: int, start: int, vals: list[int]):
        if ti == len(run_tokens):
            if len(vals) <= 7:
                full = vals + [0] * (7 - len(vals))
                if full[6] == sum(full[:6]):
                    solutions.append(full)
            return
        token = run_tokens[ti]
        for gap in range(0, 7 - start):
            pos = start + gap
            for n in range(1, 8 - pos):
                for parts in splits(token, n):
                    next_vals = vals + [0] * gap + parts
                    place(ti + 1, pos + n, next_vals)

    place(0, 0, [])
    unique = []
    for s in solutions:
        if s not in unique:
            unique.append(s)
    return unique


def parse_l09(tokens: list[str]) -> dict:
    c = common(tokens[0])
    payload = tokens[0][31:]
    c["Item_No"] = payload[:3]
    # The converter preserves the official total column as the final non-weight
    # whitespace run, even when earlier sex/time components are blank.
    c["Total_Workers"] = number(tokens[-2]) if len(tokens) >= 3 else None
    c["Worker_Parse_Status"] = "resolved" if c["Total_Workers"] is not None else "unresolved"
    c["Multiplier"] = multiplier(tokens)
    return c
