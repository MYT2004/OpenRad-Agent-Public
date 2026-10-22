# Redundancy and efficiency audit — 23 October 2026

The local candidate removes unnecessary allocations and initialization. No regression was observed in the executed checks. This is bounded software evidence, not a claim that every future input is error-free or that the software is clinically commissioned.

Baseline: Git revision `df370da`. Candidate: the local working tree, with source SHA-256 values recorded in [comparison.json](comparison.json). No raw patient files were edited by the refactor. Patient data remains external to this evidence folder.

## Changes and measured effects

| Area | Before | After | Behavior check |
|---|---|---|---|
| Gamma coordinates | Retained dense meshgrid arrays and full reference points before cutoff filtering | Allocates physical point arrays directly; reference points are built only above the cutoff | Exact result dictionaries match on the seeded benchmark; exhaustive distance oracles cover 2D/3D, unequal shapes, anisotropic spacing and 0/80/100% cutoffs |
| DVH scaling | Repeated scaled source-array construction; direct path compares its own array to a newly scaled equivalent | Scales once per analyzer invocation; supplied independently decoded grids still undergo comparison | Both demo ROIs, DVH curves, metrics, nomenclature and linkage results match |
| Dashboard initialization | Every new app session creates the deterministic agent and REPL, even for intake | Creates the agent when entering Interactive Agent Query or Stateful Python REPL; preserves it across those workflows | All nine menus retain the recorded controls; regression verifies deferred creation and shared state |
| Imports | Unused JSON and canonical-serialization imports in evaluation, unused gamma typing import | Removes these imports | Full regression suite passes |

The gamma probe uses one synthetic 40 × 40 × 40 array pair, seed 263, 3%/2 mm, 10% cutoff, and three repeats per revision in Python 3.13.13:

| Measurement | Before | After |
|---|---:|---:|
| Median peak traced allocation | 17,598,728 bytes | 12,989,207 bytes |
| Median elapsed time | 0.09237 s | 0.09282 s |
| Scientific result dictionaries | Baseline | Identical |

Peak traced allocation fell **26.2%** in this probe. Timing was essentially unchanged; this is not evidence of a general speed improvement. Tracemalloc does not measure total process RSS. Cold imports, filesystem caches, dataset sizes and concurrent workloads can change results. The whole stress-suite times are not used as a speed benchmark.

## Before/after verification

| Check | Baseline | Candidate |
|---|---:|---:|
| Existing regression suite | 370 passed | All existing checks pass |
| Total regression suite including new independent gamma/lazy-init regressions | 370 | 377 passed |
| Complete workflow stress scenarios | 28 passed, 0 failed, 0 skipped | 28 passed, 0 failed, 0 skipped |
| Streamlit menu rendering and controls | 9 menus, no exceptions | 9 menus, no exceptions; recorded labels/options unchanged |
| Clean synthetic case DVH | Recorded | Recorded scientific payload identical |
| Candidate numerical stress | — | 1,450 assertions passed |
| Installed dependency consistency | — | `pip check`: no broken requirements |
| Whitespace/diff validation | — | `git diff --check`: passed |

An initial candidate workflow run skipped five external-data scenarios because the local patient roots were not configured. The cases were found in the existing external patient-data directory. Re-running both revisions with explicit `OPENRAD_DATA_ROOTS` completed all 28 scenarios. The initial partial run was retained under ignored runtime evidence; it is not represented as a complete pass.

The complete suite exercised local HNSCC intake, SlicerRT phantom/geometry cases, grounded copilot paths, DVH, gamma controls, TOPAS generation, radiobiology, triage and REPL artifact/state behavior. All scenario status outcomes match between revisions. Structured readability checks passed; these do not replace a human usability study.

Five pytest warnings remain: one Starlette/httpx deprecation, three pydicom DicomDir deprecations from the traversal-control test, and one deliberately invalid UID warning from a malformed-input test. No warning is being hidden or counted as a test failure. No dependency additions are needed for these changes; dependency-version migration should be tested separately rather than performed as part of this optimization.

## Review of apparent duplication

The audit inspected Python entry points, frontend workflows, core tool modules, validation/triage, sessions, reports, privacy, governance, dynamic routing, resource guards, packaging and deployment configuration. An AST body comparison found no exact repeated multi-statement function bodies in `src/`, `openrad/` and `frontend/`. This does not prove the absence of semantic duplication.

The following repetitions were retained deliberately:

- `app.py`, `frontend/app.py`, `agent_main.py` and `server.py` serve different entry-point roles. The root app is a convenience launcher, not a second UI implementation.
- `src.tools` coordinates privacy, audit hooks, sessions and artifacts; lower-level `openrad.tools` performs calculations. Adapters preserve existing tool contracts and explicit linkage policies.
- The legacy array-validation helper and manifest-based model evaluator have different input/provenance contracts. Merging them in this change would require a separate contract migration and characterization tests.
- Public package re-exports and legacy reader imports support existing callers. An import can appear unused to AST analysis while remaining part of the API.
- Source identity checks before scrubbing and geometry checks on scrubbed analysis copies have different trust boundaries. Independent pydicom/PyMedPhys value checks, post-tool checks, audit-chain verification and post-computation source hashes remain in place.
- Separate gamma criteria are distinct policy evaluations; their normalized search spaces differ. No numerical tolerance, candidate search domain, dose cutoff policy or triage threshold was changed.
- `requirements.txt` delegates to the canonical dependency metadata in `pyproject.toml`; it does not duplicate version declarations.
- Historical evidence and independent analytical oracles are retained for traceability, rather than deleted as duplicate outputs.

## Remaining limits and follow-up

These checks cover the available local environment and selected supported inputs. They do not exhaust every DICOM transfer syntax, anatomy, malformed payload, platform, dependency version or concurrent workload. No new paid/live Gemini request, TOPAS executable transport run, Cloud Run deployment test or independent clinical comparison was performed in this audit. Copilot routing/failure behavior is covered by deterministic/provider-mocked regression tests and local workflow execution.

The research deployment remains a single trusted operator system. Enforced filesystem read-only mounts, isolated workers, time/cancellation budgets, authenticated multi-user ownership and durable distributed audit storage remain separate deployment work. The REPL is trusted Python execution, not a security sandbox. Do not weaken resource budgets or cache mutable patient inputs merely to improve timing.

For larger gamma datasets, the next efficiency study should measure process RSS, full-volume runtime and admission-control behavior across representative dose grids. For a larger consolidation, first characterize every public adapter and decision contract before removing it. Independent physicist review and clinical commissioning remain required for clinical use; `clinical_release` remains false.

## Reproduce

From the repository root in the installed project environment:

```bash
python -m pytest validation/tests -q
python -m validation.benchmarks.efficiency
python -m validation.benchmarks.stress.numerical
python -m pip check
```

For all external-case scenarios, first configure `OPENRAD_DATA_ROOTS` as a JSON list of authorized existing raw-data directories, then run:

```bash
python -m validation.benchmarks.stress.stress_all_menus --require-complete
```

Generated runs belong under ignored `validation/runs/`. The reviewed, patient-free comparison files for this audit are together in this folder. [comparison.json](comparison.json) records checks and candidate hashes; `gamma-before.json` / `gamma-after.json` retain all three probe results; `workflows-before.json` / `workflows-after.json` retain the synthetic DVH and menu-control snapshots. Raw patient data and patient-derived detailed run artifacts are not included here.
