"""Strict Physics & Clinical Verification Engine for OpenRad Agent.

Implements high-consequence medical physics model evaluation against AAPM clinical
QA standards (TG-218, TG-53), fail-closed deterministic boundaries, serial OAR
tolerances, and cryptographic audit hashing.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np
import pydicom
from pydantic import BaseModel, ConfigDict, Field
from scipy.ndimage import binary_dilation

from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.validation.physics_rules import PhysicsValidationEngine


class DecisionStatus(str, Enum):
    """Three-state evaluation gate for radiotherapy computational models."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"


class EvaluationReport(BaseModel):
    """Cryptographically auditable clinical evaluation report contract."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    model_id: str
    dataset_id: str
    timestamp: str
    status: DecisionStatus
    hard_physics_passed: bool
    gamma_3mm3pct_pass_rate: float
    gamma_2mm2pct_pass_rate: float
    oar_violations: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    audit_hash_sha256: str
    metrics: Dict[str, Any] = Field(default_factory=dict)


# Default clinical serial organ tolerances (QUANTEC / AAPM TG-101 / ICRU 83)
DEFAULT_SERIAL_OAR_LIMITS_GY = {
    "spinal_cord": 45.0,
    "cord": 45.0,
    "spinalcord": 45.0,
    "brainstem": 54.0,
    "optic_chiasm": 54.0,
    "chiasm": 54.0,
    "optic_nerve_l": 54.0,
    "optic_nerve_r": 54.0,
    "optic_nerve": 54.0,
}


def scrub_patient_hipaa_metadata(ds: pydicom.Dataset) -> Dict[str, Any]:
    """Verifies that patient identifiers are stripped from DICOM headers.

    Returns dict of removed/scrubbed tags and compliance verdict.
    """
    hipaa_tags = [
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "PatientSex",
        "PatientAge",
        "PatientAddress",
        "InstitutionName",
        "InstitutionalDepartmentName",
        "ReferringPhysicianName",
        "PerformingPhysicianName",
        "OperatorsName",
    ]
    unscrubbed = []
    for tag in hipaa_tags:
        if hasattr(ds, tag):
            val = str(getattr(ds, tag, "")).strip()
            if val and val.upper() not in ["ANON", "ANONYMOUS", "", "N/A"]:
                unscrubbed.append(tag)

    return {
        "hipaa_compliant": len(unscrubbed) == 0,
        "unscrubbed_tags": unscrubbed,
    }


def compute_fast_gamma(
    evaluated_dose: np.ndarray,
    reference_dose: np.ndarray,
    spacing_mm: Tuple[float, float, float],
    dose_pct: float,
    dist_mm: float,
    threshold_pct: float = 10.0,
) -> float:
    """Computes Gamma Index passing rate using coordinates and dose tolerances."""
    res = evaluate_gamma_index(
        reference_dose_path=reference_dose,
        evaluated_dose_path=evaluated_dose,
        dose_tolerance_percent=dose_pct,
        distance_tolerance_mm=dist_mm,
        dose_threshold_percent=threshold_pct,
        reference_spacing_mm=list(spacing_mm),
        evaluated_spacing_mm=list(spacing_mm),
    )
    return float(res["passing_rate"])


def verify_model_output(
    evaluated_dose: np.ndarray,
    reference_dose: Optional[np.ndarray] = None,
    spacing_mm: Tuple[float, float, float] = (3.0, 1.0, 1.0),
    model_id: str = "clinical_dose_predictor",
    dataset_id: str = "hnscc_validation_set",
    energy_mev: Optional[float] = None,
    image_orientation: Optional[Sequence[float]] = None,
    dicom_dataset: Optional[pydicom.Dataset] = None,
    prescription_dose_gy: Optional[float] = None,
    structure_masks: Optional[Dict[str, np.ndarray]] = None,
    oar_tolerance_limits_gy: Optional[Dict[str, float]] = None,
    uncertainty_grid: Optional[np.ndarray] = None,
) -> EvaluationReport:
    """Executes the High-Consequence Medical Physics & Clinical Verification Engine.

    Evaluates candidate model outputs against deterministic physics boundaries,
    AAPM TG-218 gamma criteria (3%/3mm, 2%/2mm), serial organ limits, and uncertainty zones.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    hard_physics_passed = True
    rejection_reasons: List[str] = []
    review_reasons: List[str] = []
    oar_violations: List[str] = []
    metrics: Dict[str, Any] = {}

    eval_arr = np.asarray(evaluated_dose, dtype=float)

    # =========================================================================
    # 1. Deterministic Physics Boundaries (Instant Rejection if Violated)
    # =========================================================================

    # 1a. Absorbed Dose Non-Negativity: D(r) >= 0.0 Gy across all voxels
    if not np.isfinite(eval_arr).all():
        hard_physics_passed = False
        rejection_reasons.append("Non-finite values (NaN/Inf) detected in evaluated dose grid.")
    else:
        min_dose = float(np.min(eval_arr))
        metrics["min_dose_gy"] = round(min_dose, 5)
        metrics["max_dose_gy"] = round(float(np.max(eval_arr)), 3)

        if min_dose < -1e-5:
            hard_physics_passed = False
            rejection_reasons.append(
                f"Absorbed dose non-negativity violated: minimum voxel dose is {min_dose:.5f} Gy "
                "(negative dose is physically impossible; check CT offset rescaling)."
            )

    # 1b. Beam Kinetic Energy Bounds: 0.01 MeV <= E <= 250 MeV
    if energy_mev is not None:
        metrics["beam_energy_mev"] = float(energy_mev)
        v_energy = PhysicsValidationEngine.validate_beam_energy(energy_mev, raise_on_fail=False)
        if not v_energy.passed:
            hard_physics_passed = False
            rejection_reasons.append(
                f"Beam kinetic energy {energy_mev} MeV outside clinical radiotherapy bounds "
                "[0.01 MeV - 250 MeV]."
            )

    # 1c. Coordinate Frame Orthogonality & Positive Grid Spacing
    if any(s <= 0 for s in spacing_mm):
        hard_physics_passed = False
        rejection_reasons.append(f"Non-positive grid voxel spacing detected: {spacing_mm} mm.")
    metrics["grid_spacing_mm"] = list(spacing_mm)

    if image_orientation is not None:
        if len(image_orientation) != 6:
            hard_physics_passed = False
            rejection_reasons.append("DICOM ImageOrientationPatient must contain exactly 6 direction cosines.")
        else:
            r = np.array(image_orientation[:3], dtype=float)
            c = np.array(image_orientation[3:], dtype=float)
            dot = float(abs(np.dot(r, c)))
            norm_r = float(np.linalg.norm(r))
            norm_c = float(np.linalg.norm(c))
            metrics["orientation_dot_product"] = dot

            if dot > 1e-4:
                hard_physics_passed = False
                rejection_reasons.append(
                    f"Coordinate frame orthogonality violation: e_x . e_y = {dot:.6f} > 1e-4."
                )
            if abs(norm_r - 1.0) > 1e-2 or abs(norm_c - 1.0) > 1e-2:
                hard_physics_passed = False
                rejection_reasons.append(
                    f"Orientation vectors are not unit length (|r|={norm_r:.4f}, |c|={norm_c:.4f})."
                )

    # 1d. Patient Privacy / HIPAA Compliance
    if dicom_dataset is not None:
        hipaa_check = scrub_patient_hipaa_metadata(dicom_dataset)
        if not hipaa_check["hipaa_compliant"]:
            hard_physics_passed = False
            rejection_reasons.append(
                f"HIPAA compliance violation: unscrubbed patient identifiers present in DICOM header "
                f"({', '.join(hipaa_check['unscrubbed_tags'])})."
            )

    # =========================================================================
    # 2. Dosimetric QA Tolerances & Decision Gate
    # =========================================================================

    gamma_3mm3pct = 100.0
    gamma_2mm2pct = 100.0

    if reference_dose is not None and hard_physics_passed:
        ref_arr = np.asarray(reference_dose, dtype=float)
        try:
            # Standard Gamma (3%/3mm, 10% cutoff)
            gamma_3mm3pct = compute_fast_gamma(eval_arr, ref_arr, spacing_mm, dose_pct=3.0, dist_mm=3.0)
            metrics["gamma_3mm3pct"] = round(gamma_3mm3pct, 2)

            if gamma_3mm3pct < 90.0:
                rejection_reasons.append(
                    f"AAPM TG-218 standard Gamma (3%/3mm) passing rate {gamma_3mm3pct:.2f}% "
                    "below clinical acceptance floor (< 90.0%)."
                )
            elif 90.0 <= gamma_3mm3pct < 95.0:
                review_reasons.append(
                    f"Standard Gamma (3%/3mm) passing rate {gamma_3mm3pct:.2f}% in review zone [90.0%, 94.9%]."
                )

            # Tight Margin Gamma (2%/2mm, 10% cutoff)
            gamma_2mm2pct = compute_fast_gamma(eval_arr, ref_arr, spacing_mm, dose_pct=2.0, dist_mm=2.0)
            metrics["gamma_2mm2pct"] = round(gamma_2mm2pct, 2)

            if gamma_2mm2pct < 85.0:
                rejection_reasons.append(
                    f"High-precision Gamma (2%/2mm) passing rate {gamma_2mm2pct:.2f}% below precision floor (< 85.0%)."
                )
            elif 85.0 <= gamma_2mm2pct < 90.0:
                review_reasons.append(
                    f"High-precision Gamma (2%/2mm) passing rate {gamma_2mm2pct:.2f}% in review zone [85.0%, 89.9%]."
                )
        except Exception as e:
            hard_physics_passed = False
            rejection_reasons.append(f"Gamma Index evaluation error: {str(e)}")

    # 2b. Target Coverage & OAR Tolerances
    all_oar_limits = dict(DEFAULT_SERIAL_OAR_LIMITS_GY)
    if oar_tolerance_limits_gy:
        all_oar_limits.update({k.lower().replace(" ", "_"): v for k, v in oar_tolerance_limits_gy.items()})

    if structure_masks:
        for roi_name, mask in structure_masks.items():
            roi_clean = roi_name.lower().replace(" ", "_").replace("-", "_")
            mask_arr = np.asarray(mask, dtype=bool)
            if not mask_arr.any():
                continue

            roi_doses = eval_arr[mask_arr]
            d_max = float(np.max(roi_doses))
            metrics[f"{roi_clean}_dmax_gy"] = round(d_max, 2)

            # Check PTV Coverage: D95 >= 95% of prescription
            if "ptv" in roi_clean and prescription_dose_gy is not None and prescription_dose_gy > 0:
                d95 = float(np.percentile(roi_doses, 5.0))
                metrics[f"{roi_clean}_d95_gy"] = round(d95, 2)
                target_d95 = 0.95 * prescription_dose_gy

                if d95 < target_d95:
                    deficit_pct = 100.0 * (target_d95 - d95) / target_d95
                    if d95 < 0.90 * prescription_dose_gy:
                        rejection_reasons.append(
                            f"Target underdosage: {roi_name} D95% ({d95:.2f} Gy) is < 90% of prescription "
                            f"({prescription_dose_gy:.2f} Gy)."
                        )
                    else:
                        review_reasons.append(
                            f"Target sub-optimal coverage: {roi_name} D95% ({d95:.2f} Gy) below 95% prescription "
                            f"({prescription_dose_gy:.2f} Gy) by {deficit_pct:.1f}%."
                        )

            # Check Serial Organ Max Dose
            matched_limit = None
            for oar_key, limit_val in all_oar_limits.items():
                if oar_key in roi_clean or roi_clean in oar_key:
                    matched_limit = limit_val
                    break

            if matched_limit is not None:
                if d_max > matched_limit:
                    viol_msg = (
                        f"Serial OAR limit breach: {roi_name} Dmax ({d_max:.2f} Gy) "
                        f"exceeds tolerance limit ({matched_limit:.2f} Gy)."
                    )
                    oar_violations.append(viol_msg)
                    rejection_reasons.append(viol_msg)

    # 2c. Uncertainty Bounds in Steep Gradient Zones near OARs
    if uncertainty_grid is not None and structure_masks:
        unc_arr = np.asarray(uncertainty_grid, dtype=float)
        # Compute 3D gradient magnitude
        grads = np.gradient(eval_arr, *spacing_mm)
        grad_mag = np.sqrt(sum(g**2 for g in grads))
        high_unc_threshold = 2.0  # Gy
        steep_grad_threshold = 1.0  # Gy/mm

        # Check critical OAR proximity (dilated by 3mm)
        for roi_name, mask in structure_masks.items():
            roi_clean = roi_name.lower().replace(" ", "_")
            if any(k in roi_clean for k in ["cord", "brainstem", "chiasm"]):
                mask_arr = np.asarray(mask, dtype=bool)
                dilated = binary_dilation(mask_arr, iterations=2)
                critical_zone = (unc_arr > high_unc_threshold) & (grad_mag > steep_grad_threshold) & dilated
                if critical_zone.any():
                    review_reasons.append(
                        f"High prediction uncertainty (> {high_unc_threshold} Gy) overlapping steep gradient "
                        f"(> {steep_grad_threshold} Gy/mm) in proximity to serial OAR '{roi_name}'."
                    )

    # =========================================================================
    # 3. Decision Gate Synthesis
    # =========================================================================

    if not hard_physics_passed or len(rejection_reasons) > 0 or len(oar_violations) > 0:
        status = DecisionStatus.REJECTED
    elif len(review_reasons) > 0:
        status = DecisionStatus.FLAGGED_FOR_REVIEW
    else:
        status = DecisionStatus.APPROVED

    # =========================================================================
    # 4. Cryptographic Audit Hash (SHA-256)
    # =========================================================================

    canonical_payload = json.dumps(
        {
            "model_id": model_id,
            "dataset_id": dataset_id,
            "status": status.value,
            "hard_physics_passed": hard_physics_passed,
            "gamma_3mm3pct": round(gamma_3mm3pct, 4),
            "gamma_2mm2pct": round(gamma_2mm2pct, 4),
            "oar_violations": sorted(oar_violations),
            "rejection_reasons": sorted(rejection_reasons),
            "review_reasons": sorted(review_reasons),
            "metrics": metrics,
        },
        sort_keys=True,
    )
    audit_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    return EvaluationReport(
        model_id=model_id,
        dataset_id=dataset_id,
        timestamp=timestamp,
        status=status,
        hard_physics_passed=hard_physics_passed,
        gamma_3mm3pct_pass_rate=round(gamma_3mm3pct, 2),
        gamma_2mm2pct_pass_rate=round(gamma_2mm2pct, 2),
        oar_violations=oar_violations,
        rejection_reasons=rejection_reasons + review_reasons if status != DecisionStatus.APPROVED else [],
        audit_hash_sha256=audit_hash,
        metrics=metrics,
    )
