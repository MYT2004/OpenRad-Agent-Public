# OpenRad — Patient-file intake verification

Case external-005: Intake checks found unresolved evidence or review requirements. Resolve the prioritized findings before relying on this case.

| Measure | Result | Interpretation |
|---|---|---|
| Intake status | FLAGGED_FOR_REVIEW |  |
| Generated at (UTC) | 2026-10-21T11:15:13.305944+00:00 |  |
| Verification profile | case-intake-2 |  |
| Verification fingerprint | 3fd628e5db5f811e… | Full SHA-256 digest is available in the technical JSON and audit record. |
| Source files hashed | 99 | Source paths and patient identifiers are withheld from exported reports. |
| Image/dose objects decoded | 93 | Pixel checks can be disabled only with an explicit review outcome. |
| DICOM objects by modality | {'CT': 92, 'RTDOSE': 1, 'other-DICOM': 4, 'RTPLAN': 1, 'RTSTRUCT': 1} |  |
| Dose courses inspected | 1 |  |
| CT-series-001 | 92 slices; CHECKED | Position-derived spacing: 2.500 mm. Uniform spacing cannot prove complete acquisition coverage. |
| REVIEW: burned in annotation (93) | Absence of burned-in identifying content is not explicitly established. | Review image content and the de-identification procedure; this check does not certify privacy. |
| REVIEW: plan frame absent (1) | Plan frame association is not explicit. | Review plan geometry and the applicable DICOM requirements; do not infer a patient-space association. |
| REVIEW: unsupported modality (4) | DICOM object type is outside the supported conventional CT/RT workflow. | Use a validated modality-specific assessment. No unsupported object is treated as verified. |
| REVIEW: roi contours absent (1) | Some ROI definitions have no associated contour item. Observed examples: [{"scope": "F00099", "observed": 10}] | Confirm which structures are intended for dose assessment and obtain their contours from the source system. |
| REVIEW: roi name review (11) | Structure name requires scoped nomenclature/anatomical review. | Inspect the original label locally and confirm anatomy/laterality before supplying an explicit reviewed mapping. |
| INFO: completeness scope (1) | Uniform spacing and resolved references cannot prove that no unreferenced end slices or source objects were omitted. | Compare with the authorized source-system inventory before consequential use. This tool does not provide independent clinical approval. |

## Follow-up actions

1. Review image content and the de-identification procedure; this check does not certify privacy.
2. Review plan geometry and the applicable DICOM requirements; do not infer a patient-space association.
3. Use a validated modality-specific assessment. No unsupported object is treated as verified.
4. Confirm which structures are intended for dose assessment and obtain their contours from the source system.
5. Inspect the original label locally and confirm anatomy/laterality before supplying an explicit reviewed mapping.

## Scope and limitations

- Research assessment only. This output does not authorize treatment or establish clinical commissioning.
- Read-only research intake; no complete DICOM conformance, de-identification or treatment-plan certification.
- No image registration, contour rasterization/topology assessment, clinical dose-constraint assessment or source correction is performed here.
- Only conventional single-frame CT stacks and the existing axial RTDOSE scope are supported. Other workflows require review.
- Checks are informed by DICOM geometry/reference definitions and data-transfer QA literature; this report does not establish standards conformity.

## References supporting check design

- [DICOM PS3.3 Image Plane Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html)
- [DICOM PS3.3 ROI Contour Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.6.html)
- [AAPM TG-201 rapid communication: radiotherapy data transfer QA](https://pubmed.ncbi.nlm.nih.gov/21330992/)
- [AAPM TG-201: Quality Management of External Beam Therapy Data Transfer](https://www.aapm.org/pubs/reports/detail.asp?docid=213)
- [AAPM TG-263: standardized nomenclature](https://www.aapm.org/pubs/reports/RPT_263.pdf)
