# Patient-file intake evidence

## Evidence and scope

The full local suite passes 239 tests at the external-benchmark milestone, including 42 intake checks/parameterized cases and 16 external-benchmark tests. Synthetic tests inject missing referenced end slices, irregular stacks, duplicate planes, wrong patient/issuer, dose/plan/structure frame mismatches, mismatched SOP metadata, missing/corrupted pixels, negative dose scaling, malformed/tilted/nonplanar contours and ROI ambiguity. Interface tests execute the UI, API, CLI and report downloads. Source hashes are compared before and after verification.

Local integration on three authorized folders decoded 1,301 CT/dose objects and hashed 1,318 source files without changing their contents. Profile `case-intake-2` additionally detected closed-planar contours with fewer than three points (117, 92 and 4 respectively), so all three controlled intakes now block pending source review. Earlier profile-1 results of two review cases and one blocked case are historical. A blocked intake is not a clinical plan-rejection verdict. These selected folders are not representative of all international vendors, sites, modalities or practices. Detailed patient-derived results remain local and ignored by Git. See the [external SlicerRT benchmark](../benchmarks/slicerrt/README.md) for the evidence that drove the additional checks.

Implementation and usage: [patient-file verification guide](../../docs/PATIENT_FILE_VERIFICATION.md). Source bibliography: [supporting standards, papers and datasets](../../docs/PATIENT_FILE_VERIFICATION.md#supporting-standards-papers-and-datasets).
