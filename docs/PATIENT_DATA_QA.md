# Patient-data QA: supported checks and unresolved scope

The research pipeline must preserve original bytes, associate the intended dose, plan, structure and image set, and refuse unsupported geometry before reporting a useful numerical result. A valid file is not necessarily supported by this sampler; a supported file is not proof of an accurate treatment or candidate model. Intake findings and selected-ROI measurements answer different questions.

## Common export errors and current handling

| Failure class | Implemented response | Physicist follow-up |
|---|---|---|
| Wrong patient ID or issuer, wrong linked plan/structure, incompatible frame | Intake blocks conflicting associations; direct DVH validates source identity before scrubbing; DICOM gamma checks matching patient/issuer/frame. | Confirm the intended course in the source TPS. Never rewrite UIDs to force a pass. |
| SOP class/modality mismatch, file-meta identity conflict, duplicate SOP exports | Intake reports conflicts; dose/DVH tools reject invalid object roles or file-meta conflicts. Direct DVH refuses duplicate/orphan ROI contour associations and ambiguous repeated plan/structure references. | Obtain a consistent export; preserve the conflicting originals. |
| Negative/nonfinite dose, zero or negative scaling, relative/effective dose mistaken for physical Gy | Dose analysis refuses these inputs. The application does not clip, guess unit conversion or infer a biological dose model. | Verify units, scaling, dose type and calculation provenance. |
| Fraction/beam dose mistaken for complete plan/course dose | DVH JSON and human reports label `DoseSummationType`, including UNKNOWN when absent. DICOM gamma rejects differing summation labels. No summation or fractionation conversion is performed. | Verify prescription, fraction groups, delivered fractions, boosts and accumulated dose independently. Equal labels alone do not prove comparable treatment intent. |
| Missing/duplicate CT slices, mixed reconstructions, localizers, irregular spacing, gantry tilt | Case intake inspects positions, orientation, series/reference linkage and duplicates; unsupported or ambiguous conditions are blocked or flagged. | Compare with the source-system inventory. Regular spacing cannot prove that end slices were not omitted. |
| Wrong contour point count, invalid/nonplanar/open/keyhole contours, missing planes or partial dose coverage | Direct DVH checks declared point triplets and blocks unsupported sampling. Intake highlights malformed and non-axial contours. | Inspect geometry in a validated viewer. No automated repair or anatomical inference is performed. |
| Explicit source-pixel-plane, slab-thickness or contour-offset metadata | Intake flags the sampler limitation; direct DVH refuses these encodings rather than dropping their geometry during the privacy projection. | Use a separately validated sampler that honors the metadata. These encodings can be valid DICOM. |
| Registered/transformed dose | Spatially transformed dose is refused by the axial dose tools. | Verify rigid/deformable registration and accumulation independently; this application does not validate the transform. |
| Nonstandard ROI names or laterality ambiguity | TG-263 auditor preserves source identity and requires reviewed mappings for unsupported names; naming does not certify anatomy. | Review each mapping against anatomy and the local protocol. |
| Missing codecs, corrupted pixels or very large dose grids | Intake records decode failures; shape checks enforce `OPENRAD_MAX_DOSE_VOXELS` before dose decoding. Default is 2,000,000 voxels; direct dose-file limit is 128 MiB. | Qualify codec/runtime and memory/time needs before changing budgets. No silent downsampling is used. Intake's file budget is separately configurable. |
| Identical/self-reference QA, missing uncertainty/OOD qualification or unmatched masks | Existing gamma/model-evaluation guards reject self-file comparisons and invalid arrays or return review when qualification evidence is missing. | Independently review model-bound evidence. Separate files or hashes cannot establish scientific independence. |

These are implementation controls informed by the [DICOM ROI Contour Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.6.html) and [RT Dose Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.3.html), not certification of full DICOM, AAPM or regulatory conformity.

## Run on additional authorized patient files

1. Mount source case directories read-only and set `OPENRAD_DATA_ROOTS` to those directories or their authorized parent. Keep patient identifiers, raw files and diagnostic logs private.
2. Run Patient-file Verification from the local UI or the documented [local workflow](LOCAL_WORKFLOWS.md). Review BLOCK and REVIEW findings against the source TPS and image inventory.
3. Select a verified course, supported canonical/reviewed ROI mappings and an explicitly reviewed protocol before interpreting DVH or model triage. Selected-ROI success does not clear whole-case blockers.
4. Run the export fault campaign against explicit case directories, with evidence outside every source root:

```bash
python -m validation.benchmarks.stress.patient_exports \
  --root /authorized/case-a \
  --root /authorized/case-b \
  --output /separate/new-audit/export-controls.json
```

The campaign uses scrubbed in-memory copies only. It requires a supported baseline per requested case and returns exit 2 if any baseline is unavailable or any executed control fails. Read `qualification_complete`, `all_executed_controls_expected` and `executed_controls` together: zero executed controls is never qualification. It cannot turn blocked source data into a supported baseline. Unknown aliases are not automatically mapped.

Run the full regression suite after changes and the [strict workflow qualification command](HARDENING.md#evidence-and-recovery). Keep resolved versions and the exact tested source revision. Publish only reviewed aggregate/nonpatient evidence in `validation/evidence/`; private runs remain under ignored `validation/runs/`.

## Release decisions

The stopping condition for a software audit is no unresolved reproducible defect in the declared tested scope, with unsupported cases and untested behavior explicitly recorded. It is not an assertion that no future patient, model, dependency, deployment or adversarial input can reveal another issue. Independent clinical commissioning, representative external cohorts, measured dose references where applicable, registration validation, uncertainty/OOD calibration and production infrastructure remain required. See [hardening release gates](HARDENING.md#remaining-release-gates).
