from pathlib import Path
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
CONFIG_DIR = ROOT / "config"
WORK_DIR = ROOT / "work"
REPORT_DIR = ROOT / "output" / "reports"

PRODUCTION_MANIFEST = CACHE_DIR / "step01_production_manifest.csv"
METHODOLOGY_FILE = CONFIG_DIR / "aidis_2003_methodology_lock.json"
STOCK_BASE_FILE = WORK_DIR / "step02_household_base_stock.csv"
ASSET_FACT_FILE = WORK_DIR / "step03_household_asset_facts.csv"

LOAN_FACT_FILE = WORK_DIR / "step04_cash_loan_facts.csv"
HOUSEHOLD_DEBT_FILE = WORK_DIR / "step04_household_debt_facts.csv"
JOIN_AUDIT_FILE = CACHE_DIR / "step04_loan_join_audit.csv"
JOIN_EXCEPTIONS_FILE = CACHE_DIR / "step04_loan_join_exceptions.csv"
DEBT_CONTROLS_FILE = CACHE_DIR / "step04_debt_controls.csv"
DEBT_ESTIMATES_FILE = CACHE_DIR / "step04_debt_kpi_estimates.csv"
AGENCY_BREAKDOWN_FILE = CACHE_DIR / "step04_credit_agency_breakdown.csv"
INTEREST_BREAKDOWN_FILE = CACHE_DIR / "step04_interest_nature_breakdown.csv"
PURPOSE_BREAKDOWN_FILE = CACHE_DIR / "step04_loan_purpose_breakdown.csv"
AGENCY_PURPOSE_FILE = CACHE_DIR / "step04_agency_purpose_crossbreakdown.csv"
CHECKS_FILE = CACHE_DIR / "step04_debt_credit_checks.csv"
SUMMARY_FILE = REPORT_DIR / "step04_debt_credit_summary.txt"

EXPECTED_STOCK_HOUSEHOLDS = 143_285
EXPECTED_STOCK_SECTOR = {"1": 91_192, "2": 52_093}
EXPECTED_PART1_ROWS = 97_281
EXPECTED_PART2_ROWS = 97_287

PART1_NAMES = ["Visit1_Block15pt2 part1", "Visit1_Block15pt2_part1"]
PART2_NAMES = ["Visit1_Block15pt2 part2", "Visit1_Block15pt2_part2"]

BASE_REQUIRED = [
    "HHID", "Sector", "State_Region", "State", "District",
    "Household_Group_Code", "Household_Group", "Group_Classification_Status", "Weight",
]
ASSET_REQUIRED = ["HHID", "Sector", "State", "District", "Weight", "Total_Assets_Rs"]
PART1_REQUIRED = [
    "HHID", "Sector", "State", "District", "Visit_no", "Weight",
    "B15_2_q1", "B15_2_q6", "B15_2_q8", "B15_2_q9", "B15_2_q10",
    "B15_2_q11", "B15_2_q12", "B15_2_q13",
]
PART2_REQUIRED = [
    "HHID", "Sector", "State", "District", "Visit_no", "Weight",
    "B15_2_q1", "B15_2_q20", "B15_2_q21", "B15_2_q22", "B15_2_q23", "B15_2_q24",
]

AOD_REL_TOL = 0.005
AODL_REL_TOL = 0.005
IOI_ABS_TOL = 0.15


def clean(v):
    return "" if v is None else str(v).strip()


def norm_name(v):
    return re.sub(r"[^a-z0-9]+", "", clean(v).casefold())


def as_float(v, blank_zero=False):
    t = clean(v).replace(",", "")
    if not t:
        return 0.0 if blank_zero else None
    return float(t)


def fmt(v):
    if v is None:
        return ""
    if abs(v) < 5e-12:
        v = 0.0
    return f"{v:.10f}".rstrip("0").rstrip(".")


def near(a, b, abs_tol=5e-7, rel_tol=1e-9):
    if a is None or b is None:
        return False
    return math.isclose(float(a), float(b), abs_tol=abs_tol, rel_tol=rel_tol)


def serial(v):
    t = clean(v)
    if not t:
        return ""
    try:
        n = float(t)
        if n.is_integer():
            return str(int(n))
    except ValueError:
        pass
    return t


def code(v, width=None):
    t = clean(v)
    if not t:
        return ""
    try:
        n = float(t)
        if n.is_integer():
            t = str(int(n))
    except ValueError:
        pass
    return t.zfill(width) if width and t.isdigit() else t


def open_csv(path):
    last = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            h = path.open("r", encoding=enc, newline="")
            r = csv.DictReader(h)
            if not r.fieldnames:
                h.close()
                raise ValueError("empty CSV header")
            return h, r, enc
        except UnicodeDecodeError as exc:
            last = exc
        except Exception as exc:
            last = exc
            break
    raise RuntimeError(f"Unable to read {path.name}: {last}")


def require_fields(fieldnames, required, label):
    present = {norm_name(x): x for x in (fieldnames or [])}
    missing = [x for x in required if norm_name(x) not in present]
    if missing:
        raise ValueError(f"{label}: missing fields {missing}")


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def add_check(rows, name, expected, observed, passed, note=""):
    rows.append({
        "check": name,
        "expected": str(expected),
        "observed": str(observed),
        "status": "PASS" if passed else "FAIL",
        "note": note,
    })


def load_methodology():
    if not METHODOLOGY_FILE.exists():
        raise FileNotFoundError(f"Missing methodology lock: {METHODOLOGY_FILE}")
    data = json.loads(METHODOLOGY_FILE.read_text(encoding="utf-8"))
    if data.get("methodology_lock_status") != "LOCKED":
        raise ValueError("Step 01B-C methodology is not LOCKED")
    debt = data.get("debt") or {}
    if debt.get("part2_fields", {}).get("amount_outstanding_2002_06_30") != "B15_2_q24":
        raise ValueError("Methodology does not lock B15_2_q24 as 30-06-2002 cash debt")
    if debt.get("source") != "Visit1 Block 15.2":
        raise ValueError(f"Unexpected locked debt source: {debt.get('source')!r}")
    return data


def load_manifest():
    if not PRODUCTION_MANIFEST.exists():
        raise FileNotFoundError(f"Missing production manifest: {PRODUCTION_MANIFEST}")
    with PRODUCTION_MANIFEST.open("r", encoding="utf-8-sig", newline="") as h:
        rows = list(csv.DictReader(h))
    if len(rows) != 42:
        raise ValueError(f"Production manifest expected 42 rows; found {len(rows)}")
    bad = [r for r in rows if clean(r.get("status")).upper() != "PASS"]
    if bad:
        raise ValueError(f"Production manifest has {len(bad)} non-PASS row(s)")
    return rows


def manifest_source(manifest, names):
    targets = {norm_name(x) for x in names}
    rows = [r for r in manifest if norm_name(r.get("logical_dataset")) in targets]
    if len(rows) != 1:
        raise RuntimeError(f"Expected one manifest source for {names}; found {len(rows)}")
    p = Path(rows[0]["source_path"])
    if not p.exists():
        raise FileNotFoundError(f"Manifest source does not exist: {p}")
    return p


def load_stock_base():
    if not STOCK_BASE_FILE.exists():
        raise FileNotFoundError(f"Missing Step 02 stock base: {STOCK_BASE_FILE}")
    base, order = {}, []
    sector = Counter()
    h, r, _ = open_csv(STOCK_BASE_FILE)
    try:
        require_fields(r.fieldnames, BASE_REQUIRED, STOCK_BASE_FILE.name)
        for row in r:
            hhid = clean(row.get("HHID"))
            if not hhid:
                raise ValueError("Step 02 stock base has blank HHID")
            if hhid in base:
                raise ValueError(f"Step 02 stock base duplicate HHID: {hhid}")
            weight = as_float(row.get("Weight"))
            if weight is None or weight < 0:
                raise ValueError(f"Invalid Step 02 Weight for HHID={hhid}")
            sec = code(row.get("Sector"))
            sector[sec] += 1
            base[hhid] = {
                "HHID": hhid,
                "Sector": sec,
                "Sector_Name": clean(row.get("Sector_Name")),
                "State_Region": clean(row.get("State_Region")),
                "State": clean(row.get("State")),
                "District": clean(row.get("District")),
                "Household_Group_Code": clean(row.get("Household_Group_Code")),
                "Household_Group": clean(row.get("Household_Group")),
                "Group_Classification_Status": clean(row.get("Group_Classification_Status")),
                "Weight": weight,
            }
            order.append(hhid)
    finally:
        h.close()
    if len(base) != EXPECTED_STOCK_HOUSEHOLDS:
        raise ValueError(f"Step 02 expected {EXPECTED_STOCK_HOUSEHOLDS:,} HH; found {len(base):,}")
    if dict(sector) != EXPECTED_STOCK_SECTOR:
        raise ValueError(f"Step 02 sector counts differ: {dict(sector)}")
    return base, order


def load_assets(base):
    if not ASSET_FACT_FILE.exists():
        raise FileNotFoundError(f"Missing Step 03 asset facts: {ASSET_FACT_FILE}")
    assets = {}
    weight_bad = core_bad = 0
    h, r, _ = open_csv(ASSET_FACT_FILE)
    try:
        require_fields(r.fieldnames, ASSET_REQUIRED, ASSET_FACT_FILE.name)
        for row in r:
            hhid = clean(row.get("HHID"))
            if not hhid or hhid not in base:
                raise ValueError(f"Step 03 invalid/unmatched HHID: {hhid!r}")
            if hhid in assets:
                raise ValueError(f"Step 03 duplicate HHID: {hhid}")
            sw = as_float(row.get("Weight"))
            if sw is None or not near(sw, base[hhid]["Weight"]):
                weight_bad += 1
            for f in ("Sector", "State", "District"):
                if clean(row.get(f)) != clean(base[hhid][f]):
                    core_bad += 1
                    break
            assets[hhid] = as_float(row.get("Total_Assets_Rs"), blank_zero=True)
    finally:
        h.close()
    if len(assets) != EXPECTED_STOCK_HOUSEHOLDS:
        raise ValueError(f"Step 03 expected {EXPECTED_STOCK_HOUSEHOLDS:,} HH; found {len(assets):,}")
    if weight_bad or core_bad:
        raise ValueError(f"Step03/base mismatches: weight={weight_bad}, core={core_bad}")
    return assets


def audit_core(row, base_row, stats):
    if code(row.get("Visit_no")) != "1":
        stats["non_visit1"] += 1
    for f in ("Sector", "State", "District"):
        if clean(row.get(f)) != clean(base_row[f]):
            stats["core_mismatch"] += 1
            break
    sw = as_float(row.get("Weight"))
    if sw is None or not near(sw, base_row["Weight"]):
        stats["weight_mismatch"] += 1


def load_part1(path, base):
    rec = {}
    st = Counter()
    h, r, enc = open_csv(path)
    st["encoding_marker"] = 0
    try:
        require_fields(r.fieldnames, PART1_REQUIRED, path.name)
        for row in r:
            st["rows"] += 1
            hhid = clean(row.get("HHID"))
            s = serial(row.get("B15_2_q1"))
            if not hhid:
                st["blank_hhid"] += 1
                continue
            if not s:
                st["blank_serial"] += 1
                continue
            if hhid not in base:
                st["unmatched_hhid"] += 1
                continue
            audit_core(row, base[hhid], st)
            key = (hhid, s)
            if key in rec:
                st["duplicate_key"] += 1
                continue
            rec[key] = {
                "agency": code(row.get("B15_2_q6"), 2),
                "loan_type": code(row.get("B15_2_q8")),
                "interest_nature": code(row.get("B15_2_q9")),
                "interest_rate": clean(row.get("B15_2_q10")),
                "purpose": code(row.get("B15_2_q11")),
                "security": code(row.get("B15_2_q12"), 2),
                "mortgage": code(row.get("B15_2_q13")),
            }
    finally:
        h.close()
    st["unique_keys"] = len(rec)
    st["encoding"] = enc
    return rec, st


def classifiers(methodology):
    ca = methodology.get("credit_agency_codes", {})
    return {
        "inst": {code(x, 2) for x in ca.get("institutional_codes", [])},
        "noninst": {code(x, 2) for x in ca.get("non_institutional_codes", [])},
        "agency_labels": {code(k, 2): clean(v) for k, v in ca.get("labels", {}).items()},
        "interest_labels": {code(k): clean(v) for k, v in methodology.get("interest_nature_codes", {}).items()},
        "purpose_labels": {code(k): clean(v) for k, v in methodology.get("loan_purpose_codes", {}).items()},
    }


def agency_class(c, cl):
    if c in cl["inst"]:
        return "Institutional"
    if c in cl["noninst"]:
        return "Non-institutional"
    return "Unclassified"


def agency_label(c, cl):
    return cl["agency_labels"].get(c, "Unclassified / missing" if not c else f"Unmapped agency code {c}")


def interest_label(c, cl):
    return cl["interest_labels"].get(c, "Unclassified / missing" if not c else f"Unmapped interest code {c}")


def purpose_label(c, cl):
    return cl["purpose_labels"].get(c, "Unclassified / missing" if not c else f"Unmapped purpose code {c}")


def scopes(meta):
    return ["All India", meta["Sector_Name"]]


def add_breakdown(store, seen, dimension, c, label, klass, hhid, meta, debt):
    for scope in scopes(meta):
        key = (scope, c, label, klass)
        cell = store[key]
        cell["loan_rows"] += 1
        cell["raw_debt"] += debt
        cell["weighted_debt"] += meta["Weight"] * debt
        sk = (dimension, scope, c, klass, hhid)
        if sk not in seen:
            seen.add(sk)
            cell["hh_n"] += 1
            cell["hh_weight"] += meta["Weight"]


def add_cross(store, seen, ac, pc, hhid, meta, debt):
    for scope in scopes(meta):
        key = (scope, ac, pc)
        cell = store[key]
        cell["loan_rows"] += 1
        cell["raw_debt"] += debt
        cell["weighted_debt"] += meta["Weight"] * debt
        sk = (scope, ac, pc, hhid)
        if sk not in seen:
            seen.add(sk)
            cell["hh_n"] += 1
            cell["hh_weight"] += meta["Weight"]


def process_part2(path, base, p1, cl):
    hh = defaultdict(lambda: defaultdict(float))
    st = Counter()
    part2_keys = set()
    exceptions = []
    agency = defaultdict(lambda: defaultdict(float))
    interest = defaultdict(lambda: defaultdict(float))
    purpose = defaultdict(lambda: defaultdict(float))
    cross = defaultdict(lambda: defaultdict(float))
    seen = set()
    seen_cross = set()

    loan_fields = [
        "HHID", "Loan_Serial_No", "Sector", "Sector_Name", "State_Region", "State", "District",
        "Household_Group_Code", "Household_Group", "Weight", "Part1_Match_Status",
        "Included_In_Core_Debt_Indicator",
        "Credit_Agency_Code", "Credit_Agency_Label", "Credit_Agency_Class", "Loan_Type_Code",
        "Nature_Interest_Code", "Nature_Interest_Label", "Interest_Rate", "Purpose_Code", "Purpose_Label",
        "Security_Code", "Mortgage_Code", "Outstanding_Principal_SurveyDate_Rs",
        "Outstanding_Interest_SurveyDate_Rs", "Outstanding_Total_SurveyDate_Rs",
        "Cash_Debt_2002_06_30_Rs", "Positive_Debt_2002_Indicator", "Debt_Reference_Date",
    ]

    h, r, enc = open_csv(path)
    with LOAN_FACT_FILE.open("w", encoding="utf-8", newline="") as out:
        w = csv.DictWriter(out, fieldnames=loan_fields)
        w.writeheader()
        try:
            require_fields(r.fieldnames, PART2_REQUIRED, path.name)
            for row in r:
                st["rows"] += 1
                hhid = clean(row.get("HHID"))
                s = serial(row.get("B15_2_q1"))
                if not hhid:
                    st["blank_hhid"] += 1
                    continue
                if not s:
                    st["blank_serial"] += 1
                    continue
                if hhid not in base:
                    st["unmatched_hhid"] += 1
                    continue
                audit_core(row, base[hhid], st)
                key = (hhid, s)
                if key in part2_keys:
                    st["duplicate_key"] += 1
                    continue
                part2_keys.add(key)

                det = p1.get(key)
                if det is None:
                    st["part2_only"] += 1
                    match = "PART2_ONLY"
                    det = {"agency":"", "loan_type":"", "interest_nature":"", "interest_rate":"", "purpose":"", "security":"", "mortgage":""}
                else:
                    st["matched"] += 1
                    match = "MATCHED"

                if not clean(row.get("B15_2_q24")):
                    st["blank_q24"] += 1
                debt = as_float(row.get("B15_2_q24"), blank_zero=True)
                if debt < 0:
                    st["negative_q24"] += 1
                elif debt == 0:
                    st["zero_q24"] += 1
                else:
                    st["positive_q24"] += 1

                meta = base[hhid]
                ac = code(det["agency"], 2)
                acl = agency_class(ac, cl)
                al = agency_label(ac, cl)
                ic = code(det["interest_nature"])
                il = interest_label(ic, cl)
                pc = code(det["purpose"])
                pl = purpose_label(pc, cl)

                # A valid production debt record requires both halves of Block 15.2.
                # Part-2-only rows are retained in the loan audit file but excluded
                # from the core debt numerator because agency/interest/purpose and
                # the first-half loan record are missing. This also reproduces the
                # published Report 501 rural/urban debt totals.
                include_in_core = match == "MATCHED"
                if debt > 0 and include_in_core:
                    st["core_positive_q24"] += 1
                    x = hh[hhid]
                    x["debt"] += debt
                    x["positive_loans"] += 1
                    if acl == "Institutional":
                        x["institutional"] += debt
                    elif acl == "Non-institutional":
                        x["noninstitutional"] += debt
                    else:
                        x["agency_unclassified"] += debt
                    if ic == "1": x["interest_free"] += debt
                    elif ic == "2": x["simple"] += debt
                    elif ic == "3": x["compound"] += debt
                    elif ic == "4": x["concessional"] += debt
                    else: x["interest_unclassified"] += debt

                    add_breakdown(agency, seen, "agency", ac or "UNCLASSIFIED", al, acl, hhid, meta, debt)
                    add_breakdown(interest, seen, "interest", ic or "UNCLASSIFIED", il, "", hhid, meta, debt)
                    add_breakdown(purpose, seen, "purpose", pc or "UNCLASSIFIED", pl, "", hhid, meta, debt)
                    add_cross(cross, seen_cross, ac or "UNCLASSIFIED", pc or "UNCLASSIFIED", hhid, meta, debt)

                if debt > 0 and match == "PART2_ONLY":
                    st["part2_only_positive"] += 1
                    st["part2_only_positive_raw_debt"] += debt
                    st["part2_only_positive_weighted_debt"] += meta["Weight"] * debt

                if match == "PART2_ONLY":
                    exceptions.append({
                        "exception_side":"PART2_ONLY", "HHID":hhid, "Loan_Serial_No":s,
                        "Cash_Debt_2002_06_30_Rs":fmt(debt),
                        "note":"Part 2 loan key has no matching Part 1 classification row",
                    })

                principal = as_float(row.get("B15_2_q21"), blank_zero=True)
                int_amt = as_float(row.get("B15_2_q22"), blank_zero=True)
                total_now = as_float(row.get("B15_2_q23"), blank_zero=True)
                w.writerow({
                    "HHID":hhid, "Loan_Serial_No":s, "Sector":meta["Sector"], "Sector_Name":meta["Sector_Name"],
                    "State_Region":meta["State_Region"], "State":meta["State"], "District":meta["District"],
                    "Household_Group_Code":meta["Household_Group_Code"], "Household_Group":meta["Household_Group"],
                    "Weight":fmt(meta["Weight"]), "Part1_Match_Status":match,
                    "Included_In_Core_Debt_Indicator":"1" if include_in_core else "0",
                    "Credit_Agency_Code":ac, "Credit_Agency_Label":al, "Credit_Agency_Class":acl,
                    "Loan_Type_Code":code(det["loan_type"]), "Nature_Interest_Code":ic,
                    "Nature_Interest_Label":il, "Interest_Rate":clean(det["interest_rate"]),
                    "Purpose_Code":pc, "Purpose_Label":pl, "Security_Code":code(det["security"],2),
                    "Mortgage_Code":code(det["mortgage"]), "Outstanding_Principal_SurveyDate_Rs":fmt(principal),
                    "Outstanding_Interest_SurveyDate_Rs":fmt(int_amt), "Outstanding_Total_SurveyDate_Rs":fmt(total_now),
                    "Cash_Debt_2002_06_30_Rs":fmt(debt), "Positive_Debt_2002_Indicator":"1" if debt > 0 else "0",
                    "Debt_Reference_Date":"2002-06-30",
                })
        finally:
            h.close()

    st["unique_keys"] = len(part2_keys)
    st["encoding"] = enc
    p1_only = sorted(set(p1) - part2_keys)
    for hhid, s in p1_only:
        exceptions.append({
            "exception_side":"PART1_ONLY", "HHID":hhid, "Loan_Serial_No":s,
            "Cash_Debt_2002_06_30_Rs":"", "note":"Part 1 classification row has no matching Part 2 row",
        })
    return hh, st, p1_only, exceptions, agency, interest, purpose, cross


def group_scopes(meta):
    out = [("ALL", "All India"), ("SECTOR", meta["Sector_Name"])]
    if meta["Household_Group"]:
        out.append(("HOUSEHOLD_GROUP", meta["Household_Group"]))
    return out


def build_household_facts(base, order, assets, hh_debt):
    kpi = defaultdict(lambda: defaultdict(float))
    fields = [
        "HHID", "Sector", "Sector_Name", "State_Region", "State", "District",
        "Household_Group_Code", "Household_Group", "Group_Classification_Status", "Weight",
        "Cash_Debt_2002_Rs", "Indebted_Indicator", "Positive_Debt_Loan_Count",
        "Institutional_Debt_Rs", "NonInstitutional_Debt_Rs", "Unclassified_Agency_Debt_Rs",
        "Interest_Free_Debt_Rs", "Simple_Interest_Debt_Rs", "Compound_Interest_Debt_Rs",
        "Concessional_Interest_Debt_Rs", "Unclassified_Interest_Debt_Rs",
        "Total_Assets_Rs", "Debt_Reference_Date",
    ]
    rows = neg = agency_balance = interest_balance = 0
    with HOUSEHOLD_DEBT_FILE.open("w", encoding="utf-8", newline="") as out:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        for hhid in order:
            meta = base[hhid]
            d = hh_debt.get(hhid, {})
            debt = float(d.get("debt", 0.0))
            inst = float(d.get("institutional", 0.0))
            noninst = float(d.get("noninstitutional", 0.0))
            au = float(d.get("agency_unclassified", 0.0))
            ifree = float(d.get("interest_free", 0.0))
            simp = float(d.get("simple", 0.0))
            comp = float(d.get("compound", 0.0))
            conc = float(d.get("concessional", 0.0))
            iu = float(d.get("interest_unclassified", 0.0))
            if debt < 0: neg += 1
            if not near(debt, inst + noninst + au, abs_tol=1e-6): agency_balance += 1
            if not near(debt, ifree + simp + comp + conc + iu, abs_tol=1e-6): interest_balance += 1
            indebted = 1 if debt > 0 else 0
            weight = meta["Weight"]
            av = assets[hhid]
            w.writerow({
                "HHID":hhid, "Sector":meta["Sector"], "Sector_Name":meta["Sector_Name"],
                "State_Region":meta["State_Region"], "State":meta["State"], "District":meta["District"],
                "Household_Group_Code":meta["Household_Group_Code"], "Household_Group":meta["Household_Group"],
                "Group_Classification_Status":meta["Group_Classification_Status"], "Weight":fmt(weight),
                "Cash_Debt_2002_Rs":fmt(debt), "Indebted_Indicator":str(indebted),
                "Positive_Debt_Loan_Count":str(int(d.get("positive_loans", 0))),
                "Institutional_Debt_Rs":fmt(inst), "NonInstitutional_Debt_Rs":fmt(noninst),
                "Unclassified_Agency_Debt_Rs":fmt(au), "Interest_Free_Debt_Rs":fmt(ifree),
                "Simple_Interest_Debt_Rs":fmt(simp), "Compound_Interest_Debt_Rs":fmt(comp),
                "Concessional_Interest_Debt_Rs":fmt(conc), "Unclassified_Interest_Debt_Rs":fmt(iu),
                "Total_Assets_Rs":fmt(av), "Debt_Reference_Date":"2002-06-30",
            })
            rows += 1
            for lvl, label in group_scopes(meta):
                c = kpi[(lvl, label)]
                c["n"] += 1
                c["weight"] += weight
                c["weighted_debt"] += weight * debt
                c["weighted_assets"] += weight * av
                if indebted:
                    c["indebted_n"] += 1
                    c["indebted_weight"] += weight
    return rows, neg, agency_balance, interest_balance, kpi


def metrics(c):
    w = c["weight"]
    iw = c["indebted_weight"]
    wd = c["weighted_debt"]
    wa = c["weighted_assets"]
    return {
        "AOD_Rs_per_HH": wd / w if w else None,
        "AODL_Rs_per_indebted_HH": wd / iw if iw else None,
        "IOI_percent": 100.0 * iw / w if w else None,
        "DAR_percent": 100.0 * wd / wa if wa else None,
    }


def write_kpis(kpi):
    rows = []
    for (lvl, label), c in sorted(kpi.items(), key=lambda x: (x[0][0], x[0][1])):
        m = metrics(c)
        rows.append({
            "group_level":lvl, "group":label, "sample_households":int(c["n"]), "weight_sum":fmt(c["weight"]),
            "indebted_sample_households":int(c["indebted_n"]), "indebted_weight_sum":fmt(c["indebted_weight"]),
            "weighted_debt_sum":fmt(c["weighted_debt"]), "weighted_assets_sum":fmt(c["weighted_assets"]),
            "AOD_Rs_per_HH":fmt(m["AOD_Rs_per_HH"]), "AODL_Rs_per_indebted_HH":fmt(m["AODL_Rs_per_indebted_HH"]),
            "IOI_percent":fmt(m["IOI_percent"]), "DAR_percent":fmt(m["DAR_percent"]),
        })
    write_csv(DEBT_ESTIMATES_FILE, [
        "group_level","group","sample_households","weight_sum","indebted_sample_households","indebted_weight_sum",
        "weighted_debt_sum","weighted_assets_sum","AOD_Rs_per_HH","AODL_Rs_per_indebted_HH","IOI_percent","DAR_percent"
    ], rows)


def validate_controls(methodology, kpi):
    qa = methodology.get("official_qa_controls_for_later_steps", {}).get("debt_2002", {})
    if not qa:
        raise ValueError("Methodology lock has no debt_2002 QA controls")
    rows = []
    for source, label in (("rural","Rural"),("urban","Urban")):
        exp = qa.get(source, {})
        obs = metrics(kpi[("SECTOR", label)])
        specs = [
            ("IOI_percent", exp.get("IOI_percent"), obs["IOI_percent"], IOI_ABS_TOL, "ABS"),
            ("AOD_Rs_per_HH", exp.get("AOD_Rs_per_HH"), obs["AOD_Rs_per_HH"], AOD_REL_TOL, "REL"),
            ("AODL_Rs_per_indebted_HH", exp.get("AODL_Rs_per_indebted_HH"), obs["AODL_Rs_per_indebted_HH"], AODL_REL_TOL, "REL"),
        ]
        for metric, e, o, tol, typ in specs:
            if e is None or o is None:
                passed, diff, pdiff = False, None, None
            else:
                e = float(e)
                diff = o - e
                pdiff = 100.0 * diff / e if e else None
                passed = abs(diff) <= tol if typ == "ABS" else abs(diff / e) <= tol
            rows.append({
                "group":label, "metric":metric, "official_value":fmt(float(e)) if e is not None else "",
                "microdata_value":fmt(o), "difference":fmt(diff), "percent_difference":fmt(pdiff),
                "tolerance":f"+/- {tol} percentage points" if typ == "ABS" else f"+/- {100*tol:.3f}%",
                "status":"PASS" if passed else "FAIL",
            })
    write_csv(DEBT_CONTROLS_FILE, ["group","metric","official_value","microdata_value","difference","percent_difference","tolerance","status"], rows)
    return rows


def denominators(kpi):
    out = {}
    for scope, key in (("All India",("ALL","All India")),("Rural",("SECTOR","Rural")),("Urban",("SECTOR","Urban"))):
        c = kpi.get(key)
        if c:
            out[scope] = (c["weight"], c["weighted_debt"])
    return out


def write_breakdown(path, store, dimension, den):
    rows = []
    for (scope, c, label, klass), cell in sorted(store.items(), key=lambda x: x[0]):
        hw, wd = den.get(scope, (0.0, 0.0))
        rows.append({
            "scope":scope, "dimension":dimension, "code":c, "label":label, "classification":klass,
            "positive_loan_rows":int(cell["loan_rows"]), "reporting_households":int(cell["hh_n"]),
            "reporting_weight":fmt(cell["hh_weight"]),
            "incidence_per_1000_households":fmt(1000.0 * cell["hh_weight"] / hw if hw else None),
            "raw_debt_sum_rs":fmt(cell["raw_debt"]), "weighted_debt_sum":fmt(cell["weighted_debt"]),
            "share_of_weighted_debt_percent":fmt(100.0 * cell["weighted_debt"] / wd if wd else None),
        })
    write_csv(path, [
        "scope","dimension","code","label","classification","positive_loan_rows","reporting_households","reporting_weight",
        "incidence_per_1000_households","raw_debt_sum_rs","weighted_debt_sum","share_of_weighted_debt_percent"
    ], rows)


def write_cross(store, cl, den):
    rows = []
    for (scope, ac, pc), cell in sorted(store.items(), key=lambda x: x[0]):
        hw, wd = den.get(scope, (0.0, 0.0))
        ac_real = "" if ac == "UNCLASSIFIED" else ac
        pc_real = "" if pc == "UNCLASSIFIED" else pc
        rows.append({
            "scope":scope, "credit_agency_code":ac, "credit_agency_label":agency_label(ac_real, cl),
            "credit_agency_class":"Unclassified" if not ac_real else agency_class(ac_real, cl),
            "purpose_code":pc, "purpose_label":purpose_label(pc_real, cl),
            "positive_loan_rows":int(cell["loan_rows"]), "reporting_households":int(cell["hh_n"]),
            "reporting_weight":fmt(cell["hh_weight"]),
            "incidence_per_1000_households":fmt(1000.0 * cell["hh_weight"] / hw if hw else None),
            "raw_debt_sum_rs":fmt(cell["raw_debt"]), "weighted_debt_sum":fmt(cell["weighted_debt"]),
            "share_of_weighted_debt_percent":fmt(100.0 * cell["weighted_debt"] / wd if wd else None),
        })
    write_csv(AGENCY_PURPOSE_FILE, [
        "scope","credit_agency_code","credit_agency_label","credit_agency_class","purpose_code","purpose_label",
        "positive_loan_rows","reporting_households","reporting_weight","incidence_per_1000_households",
        "raw_debt_sum_rs","weighted_debt_sum","share_of_weighted_debt_percent"
    ], rows)


def main():
    print("=" * 78)
    print("AIDIS 2003 - STEP 04 DEBT / CREDIT FACTS [V2 ORPHAN FILTER]")
    print("Build 30-06-2002 cash debt from matched Visit-1 Block 15.2 loan records")
    print("=" * 78)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    errors, warnings, checks = [], [], []

    print("\n[1] Step prerequisites")
    try:
        methodology = load_methodology()
        manifest = load_manifest()
        base, order = load_stock_base()
        assets = load_assets(base)
        part1_path = manifest_source(manifest, PART1_NAMES)
        part2_path = manifest_source(manifest, PART2_NAMES)
        cl = classifiers(methodology)
        print("Methodology lock          : PASS")
        print(f"Step 02 stock households  : {len(base):,}")
        print(f"Step 03 asset households  : {len(assets):,}")
        print(f"Production manifest       : PASS ({len(manifest)}/42)")
        print(f"Block 15.2 part 1         : {part1_path.name}")
        print(f"Block 15.2 part 2         : {part2_path.name}")
        add_check(checks, "stock_households", EXPECTED_STOCK_HOUSEHOLDS, len(base), len(base) == EXPECTED_STOCK_HOUSEHOLDS)
        add_check(checks, "asset_households", EXPECTED_STOCK_HOUSEHOLDS, len(assets), len(assets) == EXPECTED_STOCK_HOUSEHOLDS)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print("\nSTEP 04 STATUS: FAIL")
        return 1

    print("\n[2] Block 15.2 part 1 - loan classifications")
    try:
        p1, s1 = load_part1(part1_path, base)
        print(f"Part1 source rows          : {s1['rows']:,}")
        print(f"Part1 unique loan keys     : {s1['unique_keys']:,}")
        print(f"Part1 duplicate keys       : {s1['duplicate_key']}")
        print(f"Part1 unmatched HHID       : {s1['unmatched_hhid']}")
        print(f"Part1 core mismatches      : {s1['core_mismatch']}")
        print(f"Part1 Weight mismatches    : {s1['weight_mismatch']}")
        for name, exp, obs in [
            ("part1_source_rows", EXPECTED_PART1_ROWS, s1["rows"]), ("part1_duplicate_keys",0,s1["duplicate_key"]),
            ("part1_blank_hhid",0,s1["blank_hhid"]), ("part1_blank_serial",0,s1["blank_serial"]),
            ("part1_unmatched_hhid",0,s1["unmatched_hhid"]), ("part1_non_visit1",0,s1["non_visit1"]),
            ("part1_core_mismatch",0,s1["core_mismatch"]), ("part1_weight_mismatch",0,s1["weight_mismatch"]),
        ]:
            add_check(checks, name, exp, obs, exp == obs)
            if exp != obs: errors.append(f"{name}: expected {exp}, observed {obs}")
    except Exception as exc:
        errors.append(f"Block15.2 part1 failed: {type(exc).__name__}: {exc}")
        p1, s1 = {}, Counter()

    print("\n[3] Block 15.2 part 2 - debt amount / join")
    result = None
    if p1:
        try:
            result = process_part2(part2_path, base, p1, cl)
            hh_debt, s2, p1_only, exceptions, agency, interest, purpose, cross = result
            print(f"Part2 source rows          : {s2['rows']:,}")
            print(f"Part2 unique loan keys     : {s2['unique_keys']:,}")
            print(f"Matched part1 keys         : {s2['matched']:,}")
            print(f"Part2-only loan keys       : {s2['part2_only']:,}")
            print(f"Part1-only loan keys       : {len(p1_only):,}")
            print(f"Blank B15_2_q24 rows       : {s2['blank_q24']:,}")
            print(f"Positive raw debt rows     : {s2['positive_q24']:,}")
            print(f"Positive core debt rows    : {s2['core_positive_q24']:,}")
            print(f"Negative B15_2_q24 rows    : {s2['negative_q24']}")
            print(f"Part2 core mismatches      : {s2['core_mismatch']}")
            print(f"Part2 Weight mismatches    : {s2['weight_mismatch']}")
            for name, exp, obs in [
                ("part2_source_rows", EXPECTED_PART2_ROWS, s2["rows"]), ("part2_duplicate_keys",0,s2["duplicate_key"]),
                ("part2_blank_hhid",0,s2["blank_hhid"]), ("part2_blank_serial",0,s2["blank_serial"]),
                ("part2_unmatched_hhid",0,s2["unmatched_hhid"]), ("part2_non_visit1",0,s2["non_visit1"]),
                ("part2_core_mismatch",0,s2["core_mismatch"]), ("part2_weight_mismatch",0,s2["weight_mismatch"]),
                ("negative_reference_debt_rows",0,s2["negative_q24"]),
            ]:
                add_check(checks, name, exp, obs, exp == obs)
                if exp != obs: errors.append(f"{name}: expected {exp}, observed {obs}")
            if s2["part2_only"]:
                warnings.append(f"{s2['part2_only']} part2 loan key(s) have no matching part1 classification row")
            if p1_only:
                warnings.append(f"{len(p1_only)} part1 loan key(s) have no matching part2 row")
            if s2["part2_only_positive"]:
                warnings.append(
                    f"{s2['part2_only_positive']} positive 30-06-2002 Part2-only loan row(s) were "
                    f"excluded from the core debt estimate because they have no matching Part1 loan record; "
                    f"weighted raw debt excluded={s2['part2_only_positive_weighted_debt']:.6f}. "
                    "The rows remain in the loan-level audit output with Included_In_Core_Debt_Indicator=0."
                )
            write_csv(JOIN_AUDIT_FILE, ["metric","value"], [
                {"metric":"part1_source_rows","value":s1["rows"]}, {"metric":"part1_unique_keys","value":s1["unique_keys"]},
                {"metric":"part2_source_rows","value":s2["rows"]}, {"metric":"part2_unique_keys","value":s2["unique_keys"]},
                {"metric":"matched_keys","value":s2["matched"]}, {"metric":"part2_only_keys","value":s2["part2_only"]},
                {"metric":"part1_only_keys","value":len(p1_only)}, {"metric":"blank_q24","value":s2["blank_q24"]},
                {"metric":"positive_q24_raw","value":s2["positive_q24"]},
                {"metric":"positive_q24_core_matched","value":s2["core_positive_q24"]},
                {"metric":"negative_q24","value":s2["negative_q24"]},
                {"metric":"part2_only_positive_rows","value":s2["part2_only_positive"]},
                {"metric":"part2_only_positive_raw_debt","value":fmt(s2["part2_only_positive_raw_debt"])},
                {"metric":"part2_only_positive_weighted_debt","value":fmt(s2["part2_only_positive_weighted_debt"])},
            ])
            write_csv(JOIN_EXCEPTIONS_FILE, ["exception_side","HHID","Loan_Serial_No","Cash_Debt_2002_06_30_Rs","note"], exceptions)
        except Exception as exc:
            errors.append(f"Block15.2 part2 failed: {type(exc).__name__}: {exc}")

    print("\n[4] Build household debt facts")
    kpi = None
    household_rows = 0
    if result is not None:
        try:
            household_rows, neg, ab, ib, kpi = build_household_facts(base, order, assets, hh_debt)
            print(f"Household debt rows        : {household_rows:,}")
            print(f"Negative household debt    : {neg}")
            print(f"Agency allocation errors   : {ab}")
            print(f"Interest allocation errors : {ib}")
            for name, exp, obs in [
                ("household_debt_rows", EXPECTED_STOCK_HOUSEHOLDS, household_rows),
                ("negative_household_debt",0,neg), ("agency_allocation_errors",0,ab), ("interest_allocation_errors",0,ib),
            ]:
                add_check(checks, name, exp, obs, exp == obs)
                if exp != obs: errors.append(f"{name}: expected {exp}, observed {obs}")
            write_kpis(kpi)
        except Exception as exc:
            errors.append(f"Household debt fact build failed: {type(exc).__name__}: {exc}")

    print("\n[5] Official Report No. 501 debt controls")
    controls, failed_controls = [], 0
    if kpi is not None:
        try:
            controls = validate_controls(methodology, kpi)
            for row in controls:
                print(
                    f"{row['status']:4s} | {row['group']:5s} | {row['metric']:28s} | "
                    f"official={float(row['official_value']):>12,.3f} | microdata={float(row['microdata_value']):>12,.3f}"
                )
            failed_controls = sum(x["status"] != "PASS" for x in controls)
            add_check(checks, "official_debt_controls", len(controls), len(controls)-failed_controls, failed_controls == 0)
            if failed_controls: errors.append(f"{failed_controls} official debt control(s) failed")
        except Exception as exc:
            errors.append(f"Official debt controls failed: {type(exc).__name__}: {exc}")

    print("\n[6] Credit breakdown outputs")
    if kpi is not None and result is not None:
        try:
            den = denominators(kpi)
            write_breakdown(AGENCY_BREAKDOWN_FILE, agency, "Credit agency", den)
            write_breakdown(INTEREST_BREAKDOWN_FILE, interest, "Nature of interest", den)
            write_breakdown(PURPOSE_BREAKDOWN_FILE, purpose, "Purpose of loan", den)
            write_cross(cross, cl, den)
            print(f"Agency breakdown            : {AGENCY_BREAKDOWN_FILE}")
            print(f"Interest breakdown          : {INTEREST_BREAKDOWN_FILE}")
            print(f"Purpose breakdown           : {PURPOSE_BREAKDOWN_FILE}")
            print(f"Agency x purpose            : {AGENCY_PURPOSE_FILE}")
        except Exception as exc:
            errors.append(f"Breakdown output failed: {type(exc).__name__}: {exc}")

    write_csv(CHECKS_FILE, ["check","expected","observed","status","note"], checks)
    failed_checks = sum(x["status"] != "PASS" for x in checks)
    status = "PASS" if not errors and failed_checks == 0 else "FAIL"

    all_metrics = metrics(kpi[("ALL","All India")]) if kpi is not None else None
    s2 = result[1] if result is not None else Counter()
    p1_only = result[2] if result is not None else []
    summary = [
        "="*78, "AIDIS 2003 - STEP 04 DEBT / CREDIT FACTS SUMMARY", "="*78,
        f"Stock household universe      : {len(base):,}",
        f"Part1 source rows             : {s1['rows'] if s1 else 0:,}",
        f"Part2 source rows             : {s2['rows'] if s2 else 0:,}",
        f"Matched loan keys             : {s2['matched'] if s2 else 0:,}",
        f"Part2-only loan keys          : {s2['part2_only'] if s2 else 0:,}",
        f"Part1-only loan keys          : {len(p1_only):,}",
        f"Positive raw q24 loan rows     : {s2['positive_q24'] if s2 else 0:,}",
        f"Positive core matched rows     : {s2['core_positive_q24'] if s2 else 0:,}",
        f"Household debt fact rows      : {household_rows:,}",
        f"Official debt controls        : {len(controls)}",
        f"Failed debt controls          : {failed_controls}",
        f"Validation checks             : {len(checks)}",
        f"Failed validation checks      : {failed_checks}",
        f"Warnings                      : {len(warnings)}",
        f"Errors                        : {len(errors)}", "",
    ]
    if all_metrics:
        summary += [
            "ALL-INDIA DERIVED CORE METRICS:",
            f"  AOD Rs/HH                  : {all_metrics['AOD_Rs_per_HH']:.6f}",
            f"  AODL Rs/indebted HH        : {all_metrics['AODL_Rs_per_indebted_HH']:.6f}",
            f"  IOI percent                : {all_metrics['IOI_percent']:.6f}",
            f"  DAR percent                : {all_metrics['DAR_percent']:.6f}", "",
        ]
    summary += [
        "LOCKED DEBT RULES:",
        "  - Core debt = cash loans payable outstanding on 30-06-2002.",
        "  - Source amount = Visit1 Block15.2 part2 B15_2_q24.",
        "  - Loan join key = HHID + B15_2_q1.",
        "  - Part1 supplies agency / interest / purpose classifications.",
        "  - A core loan record must match Part1 + Part2 on HHID + B15_2_q1.",
        "  - Part2-only continuation rows are retained for audit but excluded from core debt.",
        "  - Aggregate matched loan debt to HHID before applying household Weight.",
        "  - Indebted household = household cash debt > 0.",
        "  - Block14 is asset-side loans receivable, not payable debt.",
        "  - Block16/current liabilities are outside the locked core cash-debt metric.", "",
        f"Loan facts                     : {LOAN_FACT_FILE}",
        f"Household debt facts           : {HOUSEHOLD_DEBT_FILE}",
        f"Join audit                     : {JOIN_AUDIT_FILE}",
        f"Join exceptions                : {JOIN_EXCEPTIONS_FILE}",
        f"Debt controls                  : {DEBT_CONTROLS_FILE}",
        f"Debt KPI estimates             : {DEBT_ESTIMATES_FILE}",
        f"Agency breakdown               : {AGENCY_BREAKDOWN_FILE}",
        f"Interest breakdown             : {INTEREST_BREAKDOWN_FILE}",
        f"Purpose breakdown              : {PURPOSE_BREAKDOWN_FILE}",
        f"Agency-purpose breakdown       : {AGENCY_PURPOSE_FILE}",
        f"Checks CSV                     : {CHECKS_FILE}", "",
    ]
    if warnings:
        summary += ["WARNINGS:"] + [f"  - {x}" for x in warnings] + [""]
    if errors:
        summary += ["ERRORS:"] + [f"  - {x}" for x in errors] + [""]
    summary += [f"STEP 04 STATUS: {status}", "="*78]
    SUMMARY_FILE.write_text("\n".join(summary), encoding="utf-8")

    print("\n" + "="*78)
    print("AIDIS 2003 - STEP 04 SUMMARY")
    print("="*78)
    print(f"Stock household universe     : {len(base):,}")
    print(f"Part1 source rows            : {s1['rows'] if s1 else 0:,}")
    print(f"Part2 source rows            : {s2['rows'] if s2 else 0:,}")
    print(f"Matched loan keys            : {s2['matched'] if s2 else 0:,}")
    print(f"Part2-only loan keys         : {s2['part2_only'] if s2 else 0:,}")
    print(f"Part1-only loan keys         : {len(p1_only):,}")
    print(f"Positive raw debt rows       : {s2['positive_q24'] if s2 else 0:,}")
    print(f"Positive core debt rows      : {s2['core_positive_q24'] if s2 else 0:,}")
    print(f"Household debt fact rows     : {household_rows:,}")
    print(f"Official debt controls       : {len(controls)}")
    print(f"Failed debt controls         : {failed_controls}")
    print(f"Validation checks            : {len(checks)}")
    print(f"Failed validation checks     : {failed_checks}")
    print(f"Warnings                     : {len(warnings)}")
    print(f"Errors                       : {len(errors)}")
    print(f"Loan facts                   : {LOAN_FACT_FILE}")
    print(f"Household debt facts         : {HOUSEHOLD_DEBT_FILE}")
    print(f"Debt controls                : {DEBT_CONTROLS_FILE}")
    print(f"Debt KPI estimates           : {DEBT_ESTIMATES_FILE}")
    print(f"Checks CSV                   : {CHECKS_FILE}")
    print(f"Summary                      : {SUMMARY_FILE}")
    print()
    print(f"STEP 04 STATUS: {status}")
    print("="*78)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())