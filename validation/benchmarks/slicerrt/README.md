# External SlicerRT benchmark

This is an executed compatibility and numerical-comparison exercise for OpenRad. It does not qualify a computational model, validate anatomical labels, establish measured dose accuracy or authorize treatment.

## Reproduce

From the repository root, after installing the existing requirements:

```bash
python -m validation.benchmarks.slicerrt fetch
python -m validation.benchmarks.slicerrt run
```

The explicit fetch command downloads five selected examples (314 files; 170,232,024 bytes) from [SlicerRtData](https://github.com/SlicerRt/SlicerRtData) commit `704936e8889c77174a0dd97cfb8703b47952e62c`. The tracked manifest contains source paths, sizes and Git blob hashes, not DICOM payloads. Files are published exclusively into a new ignored `data/raw/slicerrt/<commit>/` cache after size/hash verification. Existing mismatched sources cause an error and are never repaired or overwritten. Run uses no network, rejects missing/extra/modified inputs, and compares SHA-256 inventories before and after assessment. The user's original patient folders are not used as this cache.

Results are written under unique ignored `validation/runs/slicerrt/<run-id>/`: `assessment.md`, `assessment.json`, `dvh-comparison.png` and individual session reports. Existing run directories cannot be overwritten. The Markdown assessment links those case reports. JSON records source hashes, library versions, implementation hashes, measured discrepancies and expected-finding checks. A successful benchmark exit means the specified software checks executed as expected; it does not mean the source cases or models were approved. Code 2 means an expected benchmark finding/probe was absent. Source modification or malformed comparison evidence aborts the run. A reviewed [executed evidence snapshot](../../evidence/slicerrt/2026-10-21-bc757c0/assessment.md) is committed alongside the methodology; [artifact hashes and CI provenance](../../evidence/slicerrt/2026-10-21-bc757c0/provenance.json) retain its original implementation version.

No new pip dependency is required: pydicom, NumPy, Shapely, Matplotlib and dicompyler-core are already present. The full data download is opt-in and is not performed by default CI tests. Offline tests cover source preservation, download hash failures, path restrictions, exact source inventories, the real intake runner, explicit TPS units, malformed curves and cumulative-DVH threshold semantics.

No dataset-specific license was located at the data repository root. The SlicerRT software license must not be assumed to grant rights to every sample dataset. OpenRad publishes benchmark code/manifests and reviewed generated evidence, not the downloaded datasets; check provenance and terms before redistribution.

## Observed intake findings

| Selected example | Outcome | What the evidence actually establishes |
|---|---|---|
| `plastimatch_tiny-rt-study` | BLOCKED | The compact study has CT, dose and structures but lacks the complete referenced plan association required by the controlled course gate. No plan is fabricated. |
| `oncentra-4.1.6-prostate-ct-tilted-plane` | FLAGGED_FOR_REVIEW | Eight tilted planar contours are now identified explicitly, even without an RTDOSE/RTPLAN course. Tilted planes can be valid DICOM; the axial DVH sampler is outside scope. |
| `xio-4.60.00-phantom-irregular-spacing` | BLOCKED | Its 29 DICOM-named files lack the Part-10 prefix/header required by the current reader. This run establishes rejection of unsupported input encoding, **not successful detection of its irregular slice spacing**. No `force=True` decoding or transfer syntax is silently inferred. |
| `aria-phantom-contours-keyhole` | FLAGGED_FOR_REVIEW | Naming/privacy evidence requires review. The additional numeric probe found no invalid simple polygons and sampled one selected contour set. This is not proof of correct hole/topology interpretation; the folder name alone is not a rejection oracle. |
| `eclipse-8.1.20-phantom-prostate` | FLAGGED_FOR_REVIEW | Plan-frame evidence, naming, unused contour definitions, RTIMAGE scope and annotation metadata require review. Three already recognized structures can separately undergo a documented research-only numerical comparison. |

The TG-119 folder was not used as a dose benchmark because the inspected inventory contains CT/structure files without a corresponding RTDOSE. Dataset names are not evidence of a complete dose or measured-reference package.

## Eclipse phantom: independent numerical comparisons

The source includes an exported cumulative TPS DVH. Before comparison, the script verifies its patient identifier, plan label and stated 46 Gy prescription against the associated DICOM plan; identifiers are not copied into the assessment. Only exact, already recognized Bladder, PTV and Rectum source labels are selected. Their labels are not anatomical validation. No legacy alias is automatically adopted.

The narrow parser requires explicit cumulative cGy dose / percentage volume columns, agreement between absolute and relative dose columns, ordered finite values and a complete 100%→0% curve. It converts cGy to Gy. TPS mean values are rounded percentages of the export prescription; D95/D50/D2 are inverse cumulative-curve interpolations. The BODY export has a nonzero final volume and is not included. Independent dicompyler-core calculations use its default rasterization and dose-bin settings. Neither comparator is measured truth.

Observed OpenRad minus TPS differences:

| Structure | Volume (cc) | Mean dose (Gy) | D95 (Gy) | D50 (Gy) | D2 (Gy) |
|---|---:|---:|---:|---:|---:|
| Bladder | +0.653 | −0.038 | −0.0514 | −0.0061 | −0.0014 |
| PTV | +0.494 | +0.018 | −0.0105 | +0.0028 | −0.0021 |
| Rectum | +0.216 | −0.096 | −0.3715 | +0.2142 | −0.0009 |

Across these three structures, the maximum absolute OpenRad–dicompyler differences were approximately 0.000375 cc for volume, 0.00374 Gy for mean dose and 0.020 Gy for D95. This selected example does not establish general error bounds. Similar rasterization choices can produce agreement while retaining a shared discrepancy against the TPS.

The benchmark exposed a coarse **reporting-curve** problem: the former 101 thresholds produced a maximum PTV curve difference of about 9.72 percentage points against the exported TPS dose bins. With efficient normally 0.01 Gy cumulative thresholds, the observed maximum was about 0.47 points; Bladder was about 0.88 and Rectum 2.41 points. Rectum disagreement remains visible and is not declared acceptable. Linear display interpolation and different dose/volume sampling conventions influence these comparisons. D metrics were already calculated from sampled doses and did not depend on the former 101-point reporting curve.

OpenRad now calculates cumulative volumes by sorting doses and searching threshold indices, rather than scanning every voxel at every threshold. Thresholds are rounded before evaluation so a reported dose threshold is exactly the threshold used. Output is bounded to 10,001 points; unusually large dose ranges increase the explicit step in whole centigray increments. The exported step is reporting resolution, not spatial dose resolution or a clinical uncertainty estimate.

## Changes driven by external evidence

- Structure naming and basic contour integrity checks now run for every RTSTRUCT, independent of a complete dose course.
- Intake profile `case-intake-2` identifies tilted contours for review and blocks closed-planar contours with nonfinite/mismatched points, fewer than three points, or planarity residual above the stated 0.01 mm engineering tolerance. Valid POINT contours receive scope review rather than being treated as closed volumes. Findings identify pseudonymous file, ROI number and contour index.
- Rechecking the three authorized local patient folders with this additional closed-polygon check found 117, 92 and 4 one-/two-point contours labelled closed-planar. All three case intakes are now BLOCKED within this controlled workflow pending source review; this is not a clinical judgment that the treatment plans are unacceptable. All 1,318 source-file hashes remained unchanged. No source contour was rewritten, deleted or relabelled.

## Required follow-up

Investigate the Rectum TPS discrepancy with exported reference masks, contour-slab conventions and resolution/convergence studies. Run the same pinned inputs in an independently installed SlicerRT environment and record its exact versions/settings; that runtime has **not** been executed here. Validate complete hole/XOR/branching semantics against explicit reference volumes before expanding supported topology. Add a separately specified legacy DICOM reader only with explicit encoding evidence and tests. Use representative held-out patient/model cohorts and independently measured/calculated references before claiming model qualification.

Sources: [SlicerRtData](https://github.com/SlicerRt/SlicerRtData), [SlicerRT validation paper](https://pubmed.ncbi.nlm.nih.gov/23039669/), and [DICOM ROI Contour Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.6.html). These inform the exercise; they do not certify OpenRad.
