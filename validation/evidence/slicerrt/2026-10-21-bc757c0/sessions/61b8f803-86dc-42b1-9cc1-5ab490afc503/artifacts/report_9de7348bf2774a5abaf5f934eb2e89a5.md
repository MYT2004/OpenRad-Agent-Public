# OpenRad — Patient-file intake verification

Case external-001: File inconsistencies or unsupported associations block use of this case in the controlled analysis workflow.

| Measure | Result | Interpretation |
|---|---|---|
| Intake status | BLOCKED |  |
| Generated at (UTC) | 2026-10-21T11:15:11.853029+00:00 |  |
| Verification profile | case-intake-2 |  |
| Verification fingerprint | 78a73a42eee26b55… | Full SHA-256 digest is available in the technical JSON and audit record. |
| Source files hashed | 12 | Source paths and patient identifiers are withheld from exported reports. |
| Image/dose objects decoded | 11 | Pixel checks can be disabled only with an explicit review outcome. |
| DICOM objects by modality | {'RTDOSE': 1, 'CT': 10, 'RTSTRUCT': 1} |  |
| Dose courses inspected | 1 |  |
| CT-series-001 | 10 slices; CHECKED | Position-derived spacing: 23.000 mm. Uniform spacing cannot prove complete acquisition coverage. |
| BLOCK: course linkage (1) | A unique dose→plan→structure association or unambiguous ROI index could not be established. | Export all referenced RT objects together and resolve identity, reference or ROI ambiguities in the authorized source system. |
| REVIEW: burned in annotation (11) | Absence of burned-in identifying content is not explicitly established. | Review image content and the de-identification procedure; this check does not certify privacy. |
| REVIEW: roi name review (2) | Structure name requires scoped nomenclature/anatomical review. | Inspect the original label locally and confirm anatomy/laterality before supplying an explicit reviewed mapping. |
| INFO: completeness scope (1) | Uniform spacing and resolved references cannot prove that no unreferenced end slices or source objects were omitted. | Compare with the authorized source-system inventory before consequential use. This tool does not provide independent clinical approval. |

## Follow-up actions

1. Export all referenced RT objects together and resolve identity, reference or ROI ambiguities in the authorized source system.
2. Review image content and the de-identification procedure; this check does not certify privacy.
3. Inspect the original label locally and confirm anatomy/laterality before supplying an explicit reviewed mapping.

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
