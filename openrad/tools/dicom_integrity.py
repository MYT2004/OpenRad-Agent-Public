"""Association checks shared by raw and scrubbed DICOM analysis entry points."""
from pydicom.uid import RTDoseStorage, RTStructureSetStorage, RTPlanStorage, UID
from openrad.validation.physics_rules import DICOMGeometryError


def validate_rt_object(ds,modality,cls):
    if str(getattr(ds,'Modality',''))!=modality or str(getattr(ds,'SOPClassUID',''))!=str(cls):
        raise DICOMGeometryError('DICOM modality and SOP class must match the requested RT object role.')
    uid=str(getattr(ds,'SOPInstanceUID',''))
    if not uid or not UID(uid).is_valid:
        raise DICOMGeometryError('DICOM object identity is required.')
    meta=getattr(ds,'file_meta',None)
    for keyword,expected in [('MediaStorageSOPInstanceUID',uid),('MediaStorageSOPClassUID',str(cls))]:
        value=str(getattr(meta,keyword,''))
        if value and value!=expected:
            raise DICOMGeometryError('File meta and dataset object identities disagree.')
    return uid


def validate_analysis_identity(dose, struct, plan=None):
    sources=[(dose,'RTDOSE',RTDoseStorage),(struct,'RTSTRUCT',RTStructureSetStorage)]
    if plan is not None:
        sources.append((plan,'RTPLAN',RTPlanStorage))
    identities=[]
    instance_uids=[]
    for ds,modality,cls in sources:
        instance_uids.append(validate_rt_object(ds,modality,cls))
        identities.append((str(getattr(ds,'PatientID','')).strip(),str(getattr(ds,'IssuerOfPatientID','')).strip()))
    if not all(identity[0] for identity in identities) or len(set(identities))!=1:
        raise DICOMGeometryError('Missing or inconsistent patient ID/issuer associations.')

    if len(set(instance_uids))!=len(instance_uids):
        raise DICOMGeometryError('Distinct RT objects must not share an instance identity.')
    if plan is not None:
        frame=str(getattr(plan,'FrameOfReferenceUID',''))
        if frame and frame!=str(getattr(dose,'FrameOfReferenceUID','')):
            raise DICOMGeometryError('Plan and dose frame identities disagree.')
        dose_refs=list(getattr(dose,'ReferencedRTPlanSequence',[]))
        struct_refs=list(getattr(plan,'ReferencedStructureSetSequence',[]))
        if len(dose_refs)!=1 or len(struct_refs)!=1:
            raise DICOMGeometryError('A unique dose-to-plan-to-structure reference is required.')


def validate_roi_associations(struct):
    """Never let a dictionary overwrite select one of multiple contour definitions."""
    numbers=[int(roi.ROINumber) for roi in struct.StructureSetROISequence]
    if len(set(numbers))!=len(numbers):
        raise DICOMGeometryError('ROI definitions have duplicate numbers.')
    references=[int(item.ReferencedROINumber) for item in getattr(struct,'ROIContourSequence',[])]
    if len(set(references))!=len(references) or set(references)-set(numbers):
        raise DICOMGeometryError('ROI contour associations are duplicate or refer to an undefined ROI.')
