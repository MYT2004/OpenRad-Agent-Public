# Medical physics audit — 21 October 2026

Baseline: GitHub main e62a73a. Status: research prototype; ALL-standards compliance is NOT established. This is a source-code review and synthetic regression exercise, not clinical commissioning or regulatory certification. Jurisdiction, intended use, machine modalities, patient populations and institutional protocols remain unspecified.

## Findings and mitigations

- Critical: NaN beam energy, infinite dose and invalid spacing could pass sanity checks. Reject non-finite values; negative dose rejected by default without silent repair. Orientation numerical acceptance tightened to 1e-4 (engineering policy, not a clinical error margin).
- Critical: DICOM spatial defaults could assign false locations/units. Both tools now reject missing dose units/scaling/geometry, relative/nonphysical dose, noncanonical orientation, nonuniform/absolute frame offsets and single-frame data. These are unsupported cases, not invalid DICOM in general. DVH requires matching patient and frame identifiers and exact ROI names.
- Critical: heuristic agent silently clamped invalid beam energies and substituted the same sample as both gamma inputs. Removed these substitutions; failures now require corrected explicit inputs.
- High: gamma used a truncated neighborhood and fabricated gamma for absent neighbors. Joint distance/dose KD-tree now computes exact discrete nearest-neighbor gamma. Defaults are 3% global / 2 mm / 10% cutoff. No interpolation, measurement uncertainty, clinical release decision or commissioned sampling-convergence evidence exists. Bare arrays still explicitly assume Gy and 1 mm spacing.
- High: malformed DVHs were normalized using absolute differences or uniform weights. Reject negative/nonfinite/zero volumes, unordered dose bins, nonmonotonic cumulative curves and incomplete cumulative tails. Cumulative/differential inference remains ambiguous; an explicit format contract and parameter provenance are still needed.
- Critical: patient CT option generated a homogeneous water box. That option now aborts. TOPAS decks still need actual TOPAS execution, commissioned beam models, material conversion, scoring validation and statistical convergence studies.

## Standards and evidence matrix

| Reference | Applicability and current evidence | Release gap |
| --- | --- | --- |
| DICOM PS3.3 RT Dose / frame offsets | Restricted axial geometry checks and explicit units | Full IOD conformance, linkage, registrations, contour topology and independent vendor fixtures |
| AAPM TG-218 | Default numeric criteria corrected; discrete algorithm only | Commission against independent reference; assess interpolation/grid resolution, detector response, normalization and uncertainty; institution-specific limits |
| AAPM TG-100 | This initial hazard list and regression suite | Clinical process map, multidisciplinary FMEA, owners, residual risk acceptance, incident learning |
| AAPM TG-275 | Human review required; no complete plan/chart review implementation | Qualified physicist workflow, independent plan/prescription verification and sign-off |
| Dose calculation / machine QA / calibration | No physical measurements supplied | Determine applicable TG-51/TRS-398, MPPG 5, TG-142/MPPG 8, small-field/brachy/proton protocols by actual intended use and edition |
| Radiobiology | Mathematical sanity checks only | Endpoint/population/fractionation fit, parameter citations, external validation and uncertainty; current TCP label does not establish a fractionation-aware LQ model |
| Software lifecycle / regulation | No conformity assessment | Determine jurisdiction and applicability of IEC 62304, ISO 14971, IEC 62366-1 and local device/data requirements; licensed normative text and clinical evidence required |

## Error margins and discrepancy management

No universal dose uncertainty or probabilistic confidence bound can be inferred from software alone. Do not treat round-off thresholds or the 0.01–250 MeV application energy policy as clinical standards. Establish a measured uncertainty budget covering calibration, detector response, setup/registration, dose grid/interpolation, contour rasterization, Monte Carlo statistics and model parameters. State units, correlations, coverage factor and acceptance rules. Escalate unresolved disagreement; never alter source patient data to make a check pass.

Known residual hazards: DVH holes/overlapping contours and repeated slice sampling can bias volumes; nearest-slice mapping and partial grid coverage lack validated uncertainty. LKB overflow, zero-dose TCP flooring, implicit model defaults and fractionation handling need further work. REPL validation is name-based and does not establish complete mediation of arbitrary scripts. No PHI/security review was performed.

Every GitHub push/PR runs synthetic regressions once this workflow is pushed. This detects known software regressions; it does not continuously monitor clinical discrepancies or new standard editions. Maintain a discrepancy register with source/version, expected/observed result, uncertainty, severity, owner, resolution and independent reviewer. Clinical deployment remains blocked pending commissioning and closure of critical hazards. No recurring automation was created.

## Primary references

- https://dicom.nema.org/medical/dicom/2024e/output/chtml/part03/sect_C.8.8.3.html
- https://dicom.nema.org/medical/dicom/2022e/output/chtml/part03/sect_C.8.8.3.2.html
- https://www.aapm.org/pubs/reports/detail.asp?docid=173 (TG-218)
- https://aapm.org/pubs/reports/detail.asp?docid=156 (TG-100; also located using Valency, PMID 27370140)
- https://www.aapm.org/pubs/reports/detail.asp?docid=198 (TG-275)

Sources were consulted for scope and selected requirements; the matrix is not an exhaustive normative clause review or a claim that these editions are the newest editions.

## Validation result

71 tests passed on Python 3.9, including TG-263 naming and synthetic DVH integration (14 upstream matplotlib/pyparsing deprecation warnings). No patient measurements, external dose-engine comparison, TOPAS runtime or full normative standards assessment was available. GitHub workflow activation and its result are recorded in the delivery message.

## TG-263 follow-up

See [implementation scope and provenance](docs/TG263.md). Added the official pinned vocabulary, collision detection, explicit reviewed aliases and unit-explicit metric outputs. This applies nomenclature checks within the documented scope; anatomy, complex naming forms and clinical commissioning still require review.

## Local integration follow-up

Local workflows now discover linked DICOM objects, verify course references, use contour rather than dose-grid slab thickness, interpolate z-dose and quarantine malformed contours. API mappings are forwarded and synthetic patient outputs have been removed. See docs/LOCAL_WORKFLOWS.md; dataset-specific evidence remains in ignored local reports. 86 automated tests plus real-data UI/API checks were performed. Prior DVH volume estimates should not be reused. Clinical release blockers remain open.
