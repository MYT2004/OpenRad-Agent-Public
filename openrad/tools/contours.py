"""Restricted axial contour sampling with explicit plane thickness and coverage checks."""
import numpy as np
from matplotlib.path import Path
from shapely.geometry import Polygon
from openrad.validation.physics_rules import DICOMGeometryError, PhysicsValidationEngine


def sample_contour_doses(contour_item, dose_grid, z_coords, x0, y0, dx, dy):
    if hasattr(contour_item, 'SourcePixelPlanesCharacteristicsSequence'):
        raise DICOMGeometryError('Source pixel-plane sampling is outside the validated contour-spacing inference scope.')
    planes, types = {}, set()
    for contour in getattr(contour_item, 'ContourSequence', []):
        kind = str(getattr(contour, 'ContourGeometricType', ''))
        if kind not in ('CLOSED_PLANAR', 'CLOSEDPLANAR_XOR'):
            raise DICOMGeometryError('Only closed planar volume contours can be sampled; points/open contours have no DVH volume.')
        if hasattr(contour, 'ContourSlabThickness') or hasattr(contour, 'ContourOffsetVector'):
            raise DICOMGeometryError('Explicit contour slab/offset geometry requires a separately validated sampler.')
        data = np.asarray(contour.ContourData, dtype=float)
        count = int(getattr(contour, 'NumberOfContourPoints', 0))
        if data.ndim != 1 or count < 3 or data.size != 3 * count:
            raise DICOMGeometryError('Declared contour point count must match the coordinate triplets.')
        pts = data.reshape(-1, 3)
        if len(pts) < 3 or not np.isfinite(pts).all() or np.ptp(pts[:, 2]) > .01:
            raise DICOMGeometryError('Malformed, nonfinite or non-axial contour.')
        poly = Polygon(pts[:, :2])
        if not poly.is_valid or poly.area <= 0:
            raise DICOMGeometryError('Self-intersecting/keyhole or degenerate contour needs a validated topology handler.')
        z = round(float(pts[0, 2]), 3)
        planes.setdefault(z, []).append(pts[:, :2])
        types.add(kind)
    if len(types) != 1 or len(planes) < 2:
        raise DICOMGeometryError('Consistent contour type and at least two planes are required to establish slab thickness.')
    levels = np.array(sorted(planes))
    gaps = np.diff(levels)
    thickness = float(np.median(gaps))
    if not np.allclose(gaps, thickness, atol=.01, rtol=0):
        raise DICOMGeometryError('Irregular/missing contour planes; volume interpolation has not been validated.')
    # Each contour plane represents one slab of inferred uniform contour spacing.
    # This is distinct from the RTDOSE grid spacing.
    all_doses = []
    for z, polygons in sorted(planes.items()):
        pts = np.concatenate(polygons)
        if (z < z_coords[0] or z > z_coords[-1] or pts[:, 0].min() < x0 or pts[:, 0].max() > x0+(dose_grid.shape[2]-1)*dx or pts[:, 1].min() < y0 or pts[:, 1].max() > y0+(dose_grid.shape[1]-1)*dy):
            raise DICOMGeometryError('Contour extends outside dose-grid coverage; incomplete-volume metrics are blocked.')
        j0=max(0,int(np.floor((pts[:,0].min()-x0)/dx)));j1=min(dose_grid.shape[2]-1,int(np.ceil((pts[:,0].max()-x0)/dx)))
        i0=max(0,int(np.floor((pts[:,1].min()-y0)/dy)));i1=min(dose_grid.shape[1]-1,int(np.ceil((pts[:,1].max()-y0)/dy)))
        xx,yy=np.meshgrid(x0+np.arange(j0,j1+1)*dx,y0+np.arange(i0,i1+1)*dy)
        xy=np.column_stack((xx.ravel(),yy.ravel()))
        mask=np.zeros(len(xy),dtype=bool)
        for poly in polygons:
            inside=Path(poly).contains_points(xy)
            if 'CLOSEDPLANAR_XOR' in types:
                mask ^= inside
            else:
                mask |= inside
        hi=min(int(np.searchsorted(z_coords,z)),len(z_coords)-1)
        lo=max(0,hi-1)
        weight=0. if hi==lo else float((z-z_coords[lo])/(z_coords[hi]-z_coords[lo]))
        slab=(1-weight)*dose_grid[lo,i0:i1+1,j0:j1+1]+weight*dose_grid[hi,i0:i1+1,j0:j1+1]
        all_doses.extend(slab.ravel()[mask])
    values=np.asarray(all_doses,dtype=float)
    PhysicsValidationEngine.validate_dose_grid(values,raise_on_fail=True)
    return values, dx*dy*thickness/1000., thickness
