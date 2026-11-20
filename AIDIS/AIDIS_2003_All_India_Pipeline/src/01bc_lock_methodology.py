from pathlib import Path
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict


# =============================================================================
# AIDIS 2003 - STEP 01B-C METHODOLOGY LOCK
# NSS 59th Round, Schedule 18.2 (Debt & Investment)
#
# This step does NOT calculate final KPIs. It freezes the estimator, visit,
# reference-period, household-group, debt, credit-agency and flow rules that
# downstream Steps 02-05 must follow.
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
CONFIG_DIR = ROOT / "config"
REPORT_DIR = ROOT / "output" / "reports"
REFERENCE_DIR = ROOT / "input" / "reference"

PRODUCTION_MANIFEST = CACHE_DIR / "step01_production_manifest.csv"
RESOLVED_MAPPING = CACHE_DIR / "step01b_variable_mapping_resolved.csv"
UNRESOLVED_AFTER = CACHE_DIR / "step01b_unresolved_variables_after_resolution.csv"
RESOLVED_CONFIG = CONFIG_DIR / "aidis_2003_variable_map_resolved.json"

CHECKS_FILE = CACHE_DIR / "step01bc_methodology_checks.csv"
METHODOLOGY_FILE = CONFIG_DIR / "aidis_2003_methodology_lock.json"
SUMMARY_FILE = REPORT_DIR / "step01bc_methodology_lock_summary.txt"

EXPECTED_REFERENCES = [
    "Schedule_V1_18.pdf",
    "Schedule_V2_18.pdf",
    "500_final.pdf",
    "501_final.pdf",
    "502_final.pdf",
    "503_final.pdf",
    "504_final.pdf",
]

EXPECTED_VISIT1_ROWS = 143_285
EXPECTED_VISIT1_SECTOR = {"1": 91_192, "2": 52_093}

EXPECTED_COMBINED_ROWS = 278_078
EXPECTED_PANEL_HOUSEHOLDS = 139_039
EXPECTED_COMBINED_VISIT_ROWS = {"1": 139_039, "2": 139_039}
EXPECTED_COMBINED_SECTOR_PER_VISIT = {
    "1": {"1": 89_718, "2": 49_321},
    "2": {"1": 89_718, "2": 49_321},
}

CORE_ID_FIELDS = [
    "HHID", "Sector", "State", "District", "Visit_no", "NSS", "NSC", "MLT", "Weight"
]


# =============================================================================
# HELPERS
# =============================================================================

def clean(value):
    return "" if value is None else str(value).strip()


def norm_name(value):
    return re.sub(r"[^a-z0-9]+", "", clean(value).casefold())


def add_check(rows, name, expected, observed, passed, note=""):
    rows.append({
        "check": name,
        "expected": str(expected),
        "observed": str(observed),
        "status": "PASS" if passed else "FAIL",
        "note": note,
    })


def read_manifest():
    if not PRODUCTION_MANIFEST.exists():
        raise FileNotFoundError(f"Missing Step 01D manifest: {PRODUCTION_MANIFEST}")

    with PRODUCTION_MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    return rows


def find_manifest_source(manifest, logical_name):
    target = norm_name(logical_name)
    matches = [r for r in manifest if norm_name(r.get("logical_dataset")) == target]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one manifest row for {logical_name}; found {len(matches)}"
        )
    path = Path(matches[0]["source_path"])
    if not path.exists():
        raise FileNotFoundError(f"Manifest source does not exist: {path}")
    return path, matches[0]


def open_csv_dict(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            handle = path.open("r", encoding=encoding, newline="")
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                handle.close()
                raise ValueError("empty CSV header")
            return handle, reader, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
            break
    raise RuntimeError(f"Unable to read {path.name}: {last_error}")


def require_fields(fieldnames, required, dataset_label):
    present = {norm_name(x): x for x in fieldnames or []}
    missing = [x for x in required if norm_name(x) not in present]
    if missing:
        raise ValueError(f"{dataset_label}: missing fields {missing}")


def as_float(value):
    text = clean(value)
    if not text:
        return None
    return float(text)


def weight_expected(mlt, nss, nsc):
    # Validated against all identification rows in this microdata package.
    # NSS 59th Round final Weight is MLT/200 when NSC>NSS, else MLT/100.
    divisor = 200.0 if nsc > nss else 100.0
    return mlt / divisor


def nearly_equal(a, b):
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=5e-7)


def derive_panel_hhid(hhid, visit_no):
    """
    Combined-file HHID is visit-specific. In this package the visit number is
    the 8th character (1-based). Removing that one character creates a stable
    9-character cross-visit household key.
    """
    hhid = clean(hhid)
    visit_no = clean(visit_no)
    if len(hhid) != 10:
        return None, "HHID length is not 10"
    if hhid[7] != visit_no:
        return None, f"HHID visit digit {hhid[7]!r} != Visit_no {visit_no!r}"
    return hhid[:7] + hhid[8:], ""


def scan_visit1_identification(path):
    result = {
        "rows": 0,
        "sector": Counter(),
        "visit": Counter(),
        "weight_mismatches": 0,
        "weight_parse_errors": 0,
        "encoding": "",
    }

    handle, reader, encoding = open_csv_dict(path)
    result["encoding"] = encoding
    try:
        require_fields(reader.fieldnames, CORE_ID_FIELDS, path.name)
        for row in reader:
            result["rows"] += 1
            sector = clean(row.get("Sector"))
            visit = clean(row.get("Visit_no"))
            result["sector"][sector] += 1
            result["visit"][visit] += 1

            try:
                mlt = as_float(row.get("MLT"))
                weight = as_float(row.get("Weight"))
                nss = as_float(row.get("NSS"))
                nsc = as_float(row.get("NSC"))
                if None in (mlt, weight, nss, nsc):
                    result["weight_parse_errors"] += 1
                    continue
                expected = weight_expected(mlt, nss, nsc)
                if not nearly_equal(weight, expected):
                    result["weight_mismatches"] += 1
            except Exception:
                result["weight_parse_errors"] += 1
    finally:
        handle.close()

    return result


def scan_combined_identification(path):
    result = {
        "rows": 0,
        "visit": Counter(),
        "sector_by_visit": defaultdict(Counter),
        "weight_mismatches": 0,
        "weight_parse_errors": 0,
        "panel_format_errors": 0,
        "panel_visit_mask": {},
        "panel_sector": {},
        "panel_geo_mismatches": 0,
        "encoding": "",
    }

    # panel_geo keeps only state/district/sector to validate that a paired HH
    # stays in the same reporting domain across the two visits.
    panel_geo = {}

    handle, reader, encoding = open_csv_dict(path)
    result["encoding"] = encoding
    try:
        require_fields(reader.fieldnames, CORE_ID_FIELDS, path.name)
        for row in reader:
            result["rows"] += 1
            visit = clean(row.get("Visit_no"))
            sector = clean(row.get("Sector"))
            result["visit"][visit] += 1
            result["sector_by_visit"][visit][sector] += 1

            try:
                mlt = as_float(row.get("MLT"))
                weight = as_float(row.get("Weight"))
                nss = as_float(row.get("NSS"))
                nsc = as_float(row.get("NSC"))
                if None in (mlt, weight, nss, nsc):
                    result["weight_parse_errors"] += 1
                else:
                    expected = weight_expected(mlt, nss, nsc)
                    if not nearly_equal(weight, expected):
                        result["weight_mismatches"] += 1
            except Exception:
                result["weight_parse_errors"] += 1

            panel, err = derive_panel_hhid(row.get("HHID"), visit)
            if panel is None:
                result["panel_format_errors"] += 1
                continue

            bit = 1 if visit == "1" else 2 if visit == "2" else 0
            result["panel_visit_mask"][panel] = result["panel_visit_mask"].get(panel, 0) | bit

            geo = (
                clean(row.get("Sector")),
                clean(row.get("State")),
                clean(row.get("District")),
            )
            if panel in panel_geo and panel_geo[panel] != geo:
                result["panel_geo_mismatches"] += 1
            else:
                panel_geo.setdefault(panel, geo)
            result["panel_sector"].setdefault(panel, sector)
    finally:
        handle.close()

    result["panel_count"] = len(result["panel_visit_mask"])
    result["complete_panels"] = sum(1 for mask in result["panel_visit_mask"].values() if mask == 3)
    result["incomplete_panels"] = result["panel_count"] - result["complete_panels"]
    result["panel_sector_counts"] = Counter(result["panel_sector"].values())

    # Do not keep the large dicts in the final report payload.
    del result["panel_visit_mask"]
    del result["panel_sector"]

    return result


def count_unresolved_rows(path):
    if not path.exists():
        raise FileNotFoundError(f"Missing Step 01B-B output: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def write_checks(rows):
    CHECKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CHECKS_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["check", "expected", "observed", "status", "note"],
        )
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# LOCKED METHODOLOGY
# =============================================================================

def build_methodology_config(visit1_source, combined_source, validations):
    return {
        "survey": {
            "survey_name": "Debt & Investment, Jan - Dec 2003",
            "round": "NSS 59th Round",
            "schedule": "18.2",
            "country": "India",
            "stock_reference_date": "2002-06-30",
            "capital_expenditure_reference_period": {
                "start": "2002-07-01",
                "end": "2003-06-30",
            },
            "fieldwork": {
                "visit_1": "Jan-Aug 2003",
                "visit_2": "Sep-Dec 2003",
            },
        },
        "production_sources": {
            "visit1_identification": str(visit1_source),
            "combined_identification": str(combined_source),
            "production_manifest": str(PRODUCTION_MANIFEST),
            "resolved_variable_mapping": str(RESOLVED_MAPPING),
            "resolved_variable_config": str(RESOLVED_CONFIG),
        },
        "estimation": {
            "locked_weight_field": "Weight",
            "do_not_use_raw_mlt_directly": True,
            "weight_rule": "Weight = MLT/200 when NSC > NSS; otherwise MLT/100",
            "weight_rule_validated_against_microdata": True,
            "ratio_estimator_pattern": "sum(Weight * numerator) / sum(Weight * denominator_indicator)",
            "missing_weight_policy": "Fail/flag record; never silently replace with 1",
        },
        "visit_and_panel_strategy": {
            "stock_kpis": {
                "source": "Visit 1",
                "reason": "Assets/liabilities are estimated as on 30-06-2002; stock reconstruction is based on Visit-1 information.",
                "household_universe": "Visit-1 surveyed households",
                "expected_households": EXPECTED_VISIT1_ROWS,
            },
            "full_year_flow_kpis": {
                "source": "Visit 1 & 2 Combined",
                "reason": "The two visits supply the two half-year portions required for 01-07-2002 to 30-06-2003 flow estimates.",
                "household_universe": "Households canvassed in both visits",
                "expected_panel_households": EXPECTED_PANEL_HOUSEHOLDS,
                "aggregation": "Aggregate visit-specific flow facts to PANEL_HHID, then estimate once per household using one household Weight.",
            },
            "panel_key": {
                "name": "PANEL_HHID",
                "derivation": "Remove the 8th character (1-based) from the 10-character visit-specific HHID.",
                "python_equivalent": "HHID[:7] + HHID[8:]",
                "validation": "Each PANEL_HHID must have exactly Visit_no 1 and Visit_no 2.",
                "use_for_cross_visit_join": True,
                "do_not_join_visits_on_raw_hhid": True,
            },
        },
        "sector_codes": {
            "1": "Rural",
            "2": "Urban",
        },
        "household_groups": {
            "rural": {
                "cultivator": {
                    "rule": "B3_q8 >= 0.002 hectares",
                    "official_definition": "Household operated at least 0.002 hectare for agricultural activities during the last 365 days.",
                },
                "non_cultivator": {
                    "rule": "B3_q8 < 0.002 hectares or no operated land",
                },
                "important_note": "Do not substitute household-type code B3_q4=4 for the official cultivator definition.",
            },
            "urban": {
                "self_employed": {
                    "rule": "B3_q4 == 1",
                    "description": "Major source of household income during last 365 days was self-employment.",
                },
                "others": {
                    "rule": "B3_q4 in {2,3,9}",
                    "description": "Regular wage/salary, casual labour, and other households.",
                },
            },
        },
        "geography": {
            "state_code_field": "State",
            "district_code_field": "District",
            "state_region_field": "State_Region",
            "policy": "Use NSS 59th Round / survey-era geography. Do not remap observations to present-day states or districts.",
            "name_mapping": "Build/use a 2003 survey-era state/district codebook; preserve original codes in final output.",
        },
        "assets": {
            "reference_date": "2002-06-30",
            "universe": "Visit 1 households",
            "asset_side_blocks": [
                "5 Land",
                "6 Buildings and constructions",
                "7 Livestock and poultry",
                "8 Agricultural machinery and implements",
                "9 Non-farm business equipment",
                "10 Transport equipment",
                "11 Durable assets",
                "12 Shares and debentures",
                "13 Other financial assets",
                "14 Loans receivable",
            ],
            "block14_treatment": "Loans receivable are assets. Never include Block 14 in household payable debt.",
            "valuation_principle": "Use official as-on-30-06-2002 values where directly supplied; otherwise reconstruct the 30-06-2002 stock from schedule-prescribed stock/transaction fields.",
            "household_total_asset_value": "Sum all non-overlapping physical and financial asset components at household level before weighting.",
            "ava": "Weighted mean household total asset value = sum(Weight*HH_asset_value)/sum(Weight).",
            "gini_asset": "Client-derived weighted Gini of household total asset value; disclose as derived, not an official published NSS statistic unless independently matched to a publication.",
            "asset_deciles": "Client-derived weighted deciles of household total asset value; do not confuse with published asset-holding classes.",
        },
        "debt": {
            "reference_date": "2002-06-30",
            "core_debt_definition": "Cash loans payable outstanding as on 30-06-2002.",
            "source": "Visit1 Block 15.2",
            "loan_join_key": ["HHID", "B15_2_q1"],
            "part1_fields": {
                "credit_agency": "B15_2_q6",
                "nature_of_interest": "B15_2_q9",
                "rate_of_interest": "B15_2_q10",
                "purpose": "B15_2_q11",
            },
            "part2_fields": {
                "amount_outstanding_2002_06_30": "B15_2_q24",
            },
            "indebted_household_rule": "Household is indebted when summed B15_2_q24 cash-loan debt > 0.",
            "block16_policy": "Kind loans and other liabilities are not included in the core AOD/IOI/DAR cash-debt metric; retain separately if a client output explicitly requires them.",
            "formulas": {
                "AOD_Rs_per_HH": "sum(Weight*HH_cash_debt)/sum(Weight)",
                "AODL_Rs_per_indebted_HH": "sum(Weight*HH_cash_debt)/sum(Weight*indebted_indicator)",
                "IOI_percent": "100*sum(Weight*indebted_indicator)/sum(Weight)",
                "DAR_percent": "100*sum(Weight*HH_cash_debt)/sum(Weight*HH_total_asset_value)",
            },
        },
        "credit_agency_codes": {
            "institutional_codes": ["01", "02", "03", "04", "05", "06", "07", "08"],
            "non_institutional_codes": ["09", "10", "11", "12", "13", "14", "99"],
            "labels": {
                "01": "Government",
                "02": "Co-operative society / co-operative bank",
                "03": "Commercial bank including regional rural bank",
                "04": "Insurance",
                "05": "Provident fund",
                "06": "Financial corporation / institution",
                "07": "Financial company",
                "08": "Other institutional agency",
                "09": "Landlord",
                "10": "Agriculturist money lender",
                "11": "Professional money lender",
                "12": "Trader",
                "13": "Relatives and friends",
                "14": "Doctors, lawyers and other professionals",
                "99": "Other agency",
            },
        },
        "interest_nature_codes": {
            "1": "Interest free",
            "2": "Simple",
            "3": "Compound",
            "4": "Concessional rate",
        },
        "loan_purpose_codes": {
            "1": "Capital expenditure in farm business",
            "2": "Current expenditure in farm business",
            "3": "Capital expenditure in non-farm business",
            "4": "Current expenditure in non-farm business",
            "5": "Household expenditure",
            "6": "Litigation",
            "7": "Repayment of debt",
            "8": "Financial investment expenditure",
            "9": "Other purpose",
        },
        "capital_expenditure": {
            "reference_period": "2002-07-01 to 2003-06-30",
            "source": "Visit 1 & 2 Combined Blocks 17 and 18 with schedule-specific item coding",
            "fce_definition": "Fixed capital expenditure: purchase/construction/additions/alterations/improvements/major repairs of fixed assets, including eligible home-produced inputs and household labour, following the schedule/report rules.",
            "epl_definition": "Expenditure on purchase of land; keep separate from fixed capital expenditure where the official report does so.",
            "normal_repairs": "Recurring normal repairs/maintenance are tracked separately and must not be mixed into FCE unless the official table definition explicitly requires them.",
        },
        "official_qa_controls_for_later_steps": {
            "debt_2002": {
                "rural": {
                    "IOI_percent": 26.5,
                    "AOD_Rs_per_HH": 7539,
                    "AODL_Rs_per_indebted_HH": 28449,
                },
                "urban": {
                    "IOI_percent": 17.8,
                    "AOD_Rs_per_HH": 11771,
                    "AODL_Rs_per_indebted_HH": 66129,
                },
                "usage": "Validation controls for Step 04; allow only explainable publication-rounding differences.",
            },
        },
        "documented_client_limitations": [
            {
                "code": "SCB_RRB_NOT_SEPARABLE",
                "severity": "NONBLOCKING_DISCLOSURE",
                "detail": "2003 credit-agency code 03 combines commercial banks including RRBs. Do not fabricate separate SCB and RRB estimates from this field.",
            },
            {
                "code": "COOP_BANK_SOCIETY_COMBINED",
                "severity": "NONBLOCKING_DISCLOSURE",
                "detail": "Credit-agency code 02 combines co-operative society and co-operative bank in the schedule classification.",
            },
            {
                "code": "ADULT_BANK_ACCOUNT_GENDER_NOT_DIRECT",
                "severity": "NONBLOCKING_DISCLOSURE",
                "detail": "The available person-level Block 4 does not directly provide individual bank-account ownership. Do not manufacture total/male/female adult bank-account indicators without an independently supported variable or external source.",
            },
            {
                "code": "NBFC_LABEL_CAUTION",
                "severity": "NONBLOCKING_DISCLOSURE",
                "detail": "Code 07 is officially labelled financial company. If presented as NBFC, label the transformation/disclosure explicitly rather than silently renaming the category.",
            },
        ],
        "pipeline_invariants": [
            "Aggregate one-to-many fact blocks to household level before joining to the household base.",
            "Never multiply household Weight by the number of asset/loan/item rows.",
            "Use raw HHID for joins within a single visit and PANEL_HHID for cross-visit joins.",
            "For paired-flow estimates, use one household Weight after visit-level facts have been consolidated to PANEL_HHID.",
            "Preserve 2003 State/District codes alongside mapped names.",
            "Do not reuse NSS 77th Round variable formulas or geography mappings unless independently proven identical for NSS 59th Round.",
        ],
        "validation_snapshot": validations,
        "reference_documents": EXPECTED_REFERENCES,
        "methodology_lock_status": "LOCKED",
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 78)
    print("AIDIS 2003 - STEP 01B-C METHODOLOGY LOCK")
    print("NSS 59th Round - freeze estimator, visit, panel and KPI rules")
    print("=" * 78)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    checks = []
    errors = []
    limitations = []

    # -------------------------------------------------------------------------
    # 1. Prerequisite files
    # -------------------------------------------------------------------------
    print("\n[1] Step prerequisites")

    try:
        manifest = read_manifest()
        manifest_pass = sum(1 for r in manifest if clean(r.get("status")).upper() == "PASS")
        ok = len(manifest) == 42 and manifest_pass == 42
        add_check(checks, "production_manifest_42_pass", "42 PASS rows", f"{len(manifest)} rows; {manifest_pass} PASS", ok)
        print(f"Production manifest        : {'PASS' if ok else 'FAIL'} ({len(manifest)} rows, {manifest_pass} PASS)")
        if not ok:
            errors.append("Production manifest is not 42/42 PASS")
    except Exception as exc:
        manifest = []
        errors.append(str(exc))
        add_check(checks, "production_manifest_42_pass", "42 PASS rows", f"ERROR: {exc}", False)
        print(f"Production manifest        : FAIL ({exc})")

    resolved_ok = RESOLVED_MAPPING.exists() and RESOLVED_CONFIG.exists()
    add_check(
        checks,
        "resolved_mapping_outputs_exist",
        "resolved CSV + resolved JSON",
        f"csv={RESOLVED_MAPPING.exists()}, json={RESOLVED_CONFIG.exists()}",
        resolved_ok,
    )
    print(f"Resolved variable mapping  : {'PASS' if resolved_ok else 'FAIL'}")
    if not resolved_ok:
        errors.append("Step 01B-B resolved mapping/config output is missing")

    try:
        unresolved_count = count_unresolved_rows(UNRESOLVED_AFTER)
        unresolved_ok = unresolved_count == 0
        add_check(checks, "unresolved_variables_after_01bb", 0, unresolved_count, unresolved_ok)
        print(f"Unresolved variables       : {unresolved_count}")
        if not unresolved_ok:
            errors.append(f"Unresolved variables remain after Step 01B-B: {unresolved_count}")
    except Exception as exc:
        unresolved_count = -1
        add_check(checks, "unresolved_variables_after_01bb", 0, f"ERROR: {exc}", False)
        errors.append(str(exc))
        print(f"Unresolved variables       : FAIL ({exc})")

    # -------------------------------------------------------------------------
    # 2. Official reference package
    # -------------------------------------------------------------------------
    print("\n[2] Official methodology reference package")
    refs_found = 0
    for name in EXPECTED_REFERENCES:
        path = REFERENCE_DIR / name
        exists = path.exists() and path.is_file() and path.stat().st_size > 0
        refs_found += int(exists)
        add_check(checks, f"reference_{name}", "present and non-empty", "present" if exists else "missing", exists)
        print(f"{name:24s}: {'PASS' if exists else 'FAIL'}")
        if not exists:
            errors.append(f"Missing official reference PDF: {path}")

    # -------------------------------------------------------------------------
    # 3. Identification microdata validations
    # -------------------------------------------------------------------------
    visit1_source = None
    combined_source = None
    visit1 = {}
    combined = {}

    if manifest:
        print("\n[3] Identification / estimator validation")
        try:
            visit1_source, _ = find_manifest_source(manifest, "Visit1_Blocks_1_and_2")
            visit1 = scan_visit1_identification(visit1_source)

            row_ok = visit1["rows"] == EXPECTED_VISIT1_ROWS
            add_check(checks, "visit1_household_rows", EXPECTED_VISIT1_ROWS, visit1["rows"], row_ok)

            sector_observed = {k: visit1["sector"].get(k, 0) for k in ("1", "2")}
            sector_ok = sector_observed == EXPECTED_VISIT1_SECTOR
            add_check(checks, "visit1_sector_counts", EXPECTED_VISIT1_SECTOR, sector_observed, sector_ok)

            visit_ok = visit1["visit"] == Counter({"1": EXPECTED_VISIT1_ROWS})
            add_check(checks, "visit1_visit_number", {"1": EXPECTED_VISIT1_ROWS}, dict(visit1["visit"]), visit_ok)

            weight_ok = visit1["weight_mismatches"] == 0 and visit1["weight_parse_errors"] == 0
            add_check(
                checks,
                "visit1_weight_formula",
                "0 mismatches / 0 parse errors",
                f"mismatches={visit1['weight_mismatches']}; parse_errors={visit1['weight_parse_errors']}",
                weight_ok,
                "Expected Weight=MLT/200 when NSC>NSS else MLT/100",
            )

            print(f"Visit1 households          : {visit1['rows']:,}")
            print(f"Visit1 rural / urban       : {sector_observed['1']:,} / {sector_observed['2']:,}")
            print(f"Visit1 weight mismatches   : {visit1['weight_mismatches']}")

            if not all((row_ok, sector_ok, visit_ok, weight_ok)):
                errors.append("Visit1 identification validation failed")

        except Exception as exc:
            errors.append(f"Visit1 identification validation failed: {exc}")
            add_check(checks, "visit1_identification_scan", "PASS", f"ERROR: {exc}", False)
            print(f"Visit1 validation          : FAIL ({exc})")

        try:
            combined_source, _ = find_manifest_source(manifest, "Visit1and2_CBlocks_1and2")
            combined = scan_combined_identification(combined_source)

            rows_ok = combined["rows"] == EXPECTED_COMBINED_ROWS
            add_check(checks, "combined_rows", EXPECTED_COMBINED_ROWS, combined["rows"], rows_ok)

            visit_counts = {k: combined["visit"].get(k, 0) for k in ("1", "2")}
            visits_ok = visit_counts == EXPECTED_COMBINED_VISIT_ROWS
            add_check(checks, "combined_visit_counts", EXPECTED_COMBINED_VISIT_ROWS, visit_counts, visits_ok)

            sector_by_visit = {
                v: {s: combined["sector_by_visit"][v].get(s, 0) for s in ("1", "2")}
                for v in ("1", "2")
            }
            sector_ok = sector_by_visit == EXPECTED_COMBINED_SECTOR_PER_VISIT
            add_check(checks, "combined_sector_counts_by_visit", EXPECTED_COMBINED_SECTOR_PER_VISIT, sector_by_visit, sector_ok)

            panel_count_ok = combined["panel_count"] == EXPECTED_PANEL_HOUSEHOLDS
            add_check(checks, "panel_household_count", EXPECTED_PANEL_HOUSEHOLDS, combined["panel_count"], panel_count_ok)

            panel_pair_ok = (
                combined["complete_panels"] == EXPECTED_PANEL_HOUSEHOLDS
                and combined["incomplete_panels"] == 0
                and combined["panel_format_errors"] == 0
            )
            add_check(
                checks,
                "panel_pairing",
                f"{EXPECTED_PANEL_HOUSEHOLDS} complete; 0 incomplete; 0 format errors",
                f"complete={combined['complete_panels']}; incomplete={combined['incomplete_panels']}; format_errors={combined['panel_format_errors']}",
                panel_pair_ok,
                "PANEL_HHID = HHID[:7] + HHID[8:]",
            )

            panel_geo_ok = combined["panel_geo_mismatches"] == 0
            add_check(checks, "panel_state_district_sector_stability", 0, combined["panel_geo_mismatches"], panel_geo_ok)

            weight_ok = combined["weight_mismatches"] == 0 and combined["weight_parse_errors"] == 0
            add_check(
                checks,
                "combined_weight_formula",
                "0 mismatches / 0 parse errors",
                f"mismatches={combined['weight_mismatches']}; parse_errors={combined['weight_parse_errors']}",
                weight_ok,
                "Expected Weight=MLT/200 when NSC>NSS else MLT/100",
            )

            panel_sector = {k: combined["panel_sector_counts"].get(k, 0) for k in ("1", "2")}
            add_check(
                checks,
                "panel_sector_counts",
                {"1": 89_718, "2": 49_321},
                panel_sector,
                panel_sector == {"1": 89_718, "2": 49_321},
            )

            print(f"Combined rows              : {combined['rows']:,}")
            print(f"Combined Visit1 / Visit2   : {visit_counts['1']:,} / {visit_counts['2']:,}")
            print(f"Paired PANEL_HHID          : {combined['complete_panels']:,}")
            print(f"Panel rural / urban        : {panel_sector['1']:,} / {panel_sector['2']:,}")
            print(f"Panel-format errors        : {combined['panel_format_errors']}")
            print(f"Panel geo mismatches       : {combined['panel_geo_mismatches']}")
            print(f"Combined weight mismatches : {combined['weight_mismatches']}")

            if not all((rows_ok, visits_ok, sector_ok, panel_count_ok, panel_pair_ok, panel_geo_ok, weight_ok)):
                errors.append("Combined identification/panel validation failed")

        except Exception as exc:
            errors.append(f"Combined identification validation failed: {exc}")
            add_check(checks, "combined_identification_scan", "PASS", f"ERROR: {exc}", False)
            print(f"Combined validation        : FAIL ({exc})")

    # -------------------------------------------------------------------------
    # 4. Methodology lock file
    # -------------------------------------------------------------------------
    print("\n[4] Methodology lock")

    validations = {
        "visit1_rows": visit1.get("rows"),
        "visit1_sector_counts": dict(visit1.get("sector", {})),
        "visit1_weight_mismatches": visit1.get("weight_mismatches"),
        "combined_rows": combined.get("rows"),
        "combined_visit_counts": dict(combined.get("visit", {})),
        "panel_households": combined.get("panel_count"),
        "complete_panel_households": combined.get("complete_panels"),
        "panel_format_errors": combined.get("panel_format_errors"),
        "panel_geo_mismatches": combined.get("panel_geo_mismatches"),
        "combined_weight_mismatches": combined.get("weight_mismatches"),
    }

    if visit1_source is not None and combined_source is not None:
        methodology = build_methodology_config(visit1_source, combined_source, validations)
        limitations = methodology["documented_client_limitations"]
        if errors:
            methodology["methodology_lock_status"] = "FAILED_VALIDATION"
        METHODOLOGY_FILE.write_text(
            json.dumps(methodology, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Methodology JSON           : {METHODOLOGY_FILE}")
    else:
        errors.append("Methodology JSON not written because identification sources were not resolved")

    write_checks(checks)

    failed_checks = [r for r in checks if r["status"] == "FAIL"]
    if failed_checks and not errors:
        errors.append(f"{len(failed_checks)} methodology validation checks failed")

    status = "PASS" if not errors else "FAIL"

    # -------------------------------------------------------------------------
    # 5. Summary report
    # -------------------------------------------------------------------------
    summary = [
        "=" * 78,
        "AIDIS 2003 - STEP 01B-C METHODOLOGY LOCK SUMMARY",
        "=" * 78,
        f"Reference PDFs              : {refs_found}/{len(EXPECTED_REFERENCES)}",
        f"Resolved mapping            : {'PASS' if resolved_ok and unresolved_count == 0 else 'FAIL'}",
        f"Visit1 households           : {visit1.get('rows', 'NA')}",
        f"Visit1 rural                : {visit1.get('sector', {}).get('1', 'NA') if visit1 else 'NA'}",
        f"Visit1 urban                : {visit1.get('sector', {}).get('2', 'NA') if visit1 else 'NA'}",
        f"Visit1 weight mismatches    : {visit1.get('weight_mismatches', 'NA')}",
        f"Combined rows               : {combined.get('rows', 'NA')}",
        f"Combined Visit1 rows        : {combined.get('visit', {}).get('1', 'NA') if combined else 'NA'}",
        f"Combined Visit2 rows        : {combined.get('visit', {}).get('2', 'NA') if combined else 'NA'}",
        f"Paired households           : {combined.get('complete_panels', 'NA')}",
        f"Panel format errors         : {combined.get('panel_format_errors', 'NA')}",
        f"Panel geo mismatches        : {combined.get('panel_geo_mismatches', 'NA')}",
        f"Combined weight mismatches  : {combined.get('weight_mismatches', 'NA')}",
        f"Validation checks           : {len(checks)}",
        f"Failed validation checks    : {len(failed_checks)}",
        f"Nonblocking limitations     : {len(limitations)}",
        f"Errors                      : {len(errors)}",
        "",
        "LOCKED CORE RULES:",
        "  - Weight is the estimator field; raw MLT is not applied directly.",
        "  - Stock reference date: 30-06-2002.",
        "  - Stock KPIs: Visit 1 universe (143,285 surveyed households).",
        "  - Full-year flow KPIs: paired Visit1+Visit2 universe (139,039 households).",
        "  - Cross-visit key: PANEL_HHID = HHID[:7] + HHID[8:].",
        "  - Rural cultivator: operated area B3_q8 >= 0.002 hectare.",
        "  - Urban self-employed: B3_q4 = 1; others = 2/3/9.",
        "  - Core debt: Visit1 B15.2 cash debt outstanding on 30-06-2002 (B15_2_q24).",
        "  - Block 14 is asset-side loans receivable, not payable household debt.",
        "  - Geography remains NSS 59th Round / survey-era geography.",
        "",
        f"Checks CSV                  : {CHECKS_FILE}",
        f"Methodology JSON            : {METHODOLOGY_FILE}",
        f"Summary                     : {SUMMARY_FILE}",
    ]

    if limitations:
        summary.append("")
        summary.append("NONBLOCKING CLIENT-DATA LIMITATIONS:")
        for item in limitations:
            summary.append(f"  - {item['code']}: {item['detail']}")

    if errors:
        summary.append("")
        summary.append("ERRORS:")
        summary.extend(f"  - {e}" for e in errors)

    summary.extend(["", f"STEP 01B-C STATUS: {status}", "=" * 78])
    SUMMARY_FILE.write_text("\n".join(summary), encoding="utf-8")

    print("\n" + "=" * 78)
    print("AIDIS 2003 - STEP 01B-C SUMMARY")
    print("=" * 78)
    print(f"Reference PDFs              : {refs_found}/{len(EXPECTED_REFERENCES)}")
    print(f"Resolved mapping            : {'PASS' if resolved_ok and unresolved_count == 0 else 'FAIL'}")
    print(f"Visit1 households           : {visit1.get('rows', 'NA')}")
    if visit1:
        print(f"Visit1 rural / urban        : {visit1['sector'].get('1', 0)} / {visit1['sector'].get('2', 0)}")
        print(f"Visit1 weight mismatches    : {visit1.get('weight_mismatches', 'NA')}")
    print(f"Combined rows               : {combined.get('rows', 'NA')}")
    if combined:
        print(f"Paired households           : {combined.get('complete_panels', 'NA')}")
        print(f"Panel format errors         : {combined.get('panel_format_errors', 'NA')}")
        print(f"Panel geo mismatches        : {combined.get('panel_geo_mismatches', 'NA')}")
        print(f"Combined weight mismatches  : {combined.get('weight_mismatches', 'NA')}")
    print(f"Validation checks           : {len(checks)}")
    print(f"Failed validation checks    : {len(failed_checks)}")
    print(f"Nonblocking limitations     : {len(limitations)}")
    print(f"Errors                      : {len(errors)}")
    print(f"Checks CSV                  : {CHECKS_FILE}")
    print(f"Methodology JSON            : {METHODOLOGY_FILE}")
    print(f"Summary                     : {SUMMARY_FILE}")
    print()
    print(f"STEP 01B-C STATUS: {status}")
    print("=" * 78)

    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())