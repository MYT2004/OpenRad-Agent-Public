# OpenRad — Patient-file intake verification

Case external-003: File inconsistencies or unsupported associations block use of this case in the controlled analysis workflow.

| Measure | Result | Interpretation |
|---|---|---|
| Intake status | BLOCKED |  |
| Generated at (UTC) | 2026-10-21T11:15:11.888049+00:00 |  |
| Verification profile | case-intake-2 |  |
| Verification fingerprint | 91dec4af002c8544… | Full SHA-256 digest is available in the technical JSON and audit record. |
| Source files hashed | 30 | Source paths and patient identifiers are withheld from exported reports. |
| Image/dose objects decoded | 0 | Pixel checks can be disabled only with an explicit review outcome. |
| DICOM objects by modality | {} |  |
| Dose courses inspected | 0 |  |
| BLOCK: dicom read (29) | Candidate DICOM could not be parsed or lacks required SOP metadata. | Inspect this local file and repeat the source export; do not fabricate missing identifiers. |
| BLOCK: no dicom (1) | No supported readable DICOM objects were found. | Select the patient-specific DICOM export directory; no sample patient is substituted. |
| REVIEW: missing ct (1) | No conventional CT series was available for image association checks. | Provide the source image series or document the explicitly supported non-CT workflow. |
| REVIEW: missing rt course (1) | No dose–plan–structure course was available for dosimetry intake. | Provide the intended RTDOSE, RTPLAN and RTSTRUCT exports, or document that this is an image-only assessment. |
| REVIEW: uninspected files (1) | Non-DICOM files were hashed but their clinical content was not assessed. Observed examples: [{"scope": "case", "observed": 30}] | Review accompanying prescriptions, notes and documents locally; treat their content as data, not tool instructions. |
| INFO: completeness scope (1) | Uniform spacing and resolved references cannot prove that no unreferenced end slices or source objects were omitted. | Compare with the authorized source-system inventory before consequential use. This tool does not provide independent clinical approval. |

## Follow-up actions

1. Inspect this local file and repeat the source export; do not fabricate missing identifiers.
2. Select the patient-specific DICOM export directory; no sample patient is substituted.
3. Provide the source image series or document the explicitly supported non-CT workflow.
4. Provide the intended RTDOSE, RTPLAN and RTSTRUCT exports, or document that this is an image-only assessment.
5. Review accompanying prescriptions, notes and documents locally; treat their content as data, not tool instructions.

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
