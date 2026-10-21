"""DICOM-RT and Dose Volume Histogram (DVH) Analyzer Tool for OpenRad Agent."""

import os
from typing import Any, Dict, List, Optional
import numpy as np
import pydicom
from matplotlib.path import Path
from pydantic import BaseModel, Field

from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    DoseIntegrityError,
    DICOMGeometryError,
)


from openrad.validation.nomenclature import build_roi_index, tg263_dvh_metrics


class DVHAnalysisInput(BaseModel):
    dicom_rtstruct_path: str = Field(description="Path to the DICOM RTSTRUCT file containing contour data.")
    dicom_rtdose_path: str = Field(description="Path to the DICOM RTDOSE file containing 3D dose grid.")
    roi_names: List[str] = Field(description="Exact source or TG-263 primary names to analyze.")
    reviewed_name_map: Optional[Dict[str, str]] = Field(default=None, description="Human-reviewed source ROI name to TG-263 primary/target name mapping. Never infer anatomy from names.")


def analyze_dvh(
    dicom_rtstruct_path: str,
    dicom_rtdose_path: str,
    roi_names: List[str],
    reviewed_name_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Parses DICOM-RT files and computes Dose Volume Histograms (DVH).

    Returns D95, D50, D2, V50, and mean dose metrics for specified Regions of Interest (ROIs).
    Performs physics validation checks on DICOM geometry and dose non-negativity.
    """
    if not os.path.exists(dicom_rtstruct_path):
        raise FileNotFoundError(f"DICOM RTSTRUCT file not found: {dicom_rtstruct_path}")
    if not os.path.exists(dicom_rtdose_path):
        raise FileNotFoundError(f"DICOM RTDOSE file not found: {dicom_rtdose_path}")

    # Read DICOM files
    ds_struct = pydicom.dcmread(dicom_rtstruct_path)
    ds_dose = pydicom.dcmread(dicom_rtdose_path)

    from openrad.tools.dose_geometry import validate_axial_dose
    validate_axial_dose(ds_dose)
    frames = {str(roi.ReferencedFrameOfReferenceUID) for roi in ds_struct.StructureSetROISequence}
    if not getattr(ds_dose, "FrameOfReferenceUID", None) or frames != {str(ds_dose.FrameOfReferenceUID)}:
        raise DICOMGeometryError("RTSTRUCT and RTDOSE frame of reference must match explicitly.")
    if not getattr(ds_struct, "PatientID", None) or ds_struct.PatientID != getattr(ds_dose, "PatientID", None):
        raise DICOMGeometryError("RTSTRUCT and RTDOSE patient identifiers must match.")
    # 1. Physics Validation: Geometry Check
    pixel_spacing = [float(v) for v in getattr(ds_dose, "PixelSpacing", [1.0, 1.0])]
    slice_thickness = getattr(ds_dose, "SliceThickness", None)
    slice_thickness_val = float(slice_thickness) if slice_thickness is not None else None
    iop = getattr(ds_dose, "ImageOrientationPatient", None)
    iop_val = [float(v) for v in iop] if iop is not None else None

    PhysicsValidationEngine.validate_dicom_geometry(
        pixel_spacing=pixel_spacing,
        slice_thickness=slice_thickness_val,
        image_orientation=iop_val,
        raise_on_fail=True,
    )

    # 2. Physics Validation: Dose Grid Integrity
    scaling = float(getattr(ds_dose, "DoseGridScaling", 1.0))
    raw_array = ds_dose.pixel_array.astype(float)
    dose_grid = raw_array * scaling  # Shape: (Z, Y, X) in Gy

    PhysicsValidationEngine.validate_dose_grid(dose_grid, raise_on_fail=True)

    # Extract spatial coordinates of dose grid
    ipp = getattr(ds_dose, "ImagePositionPatient", [0.0, 0.0, 0.0])
    x0, y0, z0 = [float(v) for v in ipp]
    dy, dx = pixel_spacing[0], pixel_spacing[1]

    # Z coordinates: check GridFrameOffsetVector or slice thickness
    grid_offsets = getattr(ds_dose, "GridFrameOffsetVector", None)
    if grid_offsets is not None and len(grid_offsets) == dose_grid.shape[0]:
        z_coords = z0 + np.array([float(v) for v in grid_offsets])
        # estimate dz
        dz = float(np.mean(np.diff(z_coords))) if len(z_coords) > 1 else 1.0
    else:
        dz = slice_thickness_val if slice_thickness_val is not None else 3.0
        z_coords = z0 + np.arange(dose_grid.shape[0]) * dz

    voxel_volume_cc = (dx * dy * abs(dz)) / 1000.0  # mm3 to cm3 (cc)

    roi_index, naming_entries = build_roi_index(ds_struct.StructureSetROISequence, reviewed_name_map)
    roi_lookup = {e['roi_number']: e['original_name'] for e in naming_entries}

    # Map ROI contours by ROI Number
    roi_contours: Dict[int, Any] = {}
    if hasattr(ds_struct, "ROIContourSequence"):
        for contour in ds_struct.ROIContourSequence:
            roi_contours[int(contour.ReferencedROINumber)] = contour

    results: Dict[str, Any] = {
        "status": "research_only",
        "clinical_release": False,
        "limitations": ["Voxel-center contour sampling; no commissioned contour topology or partial-volume model. No clinical uncertainty bound established."],
        "dose_grid_shape": list(dose_grid.shape),
        "max_dose_Gy": float(np.max(dose_grid)),
        "voxel_volume_cc": float(voxel_volume_cc),
        "nomenclature": {"standard": "AAPM TG-263 (2018)", "vocabulary_version": "20170815", "structures": naming_entries},
        "structures": {},
    }

    # Analyze each requested ROI
    for target_name in roi_names:
        if not isinstance(target_name, str) or not target_name:
            raise ValueError("Requested ROI names must be nonempty strings.")
        entry = roi_index.get(target_name.casefold())
        matched_num = entry['roi_number'] if entry else None
        if entry is None or entry['canonical_name'] is None or matched_num not in roi_contours:
            results["structures"][target_name] = {
                "found": False,
                "error": "ROI absent, has no contours, or requires an explicit reviewed TG-263 mapping.",
                "nomenclature": entry,
                "available_structures": list(roi_lookup.values()),
            }
            continue

        actual_name = roi_lookup[matched_num]
        contour_item = roi_contours[matched_num]

        # Extract doses inside ROI contours
        roi_voxel_doses: List[float] = []

        if hasattr(contour_item, "ContourSequence"):
            for c_seq in contour_item.ContourSequence:
                pts = np.array(c_seq.ContourData, dtype=float).reshape(-1, 3)
                if pts.shape[0] < 3:
                    continue

                c_z = pts[0, 2]
                z_idx = int(np.argmin(np.abs(z_coords - c_z)))
                # Only process if contour slice is reasonably close to dose grid slice
                if abs(z_coords[z_idx] - c_z) > max(abs(dz) * 1.5, 3.0):
                    continue

                min_x, max_x = float(pts[:, 0].min()), float(pts[:, 0].max())
                min_y, max_y = float(pts[:, 1].min()), float(pts[:, 1].max())

                j_min = max(0, int(np.floor((min_x - x0) / dx)))
                j_max = min(dose_grid.shape[2] - 1, int(np.ceil((max_x - x0) / dx)))
                i_min = max(0, int(np.floor((min_y - y0) / dy)))
                i_max = min(dose_grid.shape[1] - 1, int(np.ceil((max_y - y0) / dy)))

                if j_min > j_max or i_min > i_max:
                    continue

                grid_x = x0 + np.arange(j_min, j_max + 1) * dx
                grid_y = y0 + np.arange(i_min, i_max + 1) * dy
                gx, gy = np.meshgrid(grid_x, grid_y)
                grid_pts = np.vstack([gx.ravel(), gy.ravel()]).T

                path = Path(pts[:, :2])
                mask = path.contains_points(grid_pts)
                if mask.any():
                    sub_grid = dose_grid[z_idx, i_min : i_max + 1, j_min : j_max + 1].ravel()
                    roi_voxel_doses.extend(sub_grid[mask].tolist())

        doses = np.array(roi_voxel_doses, dtype=float)
        if len(doses) == 0:
            results["structures"][target_name] = {
                "found": True,
                "structure_name": actual_name,
                "voxel_count": 0,
                "volume_cc": 0.0,
                "warning": "No dose voxels intercepted within contour volume.",
            }
            continue

        # Compute standard DVH metrics: D95, D50, D2, V50, mean, min, max
        total_vol_cc = float(len(doses) * voxel_volume_cc)
        d_mean = float(np.mean(doses))
        d_min = float(np.min(doses))
        d_max = float(np.max(doses))

        # D_x is the minimum dose received by at least x% of the volume
        # In ascending order, D95 corresponds to (100 - 95)% = 5th percentile
        d95 = float(np.percentile(doses, 5.0))
        d50 = float(np.percentile(doses, 50.0))
        d2 = float(np.percentile(doses, 98.0))

        # V50: volume receiving at least 50 Gy
        v50_count = int(np.sum(doses >= 50.0))
        v50_percent = float(100.0 * v50_count / len(doses))
        v50_cc = float(v50_count * voxel_volume_cc)

        # Generate cumulative DVH curve bins (100 points)
        dose_bins = np.linspace(0.0, max(d_max * 1.05, 1.0), 101)
        # Cumulative volume fraction >= dose
        vol_fractions = [float(100.0 * np.sum(doses >= b) / len(doses)) for b in dose_bins]

        results["structures"][target_name] = {
            "found": True,
            "structure_name": actual_name,
            "roi_number": matched_num,
            "canonical_structure_name": entry['canonical_name'],
            "nomenclature": entry,
            "tg263_metrics": tg263_dvh_metrics(d95, d50, d2, v50_percent, v50_cc),
            "voxel_count": len(doses),
            "volume_cc": round(total_vol_cc, 3),
            "mean_dose_Gy": round(d_mean, 2),
            "min_dose_Gy": round(d_min, 2),
            "max_dose_Gy": round(d_max, 2),
            "D95_Gy": round(d95, 2),
            "D50_Gy": round(d50, 2),
            "D2_Gy": round(d2, 2),
            "V50_percent": round(v50_percent, 2),
            "V50_cc": round(v50_cc, 3),
            "dvh_curve": {
                "dose_bins_Gy": [round(float(b), 2) for b in dose_bins.tolist()],
                "volume_percent": [round(float(v), 2) for v in vol_fractions],
            },
        }

    return results
