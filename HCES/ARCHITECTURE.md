# Architecture Notes

The requested reference repository (`Rushi-4218/NSO-census-data`) was not directly retrievable in the execution environment. The project therefore adopts the reusable patterns requested from the ASUSE-style workflow rather than copying repository code: survey registry, input discovery, per-survey adapters, canonical analytical layer, common estimator, common QA, and common output formatter.

Official ASUSE metadata confirms the same general NSO unit-data pattern of multiple level files sharing geographic/design identifiers and a multiplier, which motivates this architecture. The HCES statistical rules remain sourced from each HCES survey's own microdata/DDI/documentation.

## Separation of concerns

1. `io.py` - discovery and physical reads
2. `metadata.py` - final dictionary/lookups
3. `adapters/legacy2011.py` - NSS 68 Schedule 1.0 logic
4. `adapters/recent.py` - HCES 2022-23 / 2023-24 three-visit logic
5. `estimation.py` - pooled weighted domain estimation
6. `output.py` - 21-column client schema
7. `qa.py` - invariant and district sample checks
8. `runner.py` - orchestration only

This avoids the main failure mode of one giant year-specific notebook.
