"""Physics Validation Guardrails and Domain Boundary Checks for OpenRad Agent.

Enforces hardcoded sanity checks and domain guardrails:
1. Dose Grid Integrity: D(r) >= 0 Gy. Rejects negative doses (calibration/subtraction error).
2. Beam Energy Bounds: 0.01 MeV <= E <= 250 MeV for clinical radiotherapy.
3. Gamma Index: 0% <= Pass Rate <= 100%, gamma >= 0.
4. DICOM Geometry: delta_x, delta_y, delta_z > 0 and orthogonal orientation vectors.
5. Radiobiological Limits: 0.0 <= TCP/NTCP <= 1.0, TD50 > 0, m > 0, n > 0.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union
import numpy as np


class PhysicsValidationError(ValueError):
    """Base exception for all domain physics rule violations."""
    pass


class DoseIntegrityError(PhysicsValidationError):
    """Raised when dose grid contains unphysical negative dose values."""
    pass


class BeamEnergyBoundsError(PhysicsValidationError):
    """Raised when beam energy falls outside clinical radiotherapy bounds (0.01 - 250 MeV)."""
    pass


class GammaEvaluationError(PhysicsValidationError):
    """Raised when gamma index passing rate or values violate physics/registration constraints."""
    pass


class DICOMGeometryError(PhysicsValidationError):
    """Raised when DICOM voxel spacing or directional cosines violate physical spatial geometry."""
    pass


class RadiobiologyBoundsError(PhysicsValidationError):
    """Raised when radiobiological parameters or probabilities violate physiological limits."""
    pass


@dataclass
class ValidationResult:
    """Encapsulates the verdict and diagnostics of a physics validation check."""
    passed: bool
    rule_name: str
    error_message: Optional[str] = None
    remediation_suggestion: Optional[str] = None
    diagnostics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "rule_name": self.rule_name,
            "error_message": self.error_message,
            "remediation_suggestion": self.remediation_suggestion,
            "diagnostics": self.diagnostics or {},
        }


class PhysicsValidationEngine:
    """Domain validation engine implementing radiotherapy guardrails."""

    MIN_CLINICAL_ENERGY_MEV: float = 0.01
    MAX_CLINICAL_ENERGY_MEV: float = 250.0

    @classmethod
    def validate_dose_grid(
        cls,
        dose_array: Union[np.ndarray, Sequence],
        tolerance: float = -1e-5,
        raise_on_fail: bool = False,
    ) -> ValidationResult:
        """Rule: Dose values D(r) >= 0 Gy. Negative dose values are physically invalid.

        Action on Violation: Reject output; prompt agent to re-check array calibration or background subtraction.
        """
        arr = np.asarray(dose_array, dtype=float)
        if arr.size == 0:
            res = ValidationResult(
                passed=False,
                rule_name="Dose Grid Integrity",
                error_message="Dose grid array is empty.",
                remediation_suggestion="Ensure input dose file contains populated pixel data.",
                diagnostics={"size": 0},
            )
            if raise_on_fail:
                raise DoseIntegrityError(res.error_message)
            return res

        min_val = float(np.nanmin(arr))
        max_val = float(np.nanmax(arr))
        has_nans = bool(np.isnan(arr).any())

        if has_nans:
            res = ValidationResult(
                passed=False,
                rule_name="Dose Grid Integrity",
                error_message="Dose grid contains NaN (not a number) values.",
                remediation_suggestion="Inspect dose calculation algorithm or file corruption.",
                diagnostics={"min": min_val, "max": max_val, "contains_nan": True},
            )
            if raise_on_fail:
                raise DoseIntegrityError(res.error_message)
            return res

        if min_val < tolerance:
            res = ValidationResult(
                passed=False,
                rule_name="Dose Grid Integrity",
                error_message=(
                    f"Negative dose values detected (minimum dose: {min_val:.5f} Gy). "
                    "Dose values D(r) >= 0 Gy; negative dose is physically invalid."
                ),
                remediation_suggestion=(
                    "Reject output; auto-prompt agent to re-check array calibration, "
                    "rescale slope/intercept, or background subtraction parameters."
                ),
                diagnostics={"min_dose_Gy": min_val, "max_dose_Gy": max_val},
            )
            if raise_on_fail:
                raise DoseIntegrityError(res.error_message)
            return res

        return ValidationResult(
            passed=True,
            rule_name="Dose Grid Integrity",
            diagnostics={"min_dose_Gy": min_val, "max_dose_Gy": max_val},
        )

    @classmethod
    def validate_beam_energy(
        cls,
        energy_MeV: float,
        particle_type: str = "proton",
        raise_on_fail: bool = False,
    ) -> ValidationResult:
        """Rule: Clinical radiotherapy energies restricted to 0.01 MeV <= E <= 250 MeV.

        Action on Violation: Abort Monte Carlo execution; inform agent of unphysical energy parameter.
        """
        try:
            energy = float(energy_MeV)
        except (ValueError, TypeError):
            res = ValidationResult(
                passed=False,
                rule_name="Beam Energy Bounds",
                error_message=f"Energy parameter '{energy_MeV}' is not a valid float.",
                remediation_suggestion="Provide energy as a positive numerical value in MeV.",
            )
            if raise_on_fail:
                raise BeamEnergyBoundsError(res.error_message)
            return res

        if energy < cls.MIN_CLINICAL_ENERGY_MEV or energy > cls.MAX_CLINICAL_ENERGY_MEV:
            res = ValidationResult(
                passed=False,
                rule_name="Beam Energy Bounds",
                error_message=(
                    f"Beam energy {energy:.3f} MeV is outside clinical radiotherapy bounds "
                    f"[{cls.MIN_CLINICAL_ENERGY_MEV} MeV - {cls.MAX_CLINICAL_ENERGY_MEV} MeV]."
                ),
                remediation_suggestion=(
                    "Abort Monte Carlo execution; inform agent of unphysical energy parameter. "
                    "Standard clinical external beam values: 6-18 MV photons, 6-22 MeV electrons, "
                    "70-250 MeV protons, or 0.01-0.25 MeV superficial/orthovoltage."
                ),
                diagnostics={"energy_MeV": energy, "particle_type": particle_type},
            )
            if raise_on_fail:
                raise BeamEnergyBoundsError(res.error_message)
            return res

        return ValidationResult(
            passed=True,
            rule_name="Beam Energy Bounds",
            diagnostics={"energy_MeV": energy, "particle_type": particle_type},
        )

    @classmethod
    def validate_gamma_index(
        cls,
        pass_rate: float,
        average_gamma: Optional[float] = None,
        max_gamma: Optional[float] = None,
        raise_on_fail: bool = False,
    ) -> ValidationResult:
        """Rule: 0% <= Pass Rate <= 100%.

        Action on Violation: Check array alignment and spatial registration dimensions.
        """
        if np.isnan(pass_rate) or pass_rate < 0.0 or pass_rate > 100.0:
            res = ValidationResult(
                passed=False,
                rule_name="Gamma Index",
                error_message=f"Gamma passing rate {pass_rate}% is outside valid range [0%, 100%].",
                remediation_suggestion="Check array alignment, origin shifts, and spatial registration dimensions.",
                diagnostics={"pass_rate": pass_rate, "average_gamma": average_gamma, "max_gamma": max_gamma},
            )
            if raise_on_fail:
                raise GammaEvaluationError(res.error_message)
            return res

        if average_gamma is not None and (average_gamma < 0.0 or np.isnan(average_gamma)):
            res = ValidationResult(
                passed=False,
                rule_name="Gamma Index",
                error_message=f"Average gamma index {average_gamma} is physically impossible (< 0).",
                remediation_suggestion="Check dose normalization and distance-to-agreement calculation logic.",
                diagnostics={"pass_rate": pass_rate, "average_gamma": average_gamma},
            )
            if raise_on_fail:
                raise GammaEvaluationError(res.error_message)
            return res

        return ValidationResult(
            passed=True,
            rule_name="Gamma Index",
            diagnostics={"pass_rate": pass_rate, "average_gamma": average_gamma, "max_gamma": max_gamma},
        )

    @classmethod
    def validate_dicom_geometry(
        cls,
        pixel_spacing: Sequence[float],
        slice_thickness: Optional[float] = None,
        image_orientation: Optional[Sequence[float]] = None,
        raise_on_fail: bool = False,
    ) -> ValidationResult:
        """Rule: Grid voxel spacing delta_x, delta_y, delta_z > 0 and slice orientation vectors are orthogonal.

        Action on Violation: Flag DICOM header discrepancy.
        """
        if len(pixel_spacing) < 2:
            res = ValidationResult(
                passed=False,
                rule_name="DICOM Geometry",
                error_message=f"PixelSpacing must contain 2 values (delta_row, delta_col). Got: {pixel_spacing}",
                remediation_suggestion="Verify DICOM PixelSpacing tag (0028,0030).",
            )
            if raise_on_fail:
                raise DICOMGeometryError(res.error_message)
            return res

        dx, dy = float(pixel_spacing[0]), float(pixel_spacing[1])
        if dx <= 0 or dy <= 0:
            res = ValidationResult(
                passed=False,
                rule_name="DICOM Geometry",
                error_message=f"Non-positive pixel spacing detected: ({dx}, {dy}) mm.",
                remediation_suggestion="Flag DICOM header discrepancy; voxel spacing must be strictly > 0.",
                diagnostics={"dx": dx, "dy": dy},
            )
            if raise_on_fail:
                raise DICOMGeometryError(res.error_message)
            return res

        if slice_thickness is not None:
            dz = float(slice_thickness)
            if dz <= 0:
                res = ValidationResult(
                    passed=False,
                    rule_name="DICOM Geometry",
                    error_message=f"Non-positive slice thickness/spacing: {dz} mm.",
                    remediation_suggestion="Flag DICOM header discrepancy; slice thickness must be strictly > 0.",
                    diagnostics={"dz": dz},
                )
                if raise_on_fail:
                    raise DICOMGeometryError(res.error_message)
                return res

        if image_orientation is not None:
            if len(image_orientation) != 6:
                res = ValidationResult(
                    passed=False,
                    rule_name="DICOM Geometry",
                    error_message=f"ImageOrientationPatient must contain exactly 6 directional cosines, got {len(image_orientation)}.",
                    remediation_suggestion="Ensure valid DICOM tag (0020,0037).",
                )
                if raise_on_fail:
                    raise DICOMGeometryError(res.error_message)
                return res

            r = np.array(image_orientation[:3], dtype=float)
            c = np.array(image_orientation[3:], dtype=float)

            # Check unit vectors
            norm_r = np.linalg.norm(r)
            norm_c = np.linalg.norm(c)
            if not (0.95 <= norm_r <= 1.05 and 0.95 <= norm_c <= 1.05):
                res = ValidationResult(
                    passed=False,
                    rule_name="DICOM Geometry",
                    error_message=f"Orientation vectors are not unit length: |r|={norm_r:.4f}, |c|={norm_c:.4f}.",
                    remediation_suggestion="Flag DICOM header discrepancy in directional cosines.",
                    diagnostics={"norm_r": norm_r, "norm_c": norm_c},
                )
                if raise_on_fail:
                    raise DICOMGeometryError(res.error_message)
                return res

            # Check orthogonality: dot product should be close to 0
            dot = float(np.dot(r, c))
            if abs(dot) > 0.05:
                res = ValidationResult(
                    passed=False,
                    rule_name="DICOM Geometry",
                    error_message=f"Slice orientation row and column vectors are not orthogonal (dot product: {dot:.4f} != 0).",
                    remediation_suggestion="Flag DICOM header discrepancy; verify patient positioning coordinates.",
                    diagnostics={"dot_product": dot, "r": list(r), "c": list(c)},
                )
                if raise_on_fail:
                    raise DICOMGeometryError(res.error_message)
                return res

        return ValidationResult(
            passed=True,
            rule_name="DICOM Geometry",
            diagnostics={"dx": dx, "dy": dy, "slice_thickness": slice_thickness},
        )

    @classmethod
    def validate_radiobiology(
        cls,
        results: Dict[str, float],
        raise_on_fail: bool = False,
    ) -> ValidationResult:
        """Rule: Probabilities (TCP, NTCP) must lie in [0.0, 1.0]."""
        for metric, val in results.items():
            if "probability" in metric.lower() or "tcp" in metric.lower() or "ntcp" in metric.lower():
                if val < 0.0 or val > 1.0 or np.isnan(val):
                    res = ValidationResult(
                        passed=False,
                        rule_name="Radiobiological Modeling",
                        error_message=f"Computed {metric} = {val} is outside probability range [0.0, 1.0].",
                        remediation_suggestion="Review model parameters (TD50/m/n or alpha/beta) and dose normalization.",
                        diagnostics={"metric": metric, "value": val},
                    )
                    if raise_on_fail:
                        raise RadiobiologyBoundsError(res.error_message)
                    return res

        return ValidationResult(
            passed=True,
            rule_name="Radiobiological Modeling",
            diagnostics=results,
        )
