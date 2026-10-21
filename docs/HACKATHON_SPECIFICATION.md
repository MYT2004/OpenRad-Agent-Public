# OpenRad Agent — project outline and technical specification

## Executive summary

OpenRad Agent is an open-source research workflow assistant for computational medical physics and radiotherapy dosimetry, developed for the OSI Hackathon. It combines patient-file intake verification, deterministic DICOM-RT analysis, TG-263 naming review, dose-comparison metrics, TOPAS parameter generation and auditable research triage through Streamlit, FastAPI and CLI interfaces.

The prototype reduces repetitive scripting and makes invalid inputs, unresolved discrepancies and missing evidence visible. It produces readable assessments, plots, measurements with units and prioritized follow-up actions while preserving raw source files. Automated checks provide evidence within their documented scope; they do not establish clinical commissioning, complete standards conformity or error-free operation.

## Demonstration

1. Start `streamlit run frontend/app.py` from the repository root. Select **Patient-file Verification**.
2. Choose **Create an explicitly synthetic demo case**, then **Verify patient files**. Inspect the research intake status, grouped findings, criteria and follow-up actions. Download Markdown, CSV or JSON.
3. Choose **Continue to DVH and structure review**, select the demonstrated structure and compute its DVH. Artificial inputs stay labelled in reports and plots.
4. Generate separate defective inputs with `python agent_main.py demo-case --output data/processed/demo-missing --defect missing_slice`. Verify that directory with `python agent_main.py verify-case --root data/processed/demo-missing --case-id demo-missing`. Repeat with new directories and `wrong_frame` or `negative_dose_scaling` to demonstrate blocking findings. Exit code 2 is expected for blocked intake; existing directories are never overwritten.

No patient data is required for this demonstration. The generated DICOM objects are artificial teaching inputs, not clinically complete IOD examples or validation of anatomical accuracy.

## Implemented capability and boundaries

| Capability | Implemented behavior | Evidence boundary / next requirement |
|---|---|---|
| Workflow routing | Typed deterministic tasks through three interfaces | Autonomous LLM orchestration is not implemented. |
| Patient-file verification | Checks supported SOP identities, patient/issuer consistency, dose→plan→structure references, CT geometry, pixels, referenced-image completeness and basic contours | Detects specified inconsistencies; does not prove the intended patient, complete export, full DICOM conformance, anatomy or calibration. |
| TG-263 review | Pinned vocabulary and supported naming syntax; unknown labels require review; explicit human-reviewed mappings | Naming does not prove anatomy. A governed persistent institutional alias registry remains future work. |
| DVH | D95%, D50%, D2%, mean and voxel maximum dose in Gy; V50Gy in percent and cc; cumulative DVH plots | Supported axial geometry/topology only. V50Gy is an absolute 50 Gy threshold, not 50% of prescription. Voxel maximum is resolution dependent. |
| Dose comparison | Reference-maximum global normalization, 10% cutoff and discrete nearest-neighbour Gamma without interpolation; MAE and supplied target/OAR evidence | Numerical commissioning against independent methods/measurements remains required. Gamma alone does not establish clinical acceptability. |
| Decision authority | APPROVED means a research candidate for the single evaluation; missing evidence requires review; clinical_release is always false | No population-level model qualification or treatment authorization. Intake uses a separate readiness state, not APPROVED. |
| TOPAS | Parameter templates, input bounds and structural checks | Installed TOPAS parser/runtime execution, transport and scorer validation remain outstanding. |
| Review and provenance | Source/output hashes, rule observations, hash-chained audit records, externally signed research dispositions | Hashes establish integrity evidence, not scientific validity or provenance authenticity. Hard physical failures cannot be signed into approvals. |
| Source protection | Read-only source access, output-path restrictions, source-hash comparisons and isolated sessions | OS/container read-only mounts are needed for filesystem enforcement. The local REPL is not a security sandbox. |
| Privacy | Minimal in-memory analysis copies; identifying source metadata excluded from reports; explicit burned-in-annotation review | No complete DICOM de-identification certification, OCR or assurance that a caller-entered pseudonym contains no PHI. |
| Uncertainty / OOD | Accepts explicit supplied evidence and exposes missing evidence | Calibrated uncertainty estimation, OOD detection and inference are not implemented. |

## Architecture and module responsibilities

The controlled pathway is **interface → deterministic task → input checks → supported calculation → research policy → readable report and audit → human review**. Invalid or unsupported inputs are reported; source files, registrations and prescriptions are never silently corrected.

| Module | Responsibility |
|---|---|
| `src/case_verification.py` | Case inventory, identity/linkage, CT-stack consistency, referenced-image completeness, basic contour and privacy-evidence screening |
| `src/tools.py` and `openrad/tools/` | Canonical DICOM DVH orchestration, supported geometry/contour sampling and TOPAS generation |
| `src/validation.py` | Array preflight and direct-array research assessment |
| `src/evaluation.py` | Manifest-based dose-array comparison, metrics, plots and provenance |
| `src/decision.py` | Typed inputs, policy thresholds and three-state research gate |
| `src/governance.py` | Hash-chained audit records and Ed25519 research review verification |
| `src/reports.py` | Human summaries, units, limitations and follow-up actions |
| `src/storage.py`, `src/readonly.py` | Session/artifact management and application output-path restrictions |

## Physics and QA interpretation

[AAPM TG-218](https://www.aapm.org/pubs/reports/detail.asp?docid=173) addresses measurement-based patient-specific IMRT QA. Its reference criteria include 3%/2 mm, global normalization, a 10% low-dose threshold, a 95% tolerance limit and a 90% action limit. OpenRad uses corresponding research reference thresholds for supplied dose arrays; that does not implement or establish conformity with all TG-218 procedures. Additional 3%/3 mm and 2%/2 mm policies are explicitly custom research choices. The implementation uses reference-maximum normalization; it does not offer arbitrary prescription-point normalization.

An intake discrepancy is not automatically a clinical plan failure. Irregular spacing requires review; missing explicitly referenced images or incompatible frame associations block intake. Regular spacing cannot prove that unreferenced end planes are present. No missing-slice interpolation or registration is invented. OAR limits require explicit authorized protocols, fractionation and anatomical review; a universal international organ tolerance is not assumed. See [exact decision rules](DECISION_ENGINE.md) and [TG-263 scope](TG263.md).

## Evidence and international usefulness

The external-benchmark milestone executed **239 passing tests**, including UI/API/CLI workflows, reports, invalid input cases, synthetic teaching provenance and external-data integrity/reference parsing. Test count is software regression evidence, not a clinical accuracy measure; the GitHub commit and CI run identify the published version. [Patient-file verification](PATIENT_FILE_VERIFICATION.md) records the scope of local integration: 1,318 source files hashed, 1,301 CT/dose objects decoded, unchanged source hashes and three case-level outcomes. The [SlicerRT benchmark](../validation/benchmarks/slicerrt/README.md) adds five pinned external examples and selected TPS/dicompyler DVH comparisons. Those selected cases do not establish vendor-wide or population-wide performance.

Reports use explicit Gy, mm and cc units and UTC timestamps. They preserve incomplete evidence and provide concrete next actions for a physicist rather than a single unexplained score. DICOM geometry definitions, TG-201 data-transfer QA and TG-263 nomenclature inform check design. Valency searches supported discovery, with primary references and candidate public benchmarks documented in the [research bibliography](PATIENT_FILE_VERIFICATION.md#supporting-standards-papers-and-datasets). OpenKBP and OpenKBP-Opt remain proposed external benchmarks; their results have not been reproduced by this prototype.

## Next measurable milestones

1. Benchmark representative held-out vendor/site cohorts against independent geometry, DVH and Gamma implementations; define tolerances before assessing results and report discrepancies and failure cases.
2. Measure end-to-end time and manual interventions against a specified manual workflow. Report cohort size, hardware, repeated timings and error-detection sensitivity/false-positive rates with uncertainty; injected defect examples alone are not sensitivity estimates.
3. Add governed protocol selection with fractionation-aware, institution-authorized OAR constraints and a persistent, versioned human-reviewed alias registry.
4. Commission the installed TOPAS runtime, dose scoring and transport examples; add segmentation-specific anatomical and surface-distance assessment before qualifying auto-segmentation models.
5. Validate uncertainty/OOD methods, deployment authentication, durable audit retention and read-only source mounts before expanding beyond a trusted local research deployment.

Hackathon impact is demonstrated through a reproducible end-to-end workflow and explicit evidence. Judging scores, clinical failure prevention, conservation-law verification and clinical certification are not claimed.
