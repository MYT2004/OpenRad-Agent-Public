# Validation and evidence

This is the single entry point for OpenRad benchmarks, regression tests, audit documents and research evidence. Application code remains in `src/`, `openrad/` and `frontend/`; user guides remain in `docs/`. Passing a software check does not establish clinical commissioning or model qualification.

```text
validation/
  benchmarks/
    stress/            Full-corpus, seeded numerical and live synthetic copilot checks
    slicerrt/          Runner, reference comparison, pinned manifest and methodology
    local_datasets.py Read-only local integration comparison utility
  tests/              All offline unit, integration, API and UI regressions
  audits/             Historical medical-physics and workflow audit records
  evidence/           Reviewed public evidence snapshots, committed to Git
  runs/               Generated local runs and private evidence, ignored by Git
```

## Run checks

```bash
python -m pytest validation/tests -q
python -m validation.benchmarks.slicerrt fetch
python -m validation.benchmarks.slicerrt run
python -m validation.benchmarks.local_datasets /authorized/read-only/case --reference
```

`python -m pytest -q` discovers the same suite through `pyproject.toml`. CI uses the explicit central test path. The SlicerRT fetch is opt-in; default tests do not download patient/sample datasets. New SlicerRT executions create unique UTC/UUID run directories under `runs/slicerrt/` and print their location. Existing run directories cannot be overwritten. Local patient comparisons default to `runs/local-datasets/` and must remain local.

Raw sources remain in their existing authorized locations or the ignored `data/raw/slicerrt/<commit>/` cache. They are not moved into published evidence or modified to satisfy a check. Normal application sessions remain in runtime session storage; they are not automatically published as benchmark evidence. Benchmark-generated session artifacts live inside their run directory.

## Review evidence

- [SlicerRT benchmark methodology and observed discrepancies](benchmarks/slicerrt/README.md)
- [Published executed SlicerRT snapshot](evidence/slicerrt/2026-10-21-bc757c0/assessment.md)
- [Snapshot hashes, implementation commit and CI reference](evidence/slicerrt/2026-10-21-bc757c0/provenance.json)
- [Historical medical-physics audit](audits/medical_physics.md)
- [Historical workflow audit](audits/physicist_workflows.md)
- [Patient-file intake evidence and outcome changes](audits/patient_intake.md)

The public snapshot preserves the recorded `bc757c0` execution and its original code hashes, report links and audit chains. It is historical evidence, not a claim that every later commit was externally benchmarked. Current code can reproduce the exercise using the commands above. The regression suite verifies the snapshot's artifact hashes and audit chains.

The consolidation milestone passes 241 offline tests. That includes tests for unique centralized run directories, refusal to replace existing evidence, and verification of the public snapshot hashes/audit chains. Test results remain software evidence, not a clinical accuracy claim.

Existing generated evidence formerly scattered under `data/processed/` was relocated byte-for-byte into ignored `runs/legacy-workspace/`; its local `migration.json` records old/new paths and unchanged-file counts. Historical serialized paths are preserved as evidence rather than rewritten. Existing synthetic demonstration inputs were archived with that local evidence. Patient source folders and the raw external cache were left in place.

## Add another benchmark

Create `benchmarks/<suite>/` with its runner, pinned source manifest and methodology. Place offline regression coverage in `tests/`. Write generated results under a new `runs/<suite>/<run-id>/`, with sources, software versions, observed values, limitations and follow-up actions. Publish only a reviewed, immutable snapshot under `evidence/<suite>/<run-id>/`, including artifact hashes and the executed implementation/CI reference. Keep patient-derived files, raw DICOM, credentials and local screenshots out of published snapshots.

Latest reviewed stress summary: [2026-10-21 copilot and full corpus](evidence/stress/2026-10-21/README.md). Source inputs and detailed private case reports remain local.
