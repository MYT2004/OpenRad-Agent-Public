"""DICOM-RT and Dose Volume Histogram (DVH) Analyzer Tool for OpenRad Agent."""

import os
from typing import Any, Dict, List, Optional
import numpy as np
import pydicom
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
    dicom_rtplan_path: Optional[str] = None
    reviewed_name_map: Optional[Dict[str, str]] = Field(default=None, description="Human-reviewed source ROI name to TG-263 primary/target name mapping. Never infer anatomy from names.")


def cumulative_dvh_curve(doses):
    """Empirical cumulative curve at 0.01 Gy resolution, bounded to 10,001 bins.

    Sorting/search avoids a full voxel scan at every threshold. Above the bin
    budget, the explicitly returned step increases in whole centigray units.
    Clinical D metrics are calculated independently from the sampled doses.
    """
    values=np.sort(np.asarray(doses,dtype=float))
    PhysicsValidationEngine.validate_dose_grid(values,raise_on_fail=True)
    upper=max(float(values[-1])*1.05,1.)
    step=max(.01,float(np.ceil(upper/10000*100)/100))
    bins=np.round(np.arange(min(10000,int(np.ceil(upper/step)))+1)*step,2)
    volumes=100*(len(values)-np.searchsorted(values,bins,side='left'))/len(values)
    return {'dose_bins_Gy':np.round(bins,2).tolist(),'volume_percent':np.round(volumes,2).tolist(),
            'bin_width_Gy':step,'method':'Empirical volume receiving at least each threshold; sorted samples, no dose smoothing.'}


def analyze_dvh(
    dicom_rtstruct_path: str,
    dicom_rtdose_path: str,
    roi_names: List[str],
    reviewed_name_map: Optional[Dict[str, str]] = None,
    dicom_rtplan_path: Optional[str] = None,
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

    ds_plan = pydicom.dcmread(dicom_rtplan_path, stop_before_pixels=True) if dicom_rtplan_path else None
    return analyze_dvh_datasets(ds_struct, ds_dose, roi_names, reviewed_name_map, ds_plan)


def analyze_dvh_datasets(ds_struct, ds_dose, roi_names, reviewed_name_map=None, ds_plan=None, require_plan_linkage=True, parsed_dose=None):
    """Analyze validated in-memory datasets, including scrubbed analysis copies."""
    from openrad.tools.dicom_integrity import validate_analysis_identity, validate_roi_associations
    from src.resources import check_dose_shape
    validate_analysis_identity(ds_dose, ds_struct, ds_plan)
    validate_roi_associations(ds_struct)
    check_dose_shape((int(ds_dose.NumberOfFrames), int(ds_dose.Rows), int(ds_dose.Columns)))
    linkage_verified = False
    if getattr(ds_dose, 'ReferencedRTPlanSequence', None) and ds_plan is None and require_plan_linkage:
        raise DICOMGeometryError("Referenced RTPLAN is required to verify dose/structure course linkage.")
    if getattr(ds_dose, 'ReferencedRTPlanSequence', None) and ds_plan is not None:
        plan = ds_plan
        dose_refs = {str(r.ReferencedSOPInstanceUID) for r in ds_dose.ReferencedRTPlanSequence}
        struct_refs = {str(r.ReferencedSOPInstanceUID) for r in getattr(plan, 'ReferencedStructureSetSequence', [])}
        if plan.Modality != 'RTPLAN' or dose_refs != {str(plan.SOPInstanceUID)} or struct_refs != {str(ds_struct.SOPInstanceUID)} or plan.PatientID != ds_dose.PatientID:
            raise DICOMGeometryError("Dose, plan and structure references/patient identifiers do not match.")
        linkage_verified = True
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
    if raw_array.ndim != 3 or raw_array.shape[0] != len(ds_dose.GridFrameOffsetVector):
        raise DICOMGeometryError("Dose pixel shape does not match frame geometry.")
    dose_grid = raw_array * scaling if parsed_dose is None else np.asarray(parsed_dose, dtype=float)
    if dose_grid.shape != raw_array.shape or not np.allclose(dose_grid, raw_array * scaling, rtol=0, atol=1e-10):
        raise DICOMGeometryError("Parsed dose grid disagrees with source scaling/shape.")

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
        "course_linkage_verified": linkage_verified,
        "clinical_release": False,
        "limitations": ["Axial voxel-center sampling with contour-plane slab thickness and linear z dose interpolation. Unsupported/self-intersecting polygon encodings, irregular planes and partial dose coverage are blocked. Topology interpretation requires independent verification. No clinical uncertainty bound established."],
        "dose_summation_type": str(getattr(ds_dose, 'DoseSummationType', 'UNKNOWN')),
        "dose_grid_shape": list(dose_grid.shape),
        "max_dose_Gy": float(np.max(dose_grid)),
        "voxel_volume_cc": float(voxel_volume_cc),
        "nomenclature": {"standard": "AAPM TG-263 (2018)", "vocabulary_version": "20170815", "structures": naming_entries},
        "structures": {},
    }

    results['limitations'].append(
        'Dose summation scope is ' + results['dose_summation_type'] +
        '; reference linkage alone does not establish full treatment-course dose, prescription or fractionation. '
        'No automatic summation or rescaling is performed.')

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

        from openrad.tools.contours import sample_contour_doses
        try:
            doses, roi_voxel_volume_cc, contour_thickness = sample_contour_doses(
                contour_item, dose_grid, z_coords, x0, y0, dx, dy)
        except (ValueError, AttributeError) as exc:
            results["structures"][target_name] = {
                "found": False, "structure_name": actual_name,
                "nomenclature": entry, "error": str(exc)}
            continue

        # Compute standard DVH metrics: D95, D50, D2, V50, mean, min, max
        total_vol_cc = float(len(doses) * roi_voxel_volume_cc)
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
        v50_cc = float(v50_count * roi_voxel_volume_cc)

        results["structures"][target_name] = {
            "found": True,
            "structure_name": actual_name,
            "roi_number": matched_num,
            "canonical_structure_name": entry['canonical_name'],
            "nomenclature": entry,
            "tg263_metrics": tg263_dvh_metrics(d95, d50, d2, v50_percent, v50_cc),
            "voxel_count": len(doses),
            "contour_plane_thickness_mm": contour_thickness,
            "sampling_volume_cc": roi_voxel_volume_cc,
            "volume_cc": round(total_vol_cc, 3),
            "mean_dose_Gy": round(d_mean, 2),
            "min_dose_Gy": round(d_min, 2),
            "max_dose_Gy": round(d_max, 2),
            "D95_Gy": round(d95, 2),
            "D50_Gy": round(d50, 2),
            "D2_Gy": round(d2, 2),
            "V50_percent": round(v50_percent, 2),
            "V50_cc": round(v50_cc, 3),
            "dvh_curve": cumulative_dvh_curve(doses),
        }

    return results
