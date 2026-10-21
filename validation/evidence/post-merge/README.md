# Post-merge patient export audit

The [22 October 2026 assessment](2026-10-22/assessment.json) follows the merged PR #2 baseline (`9929ff0`). It binds the new tested sources by [SHA-256 manifest](2026-10-22/tested-source-tree.json).

- **370 passing regression tests**, including 29 added export-boundary and campaign checks.
- **28/28 strict workflow scenarios** and **1,450 seeded numerical checks** passed.
- Read-only intake completed across **48 collections**, including all three available local patient folders and the pinned SlicerRT corpus: **41 BLOCKED, 7 FLAGGED_FOR_REVIEW, zero execution errors**. These are intake/support classifications, not clinical diagnoses or proof that the source treatment was invalid. There were 58 dose-budget findings; this change enforces the existing resource limit before decoding rather than expanding it without qualification.
- **63/63 executed export-fault controls** behaved as expected on two local selected-ROI baselines and one public phantom baseline. The third local case had no unambiguous supported baseline: the [campaign evidence](2026-10-22/export-controls.json) records incomplete qualification and exit 2, with no fabricated pass. A selected-ROI baseline does not release a blocked whole case.
- All **8,599 protected raw entries** matched the preceding audit's hashes. No source patient files were edited.

[Common patient export errors and follow-up instructions](../../../docs/PATIENT_DATA_QA.md) explains the refusal policies, limitations and reproducible campaign command. [Operating and release gates](../../../docs/HARDENING.md) still apply.

The first targeted checks reproduced 16 failures before rectification; the expanded suite passes after fixes. The changes prevent direct DVH bypasses of identity, SOP/file-meta, contour-count, ROI-association and frame/reference checks; preserve unsupported geometry metadata for refusal; bound intake decoding; label dose summation scope; and extend DICOM gamma association checks. Valid but unsupported geometry is distinguished from malformed input.

The independent public phantom comparison was rerun successfully. It remains an algorithm/TPS-export comparator, not measured ground truth. No live hosted inference, new patient acquisition, transport commissioning, full-cohort candidate-model validation, clinical usability study or production qualification is claimed. The existing dependency advisory/backport discrepancy remains documented in the [prior assessment](../rectification/2026-10-22/dependency-advisory.json).

Published JSON contains pseudonymous/aggregate evidence and source hashes. Private case reports, input paths, raw DICOM and detailed execution logs remain in ignored local run directories. No assertion of zero possible future defects is made.
