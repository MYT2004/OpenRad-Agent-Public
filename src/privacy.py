"""Minimal, in-memory DICOM analysis copies, not a general de-identification exporter.

Only geometry, dose and contour attributes needed by this application survive.
No source DICOMs, original UIDs, arbitrary names or metadata are written to disk.
"""
from copy import deepcopy
from uuid import uuid4
from pydicom.dataset import Dataset, FileMetaDataset
from openrad.validation.nomenclature import check_structure_name
from openrad.validation.physics_rules import DICOMGeometryError

_ALLOWED = {
    'Modality','SOPClassUID','SOPInstanceUID','FrameOfReferenceUID',
    'ReferencedSOPClassUID','ReferencedSOPInstanceUID','ReferencedRTPlanSequence',
    'ReferencedStructureSetSequence','StructureSetROISequence','ROINumber','ROIName',
    'ReferencedFrameOfReferenceUID','ROIContourSequence','ReferencedROINumber',
    'ContourSequence','ContourGeometricType','NumberOfContourPoints','ContourData',
    'DoseGridScaling','DoseUnits','DoseType','DoseSummationType',
    'PixelSpacing','SliceThickness','ImagePositionPatient','ImageOrientationPatient',
    'GridFrameOffsetVector','NumberOfFrames','Rows','Columns','SamplesPerPixel',
    'PhotometricInterpretation','BitsAllocated','BitsStored','HighBit',
    'PixelRepresentation','PixelData','PlanarConfiguration',
}


def scrub_analysis_copies(dose, struct, plan=None, reviewed_name_map=None):
    """Check source identity/linkage before replacing identifiers consistently."""
    sources = [dose, struct] + ([plan] if plan is not None else [])
    ids = [str(getattr(ds, 'PatientID', '')) for ds in sources]
    if not all(ids) or len(set(ids)) != 1:
        raise DICOMGeometryError('Missing or inconsistent patient identifiers.')
    if any(str(getattr(ds, 'BurnedInAnnotation', 'NO')) != 'NO' for ds in sources):
        raise DICOMGeometryError('Burned-in annotation requires dedicated de-identification review.')
    uid_map, source_names, safe_map = {}, {}, {}
    reviewed_name_map = reviewed_name_map or {}
    for roi in struct.StructureSetROISequence:
        original = str(roi.ROIName)
        mapped = reviewed_name_map.get(original, original)
        verdict = check_structure_name(mapped)
        canonical = verdict['canonical_name']
        if canonical is None:
            canonical = f'ROI_{int(roi.ROINumber)}'
        source_names[original.casefold()] = canonical
        safe_map[original] = canonical
    if set(reviewed_name_map) - set(safe_map):
        raise ValueError('Reviewed mapping references an absent source ROI.')
    # Reject ambiguity in the original data before a scrub could hide it.
    from openrad.validation.nomenclature import build_roi_index
    build_roi_index(struct.StructureSetROISequence, reviewed_name_map)

    def copy_minimal(source):
        target = Dataset()
        for element in source:
            if element.is_private or element.keyword not in _ALLOWED:
                continue
            if element.VR == 'SQ':
                target.add_new(element.tag, element.VR, [copy_minimal(item) for item in element.value])
            elif element.VR == 'UI' and element.keyword not in ('SOPClassUID', 'ReferencedSOPClassUID'):
                uid = str(element.value)
                target.add_new(element.tag, 'UI', uid_map.setdefault(uid, '2.25.' + str(uuid4().int)))
            elif element.keyword == 'ROIName':
                target.add_new(element.tag, element.VR, safe_map[str(element.value)])
            else:
                target.add(deepcopy(element))
        return target

    copies = [copy_minimal(ds) for ds in sources]
    for original, cleaned in zip(sources, copies):
        cleaned.PatientID = 'ANON'
        if hasattr(original, 'file_meta') and hasattr(original.file_meta, 'TransferSyntaxUID'):
            cleaned.file_meta = FileMetaDataset()
            cleaned.file_meta.TransferSyntaxUID = original.file_meta.TransferSyntaxUID
        cleaned.is_little_endian = getattr(original, 'is_little_endian', True)
        cleaned.is_implicit_VR = getattr(original, 'is_implicit_VR', False)
    return copies[0], copies[1], copies[2] if plan is not None else None, source_names
