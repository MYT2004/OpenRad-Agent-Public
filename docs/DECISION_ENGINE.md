# Research model decision engine

`src/decision.py` defines a strict Pydantic contract. `src/evaluation.py` reads numeric NPY arrays with `allow_pickle=False`, computes metrics, applies rules and writes an audit event. Model weights are hashed only: no model code is imported or executed. Use pseudonyms in `model_name` and `dataset_id`.

`APPROVED` means a research candidate on **one supplied case**, never clinical release or approval of a model across its intended population. All results have `clinical_release=false`. Missing evidence produces `FLAGGED_FOR_REVIEW`; failed physical checks produce `REJECTED`. Invalid request schemas return HTTP 422 before evaluation. Unreadable/corrupt evaluation inputs produce an audited rejection when session storage is available. Storage/audit failures return an error without claiming a committed result.

## Run

```bash
python agent_main.py --storage-dir storage/sessions evaluate --manifest evaluation.json
```

Exit codes: 0 candidate, 3 review, 2 reject/error. The same contract is accepted by `POST /api/v1/evaluations` and the frontend's **Model Evaluation & Triage** workflow. The REST endpoint creates a fresh session; generated plots are served through the existing restricted artifact endpoint. Audit files are not publicly mounted. Operator access to session files is needed for verification/export.

Minimal manifest (all paths refer to existing files; grids must reflect independently verified source geometry):

```json
{
  "model_name": "dose-model-v1",
  "dataset_id": "phantom-001",
  "model_kind": "dose_predictor",
  "model_weights_path": "/input/weights.bin",
  "input_paths": ["/input/source-series-file.dcm"],
  "reference_path": "/input/reference.npy",
  "prediction_path": "/input/prediction.npy",
  "image_grid": {"shape": [3,3,3], "spacing_mm": [2,2,2], "origin_mm": [0,0,0], "frame_id": "registered-frame"},
  "reference_grid": {"shape": [3,3,3], "spacing_mm": [2,2,2], "origin_mm": [0,0,0], "frame_id": "registered-frame"},
  "prediction_grid": {"shape": [3,3,3], "spacing_mm": [2,2,2], "origin_mm": [0,0,0], "frame_id": "registered-frame"},
  "prescription_gy": 40,
  "target_mask_path": "/input/ptv.npy",
  "oar_mask_paths": {"Brainstem": "/input/brainstem.npy"},
  "oar_limits_gy": {"Brainstem": 50}
}
```

This minimal example requires review because calibration and uncertainty evidence are absent. Include every source-series file in `input_paths`; completeness is an operator responsibility. The evaluator does not parse DICOM to verify this manifest's geometry declarations. Use the existing DICOM workflow for UID linkage, scrubbed analysis and DVH analysis, then validate any exported reference-grid masks independently. Array axes are z,y,x; directions are an orthonormal 3×3 row-major matrix shared by all grids. Mask coordinates belong to `image_grid`. All masks must be binary and nonempty, with exactly matching shapes. OAR keys must be canonical TG-263 names. Naming cannot establish correct anatomy. No registration or resampling is guessed.

## Exact policy

| Metric | Candidate | Review | Reject |
|---|---|---|---|
| Custom global 3%/3 mm gamma | ≥95% | ≥90%, <95% | <90% |
| Custom global 2%/2 mm gamma | ≥90% | ≥85%, <90% | <85% |
| TG-218 reference global 3%/2 mm gamma | ≥95% | ≥90%, <95% | <90% |
| PTV D95 / prescription | ≥95% | ≥93%, <95% | <93% |
| MAE / prescription | <1.5% | 1.5–3% inclusive | >3% |
| OAR voxel Dmax / supplied limit | <98% | 98–100% inclusive | >100% |

The OAR review band deliberately takes precedence over the overlapping “≤100% pass” range in the requested table. Limits must be supplied for every evaluated OAR and must account for fractionation, endpoint, prior treatment and protocol; the application does not infer clinical tolerances. MAE is over the complete common grid. D95 is the linear fifth percentile of equal-volume target voxels. Dmax is the maximum sampled voxel value, not D0.03cc or an interpolated anatomical maximum.

Gamma uses 10% of reference maximum as cutoff and global reference-maximum normalization. This is exact **discrete** nearest-neighbour gamma, without interpolation; it is not a commissioned implementation of all TG-218 procedures. The 3%/2 mm reference limits come from [AAPM TG-218](https://www.aapm.org/pubs/reports/detail.asp?docid=173). The additional custom criteria are research policy, not universal TG-218 requirements. Resource limits flag oversized grids for review rather than sampling or silently reducing resolution.

Hard rejections include negative/nonfinite dose, shape/frame/origin/spacing/direction disagreement, nonpositive reference maximum, invalid masks, probabilities outside [0,1], negative fluence, configured fluence excess, supplied energy outside 0.01–250 MeV, and mass density outside (0, configured maximum]. The default 3 g/cm³ mass density bound is an application restriction and can exclude valid metals; it is not an electron-density unit or a universal physical law. Energy limits are the application's supported range, not a universal range for every radiotherapy modality. Monte Carlo requests missing energy or density evidence require review.

Optional `depth_dose_path` is an NPY array of [depth_mm, dose_Gy] rows. Increasing dose beyond the supplied tolerance after `buildup_end_mm` rejects only when `homogeneous_photon_depth_dose=true`. This test must not be applied indiscriminately to proton Bragg peaks, heterogeneities or arbitrary clinical beam arrangements. An inapplicable profile triggers review. Tolerance is explicit, never automatically enlarged to obtain a pass.

## Uncertainty and OOD evidence

Supply a nonnegative `uncertainty_std_path` map in Gy (standard deviation, not variance), `confidence`, `ood_score`, and hashable `qualification_evidence_path`, `uncertainty_calibration_path`, `ood_calibration_path`. Missing evidence requires review. These files are hashed but **their scientific validity is not independently certified**. A placeholder file can satisfy evidence presence; commissioning must establish provenance, adequacy and independent approval of these records before this workflow is used for consequential decisions.

Default research policy: maximum SD <2 Gy; steep gradient ≥1 Gy/mm; no SD ≥2 Gy within 3 mm of an OAR where the gradient is steep; confidence ≥0.95; OOD score ≤0.1. SD failures and OOD flags require review; supplied confidence below its limit rejects. `ood_flags` can identify `metal_artifact`, `post_surgical`, `pediatric`, `unseen_geometry`. The evaluator consumes externally derived flags/scores; it does not claim to detect these anatomies itself. No uncertainty or confidence is fabricated. Thresholds are configurable in `policy` and recorded with each result. Difference maps, SD heatmaps, and reference/model cumulative DVH overlays are generated for cases that pass physical checks.

Auto-segmentation requests cannot be approved under this dose policy: they require a separate validated Dice, surface-distance and anatomical review workflow. This version also does not execute model inference, ensembles, clinical OOD detection or Monte Carlo transport. The existing TOPAS generator emits [seed 42](https://github.com/topasmc/topas-docs/blob/master/parameters/intro/batch_jobs.rst) and one thread; runtime, physics tables and hardware still require validation. Evaluations are deterministic on supplied arrays and record the declared inference seed and library versions. Setting a seed alone cannot guarantee reproducible external GPU inference. Changes in runtime or implementation can change metrics and decision hashes.

## Audit and signed review

Each evaluation records SHA-256 hashes of supplied model weights, source files, prediction, reference, masks and optional evidence; exact observed values, rule outcomes, criteria, policy and a deterministic decision hash. Paths and original DICOM identifiers are not written into evaluation results. The request is hashed rather than logged verbatim. Timestamps and plot UUIDs are outside the deterministic decision hash. Evaluation events are appended to `decisions.jsonl` with sequence numbers, previous-event hashes, locking and fsync. Verification detects local changes/reordering; a local hash chain alone cannot detect complete rollback or establish regulatory compliance. Production requires durable authenticated storage, external chain-head anchoring, retention controls and access control. Cloud Run's default ephemeral session storage is insufficient for regulated records.

Reviewer identity comes from an operator-controlled `OPENRAD_REVIEWER_KEYS` JSON mapping of reviewer IDs to base64 raw Ed25519 public keys. Keep private keys outside the application; register only independently authenticated, authorized reviewers. Application key possession does not independently verify professional credentials.

Sign the following exact UTF-8 canonical JSON bytes: sorted keys, separators `(',', ':')`, no NaN. Use `src.governance.canonical` and an external Ed25519 signer. Submit to `POST /api/v1/sessions/{session_id}/reviews`:

```json
{
  "payload": {
    "decision_hash": "HASH_FROM_EVALUATION",
    "session_id": "SESSION_FROM_EVALUATION",
    "reviewer_id": "physicist-1",
    "disposition": "FLAGGED_FOR_REVIEW",
    "justification": "Independent measurement required before proceeding",
    "nonce": "UNIQUE_VALUE_AT_LEAST_16_CHARACTERS"
  },
  "signature_b64": "BASE64_ED25519_SIGNATURE"
}
```

Unregistered reviewers, wrong signatures, absent/short justifications, mismatched decisions/sessions and replayed nonces are rejected. Signed dispositions are separate audit events: the automated result is immutable. Hard physical rejections cannot be changed into approvals; correct a derived output and evaluate again. A signed research disposition never releases a clinical treatment. Reviewer notes must exclude PHI.

## Raw-data boundary and outstanding validation

The evaluator only opens sources for reading. Tests hash synthetic source files before/after evaluation. Session storage and TOPAS outputs are blocked beneath paths named `raw`, configured `OPENRAD_DATA_ROOTS`, including resolved symlinks. Use read-only filesystem/container mounts for OS-enforced protection; application path checks do not replace OS permissions. Never alter source DICOM files to resolve frame or contour discrepancies. Derivatives belong in separate output storage and need provenance.

Before clinical claims: commission dose/gamma against independent physical measurements and relevant protocols; validate registration and masks; establish site/fractionation-specific constraints; calibrate uncertainty, OOD and confidence on representative held-out and adversarial cohorts; add segmentation-specific validation; validate Monte Carlo transport; deploy authenticated APIs, authorized reviewer registration, durable audited storage and reproducible environments. This POC does not establish TG-53, TG-218, TG-263 or FDA SaMD conformity in full. See [FDA good machine learning practice](https://www.fda.gov/medical-devices/artificial-intelligence-enabled-medical-devices/good-machine-learning-practice-medical-device-development-guiding-principles) for development and evaluation context.
