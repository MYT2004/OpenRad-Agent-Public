"""Gamma Index Evaluation Tool for OpenRad Agent.

Computes 2D/3D Gamma Index (Low et al., AAPM TG-218 standard) comparing reference
and evaluated dose distributions with physics validation guardrails.
"""

import os
from typing import Any, Dict, Optional, Tuple, Union
import numpy as np
import pydicom
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    DoseIntegrityError,
    GammaEvaluationError,
)


class GammaEvaluationInput(BaseModel):
    reference_dose_path: str = Field(description="Path to baseline DICOM/3D dose array (e.g., TPS calculated dose).")
    evaluated_dose_path: str = Field(description="Path to measured or Monte Carlo simulated 3D dose array.")
    dose_tolerance_percent: float = Field(default=3.0, description="Dose difference tolerance in percent (e.g., 3.0 for 3%).")
    distance_tolerance_mm: float = Field(default=2.0, description="Distance-to-agreement tolerance in mm (e.g., 3.0 mm).")
    dose_threshold_percent: float = Field(default=10.0, description="Low-dose cutoff threshold percentage.")


def _load_dose_and_coords(
    path_or_array: Union[str, np.ndarray],
) -> Tuple[np.ndarray, Tuple[np.ndarray, ...]]:
    """Loads dose distribution and spatial coordinates (in mm) from DICOM RTDOSE, NPY, or array."""
    if isinstance(path_or_array, np.ndarray):
        arr = path_or_array.astype(float)
        coords = tuple(np.arange(s, dtype=float) for s in arr.shape)
        return arr, coords

    if not isinstance(path_or_array, str) or not os.path.exists(path_or_array):
        raise FileNotFoundError(f"Dose file not found at path: {path_or_array}")

    lower_path = path_or_array.lower()
    if lower_path.endswith(".dcm") or lower_path.endswith(".dicom"):
        ds = pydicom.dcmread(path_or_array)
        from openrad.tools.dose_geometry import validate_axial_dose
        validate_axial_dose(ds)
        scaling = float(ds.DoseGridScaling)
        dose = ds.pixel_array.astype(float) * scaling

        spacing = [float(v) for v in getattr(ds, "PixelSpacing", [1.0, 1.0])]
        dy, dx = spacing[0], spacing[1]
        ipp = [float(v) for v in getattr(ds, "ImagePositionPatient", [0.0, 0.0, 0.0])]
        x0, y0, z0 = ipp[0], ipp[1], ipp[2]

        offsets = getattr(ds, "GridFrameOffsetVector", None)
        if offsets is not None and len(offsets) == dose.shape[0]:
            z_coords = z0 + np.array([float(v) for v in offsets])
        else:
            dz = float(getattr(ds, "SliceThickness", 3.0))
            z_coords = z0 + np.arange(dose.shape[0]) * dz

        y_coords = y0 + np.arange(dose.shape[1]) * dy
        x_coords = x0 + np.arange(dose.shape[2]) * dx
        return dose, (z_coords, y_coords, x_coords)

    elif lower_path.endswith(".npy"):
        loaded = np.load(path_or_array, allow_pickle=False)
        if isinstance(loaded, np.ndarray):
            arr = loaded.astype(float)
            coords = tuple(np.arange(s, dtype=float) for s in arr.shape)
            return arr, coords
        elif isinstance(loaded, dict) or hasattr(loaded, "item"):
            data = loaded.item() if hasattr(loaded, "item") else loaded
            dose = np.asarray(data["dose"], dtype=float)
            coords = tuple(np.asarray(c, dtype=float) for c in data.get("coords", ()))
            return dose, coords
        else:
            arr = np.asarray(loaded, dtype=float)
            coords = tuple(np.arange(s, dtype=float) for s in arr.shape)
            return arr, coords
    else:
        # Default text/csv or general loader fallback
        try:
            arr = np.loadtxt(path_or_array, delimiter=",").astype(float)
            coords = tuple(np.arange(s, dtype=float) for s in arr.shape)
            return arr, coords
        except Exception as e:
            raise ValueError(f"Unsupported dose format for file '{path_or_array}': {e}")


def evaluate_gamma_index(
    reference_dose_path: str,
    evaluated_dose_path: str,
    dose_tolerance_percent: float = 3.0,
    distance_tolerance_mm: float = 2.0,
    dose_threshold_percent: float = 10.0,
) -> Dict[str, float]:
    """Computes 2D/3D Gamma Index passing rates between reference and evaluated dose distributions.

    Returns passing rate percentage, average gamma, and max gamma.
    Validates physics domain guardrails on dose positivity and gamma limits.
    """
    if not np.isfinite([dose_tolerance_percent, distance_tolerance_mm, dose_threshold_percent]).all() or dose_tolerance_percent <= 0 or distance_tolerance_mm <= 0 or not 0 <= dose_threshold_percent <= 100:
        raise GammaEvaluationError("Gamma tolerances must be finite and positive; cutoff must be in [0,100].")
    ref_dose, ref_coords = _load_dose_and_coords(reference_dose_path)
    eval_dose, eval_coords = _load_dose_and_coords(evaluated_dose_path)

    if ref_dose.ndim not in (2, 3) or eval_dose.ndim != ref_dose.ndim:
        raise GammaEvaluationError("Dose arrays must have matching dimensionality (2D or 3D).")
    # 1. Physics Validation: Non-negative dose
    PhysicsValidationEngine.validate_dose_grid(ref_dose, raise_on_fail=True)
    PhysicsValidationEngine.validate_dose_grid(eval_dose, raise_on_fail=True)

    # Low-dose cutoff and normalization threshold
    max_ref_dose = float(np.max(ref_dose))
    if max_ref_dose <= 0:
        raise DoseIntegrityError(f"Maximum reference dose is {max_ref_dose} Gy (must be > 0).")

    dose_cutoff_val = (dose_threshold_percent / 100.0) * max_ref_dose
    delta_dose = (dose_tolerance_percent / 100.0) * max_ref_dose
    delta_dist = float(distance_tolerance_mm)

    # Construct spatial meshgrid points
    ref_grids = np.meshgrid(*ref_coords, indexing="ij")
    ref_pts = np.vstack([g.ravel() for g in ref_grids]).T
    ref_d = ref_dose.ravel()

    eval_grids = np.meshgrid(*eval_coords, indexing="ij")
    eval_pts = np.vstack([g.ravel() for g in eval_grids]).T
    eval_d = eval_dose.ravel()

    # Filter by low-dose cutoff
    mask_eval = ref_d >= dose_cutoff_val
    eval_count = int(np.sum(mask_eval))

    if eval_count == 0:
        raise GammaEvaluationError("No voxels above cutoff; no QA verdict can be computed.")

    sub_ref_pts = ref_pts[mask_eval]
    sub_ref_d = ref_d[mask_eval]

    # Exact nearest-neighbor search in normalized joint space/dose coordinates.
    # This is discrete gamma: interpolation and commissioning remain required.
    candidates = np.column_stack((eval_pts / delta_dist, eval_d / delta_dose))
    queries = np.column_stack((sub_ref_pts / delta_dist, sub_ref_d / delta_dose))
    gamma_values, _ = cKDTree(candidates).query(queries)

    passed_points = int(np.sum(gamma_values <= 1.0))
    pass_rate = float(100.0 * passed_points / eval_count)
    avg_gamma = float(np.mean(gamma_values))
    max_gamma = float(np.max(gamma_values))

    # 2. Physics Validation: Gamma Index Output
    PhysicsValidationEngine.validate_gamma_index(
        pass_rate=pass_rate,
        average_gamma=avg_gamma,
        max_gamma=max_gamma,
        raise_on_fail=True,
    )

    return {
        "clinical_release": False,
        "method": "discrete_global_gamma",
        "criteria": {"dose_percent": dose_tolerance_percent, "distance_mm": distance_tolerance_mm, "cutoff_percent": dose_threshold_percent},
        "limitations": ["No interpolation or measurement uncertainty model; not commissioned for clinical QA.", "Array/NPY/CSV inputs assume 1 mm spacing and Gy; DICOM supports canonical axial geometry only."],
        "passing_rate": pass_rate,
        "average_gamma": round(avg_gamma, 3),
        "max_gamma": round(max_gamma, 3),
        "evaluated_voxels": eval_count,
        "total_voxels": int(ref_d.size),
    }
