from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / 'cache'
CONFIG_DIR = ROOT / 'config'
REPORT_DIR = ROOT / 'output' / 'reports'

INPUT_MAPPING = CACHE_DIR / 'step01b_variable_mapping.csv'
INPUT_CONFIG = CONFIG_DIR / 'aidis_2003_variable_map.json'

OUTPUT_MAPPING = CACHE_DIR / 'step01b_variable_mapping_resolved.csv'
OUTPUT_UNRESOLVED = CACHE_DIR / 'step01b_unresolved_variables_after_resolution.csv'
OUTPUT_TABLE = CACHE_DIR / 'step01b_official_variable_resolution_table.csv'
OUTPUT_CONFIG = CONFIG_DIR / 'aidis_2003_variable_map_resolved.json'
OUTPUT_SUMMARY = REPORT_DIR / 'step01b_resolution_summary.txt'

SOURCE_NADA = 'MoSPI/NADA NSS 59th Round AIDIS 2003 data dictionary/study description'
SOURCE_FIELD_STAFF = 'NSS 59th Round Schedule 18.2 field instructions, Block 17.1'

RESOLUTIONS = {
    'B8_q1': ('Serial no.', SOURCE_NADA),
    'B8_q3': ('Owned - Number', SOURCE_NADA),
    'B8_q4': ('Owned - Value (Rs.)', SOURCE_NADA),
    'B8_q5': ('Transactions - Acquisition - Number', SOURCE_NADA),
    'B8_q6': ('Transactions - Acquisition - Value (Rs.)', SOURCE_NADA),
    'B8_q7': ('Transactions - Disposal - Number', SOURCE_NADA),
    'B8_q8': ('Transactions - Disposal - Value (Rs.)', SOURCE_NADA),
    'B8_q9': ('Assets owned - Number', SOURCE_NADA),
    'B8_q10': ('Assets owned - Value (Rs.)', SOURCE_NADA),

    'B16_q1': ('Serial no. of liability', SOURCE_NADA),
    'B16_q2': ('Nature of liability', SOURCE_NADA),
    'B16_q3': ('Period for which liability is outstanding', SOURCE_NADA),
    'B16_q4': ('Source of liability / loan', SOURCE_NADA),
    'B16_q5': ('Purpose of liability / loan', SOURCE_NADA),
    'B16_q6': ('Amount outstanding (Rs.)', SOURCE_NADA),

    'B17_1_q1': ('Item code', SOURCE_FIELD_STAFF),
    'B17_1_q3': (
        'Whether expenditure was incurred for purchase, construction, additions, major repairs and alterations, or improvements (yes=1, no=2)',
        SOURCE_FIELD_STAFF,
    ),
    'B17_1_q4': (
        'Whether expenditure was incurred on normal repairs and maintenance (yes=1, no=2; not applicable for schedule-crossmarked items)',
        SOURCE_FIELD_STAFF,
    ),

    'B17_2_q1': ('Item code', SOURCE_NADA),
    'B17_2_q3': ('Purpose of expenditure', SOURCE_NADA),
    'B17_2_q4': ('Expenditure in cash - Purchase of assets etc. (Rs.)', SOURCE_NADA),
    'B17_2_q5': ('Expenditure in cash - Payment to hired labour (Rs.)', SOURCE_NADA),
    'B17_2_q6': ('Expenditure in kind - Purchase of assets etc. (Rs.)', SOURCE_NADA),
    'B17_2_q7': ('Expenditure in kind - Payment to hired labour (Rs.)', SOURCE_NADA),
    'B17_2_q8': ('Value out of home-produced stock (Rs.)', SOURCE_NADA),
    'B17_2_q9': ('Value of work done by household members (Rs.)', SOURCE_NADA),
    'B17_2_q10': ('Total expenditure (Rs.)', SOURCE_NADA),
    'B17_2_q11': ('Amount financed from institutional agency (Rs.)', SOURCE_NADA),
    'B17_2_q12': ('Amount financed from non-institutional agency (Rs.)', SOURCE_NADA),

    'B18_q1': ('Serial no.', SOURCE_NADA),
    'B18_q3': ('Amount received from sale (Rs.)', SOURCE_NADA),
    'B18_q4': ('Value of loss by natural calamities (Rs.)', SOURCE_NADA),
    'B18_q5': ('Value of loss due to other reasons (Rs.)', SOURCE_NADA),
    'B18_q6': ('Salvage value of discarded assets (Rs.)', SOURCE_NADA),
}

EXPECTED_UNIQUE = 34
EXPECTED_OCCURRENCES = 68


def read_csv(path):
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    print('=' * 78)
    print('AIDIS 2003 - STEP 01B-B OFFICIAL VARIABLE GAP RESOLUTION')
    print('=' * 78)

    errors = []

    if not INPUT_MAPPING.exists():
        errors.append(f'Missing input mapping: {INPUT_MAPPING}')
    if not INPUT_CONFIG.exists():
        errors.append(f'Missing input config: {INPUT_CONFIG}')
    if errors:
        for item in errors:
            print('ERROR:', item)
        print('\nSTEP 01B-B STATUS: FAIL')
        return 1

    rows = read_csv(INPUT_MAPPING)

    unresolved_before = [
        r for r in rows
        if str(r.get('mapping_status', '')).startswith('UNRESOLVED')
    ]
    unique_before = sorted({r['raw_variable'] for r in unresolved_before})

    print('\n[1] Input unresolved set')
    print(f'Unresolved occurrences before : {len(unresolved_before)}')
    print(f'Unique unresolved variables   : {len(unique_before)}')

    resolution_names = sorted(RESOLUTIONS)
    missing_from_resolution = sorted(set(unique_before) - set(resolution_names))
    extra_in_resolution = sorted(set(resolution_names) - set(unique_before))

    if len(unique_before) != EXPECTED_UNIQUE:
        errors.append(
            f'Expected {EXPECTED_UNIQUE} unique unresolved variables; found {len(unique_before)}'
        )
    if len(unresolved_before) != EXPECTED_OCCURRENCES:
        errors.append(
            f'Expected {EXPECTED_OCCURRENCES} unresolved occurrences; found {len(unresolved_before)}'
        )
    if missing_from_resolution:
        errors.append('Resolution dictionary missing: ' + ', '.join(missing_from_resolution))
    if extra_in_resolution:
        errors.append('Resolution dictionary has unexpected names: ' + ', '.join(extra_in_resolution))

    resolved_occurrences = 0
    output_rows = []

    base_fields = list(rows[0].keys()) if rows else []
    if 'resolution_source' not in base_fields:
        base_fields.append('resolution_source')

    for row in rows:
        out = dict(row)
        raw_var = str(out.get('raw_variable', '')).strip()
        if str(out.get('mapping_status', '')).startswith('UNRESOLVED') and raw_var in RESOLUTIONS:
            description, source = RESOLUTIONS[raw_var]
            out['description'] = description
            out['mapping_status'] = 'MAPPED_OFFICIAL_RESOLUTION'
            out['unresolved_reason'] = ''
            out['methodology_status'] = 'VARIABLE_RESOLVED'
            out['resolution_source'] = source
            resolved_occurrences += 1
        else:
            out.setdefault('resolution_source', '')
        output_rows.append(out)

    unresolved_after = [
        r for r in output_rows
        if str(r.get('mapping_status', '')).startswith('UNRESOLVED')
    ]

    print('\n[2] Resolution result')
    print(f'Resolved occurrences         : {resolved_occurrences}')
    print(f'Unresolved occurrences after : {len(unresolved_after)}')

    if resolved_occurrences != EXPECTED_OCCURRENCES:
        errors.append(
            f'Expected to resolve {EXPECTED_OCCURRENCES} occurrences; resolved {resolved_occurrences}'
        )
    if unresolved_after:
        errors.append(
            'Unresolved variables remain: ' + ', '.join(
                sorted({r['raw_variable'] for r in unresolved_after})
            )
        )

    write_csv(OUTPUT_MAPPING, output_rows, base_fields)
    write_csv(OUTPUT_UNRESOLVED, unresolved_after, base_fields)

    resolution_table = [
        {
            'raw_variable': name,
            'description': RESOLUTIONS[name][0],
            'resolution_source': RESOLUTIONS[name][1],
        }
        for name in sorted(RESOLUTIONS)
    ]
    write_csv(
        OUTPUT_TABLE,
        resolution_table,
        ['raw_variable', 'description', 'resolution_source'],
    )

    with INPUT_CONFIG.open('r', encoding='utf-8') as handle:
        config = json.load(handle)

    updated_json_occurrences = 0
    for dataset in config.get('datasets', {}).values():
        for variable in dataset.get('variables', []):
            raw_var = str(variable.get('raw_variable', '')).strip()
            if raw_var in RESOLUTIONS and str(variable.get('mapping_status', '')).startswith('UNRESOLVED'):
                variable['description'] = RESOLUTIONS[raw_var][0]
                variable['mapping_status'] = 'MAPPED_OFFICIAL_RESOLUTION'
                variable['resolution_source'] = RESOLUTIONS[raw_var][1]
                updated_json_occurrences += 1

    config['variable_resolution'] = {
        'status': 'PASS' if not errors else 'FAIL',
        'unique_variables_resolved': len(RESOLUTIONS),
        'occurrences_resolved': resolved_occurrences,
        'unresolved_occurrences_after': len(unresolved_after),
        'sources': [SOURCE_NADA, SOURCE_FIELD_STAFF],
    }
    config['unresolved_variable_occurrences'] = len(unresolved_after)
    config['unresolved_unique_variable_names'] = sorted(
        {r['raw_variable'] for r in unresolved_after}
    )

    OUTPUT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    print('\n[3] JSON configuration update')
    print(f'JSON variable occurrences updated : {updated_json_occurrences}')

    if updated_json_occurrences != EXPECTED_OCCURRENCES:
        errors.append(
            f'Expected {EXPECTED_OCCURRENCES} JSON occurrences updated; got {updated_json_occurrences}'
        )

    status = 'PASS' if not errors else 'FAIL'

    summary_lines = [
        '=' * 78,
        'AIDIS 2003 - STEP 01B-B OFFICIAL VARIABLE GAP RESOLUTION SUMMARY',
        '=' * 78,
        f'Unique unresolved before      : {len(unique_before)}',
        f'Unresolved occurrences before : {len(unresolved_before)}',
        f'Unique variables resolved      : {len(RESOLUTIONS)}',
        f'Occurrences resolved           : {resolved_occurrences}',
        f'Unresolved occurrences after  : {len(unresolved_after)}',
        f'JSON occurrences updated       : {updated_json_occurrences}',
        f'Errors                         : {len(errors)}',
        '',
        f'Resolved mapping               : {OUTPUT_MAPPING}',
        f'Resolution table               : {OUTPUT_TABLE}',
        f'Unresolved after resolution    : {OUTPUT_UNRESOLVED}',
        f'Resolved JSON config           : {OUTPUT_CONFIG}',
        '',
    ]
    if errors:
        summary_lines.append('ERRORS:')
        summary_lines.extend(f'  - {item}' for item in errors)
        summary_lines.append('')
    summary_lines.extend([
        f'STEP 01B-B STATUS: {status}',
        '=' * 78,
    ])

    OUTPUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_SUMMARY.write_text('\n'.join(summary_lines), encoding='utf-8')

    print('\n' + '=' * 78)
    print('AIDIS 2003 - STEP 01B-B SUMMARY')
    print('=' * 78)
    print(f'Unique variables resolved      : {len(RESOLUTIONS)}')
    print(f'Occurrences resolved           : {resolved_occurrences}')
    print(f'Unresolved occurrences after  : {len(unresolved_after)}')
    print(f'Errors                         : {len(errors)}')
    print(f'Resolved mapping               : {OUTPUT_MAPPING}')
    print(f'Resolved JSON config           : {OUTPUT_CONFIG}')
    print(f'Summary                        : {OUTPUT_SUMMARY}')
    print()
    print(f'STEP 01B-B STATUS: {status}')
    print('=' * 78)

    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())