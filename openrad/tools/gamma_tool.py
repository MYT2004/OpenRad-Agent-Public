"""Gamma Index Evaluation Tool for OpenRad Agent.

Computes 2D/3D Gamma Index (Low et al., AAPM TG-218 standard) comparing reference
and evaluated dose distributions with physics validation guardrails.
"""

from src.operations import audited_operation

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pydicom
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    PhysicsValidationError,
    DoseIntegrityError,
    GammaEvaluationError,
)


class GammaEvaluationInput(BaseModel):
    reference_dose_path: str = Field(description="Path to baseline DICOM/3D dose array (e.g., TPS calculated dose).")
    evaluated_dose_path: str = Field(description="Path to measured or Monte Carlo simulated 3D dose array.")
    dose_tolerance_percent: float = Field(default=3.0, description="Dose difference tolerance in percent (e.g., 3.0 for 3%).")
    distance_tolerance_mm: float = Field(default=2.0, description="Distance-to-agreement tolerance in mm (e.g., 3.0 mm).")
    reference_spacing_mm: Optional[List[float]] = None
    evaluated_spacing_mm: Optional[List[float]] = None
    dose_threshold_percent: float = Field(default=10.0, description="Low-dose cutoff threshold percentage.")


def _array_coords(arr, spacing):
    if spacing is None or len(spacing)!=arr.ndim or not np.isfinite(spacing).all() or any(v<=0 for v in spacing):
        raise GammaEvaluationError('Non-DICOM dose requires explicit positive spacing_mm per array axis; units must be Gy.')
    return tuple(np.arange(size,dtype=float)*step for size,step in zip(arr.shape,spacing))


def _grid_points(coords, mask=None):
    """Build C-order physical points without retaining dense meshgrid copies."""
    if mask is not None:
        indices = np.nonzero(mask)
        points = np.empty((len(indices[0]), len(coords)), dtype=float)
        for axis, (values, index) in enumerate(zip(coords, indices)):
            points[:, axis] = values[index]
        return points
    shape = tuple(len(values) for values in coords)
    points = np.empty((*shape, len(coords)), dtype=float)
    for axis, values in enumerate(coords):
        broadcast_shape = [1] * len(coords)
        broadcast_shape[axis] = len(values)
        points[..., axis] = np.asarray(values).reshape(broadcast_shape)
    return points.reshape(-1, len(coords))


def _load_dose_and_coords(
    path_or_array: Union[str, np.ndarray],
    spacing_mm: Optional[List[float]] = None,
) -> Tuple[np.ndarray, Tuple[np.ndarray, ...]]:
    """Loads dose distribution and spatial coordinates (in mm) from DICOM RTDOSE, NPY, or array."""
    from src.resources import (check_dose_shape, check_input_file, preflight_npy,
                               preflight_dicom_dose, InputBudgetError)
    malformed = "Unsupported or malformed dose data: file could not be parsed as a numerical dose grid."
    if isinstance(path_or_array, np.ndarray):
        check_dose_shape(path_or_array.shape)
        if path_or_array.dtype.kind not in 'ufi':
            raise GammaEvaluationError(malformed)
        arr = path_or_array.astype(float)
        return arr, _array_coords(arr, spacing_mm)
    if not isinstance(path_or_array, (str, Path)) or not Path(path_or_array).is_file():
        raise FileNotFoundError("Dose input is unavailable.")
    path = Path(path_or_array)
    try:
        check_input_file(path)
        if path.suffix.lower() in ('.dcm', '.dicom'):
            preflight_dicom_dose(path)
            ds = pydicom.dcmread(path)
            from openrad.tools.dose_geometry import validate_axial_dose
            from openrad.tools.dicom_integrity import validate_rt_object
            from pydicom.uid import RTDoseStorage
            validate_rt_object(ds,'RTDOSE',RTDoseStorage)
            validate_axial_dose(ds)
            dose = ds.pixel_array.astype(float) * float(ds.DoseGridScaling)
            ipp = np.asarray(ds.ImagePositionPatient, dtype=float)
            dy, dx = map(float, ds.PixelSpacing)
            coords = (ipp[2] + np.asarray(ds.GridFrameOffsetVector, dtype=float),
                      ipp[1] + np.arange(dose.shape[1])*dy,
                      ipp[0] + np.arange(dose.shape[2])*dx)
            return dose, coords
        if path.suffix.lower() == '.npy':
            preflight_npy(path)
            arr = np.load(path, allow_pickle=False, mmap_mode='r')
            # Recheck after load to catch a replaced header; never convert text to float.
            if not isinstance(arr, np.ndarray) or arr.dtype.kind not in 'ufi':
                raise GammaEvaluationError(malformed)
        else:
            if path.stat().st_size > 8 * 1024 * 1024:
                raise InputBudgetError('Text dose input exceeds the 8 MiB parsing budget.')
            arr = np.loadtxt(path, delimiter=',')
        check_dose_shape(arr.shape)
        arr = arr.astype(float)
    except (InputBudgetError, PhysicsValidationError):
        raise
    except Exception:
        raise GammaEvaluationError(malformed) from None
    return arr, _array_coords(arr, spacing_mm)


@audited_operation
def evaluate_gamma_index(
    reference_dose_path: str,
    evaluated_dose_path: str,
    dose_tolerance_percent: float = 3.0,
    distance_tolerance_mm: float = 2.0,
    dose_threshold_percent: float = 10.0,
    reference_spacing_mm: Optional[List[float]] = None,
    evaluated_spacing_mm: Optional[List[float]] = None,
) -> Dict[str, float]:
    """Computes 2D/3D Gamma Index passing rates between reference and evaluated dose distributions.

    Returns passing rate percentage, average gamma, and max gamma.
    Validates physics domain guardrails on dose positivity and gamma limits.
    """
    if not np.isfinite([dose_tolerance_percent, distance_tolerance_mm, dose_threshold_percent]).all() or dose_tolerance_percent <= 0 or distance_tolerance_mm <= 0 or not 0 <= dose_threshold_percent <= 100:
        raise GammaEvaluationError("Gamma tolerances must be finite and positive; cutoff must be in [0,100].")
    if isinstance(reference_dose_path, (str, Path)) and isinstance(evaluated_dose_path, (str, Path)):
        ref_str = str(reference_dose_path)
        eval_str = str(evaluated_dose_path)
        ref_real = os.path.realpath(os.path.expanduser(ref_str))
        eval_real = os.path.realpath(os.path.expanduser(eval_str))
        is_same = (ref_real == eval_real)
        if not is_same and os.path.exists(ref_real) and os.path.exists(eval_real):
            try:
                is_same = os.path.samefile(ref_real, eval_real)
            except (OSError, ValueError):
                pass
        if is_same:
            raise GammaEvaluationError("INDEPENDENT_REFERENCE_REQUIRED: Evaluation and reference dose distributions must be independent files; self-comparison cannot serve as QA verification.")
    if all(isinstance(p, (str, Path)) and Path(p).suffix.lower() in ('.dcm', '.dicom')
           for p in (reference_dose_path, evaluated_dose_path)):
        from src.resources import preflight_dicom_dose
        try:
            headers=[preflight_dicom_dose(p) for p in (reference_dose_path,evaluated_dose_path)]
        except Exception:
            raise GammaEvaluationError('DICOM dose inputs could not be validated.') from None
        for tag in ('PatientID','FrameOfReferenceUID'):
            if not getattr(headers[0],tag,None) or getattr(headers[0],tag,None)!=getattr(headers[1],tag,None):
                raise GammaEvaluationError('DICOM gamma inputs require matching explicit patient and frame identifiers.')
        if str(getattr(headers[0],'IssuerOfPatientID','')).strip()!=str(getattr(headers[1],'IssuerOfPatientID','')).strip():
            raise GammaEvaluationError('DICOM gamma patient ID issuers must match.')
        if str(getattr(headers[0],'DoseSummationType','UNKNOWN'))!=str(getattr(headers[1],'DoseSummationType','UNKNOWN')):
            raise GammaEvaluationError('DICOM gamma dose summation scopes must match; no implicit fraction/course conversion is supported.')
    ref_dose, ref_coords = _load_dose_and_coords(reference_dose_path, reference_spacing_mm)
    eval_dose, eval_coords = _load_dose_and_coords(evaluated_dose_path, evaluated_spacing_mm)

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
    delta_dose = max_ref_dose * dose_tolerance_percent / 100.0
    delta_dist = float(distance_tolerance_mm)

    ref_d = ref_dose.ravel()
    eval_d = eval_dose.ravel()

    # Filter by low-dose cutoff
    reference_mask = ref_dose >= dose_cutoff_val
    eval_count = int(np.count_nonzero(reference_mask))

    if eval_count == 0:
        raise GammaEvaluationError("No voxels above cutoff; no QA verdict can be computed.")

    # Only reference voxels above cutoff need physical query points. Evaluation
    # candidates retain every voxel, including those below the reference cutoff.
    sub_ref_pts = _grid_points(ref_coords, reference_mask)
    sub_ref_d = ref_dose[reference_mask]
    eval_pts = _grid_points(eval_coords)

    # Exact nearest-neighbor search in normalized joint space/dose coordinates.
    # This is discrete gamma: interpolation and commissioning remain required.
    candidates = np.column_stack((eval_pts / delta_dist, eval_d / delta_dose))
    queries = np.column_stack((sub_ref_pts / delta_dist, sub_ref_d / delta_dose))
    _, nearest = cKDTree(candidates).query(queries)
    # Compute the reported distance from direct physical differences. Subtracting
    # normalized absolute doses first can round a strict gamma>1 tie to exactly 1.
    spatial_delta = (sub_ref_pts - eval_pts[nearest]) / delta_dist
    dose_delta = (sub_ref_d - eval_d[nearest]) / delta_dose
    gamma_values = np.sqrt(np.sum(spatial_delta**2, axis=1) + dose_delta**2)

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
        "limitations": ["No interpolation or measurement uncertainty model; not commissioned for clinical QA.", "Array/NPY/CSV inputs require explicit mm spacing and assume Gy with zero origin; DICOM supports canonical axial geometry only."],
        "threshold_policy": "direct_difference_float64_le_1",
        "numerical_tolerance": 0.0,
        "average_gamma_unrounded": avg_gamma,
        "max_gamma_unrounded": max_gamma,
        "passing_rate": pass_rate,
        "average_gamma": round(avg_gamma, 3),
        "max_gamma": round(max_gamma, 3),
        "evaluated_voxels": eval_count,
        "total_voxels": int(ref_d.size),
    }
