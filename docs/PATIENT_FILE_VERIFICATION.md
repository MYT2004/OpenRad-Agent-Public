# Patient-file intake verification

The **Patient-file Verification** workflow checks a local case directory and generates a prioritized, human-readable intake report with follow-up actions. It reads sources without changing them. Results are research intake evidence, not clinical authorization, a complete DICOM conformance validator, or a de-identification certificate.

## Use

- UI: choose **Patient-file Verification**, enter the authorized case directory and a pseudonym, then **Verify patient files**. Pixel decoding is enabled by default. Download Markdown, CSV or JSON. Changed input fields hide the previous result until a new check is run. A non-blocked case can continue directly into the DVH/structure-review workflow without retyping paths; the dosimetry tool performs its own checks.
- CLI: `python agent_main.py verify-case --root /authorized/case --case-id research-case-001`. Exit codes: 0 ready for research analysis, 3 review, 2 blocked/error. `--headers-only` explicitly leaves pixel integrity unverified and requires review.
- API: `POST /api/v1/cases/verify` with `{"root":"/authorized/case","case_id":"research-case-001","check_pixels":true}`. Deployment requires authentication and authorized filesystem access; do not expose local file APIs publicly.

Outputs use the normal session artifact directory and restricted report download endpoint. A locked, hash-chained `case-audit.jsonl` records each result. The report includes UTC generation time, source-content hashes, numerical criteria, implementation/library provenance, scope and supporting references. Its deterministic verification hash excludes generation time and artifact UUIDs. Human reports group repeated findings; JSON retains file-level findings with pseudonymous file/series/ROI labels. Source filenames, paths, original patient IDs and original UIDs are not exported. Unknown source ROI labels are withheld; review them locally in the naming workflow. Never enter a patient name or original identifier as the case pseudonym.

## Reproducible synthetic demo

No patient dataset is required to try the proof of concept. In the verification UI, choose **Create an explicitly synthetic demo case**, then verify it and continue into the DVH workflow. Artificial anatomy/dose is prominently labelled in intake and derived DVH reports/plots; mixed teaching-marker and unmarked DICOM sources are blocked; it is never substituted silently for a selected patient case. The generated files use a new, isolated runtime directory and are not clinically complete DICOM IOD examples.

```bash
python agent_main.py demo-case --output data/processed/demo-inputs
python agent_main.py verify-case --root data/processed/demo-inputs --case-id synthetic-demo
```

Use a different new output directory with `demo-case --defect missing_slice`, `--defect wrong_frame`, or `--defect negative_dose_scaling` to demonstrate specific rejection findings. Existing input directories are never overwritten. The ordinary synthetic case is ready only for research intake; this does not validate its artificial anatomy, dose distribution or any clinical model.

## Checks and interpretation

| Check | Behavior |
|---|---|
| Source inventory | Hash source files, recognize conventional Part-10 DICOM even without a filename extension, flag unreadable DICOM and unsupported files, do not follow symlinks. Auxiliary OS metadata is hashed but excluded from clinical-content assessment. |
| SOP identity | Block conflicting content with the same SOP identity, inconsistent file-meta/dataset identities, or a supported modality paired with the wrong SOP class. Identical duplicate copies require review. |
| Patient identity | Compare PatientID and IssuerOfPatientID, without exporting their values. Mixed identities block intake; consistent identity does not independently confirm the intended patient. |
| Pixel integrity | Decode CT and dose pixels; verify dimensions, finite values and nonnegative scaled dose. Missing payloads/decoders and malformed pixels block assessment. No CT calibration or dose accuracy is certified by decoding. |
| CT stacks | Check finite positive spacing, dimensions, orthonormal directions, frame consistency, projected plane spacing and repeated positions. Oblique stacks can be valid. Irregular spacing requires review, rather than an invented missing-slice correction. In-plane origin changes require a geometry-aware workflow. Localizers are excluded from volumetric stack checks. |
| CT completeness | Detect absent image SOPs explicitly referenced by the structure set. Consistent spacing cannot detect all omitted end planes or uniformly subsampled images. An external source inventory remains necessary. |
| RT linkage | Resolve one dose→plan→structure chain by SOP references and compare patient/issuer and available frame associations. Frame disagreements and missing referenced images block intake. No registration or UID replacement is performed. |
| Contours | Independently inspect every RTSTRUCT, even without dose/plan objects. Check ROI-index ambiguity, point-count/finite-coordinate integrity, closed-contour minimum point count and coplanarity. Tilted planar contours require orientation-aware review. This intake step does not rasterize contours, verify complete topology/anatomy or establish adequate dose coverage. |
| Nomenclature | Check the pinned TG-263 vocabulary and supported target syntax; unknown/derived names require scoped review. Do not infer anatomical equivalence from a label. Suggested anatomical aliases use pinned primary spellings and require confirmation. A generic PTV is never suggested as PTV_High or assigned a prescription/priority from its name. |
| Privacy evidence | Flag when image objects do not explicitly establish absence of burned-in annotation. This is a metadata screening flag, not OCR, pixel de-identification or proof of a privacy violation. |

**States:** `BLOCKED` when a definite inconsistency or unsupported association prevents controlled use; `FLAGGED_FOR_REVIEW` for incomplete evidence, unsupported scope or review requirements; `READY_FOR_RESEARCH_ANALYSIS` when the implemented intake checks found neither. Readiness does not mean the patient, plan, anatomy, calibration, dose or model is clinically approved.

`SliceThickness` is a nominal thickness and is never substituted for actual center-to-center slice spacing. Regularity is assessed from ImagePositionPatient projected onto the normal derived from ImageOrientationPatient. Numerical defaults are recorded: orientation tolerance 1e-4, duplicate-plane tolerance 1e-4 mm, spacing absolute tolerance 0.05 mm and relative tolerance 1%. These are prototype numerical checks, not universal clinical acceptance tolerances.

The default budget is 10,000 files and 256 MiB per file; larger files require review or a separate appropriate reader. Only conventional single-frame CT and the existing axial RTDOSE scope are supported. MR, PET, enhanced/multiframe image objects and other modalities are not silently treated as verified. Document text is never executed or sent to an LLM. Outputs must be outside the input case directory. Use OS/container read-only mounts for filesystem enforcement.

## Evidence and scope

The full local suite passes 239 tests at the external-benchmark milestone, including 42 intake checks/parameterized cases and 16 external-benchmark tests. Synthetic tests inject missing referenced end slices, irregular stacks, duplicate planes, wrong patient/issuer, dose/plan/structure frame mismatches, mismatched SOP metadata, missing/corrupted pixels, negative dose scaling, malformed/tilted/nonplanar contours and ROI ambiguity. Interface tests execute the UI, API, CLI and report downloads. Source hashes are compared before and after verification.

Local integration on three authorized folders decoded 1,301 CT/dose objects and hashed 1,318 source files without changing their contents. Profile `case-intake-2` additionally detected closed-planar contours with fewer than three points (117, 92 and 4 respectively), so all three controlled intakes now block pending source review. Earlier profile-1 results of two review cases and one blocked case are historical. A blocked intake is not a clinical plan-rejection verdict. These selected folders are not representative of all international vendors, sites, modalities or practices. Detailed patient-derived results remain local and ignored by Git. See the [external SlicerRT benchmark](SLICERRT_BENCHMARK.md) for the evidence that drove the additional checks.

## Supporting standards, papers and datasets

Searches were performed through the **Valency** plugin, across enabled sources without a source restriction, and verified against primary sources. These references inform check design; citing them does not establish conformity.

| Source | Relevance | Boundary |
|---|---|---|
| [DICOM PS3.3 Image Plane Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html) | Definitions of spacing, position, direction and nominal thickness. | Our numerical tolerances and supported geometry subset are application choices. |
| [DICOM PS3.3 ROI Contour Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.6.html) | ROI/contour association and source-image information. | The intake checker implements selected consistency checks, not every module requirement. |
| [AAPM TG-201 rapid communication](https://pubmed.ncbi.nlm.nih.gov/21330992/) and [full report](https://www.aapm.org/pubs/reports/detail.asp?docid=213) | Data-transfer QA, consistency and information integrity. | Treatment delivery, R&V systems and database transfer comparison remain outside this intake tool. |
| [AAPM TG-263](https://www.aapm.org/pubs/reports/RPT_263.pdf) | Structure and DVH naming conventions. | Syntax/naming does not prove anatomy. |
| [OpenKBP](https://arxiv.org/abs/2011.14076), [official code/data entry point](https://github.com/ababier/open-kbp) | Public head-and-neck dose-prediction benchmark for a future held-out model-evaluation study. | Not downloaded or validated in this implementation; original challenge scores must not be equated with clinical acceptability. Check current data terms and cite the dataset. |
| [OpenKBP-Opt](https://pubmed.ncbi.nlm.nih.gov/36093921/) | Reproducible prediction/optimization pipeline evaluation and DVH criteria assessment. | A potential future benchmark; no claim that OpenRad reproduces its study. |
| [TCIA HNSCC](https://www.cancerimagingarchive.net/collection/hnscc/) | Public CT/RT dataset context for the user-supplied local examples. | Data citation and collection-specific terms apply; no new patient files are uploaded or redistributed. |

For international use, retain explicit Gy/mm/cc units and UTC time, document site/vendor/fractionation applicability, and use locally authorized clinical protocols. The prototype deliberately avoids imposing a single country's or institution's OAR limits globally.
