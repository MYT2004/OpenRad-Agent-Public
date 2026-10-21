"""Fail closed on geometry outside the current axial algorithms' supported scope."""
import numpy as np
from openrad.validation.physics_rules import PhysicsValidationEngine, DICOMGeometryError


def validate_axial_dose(ds):
    required = ("DoseGridScaling", "DoseUnits", "DoseType", "PixelSpacing", "ImagePositionPatient", "ImageOrientationPatient", "GridFrameOffsetVector")
    if any(not hasattr(ds, key) for key in required):
        raise DICOMGeometryError("RTDOSE requires explicit dose units, scaling and spatial geometry.")
    if ds.Modality != "RTDOSE" or ds.DoseUnits != "GY" or ds.DoseType != "PHYSICAL":
        raise DICOMGeometryError("Only physical RTDOSE in Gy is supported.")
    if str(getattr(ds, 'SpatialTransformOfDose', 'NONE')) != 'NONE':
        raise DICOMGeometryError('Spatially transformed dose requires a separately verified registration workflow.')
    scaling = float(ds.DoseGridScaling)
    if not np.isfinite(scaling) or scaling <= 0:
        raise DICOMGeometryError("DoseGridScaling must be finite and positive.")
    PhysicsValidationEngine.validate_dicom_geometry(ds.PixelSpacing, image_orientation=ds.ImageOrientationPatient, raise_on_fail=True)
    if not np.allclose(ds.ImageOrientationPatient, [1, 0, 0, 0, 1, 0], atol=1e-6, rtol=0):
        raise DICOMGeometryError("Oblique or reversed orientation is not supported by the axial algorithm.")
    position = np.asarray(ds.ImagePositionPatient, dtype=float)
    offsets = np.asarray(ds.GridFrameOffsetVector, dtype=float)
    if position.shape != (3,) or not np.isfinite(position).all():
        raise DICOMGeometryError("ImagePositionPatient must contain three finite coordinates.")
    if offsets.ndim != 1 or len(offsets) < 2 or len(offsets) != int(ds.NumberOfFrames) or not np.isfinite(offsets).all() or offsets[0] != 0 or (np.diff(offsets) <= 0).any():
        raise DICOMGeometryError("Only increasing relative frame offsets beginning at zero are supported.")
    if not np.allclose(np.diff(offsets), np.diff(offsets)[0], atol=1e-6, rtol=0):
        raise DICOMGeometryError("Nonuniform frame spacing is not supported.")
